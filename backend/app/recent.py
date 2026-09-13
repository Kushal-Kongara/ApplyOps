"""Recent Jobs timeline: non-overlapping 2-hour discovery-age buckets.

"Discovery age" is measured from `jobs.first_seen_at` — the timestamp
`app/database.py` already sets once, the first time a job is ever stored,
and never touches again on later rescans (see `_upsert_jobs`'s UPDATE
branch, which omits `first_seen_at`). That's exactly "when JobOS first
discovered this job," which is what this timeline answers — not
`posted_at` (the source's own claim, which can say a job is days old even
though we only just found it) and not a new column (none was needed).

Bucketing is a pure function of `(now, first_seen_at)` pairs, so it's
tested directly without a database. Ranking within a bucket is whatever
`database.list_matches` already returned — score descending, then
`first_seen_at` descending as a tiebreak — preserved by iterating the rows
in order and appending each into its bucket; nothing here re-sorts, re-
scores, or re-filters beyond the `min_score` already passed through to
`list_matches`.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app import database
from app.applications import DailyItem, job_card_from_row

BUCKET_SIZE_HOURS = 2
WINDOW_HOURS = 24
HIGH_PRIORITY_MIN_SCORE = 70  # same threshold the rest of the app uses

OLDER_KEY = "24+"
OLDER_LABEL = "Older than 24 hours"

DEFAULT_MIN_SCORE = 65
DEFAULT_OLDER_LIMIT = 25


@dataclass(frozen=True, slots=True)
class RecentJob:
    """One job on the timeline: its job card, plus when it was discovered."""

    job: DailyItem
    first_seen_at: datetime


@dataclass(slots=True)
class Bucket:
    key: str
    label: str
    min_hours: int
    max_hours: int | None  # None only for the "older" bucket
    jobs: list[RecentJob] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.jobs)


@dataclass(frozen=True, slots=True)
class RecentTimeline:
    generated_at: datetime
    buckets: list[Bucket]
    older: Bucket
    older_total_count: int  # true total older than 24h, independent of pagination

    @property
    def last_24h_count(self) -> int:
        return sum(bucket.count for bucket in self.buckets)

    @property
    def high_priority_count(self) -> int:
        return sum(
            1 for bucket in self.buckets for recent_job in bucket.jobs
            if recent_job.job.total_score is not None and recent_job.job.total_score >= HIGH_PRIORITY_MIN_SCORE
        )

    @property
    def review_count(self) -> int:
        return sum(
            1 for bucket in self.buckets for recent_job in bucket.jobs
            if recent_job.job.total_score is not None and recent_job.job.total_score < HIGH_PRIORITY_MIN_SCORE
        )


def _bucket_boundaries() -> list[tuple[int, int]]:
    return [(hour, hour + BUCKET_SIZE_HOURS) for hour in range(0, WINDOW_HOURS, BUCKET_SIZE_HOURS)]


def _label_for(min_hours: int, max_hours: int) -> str:
    if min_hours == 0:
        return f"Last {max_hours} hours"
    return f"{min_hours}–{max_hours} hours ago"


def empty_buckets() -> list[Bucket]:
    """The 12 fixed 2-hour buckets, in chronological age order, all empty.

    Exposed separately so the bucket *shape* (keys, labels, boundaries) is
    deterministic and testable independent of any actual data.
    """
    return [
        Bucket(key=f"{lo}-{hi}", label=_label_for(lo, hi), min_hours=lo, max_hours=hi)
        for lo, hi in _bucket_boundaries()
    ]


def bucket_for_age(age_hours: float, buckets: list[Bucket]) -> Bucket | None:
    """Which of the 12 fixed buckets `age_hours` falls into, or `None` if
    it's 24h or older (the caller routes that to the "older" bucket).

    Explicit half-open ranges — `min_hours <= age < max_hours` — are what
    guarantee a job lands in exactly one bucket, with no double-counting
    at the boundaries themselves (a job at exactly 2h0m0s goes to 2-4, not
    0-2; a job at exactly 24h0m0s goes to "older", not 22-24).
    """
    for bucket in buckets:
        if bucket.min_hours <= age_hours < bucket.max_hours:
            return bucket
    return None


def build_recent_timeline(
    connection,
    profile_id: str,
    min_score: int = DEFAULT_MIN_SCORE,
    now: datetime | None = None,
    older_limit: int = DEFAULT_OLDER_LIMIT,
    older_offset: int = 0,
    limit: int = 5000,
) -> RecentTimeline:
    """Bucket every non-filtered scored job at or above `min_score`.

    Only reuses existing, already-ranked data: `database.list_matches`
    (same `filtered = 0` rule, same score-then-freshness ordering every
    other view uses) — this function filters into buckets, it never
    recomputes a score or invents a new sort order.
    """
    now = now or database.utcnow()
    rows = database.list_matches(connection, profile_id, min_score=min_score, limit=limit)

    buckets = empty_buckets()
    older_jobs: list[RecentJob] = []

    for row in rows:
        first_seen_at = datetime.fromisoformat(row["first_seen_at"])
        age_hours = (now - first_seen_at).total_seconds() / 3600.0
        recent_job = RecentJob(job=job_card_from_row(row, "new"), first_seen_at=first_seen_at)

        bucket = bucket_for_age(age_hours, buckets)
        if bucket is not None:
            bucket.jobs.append(recent_job)
        else:
            older_jobs.append(recent_job)

    older_total_count = len(older_jobs)
    older_page = older_jobs[older_offset : older_offset + older_limit]
    older = Bucket(key=OLDER_KEY, label=OLDER_LABEL, min_hours=WINDOW_HOURS, max_hours=None, jobs=older_page)

    return RecentTimeline(
        generated_at=now,
        buckets=buckets,
        older=older,
        older_total_count=older_total_count,
    )
