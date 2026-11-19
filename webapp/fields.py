#!/usr/bin/env python3
"""Multi-field extraction: locate several labels on one page and read each value.

One OCR pass, one mask, then per-field crops. The diagnosis keeps its
constrained decode (hard gates → decision); the free-text fields get a plain
read and are reported as reads, because no gate exists that could turn
"Dispense: 1 (ONE) month supply" into a verified value.

The awkward part on this form family is that the label and its value often land
in the SAME OCR box ("Drug: ADALIMUMAB-ADBM(CF) PEN 40 MG"). So the crop
boundary cannot be "right of the label box" — it has to be found inside the
line, at the whitespace gap following the label text.
"""
import base64
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import decode_lib
import ocr_engine

FIELD_SPECS = [
    {"key": "diagnosis", "label": "Diagnosis", "rx": r"diagnosis\s*:", "kind": "code"},
    {"key": "drug", "label": "Drug", "rx": r"\bdrug\s*:", "kind": "text"},
    {"key": "sig", "label": "Label instructions", "rx": r"labe[l1i]\s*instructions\s*:", "kind": "text"},
    {"key": "dispense", "label": "Dispense", "rx": r"\bdispense\s*:", "kind": "text"},
    {"key": "refills", "label": "Refills", "rx": r"refills?\s*:", "kind": "checkbox"},
]

MIN_READ_SCORE = 0.85


def _match(words, rx):
    """First word box matching rx, in page order."""
    for w in words:
        m = re.search(rx, w["text"].lower())
        if m:
            return w, m
    return None, None


def _snap_gap(im, word, split, sens):
    """Move a guessed split point onto the nearest whitespace gap in the line.

    Proportional character estimates drift; the gap between the printed label
    and its value does not.
    """
    from decode_lib import binarise

    x0, y0, x1, y1 = word["box"]
    h = max(6.0, y1 - y0)
    top = max(0, int(y0 - 0.15 * h))
    bot = min(im.size[1], int(y1 + 0.15 * h))
    strip = im.crop((int(x0), top, int(x1), bot))
    b = binarise(strip, sens)
    wpx, hpx = b.size
    if wpx < 8 or hpx < 4:
        return split
    px = b.load()
    # binarise() renders ink bright on black — ink is > 127, not < 128.
    cols = [any(px[x, y] > 127 for y in range(hpx)) for x in range(wpx)]

    gaps, run = [], None
    for x, ink in enumerate(cols):
        if not ink:
            if run is None:
                run = x
        else:
            if run is not None:
                gaps.append((run, x))
                run = None
    if run is not None:
        gaps.append((run, wpx))

    target = split - int(x0)
    tol = 0.03 * wpx
    best = None
    for a, b2 in gaps:
        if b2 - a < 0.012 * wpx:      # ignore kerning gaps
            continue
        c = (a + b2) / 2.0
        if c < target - tol:
            continue
        if best is None or abs(c - target) < abs(best - target):
            best = c
    return int(x0) + best if best is not None else split


def _cut_at_field_gap(img, bb, h, min_gap_frac=0.9, min_ink_cols=3):
    """End the crop at the first gap wider than one glyph height.

    Word spaces are a fraction of the line height; the space between this
    field's value and whatever sits to its right is wider. Cutting on that
    boundary ignores stray marks that would otherwise stretch the crop and make
    the decoder segment a phantom glyph.
    """
    if not bb:
        return None
    px = img.load()
    x0, y0, x1, y1 = bb
    gap_need = max(12, int(h * min_gap_frac))

    run_start, ink_cols = None, 0
    for i, x in enumerate(range(x0, x1)):
        if any(px[x, y] > 127 for y in range(y0, y1)):
            if run_start is not None:
                if i - run_start >= gap_need and ink_cols >= min_ink_cols:
                    return (x0, y0, x0 + run_start, y1)
                run_start = None
            ink_cols += 1
        elif run_start is None:
            run_start = i
    return (x0, y0, x1, y1)


def value_box(im, word, end_frac, sens=28, pad_top=0.25, pad_bot=0.25):
    """Pixel box covering the value that follows a label.

    pad_bot is larger for handwritten fields: a printed line is bounded by its
    own box, but handwriting descends past the label's baseline and clipping
    the descender silently changes the decode.
    """
    from decode_lib import binarise, strip_rules

    W, H = im.size
    x0, y0, x1, y1 = word["box"]
    h = max(6.0, y1 - y0)

    if end_frac > 0.92:
        # Label has its own box: scan generously to the right, then stop at the
        # first gap wider than a glyph — that gap is the next field.
        left = int(x1 - 0.25 * h)
        right = min(W, int(left + 10 * h))
        stop_at_gap = True
    else:
        # Label and value share one box, so the box already ends at the value
        # and there is nothing to cut. Do NOT gap-cut here: a pen lift inside
        # handwriting routinely exceeds a glyph height, and cutting on it
        # truncates the code to a sliver.
        split = x0 + (x1 - x0) * end_frac
        left = int(_snap_gap(im, word, split, sens))
        right = min(W, int(x1) + int(0.8 * h))
        stop_at_gap = False

    top = max(0, int(y0 - pad_top * h))
    bot = min(H, int(y1 + pad_bot * h))
    if right - left < 4:
        return None

    strip = strip_rules(binarise(im.crop((left, top, right, bot)), sens))
    bb = strip.getbbox()
    if stop_at_gap:
        bb = _cut_at_field_gap(strip, bb, h)
    if not bb:
        return None
    return (left + bb[0], top + bb[1], left + bb[2], top + bb[3])


