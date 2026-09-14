"""Normalized label matching -- known synonyms, sensitive/demographic
detection, legal/attestation detection, and prepared-answer matching. No
embeddings, no LLM: fixed phrases plus simple normalized overlap."""

import unittest

from app.ats.field_matcher import (
    is_legal_attestation_field,
    is_sensitive_field,
    match_known_field,
    match_prepared_answer,
    normalize_label,
)


class NormalizeLabelTest(unittest.TestCase):
    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(normalize_label("LinkedIn URL:"), "linkedin url")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_label("Full   Name  "), "full name")


class MatchKnownFieldTest(unittest.TestCase):
    def test_work_authorization_question_matches(self):
        self.assertEqual(
            match_known_field("Are you authorized to work in the United States?"), "work_authorization",
        )

    def test_sponsorship_question_matches(self):
        self.assertEqual(
            match_known_field("Will you now or in the future require sponsorship?"), "sponsorship",
        )

    def test_linkedin_profile_label_matches(self):
        self.assertEqual(match_known_field("LinkedIn Profile"), "linkedin")

    def test_linkedin_url_label_matches(self):
        self.assertEqual(match_known_field("LinkedIn URL"), "linkedin")

    def test_relocation_question_matches(self):
        self.assertEqual(match_known_field("Are you willing to relocate?"), "relocation")

    def test_unrecognized_label_returns_none(self):
        self.assertIsNone(match_known_field("What's your favorite programming language?"))

    def test_case_and_punctuation_insensitive(self):
        self.assertEqual(match_known_field("  EMAIL ADDRESS!!  "), "email")


class SensitiveFieldTest(unittest.TestCase):
    def test_race_question_is_sensitive(self):
        self.assertTrue(is_sensitive_field("What is your race/ethnicity?"))

    def test_gender_question_is_sensitive(self):
        self.assertTrue(is_sensitive_field("Gender identity"))

    def test_veteran_question_is_sensitive(self):
        self.assertTrue(is_sensitive_field("Veteran status"))

    def test_disability_question_is_sensitive(self):
        self.assertTrue(is_sensitive_field("Do you have a disability?"))

    def test_ordinary_question_is_not_sensitive(self):
        self.assertFalse(is_sensitive_field("What is your phone number?"))


class LegalAttestationFieldTest(unittest.TestCase):
    def test_signature_field_is_legal(self):
        self.assertTrue(is_legal_attestation_field("Signature"))

    def test_certification_field_is_legal(self):
        self.assertTrue(is_legal_attestation_field("I certify that the information provided is true"))

    def test_background_check_consent_is_legal(self):
        self.assertTrue(is_legal_attestation_field("Background check consent"))

    def test_ordinary_question_is_not_legal(self):
        self.assertFalse(is_legal_attestation_field("What is your email?"))


class MatchPreparedAnswerTest(unittest.TestCase):
    def test_exact_containment_matches(self):
        questions = ["Why are you interested in this role?", "Why this company?"]
        self.assertEqual(match_prepared_answer("Why are you interested in this role?", questions), 0)

    def test_reworded_question_with_majority_word_overlap_matches(self):
        questions = ["Describe your most relevant experience for this role."]
        idx = match_prepared_answer("What is your most relevant experience for the role?", questions)
        self.assertEqual(idx, 0)

    def test_unrelated_label_does_not_match(self):
        questions = ["Why this company?", "Why this role?"]
        self.assertIsNone(match_prepared_answer("What is your desired start date?", questions))

    def test_empty_prepared_list_never_matches(self):
        self.assertIsNone(match_prepared_answer("Why this role?", []))


if __name__ == "__main__":
    unittest.main()
