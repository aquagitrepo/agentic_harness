"""HTTP endpoints for the chat page (/chat)."""

import traceback

import harness
from errors import HarnessError
from routes import Reply, Stream, get, post


@get("/api/models")
def models(req):
    available = harness.list_models()
    return {"models": available, "default": harness.default_model(available)}


@get("/api/projects")
def projects(req):
    return {"projects": harness.list_projects()}


@post("/api/chat")
def chat(req):
    message = str(req.body.get("message") or "").strip()
    if not message:
        return Reply({"error": "Type a message first, then press Send."}, 400)
    return Stream(harness.run_turn(str(req.body.get("model") or ""), req.body.get("history"), message))


@post("/api/save-project")
def save_project(req):
    try:
        return harness.save_project(str(req.body.get("model") or ""), req.body.get("history"))
    except HarnessError as exc:
        return Reply({"error": str(exc)}, 502)
    except Exception:
        traceback.print_exc()
        return Reply({"error": "Something went wrong saving the project (details are in the server terminal)."}, 500)
