#!/bin/bash
# =============================================================================
#  JARVIS — Desktop Launcher (local-only, no auth)
#  Starts the JARVIS Flask server (if not running) and opens the UI in
#  Google Chrome app mode (a clean standalone window).
# =============================================================================

# Run from the script's own directory (works regardless of how it's launched).
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PORT="${PORT:-5000}"
URL="http://127.0.0.1:${PORT}"
LOG="/tmp/jarvis_server.log"

# Prefer the project venv when present.
PYBIN="python3"
if [ -x "venv/bin/python" ]; then
  PYBIN="venv/bin/python"
fi

# --- 1. Start the server if it isn't already listening -----------------------
if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✔  JARVIS is already running on port ${PORT}."
else
    echo "⏳  Starting JARVIS server (${PYBIN} app.py)…"
    # shellcheck disable=SC2086
    nohup $PYBIN app.py >"$LOG" 2>&1 &
    # Give it a moment to bind the port.
    for _ in $(seq 1 20); do
        if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
    if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "✔  JARVIS server started. Logs: $LOG"
    else
        echo "⚠  Server did not start. Check $LOG for details."
    fi
fi

# --- 2. Ensure a usable Google Chrome, then open the app window ---------------
if open -na "Google Chrome" --args --app="$URL" 2>/dev/null; then
    echo "🖥️   Opened JARVIS in Chrome app mode."
else
    echo "🖥️   Fallback: opening in default browser."
    open "$URL"
fi

echo "✨  JARVIS is ready — have a great day, sir."
