# Referral intake — field decode POC

Proof of concept for reading a faxed specialty-pharmacy referral form: locate fields by their
printed labels, de-identify the page before anything reads it, and decode the diagnosis code with
hard gates rather than a confidence score.

## What it does

1. **Mask first.** One local OCR pass locates the lines carrying patient-identity labels, blanks
   them, and discards the original. Every later stage sees only the masked image, so privacy is
   structural rather than a promise about what a stage was shown. The mask report records label
   names and boxes — never the values it removed.
2. **Anchor by label, not by coordinate.** Crops are derived from the printed label and the ink to
   its right. No measured page fractions, so a form revision does not silently move the crop.
3. **Constrain the decode.** The diagnosis field is not OCR. The alphabet is small, the grammar is
   fixed, and the drug on the page narrows the legitimate answers to a few hundred codes. Existence,
   grammar and candidate-set membership are pass/fail gates; the shape score only ranks what
   survives. That is what makes a decision explainable in one line.
4. **Separate reads from decisions.** Only the diagnosis gets a gate. Drug, SIG, dispense and
   refills are reported as `read` or `review`, because no gate exists that could verify
   "1 (ONE) month supply" — calling that `accept` would be the confident-wrong failure this design
   exists to prevent.

## Run

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-ocr.txt
./run.sh webapp/server.py --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765 and drop a form image in. `run.sh` invokes the venv with `-E -s` so an
inherited `PYTHONPATH` cannot shadow the venv's packages.

CLI:

```bash
./run.sh webapp/fields.py path/to/form.jpg     # all fields
./run.sh webapp/mask_first.py path/to/form.jpg out.png
```

## Privacy

- No referral images, scans or vendor forms are in this repository; `*.pdf`, `*.png`, `*.jpg` and
  `samples/` are gitignored.
- OCR inference is local ONNX. Nothing is uploaded, and there is no network call in the pipeline.
- The mask step runs before any field extraction, so a downstream model never sees patient identity.

## Status

Proof of concept. Measured on a single photographed fax:

- mask + quality gate + fingerprint + 5 field crops: ~5 s/page, warm
- diagnosis decode: ~0.7 s
- OCR is ~80% of the cost; downscaling the page breaks the decode, so only the OCR pass is capped

Not yet validated: the quality gate has never fired on a genuinely degraded scan, and every number
comes from one form family. Treat the thresholds as placeholders until measured on real volume.

## Layout

```
webapp/
  ocr_engine.py   OCR wrapper: read, label search, quality gate, fingerprint, masking
  mask_first.py   de-identify a page and discard the original
  fields.py       multi-field location + read/decode per field
  decode_lib.py   constrained ICD decode: gates, enumeration, ranking
  server.py       stdlib HTTP server (/api/fields, /api/decode)
  index.html      three-panel UI: input, masked page, output
spec/             field contract, derivation map, triage spec
redact/           earlier masking tooling and ICD indication map
```
