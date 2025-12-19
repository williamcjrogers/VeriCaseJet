"""Unit tests for correspondence visibility filtering.

The Correspondence Enterprise UI relies on server-side filtering to exclude spam/other
project / hidden emails. Production uses Postgres JSON (not JSONB) for
`email_messages.metadata`, so the filter must be compatible with JSON operators.
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


from sqlalchemy.dialects import postgresql  # noqa: E402

from api.app.correspondence import (  # noqa: E402
    build_correspondence_visibility_filter,
    compute_correspondence_exclusion,
)


class TestCorrespondenceVisibilityFilter(unittest.TestCase):
    def test_filter_compiles_with_postgres_json_operators(self):
        expr = build_correspondence_visibility_filter()
        compiled = str(
            expr.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        # We should be using -> / ->> operators (JSON-compatible), not JSONB-only concatenation.
        self.assertIn("->>", compiled)
        self.assertIn("->", compiled)
        self.assertNotIn("::jsonb", compiled.lower())
        self.assertNotIn("||", compiled)  # jsonb concatenation operator

    def test_compute_correspondence_exclusion_default_visible(self):
        info = compute_correspondence_exclusion({}, "Hello")
        self.assertFalse(info["excluded"])
        self.assertEqual(info["excluded_reasons"], [])

    def test_compute_correspondence_exclusion_spam_override_hidden(self):
        info = compute_correspondence_exclusion(
            {"spam": {"user_override": "hidden"}}, "Hi"
        )
        self.assertTrue(info["excluded"])
        self.assertEqual(info["excluded_label"], "Spam")
        self.assertEqual(info["excluded_reason"], "spam_override:hidden")

    def test_compute_correspondence_exclusion_override_visible_wins(self):
        info = compute_correspondence_exclusion(
            {"spam": {"user_override": "visible"}, "status": "spam:newsletter"},
            "Hi",
        )
        self.assertFalse(info["excluded"])

    def test_compute_correspondence_exclusion_status_other_project(self):
        info = compute_correspondence_exclusion({"status": "other_project:ABC"}, "Hi")
        self.assertTrue(info["excluded"])
        self.assertEqual(info["excluded_label"], "Other Project")
        self.assertEqual(info["excluded_reason"], "status:other_project:ABC")

    def test_compute_correspondence_exclusion_is_hidden(self):
        info = compute_correspondence_exclusion({"is_hidden": "true"}, "Hi")
        self.assertTrue(info["excluded"])
        self.assertEqual(info["excluded_label"], "Hidden")
        self.assertEqual(info["excluded_reason"], "is_hidden:true")

    def test_compute_correspondence_exclusion_system_item_ipm(self):
        info = compute_correspondence_exclusion({}, "IPM.Note")
        self.assertTrue(info["excluded"])
        self.assertEqual(info["excluded_label"], "System Item")
        self.assertEqual(info["excluded_reason"], "system_item:ipm")

    def test_compute_correspondence_exclusion_ai_flags_normalized(self):
        info = compute_correspondence_exclusion(
            {"ai_excluded": "true", "ai_exclude_reason": "spam:newsletter"},
            "Hello",
        )
        self.assertTrue(info["ai_excluded"])
        self.assertEqual(info["ai_exclude_reason"], "spam:newsletter")


if __name__ == "__main__":
    unittest.main()
