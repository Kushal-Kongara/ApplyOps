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

CREATE TABLE IF NOT EXISTS applications (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_unique_key    TEXT    NOT NULL UNIQUE,
    status            TEXT    NOT NULL DEFAULT 'new'
                      CHECK (status IN (
                          'new', 'shortlisted', 'applying', 'applied', 'outreach_sent',
                          'interviewing', 'rejected', 'offer', 'skipped'
                      )),
    applied_at        TEXT,
    last_action_at    TEXT    NOT NULL,
    next_follow_up_at TEXT,
    notes             TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    FOREIGN KEY (job_unique_key) REFERENCES jobs (unique_key)
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications (status);
CREATE INDEX IF NOT EXISTS idx_applications_next_follow_up_at ON applications (next_follow_up_at);

-- One row per full refresh cycle (collect every source + run matching).
-- Deliberately small: counts only, never a serialized job payload — that's
-- what `jobs`/`job_matches`/`scan_runs` already are for.
CREATE TABLE IF NOT EXISTS refresh_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id         TEXT    NOT NULL,
    started_at         TEXT    NOT NULL,
    finished_at        TEXT,
    status             TEXT    NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    sources_attempted  INTEGER NOT NULL DEFAULT 0,
    sources_succeeded  INTEGER NOT NULL DEFAULT 0,
    sources_failed     INTEGER NOT NULL DEFAULT 0,
    jobs_fetched       INTEGER NOT NULL DEFAULT 0,
    jobs_new           INTEGER NOT NULL DEFAULT 0,
    jobs_updated       INTEGER NOT NULL DEFAULT 0,
    jobs_deactivated   INTEGER NOT NULL DEFAULT 0,
    jobs_scored        INTEGER NOT NULL DEFAULT 0,
    jobs_filtered      INTEGER NOT NULL DEFAULT 0,
    high_priority_new  INTEGER NOT NULL DEFAULT 0,
    review_new         INTEGER NOT NULL DEFAULT 0,
    error_message      TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_runs_started_at ON refresh_runs (started_at DESC);

-- One row per generated resume version. `latex_source` is the source of
-- truth served by the API (never a filesystem path) — the on-disk copy
-- under `data/resumes/` exists only so a local LaTeX compiler has a file to
-- read. Regeneration always inserts a new `version`; a row is never
-- overwritten or deleted, so every prior version stays available.
CREATE TABLE IF NOT EXISTS resume_versions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    job_unique_key     TEXT    NOT NULL,
    version            INTEGER NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'approved', 'used')),
    latex_source       TEXT    NOT NULL,
    pdf_path           TEXT,
    compiler_status    TEXT    NOT NULL DEFAULT 'not_attempted'
                       CHECK (compiler_status IN ('not_attempted', 'compiled', 'unavailable', 'failed')),
    compile_log        TEXT,
    page_count         INTEGER,
    tailoring_analysis TEXT    NOT NULL DEFAULT '{}',
    generation_mode    TEXT    NOT NULL DEFAULT 'deterministic'
                       CHECK (generation_mode IN ('deterministic', 'llm_enhanced')),
    llm_provider       TEXT,
    llm_model          TEXT,
    rewrite_attempted  INTEGER NOT NULL DEFAULT 0,
    rewrite_accepted   INTEGER NOT NULL DEFAULT 0,
    rewrite_rejected   INTEGER NOT NULL DEFAULT 0,
    rewrite_provenance TEXT    NOT NULL DEFAULT '[]',
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL,
    approved_at        TEXT,
    UNIQUE (job_unique_key, version),
    FOREIGN KEY (job_unique_key) REFERENCES jobs (unique_key)
);

CREATE INDEX IF NOT EXISTS idx_resume_versions_job ON resume_versions (job_unique_key, version DESC);

