# data/ — Persistent Memory

File-based memory for this workspace. JSON/markdown only — no external DB. See `agentic-os` in the skill library for the full pattern this follows.

| Directory | Purpose | Tracked in git? |
|---|---|---|
| `daily-logs/` | Append-only per-day session logs | No (ephemeral) |
| `projects/` | One file per project this workspace tracks context for | Yes |
| `decisions/` | Lightweight ADRs — architectural/business decisions with rationale | Yes |
| `inbox/` | Untriaged tasks/ideas awaiting a decision | No (ephemeral) |
| `templates/` | Reusable file templates (e.g. `project.md`) | Yes |

Rules:
- Logs are append-only — never edit a past day's log.
- Every agent that produces a durable fact writes it back here before finishing (see each `agents/*.md` Memory Scope).
- Read the relevant files here at the start of a task before assuming there's no prior context.
