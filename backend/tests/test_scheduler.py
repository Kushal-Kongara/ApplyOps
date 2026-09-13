"""Tests for `app/scheduler.py`: wall-clock cadence and non-overlapping
refreshes. No real sleeping — `sleep_fn`/`now_fn` are fully injected."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database, scheduler
from tests.support import GREENHOUSE_PAYLOAD, json_client


class NextBoundaryTest(unittest.TestCase):
    def test_requires_a_timezone_aware_datetime(self):
        with self.assertRaises(ValueError):
            scheduler.next_boundary(datetime(2026, 9, 13, 9, 0, 0))

    def test_midnight_to_2am(self):
        now = datetime(2026, 9, 13, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_boundary(now), datetime(2026, 9, 13, 2, 0, 0, tzinfo=timezone.utc))

    def test_just_before_a_boundary(self):
        now = datetime(2026, 9, 13, 1, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_boundary(now), datetime(2026, 9, 13, 2, 0, 0, tzinfo=timezone.utc))

    def test_exactly_on_a_boundary_advances_to_the_next_one(self):
        # At exactly 02:00, that boundary has already happened — the next
        # one is 04:00, not 02:00 again.
        now = datetime(2026, 9, 13, 2, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_boundary(now), datetime(2026, 9, 13, 4, 0, 0, tzinfo=timezone.utc))

    def test_mid_afternoon(self):
        now = datetime(2026, 9, 13, 9, 47, 0, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_boundary(now), datetime(2026, 9, 13, 10, 0, 0, tzinfo=timezone.utc))

    def test_rolls_over_to_the_next_day_at_midnight(self):
        now = datetime(2026, 9, 13, 23, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_boundary(now), datetime(2026, 9, 14, 0, 0, 0, tzinfo=timezone.utc))

    def test_every_boundary_is_an_even_multiple_of_the_interval(self):
        now = datetime(2026, 9, 13, 13, 5, 0, tzinfo=timezone.utc)
        boundary = scheduler.next_boundary(now, interval_hours=2)
        self.assertEqual(boundary.hour % 2, 0)
        self.assertEqual((boundary.minute, boundary.second, boundary.microsecond), (0, 0, 0))

    def test_custom_interval(self):
        now = datetime(2026, 9, 13, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_boundary(now, interval_hours=4), datetime(2026, 9, 13, 4, 0, 0, tzinfo=timezone.utc))


class RunSchedulerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "data" / "test.db"
        self.lock_path = self.tmp_path / "refresh.lock"

        sources_path = self.tmp_path / "sources.json"
        sources_path.write_text(json.dumps([{"type": "greenhouse", "company": "Adobe", "identifier": "adobe"}]))
        profile_path = self.tmp_path / "profile.json"
        profile_path.write_text(json.dumps({
            "profile_id": "test", "years_experience": 4,
            "target_titles": ["Full Stack Engineer"], "primary_locations": ["San Francisco"],
            "allow_remote_us": True, "allow_relocation_us": True,
            "primary_skills": ["React"], "secondary_skills": [],
        }))
        self.sources_path = sources_path
        self.profile_path = profile_path

    def _run(self, max_cycles, start=datetime(2026, 9, 13, 9, 47, 0, tzinfo=timezone.utc)):
        logs = []
        sleeps = []
        clock = [start]

        def now_fn():
            return clock[0]

        def sleep_fn(seconds):
            sleeps.append(seconds)
            clock[0] = clock[0] + timedelta(seconds=seconds)

        scheduler.run_scheduler(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            lock_path=self.lock_path,  # isolated from the real default lock file
            client=json_client(GREENHOUSE_PAYLOAD),
            now_fn=now_fn,
            sleep_fn=sleep_fn,
            log=logs.append,
            max_cycles=max_cycles,
        )

        return logs, sleeps

    def test_runs_immediately_without_sleeping_first(self):
        logs, sleeps = self._run(max_cycles=1)
        self.assertIn("refresh started", logs)
        self.assertTrue(any("refresh completed" in line for line in logs))
        self.assertEqual(sleeps, [])  # stopped before any sleep — ran once, immediately

    def test_sleeps_to_the_next_wall_clock_boundary_not_a_fixed_offset(self):
        start = datetime(2026, 9, 13, 9, 47, 0, tzinfo=timezone.utc)
        _, sleeps = self._run(max_cycles=2, start=start)
        # 9:47 -> 10:00 is 13 minutes, not "2 hours after start".
        self.assertEqual(sleeps, [780.0])

    def test_three_cycles_land_on_successive_two_hour_marks(self):
        logs, sleeps = self._run(max_cycles=3)
        self.assertEqual(sleeps, [780.0, 7200.0])
        self.assertIn("next scheduled run: 2026-09-13T10:00:00+00:00", logs)
        self.assertIn("next scheduled run: 2026-09-13T12:00:00+00:00", logs)

    def test_refreshes_never_overlap_each_cycle_fully_completes_first(self):
        logs, _ = self._run(max_cycles=3)
        # A "refresh completed" (or a recorded failure) always appears
        # before the *next* "refresh started" — cycles are strictly
        # sequential, never interleaved.
        started_indices = [i for i, line in enumerate(logs) if line == "refresh started"]
        for i, start_index in enumerate(started_indices[:-1]):
            next_start = started_indices[i + 1]
            between = logs[start_index:next_start]
            self.assertTrue(any("completed" in line or "failed" in line or "skipped" in line for line in between))

    def test_second_cycle_counts_zero_new_jobs(self):
        logs, _ = self._run(max_cycles=2)
        completed_lines = [line for line in logs if line.startswith("refresh completed")]
        self.assertIn("new=1", completed_lines[0])
        self.assertIn("new=0", completed_lines[1])

    def test_each_cycle_is_recorded_in_refresh_history(self):
        self._run(max_cycles=2)
        connection = database.connect(self.db_path)
        self.addCleanup(connection.close)
        self.assertEqual(len(database.list_refresh_runs(connection, "test")), 2)

    def test_a_source_failure_is_logged_but_the_loop_continues(self):
        import httpx

        def failing_client_factory():
            return httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(500, text="down", request=request)
            ))

        logs = []
        sleeps = []
        clock = [datetime(2026, 9, 13, 9, 0, 0, tzinfo=timezone.utc)]

        scheduler.run_scheduler(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            lock_path=self.lock_path,
            client=failing_client_factory(),
            now_fn=lambda: clock[0],
            sleep_fn=lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + timedelta(seconds=s))),
            log=logs.append,
            max_cycles=2,
        )

        self.assertTrue(any("status=failed" in line for line in logs))
        self.assertTrue(any("refresh errors" in line for line in logs))
        # The loop kept going for a second cycle despite the failure.
        self.assertEqual(logs.count("refresh started"), 2)


if __name__ == "__main__":
    unittest.main()
