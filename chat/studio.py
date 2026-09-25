"""Harness Studio: understand the user's project with them, then build it live.

Each user message runs one Claude tool-use loop. The model keeps a project brief
current (update_brief), asks one question at a time (ask_user), proposes a first
version (propose_plan), and once the user approves, writes and runs Python inside
projects/<slug>/. Every step streams to the UI as an event, including file
contents while they are being written. Sessions persist to data/studio/<id>.json
so a project can be picked up later.
"""

import datetime
import importlib.util
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import anthropic
from jiter import from_json

import harness
from dashboard import DATA, ROOT, one_line, slugify, write_project

PROJECTS = ROOT / "projects"
EFFORT = "high"
MAX_TOKENS = 64000
MAX_ROUNDS = 30  # Claude calls per user message, so a fix-and-retry loop can't run away with the bill
RUN_TIMEOUT = 60
MAX_FILE_BYTES = 200_000
MAX_READ_CHARS = 60_000
MAX_OUTPUT_CHARS = 8_000
MAX_STREAMED_LINES = 2_000
PREVIEW_INTERVAL = 0.15  # seconds between live previews of a file being written
BRIEF_FIELDS = ("goal", "users", "first_version", "inputs", "constraints")
SESSION_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
# Extra packages generated code may use, by import name, when this interpreter has them.
OPTIONAL_PACKAGES = {"numpy": "numpy", "pandas": "pandas", "requests": "requests", "httpx": "httpx",
                     "matplotlib": "matplotlib", "Pillow": "PIL", "lxml": "lxml", "pypdf": "pypdf",
                     "openpyxl": "openpyxl", "beautifulsoup4": "bs4", "flask": "flask", "scikit-learn": "sklearn"}
INSTALLED = [name for name, module in OPTIONAL_PACKAGES.items() if importlib.util.find_spec(module)]

SYSTEM = f"""You are Harness Studio: a patient senior engineer who helps someone turn an idea into working software, live, in their own project folder. They may be a beginner, so use plain language and short sentences, and explain any technical term in a few words the first time.

You work in three phases.

1. Discover: understand what they actually want before building anything.
- After each user message, call update_brief with what you learned (only the fields that changed) and your confidence in each field.
- Then ask the one question whose answer would most change what you build, with ask_user: 2 to 4 concrete options, a one-line reason in `why`, and the option you'd recommend first with its reason in its detail.
- Don't ask about things you can sensibly default. Assume them, record the assumption in the brief with confidence 3, and move on. Three to six questions is usually enough.

2. Plan: once the goal, the first version and the inputs are clear, call propose_plan with the smallest first version that works end to end: 3 to 8 steps, the files, and the command that runs it. Nothing gets built until the user approves.

3. Build, only after approval: write one file at a time with write_file, small and readable, each tagged with its plan step. Then run it with run_python and fix whatever fails until it works. Before each tool call, say in one short sentence what you're about to do. When it works, tell them how to run it themselves and what to try next, then ask what they'd like to change.

Rules for the code:
- Python {sys.version_info.major}.{sys.version_info.minor} with its standard library. These extra packages are installed and you may use them: {", ".join(INSTALLED) or "none"}. You can't install anything else; if the project truly needs another package, say so and list it in requirements.txt.
- Programs run without a keyboard, so never call input(). Take command-line arguments, or read a small sample file you create in the project.
- Only touch files inside the project folder, by relative path.
- Read API keys and other secrets from environment variables, and never print them.

If the user changes their mind at any point, update the brief and adapt; re-plan if the change is big."""


