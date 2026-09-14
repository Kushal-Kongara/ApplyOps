"""Typed structures for application preparation.

Two layers: the applicant's own local facts (`ApplicantProfile` and its
parts — the source of truth for stable personal answers), and the
per-question answer model (`QuestionSpec`/`PreparedAnswer`) that both the
default question packet and any custom question use.
"""

from dataclasses import dataclass, field

QUESTION_TYPES = ("text", "textarea", "number", "boolean", "single_select", "multi_select", "date")

QUESTION_CATEGORIES = (
    "identity", "contact", "work_authorization", "sponsorship", "location", "relocation",
    "availability", "salary", "education", "experience", "skills",
    "company_motivation", "role_motivation", "behavioral", "demographic_optional", "other",
)

# Where a prepared answer's text actually came from — every answer must
# say which of these it is; nothing is ever allowed to look authoritative
# without one.
ANSWER_SOURCES = (
    "applicant_profile", "master_resume", "approved_resume",
    "generated_from_evidence", "user_input_required", "user_edited",
)

PREPARATION_STATUSES = ("draft", "needs_input", "ready", "used")


@dataclass(frozen=True, slots=True)
class Identity:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""


@dataclass(frozen=True, slots=True)
class Links:
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


@dataclass(frozen=True, slots=True)
class WorkAuthorization:
    authorized_to_work: bool | None = None
    requires_sponsorship_now: bool | None = None
    requires_sponsorship_future: bool | None = None
    status_label: str = ""


@dataclass(frozen=True, slots=True)
class SalaryExpectation:
    """`mode` is the only field application code ever branches on:
    `"user_input"` (or anything else unrecognized) always means "ask the
    candidate," never a reason to guess; `"range"` supplies `min`/`max`
    the candidate has explicitly set themselves."""

    mode: str = "user_input"
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True, slots=True)
class Preferences:
    relocation: str = ""
    remote: str = ""
    start_availability: str = ""
    salary_expectation: SalaryExpectation = field(default_factory=SalaryExpectation)


@dataclass(frozen=True, slots=True)
class EducationEntry:
    school: str = ""
    degree: str = ""
    graduation_year: str = ""


@dataclass(frozen=True, slots=True)
class ApplicantProfile:
    """The one local, truthful source of stable personal facts an
    application can answer without generating anything. Gitignored --
    see `app/application_prep/profile.py`."""

    identity: Identity
    links: Links
    work_authorization: WorkAuthorization
    preferences: Preferences
    education: list[EducationEntry] = field(default_factory=list)
    # Sensitive/protected demographic questions default to always needing
    # user input; the only way to pre-fill one is an explicit, candidate-set
    # policy here -- never an inference.
    demographic_response_policy: str | None = None
    custom_facts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    """One question to answer -- either from the default standard packet
    or added manually. Not yet persisted; `PreparedAnswer` is what actually
    gets stored once resolved."""

    id: str
    question_text: str
    question_type: str
    category: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class PreparedAnswer:
    """One resolved (or unresolved) answer. `needs_user_input=True` means
    exactly what it says regardless of what `answer` holds -- a UI must
    never present it as authoritative just because `answer` is non-empty."""

    question_text: str
    question_type: str
    category: str
    required: bool
    answer: str | None
    answer_source: str
    needs_user_input: bool
    evidence_ids: list[str] = field(default_factory=list)
    confidence: str | None = None
