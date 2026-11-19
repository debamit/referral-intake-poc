#!/usr/bin/env python3
"""Shared decoding logic: the lexicographic workflow, callable from a CLI or a server.

Order is the point. Hard constraints decide what is possible; scores only rank
what survives them. Nothing is summed into a single number.

  Stage 0  intake        form version / page completeness
  Stage 1  geometry      crop to the field (normalisation happens upstream)
  Stage 2  hard set      A = leaves(code_set) ∩ indications(drug)
  Stage 3  enumerate     segmentation × per-glyph alternatives
  Stage 4  gate          exists(code_set) then ∈ A      <- no scores here
  Stage 5  rank          shape score, margin
  Stage 6  decide        one disposition + one reason code
"""
import base64, io, json, os
from collections import deque
from PIL import Image, ImageFilter, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITS = "0123456789"
LEAD_LETTERS = "MLKH"

# Calibration placeholders — replace with thresholds fitted to a labelled set.
TAU_HIGH = 0.25
TAU_LOW = 0.10


def load_table(path=None):
    cands = [path,
             os.path.join(HERE, "data", "icd-map.json"),
             os.path.join(os.path.dirname(HERE), "redact", "icd-map.json"),
             os.path.join(os.path.dirname(HERE), "icd-map.json")]
    for c in cands:
        if c and os.path.exists(c):
            with open(c) as f:
                return json.load(f)
    raise FileNotFoundError("icd-map.json not found; looked in: "
                            + ", ".join(str(c) for c in cands))


# ---------- imaging ----------

