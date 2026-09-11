"""Phase 3 voice tests (no network, no macOS side effects)."""
import base64
import os
import struct
import unittest
from unittest import mock

from agent import voice
from agent.events import EventBus


class TestVAD(unittest.TestCase):
    def test_silence(self):
        self.assertFalse(voice.energy_vad(b"\x00\x00" * 1600))

    def test_tone(self):
        pcm = voice.make_pcm16_sine(seconds=0.1)
        self.assertTrue(voice.energy_vad(pcm))

    def test_silero_absent_falls_back(self):
        with mock.patch.dict("sys.modules", {"torch": None}):
            # torch=None makes import succeed but load fail -> None
            with mock.patch("builtins.__import__", side_effect=ImportError):
                self.assertIsNone(voice.silero_vad(b"\x00" * 100))


class TestModes(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("BUTLER_TTS", "BUTLER_STT", "ELEVENLABS_API_KEY", "OPENAI_API_KEY",
                      "GROQ_API_KEY", "DEEPGRAM_API_KEY"):
                os.environ.pop(k, None)
            s = voice.voice_status()
        self.assertEqual(s["tts"], "say")
        self.assertEqual(s["stt"], "off")
        self.assertFalse(any(s["keys_set"].values()))

    def test_local_synthesize_raises(self):
        with mock.patch.dict(os.environ, {"BUTLER_TTS": "say"}):
            with self.assertRaises(RuntimeError):
                voice.synthesize("hi")

    def test_stt_off_501_shape(self):
        with mock.patch.dict(os.environ, {"BUTLER_STT": "off"}):
            with self.assertRaises(RuntimeError):
                voice.transcribe(base64.b64encode(b"1234").decode())

    def test_bad_b64(self):
        with self.assertRaises(ValueError):
            voice._decode_audio_b64("!!!not-b64!!!")


class TestDucking(unittest.TestCase):
    def test_dip_and_restore(self):
        calls = []
        ctl = voice.DuckingController(run=lambda cmd: (calls.append(cmd), "60")[1])
        with mock.patch.dict(os.environ, {"BUTLER_DUCKING": "1", "BUTLER_DUCK_LEVEL": "25"}):
            ctl.on_start({})
            ctl.on_stop({})
        joined = " ".join(" ".join(c) for c in calls)
        self.assertIn("35", joined)  # 60 - 25
        self.assertIn("60", joined)  # restored

    def test_disabled_noop(self):
        calls = []
        ctl = voice.DuckingController(run=lambda cmd: calls.append(cmd) or "60")
        with mock.patch.dict(os.environ, {"BUTLER_DUCKING": "0"}):
            ctl.on_start({})
            ctl.on_stop({})
        self.assertEqual(calls, [])

    def test_bus_wiring(self):
        bus = EventBus()
        seen = []
        ctl = voice.DuckingController(run=lambda cmd: "60")
        ctl._set = lambda level: seen.append(level)
        ctl.attach(bus)
        with mock.patch.dict(os.environ, {"BUTLER_DUCKING": "1", "BUTLER_DUCK_LEVEL": "10"}):
            bus.emit("speak.start", {})
            bus.emit("speak.stop", {})
        self.assertEqual(seen, [50, 60])


if __name__ == "__main__":
    unittest.main()
