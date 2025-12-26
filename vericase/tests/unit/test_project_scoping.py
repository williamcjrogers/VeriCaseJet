import os
import sys
import unittest


TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.project_scoping import ScopeMatcher


class TestScopeMatcher(unittest.TestCase):
    def test_detects_other_project_in_subject(self):
        matcher = ScopeMatcher.from_labels(
            current_labels=["Welbourne"],
            other_labels=["Abbey Road"],
        )
        detected = matcher.detect_other_project("RE: Abbey Road update")
        self.assertEqual(detected, "Abbey Road")

    def test_detects_other_project_in_body(self):
        matcher = ScopeMatcher.from_labels(
            current_labels=["Welbourne"],
            other_labels=["Abbey Road"],
        )
        detected = matcher.detect_other_project(
            "Weekly update",
            body_preview="Schedule for Abbey Road phase 2",
        )
        self.assertEqual(detected, "Abbey Road")

    def test_current_terms_override_by_default(self):
        matcher = ScopeMatcher.from_labels(
            current_labels=["Welbourne"],
            other_labels=["Abbey Road"],
        )
        detected = matcher.detect_other_project("Welbourne / Abbey Road sync")
        self.assertIsNone(detected)

    def test_strict_mode_detects_other_project(self):
        matcher = ScopeMatcher.from_labels(
            current_labels=["Welbourne"],
            other_labels=["Abbey Road"],
        )
        detected = matcher.detect_other_project(
            "Welbourne / Abbey Road sync",
            allow_current_terms=False,
        )
        self.assertEqual(detected, "Abbey Road")


if __name__ == "__main__":
    unittest.main()
