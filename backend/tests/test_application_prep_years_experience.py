"""Deterministic years-of-experience calculation. Never guesses from a
skill merely listed in the skills section -- only from bullets that
explicitly demonstrate a technology within a dated experience entry."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.application_prep.years_experience import calculate_years_of_experience
from app.resume.master import load_master_resume
from tests.support import make_master_resume_dict


def _load_master(**overrides):
    payload = make_master_resume_dict(**overrides)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume_master.json"
        path.write_text(json.dumps(payload))
        return load_master_resume(path)


class CalculateYearsOfExperienceTest(unittest.TestCase):
    def test_dated_evidence_that_explicitly_mentions_the_skill_is_calculated(self):
        master = _load_master(experience=[
            {
                "id": "exp_a", "company": "Acme", "title": "Engineer",
                "start_date": "Jan 2020", "end_date": "Jan 2022",
                "bullets": [{"id": "exp_a_b1", "text": "Built features using React and TypeScript."}],
            },
        ])
        result = calculate_years_of_experience(master, "React", today=date(2026, 1, 1))
        self.assertTrue(result.supported)
        self.assertAlmostEqual(result.years, 2.0, delta=0.1)
        self.assertEqual(result.evidence_ids, ["exp_a"])

    def test_skill_only_listed_in_skills_section_is_not_supported(self):
        # "Python" appears only in the flat skills list, not in any bullet.
        master = _load_master(
            experience=[
                {
                    "id": "exp_a", "company": "Acme", "title": "Engineer",
                    "start_date": "Jan 2020", "end_date": "Jan 2022",
                    "bullets": [{"id": "exp_a_b1", "text": "Built features using React."}],
                },
            ],
            skills={"languages": ["Python"], "frontend": ["React"]},
        )
        result = calculate_years_of_experience(master, "Python", today=date(2026, 1, 1))
        self.assertFalse(result.supported)
        self.assertIsNone(result.years)

    def test_sums_multiple_dated_entries_demonstrating_the_same_skill(self):
        master = _load_master(experience=[
            {
                "id": "exp_a", "company": "Acme", "title": "Engineer",
                "start_date": "Jan 2018", "end_date": "Jan 2020",
                "bullets": [{"id": "exp_a_b1", "text": "Built features using Python."}],
            },
            {
                "id": "exp_b", "company": "Beta", "title": "Engineer",
                "start_date": "Jan 2020", "end_date": "Jan 2022",
                "bullets": [{"id": "exp_b_b1", "text": "Built services using Python and SQL."}],
            },
        ])
        result = calculate_years_of_experience(master, "Python", today=date(2026, 1, 1))
        self.assertTrue(result.supported)
        self.assertAlmostEqual(result.years, 4.0, delta=0.1)
        self.assertEqual(set(result.evidence_ids), {"exp_a", "exp_b"})

    def test_present_end_date_is_calculated_to_today(self):
        master = _load_master(experience=[
            {
                "id": "exp_a", "company": "Acme", "title": "Engineer",
                "start_date": "Jan 2024", "end_date": "Present",
                "bullets": [{"id": "exp_a_b1", "text": "Built features using React."}],
            },
        ])
        result = calculate_years_of_experience(master, "React", today=date(2026, 1, 1))
        self.assertTrue(result.supported)
        self.assertAlmostEqual(result.years, 2.0, delta=0.1)

    def test_unparseable_dates_are_not_guessed(self):
        master = _load_master(experience=[
            {
                "id": "exp_a", "company": "Acme", "title": "Engineer",
                "start_date": "sometime in the past", "end_date": "later",
                "bullets": [{"id": "exp_a_b1", "text": "Built features using React."}],
            },
        ])
        result = calculate_years_of_experience(master, "React")
        self.assertFalse(result.supported)
        self.assertIn("Could not reliably parse", result.reason)

    def test_no_matching_bullet_at_all_is_not_supported(self):
        master = _load_master(experience=[
            {
                "id": "exp_a", "company": "Acme", "title": "Engineer",
                "start_date": "Jan 2020", "end_date": "Jan 2022",
                "bullets": [{"id": "exp_a_b1", "text": "Built features using Java."}],
            },
        ])
        result = calculate_years_of_experience(master, "Kubernetes")
        self.assertFalse(result.supported)


if __name__ == "__main__":
    unittest.main()
