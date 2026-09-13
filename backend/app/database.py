"""SQLite storage for collected jobs and scan history.

Phase 1 uses the standard library `sqlite3` module directly: the schema is
small, the queries are few, and an ORM would hide the upsert and
deactivation behaviour that makes de-duplication work.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import Job, utcnow

DEFAULT_DB_PATH = Path("data/applyops.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_key         TEXT    NOT NULL UNIQUE,
    external_id        TEXT    NOT NULL,
    source             TEXT    NOT NULL,
    source_identifier  TEXT    NOT NULL,
    company            TEXT    NOT NULL,
    title              TEXT    NOT NULL,
    location           TEXT    NOT NULL DEFAULT '',
    description        TEXT    NOT NULL DEFAULT '',
    application_url    TEXT    NOT NULL DEFAULT '',
    posted_at          TEXT,
    source_updated_at  TEXT,
    first_seen_at      TEXT    NOT NULL,
    last_seen_at       TEXT    NOT NULL,
    is_active          INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_jobs_source_company ON jobs (source, company);
CREATE INDEX IF NOT EXISTS idx_jobs_source_identifier ON jobs (source, source_identifier);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen_at ON jobs (first_seen_at);

CREATE TABLE IF NOT EXISTS scan_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT    NOT NULL,
    company           TEXT    NOT NULL,
    started_at        TEXT    NOT NULL,
    finished_at       TEXT,
    fetched_count     INTEGER NOT NULL DEFAULT 0,
    inserted_count    INTEGER NOT NULL DEFAULT 0,
    updated_count     INTEGER NOT NULL DEFAULT 0,
    deactivated_count INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL,
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_runs_started_at ON scan_runs (started_at);

CREATE TABLE IF NOT EXISTS job_matches (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    job_unique_key     TEXT    NOT NULL,
    profile_id         TEXT    NOT NULL,
    total_score        INTEGER NOT NULL,
    title_score        INTEGER NOT NULL,
    skills_score       INTEGER NOT NULL,
    location_score     INTEGER NOT NULL,
    seniority_score    INTEGER NOT NULL,
    product_score      INTEGER NOT NULL,
    matched_skills     TEXT    NOT NULL DEFAULT '[]',
    unmatched_skills   TEXT    NOT NULL DEFAULT '[]',
    skill_evidence     TEXT    NOT NULL DEFAULT '[]',
    title_evidence     TEXT    NOT NULL DEFAULT '',
    location_evidence  TEXT    NOT NULL DEFAULT '',
    seniority_evidence TEXT    NOT NULL DEFAULT '',
    product_evidence   TEXT    NOT NULL DEFAULT '[]',
    visa_signal        TEXT    NOT NULL DEFAULT 'unknown',
    visa_evidence      TEXT,
    filtered           INTEGER NOT NULL DEFAULT 0,
    filter_reason      TEXT,
    scored_at          TEXT    NOT NULL,
    UNIQUE (job_unique_key, profile_id),
    FOREIGN KEY (job_unique_key) REFERENCES jobs (unique_key)
);

CREATE INDEX IF NOT EXISTS idx_job_matches_profile_score ON job_matches (profile_id, total_score DESC);
"""

