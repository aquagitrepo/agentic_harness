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
- Pushed to `origin/main` at github.com/aquagitrepo/agentic_harness (as of 2026-09-24; later work — chat app, wizard, tests, review fixes — not yet committed).
- Chat app (`chat/`, 127.0.0.1:8788) runs on the Claude API; needs ANTHROPIC_API_KEY in the server's terminal.

## Open Decisions
- No scheduled/unattended automation configured (decided early on) — everything runs interactively.
- Git identity and GitHub auth set up locally (repo-scoped identity, Git Credential Manager as global credential helper) rather than via GitHub CLI (not installed on this machine) or the MCP GitHub connector (not authorized/available this session).

## Next Actions
- [ ] Register a real (non-meta) project via `/new-project <name>` to start using the harness for actual work.
