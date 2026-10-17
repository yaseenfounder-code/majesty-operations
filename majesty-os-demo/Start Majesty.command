#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Install Python 3.11 or newer from https://www.python.org/downloads/ and run this again.'
  read -r -p 'Press Return to close.'
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or newer is required"'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/flask --app majesty:create_app seed
echo 'Open http://127.0.0.1:5055 on this Mac. Keep this window open. Press Control-C to stop.'
.venv/bin/flask --app majesty:create_app run --host 127.0.0.1 --port 5055
