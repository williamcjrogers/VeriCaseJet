"""Unit tests for email-import dedupe helpers."""

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


from api.app.correspondence.email_import import (  # noqa: E402
    ParsedAttachment,
    _prepare_attachment_entries,
)


class TestEmailImportDedupeHelpers(unittest.TestCase):
    def test_prepare_attachment_entries_filters_inline_and_signature(self):
        attachments = [
            ParsedAttachment(
                filename="logo.png",
                content_type="image/png",
                data=b"small",
                is_inline=False,
                content_id="logo-1",
            ),
            ParsedAttachment(
                filename="inline.png",
                content_type="image/png",
                data=b"inline",
                is_inline=True,
                content_id=None,
            ),
            ParsedAttachment(
                filename="report.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.4",
                is_inline=False,
                content_id=None,
            ),
        ]

        entries = _prepare_attachment_entries(attachments)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].safe_filename, "report.pdf")
        self.assertEqual(entries[0].content_type, "application/pdf")
        self.assertEqual(len(entries[0].file_hash), 64)


if __name__ == "__main__":
    unittest.main()
