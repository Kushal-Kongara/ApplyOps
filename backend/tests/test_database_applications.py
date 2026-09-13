"""Persistence tests for the `applications` table."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database
from tests.support import make_job, make_match_kwargs

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)
        database.upsert_jobs(self.connection, [make_job(external_id="1")])


class UpsertApplicationTest(DatabaseTestCase):
    def test_creates_a_new_row_defaulting_to_new_status(self):
        created = database.upsert_application(self.connection, "greenhouse:acme:1", now=NOW)

        self.assertTrue(created)
        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["status"], "new")
        self.assertIsNone(row["applied_at"])
        self.assertEqual(row["created_at"], row["updated_at"])
        self.assertEqual(row["last_action_at"], row["updated_at"])

    def test_creates_with_an_explicit_status(self):
        database.upsert_application(self.connection, "greenhouse:acme:1", status="shortlisted", now=NOW)

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["status"], "shortlisted")

    def test_update_does_not_create_a_second_row(self):
        database.upsert_application(self.connection, "greenhouse:acme:1", status="new", now=NOW)
        created_again = database.upsert_application(
            self.connection, "greenhouse:acme:1", status="shortlisted", now=NOW + timedelta(hours=1)
        )

        self.assertFalse(created_again)
        count = self.connection.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_update_changes_only_the_given_fields(self):
        database.upsert_application(
            self.connection, "greenhouse:acme:1", status="shortlisted", notes="looks good", now=NOW
        )
        database.upsert_application(
            self.connection, "greenhouse:acme:1", status="applying", now=NOW + timedelta(hours=1)
        )

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["status"], "applying")
        self.assertEqual(row["notes"], "looks good")  # untouched by the second call

    def test_marking_applied_with_no_date_auto_sets_applied_at(self):
        database.upsert_application(self.connection, "greenhouse:acme:1", status="applied", now=NOW)

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["applied_at"], NOW.isoformat())

    def test_explicit_applied_at_overrides_auto_default(self):
        explicit = NOW - timedelta(days=3)
        database.upsert_application(
            self.connection, "greenhouse:acme:1", status="applied", applied_at=explicit, now=NOW
        )

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["applied_at"], explicit.isoformat())

    def test_next_follow_up_at_can_be_set_and_cleared(self):
        follow_up = NOW + timedelta(days=5)
        database.upsert_application(
            self.connection, "greenhouse:acme:1", next_follow_up_at=follow_up, now=NOW
        )
        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["next_follow_up_at"], follow_up.isoformat())

        database.upsert_application(
            self.connection, "greenhouse:acme:1", next_follow_up_at=None, now=NOW + timedelta(hours=1)
        )
        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertIsNone(row["next_follow_up_at"])

    def test_omitting_next_follow_up_at_leaves_it_unchanged(self):
        follow_up = NOW + timedelta(days=5)
        database.upsert_application(
            self.connection, "greenhouse:acme:1", next_follow_up_at=follow_up, now=NOW
        )
        database.upsert_application(self.connection, "greenhouse:acme:1", status="applying", now=NOW)

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["next_follow_up_at"], follow_up.isoformat())

    def test_last_action_and_updated_at_bump_on_every_call(self):
        database.upsert_application(self.connection, "greenhouse:acme:1", now=NOW)
        database.upsert_application(
            self.connection, "greenhouse:acme:1", notes="checked in", now=NOW + timedelta(days=1)
        )

        row = database.get_application(self.connection, "greenhouse:acme:1")
        self.assertEqual(row["last_action_at"], (NOW + timedelta(days=1)).isoformat())
        self.assertEqual(row["created_at"], NOW.isoformat())  # never changes after creation


class ListApplicationsTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(self.connection, [make_job(external_id="2", title="Job Two")])
        database.upsert_application(self.connection, "greenhouse:acme:1", status="shortlisted", now=NOW)
        database.upsert_application(
            self.connection, "greenhouse:acme:2", status="applied", now=NOW + timedelta(hours=1)
        )

    def test_lists_all_by_default(self):
        rows = database.list_applications(self.connection)
        self.assertEqual(len(rows), 2)

    def test_filters_by_status(self):
        rows = database.list_applications(self.connection, status="applied")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_unique_key"], "greenhouse:acme:2")

    def test_includes_job_display_fields(self):
        rows = database.list_applications(self.connection, status="shortlisted")
        self.assertEqual(rows[0]["title"], "Full Stack Engineer")


class DailyQueryTest(DatabaseTestCase):
    """Tests for the raw query helpers `build_daily_queue` composes."""

    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="2", title="High Score Job"),
                make_job(external_id="3", title="Review Band Job"),
                make_job(external_id="4", title="Below Threshold Job"),
                make_job(external_id="5", title="No URL Job", application_url=""),
                make_job(external_id="6", title="Applied Already"),
            ],
        )
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:1", total_score=75))
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:2", total_score=90))
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:3", total_score=67))
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:4", total_score=50))
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:5", total_score=95))
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key="greenhouse:acme:6", total_score=95))
        database.upsert_application(self.connection, "greenhouse:acme:6", status="applied", now=NOW)

    def test_new_candidates_respects_min_score(self):
        rows = database.get_daily_new_candidates(self.connection, "test", 70, ())
        keys = {r["job_unique_key"] for r in rows}
        self.assertIn("greenhouse:acme:1", keys)
        self.assertIn("greenhouse:acme:2", keys)
        self.assertNotIn("greenhouse:acme:4", keys)  # scored 50, below threshold

    def test_new_candidates_excludes_jobs_without_a_url(self):
        rows = database.get_daily_new_candidates(self.connection, "test", 0, ())
        keys = {r["job_unique_key"] for r in rows}
        self.assertNotIn("greenhouse:acme:5", keys)

    def test_new_candidates_excludes_configured_statuses(self):
        rows = database.get_daily_new_candidates(self.connection, "test", 0, ("applied",))
        keys = {r["job_unique_key"] for r in rows}
        self.assertNotIn("greenhouse:acme:6", keys)

    def test_new_candidates_default_status_for_untouched_job_is_new(self):
        rows = database.get_daily_new_candidates(self.connection, "test", 70, ("applied",))
        row = next(r for r in rows if r["job_unique_key"] == "greenhouse:acme:1")
        self.assertEqual(row["status"], "new")

    def test_new_candidates_ordered_by_score_then_freshness(self):
        rows = database.get_daily_new_candidates(self.connection, "test", 70, ())
        scores = [r["total_score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_due_follow_ups_returns_only_due_rows(self):
        database.upsert_application(
            self.connection, "greenhouse:acme:2", next_follow_up_at=NOW - timedelta(days=1), now=NOW
        )
        database.upsert_application(
            self.connection, "greenhouse:acme:3", next_follow_up_at=NOW + timedelta(days=5), now=NOW
        )

        rows = database.get_due_follow_ups(self.connection, "test", NOW, ())
        keys = {r["job_unique_key"] for r in rows}
        self.assertIn("greenhouse:acme:2", keys)
        self.assertNotIn("greenhouse:acme:3", keys)

    def test_due_follow_ups_excludes_configured_statuses(self):
        database.upsert_application(
            self.connection, "greenhouse:acme:6",
            next_follow_up_at=NOW - timedelta(days=1), now=NOW,
        )
        rows = database.get_due_follow_ups(self.connection, "test", NOW, ("applied",))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
