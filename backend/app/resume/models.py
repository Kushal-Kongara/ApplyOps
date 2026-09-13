"""Typed structures for the resume tailoring pipeline.

Two kinds of objects live here: the **master resume** (`MasterResume` and
its parts) — the single, truthful source of every fact a resume can ever
state — and the **tailored output** (`TailoredResume`/`TailoringAnalysis`)
produced from it for one job. Every piece of text in a `TailoredResume`
traces back to a specific ID in the master resume; nothing here can hold
text that didn't come from `resume_master.json`.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Contact:
    name: str
    headline: str
    email: str
    phone: str = ""
    linkedin: str = ""
    github: str = ""


@dataclass(frozen=True, slots=True)
class Bullet:
    """One truthful, atomic claim. `id` is the evidence reference every
    tailored bullet traces back to — e.g. `exp_liminl_b2`."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class ExperienceEntry:
    id: str
    company: str
    title: str
    start_date: str
    end_date: str
    bullets: list[Bullet]
    location: str = ""


@dataclass(frozen=True, slots=True)
class ProjectEntry:
    id: str
    name: str
    technologies: list[str]
    bullets: list[Bullet]


@dataclass(frozen=True, slots=True)
class EducationEntry:
    id: str
    school: str
    degree: str
    start_date: str = ""
    end_date: str = ""
    location: str = ""


@dataclass(frozen=True, slots=True)
class Achievement:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class MasterResume:
    """The one canonical, truthful source of candidate facts. Every field
    here is exactly what the candidate provided — tailoring may select,
    reorder, or omit from this, but never add to it."""

    contact: Contact
    summary: str
    experience: list[ExperienceEntry]
    skills: dict[str, list[str]]
    education: list[EducationEntry]
    projects: list[ProjectEntry] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TailoredBullet:
    """A bullet as it appears in the tailored resume. `text` is always
    verbatim from the master resume (see `app/resume/tailor.py` for why
    this version never rephrases) — `evidence_id` names exactly which
    master bullet it is."""

    text: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class TailoredExperienceEntry:
    id: str
    company: str
    title: str
    start_date: str
    end_date: str
    location: str
    bullets: list[TailoredBullet]


@dataclass(frozen=True, slots=True)
class TailoredProjectEntry:
    id: str
    name: str
    technologies: list[str]
    bullets: list[TailoredBullet]


@dataclass(frozen=True, slots=True)
class TailoredResume:
    """The fully assembled, job-specific resume content — still nothing
    but a selection/reordering of `MasterResume` data. This is what
    `app/resume/latex.py` renders; it is never handed raw JD or LLM text."""

    contact: Contact
    summary: str
    skills: list[str]
    experience: list[TailoredExperienceEntry]
    education: list[EducationEntry]
    projects: list[TailoredProjectEntry] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TailoringAnalysis:
    """Why the resume looks the way it does — powers the UI's Changes panel.

    `unsupported_requirements` is purely informational: it names JD terms
    the master resume has no evidence for. Nothing in this analysis, or in
    the `TailoredResume` it accompanies, ever turns an unsupported
    requirement into a claim.
    """

    strong_matches: list[str] = field(default_factory=list)
    supported_but_underemphasized: list[str] = field(default_factory=list)
    unsupported_requirements: list[str] = field(default_factory=list)
    selected_experience: list[str] = field(default_factory=list)
    selected_projects: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RewriteAttempt:
    """Full provenance for one attempted LLM rewrite of one bullet — kept
    even when rejected, so nothing about an LLM-enhanced version is hidden
    from the user. `rewritten_text` is `None` only when the provider itself
    failed (unreachable/timeout/malformed output) before producing text to
    validate."""

    evidence_id: str
    original_text: str
    rewritten_text: str | None
    validation_status: str  # "accepted" | "rejected" | "error"
    validation_reasons: list[str]
    provider: str
    model: str
