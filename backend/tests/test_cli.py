"""CLI tests: reporting, resilience, exit codes. All HTTP is mocked."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from app import cli, database
from app.config import SourceConfig
from app.models import Job, utcnow
from tests.support import ASHBY_PAYLOAD, GREENHOUSE_PAYLOAD, LEVER_PAYLOAD, json_client

GREENHOUSE_TWO_JOBS = {
    "jobs": GREENHOUSE_PAYLOAD["jobs"]
    + [
        {
            "id": 8888,
            "title": "Data Engineer",
            "updated_at": "2026-08-01T12:00:00-04:00",
            "first_published": "2026-07-30T09:30:00-04:00",
            "absolute_url": "https://boards.greenhouse.io/adobe/jobs/8888",
            "location": {"name": "Remote"},
            "content": "<p>Own the pipeline.</p>",
        }
    ]
}

SOURCES = [
    SourceConfig(type="greenhouse", company="Adobe", identifier="adobe"),
    SourceConfig(type="ashby", company="Example Startup", identifier="example"),
    SourceConfig(type="lever", company="Example Labs", identifier="example"),
]


def mixed_client() -> httpx.Client:
    """Greenhouse and Lever answer normally; Ashby returns a server error."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "greenhouse" in host:
            return httpx.Response(200, json=GREENHOUSE_PAYLOAD, request=request)
        if "ashby" in host:
            return httpx.Response(503, text="unavailable", request=request)
        return httpx.Response(200, json=LEVER_PAYLOAD, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def healthy_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "greenhouse" in host:
            return httpx.Response(200, json=GREENHOUSE_PAYLOAD, request=request)
        if "ashby" in host:
            return httpx.Response(200, json=ASHBY_PAYLOAD, request=request)
        return httpx.Response(200, json=LEVER_PAYLOAD, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)
        self.out = io.StringIO()


class ScanSourcesTest(CliTestCase):
    def test_healthy_scan_reports_each_source(self):
        results = cli.scan_sources(
            self.connection, SOURCES, client=healthy_client(), out=self.out
        )
        cli.print_summary(results, out=self.out)
        output = self.out.getvalue()

        self.assertIn("Adobe / greenhouse: 1 fetched, 1 new, 0 updated", output)
        self.assertIn("Example Startup / ashby: 1 fetched, 1 new, 0 updated", output)
        self.assertIn("Scan complete: 3 new jobs, 0 updated", output)
        self.assertNotIn("failed", output)

    def test_one_failed_source_does_not_stop_the_scan(self):
        results = cli.scan_sources(
            self.connection, SOURCES, client=mixed_client(), out=self.out
        )

        self.assertEqual(len(results), 3)
        self.assertFalse(results[0].failed)
        self.assertTrue(results[1].failed)
        self.assertFalse(results[2].failed)
        # The two healthy sources still stored their jobs.
        self.assertEqual(len(database.list_jobs(self.connection)), 2)

    def test_failure_is_reported_with_a_useful_message(self):
        cli.scan_sources(self.connection, SOURCES, client=mixed_client(), out=self.out)
        output = self.out.getvalue()

        self.assertIn("Example Startup / ashby: failed — HTTP 503", output)

    def test_summary_counts_failed_sources(self):
        results = cli.scan_sources(
            self.connection, SOURCES, client=mixed_client(), out=self.out
        )
        self.out.truncate(0)
        self.out.seek(0)
        cli.print_summary(results, out=self.out)

        self.assertEqual(
            self.out.getvalue().strip(),
            "Scan complete: 2 new jobs, 0 updated, 1 source failed",
        )

    def test_failure_is_recorded_in_scan_runs(self):
        cli.scan_sources(self.connection, SOURCES, client=mixed_client(), out=self.out)

        runs = {(r["company"], r["status"]): r for r in database.list_scan_runs(self.connection)}
        failed = runs[("Example Startup", "failed")]

        self.assertEqual(len(runs), 3)
        self.assertIn("HTTP 503", failed["error_message"])
        self.assertIsNotNone(failed["finished_at"])

    def test_second_scan_updates_instead_of_inserting(self):
        cli.scan_sources(self.connection, SOURCES, client=healthy_client(), out=self.out)
        self.out.truncate(0)
        self.out.seek(0)

        results = cli.scan_sources(
            self.connection, SOURCES, client=healthy_client(), out=self.out
        )

        self.assertEqual(sum(r.inserted for r in results), 0)
        self.assertEqual(sum(r.updated for r in results), 3)
        self.assertIn("Adobe / greenhouse: 1 fetched, 0 new, 1 updated", self.out.getvalue())


class DeactivationTest(CliTestCase):
    GREENHOUSE_ONLY = [SourceConfig(type="greenhouse", company="Adobe", identifier="adobe")]

    def test_missing_job_is_deactivated_and_reported(self):
        cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_TWO_JOBS),
            out=self.out,
        )
        self.assertEqual(len(database.list_jobs(self.connection)), 2)

        self.out.truncate(0)
        self.out.seek(0)
        results = cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_PAYLOAD),
            out=self.out,
        )
        cli.print_summary(results, out=self.out)
        output = self.out.getvalue()

        self.assertEqual(results[0].deactivated, 1)
        self.assertIn("Adobe / greenhouse: 1 fetched, 0 new, 1 updated, 1 deactivated", output)
        self.assertIn("Scan complete: 0 new jobs, 1 updated, 1 deactivated", output)
        self.assertEqual(len(database.list_jobs(self.connection)), 1)
        self.assertEqual(len(database.list_jobs(self.connection, active_only=False)), 2)

    def test_failed_scan_does_not_deactivate_existing_jobs(self):
        # Pre-existing active Ashby job, from a prior successful scan.
        existing = Job(
            external_id="preexisting",
            source="ashby",
            source_identifier="example",
            company="Example Startup",
            title="Support Engineer",
            location="Remote",
            description="",
            application_url="",
            posted_at=None,
            source_updated_at=None,
            first_seen_at=utcnow(),
        )
        database.upsert_jobs(self.connection, [existing])

        # mixed_client() makes the Ashby source fail with HTTP 503.
        cli.scan_sources(self.connection, SOURCES, client=mixed_client(), out=self.out)

        row = database.get_job(self.connection, existing.unique_key)
        self.assertEqual(row["is_active"], 1)

    def test_jobs_from_a_different_board_are_unaffected_by_deactivation(self):
        figma_job = Job(
            external_id="1",
            source="greenhouse",
            source_identifier="figma",
            company="Figma",
            title="Designer",
            location="Remote",
            description="",
            application_url="",
            posted_at=None,
            source_updated_at=None,
            first_seen_at=utcnow(),
        )
        database.upsert_jobs(self.connection, [figma_job])

        cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_PAYLOAD),
            out=self.out,
        )

        row = database.get_job(self.connection, figma_job.unique_key)
        self.assertEqual(row["is_active"], 1)

    def test_successful_empty_scan_deactivates_without_error(self):
        cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_PAYLOAD),
            out=self.out,
        )

        self.out.truncate(0)
        self.out.seek(0)
        results = cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client({"jobs": []}),
            out=self.out,
        )

        self.assertEqual(results[0].deactivated, 1)
        self.assertEqual(len(database.list_jobs(self.connection)), 0)

    def test_inactive_job_is_reactivated_on_a_later_successful_scan(self):
        cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_TWO_JOBS),
            out=self.out,
        )
        cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_PAYLOAD),
            out=self.out,
        )
        row = database.get_job(self.connection, "greenhouse:adobe:8888")
        self.assertEqual(row["is_active"], 0)

        cli.scan_sources(
            self.connection,
            self.GREENHOUSE_ONLY,
            client=json_client(GREENHOUSE_TWO_JOBS),
            out=self.out,
        )

        row = database.get_job(self.connection, "greenhouse:adobe:8888")
        self.assertEqual(row["is_active"], 1)


