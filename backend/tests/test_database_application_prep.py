"""`application_preparations`/`application_answers` persistence: creation,
answer edits, user-edit preservation, ready/not-ready state, and job
isolation."""

import unittest

from app import database
from app.application_prep import service
from tests.support import make_job


class ApplicationPrepPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(self.connection, [
            make_job(external_id="1", description="React job."),
            make_job(external_id="2", description="Python job."),
        ])
        self.job_a = database.get_job(self.connection, "greenhouse:acme:1")
        self.job_b = database.get_job(self.connection, "greenhouse:acme:2")

        self.resume_a = database.insert_resume_version(
            self.connection, job_unique_key="greenhouse:acme:1", version=1, latex_source="x",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        database.approve_resume_version(self.connection, self.resume_a)

    def test_preparation_creation_inserts_default_packet_as_placeholders(self):
        prep = service.create_preparation(self.connection, self.job_a)
        self.assertEqual(prep["status"], "draft")
        answers = database.list_application_answers(self.connection, prep["id"])
        self.assertGreater(len(answers), 0)
        self.assertTrue(all(row["needs_user_input"] for row in answers))

    def test_creation_without_an_approved_resume_raises(self):
        with self.assertRaises(service.NoApprovedResumeError):
            service.create_preparation(self.connection, self.job_b)

    def test_answer_edit_marks_user_edited(self):
        prep = service.create_preparation(self.connection, self.job_a)
        answers = database.list_application_answers(self.connection, prep["id"])
        row = answers[0]
        updated = database.update_application_answer(self.connection, row["id"], answer="Custom value", user_edited=True)
        self.assertEqual(updated["answer"], "Custom value")
        self.assertEqual(updated["user_edited"], 1)

    def test_user_edited_answer_is_preserved_across_regeneration(self):
        import json
        import tempfile
        from pathlib import Path

        from tests.support import make_applicant_profile_dict

        prep = service.create_preparation(self.connection, self.job_a)
        answers = database.list_application_answers(self.connection, prep["id"])
        full_name_row = next(a for a in answers if a["question_id"] == "full_name")
        database.update_application_answer(self.connection, full_name_row["id"], answer="Edited Name", user_edited=True)

        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "applicant_profile.json"
            profile_path.write_text(json.dumps(make_applicant_profile_dict()))
            service.generate_preparation(
                self.connection, prep["id"], applicant_profile_path=profile_path,
                master_resume_path="config/resume_master.json",
            )

        after = database.get_application_answer(self.connection, full_name_row["id"])
        self.assertEqual(after["answer"], "Edited Name")

    def test_ready_state_requires_no_unmet_required_answers(self):
        import json
        import tempfile
        from pathlib import Path

        from tests.support import make_applicant_profile_dict

        prep = service.create_preparation(self.connection, self.job_a)
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "applicant_profile.json"
            profile_path.write_text(json.dumps(make_applicant_profile_dict()))
            generated = service.generate_preparation(
                self.connection, prep["id"], applicant_profile_path=profile_path,
                master_resume_path="config/resume_master.json",
            )
        # No LLM provider configured -> why_role/why_company/experience
        # summary remain needs_input -> not ready.
        self.assertEqual(generated["status"], "needs_input")

    def test_ready_state_becomes_ready_once_required_answers_are_filled(self):
        prep = service.create_preparation(self.connection, self.job_a)
        for row in database.list_application_answers(self.connection, prep["id"]):
            if row["required"]:
                database.update_application_answer(self.connection, row["id"], answer="filled", user_edited=True, needs_user_input=False)
        service.recompute_status(self.connection, prep["id"])
        updated = database.get_application_preparation(self.connection, prep["id"])
        self.assertEqual(updated["status"], "ready")

    def test_optional_unresolved_question_does_not_block_ready(self):
        prep = service.create_preparation(self.connection, self.job_a)
        for row in database.list_application_answers(self.connection, prep["id"]):
            if row["required"]:
                database.update_application_answer(self.connection, row["id"], answer="filled", user_edited=True, needs_user_input=False)
        service.recompute_status(self.connection, prep["id"])
        updated = database.get_application_preparation(self.connection, prep["id"])
        # Optional questions (e.g. portfolio) may still be unanswered.
        optional_unanswered = [
            row for row in database.list_application_answers(self.connection, prep["id"])
            if not row["required"] and row["needs_user_input"]
        ]
        self.assertTrue(len(optional_unanswered) > 0)
        self.assertEqual(updated["status"], "ready")

    def test_job_isolation_between_preparations(self):
        prep_a = service.create_preparation(self.connection, self.job_a)
        resume_b = database.insert_resume_version(
            self.connection, job_unique_key="greenhouse:acme:2", version=1, latex_source="y",
            pdf_path=None, compiler_status="unavailable", compile_log=None, page_count=None, tailoring_analysis={},
        )
        database.approve_resume_version(self.connection, resume_b)
        prep_b = service.create_preparation(self.connection, self.job_b)

        self.assertNotEqual(prep_a["id"], prep_b["id"])
        answers_a = database.list_application_answers(self.connection, prep_a["id"])
        answers_b = database.list_application_answers(self.connection, prep_b["id"])
        ids_a = {row["id"] for row in answers_a}
        ids_b = {row["id"] for row in answers_b}
        self.assertEqual(ids_a & ids_b, set())

    def test_adding_a_custom_question(self):
        prep = service.create_preparation(self.connection, self.job_a)
        answer = service.add_custom_question(
            self.connection, prep["id"], "How many years of Python experience?", "text", "experience",
        )
        self.assertTrue(answer["needs_user_input"])
        answers = database.list_application_answers(self.connection, prep["id"])
        self.assertIn("How many years of Python experience?", [row["question_text"] for row in answers])

    def test_preparation_list_is_never_filtered_out(self):
        service.create_preparation(self.connection, self.job_a)
        service.create_preparation(self.connection, self.job_a)
        preps = database.list_application_preparations(self.connection, "greenhouse:acme:1")
        self.assertEqual(len(preps), 2)


if __name__ == "__main__":
    unittest.main()
