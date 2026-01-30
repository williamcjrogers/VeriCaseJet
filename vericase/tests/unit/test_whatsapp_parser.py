"""Unit tests for WhatsApp parser used by correspondence email import."""

import os
import sys
import unittest
import zipfile
from io import BytesIO


os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from api.app.correspondence.whatsapp_parser import (  # noqa: E402
    parse_whatsapp_bytes,
    parse_whatsapp_zip_bytes,
)


class TestWhatsAppParser(unittest.TestCase):
    def test_parses_basic_android_export(self):
        raw = (
            "12/01/2024, 19:45 - Alice: Hello there\n"
            "12/01/2024, 19:46 - Bob: Hi!\n"
            "12/01/2024, 19:47 - Messages to this chat and calls are now secured with end-to-end encryption.\n"
            "12/01/2024, 19:48 - Alice: Multi-line start\n"
            "continued line\n"
        ).encode("utf-8")

        result = parse_whatsapp_bytes(
            raw,
            filename="WhatsApp Chat with Project Alpha.txt",
            source_file_sha256="deadbeef",
        )

        self.assertEqual(len(result.messages), 3)
        self.assertTrue(result.messages[0].subject.startswith("WhatsApp:"))
        self.assertIn("Hello there", result.messages[0].body_plain or "")
        self.assertIn("continued line", result.messages[-1].body_plain or "")

        # Deterministic IDs
        result_again = parse_whatsapp_bytes(
            raw,
            filename="WhatsApp Chat with Project Alpha.txt",
            source_file_sha256="deadbeef",
        )
        self.assertEqual(
            result.messages[0].message_id, result_again.messages[0].message_id
        )

    def test_parses_zip_with_media_attachment(self):
        chat = (
            "12/01/2024, 19:45 - Alice: IMG-0001.jpg (file attached)\n"
            "12/01/2024, 19:46 - Bob: OK\n"
        ).encode("utf-8")

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("WhatsApp Chat with Team.txt", chat)
            zf.writestr("IMG-0001.jpg", b"\xff\xd8\xff\xe0" + b"data")
            zf.writestr("EXTRA.png", b"fake")

        raw_zip = buf.getvalue()

        result = parse_whatsapp_zip_bytes(
            raw_zip,
            filename="chat_export.zip",
            source_file_sha256="beadfeed",
        )

        self.assertEqual(len(result.messages), 2)
        self.assertEqual(len(result.messages[0].attachments), 1)
        self.assertEqual(result.messages[0].attachments[0].filename, "IMG-0001.jpg")
        self.assertIn("extra.png", [m.lower() for m in result.unmatched_media])


if __name__ == "__main__":
    unittest.main()