-- One row per application-preparation attempt for one job. Deliberately
-- holds only a reference to the resume version used (never a copy of its
-- content) and no copy of the job/JD -- both are already fully available
-- via `job_unique_key`/`resume_version_id`.
CREATE TABLE IF NOT EXISTS application_preparations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_unique_key    TEXT    NOT NULL,
    resume_version_id INTEGER,
    status            TEXT    NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'needs_input', 'ready', 'used')),
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    FOREIGN KEY (job_unique_key) REFERENCES jobs (unique_key),
    FOREIGN KEY (resume_version_id) REFERENCES resume_versions (id)
);

CREATE INDEX IF NOT EXISTS idx_application_preparations_job ON application_preparations (job_unique_key, id DESC);

-- One row per question in a preparation -- both the default standard
-- packet and any manually-added custom question. `user_edited` is set the
-- moment a human edits `answer` directly, and regeneration must never
-- silently overwrite a row with that flag set.
CREATE TABLE IF NOT EXISTS application_answers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    preparation_id   INTEGER NOT NULL,
    question_id      TEXT    NOT NULL DEFAULT '',
    question_text    TEXT    NOT NULL,
    question_type    TEXT    NOT NULL,
    category         TEXT    NOT NULL,
    required         INTEGER NOT NULL DEFAULT 1,
    answer           TEXT,
    answer_source    TEXT    NOT NULL DEFAULT 'user_input_required',
    needs_user_input INTEGER NOT NULL DEFAULT 1,
    evidence_ids     TEXT    NOT NULL DEFAULT '[]',
    user_edited      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    FOREIGN KEY (preparation_id) REFERENCES application_preparations (id)
);

CREATE INDEX IF NOT EXISTS idx_application_answers_preparation ON application_answers (preparation_id, id);
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

    # check_same_thread=False: the API layer (app/api.py) hands each
    # request's connection through FastAPI's sync-endpoint threadpool,
    # where dependency resolution and the route body aren't guaranteed to
    # run on the same worker thread. Each request still gets its own
    # connection (see api.get_connection) and this process handles one
    # request at a time in practice, so this doesn't introduce real
    # concurrent access to a single connection — it just stops sqlite3's
    # same-thread check from rejecting the thread hand-off above.
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    """Create every table and index this phase needs. Safe to call repeatedly."""
    connection.executescript(SCHEMA)
    _migrate_resume_versions_columns(connection)
    connection.commit()


# SQLite's `CREATE TABLE IF NOT EXISTS` above is a no-op against a database
# that already has a `resume_versions` table from before this phase's new
# columns existed (e.g. this project's own real local database, which
# already had rows from the deterministic-only phase). `ALTER TABLE ADD
# COLUMN` is the one additive, non-destructive migration SQLite supports
# without a full migration framework — existing rows backfill with each
# column's default.
_RESUME_VERSION_COLUMN_MIGRATIONS = (
    ("generation_mode", "ALTER TABLE resume_versions ADD COLUMN generation_mode TEXT NOT NULL DEFAULT 'deterministic'"),
    ("llm_provider", "ALTER TABLE resume_versions ADD COLUMN llm_provider TEXT"),
    ("llm_model", "ALTER TABLE resume_versions ADD COLUMN llm_model TEXT"),
    ("rewrite_attempted", "ALTER TABLE resume_versions ADD COLUMN rewrite_attempted INTEGER NOT NULL DEFAULT 0"),
    ("rewrite_accepted", "ALTER TABLE resume_versions ADD COLUMN rewrite_accepted INTEGER NOT NULL DEFAULT 0"),
    ("rewrite_rejected", "ALTER TABLE resume_versions ADD COLUMN rewrite_rejected INTEGER NOT NULL DEFAULT 0"),
    ("rewrite_provenance", "ALTER TABLE resume_versions ADD COLUMN rewrite_provenance TEXT NOT NULL DEFAULT '[]'"),
)


def _migrate_resume_versions_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(resume_versions)").fetchall()}
    for column, ddl in _RESUME_VERSION_COLUMN_MIGRATIONS:
        if column not in existing_columns:
            connection.execute(ddl)


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


