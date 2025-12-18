"""Unit tests for small email classification utilities.

This file previously referenced a scaffold `src.*` module. It now tests helpers that
populate legacy metadata fields (e.g. `other_project`) used by filtering/analytics.
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


from api.app.spam_filter import extract_other_project  # noqa: E402


class TestOtherProjectExtraction(unittest.TestCase):

    def test_extract_returns_none_on_empty(self):
        self.assertIsNone(extract_other_project(None))
        self.assertIsNone(extract_other_project(""))

    def test_extract_title_cases_common_keywords(self):
        self.assertEqual(extract_other_project("Re: peabody update"), "Peabody")

    def test_extract_handles_special_casing(self):
        self.assertEqual(extract_other_project("MTVH programme"), "MTVH")
        self.assertEqual(extract_other_project("lsa weekly"), "LSA")
        self.assertEqual(extract_other_project("befirst new build"), "BeFirst")


if __name__ == "__main__":
    unittest.main()
