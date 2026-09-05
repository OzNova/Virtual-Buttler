"""JARVIS — macOS AI Assistant Backend.

Flask REST API backend with native macOS system integration.
REST endpoint:  POST /api/command   {"command": "text"}
Frontend uses native fetch() — no WebSockets.

System access via subprocess (osascript / open / pmset / system_profiler / etc.)
Voice output via pyttsx3 (local TTS). Microphone input is handled in the
browser using the Web Speech API, so no backend speech_recognition is required.
"""

import os
import re
import subprocess
import webbrowser
import datetime
import random
import socket
import platform

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Text-to-Speech Engine (local, no internet needed)
# ---------------------------------------------------------------------------
try:
    import pyttsx3
    _engine = pyttsx3.init()
    _engine.setProperty("rate", 150)
    _engine.setProperty("volume", 0.9)

    def speak(text):
        try:
            _engine.say(text)
            _engine.runAndWait()
        except Exception:
            pass
except Exception:
    _engine = None
    def speak(text):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd):
    """Run a shell-level command list and return stripped stdout or None."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    except Exception:
        return None


def _osascript(script):
    """Run an AppleScript snippet via osascript."""
    return _run(["osascript", "-e", script])


# ---------------------------------------------------------------------------
# Conversational Knowledge Base
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE = {
    "greetings": {
        "patterns": ["hello", "hi", "hey", "good morning", "good afternoon", "good evening", "selam"],
        "responses": [
            "Hello Ozan. All systems are fully operational.",
            "Online and ready for your commands, sir.",
            "Hey! How can I assist you with your system today?"
        ]
    },
    "status": {
        "patterns": ["how are you", "whats up", "how do you do", "status"],
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
        "patterns": ["thanks", "thank you", "thankyou", "teşekkür"],
        "responses": [
            "You're welcome, sir.",
            "Always at your service.",
            "Anytime, Ozan!"
        ]
    },
    "capabilities": {
        "patterns": ["what can you do", "help", "commands", "abilities", "features"],
        "responses": [
            "I can open apps and websites, control system volume, take screenshots, report CPU/RAM/battery/network stats, show the time and date, send desktop notifications, and hold a conversation. Just tell me what you need, sir."
        ]
    }
}

# Common macOS apps: "open app" style. Key is a trigger substring, value is the app name.
APP_MAP = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "finder": "Finder",
    "music": "Music",
    "itunes": "Music",
    "spotify": "Spotify",
    "notes": "Notes",
    "calculator": "Calculator",
    "calendar": "Calendar",
    "mail": "Mail",
    "messages": "Messages",
    "facetime": "FaceTime",
    "photos": "Photos",
    "preview": "Preview",
    "textedit": "TextEdit",
    "sublime": "Sublime Text",
    "code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "pycharm": "PyCharm",
}


# ---------------------------------------------------------------------------
# System Command Handlers
# ---------------------------------------------------------------------------

def _handle_system_command(clean_text, original_text):
    """Return a response message for a matched system command, or None."""

    # --- Open a website ---
    url_match = re.search(r"open\s+(https?://\S+|www\.\S+)", clean_text)
    if url_match:
        url = url_match.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        speak(f"Opening {url}, sir.")
        return f"Opening {url} in your browser, sir."

    known_sites = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "stack overflow": "https://stackoverflow.com",
        "twitter": "https://twitter.com",
        "x ": "https://x.com",
    }
    for site, url in known_sites.items():
        if ("open " + site.strip()) in clean_text or (site.strip() + " sayfası") in clean_text:
            webbrowser.open(url)
            speak(f"Opening {site.strip()}, sir.")
            return f"Opening {site.strip()} in your browser, sir."

    # --- Open an installed app ---
    for trigger, app_name in APP_MAP.items():
        if f"open {trigger}" in clean_text or (trigger in clean_text and "open" in clean_text):
            subprocess.run(["open", "-a", app_name])
            speak(f"Launching {app_name}, sir.")
            return f"Launching {app_name}, sir."

    # --- Volume control ---
    if "mute" in clean_text and "unmute" not in clean_text:
        _run(["osascript", "-e", "set volume output muted true"])
        speak("System audio muted, sir.")
        return "System audio muted, sir."

    if "unmute" in clean_text:
        _run(["osascript", "-e", "set volume output muted false"])
        speak("System audio unmuted, sir.")
        return "System audio unmuted, sir."

    vol_match = re.search(r"volume(?: to)?\s*(\d{1,3})", clean_text)
    if vol_match:
        level = max(0, min(100, int(vol_match.group(1))))
        _run(["osascript", "-e", f"set volume output volume {level}"])
        speak(f"Volume set to {level} percent, sir.")
        return f"Volume set to {level} percent."

    if "volume up" in clean_text or re.search(r"\b(stop|raise|art)(?:ır)?", clean_text):
        _run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 10)"])
        speak("Turning the volume up, sir.")
        return "Volume increased by 10 percent."

    if "volume down" in clean_text or re.search(r"\b(azalt|kıs|düş)\b", clean_text):
        _run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 10)"])
        speak("Turning the volume down, sir.")
        return "Volume decreased by 10 percent."

    # --- System telemetry ---
    if any(k in clean_text for k in ["system check", "specs", "cpu", "ram", "telemetry"]):
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        msg = f"System Telemetry — CPU: {cpu}% | RAM Usage: {ram}%"
        speak(msg)
        return msg

    # --- Battery ---
    if any(k in clean_text for k in ["battery", "batarya", "şarj", "charge"]):
        out = _run(["pmset", "-g", "batt"])
        pct = re.search(r"(\d+)%", out or "")
        state = "charging" if "charging" in (out or "") else "on battery"
        msg = f"Battery at {pct.group(1)}%" if pct else "Battery info unavailable."
        speak(msg)
        return f"Battery: {pct.group(1)}%, {state}." if pct else msg

    # --- Network info ---
    if any(k in clean_text for k in ["network", "ip address", "my ip", "ip adres"]):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "unavailable"
        speak(f"Your local IP address is {ip}, sir.")
        return f"Your local IP address is {ip}."

    # --- Screenshot ---
    if "screenshot" in clean_text or "ekran görüntüsü" in clean_text or "screen shot" in clean_text:
        desktop = os.path.expanduser("~/Desktop")
        path = os.path.join(desktop, f"JARVIS_screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        _run(["screencapture", "-x", path])
        speak(f"Screenshot saved to Desktop, sir.")
        return f"Screenshot saved to {path}."

    # --- Desktop notification ---
    notif_match = re.search(r"notif(?:y|ication)?\s+(.+)$", clean_text)
    if "notify" in clean_text or "notification" in clean_text or "bildir" in clean_text:
        message = notif_match.group(1).strip() if notif_match else "Notification from JARVIS"
        _osascript(f'display notification "{message}" with title "JARVIS"')
        speak(f"Notification sent, sir.")
        return f"Notification sent: {message}"

    # --- Create a file / note ---
    note_match = re.search(r"(?:create|make|write a)?\s*(?:note|file|not)\s+(.+)$", clean_text)
    if ("create file" in clean_text or "make file" in clean_text or "write note" in clean_text or "create note" in clean_text) and note_match:
        filename = f"JARVIS_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = os.path.join(os.path.expanduser("~/Desktop"), filename)
        with open(path, "w") as f:
            f.write(note_match.group(1).strip())
        speak(f"Note saved to your Desktop, sir.")
        return f"Note saved to {path}."

    # --- Date ---
    if any(k in clean_text for k in ["todays date", "what is the date", "today's date", "tarih", "date today"]):
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        speak(f"Today is {today}, sir.")
        return f"Today is {today}."

    # --- Time ---
    if any(k in clean_text for k in ["time", "saat", "clock"]):
        now = datetime.datetime.now().strftime("%I:%M %p")
        speak(f"The current time is {now}, sir.")
        return f"The current local time is {now}."

    # --- Sleep / shut down / restart ---
    if any(k in clean_text for k in ["shut down", "shutdown", "turn off", "kapat"]):
        _run(["osascript", "-e", 'tell application "System Events" to shut down'])
        speak("Shutting down your computer.")
        return "Shutting down the computer now."

    if "restart" in clean_text or "reboot" in clean_text or "yeniden başlat" in clean_text:
        _run(["osascript", "-e", 'tell application "System Events" to restart'])
        speak("Restarting your computer.")
        return "Restarting the computer now."

    if "sleep" in clean_text or "uyku" in clean_text or "lock screen" in clean_text or "kilitle" in clean_text:
        _run(["pmset", "sleepnow"])
        speak("Putting the computer to sleep.")
        return "Putting the computer to sleep."

    return None


# ---------------------------------------------------------------------------
# Smart Response Engine
# ---------------------------------------------------------------------------

def generate_smart_response(text):
    """Generate a natural, varied response for conversational/command inputs."""
    clean_text = text.lower().strip()

    # 1) System commands take priority
    system_response = _handle_system_command(clean_text, text)
    if system_response:
        return system_response

    # 2) Conversational intents
    for intent, data in KNOWLEDGE_BASE.items():
        if any(pattern in clean_text for pattern in data["patterns"]):
            return random.choice(data["responses"])

    # 3) Generic / fallback responses
    fallbacks = [
        f"I've analyzed '{text}'. It isn't a recognized system command, but I'm logging it.",
        "Understood. I can open apps and websites, control volume, take screenshots, ",
        "show CPU/RAM/battery/network stats, send notifications, and more.",
        f"I heard: '{text}'. Try asking me for 'system check', 'open terminal', ",
        "or 'what can you do'.",
    ]
    return "".join(random.sample(fallbacks, 2))


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


@app.route("/api/ping", methods=["GET"])
def ping():
    return jsonify({"status": "success", "message": "pong"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
