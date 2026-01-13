import unittest

from vericase.api.app.email_content import select_best_body


class TestEmailContent(unittest.TestCase):
    def test_selects_html_when_plain_is_quote_only(self) -> None:
        plain = "On Jan 1, Alice wrote:\n> Old content\n"
        html = "<div>Hello Bob</div><blockquote>Old content</blockquote>"

        selection = select_best_body(
            plain_text=plain,
            html_body=html,
            rtf_body=None,
        )

        self.assertEqual(selection.selected_source, "html")
        self.assertIn("Hello Bob", selection.top_text)
        self.assertNotIn("Old content", selection.top_text)

    def test_signature_not_stripped_for_thanks_line(self) -> None:
        plain = "Thanks for the update\nOn Jan 1, Alice wrote:\n> Old content"

        selection = select_best_body(
            plain_text=plain,
            html_body=None,
            rtf_body=None,
        )

        self.assertIn("Thanks for the update", selection.top_text)
        self.assertEqual(selection.signature_text, "")

    def test_empty_bodies_select_none(self) -> None:
        selection = select_best_body(
            plain_text=None,
            html_body=None,
            rtf_body=None,
        )

        self.assertEqual(selection.selected_source, "none")

    def test_rtf_font_table_does_not_pollute_body(self) -> None:
        # RTF-only messages are common in PST exports; the fallback converter must not
        # leak font table content like "Times New Roman; Symbol;" into the email body.
        rtf = (
            "{\\rtf1\\ansi\\deff0"
            "{\\fonttbl{\\f0\\fnil Times New Roman;}{\\f1\\fswiss Symbol;}}"
            "\\viewkind4\\uc1\\pard\\f0\\fs20 Hello Bob\\par"
            "}"
        )

        selection = select_best_body(
            plain_text=None,
            html_body=None,
            rtf_body=rtf,
        )

        self.assertEqual(selection.selected_source, "rtf")
        self.assertIn("Hello Bob", selection.top_text)
        self.assertNotIn("Times New Roman", selection.top_text)
        self.assertNotIn("Symbol", selection.top_text)


if __name__ == "__main__":
    unittest.main()
