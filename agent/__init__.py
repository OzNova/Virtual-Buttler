"""Agent package: tool registry, router, memory, events (Phase 1).

Local-only, stdlib-only. No LLM calls here — the deterministic router
produces ToolCalls; an LLM tool-caller can replace it in Phase 2.
"""
