"""Tiny pub/sub event bus (Phase 1).

Future: proactive triggers (calendar/focus), telemetry fan-out,
music ducking on speak start/stop, WS broadcast.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable, Dict, List


class EventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def on(self, topic: str, fn: Callable) -> None:
        with self._lock:
            self._subs[topic].append(fn)

    def emit(self, topic: str, payload: dict | None = None) -> None:
        with self._lock:
            fns = list(self._subs.get(topic, []))
        for fn in fns:
            try:
                fn(payload or {})
            except Exception:
                pass


BUS = EventBus()
