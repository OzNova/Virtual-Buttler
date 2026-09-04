"""Virtual Butler — Flask + SocketIO Backend Server.

Run this server independently, or let jarvis.py auto-start it.
Serves the HUD UI and handles real-time voice engine events.
"""

import os
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

app = Flask(__name__, static_folder=".")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "virtual-butler-secret")

# Disable Flask-SocketIO logger spam in production
socketio_logger = os.getenv("SOCKETIO_LOGGER", "0")
if socketio_logger.strip() not in ("1", "true", "True"):
    import logging as _logging
    _logging.getLogger("socketio").setLevel(_logging.WARNING)
    _logging.getLogger("engineio").setLevel(_logging.WARNING)

socketio = SocketIO(app, cors_allowed_origins="*")

# ── Serve the HUD UI ──────────────────────────────────────────────


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/<path:path>")
def static_proxy(path):
    if os.path.exists(path):
        return send_from_directory(".", path)
    return {"error": "not found"}, 404


# ── Socket.IO events ──────────────────────────────────────────────


@socketio.on("connect")
def handle_connect():
    print("[BACKEND] Client connected.", flush=True)
    emit("system_event", {
        "message": "Virtual Butler backend online, sir. "
                   "Hold CMD+SHIFT or press PUSH TO TALK."
    })


@socketio.on("disconnect")
def handle_disconnect():
    print("[BACKEND] Client disconnected.", flush=True)


@socketio.on("voice_start")
def handle_voice_start():
    print("[BACKEND] Voice start received.", flush=True)
    emit("system_event", {"message": "Listening…"})


@socketio.on("voice_stop")
def handle_voice_stop():
    print("[BACKEND] Voice stop received.", flush=True)
    emit("system_event", {"message": "Processing..."})


@socketio.on("action")
def handle_action(data):
    """Receive a text command from the frontend and return a JSON action."""
    text = data.get("text", "")
    if not text:
        return

    print(f"[BACKEND] Action requested: \"{text}\"", flush=True)

    # TODO: In a full integration, this would feed into the Python assistant
    # For now, echo back a response
    emit("action_result", {
        "text": f"Command received: {text}",
        "success": True
    })


@socketio.on("voice_state")
def handle_voice_state(data):
    """Broadcast voice state to all connected clients."""
    state = data.get("state", "idle")
    print(f"[BACKEND] Voice state: {state}", flush=True)
    emit("voice_state", {"state": state}, broadcast=True)


@socketio.on("voice_error")
def handle_voice_error(data):
    """Handle error events from the voice engine."""
    message = data.get("message", "Unknown error")
    print(f"[BACKEND] Error: {message}", flush=True)
    emit("voice_error", {"message": message}, broadcast=True)


# ── Main ──────────────────────────────────────────────────────────


def main():
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1")
    debug = os.getenv("FLASK_DEBUG", "0") not in ("1", "true", "True")

    print(f"▶️  Virtual Butler backend starting on {host}:{port}", flush=True)
    socketio.run(app, host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()