# Chat app: planning and project summaries run on Sonnet 5

## Context
Each chat message makes a small structured-JSON planning call and a streamed answer. Both ran on the model picked for the answer, so with the Opus 5 default the planning call paid Opus prices ($5/$25 per million tokens).

## Options Considered
- Keep one model: simplest, and all calls share one cache namespace. But planning pays Opus prices. The plan and answer prompts differ, so there was no cache reuse between them to lose.
- Haiku 4.5 ($1/$5): cheapest. But it rejects the `effort` setting the app sends, so the request shape would differ, and routing needs judgment.
- Sonnet 5 ($2/$10): same request shape (effort plus structured outputs), and 60% cheaper per token than Opus 5.

## Decision
`ROUTER_MODEL = "claude-sonnet-5"` for the plan and the "save as project" summary, at low effort. Sonnet 5 has no server-side refusal fallback, and a key may not allow it. So a refusal or an unavailable model there is retried on the chosen model, and Opus 5 keeps its `fallbacks: "default"`. Opus 5 stays the default answer model. Opus 5.5 and Fable 5.1 aren't offered unless someone asks for them by name.

## Consequences
- Each call's spend is logged to `data/costs/<date>.jsonl`, so the saving can be checked against real usage.
- Not yet checked against the live API. The test stub only shows the requests are shaped as intended.
