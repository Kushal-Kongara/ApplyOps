"""Seniority alignment scoring (max 10 points).

The profile is roughly a 4-years-of-experience engineer. Extraction is a
small ordered list of readable regex patterns rather than one fragile
all-in-one expression, plus a written-number preprocessing step so "five
years" reads the same as "5 years".

Bands (an explicit "5 years" posting lands in the 5-6 partial band, not the
2-5 strong one, so the two never overlap in practice):

- strong  (10 pts): roughly 2-4 years, clearly stated
- partial (6 pts):  title says "Senior", or the posting asks for 5-6 years
- low     (2 pts):  staff/principal/architect/manager-level title, or 7+ years
- neutral (6 pts):  no usable experience evidence at all — this is
  deliberately the same as "partial," not "strong": an absent requirement is
  not evidence the role fits, so it must not score as if it were confirmed.
"""

import re
from dataclasses import dataclass
from typing import Callable

from app.matching.text import collapse_whitespace, contains_phrase, normalize_text

MAX_SENIORITY_SCORE = 10

_STRONG_POINTS = 10
_PARTIAL_POINTS = 6
_LOW_POINTS = 2
_NEUTRAL_POINTS = 6

_WORD_TO_NUMBER = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
# "seven years", "five or more years" — converted to digits before any other
# pattern runs, so every pattern below only ever needs to handle numerals.
_WRITTEN_NUMBER_PATTERN = re.compile(
    r"\b(" + "|".join(_WORD_TO_NUMBER) + r")\b(?=\s+(?:or more\s+)?years?\b)", re.IGNORECASE
)

# Ordered most-specific-first: a "3-5 years" range should never be read by
# the open-ended "5+ years" pattern first.
_RANGE_PATTERN = re.compile(r"(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\+?\s*years?", re.IGNORECASE)
_AT_LEAST_PATTERN = re.compile(r"(?:at least|a minimum of|minimum of)\s+(\d{1,2})\+?\s*years?", re.IGNORECASE)
_OR_MORE_PATTERN = re.compile(r"(\d{1,2})\s*or more\s*years?", re.IGNORECASE)
_PLUS_PATTERN = re.compile(r"(\d{1,2})\s*\+\s*years?", re.IGNORECASE)
_SINGLE_PATTERN = re.compile(
    r"(\d{1,2})\s*years?\s*(?:of\s+)?(?:relevant\s+|professional\s+|prior\s+)?experience",
    re.IGNORECASE,
)

# Preferring matches near one of these words is how extraction avoids
# latching onto an unrelated number ("founded in 2015", "5 years in
# business") — see `_has_experience_context`.
_CONTEXT_PATTERN = re.compile(r"experience|professional|industry", re.IGNORECASE)
_CONTEXT_WINDOW = 50

_SENIOR_TITLE_MARKERS = ["senior", "sr"]
_LOW_TITLE_MARKERS = ["staff", "principal", "architect", "manager", "director", "vp"]


@dataclass(frozen=True, slots=True)
class ExperienceRange:
    min_years: int
    max_years: int | None  # None means open-ended ("7+ years")


@dataclass(frozen=True, slots=True)
class SeniorityScore:
    points: int
    evidence: str


def _range_range(match: re.Match[str]) -> ExperienceRange:
    low, high = int(match.group(1)), int(match.group(2))
    return ExperienceRange(min(low, high), max(low, high))


def _open_ended_range(match: re.Match[str]) -> ExperienceRange:
    return ExperienceRange(int(match.group(1)), None)


def _single_range(match: re.Match[str]) -> ExperienceRange:
    years = int(match.group(1))
    return ExperienceRange(years, years)


_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], ExperienceRange]], ...] = (
    (_RANGE_PATTERN, _range_range),
    (_AT_LEAST_PATTERN, _open_ended_range),
    (_OR_MORE_PATTERN, _open_ended_range),
    (_PLUS_PATTERN, _open_ended_range),
    (_SINGLE_PATTERN, _single_range),
)


def _has_experience_context(text: str, start: int, end: int) -> bool:
    left = max(0, start - _CONTEXT_WINDOW)
    right = min(len(text), end + _CONTEXT_WINDOW)
    return _CONTEXT_PATTERN.search(text[left:right]) is not None


def extract_experience_years(text: str) -> ExperienceRange | None:
    """Find the most credible years-of-experience mention in `text`, if any.

    Collects every candidate match across all patterns, then prefers the
    first one (in reading order) that appears near a word like "experience"
    or "professional" — a bare number, without that context, is much more
    likely to be an unrelated year mention than an actual requirement.
    """
    searchable = collapse_whitespace(text)
    searchable = _WRITTEN_NUMBER_PATTERN.sub(lambda m: str(_WORD_TO_NUMBER[m.group(1).lower()]), searchable)

    candidates: list[tuple[int, int, ExperienceRange]] = []
    for pattern, build in _PATTERNS:
        for match in pattern.finditer(searchable):
            candidates.append((match.start(), match.end(), build(match)))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0])

    contextual = [c for c in candidates if _has_experience_context(searchable, c[0], c[1])]
    chosen = contextual[0] if contextual else candidates[0]
    return chosen[2]


def classify_seniority(title: str, description: str, years_experience: int) -> SeniorityScore:
    """Score how well a job's seniority level fits `years_experience`.

    Bands scale with the profile's own experience: for the default profile
    (4 years) that's 2-4 strong, 5-6 partial, 7+ low — matching the spec's
    "roughly 2-5" / "5-6" / "7+" guidance without the 5-year overlap. No
    stated requirement at all scores the same as "partial," not "strong" —
    an absence of evidence is not evidence of a good fit.
    """
    normalized_title = normalize_text(title)
    experience = extract_experience_years(f"{title}\n{description}")

    partial_band = range(years_experience + 1, years_experience + 3)  # e.g. 5-6
    low_threshold = years_experience + 3  # e.g. 7+

    if any(contains_phrase(normalized_title, marker) for marker in _LOW_TITLE_MARKERS):
        return SeniorityScore(_LOW_POINTS, "title signals a senior individual-contributor or management level")

    if experience is not None and experience.min_years >= low_threshold:
        return SeniorityScore(
            _LOW_POINTS, f"posting asks for {_describe(experience)}, well above the profile's experience"
        )

    if any(contains_phrase(normalized_title, marker) for marker in _SENIOR_TITLE_MARKERS):
        return SeniorityScore(_PARTIAL_POINTS, "title includes 'Senior', one level above the profile")

    if experience is not None and experience.min_years in partial_band:
        return SeniorityScore(_PARTIAL_POINTS, f"posting asks for {_describe(experience)}, slightly above the profile")

    if experience is None:
        return SeniorityScore(_NEUTRAL_POINTS, "no usable seniority evidence found; scored neutrally, not as a confirmed fit")

    if experience.min_years < partial_band.start:
        return SeniorityScore(_STRONG_POINTS, f"posting asks for {_describe(experience)}, matching the profile")

    # Falls above the low threshold's own range check but through some other
    # shape (shouldn't normally happen given the checks above) — treat as
    # partial rather than guessing either extreme.
    return SeniorityScore(_PARTIAL_POINTS, f"posting asks for {_describe(experience)}")


def _describe(experience: ExperienceRange) -> str:
    if experience.max_years is None:
        return f"{experience.min_years}+ years"
    if experience.min_years == experience.max_years:
        return f"{experience.min_years} years"
    return f"{experience.min_years}-{experience.max_years} years"
