#!/usr/bin/env python3
"""Rectify a photographed form so template coordinates become stable.

Two operations, both deterministic and model-free:

  1. DESKEW   - estimate page rotation by projection-profile sharpness: rotate
                through a range of angles and keep the one whose horizontal ink
                profile is sharpest. Text lines are horizontal in a square page.
  2. CROP     - trim to the ink bounding box and rescale to a canonical width, so
                every capture of the same form lands in the same coordinate frame.

The point: after this, a per-layout template of fractional boxes applies without
a vision model in the loop, so PHI is never handed to a model to locate.

  /usr/bin/python3 -I normalize.py <image> <out.png> [--width 450] [--range 4] [--step 0.25]
"""
import sys
from PIL import Image, ImageFilter, ImageChops


def ink_mask(im, scale_width=None):
    if scale_width and im.width > scale_width:
        im = im.copy()
        im.thumbnail((scale_width, 20000), Image.LANCZOS)
    bg = im.filter(ImageFilter.GaussianBlur(max(6, im.width // 25)))
    return ImageChops.subtract(bg, im).point(lambda v: 255 if v >= 28 else 0)


def sharpness(mask):
    w, h = mask.size
    px = mask.load()
    rows = [0] * h
    for y in range(h):
        c = 0
        for x in range(w):
            if px[x, y]:
                c += 1
        rows[y] = c
    return sum((rows[i] - rows[i - 1]) ** 2 for i in range(1, h))


def estimate_angle(im, rng, step, width):
    best, best_a = -1, 0.0
    n = int(rng / step)
    for i in range(-n, n + 1):
        a = i * step
        r = im.rotate(a, resample=Image.BILINEAR, fillcolor=255)
        s = sharpness(ink_mask(r, width))
        if s > best:
            best, best_a = s, a
    return best_a, best


def ink_bbox(im, pad_frac=0.02):
    m = ink_mask(im)
    w, h = m.size
    px = m.load()
    rows = [y for y in range(h) if any(px[x, y] for x in range(0, w, 2))]
    cols = [x for x in range(w) if any(px[x, y] for y in range(0, h, 2))]
    if not rows or not cols:
        return (0, 0, w, h)
    pad = int(min(w, h) * pad_frac)
    return (max(0, cols[0] - pad), max(0, rows[0] - pad),
            min(w, cols[-1] + pad), min(h, rows[-1] + pad))


def main():
    src, out = sys.argv[1], sys.argv[2]
    width = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 450
    rng = float(sys.argv[sys.argv.index("--range") + 1]) if "--range" in sys.argv else 4.0
    step = float(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else 0.25
    canon = int(sys.argv[sys.argv.index("--canon") + 1]) if "--canon" in sys.argv else 1400

    im = Image.open(src).convert("L")
    angle, score = estimate_angle(im, rng, step, width)
    print(f"deskew angle : {angle:+.2f} deg  (score {score:,.0f})")

    rot = im.rotate(angle, resample=Image.BICUBIC, fillcolor=255, expand=True)
    box = ink_bbox(rot)
    print(f"ink bbox     : {box}  of {rot.size}")
    crop = rot.crop(box)

    ratio = canon / crop.width
    crop = crop.resize((canon, int(crop.height * ratio)), Image.LANCZOS)
    crop.save(out)
    print(f"output       : {out}  {crop.size}")
    print(f"frame note   : template boxes are fractions of THIS canvas; "
          f"aspect {crop.width / crop.height:.3f}")


if __name__ == "__main__":
    main()
