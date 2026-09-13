"""Test helpers: fake HTTP transports and fixture payloads."""

from typing import Any, Callable

import httpx


def json_client(payload: Any, status_code: int = 200) -> httpx.Client:
    """Return an httpx client that answers every request with `payload`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def status_client(status_code: int, body: str = "error") -> httpx.Client:
    """Return an httpx client that answers every request with an error status."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def recording_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.Client, list[httpx.Request]]:
    """Return a client plus the list of requests it receives."""
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), requests


GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 4567,
            "title": "Full Stack Engineer",
            "updated_at": "2026-08-01T12:00:00-04:00",
            "first_published": "2026-07-30T09:30:00-04:00",
            "absolute_url": "https://boards.greenhouse.io/adobe/jobs/4567",
            "location": {"name": "San Jose, CA"},
            # Greenhouse returns the description as HTML-escaped HTML.
            "content": "&lt;p&gt;Build products.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Ship code&lt;/li&gt;&lt;/ul&gt;",
        }
    ]
}

ASHBY_PAYLOAD = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "b1f0c2d3-1111-2222-3333-444455556666",
            "title": "Backend Engineer",
            "location": "Remote (US)",
            "descriptionHtml": "<p>Own the API.</p><ul><li>Python</li></ul>",
            "descriptionPlain": "Own the API.",
            "jobUrl": "https://jobs.ashbyhq.com/example/b1f0c2d3",
            "applyUrl": "https://jobs.ashbyhq.com/example/b1f0c2d3/application",
            "publishedAt": "2026-08-05T10:00:00Z",
            "updatedAt": "2026-08-06T09:15:00Z",
            "isListed": True,
        }
    ],
}

LEVER_PAYLOAD = [
    {
        "id": "9a8b7c6d-0000-1111-2222-333344445555",
        "text": "Platform Engineer",
        "hostedUrl": "https://jobs.lever.co/example/9a8b7c6d",
        "applyUrl": "https://jobs.lever.co/example/9a8b7c6d/apply",
        "createdAt": 1754308800000,
        "categories": {"location": "New York, NY", "team": "Platform"},
        "description": "<p>Run the platform.</p>",
        "descriptionPlain": "Run the platform.",
    }
]
