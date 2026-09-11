"""Oztudy — Desktop App Launcher
================================
Starts the Flask backend on a free local port and opens the planner in a
native macOS pywebview window. If webview fails, falls back to the default
browser.

Run:  python3 run_desktop.py    (or double-click the .command file)
"""

import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PY = os.path.join(BASE_DIR, "app.py")
LOG_FILE = os.path.join(BASE_DIR, "error.log")

log_fp = open(LOG_FILE, "a", buffering=1)


def _log(message):
    print(message, file=sys.stderr)
    print(message, file=log_fp)


def _pick_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _server_ready(url, attempts=60, delay=0.25):
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(delay)
    return False


if __name__ == "__main__":
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"
    os.environ["PLANNER_PORT"] = str(port)

    _log(f"[planner] starting {APP_PY} on {url}")
    server = subprocess.Popen(
        [sys.executable, APP_PY],
        stdout=log_fp, stderr=log_fp, cwd=BASE_DIR,
    )

    if not _server_ready(url):
        _log(f"[planner] server did not become ready at {url} — exiting")
        server.terminate()
        sys.exit(1)

    _log(f"[planner] flask bound to {url}")

    try:
        import webview
        webview.create_window(
            "Oztudy", url,
            width=1180, height=820, min_size=(980, 700),
            background_color="#F9FAFB",
        )
        webview.start()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        traceback.print_exc(file=log_fp)
        _log("[planner] webview unavailable — opening in the default browser")
        subprocess.run(["open", url], capture_output=True)

    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
