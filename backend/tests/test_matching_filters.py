"""Hard filtering tests."""

import unittest

from app.matching.filters import evaluate_filters
from tests.support import make_profile

PROFILE = make_profile()


class EvaluateFiltersTest(unittest.TestCase):
    def test_engineering_title_passes(self):
        result = evaluate_filters("Full Stack Engineer", PROFILE)
        self.assertFalse(result.filtered)
        self.assertIsNone(result.reason)

    def test_excluded_title_term_is_filtered(self):
        result = evaluate_filters("Software Engineering Intern", PROFILE)
        self.assertTrue(result.filtered)
        self.assertIn("intern", result.reason.lower())

    def test_new_grad_is_filtered(self):
        result = evaluate_filters("New Grad Software Engineer", PROFILE)
        self.assertTrue(result.filtered)

    def test_engineering_manager_is_filtered(self):
        result = evaluate_filters("Engineering Manager", PROFILE)
        self.assertTrue(result.filtered)

    def test_director_is_filtered(self):
        result = evaluate_filters("Director of Engineering", PROFILE)
        self.assertTrue(result.filtered)

    def test_non_engineering_title_is_filtered(self):
        result = evaluate_filters("Account Executive, FedCiv", PROFILE)
        self.assertTrue(result.filtered)
        self.assertIn("outside target role families", result.reason)

    def test_general_counsel_is_filtered(self):
        result = evaluate_filters("Associate General Counsel, Privacy Compliance", PROFILE)
        self.assertTrue(result.filtered)

    def test_senior_title_is_not_filtered(self):
        # A senior title should lower the score, never trigger a hard reject.
        result = evaluate_filters("Senior Software Engineer", PROFILE)
        self.assertFalse(result.filtered)

    def test_developer_title_is_not_filtered(self):
        result = evaluate_filters("Backend Developer", PROFILE)
        self.assertFalse(result.filtered)


class ManagementTitleFilterTest(unittest.TestCase):
    """Built-in management/leadership exclusion, independent of profile config."""

    def test_reversed_word_order_management_title_is_filtered(self):
        # The real case this was added for: "engineering manager" as a
        # configured excluded phrase doesn't match when the words are in
        # the other order.
        result = evaluate_filters("Manager, Applied AI Engineering (Codex)", PROFILE)
        self.assertTrue(result.filtered)
        self.assertIn("management", result.reason.lower())

    def test_bare_manager_is_filtered(self):
        result = evaluate_filters("Engineering Manager, Platform", PROFILE)
        self.assertTrue(result.filtered)

    def test_director_title_is_filtered(self):
        result = evaluate_filters("Director, Site Reliability Engineering", PROFILE)
        self.assertTrue(result.filtered)

    def test_vp_abbreviation_is_filtered(self):
        result = evaluate_filters("VP, Engineering", PROFILE)
        self.assertTrue(result.filtered)

    def test_head_of_is_filtered(self):
        result = evaluate_filters("Head of Engineering", PROFILE)
        self.assertTrue(result.filtered)

    def test_ic_titles_are_not_accidentally_filtered(self):
        for title in (
            "Applied AI Engineer, Enterprise",
            "Full Stack Engineer",
            "Software Engineer, Full Stack",
            "Staff Software Engineer",
            "Engineering Lead",
            "Technical Lead, Engineering",
            "Tech Lead, Software Engineering",
        ):
            with self.subTest(title=title):
                result = evaluate_filters(title, PROFILE)
                self.assertFalse(result.filtered, f"'{title}' should not be filtered: {result.reason}")

    def test_lead_alone_is_not_treated_as_management(self):
        # Explicit requirement: "lead" must not be a management marker —
        # Lead/Technical Lead roles are often still IC roles.
        result = evaluate_filters("Lead Software Engineer", PROFILE)
        self.assertFalse(result.filtered)


if __name__ == "__main__":
    unittest.main()
