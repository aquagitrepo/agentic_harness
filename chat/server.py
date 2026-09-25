"""Harness chat server: serves the chat UI and streams agent events over SSE.

Run: python chat/server.py  then open http://127.0.0.1:8788
"""

import json
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import harness
import studio
from dashboard import body_length, request_problem

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/styles.css": ("styles.css", "text/css"),
    "/studio": ("studio.html", "text/html"),
    "/studio.js": ("studio.js", "text/javascript"),
    "/studio.css": ("studio.css", "text/css"),
}
PORT = 8788


class Handler(BaseHTTPRequestHandler):
    server_version = "HarnessChat/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = body_length(self.headers)
        if length is None:
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _refused(self, method: str) -> bool:
        problem = request_problem(self.headers, PORT, method)
        if not problem and method == "POST" and not self.headers.get("Content-Type", "").startswith("application/json"):
            problem = "expected a JSON request"
        if problem:
            self._json({"error": f"Refused: {problem}"}, 403)
        return bool(problem)

    def _sse(self, event: dict):
        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _stream(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            try:
                for event in events:
                    self._sse(event)
            except harness.HarnessError as exc:
                self._sse({"type": "error", "message": str(exc)})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                raise
            except Exception:  # headers are already sent: anything uncaught would end the stream silently
                traceback.print_exc()
                self._sse({"type": "error", "message": "Something went wrong on the harness server "
                                                       "(details are in its terminal). Try again."})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        if self._refused("GET"):
            return
        path = self.path.split("?", 1)[0]
        if path in STATIC_FILES:
            name, ctype = STATIC_FILES[path]
            data = (STATIC / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/models":
            models = harness.list_models()
            self._json({"models": models, "default": harness.default_model(models)})
        elif path == "/api/projects":
            self._json({"projects": harness.list_projects()})
        elif path == "/api/studio/sessions":
            self._json({"sessions": studio.list_sessions()})
        elif path in ("/api/studio/session", "/api/studio/file"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            sid = (query.get("id") or [""])[0]
            try:
                if path == "/api/studio/session":
                    self._json(studio.public(studio.load(sid)))
                else:
                    self._json(studio.read_for_ui(sid, (query.get("path") or [""])[0]))
            except harness.HarnessError as exc:
                self._json({"error": str(exc)}, 404)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self._refused("POST"):
            return
        body = self._body()
        if body is None:
            self._json({"error": "The request body was missing, too large, or not valid JSON."}, 400)
            return
        model = str(body.get("model") or "")
        history = body.get("history")

        if self.path == "/api/chat":
            message = str(body.get("message") or "").strip()
            if not message:
                self._json({"error": "Type a message first, then press Send."}, 400)
                return
            self._stream(harness.run_turn(model, history, message))

        elif self.path == "/api/studio/new":
            self._json(studio.public(studio.new_session(model)))

        elif self.path == "/api/studio/message":
            self._stream(studio.run_turn(str(body.get("id") or ""), body.get("message"), model or None,
                                         bool(body.get("approve"))))

        elif self.path == "/api/save-project":
            try:
                self._json(harness.save_project(model, history))
            except harness.HarnessError as exc:
                self._json({"error": str(exc)}, 502)
            except Exception:
                traceback.print_exc()
                self._json({"error": "Something went wrong saving the project (details are in the server terminal)."}, 500)
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        httpd.daemon_threads = True
        print(f"Harness chat at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