_JOB_COLUMNS = (
    "unique_key, external_id, source, source_identifier, company, title, location, "
    "description, application_url, posted_at, source_updated_at, first_seen_at, "
    "last_seen_at, is_active"
)


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (and create if needed) the SQLite database with the schema applied."""
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    """Create every table and index this phase needs. Safe to call repeatedly."""
    connection.executescript(SCHEMA)
    connection.commit()


def _upsert_jobs(connection: sqlite3.Connection, jobs: Iterable[Job]) -> tuple[int, int]:
    """Insert new jobs and refresh existing ones. Does not commit.

    Returns `(inserted, updated)`. An existing job keeps its original
    `first_seen_at`; everything else, including `last_seen_at` and
    `is_active` (so a job seen again is reactivated), is refreshed.
    """
    inserted = 0
    updated = 0

    for job in jobs:
        row = connection.execute(
            "SELECT id FROM jobs WHERE unique_key = ?", (job.unique_key,)
        ).fetchone()

        if row is None:
            connection.execute(
                f"INSERT INTO jobs ({_JOB_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.unique_key,
                    job.external_id,
                    job.source,
                    job.source_identifier,
                    job.company,
                    job.title,
                    job.location,
                    job.description,
                    job.application_url,
                    _to_iso(job.posted_at),
                    _to_iso(job.source_updated_at),
                    _to_iso(job.first_seen_at),
                    _to_iso(job.last_seen_at),
                    int(job.is_active),
                ),
            )
            inserted += 1
        else:
            connection.execute(
                """
                UPDATE jobs
                   SET company = ?,
                       title = ?,
                       location = ?,
                       description = ?,
                       application_url = ?,
                       posted_at = ?,
                       source_updated_at = ?,
                       last_seen_at = ?,
                       is_active = ?
                 WHERE unique_key = ?
                """,
                (
                    job.company,
                    job.title,
                    job.location,
                    job.description,
                    job.application_url,
                    _to_iso(job.posted_at),
                    _to_iso(job.source_updated_at),
                    _to_iso(job.last_seen_at),
                    int(job.is_active),
                    job.unique_key,
                ),
            )
            updated += 1

    return inserted, updated


def upsert_jobs(connection: sqlite3.Connection, jobs: Iterable[Job]) -> tuple[int, int]:
    """Insert new jobs and refresh existing ones, committing immediately.

    See `_upsert_jobs` for the update semantics. Kept as a standalone,
    self-committing entry point for direct use and unit testing; a full scan
    should go through `apply_scan_results` instead so upserts and
    deactivation land in one transaction.
    """
    inserted, updated = _upsert_jobs(connection, jobs)
    connection.commit()
    return inserted, updated


def _deactivate_missing_jobs(
    connection: sqlite3.Connection,
    source: str,
    source_identifier: str,
    seen_unique_keys: list[str],
) -> int:
    """Mark previously active jobs for one source+board absent this scan.

    Only rows matching the given `source` and `source_identifier` (both
    normalized the same way `Job.unique_key` normalizes them) are touched —
    other boards, and other companies configured under a different
    identifier, are unaffected. Rows are never deleted, so history and
    `first_seen_at` survive. Does not commit.
    """
    normalized_source = source.strip().lower()
    normalized_identifier = source_identifier.strip().lower()

    if seen_unique_keys:
        placeholders = ",".join("?" for _ in seen_unique_keys)
        cursor = connection.execute(
            f"""
            UPDATE jobs
               SET is_active = 0
             WHERE lower(source) = ?
               AND lower(source_identifier) = ?
               AND is_active = 1
               AND unique_key NOT IN ({placeholders})
            """,
            (normalized_source, normalized_identifier, *seen_unique_keys),
        )
    else:
        # Nothing was fetched this scan, so every previously active job for
        # this source+board is now missing.
        cursor = connection.execute(
            """
            UPDATE jobs
               SET is_active = 0
             WHERE lower(source) = ?
               AND lower(source_identifier) = ?
               AND is_active = 1
            """,
            (normalized_source, normalized_identifier),
        )

    return cursor.rowcount


def deactivate_missing_jobs(
    connection: sqlite3.Connection,
    source: str,
    source_identifier: str,
    seen_unique_keys: list[str],
) -> int:
    """Standalone, self-committing wrapper around `_deactivate_missing_jobs`."""
    count = _deactivate_missing_jobs(connection, source, source_identifier, seen_unique_keys)
    connection.commit()
    return count


def apply_scan_results(
    connection: sqlite3.Connection,
    jobs: list[Job],
    source: str,
    source_identifier: str,
) -> tuple[int, int, int]:
    """Store one successful scan's jobs and deactivate what went missing.

    Upserts and deactivation happen in a single transaction: either both
    land or neither does. Call this only after a source scan has fully
    succeeded — never on a failed fetch/parse, so a transient HTTP or
    normalization error can't wipe out jobs that are actually still live.

    Returns `(inserted, updated, deactivated)`.
    """
    seen_unique_keys = [job.unique_key for job in jobs]

    try:
        inserted, updated = _upsert_jobs(connection, jobs)
        deactivated = _deactivate_missing_jobs(connection, source, source_identifier, seen_unique_keys)
    except Exception:
        connection.rollback()
        raise

    connection.commit()
    return inserted, updated, deactivated


def start_scan_run(
    connection: sqlite3.Connection,
    source: str,
    company: str,
    started_at: datetime | None = None,
) -> int:
    """Record the beginning of one source scan and return its scan id."""
    cursor = connection.execute(
        """
        INSERT INTO scan_runs (source, company, started_at, status)
        VALUES (?, ?, ?, 'running')
        """,
        (source, company, _to_iso(started_at or utcnow())),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_scan_run(
    connection: sqlite3.Connection,
    scan_id: int,
    status: str,
    fetched: int = 0,
    inserted: int = 0,
    updated: int = 0,
    deactivated: int = 0,
    error_message: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Record the outcome of one source scan."""
    connection.execute(
        """
        UPDATE scan_runs
           SET finished_at = ?,
               fetched_count = ?,
               inserted_count = ?,
               updated_count = ?,
               deactivated_count = ?,
               status = ?,
               error_message = ?
         WHERE id = ?
        """,
        (
            _to_iso(finished_at or utcnow()),
            fetched,
            inserted,
            updated,
            deactivated,
            status,
            error_message,
            scan_id,
        ),
    )
    connection.commit()