def binarise(im, sens=28):
    grey = im.convert("L")
    bg = grey.filter(ImageFilter.GaussianBlur(max(6, grey.width // 12)))
    return ImageChops.subtract(bg, grey).point(lambda v: 255 if v >= sens else 0)


def trim(m):
    bb = m.getbbox()
    return m.crop(bb) if bb else m


def strip_rules(mask, frac=0.30):
    w, h = mask.size
    px = mask.load()
    for y in range(h):
        best = cur = 0
        for x in range(w):
            if px[x, y]:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        if best > w * frac:
            for x in range(w):
                px[x, y] = 0
    return mask


def col_profile(mask):
    w, h = mask.size
    px = mask.load()
    return [sum(1 for y in range(h) if px[x, y]) for x in range(w)]


def split_at(prof, k, min_w):
    w = len(prof)
    order = sorted(range(min_w, w - min_w), key=lambda x: prof[x])
    chosen = []
    for x in order:
        if all(abs(x - c) >= min_w for c in chosen):
            chosen.append(x)
        if len(chosen) == k - 1:
            break
    b = [0] + sorted(chosen) + [w]
    return [(b[i], b[i + 1] - 1) for i in range(len(b) - 1)]


# ---------- glyph shape ----------

def holes(g):
    w, h = g.size
    px = g.load()
    seen = [[False] * h for _ in range(w)]
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not px[x, y] and not seen[x][y]:
                seen[x][y] = True; q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not px[x, y] and not seen[x][y]:
                seen[x][y] = True; q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny] and not px[nx, ny]:
                seen[nx][ny] = True; q.append((nx, ny))
    cent, vis = [], set()
    for x in range(w):
        for y in range(h):
            if px[x, y] or seen[x][y] or (x, y) in vis:
                continue
            comp, qq = [], deque([(x, y)]); vis.add((x, y))
            while qq:
                cx, cy = qq.popleft(); comp.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not px[nx, ny] \
                       and not seen[nx][ny] and (nx, ny) not in vis:
                        vis.add((nx, ny)); qq.append((nx, ny))
            if len(comp) > w * h * 0.005:
                cent.append(sum(p[1] for p in comp) / len(comp) / h)
    return cent


def features(g):
    w, h = g.size
    px = g.load()
    ink = sum(1 for x in range(w) for y in range(h) if px[x, y])
    hl = holes(g)
    top = sum(1 for x in range(w) for y in range(h // 3) if px[x, y])
    bot = sum(1 for x in range(w) for y in range(2 * h // 3, h) if px[x, y])
    maxrun, hbar_y, cur = 0, 0.0, 0
    for y in range(h):
        cur = 0
        for x in range(w):
            if px[x, y]:
                cur += 1
                if cur > maxrun:
                    maxrun, hbar_y = cur, y / h
            else:
                cur = 0
    return {"aspect": round(w / h if h else 0, 3),
            "density": round(ink / (w * h) if w * h else 0, 3),
            "holes": len(hl),
            "hole_y": round(sum(hl) / len(hl), 3) if hl else None,
            "hbar": maxrun > 0.55 * w,
            "hbar_y": round(hbar_y, 3),
            "top_heavy": top > bot * 1.35, "bot_heavy": bot > top * 1.35}


def score_char(f, pos):
    s = dict.fromkeys(DIGITS, 0.0)
    if pos == 0:
        for c in LEAD_LETTERS:
            s[c] = 0.0
    n, hy = f["holes"], f["hole_y"]
    if n == 2:
        s["8"] += 1.0
    if n == 1:
        if hy is not None and hy < 0.42:
            s["9"] += 0.75; s["4"] += 0.20
        elif hy is not None and hy > 0.58:
            s["6"] += 0.60; s["0"] += 0.55
        else:
            s["0"] += 0.70; s["4"] += 0.25
    if n == 0:
        if f["hbar"] and f["hbar_y"] > 0.65:
            if "L" in s:
                s["L"] += 0.55
            s["4"] += 0.25
        if f["hbar"] and 0.25 <= f["hbar_y"] <= 0.70:
            s["4"] += 0.50
        if f["aspect"] < 0.45 and not f["hbar"]:
            s["1"] += 0.55
        if f["aspect"] > 1.20:
            s["7"] += 0.35; s["2"] += 0.20
        for c in LEAD_LETTERS:
            if c in s:
                s[c] += 0.12
        s["2"] += 0.12; s["3"] += 0.12; s["5"] += 0.12
    if f["top_heavy"]:
        s["7"] += 0.15; s["9"] += 0.10
    if f["bot_heavy"]:
        s["6"] += 0.10; s["2"] += 0.10
        if "L" in s:
            s["L"] += 0.15
    if 0.10 <= f["density"] <= 0.45:
        for d in "04689":
            s[d] += 0.08
    return {k: round(v, 3) for k, v in s.items()}


# ---------- code-set gate ----------

def syntax_ok(code):
    """ICD-10-CM shape: letter, two alphanumerics, optional decimal + up to 4."""
    if not code or not code[0].isalpha():
        return False
    if any(c in "IO" for c in code.upper()):
        return False
    body = code.replace(".", "")
    return 3 <= len(body) <= 7 and all(c.isalnum() for c in body)


def build_code_set(table, drug):
    """SAMPLE code set. Production must load the full FY ICD-10-CM file here."""
    codes = set()
    for ind in table["drugs"][drug]["indications"]:
        codes.update(c.upper() for c in ind.get("examples_icd10", []))
    for c in table.get("control_examples", []):
        codes.add(c["code"].upper())
    return codes


# Long edge for the OCR pass ONLY; the decoder always sees full-resolution
# pixels. Measured on a 3072x4080 phone photo, warm, repeated:
#   full 3072 : 2.8-3.0s  L40.9 accept
#   1600      : 2.3-2.9s  L40.9 accept   <- sweet spot
#   1080      : 3.4s      FAIL
#   720       : 4.5s      FAIL, and loses 1 of 3 mask regions
#
# Below 1600 it gets slower AND wrong. Cause is box quantization, not
# legibility: at 1080 one OCR pixel is 3.8 original pixels, so the label's
# right edge is only known to +-4px, the crop anchor clips the first glyph, and
# the decoder then enumerates more segmentation choices trying to recover.
# If you lower this, re-measure the crop anchor and the final code — OCR
# confidence stays high while the answer goes wrong.
OCR_MAX_SIDE = 1600


def _preview(im, max_w=900):
    """Downscale for display only — the decode itself always uses full pixels."""
    w, h = im.size
    if w <= max_w:
        return im
    s = max_w / float(w)
    return im.resize((max_w, max(1, round(h * s))), Image.LANCZOS)


def box_right_of_label(im, label_word, sens=28, pad_frac=0.15):
    """Crop box for the value to the right of a label, derived from actual ink.

    Height-scaled guesses are brittle: a little too tight clips the last glyph,
    a little too wide drags the label in. Instead, binarise the strip to the
    right of the label, remove the field's underline, and take the ink extent.
    """
    W, H = im.size
    x0, y0, x1, y1 = label_word["box"]
    h = max(8.0, y1 - y0)
    top, bot = max(0, int(y0 - 0.5 * h)), min(H, int(y1 + 0.5 * h))
    xstart = min(W - 1, int(x1 + 2))
    xend = min(W, xstart + int(10 * h))
    strip = im.crop((xstart, top, xend, bot))
    m = strip_rules(trim(binarise(strip, sens)))
    bb = m.getbbox()
    if not bb:
        return None
    pad = int(h * pad_frac)
    left = xstart + max(0, bb[0] - pad)
    right = xstart + min(strip.width, bb[2] + pad)
    return [left / W, (top + max(0, bb[1] - pad)) / H,
            right / W, (top + min(strip.height, bb[3] + pad)) / H]


def decode(image_bytes_or_path, box=None, drug="adalimumab", sens=28, table_path=None,
           ocr=False):
    table = load_table(table_path)
    src = (Image.open(io.BytesIO(image_bytes_or_path))
           if isinstance(image_bytes_or_path, (bytes, bytearray))
           else Image.open(image_bytes_or_path))
    im = src.convert("RGB")
    W, H = im.size

    ocr_q, ocr_fp, mask_report, box_source = None, None, [], "template"
    masked_preview = None
    stages = []

    if ocr:
        import ocr_engine
        words = ocr_engine.read(im, max_side=OCR_MAX_SIDE)
        im, mask_report = ocr_engine.mask_lines(im, words)
        masked_preview = _preview(im)
        ocr_q = ocr_engine.quality(words)
        ocr_fp = ocr_engine.fingerprint(words)

        stages.append({"id": "0a", "name": "mask", "state": "pass" if mask_report else "warn",
                       "detail": f"{len(mask_report)} line(s) blanked, original discarded"})
        stages.append({"id": "0b", "name": "quality",
                       "state": "pass" if ocr_q["verdict"] == "pass" else "fail",
                       "detail": f"median {ocr_q.get('median')} p10 {ocr_q.get('p10')} "
                                 f"low {ocr_q.get('frac_below_0.50')} -> {ocr_q['verdict']}"})
        stages.append({"id": "0c", "name": "fingerprint",
                       "state": "pass" if ocr_fp["form_id"] else "warn",
                       "detail": f"{ocr_fp['form_id']} ({ocr_fp['confidence']})"})

        if box is None:
            lab = ocr_engine.find_label(words, r"diagnos")
            if lab:
                derived = box_right_of_label(im, lab[0], sens)
                if derived:
                    box = derived
                    box_source = "ocr-label"
            if box is None:
                # Fail closed. Without a located field the decoder enumerates
                # the entire page, which is both slow (measured 6.9s on a 480p
                # page) and unbounded. A human is cheaper than a guess.
                raise ValueError("ocr: no 'Diagnosis' label located on this page "
                                 "- refusing to decode the full page")

    stages.append({"id": 0, "name": "intake", "state": "pass",
                   "detail": "single field crop; form version accepted by the caller"})
    stages.append({"id": 1, "name": "geometry", "state": "pass" if box else "warn",
                   "detail": f"crop box {[round(b,3) for b in box]} from {box_source}" if box
                             else "no crop box - full image used"})

    if box:
        crop = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
    else:
        crop = im
    up = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
    mask = trim(strip_rules(trim(binarise(up, sens))))

    cands = {}
    for ind in table["drugs"][drug]["indications"]:
        for c in ind.get("examples_icd10", []):
            cands[c.upper()] = ind["condition"]
    code_set = build_code_set(table, drug)

    stages.append({"id": 2, "name": "hard set",
                   "state": "pass" if cands else "fail",
                   "detail": f"A = {len(cands)} codes for {drug}"})

    w, h = mask.size
    prof = col_profile(mask)
    min_w = max(6, w // 12)

    readings = []
    for k in range(3, 7):
        segs = split_at(prof, k, min_w)
        glyph_alt, ok = [], True
        for pos, (x0, x1) in enumerate(segs):
            g = mask.crop((x0, 0, x1 + 1, h))
            bb = g.getbbox()
            if not bb:
                ok = False; break
            g = g.crop(bb)
            f = features(g)
            if g.width < w * 0.04 and g.height < h * 0.30:
                glyph_alt.append([(".", 0.90, f)])
                continue
            sc = score_char(f, pos)
            glyph_alt.append([(c, v, f) for c, v in sorted(sc.items(), key=lambda kv: -kv[1])[:3]])
        if ok:
            readings.append((k, glyph_alt, segs))

    stages.append({"id": 3, "name": "enumerate",
                   "state": "pass" if readings else "fail",
                   "detail": f"{len(readings)} segmentation choices tried (k=3..6)"})

    # --- gated evaluation -------------------------------------------------
    evaluated, seen = [], set()
    for k, glyph_alt, segs in readings:
        import itertools
        for combo in itertools.product(*glyph_alt):
            code = "".join(g[0] for g in combo)
            if code in seen:
                continue
            seen.add(code)
            shape = sum(g[1] for g in combo) / len(combo)
            if code.startswith("."):
                shape -= 1.0
            if "." in code and code.index(".") != 3:
                shape -= 0.8
            gate_syntax = syntax_ok(code)
            gate_exists = code.upper() in {c.upper() for c in code_set}
            gate_in_a = code.upper() in cands
            evaluated.append({"code": code, "shape": round(shape, 3), "k": k,
                              "syntax": gate_syntax, "exists": gate_exists,
                              "in_set": gate_in_a,
                              "condition": cands.get(code.upper())})

    survivors = [e for e in evaluated if e["syntax"] and e["exists"] and e["in_set"]]
    survivors.sort(key=lambda e: -e["shape"])
    real_but_wrong = [e for e in evaluated
                      if e["syntax"] and e["exists"] and not e["in_set"]]

    stages.append({"id": 4, "name": "gate",
                   "state": "pass" if survivors else "fail",
                   "detail": f"{len(survivors)} survive exists ∩ in-A of {len(evaluated)} readings"})
    stages.append({"id": 5, "name": "rank",
                   "state": "pass" if survivors else "skip",
                   "detail": "shape score, margin between top two survivors" if survivors else "nothing to rank"})

    if not cands:
        disp, reason, chosen, margin = "callback", "CLINICAL_CHECK_UNAVAILABLE", None, 0.0
    elif survivors:
        chosen = survivors[0]
        margin = round(chosen["shape"] - survivors[1]["shape"], 3) if len(survivors) > 1 else 1.0
        if margin >= TAU_HIGH:
            disp, reason = "accept", "MATCH_INDICATION"
        else:
            disp, reason = "review", "AMBIGUOUS_SHAPE"
    elif real_but_wrong:
        real_but_wrong.sort(key=lambda e: -e["shape"])
        chosen, margin = real_but_wrong[0], 0.0
        disp, reason = "callback", "CLINICAL_MISMATCH"
    else:
        chosen, margin = None, 0.0
        disp, reason = "callback", "NO_VALID_CODE"

    # The quality gate outranks every downstream result: a degraded scan
    # invalidates whatever was read off it.
    if ocr_q is not None and ocr_q.get("verdict") != "pass":
        disp, reason = "callback", "SCAN_DEGRADED"

    stages.append({"id": 6, "name": "decide", "state": "pass",
                   "detail": reason})

    ann = crop.copy()
    d = ImageDraw.Draw(ann)
    if chosen and readings:
        best = next((r for r in readings if r[0] == chosen["k"]), readings[0])
        for (x0, x1) in best[2]:
            d.rectangle((x0 // 4, 0, x1 // 4, ann.height), outline=(220, 40, 40), width=3)

    def b64(img, fmt="PNG"):
        buf = io.BytesIO()
        img.save(buf, fmt)
        return base64.b64encode(buf.getvalue()).decode()

    return {
        "stages": stages,
        "candidates": {"drug": drug, "count": len(cands), "codes": sorted(cands)},
        "code_set": {"size": len(code_set), "complete": False,
                     "note": "sample set - production loads the full FY ICD-10-CM file"},
        "readings": sorted(evaluated, key=lambda e: -e["shape"])[:12],
        "reading_count": len(evaluated),
        "survivors": survivors[:5],
        "chosen": chosen,
        "margin": margin,
        "thresholds": {"tau_high": TAU_HIGH, "tau_low": TAU_LOW},
        "disposition": disp,
        "reason": reason,
        "ocr": {"enabled": ocr, "quality": ocr_q, "fingerprint": ocr_fp,
                "masked_regions": len(mask_report), "box_source": box_source,
                "labels_hit": sorted({l for m in mask_report for l in m["labels"]}),
                "mask_detail": mask_report},
        "images": {"annotated": b64(ann), "mask": b64(mask.convert("RGB")),
                   "masked_page": b64(masked_preview) if masked_preview else None},
        "audit": {
            "crop_box": box, "sens": sens, "upsample": 4,
            "mask_size": [w, h], "segmentation_k": chosen["k"] if chosen else None,
            "indication_map_version": table.get("schema_version", "?"),
            "code_set_version": "sample", "rule_set_version": "rules-v2",
        },
    }
