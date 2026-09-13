"""API layer tests. No network calls — dependencies are overridden to use
a temporary database and an in-memory profile instead of real files."""

import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import database
from app.api import app, get_connection, get_profile
from tests.support import make_job, make_match_kwargs, make_profile

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.profile = make_profile(profile_id="test")

        app.dependency_overrides[get_connection] = lambda: self.connection
        app.dependency_overrides[get_profile] = lambda: self.profile
        self.addCleanup(app.dependency_overrides.clear)

        self.client = TestClient(app)

    def score(self, key: str, total: int, **overrides) -> None:
        database.upsert_match(self.connection, **make_match_kwargs(job_unique_key=key, total_score=total, **overrides))


class DashboardTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", title="High Job"),
                make_job(external_id="2", title="Review Job"),
                make_job(external_id="3", title="Applied Job"),
            ],
        )
        self.score("greenhouse:acme:1", 80)
        self.score("greenhouse:acme:2", 67)
        self.score("greenhouse:acme:3", 90)
        database.upsert_application(self.connection, "greenhouse:acme:3", status="applied", now=NOW)

    def test_dashboard_reuses_daily_queue_counts_and_order(self):
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["summary"], {
            "high_priority": 1, "review": 1, "follow_ups_due": 0, "applications_total": 1,
        })
        self.assertEqual(data["high_priority"][0]["title"], "High Job")
        self.assertEqual(data["review_candidates"][0]["title"], "Review Job")
        # Applied job is excluded from new-candidate sections.
        titles = {item["title"] for item in data["high_priority"] + data["review_candidates"]}
        self.assertNotIn("Applied Job", titles)

    def test_job_card_exposes_component_scores_and_matched_skills(self):
        data = self.client.get("/api/dashboard").json()
        card = data["high_priority"][0]

        for field in (
            "job_unique_key", "total_score", "title", "company", "location", "source",
            "application_url", "status", "title_score", "skills_score", "location_score",
            "seniority_score", "product_score", "visa_signal", "matched_skills",
        ):
            self.assertIn(field, card)
        self.assertEqual(card["matched_skills"], ["React", "Python"])


class JobsEndpointTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", title="Full Stack Engineer", company="Acme"),
                make_job(external_id="2", title="Backend Engineer", company="Other Co"),
            ],
        )
        self.score("greenhouse:acme:1", 80)
        self.score("greenhouse:acme:2", 60)

    def test_lists_jobs_ordered_by_score_descending(self):
        response = self.client.get("/api/jobs")
        titles = [j["title"] for j in response.json()]
        self.assertEqual(titles, ["Full Stack Engineer", "Backend Engineer"])

    def test_min_score_filters_results(self):
        response = self.client.get("/api/jobs", params={"min_score": 70})
        self.assertEqual(len(response.json()), 1)

    def test_search_filters_by_title_or_company(self):
        response = self.client.get("/api/jobs", params={"q": "Other Co"})
        titles = [j["title"] for j in response.json()]
        self.assertEqual(titles, ["Backend Engineer"])

    def test_status_filter(self):
        database.upsert_application(self.connection, "greenhouse:acme:1", status="shortlisted", now=NOW)
        response = self.client.get("/api/jobs", params={"status": "shortlisted"})
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["status"], "shortlisted")

    def test_get_single_job(self):
        response = self.client.get("/api/jobs/greenhouse:acme:1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Full Stack Engineer")

    def test_get_unknown_job_returns_404(self):
        response = self.client.get("/api/jobs/does-not-exist")
        self.assertEqual(response.status_code, 404)


class ApplicationsEndpointTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [make_job(external_id="1", title="Job One"), make_job(external_id="2", title="Job Two")],
        )
        database.upsert_application(self.connection, "greenhouse:acme:1", status="shortlisted", now=NOW)
        database.upsert_application(self.connection, "greenhouse:acme:2", status="applied", now=NOW)

    def test_lists_all_applications(self):
        response = self.client.get("/api/applications")
        self.assertEqual(len(response.json()), 2)

    def test_filters_by_status(self):
        response = self.client.get("/api/applications", params={"status": "applied"})
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Job Two")

    def test_invalid_status_filter_rejected(self):
        response = self.client.get("/api/applications", params={"status": "ghosted"})
        self.assertEqual(response.status_code, 400)


class PatchApplicationTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(self.connection, [make_job(external_id="1", title="Full Stack Engineer")])

    def test_creates_application_when_none_exists(self):
        response = self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "shortlisted"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "shortlisted")

    def test_updates_only_provided_fields(self):
        self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "shortlisted", "notes": "good fit"})
        response = self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "applying"})

        self.assertEqual(response.json()["status"], "applying")
        self.assertEqual(response.json()["notes"], "good fit")  # untouched

    def test_marking_applied_auto_sets_applied_at_once(self):
        response = self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "applied"})
        self.assertIsNotNone(response.json()["applied_at"])

    def test_invalid_status_returns_400(self):
        response = self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "ghosted"})
        self.assertEqual(response.status_code, 400)

    def test_unknown_job_returns_404(self):
        response = self.client.patch("/api/applications/does-not-exist", json={"status": "new"})
        self.assertEqual(response.status_code, 404)

    def test_no_duplicate_application_row_is_created(self):
        self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "shortlisted"})
        self.client.patch("/api/applications/greenhouse:acme:1", json={"status": "applying"})

        count = self.connection.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_next_follow_up_at_can_be_set_and_cleared(self):
        set_response = self.client.patch(
            "/api/applications/greenhouse:acme:1", json={"next_follow_up_at": "2026-10-01"}
        )
        self.assertIsNotNone(set_response.json()["next_follow_up_at"])

        clear_response = self.client.patch(
            "/api/applications/greenhouse:acme:1", json={"next_follow_up_at": None}
        )
        self.assertIsNone(clear_response.json()["next_follow_up_at"])

    def test_invalid_follow_up_date_returns_400(self):
        response = self.client.patch(
            "/api/applications/greenhouse:acme:1", json={"next_follow_up_at": "not-a-date"}
        )
        self.assertEqual(response.status_code, 400)


class RecentJobsEndpointTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        # The endpoint has no `now` override (unlike `build_recent_timeline`
        # directly, which the dedicated recent.py tests exercise) — it
        # always buckets against the real wall clock, so these fixtures
        # must be relative to *actual* now, not the file's fixed NOW.
        real_now = database.utcnow()
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", title="One Hour Old", first_seen_at=real_now - timedelta(hours=1)),
                make_job(external_id="2", title="Three Hours Old", first_seen_at=real_now - timedelta(hours=3)),
                make_job(external_id="3", title="Too Old", first_seen_at=real_now - timedelta(hours=30)),
                make_job(external_id="4", title="Below Threshold", first_seen_at=real_now - timedelta(hours=1)),
            ],
        )
        self.score("greenhouse:acme:1", 80)
        self.score("greenhouse:acme:2", 67)
        self.score("greenhouse:acme:3", 80)
        self.score("greenhouse:acme:4", 60)

    def test_route_is_not_shadowed_by_the_job_id_path_param(self):
        # "/api/jobs/recent" must resolve to this endpoint, not be treated
        # as a lookup for a job literally named "recent".
        response = self.client.get("/api/jobs/recent")
        self.assertEqual(response.status_code, 200)
        self.assertIn("buckets", response.json())

    def test_jobs_placed_in_the_correct_bucket(self):
        data = self.client.get("/api/jobs/recent").json()
        buckets_by_key = {b["key"]: b for b in data["buckets"]}

        self.assertEqual([j["title"] for j in buckets_by_key["0-2"]["jobs"]], ["One Hour Old"])
        self.assertEqual([j["title"] for j in buckets_by_key["2-4"]["jobs"]], ["Three Hours Old"])

    def test_older_than_24h_job_is_in_the_older_section(self):
        data = self.client.get("/api/jobs/recent").json()
        self.assertEqual(data["older"]["count"], 1)
        self.assertEqual(data["older"]["jobs"][0]["title"], "Too Old")

    def test_below_65_is_excluded(self):
        data = self.client.get("/api/jobs/recent").json()
        all_titles = {j["title"] for b in data["buckets"] for j in b["jobs"]}
        self.assertNotIn("Below Threshold", all_titles)

    def test_summary_reflects_last_24h_only_not_older(self):
        data = self.client.get("/api/jobs/recent").json()
        self.assertEqual(data["summary"]["last_24h"], 2)  # 1h + 3h jobs, not the 30h one
        self.assertEqual(data["summary"]["older_than_24h"], 1)

    def test_min_score_query_param_is_respected(self):
        data = self.client.get("/api/jobs/recent", params={"min_score": 70}).json()
        self.assertEqual(data["summary"]["last_24h"], 1)

    def test_job_card_includes_first_seen_at(self):
        data = self.client.get("/api/jobs/recent").json()
        job = data["buckets"][0]["jobs"][0]
        self.assertIn("first_seen_at", job)
        self.assertIn("status", job)
        self.assertIn("matched_skills", job)

    def test_application_status_does_not_remove_a_job_from_the_timeline(self):
        database.upsert_application(self.connection, "greenhouse:acme:1", status="applied", now=NOW)
        data = self.client.get("/api/jobs/recent").json()

        job = data["buckets"][0]["jobs"][0]
        self.assertEqual(job["title"], "One Hour Old")
        self.assertEqual(job["status"], "applied")


class FollowUpsEndpointTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        database.upsert_jobs(
            self.connection,
            [
                make_job(external_id="1", title="Due Job"),
                make_job(external_id="2", title="Upcoming Job"),
                make_job(external_id="3", title="No Follow-up Job"),
            ],
        )
        self.score("greenhouse:acme:1", 80)
        self.score("greenhouse:acme:2", 80)
        self.score("greenhouse:acme:3", 80)
        database.upsert_application(
            self.connection, "greenhouse:acme:1", status="applying",
            next_follow_up_at=NOW - timedelta(days=1), now=NOW,
        )
        database.upsert_application(
            self.connection, "greenhouse:acme:2", status="applying",
            next_follow_up_at=NOW + timedelta(days=5), now=NOW,
        )

    def test_due_and_upcoming_are_separated(self):
        response = self.client.get("/api/follow-ups")
        data = response.json()

        due_titles = {item["title"] for item in data["due"]}
        upcoming_titles = {item["title"] for item in data["upcoming"]}

        self.assertEqual(due_titles, {"Due Job"})
        self.assertEqual(upcoming_titles, {"Upcoming Job"})

    def test_job_without_a_follow_up_date_appears_in_neither(self):
        response = self.client.get("/api/follow-ups")
        data = response.json()
        all_titles = {item["title"] for item in data["due"] + data["upcoming"]}
        self.assertNotIn("No Follow-up Job", all_titles)


if __name__ == "__main__":
    unittest.main()
