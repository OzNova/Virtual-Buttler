"""Deterministic router: text -> ToolCall (Phase 1).

Mirrors the intent coverage of app.py but returns a structured call
instead of executing. Server/main.py executes; a future LLM caller can
produce the same ToolCall shape.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .tools import ToolCall, build_search_url, is_blocked_terminal, sanitize_filename


@dataclass(frozen=True)
class AgentDecision:
    call: ToolCall
    speak: str
    widget: Optional[dict] = None  # future HUD card, e.g. {"kind": "telemetry"}


def route(text: str) -> AgentDecision:
    raw = (text or "").strip()
    clean = raw.lower().strip()
    if not clean:
        return AgentDecision(ToolCall("chat.reply", {"text": ""}), "I didn't catch that, sir.")

    # System telemetry / time
    if re.search(r"\b(system check|check system|telemetry|specs|\bcpu\b|\bram\b|memory|battery)\b", clean):
        return AgentDecision(ToolCall("system.telemetry", {}), "On it, sir.",
                             widget={"kind": "telemetry"})
    if re.search(r"\btime\b|\bclock\b", clean):
        return AgentDecision(ToolCall("system.time", {"which": "time"}), "On it, sir.")
    if re.search(r"\bdate\b|today's date|todays date", clean):
        return AgentDecision(ToolCall("system.time", {"which": "date"}), "On it, sir.")

    # Mute (before volume numbers)
    if re.search(r"\bunmute\b|sound on|sesi a", clean):
        return AgentDecision(ToolCall("system.mute", {"muted": False}), "Audio unmuted, sir.")
    if re.search(r"\bmute\b|sound off|sesi kapat", clean):
        return AgentDecision(ToolCall("system.mute", {"muted": True}), "Audio muted, sir.")

    # Volume
    if re.search(r"\bvolume\b|ses|sesi|sound", clean):
        m = re.search(r"(\d{1,3})", clean)
        level = int(m.group(1)) if m else 50
        level = max(0, min(100, level))
        return AgentDecision(ToolCall("system.volume", {"level": level}),
                             f"Volume set to {level} percent, sir.")

    # Spotify
    if re.search(r"\bnext\b.*\b(song|track)\b|next song|next track", clean):
        return AgentDecision(ToolCall("media.spotify", {"action": "next"}), "Playing the next track, sir.")
    if re.search(r"\bprevious\b.*\b(song|track)\b|previous song", clean):
        return AgentDecision(ToolCall("media.spotify", {"action": "previous"}), "Previous track, sir.")
    if "pause music" in clean or clean.strip() == "pause" or "stop music" in clean:
        return AgentDecision(ToolCall("media.spotify", {"action": "playpause"}), "Toggling the music, sir.")
    if any(k in clean for k in ("resume music", "play music", "unpause", "resume")):
        return AgentDecision(ToolCall("media.spotify", {"action": "playpause"}), "Toggling the music, sir.")

    # Terminal (guarded; execution layer re-checks blocklist)
    if "terminal" in clean:
        m = re.search(r"\brun\b\s+(.+?)\s+\bin\b\s+(?:the\s+)?terminal\b", clean)
        m2 = re.search(r"\bin\b\s+(?:the\s+)?terminal\b\s*[,:]?\s*(?:run\s+)?(.+?)\s*$", clean)
        cmd = (m.group(1).strip() if m else (m2.group(1).strip() if m2 else ""))
        if cmd and len(cmd) <= 200 and not is_blocked_terminal(cmd):
            return AgentDecision(ToolCall("terminal.run", {"command": cmd}),
                                 f"Executed '{cmd}' in Terminal, sir.")

    # Known apps
    for target in ("youtube", "terminal", "finder", "spotify", "chrome"):
        if re.search(r"\b" + re.escape(target) + r"\b", clean) and re.search(
                r"\b(open|launch|start|show|run|go to)\b", clean):
            return AgentDecision(ToolCall("apps.open", {"target": target}),
                                 f"Opening {target.title()}, sir.")

    # Folders
    for name in ("downloads", "desktop", "documents", "pictures", "music", "movies", "applications", "home"):
        if name in clean and re.search(r"\b(open|launch|show)\b", clean):
            return AgentDecision(ToolCall("folders.open", {"name": name}),
                                 f"Opening {name} for you, sir.")

    # Create file/folder (preserve case from raw)
    m = re.search(
        r"(?:create|make|mkdir)\s+(?:a |new )?(folder|directory|file)"
        r"(?:\s+(?:named|called))?\s+[\"'`]?([^\"'`]+?)[\"'`]?\s*$",
        raw, flags=re.IGNORECASE)
    if m:
        kind = "folder" if m.group(1).lower() in ("folder", "directory") else "file"
        safe = sanitize_filename(m.group(2))
        if safe:
            return AgentDecision(ToolCall("files.create", {"kind": kind, "name": safe}),
                                 f"Created the {kind} '{safe}' on your desktop, sir.")
        return AgentDecision(ToolCall("chat.reply", {"text": "bad name"}),
                             "I can't create that name — please use a simple folder or file name, sir.")

    # Bare domain
    m = re.search(r"\b(?:open|visit|launch|go to)\s+([a-z0-9\-]+(?:\.[a-z]{2,})+)", clean)
    if m:
        return AgentDecision(ToolCall("web.open_domain", {"domain": m.group(1)}),
                             f"Opening {m.group(1)}, sir.")

    # Video / image / shopping shortcuts
    m = re.match(r"^(?:newest|latest|most recent) (.+) video$", clean) or \
        re.match(r"^open a (.+) video$", clean)
    if m:
        return AgentDecision(ToolCall("web.search", {"query": m.group(1) + " latest video", "vertical": "video"}),
                             f"Opening the latest {m.group(1).title()} video, sir.",
                             widget={"kind": "video", "query": m.group(1)})
    m = re.match(r"^show me (?:a |an |the )?(picture|photo|image) of (.+)$", clean)
    if m:
        return AgentDecision(ToolCall("web.search", {"query": m.group(2), "vertical": "images"}),
                             f"Showing images of {m.group(2).title()}, sir.",
                             widget={"kind": "images", "query": m.group(2)})

    for plat in ("trendyol", "amazon", "hepsiburada", "n11", "ebay", "google shopping", "shopping"):
        if plat in clean:
            q = re.sub(r"\b(" + re.escape(plat) + r"|buy|find|show|search|shop|for|on|please)\b", " ", clean)
            q = re.sub(r"\s+", " ", q).strip()
            platform = "google shopping" if plat == "shopping" else plat
            url = build_search_url(q)  # speak text only; server builds platform URL
            _ = url
            return AgentDecision(ToolCall("shop.search", {"platform": platform, "query": q or plat}),
                                 f"Searching {platform.title()} for '{(q or plat).title()}', sir.",
                                 widget={"kind": "shopping", "platform": platform, "query": q})

    # Explicit search verbs
    for prefix in ("search youtube for ", "search google for ", "google ", "search the web for "):
        if clean.startswith(prefix):
            q = clean[len(prefix):].strip()
            if q:
                vertical = "video" if "youtube" in prefix else "web"
                return AgentDecision(ToolCall("web.search", {"query": q, "vertical": vertical}),
                                     f"Searching for '{q.title()}', sir.")

    # Fallback: chat (Phase 2 LLM plugs in here)
    return AgentDecision(ToolCall("chat.reply", {"text": raw}),
                         "Understood, sir.",
                         widget=None)


def speak_for_call(call: ToolCall, raw: str = "") -> tuple[str, dict | None]:
    """Speak text + widget hint for an LLM-produced ToolCall (Phase 2)."""
    name, a = call.name, call.args or {}
    if name == "system.telemetry":
        return "On it, sir.", {"kind": "telemetry"}
    if name == "system.time":
        return "On it, sir.", None
    if name == "system.volume":
        from .tools import clamp_volume
        return f"Volume set to {clamp_volume(a.get('level', 50))} percent, sir.", None
    if name == "system.mute":
        return ("Audio muted, sir." if a.get("muted") else "Audio unmuted, sir."), None
    if name == "media.spotify":
        return {"next": "Playing the next track, sir.",
                "previous": "Previous track, sir."}.get(a.get("action"), "Toggling the music, sir."), None
    if name == "apps.open":
        return f"Opening {str(a.get('target', '')).title()}, sir.", None
    if name == "folders.open":
        return f"Opening {a.get('name')} for you, sir.", None
    if name == "files.create":
        return f"Created the {a.get('kind')} '{a.get('name')}' on your desktop, sir.", None
    if name == "web.open_domain":
        return f"Opening {a.get('domain')}, sir.", None
    if name == "web.search":
        q = str(a.get("query", raw))
        v = a.get("vertical", "web")
        if v == "video":
            return f"Opening results for '{q.title()}', sir.", {"kind": "video", "query": q}
        if v == "images":
            return f"Showing images of {q.title()}, sir.", {"kind": "images", "query": q}
        return f"Searching for '{q.title()}', sir.", None
    if name == "shop.search":
        return (f"Searching {str(a.get('platform', '')).title()} "
                f"for '{str(a.get('query', '')).title()}', sir."), \
               {"kind": "shopping", "platform": a.get("platform"), "query": a.get("query")}
    if name == "terminal.run":
        return f"Executed '{a.get('command')}' in Terminal, sir.", None
    return "Understood, sir.", None
