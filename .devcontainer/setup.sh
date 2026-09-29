#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
echo "GrowthLog is ready. Run: .venv/bin/python -m flask --app app run --host 127.0.0.1 --reload"
