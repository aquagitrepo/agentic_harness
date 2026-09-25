# Sentiment analysis: start with a stdlib Naive Bayes baseline

## Context
Needed a first working sentiment classifier to validate the project end to end before investing in a bigger dependency (scikit-learn, transformers, a labeled dataset download).

## Options Considered
- Lexicon-based (word list + polarity score): simplest, but brittle on negation/sarcasm and gives no confidence signal worth trusting.
- scikit-learn (TF-IDF + logistic regression / linear SVM): standard, robust choice, but adds a dependency and setup step before we've even confirmed the project's real data source.
- Transformer (e.g. a pretrained sentiment model): best accuracy, but heavy (model download, GPU/CPU cost) for a first pass.
- Hand-rolled Naive Bayes, stdlib only: weakest ceiling on accuracy, but zero dependencies and runs instantly anywhere.

## Decision
Built the hand-rolled stdlib Naive Bayes baseline (`projects/sentiment-analysis/sentiment.py`) first, to prove the pipeline (train → evaluate → predict) before adding any dependency.

## Consequences
- Spot-checking showed function words ("this", "was", "an") flipping clear-cut sentences, so a stopword filter was added. Correction (2026-09-24 review): the 6-example check can't show the filter helps; with or without it the test predictions are identical.
- Correction (2026-09-24 review): the reported "67% held-out accuracy" was noise, not a baseline result. Leave-one-out on the training set is 37.5%, below the 50% of always guessing "pos", and unknown words defaulted to "neg". Treat this as a working pipeline with no measured accuracy.
- Next step before this is "real": replace the 32-sentence hand-written dataset with a real labeled dataset (e.g. IMDB, SST-2, or the project's actual data source) and re-evaluate; consider scikit-learn once a real dataset exists.
