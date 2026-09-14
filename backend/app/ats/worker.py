"""Standalone worker process for one ATS fill attempt.

Playwright's sync API does not support two concurrent un-stopped driver
instances in the same OS thread/process -- a second `fill_application`
call in the same backend server process (very possible: FastAPI reuses a
small threadpool across requests) breaks with an asyncio-loop error, and
the first call's browser is meant to stay open indefinitely for review
anyway. So each fill attempt gets its own OS process instead: this module,
invoked as `python -m app.ats.worker <input.json> <output.json>`.

Reads the fill request from `input.json`, dispatches to the matching
`app.ats.lever`/`app.ats.ashby`/`app.ats.greenhouse` module by `payload["ats"]`,
writes the result to `output.json`, then blocks forever so its browser
stays open -- the parent process reads `output.json` and returns
immediately, never waiting for this process to exit.
"""

import dataclasses
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

from app.application_prep.profile import load_applicant_profile
from app.ats import ashby, greenhouse, lever

# One fill/upload function pair per implemented ATS (`app.ats.detect.IMPLEMENTED_ATS`)
# -- each module owns its own real-DOM-verified logic; this is only routing.
_FILL_FUNCS = {
    "lever": lever.fill_lever_form,
    "ashby": ashby.fill_ashby_form,
    "greenhouse": greenhouse.fill_greenhouse_form,
}
_UPLOAD_FUNCS = {
    "lever": lever.upload_resume,
    "ashby": ashby.upload_resume,
    "greenhouse": greenhouse.upload_resume,
}


def _write_result(output_path: str, data: dict) -> None:
    """Write atomically so the parent process never reads a half-written
    file (rename is atomic on the same filesystem, unlike a direct write)."""
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp_path, output_path)


def main() -> None:
    input_path, output_path = sys.argv[1], sys.argv[2]
    with open(input_path, encoding="utf-8") as handle:
        payload = json.load(handle)

    result = {
        "ats": payload["ats"], "application_url": payload["form_url"],
        "fields": [], "resume_uploaded": False, "resume_error": None, "error": None,
    }

    try:
        profile = load_applicant_profile(payload["applicant_profile_path"])
    except Exception as exc:
        result["error"] = f"Could not load applicant profile: {exc}"
        _write_result(output_path, result)
        return

    playwright = sync_playwright().start()
    browser = None
    try:
        browser = playwright.chromium.launch(headless=payload.get("headless", False))
        page = browser.new_page()
        page.goto(payload["form_url"], wait_until="domcontentloaded", timeout=30000)
        # Ashby/Greenhouse hydrate their whole form client-side after
        # `domcontentloaded` -- 1s (enough for Lever's near-static page)
        # isn't reliably enough for that, so wait longer for both.
        page.wait_for_timeout(3000)
    except Exception as exc:
        if browser is not None:
            browser.close()
        playwright.stop()
        result["error"] = f"Could not open the application page: {exc}"
        _write_result(output_path, result)
        return

    upload_fn = _UPLOAD_FUNCS[payload["ats"]]
    fill_fn = _FILL_FUNCS[payload["ats"]]

    pdf_path = payload.get("pdf_path")
    if not pdf_path:
        result["resume_error"] = "No compiled PDF exists for the approved resume version."
    else:
        uploaded, resume_error = upload_fn(page, pdf_path)
        result["resume_uploaded"] = uploaded
        result["resume_error"] = resume_error

    try:
        fields = fill_fn(page, profile, payload["prepared_answers"])
        result["fields"] = [dataclasses.asdict(f) for f in fields]
    except Exception as exc:
        result["error"] = f"Form filling stopped early: {exc}"

    _write_result(output_path, result)

    # Deliberately never call browser.close()/playwright.stop() past this
    # point -- keep this whole process alive so the browser stays open for
    # the user to review and submit by hand. The parent already has its
    # answer and isn't waiting on this process to exit.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
