"""Local dashboard for the agentic-OS harness in this workspace.

Stdlib-only HTTP server, binds to 127.0.0.1 only. Reads/writes the same
data/ files the slash commands (/status, /new-project, /decision) use, so
the UI and the commands stay in sync automatically -- there is no separate
database.

Run: python scripts/dashboard.py  (or via .claude/launch.json "harness-dashboard")
"""

import datetime
import html
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AGENTS = ROOT / ".claude" / "agents"
COMMANDS = ROOT / ".claude" / "commands"
PORT = 8787


WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
MAX_BODY = 1_000_000


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-") or "untitled"
    # "nul.md" etc. are devices on Windows: writes vanish while reporting success.
    return f"{slug}-project" if slug in WINDOWS_RESERVED else slug


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def read_text(path: Path) -> str:
    # Files may be hand-edited in other tools (ANSI, BOM); a bad byte must not take the page or a chat turn down.
    return path.read_text(encoding="utf-8-sig", errors="replace")


def one_line(value) -> str:
    return " ".join(str(value or "").split())


def read_files(dir_path: Path, pattern: str = "*.md"):
    if not dir_path.exists():
        return []
    return sorted(
        (p for p in dir_path.glob(pattern) if not p.name.startswith(".")),
        key=lambda p: p.name,
    )


def parse_frontmatter(text: str):
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text
    fm = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, val = line.partition(":")
            fm.setdefault(key.strip(), val.strip())
    return fm, "\n".join(lines[end + 1:]).strip()


