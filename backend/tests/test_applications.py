"""Tests for `app/applications.py`: status validation and the daily queue."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database
from app.applications import (
    ApplicationError,
    build_daily_queue,
    parse_datetime_arg,
    validate_status,
)
from tests.support import make_job, make_match_kwargs

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class ValidateStatusTest(unittest.TestCase):
    def test_accepts_every_documented_status(self):
        for status in (
            "new", "shortlisted", "applying", "applied", "outreach_sent",
            "interviewing", "rejected", "offer", "skipped",
        ):
            with self.subTest(status=status):
                self.assertEqual(validate_status(status), status)

    def test_rejects_an_unknown_status(self):
        with self.assertRaises(ApplicationError) as ctx:
            validate_status("ghosted")
        self.assertIn("ghosted", str(ctx.exception))
        self.assertIn("new", str(ctx.exception))  # lists the valid ones


class ParseDatetimeArgTest(unittest.TestCase):
    def test_bare_date_assumes_midnight_utc(self):
        result = parse_datetime_arg("2026-09-20")
        self.assertEqual(result, datetime(2026, 9, 20, tzinfo=timezone.utc))

    def test_full_iso_datetime_is_parsed_as_is(self):
        result = parse_datetime_arg("2026-09-20T15:30:00+00:00")
        self.assertEqual(result, datetime(2026, 9, 20, 15, 30, tzinfo=timezone.utc))

    def test_invalid_value_raises_application_error(self):
        with self.assertRaises(ApplicationError):
            parse_datetime_arg("next tuesday")


class BuildDailyQueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)

        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", title="High A", first_seen_at=NOW - timedelta(days=1)),
                make_job(external_id="2", title="High B", first_seen_at=NOW - timedelta(days=2)),
                make_job(external_id="3", title="Review Job", first_seen_at=NOW - timedelta(days=1)),
                make_job(external_id="4", title="Below Threshold", first_seen_at=NOW - timedelta(days=1)),
                make_job(external_id="5", title="No URL Job", application_url="", first_seen_at=NOW - timedelta(days=1)),
                make_job(external_id="6", title="Already Applied", first_seen_at=NOW - timedelta(days=1)),
                make_job(external_id="7", title="Follow Up Job", first_seen_at=NOW - timedelta(days=1)),
                make_job(external_id="8", title="Rejected With Stale Follow-up", first_seen_at=NOW - timedelta(days=1)),
            ],
        )

        def score(key: str, total: int) -> None:
            database.upsert_match(self.connection, **make_match_kwargs(job_unique_key=key, total_score=total))

        score("greenhouse:acme:1", 80)
        score("greenhouse:acme:2", 80)  # tie with #1, but seen earlier -> ranks after
        score("greenhouse:acme:3", 67)
        score("greenhouse:acme:4", 60)
        score("greenhouse:acme:5", 95)
        score("greenhouse:acme:6", 95)
        score("greenhouse:acme:7", 40)  # low score, but has a due follow-up
        score("greenhouse:acme:8", 90)

        database.upsert_application(self.connection, "greenhouse:acme:6", status="applied", now=NOW)
        database.upsert_application(
            self.connection, "greenhouse:acme:7", status="applying",
            next_follow_up_at=NOW - timedelta(days=1), now=NOW,
        )
        database.upsert_application(
            self.connection, "greenhouse:acme:8", status="rejected",
            next_follow_up_at=NOW - timedelta(days=1), now=NOW,
        )

    def test_high_priority_band_is_70_plus(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        titles = {item.title for item in queue.high_priority}
        self.assertEqual(titles, {"High A", "High B"})

    def test_review_band_is_65_to_69(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        titles = {item.title for item in queue.review}
        self.assertEqual(titles, {"Review Job"})

    def test_below_65_is_excluded_by_default(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        all_new_titles = {item.title for item in queue.high_priority + queue.review}
        self.assertNotIn("Below Threshold", all_new_titles)

    def test_job_without_actionable_url_is_excluded(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        all_new_titles = {item.title for item in queue.high_priority + queue.review}
        self.assertNotIn("No URL Job", all_new_titles)

    def test_excluded_status_does_not_appear_as_a_new_candidate(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        all_new_titles = {item.title for item in queue.high_priority + queue.review}
        self.assertNotIn("Already Applied", all_new_titles)

    def test_high_priority_ordered_before_review(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        # Structural guarantee: they're different lists/sections entirely.
        self.assertTrue(queue.high_priority)
        self.assertTrue(queue.review)
        self.assertNotIn(queue.review[0].title, {item.title for item in queue.high_priority})

    def test_ranking_order_is_preserved_within_a_band(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        titles = [item.title for item in queue.high_priority]
        # Both score 80 — the more recently first-seen one (High A) sorts
        # first, exactly like `list_matches`.
        self.assertEqual(titles, ["High A", "High B"])

    def test_due_follow_up_appears(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        titles = {item.title for item in queue.follow_ups}
        self.assertIn("Follow Up Job", titles)

    def test_future_follow_up_does_not_appear(self):
        database.upsert_application(
            self.connection, "greenhouse:acme:3",
            next_follow_up_at=NOW + timedelta(days=10), now=NOW,
        )
        queue = build_daily_queue(self.connection, "test", now=NOW)
        titles = {item.title for item in queue.follow_ups}
        self.assertNotIn("Review Job", titles)

    def test_rejected_job_does_not_appear_as_a_follow_up_even_if_due(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        titles = {item.title for item in queue.follow_ups}
        self.assertNotIn("Rejected With Stale Follow-up", titles)

    def test_follow_up_can_be_below_the_review_score_band(self):
        # The whole point of a follow-up: it surfaces regardless of score.
        queue = build_daily_queue(self.connection, "test", now=NOW)
        follow_up = next(item for item in queue.follow_ups if item.title == "Follow Up Job")
        self.assertEqual(follow_up.total_score, 40)

    def test_new_vs_follow_up_kind_is_distinguishable(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        self.assertTrue(all(item.kind == "new" for item in queue.high_priority + queue.review))
        self.assertTrue(all(item.kind == "follow_up" for item in queue.follow_ups))

    def test_is_empty_reflects_whether_any_section_has_items(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        self.assertFalse(queue.is_empty)


class PreApplicationStatusesStillActionableTest(unittest.TestCase):
    """The exact contract: new/shortlisted/applying/outreach_sent are still
    open action items and must keep appearing as new candidates; the five
    "decided" statuses must not — though `applied` can still resurface as
    a follow-up.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.connection = database.connect(Path(self._tmp.name) / "data" / "test.db")
        self.addCleanup(self.connection.close)

        self.statuses = [
            "new", "shortlisted", "applying", "outreach_sent",
            "applied", "interviewing", "rejected", "offer", "skipped",
        ]
        for i, status in enumerate(self.statuses, start=1):
            database.upsert_jobs(self.connection, [make_job(external_id=str(i), title=status)])
            database.upsert_match(
                self.connection, **make_match_kwargs(job_unique_key=f"greenhouse:acme:{i}", total_score=80)
            )
            if status != "new":  # "new" is the implicit default — no row at all
                database.upsert_application(self.connection, f"greenhouse:acme:{i}", status=status, now=NOW)

    def test_pre_application_statuses_still_appear_as_new_candidates(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        new_titles = {item.title for item in queue.high_priority}

        for status in ("new", "shortlisted", "applying", "outreach_sent"):
            with self.subTest(status=status):
                self.assertIn(status, new_titles)

    def test_decided_statuses_do_not_appear_as_new_candidates(self):
        queue = build_daily_queue(self.connection, "test", now=NOW)
        new_titles = {item.title for item in queue.high_priority}

        for status in ("applied", "interviewing", "rejected", "offer", "skipped"):
            with self.subTest(status=status):
                self.assertNotIn(status, new_titles)

    def test_applied_job_still_appears_as_a_follow_up_when_due(self):
        database.upsert_application(
            self.connection, "greenhouse:acme:5",  # index 5 = "applied"
            next_follow_up_at=NOW - timedelta(days=1), now=NOW,
        )
        queue = build_daily_queue(self.connection, "test", now=NOW)

        follow_up_titles = {item.title for item in queue.follow_ups}
        new_titles = {item.title for item in queue.high_priority}

        self.assertIn("applied", follow_up_titles)
        self.assertNotIn("applied", new_titles)  # still absent from the new-candidates side


class EmptyDailyQueueTest(unittest.TestCase):
    def test_fresh_database_has_an_empty_queue(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        connection = database.connect(Path(tmp.name) / "data" / "test.db")
        self.addCleanup(connection.close)

        queue = build_daily_queue(connection, "test", now=NOW)
        self.assertTrue(queue.is_empty)


if __name__ == "__main__":
    unittest.main()
