"""The vocabulary of recognized facts used to validate an LLM rewrite.

The job-matching alias table (`app.matching.aliases.SKILL_ALIASES`, reached
here through `keyword_universe()`) is useful for synonym normalization
("React.js" -> React) but it is scoped to what job *matching* cares about —
it is not, and was never meant to be, the full set of truthful facts a
candidate's resume can state. That source of truth is `resume_master.json`
itself. This module merges the two: every matching alias survives (for the
synonym coverage it gives), plus every skill the master resume's own
`skills` block lists that the alias table doesn't already cover, recognized
literally under its own name.

This means a skill added to `resume_master.json` is recognized by the
resume-rewrite validator immediately — no corresponding update to the
job-matching alias table is required. Job matching's own keyword universe
(`app/resume/tailor.py`) is unaffected; this is purely about what the
rewrite *validator* is allowed to count as evidence.
"""

from app.matching.text import any_phrase_matches, normalize_text
from app.resume.models import MasterResume
from app.resume.tailor import flatten_skills, keyword_universe


def build_evidence_vocabulary(master: MasterResume) -> dict[str, list[str]]:
    """Canonical fact name -> normalized phrases it can be recognized by.

    A skill already covered by `keyword_universe()` keeps its existing
    alias list (so "React.js" still resolves to "React"); a master-resume
    skill with no alias entry is added under its own literal name.
    """
    vocabulary = {name: list(phrases) for name, phrases in keyword_universe().items()}
    covered_normalized_names = {normalize_text(name) for name in vocabulary}

    for skill in flatten_skills(master.skills):
        skill_normalized = normalize_text(skill)
        if not skill_normalized or skill_normalized in covered_normalized_names:
            continue
        vocabulary[skill] = [skill_normalized]
        covered_normalized_names.add(skill_normalized)

    return vocabulary


def recognized_facts(text_normalized: str, vocabulary: dict[str, list[str]]) -> set[str]:
    """Canonical fact names (from `vocabulary`) that `text_normalized`
    demonstrably mentions."""
    return {name for name, phrases in vocabulary.items() if any_phrase_matches(text_normalized, phrases)}
