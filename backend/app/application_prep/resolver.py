"""Resolves one `QuestionSpec` into a `PreparedAnswer`.

Dispatch order, per question:

1. Sensitive/demographic questions (`category == "demographic_optional"`)
   always need user input unless the candidate has set an explicit policy.
2. Known default-packet questions (matched by `question.id`) resolve
   directly from the applicant profile / a years-of-experience calculation.
3. Custom questions in a profile-backed category resolve the same way,
   using the category (plus light keyword matching for categories that
   cover more than one profile field) to find the right fact.
4. A "how many years of X" question (any category) is answered by the
   deterministic calculator in `years_experience.py`, never guessed.
5. Anything else in a generation-friendly category (experience, skills,
   company/role motivation, behavioral, other) is generated from evidence
   via the configured LLM provider -- or marked `needs_user_input` if no
   provider is reachable.
6. Anything that reaches none of the above needs user input.

Nothing here ever invents a fact; every branch either returns a
profile/evidence-backed answer or an honest `needs_user_input=True`.
"""

from app.application_prep.answer_validator import validate_answer
from app.application_prep.models import ApplicantProfile, PreparedAnswer, QuestionSpec
from app.application_prep.years_experience import calculate_years_of_experience
from app.matching.text import any_phrase_matches, normalize_text
from app.resume.evidence import build_evidence_vocabulary
from app.resume.llm_provider import AnswerRequest, ResumeLLMProvider, ResumeLLMProviderError
from app.resume.models import MasterResume, TailoringAnalysis

GENERATION_CATEGORIES = ("experience", "skills", "company_motivation", "role_motivation", "behavioral", "other")
PROFILE_SINGLE_FACT_CATEGORIES = ("work_authorization", "location", "relocation", "availability")

JD_EXCERPT_MAX_CHARS = 800
MAX_EVIDENCE_BULLETS = 4


def _needs_input(question: QuestionSpec) -> PreparedAnswer:
    return PreparedAnswer(
        question_text=question.question_text, question_type=question.question_type,
        category=question.category, required=question.required,
        answer=None, answer_source="user_input_required", needs_user_input=True, evidence_ids=[],
    )


def _from_profile(question: QuestionSpec, answer: str) -> PreparedAnswer:
    if not answer.strip():
        return _needs_input(question)
    return PreparedAnswer(
        question_text=question.question_text, question_type=question.question_type,
        category=question.category, required=question.required,
        answer=answer, answer_source="applicant_profile", needs_user_input=False, evidence_ids=[],
    )


def _from_bool(question: QuestionSpec, value: bool | None, true_text: str, false_text: str) -> PreparedAnswer:
    if value is None:
        return _needs_input(question)
    return PreparedAnswer(
        question_text=question.question_text, question_type=question.question_type,
        category=question.category, required=question.required,
        answer=true_text if value else false_text, answer_source="applicant_profile",
        needs_user_input=False, evidence_ids=[],
    )


def _resolve_salary(question: QuestionSpec, profile: ApplicantProfile) -> PreparedAnswer:
    expectation = profile.preferences.salary_expectation
    if expectation.mode == "range" and expectation.min is not None and expectation.max is not None:
        return _from_profile(question, f"${expectation.min:,} - ${expectation.max:,}")
    # mode == "user_input" or anything unrecognized: always ask, never derive
    # a number from the job description and present it as the candidate's own.
    return _needs_input(question)


def _resolve_default_by_id(question: QuestionSpec, profile: ApplicantProfile) -> PreparedAnswer | None:
    """Resolves the fixed default-packet question ids. Returns `None` for
    any id it doesn't recognize (e.g. a custom question)."""
    handlers = {
        "full_name": lambda: _from_profile(question, profile.identity.full_name),
        "email": lambda: _from_profile(question, profile.identity.email),
        "phone": lambda: _from_profile(question, profile.identity.phone),
        "location": lambda: _from_profile(question, profile.identity.location),
        "linkedin": lambda: _from_profile(question, profile.links.linkedin),
        "github": lambda: _from_profile(question, profile.links.github),
        "portfolio": lambda: _from_profile(question, profile.links.portfolio),
        "work_authorization": lambda: (
            _from_profile(question, profile.work_authorization.status_label)
            if profile.work_authorization.status_label
            else _from_bool(question, profile.work_authorization.authorized_to_work, "Yes", "No")
        ),
        "sponsorship_now": lambda: _from_bool(
            question, profile.work_authorization.requires_sponsorship_now, "Yes", "No"
        ),
        "sponsorship_future": lambda: _from_bool(
            question, profile.work_authorization.requires_sponsorship_future, "Yes", "No"
        ),
        "relocation": lambda: _from_profile(question, profile.preferences.relocation),
        "availability": lambda: _from_profile(question, profile.preferences.start_availability),
        "salary_expectation": lambda: _resolve_salary(question, profile),
    }
    handler = handlers.get(question.id)
    return handler() if handler else None


def _resolve_custom_identity_or_contact(question: QuestionSpec, profile: ApplicantProfile) -> PreparedAnswer | None:
    """Best-effort keyword match for a custom question in the `identity`
    or `contact` category, which (unlike every other category) can mean
    more than one distinct profile field. Returns `None` (never a guess)
    when the question text doesn't clearly point at one field."""
    text = normalize_text(question.question_text)
    field_keywords = [
        (["email", "e mail"], profile.identity.email),
        (["phone", "telephone", "mobile"], profile.identity.phone),
        (["linkedin"], profile.links.linkedin),
        (["github"], profile.links.github),
        (["portfolio", "website", "personal site"], profile.links.portfolio),
        (["name"], profile.identity.full_name),
    ]
    for keywords, value in field_keywords:
        if any_phrase_matches(text, [normalize_text(k) for k in keywords]):
            return _from_profile(question, value)
    return None


