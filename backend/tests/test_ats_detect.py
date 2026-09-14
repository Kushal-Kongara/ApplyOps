"""ATS detection by application URL."""

import unittest

from app.ats.detect import IMPLEMENTED_ATS, SUPPORTED_ATS, apply_url_for, detect_ats


class DetectAtsTest(unittest.TestCase):
    def test_lever_is_detected(self):
        self.assertEqual(detect_ats("https://jobs.lever.co/AIFund/abc123"), "lever")

    def test_ashby_is_detected(self):
        self.assertEqual(detect_ats("https://jobs.ashbyhq.com/acme/abc123"), "ashby")

    def test_greenhouse_is_detected(self):
        self.assertEqual(detect_ats("https://boards.greenhouse.io/acme/jobs/123"), "greenhouse")

    def test_greenhouse_job_boards_subdomain_is_detected(self):
        self.assertEqual(detect_ats("https://job-boards.greenhouse.io/acme/jobs/123"), "greenhouse")

    def test_unrecognized_ats_returns_none(self):
        self.assertIsNone(detect_ats("https://careers.somecompany.com/apply/123"))

    def test_empty_url_returns_none(self):
        self.assertIsNone(detect_ats(""))

    def test_only_lever_is_implemented_yet(self):
        self.assertEqual(IMPLEMENTED_ATS, ("lever",))
        self.assertIn("ashby", SUPPORTED_ATS)
        self.assertIn("greenhouse", SUPPORTED_ATS)


class ApplyUrlForTest(unittest.TestCase):
    def test_lever_posting_url_gets_apply_suffix(self):
        result = apply_url_for("https://jobs.lever.co/AIFund/abc123", "lever")
        self.assertEqual(result, "https://jobs.lever.co/AIFund/abc123/apply")

    def test_lever_url_already_ending_in_apply_is_unchanged(self):
        result = apply_url_for("https://jobs.lever.co/AIFund/abc123/apply", "lever")
        self.assertEqual(result, "https://jobs.lever.co/AIFund/abc123/apply")

    def test_non_lever_url_is_unchanged(self):
        url = "https://jobs.ashbyhq.com/acme/abc123"
        self.assertEqual(apply_url_for(url, "ashby"), url)


if __name__ == "__main__":
    unittest.main()
