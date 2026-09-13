"""Title alignment scoring tests.

A flat 35-for-any-alias score couldn't tell twenty different roles apart.
These tests exercise the five documented bands (exact / strong-or-related /
generic / weak / unrelated) and confirm qualifier words shift a score within
its band without ever crossing into the one below.
"""

import unittest

from app.matching.titles import (
    EXACT_MATCH_SCORE,
    GENERIC_BAND,
    MAX_TITLE_SCORE,
    NO_MATCH_SCORE,
    STRONG_BAND,
    WEAK_BAND,
    score_title,
)
from tests.support import make_profile

TARGET_TITLES = make_profile().target_titles


class ExactAndAliasTest(unittest.TestCase):
    def test_exact_target_title_gets_full_credit(self):
        self.assertEqual(score_title("Full Stack Engineer", TARGET_TITLES).points, EXACT_MATCH_SCORE)
        self.assertEqual(EXACT_MATCH_SCORE, MAX_TITLE_SCORE)

    def test_founding_engineer_is_an_exact_match(self):
        self.assertEqual(score_title("Founding Engineer", TARGET_TITLES).points, EXACT_MATCH_SCORE)

    def test_forward_deployed_engineer_is_an_exact_match(self):
        self.assertEqual(score_title("Forward Deployed Engineer", TARGET_TITLES).points, EXACT_MATCH_SCORE)

    def test_strong_alias_scores_within_the_strong_band_not_exact(self):
        # Same words as a target title, reordered — a real alias, not the
        # literal configured spelling, so it should land just under exact.
        result = score_title("Software Engineer, Full Stack", TARGET_TITLES)
        self.assertLess(result.points, EXACT_MATCH_SCORE)
        self.assertGreaterEqual(result.points, STRONG_BAND[0])
        self.assertLessEqual(result.points, STRONG_BAND[1])

    def test_hyphenated_and_fused_spellings_score_in_the_strong_band(self):
        for title in ("Full-Stack Engineer", "Fullstack Engineer"):
            with self.subTest(title=title):
                result = score_title(title, TARGET_TITLES)
                self.assertGreaterEqual(result.points, STRONG_BAND[0])

    def test_applied_ai_engineer_with_department_qualifier_is_strong(self):
        result = score_title("Applied AI Engineer, Enterprise", TARGET_TITLES)
        self.assertGreaterEqual(result.points, STRONG_BAND[0])
        self.assertLessEqual(result.points, STRONG_BAND[1])

    def test_full_stack_swe_with_team_qualifier_is_strong_or_related(self):
        result = score_title("Full-Stack SWE, Data Acquisition (Foundations)", TARGET_TITLES)
        self.assertGreaterEqual(result.points, STRONG_BAND[0])
        self.assertLessEqual(result.points, STRONG_BAND[1])


class QualifierTest(unittest.TestCase):
    def test_qualifiers_lower_the_score_within_the_band_but_never_below_its_floor(self):
        clean = score_title("Full Stack Engineer", TARGET_TITLES).points
        one_qualifier = score_title("Software Engineer, Full Stack", TARGET_TITLES).points
        many_qualifiers = score_title(
            "Full-Stack SWE, Data Acquisition (Foundations) Platform Team", TARGET_TITLES
        ).points

        self.assertGreaterEqual(clean, one_qualifier)
        self.assertGreaterEqual(one_qualifier, many_qualifiers)
        self.assertGreaterEqual(many_qualifiers, STRONG_BAND[0])

    def test_department_qualifier_does_not_destroy_a_specific_match(self):
        result = score_title("Backend Engineer, Payments Platform", TARGET_TITLES)
        self.assertGreaterEqual(result.points, STRONG_BAND[0])


class GenericTitleTest(unittest.TestCase):
    def test_generic_software_engineer_is_below_a_specific_match(self):
        # "Software Engineer" itself is an exact configured target title, so
        # use a variant that isn't a literal string match to exercise the
        # generic band specifically.
        generic = score_title("Software Engineer II", TARGET_TITLES).points
        specific = score_title("Founding Engineer", TARGET_TITLES).points

        self.assertGreaterEqual(generic, GENERIC_BAND[0])
        self.assertLessEqual(generic, GENERIC_BAND[1])
        self.assertLess(generic, specific)

    def test_software_engineer_with_qualifier_is_generic_not_thirty_five(self):
        result = score_title("Software Engineer, API Multicloud", TARGET_TITLES)
        self.assertGreaterEqual(result.points, GENERIC_BAND[0])
        self.assertLessEqual(result.points, GENERIC_BAND[1])
        self.assertLess(result.points, EXACT_MATCH_SCORE)


class WeakAndUnrelatedTitleTest(unittest.TestCase):
    def test_adjacent_engineering_title_is_weak_but_plausible(self):
        result = score_title("Data Engineer", TARGET_TITLES)
        specific = score_title("Full Stack Engineer", TARGET_TITLES).points

        self.assertGreaterEqual(result.points, WEAK_BAND[0])
        self.assertLessEqual(result.points, WEAK_BAND[1])
        self.assertLess(result.points, specific)

    def test_no_accidental_substring_match(self):
        # "Maintenance" contains "ai" as a substring but not as a word, so
        # this must not score as an AI-engineer match.
        result = score_title("Maintenance Engineer", TARGET_TITLES)
        self.assertLess(result.points, EXACT_MATCH_SCORE)

    def test_java_does_not_match_javascript_word_boundary(self):
        from app.matching.text import contains_phrase, normalize_text

        self.assertFalse(contains_phrase(normalize_text("JavaScript Engineer"), "java"))

    def test_engineering_manager_scores_low_even_though_not_evaluated_here(self):
        # This title is hard-filtered before scoring in the real pipeline
        # (see test_matching_filters.py); on its own, title scoring alone
        # should not consider it a strong match to any wanted family.
        result = score_title("Engineering Manager", TARGET_TITLES)
        self.assertLess(result.points, STRONG_BAND[0])

    def test_unrelated_title_scores_zero(self):
        result = score_title("Account Executive, FedCiv", [t for t in TARGET_TITLES if "Engineer" in t])
        self.assertEqual(result.points, NO_MATCH_SCORE)


if __name__ == "__main__":
    unittest.main()
