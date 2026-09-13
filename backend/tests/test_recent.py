"""Recent Jobs timeline: bucket boundary correctness and business rules.

No network calls. Boundary tests use exact timedeltas so float arithmetic
lands on exact hour values (2h == 7200.0 seconds), matching the spec's
"1h59m / 2h exactly / 3h59m / 4h exactly / ..." cases precisely.
"""

import unittest
from datetime import datetime, timedelta, timezone

from app import database
from app.recent import (
    DEFAULT_MIN_SCORE,
    HIGH_PRIORITY_MIN_SCORE,
    OLDER_KEY,
    bucket_for_age,
    build_recent_timeline,
    empty_buckets,
)
from tests.support import make_job, make_match_kwargs

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def age_of(hours: float, minutes: float = 0) -> datetime:
    """The first_seen_at that puts a job at exactly this age relative to NOW."""
    return NOW - timedelta(hours=hours, minutes=minutes)


class BucketForAgeTest(unittest.TestCase):
    def setUp(self):
        self.buckets = empty_buckets()

    def test_twelve_buckets_covering_0_to_24_hours(self):
        self.assertEqual(len(self.buckets), 12)
        self.assertEqual((self.buckets[0].min_hours, self.buckets[0].max_hours), (0, 2))
        self.assertEqual((self.buckets[-1].min_hours, self.buckets[-1].max_hours), (22, 24))

    def test_zero_hours(self):
        bucket = bucket_for_age(0.0, self.buckets)
        self.assertEqual(bucket.key, "0-2")

    def test_1h59m_is_in_0_2(self):
        bucket = bucket_for_age(1 + 59 / 60, self.buckets)
        self.assertEqual(bucket.key, "0-2")

    def test_2h_exactly_is_in_2_4_not_0_2(self):
        bucket = bucket_for_age(2.0, self.buckets)
        self.assertEqual(bucket.key, "2-4")

    def test_3h59m_is_in_2_4(self):
        bucket = bucket_for_age(3 + 59 / 60, self.buckets)
        self.assertEqual(bucket.key, "2-4")

    def test_4h_exactly_is_in_4_6(self):
        bucket = bucket_for_age(4.0, self.buckets)
        self.assertEqual(bucket.key, "4-6")

    def test_23h59m_is_in_22_24(self):
        bucket = bucket_for_age(23 + 59 / 60, self.buckets)
        self.assertEqual(bucket.key, "22-24")

    def test_24h_exactly_is_older_not_22_24(self):
        bucket = bucket_for_age(24.0, self.buckets)
        self.assertIsNone(bucket)  # caller routes None to "older"

    def test_48h_is_older(self):
        bucket = bucket_for_age(48.0, self.buckets)
        self.assertIsNone(bucket)

    def test_labels(self):
        self.assertEqual(self.buckets[0].label, "Last 2 hours")
        self.assertEqual(self.buckets[1].label, "2–4 hours ago")
        self.assertEqual(self.buckets[-1].label, "22–24 hours ago")


class BuildRecentTimelineTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)

    def seed(self, external_id: str, hours_ago: float, total_score: int, **overrides) -> str:
        job = make_job(external_id=external_id, first_seen_at=age_of(hours_ago))
        database.upsert_jobs(self.connection, [job])
        database.upsert_match(
            self.connection, **make_match_kwargs(job_unique_key=job.unique_key, total_score=total_score, **overrides)
        )
        return job.unique_key


class BoundaryPlacementTest(BuildRecentTimelineTestCase):
    def test_job_appears_in_exactly_one_bucket(self):
        self.seed("1", hours_ago=1, total_score=80)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        occurrences = sum(
            1 for bucket in timeline.buckets for job in bucket.jobs
        ) + len(timeline.older.jobs)
        self.assertEqual(occurrences, 1)
        self.assertEqual(timeline.buckets[0].count, 1)

    def test_job_at_exactly_2h_is_not_in_the_0_2_bucket(self):
        self.seed("1", hours_ago=2, total_score=80)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(timeline.buckets[0].count, 0)
        self.assertEqual(timeline.buckets[1].count, 1)

    def test_job_at_exactly_24h_lands_in_older(self):
        self.seed("1", hours_ago=24, total_score=80)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(sum(b.count for b in timeline.buckets), 0)
        self.assertEqual(timeline.older_total_count, 1)


