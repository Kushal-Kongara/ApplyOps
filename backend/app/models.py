"""Normalized job model shared by every collector."""

from dataclasses import dataclass
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Job:
    external_id: str
    source: str
    # The board/site identifier from config (Greenhouse board token, Ashby
    # board name, Lever site name). Part of job identity; a company's
    # *display name* is not, because it can be edited without the board
    # itself changing.
    source_identifier: str
    company: str
    title: str
    location: str
    description: str
    application_url: str
    posted_at: datetime | None
    # The source's own "last modified" timestamp, when it clearly supplies
    # one. Not the same as posted_at — see the module docstring in
    # app/collectors/base.py for per-source notes.
    source_updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        # A freshly collected job has only been seen once, so last_seen_at
        # defaults to the moment it was first seen.
        if self.last_seen_at is None:
            object.__setattr__(self, "last_seen_at", self.first_seen_at)

    @property
    def unique_key(self) -> str:
        """Stable identity for this job across scans.

        Built from `source + source_identifier + external_id` — not company,
        which is display metadata a user can rename without the underlying
        board changing. Each part is stripped and lowercased so the key does
        not change if a config value's casing is later touched up.
        """
        parts = [
            self.source,
            self.source_identifier,
            self.external_id,
        ]

        return ":".join(part.strip().lower() for part in parts)
