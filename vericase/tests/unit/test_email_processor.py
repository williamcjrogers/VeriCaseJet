import unittest
from src.core.email_processor import EmailProcessor


class TestEmailProcessor(unittest.TestCase):

    def setUp(self):
        self.processor = EmailProcessor()

    def test_process_email(self):
        email_data = {
            "subject": "Test Email",
            "body": "This is a test email.",
            "attachments": [],
        }
        result = self.processor.process_email(email_data)
        self.assertIsNotNone(result)
        self.assertEqual(result["subject"], "Test Email")
        self.assertEqual(result["body"], "This is a test email.")

    def test_process_email_with_attachments(self):
        email_data = {
            "subject": "Email with Attachment",
            "body": "This email has an attachment.",
            "attachments": ["file1.txt"],
        }
        result = self.processor.process_email(email_data)
        self.assertIn("attachments", result)
        self.assertEqual(len(result["attachments"]), 1)

    def test_process_empty_email(self):
        email_data = {}
        result = self.processor.process_email(email_data)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
