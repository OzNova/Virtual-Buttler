"""Vision: local screenshot capture + optional vision-LLM describe.

Capture is local-only (macOS `screencapture`). Describe needs a vision key:
- Gemini (GEMINI_API_KEY): generateContent with inline_data image.
- Else: returns {hint} so callers degrade gracefully (no crash, no key needed).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
import urllib.request

logger = logging.getLogger("butler-agent.vision")


def capture_screen(path: str | None = None) -> dict:
    dest = path or os.path.join(tempfile.gettempdir(), "butler_screen.png")
    try:
        subprocess.run(["screencapture", "-x", dest], check=False, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return {"ok": False, "error": "screenshot failed (macOS screencapture unavailable?)"}
    if not os.path.exists(dest):
        return {"ok": False, "error": "screenshot produced no file"}
    try:
        size = os.path.getsize(dest)
    except OSError:
        size = -1
    return {"ok": True, "path": dest, "bytes": size}


def describe_image(image_path: str, question: str = "What is on screen?") -> dict:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return {"ok": False, "hint": "Set GEMINI_API_KEY for vision describe; capture only for now."}
    try:
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
    except OSError:
        return {"ok": False, "error": "cannot read image"}
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    payload = {"contents": [{"parts": [
        {"text": question},
        {"inline_data": {"mime_type": "image/png", "data": b64}}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        text = data["candidates"][0]["content"]["parts"][0].get("text", "").strip()
        return {"ok": True, "text": text}
    except Exception:
        logger.debug("vision describe failed", exc_info=True)
        return {"ok": False, "error": "vision request failed"}
