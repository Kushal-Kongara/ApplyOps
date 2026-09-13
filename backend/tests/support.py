"""Test helpers: fake HTTP transports and fixture payloads."""

from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from app.models import Job
from app.profile import Profile


def make_job(**overrides: Any) -> Job:
    """Build a `Job` for matching tests, with sensible engineering-role defaults."""
    fields: dict[str, Any] = {
        "external_id": "1",
        "source": "greenhouse",
        "source_identifier": "acme",
        "company": "Acme",
        "title": "Full Stack Engineer",
        "location": "San Francisco, CA",
        "description": "Build our product end to end.",
        "application_url": "https://boards.greenhouse.io/acme/jobs/1",
        "posted_at": None,
        "source_updated_at": None,
        "first_seen_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "is_active": True,
    }
    fields.update(overrides)
    return Job(**fields)


def make_profile(**overrides: Any) -> Profile:
    """Build a `Profile` for matching tests, mirroring config/profile.example.json."""
    fields: dict[str, Any] = {
        "profile_id": "test",
        "years_experience": 4,
        "target_titles": [
            "Full Stack Engineer",
            "Full Stack Developer",
            "Founding Engineer",
            "Product Engineer",
            "Forward Deployed Engineer",
            "Frontend Engineer",
            "Backend Engineer",
            "Software Engineer",
            "AI Engineer",
            "Applied AI Engineer",
        ],
        "primary_locations": [
            "San Francisco", "San Jose", "Santa Clara", "Sunnyvale",
            "Mountain View", "Palo Alto", "Redwood City", "Bay Area",
        ],
        "allow_remote_us": True,
        "allow_relocation_us": True,
        "primary_skills": ["React", "TypeScript", "Python", "Node.js", "PostgreSQL", "AWS"],
        "secondary_skills": [
            "JavaScript", "NestJS", "Java", "SQL", "Prisma", "REST APIs", "ECS",
            "Fargate", "RDS", "S3", "CloudFront", "Docker", "GitHub Actions",
            "CI/CD", "LLMs", "AI Agents", "RAG", "Prompt Engineering", "Vapi",
            "ElevenLabs",
        ],
        "excluded_title_terms": [
            "intern", "internship", "new grad", "university graduate",
            "engineering manager", "director", "vice president",
        ],
    }
    fields.update(overrides)
    return Profile(**fields)


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


def make_match_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword args for `database.upsert_match`, with reasonable defaults."""
    fields: dict[str, Any] = dict(
        job_unique_key="greenhouse:acme:1",
        profile_id="test",
        total_score=80,
        title_score=35,
        skills_score=20,
        location_score=15,
        seniority_score=10,
        product_score=0,
        matched_skills=["React", "Python"],
        unmatched_skills=["AWS"],
        skill_evidence=["React (matched 'react')"],
        title_evidence="title matches wanted role family 'full stack'",
        location_evidence="matches a primary Bay Area location",
        seniority_evidence="no explicit experience requirement found; assumed compatible",
        product_evidence=[],
        visa_signal="unknown",
        visa_evidence=None,
        filtered=False,
        filter_reason=None,
        scored_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return fields
