"""Ashby job board collector.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{board_name}

Timestamp fields: Ashby documents `publishedAt` as when the posting went
live, so it maps to `posted_at`. `updatedAt` means the record was last
modified and maps to `source_updated_at` — it is never used as a fallback
for `posted_at`, since a modification date is not a publish date.
"""

from typing import Any

from app.collectors.base import JobCollector, clean_text, parse_timestamp, utcnow
from app.html_text import html_to_text
from app.models import Job

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyCollector(JobCollector):
    source = "ashby"

    def collect(self) -> list[Job]:
        url = f"{BASE_URL}/{self.identifier}"
        payload = self._get_json(url)

        seen_at = utcnow()
        postings = payload.get("jobs") or [] if isinstance(payload, dict) else []

        return [self._to_job(posting, seen_at) for posting in postings]

    def _to_job(self, posting: dict[str, Any], seen_at) -> Job:
        description = posting.get("descriptionHtml")
        plain = clean_text(posting.get("descriptionPlain"))

        return Job(
            external_id=clean_text(posting.get("id")),
            source=self.source,
            source_identifier=self.identifier,
            company=self.company,
            title=clean_text(posting.get("title")),
            location=clean_text(posting.get("location")),
            description=html_to_text(description) if description else plain,
            application_url=clean_text(posting.get("applyUrl") or posting.get("jobUrl")),
            posted_at=parse_timestamp(posting.get("publishedAt")),
            source_updated_at=parse_timestamp(posting.get("updatedAt")),
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            is_active=bool(posting.get("isListed", True)),
        )
