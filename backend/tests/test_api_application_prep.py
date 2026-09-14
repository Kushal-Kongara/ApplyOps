"""API tests for application preparation. Applicant profile path is patched
to a temp file per test -- no dependency on real local config."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import database
from app.api import app, get_connection
from tests.support import make_applicant_profile_dict, make_job


class ApplicationPrepApiTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(
            self.connection, [make_job(external_id="1", description="React and TypeScript engineer wanted.")],
        )
        self.job_id = "greenhouse:acme:1"

        app.dependency_overrides[get_connection] = lambda: self.connection
        self.addCleanup(app.dependency_overrides.clear)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.profile_path = self.tmp_path / "applicant_profile.json"
        self.profile_path.write_text(json.dumps(make_applicant_profile_dict()))

        self._patches = [
            mock.patch("app.api.APPLICANT_PROFILE_PATH", self.profile_path),
            mock.patch("app.api.MASTER_RESUME_PATH", Path("config/resume_master.json")),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

        self.client = TestClient(app)

    def approve_a_resume(self) -> int:
        resume_id = database.insert_resume_version(
            self.connection, job_unique_key=self.job_id, version=1, latex_source="x",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        database.approve_resume_version(self.connection, resume_id)
        return resume_id


class CreatePreparationTest(ApplicationPrepApiTestCase):
    def test_create_with_approved_resume_succeeds(self):
        self.approve_a_resume()
        response = self.client.post(f"/api/jobs/{self.job_id}/application-preparations")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "draft")
        self.assertGreater(len(data["answers"]), 0)

    def test_create_without_approved_resume_is_a_clean_409(self):
        response = self.client.post(f"/api/jobs/{self.job_id}/application-preparations")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "no_approved_resume")

    def test_create_for_unknown_job_is_404(self):
        response = self.client.post("/api/jobs/does-not-exist/application-preparations")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["error"], "job_not_found")


class RetrieveAndListTest(ApplicationPrepApiTestCase):
    def test_get_single_preparation(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.get(f"/api/application-preparations/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

    def test_get_unknown_preparation_is_404(self):
        response = self.client.get("/api/application-preparations/999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["error"], "preparation_not_found")

    def test_list_preparations_for_job(self):
        self.approve_a_resume()
        self.client.post(f"/api/jobs/{self.job_id}/application-preparations")
        self.client.post(f"/api/jobs/{self.job_id}/application-preparations")
        response = self.client.get(f"/api/jobs/{self.job_id}/application-preparations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)


class GenerateTest(ApplicationPrepApiTestCase):
    def test_generate_resolves_deterministic_answers(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.post(f"/api/application-preparations/{created['id']}/generate")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        full_name = next(a for a in data["answers"] if a["question_id"] == "full_name")
        self.assertEqual(full_name["answer"], "Test Candidate")
        self.assertFalse(full_name["needs_user_input"])

    def test_generate_without_applicant_profile_is_a_clean_409(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        self.profile_path.unlink()
        response = self.client.post(f"/api/application-preparations/{created['id']}/generate")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "applicant_profile_missing")

    def test_generate_for_unknown_preparation_is_404(self):
        response = self.client.post("/api/application-preparations/999999/generate")
        self.assertEqual(response.status_code, 404)

    def test_llm_unavailable_marks_open_ended_questions_needs_input_not_a_failure(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.post(f"/api/application-preparations/{created['id']}/generate")
        self.assertEqual(response.status_code, 200)
        why_role = next(a for a in response.json()["answers"] if a["question_id"] == "why_role")
        self.assertTrue(why_role["needs_user_input"])


class CustomQuestionTest(ApplicationPrepApiTestCase):
    def test_add_custom_question(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.post(
            f"/api/application-preparations/{created['id']}/questions",
            json={"question_text": "How many years of React experience?", "question_type": "text", "category": "experience"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["question_text"], "How many years of React experience?")

    def test_custom_question_resolves_on_next_generate(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        added = self.client.post(
            f"/api/application-preparations/{created['id']}/questions",
            json={"question_text": "How many years of React experience?", "question_type": "text", "category": "experience"},
        ).json()
        generated = self.client.post(f"/api/application-preparations/{created['id']}/generate").json()
        answer = next(a for a in generated["answers"] if a["id"] == added["id"])
        self.assertFalse(answer["needs_user_input"])
        self.assertIn("years", answer["answer"])

    def test_invalid_question_type_is_rejected(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.post(
            f"/api/application-preparations/{created['id']}/questions",
            json={"question_text": "X?", "question_type": "essay", "category": "other"},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_category_is_rejected(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.post(
            f"/api/application-preparations/{created['id']}/questions",
            json={"question_text": "X?", "question_type": "text", "category": "bogus"},
        )
        self.assertEqual(response.status_code, 400)


class EditAnswerTest(ApplicationPrepApiTestCase):
    def test_edit_answer_marks_user_edited(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        answer_id = created["answers"][0]["id"]
        response = self.client.patch(f"/api/application-answers/{answer_id}", json={"answer": "My custom value"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["answer"], "My custom value")
        self.assertTrue(data["user_edited"])
        self.assertFalse(data["needs_user_input"])
        self.assertEqual(data["answer_source"], "user_edited")

    def test_edit_unknown_answer_is_404(self):
        response = self.client.patch("/api/application-answers/999999", json={"answer": "x"})
        self.assertEqual(response.status_code, 404)

    def test_editing_a_required_answer_can_flip_preparation_to_ready(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        self.client.post(f"/api/application-preparations/{created['id']}/generate")
        for answer in created["answers"]:
            if answer["required"]:
                self.client.patch(f"/api/application-answers/{answer['id']}", json={"answer": "filled"})
        final = self.client.get(f"/api/application-preparations/{created['id']}").json()
        self.assertEqual(final["status"], "ready")


class UpdatePreparationTest(ApplicationPrepApiTestCase):
    def test_update_resume_version(self):
        resume_id = self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        other_resume = database.insert_resume_version(
            self.connection, job_unique_key=self.job_id, version=2, latex_source="y",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        response = self.client.patch(
            f"/api/application-preparations/{created['id']}", json={"resume_version_id": other_resume},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resume_version_id"], other_resume)

    def test_invalid_status_is_rejected(self):
        self.approve_a_resume()
        created = self.client.post(f"/api/jobs/{self.job_id}/application-preparations").json()
        response = self.client.patch(f"/api/application-preparations/{created['id']}", json={"status": "bogus"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
