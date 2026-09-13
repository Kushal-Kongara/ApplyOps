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

## Architecture

- Python collectors
- FastAPI backend
- PostgreSQL database
- React and TypeScript dashboard
- NVIDIA DGX with Ollama for local AI inference
