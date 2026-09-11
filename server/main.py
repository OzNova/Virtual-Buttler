"""Butler FastAPI sidecar — Phase 1 agent seam (local-only, no auth).

Runs alongside legacy Flask app.py (:5000). This server on 127.0.0.1:8000:
- mirrors the compat REST surface (/api/*) so the Apple UI works unchanged
  (point it at :8000 or keep :5000; both answer),
- adds agent-native surface: /api/tools, /api/agent, /api/widgets, WS /ws/chat,
- executes ToolCalls from agent/router.py (decision vs execution split).

Run:  pip install -r requirements-agent.txt && python -m server.main
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import pathlib
import subprocess
import threading
import webbrowser

logger = logging.getLogger("butler-agent")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - import error surfaces at runtime with hint
    raise SystemExit("Missing agent deps. Run: pip install -r requirements-agent.txt")

from agent.decide import decide
from agent.events import BUS
from agent.voice import DuckingController, synthesize, transcribe, voice_status
from agent.llm import gemini_model, mode, ollama_base, ollama_model
from agent.memory import LongMemory, ShortMemory
from agent.router import route
from agent.tools import build_shopping_url, clamp_volume, is_blocked_terminal, list_schemas, sanitize_filename

TTS_VOICE = os.getenv("TTS_VOICE", "Daniel")
MAX_COMMAND_CHARS = 1000
SPEAK_MAX = 400

VOICE_MUTED = {"muted": False}
_VOICE_LOCK = threading.Lock()
SHORT = ShortMemory(max_turns=6)
LONG = LongMemory(path=os.getenv("BUTLER_MEMORY", "data/memory.jsonl"))


class CommandIn(BaseModel):
    command: str


class AgentIn(BaseModel):
    message: str


def speak(text: str) -> None:
    with _VOICE_LOCK:
        muted = VOICE_MUTED["muted"]
    if not text or muted:
        return
    BUS.emit("speak.start", {"chars": len(text)})
    try:
        subprocess.Popen(["say", "-v", TTS_VOICE, (text or "")[:SPEAK_MAX]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        logger.debug("speak failed", exc_info=True)
    finally:
        BUS.emit("speak.stop", {})


def _run(cmd: list, timeout: int = 5) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False,
                              timeout=timeout).stdout.strip()
    except Exception:
        return None


def _osascript(script: str):
    return _run(["osascript", "-e", script])


def gather_telemetry() -> dict:
    info = {
        "cpu": 0, "ram_percent": 0, "ram_used_gb": 0, "ram_total_gb": 0,
        "battery_percent": None, "battery_charging": None,
        "time": datetime.datetime.now().strftime("%I:%M %p"),
        "date": datetime.datetime.now().strftime("%A, %B %d, %Y"),
        "gemini_ready": bool(os.getenv("GEMINI_API_KEY")),
    }
    try:
        import psutil
        info["cpu"] = round(psutil.cpu_percent(interval=None) or 0, 1)
        vm = psutil.virtual_memory()
        info["ram_percent"] = round(vm.percent, 1)
        info["ram_used_gb"] = round(vm.used / (1024 ** 3), 1)
        info["ram_total_gb"] = round(vm.total / (1024 ** 3), 1)
        bat = psutil.sensors_battery()
        if bat is not None:
            info["battery_percent"] = round(bat.percent, 0)
            info["battery_charging"] = bool(bat.power_plugged)
    except Exception:
        pass
    return info


def execute(call_name: str, args: dict, raw: str) -> dict:
    """Execute a ToolCall, speak, remember. Returns {message, widget}."""
    decision_speak = None
    widget = None
    # Re-route to keep single source of truth for speak/widget text,
    # but execute here (router itself is side-effect free).
    d = route(raw)
    decision_speak, widget = d.speak, d.widget
    name, a = call_name, args or {}

    if name == "system.telemetry":
        t = gather_telemetry()
        msg = (f"CPU {t['cpu']}% | RAM {t['ram_percent']}% "
               f"({t['ram_used_gb']} of {t['ram_total_gb']} GB used), sir.")
        if t["battery_percent"] is not None:
            msg += f" Battery {t['battery_percent']}%."
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        LONG.remember(raw, msg)
        return {"message": msg, "widget": {"kind": "telemetry", "telemetry": t}}

    if name == "system.time":
        now = datetime.datetime.now()
        msg = (f"The local time is {now.strftime('%I:%M %p')}, sir."
               if a.get("which", "time") == "time"
               else f"Today is {now.strftime('%A, %B %d, %Y')}, sir.")
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": widget}

    if name == "system.volume":
        level = clamp_volume(a.get("level", 50))
        _osascript(f"set volume output volume {level}")
        msg = f"Volume set to {level} percent, sir."
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": widget}

    if name == "system.mute":
        _osascript("set volume output muted true" if a.get("muted") else "set volume output muted false")
        msg = "Audio muted, sir." if a.get("muted") else "Audio unmuted, sir."
        speak(msg)
        return {"message": msg, "widget": widget}

    if name == "media.spotify":
        action = a.get("action", "playpause")
        scripts = {"next": 'tell application "Spotify" to next track',
                   "previous": 'tell application "Spotify" to previous track',
                   "playpause": 'tell application "Spotify" to playpause'}
        _osascript(scripts.get(action, scripts["playpause"]))
        labels = {"next": "Playing the next track, sir.",
                  "previous": "Previous track, sir.",
                  "playpause": "Toggling the music, sir."}
        msg = labels.get(action, labels["playpause"])
        speak(msg)
        return {"message": msg, "widget": widget}

    if name == "apps.open":
        target = a.get("target", "")
        if target == "youtube":
            webbrowser.open("https://www.youtube.com")
            msg = "Opening YouTube in your browser, sir."
        else:
            apps = {"terminal": "Terminal", "finder": "Finder",
                    "spotify": "Spotify", "chrome": "Google Chrome"}
            try:
                subprocess.Popen(["open", "-a", apps.get(target, target)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            msg = f"Launching {apps.get(target, target)}, sir."
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": widget}

    if name == "folders.open":
        paths = {"downloads": "~/Downloads", "desktop": "~/Desktop", "documents": "~/Documents",
                 "pictures": "~/Pictures", "music": "~/Music", "movies": "~/Movies",
                 "applications": "/Applications", "home": "~"}
        p = os.path.expanduser(paths.get(a.get("name", ""), "~"))
        os.makedirs(p, exist_ok=True)
        try:
            subprocess.Popen(["open", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        msg = f"Opening {a.get('name')} for you, sir."
        speak(msg)
        return {"message": msg, "widget": widget}

    if name == "files.create":
        safe = sanitize_filename(a.get("name", ""))
        if not safe:
            msg = "I can't create that name — please use a simple folder or file name, sir."
            speak(msg)
            return {"message": msg, "widget": widget}
        desktop = pathlib.Path(os.path.expanduser("~/Desktop")).resolve()
        path = (desktop / safe).resolve()
        try:
            path.relative_to(desktop)
        except ValueError:
            msg = "I can't create that name — please use a simple folder or file name, sir."
            speak(msg)
            return {"message": msg, "widget": widget}
        try:
            if a.get("kind") == "file":
                if path.exists():
                    msg = f"'{safe}' already exists on your desktop, sir."
                else:
                    path.write_text("", encoding="utf-8")
                    msg = f"Created the file '{safe}' on your desktop, sir."
            else:
                path.mkdir(parents=False, exist_ok=False)
                msg = f"Created the folder '{safe}' on your desktop, sir."
        except FileExistsError:
            msg = f"'{safe}' already exists on your desktop, sir."
        except Exception:
            msg = "I couldn't create that, sir."
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": widget}

    if name == "web.open_domain":
        domain = a.get("domain", "")
        webbrowser.open("https://" + domain)
        msg = f"Opening {domain}, sir."
        speak(msg)
        return {"message": msg, "widget": widget}

    if name == "web.search":
        from agent.tools import build_search_url
        q, v = a.get("query", raw), a.get("vertical", "web")
        webbrowser.open(build_search_url(q, v))
        msg = decision_speak
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": widget or {"kind": v, "query": q}}

    if name == "shop.search":
        url = build_shopping_url(a.get("platform", "google shopping"), a.get("query", ""))
        webbrowser.open(url)
        msg = decision_speak
        speak(msg)
        return {"message": msg, "widget": {"kind": "shopping", "platform": a.get("platform"),
                                           "query": a.get("query"), "url": url}}

    if name == "terminal.run":
        cmd = (a.get("command") or "")[:200]
        if not cmd or is_blocked_terminal(cmd):
            msg = "I can't run that destructive command, sir."
            speak(msg)
            return {"message": msg, "widget": widget}
        safe = cmd.replace("\\", "\\\\").replace('"', '\\"')
        try:
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{safe}"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        msg = f"Executed '{cmd}' in Terminal, sir."
        speak(msg)
        return {"message": msg, "widget": widget}

    if name == "memory.recall":
        from agent.memory import LongMemory
        hits = LONG.recall(a.get("query", raw), limit=3)
        if not hits:
            msg = "I don't have notes on that yet, sir."
        else:
            top = hits[0]
            msg = f"From my notes: you asked '{top.get('user', '')[:120]}' — I replied '{top.get('assistant', '')[:160]}', sir."
        speak(msg)
        return {"message": msg, "widget": {"kind": "memory", "hits": len(hits)}}

    if name == "docs.search":
        from agent.knowledge import search_docs
        hits = search_docs(a.get("query", raw), limit=3)
        if not hits:
            msg = "No matching documents. Set BUTLER_DOC_PATHS to index a folder, sir."
        else:
            msg = f"Top match: {hits[0]['path']} — {hits[0]['snippet'][:200]}, sir."
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": {"kind": "docs", "hits": hits}}

    if name == "docs.summarize":
        from agent.knowledge import summarize_doc
        res = summarize_doc(a.get("query", raw))
        if not res:
            msg = "No matching documents. Set BUTLER_DOC_PATHS to index a folder, sir."
            speak(msg)
            return {"message": msg, "widget": {"kind": "docs"}}
        msg = f"Summary of {res['path']}: {res['summary']}, sir."
        speak(msg)
        SHORT.add("user", raw)
        SHORT.add("jarvis", msg)
        return {"message": msg, "widget": {"kind": "docs", "path": res["path"]}}

    if name == "vision.capture":
        from agent.vision import capture_screen, describe_image
        cap = capture_screen()
        if not cap.get("ok"):
            msg = "I couldn't capture the screen, sir."
            speak(msg)
            return {"message": msg, "widget": {"kind": "vision"}}
        desc = describe_image(cap["path"], (a.get("question") or raw)[:300])
        if desc.get("ok"):
            msg = f"On screen: {desc['text'][:400]}, sir."
        else:
            msg = f"Screenshot saved to {cap['path']}. {desc.get('hint', '')} sir.".strip()
        speak(msg)
        return {"message": msg, "widget": {"kind": "vision", "path": cap["path"]}}

    if name == "calendar.next":
        from agent.focus import upcoming
        data = upcoming()
        if not data.get("ok"):
            msg = f"No calendar source. {data.get('hint', '')} sir."
            speak(msg)
            return {"message": msg, "widget": {"kind": "calendar"}}
        evs = data.get("events", [])[:3]
        msg = ("Up next: " + "; ".join(e.get("title", "") for e in evs) + ", sir.") if evs else "Nothing upcoming, sir."
        speak(msg)
        return {"message": msg, "widget": {"kind": "calendar", "events": evs}}

    if name == "focus.check":
        from agent.focus import focus_check
        res = focus_check()
        msg = res.get("suggestion") or "No focus block starting soon, sir."
        if not res.get("suggest"):
            msg = "No focus block starting soon, sir."
        speak(msg)
        return {"message": msg, "widget": {"kind": "focus", "suggest": res.get("suggest", False)}}

    if name == "home.state":
        from agent.home import get_state
        res = get_state(a.get("entity_id", ""))
        if not res.get("ok"):
            msg = f"Smart home unavailable. {res.get('hint', res.get('error', ''))} sir.".strip()
        else:
            msg = f"{a.get('entity_id')} is {res.get('state')}, sir."
        speak(msg)
        return {"message": msg, "widget": {"kind": "home"}}

    if name == "home.call":
        from agent.home import call_service
        res = call_service(a.get("domain", ""), a.get("service", ""),
                           {"entity_id": a.get("entity_id")} if a.get("entity_id") else {})
        if not res.get("ok"):
            msg = f"Smart home unavailable. {res.get('hint', res.get('error', ''))} sir.".strip()
        else:
            msg = "Done, sir."
        speak(msg)
        return {"message": msg, "widget": {"kind": "home"}}

    # chat.reply + unknown: deterministic Phase 1 (LLM plugs in Phase 2)
    msg = decision_speak or "Understood, sir."
    speak(msg)
    SHORT.add("user", raw)
    SHORT.add("jarvis", msg)
    LONG.remember(raw, msg)
    return {"message": msg, "widget": widget}


app = FastAPI(title="Butler Agent", version="0.2.0")

_DUCKING_ATTACHED = False


def _ensure_ducking() -> None:
    global _DUCKING_ATTACHED
    if _DUCKING_ATTACHED:
        return
    try:
        DuckingController().attach(BUS)
        _DUCKING_ATTACHED = True
    except Exception:
        pass


_ensure_ducking()


@app.get("/")
def index():
    tpl = pathlib.Path(__file__).resolve().parent.parent / "templates" / "index.html"
    if tpl.exists():
        return FileResponse(str(tpl))
    return {"service": "butler-agent", "ui": "http://127.0.0.1:5000"}


@app.get("/api/ping")
def ping():
    return {"status": "success", "message": "pong"}


@app.get("/api/telemetry")
def telemetry():
    return {"status": "success", "telemetry": gather_telemetry()}


@app.get("/api/voice-mute")
def voice_mute_get():
    with _VOICE_LOCK:
        m = VOICE_MUTED["muted"]
    return {"status": "success", "muted": m}


@app.post("/api/voice-mute")
def voice_mute_post(payload: dict | None = None):
    with _VOICE_LOCK:
        if isinstance((payload or {}).get("muted"), bool):
            VOICE_MUTED["muted"] = payload["muted"]
        else:
            VOICE_MUTED["muted"] = not VOICE_MUTED["muted"]
        m = VOICE_MUTED["muted"]
    return {"status": "success", "muted": m}


@app.post("/api/media")
def media(payload: dict):
    action = (payload or {}).get("action", "")
    if action not in ("playpause", "next", "previous"):
        return JSONResponse({"status": "error", "message": "Unsupported media action."}, status_code=400)
    out = execute("media.spotify", {"action": action}, f"media {action}")
    return {"status": "success", "message": out["message"]}


@app.post("/api/broadcast")
def broadcast(payload: dict):
    text = ((payload or {}).get("text") or "").strip()
    if text:
        speak(text)
    return {"status": "success", "message": "Broadcast sent."}


@app.post("/api/command")
def command(payload: CommandIn):
    raw = (payload.command or "").strip()
    if not raw:
        return JSONResponse({"status": "error", "message": "Empty command"}, status_code=400)
    if len(raw) > MAX_COMMAND_CHARS:
        return JSONResponse({"status": "error", "message": "Command too long"}, status_code=400)
    d = route(raw)
    out = execute(d.call.name, d.call.args, raw)
    return {"status": "success", "message": out["message"], "tool": d.call.to_dict(),
            "widget": out.get("widget")}


@app.get("/api/tools")
def tools():
    return {"status": "success", "tools": list_schemas()}


@app.post("/api/agent")
def agent_run(payload: AgentIn):
    raw = (payload.message or "").strip()
    if not raw:
        return JSONResponse({"status": "error", "message": "Empty message"}, status_code=400)
    if len(raw) > MAX_COMMAND_CHARS:
        return JSONResponse({"status": "error", "message": "Message too long"}, status_code=400)
    d = decide(raw, SHORT.snapshot())
    out = execute(d.call.name, d.call.args, raw)
    return {"status": "success", "call": d.call.to_dict(), "message": out["message"],
            "widget": out.get("widget"), "llm": mode()}


@app.get("/api/agent/status")
def agent_status():
    return {"status": "success", "llm": mode(), "ollama_base": ollama_base(),
            "ollama_model": ollama_model(), "gemini_model": gemini_model(),
            "gemini_key_set": bool(os.getenv("GEMINI_API_KEY"))}


@app.post("/api/agent/stream")
def agent_stream(payload: AgentIn):
    raw = (payload.message or "").strip()
    if not raw:
        return JSONResponse({"status": "error", "message": "Empty message"}, status_code=400)

    def gen():
        d = decide(raw, SHORT.snapshot())
        words = (d.speak or "").split() or ["Understood, sir."]
        for i in range(0, len(words), 4):
            yield f"event: token\ndata: {' '.join(words[i:i + 4])}\n\n"
        out = execute(d.call.name, d.call.args, raw)
        yield ("event: result\ndata: " + __import__("json").dumps(
            {"message": out["message"], "tool": d.call.to_dict(),
             "widget": out.get("widget"), "llm": mode()}) + "\n\n")

    return StreamingResponse(gen(), media_type="text/event-stream")


class TTSIn(BaseModel):
    text: str
    voice: str | None = None


class STTIn(BaseModel):
    audio_b64: str
    mime: str = "audio/wav"


@app.get("/api/voice/status")
def voice_status_ep():
    _ensure_ducking()
    return {"status": "success", **voice_status()}


@app.post("/api/tts")
def tts_ep(payload: TTSIn):
    text = (payload.text or "").strip()
    if not text:
        return JSONResponse({"status": "error", "message": "Empty text"}, status_code=400)
    try:
        out = synthesize(text)
    except RuntimeError as e:
        return {"status": "local", "message": str(e),
                "hint": "Default TTS is macOS say + browser speechSynthesis (no key needed)."}
    except Exception:
        logger.debug("TTS failed", exc_info=True)
        return JSONResponse({"status": "error", "message": "TTS failed"}, status_code=502)
    return {"status": "success", **out}


@app.post("/api/stt")
def stt_ep(payload: STTIn):
    if not (payload.audio_b64 or "").strip():
        return JSONResponse({"status": "error", "message": "Empty audio"}, status_code=400)
    try:
        text = transcribe(payload.audio_b64, payload.mime or "audio/wav")
    except RuntimeError as e:
        return JSONResponse({"status": "error", "message": str(e),
                             "hint": "Default STT is the browser Web Speech mic (no key needed)."},
                            status_code=501)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception:
        logger.debug("STT failed", exc_info=True)
        return JSONResponse({"status": "error", "message": "STT failed"}, status_code=502)
    return {"status": "success", "transcript": text}


class RecallIn(BaseModel):
    query: str


class DocsIn(BaseModel):
    query: str


class VisionIn(BaseModel):
    question: str = "What is on screen?"


class HomeStateIn(BaseModel):
    entity_id: str


class HomeCallIn(BaseModel):
    domain: str
    service: str
    entity_id: str | None = None


@app.post("/api/memory/recall")
def memory_recall(payload: RecallIn):
    out = execute("memory.recall", {"query": payload.query}, payload.query)
    return {"status": "success", **out}


@app.post("/api/docs/search")
def docs_search(payload: DocsIn):
    out = execute("docs.search", {"query": payload.query}, payload.query)
    return {"status": "success", **out}


@app.post("/api/docs/summarize")
def docs_summarize(payload: DocsIn):
    out = execute("docs.summarize", {"query": payload.query}, payload.query)
    return {"status": "success", **out}


@app.post("/api/vision/capture")
def vision_capture(payload: VisionIn):
    out = execute("vision.capture", {"question": payload.question}, payload.question)
    return {"status": "success", **out}


@app.get("/api/calendar/next")
def calendar_next():
    out = execute("calendar.next", {}, "what is next on my calendar?")
    return {"status": "success", **out}


@app.get("/api/focus")
def focus_ep():
    out = execute("focus.check", {}, "should I focus now?")
    return {"status": "success", **out}


@app.post("/api/home/state")
def home_state(payload: HomeStateIn):
    out = execute("home.state", {"entity_id": payload.entity_id}, f"is {payload.entity_id} on?")
    return {"status": "success", **out}


@app.post("/api/home/call")
def home_call(payload: HomeCallIn):
    args = {"domain": payload.domain, "service": payload.service}
    if payload.entity_id:
        args["entity_id"] = payload.entity_id
    out = execute("home.call", args, f"{payload.service} {payload.entity_id or ''}")
    return {"status": "success", **out}


@app.get("/api/widgets")
def widgets(kind: str = "telemetry"):
    """Stub for Phase 5 HUD cards. Returns data the Next.js HUD will render."""
    if kind == "telemetry":
        return {"status": "success", "widget": {"kind": "telemetry", "telemetry": gather_telemetry()}}
    return {"status": "success", "widget": {"kind": kind}}


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()
            raw = ((data or {}).get("command") or (data or {}).get("message") or "").strip()
            if not raw:
                await ws.send_json({"type": "error", "message": "Empty command"})
                continue
            d = decide(raw, SHORT.snapshot())
            # Phase 2: LLM text streams as word chunks; true token streaming later
            words = d.speak.split()
            for i in range(0, len(words), 4):
                await ws.send_json({"type": "token", "text": " ".join(words[i:i + 4])})
                await asyncio.sleep(0.02)
            out = execute(d.call.name, d.call.args, raw)
            await ws.send_json({"type": "result", "message": out["message"],
                                "tool": d.call.to_dict(), "widget": out.get("widget")})
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("AGENT_PORT", "8000"))
    # Local-only, no auth (operator requirement).
    uvicorn.run("server.main:app", host="127.0.0.1", port=port, log_level="info")
