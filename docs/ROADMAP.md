# Virtual-Buttler — Agent Roadmap (local-only, no auth)

Goal: from scripted regex intents to an event-driven, multimodal agent,
without breaking the working Flask app. Each phase is additive and demoable.

## Phase 1 — Agent seam (THIS CHANGE)
- `agent/tools.py`: typed tool registry (JSON Schema per tool, no LLM required).
- `agent/router.py`: deterministic router returning `ToolCall` (decision vs execution split).
- `agent/memory.py`: short-term deque + long-term JSONL (keyword recall, ChromaDB-ready interface).
- `agent/events.py`: tiny pub/sub event bus (future: proactive + telemetry streaming).
- `server/main.py`: FastAPI sidecar on `127.0.0.1:8000` with compat REST
  (`/api/command`, `/api/ping`, `/api/telemetry`, `/api/voice-mute`, `/api/media`, `/api/broadcast`)
  plus new `/api/tools`, `/api/agent`, `/api/widgets` (stub), `WS /ws/chat` (chunked stream).
- Flask `app.py` untouched (legacy on `:5000`). New stack is opt-in:
  `pip install -r requirements-agent.txt && python -m server.main`.

## Phase 2 — LLM tool-calling (next)
- Ollama/Gemini function-calling behind `AGENT_LLM=off|ollama|gemini`.
- Fallback to deterministic router. No new keys required for default path.
- Add `POST /api/agent/stream` (SSE) + WS token streaming.

## Phase 3 — Voice pipeline (optional providers)
- Abstractions: `STTProvider`, `TTSProvider`, `VAD`.
- Default: Web Speech API (browser) + macOS `say`. Optional: Deepgram/Groq STT,
  ElevenLabs/OpenAI TTS, Silero VAD, barge-in (stop-speak-on-interrupt).
- Music ducking on speak start/stop (event bus).

## Phase 4 — Memory + knowledge
- `agent/memory.py` gains vector backend: ChromaDB/Qdrant (lazy import, local dir).
- Index `~/Documents` (opt-in path allowlist). `summarize_pdf`, `recall_notes` tools.
- Vision: `capture_screen()` tool -> Vision LLM (Gemini/GPT-4o, key required).
- Proactive: calendar hook (macOS Calendar read-only) + focus-mode suggestion event.
- Smart home: MQTT/Home Assistant bridge (opt-in `HASS_URL`+token, local only).

## Phase 5 — Desktop + HUD UI
- Keep Apple-like `templates/index.html` as fallback.
- New: Next.js + Tailwind + Framer Motion HUD (`/api/widgets` feeds cards),
  React Three Fiber orb driven by `/ws/audio` levels.
- Tauri shell: tray, global hotkey `Cmd+Shift+Space`, secure OS bridge.
- Telemetry graphs (Recharts) from existing `/api/telemetry` polling.

## Conventions
- Local-only: bind `127.0.0.1`, no auth, no rate-limit (operator requirement).
- Safety rails (not auth): Desktop confinement, terminal destructive blocklist,
  `MAX_COMMAND_CHARS`, TTS truncation. See `app.py`.
- Every phase must keep `tests/` green and Flask `:5000` working.
