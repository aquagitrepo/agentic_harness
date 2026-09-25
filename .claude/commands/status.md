# /status

Give a snapshot of where things stand:

1. Get the harness status: use the session-start hook's output if it's already in context, otherwise run `python scripts/session_context.py`. It lists projects with their status, untriaged inbox items, the latest decision, the latest daily log's open actions, and today's chat API spend.
2. Present it as a short list. Open individual `data/` files only if something in it needs explaining.
3. Keep it to a glance, not a report.
