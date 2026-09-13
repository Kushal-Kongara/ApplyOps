"""Greenhouse job board collector.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

Timestamp fields: Greenhouse documents `first_published` as the original
publish time, so it maps to `posted_at`. `updated_at` only means "this record
was last modified" — it is not a publish date, and a job can be modified
long after it was first posted — so it maps to `source_updated_at` and is
never used as a fallback for `posted_at`.
"""

from typing import Any

from app.collectors.base import JobCollector, clean_text, parse_timestamp, utcnow
from app.html_text import html_to_text
from app.models import Job

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseCollector(JobCollector):
    source = "greenhouse"

    def collect(self) -> list[Job]:
        url = f"{BASE_URL}/{self.identifier}/jobs"
        payload = self._get_json(url, params={"content": "true"})

        seen_at = utcnow()
        postings = payload.get("jobs") or [] if isinstance(payload, dict) else []

        return [self._to_job(posting, seen_at) for posting in postings]

    def _to_job(self, posting: dict[str, Any], seen_at) -> Job:
        external_id = clean_text(posting.get("id"))
        location = posting.get("location") or {}
        absolute_url = clean_text(posting.get("absolute_url"))

        return Job(
            external_id=external_id,
            source=self.source,
            source_identifier=self.identifier,
            company=self.company,
            title=clean_text(posting.get("title")),
            location=clean_text(location.get("name")) if isinstance(location, dict) else clean_text(location),
            description=html_to_text(posting.get("content")),
            application_url=absolute_url,
            posted_at=parse_timestamp(posting.get("first_published")),
            source_updated_at=parse_timestamp(posting.get("updated_at")),
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            is_active=True,
        )
