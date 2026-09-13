"""Product / AI relevance scoring (max 10 points).

Each category in `PRODUCT_EVIDENCE_CATEGORIES` is a distinct kind of
evidence (customer-facing work, AI agents, startup environment, ...).
Matching more than one phrase within the same category still only counts
that category once — the score reflects breadth of relevant evidence, not
how many synonyms happened to appear.
"""

from dataclasses import dataclass

from app.matching.aliases import PRODUCT_EVIDENCE_CATEGORIES
from app.matching.text import any_phrase_matches, normalize_text

MAX_PRODUCT_SCORE = 10
_POINTS_PER_CATEGORY = 2


@dataclass(frozen=True, slots=True)
class ProductScore:
    points: int
    evidence: list[str]


def score_product_relevance(text: str) -> ProductScore:
    """Score product/AI relevance evidence found in `text`."""
    normalized = normalize_text(text)

    matched_categories = [
        label
        for label, phrases in PRODUCT_EVIDENCE_CATEGORIES.items()
        if any_phrase_matches(normalized, phrases)
    ]

    points = min(MAX_PRODUCT_SCORE, len(matched_categories) * _POINTS_PER_CATEGORY)
    return ProductScore(points=points, evidence=matched_categories)
