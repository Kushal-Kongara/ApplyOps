"""Deterministic acceptance check for an LLM-rewritten bullet.

The model's own `claims_used` array is never trusted — every check here
scans the actual rewritten text. This is the one gate standing between "the
model said something" and "the resume states something": when a check is
ambiguous, it rejects. Truth outranks better wording every time (see the
phase spec) — this file is deliberately biased toward over-rejecting rather
than under-rejecting.
"""

import re
from dataclasses import dataclass, field

from app.matching.text import any_phrase_matches, normalize_text
from app.resume.evidence import recognized_facts
from app.resume.tailor import keyword_universe

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

_WORD_NUMBERS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "forty", "fifty",
)
_DURATION_RE = re.compile(
    r"\b(?:\d+\+?|" + "|".join(_WORD_NUMBERS) + r")\s*[- ]?(?:years?|yrs?|months?)\b",
    re.IGNORECASE,
)

# Leadership/ownership/scope verbs a bullet can only claim if the original
# evidence already uses that same word — never inferred from context.
_LEADERSHIP_TERMS = (
    "led", "lead", "leads", "leading",
    "managed", "manages", "managing", "management",
    "architected", "architecting",
    "mentored", "mentors", "mentoring",
    "supervised", "supervising",
    "directed", "directing",
    "spearheaded", "spearheading",
    "owned", "owns", "owning",
    "founded", "founding",
)

# A rewrite may reasonably drop facts the original bullet mentions but the
# job doesn't care about — but if it keeps fewer than half of everything
# the original demonstrated, that's not "concise," that's "lost most of the
# evidence," and a resume shouldn't get vaguer just because an LLM touched
# it. This is deliberately a blunt, deterministic ratio — no LLM judgment
# call about what counts as "too generic."
_RETENTION_RATIO_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class ValidationResult:
    accepted: bool
    reasons: list[str] = field(default_factory=list)


def _normalized_words(text: str) -> set[str]:
    return set(normalize_text(text).split())


def _check_technology_claims(
    original_normalized: str, rewritten_normalized: str, allowed_normalized: set[str], vocabulary: dict[str, list[str]],
) -> list[str]:
    reasons = []
    for name, phrases in vocabulary.items():
        if not any_phrase_matches(rewritten_normalized, phrases):
            continue
        name_normalized = normalize_text(name)
        already_in_original = any_phrase_matches(original_normalized, phrases)
        explicitly_allowed = any_phrase_matches(" ".join(allowed_normalized), phrases) or name_normalized in allowed_normalized
        if not already_in_original and not explicitly_allowed:
            reasons.append(f'unsupported technology: "{name}"')
    return reasons


def _check_numeric_claims(original_text: str, rewritten_text: str) -> list[str]:
    reasons = []
    original_numbers = set(_NUMBER_RE.findall(original_text))
    for match in _NUMBER_RE.finditer(rewritten_text):
        number = match.group(0)
        if number not in original_numbers:
            reasons.append(f'unsupported numeric claim: "{number}"')
    return reasons


def _check_duration_claims(original_text: str, rewritten_text: str) -> list[str]:
    reasons = []
    original_normalized = normalize_text(original_text)
    for match in _DURATION_RE.finditer(rewritten_text):
        phrase = match.group(0)
        if normalize_text(phrase) not in original_normalized:
            reasons.append(f'unsupported duration claim: "{phrase.strip()}"')
    return reasons


def _check_leadership_claims(original_words: set[str], rewritten_words: set[str]) -> list[str]:
    reasons = []
    for term in _LEADERSHIP_TERMS:
        if term in rewritten_words and term not in original_words:
            reasons.append(f'unsupported leadership/scope claim: "{term}"')
    return reasons


