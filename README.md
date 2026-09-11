# Virtual-Buttler · Daily Planner

Single-user study planner for a 9th-grade IB MYP student. Pick topics with a
confidence level, and it builds a daily focus timeline (60/45/30 min blocks
+ breaks), ordered by what you had at school today/tomorrow. Unfinished work
rolls into a catch-up queue, completed topics get 3/7-day spaced reviews,
weak topics accumulate in a drawer, and weekly stats track minutes, questions
and pages. State lives in a local JSON file — no server, no account.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 app.py            # http://127.0.0.1:5000
```

## Desktop (macOS)

Double-click `Daily Planner.command` — starts the backend and opens a native
window via pywebview (falls back to the default browser). The launcher picks a
free port, so other apps on port 5000 are not touched.

Package as an app bundle:

```bash
pip install py2app
python3 setup.py py2app   # -> "Oztudy.app"
```

## Configuration

`Planner/config.json` holds the school timetable and the 2026-27 academic
calendar (holidays, midterm breaks, bayram, summer). Edit it to roll over to a
new academic year — no code changes needed. Built-in defaults are used if the
file is missing.

Data is stored in `Planner/userData/planner.json` (gitignored).

## Tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest Planner/tests -v
```

## Layout

| Path | Purpose |
| --- | --- |
| `Planner/app.py` | Flask API + planning/calendar/gamification logic |
| `Planner/templates/index.html` | Single-page frontend (markup only) |
| `Planner/static/app.css` | Frontend styles |
| `Planner/static/app.js` | Frontend behavior (timers, Zen mode, charts) |
| `Planner/run_desktop.py` | Desktop launcher (backend + pywebview) |
| `Planner/setup.py` | py2app packaging |
| `Planner/tests/` | pytest suite for planning, rollover, streak, API guardrails |
