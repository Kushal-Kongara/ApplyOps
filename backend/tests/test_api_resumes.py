"""API tests for the resume endpoints. Master resume path/resumes root are
patched to temp files/dirs per test — no dependency on real local config or
a real LaTeX install (this machine's real "no compiler" behavior is exactly
what's exercised for the compiler-unavailable path).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import database
from app.api import app, get_connection
from tests.support import make_job, make_master_resume_dict


class ResumeApiTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(
            self.connection,
            [make_job(external_id="1", description="Looking for a React and Python engineer.")],
        )
        self.job_id = "greenhouse:acme:1"

        app.dependency_overrides[get_connection] = lambda: self.connection
        self.addCleanup(app.dependency_overrides.clear)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.master_path = self.tmp_path / "resume_master.json"
        self.master_path.write_text(json.dumps(make_master_resume_dict()))
        self.resumes_root = self.tmp_path / "resumes"

        self._patches = [
            mock.patch("app.api.MASTER_RESUME_PATH", self.master_path),
            mock.patch("app.api.RESUMES_ROOT", self.resumes_root),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

        self.client = TestClient(app)


class GenerateResumeTest(ResumeApiTestCase):
    def test_generating_for_unknown_job_returns_job_not_found(self):
        response = self.client.post("/api/jobs/does-not-exist/resumes")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["error"], "job_not_found")

    def test_missing_master_resume_returns_master_resume_missing(self):
        self.master_path.unlink()
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "master_resume_missing")

    def test_successful_generation_returns_version_one(self):
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["status"], "draft")
        self.assertIn("React", data["tailoring_analysis"]["strong_matches"])

    def test_regenerating_creates_version_two(self):
        self.client.post(f"/api/jobs/{self.job_id}/resumes")
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes")
        self.assertEqual(response.json()["version"], 2)


class ListAndGetResumeTest(ResumeApiTestCase):
    def test_list_versions_newest_first(self):
        self.client.post(f"/api/jobs/{self.job_id}/resumes")
        self.client.post(f"/api/jobs/{self.job_id}/resumes")
        response = self.client.get(f"/api/jobs/{self.job_id}/resumes")
        self.assertEqual(response.status_code, 200)
        versions = [item["version"] for item in response.json()]
        self.assertEqual(versions, [2, 1])

    def test_list_versions_for_unknown_job_is_404(self):
        response = self.client.get("/api/jobs/does-not-exist/resumes")
        self.assertEqual(response.status_code, 404)

    def test_get_single_resume_detail(self):
        created = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        response = self.client.get(f"/api/resumes/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

    def test_get_unknown_resume_is_404(self):
        response = self.client.get("/api/resumes/999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["error"], "resume_not_found")


class LatexAndPdfEndpointsTest(ResumeApiTestCase):
    def test_latex_endpoint_returns_full_source(self):
        created = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        response = self.client.get(f"/api/resumes/{created['id']}/latex")
        self.assertEqual(response.status_code, 200)
        self.assertIn(r"\documentclass", response.json()["latex_source"])

    def test_pdf_endpoint_returns_compiler_unavailable_when_no_compiler_present(self):
        # This test machine has no LaTeX compiler installed, so a real
        # (unmocked) generation genuinely hits the unavailable path.
        created = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        response = self.client.get(f"/api/resumes/{created['id']}/pdf")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "latex_compiler_unavailable")

    def test_pdf_endpoint_streams_bytes_when_a_version_was_compiled(self):
        # The compiler mock is injected directly against the DB row rather
        # than through the HTTP layer (api.py doesn't accept which/run
        # overrides -- that's test-only plumbing this app has no product
        # reason to expose). `app.resume.service`'s own injection is already
        # covered end-to-end in tests/test_resume_service.py; this test only
        # confirms the PDF endpoint correctly streams bytes for a row that
        # *is* marked compiled.
        pdf_path = self.resumes_root / "job" / "v1" / "resume.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-fake-bytes")
        resume_id = database.insert_resume_version(
            self.connection,
            job_unique_key=self.job_id,
            version=1,
            latex_source="\\documentclass{article}",
            pdf_path=str(pdf_path),
            compiler_status="compiled",
            compile_log="ok",
            page_count=1,
            tailoring_analysis={"strong_matches": []},
        )

        response = self.client.get(f"/api/resumes/{resume_id}/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.content, b"%PDF-fake-bytes")

    def test_pdf_endpoint_for_unknown_resume_is_404(self):
        response = self.client.get("/api/resumes/999999/pdf")
        self.assertEqual(response.status_code, 404)


class ApproveResumeTest(ResumeApiTestCase):
    def test_approve_marks_version_approved(self):
        created = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        response = self.client.post(f"/api/resumes/{created['id']}/approve")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")

    def test_approving_a_new_version_demotes_the_previous_one(self):
        v1 = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        v2 = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        self.client.post(f"/api/resumes/{v1['id']}/approve")
        self.client.post(f"/api/resumes/{v2['id']}/approve")

        v1_after = self.client.get(f"/api/resumes/{v1['id']}").json()
        v2_after = self.client.get(f"/api/resumes/{v2['id']}").json()
        self.assertEqual(v1_after["status"], "draft")
        self.assertEqual(v2_after["status"], "approved")

    def test_approve_never_touches_application_status(self):
        created = self.client.post(f"/api/jobs/{self.job_id}/resumes").json()
        self.client.post(f"/api/resumes/{created['id']}/approve")
        app_row = database.get_application(self.connection, self.job_id)
        self.assertIsNone(app_row)

    def test_approving_unknown_resume_is_404(self):
        response = self.client.post("/api/resumes/999999/approve")
        self.assertEqual(response.status_code, 404)


class GenerationModeTest(ResumeApiTestCase):
    def test_no_body_defaults_to_deterministic(self):
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["generation_mode"], "deterministic")

    def test_explicit_deterministic_mode(self):
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes", json={"mode": "deterministic"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["generation_mode"], "deterministic")

    def test_invalid_mode_is_a_clean_400(self):
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes", json={"mode": "bogus"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "invalid_mode")

    def test_llm_enhanced_with_no_provider_configured_is_a_clean_503(self):
        # This test process has no APPLYOPS_LLM_PROVIDER set, so this
        # exercises the real "nothing configured" path, not a mock.
        response = self.client.post(f"/api/jobs/{self.job_id}/resumes", json={"mode": "llm_enhanced"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["error"], "llm_unavailable")

    def test_llm_enhanced_failure_creates_no_version(self):
        self.client.post(f"/api/jobs/{self.job_id}/resumes", json={"mode": "llm_enhanced"})
        response = self.client.get(f"/api/jobs/{self.job_id}/resumes")
        self.assertEqual(response.json(), [])


class LLMStatusEndpointTest(ResumeApiTestCase):
    def test_status_when_unconfigured(self):
        response = self.client.get("/api/llm/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["configured"])
        self.assertFalse(data["reachable"])
        self.assertIsNone(data.get("model"))

    def test_status_never_returns_a_5xx(self):
        # Even fully unconfigured/unreachable, this is a normal 200 -- the
        # dashboard must never fail to load because a DGX is offline.
        response = self.client.get("/api/llm/status")
        self.assertLess(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