def _check_retention(
    original_normalized: str, rewritten_normalized: str, target_emphasis: list[str], vocabulary: dict[str, list[str]],
) -> list[str]:
    """Reject a rewrite that quietly drops the facts a bullet was actually
    selected to emphasize, or that collapses into something vague enough to
    have lost most of what the original demonstrated.

    Two independent, deterministic checks — neither requires judging
    "quality," only counting recognized facts:

    1. Every `target_emphasis` fact (the job-relevant facts this bullet was
       chosen for) that the original bullet demonstrates must still appear
       in the rewrite. These are exactly the facts tailoring picked this
       bullet to highlight — losing one defeats the point of rewriting it.
    2. At least half of *all* the original bullet's recognized facts (not
       just the emphasized ones) must survive. A rewrite that keeps the
       emphasized skill but throws away everything else recognizable is
       "generic" in a way a resume shouldn't tolerate, even if nothing it
       added was false.
    """
    reasons: list[str] = []
    original_facts = recognized_facts(original_normalized, vocabulary)
    rewritten_facts = recognized_facts(rewritten_normalized, vocabulary)

    missing_emphasis = [fact for fact in target_emphasis if fact in original_facts and fact not in rewritten_facts]
    if missing_emphasis:
        joined = ", ".join(f'"{fact}"' for fact in missing_emphasis)
        reasons.append(f"rewrite dropped job-relevant fact(s): {joined}")

    if original_facts:
        retained = len(original_facts & rewritten_facts)
        ratio = retained / len(original_facts)
        if ratio < _RETENTION_RATIO_THRESHOLD:
            reasons.append(
                f"rewrite retains too little of the original bullet's supported facts "
                f"({retained}/{len(original_facts)} kept)"
            )

    return reasons


def validate_rewrite(
    original_text: str,
    rewritten_text: str,
    allowed_facts: list[str],
    target_emphasis: list[str] | None = None,
    evidence_vocabulary: dict[str, list[str]] | None = None,
) -> ValidationResult:
    """Accept a rewrite only if every technology, number, duration, and
    leadership/scope claim it makes is already present in `original_text`
    or explicitly listed in `allowed_facts`, AND it retains enough of the
    original bullet's substance (see `_check_retention`).

    `allowed_facts` widens the technology check only (e.g. skills the
    tailoring engine already recognizes in this bullet) — numbers,
    durations, and leadership claims are checked strictly against
    `original_text` itself, since those are exactly the categories the
    phase spec singles out as never safe to relax. `target_emphasis` is the
    subset of this bullet's facts the job actually cares about; omit it
    (or pass an empty list) to skip the emphasis-specific check while still
    applying the general retention ratio.

    `evidence_vocabulary` is what counts as a "recognized fact" for the
    technology and retention checks — pass
    `app.resume.evidence.build_evidence_vocabulary(master)` so a skill
    listed in the candidate's own master resume is recognized as evidence
    even if the job-matching alias table (`keyword_universe()`, the
    fallback when this is omitted) has no entry for it.
    """
    if not rewritten_text.strip():
        return ValidationResult(accepted=False, reasons=["empty rewrite"])

    vocabulary = evidence_vocabulary if evidence_vocabulary is not None else keyword_universe()

    original_normalized = normalize_text(original_text)
    rewritten_normalized = normalize_text(rewritten_text)
    allowed_normalized = {normalize_text(fact) for fact in allowed_facts}
    original_words = _normalized_words(original_text)
    rewritten_words = _normalized_words(rewritten_text)

    reasons: list[str] = []
    reasons += _check_technology_claims(original_normalized, rewritten_normalized, allowed_normalized, vocabulary)
    reasons += _check_numeric_claims(original_text, rewritten_text)
    reasons += _check_duration_claims(original_text, rewritten_text)
    reasons += _check_leadership_claims(original_words, rewritten_words)
    reasons += _check_retention(original_normalized, rewritten_normalized, target_emphasis or [], vocabulary)

    return ValidationResult(accepted=len(reasons) == 0, reasons=reasons)
