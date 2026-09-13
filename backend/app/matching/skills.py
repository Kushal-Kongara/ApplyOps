"""Skill alignment scoring (max 30 points).

Searches normalized title + description text for each profile skill. A
skill counts once no matter how many of its aliases appear (searching for
"React" and "React.js" and "ReactJS" separately would double-count a
single mention), and a skill mentioned five times still only counts once.

Primary vs. secondary, and why the score isn't "matched / total":

Dividing matches by the *entire* profile skill list punishes a job for not
mentioning a niche tool (Vapi, ElevenLabs) exactly as much as for missing a
core one (React, Python) — a posting naming every skill that actually
matters still scored ~6/30 if the profile also listed twenty other tools it
never mentions. Instead, primary and secondary skills are scored against
their *own* list sizes and combined with fixed weights, so a role hitting
every primary skill scores strongly regardless of how long the secondary
list is:

    points = round(PRIMARY_CAP * (primary matched / primary total)
                  + SECONDARY_CAP * (secondary matched / secondary total))

with PRIMARY_CAP=24 and SECONDARY_CAP=6 (80/20 split of the 30-point
component). A posting matching every primary skill and nothing else still
scores 24/30 — "strong skill credit" — instead of being dragged down by a
long secondary list it was never going to fully mention.

JavaScript and TypeScript (or React and Node.js) can both appear in the
same skill list even though they overlap conceptually — that's intentional,
not a double-count: each is checked independently and each is a real,
separately meaningful skill a posting can mention or not. Double-counting
only means *one* skill's own aliases being tallied more than once, which
this never does.
"""

from dataclasses import dataclass

from app.matching.aliases import SKILL_ALIASES
from app.matching.text import any_phrase_matches, normalize_text

MAX_SKILL_SCORE = 30
PRIMARY_CAP = 24
SECONDARY_CAP = 6
assert PRIMARY_CAP + SECONDARY_CAP == MAX_SKILL_SCORE


@dataclass(frozen=True, slots=True)
class SkillResult:
    points: int
    matched_primary: list[str]
    matched_secondary: list[str]
    unmatched_primary: list[str]
    unmatched_secondary: list[str]
    evidence: list[str]

    @property
    def matched(self) -> list[str]:
        """All matched skills, primary first — the flat view stored on a match."""
        return self.matched_primary + self.matched_secondary

    @property
    def unmatched(self) -> list[str]:
        """Profile skills not found in this posting — not "required and missing"."""
        return self.unmatched_primary + self.unmatched_secondary


def _aliases_for(skill: str) -> list[str]:
    """Every normalized phrase that counts as evidence for `skill`.

    Skills with a curated alias list (see aliases.py) use it; anything else
    falls back to its own normalized name so an arbitrary profile skill
    still works without a code change.
    """
    return SKILL_ALIASES.get(skill, [normalize_text(skill)])


def _match_skills(normalized_text: str, skills: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split `skills` into matched/unmatched against `normalized_text`, with evidence."""
    matched: list[str] = []
    unmatched: list[str] = []
    evidence: list[str] = []

    for skill in skills:
        aliases = _aliases_for(skill)
        hit = next((alias for alias in aliases if any_phrase_matches(normalized_text, [alias])), None)
        if hit is not None:
            matched.append(skill)
            evidence.append(f"{skill} (matched '{hit}')")
        else:
            unmatched.append(skill)

    return matched, unmatched, evidence


def score_skills(text: str, primary_skills: list[str], secondary_skills: list[str]) -> SkillResult:
    """Score how many of the profile's primary/secondary skills show up in `text`."""
    normalized_text = normalize_text(text)

    matched_primary, unmatched_primary, primary_evidence = _match_skills(normalized_text, primary_skills)
    matched_secondary, unmatched_secondary, secondary_evidence = _match_skills(normalized_text, secondary_skills)

    primary_fraction = len(matched_primary) / len(primary_skills) if primary_skills else 0.0
    secondary_fraction = len(matched_secondary) / len(secondary_skills) if secondary_skills else 0.0

    points = round(PRIMARY_CAP * primary_fraction + SECONDARY_CAP * secondary_fraction)
    points = max(0, min(MAX_SKILL_SCORE, points))

    return SkillResult(
        points=points,
        matched_primary=matched_primary,
        matched_secondary=matched_secondary,
        unmatched_primary=unmatched_primary,
        unmatched_secondary=unmatched_secondary,
        evidence=primary_evidence + secondary_evidence,
    )
