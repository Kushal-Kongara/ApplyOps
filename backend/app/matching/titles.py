"""Title alignment scoring (max 35 points).

A flat "35 if any wanted family phrase appears, else 20, else 10" scheme
made twenty unrelated titles all score identically — it couldn't tell
"Full Stack Engineer" from "Software Engineer, Full Stack, API Multicloud
Platform Team". This version scores on a continuous scale within five
documented bands, driven by two things:

1. which kind of match the title is (exact / a specific wanted family /
   only the generic "Software Engineer" family / no family, just a bare
   engineering word), and
2. how many *extra qualifier words* the title has beyond that match —
   words like a team or product name ("Enterprise", "Data Acquisition")
   that don't change what the role fundamentally is.

Qualifiers lower a title within its band but never knock it into the band
below — "harmless qualifiers... must not destroy an otherwise strong title
match" — because each band has its own floor the formula can't cross.

    Band                                   Points   Trigger
    --------------------------------------  -------  -----------------------------------
    Exact configured target title           35       normalized title == a target title
    Strong alias / closely related          23-34    a specific wanted family matches
    Generic "Software Engineer"             15-22    only the generic family matches
    Weak but plausible adjacent title       8-14     a bare engineering word, no family
    Unrelated                               0        none of the above (normally filtered
                                                       out before scoring ever sees it)
"""

from dataclasses import dataclass

from app.matching.aliases import GENERIC_ENGINEERING_MARKERS, ROLE_FAMILIES
from app.matching.text import contains_phrase, normalize_text

MAX_TITLE_SCORE = 35

EXACT_MATCH_SCORE = 35
STRONG_BAND = (23, 34)
GENERIC_BAND = (15, 22)
WEAK_BAND = (8, 14)
NO_MATCH_SCORE = 0

_GENERIC_FAMILY = "software_engineer"

# Words that describe the *role*, not what distinguishes this posting from
# another one in the same family — they never count as a "qualifier".
_CONNECTOR_WORDS = frozenset(GENERIC_ENGINEERING_MARKERS) | frozenset(
    {"a", "an", "the", "of", "for", "and", "at", "in", "on", "with", "our", "team"}
)


@dataclass(frozen=True, slots=True)
class TitleScore:
    points: int
    evidence: str


def families_in_text(text_normalized: str) -> dict[str, list[str]]:
    """Which configured role families appear, and which of their phrases matched."""
    found: dict[str, list[str]] = {}
    for family, phrases in ROLE_FAMILIES.items():
        matches = [phrase for phrase in phrases if contains_phrase(text_normalized, phrase)]
        if matches:
            found[family] = matches
    return found


def wanted_families(target_titles: list[str]) -> set[str]:
    """Which role families the profile's target titles map to."""
    wanted: set[str] = set()
    for target_title in target_titles:
        wanted |= families_in_text(normalize_text(target_title)).keys()
    return wanted


def _qualifier_count(title_tokens: list[str], phrase: str) -> int:
    """How many title words are neither part of `phrase` nor a connector word."""
    consumed = set(phrase.split()) | _CONNECTOR_WORDS
    return len([token for token in title_tokens if token not in consumed])


def score_title(job_title: str, target_titles: list[str]) -> TitleScore:
    """Score how well one job title matches the profile's target titles."""
    normalized_title = normalize_text(job_title)
    title_tokens = normalized_title.split()

    for target_title in target_titles:
        if normalize_text(target_title) == normalized_title:
            return TitleScore(EXACT_MATCH_SCORE, f"exact match with configured target title '{target_title}'")

    wanted = wanted_families(target_titles)
    present = families_in_text(normalized_title)

    specific_present = {
        family: phrases for family, phrases in present.items() if family in wanted and family != _GENERIC_FAMILY
    }
    if specific_present:
        # Prefer whichever matched phrase leaves the fewest leftover words —
        # the best-fitting characterization of this title.
        family, phrase, qualifiers = min(
            (
                (family, phrase, _qualifier_count(title_tokens, phrase))
                for family, phrases in specific_present.items()
                for phrase in phrases
            ),
            key=lambda item: item[2],
        )
        ceiling, floor = STRONG_BAND[1], STRONG_BAND[0]
        points = max(floor, min(ceiling, ceiling - qualifiers))
        qualifier_note = "no extra qualifiers" if qualifiers == 0 else f"{qualifiers} extra qualifier word(s)"
        return TitleScore(
            points,
            f"matches wanted role family '{family.replace('_', ' ')}' ({qualifier_note})",
        )

    if _GENERIC_FAMILY in present and _GENERIC_FAMILY in wanted:
        phrase = present[_GENERIC_FAMILY][0]
        qualifiers = _qualifier_count(title_tokens, phrase)
        ceiling, floor = GENERIC_BAND[1], GENERIC_BAND[0]
        points = max(floor, min(ceiling, ceiling - qualifiers))
        return TitleScore(
            points,
            f"matches only the generic wanted title 'software engineer' "
            f"({qualifiers} extra qualifier word(s))",
        )

    matching_marker = next(
        (marker for marker in GENERIC_ENGINEERING_MARKERS if contains_phrase(normalized_title, marker)), None
    )
    if matching_marker is not None:
        qualifiers = _qualifier_count(title_tokens, matching_marker)
        ceiling, floor = WEAK_BAND[1], WEAK_BAND[0]
        points = max(floor, min(ceiling, ceiling - qualifiers))
        return TitleScore(
            points, "title is a plausible adjacent engineering role, not a specifically targeted one"
        )

    return TitleScore(NO_MATCH_SCORE, "title does not match any targeted role")
