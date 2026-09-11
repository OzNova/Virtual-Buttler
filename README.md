# Butler — Virtual-Buttler

Local-only macOS assistant with an **action-over-advice** policy: commands are
*executed* (apps, folders, volume, Terminal, files, media, smart home), never
answered with instructions. Conversation goes through a local-first brain.

> Local-only by design: everything binds `127.0.0.1`, no auth. Do not expose
> to a network.

## Run it

```bash
git clone https://github.com/OzNova/Virtual-Buttler.git
cd Virtual-Buttler
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt          # Flask UI + CLI (zero Node/Rust)
```

| Mode | Command | What you get |
| ---- | ------- | ------------ |
| Classic UI | `python3 app.py` or `./run.sh` or double-click `launch_jarvis.command` | Apple-style Command Center at `http://127.0.0.1:5000` |
| CLI | `python3 jarvis.py "what time is it"` | Stdlib client → `POST /api/command` (also REPL/pipe mode) |
| Agent API | `pip install -r requirements-agent.txt && python -m server.main` | FastAPI on `http://127.0.0.1:8000` — 21 typed tools, WS/SSE streaming |
| HUD | `cd hud && npm install && npm run dev` (+ agent API above) | Next.js HUD at `http://localhost:3000` — orb, charts, widget cards |
| Desktop | `cargo tauri dev` in `src-tauri/` | Tray + `Cmd/Ctrl+Shift+Space` shell around the HUD |

## Try

```
open the downloads folder      create a folder named Reports
set volume to 40               run ls -la in the terminal
open github.com                next song
latest taylor swift video      show me a picture of a fox
brown iphone 13 case trendyol  dolar kaç tl
summarize the Q3 budget pdf    what is my next meeting?
turn on the living room light  should I focus now?
```

## How it works

```
templates/index.html / hud/ / jarvis.py
        │  REST / WS (loopback)
        ▼
Flask app.py (:5000, legacy)  ·  FastAPI server/main.py (:8000, agent)
        │                              │  decide() → execute()
        │                              ▼
        │                    agent/{router,decide,llm,tools,memory,
        │                           knowledge,vision,focus,home,voice,events}
        ▼                              ▼
macOS: open / osascript / say / screencapture · web · Ollama/Gemini (opt-in)
```

- **Decision vs execution split:** `agent/router.py` (deterministic) returns a
  `ToolCall`; `agent/decide.py` tries the LLM first when `AGENT_LLM` is set,
  else the router. `server/main.py:execute()` performs it. Same shape a future
  LangGraph/PydanticAI caller can produce.
- **Fallbacks everywhere:** LLM fail → router; vector DB absent → keyword
  search; vision key absent → screenshot path + hint; calendar/home unconfigured
  → hint, never crash.
- **Safety rails (not auth):** Desktop confinement, terminal destructive
  blocklist, `MAX_COMMAND_CHARS=1000`, TTS truncation, doc-path allowlist.

## API (FastAPI :8000; Flask :5000 mirrors the `*` rows)

| Endpoint | Method | Description |
| -------- | ------ | ----------- |
| `/` | `GET` | UI (`templates/index.html`) / service info |
| `/api/command` * | `POST` | `{"command":"…"}` → `{"message",…}` (deterministic) |
| `/api/agent` | `POST` | `{"message":"…"}` → `{call, message, widget, llm}` (LLM when enabled) |
| `/api/agent/stream` | `POST` | SSE `token` chunks + `result` |
| `/api/agent/status` | `GET` | `{llm, ollama_base/model, gemini_model, gemini_key_set}` |
| `/api/tools` | `GET` | 21 tool schemas (JSON Schema) |
| `/api/ping` * | `GET` | Health check |
| `/api/telemetry` * | `GET` | CPU / RAM / battery + clock |
| `/api/voice-mute` * | `GET`/`POST` | TTS mute flag |
| `/api/media` * | `POST` | Spotify `next/previous/playpause` |
| `/api/broadcast` * | `POST` | Speak a message via TTS |
| `/api/voice/status` | `GET` | `{tts, stt, vad, ducking, keys_set}` |
| `/api/tts` | `POST` | `{"text"}` → `{audio_b64, mime}` or `local` hint |
| `/api/stt` | `POST` | `{"audio_b64", "mime"}` → `{transcript}` or `501` hint |
| `/api/memory/recall` | `POST` | Past conversation notes |
| `/api/docs/search` | `POST` | Allowlisted document search |
| `/api/docs/summarize` | `POST` | Extractive doc summary |
| `/api/vision/capture` | `POST` | Screenshot (+ Gemini describe when key set) |
| `/api/calendar/next` | `GET` | Upcoming events (ICS/icalBuddy) |
| `/api/focus` | `GET` | Focus-mode suggestion near deep-work blocks |
| `/api/home/state` | `POST` | Home Assistant entity state |
| `/api/home/call` | `POST` | Home Assistant service call |
| `/api/widgets` | `GET` | HUD card data (`?kind=telemetry`) |
| `/api/hud/state` | `GET` | Combined boot payload for the HUD |
| `/ws/chat` | `WS` | `{command}` → `token`* + `result` |
| `/ws/audio` | `WS` | 4Hz `{level, speaking, cpu}` for the orb |

