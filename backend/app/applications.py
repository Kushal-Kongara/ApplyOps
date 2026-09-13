"""Tracking job applications, and turning ranked jobs into a daily action queue.

Kept separate from `app/database.py` (which only holds SQL) and from
`app/matching/` (which only scores jobs): this is the layer that decides
what to *do* about a job — what statuses exist, which ones mean "done,"
and how a scored job plus its tracked status becomes one line in `daily`.
No new ranking formula lives here; ordering and score bands are read
straight from what `app/matching/` already computed.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app import database

NEW = "new"
SHORTLISTED = "shortlisted"
APPLYING = "applying"
APPLIED = "applied"
OUTREACH_SENT = "outreach_sent"
INTERVIEWING = "interviewing"
REJECTED = "rejected"
OFFER = "offer"
SKIPPED = "skipped"

STATUSES = (NEW, SHORTLISTED, APPLYING, APPLIED, OUTREACH_SENT, INTERVIEWING, REJECTED, OFFER, SKIPPED)

# Once a job is in one of these states there's nothing left to "act on" as
# a new candidate — it's already been decided one way or another. It can
# still resurface through a follow-up reminder (see FOLLOW_UP_EXCLUDED
# below), which is a different, narrower question.
DAILY_EXCLUDED_STATUSES = (APPLIED, INTERVIEWING, REJECTED, OFFER, SKIPPED)

# A rejected or skipped job has nothing left to follow up on, even if a
# stale next_follow_up_at is still sitting on the row.
FOLLOW_UP_EXCLUDED_STATUSES = (REJECTED, SKIPPED)

HIGH_PRIORITY_MIN_SCORE = 70
REVIEW_MIN_SCORE = 65


class ApplicationError(ValueError):
    """Raised for invalid application input (e.g. an unknown status)."""


def validate_status(status: str) -> str:
    """Return `status` unchanged if valid, else raise `ApplicationError`."""
    if status not in STATUSES:
        raise ApplicationError(
            f"'{status}' is not a valid application status. Valid statuses: {', '.join(STATUSES)}."
        )
    return status


def parse_datetime_arg(value: str) -> datetime:
    """Parse a CLI-provided date/datetime string into a UTC-aware datetime.

    Accepts a bare date ("2026-09-20", assumed midnight UTC) or a full
    ISO-8601 datetime. Raises `ApplicationError` with a clear message on
    anything else, rather than letting a raw `ValueError` leak out.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApplicationError(
            f"'{value}' is not a valid date/datetime. Use YYYY-MM-DD or full ISO-8601."
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class DailyItem:
    """One line of the daily action queue — a job plus its tracked status."""

    job_unique_key: str
    kind: str  # "new" or "follow_up"
    title: str
    company: str
    location: str
    application_url: str
    status: str
    total_score: int | None
    visa_signal: str | None
    visa_evidence: str | None
    matched_skills: list[str] = field(default_factory=list)
    next_follow_up_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DailyQueue:
    high_priority: list[DailyItem]
    review: list[DailyItem]
    follow_ups: list[DailyItem]

    @property
    def is_empty(self) -> bool:
        return not (self.high_priority or self.review or self.follow_ups)


def _row_to_new_item(row) -> DailyItem:
    return DailyItem(
        job_unique_key=row["job_unique_key"],
        kind="new",
        title=row["title"],
        company=row["company"],
        location=row["location"],
        application_url=row["application_url"],
        status=row["status"],
        total_score=row["total_score"],
        visa_signal=row["visa_signal"],
        visa_evidence=row["visa_evidence"],
        matched_skills=json.loads(row["matched_skills"]),
    )


def _row_to_follow_up_item(row) -> DailyItem:
    matched_skills = json.loads(row["matched_skills"]) if row["matched_skills"] is not None else []
    next_follow_up_at = row["next_follow_up_at"]
    return DailyItem(
        job_unique_key=row["job_unique_key"],
        kind="follow_up",
        title=row["title"],
        company=row["company"],
        location=row["location"],
        application_url=row["application_url"],
        status=row["status"],
        total_score=row["total_score"],
        visa_signal=row["visa_signal"],
        visa_evidence=row["visa_evidence"],
        matched_skills=matched_skills,
        next_follow_up_at=datetime.fromisoformat(next_follow_up_at) if next_follow_up_at else None,
    )


def build_daily_queue(connection, profile_id: str, now: datetime | None = None) -> DailyQueue:
    """Assemble the daily action queue for one profile.

    Three sections, in priority order:
      1. `high_priority` — active, undecided, actionable jobs scoring 70+.
      2. `review` — the same, scoring 65-69.
      3. `follow_ups` — tracked applications whose reminder date has arrived,
         regardless of score band (a due follow-up is its own kind of
         priority, separate from a fresh candidate's score).

    All three preserve the ranking order `app/matching/` already produced —
    this function filters and labels, it does not re-score or re-rank.
    """
    now = now or database.utcnow()

    high_rows = database.get_daily_new_candidates(
        connection, profile_id, HIGH_PRIORITY_MIN_SCORE, DAILY_EXCLUDED_STATUSES
    )
    review_rows = database.get_daily_new_candidates(
        connection, profile_id, REVIEW_MIN_SCORE, DAILY_EXCLUDED_STATUSES
    )
    # get_daily_new_candidates is a ">= min_score" query, so the review pull
    # (>= 65) includes the high-priority jobs (>= 70) too; exclude those by
    # key so a job never appears in both bands.
    high_keys = {row["job_unique_key"] for row in high_rows}
    review_rows = [row for row in review_rows if row["job_unique_key"] not in high_keys]

    follow_up_rows = database.get_due_follow_ups(connection, profile_id, now, FOLLOW_UP_EXCLUDED_STATUSES)

    return DailyQueue(
        high_priority=[_row_to_new_item(row) for row in high_rows],
        review=[_row_to_new_item(row) for row in review_rows],
        follow_ups=[_row_to_follow_up_item(row) for row in follow_up_rows],
    )