def create_exclusive(directory: Path, stem: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        path = directory / (f"{stem}.md" if suffix == 1 else f"{stem}-{suffix}.md")
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(content)
            return path
        except FileExistsError:
            suffix += 1


def write_project(name, status="planning", milestone="", repo_path="", description="", data_source="",
                  projects_dir: Path = None) -> Path:
    name = one_line(name)[:80] or "untitled project"
    lines = [
        "---",
        f"name: {name}",
        f"status: {one_line(status) or 'planning'}",
        f"milestone: {one_line(milestone)}",
        f"repo_path: {one_line(repo_path)}",
        "---",
        "",
        "## Description",
        str(description or "").strip(),
        "",
    ]
    if one_line(data_source):
        lines += [f"Data/input: {one_line(data_source)}", ""]
    lines += ["## Current State", "", "## Open Decisions", "", "## Next Actions", "- [ ]", ""]
    return create_exclusive(projects_dir or DATA / "projects", slugify(name), "\n".join(lines))


def request_problem(headers, port: int, method: str):
    """Why a request must be refused, or None. Stops other websites (CSRF, DNS rebinding) from using the server."""
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if headers.get("Host", "") not in allowed:
        return "unexpected Host header"
    origin = headers.get("Origin")
    if method == "POST" and origin is not None and origin.replace("http://", "", 1) not in allowed:
        return "request came from another website"
    return None


def body_length(headers):
    try:
        length = int(headers.get("Content-Length", 0))
    except ValueError:
        return None
    return length if 0 <= length <= MAX_BODY else None


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def render_projects():
    items = []
    for p in read_files(DATA / "projects"):
        fm, body = parse_frontmatter(read_text(p))
        name = fm.get("name") or p.stem
        status = fm.get("status", "unknown")
        milestone = fm.get("milestone", "")
        items.append(
            f'<li class="card"><div class="card-title">{esc(name)} '
            f'<span class="badge badge-{esc(slugify(status))}">{esc(status)}</span></div>'
            f'{f"<div class=card-sub>{esc(milestone)}</div>" if milestone else ""}'
            f'<div class="card-file">data/projects/{esc(p.name)}</div></li>'
        )
    return "".join(items) or '<li class="empty">No projects registered yet.</li>'


def render_inbox():
    items = []
    for p in read_files(DATA / "inbox"):
        text = read_text(p).strip()
        title = text.splitlines()[0] if text else p.stem
        items.append(
            f'<li class="card inbox-item">'
            f'<form method="post" action="/inbox/dismiss" class="dismiss-form">'
            f'<input type="hidden" name="file" value="{esc(p.name)}">'
            f'<span>{esc(title)}</span>'
            f'<button type="submit" class="btn-small">Dismiss</button>'
            f'</form></li>'
        )
    return "".join(items) or '<li class="empty">Inbox is empty.</li>'


def render_decisions():
    items = []
    for p in reversed(read_files(DATA / "decisions")):
        text = read_text(p)
        title = first_heading(text) or p.stem
        items.append(
            f'<li class="card"><div class="card-title">{esc(title)}</div>'
            f'<div class="card-file">data/decisions/{esc(p.name)}</div></li>'
        )
    return "".join(items) or '<li class="empty">No decisions logged yet.</li>'


def render_daily_log():
    logs = read_files(DATA / "daily-logs")
    if not logs:
        return '<p class="empty">No daily logs yet. Run /daily-sync in a session.</p>'
    latest = logs[-1]
    body = esc(read_text(latest).strip())
    return f'<div class="card-file">{esc(latest.name)}</div><pre class="log">{body}</pre>'


def render_agents():
    items = []
    for p in sorted(AGENTS.glob("*.md")):
        text = read_text(p)
        title = first_heading(text) or p.stem
        items.append(f'<li class="chip">{esc(title)}</li>')
    return "".join(items)


def render_commands():
    items = []
    for p in sorted(COMMANDS.glob("*.md")):
        text = read_text(p)
        title = first_heading(text) or p.stem
        items.append(f'<li class="chip chip-command">{esc(title)}</li>')
    return "".join(items)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness Dashboard</title>
<style>
  :root {{
    --bg: #f7f7f8; --panel: #ffffff; --border: #e3e3e6; --text: #1c1c1f;
    --muted: #6b6b72; --accent: #4f46e5; --ok: #16a34a; --warn: #d97706;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #16161a; --panel: #1f1f24; --border: #302f37; --text: #f0f0f2; --muted: #9a99a2; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 24px 16px 64px; background: var(--bg); color: var(--text);
         font: 15px/1.5 -apple-system, Segoe UI, Roboto, sans-serif; }}
  .wrap {{ max-width: 920px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); margin: 0 0 28px; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
             padding: 16px; margin-bottom: 16px; }}
  section h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
                margin: 0 0 12px; }}
  ul {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }}
  .card {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }}
  .card-title {{ font-weight: 600; display: flex; align-items: center; gap: 8px; }}
  .card-sub {{ color: var(--muted); font-size: 13px; margin-top: 2px; }}
  .card-file {{ color: var(--muted); font-size: 11px; margin-top: 4px; font-family: ui-monospace, monospace; }}
  .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--border); font-weight: 500; }}
  .badge-in-progress, .badge-active {{ background: #dbeafe; color: #1e40af; }}
  .badge-done, .badge-shipped {{ background: #dcfce7; color: #166534; }}
  .badge-blocked {{ background: #fee2e2; color: #991b1b; }}
  .empty {{ color: var(--muted); font-style: italic; }}
  .inbox-item form.dismiss-form {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin: 0; }}
  .btn-small {{ font-size: 12px; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border);
                background: var(--bg); color: var(--text); cursor: pointer; }}
  .chip {{ display: inline-block; background: var(--bg); border: 1px solid var(--border); border-radius: 999px;
           padding: 4px 10px; font-size: 12px; margin: 0 6px 6px 0; }}
  .chip-command {{ font-family: ui-monospace, monospace; }}
  .chips {{ padding: 0; }}
  .chips li {{ display: inline; }}
  pre.log {{ white-space: pre-wrap; font-size: 13px; background: var(--bg); border-radius: 8px; padding: 10px;
             border: 1px solid var(--border); }}
  form.panel-form {{ display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }}
  form.panel-form input, form.panel-form textarea, form.panel-form select {{
    background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 10px; font: inherit; }}
  form.panel-form button {{ align-self: flex-start; background: var(--accent); color: white; border: none;
    border-radius: 6px; padding: 8px 14px; font-weight: 600; cursor: pointer; }}
  details summary {{ cursor: pointer; color: var(--accent); font-size: 13px; margin-top: 8px; }}
  .full {{ grid-column: 1 / -1; }}

  .wizard {{ margin-top: 10px; }}
  .wiz-q {{ font-weight: 600; margin: 0 0 4px; }}
  .wiz-hint {{ color: var(--muted); font-size: 12px; margin: 0 0 10px; }}
  .wiz-step textarea, .wiz-step input {{
    width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 10px; font: inherit; }}
  .wiz-nav {{ display: flex; gap: 8px; margin-top: 10px; }}
  .wiz-nav button {{ border-radius: 6px; padding: 8px 14px; font-weight: 600; cursor: pointer; border: none; }}
  .wiz-next, #wiz-submit {{ background: var(--accent); color: white; }}
  .wiz-back {{ background: var(--bg); color: var(--text); border: 1px solid var(--border) !important; }}
  .wiz-choices {{ display: flex; flex-direction: column; gap: 8px; }}
  .wiz-choice {{ text-align: left; background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 12px; cursor: pointer; font: inherit; }}
  .wiz-choice:hover, .wiz-choice.selected {{ border-color: var(--accent); }}
  .wiz-choice.selected {{ background: var(--accent); color: white; }}
  .wiz-summary {{ background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
    font-size: 13px; line-height: 1.6; }}
  .wiz-advanced {{ margin-top: 10px; font-size: 12px; }}
  .wiz-advanced select, .wiz-advanced input {{ width: 100%; margin-top: 6px; background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font: inherit; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Agentic Harness Dashboard</h1>
  <p class="sub">Live view of data/ in this workspace &mdash; the same files /status, /daily-sync, /new-project, and /decision read and write.</p>

  <div class="grid">
    <section>
      <h2>Projects</h2>
      <ul>{projects}</ul>
      <details id="wiz-toggle">
        <summary>+ Register a project</summary>
        <div id="wizard" class="wizard">
          <form id="wiz-form" method="post" action="/project">
            <input type="hidden" name="name" id="wiz-out-name">
            <input type="hidden" name="status" id="wiz-out-status">
            <input type="hidden" name="milestone" id="wiz-out-milestone">
            <input type="hidden" name="repo_path" id="wiz-out-repo">
            <input type="hidden" name="description" id="wiz-out-description">
            <input type="hidden" name="data_source" id="wiz-out-data">
          </form>

          <div class="wiz-step" data-step="0">
            <p class="wiz-q">What do you want to build?</p>
            <p class="wiz-hint">In your own words &mdash; no need to be precise.</p>
            <textarea id="wiz-goal" rows="3" placeholder="e.g. a tool that sorts photos by whether the paint looks even or uneven"></textarea>
            <div class="wiz-nav"><button type="button" class="wiz-next" data-next="1">Next</button></div>
          </div>

          <div class="wiz-step" data-step="1" hidden>
            <p class="wiz-q">What would a first working version actually do?</p>
            <p class="wiz-hint">Doesn't need to be the whole thing &mdash; just what "it works" would look like the first time.</p>
            <textarea id="wiz-first" rows="3" placeholder="e.g. I give it one photo and it tells me even or uneven"></textarea>
            <div class="wiz-nav"><button type="button" class="wiz-back" data-back="0">Back</button><button type="button" class="wiz-next" data-next="2">Next</button></div>
          </div>

          <div class="wiz-step" data-step="2" hidden>
            <p class="wiz-q">Where's the data or input coming from?</p>
            <div class="wiz-choices">
              <button type="button" class="wiz-choice" data-value="have">I already have it (a file or folder)</button>
              <button type="button" class="wiz-choice" data-value="find">It's out there publicly &mdash; help me find it</button>
              <button type="button" class="wiz-choice" data-value="unsure">Not sure yet</button>
            </div>
            <div class="wiz-nav"><button type="button" class="wiz-back" data-back="1">Back</button></div>
          </div>

          <div class="wiz-step" data-step="3" hidden>
            <p class="wiz-q">What should we call it?</p>
            <p class="wiz-hint">Just a short name, used as a label &mdash; you can rename later.</p>
            <input id="wiz-name" placeholder="e.g. paint checker">
            <div class="wiz-nav"><button type="button" class="wiz-back" data-back="2">Back</button><button type="button" class="wiz-next" data-next="4" id="wiz-to-review">Review</button></div>
          </div>

          <div class="wiz-step" data-step="4" hidden>
            <p class="wiz-q">Here's what I've got:</p>
            <div id="wiz-summary" class="wiz-summary"></div>
            <details class="wiz-advanced">
              <summary>Advanced (optional)</summary>
              <select id="wiz-status-override">
                <option value="">Use suggested status</option>
                <option value="planning">planning</option>
                <option value="in-progress">in-progress</option>
                <option value="blocked">blocked</option>
                <option value="done">done</option>
              </select>
              <input id="wiz-repo-override" placeholder="Code folder/repo path (optional)">
            </details>
            <div class="wiz-nav"><button type="button" class="wiz-back" data-back="3">Back</button><button type="button" id="wiz-submit">Create project</button></div>
          </div>
        </div>
      </details>
    </section>

    <section>
      <h2>Inbox</h2>
      <ul>{inbox}</ul>
      <details>
        <summary>+ Add to inbox</summary>
        <form class="panel-form" method="post" action="/inbox">
          <textarea name="text" placeholder="Task or idea to triage later" rows="2" required></textarea>
          <button type="submit">Add</button>
        </form>
      </details>
    </section>

    <section>
      <h2>Recent decisions</h2>
      <ul>{decisions}</ul>
      <details>
        <summary>+ Log a decision</summary>
        <form class="panel-form" method="post" action="/decision">
          <input name="topic" placeholder="Decision topic" required>
          <textarea name="context" placeholder="Context" rows="2"></textarea>
          <textarea name="options" placeholder="Options considered" rows="2"></textarea>
          <textarea name="decision" placeholder="Decision" rows="2" required></textarea>
          <textarea name="consequences" placeholder="Consequences" rows="2"></textarea>
          <button type="submit">Log</button>
        </form>
      </details>
    </section>

    <section>
      <h2>Latest daily log</h2>
      {daily_log}
    </section>

    <section class="full">
      <h2>Agents &amp; commands</h2>
      <ul class="chips">{agents}</ul>
      <ul class="chips">{commands}</ul>
    </section>
  </div>
</div>
<script>
(function() {{
  var answers = {{ goal: '', first: '', source: '', name: '' }};
  var steps = document.querySelectorAll('.wiz-step');

  var advanceTimer = null;

  function showStep(n) {{
    clearTimeout(advanceTimer);
    steps.forEach(function(s) {{ s.hidden = (s.dataset.step !== String(n)); }});
    if (n === 4) renderSummary();
  }}

  document.querySelectorAll('.wiz-next').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var step = btn.closest('.wiz-step').dataset.step;
      if (step === '0') answers.goal = document.getElementById('wiz-goal').value.trim();
      if (step === '1') answers.first = document.getElementById('wiz-first').value.trim();
      if (step === '3') answers.name = document.getElementById('wiz-name').value.trim();
      showStep(parseInt(btn.dataset.next, 10));
    }});
  }});

  document.querySelectorAll('.wiz-back').forEach(function(btn) {{
    btn.addEventListener('click', function() {{ showStep(parseInt(btn.dataset.back, 10)); }});
  }});

  document.querySelectorAll('.wiz-choice').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      document.querySelectorAll('.wiz-choice').forEach(function(b) {{ b.classList.remove('selected'); }});
      btn.classList.add('selected');
      answers.source = btn.dataset.value;
      advanceTimer = setTimeout(function() {{ showStep(3); }}, 150);
    }});
  }});

  function sourceLine() {{
    if (answers.source === 'have') return "You already have the data (a file or folder).";
    if (answers.source === 'find') return "The data is public \\u2014 still need to find/fetch it.";
    return "Data source not decided yet.";
  }}

  function renderSummary() {{
    var el = document.getElementById('wiz-summary');
    el.innerHTML =
      '<strong>' + escapeHtml(answers.name || 'Untitled') + '</strong><br>' +
      escapeHtml(answers.goal || '(not described)') + '<br><br>' +
      '<em>First version:</em> ' + escapeHtml(answers.first || '(not described)') + '<br>' +
      '<em>Data:</em> ' + escapeHtml(sourceLine());
  }}

  function escapeHtml(s) {{
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }}

  document.getElementById('wiz-submit').addEventListener('click', function() {{
    if (!answers.name) answers.name = (answers.goal || 'untitled').slice(0, 40);
    document.getElementById('wiz-out-name').value = answers.name;
    document.getElementById('wiz-out-status').value = document.getElementById('wiz-status-override').value || 'planning';
    document.getElementById('wiz-out-milestone').value = answers.first || '';
    document.getElementById('wiz-out-repo').value = document.getElementById('wiz-repo-override').value.trim();
    document.getElementById('wiz-out-description').value = answers.goal || '';
    document.getElementById('wiz-out-data').value = sourceLine();
    document.getElementById('wiz-form').submit();
  }});
}})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "HarnessDashboard/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet

    def _send_html(self, body: str, status: int = 200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect_home(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def _refuse(self, status: int, reason: str):
        self._send_html(f"<p>Refused: {esc(reason)}</p>", status)

    def _read_form(self):
        length = body_length(self.headers)
        if length is None:
            return None
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = urllib.parse.parse_qs(raw)
        return {k: v[0] for k, v in parsed.items()}

    def do_GET(self):
        problem = request_problem(self.headers, PORT, "GET")
        if problem:
            self._refuse(403, problem)
            return
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        page = PAGE.format(
            projects=render_projects(),
            inbox=render_inbox(),
            decisions=render_decisions(),
            daily_log=render_daily_log(),
            agents=render_agents(),
            commands=render_commands(),
        )
        self._send_html(page)

    def do_POST(self):
        problem = request_problem(self.headers, PORT, "POST")
        if problem:
            self._refuse(403, problem)
            return
        form = self._read_form()
        if form is None:
            self._refuse(400, "missing, invalid or oversized request body")
            return

        if self.path == "/project":
            if one_line(form.get("name")):
                write_project(form.get("name"), form.get("status") or "planning", form.get("milestone"),
                              form.get("repo_path"), form.get("description"), form.get("data_source"))
            self._redirect_home()

        elif self.path == "/inbox":
            text = form.get("text", "").strip()
            if text:
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                create_exclusive(DATA / "inbox", f"{ts}-{slugify(text[:40])}", text + "\n")
            self._redirect_home()

        elif self.path == "/inbox/dismiss":
            fname = form.get("file", "")
            target = (DATA / "inbox" / fname).resolve()
            if (target.parent == (DATA / "inbox").resolve() and target.suffix == ".md"
                    and not target.name.startswith(".") and target.exists()):
                target.unlink()
            self._redirect_home()

        elif self.path == "/decision":
            topic = one_line(form.get("topic"))
            if topic:
                content = (
                    f"# {topic}\n\n"
                    f"## Context\n{form.get('context', '')}\n\n"
                    f"## Options Considered\n{form.get('options', '')}\n\n"
                    f"## Decision\n{form.get('decision', '')}\n\n"
                    f"## Consequences\n{form.get('consequences', '')}\n"
                )
                create_exclusive(DATA / "decisions", f"{datetime.date.today().isoformat()}-{slugify(topic)}", content)
            self._redirect_home()

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    # ThreadingHTTPServer, not TCPServer: a single-threaded server can get
    # stuck forever on one idle/speculative connection a real browser opens
    # alongside the actual request, blocking every other request behind it.
    with ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        httpd.daemon_threads = True
        print(f"Harness dashboard at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
