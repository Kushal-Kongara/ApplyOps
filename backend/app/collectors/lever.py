"""Lever job postings collector.

Endpoint: https://api.lever.co/v0/postings/{site}?mode=json

Timestamp fields: Lever documents `createdAt` as when the posting was
created, so it maps to `posted_at`. Lever's public postings API does not
document a separate "last modified" field, so `source_updated_at` is always
`None` here rather than guessing.
"""

from typing import Any

from app.collectors.base import JobCollector, clean_text, parse_timestamp, utcnow
from app.html_text import html_to_text
from app.models import Job

BASE_URL = "https://api.lever.co/v0/postings"


class LeverCollector(JobCollector):
    source = "lever"

    def collect(self) -> list[Job]:
        url = f"{BASE_URL}/{self.identifier}"
        payload = self._get_json(url, params={"mode": "json"})

        seen_at = utcnow()
        postings = payload if isinstance(payload, list) else []

        return [self._to_job(posting, seen_at) for posting in postings]

    def _to_job(self, posting: dict[str, Any], seen_at) -> Job:
        categories = posting.get("categories")
        categories = categories if isinstance(categories, dict) else {}
        description = posting.get("description")

        return Job(
            external_id=clean_text(posting.get("id")),
            source=self.source,
            source_identifier=self.identifier,
            company=self.company,
            title=clean_text(posting.get("text")),
            location=clean_text(categories.get("location")),
            description=html_to_text(description) if description else clean_text(posting.get("descriptionPlain")),
            application_url=clean_text(posting.get("hostedUrl") or posting.get("applyUrl")),
            posted_at=parse_timestamp(posting.get("createdAt")),
            source_updated_at=None,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            is_active=True,
        )
