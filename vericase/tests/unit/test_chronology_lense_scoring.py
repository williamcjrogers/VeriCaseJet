import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace


# Provide minimal env for Settings validation during import.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

# Ensure `api` package is importable when running from repo root.
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.chronology_lense import (  # noqa: E402
    LenseCitation,
    classify_milestone_band,
    compute_event_score,
    score_evidence_item,
)


class TestChronologyLenseScoring(unittest.TestCase):
    def test_evidence_item_hard_score(self):
        item = SimpleNamespace(
            document_date=datetime(2024, 1, 2),
            document_date_confidence=90,
            extracted_text="On 2024-01-02 the contractor issued a notice.",
            evidence_type="notice",
            document_category="letter",
            source_email_id="email-1",
        )
        score = score_evidence_item(item)
        self.assertGreaterEqual(score, 0.75)
        self.assertEqual(classify_milestone_band(score), "MilestoneHard")

    def test_compute_event_score_multi_source(self):
        citations = [
            LenseCitation(source_type="email", source_id="1", excerpt="a", confidence=0.6),
            LenseCitation(source_type="evidence", source_id="2", excerpt="b", confidence=0.7),
        ]
        score = compute_event_score(
            citations, {"email:1": 0.6, "evidence:2": 0.7}
        )
        self.assertGreaterEqual(score, 0.7)


if __name__ == "__main__":
    unittest.main()
