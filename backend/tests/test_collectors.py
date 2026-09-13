"""Collector normalization tests. No network access: every client is mocked."""

import unittest
from datetime import datetime, timezone

import httpx

from app.collectors import AshbyCollector, GreenhouseCollector, LeverCollector
from tests.support import (
    ASHBY_PAYLOAD,
    GREENHOUSE_PAYLOAD,
    LEVER_PAYLOAD,
    json_client,
    recording_client,
    status_client,
)


class GreenhouseCollectorTest(unittest.TestCase):
    def test_normalizes_a_posting(self):
        collector = GreenhouseCollector(
            company="Adobe", identifier="adobe", client=json_client(GREENHOUSE_PAYLOAD)
        )

        jobs = collector.collect()

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.external_id, "4567")
        self.assertEqual(job.source, "greenhouse")
        self.assertEqual(job.source_identifier, "adobe")
        self.assertEqual(job.company, "Adobe")
        self.assertEqual(job.title, "Full Stack Engineer")
        self.assertEqual(job.location, "San Jose, CA")
        self.assertEqual(job.application_url, "https://boards.greenhouse.io/adobe/jobs/4567")
        self.assertEqual(job.unique_key, "greenhouse:adobe:4567")
        self.assertTrue(job.is_active)

    def test_converts_escaped_html_description_to_text(self):
        collector = GreenhouseCollector(
            company="Adobe", identifier="adobe", client=json_client(GREENHOUSE_PAYLOAD)
        )

        description = collector.collect()[0].description

        self.assertIn("Build products.", description)
        self.assertIn("- Ship code", description)
        self.assertNotIn("<p>", description)
        self.assertNotIn("&lt;", description)

    def test_posted_at_uses_first_published_only(self):
        collector = GreenhouseCollector(
            company="Adobe", identifier="adobe", client=json_client(GREENHOUSE_PAYLOAD)
        )

        job = collector.collect()[0]

        # first_published (07-30) is the real publish date; updated_at
        # (08-01) must never leak into posted_at.
        self.assertEqual(job.posted_at, datetime(2026, 7, 30, 13, 30, tzinfo=timezone.utc))
        self.assertIs(job.posted_at.tzinfo, timezone.utc)

    def test_source_updated_at_uses_updated_at_field(self):
        collector = GreenhouseCollector(
            company="Adobe", identifier="adobe", client=json_client(GREENHOUSE_PAYLOAD)
        )

        job = collector.collect()[0]

        self.assertEqual(job.source_updated_at, datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc))

    def test_requests_the_documented_endpoint_with_a_user_agent(self):
        client, requests = recording_client(
            lambda request: httpx.Response(200, json=GREENHOUSE_PAYLOAD, request=request)
        )
        GreenhouseCollector(company="Adobe", identifier="adobe", client=client).collect()

        self.assertEqual(len(requests), 1)
        self.assertEqual(
            str(requests[0].url),
            "https://boards-api.greenhouse.io/v1/boards/adobe/jobs?content=true",
        )
        self.assertIn("ApplyOps", requests[0].headers["user-agent"])

    def test_missing_optional_fields_are_safe(self):
        payload = {"jobs": [{"id": 1}]}
        collector = GreenhouseCollector(
            company="Adobe", identifier="adobe", client=json_client(payload)
        )

        job = collector.collect()[0]

        self.assertEqual(job.title, "")
        self.assertEqual(job.location, "")
        self.assertEqual(job.description, "")
        self.assertEqual(job.application_url, "")
        self.assertIsNone(job.posted_at)
        self.assertIsNone(job.source_updated_at)
        self.assertEqual(job.source_identifier, "adobe")

    def test_http_error_is_raised(self):
        collector = GreenhouseCollector(
            company="Adobe", identifier="adobe", client=status_client(404)
        )

        with self.assertRaises(httpx.HTTPStatusError):
            collector.collect()