def _object(properties: dict, required=()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_TEXT = {"type": "string"}
TOOLS = [
    {"name": "update_brief",
     "description": ("Record what you now understand about the project; the user sees it as a live brief. Send only "
                     "the fields that changed. confidence per field: 5 = the user said it, 3 = a sensible default you "
                     "assumed, 0 = unknown."),
     "input_schema": _object({
         "name": {"type": "string", "description": "Short project name, 2 to 4 words"},
         "goal": _TEXT,
         "users": {"type": "string", "description": "Who it is for"},
         "first_version": {"type": "string", "description": "What the first working version does"},
         "inputs": {"type": "string", "description": "Where its data or input comes from"},
         "constraints": _TEXT,
         "open_questions": {"type": "array", "items": _TEXT},
         "confidence": _object({field: {"type": "integer", "minimum": 0, "maximum": 5} for field in BRIEF_FIELDS}),
     })},
    {"name": "ask_user",
     "description": ("Ask the user one question, then wait for their answer. Pick the question whose answer would "
                     "most change what you build."),
     "input_schema": _object({
         "question": _TEXT,
         "why": {"type": "string", "description": "One line on what the answer decides"},
         "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": _object(
             {"label": _TEXT, "detail": {"type": "string", "description": "Short consequence, or why you recommend it"}},
             ["label"])},
     }, ["question", "why", "options"])},
    {"name": "propose_plan",
     "description": ("Propose the smallest first version that works end to end, then wait. Nothing is built until "
                     "the user approves."),
     "input_schema": _object({
         "summary": _TEXT,
         "steps": {"type": "array", "minItems": 1, "maxItems": 8, "items": _TEXT},
         "files": {"type": "array", "items": _TEXT},
         "run": {"type": "string", "description": "The command that runs it, e.g. python main.py sample.csv"},
     }, ["summary", "steps", "files"])},
    {"name": "write_file",
     "description": "Create or overwrite a text file in the project folder. Only works after the plan is approved.",
     "input_schema": _object({
         "path": {"type": "string", "description": "Relative to the project folder, e.g. main.py"},
         "content": _TEXT,
         "step": {"type": "integer", "description": "The plan step (1-based) this file belongs to"},
     }, ["path", "content"])},
    {"name": "read_file", "description": "Read a text file from the project folder.",
     "input_schema": _object({"path": _TEXT}, ["path"])},
    {"name": "list_files", "description": "List the files in the project folder.", "input_schema": _object({})},
    {"name": "run_python",
     "description": (f"Run a Python file from the project folder and get its output. It runs right away, with no "
                     f"keyboard input, and is stopped after {RUN_TIMEOUT} seconds. You can't install packages."),
     "input_schema": _object({
         "path": _TEXT,
         "args": {"type": "array", "items": _TEXT},
         "step": {"type": "integer", "description": "The plan step (1-based) this run belongs to"},
     }, ["path"])},
]
for _tool in TOOLS:
    _tool["eager_input_streaming"] = True  # file contents stream into the UI while they're written


class ToolError(Exception):
    """A problem to report back to Claude as an error tool_result, not to the user."""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _error(tool_use_id: str, message: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}


# ---- sessions ----------------------------------------------------------------

def _session_path(sid) -> Path:
    if not isinstance(sid, str) or not SESSION_ID.match(sid):
        raise harness.HarnessError("That project session doesn't exist.")
    return DATA / "studio" / f"{sid}.json"


def new_session(model=None) -> dict:
    sid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    session = {"id": sid, "created": _now(), "updated": _now(), "model": harness.pick_model(model),
               "phase": "discover", "slug": "", "record": "", "brief": {}, "messages": [], "log": [],
               "pending": None, "cost_usd": 0.0}
    save(session)
    return session


def load(sid) -> dict:
    path = _session_path(sid)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise harness.HarnessError("That project session doesn't exist.") from exc


