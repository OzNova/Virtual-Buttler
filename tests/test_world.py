"""Phase 4 world tests (no network, no macOS, mocked side effects)."""
import json
import os
import tempfile
import unittest
from unittest import mock

from agent import focus as focus_mod
from agent import home as home_mod
from agent import knowledge as know
from agent.router import route


class TestKnowledge(unittest.TestCase):
    def test_allowlist_empty(self):
        with mock.patch.dict(os.environ, {"BUTLER_DOC_PATHS": ""}):
            self.assertEqual(know.collect_documents(), [])
            self.assertEqual(know.search_docs("budget"), [])

    def test_txt_index_search_summarize(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "budget.md")
            with open(p, "w") as fh:
                fh.write("Q3 marketing budget review. The budget allocates 40k to search ads. "
                         "Timeline is September. Risks include overspend.")
            idx = os.path.join(d, "docs.jsonl")
            with mock.patch.dict(os.environ, {"BUTLER_DOC_PATHS": d, "BUTLER_DOC_INDEX": idx}):
                docs = know.collect_documents()
                self.assertEqual(len(docs), 1)
                self.assertEqual(know.write_index(docs, idx), 1)
                hits = know.search_docs("marketing budget")
                self.assertTrue(hits and hits[0]["path"].endswith("budget.md"))
                res = know.summarize_doc("marketing budget")
                self.assertIn("40k", res["summary"])

    def test_traversal_confined(self):
        with tempfile.TemporaryDirectory() as d:
            link = os.path.join(d, "link")
            try:
                os.symlink("/etc", link)
            except OSError:
                self.skipTest("symlink unavailable")
            with mock.patch.dict(os.environ, {"BUTLER_DOC_PATHS": d}):
                for doc in know.collect_documents():
                    self.assertTrue(doc["path"].startswith(d))


class TestRouterPhase4(unittest.TestCase):
    def test_summarize(self):
        d = route("summarize the Q3 marketing budget pdf")
        self.assertEqual(d.call.name, "docs.summarize")

    def test_docs_search(self):
        d = route("find the budget in my documents")
        self.assertEqual(d.call.name, "docs.search")

    def test_vision(self):
        d = route("why is this script throwing an error on my screen?")
        self.assertEqual(d.call.name, "vision.capture")

    def test_calendar(self):
        d = route("what is my next meeting?")
        self.assertEqual(d.call.name, "calendar.next")

    def test_focus(self):
        d = route("should I focus now?")
        self.assertEqual(d.call.name, "focus.check")

    def test_home_state(self):
        d = route("is the light on?")
        self.assertEqual(d.call.name, "home.state")

    def test_home_call(self):
        d = route("turn on the living room light")
        self.assertEqual(d.call.name, "home.call")
        self.assertEqual(d.call.args["service"], "turn_on")


class TestFocus(unittest.TestCase):
    def test_no_source_hint(self):
        with mock.patch.dict(os.environ, {"BUTLER_ICS_PATHS": ""}):
            with mock.patch.object(focus_mod.subprocess, "run", side_effect=OSError):
                data = focus_mod.upcoming()
        self.assertFalse(data["ok"])
        self.assertIn("hint", data)

    def test_ics_upcoming_and_focus(self):
        ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Deep work block\n"
               "DTSTART:20990101T100000\nEND:VEVENT\nEND:VCALENDAR\n")
        with tempfile.NamedTemporaryFile("w", suffix=".ics", delete=False) as fh:
            fh.write(ics)
            path = fh.name
        try:
            with mock.patch.dict(os.environ, {"BUTLER_ICS_PATHS": path}):
                data = focus_mod.upcoming()
            self.assertTrue(data["ok"])
            self.assertEqual(data["events"][0]["title"], "Deep work block")
        finally:
            os.unlink(path)


class TestHome(unittest.TestCase):
    def test_unconfigured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HASS_URL", None)
            os.environ.pop("HASS_TOKEN", None)
            self.assertIn("hint", home_mod.get_state("light.x"))
            self.assertIn("hint", home_mod.call_service("light", "turn_on", {}))


if __name__ == "__main__":
    unittest.main()
