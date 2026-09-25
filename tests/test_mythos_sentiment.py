"""Retained tests for the sentiment baseline's honesty fixes."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "projects" / "sentiment-analysis"))

import sentiment  # noqa: E402


class SentimentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = sentiment.NaiveBayesClassifier()
        cls.model.fit(sentiment.TRAIN_DATA)

    def test_unknown_words_are_not_a_confident_negative(self):
        self.assertEqual(self.model.predict("zzz qqq"), "unknown")
        self.assertEqual(self.model.predict(""), "unknown")

    def test_clear_cases_from_the_review(self):
        self.assertEqual(self.model.predict("This was an absolutely wonderful experience"), "pos")
        self.assertEqual(self.model.predict("I am furious, this is the worst service ever"), "neg")


if __name__ == "__main__":
    unittest.main()
