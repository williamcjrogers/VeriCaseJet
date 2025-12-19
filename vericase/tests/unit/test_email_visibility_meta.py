"""Unit tests for the pure-Python email visibility rules.

These rules must match the Correspondence Enterprise defaults:
- excluded/hidden emails (spam/other_project/not_relevant/etc) must not be used
  as AI evidence unless explicitly restored by a human.
"""

import os
import sys
import unittest


# Provide minimal env for Settings validation during import in other modules.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

# Ensure `api` package is importable when running from repo root.
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.visibility import is_email_visible_meta


class TestEmailVisibilityMeta(unittest.TestCase):
    def test_none_meta_is_visible(self):
        self.assertTrue(is_email_visible_meta(None))

    def test_empty_meta_is_visible(self):
        self.assertTrue(is_email_visible_meta({}))

    def test_status_spam_is_hidden(self):
        self.assertFalse(is_email_visible_meta({"status": "spam"}))

    def test_status_other_project_is_hidden(self):
        self.assertFalse(is_email_visible_meta({"status": "other_project"}))

    def test_status_not_relevant_is_hidden(self):
        self.assertFalse(is_email_visible_meta({"status": "not_relevant"}))

    def test_is_hidden_true_is_hidden(self):
        self.assertFalse(is_email_visible_meta({"is_hidden": True}))
        self.assertFalse(is_email_visible_meta({"is_hidden": "true"}))

    def test_excluded_true_is_hidden(self):
        # Even if status isn't present, the backward-compatible flag should hide.
        self.assertFalse(is_email_visible_meta({"excluded": True}))
        self.assertFalse(is_email_visible_meta({"excluded": "true"}))

    def test_user_override_visible_wins(self):
        self.assertTrue(
            is_email_visible_meta(
                {
                    "status": "spam",
                    "is_hidden": True,
                    "spam": {"user_override": "visible"},
                }
            )
        )

    def test_user_override_hidden_loses(self):
        self.assertFalse(
            is_email_visible_meta(
                {
                    "status": None,
                    "is_hidden": False,
                    "spam": {"user_override": "hidden"},
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
