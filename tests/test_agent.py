"""Phase 1 agent tests (stdlib only, no server, no macOS side effects)."""
import unittest

from agent.router import route
from agent.tools import (build_search_url, build_shopping_url, clamp_volume,
                         is_blocked_terminal, list_schemas, sanitize_filename)


class TestTools(unittest.TestCase):
    def test_volume_clamp(self):
        self.assertEqual(clamp_volume(200), 100)
        self.assertEqual(clamp_volume(-5), 0)
        self.assertEqual(clamp_volume("40"), 40)

    def test_terminal_blocklist(self):
        self.assertTrue(is_blocked_terminal("rm -rf / in the terminal"))
        self.assertFalse(is_blocked_terminal("ls -la"))

    def test_filename(self):
        self.assertEqual(sanitize_filename("Reports"), "Reports")
        self.assertIsNone(sanitize_filename("../../etc"))
        self.assertIsNone(sanitize_filename("a/b"))
        self.assertIsNone(sanitize_filename(""))

    def test_urls(self):
        self.assertIn("trendyol.com", build_shopping_url("trendyol", "iphone kilif"))
        self.assertIn("tbm=isch", build_search_url("fox", "images"))
        self.assertIn("youtube.com", build_search_url("x", "video"))

    def test_schemas(self):
        names = {s["name"] for s in list_schemas()}
        self.assertIn("system.volume", names)
        self.assertIn("terminal.run", names)


class TestRouter(unittest.TestCase):
    def test_telemetry(self):
        d = route("system check")
        self.assertEqual(d.call.name, "system.telemetry")

    def test_volume(self):
        d = route("set volume to 40")
        self.assertEqual(d.call.name, "system.volume")
        self.assertEqual(d.call.args["level"], 40)

    def test_create_preserves_case(self):
        d = route("create a folder named MyReports")
        self.assertEqual(d.call.name, "files.create")
        self.assertEqual(d.call.args["name"], "MyReports")

    def test_create_traversal_refused(self):
        d = route("create a folder named ../../x")
        self.assertEqual(d.call.name, "chat.reply")

    def test_terminal_blocked(self):
        d = route("run rm -rf / in the terminal")
        self.assertNotEqual(d.call.name, "terminal.run")

    def test_domain(self):
        d = route("open github.com")
        self.assertEqual(d.call.name, "web.open_domain")

    def test_video_widget(self):
        d = route("latest taylor swift video")
        self.assertEqual(d.call.name, "web.search")
        self.assertEqual(d.widget["kind"], "video")


if __name__ == "__main__":
    unittest.main()
