"""Tests for loading/validating `applicant_profile.json`."""

import json
import tempfile
import unittest
from pathlib import Path

from app.application_prep.profile import ApplicantProfileError, load_applicant_profile
from tests.support import make_applicant_profile_dict


class LoadApplicantProfileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def write(self, payload) -> Path:
        path = self.tmp_path / "applicant_profile.json"
        path.write_text(json.dumps(payload))
        return path

    def test_valid_profile_loads_successfully(self):
        path = self.write(make_applicant_profile_dict())
        profile = load_applicant_profile(path)
        self.assertEqual(profile.identity.full_name, "Test Candidate")
        self.assertEqual(profile.work_authorization.authorized_to_work, True)
        self.assertEqual(profile.preferences.salary_expectation.mode, "user_input")

    def test_missing_file_raises_clean_setup_message(self):
        missing = self.tmp_path / "does_not_exist.json"
        with self.assertRaises(ApplicantProfileError) as ctx:
            load_applicant_profile(missing)
        self.assertIn("No applicant profile found", str(ctx.exception))
        self.assertIn("applicant_profile.example.json", str(ctx.exception))

    def test_malformed_json_is_rejected(self):
        path = self.tmp_path / "applicant_profile.json"
        path.write_text("{not valid json")
        with self.assertRaises(ApplicantProfileError) as ctx:
            load_applicant_profile(path)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_non_object_json_is_rejected(self):
        path = self.write(["not", "an", "object"])
        with self.assertRaises(ApplicantProfileError):
            load_applicant_profile(path)

    def test_work_authorization_must_be_boolean_or_null(self):
        payload = make_applicant_profile_dict()
        payload["work_authorization"]["authorized_to_work"] = "yes"
        path = self.write(payload)
        with self.assertRaises(ApplicantProfileError):
            load_applicant_profile(path)

    def test_missing_sections_default_to_empty_rather_than_erroring(self):
        path = self.write({})
        profile = load_applicant_profile(path)
        self.assertEqual(profile.identity.full_name, "")
        self.assertEqual(profile.education, [])

    def test_salary_expectation_range_mode_is_parsed(self):
        payload = make_applicant_profile_dict()
        payload["preferences"]["salary_expectation"] = {"mode": "range", "min": 120000, "max": 150000}
        path = self.write(payload)
        profile = load_applicant_profile(path)
        self.assertEqual(profile.preferences.salary_expectation.mode, "range")
        self.assertEqual(profile.preferences.salary_expectation.min, 120000)
        self.assertEqual(profile.preferences.salary_expectation.max, 150000)

    def test_salary_expectation_min_must_be_an_integer(self):
        payload = make_applicant_profile_dict()
        payload["preferences"]["salary_expectation"] = {"mode": "range", "min": "a lot", "max": 150000}
        path = self.write(payload)
        with self.assertRaises(ApplicantProfileError):
            load_applicant_profile(path)

    def test_custom_facts_must_be_string_values(self):
        payload = make_applicant_profile_dict()
        payload["custom_facts"] = {"favorite_language": 123}
        path = self.write(payload)
        with self.assertRaises(ApplicantProfileError):
            load_applicant_profile(path)

    def test_example_config_is_itself_valid(self):
        # Confirms the committed example config parses cleanly.
        profile = load_applicant_profile(Path("config/applicant_profile.example.json"))
        self.assertEqual(profile.identity.full_name, "Jordan Example")

    def test_real_applicant_profile_remains_gitignored(self):
        import subprocess

        result = subprocess.run(
            ["git", "check-ignore", "-q", "backend/config/applicant_profile.json"],
            cwd=Path(__file__).resolve().parents[2],
        )
        self.assertEqual(result.returncode, 0, "backend/config/applicant_profile.json must be gitignored")


if __name__ == "__main__":
    unittest.main()
