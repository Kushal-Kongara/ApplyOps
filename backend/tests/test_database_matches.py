"""Persistence tests for `job_matches` and the active-jobs helper."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database
from tests.support import make_job, make_match_kwargs as match_kwargs

FIRST_SCAN = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
SECOND_SCAN = FIRST_SCAN + timedelta(days=1)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)


class GetActiveJobsTest(DatabaseTestCase):
    def test_returns_only_active_jobs_as_job_objects(self):
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", first_seen_at=FIRST_SCAN, is_active=True),
                make_job(external_id="2", first_seen_at=FIRST_SCAN, is_active=False),
            ],
        )

        active = database.get_active_jobs(self.connection)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].external_id, "1")
        self.assertEqual(active[0].unique_key, "greenhouse:acme:1")


class UpsertMatchTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(self.connection, [make_job(external_id="1", first_seen_at=FIRST_SCAN)])

    def test_insert_creates_a_new_row(self):
        created = database.upsert_match(self.connection, **match_kwargs())
        self.assertTrue(created)

        row = database.get_match(self.connection, "greenhouse:acme:1", "test")
        self.assertEqual(row["total_score"], 80)
        self.assertEqual(row["matched_skills"], '["React", "Python"]')

    def test_rescoring_updates_the_existing_row_without_duplicating(self):
        database.upsert_match(self.connection, **match_kwargs(total_score=80))
        created = database.upsert_match(self.connection, **match_kwargs(total_score=55, scored_at=SECOND_SCAN))

        self.assertFalse(created)
        count = self.connection.execute(
            "SELECT COUNT(*) AS n FROM job_matches WHERE job_unique_key = ? AND profile_id = ?",
            ("greenhouse:acme:1", "test"),
        ).fetchone()["n"]
        self.assertEqual(count, 1)

        row = database.get_match(self.connection, "greenhouse:acme:1", "test")
        self.assertEqual(row["total_score"], 55)

    def test_different_profile_gets_its_own_row(self):
        database.upsert_match(self.connection, **match_kwargs(profile_id="a"))
        database.upsert_match(self.connection, **match_kwargs(profile_id="b"))

        count = self.connection.execute("SELECT COUNT(*) AS n FROM job_matches").fetchone()["n"]
        self.assertEqual(count, 2)

    def test_filtered_match_is_stored_with_its_reason(self):
        database.upsert_match(
            self.connection, **match_kwargs(filtered=True, filter_reason="excluded title term matched: 'intern'")
        )

        row = database.get_match(self.connection, "greenhouse:acme:1", "test")
        self.assertEqual(row["filtered"], 1)
        self.assertIn("intern", row["filter_reason"])


class ListMatchesTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", title="Job A", first_seen_at=FIRST_SCAN),
                make_job(external_id="2", title="Job B", first_seen_at=SECOND_SCAN),
                make_job(external_id="3", title="Job C", first_seen_at=SECOND_SCAN),
                make_job(external_id="4", title="Job D (filtered)", first_seen_at=SECOND_SCAN),
            ],
        )
        database.upsert_match(
            self.connection, **match_kwargs(job_unique_key="greenhouse:acme:1", total_score=60)
        )
        database.upsert_match(
            self.connection, **match_kwargs(job_unique_key="greenhouse:acme:2", total_score=90)
        )
        database.upsert_match(
            self.connection, **match_kwargs(job_unique_key="greenhouse:acme:3", total_score=90)
        )
        database.upsert_match(
            self.connection,
            **match_kwargs(
                job_unique_key="greenhouse:acme:4", total_score=95, filtered=True, filter_reason="excluded"
            ),
        )

    def test_orders_by_score_then_freshness_descending(self):
        rows = database.list_matches(self.connection, "test", min_score=0, limit=10)
        titles = [row["title"] for row in rows]

        # Both score-90 jobs (B, C) outrank the score-60 job (A); B and C
        # tie on score and on first_seen_at, so their relative order isn't
        # asserted, only that both precede the lower-scored job.
        self.assertEqual(set(titles[:2]), {"Job B", "Job C"})
        self.assertEqual(titles[2], "Job A")

    def test_equal_scores_break_ties_by_freshness_descending(self):
        # Job C was first seen after Job B (SECOND_SCAN both here in setUp,
        # so use two distinct jobs with distinct first_seen_at to make the
        # tiebreaker itself deterministic).
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="5", title="Older, same score", first_seen_at=FIRST_SCAN),
                make_job(external_id="6", title="Newer, same score", first_seen_at=SECOND_SCAN),
            ],
        )
        database.upsert_match(
            self.connection, **match_kwargs(job_unique_key="greenhouse:acme:5", total_score=100)
        )
        database.upsert_match(
            self.connection, **match_kwargs(job_unique_key="greenhouse:acme:6", total_score=100)
        )

        rows = database.list_matches(self.connection, "test", min_score=100, limit=2)
        titles = [row["title"] for row in rows]

        self.assertEqual(titles, ["Newer, same score", "Older, same score"])

    def test_min_score_filters_out_lower_scores(self):
        rows = database.list_matches(self.connection, "test", min_score=70, limit=10)
        titles = {row["title"] for row in rows}
        self.assertEqual(titles, {"Job B", "Job C"})

    def test_filtered_jobs_are_excluded_by_default(self):
        rows = database.list_matches(self.connection, "test", min_score=0, limit=10)
        titles = {row["title"] for row in rows}
        self.assertNotIn("Job D (filtered)", titles)

    def test_include_filtered_shows_filtered_jobs_too(self):
        rows = database.list_matches(self.connection, "test", min_score=0, limit=10, include_filtered=True)
        titles = {row["title"] for row in rows}
        self.assertIn("Job D (filtered)", titles)

    def test_limit_is_respected(self):
        rows = database.list_matches(self.connection, "test", min_score=0, limit=1)
        self.assertEqual(len(rows), 1)

    def test_count_matches_excludes_filtered_and_respects_min_score(self):
        self.assertEqual(database.count_matches(self.connection, "test", min_score=0), 3)
        self.assertEqual(database.count_matches(self.connection, "test", min_score=70), 2)


if __name__ == "__main__":
    unittest.main()
