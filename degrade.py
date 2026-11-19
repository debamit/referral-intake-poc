#!/usr/bin/env python3
"""Degrade clean PDF pages into a fax-scan look (pure stdlib).

Pipeline: pdftoppm -gray -r 200 -> PGM -> blur/streak/tone/noise -> PGMs
          -> re-embed as /DeviceGray image XObjects in a new PDF.
"""
import sys, zlib, random, subprocess, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_form import PDFBuilder, W, H


def read_pgm(path):
    data = open(path, "rb").read()
    fields, i = [], 0
    while len(fields) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        fields.append(data[i:j])
        i = j
    assert fields[0] == b"P5", fields[0]
    w, h = int(fields[1]), int(fields[2])
    px = bytearray(data[i + 1:i + 1 + w * h])
    return w, h, px


def blur(src, w, h, passes=1):
    for _ in range(passes):
        out = bytearray(src)
        # vertical [1 2 1]/4
        for y in range(1, h - 1):
            r0 = (y - 1) * w
            r1 = y * w
            r2 = (y + 1) * w
            for x in range(w):
                out[r1 + x] = (src[r0 + x] + 2 * src[r1 + x] + src[r2 + x]) >> 2
        src = out
    return src


def degrade(w, h, px, rng):
    px = blur(px, w, h, passes=1)

    # per-column gain drift (fax CCD streaks)
    gain = [1.0] * w
    cur = 1.0
    for x in range(w):
        cur += rng.uniform(-0.004, 0.004)
        cur = min(1.03, max(0.965, cur))
        gain[x] = cur

    out = bytearray(len(px))
    noise = rng.randint
    for y in range(h):
        row = y * w
        # occasional horizontal line artifact
        line_bias = -6 if rng.random() < 0.004 else 0
        for x in range(w):
            v = px[row + x] * gain[x]
            # lift blacks / compress contrast: paper ~247, ink ~35
            v = 14 + (v * 0.912)
            v += line_bias + noise(-7, 7)
            if rng.random() < 0.00002:      # speckle
                v = 30
            out[row + x] = 0 if v < 0 else (255 if v > 255 else int(v))
    return out


def write_pgm(path, w, h, px):
    with open(path, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        f.write(bytes(px))


def build_pdf(pgms, out):
    b = PDFBuilder()
    b.add("<< /Type /Catalog /Pages 2 0 R >>")
    b.add("PLACEHOLDER_PAGES")
    pages = []
    for w, h, px in pgms:
        comp = zlib.compress(bytes(px), 9)
        inum = b.add((f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
                      f"/ColorSpace /DeviceGray /BitsPerComponent 8 "
                      f"/Filter /FlateDecode /Length {len(comp)} >>\nstream\n").encode()
                     + comp + b"\nendstream")
        content = f"q {W:.2f} 0 0 {H:.2f} 0 0 cm /Im0 Do Q".encode()
        cnum = b.add(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        pnum = b.add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
                     f"/Resources << /XObject << /Im0 {inum} 0 R >> >> "
                     f"/Contents {cnum} 0 R >>")
        pages.append(pnum)
    b.entries[1] = (f"<< /Type /Pages /Count {len(pages)} /Kids ["
                    + " ".join(f"{p} 0 R" for p in pages) + "] >>").encode()
    open(out, "wb").write(b.out())


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    tmp = os.path.join(os.path.dirname(out) or ".", "_faxpg")
    subprocess.run(["pdftoppm", "-gray", "-r", str(dpi), src, tmp], check=True)
    pgms = []
    rng = random.Random(20261117)
    for p in sorted(f for f in os.listdir(os.path.dirname(tmp) or ".") if f.startswith("_faxpg-")):
        w, h, px = read_pgm(os.path.join(os.path.dirname(tmp) or ".", p))
        pgms.append((w, h, degrade(w, h, px, rng)))
        os.remove(os.path.join(os.path.dirname(tmp) or ".", p))
    build_pdf(pgms, out)
    print("wrote", out, "pages=%d %dx%d" % (len(pgms), pgms[0][0], pgms[0][1]))
