"""Turn ATS HTML descriptions into readable plain text.

Job boards return descriptions as HTML (sometimes HTML-escaped HTML). We keep
the readable words, drop the markup, and preserve paragraph and list breaks so
the stored description is still skimmable by a human.
"""

import html
import re
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address", "article", "blockquote", "br", "div", "dd", "dl", "dt", "h1",
    "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "section",
    "table", "tr", "ul",
}
_SKIPPED_TAGS = {"script", "style"}
_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")
        if tag == "li":
            self._chunks.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def html_to_text(raw: str | None) -> str:
    """Convert an HTML (or HTML-escaped) description into plain text."""
    if not raw:
        return ""

    # Greenhouse returns the description as an escaped HTML string, so unescape
    # first and let the parser see real tags.
    unescaped = html.unescape(raw)

    parser = _TextExtractor()
    parser.feed(unescaped)
    parser.close()

    text = parser.text().replace("\xa0", " ")
    text = _TRAILING_SPACE.sub("\n", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = _BLANK_LINES.sub("\n\n", text)

    return text.strip()
