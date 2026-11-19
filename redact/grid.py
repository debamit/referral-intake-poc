#!/usr/bin/env python3
"""Overlay a labelled 5% grid so redaction regions can be read off in page fractions."""
from PIL import Image, ImageDraw, ImageFont
import sys

src, out = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGB")
W, H = im.size
d = ImageDraw.Draw(im, "RGBA")

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
except Exception:
    font = ImageFont.load_default()

for i in range(1, 20):
    f = i / 20.0
    x, y = int(W * f), int(H * f)
    d.line([(x, 0), (x, H)], fill=(255, 0, 0, 140), width=5)
    d.line([(0, y), (W, y)], fill=(0, 90, 255, 140), width=5)
    d.text((x + 6, 8), f"{int(f*100)}", fill=(255, 0, 0), font=font)
    d.text((8, y + 4), f"{int(f*100)}", fill=(0, 60, 255), font=font)

im.save(out)
print(out, im.size, "grid: x red 5..95, y blue 5..95")