class AshbyCollectorTest(unittest.TestCase):
    def test_normalizes_a_posting(self):
        collector = AshbyCollector(
            company="Example Startup", identifier="example", client=json_client(ASHBY_PAYLOAD)
        )

        job = collector.collect()[0]

        self.assertEqual(job.external_id, "b1f0c2d3-1111-2222-3333-444455556666")
        self.assertEqual(job.source, "ashby")
        self.assertEqual(job.source_identifier, "example")
        self.assertEqual(
            job.application_url,
            "https://jobs.ashbyhq.com/example/b1f0c2d3/application",
        )
        self.assertIn("Own the API.", job.description)
        self.assertIn("- Python", job.description)
        self.assertNotIn("<p>", job.description)
        self.assertEqual(job.posted_at, datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(job.source_updated_at, datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc))

    def test_requests_the_documented_endpoint(self):
        client, requests = recording_client(
            lambda request: httpx.Response(200, json=ASHBY_PAYLOAD, request=request)
        )
        AshbyCollector(company="Example Startup", identifier="example", client=client).collect()

        self.assertEqual(
            str(requests[0].url), "https://api.ashbyhq.com/posting-api/job-board/example"
        )

    def test_missing_optional_fields_are_safe(self):
        payload = {"jobs": [{"id": "abc"}]}
        collector = AshbyCollector(
            company="Example Startup", identifier="example", client=json_client(payload)
        )

        job = collector.collect()[0]

        self.assertEqual(job.external_id, "abc")
        self.assertEqual(job.description, "")
        self.assertEqual(job.application_url, "")
        self.assertIsNone(job.posted_at)
        self.assertIsNone(job.source_updated_at)
        self.assertTrue(job.is_active)
        self.assertEqual(job.source_identifier, "example")

    def test_unlisted_job_is_inactive(self):
        payload = {"jobs": [{"id": "abc", "isListed": False}]}
        collector = AshbyCollector(
            company="Example Startup", identifier="example", client=json_client(payload)
        )

        self.assertFalse(collector.collect()[0].is_active)

    def test_http_error_is_raised(self):
        collector = AshbyCollector(
            company="Example Startup", identifier="example", client=status_client(500)
        )

        with self.assertRaises(httpx.HTTPStatusError):
            collector.collect()


class LeverCollectorTest(unittest.TestCase):
    def test_normalizes_a_posting(self):
        collector = LeverCollector(
            company="Example Labs", identifier="example", client=json_client(LEVER_PAYLOAD)
        )

        job = collector.collect()[0]

        self.assertEqual(job.external_id, "9a8b7c6d-0000-1111-2222-333344445555")
        self.assertEqual(job.source, "lever")
        self.assertEqual(job.source_identifier, "example")
        self.assertEqual(job.title, "Platform Engineer")
        self.assertEqual(job.location, "New York, NY")
        self.assertEqual(job.application_url, "https://jobs.lever.co/example/9a8b7c6d")
        self.assertEqual(job.description, "Run the platform.")
        self.assertEqual(job.posted_at, datetime(2025, 8, 4, 12, 0, tzinfo=timezone.utc))
        # Lever's public postings API has no documented "last modified"
        # field, so we don't guess one.
        self.assertIsNone(job.source_updated_at)

    def test_requests_the_documented_endpoint(self):
        client, requests = recording_client(
            lambda request: httpx.Response(200, json=LEVER_PAYLOAD, request=request)
        )
        LeverCollector(company="Example Labs", identifier="example", client=client).collect()

        self.assertEqual(
            str(requests[0].url), "https://api.lever.co/v0/postings/example?mode=json"
        )

    def test_missing_optional_fields_are_safe(self):
        collector = LeverCollector(
            company="Example Labs", identifier="example", client=json_client([{"id": "x1"}])
        )

        job = collector.collect()[0]

        self.assertEqual(job.external_id, "x1")
        self.assertEqual(job.title, "")
        self.assertEqual(job.location, "")
        self.assertEqual(job.description, "")
        self.assertIsNone(job.posted_at)
        self.assertIsNone(job.source_updated_at)
        self.assertEqual(job.source_identifier, "example")

    def test_http_error_is_raised(self):
        collector = LeverCollector(
            company="Example Labs", identifier="example", client=status_client(403)
        )

        with self.assertRaises(httpx.HTTPStatusError):
            collector.collect()


if __name__ == "__main__":
    unittest.main()
