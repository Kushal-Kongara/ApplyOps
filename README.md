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
explainable shortlist. Everything else below is planned, not built.

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

## Architecture

- Python collectors (Phase 1: standard-library `sqlite3` + `httpx`)
- FastAPI backend (later phase)
- PostgreSQL database (later phase)
- React and TypeScript dashboard
- NVIDIA DGX with Ollama for local AI inference
