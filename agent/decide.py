"""Decide: LLM tool-call first (when enabled), else deterministic router.

Single entry for server paths that want Phase 2 behavior:
  decide(text, history) -> AgentDecision
`/api/command` stays deterministic for compat; `/api/agent`, `/ws/chat`,
`/api/agent/stream` use decide().
"""
from __future__ import annotations

from .llm import llm_tool_call
from .router import AgentDecision, route, speak_for_call
from .tools import REGISTRY, ToolCall


def decide(text: str, history: list | None = None) -> AgentDecision:
    raw = (text or "").strip()
    if not raw:
        return AgentDecision(ToolCall("chat.reply", {"text": ""}), "I didn't catch that, sir.")
    res = llm_tool_call(raw, history)
    if not res:
        return route(raw)
    if "call" in res:
        call = res["call"]
        if call.name not in REGISTRY:
            return route(raw)
        speak, widget = speak_for_call(call, raw)
        return AgentDecision(call, speak, widget)
    if "text" in res and res["text"]:
        return AgentDecision(ToolCall("chat.reply", {"text": res["text"]}), res["text"])
    return route(raw)
