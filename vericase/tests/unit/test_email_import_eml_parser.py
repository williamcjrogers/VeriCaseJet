"""Unit tests for standalone .eml parsing used by correspondence email import."""

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


from api.app.correspondence.email_import import parse_eml_bytes  # noqa: E402


class TestParseEmlBytes(unittest.TestCase):
    def test_parses_basic_headers_body_and_attachment(self):
        raw = (
            "From: Alice <alice@example.com>\r\n"
            "To: Bob <bob@example.com>\r\n"
            "Cc: Carol <carol@example.com>\r\n"
            "Subject: Test email\r\n"
            "Date: Tue, 01 Jan 2024 12:34:56 +0000\r\n"
            "Message-ID: <abc123@example.com>\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: multipart/mixed; boundary=BOUND\r\n"
            "\r\n"
            "--BOUND\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Hello world\r\n"
            "\r\n"
            "--BOUND\r\n"
            "Content-Type: application/pdf\r\n"
            'Content-Disposition: attachment; filename="file.pdf"\r\n'
            "Content-Transfer-Encoding: base64\r\n"
            "\r\n"
            "JVBERi0xLjQK\r\n"
            "--BOUND--\r\n"
        ).encode("utf-8")

        parsed = parse_eml_bytes(raw)

        self.assertEqual(parsed.subject, "Test email")
        self.assertEqual(parsed.sender_email, "alice@example.com")
        self.assertEqual(parsed.sender_name, "Alice")
        self.assertEqual(parsed.recipients_to, ["bob@example.com"])
        self.assertEqual(parsed.recipients_cc, ["carol@example.com"])
        self.assertIsNone(parsed.recipients_bcc)
        self.assertEqual(parsed.message_id, "<abc123@example.com>")
        self.assertIsNotNone(parsed.date_sent)
        self.assertTrue((parsed.body_plain or "").strip().startswith("Hello world"))

        self.assertEqual(len(parsed.attachments), 1)
        att = parsed.attachments[0]
        self.assertEqual(att.filename, "file.pdf")
        self.assertEqual(att.content_type, "application/pdf")
        self.assertGreater(len(att.data), 0)


if __name__ == "__main__":
    unittest.main()
