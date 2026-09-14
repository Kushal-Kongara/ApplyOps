"""Deterministic matching of one ATS form label to what can answer it --
a stable applicant-profile field, a prepared application answer, or
neither. No embeddings, no vector search, no LLM routing: normalized text
plus a small fixed synonym table, exactly as the phase spec asks for.
When nothing matches confidently, the caller must leave the field alone.
"""

from app.matching.text import normalize_text

# Normalized label phrase -> applicant-profile/prepared-answer category.
# Every phrase here is written in `normalize_text()` form.
_KNOWN_FIELD_SYNONYMS: dict[str, str] = {
    "full name": "full_name",
    "name": "full_name",
    "your name": "full_name",
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile number": "phone",
    "location": "location",
    "current location": "location",
    "linkedin": "linkedin",
    "linkedin profile": "linkedin",
    "linkedin url": "linkedin",
    "github": "github",
    "github url": "github",
    "github profile": "github",
    "portfolio": "portfolio",
    "portfolio url": "portfolio",
    "personal website": "portfolio",
    "website": "portfolio",
    "are you authorized to work in the united states": "work_authorization",
    "are you legally authorized to work in the united states": "work_authorization",
    "are you authorized to work in the us": "work_authorization",
    "work authorization": "work_authorization",
    "will you now or in the future require sponsorship": "sponsorship",
    "will you require sponsorship": "sponsorship",
    "do you require visa sponsorship": "sponsorship",
    "do you now or will you in the future require sponsorship to work": "sponsorship",
    "are you willing to relocate": "relocation",
    "willing to relocate": "relocation",
    "relocation": "relocation",
    "why are you interested in this role": "role_motivation",
    "why this role": "role_motivation",
    "why do you want this job": "role_motivation",
    "why this company": "company_motivation",
    "why are you interested in this company": "company_motivation",
    "why do you want to work here": "company_motivation",
    "describe your most relevant experience for this role": "experience",
    "relevant experience": "experience",
}

# Substring markers -- never auto-answered unless the profile has an
# explicit policy (checked by the caller, not here).
_SENSITIVE_MARKERS = (
    "race", "ethnicity", "gender", "disability", "veteran",
    "religion", "sexual orientation", "pronoun",
)

# Never touched at all, regardless of any policy -- these belong to the
# user alone.
_LEGAL_ATTESTATION_MARKERS = (
    "signature", "certify", "certification", "background check",
    "consent", "terms and conditions", "terms of service", "attest",
    "i agree", "acknowledge",
)


def normalize_label(text: str) -> str:
    return normalize_text(text)


def match_known_field(label: str) -> str | None:
    """A stable applicant-profile/motivation category this label
    confidently means, or `None` if it isn't one of the fixed phrases this
    MVP recognizes. Never a fuzzy/partial guess."""
    return _KNOWN_FIELD_SYNONYMS.get(normalize_label(label))


def is_sensitive_field(label: str) -> bool:
    normalized = normalize_label(label)
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def is_legal_attestation_field(label: str) -> bool:
    normalized = normalize_label(label)
    return any(marker in normalized for marker in _LEGAL_ATTESTATION_MARKERS)


def match_prepared_answer(label: str, prepared_question_texts: list[str]) -> int | None:
    """Index into `prepared_question_texts` this label most likely refers
    to, or `None` if nothing is a confident enough match. A match requires
    either text containment or a majority of shared normalized words --
    deliberately simple, deterministic overlap, not similarity scoring."""
    label_normalized = normalize_label(label)
    label_words = set(label_normalized.split())
    if not label_words:
        return None

    for index, question_text in enumerate(prepared_question_texts):
        question_normalized = normalize_label(question_text)
        if not question_normalized:
            continue
        if label_normalized in question_normalized or question_normalized in label_normalized:
            return index

        question_words = set(question_normalized.split())
        if not question_words:
            continue
        overlap = len(label_words & question_words)
        if overlap / max(len(label_words), len(question_words)) > 0.5:
            return index

    return None
