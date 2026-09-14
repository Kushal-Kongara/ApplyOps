"""Typed structures for one ATS fill attempt."""

from dataclasses import dataclass, field

# What happened to one field on the form -- the UI must distinguish all four.
FIELD_STATUSES = ("filled", "needs_input", "skipped", "unsupported")


@dataclass(frozen=True, slots=True)
class FilledField:
    label: str
    status: str  # one of FIELD_STATUSES
    value: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FillResult:
    ats: str | None
    application_url: str
    fields: list[FilledField] = field(default_factory=list)
    resume_uploaded: bool = False
    resume_error: str | None = None
    error: str | None = None
