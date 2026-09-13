"""End-to-end `evaluate_job` tests: component totals, bounds, and filtering."""

import unittest

from app.matching.scorer import MAX_TOTAL_SCORE, evaluate_job
from tests.support import make_job, make_profile

PROFILE = make_profile()


class EvaluateJobTest(unittest.TestCase):
    def test_total_score_equals_sum_of_components(self):
        job = make_job(
            title="Full Stack Engineer",
            location="San Francisco, CA",
            description="React, TypeScript, Python, AWS. 2-5 years experience. Own the full stack.",
        )
        match = evaluate_job(job, PROFILE)

        expected = (
            match.components.title
            + match.components.skills
            + match.components.location
            + match.components.seniority
            + match.components.product
        )
        self.assertEqual(match.total_score, expected)

    def test_score_is_never_below_zero_or_above_hundred(self):
        cases = [
            make_job(title="Full Stack Engineer", location="San Francisco, CA", description="React Python AWS"),
            make_job(title="Staff Principal Architect", location="Antarctica", description=""),
            make_job(title="Account Executive", location="", description=""),
        ]
        for job in cases:
            match = evaluate_job(job, PROFILE)
            with self.subTest(title=job.title):
                self.assertGreaterEqual(match.total_score, 0)
                self.assertLessEqual(match.total_score, 100)
                self.assertLessEqual(match.total_score, MAX_TOTAL_SCORE)

    def test_visa_signal_never_changes_the_score(self):
        base = make_job(
            title="Full Stack Engineer",
            location="San Francisco, CA",
            description="React, TypeScript, Python.",
        )
        with_risk = make_job(
            title="Full Stack Engineer",
            location="San Francisco, CA",
            description="React, TypeScript, Python. We do not provide sponsorship.",
        )

        self.assertEqual(evaluate_job(base, PROFILE).total_score, evaluate_job(with_risk, PROFILE).total_score)

    def test_filtered_job_is_still_scored(self):
        job = make_job(title="Software Engineering Intern", description="React, TypeScript, Python.")
        match = evaluate_job(job, PROFILE)

        self.assertTrue(match.filter_result.filtered)
        self.assertGreater(match.total_score, 0)

    def test_inspectable_explanation_fields_are_present(self):
        job = make_job(
            title="Full Stack Engineer",
            location="San Francisco, CA",
            description="React, TypeScript. We do not provide sponsorship.",
        )
        match = evaluate_job(job, PROFILE)

        self.assertTrue(match.title_evidence)
        self.assertTrue(match.location_evidence)
        self.assertTrue(match.seniority_evidence)
        self.assertIn("React", match.matched_skills)
        self.assertEqual(match.visa.status, "sponsorship_risk")
        self.assertIsNotNone(match.visa.evidence)


if __name__ == "__main__":
    unittest.main()
