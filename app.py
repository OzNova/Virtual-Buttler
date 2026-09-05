"""JARVIS — macOS AI Assistant Backend.

Ultra-modern Flask REST backend with a typo-tolerant natural-language
intent engine and native macOS system integration.

Endpoint:
    POST /api/command   {"command": "text"}
    -> {"status": "success", "message": "JARVIS response text"}

Caching is fully disabled via after_request so the UI always reflects the
latest template/markup during development.
"""

import os
import re
import json
import random
import datetime
import difflib
import subprocess
import webbrowser
import urllib.request
import urllib.error

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Auto-reload templates from disk on every request during development.
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ---------------------------------------------------------------------------
# Gemini LLM (natural chat fallback when no system command matches)
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# NOTE: gemini-2.5-flash is decommissioned for new accounts (HTTP 404). The
# working replacement on this key is gemini-3.6-flash.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# JARVIS persona injected as context for natural, on-brand answers.
JARVIS_PERSONA = (
    "You are JARVIS, the user's personal macOS AI assistant addressed as 'sir'. "
    "Be concise, sharp, and helpful — 1 or 2 sentences max. Never claim to have "
    "performed a system action; system actions are handled by local handlers."
)


@app.after_request
def add_header(response):
    """Kill all caching so browsers/Flask never serve stale files."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# Text-to-Speech (local, optional) — pyttsx3
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

    def speak(text):  # no-op fallback
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd):
    """Run a shell command list and return stripped stdout, or None."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    except Exception:
        return None


def _osascript(script):
    """Run an AppleScript snippet via osascript."""
    return _run(["osascript", "-e", script])


