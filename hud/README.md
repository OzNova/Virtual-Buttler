# Butler HUD (Phase 5 scaffold, local-only)

Next.js + Tailwind + Framer Motion + React Three Fiber + Recharts talking to
the FastAPI sidecar on `http://127.0.0.1:8000`. No auth by design (loopback).

## Develop

```bash
cd hud
npm install
npm run dev        # http://localhost:3000
```

In another terminal:

```bash
pip install -r requirements-agent.txt
python -m server.main   # :8000
```

## Build for Tauri

```bash
cd hud
npm run build      # emits ../hud/out (see next.config.mjs output:export)
```

Then:

```bash
cargo tauri dev    # from repo root (see src-tauri/)
cargo tauri build
```

## Env

- `BUTLER_API` (default `http://127.0.0.1:8000`)

## Notes

- `templates/index.html` (Flask :5000) remains the zero-dependency fallback.
- Orb is matte Apple-quiet (no neon); level comes from `WS /ws/audio`.
- Telemetry chart polls `GET /api/telemetry` every 2.5s (same source as rings).
