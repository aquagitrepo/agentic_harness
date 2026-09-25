"""The session-start status must summarize data/ in a few lines and survive odd files."""

import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dashboard  # noqa: E402
import session_context  # noqa: E402


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative: str, text: str):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_empty_workspace(self):
        text = session_context.summary(self.data)
        self.assertIn("Projects: none registered", text)
        self.assertIn("Inbox: empty", text)
        self.assertNotIn("spend", text)

    def test_full_workspace_fits_in_a_few_lines(self):
        dashboard.write_project("Paint Checker", "in-progress", "classify one photo", projects_dir=self.data / "projects")
        self.write("inbox/idea.md", "Try a CNN\nmore detail")
        self.write("decisions/2026-09-01-old.md", "# Old call\n")
        self.write("decisions/2026-09-20-new.md", "# Plan on Sonnet 5\n")
        self.write("daily-logs/2026-09-24.md", "## Next Actions\n- [ ] Pick a dataset\n- [x] Done thing\n- [ ]\n")
        rows = [{"usd": 0.01}, {"usd": None}, {"usd": 0.02}, [1]]
        self.write("costs/2026-09-25.jsonl", "\n".join(map(json.dumps, rows)) + "\nnot json\n")
        text = session_context.summary(self.data, datetime.date(2026, 9, 25))
        self.assertIn("Paint Checker (in-progress): classify one photo", text)
        self.assertIn("Inbox: 1 untriaged: Try a CNN", text)
        self.assertIn("Latest decision: Plan on Sonnet 5", text)
        self.assertIn("next actions: Pick a dataset", text)
        self.assertNotIn("Done thing", text)
        self.assertIn("~$0.0300 over 3 calls", text)
        self.assertLessEqual(len(text.splitlines()), 6)

    def test_other_days_spend_is_not_counted(self):
        self.write("costs/2026-09-24.jsonl", json.dumps({"usd": 5}) + "\n")
        self.assertNotIn("spend", session_context.summary(self.data, datetime.date(2026, 9, 25)))

    def test_hook_output_survives_non_ascii_names_on_a_pipe(self):
        dashboard.write_project("Café ☕ checker", projects_dir=self.data / "projects")
        run = subprocess.run([sys.executable, str(SCRIPTS / "session_context.py"), str(self.data)],
                             capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        self.assertIn("Café ☕ checker", run.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
