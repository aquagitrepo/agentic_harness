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
import socketserver
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AGENTS = ROOT / "agents"
COMMANDS = ROOT / ".claude" / "commands"
PORT = 8787


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "untitled"


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def read_files(dir_path: Path, pattern: str = "*.md"):
    if not dir_path.exists():
        return []
    return sorted(
        (p for p in dir_path.glob(pattern) if p.name != ".gitkeep"),
        key=lambda p: p.name,
    )


def parse_frontmatter(text: str):
    fm, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    fm[key.strip()] = val.strip()
            body = parts[2].strip()
    return fm, body


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def render_projects():
    items = []
    for p in read_files(DATA / "projects"):
        fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
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
        text = p.read_text(encoding="utf-8").strip()
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
        text = p.read_text(encoding="utf-8")
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
    body = esc(latest.read_text(encoding="utf-8").strip())
    return f'<div class="card-file">{esc(latest.name)}</div><pre class="log">{body}</pre>'


def render_agents():
    items = []
    for p in sorted(AGENTS.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title = first_heading(text) or p.stem
        items.append(f'<li class="chip">{esc(title)}</li>')
    return "".join(items)


def render_commands():
    items = []
    for p in sorted(COMMANDS.glob("*.md")):
        text = p.read_text(encoding="utf-8")
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
      <details>
        <summary>+ Register a project</summary>
        <form class="panel-form" method="post" action="/project">
          <input name="name" placeholder="Project name" required>
          <select name="status">
            <option value="planning">planning</option>
            <option value="in-progress">in-progress</option>
            <option value="blocked">blocked</option>
            <option value="done">done</option>
          </select>
          <input name="milestone" placeholder="Milestone (optional)">
          <input name="repo_path" placeholder="Repo path (optional)">
          <textarea name="description" placeholder="One-line description" rows="2"></textarea>
          <button type="submit">Create</button>
        </form>
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

    def _read_form(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = urllib.parse.parse_qs(raw)
        return {k: v[0] for k, v in parsed.items()}

    def do_GET(self):
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
        form = self._read_form()

        if self.path == "/project":
            name = form.get("name", "").strip()
            if name:
                slug = slugify(name)
                (DATA / "projects").mkdir(parents=True, exist_ok=True)
                content = (
                    "---\n"
                    f"name: {name}\n"
                    f"status: {form.get('status', 'planning')}\n"
                    f"milestone: {form.get('milestone', '')}\n"
                    f"repo_path: {form.get('repo_path', '')}\n"
                    "---\n\n"
                    f"## Description\n{form.get('description', '')}\n\n"
                    "## Current State\n\n## Open Decisions\n\n## Next Actions\n- [ ]\n"
                )
                (DATA / "projects" / f"{slug}.md").write_text(content, encoding="utf-8")
            self._redirect_home()

        elif self.path == "/inbox":
            text = form.get("text", "").strip()
            if text:
                (DATA / "inbox").mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                slug = slugify(text[:40])
                (DATA / "inbox" / f"{ts}-{slug}.md").write_text(text + "\n", encoding="utf-8")
            self._redirect_home()

        elif self.path == "/inbox/dismiss":
            fname = form.get("file", "")
            target = (DATA / "inbox" / fname).resolve()
            if target.parent == (DATA / "inbox").resolve() and target.exists():
                target.unlink()
            self._redirect_home()

        elif self.path == "/decision":
            topic = form.get("topic", "").strip()
            if topic:
                (DATA / "decisions").mkdir(parents=True, exist_ok=True)
                date = datetime.date.today().isoformat()
                slug = slugify(topic)
                content = (
                    f"# {topic}\n\n"
                    f"## Context\n{form.get('context', '')}\n\n"
                    f"## Options Considered\n{form.get('options', '')}\n\n"
                    f"## Decision\n{form.get('decision', '')}\n\n"
                    f"## Consequences\n{form.get('consequences', '')}\n"
                )
                (DATA / "decisions" / f"{date}-{slug}.md").write_text(content, encoding="utf-8")
            self._redirect_home()

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Harness dashboard at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
