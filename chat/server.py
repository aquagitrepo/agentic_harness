"""The harness app server: every page and API on one local port.

Pages: /chat (also at /) and /studio. The endpoints live in the api_*.py modules,
which register themselves in routes.py. Everything here
is shared protection: only this machine's own pages may call the server (Host and
Origin checks), POST bodies must be JSON under each route's size limit, and no
other website may frame a page (so it can't trick you into clicking "Approve").

Run: python chat/server.py  then open http://127.0.0.1:8788
"""

import json
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import harness  # noqa: F401  (sets up the import path for scripts/)
import routes
from dashboard import request_problem
from errors import HarnessError

import api_chat  # noqa: F401,E402  (each api module registers its routes on import)
import api_studio  # noqa: F401,E402

STATIC = Path(__file__).resolve().parent / "static"
PAGES = {"/": "chat.html", "/chat": "chat.html", "/studio": "studio.html"}
ASSET = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9_-]*\.(?:js|css|svg|png|ico|webmanifest))$")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".ico": "image/x-icon", ".webmanifest": "application/manifest+json"}
PORT = 8788


class Handler(BaseHTTPRequestHandler):
    server_version = "Harness/2.0"

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, data: bytes, content_type: str, filename: str = ""):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:120] or "download"
            self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.end_headers()
        self.wfile.write(data)

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
            except HarnessError as exc:
                self._sse({"type": "error", "message": str(exc)})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                raise
            except Exception:  # headers are already sent: anything uncaught would end the stream silently
                traceback.print_exc()
                self._sse({"type": "error", "message": "Something went wrong on the harness server "
                                                       "(details are in its terminal). Try again."})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the page stopped listening (Stop button, reload or closed tab)
        finally:
            close = getattr(events, "close", None)
            if close:
                close()  # runs the generator's cleanup (kill a running program, save a consistent session)

    def _respond(self, result):
        if isinstance(result, routes.Stream):
            self._stream(result.events)
        elif isinstance(result, routes.Raw):
            self._raw(result.data, result.content_type, result.filename)
        elif isinstance(result, routes.Reply):
            self._json(result.payload, result.status)
        else:
            self._json(result)

    def _call(self, handler, req):
        try:
            result = handler(req)
        except HarnessError as exc:
            self._json({"error": str(exc)}, 400)
            return
        except Exception:
            traceback.print_exc()
            self._json({"error": "Something went wrong on the harness server (details are in its terminal)."}, 500)
            return
        self._respond(result)

    def _refused(self, method: str) -> bool:
        problem = request_problem(self.headers, PORT, method)
        if not problem and method == "POST" and not self.headers.get("Content-Type", "").startswith("application/json"):
            problem = "expected a JSON request"
        if problem:
            self._json({"error": f"Refused: {problem}"}, 403)
        return bool(problem)

    def _query(self) -> dict:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return {key: values[0] for key, values in query.items()}

    def _static(self, path: str) -> bool:
        name = PAGES.get(path)
        if name is None:
            match = ASSET.match(path)
            name = match.group(1) if match else None
        target = STATIC / name if name else None
        if target is None or not target.is_file():
            return False
        self._raw(target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        return True

    def do_GET(self):
        if self._refused("GET"):
            return
        path = urllib.parse.urlsplit(self.path).path
        handler = routes.GET.get(path)
        if handler:
            self._call(handler, routes.Request(path, self._query()))
        elif not self._static(path):
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self._refused("POST"):
            return
        path = urllib.parse.urlsplit(self.path).path
        handler, max_body = routes.POST.get(path, (None, routes.DEFAULT_MAX_BODY))
        body = self._body(max_body)
        if body is None:
            self._json({"error": "The request body was missing, too large, or not valid JSON."}, 400)
            return
        if handler is None:
            self._json({"error": "not found"}, 404)
            return
        self._call(handler, routes.Request(path, self._query(), body))

    def _body(self, max_body: int):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if not 0 <= length <= max_body:
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        httpd.daemon_threads = True
        print(f"Harness is running at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
