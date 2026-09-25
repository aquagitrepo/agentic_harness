# /new-project <name>

Don't hand the user a form or ask for field names (status, milestone, repo_path) — they shouldn't need to know this harness's internal structure. Interview them like a teammate, in plain language, one question at a time:

1. "What do you want to build?" — let them answer in their own words, no jargon back.
2. "What would a first working version actually do?" — this becomes the milestone, but don't call it that to them.
3. "Where's the data/input coming from, if any?" — a file they have, a public dataset, an API, or "don't know yet." If it points at an external source needing an account or API key, tell them plainly what account/login they'll need and that they should set it up themselves — never ask them to paste a credential into chat.
4. Only if their goal is genuinely ambiguous or has a real fork in approach (e.g. "quick and rough" vs "accurate but slower"), ask a single clarifying multiple-choice question. Don't interrogate past what's needed to start.

Then, without involving the user in the mechanics:
- Translate their answers into `data/projects/<slug>.md` yourself, in the same format the dashboard and chat write (see `data/README.md`): frontmatter `name`, `status: planning`, `milestone`, `repo_path` (leave empty until code exists, then the code's folder such as `projects/<slug>` or a repo URL), then `## Description`, a `Data/input:` line, `## Current State`, `## Open Decisions`, `## Next Actions`. Keep every frontmatter value on one line. If the file already exists, use `<slug>-2.md` rather than overwriting it.
- Summarize back in plain language what you understood ("So: a tool that does X, starting from Y, first version does Z — sound right?") so they can correct you before any building starts.
- Only after they confirm, start on the actual work (or hand off to `@dev`).
