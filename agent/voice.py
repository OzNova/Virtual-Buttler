"""Voice pipeline abstractions (Phase 3). Stdlib-only, optional providers.

Defaults (no keys, local-only):
- TTS: macOS `say` (via server speak) + browser speechSynthesis (frontend).
- STT: browser Web Speech API (frontend mic). Backend /api/stt only active
  when a provider key is set (Groq/Deepgram), else 501 with hint.
- VAD: energy-based fallback (pure stdlib) + Silero stub (lazy torch import).
- Ducking: lower system volume on speak.start, restore on speak.stop.

Env:
  BUTLER_TTS=mute|say|elevenlabs|openai (default say)
  BUTLER_STT=off|groq|deepgram (default off)
  ELEVENLABS_API_KEY, ELEVENLABS_VOICE, OPENAI_API_KEY, OPENAI_TTS_VOICE,
  GROQ_API_KEY, DEEPGRAM_API_KEY, BUTLER_DUCKING=1|0, BUTLER_DUCK_LEVEL (0-50, default 25)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import struct
import subprocess
import urllib.request

logger = logging.getLogger("butler-agent.voice")


def tts_mode() -> str:
    return (os.getenv("BUTLER_TTS", "say") or "say").lower().strip()


def stt_mode() -> str:
    return (os.getenv("BUTLER_STT", "off") or "off").lower().strip()


def ducking_enabled() -> bool:
    return (os.getenv("BUTLER_DUCKING", "1") or "1").strip() not in ("0", "false", "no", "off")


def duck_level() -> int:
    try:
        return max(0, min(50, int(os.getenv("BUTLER_DUCK_LEVEL", "25"))))
    except ValueError:
        return 25


def voice_status() -> dict:
    return {
        "tts": tts_mode(),
        "stt": stt_mode(),
        "vad": "energy" if os.getenv("BUTLER_VAD", "energy") == "energy" else os.getenv("BUTLER_VAD"),
        "ducking": ducking_enabled(),
        "keys_set": {
            "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "deepgram": bool(os.getenv("DEEPGRAM_API_KEY")),
        },
    }


# ── VAD ──

def energy_vad(pcm16: bytes, sample_rate: int = 16000, threshold: int = 500) -> bool:
    """True if PCM16 mono bytes contain speech-like energy (stdlib only)."""
    n = len(pcm16 or b"") // 2
    if n <= 0:
        return False
    try:
        samples = struct.unpack(f"<{n}h", pcm16[: n * 2])
    except struct.error:
        return False
    rms = (sum(s * s for s in samples) / n) ** 0.5
    return rms >= threshold


def silero_vad(pcm16: bytes, sample_rate: int = 16000) -> bool | None:
    """Try Silero (lazy torch); return None when unavailable -> caller falls back."""
    try:
        import torch  # type: ignore
    except ImportError:
        return None
    try:
        model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=False)
        (get_speech_timestamps, _, _, _, _) = utils
        import numpy as np  # type: ignore
        audio = np.frombuffer(pcm16, dtype=np.int16).astype("float32") / 32768.0
        stamps = get_speech_timestamps(torch.from_numpy(audio), model, sampling_rate=sample_rate)
        return bool(stamps)
    except Exception:
        logger.debug("silero VAD failed", exc_info=True)
        return None


def vad_speech(pcm16: bytes, sample_rate: int = 16000, threshold: int = 500) -> bool:
    if os.getenv("BUTLER_VAD", "energy") == "silero":
        res = silero_vad(pcm16, sample_rate)
        if res is not None:
            return res
    return energy_vad(pcm16, sample_rate, threshold)


def make_pcm16_sine(freq: float = 440.0, seconds: float = 0.1,
                    sample_rate: int = 16000, amplitude: int = 8000) -> bytes:
    import math
    n = int(sample_rate * seconds)
    return struct.pack(f"<{n}h", *[int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
                                   for i in range(n)])


# ── TTS providers (REST via urllib; default say handled by server) ──

def _post_bytes(url: str, body: bytes, headers: dict, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def elevenlabs_synthesize(text: str) -> tuple[bytes, str]:
    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    voice = os.getenv("ELEVENLABS_VOICE", "21m00Tcm4TlvDq8ikWAM")
    body = json.dumps({"text": text[:1000], "model_id": "eleven_turbo_v2",
                       "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode()
    audio = _post_bytes(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                        body, {"xi-api-key": key, "Content-Type": "application/json",
                               "Accept": "audio/mpeg"})
    return audio, "audio/mpeg"


def openai_synthesize(text: str) -> tuple[bytes, str]:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    voice = os.getenv("OPENAI_TTS_VOICE", "alloy")
    body = json.dumps({"model": "tts-1", "input": text[:1000], "voice": voice}).encode()
    audio = _post_bytes("https://api.openai.com/v1/audio/speech", body,
                        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return audio, "audio/mpeg"


def synthesize(text: str) -> dict:
    """Synthesize via BUTLER_TTS. Returns {audio_b64, mime} or raises."""
    m = tts_mode()
    if m == "elevenlabs":
        audio, mime = elevenlabs_synthesize(text)
    elif m == "openai":
        audio, mime = openai_synthesize(text)
    else:
        raise RuntimeError(f"TTS mode {m!r} is local (use macOS say / browser speech)")
    return {"audio_b64": base64.b64encode(audio).decode(), "mime": mime}


# ── STT providers ──

def _decode_audio_b64(audio_b64: str) -> bytes:
    try:
        return base64.b64decode(audio_b64, validate=True)
    except Exception:
        raise ValueError("invalid audio_b64")


def groq_transcribe(audio: bytes, mime: str = "audio/wav") -> str:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    boundary = "----butler1234"
    fname = "audio." + ("mp3" if "mp3" in mime else "wav")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-large-v3\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n".encode() + audio + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(p if isinstance(p, bytes) else p.encode() for p in parts)
    req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode()).get("text", "").strip()


def deepgram_transcribe(audio: bytes, mime: str = "audio/wav") -> str:
    key = os.getenv("DEEPGRAM_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY not set")
    req = urllib.request.Request("https://api.deepgram.com/v1/listen?model=nova-2", data=audio,
                                 headers={"Authorization": f"Token {key}", "Content-Type": mime},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    try:
        return data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


def transcribe(audio_b64: str, mime: str = "audio/wav") -> str:
    m = stt_mode()
    audio = _decode_audio_b64(audio_b64)
    if not audio:
        raise ValueError("empty audio")
    if m == "groq":
        return groq_transcribe(audio, mime)
    if m == "deepgram":
        return deepgram_transcribe(audio, mime)
    raise RuntimeError(f"STT mode {m!r} is off (use browser Web Speech mic)")


# ── Ducking: lower system volume while speaking, restore after ──

class DuckingController:
    """Subscribe to BUS speak.start/stop; dip macOS output volume briefly."""

    def __init__(self, run=None):
        self._run = run or (lambda cmd: subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=5).stdout.strip())
        self._saved: int | None = None
        self._lock_holder = None
        try:
            import threading
            self._lock_holder = threading.Lock()
        except ImportError:
            pass

    def _get(self) -> int | None:
        try:
            out = self._run(["osascript", "-e", "output volume of (get volume settings)"])
            return max(0, min(100, int(str(out).strip())))
        except Exception:
            return None

    def _set(self, level: int) -> None:
        try:
            self._run(["osascript", "-e", f"set volume output volume {max(0, min(100, int(level)))}"])
        except Exception:
            pass

    def on_start(self, _payload: dict | None = None) -> None:
        if not ducking_enabled():
            return
        cur = self._get()
        if cur is None:
            return
        self._saved = cur
        dip = max(0, cur - duck_level())
        if dip < cur:
            self._set(dip)

    def on_stop(self, _payload: dict | None = None) -> None:
        if not ducking_enabled() or self._saved is None:
            return
        self._set(self._saved)
        self._saved = None

    def attach(self, bus) -> "DuckingController":
        bus.on("speak.start", self.on_start)
        bus.on("speak.stop", self.on_stop)
        return self
