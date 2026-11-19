#!/usr/bin/env python3
"""Drug-constrained decoding of a handwritten diagnosis code. No model, no training.

Core idea: the drug on the page determines which diagnosis codes are possible, so
recognition is driven by the candidate set, not by the glyphs alone. Each glyph
contributes ranked alternatives; combinations are scored on (a) how well the
shapes fit and (b) whether the assembled string is a code this drug can legally
be prescribed for. A reading outside the candidate set is never "confident",
however clean the strokes look.

  /usr/bin/python3 -I decode_code.py <image> --box x0 y0 x1 y1 [--drug adalimumab]
"""
import itertools, json, os, sys
from collections import deque
from PIL import Image, ImageFilter, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITS = "0123456789"
LEAD_LETTERS = "MLKH"          # first-position letters across adalimumab indications


def binarise(im, sens=28):
    grey = im.convert("L")
    bg = grey.filter(ImageFilter.GaussianBlur(max(6, grey.width // 12)))
    return ImageChops.subtract(bg, grey).point(lambda v: 255 if v >= sens else 0)


def trim(m):
    bb = m.getbbox()
    return m.crop(bb) if bb else m


def strip_rules(mask, frac=0.30):
    """Erase rows whose longest horizontal run exceeds frac of the width."""
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
    return {"w": w, "h": h, "aspect": w / h if h else 0,
            "density": ink / (w * h) if w * h else 0,
            "holes": len(hl), "hole_y": (sum(hl) / len(hl)) if hl else None,
            "top_heavy": top > bot * 1.35, "bot_heavy": bot > top * 1.35,
            "hbar": maxrun > 0.55 * w, "hbar_y": hbar_y}


def score_char(f, pos):
    """Ranked scores over digits, plus leading letters at position 0."""
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
            s["6"] += 0.60; s["0"] += 0.55     # loop low: 6, or a 0 with a lead-in stroke
        else:
            s["0"] += 0.70; s["4"] += 0.25
    if n == 0:
        if f["hbar"] and f["hbar_y"] > 0.65:            # bar at the foot of the stroke
            if "L" in s:
                s["L"] += 0.55
            s["4"] += 0.25
        if f["hbar"] and 0.25 <= f["hbar_y"] <= 0.70:   # bar crossing or high
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
            s["L"] += 0.15                              # an L's mass sits at the foot
    if 0.10 <= f["density"] <= 0.45:
        for d in "04689":
            s[d] += 0.08
    return s


def grammar(t):
    if not t:
        return None
    if t[0].isalpha():
        return "ICD-10-CM"
    if t[0].isdigit():
        return "ICD-9-CM"
    return None


def main():
    src = sys.argv[1]
    box = None
    if "--box" in sys.argv:
        i = sys.argv.index("--box"); box = [float(v) for v in sys.argv[i + 1:i + 5]]
    sens = int(sys.argv[sys.argv.index("--sens") + 1]) if "--sens" in sys.argv else 28
    drug = sys.argv[sys.argv.index("--drug") + 1] if "--drug" in sys.argv else "adalimumab"

    im = Image.open(src).convert("RGB")
    W, H = im.size
    if box:
        im = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
    crop = im.resize((im.width * 4, im.height * 4), Image.LANCZOS)
    mask = trim(strip_rules(trim(binarise(crop, sens))))

    w, h = mask.size
    prof = col_profile(mask)
    table = json.load(open(os.path.join(HERE, "icd-map.json")))
    cands, controls = {}, {}
    for ind in table["drugs"][drug]["indications"]:
        for c in ind.get("examples_icd10", []):
            cands[c.upper()] = ind["condition"]
    for c in table.get("control_examples", []):
        controls[c["code"].upper()] = c
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
                glyph_alt.append([(".", 0.90)])
                continue
            sc = score_char(f, pos)
            glyph_alt.append(sorted(sc.items(), key=lambda kv: -kv[1])[:3])
        if not ok:
            continue
        for combo in itertools.product(*glyph_alt):
            code = "".join(c for c, _ in combo)
            shape = sum(v for _, v in combo) / len(combo)
            if code.startswith("."):
                shape -= 1.0
            if "." in code and code.index(".") != 3:
                shape -= 0.8
            hit = cands.get(code.upper())
            total = shape + (2.5 if hit else 0.0) + (0.5 if grammar(code) else 0.0)
            readings.append((total, code, shape, hit, k))

    if not readings:
        print("no parse produced"); return

    readings.sort(key=lambda r: -r[0])
    seen, uniq = set(), []
    for r in readings:
        if r[1] in seen:
            continue
        seen.add(r[1]); uniq.append(r)

    print(f"mask {w}x{h}  drug={drug}  candidate codes={len(cands)}")
    print(f"{'reading':<10}{'shape':>7}{'in set':>8}  condition / note")
    for total, code, shape, hit, k in uniq[:6]:
        note = hit or (controls.get(code.upper(), {}).get("description", "") if code.upper() in controls else "")
        print(f"{code:<10}{shape:>7.2f}{('YES' if hit else 'no'):>8}  {note[:52]}")

    best = uniq[0]
    runner = uniq[1] if len(uniq) > 1 else None
    margin = best[0] - runner[0] if runner else best[0]
    conf = bool(best[3]) and margin >= 0.20

    print(f"\nreading      : {best[1]}")
    print(f"grammar      : {grammar(best[1])}")
    print(f"candidate set: {'MATCH - ' + best[3] if best[3] else 'not an indication for this drug'}")
    print(f"margin       : {margin:.2f}  ({'confident' if conf else 'AMBIGUOUS - human review'})")

    ann = crop.copy()
    d = ImageDraw.Draw(ann)
    for (x0, x1) in split_at(prof, best[4], min_w):
        d.rectangle((x0, 0, x1, ann.height), outline=(255, 0, 0), width=4)
    ann.save(os.path.join(HERE, "out", "_decode_annotated.png"))


if __name__ == "__main__":
    main()
