"""HTTP API for the local dashboard.

This is a thin wrapper: every endpoint calls straight into
`app.database`/`app.applications`/`app.profile` — the exact same functions
the CLI uses. No ranking, filtering, or status logic is duplicated here;
this module only shapes existing data into JSON and validates request
input using the existing `ApplicationError`-raising helpers.

Run it with:

    cd backend
    uvicorn app.api:app --reload --port 8000
"""

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app import applications, database, recent
from app.applications import ApplicationError, parse_datetime_arg, validate_status
from app.profile import Profile, ProfileError, load_profile
from app.resume import service as resume_service
from app.resume.master import DEFAULT_MASTER_RESUME_PATH, MasterResumeError
from app.resume.storage import DEFAULT_RESUMES_ROOT

# Same configuration story as the CLI (`--db`/`--profile` flags), just
# expressed as env vars since a long-running server isn't invoked per
# command. Defaults match the CLI's own defaults exactly.
DB_PATH = Path(os.environ.get("APPLYOPS_DB_PATH", str(database.DEFAULT_DB_PATH)))
PROFILE_PATH = Path(os.environ.get("APPLYOPS_PROFILE_PATH", "config/profile.json"))
MASTER_RESUME_PATH = Path(os.environ.get("APPLYOPS_MASTER_RESUME_PATH", str(DEFAULT_MASTER_RESUME_PATH)))
RESUMES_ROOT = Path(os.environ.get("APPLYOPS_RESUMES_ROOT", str(DEFAULT_RESUMES_ROOT)))

# Vite's default dev server ports. This is a local, single-user tool with
# no auth of its own — CORS is opened only to these known local origins,
# never broadly, and only GET/PATCH (the only methods this API exposes).
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(title="ApplyOps API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_methods=["GET", "PATCH", "POST"],
    allow_headers=["*"],
)


def get_connection() -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request — this tool is single-user/local,
    so a connection-per-request is simple and plenty fast."""
    connection = database.connect(DB_PATH)
    try:
        yield connection
    finally:
        connection.close()


def get_profile() -> Profile:
    try:
        return load_profile(PROFILE_PATH)
    except ProfileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- response/request shapes -------------------------------------------------
#
# One `JobCard` shape is reused for every endpoint that returns a scored
# job — dashboard sections, the jobs list, a single job, and follow-ups —
# because `app.applications.job_card_from_row` already produces exactly
# this shape for all of them.


class JobCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_unique_key: str
    kind: str
    title: str
    company: str
    location: str
    source: str | None
    application_url: str
    status: str
    total_score: int | None
    title_score: int | None
    skills_score: int | None
    location_score: int | None
    seniority_score: int | None
    product_score: int | None
    visa_signal: str | None
    visa_evidence: str | None
    matched_skills: list[str]
    next_follow_up_at: datetime | None
    notes: str | None


class DashboardSummary(BaseModel):
    high_priority: int
    review: int
    follow_ups_due: int
    applications_total: int


class RefreshSummary(BaseModel):
    """Compact refresh metadata for the dashboard's "last refreshed" indicator.

    Sourced from `refresh_runs` (see `app/refresh.py`) — never recomputed.
    """

    started_at: datetime
    finished_at: datetime
    status: str
    jobs_new: int
    jobs_updated: int
    high_priority_new: int
    review_new: int
    error_message: str | None


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    high_priority: list[JobCard]
    review_candidates: list[JobCard]
    follow_ups: list[JobCard]
    last_refresh: RefreshSummary | None


class FollowUpsResponse(BaseModel):
    due: list[JobCard]
    upcoming: list[JobCard]


class RecentJobCard(JobCard):
    """A `JobCard` plus when it was discovered — only the Recent timeline
    needs this, so it isn't on the shared `JobCard` every other view uses."""

    first_seen_at: datetime


class RecentBucket(BaseModel):
    key: str
    label: str
    min_hours: int
    max_hours: int | None
    count: int
    jobs: list[RecentJobCard]


class RecentSummary(BaseModel):
    last_24h: int
    high_priority: int
    review: int
    older_than_24h: int


class RecentResponse(BaseModel):
    generated_at: datetime
    summary: RecentSummary
    buckets: list[RecentBucket]
    older: RecentBucket


class ApplicationRecord(BaseModel):
    job_unique_key: str
    title: str
    company: str
    location: str
    application_url: str
    status: str
    applied_at: datetime | None
    last_action_at: datetime
    next_follow_up_at: datetime | None
    notes: str
    created_at: datetime
    updated_at: datetime


class JobDetailResponse(JobCard):
    """`JobCard` plus what only the Job Detail page needs — the full stored
    job description (never re-scraped from the ATS) and the skills the
    match found no evidence for."""

    description: str
    unmatched_skills: list[str]


