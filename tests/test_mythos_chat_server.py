"""Retained tests for chat/server.py and the review fixes in chat/harness.py (stub API, temp data dir)."""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import anthropic

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "chat"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
import server  # noqa: E402
from claude_stub import Stub  # noqa: E402


class ChatServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = Stub()

    @classmethod
    def tearDownClass(cls):
        cls.stub.close()

    def setUp(self):
        self.stub.requests.clear()
        self.stub.plan = {"agent": "writer", "mode": "answer", "steps": ["Quick answer", "Details"],
                          "needs_search": False, "queries": []}
        harness._client = anthropic.Anthropic(api_key="stub-key", base_url=self.stub.url, max_retries=0)
        self.tmp = tempfile.TemporaryDirectory()
        self._data = harness.DATA
        harness.DATA = Path(self.tmp.name)
        (harness.DATA / "projects").mkdir()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self._port = server.PORT
        server.PORT = self.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.PORT = self._port
        harness.DATA = self._data
        harness._client = None
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        base = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            base["Content-Type"] = "application/json"
        base.update(headers or {})
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=base)
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return resp.status, data

    def events(self, message):
        status, data = self.request("POST", "/api/chat", {"message": message, "history": []})
        self.assertEqual(status, 200)
        return [json.loads(line[5:]) for line in data.split("\n\n") if line.startswith("data:")]

    def test_text_plain_cross_site_post_is_refused(self):
        status, _ = self.request("POST", "/api/chat", {"message": "hi"}, {"Content-Type": "text/plain"})
        self.assertEqual(status, 403)
        self.assertEqual(self.stub.requests, [])

    def test_other_origin_is_refused(self):
        status, _ = self.request("POST", "/api/save-project", {"history": []}, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_rebinding_host_is_refused(self):
        status, _ = self.request("GET", "/api/projects", headers={"Host": "rebind.attacker.example"})
        self.assertEqual(status, 403)

    def test_invalid_body_is_a_clean_400(self):
        status, data = self.request("POST", "/api/chat", headers={"Content-Type": "application/json",
                                                                   "Content-Length": "-1"})
        self.assertEqual(status, 400)

    def test_unexpected_exception_still_ends_with_an_error_event(self):
        def boom(*args):
            yield {"type": "stage", "stage": "understand", "state": "active"}
            raise RuntimeError("unexpected")

        with mock.patch.object(harness, "run_turn", boom), mock.patch("traceback.print_exc"):
            events = self.events("hello")
        self.assertEqual(events[-1]["type"], "error")

    def test_cut_off_stream_is_an_error_not_a_done(self):
        types = [e["type"] for e in self.events("TRUNCATE please")]
        self.assertIn("token", types)
        self.assertEqual(types[-1], "error")
        self.assertNotIn("done", types)

    def test_normal_turn_ends_with_done(self):
        self.assertEqual(self.events("hello")[-1]["type"], "done")


class HarnessFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._data = harness.DATA
        harness.DATA = Path(self.tmp.name)
        (harness.DATA / "projects").mkdir()

    def tearDown(self):
        harness.DATA = self._data
        self.tmp.cleanup()

    def test_search_drops_non_http_links(self):
        fake = mock.MagicMock()
        fake.return_value.text.return_value = [
            {"title": "bad", "href": "javascript:alert(1)"}, {"title": "data", "href": "data:text/html,x"},
            {"title": "good", "href": "https://example.com"}]
        with mock.patch.object(harness, "DDGS", fake):
            self.assertEqual([r["href"] for r in harness.search_one("q")], ["https://example.com"])

    def test_writer_is_told_when_search_found_nothing(self):
        plan = {"agent": "researcher", "mode": "answer", "steps": ["A"], "queries": ["q"]}
        self.assertIn("found nothing usable", harness.writer_prompt(plan, [], searched=True))
        self.assertNotIn("found nothing usable", harness.writer_prompt(plan, [], searched=False))

    def test_plan_steps_are_single_line_unique_and_heading_free(self):
        raw = {"agent": "dev", "mode": "answer", "needs_search": False, "queries": ["x"],
               "steps": ["Setup\n## Hidden extra", "## Install", "install", "   ", "E", "F", "G"]}
        with mock.patch.object(harness, "chat_json", return_value=raw):
            plan = harness.make_plan("claude-opus-5", [], "hi")
        self.assertEqual(plan["steps"], ["Setup ## Hidden extra", "Install", "E", "F", "G"])
        self.assertTrue(all("\n" not in s and not s.startswith("#") for s in plan["steps"]))
        self.assertEqual(plan["queries"], [])

    def test_planner_sees_projects_and_full_history(self):
        harness.write_project("Paint Checker", projects_dir=harness.DATA / "projects")
        history = [{"role": r, "content": f"m{i}"} for i, r in enumerate(["user", "assistant"] * 6)]
        captured = {}

        def fake(model, system, messages, schema, step):
            captured.update(system=system, messages=messages)
            return {"agent": "writer", "mode": "answer", "steps": ["A"], "needs_search": False, "queries": []}

        with mock.patch.object(harness, "chat_json", fake):
            harness.make_plan("claude-opus-5", history, "continue my paint project")
        self.assertIn("Paint Checker", captured["system"])
        self.assertEqual(len(captured["messages"]), 13)

    def test_save_project_output_cannot_inject_frontmatter(self):
        hostile = {"name": "My --- project", "description": "d", "milestone": "m1\nstatus: shipped",
                   "data_source": "x"}
        with mock.patch.object(harness, "chat_json", return_value=hostile):
            result = harness.save_project("claude-opus-5", [{"role": "user", "content": "hi"}])
        fm = harness.parse_frontmatter(harness.read_text(harness.DATA / "projects" / Path(result["file"]).name))[0]
        self.assertEqual(fm["status"], "planning")
        self.assertEqual(fm["name"], "My --- project")


if __name__ == "__main__":
    unittest.main()
