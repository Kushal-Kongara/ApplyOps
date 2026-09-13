"""`resume_versions` table: version numbering, insertion, and the approval
state machine (only one approved version per job at a time)."""

import unittest

from app import database
from tests.support import make_job


class ResumeVersionsTest(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(self.connection, [make_job(external_id="1"), make_job(external_id="2")])
        self.job_a = "greenhouse:acme:1"
        self.job_b = "greenhouse:acme:2"

    def insert(self, job_unique_key, version, **overrides):
        fields = dict(
            job_unique_key=job_unique_key,
            version=version,
            latex_source=f"latex-v{version}",
            pdf_path=None,
            compiler_status="unavailable",
            compile_log=None,
            page_count=None,
            tailoring_analysis={"strong_matches": []},
        )
        fields.update(overrides)
        return database.insert_resume_version(self.connection, **fields)

    def test_first_version_for_a_job_is_one(self):
        self.assertEqual(database.next_resume_version(self.connection, self.job_a), 1)

    def test_version_increments_after_each_insert(self):
        self.insert(self.job_a, 1)
        self.assertEqual(database.next_resume_version(self.connection, self.job_a), 2)
        self.insert(self.job_a, 2)
        self.assertEqual(database.next_resume_version(self.connection, self.job_a), 3)

    def test_versions_are_isolated_per_job(self):
        self.insert(self.job_a, 1)
        self.insert(self.job_a, 2)
        self.assertEqual(database.next_resume_version(self.connection, self.job_b), 1)

    def test_regenerating_never_overwrites_a_prior_version(self):
        id1 = self.insert(self.job_a, 1)
        id2 = self.insert(self.job_a, 2)
        v1 = database.get_resume_version(self.connection, id1)
        v2 = database.get_resume_version(self.connection, id2)
        self.assertEqual(v1["latex_source"], "latex-v1")
        self.assertEqual(v2["latex_source"], "latex-v2")

    def test_list_resume_versions_is_newest_first_and_never_drops_old_ones(self):
        self.insert(self.job_a, 1)
        self.insert(self.job_a, 2)
        self.insert(self.job_a, 3)
        versions = [row["version"] for row in database.list_resume_versions(self.connection, self.job_a)]
        self.assertEqual(versions, [3, 2, 1])

    def test_approving_a_version_marks_it_approved(self):
        id1 = self.insert(self.job_a, 1)
        approved = database.approve_resume_version(self.connection, id1)
        self.assertEqual(approved["status"], "approved")
        self.assertIsNotNone(approved["approved_at"])

    def test_approving_a_new_version_demotes_the_previously_approved_one(self):
        id1 = self.insert(self.job_a, 1)
        id2 = self.insert(self.job_a, 2)
        database.approve_resume_version(self.connection, id1)
        database.approve_resume_version(self.connection, id2)

        v1 = database.get_resume_version(self.connection, id1)
        v2 = database.get_resume_version(self.connection, id2)
        self.assertEqual(v1["status"], "draft")
        self.assertEqual(v2["status"], "approved")

    def test_approving_one_jobs_version_never_touches_another_jobs_approval(self):
        id_a = self.insert(self.job_a, 1)
        id_b = self.insert(self.job_b, 1)
        database.approve_resume_version(self.connection, id_a)
        database.approve_resume_version(self.connection, id_b)

        self.assertEqual(database.get_resume_version(self.connection, id_a)["status"], "approved")
        self.assertEqual(database.get_resume_version(self.connection, id_b)["status"], "approved")

    def test_approving_unknown_resume_id_returns_none(self):
        self.assertIsNone(database.approve_resume_version(self.connection, 9999))


if __name__ == "__main__":
    unittest.main()
