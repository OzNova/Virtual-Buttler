"""Phase 5 HUD backend tests (mocked side effects)."""
import unittest
from unittest import mock

import server.main as m
from fastapi.testclient import TestClient


def client():
    m.speak = lambda *a, **k: None
    m.webbrowser.open = lambda *a, **k: True
    m._osascript = lambda *a, **k: "50"
    m.subprocess.Popen = lambda *a, **k: mock.Mock()
    return TestClient(m.app)


class TestHudState(unittest.TestCase):
    def test_shape(self):
        c = client()
        with mock.patch("agent.focus.upcoming", return_value={"ok": False, "hint": "x", "events": []}):
            with mock.patch("agent.focus.focus_check",
                            return_value={"ok": True, "suggest": False}):
                data = c.get("/api/hud/state").json()
        self.assertEqual(data["status"], "success")
        for key in ("telemetry", "voice", "agent", "calendar", "focus"):
            self.assertIn(key, data)
        self.assertIn("llm", data["agent"])

    def test_audio_stream(self):
        c = client()
        with c.websocket_connect("/ws/audio") as ws:
            msg = ws.receive_json()
        self.assertEqual(msg["type"], "level")
        self.assertIn("level", msg)
        self.assertGreaterEqual(msg["level"], 0)
        self.assertLessEqual(msg["level"], 1)


if __name__ == "__main__":
    unittest.main()