def _b64(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


def _crop_b64(im, max_w=420):
    """Crop preview for display, upscaled so small fields stay legible."""
    w, h = im.size
    scale = max_w / float(w) if w else 1.0
    scale = max(scale, 1.0)
    out = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), 1)
    return _b64(out)


def analyze(image_bytes_or_path):
    """Locate every configured field, read it, and return per-field results."""
    src = (decode_lib.Image.open(io.BytesIO(image_bytes_or_path))
           if isinstance(image_bytes_or_path, (bytes, bytearray))
           else decode_lib.Image.open(image_bytes_or_path))
    im = src.convert("RGB")
    W, H = im.size

    words = ocr_engine.read(im, max_side=decode_lib.OCR_MAX_SIDE)
    masked, mask_report = ocr_engine.mask_lines(im, words)
    quality = ocr_engine.quality(words)
    fingerprint = ocr_engine.fingerprint(words)

    buf = io.BytesIO()
    masked.save(buf, "PNG")
    masked_bytes = buf.getvalue()

    fields = []
    for spec in FIELD_SPECS:
        fields.append(_one_field(spec, masked, masked_bytes, words, W, H))

    return {
        "fields": fields,
        "ocr": {
            "enabled": True,
            "quality": quality,
            "fingerprint": fingerprint,
            "masked_regions": len(mask_report),
            "labels_hit": sorted({l for m in mask_report for l in m["labels"]}),
            "mask_detail": mask_report,
        },
        "images": {"masked_page": _b64(decode_lib._preview(masked))},
    }


def _one_field(spec, masked, masked_bytes, words, W, H):
    base = {"key": spec["key"], "label": spec["label"], "kind": spec["kind"]}

    word, m = _match(words, spec["rx"])
    if word is None:
        return {**base, "state": "not_found", "output": None, "crop": None,
                "stages": [{"id": "L", "name": "locate", "state": "fail",
                            "detail": f"no '{spec['label']}' label found on this page"}]}

    end_frac = m.end() / max(1, len(word["text"]))
    # Handwriting descends below the label baseline; printed values do not.
    pads = {"pad_top": 0.35, "pad_bot": 0.85} if spec["kind"] == "code" else {}
    box = value_box(masked, word, end_frac, **pads)
    if box is None:
        return {**base, "state": "not_found", "output": None, "crop": None,
                "stages": [{"id": "L", "name": "locate", "state": "pass",
                            "detail": f"label at {[round(v, 3) for v in word['frac']]}"},
                           {"id": "C", "name": "crop", "state": "fail",
                            "detail": "no ink found right of the label"}]}

    crop = masked.crop(box)
    frac = [box[0] / W, box[1] / H, box[2] / W, box[3] / H]
    stages = [
        {"id": "L", "name": "locate", "state": "pass",
         "detail": f"label '{word['text'][:28]}' at y={word['frac'][1]:.3f}"},
        {"id": "C", "name": "crop", "state": "pass",
         "detail": f"value box {[round(v, 3) for v in frac]} "
                   f"({box[2]-box[0]}x{box[3]-box[1]} px)"},
    ]

    if spec["kind"] == "code":
        r = decode_lib.decode(masked_bytes, box=frac, ocr=False, box_source_hint="label")
        return {
            **base,
            "state": r["disposition"],
            "output": r["chosen"]["code"] if r["chosen"] else None,
            "reason": r["reason"],
            "margin": r["margin"],
            "confidence": None,
            "crop": _crop_b64(crop),
            "stages": stages + r["stages"],
            "readings": r["readings"],
            "reading_count": r["reading_count"],
            "candidates": {"count": r["candidates"]["count"],
                           "drug": r["candidates"]["drug"]},
            "images": {"annotated": r["images"]["annotated"],
                       "mask": r["images"]["mask"]},
            "audit": r["audit"],
        }

    text, score = ocr_engine.read_crop(crop)

    if spec["kind"] == "checkbox":
        state, reason = "review", "checkbox row — selection is not machine-readable"
    elif not text:
        state, reason = "review", "no text recognised in the crop"
    elif score < MIN_READ_SCORE:
        state, reason = "review", f"read below threshold ({score:.2f} < {MIN_READ_SCORE})"
    else:
        state, reason = "read", "printed text read; no gate exists for this field"

    stages.append({"id": "R", "name": "read", "state": "pass" if text else "fail",
                   "detail": f"{score:.3f} · {text[:60]!r}" if text else "nothing recognised"})
    stages.append({"id": "G", "name": "gate", "state": "warn" if state == "review" else "pass",
                   "detail": reason})

    return {
        **base,
        "state": state,
        "output": text or None,
        "reason": reason,
        "confidence": round(score, 4),
        "crop": _crop_b64(crop),
        "stages": stages,
        "readings": None,
        "audit": {"crop_box": [round(v, 4) for v in frac],
                  "read_score": round(score, 4),
                  "ocr_model": "PP-OCRv6 small (onnxruntime)"},
    }


if __name__ == "__main__":
    import json
    if len(sys.argv) < 2:
        sys.exit("usage: fields.py <image> [--json]")
    res = analyze(sys.argv[1])
    for f in res["fields"]:
        print(f"{f['label']:20s} {str(f['state']):10s} {str(f['output'])[:60]!r}")
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in res.items() if k != "images"}, indent=2, default=str)[:2000])
