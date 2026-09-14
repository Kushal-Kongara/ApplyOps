"""Deterministic years-of-experience calculation from dated master-resume
experience entries.

Never infers duration from a skill merely being listed in the skills
section — only from bullets that explicitly demonstrate a technology
within a dated experience entry ("skill listed in skills section" is never
enough, per the phase spec). If any relevant entry's dates can't be
reliably parsed, this reports unsupported rather than guessing.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.matching.text import normalize_text
from app.resume.evidence import build_evidence_vocabulary, recognized_facts
from app.resume.models import MasterResume

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_YEAR_RE = re.compile(r"^\s*([A-Za-z]{3,9})\.?\s+(\d{4})\s*$")
_PRESENT_WORDS = ("present", "current", "now")


@dataclass(frozen=True, slots=True)
class YearsExperienceResult:
    supported: bool
    years: float | None
    reason: str
    evidence_ids: list[str] = field(default_factory=list)


def _parse_month_year(text: str, today: date) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.lower() in _PRESENT_WORDS:
        return today
    match = _MONTH_YEAR_RE.match(text)
    if not match:
        return None
    month_name, year = match.groups()
    month = _MONTHS.get(month_name.strip().lower()[:3])
    if month is None:
        return None
    return date(int(year), month, 1)


def calculate_years_of_experience(
    master: MasterResume, skill_name: str, today: date | None = None
) -> YearsExperienceResult:
    """Sum the durations of every master-resume experience entry where at
    least one bullet explicitly demonstrates `skill_name`.

    Returns `supported=False` (never a guessed number) if no entry
    demonstrates the skill in its bullets at all, or if any matching
    entry's dates can't be reliably parsed. Overlapping date ranges (e.g.
    a concurrent internship) are summed independently rather than merged —
    a known, documented simplification that can only overstate, never
    understate, a duration; still safer than guessing.
    """
    today = today or date.today()
    vocabulary = build_evidence_vocabulary(master)
    skill_normalized = normalize_text(skill_name)

    matching_entries = []
    for entry in master.experience:
        bullets_text = " ".join(bullet.text for bullet in entry.bullets)
        facts = recognized_facts(normalize_text(bullets_text), vocabulary)
        facts_normalized = {normalize_text(fact) for fact in facts}
        if skill_normalized in facts_normalized:
            matching_entries.append(entry)

    if not matching_entries:
        return YearsExperienceResult(
            supported=False, years=None,
            reason=f'No experience bullet explicitly demonstrates "{skill_name}".',
        )

    total_days = 0
    for entry in matching_entries:
        start = _parse_month_year(entry.start_date, today)
        end = _parse_month_year(entry.end_date, today)
        if start is None or end is None or end < start:
            return YearsExperienceResult(
                supported=False, years=None,
                reason=(
                    f'Could not reliably parse the employment dates for "{entry.company}" '
                    f'("{entry.start_date}" - "{entry.end_date}").'
                ),
            )
        total_days += (end - start).days

    years = round(total_days / 365.25, 1)
    return YearsExperienceResult(
        supported=True, years=years, reason="", evidence_ids=[entry.id for entry in matching_entries],
    )
