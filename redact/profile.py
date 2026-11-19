#!/usr/bin/env python3
"""Locate text lines in a photographed form, without OCR.

Flat-field corrects for uneven lighting, then removes the form's ruling lines
(long vertical/horizontal rules) so that row profiles separate into text lines.
Reports each text line as page fractions, with the ink segments across it.

  /usr/bin/python3 -I profile.py <image> [--width 700] [--sens 28]
"""
import sys
from PIL import Image, ImageFilter, ImageChops


def main():
    src = sys.argv[1]
    width = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 700
    sens = int(sys.argv[sys.argv.index("--sensitivity") + 1]) if "--sensitivity" in sys.argv else 28

    im = Image.open(src).convert("L")
    im.thumbnail((width, 20000), Image.LANCZOS)
    w, h = im.size
    bg = im.filter(ImageFilter.GaussianBlur(max(8, w // 25)))
    mask = ImageChops.subtract(bg, im).point(lambda v: 255 if v >= sens else 0)
    px = mask.load()

    col_cov = [0] * w
    for y in range(h):
        row = [x for x in range(w) if px[x, y]]
        for x in row:
            col_cov[x] += 1
    rule_col = {x for x in range(w) if col_cov[x] > 0.30 * h}
    good_cols = [x for x in range(w) if x not in rule_col]

    row_cov = []
    for y in range(h):
        row_cov.append(sum(1 for x in good_cols if px[x, y]))

    rule_row = {y for y in range(h) if row_cov[y] > 0.45 * len(good_cols)}
    thr = max(2, int(len(good_cols) * 0.006))

    bands, cur = [], None
    for y in range(h):
        on = (not y in rule_row) and row_cov[y] >= thr
        if on:
            cur = [y, y] if cur is None else [cur[0], y]
        else:
            if cur and y - cur[1] > 2:
                bands.append(tuple(cur)); cur = None
    if cur:
        bands.append(tuple(cur))

    print(f"image {w}x{h} sens={sens} words_thr={thr} rule_cols={len(rule_col)} rule_rows={len(rule_row)} bands={len(bands)}")
    print(f"{'#':>3} {'y0%':>6} {'y1%':>6} {'h%':>5}  x-segments (%)")
    for i, (y0, y1) in enumerate(bands):
        if y1 - y0 + 1 < 2:
            continue
        cols = [0] * w
        for y in range(y0, y1 + 1):
            for x in good_cols:
                if px[x, y]:
                    cols[x] += 1
        segs, start, last = [], None, None
        for x in good_cols:
            if cols[x]:
                if start is None:
                    start = x
                elif x - last > w // 60:
                    segs.append((start, last)); start = x
                last = x
        if start is not None:
            segs.append((start, last))
        segs = [s for s in segs if (s[1] - s[0]) > w * 0.008]
        print(f"{i:>3} {y0/h*100:6.2f} {y1/h*100:6.2f} {(y1-y0+1)/h*100:5.2f}  "
              + " ".join(f"{s/w*100:.1f}-{e/w*100:.1f}" for s, e in segs))


if __name__ == "__main__":
    main()
