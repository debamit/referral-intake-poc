#!/usr/bin/env python3
"""Redact PII/PHI from a scanned or photographed pharmacy referral form.

Design: regions live in a per-layout template as FRACTIONS of the page, so one
template works at any scan resolution and on a phone photo. The script is
version-agnostic; each form version supplies its own template.

Safety property (the important one): FAIL CLOSED. If no template is supplied and
the layout cannot be identified with confidence, the script exits non-zero and
writes nothing. A half-redacted page is worse than no page.

Run with an interpreter that has a working Pillow, e.g.
    /usr/bin/python3 -I redact.py --in x.jpg --template legacy_supply_request_v1 --out redacted
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(HERE, "templates")

DEFAULT_FILL = (58, 58, 58)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_template(name):
    path = name if os.path.sep in name or name.endswith(".json") else os.path.join(TPL_DIR, name + ".json")
    if not os.path.exists(path):
        sys.exit(f"error: template not found: {path}")
    with open(path) as f:
        t = json.load(f)
    for r in t["regions"]:
        x0, y0, x1, y1 = r["box"]
        if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
            sys.exit(f"error: template {t['name']} region {r['id']} has an invalid box {r['box']}")
    return t


def page_images(src, dpi, tmpdir):
    """Return [(page_no, path, width, height)] for an image or a PDF."""
    low = src.lower()
    if low.endswith((".pdf",)):
        base = os.path.join(tmpdir, "pg")
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", src, base], check=True)
        pages = sorted(f for f in os.listdir(tmpdir) if f.startswith("pg-") and f.endswith(".png"))
        out = []
        for f in pages:
            p = os.path.join(tmpdir, f)
            with Image.open(p) as im:
                out.append((len(out) + 1, p, im.width, im.height))
        return out
    return [(1, src, None, None)]


def redact_page(im, regions, fill, label, debug=False):
    im = im.convert("RGB").copy()          # new image: drops EXIF/GPS
    d = ImageDraw.Draw(im)
    W, H = im.size
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(14, W // 90))
    except Exception:
        font = ImageFont.load_default()
    for r in regions:
        x0, y0, x1, y1 = r["box"]
        px = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
        if debug:
            d.rectangle(px, outline=(255, 0, 0), width=max(3, W // 400))
            d.text((px[0] + 6, px[1] + 4), r["id"], fill=(255, 0, 0), font=font)
            continue
        d.rectangle(px, fill=fill)
        if label and (px[2] - px[0]) > 120 and (px[3] - px[1]) > 24:
            d.text((px[0] + 6, px[1] + 4), f"{r['category']}", fill=(200, 200, 200), font=font)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--template")
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--dpi", type=int, default=200, help="render dpi for PDF input")
    ap.add_argument("--label", action="store_true", help="print the category inside each box")
    ap.add_argument("--keep", nargs="*", default=[], help="categories to leave unmasked")
    ap.add_argument("--debug", action="store_true", help="draw region outlines instead of fills")
    ap.add_argument("--manifest", default=None)
    a = ap.parse_args()

    if not os.path.exists(a.src):
        sys.exit(f"error: input not found: {a.src}")
    if not a.template:
        sys.exit("error: --template is required (fail-closed: this script will not guess a layout)")

    tpl = load_template(a.template)
    regions = [r for r in tpl["regions"] if r["category"] not in a.keep]

    src_hash = sha256(a.src)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        pages = page_images(a.src, a.dpi, td)
        expected = tpl.get("pages")
        if expected and len(pages) != expected:
            sys.exit(f"error: template {tpl['name']} expects {expected} page(s), input has {len(pages)}. "
                     f"Fail-closed: refusing to emit a partially redacted document.")

        outs = []
        for n, path, w, h in pages:
            pregs = [r for r in regions if r.get("page", 1) == n]
            if not pregs:
                sys.exit(f"error: no regions defined for page {n}. Fail-closed.")
            with Image.open(path) as im:
                out = redact_page(im, pregs, tuple(tpl.get("fill", DEFAULT_FILL)), a.label, debug=a.debug)
                png = f"{a.out}-p{n}.png"
                out.save(png)
                outs.append((n, png, out))

        pdf = f"{a.out}.pdf"
        if len(outs) == 1:
            outs[0][2].save(pdf, "PDF", resolution=a.dpi)
        else:
            outs[0][2].save(pdf, "PDF", resolution=a.dpi, save_all=True,
                            append_images=[o[2] for o in outs[1:]])

    manifest = {
        "template": tpl["name"],
        "source": os.path.abspath(a.src),
        "source_sha256": src_hash,
        "source_exists_after": True,
        "regions_masked": [r["id"] for r in regions],
        "categories_masked": sorted({r["category"] for r in regions}),
        "categories_left_visible": sorted({r["category"] for r in tpl["regions"]} - {r["category"] for r in regions}),
        "outputs": [os.path.abspath(p) for _, p, _ in outs] + [os.path.abspath(pdf)],
        "box_model": "fractional, origin top-left",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "redaction_note": "pixels are overwritten in a new image; no EXIF/GPS carried forward",
    }
    if a.manifest:
        with open(a.manifest, "w") as f:
            json.dump(manifest, f, indent=2)

    print(f"template      : {tpl['name']}")
    print(f"regions masked: {len(regions)} across {len(outs)} page(s)")
    print(f"categories    : {', '.join(manifest['categories_masked'])}")
    if manifest["categories_left_visible"]:
        print(f"left visible  : {', '.join(manifest['categories_left_visible'])}")
    for o in manifest["outputs"]:
        print("wrote         :", o)


if __name__ == "__main__":
    main()
