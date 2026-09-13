# ApplyOps

ApplyOps is a local-first job discovery and application preparation system.

It will:

1. Collect newly posted jobs from company career pages and ATS platforms.
2. Normalize and remove duplicate jobs.
3. Match jobs against verified resume experience.
4. Generate a tailored resume using an NVIDIA DGX.
5. Present the job and resume for human review.
6. Open the official application page for final submission.

## Core rule

ApplyOps never invents experience and never submits an application without
human approval.

## Planned sources

- Greenhouse
- Ashby
- Lever
- Workday
- Selected company career pages

## Status

Phase 1 (job collection foundation) is implemented: collectors for Greenhouse,
Ashby, and Lever, a normalized job model, SQLite storage with de-duplication,
and a CLI.

Phase 2 (deterministic filtering and match scoring) is implemented: a
keyword-only, no-AI scoring engine that turns collected jobs into a ranked,
explainable shortlist.

Phase 3/4 (application tracking and the daily action queue) is implemented:
tracked application status, follow-up reminders, and a `daily` command that
turns the ranked shortlist into an actionable to-do list.

Phase 5 (API + web dashboard) is implemented: a FastAPI layer over the
existing CLI logic, and a React/TypeScript dashboard to browse and act on
jobs visually instead of only from the CLI.

Phase 6 (automatic refresh) is implemented: one `refresh` pipeline (collect
every source, then match) that's callable manually or on a schedule, plus a
local scheduler that runs it immediately and then every 2 hours.

Phase 7 (Job Detail + on-demand tailored resume generation) is implemented: a
Job Detail page with the full stored job description, a deterministic
(no-LLM) resume tailoring engine that selects/reorders your own master-resume
content per job, a LaTeX renderer, optional local PDF compilation, and a
version history with an approval state. Everything else below (recruiter
discovery, auto-apply, notifications) is planned, not built.

## Phase 1 setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

cd backend
cp config/sources.example.json config/sources.json
```

Edit `backend/config/sources.json` with the companies you care about. Each entry
needs a `type` (`greenhouse`, `ashby`, or `lever`), a `company` name, and the
board `identifier` from the company's public board URL, e.g.
`https://boards.greenhouse.io/COMPANY_BOARD_TOKEN` -> `COMPANY_BOARD_TOKEN`.
That file is git-ignored; `sources.example.json` is the committed template.
Verify each company's real board token/site name yourself — this doc doesn't
list any.

## Phase 1 commands

```bash
cd backend

# Collect jobs from every configured source.
python -m app.cli scan --config config/sources.json

# Show what has been stored.
python -m app.cli list-jobs

# Run the test suite (no network access required).
python -m unittest discover -v
```

`scan` prints one line per source plus a summary, and exits non-zero if any
source failed:

```text
Adobe / greenhouse: 42 fetched, 7 new, 35 updated
Example Startup / ashby: failed - useful error
Scan complete: 7 new jobs, 35 updated, 1 source failed
```

Jobs are stored in `backend/data/applyops.db` by default (override with `--db`).
The database is git-ignored.

See [docs/phase-01-job-collection.md](docs/phase-01-job-collection.md) for how
collectors, normalization, and the de-duplication key work.

## Phase 2 setup

```bash
cd backend
cp config/profile.example.json config/profile.json
```

Edit `backend/config/profile.json` with your own target titles, locations,
skills, and exclusions — see the fields in `profile.example.json`. This file
holds no personal identity information (no name, email, phone, or
immigration documents), only role preferences, and is git-ignored.

## Phase 2 commands

```bash
cd backend

# Score every active job in the database against a profile.
python -m app.cli match --profile config/profile.json

# Show the ranked shortlist (--show-key prints each job's key for the next command).
python -m app.cli list-matches --min-score 70 --limit 25 --show-key

# See exactly why one job scored what it did.
python -m app.cli inspect-match --job-key "greenhouse:acme:12345"
```

`list-matches` prints one block per job, best score first:

```text
81  Full Stack Engineer — Example Company
    San Francisco, CA | greenhouse
    Title 33/35 | Skills 17/30 | Location 15/15 | Seniority 10/10 | Product 6/10
    Visa: unknown
    Matched: React, TypeScript, Python, AWS
```

Rerunning `match` (after a new scan, or an edited profile) rescoring updates
each job's stored match in place rather than creating duplicates. Visa
status is reported per job but never affects the score — see
[docs/phase-02-matching.md](docs/phase-02-matching.md) for why, and for how
every scoring component, alias, and filter works.

