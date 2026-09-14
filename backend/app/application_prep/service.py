"""Orchestrates one application preparation: create a skeleton of
questions (default packet + any custom ones added later), then resolve
every one of them into an answer via `app/application_prep/resolver.py`.

Kept out of `app.api` so the API stays a thin HTTP layer, consistent with
how the rest of this app separates concerns (see `app/resume/service.py`).
"""

import sqlite3

from app import database
from app.application_prep.models import PreparedAnswer, QuestionSpec
from app.application_prep.profile import DEFAULT_APPLICANT_PROFILE_PATH, ApplicantProfileError, load_applicant_profile
from app.application_prep.questions import DEFAULT_QUESTIONS
from app.application_prep.resolver import resolve_question
from app.resume.llm_provider import ResumeLLMProvider
from app.resume.master import DEFAULT_MASTER_RESUME_PATH, MasterResumeError, load_master_resume
from app.resume.ollama_provider import build_provider_from_env
from app.resume.tailor import tailor_resume


class NoApprovedResumeError(RuntimeError):
    """Raised when preparing an application requires an approved resume
    and the job has none. The API turns this into a clean
    `no_approved_resume` response -- never silently falls back to a draft."""


def _find_approved_resume_id(connection: sqlite3.Connection, job_unique_key: str) -> int | None:
    for row in database.list_resume_versions(connection, job_unique_key):
        if row["status"] == "approved":
            return row["id"]
    return None


def create_preparation(
    connection: sqlite3.Connection,
    job_row: sqlite3.Row,
    *,
    resume_version_id: int | None = None,
) -> sqlite3.Row:
    """Create a new preparation with the default question packet as
    unresolved placeholders. Does not resolve any answers yet -- call
    `generate_preparation` for that, so a custom question can be added
    first if wanted.

    Prefers the job's approved resume version; raises
    `NoApprovedResumeError` if none exists and `resume_version_id` wasn't
    given explicitly.
    """
    if resume_version_id is None:
        resume_version_id = _find_approved_resume_id(connection, job_row["unique_key"])
        if resume_version_id is None:
            raise NoApprovedResumeError(
                f"No approved resume for job '{job_row['unique_key']}'. Generate and approve a resume first."
            )

    preparation_id = database.create_application_preparation(
        connection, job_row["unique_key"], resume_version_id=resume_version_id,
    )

    for question in DEFAULT_QUESTIONS:
        database.insert_application_answer(
            connection,
            preparation_id=preparation_id,
            question_id=question.id,
            question_text=question.question_text,
            question_type=question.question_type,
            category=question.category,
            required=question.required,
            answer=None,
            answer_source="user_input_required",
            needs_user_input=True,
            evidence_ids=[],
        )

    return database.get_application_preparation(connection, preparation_id)


def add_custom_question(
    connection: sqlite3.Connection,
    preparation_id: int,
    question_text: str,
    question_type: str,
    category: str,
    required: bool = True,
) -> sqlite3.Row:
    """Add one manually-specified question as an unresolved placeholder --
    the next `generate_preparation` call resolves it exactly like a
    default-packet question, dispatched by `category`."""
    answer_id = database.insert_application_answer(
        connection,
        preparation_id=preparation_id,
        question_id="",
        question_text=question_text,
        question_type=question_type,
        category=category,
        required=required,
        answer=None,
        answer_source="user_input_required",
        needs_user_input=True,
        evidence_ids=[],
    )
    return database.get_application_answer(connection, answer_id)


def _resolve_provider(llm_provider: ResumeLLMProvider | None) -> ResumeLLMProvider | None:
    """The provider to actually use for generation this call, or `None` if
    unconfigured/unreachable -- never an exception. A DGX being offline
    must never destroy a preparation; it only means open-ended questions
    fall back to `needs_user_input`."""
    provider = llm_provider if llm_provider is not None else build_provider_from_env()
    if provider is None:
        return None
    try:
        status = provider.status()
    except Exception:
        return None
    return provider if status.reachable else None


def generate_preparation(
    connection: sqlite3.Connection,
    preparation_id: int,
    *,
    applicant_profile_path=DEFAULT_APPLICANT_PROFILE_PATH,
    master_resume_path=DEFAULT_MASTER_RESUME_PATH,
    llm_provider: ResumeLLMProvider | None = None,
) -> sqlite3.Row:
    """Resolve every not-yet-user-edited answer in this preparation.

    Raises `ApplicantProfileError`/`MasterResumeError` if either source of
    truth is missing or malformed -- the API turns those into clean
    `applicant_profile_missing`/`master_resume_missing` responses. Never
    raises for a missing/unreachable LLM provider: open-ended questions
    just become `needs_user_input` instead.
    """
    preparation = database.get_application_preparation(connection, preparation_id)
    job_row = database.get_job(connection, preparation["job_unique_key"])

    profile = load_applicant_profile(applicant_profile_path)
    master = load_master_resume(master_resume_path)
    _tailored, analysis = tailor_resume(master, job_row["description"])
    provider = _resolve_provider(llm_provider)

    for row in database.list_application_answers(connection, preparation_id):
        if row["user_edited"]:
            continue

        question = QuestionSpec(
            id=row["question_id"], question_text=row["question_text"], question_type=row["question_type"],
            category=row["category"], required=bool(row["required"]),
        )
        resolved: PreparedAnswer = resolve_question(
            question, profile, master, analysis, job_row["title"], job_row["company"], job_row["description"], provider,
        )
        database.update_application_answer(
            connection, row["id"],
            answer=resolved.answer, answer_source=resolved.answer_source,
            needs_user_input=resolved.needs_user_input, evidence_ids=resolved.evidence_ids,
        )

    recompute_status(connection, preparation_id)
    return database.get_application_preparation(connection, preparation_id)


def recompute_status(connection: sqlite3.Connection, preparation_id: int) -> None:
    """`ready` only if the resume is set and every *required* answer has
    something and doesn't need input -- an unresolved optional question
    never blocks readiness."""
    preparation = database.get_application_preparation(connection, preparation_id)
    answers = database.list_application_answers(connection, preparation_id)

    required_unmet = any(row["required"] and row["needs_user_input"] for row in answers)
    resume_ok = preparation["resume_version_id"] is not None

    status = "ready" if (resume_ok and not required_unmet) else "needs_input"
    database.update_application_preparation(connection, preparation_id, status=status)