class TailoringAnalysisResponse(BaseModel):
    strong_matches: list[str]
    supported_but_underemphasized: list[str]
    unsupported_requirements: list[str]
    selected_experience: list[str]
    selected_projects: list[str]


class ResumeVersionSummary(BaseModel):
    id: int
    job_unique_key: str
    version: int
    status: str
    compiler_status: str
    page_count: int | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class ResumeVersionDetail(ResumeVersionSummary):
    compile_log: str | None
    tailoring_analysis: TailoringAnalysisResponse


class LatexSourceResponse(BaseModel):
    latex_source: str


class ApplicationUpdateRequest(BaseModel):
    """A PATCH body only ever touches the fields it actually includes.

    Omit a field to leave it unchanged; send `next_follow_up_at: null`
    explicitly to clear a scheduled follow-up.
    """

    status: str | None = None
    notes: str | None = None
    next_follow_up_at: str | None = None


# --- endpoints ---------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "applyops-api"}


@app.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(
    connection: sqlite3.Connection = Depends(get_connection),
    profile: Profile = Depends(get_profile),
) -> DashboardResponse:
    """Everything the Today page needs in one request.

    Reuses `build_daily_queue` verbatim — this endpoint never recomputes
    or re-sorts anything the matching/application layers already decided.
    """
    queue = applications.build_daily_queue(connection, profile.profile_id)
    applications_total = len(database.list_applications(connection, limit=100_000))

    refresh_row = database.get_latest_refresh_run(connection, profile.profile_id)
    last_refresh = (
        RefreshSummary(
            started_at=refresh_row["started_at"],
            finished_at=refresh_row["finished_at"],
            status=refresh_row["status"],
            jobs_new=refresh_row["jobs_new"],
            jobs_updated=refresh_row["jobs_updated"],
            high_priority_new=refresh_row["high_priority_new"],
            review_new=refresh_row["review_new"],
            error_message=refresh_row["error_message"],
        )
        if refresh_row is not None
        else None
    )

    return DashboardResponse(
        summary=DashboardSummary(
            high_priority=len(queue.high_priority),
            review=len(queue.review),
            follow_ups_due=len(queue.follow_ups),
            applications_total=applications_total,
        ),
        high_priority=[JobCard.model_validate(item) for item in queue.high_priority],
        review_candidates=[JobCard.model_validate(item) for item in queue.review],
        follow_ups=[JobCard.model_validate(item) for item in queue.follow_ups],
        last_refresh=last_refresh,
    )


@app.get("/api/jobs", response_model=list[JobCard])
def get_jobs(
    q: str | None = Query(default=None, description="Search title/company"),
    min_score: int = Query(default=0, ge=0, le=100),
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    connection: sqlite3.Connection = Depends(get_connection),
    profile: Profile = Depends(get_profile),
) -> list[JobCard]:
    """All non-filtered scored jobs, best score first — same ordering
    `list-matches` uses, with optional search/status/min-score filters."""
    items = applications.list_scored_jobs(
        connection, profile.profile_id, min_score=min_score, limit=limit, search=q, status=status
    )
    return [JobCard.model_validate(item) for item in items]


def _recent_job_card(recent_job) -> RecentJobCard:
    return RecentJobCard(**asdict(recent_job.job), first_seen_at=recent_job.first_seen_at)


def _recent_bucket(bucket, *, count_override: int | None = None) -> RecentBucket:
    return RecentBucket(
        key=bucket.key,
        label=bucket.label,
        min_hours=bucket.min_hours,
        max_hours=bucket.max_hours,
        count=bucket.count if count_override is None else count_override,
        jobs=[_recent_job_card(job) for job in bucket.jobs],
    )


# Registered before `/api/jobs/{job_id}` on purpose: Starlette matches
# routes in registration order, and "/api/jobs/recent" would otherwise be
# swallowed by the "{job_id}" path parameter (treating "recent" as a key).
@app.get("/api/jobs/recent", response_model=RecentResponse)
def get_recent_jobs(
    min_score: int = Query(default=recent.DEFAULT_MIN_SCORE, ge=0, le=100),
    older_limit: int = Query(default=recent.DEFAULT_OLDER_LIMIT, ge=1, le=200),
    older_offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_connection),
    profile: Profile = Depends(get_profile),
) -> RecentResponse:
    """The last 24 hours of scored jobs, in non-overlapping 2-hour discovery-
    age buckets, plus one "older than 24 hours" bucket (paginated via
    `older_limit`/`older_offset`). Bucket placement, scoring, and ordering
    all come straight from `app.recent.build_recent_timeline` — this
    endpoint only serializes it.
    """
    timeline = recent.build_recent_timeline(
        connection, profile.profile_id, min_score=min_score, older_limit=older_limit, older_offset=older_offset
    )

    return RecentResponse(
        generated_at=timeline.generated_at,
        summary=RecentSummary(
            last_24h=timeline.last_24h_count,
            high_priority=timeline.high_priority_count,
            review=timeline.review_count,
            older_than_24h=timeline.older_total_count,
        ),
        buckets=[_recent_bucket(bucket) for bucket in timeline.buckets],
        older=_recent_bucket(timeline.older, count_override=timeline.older_total_count),
    )


