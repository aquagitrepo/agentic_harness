# /daily-sync

Run the morning briefing for this workspace:

1. Start from the harness status: the session-start hook's output if it's already in context, otherwise run `python scripts/session_context.py`.
2. Read the most recent entry in `data/daily-logs/` in full for continuity, and run `git status` in the repo(s) of active projects where applicable.
3. If the status shows untriaged inbox items, read them in `data/inbox/`.
4. Summarize: what's in flight, what's blocked, what the sensible next actions are.
5. Append a new entry to `data/daily-logs/<today's date>.md` with that summary.
