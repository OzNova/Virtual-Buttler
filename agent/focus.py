"""Calendar read (opt-in) + focus suggestion (Phase 4).

Sources (first available wins, all local, read-only):
1. BUTLER_ICS_PATHS: colon-separated .ics files (parsed with stdlib re).
2. `icalBuddy` CLI if installed (macOS, `brew install icalbuddy`).
3. Else: {hint} — no crash, feature reports unavailable.

Focus rule: an event starting within BUTLER_FOCUS_WINDOW_MIN (default 30)
whose title matches focus/deep work/meeting keywords -> suggest focus mode.
Emits BUS event "focus.suggest" for future proactive UI.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import subprocess

logger = logging.getLogger("butler-agent.focus")

FOCUS_WORDS = ("focus", "deep work", "deepwork", "study", "exam", "interview",
               "meeting", "call", "standup", "demo", "review")


def _parse_ics(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return []
    events = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        m_sum = re.search(r"SUMMARY:(.+)", block)
        m_start = re.search(r"DTSTART[^:]*:(\d{8}T?\d{0,6}Z?)", block)
        if not (m_sum and m_start):
            continue
        raw_dt = m_start.group(1).strip()
        try:
            if len(raw_dt) >= 15 and "T" in raw_dt:
                dt = datetime.datetime.strptime(raw_dt[:15], "%Y%m%dT%H%M%S")
            else:
                dt = datetime.datetime.strptime(raw_dt[:8], "%Y%m%d")
            if raw_dt.endswith("Z"):
                dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        except ValueError:
            continue
        events.append({"title": m_sum.group(1).strip(), "start": dt})
    return events


def _icalbuddy_events() -> list[dict] | None:
    try:
        out = subprocess.run(["icalBuddy", "-npn", "-nc", "-eed", "-b", "",
                              "eventsToday+7"],
                             capture_output=True, text=True, check=False, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if not out or "error" in out.lower()[:200]:
        return None
    events = []
    for line in out.splitlines():
        line = line.strip("• ").strip()
        if line:
            events.append({"title": line[:120], "start": None})
    return events


def upcoming(limit: int = 5) -> dict:
    paths = [p.strip() for p in (os.getenv("BUTLER_ICS_PATHS", "") or "").split(os.pathsep) if p.strip()]
    events: list[dict] = []
    for p in paths:
        events.extend(_parse_ics(os.path.expanduser(p)))
    if not events:
        buddy = _icalbuddy_events()
        if buddy is not None:
            return {"ok": True, "source": "icalBuddy", "events": buddy[:limit]}
        hint = "Set BUTLER_ICS_PATHS to .ics files or install icalBuddy for calendar."
        return {"ok": False, "hint": hint, "events": []}
    now = datetime.datetime.now()
    future = sorted((e for e in events if e["start"] and e["start"] >= now - datetime.timedelta(hours=2)),
                    key=lambda e: e["start"])[:limit]
    return {"ok": True, "source": "ics",
            "events": [{"title": e["title"], "start": e["start"].isoformat()} for e in future]}


def focus_check() -> dict:
    window_min = int(os.getenv("BUTLER_FOCUS_WINDOW_MIN", "30") or 30)
    data = upcoming(limit=5)
    if not data.get("ok"):
        return {"ok": True, "suggest": False, "reason": "no calendar source", "hint": data.get("hint")}
    now = datetime.datetime.now()
    for e in data["events"]:
        try:
            start = datetime.datetime.fromisoformat(e["start"]) if e.get("start") else None
        except ValueError:
            continue
        if start and datetime.timedelta(0) <= start - now <= datetime.timedelta(minutes=window_min):
            if any(w in (e["title"] or "").lower() for w in FOCUS_WORDS):
                suggestion = (f"Starting '{e['title']}' soon. Enable Focus mode "
                              "and play your focus playlist?")
                try:
                    from .events import BUS
                    BUS.emit("focus.suggest", {"title": e["title"], "start": e["start"]})
                except ImportError:
                    pass
                return {"ok": True, "suggest": True, "event": e, "suggestion": suggestion}
    return {"ok": True, "suggest": False, "events": data["events"]}
