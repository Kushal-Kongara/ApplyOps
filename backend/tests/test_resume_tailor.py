"""Evidence-bound tailoring: only what's in the master resume can ever be
selected, and every tailored bullet must trace back to a real master bullet.
"""

import unittest

from app.resume.master import load_master_resume
from tests.support import make_master_resume_dict


def _load(payload=None):
    payload = payload or make_master_resume_dict()
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume_master.json"
        path.write_text(json.dumps(payload))
        return load_master_resume(path)


class TailorResumeTest(unittest.TestCase):
    def setUp(self):
        from app.resume.tailor import tailor_resume

        self.tailor_resume = tailor_resume
        self.master = _load()

    def test_jd_skill_demonstrated_in_a_bullet_is_a_strong_match(self):
        _, analysis = self.tailor_resume(self.master, "Looking for a React and TypeScript engineer.")
        self.assertIn("React", analysis.strong_matches)
        self.assertIn("TypeScript", analysis.strong_matches)

    def test_jd_skill_only_in_flat_skills_list_is_underemphasized(self):
        # "Node.js" is in the fixture's skills.backend list but no bullet
        # mentions it.
        _, analysis = self.tailor_resume(self.master, "Must have Node.js experience.")
        self.assertIn("Node.js", analysis.supported_but_underemphasized)
        self.assertNotIn("Node.js", analysis.strong_matches)

    def test_jd_skill_with_no_master_evidence_is_unsupported(self):
        _, analysis = self.tailor_resume(self.master, "Must know Go and Kubernetes.")
        self.assertIn("Go", analysis.unsupported_requirements)
        self.assertIn("Kubernetes", analysis.unsupported_requirements)

    def test_unsupported_requirement_never_becomes_a_resume_claim(self):
        tailored, analysis = self.tailor_resume(self.master, "Must know Go and Rust.")
        self.assertIn("Go", analysis.unsupported_requirements)
        all_text = " ".join(
            bullet.text for entry in tailored.experience for bullet in entry.bullets
        ) + " ".join(tailored.skills) + tailored.summary
        self.assertNotIn("Go", all_text.split())
        self.assertNotIn("Rust", all_text)

    def test_every_tailored_bullet_traces_to_a_real_master_bullet(self):
        tailored, _ = self.tailor_resume(self.master, "React TypeScript Python SQL")
        master_bullet_ids = {b.id: b.text for entry in self.master.experience for b in entry.bullets}
        for entry in tailored.experience:
            for bullet in entry.bullets:
                self.assertIn(bullet.evidence_id, master_bullet_ids)
                self.assertEqual(bullet.text, master_bullet_ids[bullet.evidence_id])

    def test_bullet_text_is_always_verbatim_never_rephrased(self):
        tailored, _ = self.tailor_resume(self.master, "React")
        master_texts = {b.text for entry in self.master.experience for b in entry.bullets}
        for entry in tailored.experience:
            for bullet in entry.bullets:
                self.assertIn(bullet.text, master_texts)

    def test_no_experience_entries_are_dropped(self):
        tailored, _ = self.tailor_resume(self.master, "totally unrelated posting about gardening")
        self.assertEqual(
            {e.id for e in tailored.experience},
            {e.id for e in self.master.experience},
        )

    def test_bullets_relevant_to_jd_are_reordered_first(self):
        tailored, _ = self.tailor_resume(self.master, "Looking for a Python and PostgreSQL expert.")
        acme = next(e for e in tailored.experience if e.id == "exp_acme")
        self.assertEqual(acme.bullets[0].evidence_id, "exp_acme_b2")

    def test_skills_relevant_to_jd_are_prioritized(self):
        tailored, _ = self.tailor_resume(self.master, "We need someone who knows Python well.")
        self.assertLess(tailored.skills.index("Python"), tailored.skills.index("TypeScript"))

    def test_contact_and_education_are_preserved_unchanged(self):
        tailored, _ = self.tailor_resume(self.master, "React")
        self.assertEqual(tailored.contact, self.master.contact)
        self.assertEqual(tailored.education, self.master.education)


if __name__ == "__main__":
    unittest.main()
