"""Tests for `app/refresh.py`: one full collect+match cycle, correctly
distinguishing genuinely new jobs from ones seen again, and recording
what happened. No network calls, no real waiting."""

import tempfile
import unittest
from pathlib import Path

import httpx

from app import database, refresh
from app.config import SourceConfig
from app.models import Job, utcnow
from tests.support import (
    ASHBY_PAYLOAD,
    GREENHOUSE_PAYLOAD,
    LEVER_PAYLOAD,
    json_client,
    make_profile,
    recording_client,
    status_client,
)

SOURCES = [
    SourceConfig(type="greenhouse", company="Adobe", identifier="adobe"),
    SourceConfig(type="ashby", company="Example Startup", identifier="example"),
    SourceConfig(type="lever", company="Example Labs", identifier="example"),
]


def healthy_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "greenhouse" in host:
            return httpx.Response(200, json=GREENHOUSE_PAYLOAD, request=request)
        if "ashby" in host:
            return httpx.Response(200, json=ASHBY_PAYLOAD, request=request)
        return httpx.Response(200, json=LEVER_PAYLOAD, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def mixed_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "greenhouse" in host:
            return httpx.Response(200, json=GREENHOUSE_PAYLOAD, request=request)
        if "ashby" in host:
            return httpx.Response(503, text="unavailable", request=request)
        return httpx.Response(200, json=LEVER_PAYLOAD, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def all_fail_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


class RunRefreshTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.profile = make_profile(profile_id="test")


class RunRefreshBasicsTest(RunRefreshTestCase):
    def test_invokes_existing_collection_and_matching(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())

        # Reuses the exact same collection + matching this project already
        # has: jobs actually land in `jobs`, scores actually land in
        # `job_matches` — not just numbers reported back.
        self.assertEqual(len(database.list_jobs(self.connection, active_only=False, limit=100)), 3)
        self.assertEqual(result.jobs_fetched, 3)
        self.assertEqual(result.jobs_scored + result.jobs_filtered, 3)

    def test_no_sources_is_a_trivial_success(self):
        result = refresh.run_refresh(self.connection, [], self.profile)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.jobs_fetched, 0)


class NewVsSeenAgainTest(RunRefreshTestCase):
    def test_first_refresh_counts_every_job_as_new(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())
        self.assertEqual(result.jobs_new, 3)
        self.assertEqual(result.jobs_updated, 0)

    def test_second_refresh_of_the_same_jobs_counts_zero_new(self):
        refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())

        self.assertEqual(result.jobs_new, 0)
        self.assertEqual(result.jobs_updated, 3)

    def test_a_job_seen_again_does_not_reset_first_seen_at(self):
        refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())
        first_row = database.get_job(self.connection, "greenhouse:adobe:4567")
        first_seen_at_1 = first_row["first_seen_at"]

        refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())
        second_row = database.get_job(self.connection, "greenhouse:adobe:4567")

        self.assertEqual(second_row["first_seen_at"], first_seen_at_1)
        self.assertEqual(second_row["last_seen_at"] >= first_row["last_seen_at"], True)

    def test_a_genuinely_new_source_added_later_is_counted_new_the_others_are_not(self):
        refresh.run_refresh(self.connection, SOURCES[:2], self.profile, client=healthy_client())
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())

        # Only the third source's job is new this time; the first two were
        # already seen in the prior refresh.
        self.assertEqual(result.jobs_new, 1)
        self.assertEqual(result.jobs_updated, 2)


