---
name: agentic_harness
status: in-progress
milestone: Pushed initial harness + dashboard to GitHub
repo_path: https://github.com/aquagitrepo/agentic_harness.git
---

## Description
The agentic-OS harness itself — this workspace. Kernel (`CLAUDE.md`), specialist agents (`@dev`/`@writer`/`@researcher`/`@ops`), slash commands (`/daily-sync`, `/decision`, `/new-project`, `/status`), file-based memory under `data/`, and a local read/write dashboard (`scripts/dashboard.py`). Built on top of the existing 296-skill ECC library, routed through `ecc-router`.

## Current State
- Flattened the original nested folder, git-initialized, committed.
- Local dashboard (stdlib Python, 127.0.0.1:8787) live for viewing/editing projects, inbox, decisions, and the latest daily log.
- Pushed to `origin/main` at github.com/aquagitrepo/agentic_harness as of 2026-09-24. Later work (chat app, wizard, tests, review fixes, and the 2026-09-25 upgrade) is committed on the local `harness-upgrade` branch, not pushed.
- Chat app (`chat/`, 127.0.0.1:8788) runs on the Claude API; needs ANTHROPIC_API_KEY in the server's terminal.
- 2026-09-25 upgrade:
  - The `.venv` runs both apps and all tests.
  - The ecc-router index shrank from 75 KB to 29.5 KB; full descriptions are in `index-full.md`, rebuilt by `scripts/build_skill_index.py`.
  - The chat plans on Sonnet 5 and logs spend to `data/costs/`.
  - The agents are Claude Code subagents in `.claude/agents/`.
  - `scripts/session_context.py` gives the few-line status that `/status` and `/daily-sync` use.

## Open Decisions
- No scheduled/unattended automation configured (decided early on) — everything runs interactively.
- Git identity and GitHub auth set up locally (repo-scoped identity, Git Credential Manager as global credential helper) rather than via GitHub CLI (not installed on this machine) or the MCP GitHub connector (not authorized/available this session).
- Agents as subagents: `data/decisions/2026-09-25-agents-as-claude-code-subagents.md`.
- Chat planning model: `data/decisions/2026-09-25-chat-planning-on-sonnet-5.md`.

## Next Actions
- [ ] Register a real (non-meta) project via `/new-project <name>` to start using the harness for actual work.
- [ ] Add a SessionStart hook running `python scripts/session_context.py` to `.claude/settings.json`, and prune the one-off `Bash(...)` rules in `.claude/settings.local.json`. Claude Code's auto mode blocked Claude from editing its own settings, so this needs a person.
- [ ] Live-test the chat's Sonnet 5 planning call with a real API key.
- [ ] Review and merge `harness-upgrade`, then push.
