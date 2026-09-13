"""Hard filtering: jobs that are never worth scoring for this profile.

Filtering and scoring are deliberately separate questions. Filtering asks
"is this even a candidate role family?" and only rejects on strong,
unambiguous signals — a configured excluded title, or a title with no
engineering signal at all. Everything softer (unknown location, missing
skills, an unusually senior title, unknown visa status) is left to scoring,
which can still rank such jobs low without erasing them.

A filtered job is never deleted or skipped — its `FilterResult` is stored
alongside its score so the reason is visible later.
"""

from dataclasses import dataclass

from app.matching.aliases import GENERIC_ENGINEERING_MARKERS, MANAGEMENT_TITLE_MARKERS
from app.matching.text import any_phrase_matches, contains_phrase, normalize_text
from app.profile import Profile


@dataclass(frozen=True, slots=True)
class FilterResult:
    filtered: bool
    reason: str | None


def evaluate_filters(title: str, profile: Profile) -> FilterResult:
    """Decide whether a job title should be hard-excluded for this profile."""
    normalized_title = normalize_text(title)

    for term in profile.excluded_title_terms:
        if contains_phrase(normalized_title, normalize_text(term)):
            return FilterResult(filtered=True, reason=f"excluded title term matched: '{term}'")

    for marker in MANAGEMENT_TITLE_MARKERS:
        if contains_phrase(normalized_title, marker):
            return FilterResult(filtered=True, reason=f"management/leadership title detected: '{marker}'")

    if not any_phrase_matches(normalized_title, GENERIC_ENGINEERING_MARKERS):
        return FilterResult(
            filtered=True,
            reason="title has no engineering/developer signal — outside target role families",
        )

    return FilterResult(filtered=False, reason=None)
