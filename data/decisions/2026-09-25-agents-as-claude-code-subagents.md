# Agents become Claude Code subagents in .claude/agents/

## Context
The four agents were markdown personas in `agents/` that the kernel "adopted". Their Tool Access sections and CLAUDE.md's model policies were advice only: nothing stopped @writer from running shell commands or made @dev use a stronger model.

## Options Considered
- Keep `agents/` as personas: matches the `agentic-os` layout, but nothing is enforced.
- Generate `.claude/agents/` copies from `agents/`: keeps the layout, but the two copies drift unless a build step and a test guard them.
- Move the files to `.claude/agents/` with subagent frontmatter: one copy, enforced by Claude Code, at the cost of departing from the `agentic-os` directory layout.

## Decision
Moved them (`git mv`, history kept) and added frontmatter:
- @dev runs on `opus`.
- @ops, @researcher and @writer run on `sonnet`.
- @writer and @researcher have Bash disabled through `disallowedTools`, so they still inherit MCP tools.

The kernel delegates substantial, self-contained tasks to these agents with the Agent tool, and handles quick ones itself under the same constraints. The dashboard and the chat app read the personas from the new path.

## Consequences
- Tool limits and models are enforced only when an agent runs as a subagent. When the kernel handles a task itself, it still relies on following the file.
- A subagent starts without the conversation, so delegation prompts must carry the goal and the context.
- Changing an agent's model is a one-line frontmatter edit. Update CLAUDE.md's Model Policies to match.
