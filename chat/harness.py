"""Engine behind the harness chat: route -> plan -> search agents -> streamed answer.

Uses the same .claude/agents/ personas and data/projects/ files as the rest of the
harness, Claude via the Anthropic API, and DuckDuckGo search via the ddgs library.
Credentials come from the environment (ANTHROPIC_API_KEY or an `ant auth login`
profile) and are resolved by the SDK; this module never handles the key itself.
Every Claude call's token usage and estimated cost is appended to
data/costs/<date>.jsonl.
"""

import datetime
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from ddgs import DDGS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from dashboard import DATA, one_line, parse_frontmatter, read_text, write_project  # noqa: E402

MODELS = ["claude-opus-5", "claude-sonnet-5"]
DEFAULT_MODEL = "claude-opus-5"
# The plan and the project summary are small structured-JSON steps, so they run on this cheaper model.
ROUTER_MODEL = "claude-sonnet-5"
# fallbacks="default" is documented for Opus 5; other models get no fallback rather than a guessed-at 400.
FALLBACK_MODELS = {"claude-opus-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_HISTORY = 12
# USD per million tokens (input, output) at list price, for the estimates in data/costs/.
PRICES = {"claude-opus-5": (5.00, 25.00), "claude-sonnet-5": (2.00, 10.00)}

AGENTS = {
    "dev": ("@dev", "Software Engineer"),
    "writer": ("@writer", "Technical Writer"),
    "researcher": ("@researcher", "Research Analyst"),
    "ops": ("@ops", "DevOps / Release Engineer"),
}

PLANNER_PROMPT = """You are the kernel of an agentic harness that helps beginners. Read the conversation and decide how to handle the user's latest message.

Fields:
- agent: dev writes and fixes code; writer explains, documents, and gathers requirements for new projects; researcher finds and compares information; ops handles installs, servers and deployment.
- mode: "clarify" when the user wants to build or start something but hasn't said enough to begin, otherwise "answer".
- steps: 2 to 5 short section titles for the reply, each under 6 words.
- needs_search: true only when facts from the web (datasets, libraries, docs, recent info) would clearly improve the answer.
- queries: up to 3 short web search queries when needs_search is true, otherwise an empty list."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "agent": {"type": "string", "enum": ["dev", "writer", "researcher", "ops"]},
        "mode": {"type": "string", "enum": ["answer", "clarify"]},
        "steps": {"type": "array", "items": {"type": "string"}},
        "needs_search": {"type": "boolean"},
        "queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["agent", "mode", "steps", "needs_search", "queries"],
    "additionalProperties": False,
}

SAVE_PROMPT = """Summarize the project the user wants to build, based on this conversation.
- name: a 2 to 4 word project name
- description: one or two plain sentences
- milestone: what a first working version does
- data_source: where the data comes from, or "not decided yet\""""

SAVE_SCHEMA = {
    "type": "object",
    "properties": {key: {"type": "string"} for key in ("name", "description", "milestone", "data_source")},
    "required": ["name", "description", "milestone", "data_source"],
    "additionalProperties": False,
}


class HarnessError(Exception):
    pass


class Refused(HarnessError):
    pass


class ModelUnavailable(HarnessError):
    pass


_client = None
_client_lock = threading.Lock()
_cost_lock = threading.Lock()


def client() -> anthropic.Anthropic:
    global _client
    with _client_lock:
        if _client is None:
            _client = anthropic.Anthropic()
        return _client


def list_models() -> list:
    return list(MODELS)


def default_model(models: list) -> str:
    return DEFAULT_MODEL if DEFAULT_MODEL in models else models[0]


def _friendly(exc: Exception, model: str) -> HarnessError:
    if isinstance(exc, anthropic.AuthenticationError):
        msg = "Claude rejected the API key. Check ANTHROPIC_API_KEY in the terminal that starts the chat server, then restart it."
    elif isinstance(exc, anthropic.PermissionDeniedError):
        return ModelUnavailable(f"This API key isn't allowed to use {model}. Pick another model in the sidebar.")
    elif isinstance(exc, anthropic.NotFoundError):
        return ModelUnavailable(f"Claude doesn't recognize the model '{model}'.")
    elif isinstance(exc, anthropic.RateLimitError):
        msg = "Claude is limiting how fast requests can be sent right now. Wait a minute and try again."
    elif isinstance(exc, anthropic.BadRequestError):
        msg = f"Claude couldn't accept this request: {exc.message}"
    elif isinstance(exc, anthropic.APIStatusError):
        msg = f"Claude's servers had a problem (error {exc.status_code}). Try again in a moment."
    elif isinstance(exc, anthropic.APIConnectionError):
        msg = "Can't reach the Claude API. Check this computer's internet connection."
    else:
        msg = ("No Claude credentials found. Set ANTHROPIC_API_KEY in the terminal that starts the chat server "
               "(or run `ant auth login`), then restart it.")
    return HarnessError(msg)


def _is_api_failure(exc: Exception) -> bool:
    # The SDK reports missing credentials as a bare TypeError; any other TypeError is a real bug and must surface.
    return isinstance(exc, anthropic.AnthropicError) or "authentication method" in str(exc)


def _request(model: str, effort: str, max_tokens: int, schema: dict | None = None) -> dict:
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    kwargs = {"model": model, "max_tokens": max_tokens, "output_config": output_config}
    if model in FALLBACK_MODELS:
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    return kwargs


def _refused() -> HarnessError:
    return Refused("Claude declined to answer this one. Try rephrasing the request.")


def log_usage(step: str, model: str, response) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    model = getattr(response, "model", None) or model
    tokens = {key: getattr(usage, key, 0) or 0 for key in
              ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    usd = None
    if model in PRICES:
        # input_tokens excludes cached tokens: cache writes bill at 1.25x input, cache reads at 0.1x.
        per_in, per_out = PRICES[model]
        usd = round((tokens["input_tokens"] * per_in + tokens["cache_creation_input_tokens"] * per_in * 1.25
                     + tokens["cache_read_input_tokens"] * per_in * 0.1 + tokens["output_tokens"] * per_out) / 1e6, 6)
    now = datetime.datetime.now()
    record = {"time": now.isoformat(timespec="seconds"), "step": step, "model": model, **tokens, "usd": usd}
    path = DATA / "costs" / f"{now:%Y-%m-%d}.jsonl"
    try:
        with _cost_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
    except OSError as exc:  # the log is bookkeeping; losing a line mustn't cost the user their answer
        print(f"Couldn't write the cost log: {exc}", file=sys.stderr)


def chat_json(model: str, system: str, messages: list, schema: dict, step: str) -> dict:
    try:
        response = client().beta.messages.create(
            system=system, messages=messages, **_request(model, "low", 8000, schema))
    except (anthropic.AnthropicError, TypeError) as exc:
        if not _is_api_failure(exc):
            raise
        raise _friendly(exc, model) from exc
    log_usage(step, model, response)
    if response.stop_reason == "refusal":
        raise _refused()
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise HarnessError("Claude's reply was cut off before it finished. Try again.") from exc
    if not isinstance(data, dict):
        raise HarnessError("Claude returned something unexpected. Try again.")
    return data


def chat_stream(model: str, system: str, messages: list):
    try:
        with client().beta.messages.stream(
                system=system, messages=messages, **_request(model, "medium", 64000)) as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()
    except (anthropic.AnthropicError, TypeError) as exc:
        if not _is_api_failure(exc):
            raise
        raise _friendly(exc, model) from exc
    log_usage("answer", model, final)
    if final.stop_reason == "refusal":
        raise _refused()
    if final.stop_reason not in ("end_turn", "stop_sequence"):
        # e.g. max_tokens, or a stream that closed without finishing: never present it as a complete answer.
        raise HarnessError("Claude's answer was cut off before it finished. Try asking again.")


def clean_history(history) -> list:
    if not isinstance(history, list):
        return []
    kept = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str) and m["content"].strip()
    ][-MAX_HISTORY:]
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept


def agent_identity(key: str) -> str:
    path = ROOT / ".claude" / "agents" / f"{key}.md"
    if not path.exists():
        return AGENTS[key][1]
    _, _, after = read_text(path).partition("## Identity")
    return after.split("\n## ", 1)[0].strip() or AGENTS[key][1]


def list_projects() -> list:
    projects = []
    for path in sorted((DATA / "projects").glob("*.md")):
        fm, _ = parse_frontmatter(read_text(path))
        projects.append({"name": fm.get("name") or path.stem, "status": fm.get("status", ""),
                         "milestone": fm.get("milestone", "")})
    return projects


def projects_line() -> str:
    projects = list_projects()
    if not projects:
        return ""
    return "Projects already registered in this workspace: " + "; ".join(
        f"{p['name']} ({p['status'] or 'no status'})" for p in projects[:10])


def clean_step(step) -> str:
    return one_line(step).lstrip("#").strip()[:48]


def pick_model(model) -> str:
    return model if model in MODELS else DEFAULT_MODEL


def routed_json(model: str, system: str, messages: list, schema: dict, step: str) -> dict:
    try:
        return chat_json(ROUTER_MODEL, system, messages, schema, step)
    except (Refused, ModelUnavailable):
        if model == ROUTER_MODEL:
            raise
        # The router model has no server-side fallback (and a key may not allow it); the chosen model may.
        return chat_json(model, system, messages, schema, step)


def make_plan(model: str, history: list, message: str) -> dict:
    # Same history and project list the writer gets, so the plan and the answer are decided on the same facts.
    system = "\n\n".join(filter(None, [PLANNER_PROMPT, projects_line()]))
    messages = clean_history(history) + [{"role": "user", "content": message}]
    data = routed_json(model, system, messages, PLAN_SCHEMA, "plan")

    agent = data["agent"] if data.get("agent") in AGENTS else "writer"
    mode = "clarify" if data.get("mode") == "clarify" else "answer"
    if mode == "clarify":
        # Fixed steps: planner-chosen ones ("set up structure"...) led the model to role-play past its own questions.
        steps = ["What I understood", "Questions for you"]
    else:
        steps = []
        for step in data.get("steps") or []:
            step = clean_step(step)
            if step and step.lower() not in (s.lower() for s in steps):
                steps.append(step)
        steps = steps[:5] or ["Quick answer", "How it works", "Next steps"]
    queries = [str(q).strip()[:120] for q in data.get("queries") or [] if str(q).strip()][:3]
    return {"agent": agent, "mode": mode, "steps": steps, "queries": queries if data.get("needs_search") else []}