## Phase 3/4 commands

```bash
cd backend

# Today's actionable jobs: high-priority (70+), review (65-69), due follow-ups.
python -m app.cli daily --profile config/profile.json

# Track or update one job's application.
python -m app.cli application-update "greenhouse:acme:12345" --status shortlisted
python -m app.cli application-update "greenhouse:acme:12345" --status applied

# Show tracked applications.
python -m app.cli applications --status shortlisted
```

## Phase 5 setup — API + dashboard

This phase adds two new local processes on top of the same SQLite database:
a FastAPI server, and a React/TypeScript dashboard that talks to it.

```bash
# One-time: install the new API dependencies (already added to pyproject.toml).
source .venv/bin/activate
pip install -e .

# One-time: install frontend dependencies.
cd frontend
npm install
```

### Run it

```bash
# Terminal 1 — backend API (from the backend/ directory)
cd backend
uvicorn app.api:app --reload --port 8000

# Terminal 2 — frontend dev server (from the frontend/ directory)
cd frontend
npm run dev

# Terminal 3 — scheduler: refreshes data every 2 hours (see Phase 6 below)
cd backend
python -m app.scheduler
```

Then open **http://localhost:5173** in your browser. The dev server proxies
`/api/*` requests to `http://127.0.0.1:8000`, so the two run on different
ports without you needing to configure anything else. Terminal 3 is
optional for just browsing the dashboard — it's what keeps the data itself
fresh; see Phase 6 for exactly what it does.

By default the API reads `backend/data/applyops.db` and
`backend/config/profile.json` — the same files the CLI uses — via
`APPLYOPS_DB_PATH` / `APPLYOPS_PROFILE_PATH` env vars if you want to point
it elsewhere (uncomment/edit them in `.env.example`).

### CORS

The API only allows browser requests from `http://localhost:5173` and
`http://127.0.0.1:5173` — Vite's default dev server ports — and only for
`GET`/`PATCH`/`POST`, the only methods it exposes. This is a local,
single-user tool with no login of its own, so CORS is opened just enough for
the dev server to reach it directly if you ever bypass the proxy; it is not
configured for any other origin, and doing so for a real deployment would
need a real auth story first.

### Frontend checks

```bash
cd frontend
npm run typecheck   # tsc, no emit
npm run build       # type-checks then builds a production bundle
npm test            # vitest — pure logic/formatting helpers
```

## Phase 6 — automatic refresh every 2 hours

One pipeline, two ways to run it: manually, once, whenever you want —

```bash
cd backend
python -m app.cli refresh --profile config/profile.json
```

— or continuously, on a schedule, as its own long-running process (Terminal
3 above):

```bash
cd backend
python -m app.scheduler
```

Both call the exact same `refresh_from_files` pipeline: collect every
configured source → upsert jobs (preserving `first_seen_at` for jobs seen
before) → run matching for the profile → record the run. Neither one
duplicates the existing `scan`/`match` logic — `refresh` is a thin
orchestration layer over them (see `backend/app/refresh.py`).

**Cadence and timezone**: the scheduler refreshes immediately on startup,
then again at the next even wall-clock 2-hour mark — 00:00, 02:00, 04:00,
... 22:00 — **in your computer's local timezone**, not "2 hours after
whenever you happened to start it." Start it at 9:47am and the next run is
at 10:00am, not 11:47am.

**Overlap protection**: the scheduler is a single sequential loop — it only
computes the next boundary after a refresh has fully finished, so it can
never overlap itself. A manual `cli.py refresh` run at the same time as a
scheduled one is handled by an OS-level `flock` on `backend/data/.refresh.lock`
(default path) that `refresh_from_files` holds for the exact duration of a
run — not a lock-file-age heuristic. `flock` ties the lock to the process's
open file descriptor, so the kernel releases it automatically the instant
that descriptor closes, on *any* exit path, including a crash or `kill -9`.
That means a refresh can legitimately run for however long it needs (there's
no "older than N minutes, assume it's dead" window that a slow-but-healthy
refresh could fall into), while a genuinely crashed process still can never
leave the database permanently locked. The second caller gets a clear
"already running" error instead of two collectors hitting the same SQLite
file at once.

> **The local scheduler only runs while this computer/process is running.**
> If the Mac sleeps, loses power, or the process is killed, refreshes stop
> until you start it again. There is no missed-run catch-up and no always-on
> cloud component in this phase — that's a deliberately separate, later
> problem.

