"""`build_evidence_vocabulary`: the master resume's own `skills` block is a
source of recognized facts in its own right, not just whatever the
job-matching alias table happens to cover."""

import unittest

from app.matching.text import normalize_text
from app.resume.evidence import build_evidence_vocabulary, recognized_facts
from app.resume.master import load_master_resume
from app.resume.tailor import keyword_universe
from tests.support import make_master_resume_dict


def _load_master(**skill_overrides):
    import json
    import tempfile
    from pathlib import Path

    payload = make_master_resume_dict()
    if skill_overrides:
        payload["skills"] = skill_overrides
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume_master.json"
        path.write_text(json.dumps(payload))
        return load_master_resume(path)


class BuildEvidenceVocabularyTest(unittest.TestCase):
    def test_master_only_skill_absent_from_matching_aliases_is_recognized(self):
        # HTML/CSS are the real skills that exposed this gap: neither is in
        # `SKILL_ALIASES` nor `tailor._EXTRA_KEYWORDS`.
        self.assertNotIn("HTML", keyword_universe())
        self.assertNotIn("CSS", keyword_universe())

        master = _load_master(languages=["HTML", "CSS", "JavaScript"])
        vocabulary = build_evidence_vocabulary(master)

        self.assertIn("HTML", vocabulary)
        self.assertIn("CSS", vocabulary)
        facts = recognized_facts(normalize_text("Built pages using HTML and CSS."), vocabulary)
        self.assertIn("HTML", facts)
        self.assertIn("CSS", facts)

    def test_existing_matching_alias_entries_keep_their_full_alias_list(self):
        # "React" already has a rich alias list ("react js", "reactjs", ...)
        # in keyword_universe() -- a master-resume skill of the same name
        # must not collapse that down to a single literal phrase.
        master = _load_master(frontend=["React"])
        vocabulary = build_evidence_vocabulary(master)
        self.assertEqual(vocabulary["React"], keyword_universe()["React"])

    def test_skill_in_neither_aliases_nor_master_resume_is_not_recognized(self):
        master = _load_master(languages=["Python"])
        vocabulary = build_evidence_vocabulary(master)
        facts = recognized_facts(normalize_text("Wrote some Fortran code."), vocabulary)
        self.assertEqual(facts, set())

    def test_a_skill_is_never_double_counted_under_two_different_casings(self):
        master = _load_master(languages=["react"])  # lowercase, same skill as keyword_universe's "React"
        vocabulary = build_evidence_vocabulary(master)
        # Only the canonical "React" key from keyword_universe should exist
        # -- not also a separate "react" key.
        self.assertNotIn("react", vocabulary)
        self.assertIn("React", vocabulary)

    def test_vocabulary_still_contains_the_full_matching_alias_table(self):
        master = _load_master(languages=["Python"])
        vocabulary = build_evidence_vocabulary(master)
        for name in keyword_universe():
            self.assertIn(name, vocabulary)


if __name__ == "__main__":
    unittest.main()
