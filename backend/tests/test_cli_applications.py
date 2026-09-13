"""CLI tests for `applications`, `application-update`, and `daily`."""

import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import cli, database
from tests.support import make_job, make_match_kwargs

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class CliApplicationsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)
        self.out = io.StringIO()


class CmdApplicationUpdateTest(CliApplicationsTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(self.connection, [make_job(external_id="1")])

    def test_creates_a_tracked_application(self):
        with mock.patch("sys.stdout", io.StringIO()) as out:
            exit_code = cli.main(
                ["application-update", "greenhouse:acme:1", "--status", "shortlisted", "--db", str(self.db_path)]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("Created", out.getvalue())

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["status"], "shortlisted")

    def test_updates_an_existing_application_in_place(self):
        with mock.patch("sys.stdout", io.StringIO()):
            cli.main(["application-update", "greenhouse:acme:1", "--status", "shortlisted", "--db", str(self.db_path)])
        with mock.patch("sys.stdout", io.StringIO()) as out:
            exit_code = cli.main(
                ["application-update", "greenhouse:acme:1", "--status", "applied", "--db", str(self.db_path)]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("Updated", out.getvalue())

        count = self.connection.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_invalid_status_is_rejected(self):
        with mock.patch("sys.stderr", io.StringIO()):
            exit_code = cli.main(
                ["application-update", "greenhouse:acme:1", "--status", "ghosted", "--db", str(self.db_path)]
            )
        self.assertEqual(exit_code, 2)

    def test_unknown_job_key_is_rejected(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            exit_code = cli.main(
                ["application-update", "does-not-exist", "--status", "shortlisted", "--db", str(self.db_path)]
            )
        self.assertEqual(exit_code, 2)
        self.assertIn("No job found", err.getvalue())

    def test_next_follow_up_at_is_settable_and_clearable(self):
        with mock.patch("sys.stdout", io.StringIO()):
            cli.main(
                ["application-update", "greenhouse:acme:1", "--next-follow-up-at", "2026-10-01",
                 "--db", str(self.db_path)]
            )
        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["next_follow_up_at"], "2026-10-01T00:00:00+00:00")

        with mock.patch("sys.stdout", io.StringIO()):
            cli.main(["application-update", "greenhouse:acme:1", "--clear-follow-up", "--db", str(self.db_path)])
        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertIsNone(row["next_follow_up_at"])


class CmdApplicationsListTest(CliApplicationsTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [make_job(external_id="1", title="Job One"), make_job(external_id="2", title="Job Two")],
        )
        database.upsert_application(self.connection, "greenhouse:acme:1", status="shortlisted", now=NOW)
        database.upsert_application(self.connection, "greenhouse:acme:2", status="applied", now=NOW)

    def test_lists_all_tracked_applications(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(["applications", "--db", str(self.db_path)])
        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("Job One", output)
        self.assertIn("Job Two", output)

    def test_filters_by_status(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["applications", "--status", "applied", "--db", str(self.db_path)])
        output = buffer.getvalue()
        self.assertIn("Job Two", output)
        self.assertNotIn("Job One", output)

    def test_no_applications_reports_clearly(self):
        empty_db = Path(self._tmp.name) / "data" / "empty.db"
        database.connect(empty_db).close()
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["applications", "--db", str(empty_db)])
        self.assertIn("No tracked applications", buffer.getvalue())


class CmdDailyTest(CliApplicationsTestCase):
    def setUp(self):
        super().setUp()
        self.profile_path = Path(self._tmp.name) / "profile.json"
        self.profile_path.write_text(
            '{"profile_id": "test", "years_experience": 4, '
            '"target_titles": ["Full Stack Engineer"], "primary_locations": ["San Francisco"], '
            '"allow_remote_us": true, "allow_relocation_us": true, '
            '"primary_skills": ["React"], "secondary_skills": []}',
            encoding="utf-8",
        )
        database.upsert_jobs(self.connection, [make_job(external_id="1", title="Full Stack Engineer")])
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:1", total_score=80))

    def test_daily_shows_high_priority_job(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(["daily", "--profile", str(self.profile_path), "--db", str(self.db_path)])
        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("High priority", output)
        self.assertIn("Full Stack Engineer", output)
        self.assertIn("[NEW]", output)

    def test_daily_reports_nothing_actionable_on_empty_queue(self):
        empty_db = Path(self._tmp.name) / "data" / "empty.db"
        database.connect(empty_db).close()
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["daily", "--profile", str(self.profile_path), "--db", str(empty_db)])
        self.assertIn("Nothing actionable", buffer.getvalue())

    def test_daily_shows_follow_up_section_distinctly(self):
        database.upsert_application(
            self.connection, "greenhouse:acme:1", status="applying",
            next_follow_up_at=NOW - timedelta(days=1), now=NOW,
        )
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            cli.main(["daily", "--profile", str(self.profile_path), "--db", str(self.db_path)])
        output = buffer.getvalue()
        self.assertIn("Follow-ups due", output)
        self.assertIn("[FOLLOW-UP]", output)


if __name__ == "__main__":
    unittest.main()
