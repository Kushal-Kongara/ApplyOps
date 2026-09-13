"""Tests for loading/validating `resume_master.json`."""

import json
import tempfile
import unittest
from pathlib import Path

from app.resume.master import MasterResumeError, load_master_resume
from tests.support import make_master_resume_dict


class LoadMasterResumeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def write(self, payload) -> Path:
        path = self.tmp_path / "resume_master.json"
        path.write_text(json.dumps(payload))
        return path

    def test_valid_master_resume_loads_successfully(self):
        path = self.write(make_master_resume_dict())
        master = load_master_resume(path)
        self.assertEqual(master.contact.name, "Test Candidate")
        self.assertEqual(len(master.experience), 2)
        self.assertEqual(master.experience[0].bullets[0].id, "exp_acme_b1")

    def test_missing_file_raises_clean_setup_message(self):
        missing = self.tmp_path / "does_not_exist.json"
        with self.assertRaises(MasterResumeError) as ctx:
            load_master_resume(missing)
        self.assertIn("No master resume found", str(ctx.exception))
        self.assertIn("resume_master.example.json", str(ctx.exception))

    def test_malformed_json_is_rejected(self):
        path = self.tmp_path / "resume_master.json"
        path.write_text("{not valid json")
        with self.assertRaises(MasterResumeError) as ctx:
            load_master_resume(path)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_missing_required_field_is_rejected(self):
        payload = make_master_resume_dict()
        del payload["contact"]
        path = self.write(payload)
        with self.assertRaises(MasterResumeError) as ctx:
            load_master_resume(path)
        self.assertIn("contact", str(ctx.exception))

    def test_empty_bullets_list_is_rejected(self):
        payload = make_master_resume_dict()
        payload["experience"][0]["bullets"] = []
        path = self.write(payload)
        with self.assertRaises(MasterResumeError):
            load_master_resume(path)

    def test_duplicate_evidence_id_across_sections_is_rejected(self):
        payload = make_master_resume_dict()
        # Reuse an experience bullet id as an achievement id.
        payload["achievements"] = [{"id": "exp_acme_b1", "text": "Duplicate id achievement."}]
        path = self.write(payload)
        with self.assertRaises(MasterResumeError) as ctx:
            load_master_resume(path)
        self.assertIn("duplicate id", str(ctx.exception))

    def test_missing_bullet_id_is_rejected(self):
        payload = make_master_resume_dict()
        del payload["experience"][0]["bullets"][0]["id"]
        path = self.write(payload)
        with self.assertRaises(MasterResumeError):
            load_master_resume(path)

    def test_projects_and_achievements_are_optional(self):
        payload = make_master_resume_dict()
        del payload["achievements"]
        path = self.write(payload)
        master = load_master_resume(path)
        self.assertEqual(master.achievements, [])
        self.assertEqual(master.projects, [])

    def test_skills_must_be_non_empty_object_of_string_lists(self):
        payload = make_master_resume_dict()
        payload["skills"] = {"languages": [1, 2, 3]}
        path = self.write(payload)
        with self.assertRaises(MasterResumeError):
            load_master_resume(path)


if __name__ == "__main__":
    unittest.main()
