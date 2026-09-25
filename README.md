# claude git — Agentic Dev Workspace

A reusable agentic-OS harness for Claude Code, built on the ECC skill library. It's the coordination layer for projects you build here or point it at, plus two small local tools on top of it: a dashboard and a beginner-friendly chat.

## Layout

| Path | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Kernel: identity, agent registry, routing rules |
| `agents/` | Specialist agent personas (`@dev`, `@writer`, `@researcher`, `@ops`) |
| `.claude/commands/` | Slash commands — `/daily-sync`, `/decision`, `/new-project`, `/status` |
| `data/` | File-based persistent memory — see `data/README.md` |
| `scripts/dashboard.py` | Local dashboard over `data/` (port 8787) |
| `chat/` | Beginner-friendly chat harness on the Claude API (port 8788) |
| `tests/` | Retained regression tests, run with the `.venv` Python (see Onboarding) |
| `projects/` | Code for projects tracked in `data/projects/` |
| `.claude/skill-library/` | 296-skill ECC library, indexed by the `ecc-router` skill |
| `ECC_SKILLS_LIBRARY.md` / `ECC_Skills_Catalog.pdf` | Full ECC catalog reference |

## Using it

- Start a session here; `CLAUDE.md` loads automatically and routes work to the right agent.
- Run `/new-project <name>` to register a project this workspace should track context for.
- Run `/daily-sync` or `/status` for a briefing.
- For specialized domain work (a framework, security review, infra pattern, etc.), the kernel consults `ecc-router` automatically — you don't need to invoke it by name.

## Dashboard

A local, read/write web UI over `data/` — the same files the slash commands use, so it stays in sync with no separate database. Python stdlib only, binds to `127.0.0.1` (not reachable from outside this machine).

```bash
python scripts/dashboard.py
# then open http://127.0.0.1:8787
```

Or, inside a Claude Code session, ask to preview the `harness-dashboard` launch config (`.claude/launch.json`). Shows projects, inbox, decisions, and the latest daily log, with forms to register a project, add/dismiss inbox items, and log a decision.

## Chat (beginner-friendly harness)

A chat version of the whole harness that shows its work while it runs. Each message goes through the same loop the kernel uses (understand, pick an agent from `agents/`, plan, research, build). You watch search agents fan out across the web, and the answer builds block by block as each planned section streams in. If you're starting something and haven't said enough yet, it asks a few simple questions first instead of guessing. "Save this chat as a project" writes a normal `data/projects/` file.

Claude does the thinking and writing through the Anthropic API. It defaults to `claude-opus-5`, and you can switch to `claude-sonnet-5` in the sidebar for lower cost. The search agents use the open-source [ddgs](https://pypi.org/project/ddgs/) library for DuckDuckGo searches. Each message makes two Claude calls, one to plan and one to write, and each costs real money on your API account. On `claude-opus-5`, if Claude's safety filter declines a request, the API retries it on its recommended fallback model (`fallbacks: "default"`). `claude-sonnet-5` has no fallback, so a declined request just shows a message.

Both local servers only accept requests from their own page on this machine. Other websites you visit can't post to them or read them.

You need your own Claude API key from https://console.anthropic.com. Put it in an environment variable in your own terminal. Never paste it into the chat or commit it to a file.

```powershell
$env:ANTHROPIC_API_KEY = "<your key>"   # this terminal only; use setx to keep it permanently
.venv\Scripts\python chat/server.py
# then open http://127.0.0.1:8788
```

No scheduled/unattended automation is configured — everything here runs interactively, by request.

## Onboarding (for anyone else using this repo)

1. **Clone it, then open a Claude Code session with this folder as the working directory.** `CLAUDE.md` loads automatically — nothing else to configure to start.
2. **Prerequisites**: git and Python 3.10+. The dashboard uses only the standard library. The chat needs the packages in `chat/requirements.txt` and your own Claude API key. Install the packages once into a `.venv` in the repo root. The preview configs in `.claude/launch.json` and the tests both use it:
   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -r chat/requirements.txt
   .venv\Scripts\python -m unittest discover -s tests
   ```
   On macOS/Linux the interpreter is `.venv/bin/python`; change `runtimeExecutable` in `.claude/launch.json` to match.
3. **Set your own git identity** in your clone before committing — don't assume the committer's identity carries over:
   ```bash
   git config user.name "Your Name"
   git config user.email "you@example.com"
   ```
4. **What's shared vs. personal**, since this matters more with more than one person:
   - `data/projects/`, `data/decisions/`, `data/templates/`, `agents/`, `.claude/commands/`, `CLAUDE.md` — git-tracked, shared team context. Treat conflicts on these like any other collaboratively-edited file.
   - `data/daily-logs/`, `data/inbox/` — gitignored, personal and local to your machine. Your `/daily-sync` history doesn't sync to teammates and theirs doesn't sync to you.
   - The dashboard (`scripts/dashboard.py`) is local-only per person (`127.0.0.1`) — there's no shared/networked instance; everyone reads the same git-tracked files but through their own local server.
5. **Register your own work** with `/new-project <name>` rather than repurposing someone else's project file. Use `/decision` when you make a real tradeoff call, so teammates get the *why*, not just the diff.
6. **Extending the harness itself** (new agent, new command, new convention) is a change to `CLAUDE.md`/`agents/`/`.claude/commands/` — open it as a normal PR like any other shared code, since everyone's session reads these at startup.
