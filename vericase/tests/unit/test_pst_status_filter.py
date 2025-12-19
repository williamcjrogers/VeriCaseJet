"""Unit tests for PST list status query parsing.

This test targets the small helper used by the PST history/live-tracking endpoints.
It is intentionally pure (no DB access required).
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


from api.app.correspondence import _parse_pst_status_filter  # noqa: E402


class TestParsePstStatusFilter(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(_parse_pst_status_filter(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_parse_pst_status_filter(""))

    def test_single_status(self):
        self.assertEqual(_parse_pst_status_filter("processing"), ["processing"])

    def test_csv_statuses(self):
        self.assertEqual(
            _parse_pst_status_filter(" queued ,processing "),
            ["queued", "processing"],
        )

    def test_case_insensitive(self):
        self.assertEqual(
            _parse_pst_status_filter("QUEUED,Processing"),
            ["queued", "processing"],
        )

    def test_only_commas_returns_none(self):
        self.assertIsNone(_parse_pst_status_filter(", , ,"))


if __name__ == "__main__":
    unittest.main()
