import unittest

from vericase.api.app.email_threading import _bounded_text


class TestEmailThreadingBoundedText(unittest.TestCase):
    def test_returns_none_for_none(self) -> None:
        self.assertIsNone(_bounded_text(None, max_len=64))

    def test_returns_value_when_under_limit(self) -> None:
        self.assertEqual(_bounded_text("abc", max_len=3), "abc")

    def test_compacts_value_when_over_limit(self) -> None:
        value = "x" * 200
        bounded = _bounded_text(value, max_len=64)
        self.assertIsNotNone(bounded)
        self.assertLessEqual(len(bounded or ""), 64)
        self.assertIn("~", bounded or "")
        # deterministic
        self.assertEqual(bounded, _bounded_text(value, max_len=64))


if __name__ == "__main__":
    unittest.main()
