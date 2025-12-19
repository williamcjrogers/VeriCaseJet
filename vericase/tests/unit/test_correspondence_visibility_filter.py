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

from api.app.correspondence import build_correspondence_visibility_filter  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