## Tools (21)

`system.telemetry`, `system.time`, `system.volume`, `system.mute` · `media.spotify` · `apps.open` ·
`folders.open` · `files.create` · `web.open_domain`, `web.search` · `shop.search` ·
`terminal.run` · `memory.recall` · `docs.search`, `docs.summarize` · `vision.capture` ·
`calendar.next` · `focus.check` · `home.state`, `home.call` · `chat.reply`

## Configure (all optional — see `.env.example`)

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | unset / `gemini-2.0-flash` | Gemini chat + vision fallback |
| `OLLAMA_BASE` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT` | `http://localhost:11434` / `llama3.2:1b` / `30` | Local chat tier |
| `AGENT_LLM` | `off` | `off` \| `ollama` \| `gemini` tool-calling |
| `TTS_VOICE` | `Daniel` | macOS `say` voice |
| `BUTLER_TTS` / `BUTLER_STT` | `say` / `off` | `elevenlabs`\|`openai` / `groq`\|`deepgram` with keys |
| `ELEVENLABS_API_KEY` / `OPENAI_API_KEY` / `GROQ_API_KEY` / `DEEPGRAM_API_KEY` | unset | Voice providers |
| `BUTLER_DUCKING` / `BUTLER_DUCK_LEVEL` | `1` / `25` | Volume dip while speaking |
| `BUTLER_DOC_PATHS` / `BUTLER_DOC_INDEX` / `BUTLER_VECTOR` | unset / `data/docs.jsonl` / unset | Doc allowlist (`:`-separated), index, `chroma` opt-in |
| `BUTLER_ICS_PATHS` / `BUTLER_FOCUS_WINDOW_MIN` | unset / `30` | Calendar `.ics` allowlist, focus window |
| `HASS_URL` / `HASS_TOKEN` | unset | Home Assistant bridge |
| `BUTLER_MEMORY` | `data/memory.jsonl` | Long-term notes file |
| `PORT` / `AGENT_PORT` | `5000` / `8000` | Flask / FastAPI ports |
| `JARVIS_BACKEND` | `http://127.0.0.1:5000` | CLI target |

## Layout

```
app.py  jarvis.py  run.sh  launch_jarvis.command   # classic (Flask :5000)
agent/  tools router decide llm memory knowledge vision focus home voice events
server/main.py                                      # FastAPI :8000
templates/index.html                                # zero-dep Apple UI
hud/  app/ components/ lib/                        # Next.js HUD (:3000)
src-tauri/                                          # tray + hotkey shell
tests/  test_agent test_llm test_voice test_world test_hud
docs/ROADMAP.md
```

## Test

```bash
python -m unittest discover -s tests -v   # 47 tests, stdlib-heavy, mocked OS/network
```

## Status

Phases 1–5 done (see `docs/ROADMAP.md`): tool registry → LLM calling → voice →
knowledge/vision/home → HUD/Tauri scaffold. Remaining manual steps: `npm install`,
`cargo tauri icon`, provider keys, Apple signing.

## License

[MIT](LICENSE) — © 2026 Virtual Butler Project
