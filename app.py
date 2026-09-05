"""Virtual Butler — Premium macOS AI Assistant Backend.

Flask + SocketIO server with full macOS system integration:
- Open any app/website
- Volume control via osascript
- Real-time CPU/RAM telemetry via psutil
- Conversational AI with command intent parsing
- Real-time status telemetry (status_update)
- Reliable send_command / command_result pipeline
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
from datetime import datetime

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

# Ensure background tasks run within app context
ctx = app.app_context()
ctx.push()


# ---------------------------------------------------------------------------
# Helpers: macOS System Control
# ---------------------------------------------------------------------------

def open_application(name: str):
    """Open an app or website using macOS 'open' command."""
    name = name.strip()
    # If it looks like a URL, open directly
    if name.startswith("http://") or name.startswith("https://"):
        webbrowser.open(name)
        return f"Opening website: {name}"
    # Try launching via macOS 'open -a'
    try:
        subprocess.run(["open", "-a", name], check=True, capture_output=True)
        return f"Opening application: {name}"
    except subprocess.CalledProcessError:
        # Fallback: try webbrowser if not an app
        webbrowser.open(name)
        return f"Opened via webbrowser: {name}"


def set_volume(level: int):
    """Set system output volume (0-100) via osascript."""
    level = max(0, min(100, int(level)))
    try:
        subprocess.run(
            ["osascript", "-e", f"set volume output volume {level}"],
            check=True,
            capture_output=True,
        )
        return f"Volume set to {level}%"
    except Exception as e:
        return f"Failed to set volume: {e}"


def get_system_info():
    """Return CPU and RAM usage percentages."""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        return {
            "cpu": round(cpu_percent, 1),
            "memory": round(mem.used / mem.total * 100, 1),
            "memory_total": f"{mem.total / (1024**3):.1f} GB",
            "memory_available": f"{mem.available / (1024**3):.1f} GB",
        }
    except Exception as e:
        return {"cpu": "--", "memory": "--", "error": str(e)}


def generate_assistant_response(text: str) -> str:
    """Simple conversational fallback when no action is recognized."""
    t = text.lower().strip()
    if any(w in t for w in ["hello", "hi", "hey", "how are you"]):
        return "Hello sir! All systems nominal. How may I assist you today?"
    if any(w in t for w in ["thank you", "thanks"]):
        return "You're very welcome, sir!"
    if any(w in t for w in ["what's the time", "time"]):
        return f"The current time is {datetime.now().strftime('%I:%M %p')}."
    # Default fallback
    return "I'm not sure I understand, sir. Could you rephrase?"


# ---------------------------------------------------------------------------
# Socket.IO Events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    print("[BACKEND] Client connected.", flush=True)
    emit("status_update", {
        "state": "CONNECTED",
        "model": "big-pickle",
        "latency": 0,
        "timestamp": datetime.utcnow().isoformat()
    }, room=request.sid)


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
    """Parse and intelligently handle incoming commands.

    Supported intents:
      - open <app|website>        → webbrowser.open / subprocess.run(['open', '-a', ...])
      - set volume <0-100>        → osascript volume set
      - system info / specs       → return CPU/RAM stats
      - conversational / question → AI-generated response
    """
    text = data.get("text", "") if data else ""
    if not text:
        return

    print(f"[BACKEND] Command received: \"{text}\"", flush=True)
    text_lower = text.lower().strip()

    # ── Intent: Open application or website ──────────────────────────────
    if any(keyword in text_lower for keyword in ["open", "launch"]):
        # Extract the target after "open" / "launch"
        # Patterns: "open youtube", "open spotify", "open terminal"
        target = text_lower
        for keyword in ["open ", "launch "]:
            target = target.replace(keyword, "", 1).strip()

        # Check for volume sub-command
        if "volume" in target:
            # Extract level
            level_str = target.replace("volume", "", 1).strip()
            level = int(level_str) if level_str.isdigit() else 70
            result = set_volume(level)
        elif any(app in target for app in ["youtube", "spotify", "terminal", "finder", "chrome", "safari", "music", "calculator"]):
            result = open_application(target)
        else:
            # Generic open
            result = open_application(target)

        emit("command_result", {
            "status": "success",
            "message": result,
            "action": "open"
        })

    # ── Intent: Volume Control ───────────────────────────────────────────
    elif "volume" in text_lower:
        # Extract level if present
        level_str = ""
        for word in text_lower.split():
            if word.isdigit():
                level_str = word
                break
        level = int(level_str) if level_str else 70
        result = set_volume(level)
        emit("command_result", {
            "status": "success",
            "message": result,
            "action": "volume"
        })

    # ── Intent: System Info / Specs ──────────────────────────────────────
    elif any(kw in text_lower for kw in ["specs", "system info", "my computer", "computer info", "cpu", "ram"]):
        info = get_system_info()
        lines = [
            f"CPU Usage: {info.get('cpu', '--')}%",
            f"Memory Usage: {info.get('memory', '--')}%",
        ]
        if "error" not in info:
            lines.append(f"Total RAM: {info.get('memory_total', '--')}")
            lines.append(f"Available: {info.get('memory_available', '--')}")
        emit("command_result", {
            "status": "success",
            "message": "\n".join(lines),
            "action": "system_info"
        })

    # ── Conversational / Question Fallback ───────────────────────────────
    else:
        response = generate_assistant_response(text)
        emit("command_result", {
            "status": "info",
            "message": response,
            "action": "conversational"
        })


# ── Background task for periodic status telemetry ──────────────────────────

def background_status_telemetry():
    """Emit periodic status_update with real CPU/RAM metrics."""
    while True:
        try:
            socketio.sleep(8)
            info = get_system_info()
            emit("status_update", {
                "state": "CONNECTED",
                "model": "big-pickle",
                "latency": 0,
                "cpu": info.get("cpu", 0),
                "memory": info.get("memory", 0),
            }, broadcast=True)
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

    print(f"▶️  Virtual Butler macOS Assistant starting on {host}:{port}", flush=True)

    # Start background telemetry task (with app context)
    socketio.start_background_task(background_status_telemetry)

    socketio.run(app, host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()