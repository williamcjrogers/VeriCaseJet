"""Unit tests for PDF email parser used by correspondence email import."""

import os
import sys
import unittest
import asyncio
from io import BytesIO


os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from api.app.correspondence.pdf_email_parser import parse_pdf_email_bytes  # noqa: E402


def _make_pdf(text_lines: list[str]) -> bytes:
    try:
        from reportlab.pdfgen import canvas  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"reportlab not available: {exc}") from exc

    buf = BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text_lines:
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


class TestPdfEmailParser(unittest.TestCase):
    def test_parses_basic_email_headers(self):
        raw = _make_pdf(
            [
                "From: Alice <alice@example.com>",
                "To: Bob <bob@example.com>",
                "Subject: Test PDF Email",
                "Date: Tue, 01 Jan 2024 12:34:56 +0000",
                "",
                "Hello from PDF.",
            ]
        )

        result = asyncio.run(
            parse_pdf_email_bytes(
                raw,
                filename="email.pdf",
                source_file_sha256="cafebabe",
                use_tika=False,
                use_textract=False,
            )
        )

        self.assertGreaterEqual(len(result.messages), 1)
        msg = result.messages[0]
        self.assertEqual(msg.sender_email, "alice@example.com")
        self.assertEqual(msg.subject, "Test PDF Email")
        self.assertIn("Hello from PDF", msg.body_plain or "")

    def test_rejects_non_email_pdf(self):
        raw = _make_pdf(["Just a normal PDF document", "Nothing to see here"])
        with self.assertRaises(Exception):
            asyncio.run(
                parse_pdf_email_bytes(
                    raw,
                    filename="doc.pdf",
                    source_file_sha256="cafebabe",
                    use_tika=False,
                    use_textract=False,
                )
            )


if __name__ == "__main__":
    unittest.main()
