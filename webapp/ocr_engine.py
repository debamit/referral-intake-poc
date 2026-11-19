#!/usr/bin/env python3
"""Local OCR wrapper — label anchoring, scan-quality gating, and the mask-first pre-step.

Design notes:
  * rapidocr is imported lazily. Importing this module costs nothing, so the
    app's default (template) path stays free of third-party dependencies.
  * Nothing here sends pixels anywhere. Inference is local ONNX.
  * The mask report deliberately contains counts and label names only — never
    the values it removed. A redaction log that quotes what it redacted is a
    second copy of the PHI.

Run under the pinned venv with a clean PYTHONPATH:
    env -u PYTHONPATH .venv-ocr/bin/python ...
"""
import re

_ENGINE = None

# Labels whose line must not survive the pre-step, as (name, regex).
# Deliberately specific: a bare "address" also matches the prescriber's block,
# and prescriber identity is public professional information, not patient PHI.
SENSITIVE_LABELS = [
    ("patient name", r"patient\s*name"),
    ("patient id", r"patient\s*(id|#|no)"),
    ("date of birth", r"date\s*of\s*birth"),
    ("dob", r"\bdob\b"),
    ("phone", r"\bphone\b|\btelephone\b|\bcell\b"),
    ("patient address", r"(active|home|street|patient|mailing)\s*address"),
    ("member id", r"member\s*(id|#|no)"),
    ("specialty id", r"specialty\s*id"),
    ("mrn", r"\bmrn\b"),
    ("subscriber", r"subscriber"),
]

# Lines matching these establish where the patient block is, so generic labels
# (phone, address) can be scoped to that band instead of firing page-wide.
PATIENT_ANCHORS = [r"patient\s*name", r"patient\s*(id|#|no)",
                   r"date\s*of\s*birth", r"specialty\s*id"]

# Labels that are unambiguous on their own and fire anywhere on the page.
STRONG_LABELS = {"patient name", "patient id", "date of birth", "dob",
                 "specialty id", "member id", "mrn", "subscriber"}

# Printed titles that identify which revision of the form arrived.
FORM_FINGERPRINTS = {
    "legacy_supply_request_v1": ["supply request", "rheumatoid arthritis"],
    "enrollment_2page_v1": ["enrollment form", "prescription & enrollment", "prescription and enrollment"],
}


def available():
    try:
        import rapidocr  # noqa: F401
        return True
    except Exception:
        return False


def engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def read(image, max_side=None):
    """Run OCR once.

    max_side downscales *only* the OCR pass — locating a label does not need
    full resolution. Boxes come back in ORIGINAL pixel coordinates and page
    fractions regardless, so callers can mask and crop the full-resolution
    image while paying OCR cost at the reduced size.
    """
    from PIL import Image
    im = image if hasattr(image, "size") else Image.open(image)
    W, H = im.size
    src = im
    if max_side and max(W, H) > max_side:
        s = max_side / float(max(W, H))
        src = im.resize((max(1, round(W * s)), max(1, round(H * s))), Image.LANCZOS)
    sw, sh = src.size
    res = engine()(src)
    words = []
    # A page with no detected text yields None (txts/scores) or an empty array
    # (boxes). Never test truthiness — boxes is a numpy array.
    txts = res.txts if res.txts is not None else []
    scores = res.scores if res.scores is not None else []
    boxes = res.boxes if res.boxes is not None else []
    for txt, score, box in zip(txts, scores, boxes):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        fx = (min(xs) / sw, min(ys) / sh, max(xs) / sw, max(ys) / sh)
        words.append({
            "text": txt,
            "score": round(float(score), 4),
            "frac": fx,
            "box": (fx[0] * W, fx[1] * H, fx[2] * W, fx[3] * H),
        })
    words.sort(key=lambda w: (round(w["box"][1] / 12), w["box"][0]))
    return words


def group_lines(words, overlap=0.5):
    """Group words into text lines by vertical overlap."""
    lines = []
    for w in sorted(words, key=lambda w: w["box"][1]):
        y0, y1 = w["box"][1], w["box"][3]
        for ln in lines:
            ly0 = min(x["box"][1] for x in ln)
            ly1 = max(x["box"][3] for x in ln)
            inter = max(0.0, min(y1, ly1) - max(y0, ly0))
            if inter > overlap * min(y1 - y0, ly1 - ly0):
                ln.append(w)
                break
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w["box"][0])
    return lines