def _ratio(a, b):
    """0..1 similarity between two strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _alias_hit(text, alias):
    """True if alias (or a close typo of it) appears in the text."""
    if not alias:
        return False
    if alias in text:
        return True
    # Only fuzzy-match reasonably long words to avoid false positives.
    if len(alias) < 5:
        return False
    for token in re.findall(r"[a-zçğıöşü]+", text):
        if _ratio(alias, token) >= 0.72:
            return True
    return False


def _gemini_chat(text):
    """Ask Gemini for a natural conversational reply, or None on failure."""
    if not GEMINI_API_KEY:
        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{JARVIS_PERSONA}\n\nUser: {text}\nJARVIS:"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 500,
        },
    }

    req = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text_out = (data["candidates"][0]["content"]["parts"][0].get("text") or "").strip()
        return text_out or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# App & Intent Registry
# ---------------------------------------------------------------------------

OPEN_VERBS = ("open", "launch", "start", "play", "go to", "show me", "run")
BLOCK_VERBS = ("close", "kill", "quit", "stop", "exit", "kapat")

APP_REGISTRY = {
    "youtube": {
        "kind": "web",
        "url": "https://www.youtube.com",
        "aliases": ["youtube", "yutube", "you tube", "yt"],
    },
    "terminal": {
        "kind": "app",
        "app": "Terminal",
        "aliases": ["terminal"],
    },
    "finder": {
        "kind": "app",
        "app": "Finder",
        "aliases": ["finder"],
    },
    "spotify": {
        "kind": "app",
        "app": "Spotify",
        "aliases": ["spotify", "spofity"],
    },
    "chrome": {
        "kind": "app",
        "app": "Google Chrome",
        "aliases": ["chrome", "google chrome"],
    },
}


def _detect_app(text):
    """Return the app key whose alias (or typo) matches the text, else None."""
    for key, spec in APP_REGISTRY.items():
        if any(_alias_hit(text, a) for a in spec["aliases"]):
            return key
    return None


def _open_app(key):
    """Launch/open the requested app or website."""
    spec = APP_REGISTRY[key]
    if spec["kind"] == "web":
        webbrowser.open(spec["url"])
        reply = f"Opening {key.title()} in your browser, sir."
    else:
        _run(["open", "-a", spec["app"]])
        reply = f"Launching {spec['app']}, sir."
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# System Handlers
# ---------------------------------------------------------------------------

def _system_report():
    """Live CPU / RAM / battery telemetry."""
    try:
        import psutil
    except Exception:
        return "System telemetry is momentarily unavailable, sir."
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    reply = f"System Telemetry — CPU: {cpu}% | RAM: {mem.percent}% ({mem.used // (1024 ** 3)} GB used)"
    battery = psutil.sensors_battery()
    if battery is not None:
        state = "charging" if battery.power_plugged else "on battery"
        reply += f" | Battery: {battery.percent}% ({state})"
    speak(reply)
    return reply


# ---------------------------------------------------------------------------
# Conversational Knowledge Base
# ---------------------------------------------------------------------------

CONVERSATIONAL = {
    "greetings": {
        "patterns": ["hello", "hi", "hey there", "good morning", "good afternoon", "good evening", "selam", "merhaba"],
        "responses": [
            "Hello Ozan. All systems are fully operational.",
            "At your service, sir. What shall we tackle today?",
            "Good to see you. JARVIS online and ready.",
        ],
    },
    "status": {
        "patterns": ["how are you", "how are you doing", "whats up", "status", "what's up"],
        "responses": [
            "Running at peak performance, sir.",
            "All systems are healthy and responsive.",
            "Operating smoothly. What do you need?",
        ],
    },
    "identity": {
        "patterns": ["who are you", "what are you", "your name", "what's your name", "what is your name"],
        "responses": [
            "I am JARVIS, your personal macOS AI assistant.",
            "JARVIS at your service — built to command your workspace.",
        ],
    },
    "thanks": {
        "patterns": ["thanks", "thank you", "thankyou", "ty", "teşekkür", "teşekkürler", "sağol", "sagol"],
        "responses": [
            "You're welcome, sir.",
            "Always at your service.",
            "Anytime, Ozan.",
        ],
    },
    "capabilities": {
        "patterns": ["what can you do", "help", "commands", "features", "abilities"],
        "responses": [
            "I can open apps and websites — try 'open terminal', 'open youtube' or 'open spotify' — control audio with 'mute' or 'unmute', report system telemetry with 'system check', and tell you the time or date. How can I assist, sir?",
        ],
    },
}

FALLBACK_RESPONSES = [
    "I'm not sure I caught that, sir. Try 'open terminal', 'system check', 'mute', or ask 'what can you do'.",
    "That request is outside my current command set. I can open apps, control audio, and check system status.",
    "Understood — though I don't have a handler for that yet. Try a system command like 'open spotify' or 'time'.",
]


# ---------------------------------------------------------------------------
# Smart Response Engine
# ---------------------------------------------------------------------------

def generate_smart_response(text):
    """Route user input through the typo-tolerant intent engine."""
    clean = (text or "").lower().strip()
    if not clean:
        return "I didn't catch that, sir. How may I help you?"

    # ── Open app / website (typo-tolerant) ──────────────────────────────
    app_key = _detect_app(clean)
    if app_key:
        wants_open = any(v in clean for v in OPEN_VERBS)
        is_blocked = any(v in clean for v in BLOCK_VERBS)
        # Open when explicitly asked, or when the app name stands alone.
        if wants_open or (not is_blocked and len(clean.split()) <= 2):
            return _open_app(app_key)

    # ── Audio control (unmute must be checked before mute) ──────────────
    if "unmute" in clean or "sesi aç" in clean or "sound on" in clean:
        _osascript("set volume output muted false")
        reply = "Audio unmuted, sir."
        speak(reply)
        return reply
    if "mute" in clean or "sesi kapat" in clean or "sound off" in clean:
        _osascript("set volume output muted true")
        reply = "Audio muted, sir."
        speak(reply)
        return reply

    # ── System telemetry ────────────────────────────────────────────────
    if any(k in clean for k in ["system check", "check system", "telemetry", "specs",
                                "cpu", "ram", "memory", "battery", "batarya"]):
        return _system_report()

    # ── Time & date ─────────────────────────────────────────────────────
    if re.search(r"\b(time|saat|clock)\b", clean):
        now = datetime.datetime.now().strftime("%I:%M %p")
        reply = f"The local time is {now}, sir."
        speak(reply)
        return reply
    if re.search(r"\b(date|tarih)\b", clean) or "today's date" in clean or "todays date" in clean:
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        reply = f"Today is {today}, sir."
        speak(reply)
        return reply

    # ── Natural chat via Gemini (when no system command matches) ────────
    llm_reply = _gemini_chat(text)
    if llm_reply:
        speak(llm_reply)
        return llm_reply

    # ── Local conversational intents (Gemini unavailable fallback) ──────
    for intent, data in CONVERSATIONAL.items():
        if any(re.search(r"\b" + re.escape(p) + r"\b", clean) for p in data["patterns"]):
            return random.choice(data["responses"])

    # ── Polished fallback (never a raw echo) ────────────────────────────
    return random.choice(FALLBACK_RESPONSES)


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/command", methods=["POST"])
def handle_command():
    """Accept {"command": "text"} and return {"status": "success", "message": "..."}."""
    data = request.get_json(silent=True) or {}
    raw_cmd = (data.get("command") or "").strip()

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