class NewMatchCountsTest(RunRefreshTestCase):
    def test_new_high_priority_and_review_counts_reflect_only_newly_discovered_jobs(self):
        profile = make_profile(
            profile_id="test",
            target_titles=["Full Stack Engineer", "Platform Engineer", "Backend Engineer"],
            primary_locations=["San Jose", "New York, NY"],
            primary_skills=["React", "Node.js", "Python", "SQL"],
        )
        result = refresh.run_refresh(self.connection, SOURCES, profile, client=healthy_client())

        self.assertEqual(result.high_priority_new + result.review_new, result.jobs_new - self._below_65_count(profile))

    def _below_65_count(self, profile) -> int:
        rows = database.list_matches(self.connection, profile.profile_id, min_score=0, limit=100)
        return sum(1 for r in rows if r["total_score"] < 65)

    def test_rescoring_the_same_job_again_does_not_recount_it_as_a_new_match(self):
        profile = make_profile(profile_id="test", primary_skills=["React", "Python"])
        first = refresh.run_refresh(self.connection, SOURCES, profile, client=healthy_client())
        second = refresh.run_refresh(self.connection, SOURCES, profile, client=healthy_client())

        self.assertGreaterEqual(first.high_priority_new + first.review_new, 0)
        self.assertEqual(second.high_priority_new, 0)
        self.assertEqual(second.review_new, 0)

    def test_filtered_new_job_is_not_counted_as_a_new_match(self):
        # An excluded-title job (e.g. an internship) may still be "new",
        # but it must not show up as a new 70+/65-69 match — it was never
        # scored as a candidate to begin with.
        profile = make_profile(profile_id="test")
        client, _ = recording_client(lambda request: httpx.Response(200, json={"jobs": [
            {"id": 1, "title": "Software Engineering Intern", "location": {"name": "Remote"}},
        ]}, request=request))
        source = [SourceConfig(type="greenhouse", company="Adobe", identifier="adobe")]

        result = refresh.run_refresh(self.connection, source, profile, client=client)

        self.assertEqual(result.jobs_new, 1)
        self.assertEqual(result.high_priority_new, 0)
        self.assertEqual(result.review_new, 0)


class FailureBehaviorTest(RunRefreshTestCase):
    def test_partial_failure_preserves_successful_sources_results(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=mixed_client())

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.sources_succeeded, 2)
        self.assertEqual(result.sources_failed, 1)
        # Adobe (greenhouse) and Example Labs (lever) still landed.
        self.assertEqual(len(database.list_jobs(self.connection, active_only=False, limit=100)), 2)

    def test_partial_failure_records_which_source_and_why(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=mixed_client())
        self.assertIn("Example Startup/ashby", result.error_message)
        self.assertIn("503", result.error_message)

    def test_total_failure_status_is_failed(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=all_fail_client())
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.sources_succeeded, 0)

    def test_status_client_failure_is_recorded_per_source(self):
        source = [SourceConfig(type="greenhouse", company="Adobe", identifier="adobe")]
        result = refresh.run_refresh(self.connection, source, self.profile, client=status_client(404))
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.sources[0].failed)
        self.assertIn("404", result.sources[0].error)


