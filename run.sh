#!/usr/bin/env bash
# Virtual Butler launcher (local-only, no auth).
# Serves app.py on 127.0.0.1:5000. GEMINI_API_KEY is optional (fallback tier).
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

PYBIN="python3"
if [ -x "venv/bin/python" ]; then
  PYBIN="venv/bin/python"
elif [ ! -d venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt
  PYBIN="venv/bin/python"
fi

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "(info) GEMINI_API_KEY not set — Gemini fallback disabled, Ollama + snippets still work."
fi

exec "$PYBIN" app.py
