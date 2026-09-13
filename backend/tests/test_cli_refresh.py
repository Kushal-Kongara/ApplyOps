"""CLI tests for `python -m app.cli refresh`."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import cli, database
from tests.support import GREENHOUSE_PAYLOAD, json_client


class CmdRefreshTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "data" / "test.db"
        self.lock_path = self.tmp_path / "refresh.lock"

        self.sources_path = self.tmp_path / "sources.json"
        self.sources_path.write_text(
            json.dumps([{"type": "greenhouse", "company": "Adobe", "identifier": "adobe"}])
        )
        self.profile_path = self.tmp_path / "profile.json"
        self.profile_path.write_text(json.dumps({
            "profile_id": "test", "years_experience": 4,
            "target_titles": ["Full Stack Engineer"], "primary_locations": ["San Francisco"],
            "allow_remote_us": True, "allow_relocation_us": True,
            "primary_skills": ["React"], "secondary_skills": [],
        }))

    def test_successful_refresh_exits_zero_and_prints_a_summary(self):
        with mock.patch("app.cli.refresh.refresh_from_files") as mock_refresh:
            import app.refresh as refresh_module

            mock_refresh.return_value = refresh_module.RefreshResult(
                profile_id="test",
                started_at=database.utcnow(),
                finished_at=database.utcnow(),
                status="success",
                sources=[
                    refresh_module.SourceOutcome(
                        company="Adobe", source="greenhouse", fetched=42, inserted=7,
                        updated=35, deactivated=0, failed=False, error=None,
                    )
                ],
                jobs_fetched=42, jobs_new=7, jobs_updated=35, jobs_deactivated=0,
                jobs_scored=30, jobs_filtered=12, high_priority_new=4, review_new=6,
                error_message=None,
            )

            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                exit_code = cli.main([
                    "refresh", "--config", str(self.sources_path),
                    "--profile", str(self.profile_path), "--db", str(self.db_path),
                ])

        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("Sources: 1/1 succeeded", output)
        self.assertIn("Fetched: 42", output)
        self.assertIn("New: 7", output)
        self.assertIn("Updated: 35", output)
        self.assertIn("Scored: 30", output)
        self.assertIn("Filtered: 12", output)
        self.assertIn("70+: 4", output)
        self.assertIn("65-69: 6", output)

    def test_end_to_end_refresh_against_a_real_mocked_source(self):
        # No CLI/mocking layer here — exercises the actual pipeline
        # `_cmd_refresh` calls, end to end, with a mocked HTTP transport.
        import app.refresh as refresh_module

        result = refresh_module.refresh_from_files(
            db_path=self.db_path, sources_path=self.sources_path, profile_path=self.profile_path,
            client=json_client(GREENHOUSE_PAYLOAD), lock_path=self.lock_path,
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.jobs_new, 1)

    def test_config_error_exits_with_code_two(self):
        bad_sources = self.tmp_path / "bad_sources.json"
        bad_sources.write_text("[]")

        buffer = io.StringIO()
        with mock.patch("sys.stderr", buffer):
            exit_code = cli.main([
                "refresh", "--config", str(bad_sources),
                "--profile", str(self.profile_path), "--db", str(self.db_path),
            ])

        self.assertEqual(exit_code, 2)
        self.assertIn("Configuration error", buffer.getvalue())

    def test_profile_error_exits_with_code_two(self):
        bad_profile = self.tmp_path / "bad_profile.json"
        bad_profile.write_text("{}")

        buffer = io.StringIO()
        with mock.patch("sys.stderr", buffer):
            exit_code = cli.main([
                "refresh", "--config", str(self.sources_path),
                "--profile", str(bad_profile), "--db", str(self.db_path),
            ])

        self.assertEqual(exit_code, 2)
        self.assertIn("Profile error", buffer.getvalue())

    def test_already_running_lock_exits_with_code_two(self):
        # The lock is an OS-level flock, not a file's mere existence/content
        # — a genuine hold requires actually acquiring it.
        import fcntl

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        held_file = open(self.lock_path, "w")
        self.addCleanup(held_file.close)
        fcntl.flock(held_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(fcntl.flock, held_file.fileno(), fcntl.LOCK_UN)

        buffer = io.StringIO()
        with mock.patch("sys.stderr", buffer):
            exit_code = cli.main([
                "refresh", "--config", str(self.sources_path),
                "--profile", str(self.profile_path), "--db", str(self.db_path),
                "--lock-path", str(self.lock_path),
            ])

        self.assertEqual(exit_code, 2)
        self.assertIn("Refresh error", buffer.getvalue())

    def test_partial_failure_exits_non_zero(self):
        with mock.patch("app.cli.refresh.refresh_from_files") as mock_refresh:
            import app.refresh as refresh_module

            mock_refresh.return_value = refresh_module.RefreshResult(
                profile_id="test", started_at=database.utcnow(), finished_at=database.utcnow(),
                status="partial",
                sources=[
                    refresh_module.SourceOutcome(
                        company="Adobe", source="greenhouse", fetched=1, inserted=1,
                        updated=0, deactivated=0, failed=False, error=None,
                    ),
                    refresh_module.SourceOutcome(
                        company="Beta", source="lever", fetched=0, inserted=0,
                        updated=0, deactivated=0, failed=True, error="HTTP 503",
                    ),
                ],
                jobs_fetched=1, jobs_new=1, jobs_updated=0, jobs_deactivated=0,
                jobs_scored=1, jobs_filtered=0, high_priority_new=0, review_new=0,
                error_message="Beta/lever: HTTP 503",
            )

            with mock.patch("sys.stdout", io.StringIO()):
                exit_code = cli.main([
                    "refresh", "--config", str(self.sources_path),
                    "--profile", str(self.profile_path), "--db", str(self.db_path),
                ])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
