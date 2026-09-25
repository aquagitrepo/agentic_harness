"""Baseline sentiment classifier: bag-of-words + Naive Bayes, stdlib only.

First pass for the sentiment-analysis project tracked in
data/projects/sentiment-analysis.md. No external deps so it runs anywhere;
swap in scikit-learn or a transformer later if the baseline isn't enough.
"""

import argparse
import math
import re
from collections import Counter, defaultdict

TRAIN_DATA = [
    ("I love this movie, it was fantastic", "pos"),
    ("What a wonderful, uplifting experience", "pos"),
    ("This is the best product I've ever bought", "pos"),
    ("Absolutely amazing service, highly recommend", "pos"),
    ("The food was delicious and the staff were kind", "pos"),
    ("I'm so happy with how this turned out", "pos"),
    ("Great value for money, works perfectly", "pos"),
    ("She did a fantastic job on the presentation", "pos"),
    ("The concert was incredible, best night ever", "pos"),
    ("Really impressed with the quality and speed", "pos"),
    ("Such a delightful and charming little cafe", "pos"),
    ("The team exceeded all my expectations", "pos"),
    ("I can't stop smiling after that great news", "pos"),
    ("Wonderful customer support, solved my issue instantly", "pos"),
    ("This book was a joy to read from start to finish", "pos"),
    ("Brilliant design, very easy to use", "pos"),
    ("I hate waiting this long for a simple refund", "neg"),
    ("Terrible experience, would not recommend at all", "neg"),
    ("The movie was boring and way too long", "neg"),
    ("Worst customer service I've ever dealt with", "neg"),
    ("This product broke after one day, total waste", "neg"),
    ("I'm so disappointed with the quality", "neg"),
    ("The food was cold and tasted awful", "neg"),
    ("Such a frustrating and confusing interface", "neg"),
    ("The staff were rude and unhelpful", "neg"),
    ("This was a complete disaster from start to finish", "neg"),
    ("I regret buying this, total waste of money", "neg"),
    ("Painfully slow and constantly crashes", "neg"),
    ("Never coming back to this place again", "neg"),
    ("The concert was a letdown, terrible sound quality", "neg"),
    ("Such an unpleasant and stressful ordeal", "neg"),
    ("Absolutely furious about how this was handled", "neg"),
]

TEST_DATA = [
    ("I really enjoyed this, it made my day", "pos"),
    ("Pretty good overall, would buy again", "pos"),
    ("Such a pleasant surprise, well done", "pos"),
    ("This is awful, I want a refund", "neg"),
    ("Not happy with this at all", "neg"),
    ("Disappointing and overpriced", "neg"),
]

TOKEN_RE = re.compile(r"[a-z']+")

# Function words carry no sentiment signal but dominate raw counts on a
# dataset this small (seen empirically: they flipped clear-cut predictions).
STOPWORDS = {
    "a", "an", "the", "this", "that", "is", "was", "were", "am", "are",
    "i", "it", "to", "of", "and", "in", "on", "for", "with", "from", "at",
}


def tokenize(text: str) -> list:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


class NaiveBayesClassifier:
    def __init__(self):
        self.class_word_counts = defaultdict(Counter)
        self.class_totals = Counter()
        self.class_doc_counts = Counter()
        self.vocab = set()

    def fit(self, examples):
        for text, label in examples:
            tokens = tokenize(text)
            self.class_doc_counts[label] += 1
            for token in tokens:
                self.class_word_counts[label][token] += 1
                self.class_totals[label] += 1
                self.vocab.add(token)

    def _log_likelihood(self, label: str, tokens: list) -> float:
        vocab_size = len(self.vocab)
        denom = self.class_totals[label] + vocab_size
        log_prob = 0.0
        for token in tokens:
            count = self.class_word_counts[label][token]
            log_prob += math.log((count + 1) / denom)
        return log_prob

    def predict_proba(self, text: str) -> dict:
        tokens = tokenize(text)
        total_docs = sum(self.class_doc_counts.values())
        scores = {}
        for label in self.class_doc_counts:
            log_prior = math.log(self.class_doc_counts[label] / total_docs)
            scores[label] = log_prior + self._log_likelihood(label, tokens)
        max_score = max(scores.values())
        exp_scores = {label: math.exp(s - max_score) for label, s in scores.items()}
        total = sum(exp_scores.values())
        return {label: s / total for label, s in exp_scores.items()}

    def knows_any(self, text: str) -> bool:
        return any(token in self.vocab for token in tokenize(text))

    def predict(self, text: str) -> str:
        # With no known words the scores differ only by smoothing noise, which used to read as a confident "neg".
        if not self.knows_any(text):
            return "unknown"
        proba = self.predict_proba(text)
        return max(proba, key=proba.get)


def evaluate(model: NaiveBayesClassifier, examples) -> float:
    correct = sum(1 for text, label in examples if model.predict(text) == label)
    return correct / len(examples)


def main():
    parser = argparse.ArgumentParser(description="Baseline sentiment classifier")
    parser.add_argument("text", nargs="*", help="Sentence(s) to classify")
    args = parser.parse_args()

    model = NaiveBayesClassifier()
    model.fit(TRAIN_DATA)

    accuracy = evaluate(model, TEST_DATA)
    print(f"Spot-check: {accuracy:.0%} of {len(TEST_DATA)} hand-written examples "
          "(far too few to measure real accuracy; always guessing 'pos' scores 50%)")

    if args.text:
        for text in args.text:
            label = model.predict(text)
            if label == "unknown":
                print(f'"{text}" -> unknown (none of its words were in the training data)')
            else:
                print(f'"{text}" -> {label} ({model.predict_proba(text)[label]:.0%} confidence)')


if __name__ == "__main__":
    main()
