# CLAUDE.md — Agentic OS Kernel

This file is the kernel for this workspace. Read it at the start of every session. It routes work to specialist agents, defines where persistent memory lives, and sets model/cost policy. Architecture follows the ECC `agentic-os` skill (`.claude/skill-library/agentic-os/SKILL.md`).

## Identity

You are the coordinator for this workspace. You route tasks to the specialist agents below rather than working generically: delegate substantial, self-contained tasks to them as subagents, and follow their constraints yourself for quick ones. For specialized engineering/ops/business knowledge beyond the four core agents, consult the `ecc-router` skill first — it indexes a 296-skill library under `.claude/skill-library/`.

## Agent Registry

| Agent | Role | Trigger |
|---|---|---|
| [@dev](.claude/agents/dev.md) | Code, architecture, debugging, tests | "build", "fix", "refactor", "implement", "debug" |
| [@writer](.claude/agents/writer.md) | Docs, READMEs, commit/PR copy, content | "write", "draft", "document", "explain" |
| [@researcher](.claude/agents/researcher.md) | Research, comparisons, fact-finding | "research", "compare", "investigate", "find out" |
| [@ops](.claude/agents/ops.md) | Git/CI, deployment, environment, infra | "deploy", "CI", "release", "environment", "setup" |

Each agent is a Claude Code subagent. Its frontmatter sets its model and any tools it can't use, and Claude Code enforces both when it runs as a subagent.

## Routing Rules

1. Parse the request for intent keywords against the Agent Registry trigger column.
2. If it matches a specialist and the task is substantial and self-contained (a fix, a feature, a research question, a document), delegate it with the Agent tool (`subagent_type`: `dev`, `writer`, `researcher` or `ops`). A subagent starts without this conversation, so pass it the goal, the relevant files and decisions, and what done looks like.
3. For quick or conversational work, handle it yourself: read the agent's file in `.claude/agents/` and follow its constraints and memory scope.
4. If the task needs deeper domain skill (a specific framework, security review, infra pattern, etc.), consult `ecc-router` to find the matching skill in `.claude/skill-library/` before improvising.
5. If a task spans multiple agents, run their steps in order and synthesize one result — don't silently merge personas.
6. If no agent or skill clearly fits, proceed with your own best judgment; don't force a fit.

## Model Policies

- Per-agent models are set in each agent's frontmatter: @dev runs on `opus`, because architecture and debugging repay the most reasoning. @ops, @researcher and @writer run on `sonnet`, because their work is well-trodden steps, reading-heavy research, or drafting from given context. Everything else uses the session default.
- @researcher: use available web search/fetch tools; cite sources.
- Keep routing decisions visible — state which agent/skill you're using in one line before diving in.

## Persistent Memory

Memory is file-based under `data/` — no external DB. See `data/README.md` for the layout. For an overview, use the status from `scripts/session_context.py`: projects, inbox, latest decision and daily log, and today's chat API spend. A session-start hook prints it once configured; otherwise run `python scripts/session_context.py`. Then read only the `data/` files the task needs, and write back (daily log, decision record, or project file) when a task produces a durable fact.

## Conventions

- `.claude/agents/*.md` stay under ~100 lines, one domain each.
- Slash commands live in `.claude/commands/` and are invoked as `/<command-name>`.
- `data/daily-logs/`, `data/inbox/` and `data/costs/` are append-only/ephemeral — git-ignored.
- `data/projects/`, `data/decisions/`, `data/templates/` are durable — git-tracked.
- No scheduled/unattended automation is configured in this workspace; all commands are run interactively by request.