class SourceFailureDeactivationAuditTest(RunRefreshTestCase):
    """Audit: a failed source's existing jobs must never be deactivated just
    because its collector returned nothing this run.

    This isn't a new rule — `database.apply_scan_results` is only ever
    called after `collector.collect()` succeeds (see `cli.scan_sources`),
    so a failed source's deactivation step never runs at all, and
    `tests/test_cli.py::test_failed_scan_does_not_deactivate_existing_jobs`
    already proves it at that level. These tests prove the same guarantee
    holds end-to-end through `run_refresh`, and that a partial refresh
    doesn't let the failed source corrupt the successful ones' results.
    """

    def greenhouse_fails_client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            if "greenhouse" in host:
                return httpx.Response(503, text="down", request=request)
            if "ashby" in host:
                return httpx.Response(200, json=ASHBY_PAYLOAD, request=request)
            return httpx.Response(200, json=LEVER_PAYLOAD, request=request)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_greenhouse_failure_does_not_deactivate_its_existing_jobs(self):
        existing = Job(
            external_id="preexisting", source="greenhouse", source_identifier="adobe",
            company="Adobe", title="Existing Role", location="Remote", description="",
            application_url="https://example.com/1", posted_at=None, source_updated_at=None,
            first_seen_at=utcnow(),
        )
        database.upsert_jobs(self.connection, [existing])

        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=self.greenhouse_fails_client())

        self.assertEqual(result.status, "partial")
        row = database.get_job(self.connection, existing.unique_key)
        self.assertEqual(row["is_active"], 1)

    def test_successful_sources_still_reconcile_normally_during_a_partial_refresh(self):
        # A previously-active Ashby job genuinely missing from this run's
        # (successful) Ashby fetch must still be deactivated — the failed
        # Greenhouse source must not suppress reconciliation for sources
        # that *did* succeed.
        stale = Job(
            external_id="stale-ashby-job", source="ashby", source_identifier="example",
            company="Example Startup", title="No Longer Posted", location="Remote", description="",
            application_url="https://example.com/2", posted_at=None, source_updated_at=None,
            first_seen_at=utcnow(),
        )
        database.upsert_jobs(self.connection, [stale])

        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=self.greenhouse_fails_client())

        row = database.get_job(self.connection, stale.unique_key)
        self.assertEqual(row["is_active"], 0)
        self.assertGreater(result.jobs_deactivated, 0)

    def test_deactivated_count_is_not_corrupted_by_the_failed_source(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=self.greenhouse_fails_client())

        greenhouse_outcome = next(s for s in result.sources if s.source == "greenhouse")
        self.assertTrue(greenhouse_outcome.failed)
        self.assertEqual(greenhouse_outcome.deactivated, 0)


class RefreshRunPersistenceTest(RunRefreshTestCase):
    def test_record_refresh_run_stores_the_result(self):
        result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())
        refresh.record_refresh_run(self.connection, result)

        row = database.get_latest_refresh_run(self.connection, "test")
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["jobs_new"], 3)
        self.assertEqual(row["sources_attempted"], 3)
        self.assertIsNotNone(row["finished_at"])

    def test_multiple_runs_are_all_kept(self):
        for _ in range(2):
            result = refresh.run_refresh(self.connection, SOURCES, self.profile, client=healthy_client())
            refresh.record_refresh_run(self.connection, result)

        runs = database.list_refresh_runs(self.connection, "test")
        self.assertEqual(len(runs), 2)


class RefreshFromFilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "data" / "test.db"
        self.lock_path = self.tmp_path / "refresh.lock"

        self.sources_path = self.tmp_path / "sources.json"
        self.sources_path.write_text(
            '[{"type": "greenhouse", "company": "Adobe", "identifier": "adobe"}]'
        )
        self.profile_path = self.tmp_path / "profile.json"
        self.profile_path.write_text(
            '{"profile_id": "test", "years_experience": 4, '
            '"target_titles": ["Full Stack Engineer"], "primary_locations": ["San Francisco"], '
            '"allow_remote_us": true, "allow_relocation_us": true, '
            '"primary_skills": ["React"], "secondary_skills": []}'
        )

    def test_runs_end_to_end_and_persists_a_refresh_run(self):
        result = refresh.refresh_from_files(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            client=json_client(GREENHOUSE_PAYLOAD),
            lock_path=self.lock_path,
        )
        self.assertEqual(result.status, "success")

        connection = database.connect(self.db_path)
        self.addCleanup(connection.close)
        self.assertEqual(len(database.list_refresh_runs(connection, "test")), 1)

    def test_lock_is_released_after_a_successful_run_so_a_second_refresh_can_proceed(self):
        refresh.refresh_from_files(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            client=json_client(GREENHOUSE_PAYLOAD),
            lock_path=self.lock_path,
        )
        # The lock file itself may still exist (it's left as a diagnostic —
        # see app/refresh.py) but must no longer be *held*: a second run
        # right after the first must succeed, not raise.
        result = refresh.refresh_from_files(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            client=json_client(GREENHOUSE_PAYLOAD),
            lock_path=self.lock_path,
        )
        self.assertEqual(result.status, "success")

    def test_a_concurrent_refresh_is_rejected_while_the_lock_is_genuinely_held(self):
        import fcntl

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        held_file = open(self.lock_path, "w")
        self.addCleanup(held_file.close)
        fcntl.flock(held_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # simulate an in-progress refresh
        self.addCleanup(fcntl.flock, held_file.fileno(), fcntl.LOCK_UN)

        with self.assertRaises(refresh.RefreshAlreadyRunningError):
            refresh.refresh_from_files(
                db_path=self.db_path,
                sources_path=self.sources_path,
                profile_path=self.profile_path,
                client=json_client(GREENHOUSE_PAYLOAD),
                lock_path=self.lock_path,
            )

    def test_merely_writing_lock_file_contents_without_holding_flock_does_not_block(self):
        # The old design treated the lock file's mere *existence* (plus its
        # age) as meaningful. The new design only cares whether the OS-level
        # flock is actually held — a stray file with old-looking content but
        # no live lock on it must never block a refresh.
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text("99999")  # looks like a stale PID marker, holds no lock

        result = refresh.refresh_from_files(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            client=json_client(GREENHOUSE_PAYLOAD),
            lock_path=self.lock_path,
        )
        self.assertEqual(result.status, "success")

    def test_a_lock_left_by_a_crashed_process_does_not_block_a_new_refresh(self):
        # Simulates a crash: the lock is acquired and the file descriptor is
        # closed *without* going through the normal release path (no
        # LOCK_UN). A real crash closes every fd the same way — the kernel
        # releases the flock the instant the fd is gone, regardless of how
        # it was closed, so this must not leave the database locked out.
        import fcntl

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        crashed_file = open(self.lock_path, "w")
        fcntl.flock(crashed_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        crashed_file.close()  # no LOCK_UN — this is the "crash"

        result = refresh.refresh_from_files(
            db_path=self.db_path,
            sources_path=self.sources_path,
            profile_path=self.profile_path,
            client=json_client(GREENHOUSE_PAYLOAD),
            lock_path=self.lock_path,
        )
        self.assertEqual(result.status, "success")

    def test_a_killed_subprocess_holding_the_lock_does_not_block_a_new_refresh(self):
        # Stronger version of the crash test above: an actual separate OS
        # process holds the lock and is killed with SIGKILL (no cleanup
        # code runs at all, unlike an in-process `close()`). Proves the
        # safety property doesn't depend on any of *our* code running
        # during process teardown — only on kernel behavior.
        import subprocess
        import sys
        import time

        holder_script = (
            "import fcntl, time, sys\n"
            f"f = open({str(self.lock_path)!r}, 'w')\n"
            "fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "sys.stdout.write('locked\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [sys.executable, "-c", holder_script], stdout=subprocess.PIPE, text=True
        )
        try:
            line = process.stdout.readline()
            self.assertEqual(line.strip(), "locked")

            # While the subprocess holds the lock, a refresh must be rejected.
            with self.assertRaises(refresh.RefreshAlreadyRunningError):
                refresh.refresh_from_files(
                    db_path=self.db_path, sources_path=self.sources_path,
                    profile_path=self.profile_path, client=json_client(GREENHOUSE_PAYLOAD),
                    lock_path=self.lock_path,
                )
        finally:
            process.kill()  # SIGKILL — no Python cleanup code runs in the child
            process.wait(timeout=5)
            process.stdout.close()

        # A brief wait for the kernel to finish tearing down the killed
        # process's file descriptors before asserting the lock is free.
        deadline = time.monotonic() + 2
        last_error = None
        while time.monotonic() < deadline:
            try:
                result = refresh.refresh_from_files(
                    db_path=self.db_path, sources_path=self.sources_path,
                    profile_path=self.profile_path, client=json_client(GREENHOUSE_PAYLOAD),
                    lock_path=self.lock_path,
                )
                self.assertEqual(result.status, "success")
                return
            except refresh.RefreshAlreadyRunningError as exc:
                last_error = exc
                time.sleep(0.05)
        self.fail(f"lock was still held after the holder process was killed: {last_error}")


if __name__ == "__main__":
    unittest.main()