def save(session: dict) -> None:
    session["updated"] = _now()
    path = _session_path(session["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def list_sessions() -> list:
    rows = []
    for path in sorted((DATA / "studio").glob("*.json"), reverse=True)[:50]:
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({"id": session.get("id"), "name": session.get("brief", {}).get("name") or "New project",
                     "phase": session.get("phase"), "updated": session.get("updated"),
                     "cost_usd": session.get("cost_usd", 0)})
    return rows


def public(session: dict) -> dict:
    return {"id": session["id"], "model": session["model"], "phase": session["phase"], "slug": session["slug"],
            "brief": session["brief"], "log": session["log"], "cost_usd": session["cost_usd"],
            "waiting": (session.get("pending") or {}).get("kind"), "files": list_tree(session)}


# ---- the project folder --------------------------------------------------------

def project_root(session: dict) -> Path:
    if not session.get("slug"):
        raise ToolError("There's no project folder yet: it's created when the user approves your plan.")
    return (PROJECTS / session["slug"]).resolve()


def project_path(session: dict, rel) -> Path:
    root = project_root(session)
    rel = str(rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise ToolError("Use a path relative to the project folder, like main.py or data/sample.csv.")
    target = (root / rel).resolve()
    if target == root or root not in target.parents:
        raise ToolError("That path is outside the project folder.")
    if ".git" in target.relative_to(root).parts:
        raise ToolError("The .git folder is off limits.")
    return target


def list_tree(session: dict) -> list:
    if not session.get("slug"):
        return []
    root = (PROJECTS / session["slug"]).resolve()
    files = []
    for path in sorted(root.rglob("*")) if root.is_dir() else []:
        rel = path.relative_to(root)
        if path.is_file() and not {"__pycache__", ".git"} & set(rel.parts):
            files.append({"path": rel.as_posix(), "bytes": path.stat().st_size})
            if len(files) >= 300:
                break
    return files


def read_for_ui(sid, rel) -> dict:
    session = load(sid)
    try:
        target = project_path(session, rel)
    except ToolError as exc:
        raise harness.HarnessError(str(exc)) from exc
    if not target.is_file():
        raise harness.HarnessError("That file doesn't exist.")
    return {"path": str(rel), "content": target.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")}


def _start_build(session: dict) -> None:
    session["phase"] = "build"
    if session["slug"]:
        return
    brief = session["brief"]
    name = brief.get("name") or "my project"
    base = slug = slugify(name)
    n = 2
    while (PROJECTS / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    (PROJECTS / slug).mkdir(parents=True)
    record = write_project(name, "in-progress", brief.get("first_version", ""), f"projects/{slug}",
                           brief.get("goal", ""), brief.get("inputs", ""), projects_dir=DATA / "projects")
    session.update(slug=slug, record=f"data/projects/{record.name}")


# ---- tools ---------------------------------------------------------------------

def tool_update_brief(session: dict, data: dict) -> str:
    brief = session["brief"]
    for key in ("name", *BRIEF_FIELDS):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            brief[key] = one_line(value)[:80 if key == "name" else 400]
    if isinstance(data.get("open_questions"), list):
        brief["open_questions"] = [one_line(q)[:200] for q in data["open_questions"]
                                   if isinstance(q, str) and q.strip()][:6]
    confidence = data.get("confidence")
    if isinstance(confidence, dict):
        scores = brief.setdefault("confidence", {})
        for key in BRIEF_FIELDS:
            value = confidence.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                scores[key] = max(0, min(5, value))
    return "Brief updated; the user can see it."


def clean_question(data: dict) -> dict:
    question, options = data.get("question"), data.get("options")
    if not isinstance(question, str) or not question.strip() or not isinstance(options, list):
        raise ToolError("ask_user needs a question and 2 to 4 options.")
    cleaned = [{"label": one_line(o["label"])[:120], "detail": one_line(o.get("detail") or "")[:160]}
               for o in options[:4] if isinstance(o, dict) and isinstance(o.get("label"), str) and o["label"].strip()]
    if len(cleaned) < 2:
        raise ToolError("ask_user needs at least 2 options, each with a label.")
    return {"question": one_line(question)[:400], "why": one_line(data.get("why") or "")[:240], "options": cleaned}


def clean_plan(data: dict) -> dict:
    summary, steps = data.get("summary"), data.get("steps")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(steps, list):
        raise ToolError("propose_plan needs a summary and at least one step.")
    steps = [one_line(s)[:200] for s in steps if isinstance(s, str) and s.strip()][:8]
    if not steps:
        raise ToolError("propose_plan needs at least one step.")
    files = [one_line(f)[:120] for f in data.get("files") or [] if isinstance(f, str) and f.strip()][:20]
    return {"summary": one_line(summary)[:600], "steps": steps, "files": files,
            "run": one_line(data.get("run") or "")[:200]}


def tool_write_file(session: dict, data: dict) -> tuple:
    if session["phase"] != "build":
        raise ToolError("Not yet: nothing is built until the user approves a plan. Call propose_plan first.")
    content = data.get("content")
    if not isinstance(content, str):
        raise ToolError("write_file needs the file's full text in content.")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ToolError(f"That file is over {MAX_FILE_BYTES // 1000} KB; split it into smaller modules.")
    target = project_path(session, data.get("path"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return target.relative_to(project_root(session)).as_posix(), lines


def tool_read_file(session: dict, data: dict) -> str:
    target = project_path(session, data.get("path"))
    if not target.is_file():
        raise ToolError("There's no such file in the project folder.")
    text = target.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= MAX_READ_CHARS else text[:MAX_READ_CHARS] + "\n[...truncated]"


def tool_list_files(session: dict, data: dict) -> str:
    project_root(session)
    return "\n".join(f"{f['path']} ({f['bytes']} bytes)" for f in list_tree(session)) or "The project folder is empty."


def _run_env() -> dict:
    # Generated code runs with the user's permissions: at least keep API keys and tokens out of its reach.
    env = {key: value for key, value in os.environ.items() if not SECRET_ENV.search(key)}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    return env


def _pump(stream, lines: queue.Queue) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.put(line)
    except (OSError, ValueError):  # the pipe was closed under us after a timeout
        pass
    lines.put(None)


def tool_run_python(session: dict, data: dict):
    if session["phase"] != "build":
        raise ToolError("Not yet: nothing runs until the user approves a plan.")
    target = project_path(session, data.get("path"))
    if target.suffix != ".py" or not target.is_file():
        raise ToolError("run_python needs an existing .py file in the project folder.")
    root = project_root(session)
    rel = target.relative_to(root).as_posix()
    args = [str(a)[:200] for a in data.get("args") or [] if isinstance(a, (str, int, float))][:20]
    step = data.get("step") if isinstance(data.get("step"), int) else None
    command = " ".join(["python", rel, *args])
    yield {"type": "run_start", "command": command, "step": step}

    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, rel, *args], cwd=root, env=_run_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = queue.Queue()
    reader = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    reader.start()
    output, streamed, timed_out = [], 0, False
    while True:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            line = ""
        if line is None:
            break
        if line:
            output.append(line)
            if streamed < MAX_STREAMED_LINES:
                streamed += 1
                yield {"type": "run_output", "text": line}
        if time.monotonic() - started > RUN_TIMEOUT:
            proc.kill()
            timed_out = True
            break
    try:
        code = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        code = None
    reader.join(timeout=2)
    proc.stdout.close()
    seconds = round(time.monotonic() - started, 1)
    yield {"type": "run_done", "exit_code": code, "seconds": seconds, "timed_out": timed_out, "step": step}
    text = "".join(output)
    tail = text if len(text) <= MAX_OUTPUT_CHARS else "[...earlier output cut]\n" + text[-MAX_OUTPUT_CHARS:]
    return {"command": command, "exit_code": code, "seconds": seconds, "timed_out": timed_out, "output": tail,
            "step": step}


def _run_tool(session: dict, block):
    data = block.input if isinstance(block.input, dict) else {}
    try:
        if block.name == "update_brief":
            message = tool_update_brief(session, data)
            yield {"type": "brief", "brief": session["brief"]}
        elif block.name == "write_file":
            rel, lines = tool_write_file(session, data)
            step = data.get("step") if isinstance(data.get("step"), int) else None
            session["log"].append({"kind": "file", "path": rel, "lines": lines, "step": step})
            yield {"type": "file_done", "path": rel, "lines": lines, "step": step}
            message = f"Wrote {rel} ({lines} lines)."
        elif block.name == "read_file":
            message = tool_read_file(session, data)
        elif block.name == "list_files":
            message = tool_list_files(session, data)
        elif block.name == "run_python":
            run = yield from tool_run_python(session, data)
            session["log"].append({"kind": "run", **run, "output": run["output"][-2000:]})
            stopped = f" (stopped after {RUN_TIMEOUT} s)" if run["timed_out"] else ""
            message = f"Exit code {run['exit_code']}{stopped}. Output:\n{run['output'] or '(no output)'}"
        else:
            raise ToolError(f"There's no tool called {block.name}.")
    except ToolError as exc:
        yield {"type": "tool_error", "tool": block.name, "message": str(exc)}
        return _error(block.id, str(exc))
    return {"type": "tool_result", "tool_use_id": block.id, "content": message}


# ---- the loop ------------------------------------------------------------------

def _preview(buf: str):
    # The SDK's own snapshot drops a string until it closes; parse our copy leniently so code appears as it's typed.
    try:
        snapshot = from_json(buf.encode("utf-8"), partial_mode="trailing-strings")
    except ValueError:
        return
    if isinstance(snapshot, dict) and isinstance(snapshot.get("path"), str) and "content" in snapshot:
        yield {"type": "file_delta", "path": snapshot["path"], "content": str(snapshot.get("content") or "")}


def _stream_round(session: dict):
    model = session["model"]
    kwargs = {"model": model, "max_tokens": MAX_TOKENS, "output_config": {"effort": EFFORT},
              "cache_control": {"type": "ephemeral"}}
    if model in harness.FALLBACK_MODELS:
        kwargs.update(betas=[harness.FALLBACK_BETA], fallbacks="default")
    for attempt in range(3):
        current, last_preview = None, 0.0
        try:
            with harness.client().beta.messages.stream(system=SYSTEM, tools=TOOLS, messages=session["messages"],
                                                       **kwargs) as stream:
                for event in stream:
                    if event.type == "text":
                        yield {"type": "text", "text": event.text}
                    elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                        current = {"name": event.content_block.name, "buf": ""}
                        yield {"type": "tool_start", "tool": current["name"]}
                    elif event.type == "input_json" and current:
                        current["buf"] += event.partial_json
                        if current["name"] == "write_file" and time.monotonic() - last_preview >= PREVIEW_INTERVAL:
                            last_preview = time.monotonic()
                            yield from _preview(current["buf"])
                    elif event.type == "content_block_stop":
                        if current and current["name"] == "write_file":
                            yield from _preview(current["buf"])
                        current = None
                return stream.get_final_message()
        except ValueError:
            # Tool-input JSON the SDK couldn't parse at all: there's no tool_use to answer yet, so re-issue the round.
            if attempt == 2:
                raise harness.HarnessError("Claude's reply came back garbled twice. Try sending your message again.")
            yield {"type": "retry"}
        except (anthropic.AnthropicError, TypeError) as exc:
            if not harness._is_api_failure(exc):
                raise
            raise harness._friendly(exc, model) from exc


def _user_content(session: dict, text: str, approve: bool):
    """The next user turn: results still owed from the last round, then the answer or the new message."""
    pending = session.pop("pending", None) or {}
    session["pending"] = None
    content, kind, events = list(pending.get("results") or []), pending.get("kind"), []
    if kind == "plan" and approve:
        _start_build(session)
        session["log"].append({"kind": "approved", "slug": session["slug"]})
        events.append({"type": "phase", "phase": "build", "slug": session["slug"]})
        reply = "The user approved the plan. The project folder is ready: build it now."
    else:
        session["log"].append({"kind": "user", "text": text})
        reply = (f"The user wants changes before you build: {text}" if kind == "plan"
                 else f"The user answered: {text}")
    if kind in ("plan", "question"):
        content.append({"type": "tool_result", "tool_use_id": pending["tool_use_id"], "content": reply})
    else:
        content.append({"type": "text", "text": text})
    return content, events


def run_turn(sid, message, model=None, approve=False):
    _session_path(sid)
    with _locks_guard:
        lock = _locks.setdefault(sid, threading.Lock())
    if not lock.acquire(blocking=False):
        raise harness.HarnessError("This project is still working on your last message.")
    try:
        yield from _turn(load(sid), str(message or "").strip(), model, bool(approve))
    finally:
        lock.release()


_locks = {}
_locks_guard = threading.Lock()


def _turn(session: dict, text: str, model, approve: bool):
    if not text:
        raise harness.HarnessError("Type a message first.")
    if model:
        session["model"] = harness.pick_model(model)
    content, events = _user_content(session, text, approve)
    session["messages"].append({"role": "user", "content": content})
    save(session)
    yield from events

    turn_usd = 0.0
    for round_no in range(1, MAX_ROUNDS + 1):
        yield {"type": "status", "text": "thinking"}
        final = yield from _stream_round(session)
        usd = harness.log_usage("studio", session["model"], final) or 0.0
        turn_usd += usd
        session["cost_usd"] = round(session["cost_usd"] + usd, 6)
        yield {"type": "cost", "turn_usd": round(turn_usd, 6), "session_usd": session["cost_usd"]}
        session["messages"].append({"role": "assistant",
                                    "content": [b.model_dump(mode="json", exclude_none=True) for b in final.content]})
        said = "".join(b.text for b in final.content if b.type == "text").strip()
        if said:
            session["log"].append({"kind": "assistant", "text": said})

        tool_uses = [b for b in final.content if b.type == "tool_use"]
        if final.stop_reason in ("refusal", "max_tokens") and tool_uses:
            # A cut-off tool input can still parse as a valid partial object: never run it.
            results = [_error(b.id, "Not run: your reply was cut off before this call finished. Try smaller steps.")
                       for b in tool_uses]
            if final.stop_reason == "refusal":
                session["pending"] = {"results": results}
                save(session)
                raise harness.HarnessError("Claude declined to continue with this. Try rephrasing your request.")
            session["messages"].append({"role": "user", "content": results})
            save(session)
            continue
        if final.stop_reason == "refusal":
            save(session)
            raise harness.HarnessError("Claude declined to continue with this. Try rephrasing your request.")
        if not tool_uses:
            save(session)
            yield {"type": "turn_end", "reason": "done"}
            return

        results, pause = [], None
        for block in tool_uses:
            if block.name in ("ask_user", "propose_plan"):
                if pause:
                    results.append(_error(block.id, "Not shown: ask one thing at a time."))
                    continue
                try:
                    shown = clean_question(block.input) if block.name == "ask_user" else clean_plan(block.input)
                except ToolError as exc:
                    results.append(_error(block.id, str(exc)))
                    continue
                pause = {"kind": "question" if block.name == "ask_user" else "plan", "tool_use_id": block.id,
                         "shown": shown}
                continue
            results.append((yield from _run_tool(session, block)))

        if pause:
            session["pending"] = {"kind": pause["kind"], "tool_use_id": pause["tool_use_id"], "results": results}
            session["log"].append({"kind": pause["kind"], **pause["shown"]})
            save(session)
            yield {"type": pause["kind"], **pause["shown"]}
            yield {"type": "turn_end", "reason": pause["kind"]}
            return
        if round_no == MAX_ROUNDS:
            session["pending"] = {"results": results}
            save(session)
            yield {"type": "turn_end", "reason": "limit"}
            return
        session["messages"].append({"role": "user", "content": results})
        save(session)
