#!/bin/bash
# =============================================================================
#  JARVIS — Desktop Launcher
#  Starts the JARVIS Flask server (if not running) and opens the UI in
#  Google Chrome app mode (a clean standalone window).
# =============================================================================

# Run from the script's own directory (works regardless of how it's launched).
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

URL="http://127.0.0.1:5000"
LOG="/tmp/jarvis_server.log"

# --- 1. Start the server if it isn't already listening on port 5000 ---------
if lsof -nP -iTCP:5000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✔  JARVIS is already running on port 5000."
else
    echo "⏳  Starting JARVIS server…"
    nohup python3 app.py >"$LOG" 2>&1 &
    # Give it a moment to bind the port.
    for _ in $(seq 1 20); do
        if lsof -nP -iTCP:5000 -sTCP:LISTEN >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
    if lsof -nP -iTCP:5000 -sTCP:LISTEN >/dev/null 2>&1; then
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