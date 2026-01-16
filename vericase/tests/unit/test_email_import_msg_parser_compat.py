"""Unit tests for standalone .msg parsing used by correspondence email import."""

import os
import sys
import types
import unittest


# Provide minimal env for Settings validation during import.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

# Ensure `api` package is importable when running from repo root.
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.correspondence.email_import import parse_msg_bytes  # noqa: E402


class TestParseMsgBytesCompat(unittest.TestCase):
    def test_does_not_require_process_method(self):
        """Regression test for extract-msg>=0.55 where Message.process() no longer exists.

        We stub the `extract_msg` module to ensure parse_msg_bytes stays compatible without
        requiring a real .msg fixture.
        """

        class DummyAttachment:
            longFilename = "hello.txt"
            data = b"hello"

        class DummyMessage:
            def __init__(self, path: str):
                self.subject = "Subject"
                self.sender = "Alice <alice@example.com>"
                self.to = "Bob <bob@example.com>"
                self.cc = ""
                self.bcc = ""
                self.date = "Mon, 01 Jan 2024 10:00:00 +0000"
                self.body = "Body text"
                self.htmlBody = None
                self.rtfBody = None
                self.attachments = [DummyAttachment()]

            # Note: no process() method
            def close(self):
                return None

        dummy = types.ModuleType("extract_msg")
        setattr(dummy, "__version__", "0.55.0")
        setattr(dummy, "Message", DummyMessage)

        old = sys.modules.get("extract_msg")
        sys.modules["extract_msg"] = dummy
        try:
            parsed = parse_msg_bytes(b"not really a msg")
        finally:
            if old is None:
                sys.modules.pop("extract_msg", None)
            else:
                sys.modules["extract_msg"] = old

        self.assertEqual(parsed.subject, "Subject")
        self.assertEqual(parsed.sender_email, "alice@example.com")
        self.assertEqual(parsed.recipients_to, ["bob@example.com"])
        self.assertEqual(parsed.body_plain, "Body text")
        self.assertTrue(parsed.attachments)
        self.assertEqual(parsed.attachments[0].filename, "hello.txt")
        self.assertEqual(parsed.attachments[0].data, b"hello")

    def test_promotes_htmlish_body_to_html_when_htmlBody_missing(self):
        """Some MSG exports surface HTML markup in .body while htmlBody is empty/None."""

        class DummyMessage:
            def __init__(self, path: str):
                self.subject = "Subject"
                self.sender = "Alice <alice@example.com>"
                self.to = "Bob <bob@example.com>"
                self.cc = ""
                self.bcc = ""
                self.date = "Mon, 01 Jan 2024 10:00:00 +0000"
                self.body = "<table><tr><td>Hello</td></tr></table>"
                self.htmlBody = None
                self.rtfBody = None
                self.attachments = []

            def close(self):
                return None

        dummy = types.ModuleType("extract_msg")
        setattr(dummy, "__version__", "0.55.0")
        setattr(dummy, "Message", DummyMessage)

        old = sys.modules.get("extract_msg")
        sys.modules["extract_msg"] = dummy
        try:
            parsed = parse_msg_bytes(b"not really a msg")
        finally:
            if old is None:
                sys.modules.pop("extract_msg", None)
            else:
                sys.modules["extract_msg"] = old

        self.assertTrue((parsed.body_html or "").lstrip().startswith("<table"))
        self.assertIn("Hello", parsed.body_plain or "")


if __name__ == "__main__":
    unittest.main()
