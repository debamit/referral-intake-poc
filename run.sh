#!/usr/bin/env bash
# Run project code inside the project venv, immune to the inherited PYTHONPATH.
#
# This shell exports PYTHONPATH pointing at a *python3.14* Hermes venv. Without
# -E that path is injected into this 3.12 interpreter, shadowing Pillow with a
# 3.14 build and making `pip install` believe dependencies were already present.
# -E ignores PYTHON* env vars; -s drops the user site directory.
#
# Usage:  ./run.sh webapp/server.py --host 0.0.0.0 --port 8765
#         ./run.sh webapp/mask_first.py form.jpg out.png
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -E -s "$@"
