"""Profile loading and validation tests."""

import json
import tempfile
import unittest
from pathlib import Path

from app.profile import ProfileError, load_profile

VALID = {
    "profile_id": "local",
    "years_experience": 4,
    "target_titles": ["Full Stack Engineer"],
    "primary_locations": ["San Francisco"],
    "allow_remote_us": True,
    "allow_relocation_us": True,
    "primary_skills": ["React", "Python"],
    "secondary_skills": ["Docker"],
    "excluded_title_terms": ["intern"],
}


class LoadProfileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def write_profile(self, payload) -> Path:
        path = self.tmp_path / "profile.json"
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_a_valid_profile(self):
        profile = load_profile(self.write_profile(VALID))

        self.assertEqual(profile.profile_id, "local")
        self.assertEqual(profile.years_experience, 4)
        self.assertEqual(profile.target_titles, ["Full Stack Engineer"])
        self.assertTrue(profile.allow_remote_us)
        self.assertTrue(profile.allow_relocation_us)
        self.assertEqual(profile.primary_skills, ["React", "Python"])
        self.assertEqual(profile.secondary_skills, ["Docker"])
        self.assertEqual(profile.excluded_title_terms, ["intern"])

    def test_example_profile_file_is_valid(self):
        example = Path(__file__).resolve().parents[1] / "config" / "profile.example.json"

        profile = load_profile(example)

        self.assertEqual(profile.profile_id, "local")
        self.assertIn("Full Stack Engineer", profile.target_titles)

    def test_excluded_title_terms_may_be_omitted(self):
        payload = {k: v for k, v in VALID.items() if k != "excluded_title_terms"}

        profile = load_profile(self.write_profile(payload))

        self.assertEqual(profile.excluded_title_terms, [])

    def test_secondary_skills_may_be_omitted(self):
        payload = {k: v for k, v in VALID.items() if k != "secondary_skills"}

        profile = load_profile(self.write_profile(payload))

        self.assertEqual(profile.secondary_skills, [])

    def test_missing_file(self):
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.tmp_path / "nope.json")
        self.assertIn("not found", str(ctx.exception))

    def test_invalid_json(self):
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile("{not json"))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_top_level_must_be_an_object(self):
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile([1, 2, 3]))
        self.assertIn("JSON object", str(ctx.exception))

    def test_missing_profile_id(self):
        payload = {k: v for k, v in VALID.items() if k != "profile_id"}
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile(payload))
        self.assertIn("profile_id", str(ctx.exception))

    def test_blank_profile_id(self):
        payload = {**VALID, "profile_id": "   "}
        with self.assertRaises(ProfileError):
            load_profile(self.write_profile(payload))

    def test_years_experience_must_be_an_integer(self):
        payload = {**VALID, "years_experience": "four"}
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile(payload))
        self.assertIn("years_experience", str(ctx.exception))

    def test_years_experience_must_not_be_negative(self):
        payload = {**VALID, "years_experience": -1}
        with self.assertRaises(ProfileError):
            load_profile(self.write_profile(payload))

    def test_target_titles_must_be_a_non_empty_list(self):
        payload = {**VALID, "target_titles": []}
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile(payload))
        self.assertIn("target_titles", str(ctx.exception))

    def test_target_titles_must_be_strings(self):
        payload = {**VALID, "target_titles": [123]}
        with self.assertRaises(ProfileError):
            load_profile(self.write_profile(payload))

    def test_primary_skills_must_be_a_non_empty_list(self):
        payload = {**VALID, "primary_skills": []}
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile(payload))
        self.assertIn("primary_skills", str(ctx.exception))

    def test_primary_locations_must_be_a_non_empty_list(self):
        payload = {**VALID, "primary_locations": []}
        with self.assertRaises(ProfileError):
            load_profile(self.write_profile(payload))

    def test_allow_remote_us_must_be_boolean(self):
        payload = {**VALID, "allow_remote_us": "yes"}
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write_profile(payload))
        self.assertIn("allow_remote_us", str(ctx.exception))

    def test_allow_relocation_us_must_be_boolean(self):
        payload = {**VALID, "allow_relocation_us": 1}
        with self.assertRaises(ProfileError):
            load_profile(self.write_profile(payload))

    def test_rejects_personal_identity_fields(self):
        for field in ("name", "email", "phone", "immigration_status", "ssn"):
            payload = {**VALID, field: "should not be here"}
            with self.assertRaises(ProfileError) as ctx:
                load_profile(self.write_profile(payload))
            self.assertIn(field, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
