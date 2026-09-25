"""Short status of data/ for the start of a Claude Code session and for /status.

A few lines instead of every file under data/: projects, untriaged inbox items,
the latest decision, the latest daily log's open next actions, and today's chat
API spend. Stdlib only, so a session-start hook can run it with any Python.
Run: python scripts/session_context.py [data_dir]
"""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard import DATA, first_heading, one_line, parse_frontmatter, read_files, read_text  # noqa: E402

MAX_ITEMS = 8


def clip(text: str, limit: int = 80) -> str:
    text = one_line(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def open_actions(log_text: str) -> list:
    return [clip(line.strip()[5:]) for line in log_text.splitlines()
            if line.strip().startswith("- [ ]") and line.strip()[5:].strip()]


def spend_today(data: Path, today: datetime.date) -> str:
    path = data / "costs" / f"{today:%Y-%m-%d}.jsonl"
    calls, usd = 0, 0.0
    for line in read_text(path).splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            calls += 1
            usd += row.get("usd") or 0
    return f"Chat API spend today: ~${usd:.4f} over {calls} call{'s' * (calls != 1)}" if calls else ""


def summary(data: Path = DATA, today: datetime.date = None) -> str:
    projects = []
    for path in read_files(data / "projects"):
        fm, _ = parse_frontmatter(read_text(path))
        entry = f"{clip(fm.get('name') or path.stem, 40)} ({fm.get('status') or 'no status'})"
        projects.append(entry + (f": {clip(fm['milestone'])}" if fm.get("milestone") else ""))
    lines = ["Harness status (from data/):",
             "- Projects: " + ("; ".join(projects[:MAX_ITEMS]) if projects else "none registered")]

    inbox = read_files(data / "inbox")
    titles = [clip((read_text(p).strip().splitlines() or [p.stem])[0], 60) for p in inbox[:3]]
    lines.append(f"- Inbox: {len(inbox)} untriaged: " + "; ".join(titles) if inbox else "- Inbox: empty")

    decisions = read_files(data / "decisions")
    if decisions:
        latest = decisions[-1]
        lines.append(f"- Latest decision: {clip(first_heading(read_text(latest)) or latest.stem)} ({latest.name})")

    logs = read_files(data / "daily-logs")
    if logs:
        actions = open_actions(read_text(logs[-1]))
        lines.append(f"- Latest daily log ({logs[-1].stem}) next actions: "
                     + ("; ".join(actions[:MAX_ITEMS]) if actions else "none open"))

    spend = spend_today(data, today or datetime.date.today())
    if spend:
        lines.append(f"- {spend}")
    return "\n".join(lines)


if __name__ == "__main__":
    # A hook's stdout is a pipe, which Windows encodes as cp1252: one non-ASCII project name would crash it.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(summary(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA))
