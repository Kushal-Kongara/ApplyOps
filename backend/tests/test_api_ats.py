"""API tests for `/api/jobs/{job_id}/fill-application`. `ats_service.fill_application`
is always mocked here -- this suite must never launch a real browser."""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import database
from app.api import app, get_connection
from app.application_prep.profile import ApplicantProfileError
from app.ats import service as ats_service
from app.ats.models import FilledField, FillResult
from tests.support import make_job


class FillApplicationApiTest(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(self.connection, [make_job(external_id="1")])
        self.job_id = "greenhouse:acme:1"

        app.dependency_overrides[get_connection] = lambda: self.connection
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_successful_fill_returns_field_statuses(self):
        fake_result = FillResult(
            ats="lever", application_url="https://jobs.lever.co/AIFund/abc/apply",
            fields=[
                FilledField(label="Full name", status="filled", value="Jane Doe"),
                FilledField(label="Portfolio URL", status="skipped", reason="optional, no value"),
            ],
            resume_uploaded=True, resume_error=None, error=None,
        )
        with mock.patch.object(ats_service, "fill_application", return_value=fake_result):
            response = self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ats"], "lever")
        self.assertTrue(data["resume_uploaded"])
        statuses = {f["label"]: f["status"] for f in data["fields"]}
        self.assertEqual(statuses["Full name"], "filled")
        self.assertEqual(statuses["Portfolio URL"], "skipped")

    def test_unsupported_ats_is_a_clean_409(self):
        with mock.patch.object(ats_service, "fill_application", side_effect=ats_service.UnsupportedAtsError("nope")):
            response = self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "unsupported_ats")

    def test_ats_not_implemented_is_a_clean_409(self):
        with mock.patch.object(ats_service, "fill_application", side_effect=ats_service.AtsNotImplementedError("soon")):
            response = self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "ats_not_implemented")

    def test_preparation_not_ready_is_a_clean_409(self):
        with mock.patch.object(ats_service, "fill_application", side_effect=ats_service.PreparationNotReadyError("no approved resume")):
            response = self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "preparation_not_ready")

    def test_missing_applicant_profile_is_a_clean_409(self):
        with mock.patch.object(ats_service, "fill_application", side_effect=ApplicantProfileError("missing")):
            response = self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "applicant_profile_missing")

    def test_missing_job_is_404(self):
        response = self.client.post("/api/jobs/does-not-exist/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 404)

    def test_partial_failure_is_still_a_200_with_error_field_set(self):
        # A DGX-offline/ATS-layout-changed style partial failure isn't an
        # HTTP error -- it's a normal response with `error` set and
        # whatever fields were filled before it happened.
        fake_result = FillResult(
            ats="lever", application_url="https://jobs.lever.co/AIFund/abc/apply",
            fields=[FilledField(label="Full name", status="filled", value="Jane Doe")],
            resume_uploaded=False, resume_error="No compiled PDF exists for the approved resume version.",
            error=None,
        )
        with mock.patch.object(ats_service, "fill_application", return_value=fake_result):
            response = self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["resume_uploaded"])
        self.assertIsNotNone(response.json()["resume_error"])

    def test_fill_never_marks_the_application_applied(self):
        fake_result = FillResult(ats="lever", application_url="https://x/apply", fields=[])
        with mock.patch.object(ats_service, "fill_application", return_value=fake_result):
            self.client.post(f"/api/jobs/{self.job_id}/fill-application", json={"preparation_id": 1})
        app_row = database.get_application(self.connection, self.job_id)
        self.assertIsNone(app_row)  # never created/touched by filling


if __name__ == "__main__":
    unittest.main()
