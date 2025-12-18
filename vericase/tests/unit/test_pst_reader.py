"""Unit tests for SpamClassifier.

This file previously referenced a scaffold `src.*` module. PST reading in VeriCase
is handled by ingest code paths that depend on optional libraries; the spam classifier
is pure-Python and safe to unit test in isolation.
"""

import os
import sys
import unittest


# Provide minimal env for Settings validation during import.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

# Ensure `api` package is importable when running from repo root.
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.spam_filter import SpamClassifier, classify_email  # noqa: E402


class TestSpamClassifier(unittest.TestCase):

    def setUp(self):
        self.classifier = SpamClassifier()

    def test_medium_confidence_is_boosted_by_spammy_sender(self):
        res = self.classifier.classify(
            subject="Automatic reply: out of office",
            sender="noreply@example.com",
        )
        self.assertTrue(res["is_spam"])
        self.assertEqual(res["category"], "out_of_office")
        self.assertEqual(res["score"], 85)
        self.assertFalse(res["is_hidden"])  # medium confidence groups do not auto-hide

    def test_spammy_sender_without_subject_match_is_low_confidence(self):
        res = classify_email(subject="Hello", sender="noreply@vendor.com")
        self.assertTrue(res["is_spam"])
        self.assertEqual(res["category"], "automated")
        self.assertEqual(res["score"], 40)
        self.assertFalse(res["is_hidden"])

    def test_batch_classification_returns_one_result_per_email(self):
        results = self.classifier.classify_batch(
            [
                {"subject": "Webinar: Join us", "sender": "marketing@example.com"},
                {"subject": "Re: Project update", "sender": "user@example.com"},
            ]
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["is_spam"])
        self.assertFalse(results[1]["is_spam"])


if __name__ == "__main__":
    unittest.main()
