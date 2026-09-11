"""JARVIS voice/CLI client (local-only, no auth).

Sends typed commands to the local Flask backend:
    POST http://127.0.0.1:5000/api/command {"command": "..."}

Usage:
    python3 jarvis.py "open youtube"
    python3 jarvis.py            # interactive REPL
    echo "time" | python3 jarvis.py

Env:
    JARVIS_BACKEND  backend base URL (default http://127.0.0.1:5000)
    JARVIS_TIMEOUT  HTTP timeout seconds (default 90)

Why this rewrite: the previous jarvis.py was a 51-line stub importing
numpy/sounddevice/faster-whisper/openai/pynput that were never in
requirements.txt and never implemented. This client has zero third-party
deps (stdlib only) and matches what app.py actually serves (REST, not
SocketIO). Optional voice input can be added later via macOS `say`/dictation.
"""
import json
import os
import sys
import urllib.request

BACKEND_URL = os.getenv("JARVIS_BACKEND", "http://127.0.0.1:5000").rstrip("/")
TIMEOUT = float(os.getenv("JARVIS_TIMEOUT", "90"))


def send_command(text):
    payload = json.dumps({"command": text}).encode("utf-8")
    req = urllib.request.Request(
        BACKEND_URL + "/api/command",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv):
    if len(argv) > 1:
        text = " ".join(argv[1:]).strip()
        if text:
            print(json.dumps(send_command(text), indent=2))
            return 0
    # Interactive / piped mode
    if not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                res = send_command(line)
                print(res.get("message", res))
            except Exception as e:  # keep REPL alive on backend errors
                print(f"error: {e}", file=sys.stderr)
        return 0
    print(f"JARVIS client -> {BACKEND_URL} (type 'quit' to exit)")
    while True:
        try:
            line = input("sir> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.lower() in ("quit", "exit", "q"):
            break
        if not line:
            continue
        try:
            res = send_command(line)
            print(res.get("message", res))
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
