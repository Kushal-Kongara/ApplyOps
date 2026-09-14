"""`validate_answer`: reuses the resume rewrite validator's fabrication
checks (technology/numeric/duration/leadership) for generated application
answers -- one set of anti-fabrication rules, not two."""

import unittest

from app.application_prep.answer_validator import validate_answer
from app.resume.tailor import keyword_universe

EVIDENCE = (
    "Built production full-stack features using React, TypeScript, JavaScript, "
    "Python, REST APIs, and SQL, including dashboards and customer-facing workflows."
)
ALLOWED_FACTS = ["React", "TypeScript", "JavaScript", "Python", "REST APIs", "SQL"]


class ValidateAnswerTest(unittest.TestCase):
    def test_answer_using_only_supported_facts_is_accepted(self):
        result = validate_answer(
            EVIDENCE,
            "I'm excited to bring my React and TypeScript experience to building customer-facing features.",
            ALLOWED_FACTS, keyword_universe(),
        )
        self.assertTrue(result.accepted)

    def test_answer_can_be_much_shorter_than_the_evidence_without_penalty(self):
        # Unlike a resume-bullet rewrite, an answer isn't required to
        # "retain" most of the evidence's own facts -- referencing just one
        # is fine.
        result = validate_answer(EVIDENCE, "I have hands-on React experience.", ALLOWED_FACTS, keyword_universe())
        self.assertTrue(result.accepted)

    def test_unsupported_technology_is_rejected(self):
        result = validate_answer(
            EVIDENCE, "I have deep experience with React and Kubernetes.", ALLOWED_FACTS, keyword_universe(),
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("Kubernetes" in reason for reason in result.reasons))

    def test_unsupported_numeric_claim_is_rejected(self):
        result = validate_answer(
            EVIDENCE, "I built systems handling 5M requests per day.", ALLOWED_FACTS, keyword_universe(),
        )
        self.assertFalse(result.accepted)

    def test_unsupported_years_claim_is_rejected(self):
        result = validate_answer(
            EVIDENCE, "I have 10 years of React experience.", ALLOWED_FACTS, keyword_universe(),
        )
        self.assertFalse(result.accepted)

    def test_unsupported_leadership_claim_is_rejected(self):
        result = validate_answer(
            EVIDENCE, "I led a team building these React features.", ALLOWED_FACTS, keyword_universe(),
        )
        self.assertFalse(result.accepted)

    def test_empty_answer_is_rejected(self):
        result = validate_answer(EVIDENCE, "   ", ALLOWED_FACTS, keyword_universe())
        self.assertFalse(result.accepted)

    def test_ignores_claims_used_entirely_only_scans_text(self):
        # validate_answer's signature has no claims_used parameter at all --
        # only the actual answer text is ever trusted.
        result = validate_answer(EVIDENCE, "I have experience with Kubernetes.", ALLOWED_FACTS, keyword_universe())
        self.assertFalse(result.accepted)

    def test_leadership_verb_reconjugation_is_accepted(self):
        # Same canonicalization app.resume.validator uses -- an answer that
        # reconjugates a supported leadership concept ("owning" in evidence,
        # "owned" in the answer) is not a new claim.
        evidence = EVIDENCE + " Served as founding engineer, owning engineering end to end."
        result = validate_answer(
            evidence, "I owned engineering end to end using React and TypeScript.", ALLOWED_FACTS, keyword_universe(),
        )
        self.assertTrue(result.accepted)

    def test_unsupported_broader_scope_is_still_rejected_despite_supported_verb(self):
        evidence = EVIDENCE + " Owned the delivery pipeline."
        result = validate_answer(
            evidence, "I owned company-wide delivery using React.", ALLOWED_FACTS, keyword_universe(),
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("scope" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
