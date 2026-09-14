"""`fill_lever_form`/`upload_resume` against a real (headless) Chromium
page loaded with a synthetic Lever-shaped form -- the actual DOM structure
verified against the real AI Fund Lever posting (`.application-question` >
`.application-label` + input/textarea/select). Real Playwright, no network
call and no mocking of the library itself -- just local HTML content, so
this stays fast and doesn't depend on any live site."""

import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.application_prep.models import (
    ApplicantProfile,
    Identity,
    Links,
    Preferences,
    WorkAuthorization,
)
from app.ats.lever import fill_lever_form, upload_resume

FORM_HTML = """
<html><body>
<form>
  <div class="application-question">
    <div class="application-label">Resume/CV<span>✱</span></div>
    <input type="file" name="resume" required>
  </div>
  <div class="application-question">
    <div class="application-label">Full name<span>✱</span></div>
    <input type="text" name="name" required>
  </div>
  <div class="application-question">
    <div class="application-label">Email<span>✱</span></div>
    <input type="email" name="email" required>
  </div>
  <div class="application-question">
    <div class="application-label">Phone<span>✱</span></div>
    <input type="text" name="phone" required>
  </div>
  <div class="application-question">
    <div class="application-label">Current location<span>✱</span></div>
    <input type="text" name="location" required>
  </div>
  <div class="application-question">
    <div class="application-label">Current company</div>
    <input type="text" name="org">
  </div>
  <div class="application-question">
    <div class="application-label">LinkedIn URL<span>✱</span></div>
    <input type="text" name="urls[LinkedIn]" required>
  </div>
  <div class="application-question">
    <div class="application-label">GitHub URL</div>
    <input type="text" name="urls[GitHub]">
  </div>
  <div class="application-question">
    <div class="application-label">Portfolio URL</div>
    <input type="text" name="urls[Portfolio]">
  </div>
  <div class="application-question">
    <div class="application-label">Are you authorized to work in the United States?<span>✱</span></div>
    <input type="text" name="cards[abc][field][0]" required>
  </div>
  <div class="application-question">
    <div class="application-label">Why are you interested in this role?<span>✱</span></div>
    <textarea name="cards[abc][field][1]" required></textarea>
  </div>
  <div class="application-question">
    <div class="application-label">Gender</div>
    <input type="text" name="cards[abc][field][2]">
  </div>
  <div class="application-question">
    <div class="application-label">I certify that the above information is true</div>
    <input type="text" name="cards[abc][field][3]">
  </div>
  <input type="hidden" name="h-captcha-response" value="">
</form>
</body></html>
"""


def _profile(**overrides) -> ApplicantProfile:
    fields = dict(
        identity=Identity(full_name="Jane Doe", email="jane@example.com", phone="555-1234", location="Remote"),
        links=Links(linkedin="https://linkedin.com/in/jane", github="https://github.com/jane", portfolio=""),
        work_authorization=WorkAuthorization(status_label="Authorized to work"),
        preferences=Preferences(),
    )
    fields.update(overrides)
    return ApplicantProfile(**fields)


class LeverFormFillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._playwright = sync_playwright().start()
        cls._browser = cls._playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._playwright.stop()

    def setUp(self):
        self.page = self._browser.new_page()
        self.page.set_content(FORM_HTML)
        self.addCleanup(self.page.close)

    def _field_value(self, name: str) -> str:
        return self.page.locator(f"[name='{name}']").input_value()

    def test_known_fields_fill_from_profile(self):
        profile = _profile()
        results = fill_lever_form(self.page, profile, prepared_answers=[])

        self.assertEqual(self._field_value("name"), "Jane Doe")
        self.assertEqual(self._field_value("email"), "jane@example.com")
        self.assertEqual(self._field_value("phone"), "555-1234")
        self.assertEqual(self._field_value("location"), "Remote")
        self.assertEqual(self._field_value("urls[LinkedIn]"), "https://linkedin.com/in/jane")
        self.assertEqual(self._field_value("urls[GitHub]"), "https://github.com/jane")

        statuses = {r.label: r.status for r in results}
        self.assertEqual(statuses["Full name"], "filled")
        self.assertEqual(statuses["Email"], "filled")

    def test_optional_field_with_no_profile_value_is_skipped_not_needs_input(self):
        profile = _profile(links=Links(linkedin="https://linkedin.com/in/jane", github="", portfolio=""))
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        github = next(r for r in results if r.label == "GitHub URL")
        self.assertEqual(github.status, "skipped")

    def test_current_company_has_no_confident_match_and_is_skipped(self):
        profile = _profile()
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        org = next(r for r in results if r.label == "Current company")
        self.assertEqual(org.status, "skipped")
        self.assertEqual(self._field_value("org"), "")

    def test_work_authorization_question_fills_from_profile(self):
        profile = _profile(work_authorization=WorkAuthorization(status_label="Authorized, no sponsorship needed"))
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        work_auth = next(r for r in results if "authorized to work" in r.label.lower())
        self.assertEqual(work_auth.status, "filled")
        self.assertEqual(self._field_value("cards[abc][field][0]"), "Authorized, no sponsorship needed")

    def test_prepared_answer_fills_matching_custom_question(self):
        profile = _profile()
        prepared = [{"question_text": "Why are you interested in this role?", "answer": "Because of the mission."}]
        results = fill_lever_form(self.page, profile, prepared_answers=prepared)
        why_role = next(r for r in results if "interested in this role" in r.label.lower())
        self.assertEqual(why_role.status, "filled")
        self.assertEqual(self._field_value("cards[abc][field][1]"), "Because of the mission.")

    def test_missing_prepared_answer_is_needs_input(self):
        profile = _profile()
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        why_role = next(r for r in results if "interested in this role" in r.label.lower())
        self.assertEqual(why_role.status, "needs_input")
        self.assertEqual(self._field_value("cards[abc][field][1]"), "")

    def test_sensitive_field_is_never_auto_answered_without_policy(self):
        profile = _profile()
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        gender = next(r for r in results if r.label == "Gender")
        self.assertEqual(gender.status, "skipped")
        self.assertEqual(self._field_value("cards[abc][field][2]"), "")

    def test_sensitive_field_with_explicit_policy_is_filled(self):
        profile = _profile(demographic_response_policy="prefer_not_to_answer")
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        gender = next(r for r in results if r.label == "Gender")
        self.assertEqual(gender.status, "filled")
        self.assertEqual(self._field_value("cards[abc][field][2]"), "Prefer not to answer")

    def test_legal_attestation_field_is_never_touched(self):
        profile = _profile()
        results = fill_lever_form(self.page, profile, prepared_answers=[])
        legal = next(r for r in results if "certify" in r.label.lower())
        self.assertEqual(legal.status, "skipped")
        self.assertEqual(self._field_value("cards[abc][field][3]"), "")

    def test_no_submit_button_is_ever_present_in_the_form_or_clicked(self):
        # This form has no submit button at all -- filling must not add
        # one, click one, or otherwise attempt to submit.
        self.assertEqual(self.page.locator("button[type=submit], input[type=submit]").count(), 0)
        fill_lever_form(self.page, _profile(), prepared_answers=[])
        self.assertEqual(self.page.locator("button[type=submit], input[type=submit]").count(), 0)


class LeverResumeUploadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._playwright = sync_playwright().start()
        cls._browser = cls._playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._playwright.stop()

    def setUp(self):
        self.page = self._browser.new_page()
        self.page.set_content(FORM_HTML)
        self.addCleanup(self.page.close)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_resume_uploads_to_the_file_input(self):
        pdf_path = Path(self._tmp.name) / "resume.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake resume content")

        uploaded, error = upload_resume(self.page, str(pdf_path))
        self.assertTrue(uploaded)
        self.assertIsNone(error)

        file_count = self.page.evaluate(
            "el => el.files.length", self.page.locator("input[name='resume']").element_handle(),
        )
        self.assertEqual(file_count, 1)

    def test_missing_file_input_reports_a_clean_error(self):
        self.page.set_content("<html><body><form></form></body></html>")
        uploaded, error = upload_resume(self.page, "/tmp/does-not-matter.pdf")
        self.assertFalse(uploaded)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
