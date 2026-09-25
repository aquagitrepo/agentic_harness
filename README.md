# claude git — Agentic Dev Workspace

A reusable agentic-OS harness for Claude Code, built on the ECC skill library. It's the coordination layer for projects you build here or point it at, plus two small local tools on top of it: a dashboard and a beginner-friendly chat.

## Layout

| Path | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Kernel: identity, agent registry, routing rules |
| `.claude/agents/` | Specialist agents (`@dev`, `@writer`, `@researcher`, `@ops`). Each is a Claude Code subagent with its own model and tool limits |
| `.claude/commands/` | Slash commands — `/daily-sync`, `/decision`, `/new-project`, `/status` |
| `data/` | File-based persistent memory — see `data/README.md` |
| `scripts/dashboard.py` | Local dashboard over `data/` (port 8787) |
| `scripts/session_context.py` | A few-line status of `data/` for `/status`, `/daily-sync`, and a session-start hook |
| `chat/` | Beginner-friendly chat harness on the Claude API (port 8788) |
| `tests/` | Retained regression tests, run with the `.venv` Python (see Onboarding) |
| `projects/` | Code for projects tracked in `data/projects/` |
| `.claude/skill-library/` | 296-skill ECC library, indexed by the `ecc-router` skill. After changing it, rebuild the index with `scripts/build_skill_index.py` |
| `ECC_SKILLS_LIBRARY.md` / `ECC_Skills_Catalog.pdf` | Full ECC catalog reference, kept out of routine searches by `.ignore` |

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

A chat version of the whole harness that shows its work while it runs. Each message goes through the same loop the kernel uses (understand, pick an agent from `.claude/agents/`, plan, research, build). You watch search agents fan out across the web, and the answer builds block by block as each planned section streams in. If you're starting something and haven't said enough yet, it asks a few simple questions first instead of guessing. "Save this chat as a project" writes a normal `data/projects/` file.

Claude does the thinking and writing through the Anthropic API. Answers default to `claude-opus-5`, and you can switch to `claude-sonnet-5` in the sidebar for lower cost. The search agents use the open-source [ddgs](https://pypi.org/project/ddgs/) library for DuckDuckGo searches. Each message makes two Claude calls, and each costs real money on your API account. The first is a short planning call, which always runs on the cheaper `claude-sonnet-5`. The second writes the answer on the model you picked. "Save this chat as a project" also runs on `claude-sonnet-5`. On `claude-opus-5`, if Claude's safety filter declines a request, the API retries it on its recommended fallback model (`fallbacks: "default"`). `claude-sonnet-5` has no fallback. If it declines the planning call, the chat retries that call on the model you picked. A request that's still declined shows a message.

Every call's token counts and estimated cost at list price are appended to `data/costs/<date>.jsonl`, which stays on your machine.

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
   - `data/projects/`, `data/decisions/`, `data/templates/`, `.claude/agents/`, `.claude/commands/`, `CLAUDE.md` — git-tracked, shared team context. Treat conflicts on these like any other collaboratively-edited file.
   - `data/daily-logs/`, `data/inbox/`, `data/costs/` — gitignored, personal and local to your machine. Your `/daily-sync` history doesn't sync to teammates and theirs doesn't sync to you.
   - The dashboard (`scripts/dashboard.py`) is local-only per person (`127.0.0.1`) — there's no shared/networked instance; everyone reads the same git-tracked files but through their own local server.
5. **Register your own work** with `/new-project <name>` rather than repurposing someone else's project file. Use `/decision` when you make a real tradeoff call, so teammates get the *why*, not just the diff.
6. **Extending the harness itself** (new agent, new command, new convention) is a change to `CLAUDE.md`/`.claude/agents/`/`.claude/commands/` — open it as a normal PR like any other shared code, since everyone's session reads these at startup.
