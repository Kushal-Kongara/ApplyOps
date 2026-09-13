"""Composes every scoring component into one explainable `MatchResult`.

Filtering and scoring both always run, independently: a job can be
hard-filtered (e.g. an excluded title) and still have its score computed and
stored, so the filter reason and the score are both visible later. Nothing
here calls the network or an LLM — every point is traceable to a keyword
rule in `app/matching/`.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.matching.filters import FilterResult, evaluate_filters
from app.matching.location import MAX_LOCATION_SCORE, score_location
from app.matching.product import MAX_PRODUCT_SCORE, score_product_relevance
from app.matching.seniority import MAX_SENIORITY_SCORE, classify_seniority
from app.matching.skills import MAX_SKILL_SCORE, score_skills
from app.matching.titles import MAX_TITLE_SCORE, score_title
from app.matching.visa import VisaSignal, detect_visa_signal
from app.models import Job, utcnow
from app.profile import Profile

MAX_TOTAL_SCORE = (
    MAX_TITLE_SCORE + MAX_SKILL_SCORE + MAX_LOCATION_SCORE + MAX_SENIORITY_SCORE + MAX_PRODUCT_SCORE
)
assert MAX_TOTAL_SCORE == 100


@dataclass(frozen=True, slots=True)
class ScoreComponents:
    title: int
    skills: int
    location: int
    seniority: int
    product: int

    @property
    def total(self) -> int:
        total = self.title + self.skills + self.location + self.seniority + self.product
        return max(0, min(MAX_TOTAL_SCORE, total))


@dataclass(frozen=True, slots=True)
class MatchResult:
    job_unique_key: str
    profile_id: str
    components: ScoreComponents
    matched_skills: list[str] = field(default_factory=list)
    unmatched_skills: list[str] = field(default_factory=list)
    skill_evidence: list[str] = field(default_factory=list)
    title_evidence: str = ""
    location_evidence: str = ""
    seniority_evidence: str = ""
    product_evidence: list[str] = field(default_factory=list)
    visa: VisaSignal = field(default_factory=lambda: VisaSignal(status="unknown", evidence=None))
    filter_result: FilterResult = field(default_factory=lambda: FilterResult(filtered=False, reason=None))
    scored_at: datetime = field(default_factory=utcnow)

    @property
    def total_score(self) -> int:
        return self.components.total


def evaluate_job(job: Job, profile: Profile, now: datetime | None = None) -> MatchResult:
    """Score one job against one profile. Never makes a network call."""
    combined_text = f"{job.title}\n{job.description}"

    title_result = score_title(job.title, profile.target_titles)
    skill_result = score_skills(combined_text, profile.primary_skills, profile.secondary_skills)
    location_result = score_location(
        job.location, profile.primary_locations, profile.allow_remote_us, profile.allow_relocation_us
    )
    seniority_result = classify_seniority(job.title, job.description, profile.years_experience)
    product_result = score_product_relevance(combined_text)
    visa = detect_visa_signal(job.title, job.description)
    filter_result = evaluate_filters(job.title, profile)

    components = ScoreComponents(
        title=title_result.points,
        skills=skill_result.points,
        location=location_result.points,
        seniority=seniority_result.points,
        product=product_result.points,
    )

    return MatchResult(
        job_unique_key=job.unique_key,
        profile_id=profile.profile_id,
        components=components,
        matched_skills=skill_result.matched,
        unmatched_skills=skill_result.unmatched,
        skill_evidence=skill_result.evidence,
        title_evidence=title_result.evidence,
        location_evidence=location_result.evidence,
        seniority_evidence=seniority_result.evidence,
        product_evidence=product_result.evidence,
        visa=visa,
        filter_result=filter_result,
        scored_at=now or utcnow(),
    )
