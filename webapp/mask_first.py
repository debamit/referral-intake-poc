#!/usr/bin/env python3
"""Mask-first pre-step: OCR the page, blank the patient rows, discard the original.

The point is structural, not cosmetic. After this step the only image that
continues down the pipeline has no patient identity on it, so every later stage
— including any model — is operating on de-identified pixels by construction
rather than by promise.

  env -u PYTHONPATH .venv-ocr/bin/python mask_first.py <image> <out.png>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ocr_engine


def mask_first(image_path, out_path=None, verbose=True):
    from PIL import Image

    im = Image.open(image_path).convert("RGB")
    words = ocr_engine.read(im)

    q = ocr_engine.quality(words)
    fp = ocr_engine.fingerprint(words)

    masked, report = ocr_engine.mask_lines(im, words)

    result = {
        "source": os.path.abspath(image_path),
        "quality": q,
        "fingerprint": fp,
        "regions_masked": len(report),
        "words_masked": sum(r["words_masked"] for r in report),
        "labels_hit": sorted({l for r in report for l in r["labels"]}),
        "detail": report,
        "original_discarded": True,
        "ocr_words_total": len(words),
    }

    if out_path:
        masked.save(out_path)

    if verbose:
        print(f"ocr words    : {len(words)}")
        print(f"quality      : {q['verdict']}  median={q.get('median')} p10={q.get('p10')} "
              f"low={q.get('frac_below_0.50')}")
        print(f"fingerprint  : {fp['form_id']} ({fp['confidence']}, {fp['matched_markers']} markers)")
        print(f"masked       : {len(report)} line(s), {result['words_masked']} words, "
              f"labels={result['labels_hit']}")
        for r in report:
            print(f"   box {r['box_frac']}  <- {r['labels']}")
        if out_path:
            print(f"wrote        : {out_path}")

    return masked, result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: mask_first.py <image> [out.png]")
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else None
    _, res = mask_first(src, dst)
    if len(sys.argv) > 3 and sys.argv[3] == "--json":
        print(json.dumps({k: v for k, v in res.items() if k != "detail"}, indent=2))
