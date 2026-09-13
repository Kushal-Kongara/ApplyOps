"""Deterministic job filtering and match scoring (Phase 2).

No network calls, no LLM, no embeddings — every point in a `MatchResult` is
explainable by a keyword rule somewhere in this package. See
`docs/phase-02-matching.md` for the full design rationale.
"""

from app.matching.filters import FilterResult, evaluate_filters
from app.matching.location import LocationClass, classify_location, score_location
from app.matching.scorer import MAX_TOTAL_SCORE, MatchResult, ScoreComponents, evaluate_job
from app.matching.seniority import ExperienceRange, extract_experience_years
from app.matching.skills import SkillResult, score_skills
from app.matching.titles import TitleScore, score_title
from app.matching.visa import VisaSignal, detect_visa_signal

__all__ = [
    "MAX_TOTAL_SCORE",
    "MatchResult",
    "ScoreComponents",
    "evaluate_job",
    "FilterResult",
    "evaluate_filters",
    "LocationClass",
    "classify_location",
    "score_location",
    "ExperienceRange",
    "extract_experience_years",
    "SkillResult",
    "score_skills",
    "TitleScore",
    "score_title",
    "VisaSignal",
    "detect_visa_signal",
]
