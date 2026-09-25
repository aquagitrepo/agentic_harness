# Harness Studio: Claude API engine, Python runs automatically

## Context
The user wanted a more interactive chat: one that works out what they mean, asks the right questions, and builds the project live. They asked whether a free API could power it.

## Options Considered
- **Local model via Ollama.** Free, private and unlimited. It's already installed here with `qwen2.5:32b`, which did a working tool call at ~29 tokens/s on the RTX A5000. It's weaker than Claude at intent and multi-file code.
- **Claude API.** The best at understanding intent and writing code, and API traffic isn't used for training. It's paid per use: there's no free tier, just a small one-time credit for new Console accounts.
- **Claude Code login through the Agent SDK.** Not allowed. Anthropic's docs say third-party tools must use API-key authentication.
- **Free cloud tiers.**
  - Groq doesn't train on data, but its 8K tokens/minute cap stalls a build loop.
  - The Gemini free tier and OpenRouter free models may train on prompts.
  - GitHub Models was retired in July 2026.
- **Running generated code:** ask before each run, run automatically, or never run.

## Decision
The user chose **Claude API only** and **run Python automatically**. `chat/studio.py` runs one Claude tool-use loop per message, on `claude-opus-5` at high effort or `claude-sonnet-5`. It uses prompt caching and Opus 5's server-side refusal fallback.

Nothing is written or run until the user approves a plan, and every file path is confined to `projects/<slug>/`. Runs:
- are `python <file>` only;
- stop after 60 seconds and get no keyboard input;
- can't install packages;
- run without any environment variable whose name contains KEY, TOKEN, SECRET, PASSWORD or CREDENTIAL.

A user message stops after 30 Claude calls.

## Consequences
- Every session costs money. The sidebar shows the running estimate, and `data/costs/` records each call.
- Generated code still runs with the user's own permissions and network access: the safeguards limit accidents, not intent.
- Adding Ollama later as a second engine is still open. The tool loop would need a provider layer for a non-Anthropic API.
- Tests only cover a scripted stand-in for the API. The first live session is the real check on the request shape.
