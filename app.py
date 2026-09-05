"""Virtual Butler — Flask + SocketIO Backend Server.

Run this server independently, or let jarvis.py auto-start it.
Serves the HUD UI and handles real-time voice engine events.
"""

import os
import time
import logging
from flask import Flask, send_from_directory, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, static_folder=".")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "virtual-butler-secret")

# Disable Flask-SocketIO logger spam in production
socketio_logger = os.getenv("SOCKETIO_LOGGER", "0")
if socketio_logger.strip() not in ("1", "true", "True"):
    import logging as _logging
    _logging.getLogger("socketio").setLevel(_logging.WARNING)
    _logging.getLogger("engineio").setLevel(_logging.WARNING)

socketio = SocketIO(app, cors_allowed_origins=["http://127.0.0.1:5000"])

# Track connection state and latency
connection_state = "DISCONNECTED"
model_info = "big-pickle"
last_latency = 0
connect_time = None


# ── Serve the HUD UI ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/<path:path>")
def static_proxy(path):
    if os.path.exists(path):
        return send_from_directory(".", path)
    return jsonify({"error": "not found"}), 404


# ── Socket.IO events ──────────────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    global connection_state, connect_time
    connection_state = "CONNECTED"
    connect_time = time.time()
    print("[BACKEND] Client connected.", flush=True)

    # Calculate approximate latency from connect time
    latency = 0
    if connect_time:
        latency = int((time.time() - connect_time) * 1000)

    emit("status_update", {
        "state": connection_state,
        "model": model_info,
        "latency": latency
    }, room=request.sid)

    emit("system_check_response", {
        "status": connection_state,
        "model": model_info,
        "latency": latency
    })


@socketio.on("disconnect")
def handle_disconnect():
    global connection_state
    connection_state = "DISCONNECTED"
    print("[BACKEND] Client disconnected.", flush=True)


@socketio.on("voice_start")
def handle_voice_start():
    print("[BACKEND] Voice start received.", flush=True)
    emit("system_event", {"message": "Listening…"})


@socketio.on("voice_stop")
def handle_voice_stop():
    print("[BACKEND] Voice stop received.", flush=True)
    emit("system_event", {"message": "Processing…"})


@socketio.on("action")
def handle_action(data):
    """Receive a text command from the frontend and return a JSON action."""
    text = data.get("text", "") if data else ""
    if not text:
        return

    print(f"[BACKEND] Action requested: \"{text}\"", flush=True)

    # TODO: In a full integration, this would feed into the Python assistant
    # For now, echo back a structured response
    emit("command_result", {
        "text": f"Command received: {text}",
        "success": True
    })


@socketio.on("voice_state")
def handle_voice_state(data):
    """Broadcast voice state to all connected clients."""
    state = data.get("state", "idle") if data else "idle"
    print(f"[BACKEND] Voice state: {state}", flush=True)
    emit("voice_state", {"state": state}, broadcast=True)


@socketio.on("voice_error")
def handle_voice_error(data):
    """Handle error events from the voice engine."""
    message = data.get("message", "Unknown error") if data else "Unknown error"
    print(f"[BACKEND] Error: {message}", flush=True)
    emit("voice_error", {"message": message}, broadcast=True)


@socketio.on("system_check")
def handle_system_check(data):
    """Handle system check request from client."""
    emit("system_check_response", {
        "status": connection_state,
        "model": model_info,
        "latency": last_latency
    })


@socketio.on("error")
def handle_socket_error(data):
    """Handle socket.IO error events."""
    message = data.get("message", "Socket error") if data else "Socket error"
    print(f"[BACKEND] Socket error: {message}", flush=True)
    emit("error", {"message": message})


# ── Background task for periodic status telemetry ───────────────

def background_status_telemetry():
    """Emit periodic status_update with latency metrics."""
    while True:
        try:
            socketio.sleep(5)
            # Simulate dynamic latency (in real use, this would be measured)
            import random
            latency = random.randint(20, 150)
            global last_latency
            last_latency = latency

            if connection_state == "CONNECTED":
                emit("status_update", {
                    "state": connection_state,
                    "model": model_info,
                    "latency": latency
                }, broadcast=True)
        except Exception as e:
            print(f"[BACKGROUND] Telemetry error: {e}", flush=True)
            break


# ── Main ──────────────────────────────────────────────────────────

def main():
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1")
    debug = os.getenv("FLASK_DEBUG", "0") not in ("1", "true", "True")

    print(f"▶️  Virtual Butler backend starting on {host}:{port}", flush=True)

    # Start background telemetry task
    socketio.start_background_task(background_status_telemetry)

    socketio.run(app, host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()