def _resolve_deterministic(question: QuestionSpec, profile: ApplicantProfile) -> PreparedAnswer | None:
    """Deterministic, profile-backed resolution for the default packet and
    any custom question in a profile-backed category. Returns `None` if
    this question isn't one of those (so the caller can try generation)."""
    default_answer = _resolve_default_by_id(question, profile)
    if default_answer is not None:
        return default_answer

    category = question.category
    if category in ("identity", "contact"):
        return _resolve_custom_identity_or_contact(question, profile)
    if category == "work_authorization":
        return _from_bool(question, profile.work_authorization.authorized_to_work, "Yes", "No")
    if category == "sponsorship":
        # A generic custom sponsorship question defaults to "right now" --
        # the far more common phrasing -- unless it explicitly asks about
        # the future.
        value = (
            profile.work_authorization.requires_sponsorship_future
            if "future" in normalize_text(question.question_text)
            else profile.work_authorization.requires_sponsorship_now
        )
        return _from_bool(question, value, "Yes", "No")
    if category == "location":
        return _from_profile(question, profile.identity.location)
    if category == "relocation":
        return _from_profile(question, profile.preferences.relocation)
    if category == "availability":
        return _from_profile(question, profile.preferences.start_availability)
    if category == "salary":
        return _resolve_salary(question, profile)
    if category == "education":
        if not profile.education:
            return _needs_input(question)
        formatted = "; ".join(
            f"{entry.degree}, {entry.school} ({entry.graduation_year})".strip(", ()")
            for entry in profile.education
        )
        return _from_profile(question, formatted)

    return None


def _detect_years_question_skill(question_text: str, vocabulary: dict[str, list[str]]) -> str | None:
    normalized = normalize_text(question_text)
    if "year" not in normalized:
        return None
    matches = [name for name, phrases in vocabulary.items() if any_phrase_matches(normalized, phrases)]
    if not matches:
        return None
    # More than one recognized skill mentioned -- the longest name is the
    # simplest deterministic tiebreaker (favors a specific multi-word skill
    # like "Retrieval-Augmented Generation (RAG)" over a shorter one it
    # might textually contain).
    return max(matches, key=len)


def _resolve_years_of_experience(question: QuestionSpec, master: MasterResume) -> PreparedAnswer | None:
    vocabulary = build_evidence_vocabulary(master)
    skill = _detect_years_question_skill(question.question_text, vocabulary)
    if skill is None:
        return None

    result = calculate_years_of_experience(master, skill)
    if not result.supported:
        return PreparedAnswer(
            question_text=question.question_text, question_type=question.question_type,
            category=question.category, required=question.required,
            answer=None, answer_source="user_input_required", needs_user_input=True, evidence_ids=[],
        )
    years_text = f"{result.years:g} years"
    return PreparedAnswer(
        question_text=question.question_text, question_type=question.question_type,
        category=question.category, required=question.required,
        answer=years_text, answer_source="master_resume", needs_user_input=False,
        evidence_ids=result.evidence_ids,
    )


def _select_evidence_bullets(master: MasterResume, analysis: TailoringAnalysis) -> tuple[list[str], list[str]]:
    """The top bullet from each JD-relevant experience entry, as generation
    context. Returns `(bullet_texts, evidence_ids)`."""
    texts: list[str] = []
    ids: list[str] = []
    for entry in master.experience:
        if entry.id not in analysis.selected_experience:
            continue
        if not entry.bullets:
            continue
        bullet = entry.bullets[0]
        texts.append(bullet.text)
        ids.append(bullet.id)
        if len(texts) >= MAX_EVIDENCE_BULLETS:
            break
    return texts, ids


def resolve_question(
    question: QuestionSpec,
    profile: ApplicantProfile,
    master: MasterResume,
    analysis: TailoringAnalysis,
    job_title: str,
    company: str,
    job_description: str,
    provider: ResumeLLMProvider | None,
) -> PreparedAnswer:
    """Resolve one question end to end. `provider=None` means no LLM
    provider is configured/reachable -- generation-only questions become
    `needs_user_input` rather than failing the whole preparation."""
    if question.category == "demographic_optional":
        if profile.demographic_response_policy == "prefer_not_to_answer":
            return _from_profile(question, "Prefer not to answer")
        return _needs_input(question)

    deterministic = _resolve_deterministic(question, profile)
    if deterministic is not None:
        return deterministic

    years_answer = _resolve_years_of_experience(question, master)
    if years_answer is not None:
        return years_answer

    if question.category not in GENERATION_CATEGORIES:
        return _needs_input(question)

    if provider is None:
        return _needs_input(question)

    evidence_bullets, evidence_ids = _select_evidence_bullets(master, analysis)
    allowed_facts = list(analysis.strong_matches)
    jd_excerpt = job_description.strip()[:JD_EXCERPT_MAX_CHARS]

    request = AnswerRequest(
        question_text=question.question_text, job_title=job_title, company=company,
        jd_excerpt=jd_excerpt, allowed_facts=allowed_facts, evidence_bullets=evidence_bullets,
    )

    try:
        response = provider.generate_answer(request)
    except ResumeLLMProviderError:
        return _needs_input(question)

    vocabulary = build_evidence_vocabulary(master)
    evidence_text = " ".join(evidence_bullets)
    result = validate_answer(evidence_text, response.answer_text, allowed_facts, vocabulary)
    if not result.accepted:
        return _needs_input(question)

    return PreparedAnswer(
        question_text=question.question_text, question_type=question.question_type,
        category=question.category, required=question.required,
        answer=response.answer_text, answer_source="generated_from_evidence",
        needs_user_input=False, evidence_ids=evidence_ids,
    )
