"""Local stand-in for the Claude Messages API, for tests only.

Records every request the SDK sends and answers with canned JSON or SSE, so the
chat engine can be exercised without credentials or network. Magic words in the
last user message pick the reply: REFUSE (pre-output refusal), MIDREFUSE
(refusal after some text), TRUNCATE (stream closes without finishing), BADKEY (401).
This only proves the code handles replies shaped the way this stub shapes them;
whether the real API accepts the requests is only checked by a live run.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLAN = {"agent": "researcher", "mode": "answer", "steps": ["Quick answer", "Details"],
        "needs_search": True, "queries": ["paint defect dataset", "surface defect images"]}
SUMMARY = {"name": "Paint Checker", "description": "Checks paint photos.",
           "milestone": "Classify one photo", "data_source": "not decided yet"}


class Stub:
    def __init__(self):
        self.requests = []
        self.plan = dict(PLAN)
        self.summary = dict(SUMMARY)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                last = body["messages"][-1]["content"]
                last = last if isinstance(last, str) else json.dumps(last)
                if "BADKEY" in last or not self.headers.get("x-api-key") or not self.headers.get("anthropic-version"):
                    return self._json(401, {"type": "error", "error": {"type": "authentication_error",
                                                                         "message": "invalid x-api-key"}})
                if body.get("stream"):
                    return self._stream(body, "MIDREFUSE" in last, "TRUNCATE" in last)
                if "REFUSE" in last.split():
                    return self._json(200, self._message(body, [], "refusal"))
                props = body["output_config"]["format"]["schema"]["properties"]
                payload = stub.summary if "data_source" in props else stub.plan
                return self._json(200, self._message(body, [{"type": "text", "text": json.dumps(payload)}], "end_turn"))

            def _message(self, body, content, stop_reason):
                return {"id": "msg_stub", "type": "message", "role": "assistant", "model": body["model"],
                        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
                        "usage": {"input_tokens": 10, "output_tokens": 5}}

            def _json(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, body, refuse, truncate):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                start = self._message(body, [], None)
                events = [("message_start", {"type": "message_start", "message": start}),
                          ("content_block_start", {"type": "content_block_start", "index": 0,
                                                   "content_block": {"type": "text", "text": ""}})]
                for piece in ["## Quick answer\n", "Paint text [1].\n", "## Details\n", "More."]:
                    events.append(("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                           "delta": {"type": "text_delta", "text": piece}}))
                if not truncate:
                    events += [("content_block_stop", {"type": "content_block_stop", "index": 0}),
                               ("message_delta", {"type": "message_delta",
                                                  "delta": {"stop_reason": "refusal" if refuse else "end_turn",
                                                            "stop_sequence": None},
                                                  "usage": {"output_tokens": 12}}),
                               ("message_stop", {"type": "message_stop"})]
                for name, data in events:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                    self.wfile.flush()

        return Handler
