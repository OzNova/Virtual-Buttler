"""LLM tool-calling (Phase 2). Flagged, fallback-safe, stdlib-only.

Mode via AGENT_LLM env: off (default) | ollama | gemini.
- off: never calls network, decide() uses deterministic router.
- ollama: POST {OLLAMA_BASE}/api/chat with tools; parses tool_calls.
- gemini: POST generateContent with functionDeclarations; parses functionCall.

Any failure (timeout, bad payload, unknown tool) returns None so callers
fall back to the deterministic router. No keys required for default path.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

from .tools import REGISTRY, ToolCall

logger = logging.getLogger("butler-agent.llm")

SYSTEM_INSTRUCTIONS = (
    "You are Butler, a local macOS assistant. Prefer calling a tool when the user "
    "wants something DONE (open, set, create, play, search, run). "
    "Otherwise reply in plain text, 1-2 short sentences. "
    "Never claim to have performed an action; tools execute locally."
)


def mode() -> str:
    return (os.getenv("AGENT_LLM", "off") or "off").lower().strip()


def ollama_base() -> str:
    return (os.getenv("OLLAMA_BASE", "http://localhost:11434") or "").rstrip("/")


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "llama3.2:1b")


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama_tools_payload() -> list:
    out = []
    for name, tool in REGISTRY.items():
        if name == "chat.reply":
            continue
        out.append({"type": "function",
                    "function": {"name": name, "description": tool.description,
                                 "parameters": tool.parameters}})
    return out


def ollama_tool_call(message: str, history: list | None = None, timeout: float = 15.0) -> dict | None:
    """Returns {'call': ToolCall} | {'text': str} | None."""
    msgs = [{"role": "system", "content": SYSTEM_INSTRUCTIONS}]
    for role, text in (history or [])[-12:]:
        msgs.append({"role": "user" if role == "user" else "assistant", "content": text})
    msgs.append({"role": "user", "content": message})
    data = _post_json(f"{ollama_base()}/api/chat",
                      {"model": ollama_model(), "messages": msgs,
                       "tools": _ollama_tools_payload(), "stream": False,
                       "options": {"temperature": 0.2}},
                      headers={"User-Agent": "Butler/1.0"}, timeout=timeout)
    msg = (data.get("message") or {})
    calls = msg.get("tool_calls") or []
    if calls:
        fn = (calls[0].get("function") or {})
        name = fn.get("name", "")
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if name in REGISTRY and isinstance(args, dict):
            return {"call": ToolCall(name, args)}
        return None
    content = (msg.get("content") or "").strip()
    return {"text": content} if content else None


def _gemini_declarations() -> list:
    decls = []
    for name, tool in REGISTRY.items():
        if name == "chat.reply":
            continue
        params = dict(tool.parameters or {"type": "object", "properties": {}})
        # Gemini functionDeclarations accept a subset; drop unknown keywords.
        clean_props: dict = {}
        for k, v in (params.get("properties") or {}).items():
            if not isinstance(v, dict):
                continue
            clean_props[k] = {kk: vv for kk, vv in v.items()
                              if kk in ("type", "description", "enum", "items")}
        decls.append({"name": name, "description": tool.description,
                      "parameters": {"type": "object", "properties": clean_props,
                                     "required": params.get("required", [])}})
    return decls


def gemini_tool_call(message: str, history: list | None = None, timeout: float = 15.0) -> dict | None:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    contents = []
    for role, text in (history or [])[-12:]:
        contents.append({"role": "user" if role == "user" else "model",
                         "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    data = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model()}:generateContent",
        {"system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTIONS}]},
         "contents": contents,
         "tools": [{"functionDeclarations": _gemini_declarations()}],
         "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512}},
        headers={"User-Agent": "Butler/1.0", "x-goog-api-key": key}, timeout=timeout)
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return None
    for part in parts:
        fn = part.get("functionCall") or part.get("functioncall")
        if fn and fn.get("name") in REGISTRY:
            args = fn.get("args") or {}
            if isinstance(args, dict):
                return {"call": ToolCall(fn["name"], args)}
            return None
    texts = [p.get("text", "") for p in parts if p.get("text")]
    combined = "".join(texts).strip()
    return {"text": combined} if combined else None


def llm_tool_call(message: str, history: list | None = None) -> dict | None:
    """Dispatch by AGENT_LLM. Returns {'call'|'text'} or None (fallback)."""
    m = mode()
    if m == "off":
        return None
    try:
        if m == "ollama":
            return ollama_tool_call(message, history)
        if m == "gemini":
            return gemini_tool_call(message, history)
        logger.debug("unknown AGENT_LLM=%r", m)
        return None
    except Exception:
        logger.debug("LLM tool call failed", exc_info=True)
        return None
