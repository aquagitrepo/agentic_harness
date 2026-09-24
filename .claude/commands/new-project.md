# /new-project <name>

Register a new project in this workspace's memory:

1. Create `data/projects/<slug>.md` from `data/templates/project.md`.
2. Fill in what's known: name, one-line description, repo path (if any), status, milestone.
3. If the project lives in its own repo/folder, note that path — this harness's `data/` tracks context about it, not the code itself.
4. Confirm the file was created and summarize it back.
