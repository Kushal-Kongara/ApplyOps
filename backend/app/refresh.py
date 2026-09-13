"""One complete refresh cycle: collect every configured source, persist,
run matching, and produce a structured, testable result.

This is deliberately thin — it calls `cli.scan_sources` (collection +
upsert + deactivation, exactly what `python -m app.cli scan` already runs
and already tests) and `cli.match_jobs` (scoring + persistence, exactly
what `python -m app.cli match` already runs) in sequence. No collector or
matching logic is duplicated here; this module only orchestrates the two
existing steps and turns their results into refresh-level statistics.

"Genuinely new job" vs "job seen again" is computed by snapshotting the
set of job keys already in the database *before* collection and again
*after* — the difference is exactly what was inserted this cycle. This
doesn't change `_upsert_jobs`'s own counting (still the source of truth
for `jobs_new`/`jobs_updated` totals); it's only used to know *which*
specific jobs are new, so their post-matching score can be attributed to
"new 70+"/"new 65-69" rather than to jobs that were merely rescored.
"""

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path

import httpx

from app import cli, database
from app.applications import HIGH_PRIORITY_MIN_SCORE, REVIEW_MIN_SCORE
from app.config import SourceConfig, load_sources
from app.profile import Profile, load_profile

DEFAULT_LOCK_PATH = Path("data/.refresh.lock")


class RefreshAlreadyRunningError(RuntimeError):
    """Raised when a refresh is requested while another is still in progress."""


@contextmanager
def _refresh_lock(lock_path: Path = DEFAULT_LOCK_PATH):
    """An OS-level advisory lock (`flock`) — not a lock-file-age heuristic.

    `flock` ties the lock to the *open file description*, not to a
    timestamp: the kernel releases it automatically the instant the
    holding process's file descriptor is closed, which happens on any
    exit path — normal return, an uncaught exception, or a crash/kill.
    There is therefore no "stale lock" state to reclaim and no time
    window during which a legitimate long-running refresh becomes
    vulnerable to a second one starting: a refresh that runs for five
    minutes or five hours holds the lock exactly as long as it's actually
    still running, never longer and never less.

    `LOCK_NB` makes the acquisition attempt non-blocking: a second caller
    gets `OSError` immediately rather than queueing behind the first, so
    two refreshes never run concurrently against the same SQLite file —
    the second one fails fast with a clear message instead.

    POSIX-only (`fcntl`); this is a local, single-machine tool that already
    assumes a Mac/Linux-like environment (see the scheduler's own "if the
    Mac sleeps" note), so that's an acceptable, explicit constraint rather
    than a portability regression.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock_file.close()
        raise RefreshAlreadyRunningError(
            f"A refresh is already running against this database (lock held on {lock_path}). "
            "Wait for it to finish, or check for a stuck process, before retrying."
        ) from exc

    # Diagnostic only — correctness never depends on reading this back;
    # the lock itself is the `flock`, not this file's contents or age.
    lock_file.write(str(os.getpid()))
    lock_file.flush()

    try:
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    """One configured source's result within a refresh — a smaller view of
    `cli.SourceResult`, kept separate so this module doesn't need to import
    the CLI's printing-oriented dataclass as its own public contract."""

    company: str
    source: str
    fetched: int
    inserted: int
    updated: int
    deactivated: int
    failed: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class RefreshResult:
    profile_id: str
    started_at: datetime
    finished_at: datetime
    status: str  # "success" | "partial" | "failed"
    sources: list[SourceOutcome] = field(default_factory=list)
    jobs_fetched: int = 0
    jobs_new: int = 0
    jobs_updated: int = 0
    jobs_deactivated: int = 0
    jobs_scored: int = 0
    jobs_filtered: int = 0
    high_priority_new: int = 0
    review_new: int = 0
    error_message: str | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def sources_attempted(self) -> int:
        return len(self.sources)

    @property
    def sources_succeeded(self) -> int:
        return sum(1 for s in self.sources if not s.failed)

    @property
    def sources_failed(self) -> int:
        return sum(1 for s in self.sources if s.failed)


