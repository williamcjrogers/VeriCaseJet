"""Integration-level sanity checks.

This file previously referenced a scaffold `src.*` package that does not exist in this
repository. It now validates behavior of the spam/non-email classifier that drives
batch retroactive filtering and PST ingest decisions.
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


from api.app.spam_filter import SpamClassifier  # noqa: E402


class TestSpamFilterIntegration(unittest.TestCase):

    def setUp(self):
        self.classifier = SpamClassifier()

    def test_ipm_activity_is_classified_as_non_email_and_hidden(self):
        res = self.classifier.classify(
            subject="IPM.Activity", sender="user@example.com"
        )
        self.assertTrue(res["is_spam"])
        self.assertEqual(res["category"], "non_email")
        self.assertEqual(res["score"], 100)
        self.assertTrue(res["is_hidden"])

    def test_other_project_is_classified_and_hidden(self):
        res = self.classifier.classify(
            subject="Peabody — weekly update", sender="someone@example.com"
        )
        self.assertTrue(res["is_spam"])
        self.assertEqual(res["category"], "other_projects")
        self.assertTrue(res["is_hidden"])


if __name__ == "__main__":
    unittest.main()
