import os
import sys
import unittest
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone


# Provide minimal env for Settings validation during import.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

# Ensure `api` package is importable when running from repo root.
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.ai_chat import (  # noqa: E402
    AIEvidenceOrchestrator,
    _AI_CONTEXT_MAX_EMAILS_QUICK,
    _AI_CONTEXT_MAX_EMAILS_DEEP,
)


class TestAIChatEvidenceContext(unittest.TestCase):
    def _fake_email(self, i: int, *, start: datetime) -> SimpleNamespace:
        return SimpleNamespace(
            id=f"email-{i}",
            date_sent=start - timedelta(minutes=i),
            sender_name="Sender",
            sender_email="sender@example.com",
            recipients_to=["to@example.com"],
            subject=f"Subject {i}",
            body_preview=f"Preview content {i} health centre update",
            body_text=f"Full body content {i} health centre update" * 50,
        )

    def test_context_is_capped_quick(self):
        orch = AIEvidenceOrchestrator(db=None)
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        emails = [
            self._fake_email(i, start=start)
            for i in range(_AI_CONTEXT_MAX_EMAILS_QUICK + 200)
        ]

        # Using SimpleNamespace fixtures; we only care about formatting/capping behavior here.
        ctx = orch._build_evidence_context(emails, detailed=False)  # type: ignore[arg-type]  # noqa: SLF001
        self.assertIn("Evidence truncated for performance", ctx)

        # Count quick-mode email lines.
        email_lines = [
            line
            for line in ctx.splitlines()
            if line.startswith("[") and "|" in line and "NOTE:" not in line
        ]
        self.assertEqual(len(email_lines), _AI_CONTEXT_MAX_EMAILS_QUICK)

    def test_context_is_capped_deep(self):
        orch = AIEvidenceOrchestrator(db=None)
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        emails = [
            self._fake_email(i, start=start)
            for i in range(_AI_CONTEXT_MAX_EMAILS_DEEP + 50)
        ]

        ctx = orch._build_evidence_context(emails, detailed=True)  # type: ignore[arg-type]  # noqa: SLF001
        self.assertIn("Evidence truncated for performance", ctx)

        # Count detailed-mode blocks.
        self.assertEqual(ctx.count("[Email "), _AI_CONTEXT_MAX_EMAILS_DEEP)


if __name__ == "__main__":
    unittest.main()