def run_refresh(
    connection,
    sources: list[SourceConfig],
    profile: Profile,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> RefreshResult:
    """Run one complete refresh cycle against an already-open connection.

    Collection failures on individual sources are recorded, not raised —
    the same "one source must not stop the rest" behavior `scan_sources`
    already has. This function itself never swallows an unexpected error
    from the matching step; that would mean the run's own statistics can't
    be trusted, so it's allowed to propagate.
    """
    started_at = now or database.utcnow()
    quiet = StringIO()  # this module reports structured results, not prose

    keys_before = database.list_job_unique_keys(connection)

    source_results = cli.scan_sources(connection, sources, client=client, out=quiet)

    sources_outcomes = [
        SourceOutcome(
            company=r.company,
            source=r.source,
            fetched=r.fetched,
            inserted=r.inserted,
            updated=r.updated,
            deactivated=r.deactivated,
            failed=r.failed,
            error=r.error,
        )
        for r in source_results
    ]

    keys_after_collection = database.list_job_unique_keys(connection)
    new_keys = keys_after_collection - keys_before

    match_summary = cli.match_jobs(connection, profile, out=quiet)

    high_priority_new = 0
    review_new = 0
    for key in new_keys:
        match_row = database.get_match(connection, key, profile.profile_id)
        if match_row is None or match_row["filtered"]:
            continue
        score = match_row["total_score"]
        if score >= HIGH_PRIORITY_MIN_SCORE:
            high_priority_new += 1
        elif score >= REVIEW_MIN_SCORE:
            review_new += 1

    if sources_outcomes and all(s.failed for s in sources_outcomes):
        status = "failed"
    elif any(s.failed for s in sources_outcomes):
        status = "partial"
    else:
        status = "success"

    error_message = (
        "; ".join(f"{s.company}/{s.source}: {s.error}" for s in sources_outcomes if s.failed) or None
    )

    return RefreshResult(
        profile_id=profile.profile_id,
        started_at=started_at,
        finished_at=database.utcnow(),
        status=status,
        sources=sources_outcomes,
        jobs_fetched=sum(s.fetched for s in sources_outcomes),
        jobs_new=sum(s.inserted for s in sources_outcomes),
        jobs_updated=sum(s.updated for s in sources_outcomes),
        jobs_deactivated=sum(s.deactivated for s in sources_outcomes),
        jobs_scored=match_summary.scored,
        jobs_filtered=match_summary.filtered,
        high_priority_new=high_priority_new,
        review_new=review_new,
        error_message=error_message,
    )


def record_refresh_run(connection, result: RefreshResult) -> int:
    """Persist one `RefreshResult` to the `refresh_runs` table."""
    run_id = database.start_refresh_run(connection, result.profile_id, started_at=result.started_at)
    database.finish_refresh_run(
        connection,
        run_id,
        status=result.status,
        sources_attempted=result.sources_attempted,
        sources_succeeded=result.sources_succeeded,
        sources_failed=result.sources_failed,
        jobs_fetched=result.jobs_fetched,
        jobs_new=result.jobs_new,
        jobs_updated=result.jobs_updated,
        jobs_deactivated=result.jobs_deactivated,
        jobs_scored=result.jobs_scored,
        jobs_filtered=result.jobs_filtered,
        high_priority_new=result.high_priority_new,
        review_new=result.review_new,
        error_message=result.error_message,
        finished_at=result.finished_at,
    )
    return run_id


def refresh_from_files(
    db_path=database.DEFAULT_DB_PATH,
    sources_path: str = "config/sources.json",
    profile_path: str = "config/profile.json",
    client: httpx.Client | None = None,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> RefreshResult:
    """One full refresh cycle from disk config — what both the CLI's
    `refresh` command and the scheduler call. Raises `ConfigError`/
    `ProfileError` if the config files are invalid, and
    `RefreshAlreadyRunningError` if another refresh is already in flight.
    """
    sources = load_sources(sources_path)
    profile = load_profile(profile_path)

    with _refresh_lock(lock_path):
        connection = database.connect(db_path)
        try:
            result = run_refresh(connection, sources, profile, client=client)
            record_refresh_run(connection, result)
        finally:
            connection.close()

    return result
