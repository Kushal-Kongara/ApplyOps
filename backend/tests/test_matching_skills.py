"""Skill alignment scoring tests.

Dividing matches by the *entire* profile skill list punished a job for not
mentioning niche tools it was never going to mention. These tests confirm
the weighted primary/secondary formula fixes that without losing the
earlier de-duplication guarantees (no double-counting an alias, no double-
counting a repeated mention).
"""

import unittest

from app.matching.skills import MAX_SKILL_SCORE, PRIMARY_CAP, SECONDARY_CAP, score_skills

PRIMARY = ["React", "TypeScript", "Python", "Node.js", "PostgreSQL", "AWS"]
SECONDARY = [
    "JavaScript", "NestJS", "Java", "SQL", "Prisma", "REST APIs", "ECS", "Fargate",
    "RDS", "S3", "CloudFront", "Docker", "GitHub Actions", "CI/CD", "LLMs",
    "AI Agents", "RAG", "Prompt Engineering", "Vapi", "ElevenLabs",
]


class WeightedScoreTest(unittest.TestCase):
    def test_all_primary_and_secondary_present_gets_full_credit(self):
        text = " ".join(PRIMARY + SECONDARY)
        result = score_skills(text, PRIMARY, SECONDARY)

        self.assertEqual(result.points, MAX_SKILL_SCORE)

    def test_primary_cap_plus_secondary_cap_equals_max(self):
        self.assertEqual(PRIMARY_CAP + SECONDARY_CAP, MAX_SKILL_SCORE)

    def test_all_primary_skills_alone_gets_strong_credit_not_a_sixth(self):
        # The exact complaint being fixed: a posting naming every skill that
        # actually matters should not score ~6/30 just because the profile
        # also lists twenty secondary tools it never mentions.
        text = "We build with React, TypeScript, Python, Node.js, PostgreSQL, and AWS."
        result = score_skills(text, PRIMARY, SECONDARY)

        self.assertEqual(result.points, PRIMARY_CAP)
        self.assertGreater(result.points, MAX_SKILL_SCORE // 2)

    def test_missing_unrelated_secondary_skills_is_not_an_excessive_penalty(self):
        # All primary present, zero secondary present — still a strong score.
        text = "React, TypeScript, Python, Node.js, PostgreSQL, AWS."
        result = score_skills(text, PRIMARY, SECONDARY)

        self.assertEqual(set(result.unmatched_secondary), set(SECONDARY))
        self.assertEqual(result.points, PRIMARY_CAP)

    def test_primary_skill_is_worth_more_than_a_secondary_skill(self):
        one_primary = score_skills("We use React daily.", PRIMARY, SECONDARY).points
        one_secondary = score_skills("We use Docker daily.", PRIMARY, SECONDARY).points

        self.assertGreater(one_primary, one_secondary)

    def test_partial_primary_match_is_proportional(self):
        result = score_skills("We use React every day.", PRIMARY, SECONDARY)
        self.assertEqual(result.matched_primary, ["React"])
        self.assertEqual(result.points, round(PRIMARY_CAP * 1 / len(PRIMARY)))

    def test_aliases_are_recognized_for_both_tiers(self):
        text = "Backend is Node.js with Postgres. Frontend is ReactJS. We use continuous integration."
        result = score_skills(text, PRIMARY, SECONDARY)

        self.assertIn("Node.js", result.matched_primary)
        self.assertIn("PostgreSQL", result.matched_primary)
        self.assertIn("React", result.matched_primary)
        self.assertIn("CI/CD", result.matched_secondary)

    def test_no_double_counting_of_aliases_for_the_same_skill(self):
        text = "Node backend. We love Node.js. Some call it NodeJS."
        result = score_skills(text, PRIMARY, [])

        self.assertEqual(result.matched_primary, ["Node.js"])
        self.assertEqual(result.points, round(PRIMARY_CAP * 1 / len(PRIMARY)))

    def test_repeated_mentions_of_the_same_skill_do_not_add_points(self):
        once = score_skills("Python. Python. Python is used everywhere, in Python.", PRIMARY, [])
        single_mention = score_skills("Python.", PRIMARY, [])

        self.assertEqual(once.points, single_mention.points)
        self.assertEqual(once.matched_primary, ["Python"])

    def test_node_js_does_not_falsely_trigger_the_javascript_secondary_alias(self):
        result = score_skills("We use Node.js on the backend.", PRIMARY, ["JavaScript"])

        self.assertIn("Node.js", result.matched_primary)
        self.assertEqual(result.unmatched_secondary, ["JavaScript"])

    def test_javascript_and_typescript_may_both_match_independently(self):
        # They overlap conceptually, but each is a distinct, separately
        # meaningful skill a posting can mention or not — matching both is
        # not a double-count of one skill's aliases.
        result = score_skills("Strong TypeScript and JavaScript skills.", ["TypeScript"], ["JavaScript"])

        self.assertEqual(result.matched_primary, ["TypeScript"])
        self.assertEqual(result.matched_secondary, ["JavaScript"])

    def test_unmatched_skills_are_labeled_as_not_found_not_as_required(self):
        result = score_skills("Just Python here.", PRIMARY, SECONDARY)

        self.assertIn("AWS", result.unmatched_primary)
        # The API surface is "unmatched", not "required" — no field anywhere
        # claims the posting demands these.

    def test_unknown_skill_falls_back_to_its_own_name(self):
        result = score_skills("We use Kubernetes extensively.", ["Kubernetes"], [])
        self.assertEqual(result.matched_primary, ["Kubernetes"])

    def test_no_profile_skills_scores_zero(self):
        result = score_skills("Anything at all.", [], [])
        self.assertEqual(result.points, 0)

    def test_evidence_is_short_and_present_for_matches(self):
        result = score_skills("We use Python.", ["Python"], [])
        self.assertEqual(len(result.evidence), 1)
        self.assertIn("Python", result.evidence[0])

    def test_flat_matched_and_unmatched_properties_combine_both_tiers(self):
        result = score_skills("Python and Docker.", ["Python"], ["Docker", "Vapi"])

        self.assertEqual(result.matched, ["Python", "Docker"])
        self.assertEqual(result.unmatched, ["Vapi"])


if __name__ == "__main__":
    unittest.main()
