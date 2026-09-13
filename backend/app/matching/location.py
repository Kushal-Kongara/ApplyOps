"""Location alignment scoring (max 15 points).

Deterministic, transparent buckets — never a hard reject, since a posting's
location text is often terse ("Hybrid", "Distributed") or simply missing.
"""

from dataclasses import dataclass
from enum import Enum

from app.matching.aliases import INTERNATIONAL_LOCATION_MARKERS, US_LOCATION_MARKERS
from app.matching.text import any_phrase_matches, contains_phrase, normalize_text

MAX_LOCATION_SCORE = 15

_PRIMARY_POINTS = 15
_REMOTE_US_POINTS = 15
_OTHER_US_POINTS = 8
_UNKNOWN_POINTS = 4
_INTERNATIONAL_POINTS = 0


class LocationClass(Enum):
    PRIMARY = "primary"
    REMOTE_US = "remote_us"
    OTHER_US = "other_us"
    UNKNOWN = "unknown"
    INTERNATIONAL = "international"


@dataclass(frozen=True, slots=True)
class LocationScore:
    points: int
    classification: LocationClass
    evidence: str


def classify_location(location_text: str, primary_locations: list[str]) -> LocationClass:
    """Bucket a free-text location string into one of five classes."""
    normalized = normalize_text(location_text)
    if not normalized:
        return LocationClass.UNKNOWN

    primary_phrases = [normalize_text(p) for p in primary_locations]
    if any_phrase_matches(normalized, primary_phrases):
        return LocationClass.PRIMARY

    is_remote = contains_phrase(normalized, "remote")
    is_international = any_phrase_matches(normalized, INTERNATIONAL_LOCATION_MARKERS)
    is_us = any_phrase_matches(normalized, US_LOCATION_MARKERS)

    if is_remote:
        if is_international:
            return LocationClass.INTERNATIONAL
        if is_us:
            return LocationClass.REMOTE_US
        # Bare "Remote" with no country named either way — genuinely
        # ambiguous, not "clearly" a US remote role.
        return LocationClass.UNKNOWN

    if is_international:
        return LocationClass.INTERNATIONAL

    if is_us:
        return LocationClass.OTHER_US

    return LocationClass.UNKNOWN


def score_location(
    location_text: str,
    primary_locations: list[str],
    allow_remote_us: bool,
    allow_relocation_us: bool,
) -> LocationScore:
    """Score a job's location against the profile's location preferences."""
    classification = classify_location(location_text, primary_locations)

    if classification is LocationClass.PRIMARY:
        return LocationScore(_PRIMARY_POINTS, classification, "matches a primary Bay Area location")

    if classification is LocationClass.REMOTE_US:
        if allow_remote_us:
            return LocationScore(_REMOTE_US_POINTS, classification, "remote role clearly based in the US")
        return LocationScore(_UNKNOWN_POINTS, classification, "remote role in the US, but remote is not preferred")

    if classification is LocationClass.OTHER_US:
        if allow_relocation_us:
            return LocationScore(_OTHER_US_POINTS, classification, "US location outside primary cities; relocation allowed")
        return LocationScore(0, classification, "US location outside primary cities; relocation not allowed")

    if classification is LocationClass.INTERNATIONAL:
        return LocationScore(_INTERNATIONAL_POINTS, classification, "location is clearly outside the United States")

    return LocationScore(_UNKNOWN_POINTS, classification, "location could not be determined from the posting")
