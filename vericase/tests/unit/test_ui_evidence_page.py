import os
import re
import unittest


class TestUiEvidencePage(unittest.TestCase):
    def test_evidence_page_uses_secure_api_fetch(self):
        vericase_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        evidence_path = os.path.join(vericase_root, "ui", "evidence.html")
        with open(evidence_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('<script src="security.js"></script>', html)
        self.assertRegex(html, r"\bsecureApiFetch\(")
        self.assertIsNone(re.search(r"\bfetch\(", html))


if __name__ == "__main__":
    unittest.main()

