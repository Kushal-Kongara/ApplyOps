"""HTML to plain-text conversion tests."""

import unittest

from app.html_text import html_to_text


class HtmlToTextTest(unittest.TestCase):
    def test_empty_and_missing_input(self):
        self.assertEqual(html_to_text(None), "")
        self.assertEqual(html_to_text(""), "")

    def test_paragraphs_become_blank_line_separated(self):
        self.assertEqual(html_to_text("<p>One.</p><p>Two.</p>"), "One.\n\nTwo.")

    def test_list_items_become_dashes(self):
        text = html_to_text("<ul><li>Python</li><li>SQL</li></ul>")

        self.assertIn("- Python", text)
        self.assertIn("- SQL", text)

    def test_escaped_html_is_unescaped_first(self):
        self.assertEqual(html_to_text("&lt;p&gt;Hello &amp; welcome&lt;/p&gt;"), "Hello & welcome")

    def test_scripts_and_styles_are_dropped(self):
        text = html_to_text("<style>p{color:red}</style><p>Body</p><script>alert(1)</script>")

        self.assertEqual(text, "Body")

    def test_non_breaking_spaces_become_plain_spaces(self):
        self.assertEqual(html_to_text("<p>a&nbsp;b</p>"), "a b")


if __name__ == "__main__":
    unittest.main()
