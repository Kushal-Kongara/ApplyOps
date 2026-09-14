"""Orchestrates one ATS fill attempt: detect the ATS, hand off to a
standalone worker process that opens a visible browser, uploads the
approved resume PDF, and fills what's confidently recognized. Never
submits, never marks anything applied -- that's a separate, explicit
user action.

The actual browser automation runs in `app.ats.worker`, spawned as its
own OS process (see that module's docstring for why): Playwright's sync
API can't run two concurrent un-stopped driver instances in one process,
and a successful fill's browser is meant to stay open indefinitely for
review -- so a second fill attempt from the same backend server process
needs its own process, not just its own function call.
"""

import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app import database
from app.application_prep.profile import DEFAULT_APPLICANT_PROFILE_PATH, load_applicant_profile
from app.ats.detect import IMPLEMENTED_ATS, apply_url_for, detect_ats
from app.ats.models import FilledField, FillResult

WORKER_STARTUP_TIMEOUT_SECONDS = 45


class UnsupportedAtsError(RuntimeError):
    """The job's application URL doesn't belong to any recognized ATS."""


class AtsNotImplementedError(RuntimeError):
    """The ATS is recognized but this phase hasn't built fill logic for
    it yet (Ashby, Greenhouse)."""


class PreparationNotReadyError(RuntimeError):
    """No matching preparation, or its resume version isn't approved."""


def _prepared_answers(connection: sqlite3.Connection, preparation_id: int) -> list[dict]:
    rows = database.list_application_answers(connection, preparation_id)
    return [{"question_text": row["question_text"], "answer": row["answer"]} for row in rows]


def fill_application(
    connection: sqlite3.Connection,
    job_row: sqlite3.Row,
    preparation_id: int,
    *,
    applicant_profile_path=DEFAULT_APPLICANT_PROFILE_PATH,
    headless: bool = False,
) -> FillResult:
    application_url = job_row["application_url"]
    ats = detect_ats(application_url)
    if ats is None:
        raise UnsupportedAtsError(f"'{application_url}' is not a supported ATS (Lever, Ashby, or Greenhouse only).")
    if ats not in IMPLEMENTED_ATS:
        raise AtsNotImplementedError(f"{ats.title()} is a supported ATS, but form-filling isn't implemented yet.")

    preparation = database.get_application_preparation(connection, preparation_id)
    if preparation is None or preparation["job_unique_key"] != job_row["unique_key"]:
        raise PreparationNotReadyError("No matching application preparation found for this job.")

    resume_version_id = preparation["resume_version_id"]
    resume_row = database.get_resume_version(connection, resume_version_id) if resume_version_id else None
    if resume_row is None or resume_row["status"] != "approved":
        raise PreparationNotReadyError("This preparation's resume version is not approved.")

    load_applicant_profile(applicant_profile_path)  # raises ApplicantProfileError early, before spawning a process
    prepared_answers = _prepared_answers(connection, preparation_id)
    form_url = apply_url_for(application_url, ats)

    run_dir = Path(tempfile.mkdtemp(prefix="jobos_ats_fill_"))
    input_path = run_dir / "input.json"
    output_path = run_dir / "output.json"
    input_path.write_text(json.dumps({
        "ats": ats,
        "form_url": form_url,
        "applicant_profile_path": str(applicant_profile_path),
        "prepared_answers": prepared_answers,
        "pdf_path": resume_row["pdf_path"],
        "headless": headless,
    }))

    # `start_new_session=True` detaches the worker into its own process
    # group -- it (and the browser it opens) survives independently of
    # this request, this thread, and even a later restart/interrupt of the
    # server process. We only wait for it to finish *filling* (writing
    # output.json); on success it then blocks forever to keep the browser
    # open, so we deliberately never wait for it to exit.
    process = subprocess.Popen(
        [sys.executable, "-m", "app.ats.worker", str(input_path), str(output_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )

    deadline = time.monotonic() + WORKER_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if output_path.exists():
            break
        if process.poll() is not None:
            break  # worker exited (crashed) before writing anything
        time.sleep(0.2)

    if process.poll() is not None:
        # The worker already exited (either it failed before opening a
        # browser, or it hit an error path that returns instead of
        # blocking) -- reap it so it doesn't linger as a zombie process.
        # A worker that's still running at this point (the success/partial
        # success case, which blocks forever to keep its browser open) is
        # deliberately left alone -- `.wait()` would hang forever on it.
        process.wait()

    if not output_path.exists():
        return FillResult(ats=ats, application_url=form_url, error="The fill worker did not respond in time.")

    data = json.loads(output_path.read_text())
    # Both files have already been fully read by this point -- the worker
    # read input.json at startup, and we just read the completed
    # output.json -- so it's safe to clean up regardless of whether the
    # worker process (and its browser) is still running.
    try:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        run_dir.rmdir()
    except OSError:
        pass

    return FillResult(
        ats=data["ats"], application_url=data["application_url"],
        fields=[FilledField(**field) for field in data["fields"]],
        resume_uploaded=data["resume_uploaded"], resume_error=data["resume_error"], error=data["error"],
    )
