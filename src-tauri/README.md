# Butler Tauri shell (local-only)

Hosts `hud/out` (Next.js static export) as a native window with tray +
global shortcut `CommandOrControl+Shift+Space` (focus HUD).

## Prereqs

- Node 20+, Rust stable, Tauri CLI: `cargo install tauri-cli --version ^2`
- Backend running: `python -m server.main` (:8000)

## Dev

```bash
cargo tauri dev
```

## Build

```bash
cargo tauri build
```

Icons: add `src-tauri/icons/` (32x32.png, 128x128.png, icon.icns, icon.ico)
before `cargo tauri build` — `cargo tauri icon icon.png` generates them.
