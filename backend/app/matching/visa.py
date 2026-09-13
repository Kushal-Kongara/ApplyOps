"""Visa / work-eligibility signal detection.

This never touches the match score (see docs/phase-02-matching.md for why).
It only reports what the posting explicitly says, with the actual matched
text stored as evidence — never an inferred conclusion. A generic
"authorized to work" sentence is deliberately not treated as evidence of
anything: plenty of postings say that regardless of their sponsorship
policy.
"""

import re
from dataclasses import dataclass

from app.matching.text import collapse_whitespace

UNKNOWN = "unknown"
SPONSORSHIP_AVAILABLE = "sponsorship_available"
SPONSORSHIP_RISK = "sponsorship_risk"
CITIZENSHIP_OR_CLEARANCE_REQUIRED = "citizenship_or_clearance_required"

VISA_STATUSES = (
    UNKNOWN,
    SPONSORSHIP_AVAILABLE,
    SPONSORSHIP_RISK,
    CITIZENSHIP_OR_CLEARANCE_REQUIRED,
)

# Checked in this order: citizenship/clearance is the strongest, most
# unambiguous exclusion signal, so it's reported even if a page also
# happens to mention sponsorship elsewhere.
_CITIZENSHIP_OR_CLEARANCE_PATTERNS = [
    re.compile(r"u\.?s\.?\s*citizen(?:ship)?\s*(?:only|required)", re.IGNORECASE),
    re.compile(r"must be (?:a |an )?(?:u\.?s\.?\s*)?citizen", re.IGNORECASE),
    re.compile(r"(?:active )?security clearance (?:is |will be )?required", re.IGNORECASE),
    re.compile(r"must (?:currently )?(?:hold|have|possess) (?:an? )?(?:active )?security clearance", re.IGNORECASE),
    re.compile(r"ability to obtain (?:a |an )?security clearance", re.IGNORECASE),
]
_SPONSORSHIP_RISK_PATTERNS = [
    re.compile(
        r"(?:we |the company )?(?:do(?:es)?\s*not|don'?t|doesn'?t) (?:provide|offer|sponsor)[\w\s]{0,25}?sponsorship",
        re.IGNORECASE,
    ),
    re.compile(r"no (?:visa |work )?sponsorship (?:is |are )?available", re.IGNORECASE),
    re.compile(r"(?:will not|won'?t|cannot|can'?t|unable to|not able to) sponsor", re.IGNORECASE),
    re.compile(r"must not require sponsorship", re.IGNORECASE),
    re.compile(r"sponsorship (?:is |are )?not (?:available|provided|offered)", re.IGNORECASE),
    re.compile(r"without (?:the need for |requiring )?(?:visa |work )?sponsorship", re.IGNORECASE),
]
_SPONSORSHIP_AVAILABLE_PATTERNS = [
    re.compile(r"(?:visa |work )?sponsorship (?:is |are )?available", re.IGNORECASE),
    re.compile(r"(?:we|company) (?:will|can|do|does) (?:provide|offer) sponsorship", re.IGNORECASE),
    re.compile(r"visa sponsorship (?:is |are )?(?:provided|offered)", re.IGNORECASE),
    re.compile(r"open to sponsor(?:ing)?", re.IGNORECASE),
    re.compile(r"(?:we |able to |happy to )sponsor(?:s|ship)?\b", re.IGNORECASE),
]

_CATEGORY_PATTERNS = (
    (CITIZENSHIP_OR_CLEARANCE_REQUIRED, _CITIZENSHIP_OR_CLEARANCE_PATTERNS),
    (SPONSORSHIP_RISK, _SPONSORSHIP_RISK_PATTERNS),
    (SPONSORSHIP_AVAILABLE, _SPONSORSHIP_AVAILABLE_PATTERNS),
)


@dataclass(frozen=True, slots=True)
class VisaSignal:
    status: str
    evidence: str | None


def detect_visa_signal(title: str, description: str) -> VisaSignal:
    """Detect an explicit visa/eligibility statement, if the posting has one.

    Deliberately conservative: only the specific phrasings above set a
    status other than `unknown`. Generic "authorized to work in the US"
    language matches none of them and stays `unknown`, per spec.
    """
    text = collapse_whitespace(f"{title}\n{description}")

    for status, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return VisaSignal(status=status, evidence=match.group(0).strip())

    return VisaSignal(status=UNKNOWN, evidence=None)
