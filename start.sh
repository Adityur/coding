#!/usr/bin/env bash
# First run creates a virtualenv and installs dependencies, then starts the server.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
exec python run.py
