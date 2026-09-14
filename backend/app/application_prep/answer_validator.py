"""Deterministic acceptance check for an LLM-generated application answer.

Reuses the exact same fabrication checks `app/resume/validator.py` uses for
bullet rewrites (technology/numeric/duration/leadership) — one set of rules
for "did the model invent something," not two that could drift apart. The
one thing this deliberately does *not* reuse is the resume validator's
information-retention gate: an answer is a synthesized response drawing on
evidence, not a rewrite of it, so requiring it to retain some fraction of
the evidence's own facts doesn't apply the same way.
"""

from dataclasses import dataclass, field

from app.matching.text import normalize_text
from app.resume.validator import (
    check_duration_claims,
    check_leadership_claims,
    check_numeric_claims,
    check_scope_claims,
    check_technology_claims,
    normalized_words,
)


@dataclass(frozen=True, slots=True)
class AnswerValidationResult:
    accepted: bool
    reasons: list[str] = field(default_factory=list)


def validate_answer(
    evidence_text: str, answer_text: str, allowed_facts: list[str], vocabulary: dict[str, list[str]],
) -> AnswerValidationResult:
    """Accept a generated answer only if every technology, number,
    duration, and leadership/scope claim it makes is already present in
    `evidence_text` or explicitly listed in `allowed_facts`.

    `vocabulary` should come from `app.resume.evidence.build_evidence_vocabulary`
    so a master-resume-only skill is recognized without a job-matching alias.
    """
    if not answer_text.strip():
        return AnswerValidationResult(accepted=False, reasons=["empty answer"])

    evidence_normalized = normalize_text(evidence_text)
    answer_normalized = normalize_text(answer_text)
    allowed_normalized = {normalize_text(fact) for fact in allowed_facts}
    evidence_words = normalized_words(evidence_text)
    answer_words = normalized_words(answer_text)

    reasons: list[str] = []
    reasons += check_technology_claims(evidence_normalized, answer_normalized, allowed_normalized, vocabulary)
    reasons += check_numeric_claims(evidence_text, answer_text)
    reasons += check_duration_claims(evidence_text, answer_text)
    reasons += check_leadership_claims(evidence_words, answer_words)
    reasons += check_scope_claims(evidence_text, answer_text)

    return AnswerValidationResult(accepted=len(reasons) == 0, reasons=reasons)
