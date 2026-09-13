"""Shared collector interface.

Every ATS returns a different JSON shape. A collector is an adapter: it knows
one source's API and converts it into our `Job` model. Nothing else in the
system needs to know Greenhouse from Lever.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx

from app.models import Job, utcnow

USER_AGENT = "ApplyOps/0.1 (+https://github.com/kushalkongara/ApplyOps)"
DEFAULT_TIMEOUT = 20.0


class JobCollector(ABC):
    """Base class for a single configured source (one company, one ATS)."""

    source: ClassVar[str]

    def __init__(
        self,
        company: str,
        identifier: str,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.company = company
        self.identifier = identifier
        self.timeout = timeout
        self._client = client

    @abstractmethod
    def collect(self) -> list[Job]:
        """Fetch and normalize jobs from one source."""
        raise NotImplementedError

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET `url` and return parsed JSON, raising on any HTTP error."""
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

        if self._client is not None:
            response = self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or epoch-milliseconds number into UTC."""
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        # Lever reports epoch milliseconds.
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    return None


def clean_text(value: Any) -> str:
    """Return a stripped string for any value, including missing ones."""
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "DEFAULT_TIMEOUT",
    "JobCollector",
    "USER_AGENT",
    "clean_text",
    "parse_timestamp",
    "utcnow",
]
