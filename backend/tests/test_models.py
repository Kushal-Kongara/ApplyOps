from datetime import datetime, timezone
import unittest

from app.models import Job


def make_job(**overrides) -> Job:
    fields = {
        "external_id": "123",
        "source": "Greenhouse",
        "source_identifier": "adobe-board",
        "company": "Adobe",
        "title": "Full Stack Engineer",
        "location": "San Jose, CA",
        "description": "Build customer-facing products.",
        "application_url": "https://example.com/jobs/123",
        "posted_at": None,
        "source_updated_at": None,
        "first_seen_at": datetime.now(timezone.utc),
    }
    fields.update(overrides)
    return Job(**fields)


class JobTest(unittest.TestCase):
    def test_unique_key_identifies_a_job(self):
        job = make_job()

        self.assertEqual(
            job.unique_key,
            "greenhouse:adobe-board:123",
        )


class UniqueKeyStabilityTest(unittest.TestCase):
    def test_key_ignores_fields_that_change_between_scans(self):
        first = make_job()
        later = make_job(
            title="Senior Full Stack Engineer",
            location="Remote",
            description="Rewritten description.",
            first_seen_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(first.unique_key, later.unique_key)

    def test_key_unaffected_by_company_rename(self):
        # The whole point of dropping company from the key: renaming the
        # display name in config must not create a duplicate job.
        original = make_job(company="Adobe")
        renamed = make_job(company="Adobe Inc.")

        self.assertEqual(original.unique_key, renamed.unique_key)

    def test_key_changes_with_external_id_or_source_identifier_or_source(self):
        base = make_job()

        self.assertNotEqual(base.unique_key, make_job(external_id="9999").unique_key)
        self.assertNotEqual(
            base.unique_key, make_job(source_identifier="figma-board").unique_key
        )
        self.assertNotEqual(base.unique_key, make_job(source="lever").unique_key)

    def test_key_is_case_insensitive(self):
        self.assertEqual(
            make_job(source="Greenhouse", source_identifier="ADOBE-BOARD").unique_key,
            make_job(source="greenhouse", source_identifier="adobe-board").unique_key,
        )

    def test_key_is_insensitive_to_surrounding_whitespace(self):
        self.assertEqual(
            make_job(source_identifier="  adobe-board  ").unique_key,
            make_job(source_identifier="adobe-board").unique_key,
        )


class SeenTimestampsTest(unittest.TestCase):
    def test_last_seen_at_defaults_to_first_seen_at(self):
        now = datetime.now(timezone.utc)
        job = make_job(first_seen_at=now, last_seen_at=None)

        self.assertEqual(job.last_seen_at, now)
        self.assertTrue(job.is_active)


if __name__ == "__main__":
    unittest.main()
