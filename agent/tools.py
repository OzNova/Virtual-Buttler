"""Typed tool registry (Phase 1).

Each Tool has a JSON-Schema-ish arg spec so a future LLM function-caller
(LangGraph/PydanticAI in Phase 2) can use it directly. Executors live in
server/main.py (OS side effects); this module stays pure + testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import re
import urllib.parse


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "args": dict(self.args)}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema object
    examples: List[str] = field(default_factory=list)

    def to_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def clamp_volume(level: Any) -> int:
    try:
        v = int(level)
    except (TypeError, ValueError):
        v = 50
    return max(0, min(100, v))


TERMINAL_BLOCKLIST = (
    "rm -rf /", "mkfs", ":(){", "dd if=", "shutdown", "reboot",
    "halt", "poweroff", "> /dev/sda", "diskutil erase",
)


def is_blocked_terminal(cmd: str) -> bool:
    c = (cmd or "").lower()
    return any(b in c for b in TERMINAL_BLOCKLIST)


def sanitize_filename(name: str) -> Optional[str]:
    """Return a safe Desktop-confined file/folder name, or None."""
    n = (name or "").strip().strip("/\\").strip()
    if not n or n in (".", "..") or "/" in n or "\\" in n or "\x00" in n:
        return None
    if len(n) > 100:
        return None
    return n


_PLATFORM_URLS = {
    "trendyol": "https://www.trendyol.com/sr?q={q}",
    "amazon": "https://www.amazon.com.tr/s?k={q}",
    "hepsiburada": "https://www.hepsiburada.com/ara?q={q}",
    "n11": "https://www.n11.com/arama?q={q}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={q}",
    "google shopping": "https://www.google.com/search?tbm=shop&q={q}",
}


def build_shopping_url(platform: str, query: str) -> str:
    key = (platform or "google shopping").lower().strip()
    tpl = _PLATFORM_URLS.get(key, _PLATFORM_URLS["google shopping"])
    q = re.sub(r"\s+", "+", (query or "").strip().strip("+"))
    return tpl.format(q=urllib.parse.quote(q, safe="+"))


def build_search_url(query: str, vertical: str = "web") -> str:
    q = urllib.parse.quote((query or "").strip())
    if vertical == "images":
        return "https://www.google.com/search?tbm=isch&q=" + q
    if vertical == "video":
        return "https://www.youtube.com/results?search_query=" + q
    return "https://www.google.com/search?q=" + q


TOOLS: List[Tool] = [
    Tool("system.telemetry", "Get CPU/RAM/battery snapshot.",
         {"type": "object", "properties": {}}, ["system check"]),
    Tool("system.time", "Get local time/date.",
         {"type": "object", "properties": {"which": {"type": "string", "enum": ["time", "date"]}}},
         ["what time is it"]),
    Tool("system.volume", "Set/adjust output volume 0-100.",
         {"type": "object", "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}}, "required": ["level"]},
         ["set volume to 40"]),
    Tool("system.mute", "Mute or unmute audio.",
         {"type": "object", "properties": {"muted": {"type": "boolean"}}, "required": ["muted"]},
         ["mute", "unmute"]),
    Tool("media.spotify", "Control Spotify playback.",
         {"type": "object", "properties": {"action": {"type": "string", "enum": ["next", "previous", "playpause"]}}, "required": ["action"]},
         ["next song"]),
    Tool("apps.open", "Open a known app or site.",
         {"type": "object", "properties": {"target": {"type": "string", "enum": ["youtube", "terminal", "finder", "spotify", "chrome"]}}, "required": ["target"]},
         ["open youtube"]),
    Tool("folders.open", "Open a well-known macOS folder.",
         {"type": "object", "properties": {"name": {"type": "string", "enum": ["downloads", "desktop", "documents", "pictures", "music", "movies", "applications", "home"]}}, "required": ["name"]},
         ["open the downloads folder"]),
    Tool("files.create", "Create a file/folder on the Desktop (confined).",
         {"type": "object", "properties": {"kind": {"type": "string", "enum": ["file", "folder"]}, "name": {"type": "string"}}, "required": ["kind", "name"]},
         ["create a folder named Reports"]),
    Tool("web.open_domain", "Open a bare domain in the browser.",
         {"type": "object", "properties": {"domain": {"type": "string"}}, "required": ["domain"]},
         ["open github.com"]),
    Tool("web.search", "Web/video/image search.",
         {"type": "object", "properties": {
             "query": {"type": "string"},
             "vertical": {"type": "string", "enum": ["web", "video", "images"]}},
          "required": ["query"]},
         ["latest taylor swift video"]),
    Tool("shop.search", "Product search on a marketplace.",
         {"type": "object", "properties": {
             "platform": {"type": "string", "enum": list(_PLATFORM_URLS)},
             "query": {"type": "string"}},
          "required": ["platform", "query"]},
         ["brown iphone 13 case trendyol"]),
    Tool("terminal.run", "Run a command in macOS Terminal (guarded).",
         {"type": "object", "properties": {"command": {"type": "string", "maxLength": 200}}, "required": ["command"]},
         ["run ls -la in the terminal"]),
    Tool("chat.reply", "Pure conversation (no side effect).",
         {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
         ["tell me a joke"]),
]

REGISTRY: Dict[str, Tool] = {t.name: t for t in TOOLS}


def list_schemas() -> List[Dict[str, Any]]:
    return [t.to_schema() for t in TOOLS]
