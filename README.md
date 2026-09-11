# JARVIS — Virtual Butler

A self-hosted macOS assistant with a glassmorphic **Command Center** web UI and a strict
**action-over-advice** execution policy. Say (or type) a request: JARVIS performs real
system actions — opening apps, folders, domains and products, controlling volume, running
commands in Terminal and creating files — then confirms with a single spoken line. Pure
conversation is handled by a local-first hybrid brain instead.

## Features

- **System Action Engine** — unified action/conversation classifier. Action requests are
  *executed*, never answered with step-by-step advice:
  - Launch apps & open websites (`open youtube`, `open spotify`)
  - Open folders, files & absolute paths (`open the downloads folder`)
  - Create files/folders on the Desktop (`create a folder named Reports`)
  - Control system volume (`set volume to 40`, `volume up`)
  - Mute / unmute audio, lock the screen, empty the Trash, take screenshots
  - Run commands in Terminal (`run ls -la in the terminal`), open bare domains
    (`open github.com`), Spotify media controls (next/previous/play-pause)
  - Residual actions always land: playback asks → YouTube, photo asks → Google Images,
    anything else → direct web search
- **Hybrid Brain** — Ollama (local, primary) → Gemini (fallback) → web snippet →
  direct search. Only non-action conversation reaches the LLM; queries needing live
  knowledge (news, weather, prices) skip straight to the web-capable tier.
- **Product & shopping search** — `brown iphone 13 case trendyol`,
  `mechanical keyboard amazon`, `nike shoes hepsiburada`, `iphone ebay`,
  `samsung s24 google shopping` — builds the correct search URL per platform and opens it.
- **Live data intents** — breaking news, currency exchange (USD/EUR/TRY), Bitcoin
  (USD/TRY) via CoinGecko.
- **Video intents** — `latest {topic} video`, `newest {topic} video`, `open a {topic} video`.
- **Conversation memory** — keeps up to 6 recent turns so context carries across prompts
  ("…for my girlfriend? she likes pink").
- **Telemetry + voice mute** — real-time CPU/RAM/battery endpoint and a voice-mute toggle.

## Requirements

- **Python 3.10+** (developed on 3.14)
- **macOS** — system actions use `open`, AppleScript and `osascript`
- [Ollama](https://ollama.com) *(optional)* — used as the primary chat tier when running
  (`OLLAMA_BASE` default `http://localhost:11434`). If the configured model isn't
  installed, the first installed model is auto-selected.
- Good-quality headphones/mic help voice recognition.

## Setup

```bash
git clone https://github.com/OzNova/Virtual-Buttler.git
cd Virtual-Buttler

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# API key for the Gemini fallback tier (optional but recommended)
printf 'GEMINI_API_KEY=YOUR_KEY\n' > .env
```

Optional tweaks (all environment variables with sane defaults):

| Variable         | Default                  | Purpose                          |
|------------------|--------------------------|----------------------------------|
| `GEMINI_API_KEY` | *(unset)*                | Gemini fallback tier API key     |
| `GEMINI_MODEL`   | `gemini-2.0-flash`       | Gemini model name                |
| `OLLAMA_BASE`    | `http://localhost:11434` | Ollama endpoint                  |
| `OLLAMA_MODEL`   | `llama3.2:1b`            | Preferred Ollama model           |
| `OLLAMA_TIMEOUT` | `30`                     | Ollama request timeout (seconds) |

## Run

Double-click `launch_jarvis.command` (starts the server if needed and opens the UI in a
clean Chrome app-mode window), or:

```bash
python3 app.py            # serves the Command Center at http://127.0.0.1:5000
./run.sh                  # venv-aware launcher (same server)
python3 jarvis.py "time"  # lightweight CLI client -> POST /api/command
```

> Local-only by design: binds `127.0.0.1`, no auth. Do not expose to a network.

## Example commands

```
open the downloads folder      create a folder named Reports
set volume to 40               volume up
run ls -la in the terminal     open github.com
play despacito                 show me a picture of a fox
brown iphone 13 case trendyol  mechanical keyboard amazon
latest taylor swift video      what's the weather in Paris?
dolar kaç tl                   tell me a joke
```

## REST API

| Endpoint          | Method(s)        | Description                                 |
|-------------------|------------------|---------------------------------------------|
| `/api/command`    | `POST`           | Send `{"command": "…"}` → `{"message", …}`  |
| `/api/ping`       | `GET`            | Health check (`{"status":"success"}`)       |
| `/api/telemetry`  | `GET`            | CPU / RAM / battery report                  |
| `/api/voice-mute` | `GET`/`POST`     | Get or set the voice-mute flag              |
| `/api/media`      | `POST`           | Spotify media controls (`next/prev/play`)   |
| `/api/broadcast`  | `POST`           | Broadcast a message to the UI               |

## License

[MIT](LICENSE) — © 2026 Virtual Butler Project
## Agent (Phase 1 — opt-in, local-only)

Deterministic tool-calling seam alongside the Flask app. No new keys required.

```bash
pip install -r requirements-agent.txt
python -m server.main   # FastAPI on http://127.0.0.1:8000
python -m unittest discover -s tests -v
```

- `GET /api/tools` — 13 typed tools (JSON Schema, LangGraph-ready)
- `POST /api/agent {"message":"…"}` — structured `{call, message, widget}`
- `WS /ws/chat` — chunked `token` + final `result` stream
- Phase 2: `AGENT_LLM=off|ollama|gemini` (`GET /api/agent/status`), `POST /api/agent/stream` (SSE).
  Example: `AGENT_LLM=ollama OLLAMA_MODEL=llama3.2:1b python -m server.main` — "a bit quieter" → `system.volume{level:20}`; failures fall back to router
- Phase 3: voice pipeline — defaults need no keys (browser mic + `say`).
  `GET /api/voice/status`, `POST /api/tts`, `POST /api/stt` (base64 JSON).
  Optional `BUTLER_TTS=elevenlabs|openai`, `BUTLER_STT=groq|deepgram`;
  volume ducking on speak via event bus (`BUTLER_DUCKING=1`).
- Compat REST (`/api/command`, `/api/telemetry`, …) mirrored from Flask
- See `docs/ROADMAP.md` for Phases 2–5 (LLM calling, voice, RAG/vision, Tauri/HUD).
