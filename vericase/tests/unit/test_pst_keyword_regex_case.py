import unittest
import uuid
from types import SimpleNamespace

from vericase.api.app.pst_processor import UltimatePSTProcessor


class TestPstKeywordRegexCase(unittest.TestCase):
    def test_regex_keyword_preserves_pattern_case(self) -> None:
        processor = UltimatePSTProcessor(
            db=None, s3_client=None, opensearch_client=None
        )

        keyword = SimpleNamespace(
            id=uuid.uuid4(),
            keyword_name=r"(?P<GROUP>hello)\s+world",
            variations=None,
            is_regex=True,
        )

        matches = processor._match_keywords("Subject", "Hello world", [keyword])
        self.assertEqual(matches, [keyword])


if __name__ == "__main__":
    unittest.main()