class MainTest(CliTestCase):
    def write_config(self, payload) -> Path:
        path = self.tmp_path / "sources.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_invalid_config_exits_with_code_two(self):
        config = self.write_config([{"type": "workday", "company": "A", "identifier": "a"}])

        with mock.patch("sys.stderr", io.StringIO()) as stderr:
            exit_code = cli.main(["scan", "--config", str(config), "--db", str(self.db_path)])

        self.assertEqual(exit_code, 2)
        self.assertIn("unsupported source type", stderr.getvalue())

    def test_failed_source_exits_non_zero(self):
        config = self.write_config(
            [{"type": "greenhouse", "company": "Adobe", "identifier": "adobe"}]
        )
        failing = [cli.SourceResult(company="Adobe", source="greenhouse", error="HTTP 503")]

        with mock.patch.object(cli, "scan_sources", return_value=failing), mock.patch(
            "sys.stdout", io.StringIO()
        ):
            exit_code = cli.main(["scan", "--config", str(config), "--db", str(self.db_path)])

        self.assertEqual(exit_code, 1)

    def test_healthy_scan_exits_zero(self):
        config = self.write_config(
            [{"type": "greenhouse", "company": "Adobe", "identifier": "adobe"}]
        )
        ok = [cli.SourceResult(company="Adobe", source="greenhouse", fetched=1, inserted=1)]

        with mock.patch.object(cli, "scan_sources", return_value=ok), mock.patch(
            "sys.stdout", io.StringIO()
        ):
            exit_code = cli.main(["scan", "--config", str(config), "--db", str(self.db_path)])

        self.assertEqual(exit_code, 0)

    def test_list_jobs_reports_stored_jobs(self):
        cli.scan_sources(self.connection, SOURCES, client=healthy_client(), out=self.out)

        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(["list-jobs", "--db", str(self.db_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("Full Stack Engineer", buffer.getvalue())

    def test_list_jobs_on_empty_database(self):
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            exit_code = cli.main(["list-jobs", "--db", str(self.db_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("No jobs stored yet", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
