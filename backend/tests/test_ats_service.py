"""`fill_application` pre-flight checks -- unsupported ATS, an ATS that's
recognized but not yet implemented, a missing/unapproved resume, and a
missing applicant profile. All of these must raise *before* Playwright
ever launches a browser, so these tests never open one."""

import unittest
from pathlib import Path

from app import database
from app.application_prep.profile import ApplicantProfileError
from app.ats import service as ats_service
from tests.support import make_job

_EXAMPLE_PROFILE_PATH = Path("config/applicant_profile.example.json")


class FillApplicationPreflightTest(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)

    def _job(self, application_url: str, external_id: str = "1"):
        database.upsert_jobs(self.connection, [make_job(external_id=external_id, application_url=application_url)])
        return database.get_job(self.connection, f"greenhouse:acme:{external_id}")

    def test_unsupported_ats_raises_before_any_browser_launch(self):
        job_row = self._job("https://careers.example.com/apply/123")
        with self.assertRaises(ats_service.UnsupportedAtsError):
            ats_service.fill_application(self.connection, job_row, preparation_id=1)

    def test_recognized_but_unimplemented_ats_raises(self):
        job_row = self._job("https://jobs.ashbyhq.com/acme/abc123")
        with self.assertRaises(ats_service.AtsNotImplementedError):
            ats_service.fill_application(self.connection, job_row, preparation_id=1)

    def test_greenhouse_is_recognized_but_unimplemented(self):
        job_row = self._job("https://boards.greenhouse.io/acme/jobs/123")
        with self.assertRaises(ats_service.AtsNotImplementedError):
            ats_service.fill_application(self.connection, job_row, preparation_id=1)

    def test_missing_preparation_raises(self):
        job_row = self._job("https://jobs.lever.co/AIFund/abc123")
        with self.assertRaises(ats_service.PreparationNotReadyError):
            ats_service.fill_application(self.connection, job_row, preparation_id=999999)

    def test_preparation_for_a_different_job_raises(self):
        job_row = self._job("https://jobs.lever.co/AIFund/abc123", external_id="1")
        other_job = self._job("https://jobs.lever.co/AIFund/xyz789", external_id="2")
        resume_id = database.insert_resume_version(
            self.connection, job_unique_key=other_job["unique_key"], version=1, latex_source="x",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        database.approve_resume_version(self.connection, resume_id)
        prep_id = database.create_application_preparation(self.connection, other_job["unique_key"], resume_version_id=resume_id)

        with self.assertRaises(ats_service.PreparationNotReadyError):
            ats_service.fill_application(self.connection, job_row, preparation_id=prep_id)

    def test_preparation_with_no_resume_version_raises(self):
        job_row = self._job("https://jobs.lever.co/AIFund/abc123")
        prep_id = database.create_application_preparation(self.connection, job_row["unique_key"], resume_version_id=None)
        with self.assertRaises(ats_service.PreparationNotReadyError):
            ats_service.fill_application(self.connection, job_row, preparation_id=prep_id)

    def test_preparation_with_unapproved_resume_version_raises(self):
        job_row = self._job("https://jobs.lever.co/AIFund/abc123")
        resume_id = database.insert_resume_version(
            self.connection, job_unique_key=job_row["unique_key"], version=1, latex_source="x",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        # Deliberately not approved -- resume stays in "draft".
        prep_id = database.create_application_preparation(self.connection, job_row["unique_key"], resume_version_id=resume_id)
        with self.assertRaises(ats_service.PreparationNotReadyError):
            ats_service.fill_application(self.connection, job_row, preparation_id=prep_id)

    def test_missing_applicant_profile_raises(self):
        job_row = self._job("https://jobs.lever.co/AIFund/abc123")
        resume_id = database.insert_resume_version(
            self.connection, job_unique_key=job_row["unique_key"], version=1, latex_source="x",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        database.approve_resume_version(self.connection, resume_id)
        prep_id = database.create_application_preparation(self.connection, job_row["unique_key"], resume_version_id=resume_id)

        with self.assertRaises(ApplicantProfileError):
            ats_service.fill_application(
                self.connection, job_row, preparation_id=prep_id,
                applicant_profile_path="/tmp/does-not-exist-applicant-profile.json",
            )

    def test_failure_never_touches_application_tracking_status(self):
        # This whole module never writes to the `applications` table --
        # a failed/blocked fill attempt must never mark anything applied.
        job_row = self._job("https://careers.example.com/apply/123")
        database.upsert_application(self.connection, job_row["unique_key"], status="shortlisted")
        try:
            ats_service.fill_application(self.connection, job_row, preparation_id=1)
        except ats_service.UnsupportedAtsError:
            pass
        app_row = database.get_application(self.connection, job_row["unique_key"])
        self.assertEqual(app_row["status"], "shortlisted")


class RepeatedFillAttemptTest(unittest.TestCase):
    """Regression test: each `fill_application` call runs in its own
    detached worker process (see `app.ats.worker`) specifically because
    Playwright's sync API cannot run two concurrent un-stopped driver
    instances in one process/thread -- a second in-process call used to
    crash with an asyncio-loop error. This exercises two real (but fast,
    failing-fast) worker invocations back to back."""

    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(self.connection, [make_job(
            external_id="1",
            application_url="https://jobs.lever.co.this-domain-does-not-exist.invalid/AIFund/x",
        )])
        self.job_row = database.get_job(self.connection, "greenhouse:acme:1")
        resume_id = database.insert_resume_version(
            self.connection, job_unique_key=self.job_row["unique_key"], version=1, latex_source="x",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        database.approve_resume_version(self.connection, resume_id)
        self.prep_id = database.create_application_preparation(
            self.connection, self.job_row["unique_key"], resume_version_id=resume_id,
        )

    def test_two_sequential_fill_attempts_both_complete_without_crashing(self):
        for _ in range(2):
            result = ats_service.fill_application(
                self.connection, self.job_row, self.prep_id,
                applicant_profile_path=str(_EXAMPLE_PROFILE_PATH), headless=True,
            )
            self.assertIsNotNone(result.error)  # the domain genuinely can't resolve
            self.assertNotIn("asyncio", result.error.lower())


if __name__ == "__main__":
    unittest.main()
