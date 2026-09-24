# claude git — Agentic Dev Workspace

A reusable agentic-OS harness for Claude Code, built on the ECC skill library. This workspace has no application code of its own — it's the coordination layer for projects you build here or point it at.

## Layout

| Path | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Kernel: identity, agent registry, routing rules |
| `agents/` | Specialist agent personas (`@dev`, `@writer`, `@researcher`, `@ops`) |
| `.claude/commands/` | Slash commands — `/daily-sync`, `/decision`, `/new-project`, `/status` |
| `data/` | File-based persistent memory — see `data/README.md` |
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

No scheduled/unattended automation is configured — everything here runs interactively, by request.
