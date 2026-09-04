#!/usr/bin/env bash
# Virtual Butler one-click launcher.
set -euo pipefail
cd "$(dirname "$0")"

# Load OPENAI_API_KEY from .env if present (and not already exported)
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is not set."
  echo "Create a .env file in this folder containing:"
  echo '  OPENAI_API_KEY=sk-...'
  echo "Then run ./run.sh again."
  exit 1
fi

# Create venv on first run
if [ ! -d venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt
fi

exec venv/bin/python jarvis.py