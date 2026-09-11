"""Phase 2 LLM caller tests (mocked HTTP, no network)."""
import io
import json
import os
import unittest
from unittest import mock

from agent import llm
from agent.decide import decide
from agent.tools import ToolCall


def _resp(payload: dict):
    m = mock.MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


class TestOllamaParsing(unittest.TestCase):
    def test_tool_call(self):
        payload = {"message": {"tool_calls": [
            {"function": {"name": "system.volume", "arguments": {"level": 20}}}]},
                   "done": True}
        with mock.patch.object(llm.urllib.request, "urlopen", return_value=_resp(payload)):
            out = llm.ollama_tool_call("quieter")
        self.assertEqual(out["call"], ToolCall("system.volume", {"level": 20}))

    def test_text(self):
        payload = {"message": {"content": "Hello, sir."}, "done": True}
        with mock.patch.object(llm.urllib.request, "urlopen", return_value=_resp(payload)):
            out = llm.ollama_tool_call("hi")
        self.assertEqual(out, {"text": "Hello, sir."})

    def test_unknown_tool_rejected(self):
        payload = {"message": {"tool_calls": [
            {"function": {"name": "nope.does", "arguments": {}}}]}, "done": True}
        with mock.patch.object(llm.urllib.request, "urlopen", return_value=_resp(payload)):
            out = llm.ollama_tool_call("hi")
        self.assertIsNone(out)


class TestGeminiParsing(unittest.TestCase):
    def test_function_call(self):
        payload = {"candidates": [{"content": {"parts": [
            {"functionCall": {"name": "system.mute", "args": {"muted": True}}}]}}]}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
            with mock.patch.object(llm.urllib.request, "urlopen", return_value=_resp(payload)):
                out = llm.gemini_tool_call("mute")
        self.assertEqual(out["call"], ToolCall("system.mute", {"muted": True}))

    def test_text(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "Of course, sir."}]}}]}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
            with mock.patch.object(llm.urllib.request, "urlopen", return_value=_resp(payload)):
                out = llm.gemini_tool_call("hi")
        self.assertEqual(out, {"text": "Of course, sir."})

    def test_no_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            self.assertIsNone(llm.gemini_tool_call("hi"))


class TestDecide(unittest.TestCase):
    def test_off_falls_back(self):
        with mock.patch.dict(os.environ, {"AGENT_LLM": "off"}):
            d = decide("set volume to 40")
        self.assertEqual(d.call.name, "system.volume")

    def test_llm_tool_used(self):
        with mock.patch.dict(os.environ, {"AGENT_LLM": "ollama"}):
            with mock.patch.object(llm, "ollama_tool_call",
                                   return_value={"call": ToolCall("system.volume", {"level": 20})}):
                d = decide("a bit quieter", [])
        self.assertEqual(d.call.args["level"], 20)
        self.assertIn("20", d.speak)

    def test_llm_text_used(self):
        with mock.patch.dict(os.environ, {"AGENT_LLM": "gemini"}):
            with mock.patch.object(llm, "gemini_tool_call",
                                   return_value={"text": "At once, sir."}):
                d = decide("hello", [])
        self.assertEqual(d.call.name, "chat.reply")
        self.assertEqual(d.speak, "At once, sir.")

    def test_llm_failure_falls_back(self):
        with mock.patch.dict(os.environ, {"AGENT_LLM": "ollama"}):
            with mock.patch.object(llm, "ollama_tool_call", side_effect=TimeoutError):
                d = decide("set volume to 40", [])
        self.assertEqual(d.call.name, "system.volume")


if __name__ == "__main__":
    unittest.main()
