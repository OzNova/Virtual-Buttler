"""Memory: short-term deque + long-term JSONL (Phase 1).

Interface is vector-backend ready: Phase 4 can add ChromaDB behind
remember_long/recall without changing callers.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time
from typing import Dict, List


class ShortMemory:
    def __init__(self, max_turns: int = 6):
        self._buf: collections.deque = collections.deque(maxlen=max_turns * 2)
        self._lock = threading.Lock()

    def add(self, role: str, text: str) -> None:
        with self._lock:
            self._buf.append((role, text))

    def snapshot(self) -> list:
        with self._lock:
            return list(self._buf)


class LongMemory:
    """Append-only JSONL. Recall = naive keyword overlap (upgrade later)."""

    def __init__(self, path: str = "data/memory.jsonl"):
        self.path = path

    def remember(self, user: str, assistant: str) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "user": user, "assistant": assistant}) + "\n")
        except OSError:
            pass

    def recall(self, query: str, limit: int = 3) -> List[Dict]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
        except (OSError, ValueError):
            return []
        q = set((query or "").lower().split())
        scored = sorted(rows, key=lambda r: -len(q & set(str(r.get("user", "")).lower().split())))
        return scored[:limit]
