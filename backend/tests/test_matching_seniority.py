"""Seniority alignment scoring tests."""

import unittest

from app.matching.seniority import (
    MAX_SENIORITY_SCORE,
    ExperienceRange,
    classify_seniority,
    extract_experience_years,
)

YEARS_EXPERIENCE = 4


class ExtractExperienceYearsTest(unittest.TestCase):
    def test_extracts_a_range(self):
        self.assertEqual(extract_experience_years("2-5 years of experience"), ExperienceRange(2, 5))
        self.assertEqual(extract_experience_years("3 to 5 years experience"), ExperienceRange(3, 5))

    def test_extracts_an_open_ended_minimum(self):
        self.assertEqual(extract_experience_years("7+ years of experience"), ExperienceRange(7, None))

    def test_extracts_a_single_number(self):
        self.assertEqual(extract_experience_years("5 years of professional experience"), ExperienceRange(5, 5))

    def test_returns_none_when_no_experience_mentioned(self):
        self.assertIsNone(extract_experience_years("We build great software."))

    def test_range_takes_priority_over_open_ended_pattern(self):
        # Guards against the "+" pattern greedily matching inside a range.
        result = extract_experience_years("2-5+ years of experience")
        self.assertEqual(result, ExperienceRange(2, 5))

    def test_at_least_phrasing(self):
        self.assertEqual(extract_experience_years("At least 5 years of experience."), ExperienceRange(5, None))

    def test_minimum_of_phrasing(self):
        self.assertEqual(
            extract_experience_years("A minimum of 5 years of professional experience required."),
            ExperienceRange(5, None),
        )

    def test_written_number_or_more_phrasing(self):
        self.assertEqual(
            extract_experience_years("Five or more years of relevant experience."), ExperienceRange(5, None)
        )

    def test_written_number_with_professional_experience(self):
        self.assertEqual(
            extract_experience_years("Seven years of professional experience required."), ExperienceRange(7, 7)
        )

    def test_en_dash_range(self):
        self.assertEqual(extract_experience_years("3–5 years of experience preferred."), ExperienceRange(3, 5))

    def test_prefers_engineering_experience_context_over_an_earlier_unrelated_number(self):
        # "3-5 year old" (the company's age) appears first but has no
        # experience context nearby; "6-8 years of professional experience"
        # appears later but is the real requirement — it should win even
        # though it isn't first in reading order.
        text = (
            "This 3-5 year old startup is growing fast, with a relaxed and casual "
            "environment for the whole team. We need someone with 6-8 years of "
            "professional experience in backend systems."
        )
        result = extract_experience_years(text)
        self.assertEqual(result, ExperienceRange(6, 8))

    def test_bare_number_with_no_context_is_still_returned_as_a_fallback(self):
        # No pattern anywhere is near "experience"/"professional"/"industry"
        # — still returns the only candidate found, rather than nothing.
        result = extract_experience_years("This is a 5-6 year old codebase we are modernizing.")
        self.assertEqual(result, ExperienceRange(5, 6))


class ClassifySeniorityTest(unittest.TestCase):
    def test_mid_range_experience_is_strong(self):
        result = classify_seniority("Full Stack Engineer", "2-5 years of experience required.", YEARS_EXPERIENCE)
        self.assertEqual(result.points, MAX_SENIORITY_SCORE)

    def test_no_experience_mentioned_is_neutral_not_perfect(self):
        # Unknown seniority must not score as if it were a confirmed fit.
        result = classify_seniority("Full Stack Engineer", "Build great things with us.", YEARS_EXPERIENCE)
        self.assertGreater(result.points, 0)
        self.assertLess(result.points, MAX_SENIORITY_SCORE)

        # And it should score the same as an explicit 5-6 year requirement —
        # deliberately neutral, not assumed compatible.
        partial = classify_seniority("Full Stack Engineer", "5-6 years of experience.", YEARS_EXPERIENCE)
        self.assertEqual(result.points, partial.points)

    def test_senior_title_is_partial(self):
        result = classify_seniority("Senior Full Stack Engineer", "", YEARS_EXPERIENCE)
        self.assertGreater(result.points, 0)
        self.assertLess(result.points, MAX_SENIORITY_SCORE)

    def test_five_to_six_years_is_partial(self):
        result = classify_seniority("Full Stack Engineer", "5-6 years of experience.", YEARS_EXPERIENCE)
        self.assertGreater(result.points, 0)
        self.assertLess(result.points, MAX_SENIORITY_SCORE)

    def test_staff_title_is_low(self):
        result = classify_seniority("Staff Software Engineer", "", YEARS_EXPERIENCE)
        senior = classify_seniority("Senior Full Stack Engineer", "", YEARS_EXPERIENCE)
        self.assertLess(result.points, senior.points)

    def test_principal_title_is_low(self):
        result = classify_seniority("Principal Engineer", "", YEARS_EXPERIENCE)
        self.assertLess(result.points, MAX_SENIORITY_SCORE)

    def test_seven_plus_years_is_low(self):
        result = classify_seniority("Software Engineer", "7+ years of experience required.", YEARS_EXPERIENCE)
        partial = classify_seniority("Full Stack Engineer", "5-6 years of experience.", YEARS_EXPERIENCE)
        self.assertLess(result.points, partial.points)

    def test_architect_title_is_low(self):
        result = classify_seniority("Cloud Architect", "", YEARS_EXPERIENCE)
        self.assertLess(result.points, MAX_SENIORITY_SCORE)


if __name__ == "__main__":
    unittest.main()
