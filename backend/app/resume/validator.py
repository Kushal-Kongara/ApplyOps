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

# Leadership/ownership verbs a bullet can only claim if the original
# evidence already uses that same *concept* — never inferred from context.
# Grouped into canonical families so a harmless grammatical variant of an
# already-supported claim ("owning" in evidence, "owned" in a rewrite)
# passes, while a genuinely different leadership concept ("led" where
# evidence only ever says "owned") still doesn't. This is deliberately a
# small, fixed, hand-maintained set of conjugations for exactly the verbs
# this validator already cares about — not a general stemmer, which would
# risk conflating unrelated words this file was never meant to reason about.
_LEADERSHIP_FAMILIES: dict[str, tuple[str, ...]] = {
    "own": ("own", "owns", "owned", "owning"),
    "lead": ("lead", "leads", "led", "leading"),
    "manage": ("manage", "manages", "managed", "managing", "management"),
    "mentor": ("mentor", "mentors", "mentored", "mentoring"),
    "supervise": ("supervise", "supervises", "supervised", "supervising"),
    "direct": ("direct", "directs", "directed", "directing"),
    "spearhead": ("spearhead", "spearheads", "spearheaded", "spearheading"),
    "architect": ("architect", "architects", "architected", "architecting"),
    "found": ("found", "founds", "founded", "founding"),
}
_WORD_TO_LEADERSHIP_FAMILY: dict[str, str] = {
    word: family for family, words in _LEADERSHIP_FAMILIES.items() for word in words
}

# Scope/scale phrases a rewrite can only claim if already present in the
# evidence — canonicalizing "owned" == "owning" must never be read as
# license to also widen *scope*: "architected a workflow" does not support
# "architected company-wide infrastructure." Checked as fixed phrases
# (like duration claims), not word-by-word, since these are multi-word
# scale descriptors, not verb conjugations.
_SCOPE_SCALE_PHRASES = (
    "company-wide", "company wide", "companywide",
    "org-wide", "org wide", "orgwide",
    "organization-wide", "organization wide", "organizationwide",
    "enterprise-wide", "enterprise wide", "enterprisewide",
    "team-wide", "team wide", "teamwide",
    "globally", "across the company", "across the organization",
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


def normalized_words(text: str) -> set[str]:
    return set(normalize_text(text).split())


def check_technology_claims(
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


def check_numeric_claims(original_text: str, rewritten_text: str) -> list[str]:
    reasons = []
    original_numbers = set(_NUMBER_RE.findall(original_text))
    for match in _NUMBER_RE.finditer(rewritten_text):
        number = match.group(0)
        if number not in original_numbers:
            reasons.append(f'unsupported numeric claim: "{number}"')
    return reasons


def check_duration_claims(original_text: str, rewritten_text: str) -> list[str]:
    reasons = []
    original_normalized = normalize_text(original_text)
    for match in _DURATION_RE.finditer(rewritten_text):
        phrase = match.group(0)
        if normalize_text(phrase) not in original_normalized:
            reasons.append(f'unsupported duration claim: "{phrase.strip()}"')
    return reasons


def check_leadership_claims(original_words: set[str], rewritten_words: set[str]) -> list[str]:
    """Reject a leadership/ownership *concept* (own/lead/manage/mentor/...)
    that doesn't already appear, in any conjugation, in the original text.
    A rewrite may freely reconjugate a concept the evidence already
    supports (evidence "owning", rewrite "owned") -- it just can't
    introduce a concept that was never there at all."""
    original_families = {_WORD_TO_LEADERSHIP_FAMILY[w] for w in original_words if w in _WORD_TO_LEADERSHIP_FAMILY}
    rewritten_families = {_WORD_TO_LEADERSHIP_FAMILY[w] for w in rewritten_words if w in _WORD_TO_LEADERSHIP_FAMILY}

    reasons = []
    for family in sorted(rewritten_families - original_families):
        surface_term = next(w for w in rewritten_words if _WORD_TO_LEADERSHIP_FAMILY.get(w) == family)
        reasons.append(f'unsupported leadership/scope claim: "{surface_term}"')
    return reasons


def check_scope_claims(original_text: str, rewritten_text: str) -> list[str]:
    """Reject an unsupported scope/scale claim (e.g. "company-wide") even
    when the leadership verb it modifies is otherwise legitimately
    supported -- canonicalizing a verb's conjugation is never license to
    widen what it was claimed to apply to."""
    original_normalized = normalize_text(original_text)
    rewritten_normalized = normalize_text(rewritten_text)

    seen_normalized: set[str] = set()
    reasons = []
    for phrase in _SCOPE_SCALE_PHRASES:
        phrase_normalized = normalize_text(phrase)
        if not phrase_normalized or phrase_normalized in seen_normalized:
            continue
        if phrase_normalized in rewritten_normalized and phrase_normalized not in original_normalized:
            reasons.append(f'unsupported scope claim: "{phrase}"')
            seen_normalized.add(phrase_normalized)
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
    original_words = normalized_words(original_text)
    rewritten_words = normalized_words(rewritten_text)

    reasons: list[str] = []
    reasons += check_technology_claims(original_normalized, rewritten_normalized, allowed_normalized, vocabulary)
    reasons += check_numeric_claims(original_text, rewritten_text)
    reasons += check_duration_claims(original_text, rewritten_text)
    reasons += check_leadership_claims(original_words, rewritten_words)
    reasons += check_scope_claims(original_text, rewritten_text)
    reasons += _check_retention(original_normalized, rewritten_normalized, target_emphasis or [], vocabulary)

    return ValidationResult(accepted=len(reasons) == 0, reasons=reasons)
