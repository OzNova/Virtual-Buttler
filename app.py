"""Virtual Butler — macOS AI Assistant Backend.

Flask + SocketIO server with clean, robust system integration.
"""

import os
import sys
import json
import time
import logging
import webbrowser
import subprocess
import psutil

from flask import Flask, send_from_directory, jsonify, request
from flask_socketio import SocketIO, emit

# ---------------------------------------------------------------------------
# Flask + SocketIO Setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=".")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "virtual-butler-secret")

# Disable Flask-SocketIO logger spam in production
socketio_logger = os.getenv("SOCKETIO_LOGGER", "0")
if socketio_logger.strip() not in ("1", "true", "True"):
    import logging as _logging
    _logging.getLogger("socketio").setLevel(_logging.WARNING)
    _logging.getLogger("engineio").setLevel(_logging.WARNING)

socketio = SocketIO(app, cors_allowed_origins=["http://127.0.0.1:5000"])

# Push app context so background tasks work without errors
ctx = app.app_context()
ctx.push()


# ---------------------------------------------------------------------------
# Helpers: macOS System Control
# ---------------------------------------------------------------------------

def open_app(name: str) -> str:
    """Open an application by name using macOS 'open -a'."""
    name = name.strip()
    try:
        subprocess.run(["open", "-a", name], check=True, capture_output=True)
        return f"Opened application: {name}"
    except Exception:
        if name.startswith(("http://", "https://")):
            webbrowser.open(name)
            return f"Opened website: {name}"
        return f"Could not open: {name}"


def set_volume_muted(muted: bool) -> str:
    """Toggle system audio mute status via osascript."""
    state = "on" if not muted else "off"
    try:
        subprocess.run(
            ["osascript", "-e", f"set volume output muted {state}"],
            check=True, capture_output=True,
        )
        return "Audio muted." if muted else "Audio unmuted."
    except Exception as e:
        return f"Volume toggle failed: {e}"


def get_system_info():
    """Return CPU and RAM usage percentages using psutil."""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        return {
            "cpu": round(cpu_percent, 1),
            "memory": round(mem.used / mem.total * 100, 1),
            "memory_total": f"{mem.total / (1024 ** 3):.1f} GB",
            "memory_available": f"{mem.available / (1024 ** 3):.1f} GB",
        }
    except Exception as e:
        return {"cpu": 0, "memory": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Socket.IO Event Routing
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    print("[BACKEND] Client connected.", flush=True)
    emit("status_update", {"state": "CONNECTED", "cpu": 0, "memory": 0, "model": "big-pickle"})


@socketio.on("disconnect")
def handle_disconnect():
    print("[BACKEND] Client disconnected.", flush=True)


@socketio.on("voice_start")
def handle_voice_start():
    emit("system_event", {"message": "Listening…"})


@socketio.on("voice_stop")
def handle_voice_stop():
    emit("system_event", {"message": "Processing…"})


@socketio.on("send_command")
def handle_send_command(data):
    """Parse and route incoming commands. Always emit command_result."""
    cmd = data.get("command", "").strip().lower() if data else ""
    print(f"[RECV COMMAND]: {data}", flush=True)

    if not cmd:
        emit("command_result", {"status": "info", "message": "No command received."})
        return

    # ── Open YouTube ───────────────────────────────────────────────────────
    if "open youtube" in cmd:
        webbrowser.open("https://youtube.com")
        msg = "Opening YouTube..."
        emit("command_result", {"status": "success", "message": msg})
        return

    # ── Open Terminal ──────────────────────────────────────────────────────
    if "open terminal" in cmd:
        subprocess.run(["open", "-a", "Terminal"])
        msg = "Opening Terminal..."
        emit("command_result", {"status": "success", "message": msg})
        return

    # ── Open Finder ────────────────────────────────────────────────────────
    if "open finder" in cmd:
        subprocess.run(["open", "-a", "Finder"])
        msg = "Opening Finder..."
        emit("command_result", {"status": "success", "message": msg})
        return

    # ── Mute / Unmute ──────────────────────────────────────────────────────
    if "mute" in cmd:
        subprocess.run(["osascript", "-e", "set volume output muted true"])
        msg = "Audio muted."
        emit("command_result", {"status": "success", "message": msg})
        return
    if "unmute" in cmd:
        subprocess.run(["osascript", "-e", "set volume output muted false"])
        msg = "Audio unmuted."
        emit("command_result", {"status": "success", "message": msg})
        return

    # ── Default fallback ───────────────────────────────────────────────────
    msg = f"Command received: {cmd}"
    emit("command_result", {"status": "success", "message": msg})


# ---------------------------------------------------------------------------
# Background Telemetry (with app context)
# ---------------------------------------------------------------------------

def background_status_telemetry():
    """Emit live CPU/RAM metrics every 3 seconds inside app context."""
    while True:
        try:
            with app.app_context():
                info = get_system_info()
                socketio.emit("status_update", {
                    "state": "CONNECTED",
                    "cpu": info.get("cpu", 0),
                    "memory": info.get("memory", 0),
                    "model": "big-pickle"
                }, broadcast=True)
            socketio.sleep(3)
        except Exception as e:
            print(f"[BACKGROUND] Telemetry error: {e}", flush=True)
            break


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/<path:path>")
def static_proxy(path):
    if os.path.exists(path):
        return send_from_directory(".", path)
    return jsonify({"error": "not found"}), 404


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1")
    debug = os.getenv("FLASK_DEBUG", "0") not in ("1", "true", "True")

    print(f"▶️  Virtual Butler backend starting on {host}:{port}", flush=True)
    socketio.start_background_task(background_status_telemetry)
    socketio.run(app, host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()