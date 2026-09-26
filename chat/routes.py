"""The route table for the harness app server.

Each api_*.py module registers its own endpoints with @get / @post, so a new
feature never has to edit server.py. A handler takes a Request and returns one of:
- a dict: sent as JSON with status 200
- Reply(payload, status): JSON with another status
- Stream(events): an iterable of event dicts, sent as server-sent events
- Raw(data, content_type, filename): bytes, as a download when filename is set
Raising errors.HarnessError sends {"error": message} with status 400.
Every route gets the same protection in server.py: the Host and Origin checks, and
POST bodies must be JSON no larger than the route's max_body.
"""

from dataclasses import dataclass, field

DEFAULT_MAX_BODY = 1_000_000

GET: dict = {}
POST: dict = {}


@dataclass
class Request:
    path: str
    query: dict = field(default_factory=dict)  # first value of each query parameter
    body: dict = field(default_factory=dict)  # the parsed JSON body of a POST


@dataclass
class Reply:
    payload: dict
    status: int = 200


@dataclass
class Stream:
    events: object


@dataclass
class Raw:
    data: bytes
    content_type: str
    filename: str = ""


def get(path: str):
    def register(handler):
        GET[path] = handler
        return handler
    return register


def post(path: str, max_body: int = DEFAULT_MAX_BODY):
    def register(handler):
        POST[path] = (handler, max_body)
        return handler
    return register
