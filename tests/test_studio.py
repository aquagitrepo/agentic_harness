"""Studio engine: interview, plan gate, live build and run, against a scripted Claude (no network, no key)."""

import http.client
import json
import os
import sys
import tempfile
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
import studio  # noqa: E402
from studio_stub import ScriptedClaude, text, tool  # noqa: E402

BRIEF = tool("update_brief", name="Photo Sorter", goal="Sort photos into folders by date", confidence={"goal": 5})
QUESTION = tool("ask_user", question="Where do the photos come from?", why="Decides what the tool reads.",
                options=[{"label": "A folder on this PC", "detail": "Recommended: simplest"}, {"label": "My phone"}])
PLAN = tool("propose_plan", summary="Sort photos by date", steps=["Write the sorter", "Try it"], files=["sort.py"],
            run="python sort.py")
CODE = 'import os\nprint("hello")\nprint("key visible" if os.environ.get("ANTHROPIC_API_KEY") else "key hidden")\n'


class StudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claude = ScriptedClaude()

    @classmethod
    def tearDownClass(cls):
        cls.claude.close()

    def setUp(self):
        self.claude.requests.clear()
        self.claude.replies.clear()
        harness._client = anthropic.Anthropic(api_key="stub-key", base_url=self.claude.url, max_retries=0)
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (harness.DATA, studio.DATA, studio.PROJECTS, studio.PREVIEW_INTERVAL)
        harness.DATA = studio.DATA = Path(self.tmp.name) / "data"
        studio.PROJECTS = Path(self.tmp.name) / "projects"
        self.session = studio.new_session("claude-opus-5")

    def tearDown(self):
        harness.DATA, studio.DATA, studio.PROJECTS, studio.PREVIEW_INTERVAL = self.saved
        harness._client = None
        self.tmp.cleanup()

    def turn(self, message, approve=False):
        return list(studio.run_turn(self.session["id"], message, approve=approve))

    def last_user_content(self):
        return self.claude.requests[-1]["body"]["messages"][-1]["content"]

    def to_plan(self):
        self.claude.queue(text("Nice idea."), BRIEF, QUESTION)
        self.turn("I want to sort my photos")
        self.claude.queue(PLAN)
        self.turn("A folder on this PC")

    def build(self, *blocks):
        self.to_plan()
        self.claude.queue(*blocks)
        self.claude.queue(text("Done."))
        return self.turn("Build it.", approve=True)

    def test_first_message_updates_the_brief_and_asks_one_question(self):
        self.claude.queue(text("Nice idea."), BRIEF, QUESTION)
        events = self.turn("I want to sort my photos")
        types = [e["type"] for e in events]
        self.assertIn("brief", types)
        question = next(e for e in events if e["type"] == "question")
        self.assertEqual([o["label"] for o in question["options"]], ["A folder on this PC", "My phone"])
        self.assertEqual(events[-1], {"type": "turn_end", "reason": "question"})
        saved = studio.load(self.session["id"])
        self.assertEqual(saved["brief"]["name"], "Photo Sorter")
        self.assertEqual(saved["brief"]["confidence"], {"goal": 5})
        self.assertEqual(saved["pending"]["kind"], "question")

    def test_request_uses_caching_eager_streaming_and_fallbacks(self):
        self.claude.queue(text("Hi."))
        self.turn("hello")
        request = self.claude.requests[0]
        body = request["body"]
        self.assertEqual(body["model"], "claude-opus-5")
        self.assertEqual(body["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["output_config"], {"effort": "high"})
        self.assertEqual(body["fallbacks"], "default")
        self.assertIn(harness.FALLBACK_BETA, request["headers"].get("anthropic-beta", ""))
        self.assertEqual(body["system"], studio.SYSTEM)
        self.assertTrue(body["stream"])
        self.assertEqual({t["name"] for t in body["tools"]}, {t["name"] for t in studio.TOOLS})
        self.assertTrue(all(t["eager_input_streaming"] for t in body["tools"]))

    def test_the_answer_goes_back_as_the_question_tool_result(self):
        self.to_plan()
        content = self.claude.requests[1]["body"]["messages"][-1]["content"]
        self.assertEqual([(c["type"], c["tool_use_id"]) for c in content],
                         [("tool_result", "toolu_1_1"), ("tool_result", "toolu_1_2")])
        self.assertEqual(content[1]["content"], "The user answered: A folder on this PC")
        replayed = self.claude.requests[1]["body"]["messages"][-2]
        self.assertEqual(replayed["role"], "assistant")
        self.assertEqual([b["type"] for b in replayed["content"]], ["text", "tool_use", "tool_use"])

    def test_nothing_is_built_before_the_plan_is_approved(self):
        self.claude.queue(tool("write_file", path="sort.py", content="print(1)"))
        self.claude.queue(text("Okay, planning first."))
        events = self.turn("just build it")
        self.assertTrue(any(e["type"] == "tool_error" and "Not yet" in e["message"] for e in events))
        result = self.last_user_content()[0]
        self.assertTrue(result["is_error"])
        self.assertFalse(studio.PROJECTS.exists())

    def test_approval_creates_the_project_folder_and_record(self):
        events = self.build(text("Building."))
        self.assertIn({"type": "phase", "phase": "build", "slug": "photo-sorter"}, events)
        self.assertTrue((studio.PROJECTS / "photo-sorter").is_dir())
        record = (studio.DATA / "projects" / "photo-sorter.md").read_text(encoding="utf-8")
        self.assertIn("repo_path: projects/photo-sorter", record)
        answer = self.claude.requests[2]["body"]["messages"][-1]["content"][-1]
        self.assertIn("approved the plan", answer["content"])

    def test_file_streams_live_then_lands_on_disk(self):
        studio.PREVIEW_INTERVAL = 0
        events = self.build(tool("write_file", path="sort.py", content=CODE, step=1))
        previews = [e["content"] for e in events if e["type"] == "file_delta"]
        self.assertGreater(len(previews), 2)
        self.assertTrue(any(0 < len(p) < len(CODE) for p in previews))  # partial code, before the string closed
        self.assertEqual(previews[-1], CODE)
        self.assertIn({"type": "file_done", "path": "sort.py", "lines": 3, "step": 1}, events)
        self.assertEqual((studio.PROJECTS / "photo-sorter" / "sort.py").read_text(encoding="utf-8"), CODE)

    def test_paths_outside_the_project_are_refused(self):
        events = self.build(tool("write_file", path="../escape.py", content="x"),
                            tool("write_file", path="C:/escape.py", content="x"))
        self.assertEqual(sum(e["type"] == "tool_error" for e in events), 2)
        self.assertFalse((studio.PROJECTS / "escape.py").exists())

    def test_run_streams_output_and_hides_api_keys(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-secret"}):
            events = self.build(tool("write_file", path="sort.py", content=CODE),
                                tool("run_python", path="sort.py", step=2))
        output = "".join(e["text"] for e in events if e["type"] == "run_output")
        self.assertIn("hello", output)
        self.assertIn("key hidden", output)
        done = next(e for e in events if e["type"] == "run_done")
        self.assertEqual((done["exit_code"], done["timed_out"]), (0, False))
        result = self.claude.requests[-1]["body"]["messages"][-1]["content"][-1]
        self.assertIn("Exit code 0", result["content"])

    def test_a_program_that_hangs_is_stopped(self):
        with mock.patch.object(studio, "RUN_TIMEOUT", 1):
            events = self.build(tool("write_file", path="loop.py", content="import time\nwhile True:\n    time.sleep(0.1)\n"),
                                tool("run_python", path="loop.py"))
        done = next(e for e in events if e["type"] == "run_done")
        self.assertTrue(done["timed_out"])

    def test_cost_is_logged_and_totalled(self):
        self.claude.queue(text("Hi."))
        events = self.turn("hello")
        cost = next(e for e in events if e["type"] == "cost")
        self.assertAlmostEqual(cost["session_usd"], (100 * 5.00 + 50 * 25.00) / 1e6)
        rows = [json.loads(line) for path in (harness.DATA / "costs").glob("*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["step"] for r in rows], ["studio"])
        self.assertAlmostEqual(studio.load(self.session["id"])["cost_usd"], cost["session_usd"])

    def test_round_limit_pauses_and_the_next_message_resumes_cleanly(self):
        with mock.patch.object(studio, "MAX_ROUNDS", 2):
            self.claude.queue(tool("list_files"))
            self.claude.queue(tool("list_files"))
            events = self.turn("look around")
        self.assertEqual(events[-1], {"type": "turn_end", "reason": "limit"})
        self.claude.queue(text("Continuing."))
        self.turn("keep going")
        content = self.last_user_content()
        self.assertEqual([c["type"] for c in content], ["tool_result", "text"])
        self.assertEqual(content[0]["tool_use_id"], "toolu_2_0")

    def test_a_refusal_is_reported_and_the_history_stays_valid(self):
        self.claude.queue(tool("write_file", path="x.py", content="x"), stop_reason="refusal")
        with self.assertRaisesRegex(harness.HarnessError, "declined"):
            self.turn("something")
        self.claude.queue(text("Sure."))
        self.turn("try something else")
        content = self.last_user_content()
        self.assertEqual((content[0]["type"], content[0]["tool_use_id"], content[0]["is_error"]),
                         ("tool_result", "toolu_1_0", True))

    def test_bad_session_ids_are_rejected(self):
        for bad in ("../../etc/passwd", "", None, "20260925-000000-zzzz"):
            with self.assertRaises(harness.HarnessError):
                studio.load(bad)
            with self.assertRaises(harness.HarnessError):
                list(studio.run_turn(bad, "hi"))


class StudioServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claude = ScriptedClaude()

    @classmethod
    def tearDownClass(cls):
        cls.claude.close()

    def setUp(self):
        harness._client = anthropic.Anthropic(api_key="stub-key", base_url=self.claude.url, max_retries=0)
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (harness.DATA, studio.DATA, studio.PROJECTS, server.PORT)
        harness.DATA = studio.DATA = Path(self.tmp.name) / "data"
        studio.PROJECTS = Path(self.tmp.name) / "projects"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        server.PORT = self.httpd.server_address[1]
        import threading
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        harness.DATA, studio.DATA, studio.PROJECTS, server.PORT = self.saved
        harness._client = None
        self.tmp.cleanup()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=20)
        headers = {"Host": f"127.0.0.1:{server.PORT}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        conn.close()
        return res.status, res.getheader("Content-Type"), data

    def test_page_session_and_streamed_turn(self):
        status, ctype, page = self.request("GET", "/studio")
        self.assertEqual(status, 200)
        self.assertIn("Harness Studio", page)
        status, _, created = self.request("POST", "/api/studio/new", {"model": "claude-sonnet-5"})
        session = json.loads(created)
        self.assertEqual((status, session["model"], session["phase"]), (200, "claude-sonnet-5", "discover"))
        self.claude.queue(text("Tell me more."), QUESTION)
        status, ctype, stream = self.request("POST", "/api/studio/message", {"id": session["id"], "message": "hi"})
        self.assertTrue(ctype.startswith("text/event-stream"))
        events = [json.loads(line[5:]) for line in stream.split("\n\n") if line.startswith("data:")]
        self.assertEqual(events[-1], {"type": "turn_end", "reason": "question"})
        status, _, listed = self.request("GET", "/api/studio/sessions")
        self.assertEqual(json.loads(listed)["sessions"][0]["id"], session["id"])
        status, _, missing = self.request("GET", "/api/studio/session?id=nope")
        self.assertEqual(status, 404)

    def test_bad_session_id_streams_an_error_event(self):
        status, ctype, stream = self.request("POST", "/api/studio/message", {"id": "../x", "message": "hi"})
        self.assertIn('"type": "error"', stream)


if __name__ == "__main__":
    unittest.main()