class ScoreFilteringAndSortingTest(BuildRecentTimelineTestCase):
    def test_below_65_is_excluded_by_default(self):
        self.seed("1", hours_ago=1, total_score=64)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(timeline.last_24h_count, 0)

    def test_65_and_above_is_included(self):
        self.seed("1", hours_ago=1, total_score=65)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(timeline.last_24h_count, 1)

    def test_custom_min_score_is_respected(self):
        self.seed("1", hours_ago=1, total_score=70)
        self.seed("2", hours_ago=1, total_score=65)
        timeline = build_recent_timeline(self.connection, "test", now=NOW, min_score=70)

        self.assertEqual(timeline.last_24h_count, 1)

    def test_70_plus_counted_as_high_priority_65_69_as_review(self):
        self.seed("1", hours_ago=1, total_score=80)
        self.seed("2", hours_ago=1, total_score=67)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(timeline.high_priority_count, 1)
        self.assertEqual(timeline.review_count, 1)
        self.assertEqual(HIGH_PRIORITY_MIN_SCORE, 70)

    def test_sorted_by_score_descending_within_a_bucket(self):
        self.seed("1", hours_ago=1, total_score=67)
        self.seed("2", hours_ago=1, total_score=90)
        self.seed("3", hours_ago=1, total_score=75)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        scores = [j.job.total_score for j in timeline.buckets[0].jobs]
        self.assertEqual(scores, [90, 75, 67])

    def test_tied_scores_break_by_freshness_descending(self):
        older_job = self.seed("1", hours_ago=1.9, total_score=80)
        newer_job = self.seed("2", hours_ago=0.1, total_score=80)
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        keys = [j.job.job_unique_key for j in timeline.buckets[0].jobs]
        self.assertEqual(keys, [newer_job, older_job])


class ApplicationStatusTest(BuildRecentTimelineTestCase):
    def test_applied_job_still_appears_on_the_timeline(self):
        key = self.seed("1", hours_ago=1, total_score=80)
        database.upsert_application(self.connection, key, status="applied")

        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(timeline.buckets[0].count, 1)
        self.assertEqual(timeline.buckets[0].jobs[0].job.status, "applied")


class RediscoveryDoesNotResetTest(BuildRecentTimelineTestCase):
    def test_rescoring_an_existing_job_keeps_its_original_first_seen_at(self):
        original_discovery = age_of(hours=10)
        job = make_job(external_id="1", first_seen_at=original_discovery)
        database.upsert_jobs(self.connection, [job])

        # A later collection run re-upserts the same job (same unique_key)
        # with a fresh first_seen_at on the incoming object — the database
        # layer must still keep the original.
        rescanned = make_job(external_id="1", first_seen_at=NOW)
        database.upsert_jobs(self.connection, [rescanned])

        row = database.get_job(self.connection, job.unique_key)
        self.assertEqual(row["first_seen_at"], original_discovery.isoformat())

        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key=job.unique_key, total_score=80))
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        # Still ~10h old, not freshly "discovered" — bucket 10-12, not 0-2.
        bucket_with_job = next(b for b in timeline.buckets if b.jobs)
        self.assertEqual(bucket_with_job.key, "10-12")


class TimezoneAwareTest(BuildRecentTimelineTestCase):
    def test_a_non_utc_offset_first_seen_at_is_handled_correctly(self):
        # 1 hour ago in UTC, expressed in a +05:00 offset instead.
        first_seen_utc = NOW - timedelta(hours=1)
        first_seen_local = first_seen_utc.astimezone(timezone(timedelta(hours=5)))
        job = make_job(external_id="1", first_seen_at=first_seen_local)
        database.upsert_jobs(self.connection, [job])
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key=job.unique_key, total_score=80))

        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(timeline.buckets[0].count, 1)  # correctly recognized as ~1h old


class EmptyBucketStructureTest(BuildRecentTimelineTestCase):
    def test_all_twelve_buckets_are_always_present_even_when_empty(self):
        timeline = build_recent_timeline(self.connection, "test", now=NOW)

        self.assertEqual(len(timeline.buckets), 12)
        self.assertTrue(all(bucket.count == 0 for bucket in timeline.buckets))
        self.assertEqual(timeline.older.count, 0)
        self.assertEqual(timeline.older.key, OLDER_KEY)

    def test_default_min_score_constant_is_65(self):
        self.assertEqual(DEFAULT_MIN_SCORE, 65)


class OlderBucketPaginationTest(BuildRecentTimelineTestCase):
    def test_older_bucket_is_paginated_but_count_reflects_the_true_total(self):
        for i in range(30):
            self.seed(str(i), hours_ago=25, total_score=80)

        timeline = build_recent_timeline(self.connection, "test", now=NOW, older_limit=25, older_offset=0)

        self.assertEqual(len(timeline.older.jobs), 25)
        self.assertEqual(timeline.older_total_count, 30)

    def test_older_offset_returns_the_next_page(self):
        for i in range(30):
            self.seed(str(i), hours_ago=25, total_score=80)

        timeline = build_recent_timeline(self.connection, "test", now=NOW, older_limit=25, older_offset=25)

        self.assertEqual(len(timeline.older.jobs), 5)


if __name__ == "__main__":
    unittest.main()
