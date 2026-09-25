---
name: sentiment analysis
status: in-progress
milestone: Working stdlib Naive Bayes baseline
repo_path: projects/sentiment-analysis
---

## Description
Sentiment classifier, starting from a dependency-free baseline before deciding on a real model/dataset.

## Current State
- `projects/sentiment-analysis/sentiment.py`: bag-of-words + Naive Bayes, stdlib only, trained/evaluated on a small hand-written dataset (32 train / 6 test).
- The pipeline runs end to end, but there is no meaningful accuracy number yet. The 6-example spot-check (4/6) is noise: leave-one-out on the 32 training sentences is 37.5%, below always guessing "pos" (50%).
- Text with no known words now returns "unknown" instead of a fake "neg".
- A stopword filter fixed two obviously wrong spot-check predictions, but this evaluation is too small to show whether it helps overall.

## Open Decisions
- See `data/decisions/2026-09-24-sentiment-analysis-baseline-approach.md`.

## Next Actions
- [ ] Decide on a real labeled dataset (or the project's actual data source) instead of the 32 hand-written sentences.
- [ ] Re-evaluate once real data is in; consider scikit-learn (TF-IDF + linear model) as the next step up.