def quality(words):
    """Scan-quality signal from the OCR pass itself."""
    if not words:
        return {"verdict": "fail", "reason": "no text detected", "n": 0}
    scores = sorted(w["score"] for w in words)
    med = scores[len(scores) // 2]
    p10 = scores[max(0, int(len(scores) * 0.10))]
    low = sum(1 for s in scores if s < 0.50) / len(scores)
    ok = med >= 0.80 and low <= 0.25
    return {
        "n": len(scores), "median": round(med, 3), "p10": round(p10, 3),
        "frac_below_0.50": round(low, 3),
        "verdict": "pass" if ok else "degraded",
        "thresholds": {"median_min": 0.80, "frac_low_max": 0.25},
    }


def fingerprint(words):
    """Which revision of the form is this? Decides page expectations and handler."""
    joined = " ".join(w["text"] for w in words).lower()
    joined = re.sub(r"\s+", " ", joined)
    best, hits = None, 0
    for form_id, needles in FORM_FINGERPRINTS.items():
        n = sum(1 for s in needles if s in joined)
        if n > hits:
            best, hits = form_id, n
    return {"form_id": best, "confidence": "high" if hits >= 2 else ("low" if hits else "none"),
            "matched_markers": hits}


def find_label(words, pattern):
    """Return the word boxes whose text matches pattern."""
    rx = re.compile(pattern, re.I)
    return [w for w in words if rx.search(w["text"])]


def value_right(words, label_word, max_gap=None):
    """Label-anchored field discovery: the text to the right on the same line."""
    lines = group_lines(words)
    for ln in lines:
        if label_word in ln:
            i = ln.index(label_word)
            rest = ln[i + 1:]
            if not rest:
                return None, None
            if max_gap is not None:
                rest = [w for w in rest if w["box"][0] - label_word["box"][2] <= max_gap]
            if not rest:
                return None, None
            text = " ".join(w["text"] for w in rest)
            box = (min(w["box"][0] for w in rest), min(w["box"][1] for w in rest),
                   max(w["box"][2] for w in rest), max(w["box"][3] for w in rest))
            return text, box
    return None, None


def mask_lines(image, words, labels=None, pad_px=6, fill=(58, 58, 58)):
    """Pre-step: blank every text line carrying a patient-identity label.

    Generic labels (phone, address) only fire inside the vertical band of the
    patient block, so the prescriber's contact lines survive — those are public
    professional information and the callback channel the pipeline needs later.
    Patient-specific labels fire anywhere.

    Returns (masked_image, report). The report records label names, word counts
    and boxes — never the text that was removed.
    """
    from PIL import ImageDraw
    labels = labels or SENSITIVE_LABELS
    out = image.copy()
    d = ImageDraw.Draw(out)
    W, H = out.size

    lines = group_lines(words)

    def joined(ln):
        return re.sub(r"\s+", " ", " ".join(w["text"] for w in ln)).lower()

    anchors = [ln for ln in lines if any(re.search(a, joined(ln)) for a in PATIENT_ANCHORS)]
    band = None
    if anchors:
        y0 = min(min(w["box"][1] for w in ln) for ln in anchors)
        y1 = max(max(w["box"][3] for w in ln) for ln in anchors)
        band = (y0 - 0.005 * H, y1 + 0.035 * H)

    report = []
    for ln in lines:
        hits = [name for name, rx in labels if re.search(rx, joined(ln))]
        if not hits:
            continue
        top = min(w["box"][1] for w in ln)
        in_band = band is not None and band[0] <= top <= band[1]
        strong = any(h in STRONG_LABELS for h in hits)
        if not (in_band or strong):
            continue
        x0 = min(w["box"][0] for w in ln) - pad_px
        y0 = min(w["box"][1] for w in ln) - pad_px
        x1 = max(w["box"][2] for w in ln) + pad_px
        y1 = max(w["box"][3] for w in ln) + pad_px
        d.rectangle((max(0, x0), max(0, y0), min(W, x1), min(H, y1)), fill=fill)
        report.append({
            "labels": hits,
            "words_masked": len(ln),
            "box_frac": [round(max(0, x0) / W, 4), round(max(0, y0) / H, 4),
                         round(min(W, x1) / W, 4), round(min(H, y1) / H, 4)],
        })
    return out, report
