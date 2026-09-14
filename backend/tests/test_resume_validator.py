"""Deterministic acceptance rules for an LLM-rewritten bullet. The model's
own `claims_used` is irrelevant here — only the actual rewritten text is
ever checked, per the phase spec's "never trust the model's self-report"
rule."""

import unittest

from app.resume.evidence import build_evidence_vocabulary
from app.resume.master import load_master_resume
from app.resume.tailor import keyword_universe
from app.resume.validator import validate_rewrite
from tests.support import make_master_resume_dict

ORIGINAL = (
    "Built production full-stack features using React, TypeScript, JavaScript, "
    "Python, REST APIs, and SQL, including dashboards, forms, review queues, "
    "internal tools, and customer-facing workflows."
)
ALLOWED_FACTS = ["React", "TypeScript", "JavaScript", "Python", "REST APIs", "SQL"]


class ValidWordingTest(unittest.TestCase):
    def test_reordering_and_conciseness_is_accepted(self):
        result = validate_rewrite(
            ORIGINAL,
            "Built customer-facing full-stack product features using React, TypeScript, and JavaScript, including dashboards.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.reasons, [])

    def test_emphasizing_an_already_allowed_technology_is_accepted(self):
        result = validate_rewrite(
            ORIGINAL, "Built React, TypeScript, and SQL features for customer-facing workflows.", ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)

    def test_evidence_supported_technology_not_in_allowed_facts_is_still_accepted(self):
        # allowed_facts widens the technology check; anything already
        # literally in the original text is fine too. A short, single-fact
        # original keeps the retention ratio out of the way of what this
        # test is actually checking.
        original = "Used SQL to build dashboards and review queues."
        result = validate_rewrite(original, "Built dashboards and review queues using SQL.", allowed_facts=[])
        self.assertTrue(result.accepted)

    def test_dropping_one_irrelevant_fact_still_passes(self):
        # Drops "Python" only, keeps the other 5 of 6 recognized facts —
        # well above the retention threshold.
        result = validate_rewrite(
            ORIGINAL,
            "Built customer-facing full-stack features using React, TypeScript, JavaScript, REST APIs, and SQL.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)


class UnsupportedTechnologyTest(unittest.TestCase):
    def test_new_technology_not_in_original_or_allowed_facts_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL,
            "Built full-stack features using React, TypeScript, JavaScript, Python, and Kubernetes.",
            ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("Kubernetes" in reason for reason in result.reasons))

    def test_multiple_unsupported_technologies_are_all_reported(self):
        # Also fails retention (none of the original's facts survive) —
        # this test only asserts the three technology reasons are present,
        # not that retention doesn't *also* have something to say.
        result = validate_rewrite(ORIGINAL, "Built features using Kubernetes, GraphQL, and MongoDB.", ALLOWED_FACTS)
        self.assertFalse(result.accepted)
        for tech in ("Kubernetes", "GraphQL", "MongoDB"):
            self.assertTrue(any(tech in reason for reason in result.reasons), f"missing reason for {tech}")


class UnsupportedNumericClaimTest(unittest.TestCase):
    def test_unsupported_request_count_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL, "Built React and TypeScript features handling 5M requests per day.", ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("numeric" in reason for reason in result.reasons))

    def test_unsupported_percentage_is_rejected(self):
        result = validate_rewrite(ORIGINAL, "Improved React and TypeScript performance by 40%.", ALLOWED_FACTS)
        self.assertFalse(result.accepted)
        self.assertTrue(any("40" in reason for reason in result.reasons))

    def test_numeric_claim_present_in_original_is_accepted(self):
        original_with_number = ORIGINAL + " Reduced review time by 20%."
        result = validate_rewrite(
            original_with_number,
            "Built full-stack features using React, TypeScript, and SQL, reducing review time by 20%.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)


class UnsupportedYearsTest(unittest.TestCase):
    def test_unsupported_years_of_experience_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL, "Brought 5+ years of experience to React and TypeScript full-stack features.", ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("duration" in reason or "numeric" in reason for reason in result.reasons))

    def test_spelled_out_years_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL, "Brought three years of React and TypeScript full-stack experience.", ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("duration" in reason for reason in result.reasons))

    def test_years_phrase_present_in_original_is_accepted(self):
        original_with_years = ORIGINAL + " Over 5 years leading this area."
        result = validate_rewrite(
            original_with_years,
            "Brought 5 years of React, TypeScript, and SQL experience to this area.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)


class UnsupportedLeadershipTest(unittest.TestCase):
    def test_unsupported_leadership_verb_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL, "Led a team building React and TypeScript full-stack features.", ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("leadership" in reason for reason in result.reasons))

    def test_unsupported_mentorship_claim_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL, "Mentored engineers on React and TypeScript full-stack features.", ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)

    def test_leadership_word_present_in_original_is_accepted(self):
        original_with_owned = ORIGINAL + " Owned the delivery pipeline."
        result = validate_rewrite(
            original_with_owned,
            "Owned delivery of full-stack features using React, TypeScript, and SQL.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)


class LeadershipCanonicalizationTest(unittest.TestCase):
    """A rewrite may reconjugate a leadership/ownership concept the
    evidence already supports (owning -> owned) -- canonicalization is
    per-verb-family, not a general stemmer, and it never authorizes new
    scope or scale."""

    def test_owning_evidence_owned_answer_is_accepted(self):
        original = ORIGINAL + " Served as founding engineer, owning engineering across frontend and backend."
        result = validate_rewrite(
            original,
            "Owned engineering across frontend and backend using React, TypeScript, and Python.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)

    def test_owned_evidence_owning_answer_is_accepted(self):
        original = ORIGINAL + " Owned the delivery pipeline end to end."
        result = validate_rewrite(
            original,
            "Owning delivery of full-stack features using React, TypeScript, and Python end to end.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)

    def test_leading_evidence_led_answer_is_accepted(self):
        original = ORIGINAL + " Leading a cross-functional initiative to ship the feature."
        result = validate_rewrite(
            original,
            "Led a cross-functional initiative using React, TypeScript, and Python to ship the feature.",
            ALLOWED_FACTS,
        )
        self.assertTrue(result.accepted)

    def test_unsupported_led_is_still_rejected_when_no_leadership_family_present(self):
        # Evidence never uses any leadership-family verb at all.
        result = validate_rewrite(
            ORIGINAL, "Led a team building React and TypeScript full-stack features.", ALLOWED_FACTS,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("led" in reason for reason in result.reasons))

    def test_supported_leadership_verb_with_invented_team_size_is_still_rejected(self):
        original = ORIGINAL + " Served as founding engineer, owning engineering across frontend and backend."
        result = validate_rewrite(original, "Owned a team of 12 engineers.", ALLOWED_FACTS)
        self.assertFalse(result.accepted)
        self.assertTrue(any("numeric" in reason and "12" in reason for reason in result.reasons))

    def test_supported_leadership_verb_with_invented_broader_scope_is_still_rejected(self):
        original = "Architected a workflow for onboarding using React."
        result = validate_rewrite(original, "Architected company-wide infrastructure for onboarding using React.", ["React"])
        self.assertFalse(result.accepted)
        self.assertTrue(any("scope" in reason and "company-wide" in reason for reason in result.reasons))

    def test_different_leadership_family_is_not_conflated(self):
        # Evidence supports "owning" (family: own) -- a rewrite claiming
        # "mentored" (family: mentor) is a genuinely different concept and
        # must still be rejected, not treated as a synonym.
        original = ORIGINAL + " Owned the delivery pipeline."
        result = validate_rewrite(original, "Mentored the team on React and TypeScript.", ALLOWED_FACTS)
        self.assertFalse(result.accepted)
        self.assertTrue(any("mentored" in reason for reason in result.reasons))


class ConservativeAcceptanceTest(unittest.TestCase):
    def test_empty_rewrite_is_rejected(self):
        result = validate_rewrite(ORIGINAL, "   ", ALLOWED_FACTS)
        self.assertFalse(result.accepted)

    def test_ignores_claims_used_field_entirely_only_scans_text(self):
        # validate_rewrite's signature doesn't even accept claims_used —
        # this documents that omission is deliberate: only the actual
        # rewritten text is ever trusted.
        result = validate_rewrite(ORIGINAL, "Built features using Kubernetes.", ALLOWED_FACTS)
        self.assertFalse(result.accepted)


class RetentionGateTest(unittest.TestCase):
    """The information-retention gate: a rewrite can be 100% factually safe
    (no invented tech/numbers/leadership) and still be rejected for
    dropping too much of what the original bullet actually demonstrated."""

    def test_safe_concise_rewrite_is_accepted(self):
        result = validate_rewrite(
            ORIGINAL,
            "Built customer-facing full-stack features using React, TypeScript, and Python, including dashboards.",
            ALLOWED_FACTS,
            target_emphasis=["React", "TypeScript"],
        )
        self.assertTrue(result.accepted)

    def test_dropping_one_fact_not_emphasized_still_passes(self):
        # Drops "REST APIs" only; keeps 5 of 6 recognized facts and both
        # emphasized ones.
        result = validate_rewrite(
            ORIGINAL,
            "Built customer-facing full-stack features using React, TypeScript, JavaScript, Python, and SQL.",
            ALLOWED_FACTS,
            target_emphasis=["React", "TypeScript"],
        )
        self.assertTrue(result.accepted)

    def test_removing_most_recognized_facts_is_rejected(self):
        # Keeps only React (1 of 6 recognized facts) -- below the 50%
        # retention threshold, even though nothing false was added.
        result = validate_rewrite(
            ORIGINAL, "Built features using React.", ALLOWED_FACTS, target_emphasis=["React"],
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("retains too little" in reason for reason in result.reasons))

    def test_dropping_an_emphasized_fact_is_rejected_even_if_other_facts_survive(self):
        # Keeps 4 of 6 recognized facts (well above the ratio threshold)
        # but drops "TypeScript," which was specifically emphasized for
        # this job -- that alone must reject it.
        result = validate_rewrite(
            ORIGINAL,
            "Built customer-facing full-stack features using React, JavaScript, Python, and SQL.",
            ALLOWED_FACTS,
            target_emphasis=["React", "TypeScript"],
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("TypeScript" in reason for reason in result.reasons))

    def test_generic_vague_rewrite_with_no_recognized_facts_is_rejected(self):
        result = validate_rewrite(
            ORIGINAL,
            "Worked on impactful projects using modern tools to deliver great results for the team.",
            ALLOWED_FACTS,
            target_emphasis=["React", "TypeScript"],
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("retains too little" in reason for reason in result.reasons))

    def test_retention_check_is_skipped_when_original_has_no_recognized_facts(self):
        # A bullet with no recognizable technology keyword at all (purely
        # narrative) shouldn't be penalized by a check that has nothing to
        # count -- the other safety checks still apply normally.
        original = "Coordinated closely with the design team to refine the onboarding experience."
        result = validate_rewrite(original, "Worked closely with design to improve onboarding.", allowed_facts=[])
        self.assertTrue(result.accepted)


def _master_with_html_css():
    import json
    import tempfile
    from pathlib import Path

    payload = make_master_resume_dict()
    payload["skills"] = {"languages": ["HTML", "CSS", "JavaScript"], "frontend": ["React"]}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume_master.json"
        path.write_text(json.dumps(payload))
        return load_master_resume(path)


class MasterResumeEvidenceVocabularyTest(unittest.TestCase):
    """Reproduces the real gap found during the Qwen benchmark: HTML/CSS
    are truthful skills in the master resume but have no job-matching
    alias entry. The retention validator must recognize them as evidence
    without hardcoding them -- these tests would pass equally for any other
    master-only skill."""

    DISPATCHTRACK_BULLET = (
        "Built responsive frontend interfaces and reusable UI components using HTML, CSS, "
        "JavaScript, and React, integrating user-facing workflows with backend services."
    )

    def setUp(self):
        self.master = _master_with_html_css()
        self.vocabulary = build_evidence_vocabulary(self.master)
        self.assertNotIn("HTML", keyword_universe())  # sanity: genuinely master-only

    def test_master_only_skill_is_recognized_as_evidence(self):
        # A rewrite keeping HTML/CSS is fine; the important thing is that
        # recognizing them doesn't depend on a matching-alias entry.
        result = validate_rewrite(
            self.DISPATCHTRACK_BULLET,
            "Built responsive frontend interfaces and reusable UI components using HTML, CSS, JavaScript, and React.",
            allowed_facts=["HTML", "CSS", "JavaScript", "React"],
            evidence_vocabulary=self.vocabulary,
        )
        self.assertTrue(result.accepted)

    def test_dropping_most_master_only_facts_triggers_retention_rejection(self):
        # Drops HTML, CSS, and JavaScript -- keeps only React (1 of 4
        # recognized facts). Under the old keyword_universe-only vocabulary
        # this bullet only had 2 recognized facts (React, JavaScript) and
        # this exact rewrite would have scored 1/2 = 50%, right at the
        # threshold -- accepted. With HTML/CSS counted, it's 1/4 = 25%.
        result = validate_rewrite(
            self.DISPATCHTRACK_BULLET,
            "Built responsive frontend interfaces and reusable UI components using React.",
            allowed_facts=["HTML", "CSS", "JavaScript", "React"],
            evidence_vocabulary=self.vocabulary,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("retains too little" in reason for reason in result.reasons))

    def test_dropping_one_non_target_master_only_fact_still_passes(self):
        # Drops only "HTML" (not in target_emphasis) -- keeps 3 of 4
        # recognized facts, well above the retention threshold.
        result = validate_rewrite(
            self.DISPATCHTRACK_BULLET,
            "Built responsive frontend interfaces and reusable UI components using CSS, JavaScript, and React.",
            allowed_facts=["HTML", "CSS", "JavaScript", "React"],
            target_emphasis=["React", "JavaScript"],
            evidence_vocabulary=self.vocabulary,
        )
        self.assertTrue(result.accepted)

    def test_unsupported_skill_is_still_rejected_alongside_the_wider_vocabulary(self):
        # Widening the vocabulary must never widen what's *allowed to be
        # added* -- Kubernetes is still absent from both the original text
        # and allowed_facts, so it's still rejected.
        result = validate_rewrite(
            self.DISPATCHTRACK_BULLET,
            "Built responsive frontend interfaces and reusable UI components using HTML, CSS, JavaScript, React, and Kubernetes.",
            allowed_facts=["HTML", "CSS", "JavaScript", "React"],
            evidence_vocabulary=self.vocabulary,
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("Kubernetes" in reason for reason in result.reasons))

    def test_omitting_evidence_vocabulary_keeps_the_old_matching_only_behavior(self):
        # Existing callers that don't pass evidence_vocabulary (e.g. any
        # test written before this fix) are unaffected: HTML/CSS are
        # invisible to the retention count exactly as before, so dropping
        # them alongside JavaScript here scores 1 of the 2 previously
        # recognized facts (React) -- 50%, right at the threshold, accepted
        # -- the same behavior the pre-fix real-DGX benchmark runs actually
        # exercised.
        result = validate_rewrite(
            self.DISPATCHTRACK_BULLET,
            "Built responsive frontend interfaces and reusable UI components using React.",
            allowed_facts=["HTML", "CSS", "JavaScript", "React"],
        )
        self.assertTrue(result.accepted)


if __name__ == "__main__":
    unittest.main()