def search_one(query: str) -> list:
    results = DDGS().text(query, max_results=4) or []
    return [{"title": one_line(r.get("title")), "href": r["href"], "body": (r.get("body") or "")[:300]}
            for r in results if str(r.get("href", "")).lower().startswith(("https://", "http://"))]


def writer_prompt(plan: dict, sources: list, searched: bool = False) -> str:
    headings = "\n".join(f"## {step}" for step in plan["steps"])
    lines = [
        "You are one of the specialist agents in a beginner-friendly agentic harness. Your identity:",
        agent_identity(plan["agent"]),
        "",
        "In this chat you're talking to a beginner, which overrides any audience your identity describes. Use plain "
        "language and short paragraphs. The first time you use a technical term, explain it in a few words. Prefer "
        "concrete examples over theory.",
        f"Write your reply using exactly these markdown headings, in this order, with nothing before the first heading:\n{headings}",
    ]
    if plan["mode"] == "clarify":
        lines.append("The user wants to build something but hasn't shared enough yet. Don't build or write code yet. "
                     "Briefly say what you understood, then ask at most 3 simple questions as a numbered list, each "
                     "followed by an example answer in brackets so they can reply quickly. Stop after the questions "
                     "and wait for their reply: don't answer the questions yourself or continue as if they had replied.")
    if sources:
        lines.append("Web research from your search agents. Use it where it helps and cite facts as [n]:")
        lines += [f"[{s['n']}] {s['title']} - {s['href']}\n{s['body']}" for s in sources]
    elif searched:
        lines.append("Your search agents found nothing usable this time (the searches failed or came back empty). "
                     "Say that plainly, answer from general knowledge where you can, and don't cite or invent sources.")
    if projects_line():
        lines.append(projects_line())
    return "\n".join(lines)


def run_turn(model: str, history, message: str):
    model = pick_model(model)
    history = clean_history(history)
    yield {"type": "stage", "stage": "understand", "state": "active"}
    plan = make_plan(model, history, message)
    label, role = AGENTS[plan["agent"]]
    yield {"type": "stage", "stage": "understand", "state": "done"}
    yield {"type": "route", "agent": plan["agent"], "label": label, "role": role}
    yield {"type": "stage", "stage": "route", "state": "done"}
    yield {"type": "plan", "steps": plan["steps"], "mode": plan["mode"]}
    yield {"type": "stage", "stage": "plan", "state": "done"}

    sources = []
    if plan["queries"]:
        yield {"type": "stage", "stage": "research", "state": "active"}
        with ThreadPoolExecutor(max_workers=len(plan["queries"])) as pool:
            futures = {}
            for i, query in enumerate(plan["queries"]):
                yield {"type": "agent_deployed", "id": i, "query": query}
                futures[pool.submit(search_one, query)] = i
            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    results = future.result()
                except Exception as exc:  # search is a flaky external service; one agent failing shouldn't end the turn
                    yield {"type": "agent_done", "id": agent_id, "results": [], "error": str(exc)[:160]}
                    continue
                found = []
                for r in results:
                    existing = next((s for s in sources if s["href"] == r["href"]), None)
                    if existing is None:
                        existing = {**r, "n": len(sources) + 1}
                        sources.append(existing)
                    found.append({"n": existing["n"], "title": r["title"], "href": r["href"]})
                yield {"type": "agent_done", "id": agent_id, "results": found}
        yield {"type": "stage", "stage": "research", "state": "done"}
    else:
        yield {"type": "stage", "stage": "research", "state": "skipped"}

    yield {"type": "stage", "stage": "write", "state": "active"}
    messages = history + [{"role": "user", "content": message}]
    for chunk in chat_stream(model, writer_prompt(plan, sources, searched=bool(plan["queries"])), messages):
        yield {"type": "token", "text": chunk}
    yield {"type": "stage", "stage": "write", "state": "done"}
    yield {"type": "done"}


def save_project(model: str, history) -> dict:
    model = pick_model(model)
    history = clean_history(history)
    if not history:
        raise HarnessError("Chat a bit about your project first, then save it.")
    # The request must end on a user turn: ending on Claude's reply counts as an (unsupported) prefill.
    messages = history + [{"role": "user", "content": "Summarize this conversation as a project now."}]
    data = routed_json(model, SAVE_PROMPT, messages, SAVE_SCHEMA, "save")

    path = write_project(data.get("name"), "planning", data.get("milestone"), "", data.get("description"),
                         data.get("data_source") or "not decided yet", projects_dir=DATA / "projects")
    name = parse_frontmatter(read_text(path))[0].get("name", path.stem)
    return {"name": name, "file": f"data/projects/{path.name}"}
