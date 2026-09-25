"""Scripted stand-in for the Claude Messages API's streaming tool use, for Studio tests only.

A test queues the replies it wants, in order; each request pops the next one and streams
it back as SSE shaped the way the API streams tool use, with tool inputs arriving as
input_json_delta chunks so the Studio's live file preview is exercised too. Tool-use ids
are toolu_<request number>_<block index>. This only proves the Studio handles replies
shaped like these; whether the real API accepts its requests is only checked by a live run.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def text(value):
    return {"type": "text", "text": value}


def tool(tool_name, /, **inputs):
    return {"type": "tool_use", "name": tool_name, "input": inputs}


class ScriptedClaude:
    def __init__(self):
        self.requests = []
        self.replies = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def queue(self, *blocks, stop_reason=None):
        self.replies.append((list(blocks), stop_reason))

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def send(self, name, data):
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append({"headers": dict(self.headers), "body": body})
                n = len(stub.requests)
                blocks, stop = stub.replies.pop(0) if stub.replies else ([text("(no scripted reply)")], None)
                stop = stop or ("tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.send("message_start", {"type": "message_start", "message": {
                    "id": f"msg_{n}", "type": "message", "role": "assistant", "model": body["model"], "content": [],
                    "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": 1}}})
                for i, block in enumerate(blocks):
                    if block["type"] == "text":
                        self.send("content_block_start", {"type": "content_block_start", "index": i,
                                                          "content_block": {"type": "text", "text": ""}})
                        half = len(block["text"]) // 2
                        for piece in (block["text"][:half], block["text"][half:]):
                            self.send("content_block_delta", {"type": "content_block_delta", "index": i,
                                                              "delta": {"type": "text_delta", "text": piece}})
                    else:
                        self.send("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                            "type": "tool_use", "id": f"toolu_{n}_{i}", "name": block["name"], "input": {}}})
                        raw = json.dumps(block["input"])
                        for start in range(0, len(raw), 16):
                            self.send("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                                "type": "input_json_delta", "partial_json": raw[start:start + 16]}})
                    self.send("content_block_stop", {"type": "content_block_stop", "index": i})
                self.send("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                            "usage": {"output_tokens": 50}})
                self.send("message_stop", {"type": "message_stop"})

        return Handler
