"""Retained tests for the dashboard and the shared data/ helpers (temp dirs only, never the real data/)."""

import http.client
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dashboard  # noqa: E402


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._data = dashboard.DATA
        dashboard.DATA = Path(self.tmp.name)
        (dashboard.DATA / "projects").mkdir()
        (dashboard.DATA / "inbox").mkdir()

    def tearDown(self):
        dashboard.DATA = self._data
        self.tmp.cleanup()

    def project(self, name):
        return dashboard.parse_frontmatter(dashboard.read_text(dashboard.DATA / "projects" / name))[0]


class FrontmatterTest(TempData):
    def test_newlines_in_values_cannot_inject_keys(self):
        path = dashboard.write_project("x\nstatus: done", "planning", "v1\r\nstatus: shipped")
        fm = dashboard.parse_frontmatter(dashboard.read_text(path))[0]
        self.assertEqual(fm["status"], "planning")
        self.assertEqual(fm["milestone"], "v1 status: shipped")

    def test_triple_dash_inside_a_value_keeps_every_key(self):
        path = dashboard.write_project("My --- project", milestone="v1 --- basic", repo_path="projects/x")
        fm = dashboard.parse_frontmatter(dashboard.read_text(path))[0]
        self.assertEqual(fm["name"], "My --- project")
        self.assertEqual(fm["milestone"], "v1 --- basic")
        self.assertEqual(fm["repo_path"], "projects/x")

    def test_bom_and_duplicate_keys(self):
        fm, body = dashboard.parse_frontmatter("﻿---\nname: a\nstatus: planning\nstatus: done\n---\nbody")
        self.assertEqual(fm, {"name": "a", "status": "planning"})
        self.assertEqual(body, "body")

    def test_unterminated_frontmatter_is_not_parsed(self):
        self.assertEqual(dashboard.parse_frontmatter("---\nname: a\n")[0], {})

    def test_existing_project_is_never_overwritten(self):
        first = dashboard.write_project("Paint Checker", description="original notes")
        second = dashboard.write_project("paint checker!", description="new")
        self.assertEqual((first.name, second.name), ("paint-checker.md", "paint-checker-2.md"))
        self.assertIn("original notes", dashboard.read_text(first))

    def test_concurrent_creates_never_lose_a_file(self):
        barrier = threading.Barrier(8)

        def make():
            barrier.wait()
            dashboard.write_project("race")

        threads = [threading.Thread(target=make) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(list((dashboard.DATA / "projects").glob("race*.md"))), 8)

    def test_windows_reserved_names_become_real_files(self):
        for name in ("nul", "CON", "com1"):
            path = dashboard.write_project(name)
            self.assertTrue(path.name.endswith("-project.md"), path.name)
            self.assertIn(path.name, [p.name for p in (dashboard.DATA / "projects").iterdir()])

    def test_non_utf8_file_is_readable(self):
        path = dashboard.DATA / "projects" / "ansi.md"
        path.write_bytes("---\nname: caf\xe9\n---\n".encode("cp1252"))
        self.assertEqual(self.project("ansi.md")["name"], "caf�")
        self.assertIn("caf", dashboard.render_projects())


class RequestChecksTest(unittest.TestCase):
    def test_request_problem(self):
        ok = {"Host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787"}
        self.assertIsNone(dashboard.request_problem(ok, 8787, "POST"))
        self.assertIsNone(dashboard.request_problem({"Host": "localhost:8787"}, 8787, "POST"))
        self.assertTrue(dashboard.request_problem({"Host": "evil.example"}, 8787, "GET"))
        self.assertTrue(dashboard.request_problem({"Host": "127.0.0.1:8787", "Origin": "https://evil.example"}, 8787, "POST"))
        self.assertTrue(dashboard.request_problem({"Host": "127.0.0.1:8787", "Origin": "null"}, 8787, "POST"))

    def test_body_length(self):
        self.assertIsNone(dashboard.body_length({"Content-Length": "abc"}))
        self.assertIsNone(dashboard.body_length({"Content-Length": "-1"}))
        self.assertIsNone(dashboard.body_length({"Content-Length": str(dashboard.MAX_BODY + 1)}))
        self.assertEqual(dashboard.body_length({}), 0)


class DashboardHttpTest(TempData):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        self.port = self.server.server_address[1]
        self._port = dashboard.PORT
        dashboard.PORT = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        dashboard.PORT = self._port
        super().tearDown()

    def post(self, path, fields, origin=None, raw_length=None):
        body = urllib.parse.urlencode(fields).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/x-www-form-urlencoded",
                   "Content-Length": raw_length or str(len(body))}
        if origin:
            headers["Origin"] = origin
        conn.request("POST", path, body=body, headers=headers)
        status = conn.getresponse().status
        conn.close()
        return status

    def test_cross_site_post_is_refused_and_writes_nothing(self):
        self.assertEqual(self.post("/project", {"name": "evil"}, origin="https://evil.example"), 403)
        self.assertEqual(list((dashboard.DATA / "projects").iterdir()), [])

    def test_same_origin_wizard_post_creates_project(self):
        status = self.post("/project", {"name": "Paint", "status": "planning", "milestone": "one\nstatus: done",
                                        "description": "d", "data_source": "not decided"},
                           origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 303)
        fm = self.project("paint.md")
        self.assertEqual(fm["status"], "planning")
        self.assertIn("Data/input: not decided", dashboard.read_text(dashboard.DATA / "projects" / "paint.md"))

    def test_bad_content_length_is_a_clean_400(self):
        self.assertEqual(self.post("/inbox", {"text": "x"}, raw_length="-1"), 400)

    def test_dismiss_cannot_delete_gitkeep(self):
        keep = dashboard.DATA / "inbox" / ".gitkeep"
        keep.write_text("")
        self.post("/inbox/dismiss", {"file": ".gitkeep"})
        self.assertTrue(keep.exists())

    def test_rebinding_host_is_refused(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/", headers={"Host": "attacker.example"})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()


if __name__ == "__main__":
    unittest.main()
