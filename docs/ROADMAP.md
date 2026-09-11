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

## Phase 2 — LLM tool-calling (DONE)
- `agent/llm.py`: Ollama `/api/chat` tools + Gemini `functionDeclarations`, stdlib-only, timeouts.
- `agent/decide.py`: LLM first when `AGENT_LLM=ollama|gemini`, else deterministic `route()`; unknown tools/errors fall back.
- `POST /api/agent` (structured), `POST /api/agent/stream` (SSE token+result), `WS /ws/chat` via `decide()`, `GET /api/agent/status`.
- `/api/command` stays deterministic for compat. Default `AGENT_LLM=off` (no keys).

## Phase 3 — Voice pipeline (DONE, defaults need no keys)
- `agent/voice.py`: `synthesize`/`transcribe`/`vad_speech`/`DuckingController`,
  stdlib-only; Silero via lazy import with energy-VAD fallback (no `audioop`).
- Defaults: browser Web Speech mic + macOS `say`; backend `/api/stt` 501 and
  `/api/tts` `local` hint until a provider key is set.
- Optional: `BUTLER_TTS=elevenlabs|openai`, `BUTLER_STT=groq|deepgram`
  (urllib REST, base64 JSON — no `python-multipart` needed).
- Ducking: `speak.start/stop` bus events dip system volume by
  `BUTLER_DUCK_LEVEL` (default 25) when `BUTLER_DUCKING=1`.
- Endpoints: `GET /api/voice/status`, `POST /api/tts`, `POST /api/stt`.
- Barge-in: frontend mic already stops on submit; full interrupt-mid-speech
  lands with Phase 5 audio element (backend events already emit).

## Phase 4 — Memory + knowledge (DONE, all opt-in, no required deps)
- `agent/knowledge.py`: `BUTLER_DOC_PATHS` allowlist (.txt/.md native, .pdf lazy
  pypdf), `data/docs.jsonl` index, keyword search + extractive summary;
  `BUTLER_VECTOR=chroma` uses lazy chromadb with keyword fallback.
- Tools: `memory.recall`, `docs.search`, `docs.summarize` (+ router patterns).
- `agent/vision.py`: `screencapture` capture + Gemini describe when
  `GEMINI_API_KEY` set, else path + hint. Tool `vision.capture`.
- `agent/focus.py`: `.ics` (`BUTLER_ICS_PATHS`) or `icalBuddy` read-only;
  `focus.check` suggests focus mode near deep-work blocks + `focus.suggest` bus event.
- `agent/home.py`: Home Assistant REST (`HASS_URL`+`HASS_TOKEN`), no MQTT dep yet.
  Tools `home.state`/`home.call`; unconfigured -> hint, never crash.
- Endpoints: `/api/memory/recall`, `/api/docs/search|summarize`,
  `/api/vision/capture`, `/api/calendar/next`, `/api/focus`,
  `/api/home/state|call`. Registry now 21 tools.

## Phase 5 — Desktop + HUD UI (DONE, scaffold; runtimes stay optional)
- `hud/` Next.js 14 + Tailwind + Framer Motion + R3F + Recharts (Apple-quiet,
  same tokens as `templates/index.html` fallback). `npm run dev` (:3000).
- `GET /api/hud/state` boot payload + `WS /ws/audio` 4Hz level meter drive
  the matte R3F orb; `TelemetryChart` polls `/api/telemetry` (Recharts);
  `WidgetCards` renders agent `widget` JSON (shopping/calendar/focus/...).
- `src-tauri/` shell: tray (hide-not-quit), `CommandOrControl+Shift+Space`
  shortcut, `frontendDist ../hud/out`. `cargo tauri dev|build` (icons via
  `cargo tauri icon`). Backend unchanged: still FastAPI :8000, Flask :5000 kept.

## Conventions
- Local-only: bind `127.0.0.1`, no auth, no rate-limit (operator requirement).
- Safety rails (not auth): Desktop confinement, terminal destructive blocklist,
  `MAX_COMMAND_CHARS`, TTS truncation. See `app.py`.
- Every phase must keep `tests/` green and Flask `:5000` working.
