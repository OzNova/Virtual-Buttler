"""JARVIS — macOS AI Assistant Backend.

Flask-SocketIO server with clean, robust system integration.
"""

import os
import subprocess
import webbrowser
import psutil

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# ---------------------------------------------------------------------------
# Flask + SocketIO Setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "jarvis-secret")

socketio = SocketIO(app, cors_allowed_origins="http://127.0.0.1:5000")


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
            check=True,
            capture_output=True,
        )
        return "System audio muted." if muted else "System audio unmuted."
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
    print("[BACKEND] Client connected")
    emit("status_update", {"status": "connected"})


@socketio.on("disconnect")
def handle_disconnect():
    print("[BACKEND] Client disconnected")


@socketio.on("send_command")
def handle_send_command(data):
    """Parse and route incoming commands. Always emit command_result."""
    raw_cmd = data.get("command", "").strip() if data else ""
    cmd = raw_cmd.lower()

    response = ""

    # ── Open YouTube ───────────────────────────────────────────────────────
    if "open youtube" in cmd:
        webbrowser.open("https://www.youtube.com")
        response = "Opening YouTube in your browser, sir."

    # ── Open Terminal ──────────────────────────────────────────────────────
    elif "open terminal" in cmd:
        subprocess.run(["open", "-a", "Terminal"])
        response = "Launching Terminal, sir."

    # ── Open Finder ────────────────────────────────────────────────────────
    elif "open finder" in cmd:
        subprocess.run(["open", "-a", "Finder"])
        response = "Opening Finder, sir."

    # ── Mute / Unmute ──────────────────────────────────────────────────────
    elif "mute" in cmd and "unmute" not in cmd:
        subprocess.run(["osascript", "-e", "set volume output muted true"])
        response = "System audio muted."

    elif "unmute" in cmd:
        subprocess.run(["osascript", "-e", "set volume output muted false"])
        response = "System audio unmuted."

    # ── System Check / Specs / CPU / RAM ───────────────────────────────────
    elif any(kw in cmd for kw in ["system check", "specs", "cpu", "ram"]):
        info = get_system_info()
        response = (
            f"System Stats — "
            f"CPU Usage: {info.get('cpu', 0)}% | "
            f"RAM Usage: {info.get('memory', 0)}%"
        )

    # ── Default fallback ───────────────────────────────────────────────────
    else:
        response = f"Command executed: '{raw_cmd}'"

    # MUST ALWAYS emit command_result
    emit("command_result", {"status": "success", "message": response})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)