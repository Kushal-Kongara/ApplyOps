"""Text normalization shared by every scoring component.

Everything in Phase 2 is keyword matching, so getting normalization right is
what keeps matches honest: it's what lets "full-stack", "full stack", and
"fullstack" count as the same thing, and what stops "AI" from matching inside
"email" or "Java" from matching inside "JavaScript".
"""

import re
import unicodedata
from functools import lru_cache

# "U.S." / "U.S.A." show up constantly in job postings and location strings.
# Collapsing them before the general normalization step means every other
# rule (location classification, visa phrases, skill aliases) only has to
# reason about "us" / "usa".
_US_ABBREVIATION = re.compile(r"\bu\.s\.a\.?\b|\bu\.s\.?\b", re.IGNORECASE)
# "Node.js", "React.js", "Next.js", ... — fuse the ".js" suffix onto its
# framework name *before* punctuation is turned into spaces. Otherwise
# "Node.js" would normalize to two words, "node js", and the generic
# standalone "js" alias for JavaScript would wrongly fire on every mention
# of a `*.js`-named framework.
_DOT_JS_SUFFIX = re.compile(r"\.js\b", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Lowercase, strip accents/punctuation, and collapse whitespace.

    The result contains only lowercase letters, digits, and single spaces
    between words, e.g. "Front-End (React.js)!" -> "front end react js".
    This is the form every alias/phrase list in this package is written in.
    """
    if not text:
        return ""

    text = _US_ABBREVIATION.sub(
        lambda m: "usa" if m.group(0).lower().rstrip(".") == "u.s.a" else "us", text
    )
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = _DOT_JS_SUFFIX.sub("js", text)
    text = _NON_ALNUM.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def collapse_whitespace(text: str | None) -> str:
    """Collapse whitespace/newlines but keep original casing and punctuation.

    Used where we want to show a human the actual matched wording (visa
    evidence, product-relevance evidence) rather than a normalized form.
    """
    if not text:
        return ""
    return _WHITESPACE.sub(" ", text).strip()


@lru_cache(maxsize=None)
def _phrase_pattern(phrase_normalized: str) -> re.Pattern[str]:
    escaped = re.escape(phrase_normalized)
    return re.compile(rf"\b{escaped}\b")


def contains_phrase(haystack_normalized: str, phrase_normalized: str) -> bool:
    """Word-aware phrase search within already-normalized text.

    Both arguments must already be run through `normalize_text`. Uses `\\b`
    word boundaries so "ai" matches "AI Engineer" but not "email", and "java"
    matches "Java Developer" but not "JavaScript".
    """
    if not phrase_normalized:
        return False
    return _phrase_pattern(phrase_normalized).search(haystack_normalized) is not None


def any_phrase_matches(haystack_normalized: str, phrases: list[str]) -> bool:
    """True if any of `phrases` (already normalized) appears in the text."""
    return any(contains_phrase(haystack_normalized, phrase) for phrase in phrases)
