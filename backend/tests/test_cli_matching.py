"""CLI tests for `match`, `list-matches`, and `inspect-match`. No network calls."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import cli, database
from tests.support import make_job, make_profile

PROFILE_PAYLOAD = {
    "profile_id": "test",
    "years_experience": 4,
    "target_titles": ["Full Stack Engineer", "Software Engineer"],
    "primary_locations": ["San Francisco", "Bay Area"],
    "allow_remote_us": True,
    "allow_relocation_us": True,
    "primary_skills": ["React", "TypeScript", "Python", "AWS"],
    "secondary_skills": ["Docker"],
    "excluded_title_terms": ["intern", "engineering manager"],
}


class CliMatchingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)
        self.out = io.StringIO()

    def write_profile(self, payload=PROFILE_PAYLOAD) -> Path:
        path = self.tmp_path / "profile.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class MatchJobsTest(CliMatchingTestCase):
    def test_scores_all_active_jobs_and_reports_a_summary(self):
        database.upsert_jobs(
            self.connection,
            [
                make_job(
                    external_id="1", title="Full Stack Engineer", location="San Francisco, CA",
                    description="React, TypeScript, Python, AWS. 2-5 years experience.",
                ),
                make_job(external_id="2", title="Software Engineering Intern", description=""),
                make_job(external_id="3", title="Account Executive", description="", is_active=False),
            ],
        )

        profile = make_profile(profile_id="test")
        summary = cli.match_jobs(self.connection, profile, out=self.out)

        # Inactive job is never scored at all.
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.filtered, 1)
        self.assertEqual(summary.scored, 1)
        self.assertIn("Matched 2 active job(s)", self.out.getvalue())

    def test_inactive_jobs_are_not_scored(self):
        database.upsert_jobs(
            self.connection, [make_job(external_id="1", title="Full Stack Engineer", is_active=False)]
        )

        summary = cli.match_jobs(self.connection, make_profile(), out=self.out)

        self.assertEqual(summary.total, 0)
        row = database.get_match(self.connection, "greenhouse:acme:1", "test")
        self.assertIsNone(row)

    def test_rescoring_via_match_updates_existing_row(self):
        database.upsert_jobs(
            self.connection, [make_job(external_id="1", title="Full Stack Engineer", description="React")]
        )
        profile = make_profile()

        cli.match_jobs(self.connection, profile, out=self.out)
        first = database.get_match(self.connection, "greenhouse:acme:1", profile.profile_id)

        database.upsert_jobs(
            self.connection,
            [make_job(external_id="1", title="Full Stack Engineer", description="React Python AWS TypeScript Node.js PostgreSQL")],
        )
        cli.match_jobs(self.connection, profile, out=self.out)
        second = database.get_match(self.connection, "greenhouse:acme:1", profile.profile_id)

        count = self.connection.execute("SELECT COUNT(*) AS n FROM job_matches").fetchone()["n"]
        self.assertEqual(count, 1)
        self.assertGreater(second["skills_score"], first["skills_score"])


class CmdMatchTest(CliMatchingTestCase):
    def test_invalid_profile_exits_with_code_two(self):
        bad_profile = self.write_profile({"profile_id": "test"})  # missing required fields

        with mock.patch("sys.stderr", io.StringIO()) as stderr:
            exit_code = cli.main(
                ["match", "--profile", str(bad_profile), "--db", str(self.db_path)]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("Profile error", stderr.getvalue())

    def test_healthy_match_exits_zero(self):
        profile_path = self.write_profile()
        database.upsert_jobs(self.connection, [make_job(external_id="1")])

        with mock.patch("sys.stdout", io.StringIO()):
            exit_code = cli.main(["match", "--profile", str(profile_path), "--db", str(self.db_path)])

        self.assertEqual(exit_code, 0)


class CmdListMatchesTest(CliMatchingTestCase):
    def setUp(self):
        super().setUp()
        self.profile_path = self.write_profile()
        database.upsert_jobs(
            self.connection,
            [
                make_job(
                    external_id="1", title="Full Stack Engineer", location="San Francisco, CA",
                    description="React, TypeScript, Python, AWS, Node.js, PostgreSQL.",
                ),
                make_job(external_id="2", title="Account Executive", description="", location="Remote"),
            ],
        )
        cli.match_jobs(self.connection, make_profile(profile_id="test"), out=io.StringIO())

    def test_lists_matches_above_min_score(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(
                ["list-matches", "--profile", str(self.profile_path), "--db", str(self.db_path), "--min-score", "50"]
            )

        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("Full Stack Engineer", output)
        self.assertIn("Matched:", output)
        self.assertIn("Visa: unknown", output)

    def test_filtered_job_never_appears_in_list_matches(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["list-matches", "--profile", str(self.profile_path), "--db", str(self.db_path), "--min-score", "0"])

        self.assertNotIn("Account Executive", buffer.getvalue())

    def test_no_matches_above_threshold_reports_clearly(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["list-matches", "--profile", str(self.profile_path), "--db", str(self.db_path), "--min-score", "99"])

        self.assertIn("No matches", buffer.getvalue())

    def test_show_key_flag_prints_the_job_unique_key(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(
                ["list-matches", "--profile", str(self.profile_path), "--db", str(self.db_path),
                 "--min-score", "0", "--show-key"]
            )

        self.assertIn("Key: greenhouse:acme:1", buffer.getvalue())

    def test_key_is_hidden_by_default(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["list-matches", "--profile", str(self.profile_path), "--db", str(self.db_path), "--min-score", "0"])

        self.assertNotIn("Key:", buffer.getvalue())


class CmdInspectMatchTest(CliMatchingTestCase):
    def setUp(self):
        super().setUp()
        self.profile_path = self.write_profile()
        database.upsert_jobs(
            self.connection,
            [
                make_job(
                    external_id="1", title="Full Stack Engineer", location="San Francisco, CA",
                    description="React, TypeScript, Python, AWS. We do not provide sponsorship.",
                )
            ],
        )
        cli.match_jobs(self.connection, make_profile(profile_id="test"), out=io.StringIO())

    def test_inspects_a_job_by_exact_job_key_flag(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(
                ["inspect-match", "--job-key", "greenhouse:acme:1",
                 "--profile", str(self.profile_path), "--db", str(self.db_path)]
            )

        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Total score:", output)
        self.assertIn("Title", output)
        self.assertIn("matched primary:", output)
        self.assertIn("unmatched primary:", output)
        self.assertIn("Key: greenhouse:acme:1", output)
        self.assertIn("Visa signal: sponsorship_risk", output)
        self.assertIn("do not provide sponsorship", output.lower())

    def test_inspects_a_job_by_search_text(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(
                ["inspect-match", "full stack", "--profile", str(self.profile_path), "--db", str(self.db_path)]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Total score:", buffer.getvalue())

    def test_unknown_job_reports_not_found(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(
                ["inspect-match", "nonexistent-job-xyz", "--profile", str(self.profile_path), "--db", str(self.db_path)]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("No scored job found", buffer.getvalue())

    def test_missing_query_and_job_key_reports_usage_error(self):
        with mock.patch("sys.stderr", io.StringIO()) as stderr:
            exit_code = cli.main(
                ["inspect-match", "--profile", str(self.profile_path), "--db", str(self.db_path)]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("--job-key", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
