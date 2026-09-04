import atexit
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import numpy as np
import socketio
import sounddevice as sd
from faster_whisper import WhisperModel
from openai import OpenAI
from pynput import keyboard

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SAMPLE_RATE = 16000
CHANNELS = 1
WHISPER_MODEL_SIZE = "base"
SILENCE_THRESHOLD = 500          # RMS amplitude below this counts as silence
MAX_RECORD_SECONDS = 30          # hard cap so we never record forever

# Desktop app backend (Flask + SocketIO) this voice engine streams into.
BACKEND_URL = os.getenv("JARVIS_BACKEND", "http://127.0.0.1:5000")

# Free brain: OpenCode Zen (same source app.py uses). No paid OpenAI key needed.
ZEN_BASE_URL = os.getenv("ZEN_BASE_URL", "https://opencode.ai/zen/v1")
ZEN_MODEL = os.getenv("ZEN_MODEL", "big-pickle")
ZEN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/124.0.0.0"
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are Virtual Butler, a professional AI assistant. Be crisp, concise, and helpful.
Call the user "sir" when appropriate.

RULES:
- PLAIN TEXT for conversation: ONE to TWO short sentences unless detail is demanded. No preamble, no fluff.
- JSON ACTION BLOCK (ONLY content, no surrounding text) when asked to DO something:
  {"action":"<name>","args":{...},"speak":"<terse confirmation>"}
- Available actions: open_app {"app_name"} · open_url {"url"} · search_web {"query"} · set_volume {"level":0-100} · shell {"command"} (shell ONLY if explicitly requested).
- "speak" must be one terse natural sentence.
- If unsure, ask ONE clarifying question.
"""