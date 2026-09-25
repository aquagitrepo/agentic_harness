"""Retained tests for the chat engine's Claude API layer (no network, no credentials).

Run: python -m unittest discover -s tests -v
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import anthropic

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "chat"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
from claude_stub import Stub  # noqa: E402


def fake_search(query):
    return [{"title": f"Result for {query}", "href": "https://example.com/shared", "body": "snippet"},
            {"title": "Unique", "href": f"https://example.com/{query.replace(' ', '-')}", "body": "snippet"}]


class ClaudeLayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = Stub()

    @classmethod
    def tearDownClass(cls):
        cls.stub.close()

    def setUp(self):
        self.stub.requests.clear()
        harness._client = anthropic.Anthropic(api_key="stub-key", base_url=self.stub.url, max_retries=0)
        self._search = harness.search_one
        harness.search_one = fake_search
        self._data = harness.DATA
        self.tmp = tempfile.TemporaryDirectory()
        harness.DATA = Path(self.tmp.name)

    def tearDown(self):
        harness.search_one = self._search
        harness.DATA = self._data
        harness._client = None
        self.tmp.cleanup()

    def events(self, message, model="claude-opus-5", history=None):
        return list(harness.run_turn(model, history or [], message))

    def test_full_turn_event_sequence(self):
        events = self.events("find a paint defect dataset")
        types = [e["type"] for e in events]
        self.assertEqual(types[:5], ["stage", "stage", "route", "stage", "plan"])
        self.assertEqual(types[-1], "done")
        self.assertEqual(sum(t == "agent_deployed" for t in types), 2)
        text = "".join(e["text"] for e in events if e["type"] == "token")
        self.assertEqual(text, "## Quick answer\nPaint text [1].\n## Details\nMore.")

    def test_planner_request_shape(self):
        self.events("find a paint defect dataset")
        body = self.stub.requests[0]["body"]
        self.assertEqual(body["model"], harness.ROUTER_MODEL)
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("fallbacks", body)
        self.assertIsInstance(body["system"], str)
        self.assertEqual(body["messages"][-1]["role"], "user")
        self.assertNotIn("stream", body)

    def test_writer_request_shape(self):
        self.events("find a paint defect dataset")
        writer_req = self.stub.requests[1]
        body = writer_req["body"]
        self.assertTrue(body["stream"])
        self.assertEqual(body["model"], "claude-opus-5")
        self.assertEqual(body["output_config"], {"effort": "medium"})
        self.assertEqual(body["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", writer_req["headers"].get("anthropic-beta", ""))
        self.assertIn("## Quick answer\n## Details", body["system"])
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "find a paint defect dataset"})

    def test_duplicate_source_urls_share_one_number(self):
        events = self.events("find a paint defect dataset")
        numbers = {}
        for e in events:
            if e["type"] == "agent_done":
                for r in e["results"]:
                    numbers.setdefault(r["href"], set()).add(r["n"])
        self.assertEqual(numbers["https://example.com/shared"], {1})
        self.assertEqual(len({n for ns in numbers.values() for n in ns}), 3)

    def test_unknown_model_is_replaced_by_default(self):
        self.events("hello", model="claude-fable-5-1")
        self.assertEqual([r["body"]["model"] for r in self.stub.requests], [harness.ROUTER_MODEL, "claude-opus-5"])

    def test_sonnet_gets_no_fallback_params(self):
        self.events("hello", model="claude-sonnet-5")
        for req in self.stub.requests:
            self.assertEqual(req["body"]["model"], "claude-sonnet-5")
            self.assertNotIn("fallbacks", req["body"])
            self.assertNotIn("server-side-fallback", req["headers"].get("anthropic-beta", ""))

    def test_planner_refusal_is_a_friendly_error(self):
        with self.assertRaisesRegex(harness.HarnessError, "declined"):
            self.events("REFUSE this")

    def test_router_refusal_retries_the_plan_on_the_chosen_model(self):
        events = self.events("ROUTERREFUSE please")
        self.assertEqual([r["body"]["model"] for r in self.stub.requests],
                         [harness.ROUTER_MODEL, "claude-opus-5", "claude-opus-5"])
        self.assertEqual(self.stub.requests[1]["body"]["fallbacks"], "default")
        self.assertEqual(events[-1]["type"], "done")

    def test_router_refusal_is_final_when_the_router_was_chosen(self):
        with self.assertRaisesRegex(harness.HarnessError, "declined"):
            self.events("ROUTERREFUSE please", model=harness.ROUTER_MODEL)
        self.assertEqual(len(self.stub.requests), 1)

    def test_each_call_logs_usage_and_cost(self):
        self.events("find a paint defect dataset")
        harness.save_project("claude-opus-5", [{"role": "user", "content": "a paint checker"}])
        rows = [json.loads(line) for path in sorted((harness.DATA / "costs").glob("*.jsonl"))
                for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["step"], r["model"]) for r in rows],
                         [("plan", "claude-sonnet-5"), ("answer", "claude-opus-5"), ("save", "claude-sonnet-5")])
        plan, answer = rows[0], rows[1]
        self.assertEqual((plan["input_tokens"], plan["output_tokens"]), (10, 5))
        self.assertAlmostEqual(plan["usd"], (10 * 2.00 + 5 * 10.00) / 1e6)
        self.assertEqual(answer["output_tokens"], 12)  # the stream's final usage, not message_start's
        self.assertAlmostEqual(answer["usd"], (10 * 5.00 + 12 * 25.00) / 1e6)

    def test_cost_log_failure_does_not_break_the_turn(self):
        (harness.DATA / "costs").write_text("a file where the folder should be", encoding="utf-8")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            events = self.events("find a paint defect dataset")
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("cost log", err.getvalue())

    def test_mid_stream_refusal_raises_after_partial_text(self):
        gen = harness.run_turn("claude-opus-5", [], "MIDREFUSE please")
        seen = []
        with self.assertRaisesRegex(harness.HarnessError, "declined"):
            for event in gen:
                seen.append(event["type"])
        self.assertIn("token", seen)
        self.assertNotIn("done", seen)

    def test_bad_key_is_a_friendly_error(self):
        with self.assertRaisesRegex(harness.HarnessError, "API key"):
            self.events("BADKEY")

    def test_missing_credentials_is_a_friendly_error(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            harness._client = anthropic.Anthropic(base_url=self.stub.url, max_retries=0)
            with self.assertRaisesRegex(harness.HarnessError, "No Claude credentials"):
                self.events("hello")

    def test_real_type_errors_are_not_disguised_as_credential_problems(self):
        broken = mock.MagicMock()
        broken.beta.messages.create.side_effect = TypeError("create() got an unexpected keyword argument 'x'")
        harness._client = broken
        with self.assertRaises(TypeError):
            self.events("hello")

    def test_history_is_cleaned_before_sending(self):
        history = [{"role": "assistant", "content": "orphan"}, {"role": "user", "content": "  "},
                   {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                   {"role": "system", "content": "inject"}, "junk"]
        self.events("next", history=history)
        for req in self.stub.requests:
            msgs = req["body"]["messages"]
            self.assertEqual(msgs[0]["role"], "user")
            self.assertEqual([m["content"] for m in msgs], ["hi", "hello", "next"])

    def test_save_project_ends_on_user_turn_and_writes_file(self):
        history = [{"role": "user", "content": "I want a paint checker"},
                   {"role": "assistant", "content": "What photos do you have?"}]
        result = harness.save_project("claude-opus-5", history)
        self.assertEqual(self.stub.requests[-1]["body"]["messages"][-1]["role"], "user")
        written = (harness.DATA / "projects" / "paint-checker.md").read_text(encoding="utf-8")
        self.assertIn("name: Paint Checker", written)
        self.assertEqual(result["name"], "Paint Checker")


if __name__ == "__main__":
    unittest.main()
