"""JARVIS — macOS AI Assistant Backend.

Flask REST API backend with native macOS system integration.
No WebSockets or Socket.IO. Uses native fetch() calls from the frontend.
Falls back gracefully if speech modules aren't fully available.
"""

import os
import subprocess
import webbrowser
import datetime
import random
from flask import Flask, render_template, request, jsonify
import psutil

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Text-to-Speech Engine (always available via pyttsx3)
# ---------------------------------------------------------------------------
try:
    import pyttsx3
    _engine = pyttsx3.init()
    _engine.setProperty('rate', 150)
    _engine.setProperty('volume', 0.9)

    def speak(text):
        """Text-to-speech using pyttsx3 (local, no internet needed)."""
        try:
            _engine.say(text)
            _engine.runAndWait()
        except Exception:
            pass
except Exception:
    _engine = None
    def speak(text):
        """No-op if TTS not available."""
        pass  # optional: print(f"TTS: {text}")


# ---------------------------------------------------------------------------
# Smart Response Engine
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE = {
    "greetings": {
        "patterns": ["hello", "hi", "hey", "good morning", "good afternoon"],
        "responses": [
            "Hello Ozan. All systems are fully operational.",
            "Online and ready for your commands, sir.",
            "Hey! How can I assist you with your system today?"
        ]
    },
    "status": {
        "patterns": ["how are you", "status", "whats up", "how do you do"],
        "responses": [
            "Running at peak performance, sir.",
            "All background services are healthy and responsive.",
            "I'm operating efficiently. What are we building or running today?"
        ]
    },
    "identity": {
        "patterns": ["who are you", "what are you", "your name"],
        "responses": [
            "I am JARVIS, your personal macOS AI assistant.",
            "I am JARVIS, designed to execute system controls and manage your workspace."
        ]
    },
    "thanks": {
        "patterns": ["thanks", "thank you", "thankyou"],
        "responses": [
            "You're welcome, sir.",
            "Always at your service.",
            "Anytime, Ozan!"
        ]
    }
}


def generate_smart_response(text):
    """Generate a natural, varied response for conversational inputs."""
    clean_text = text.lower().strip()

    # ── macOS Sistem Komutları Tespiti ─────────────────────────────────────
    if "open youtube" in clean_text:
        webbrowser.open("https://www.youtube.com")
        speak("Opening YouTube in your browser, sir.")
        return "Opening YouTube in your browser, sir."

    if "open terminal" in clean_text:
        subprocess.run(["open", "-a", "Terminal"])
        speak("Launching Terminal application, sir.")
        return "Launching Terminal application, sir."

    if "open finder" in clean_text:
        subprocess.run(["open", "-a", "Finder"])
        speak("Opening Finder window, sir.")
        return "Opening Finder window, sir."

    if "mute" in clean_text and "unmute" not in clean_text:
        subprocess.run(["osascript", "-e", "set volume output muted true"])
        speak("System audio muted, sir.")
        return "System audio muted, sir."

    if "unmute" in clean_text:
        subprocess.run(["osascript", "-e", "set volume output muted false"])
        speak("System audio unmuted, sir.")
        return "System audio unmuted, sir."

    if any(k in clean_text for k in ["system check", "specs", "cpu", "ram", "telemetry"]):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        msg = f"System Telemetry — CPU: {cpu}% | RAM Usage: {ram}%"
        speak(msg)
        return msg

    if any(k in clean_text for k in ["time", "saat", "clock"]):
        now = datetime.datetime.now().strftime("%H:%M")
        msg = f"Current local time is {now}, sir."
        speak(msg)
        return msg

    # ── Doğal Dil ve Sohbet Tespiti ───────────────────────────────────────
    for intent, data in KNOWLEDGE_BASE.items():
        if any(pattern in clean_text for pattern in data["patterns"]):
            return random.choice(data["responses"])

    # 3. Genel Esnek Cevap Motoru (Bilinmeyen Cümleler İçin)
    fallback_responses = [
        f"I've analyzed '{text}'. While it's not a recognized system command, I'm logging it.",
        f"Understood. Currently, I can open apps (YouTube, Terminal, Finder), adjust volume, or show system stats.",
        f"I heard: '{text}'. Try asking me for 'system check' or to 'open terminal'."
    ]
    return random.choice(fallback_responses)


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/command", methods=["POST"])
def handle_command():
    """Accept JSON {"command": "text"} and return {"status": "success", "message": "response_text"}."""
    data = request.get_json() or {}
    raw_cmd = data.get("command", "").strip()

    if not raw_cmd:
        return jsonify({"status": "error", "message": "Empty command"}), 400

    response_text = generate_smart_response(raw_cmd)
    return jsonify({"status": "success", "message": response_text})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)