The dashboard's Today page shows a compact "Last refreshed: N minutes ago"
line (with new/high-priority/review counts from that run) so you can tell
at a glance whether the scheduler is actually running — it polls the API
every 60 seconds to stay current, but the browser itself never triggers a
refresh; it only ever reads what the backend/scheduler already produced.

## Phase 7 — Job Detail + on-demand tailored resume generation

### Master resume setup (required before generating anything)

Resume tailoring reads from exactly one file: `backend/config/resume_master.json`.
This must be your own real, truthful resume content — every fact a tailored
resume can ever state comes from here.

```bash
cd backend
cp config/resume_master.example.json config/resume_master.json
```

Edit `backend/config/resume_master.json` to match the schema in the example
file: `contact`, `summary`, `experience` (each entry's `bullets` need a
stable, unique `id` — e.g. `exp_acme_b1` — used later to trace every
tailored bullet back to its source), `skills` (categorized lists), `education`,
and optional `projects`/`achievements`. This file is git-ignored — only the
fake-data example is committed. Until it exists, `POST
/api/jobs/{job_id}/resumes` fails cleanly with a `master_resume_missing`
error and a message pointing here; nothing is ever invented as a fallback.

### The truthfulness rule

Tailoring only ever **selects, reorders, or shortens** what's already in
`resume_master.json`. It never invents a technology, employer, project,
metric, or year of experience, and it never associates a skill with an
employer/project unless a bullet in your master resume already does. If a
job description asks for something your master resume has no evidence for,
that requirement is reported (visible on the Changes tab) as unsupported —
it is never added to the resume. See `backend/app/resume/tailor.py` for the
exact algorithm (deterministic keyword matching — no LLM, no paid API).

### Generating a resume

From the dashboard: open a job (any job card's **Open in JobOS** button) to
reach its Job Detail page, which shows the full stored job description (the
original text collected during a scan, never re-fetched from the ATS) plus
the full match-score breakdown. Under **Tailored Resume**, click **Generate
Resume** — this is always an explicit, user-triggered action; nothing in
this app generates a resume automatically (not on collection, not on a match
score, not on a scheduler cycle).

Each click of **Generate**/**Regenerate** creates a brand-new version
(v1, v2, v3, ...) — a previous version is never overwritten or deleted, and
regeneration with unchanged inputs can legitimately produce identical
content (this is a deterministic engine, not a reason to add randomness).
The **Versions** tab lists every version generated for a job. **Approve** on
a version marks it as "the resume I'd use for this job" — it does not
submit anything, change the application's status, or send anything anywhere.

### LaTeX and PDF

Every version's LaTeX source (`backend/app/resume/templates/resume.tex`,
rendered by `backend/app/resume/latex.py`) is always generated and always
available on the **LaTeX** tab — copy it or download the `.tex` file and
paste it straight into [Overleaf](https://www.overleaf.com/) if you don't
want to install anything locally.

PDF compilation is optional and uses whatever's already on your machine, in
this order: `latexmk`, `tectonic`, `pdflatex`. If none is installed, the
version is still generated (LaTeX only) and the **Preview** tab explains
that no local compiler was found — nothing is auto-installed. To enable PDF
preview/download, install one, e.g.:

```bash
# macOS
brew install --cask mactex-no-gui   # or: brew install tectonic

# Debian/Ubuntu
sudo apt install texlive-latex-base latexmk
```

Generated files live under `backend/data/resumes/<hashed-job-key>/v<N>/` —
this whole directory is git-ignored. The API never returns a filesystem
path; LaTeX source is served from the database, and the PDF is streamed as
bytes.

### Commands

```bash
cd backend
python -m unittest discover -v -k resume   # resume-specific backend tests only
```

There is no CLI command for resume generation in this phase — it's a
dashboard-only action (`POST /api/jobs/{job_id}/resumes` under the hood).

## Architecture

- Python collectors, matching, and application tracking (standard-library
  `sqlite3` + `httpx`)
- FastAPI backend (`backend/app/api.py`) — a thin HTTP layer over the same
  functions the CLI uses, no duplicated business logic
- SQLite database (still local-first; a hosted database is a later concern,
  not a current limitation)
- React and TypeScript dashboard (`frontend/`)
- Deterministic, evidence-bound resume tailoring (`backend/app/resume/`) —
  keyword matching only, no LLM/paid API in this phase (see Phase 7 above)
- NVIDIA DGX with Ollama for local AI inference (later phase)
