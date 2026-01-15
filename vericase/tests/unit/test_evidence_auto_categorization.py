import os
import sys
import unittest


TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.evidence.categorization import infer_document_category


class TestEvidenceAutoCategorization(unittest.TestCase):
    def test_meeting_minutes_from_filename(self):
        cat = infer_document_category(
            filename="THW_-_MEPH_Commissioning_Meeting_No_1_-_26.01.22.docx",
            title=None,
            evidence_type=None,
        )
        self.assertEqual(cat, "Meeting Minutes")

    def test_progress_report_from_filename(self):
        cat = infer_document_category(
            filename="LJJ_Progress_Report_9.pdf",
            title=None,
            evidence_type=None,
        )
        self.assertEqual(cat, "Progress Reports")

    def test_fallback_to_evidence_type(self):
        cat = infer_document_category(
            filename="random_file.bin",
            title=None,
            evidence_type="drawing",
        )
        self.assertEqual(cat, "Drawings")

    def test_returns_none_when_no_match(self):
        cat = infer_document_category(
            filename="notes.txt",
            title="misc",
            evidence_type=None,
        )
        self.assertIsNone(cat)


if __name__ == "__main__":
    unittest.main()
