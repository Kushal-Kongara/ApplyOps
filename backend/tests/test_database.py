"""Storage tests: schema, de-duplication, deactivation, and scan history."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database
from app.models import Job

FIRST_SCAN = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
SECOND_SCAN = FIRST_SCAN + timedelta(days=1)


def make_job(
    seen_at: datetime,
    title: str = "Full Stack Engineer",
    external_id: str = "4567",
    source: str = "greenhouse",
    source_identifier: str = "adobe-board",
    company: str = "Adobe",
    is_active: bool = True,
    **overrides,
) -> Job:
    fields = {
        "external_id": external_id,
        "source": source,
        "source_identifier": source_identifier,
        "company": company,
        "title": title,
        "location": "San Jose, CA",
        "description": "Build products.",
        "application_url": f"https://boards.greenhouse.io/adobe/jobs/{external_id}",
        "posted_at": FIRST_SCAN,
        "source_updated_at": None,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
        "is_active": is_active,
    }
    fields.update(overrides)
    return Job(**fields)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "data" / "test.db"
        self.connection = database.connect(self.db_path)
        self.addCleanup(self.connection.close)


class SchemaTest(DatabaseTestCase):
    def test_creates_tables(self):
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        names = {row["name"] for row in rows}

        self.assertIn("jobs", names)
        self.assertIn("scan_runs", names)

    def test_create_schema_is_repeatable(self):
        database.create_schema(self.connection)
        database.create_schema(self.connection)

        self.assertEqual(len(database.list_jobs(self.connection)), 0)


class UpsertTest(DatabaseTestCase):
    def test_inserts_new_job(self):
        inserted, updated = database.upsert_jobs(self.connection, [make_job(FIRST_SCAN)])

        self.assertEqual((inserted, updated), (1, 0))
        self.assertEqual(len(database.list_jobs(self.connection)), 1)

    def test_same_job_twice_does_not_duplicate(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN)])
        inserted, updated = database.upsert_jobs(self.connection, [make_job(SECOND_SCAN)])

        self.assertEqual((inserted, updated), (0, 1))
        count = self.connection.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_first_seen_at_is_preserved(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN)])
        database.upsert_jobs(self.connection, [make_job(SECOND_SCAN)])

        row = database.get_job(self.connection, "greenhouse:adobe-board:4567")

        self.assertEqual(row["first_seen_at"], FIRST_SCAN.isoformat())

    def test_last_seen_at_is_updated(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN)])
        database.upsert_jobs(self.connection, [make_job(SECOND_SCAN)])

        row = database.get_job(self.connection, "greenhouse:adobe-board:4567")

        self.assertEqual(row["last_seen_at"], SECOND_SCAN.isoformat())

    def test_mutable_fields_are_refreshed(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN)])
        database.upsert_jobs(
            self.connection,
            [make_job(SECOND_SCAN, title="Senior Full Stack Engineer", location="Remote")],
        )

        row = database.get_job(self.connection, "greenhouse:adobe-board:4567")

        self.assertEqual(row["title"], "Senior Full Stack Engineer")
        self.assertEqual(row["location"], "Remote")

    def test_company_rename_updates_metadata_but_not_identity(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN, company="Adobe")])
        database.upsert_jobs(self.connection, [make_job(SECOND_SCAN, company="Adobe Inc.")])

        self.assertEqual(len(database.list_jobs(self.connection)), 1)
        row = database.get_job(self.connection, "greenhouse:adobe-board:4567")
        self.assertEqual(row["company"], "Adobe Inc.")

    def test_different_jobs_are_stored_separately(self):
        jobs = [make_job(FIRST_SCAN), make_job(FIRST_SCAN, external_id="9999")]

        inserted, updated = database.upsert_jobs(self.connection, jobs)

        self.assertEqual((inserted, updated), (2, 0))

    def test_same_external_id_at_different_boards_is_not_a_duplicate(self):
        jobs = [make_job(FIRST_SCAN), make_job(FIRST_SCAN, source_identifier="figma-board")]

        inserted, _ = database.upsert_jobs(self.connection, jobs)

        self.assertEqual(inserted, 2)

    def test_same_external_id_and_board_with_different_company_name_is_one_job(self):
        # Guards the fix: identity comes from source + source_identifier +
        # external_id, not company.
        jobs = [make_job(FIRST_SCAN, company="Adobe"), make_job(FIRST_SCAN, company="ADOBE INC")]

        inserted, updated = database.upsert_jobs(self.connection, jobs)

        self.assertEqual((inserted, updated), (1, 1))
        self.assertEqual(len(database.list_jobs(self.connection)), 1)

    def test_inactive_jobs_are_hidden_by_default(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN, is_active=False)])

        self.assertEqual(len(database.list_jobs(self.connection)), 0)
        self.assertEqual(len(database.list_jobs(self.connection, active_only=False)), 1)

    def test_stored_timestamps_are_timezone_aware_utc(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN)])

        row = database.get_job(self.connection, "greenhouse:adobe-board:4567")
        parsed = datetime.fromisoformat(row["first_seen_at"])

        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_reactivates_a_job_seen_again(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN, is_active=False)])
        database.upsert_jobs(self.connection, [make_job(SECOND_SCAN, is_active=True)])

        row = database.get_job(self.connection, "greenhouse:adobe-board:4567")
        self.assertEqual(row["is_active"], 1)


class DeactivateMissingJobsTest(DatabaseTestCase):
    """Direct tests of the deactivation helper, independent of a full scan."""

    def test_job_absent_from_seen_keys_is_deactivated(self):
        database.upsert_jobs(
            self.connection,
            [
                make_job(FIRST_SCAN, external_id="1"),
                make_job(FIRST_SCAN, external_id="2"),
            ],
        )

        still_present = make_job(SECOND_SCAN, external_id="1").unique_key
        count = database.deactivate_missing_jobs(
            self.connection, "greenhouse", "adobe-board", [still_present]
        )

        self.assertEqual(count, 1)
        rows = {r["external_id"]: r["is_active"] for r in database.list_jobs(
            self.connection, active_only=False
        )}
        self.assertEqual(rows["1"], 1)
        self.assertEqual(rows["2"], 0)

    def test_empty_seen_keys_deactivates_everything_for_that_board(self):
        database.upsert_jobs(
            self.connection,
            [make_job(FIRST_SCAN, external_id="1"), make_job(FIRST_SCAN, external_id="2")],
        )

        count = database.deactivate_missing_jobs(self.connection, "greenhouse", "adobe-board", [])

        self.assertEqual(count, 2)
        self.assertEqual(len(database.list_jobs(self.connection)), 0)

    def test_other_source_identifier_is_unaffected(self):
        database.upsert_jobs(
            self.connection,
            [
                make_job(FIRST_SCAN, external_id="1", source_identifier="adobe-board"),
                make_job(FIRST_SCAN, external_id="2", source_identifier="figma-board"),
            ],
        )

        database.deactivate_missing_jobs(self.connection, "greenhouse", "adobe-board", [])

        rows = {r["source_identifier"]: r["is_active"] for r in database.list_jobs(
            self.connection, active_only=False
        )}
        self.assertEqual(rows["adobe-board"], 0)
        self.assertEqual(rows["figma-board"], 1)

    def test_other_source_is_unaffected(self):
        database.upsert_jobs(
            self.connection,
            [
                make_job(FIRST_SCAN, external_id="1", source="greenhouse", source_identifier="x"),
                make_job(FIRST_SCAN, external_id="1", source="lever", source_identifier="x"),
            ],
        )

        database.deactivate_missing_jobs(self.connection, "greenhouse", "x", [])

        rows = {r["source"]: r["is_active"] for r in database.list_jobs(
            self.connection, active_only=False
        )}
        self.assertEqual(rows["greenhouse"], 0)
        self.assertEqual(rows["lever"], 1)

    def test_matching_is_case_and_whitespace_insensitive(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN, external_id="1")])

        count = database.deactivate_missing_jobs(self.connection, "GREENHOUSE", " Adobe-Board ", [])

        self.assertEqual(count, 1)

    def test_already_inactive_jobs_are_not_recounted(self):
        database.upsert_jobs(self.connection, [make_job(FIRST_SCAN, external_id="1", is_active=False)])

        count = database.deactivate_missing_jobs(self.connection, "greenhouse", "adobe-board", [])

        self.assertEqual(count, 0)


class ApplyScanResultsTest(DatabaseTestCase):
    """The combined upsert + deactivate call a real scan uses."""

    def test_missing_job_becomes_inactive_after_successful_later_scan(self):
        database.apply_scan_results(
            self.connection,
            [make_job(FIRST_SCAN, external_id="1"), make_job(FIRST_SCAN, external_id="2")],
            source="greenhouse",
            source_identifier="adobe-board",
        )

        inserted, updated, deactivated = database.apply_scan_results(
            self.connection,
            [make_job(SECOND_SCAN, external_id="1")],
            source="greenhouse",
            source_identifier="adobe-board",
        )

        self.assertEqual((inserted, updated, deactivated), (0, 1, 1))
        rows = {r["external_id"]: r["is_active"] for r in database.list_jobs(
            self.connection, active_only=False
        )}
        self.assertEqual(rows["1"], 1)
        self.assertEqual(rows["2"], 0)
        # History survives — the row is not deleted.
        self.assertEqual(
            len(self.connection.execute("SELECT id FROM jobs").fetchall()), 2
        )

    def test_jobs_from_another_source_identifier_are_unaffected(self):
        database.apply_scan_results(
            self.connection,
            [make_job(FIRST_SCAN, external_id="1", source_identifier="figma-board")],
            source="greenhouse",
            source_identifier="figma-board",
        )

        # A scan of a *different* board with zero results must not touch
        # Figma's job.
        database.apply_scan_results(
            self.connection, [], source="greenhouse", source_identifier="adobe-board"
        )

        row = database.get_job(self.connection, "greenhouse:figma-board:1")
        self.assertEqual(row["is_active"], 1)

    def test_inactive_job_is_reactivated_when_seen_again(self):
        database.apply_scan_results(
            self.connection,
            [make_job(FIRST_SCAN, external_id="1")],
            source="greenhouse",
            source_identifier="adobe-board",
        )
        database.apply_scan_results(
            self.connection, [], source="greenhouse", source_identifier="adobe-board"
        )
        row = database.get_job(self.connection, "greenhouse:adobe-board:1")
        self.assertEqual(row["is_active"], 0)

        inserted, updated, deactivated = database.apply_scan_results(
            self.connection,
            [make_job(SECOND_SCAN, external_id="1")],
            source="greenhouse",
            source_identifier="adobe-board",
        )

        self.assertEqual(deactivated, 0)
        row = database.get_job(self.connection, "greenhouse:adobe-board:1")
        self.assertEqual(row["is_active"], 1)

    def test_successful_empty_result_is_handled_without_sql_errors(self):
        database.apply_scan_results(
            self.connection,
            [make_job(FIRST_SCAN, external_id="1"), make_job(FIRST_SCAN, external_id="2")],
            source="greenhouse",
            source_identifier="adobe-board",
        )

        inserted, updated, deactivated = database.apply_scan_results(
            self.connection, [], source="greenhouse", source_identifier="adobe-board"
        )

        self.assertEqual((inserted, updated, deactivated), (0, 0, 2))
        self.assertEqual(len(database.list_jobs(self.connection)), 0)


class ScanRunTest(DatabaseTestCase):
    def test_records_a_successful_scan(self):
        scan_id = database.start_scan_run(self.connection, "greenhouse", "Adobe", FIRST_SCAN)
        database.finish_scan_run(
            self.connection,
            scan_id,
            status="success",
            fetched=42,
            inserted=7,
            updated=35,
            deactivated=3,
        )

        row = database.list_scan_runs(self.connection)[0]

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["source"], "greenhouse")
        self.assertEqual(row["company"], "Adobe")
        self.assertEqual(row["fetched_count"], 42)
        self.assertEqual(row["inserted_count"], 7)
        self.assertEqual(row["updated_count"], 35)
        self.assertEqual(row["deactivated_count"], 3)
        self.assertIsNotNone(row["finished_at"])
        self.assertIsNone(row["error_message"])

    def test_records_a_failed_scan(self):
        scan_id = database.start_scan_run(self.connection, "ashby", "Example Startup")
        database.finish_scan_run(
            self.connection, scan_id, status="failed", error_message="HTTP 404 from ..."
        )

        row = database.list_scan_runs(self.connection)[0]

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_message"], "HTTP 404 from ...")
        self.assertEqual(row["fetched_count"], 0)
        self.assertEqual(row["deactivated_count"], 0)


if __name__ == "__main__":
    unittest.main()
