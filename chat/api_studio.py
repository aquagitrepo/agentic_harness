"""HTTP endpoints for Harness Studio (/studio)."""

import studio
from errors import HarnessError
from routes import Reply, Stream, get, post


@get("/api/studio/sessions")
def sessions(req):
    return {"sessions": studio.list_sessions()}


@get("/api/studio/session")
def session(req):
    try:
        return studio.public(studio.load(req.query.get("id", "")))
    except HarnessError as exc:
        return Reply({"error": str(exc)}, 404)


@get("/api/studio/file")
def file(req):
    try:
        return studio.read_for_ui(req.query.get("id", ""), req.query.get("path", ""))
    except HarnessError as exc:
        return Reply({"error": str(exc)}, 404)


@post("/api/studio/new")
def new(req):
    return studio.public(studio.new_session(str(req.body.get("model") or "")))


@post("/api/studio/message")
def message(req):
    body = req.body
    return Stream(studio.run_turn(str(body.get("id") or ""), body.get("message"), body.get("model") or None,
                                  bool(body.get("approve"))))