def list_job_unique_keys(connection: sqlite3.Connection) -> set[str]:
    """Every job's unique key, active or not.

    Used to tell a genuinely new job apart from one seen again: a caller
    snapshots this before a refresh's collection step and again after —
    the difference is exactly the jobs that were inserted, without
    changing what `apply_scan_results`/`_upsert_jobs` already track.
    """
    rows = connection.execute("SELECT unique_key FROM jobs").fetchall()
    return {row["unique_key"] for row in rows}


def start_refresh_run(
    connection: sqlite3.Connection, profile_id: str, started_at: datetime | None = None
) -> int:
    """Record the beginning of one refresh cycle and return its run id."""
    cursor = connection.execute(
        """
        INSERT INTO refresh_runs (profile_id, started_at, status)
        VALUES (?, ?, 'partial')
        """,
        (profile_id, _to_iso(started_at or utcnow())),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_refresh_run(
    connection: sqlite3.Connection,
    run_id: int,
    status: str,
    sources_attempted: int = 0,
    sources_succeeded: int = 0,
    sources_failed: int = 0,
    jobs_fetched: int = 0,
    jobs_new: int = 0,
    jobs_updated: int = 0,
    jobs_deactivated: int = 0,
    jobs_scored: int = 0,
    jobs_filtered: int = 0,
    high_priority_new: int = 0,
    review_new: int = 0,
    error_message: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Record the outcome of one refresh cycle."""
    connection.execute(
        """
        UPDATE refresh_runs
           SET finished_at = ?,
               status = ?,
               sources_attempted = ?,
               sources_succeeded = ?,
               sources_failed = ?,
               jobs_fetched = ?,
               jobs_new = ?,
               jobs_updated = ?,
               jobs_deactivated = ?,
               jobs_scored = ?,
               jobs_filtered = ?,
               high_priority_new = ?,
               review_new = ?,
               error_message = ?
         WHERE id = ?
        """,
        (
            _to_iso(finished_at or utcnow()),
            status,
            sources_attempted,
            sources_succeeded,
            sources_failed,
            jobs_fetched,
            jobs_new,
            jobs_updated,
            jobs_deactivated,
            jobs_scored,
            jobs_filtered,
            high_priority_new,
            review_new,
            error_message,
            run_id,
        ),
    )
    connection.commit()


def get_latest_refresh_run(connection: sqlite3.Connection, profile_id: str) -> sqlite3.Row | None:
    """The most recently *finished* refresh run for one profile, if any."""
    return connection.execute(
        """
        SELECT * FROM refresh_runs
         WHERE profile_id = ? AND finished_at IS NOT NULL
         ORDER BY id DESC
         LIMIT 1
        """,
        (profile_id,),
    ).fetchone()


def list_refresh_runs(connection: sqlite3.Connection, profile_id: str, limit: int = 20) -> list[sqlite3.Row]:
    """Return the most recent refresh runs for one profile, newest first."""
    return connection.execute(
        "SELECT * FROM refresh_runs WHERE profile_id = ? ORDER BY id DESC LIMIT ?",
        (profile_id, limit),
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
    search: str | None = None,
    status: str | None = None,
) -> list[sqlite3.Row]:
    """Return scored jobs for one profile, best/freshest first.

    Joins in the job's own display fields (title, company, location, ...)
    and the tracked application's status/notes/follow-up date (a job with no
    `applications` row reads as status `'new'`), so callers don't need a
    second query per row. `search` (title/company substring) and `status`
    are optional filters layered on top of the exact same base query and
    ordering the CLI's `list-matches` already used — they narrow the result
    set, they never change how it's ranked.
    """
    filter_clause = "" if include_filtered else "AND jm.filtered = 0"
    extra_clauses = []
    params: list = [profile_id, min_score]

    if search:
        extra_clauses.append("AND (j.title LIKE ? OR j.company LIKE ?)")
        needle = f"%{search}%"
        params += [needle, needle]
    if status:
        extra_clauses.append("AND COALESCE(a.status, 'new') = ?")
        params.append(status)

    params.append(limit)

    return connection.execute(
        f"""
        SELECT jm.*, j.title, j.company, j.location, j.source, j.application_url,
               j.first_seen_at, COALESCE(a.status, 'new') AS status,
               a.next_follow_up_at, a.notes
          FROM job_matches jm
          JOIN jobs j ON j.unique_key = jm.job_unique_key
          LEFT JOIN applications a ON a.job_unique_key = jm.job_unique_key
         WHERE jm.profile_id = ?
           AND jm.total_score >= ?
           {filter_clause}
           {' '.join(extra_clauses)}
         ORDER BY jm.total_score DESC, j.first_seen_at DESC
         LIMIT ?
        """,
        params,
    ).fetchall()


def get_match(
    connection: sqlite3.Connection, job_unique_key: str, profile_id: str
) -> sqlite3.Row | None:
    """Return one job's full score breakdown for one profile, joined with the job."""
    return connection.execute(
        """
        SELECT jm.*, j.title, j.company, j.location, j.source, j.description,
               j.application_url, j.first_seen_at, COALESCE(a.status, 'new') AS status,
               a.next_follow_up_at, a.notes
          FROM job_matches jm
          JOIN jobs j ON j.unique_key = jm.job_unique_key
          LEFT JOIN applications a ON a.job_unique_key = jm.job_unique_key
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


# --- applications -----------------------------------------------------------
#
# One row per job a user has taken any action on — created lazily by the
# first `application-update`, never by `match`. A job with no row here is
# implicitly "new": every query below treats a missing row the same as an
# explicit `status = 'new'`.

_APPLICATION_COLUMNS = (
    "job_unique_key, status, applied_at, last_action_at, next_follow_up_at, "
    "notes, created_at, updated_at"
)

# Sentinel so `upsert_application` can tell "the caller didn't mention this
# field" (leave it alone) apart from "the caller explicitly wants it
# cleared" (`None` is a real, meaningful value for both datetime fields).
_UNSET = object()


def get_application(connection: sqlite3.Connection, job_unique_key: str) -> sqlite3.Row | None:
    """Return one job's application row, or `None` if it's never been touched."""
    return connection.execute(
        f"SELECT {_APPLICATION_COLUMNS} FROM applications WHERE job_unique_key = ?",
        (job_unique_key,),
    ).fetchone()


def upsert_application(
    connection: sqlite3.Connection,
    job_unique_key: str,
    *,
    status: str | None = None,
    applied_at: datetime | None = _UNSET,  # type: ignore[assignment]
    next_follow_up_at: datetime | None = _UNSET,  # type: ignore[assignment]
    notes: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Create or update one job's application record. Never creates a second
    row for the same job — the `UNIQUE (job_unique_key)` constraint plus this
    get-then-branch is the same pattern `upsert_match` uses.

    `status` and `notes`: passing `None` means "leave unchanged" (or default
    on first creation); pass `""` to explicitly clear notes. `applied_at` and
    `next_follow_up_at`: omit the argument to leave unchanged, or pass `None`
    explicitly to clear it — that's what the `_UNSET` sentinel default is for.

    Returns `True` if this created a new row, `False` if it updated one.
    """
    now = now or utcnow()
    existing = get_application(connection, job_unique_key)

    if existing is None:
        final_status = status or "new"
        final_applied_at = None if applied_at is _UNSET else applied_at
        if final_status == "applied" and final_applied_at is None:
            # A first-time "mark as applied" with no explicit date is
            # applying right now — a reasonable default, not a guess.
            final_applied_at = now
        final_follow_up = None if next_follow_up_at is _UNSET else next_follow_up_at

        connection.execute(
            f"INSERT INTO applications ({_APPLICATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_unique_key,
                final_status,
                _to_iso(final_applied_at),
                _to_iso(now),
                _to_iso(final_follow_up),
                notes or "",
                _to_iso(now),
                _to_iso(now),
            ),
        )
        connection.commit()
        return True

    new_status = status if status is not None else existing["status"]

    if applied_at is _UNSET:
        new_applied_at = existing["applied_at"]
        if new_status == "applied" and new_applied_at is None:
            new_applied_at = _to_iso(now)
    else:
        new_applied_at = _to_iso(applied_at)

    new_follow_up = existing["next_follow_up_at"] if next_follow_up_at is _UNSET else _to_iso(next_follow_up_at)
    new_notes = notes if notes is not None else existing["notes"]

    connection.execute(
        """
        UPDATE applications
           SET status = ?,
               applied_at = ?,
               next_follow_up_at = ?,
               notes = ?,
               last_action_at = ?,
               updated_at = ?
         WHERE job_unique_key = ?
        """,
        (new_status, new_applied_at, new_follow_up, new_notes, _to_iso(now), _to_iso(now), job_unique_key),
    )
    connection.commit()
    return False


def list_applications(
    connection: sqlite3.Connection, status: str | None = None, limit: int = 100
) -> list[sqlite3.Row]:
    """Return tracked applications, most recently touched first."""
    where = "WHERE a.status = ?" if status else ""
    params: tuple = (status, limit) if status else (limit,)
    return connection.execute(
        f"""
        SELECT a.*, j.title, j.company, j.location, j.application_url
          FROM applications a
          JOIN jobs j ON j.unique_key = a.job_unique_key
          {where}
         ORDER BY a.updated_at DESC
         LIMIT ?
        """,
        params,
    ).fetchall()


def get_daily_new_candidates(
    connection: sqlite3.Connection,
    profile_id: str,
    min_score: int,
    excluded_statuses: tuple[str, ...],
    limit: int = 200,
) -> list[sqlite3.Row]:
    """Actionable, not-yet-decided jobs at or above `min_score`.

    A job with no `applications` row is treated as status `'new'`. Ordering
    (score, then freshness) matches `list_matches` exactly — this reuses the
    matching system's ranking rather than introducing a new one.
    """
    placeholders = ",".join("?" for _ in excluded_statuses)
    return connection.execute(
        f"""
        SELECT jm.job_unique_key, jm.total_score, jm.title_score, jm.skills_score,
               jm.location_score, jm.seniority_score, jm.product_score,
               jm.visa_signal, jm.visa_evidence, jm.matched_skills,
               j.title, j.company, j.location, j.source, j.application_url,
               j.first_seen_at, COALESCE(a.status, 'new') AS status,
               a.next_follow_up_at, a.notes
          FROM job_matches jm
          JOIN jobs j ON j.unique_key = jm.job_unique_key
          LEFT JOIN applications a ON a.job_unique_key = jm.job_unique_key
         WHERE jm.profile_id = ?
           AND jm.filtered = 0
           AND j.is_active = 1
           AND jm.total_score >= ?
           AND j.application_url != ''
           AND COALESCE(a.status, 'new') NOT IN ({placeholders})
         ORDER BY jm.total_score DESC, j.first_seen_at DESC
         LIMIT ?
        """,
        (profile_id, min_score, *excluded_statuses, limit),
    ).fetchall()


def get_due_follow_ups(
    connection: sqlite3.Connection,
    profile_id: str,
    now: datetime,
    excluded_statuses: tuple[str, ...],
    limit: int = 200,
) -> list[sqlite3.Row]:
    """Tracked applications whose `next_follow_up_at` has arrived.

    Left-joins `job_matches` (rather than requiring it) since a job can be
    tracked without ever having been scored for this profile; its score
    then reads as `NULL`.
    """
    placeholders = ",".join("?" for _ in excluded_statuses)
    return connection.execute(
        f"""
        SELECT a.job_unique_key, a.status, a.next_follow_up_at, a.notes,
               j.title, j.company, j.location, j.source, j.application_url,
               jm.total_score, jm.title_score, jm.skills_score, jm.location_score,
               jm.seniority_score, jm.product_score,
               jm.visa_signal, jm.visa_evidence, jm.matched_skills
          FROM applications a
          JOIN jobs j ON j.unique_key = a.job_unique_key
          LEFT JOIN job_matches jm ON jm.job_unique_key = a.job_unique_key AND jm.profile_id = ?
         WHERE a.next_follow_up_at IS NOT NULL
           AND a.next_follow_up_at <= ?
           AND a.status NOT IN ({placeholders})
         ORDER BY a.next_follow_up_at ASC
         LIMIT ?
        """,
        (profile_id, _to_iso(now), *excluded_statuses, limit),
    ).fetchall()


def list_follow_ups(
    connection: sqlite3.Connection,
    profile_id: str,
    excluded_statuses: tuple[str, ...],
    limit: int = 200,
) -> list[sqlite3.Row]:
    """Every tracked application with a follow-up date set, due or not.

    Same shape as `get_due_follow_ups`, minus the "due" time filter — for a
    Follow-ups page that needs to show upcoming reminders too, not just the
    ones that have already arrived.
    """
    placeholders = ",".join("?" for _ in excluded_statuses)
    return connection.execute(
        f"""
        SELECT a.job_unique_key, a.status, a.next_follow_up_at, a.notes,
               j.title, j.company, j.location, j.source, j.application_url,
               jm.total_score, jm.title_score, jm.skills_score, jm.location_score,
               jm.seniority_score, jm.product_score,
               jm.visa_signal, jm.visa_evidence, jm.matched_skills
          FROM applications a
          JOIN jobs j ON j.unique_key = a.job_unique_key
          LEFT JOIN job_matches jm ON jm.job_unique_key = a.job_unique_key AND jm.profile_id = ?
         WHERE a.next_follow_up_at IS NOT NULL
           AND a.status NOT IN ({placeholders})
         ORDER BY a.next_follow_up_at ASC
         LIMIT ?
        """,
        (profile_id, *excluded_statuses, limit),
    ).fetchall()


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


# --- resume_versions ----------------------------------------------------
#
# One row per generated resume version for one job. Regeneration always
# inserts a new version — nothing here ever updates `latex_source` or
# `pdf_path` on an existing row. Approval is the only mutation: it flips
# `status`/`approved_at` on one row and demotes any other approved row for
# the same job back to `draft`, so at most one version per job is ever
# `approved` at a time.

_RESUME_VERSION_COLUMNS = (
    "job_unique_key, version, status, latex_source, pdf_path, compiler_status, "
    "compile_log, page_count, tailoring_analysis, generation_mode, llm_provider, "
    "llm_model, rewrite_attempted, rewrite_accepted, rewrite_rejected, "
    "rewrite_provenance, created_at, updated_at, approved_at"
)


def next_resume_version(connection: sqlite3.Connection, job_unique_key: str) -> int:
    """The version number the next generation for this job should use."""
    row = connection.execute(
        "SELECT MAX(version) AS max_version FROM resume_versions WHERE job_unique_key = ?",
        (job_unique_key,),
    ).fetchone()
    current = row["max_version"]
    return int(current) + 1 if current is not None else 1


def insert_resume_version(
    connection: sqlite3.Connection,
    *,
    job_unique_key: str,
    version: int,
    latex_source: str,
    pdf_path: str | None,
    compiler_status: str,
    compile_log: str | None,
    page_count: int | None,
    tailoring_analysis: dict,
    generation_mode: str = "deterministic",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    rewrite_attempted: int = 0,
    rewrite_accepted: int = 0,
    rewrite_rejected: int = 0,
    rewrite_provenance: list | None = None,
    now: datetime | None = None,
) -> int:
    """Insert one new resume version. Always an insert — never updates an
    existing row, so regeneration can never clobber a prior version.

    `generation_mode`/`llm_*`/`rewrite_*` all default to plain deterministic
    generation with no LLM involvement — a caller that doesn't pass them
    (every pre-existing call site) gets exactly the old behavior.
    """
    now = now or utcnow()
    cursor = connection.execute(
        f"INSERT INTO resume_versions ({_RESUME_VERSION_COLUMNS}) "
        "VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            job_unique_key,
            version,
            latex_source,
            pdf_path,
            compiler_status,
            compile_log,
            page_count,
            json.dumps(tailoring_analysis),
            generation_mode,
            llm_provider,
            llm_model,
            rewrite_attempted,
            rewrite_accepted,
            rewrite_rejected,
            json.dumps(rewrite_provenance or []),
            _to_iso(now),
            _to_iso(now),
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_resume_version(connection: sqlite3.Connection, resume_id: int) -> sqlite3.Row | None:
    """One resume version by its own id."""
    return connection.execute(
        "SELECT * FROM resume_versions WHERE id = ?", (resume_id,)
    ).fetchone()


def list_resume_versions(connection: sqlite3.Connection, job_unique_key: str) -> list[sqlite3.Row]:
    """Every version generated for one job, newest first. Never filtered —
    old versions stay visible/available, they're just not the approved one."""
    return connection.execute(
        "SELECT * FROM resume_versions WHERE job_unique_key = ? ORDER BY version DESC",
        (job_unique_key,),
    ).fetchall()


def approve_resume_version(
    connection: sqlite3.Connection, resume_id: int, now: datetime | None = None
) -> sqlite3.Row | None:
    """Mark one resume version approved, demoting any other approved
    version of the same job back to `draft`. Returns the updated row, or
    `None` if `resume_id` doesn't exist.

    Approval means only "this is the version I'd use for this job" — it
    never touches `applications.status` or anything else outside this table.
    """
    now = now or utcnow()
    row = get_resume_version(connection, resume_id)
    if row is None:
        return None

    connection.execute(
        """
        UPDATE resume_versions
           SET status = 'draft', updated_at = ?
         WHERE job_unique_key = ? AND status = 'approved' AND id != ?
        """,
        (_to_iso(now), row["job_unique_key"], resume_id),
    )
    connection.execute(
        """
        UPDATE resume_versions
           SET status = 'approved', approved_at = ?, updated_at = ?
         WHERE id = ?
        """,
        (_to_iso(now), _to_iso(now), resume_id),
    )
    connection.commit()
    return get_resume_version(connection, resume_id)


def update_resume_version_compilation(
    connection: sqlite3.Connection,
    resume_id: int,
    *,
    compiler_status: str,
    pdf_path: str | None,
    compile_log: str | None,
    page_count: int | None,
    now: datetime | None = None,
) -> sqlite3.Row | None:
    """Recompile an *existing* version's already-stored `latex_source` and
    update only its compile metadata -- never its `version`, `status`, or
    `approved_at`. For fixing a version that was generated before a local
    compiler was available, without forcing a re-approval of a new version.
    """
    now = now or utcnow()
    if get_resume_version(connection, resume_id) is None:
        return None

    connection.execute(
        """
        UPDATE resume_versions
           SET compiler_status = ?, pdf_path = ?, compile_log = ?, page_count = ?, updated_at = ?
         WHERE id = ?
        """,
        (compiler_status, pdf_path, compile_log, page_count, _to_iso(now), resume_id),
    )
    connection.commit()
    return get_resume_version(connection, resume_id)


# --- application_preparations / application_answers --------------------
#
# One preparation per job attempt; one answer row per question in it (the
# default standard packet plus any manually-added custom question). No
# copy of the job/JD/resume content lives here -- only references
# (`job_unique_key`, `resume_version_id`).

_UNSET_ANSWER = object()


def create_application_preparation(
    connection: sqlite3.Connection,
    job_unique_key: str,
    resume_version_id: int | None = None,
    status: str = "draft",
    now: datetime | None = None,
) -> int:
    now = now or utcnow()
    cursor = connection.execute(
        """
        INSERT INTO application_preparations (job_unique_key, resume_version_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_unique_key, resume_version_id, status, _to_iso(now), _to_iso(now)),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_application_preparation(connection: sqlite3.Connection, preparation_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM application_preparations WHERE id = ?", (preparation_id,)
    ).fetchone()


def list_application_preparations(connection: sqlite3.Connection, job_unique_key: str) -> list[sqlite3.Row]:
    """Every preparation attempt for one job, newest first. Never filtered
    out -- a prior attempt stays visible even after a newer one exists."""
    return connection.execute(
        "SELECT * FROM application_preparations WHERE job_unique_key = ? ORDER BY id DESC",
        (job_unique_key,),
    ).fetchall()


def update_application_preparation(
    connection: sqlite3.Connection,
    preparation_id: int,
    *,
    status: str | None = None,
    resume_version_id: int | object = _UNSET_ANSWER,
    now: datetime | None = None,
) -> sqlite3.Row | None:
    """Update only the fields actually passed -- `status` and
    `resume_version_id` both default to "leave unchanged"."""
    existing = get_application_preparation(connection, preparation_id)
    if existing is None:
        return None

    now = now or utcnow()
    new_status = status if status is not None else existing["status"]
    new_resume_version_id = existing["resume_version_id"] if resume_version_id is _UNSET_ANSWER else resume_version_id

    connection.execute(
        """
        UPDATE application_preparations
           SET status = ?, resume_version_id = ?, updated_at = ?
         WHERE id = ?
        """,
        (new_status, new_resume_version_id, _to_iso(now), preparation_id),
    )
    connection.commit()
    return get_application_preparation(connection, preparation_id)


def insert_application_answer(
    connection: sqlite3.Connection,
    *,
    preparation_id: int,
    question_id: str,
    question_text: str,
    question_type: str,
    category: str,
    required: bool,
    answer: str | None,
    answer_source: str,
    needs_user_input: bool,
    evidence_ids: list[str],
    user_edited: bool = False,
    now: datetime | None = None,
) -> int:
    now = now or utcnow()
    cursor = connection.execute(
        """
        INSERT INTO application_answers (
            preparation_id, question_id, question_text, question_type, category, required,
            answer, answer_source, needs_user_input, evidence_ids, user_edited, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            preparation_id, question_id, question_text, question_type, category, int(required),
            answer, answer_source, int(needs_user_input), json.dumps(evidence_ids), int(user_edited),
            _to_iso(now), _to_iso(now),
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_application_answer(connection: sqlite3.Connection, answer_id: int) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM application_answers WHERE id = ?", (answer_id,)).fetchone()


def list_application_answers(connection: sqlite3.Connection, preparation_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM application_answers WHERE preparation_id = ? ORDER BY id", (preparation_id,)
    ).fetchall()


def update_application_answer(
    connection: sqlite3.Connection,
    answer_id: int,
    *,
    answer: str | object = _UNSET_ANSWER,
    answer_source: str | None = None,
    needs_user_input: bool | None = None,
    evidence_ids: list[str] | None = None,
    user_edited: bool | None = None,
    now: datetime | None = None,
) -> sqlite3.Row | None:
    """Update only the fields actually passed. A human edit should call
    this with `answer=...` and `user_edited=True`; regeneration should
    check `user_edited` first and skip any row where it's already set."""
    existing = get_application_answer(connection, answer_id)
    if existing is None:
        return None

    now = now or utcnow()
    new_answer = existing["answer"] if answer is _UNSET_ANSWER else answer
    new_source = answer_source if answer_source is not None else existing["answer_source"]
    new_needs_input = int(needs_user_input) if needs_user_input is not None else existing["needs_user_input"]
    new_evidence_ids = json.dumps(evidence_ids) if evidence_ids is not None else existing["evidence_ids"]
    new_user_edited = int(user_edited) if user_edited is not None else existing["user_edited"]

    connection.execute(
        """
        UPDATE application_answers
           SET answer = ?, answer_source = ?, needs_user_input = ?, evidence_ids = ?, user_edited = ?, updated_at = ?
         WHERE id = ?
        """,
        (new_answer, new_source, new_needs_input, new_evidence_ids, new_user_edited, _to_iso(now), answer_id),
    )
    connection.commit()
    return get_application_answer(connection, answer_id)