@app.get("/api/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    connection: sqlite3.Connection = Depends(get_connection),
    profile: Profile = Depends(get_profile),
) -> JobDetailResponse:
    """Full Job Detail: everything `JobCard` has, plus the full stored job
    description and the unmatched-skills side of the breakdown. Sourced
    from the same `job_matches` join `JobCard` uses — `database.get_match`
    just also selects `description`/`unmatched_skills`, which
    `job_card_from_row` doesn't carry onto the shared card shape.
    """
    row = database.get_match(connection, job_id, profile.profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No scored job found with key '{job_id}'.")
    item = applications.job_card_from_row(row, "new")
    unmatched_skills_json = row["unmatched_skills"]
    return JobDetailResponse(
        **asdict(item),
        description=row["description"],
        unmatched_skills=json.loads(unmatched_skills_json) if unmatched_skills_json else [],
    )


@app.get("/api/applications", response_model=list[ApplicationRecord])
def get_applications(
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    connection: sqlite3.Connection = Depends(get_connection),
) -> list[ApplicationRecord]:
    if status is not None:
        try:
            validate_status(status)
        except ApplicationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    rows = database.list_applications(connection, status=status, limit=limit)
    return [ApplicationRecord(**dict(row)) for row in rows]


@app.patch("/api/applications/{job_id}", response_model=ApplicationRecord)
def update_application(
    job_id: str,
    payload: ApplicationUpdateRequest,
    connection: sqlite3.Connection = Depends(get_connection),
) -> ApplicationRecord:
    """Create or update one job's tracked application — the same
    `database.upsert_application` the CLI's `application-update` calls.

    Marking a job `applied` with no explicit follow-up date preserves the
    existing semantics: `applied_at` auto-fills to now only if it isn't
    already set.
    """
    if database.get_job(connection, job_id) is None:
        raise HTTPException(status_code=404, detail=f"No job found with key '{job_id}'.")

    # Only fields actually present in the request body are forwarded, so
    # `upsert_application`'s "leave unchanged" default applies to anything
    # the client didn't mention.
    provided = payload.model_dump(exclude_unset=True)
    updates: dict = {}

    try:
        if "status" in provided:
            updates["status"] = validate_status(provided["status"])
        if "notes" in provided:
            updates["notes"] = provided["notes"]
        if "next_follow_up_at" in provided:
            value = provided["next_follow_up_at"]
            updates["next_follow_up_at"] = parse_datetime_arg(value) if value else None
    except ApplicationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    database.upsert_application(connection, job_id, **updates)

    app_row = database.get_application(connection, job_id)
    job_row = database.get_job(connection, job_id)
    return ApplicationRecord(
        job_unique_key=app_row["job_unique_key"],
        title=job_row["title"],
        company=job_row["company"],
        location=job_row["location"],
        application_url=job_row["application_url"],
        status=app_row["status"],
        applied_at=app_row["applied_at"],
        last_action_at=app_row["last_action_at"],
        next_follow_up_at=app_row["next_follow_up_at"],
        notes=app_row["notes"],
        created_at=app_row["created_at"],
        updated_at=app_row["updated_at"],
    )


@app.get("/api/follow-ups", response_model=FollowUpsResponse)
def get_follow_ups(
    connection: sqlite3.Connection = Depends(get_connection),
    profile: Profile = Depends(get_profile),
) -> FollowUpsResponse:
    """All tracked follow-ups, split into due/overdue and upcoming."""
    page = applications.list_follow_ups(connection, profile.profile_id)
    return FollowUpsResponse(
        due=[JobCard.model_validate(item) for item in page.due],
        upcoming=[JobCard.model_validate(item) for item in page.upcoming],
    )


# --- resumes -----------------------------------------------------------
#
# On-demand, evidence-bound tailored resume generation. Every write here
# goes through `app.resume.service`/`app.database` — this module only turns
# rows into JSON and maps error states onto HTTP status codes. Generation is
# always user-triggered by a `POST`; nothing in this file (or anywhere else
# in the app) calls it automatically.


def _require_job(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    job_row = database.get_job(connection, job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail={"error": "job_not_found", "message": f"No job found with key '{job_id}'."})
    return job_row


def _require_resume(connection: sqlite3.Connection, resume_id: int) -> sqlite3.Row:
    row = database.get_resume_version(connection, resume_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "resume_not_found", "message": f"No resume version found with id {resume_id}."})
    return row


def _resume_version_summary(row: sqlite3.Row) -> ResumeVersionSummary:
    return ResumeVersionSummary(
        id=row["id"],
        job_unique_key=row["job_unique_key"],
        version=row["version"],
        status=row["status"],
        compiler_status=row["compiler_status"],
        page_count=row["page_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        approved_at=row["approved_at"],
    )


def _resume_version_detail(row: sqlite3.Row) -> ResumeVersionDetail:
    analysis = json.loads(row["tailoring_analysis"])
    return ResumeVersionDetail(
        **_resume_version_summary(row).model_dump(),
        compile_log=row["compile_log"],
        tailoring_analysis=TailoringAnalysisResponse(**analysis),
    )


@app.post("/api/jobs/{job_id}/resumes", response_model=ResumeVersionDetail, status_code=201)
def generate_resume(
    job_id: str,
    connection: sqlite3.Connection = Depends(get_connection),
) -> ResumeVersionDetail:
    """Generate a brand-new tailored resume version for this job.

    Always creates a new version (v1 the first time, v2/v3/... on every
    later call for the same job) — regeneration never overwrites or
    returns a previously generated version.
    """
    job_row = _require_job(connection, job_id)
    try:
        row = resume_service.generate_resume_version(
            connection, job_row, master_resume_path=MASTER_RESUME_PATH, resumes_root=RESUMES_ROOT
        )
    except MasterResumeError as exc:
        raise HTTPException(status_code=409, detail={"error": "master_resume_missing", "message": str(exc)}) from exc
    return _resume_version_detail(row)


@app.get("/api/jobs/{job_id}/resumes", response_model=list[ResumeVersionSummary])
def list_job_resumes(
    job_id: str,
    connection: sqlite3.Connection = Depends(get_connection),
) -> list[ResumeVersionSummary]:
    """Every version generated for this job, newest first. Never filters out
    old versions — regeneration adds a version, it never removes one."""
    _require_job(connection, job_id)
    rows = database.list_resume_versions(connection, job_id)
    return [_resume_version_summary(row) for row in rows]


@app.get("/api/resumes/{resume_id}", response_model=ResumeVersionDetail)
def get_resume(
    resume_id: int,
    connection: sqlite3.Connection = Depends(get_connection),
) -> ResumeVersionDetail:
    row = _require_resume(connection, resume_id)
    return _resume_version_detail(row)


@app.get("/api/resumes/{resume_id}/latex", response_model=LatexSourceResponse)
def get_resume_latex(
    resume_id: int,
    connection: sqlite3.Connection = Depends(get_connection),
) -> LatexSourceResponse:
    """The full `.tex` source, straight from the database — never read off
    disk, so nothing about the local filesystem layout is exposed."""
    row = _require_resume(connection, resume_id)
    return LatexSourceResponse(latex_source=row["latex_source"])


@app.get("/api/resumes/{resume_id}/pdf")
def get_resume_pdf(
    resume_id: int,
    connection: sqlite3.Connection = Depends(get_connection),
) -> Response:
    """The compiled PDF, streamed as bytes -- the on-disk path is never
    part of the response. 409s with a clear, machine-readable error state
    if this version was never compiled (no local compiler was available)
    or if compilation failed.
    """
    row = _require_resume(connection, resume_id)
    if row["compiler_status"] == "unavailable":
        raise HTTPException(
            status_code=409,
            detail={"error": "latex_compiler_unavailable", "message": "No local LaTeX compiler was available when this version was generated."},
        )
    if row["compiler_status"] in ("failed", "not_attempted"):
        raise HTTPException(
            status_code=409,
            detail={"error": "latex_compile_failed", "message": row["compile_log"] or "LaTeX compilation did not produce a PDF."},
        )
    pdf_bytes = Path(row["pdf_path"]).read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.post("/api/resumes/{resume_id}/approve", response_model=ResumeVersionDetail)
def approve_resume(
    resume_id: int,
    connection: sqlite3.Connection = Depends(get_connection),
) -> ResumeVersionDetail:
    """Mark this version approved -- meaning only "this is the resume I'd
    use for this job." Demotes any other approved version of the same job
    back to draft. Never touches application status, never sends anything,
    never submits anything.
    """
    _require_resume(connection, resume_id)
    row = database.approve_resume_version(connection, resume_id)
    return _resume_version_detail(row)


