# data/ — Persistent Memory

File-based memory for this workspace. JSON/markdown only — no external DB. See `agentic-os` in the skill library for the full pattern this follows.

| Directory | Purpose | Meant to be committed? |
|---|---|---|
| `daily-logs/` | Append-only per-day session logs | No (gitignored) |
| `projects/` | One file per project this workspace tracks context for | Yes |
| `decisions/` | Lightweight ADRs — architectural/business decisions with rationale | Yes |
| `inbox/` | Untriaged tasks/ideas awaiting a decision | No (gitignored) |
| `costs/` | Chat API spend: one JSON line per Claude call (`<date>.jsonl`: step, model, token counts, estimated `usd` at list price) | No (gitignored) |
| `templates/` | Reusable file templates (e.g. `project.md`) | Yes |

"Yes" means these are shared once you commit them; new files stay local until then.

## Project file format

The dashboard wizard, the chat's "Save this chat as a project" and `/new-project` all write this shape (the first two through `write_project` in `scripts/dashboard.py`):

```markdown
---
name: Paint Checker
status: planning            # planning | in-progress | blocked | done
milestone: what a first working version does
repo_path:                  # empty until code exists, then e.g. projects/paint-checker or a repo URL
---

## Description
...

Data/input: where the data comes from

## Current State

## Open Decisions

## Next Actions
- [ ]
```

Frontmatter values are always one line, and existing files are never overwritten: a second project with the same name becomes `<name>-2.md`.

Rules:
- Logs are append-only — never edit a past day's log.
- Every agent that produces a durable fact writes it back here before finishing (see each `.claude/agents/*.md` Memory Scope).
- Read the relevant files here at the start of a task before assuming there's no prior context.