def get_job(connection: sqlite3.Connection, unique_key: str) -> sqlite3.Row | None:
    """Return a single stored job row by its unique key."""
    return connection.execute(
        f"SELECT id, {_JOB_COLUMNS} FROM jobs WHERE unique_key = ?", (unique_key,)
    ).fetchone()


def list_jobs(
    connection: sqlite3.Connection,
    limit: int = 50,
    active_only: bool = True,
) -> list[sqlite3.Row]:
    """Return stored jobs, newest discovery first."""
    where = "WHERE is_active = 1" if active_only else ""
    return connection.execute(
        f"""
        SELECT id, {_JOB_COLUMNS}
          FROM jobs
          {where}
         ORDER BY first_seen_at DESC, id DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()


def list_scan_runs(connection: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Return the most recent scan runs, newest first."""
    return connection.execute(
        "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def row_to_job(row: sqlite3.Row) -> Job:
    """Reconstruct a `Job` from a `jobs` table row (the inverse of storing one)."""
    return Job(
        external_id=row["external_id"],
        source=row["source"],
        source_identifier=row["source_identifier"],
        company=row["company"],
        title=row["title"],
        location=row["location"],
        description=row["description"],
        application_url=row["application_url"],
        posted_at=_from_iso(row["posted_at"]),
        source_updated_at=_from_iso(row["source_updated_at"]),
        first_seen_at=_from_iso(row["first_seen_at"]),
        last_seen_at=_from_iso(row["last_seen_at"]),
        is_active=bool(row["is_active"]),
    )


def get_active_jobs(connection: sqlite3.Connection) -> list[Job]:
    """Return every active job, as `Job` objects, for match scoring.

    Unlike `list_jobs` (a display helper with a default page size), this is
    the full working set a scan should score — no limit.
    """
    rows = connection.execute(
        f"SELECT {_JOB_COLUMNS} FROM jobs WHERE is_active = 1"
    ).fetchall()
    return [row_to_job(row) for row in rows]


# --- job_matches ------------------------------------------------------------
#
# One row per (job, profile) pair. Filtering and scoring are both stored for
# every scored job, even a filtered one — the point is to see *why* a job
# scored or was excluded, not to hide the ones that were.

_MATCH_COLUMNS = (
    "job_unique_key, profile_id, total_score, title_score, skills_score, "
    "location_score, seniority_score, product_score, matched_skills, "
    "unmatched_skills, skill_evidence, title_evidence, location_evidence, "
    "seniority_evidence, product_evidence, visa_signal, visa_evidence, "
    "filtered, filter_reason, scored_at"
)


def upsert_match(
    connection: sqlite3.Connection,
    *,
    job_unique_key: str,
    profile_id: str,
    total_score: int,
    title_score: int,
    skills_score: int,
    location_score: int,
    seniority_score: int,
    product_score: int,
    matched_skills: list[str],
    unmatched_skills: list[str],
    skill_evidence: list[str],
    title_evidence: str,
    location_evidence: str,
    seniority_evidence: str,
    product_evidence: list[str],
    visa_signal: str,
    visa_evidence: str | None,
    filtered: bool,
    filter_reason: str | None,
    scored_at: datetime,
) -> bool:
    """Insert or refresh one job's score for one profile. Commits immediately.

    Returns `True` if this created a new row, `False` if it updated an
    existing one — the `UNIQUE (job_unique_key, profile_id)` constraint is
    what makes rescoring update in place instead of piling up duplicates.
    """
    row = connection.execute(
        "SELECT id FROM job_matches WHERE job_unique_key = ? AND profile_id = ?",
        (job_unique_key, profile_id),
    ).fetchone()

    values = (
        total_score,
        title_score,
        skills_score,
        location_score,
        seniority_score,
        product_score,
        json.dumps(matched_skills),
        json.dumps(unmatched_skills),
        json.dumps(skill_evidence),
        title_evidence,
        location_evidence,
        seniority_evidence,
        json.dumps(product_evidence),
        visa_signal,
        visa_evidence,
        int(filtered),
        filter_reason,
        _to_iso(scored_at),
    )

    if row is None:
        connection.execute(
            f"INSERT INTO job_matches ({_MATCH_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_unique_key, profile_id, *values),
        )
        connection.commit()
        return True

    connection.execute(
        """
        UPDATE job_matches
           SET total_score = ?,
               title_score = ?,
               skills_score = ?,
               location_score = ?,
               seniority_score = ?,
               product_score = ?,
               matched_skills = ?,
               unmatched_skills = ?,
               skill_evidence = ?,
               title_evidence = ?,
               location_evidence = ?,
               seniority_evidence = ?,
               product_evidence = ?,
               visa_signal = ?,
               visa_evidence = ?,
               filtered = ?,
               filter_reason = ?,
               scored_at = ?
         WHERE job_unique_key = ? AND profile_id = ?
        """,
        (*values, job_unique_key, profile_id),
    )
    connection.commit()
    return False


def list_matches(
    connection: sqlite3.Connection,
    profile_id: str,
    min_score: int = 0,
    limit: int = 25,
    include_filtered: bool = False,
) -> list[sqlite3.Row]:
    """Return scored jobs for one profile, best/freshest first.

    Joins in the job's own display fields (title, company, location, ...) so
    callers don't need a second query per row.
    """
    filter_clause = "" if include_filtered else "AND jm.filtered = 0"
    return connection.execute(
        f"""
        SELECT jm.*, j.title, j.company, j.location, j.source, j.application_url,
               j.first_seen_at
          FROM job_matches jm
          JOIN jobs j ON j.unique_key = jm.job_unique_key
         WHERE jm.profile_id = ?
           AND jm.total_score >= ?
           {filter_clause}
         ORDER BY jm.total_score DESC, j.first_seen_at DESC
         LIMIT ?
        """,
        (profile_id, min_score, limit),
    ).fetchall()


def get_match(
    connection: sqlite3.Connection, job_unique_key: str, profile_id: str
) -> sqlite3.Row | None:
    """Return one job's full score breakdown for one profile, joined with the job."""
    return connection.execute(
        """
        SELECT jm.*, j.title, j.company, j.location, j.source, j.description,
               j.application_url, j.first_seen_at
          FROM job_matches jm
          JOIN jobs j ON j.unique_key = jm.job_unique_key
         WHERE jm.job_unique_key = ? AND jm.profile_id = ?
        """,
        (job_unique_key, profile_id),
    ).fetchone()


def count_matches(
    connection: sqlite3.Connection, profile_id: str, min_score: int = 0
) -> int:
    """Count non-filtered scored jobs for one profile at or above `min_score`."""
    row = connection.execute(
        """
        SELECT COUNT(*) AS n FROM job_matches
         WHERE profile_id = ? AND filtered = 0 AND total_score >= ?
        """,
        (profile_id, min_score),
    ).fetchone()
    return int(row["n"])


def _to_iso(value: datetime | None) -> str | None:
    """Store datetimes as ISO-8601 UTC strings."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    """Parse a stored ISO-8601 string back into a timezone-aware datetime."""
    if value is None:
        return None
    return datetime.fromisoformat(value)
