"""`fill_greenhouse_form`/`upload_resume` against a real (headless)
Chromium page loaded with a synthetic Greenhouse-shaped form -- the actual
DOM structure verified against a real Cloudflare Greenhouse posting (one
`<label for="...">` per control sharing that `id`, `aria-required` for
required fields, and several "select"-shaped fields -- location, EEOC
categories, work authorization/sponsorship -- rendered as a plain
`role="combobox"` text input rather than a native `<select>`). Real
Playwright, no network call and no mocking of the library itself -- just
local HTML content, so this stays fast and doesn't depend on any live site.
"""

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
from app.ats.greenhouse import fill_greenhouse_form, upload_resume

FORM_HTML = """
<html><body>
<form>
  <div class="field">
    <label for="first_name">First Name<span aria-hidden="true">*</span></label>
    <input id="first_name" type="text" aria-required="true">
  </div>
  <div class="field">
    <label for="last_name">Last Name<span aria-hidden="true">*</span></label>
    <input id="last_name" type="text" aria-required="true">
  </div>
  <div class="field">
    <label for="email">Email<span aria-hidden="true">*</span></label>
    <input id="email" type="text" aria-required="true">
  </div>
  <div class="field">
    <label for="phone">Phone<span aria-hidden="true">*</span></label>
    <input id="phone" type="tel" aria-required="true">
  </div>
  <div class="field">
    <label for="candidate-location">Location (City)<span aria-hidden="true">*</span></label>
    <input id="candidate-location" type="text" role="combobox" aria-required="true">
  </div>
  <div class="field">
    <label for="country">Country<span aria-hidden="true">*</span></label>
    <input id="country" type="text" role="combobox" aria-required="true">
  </div>
  <div class="field">
    <label for="resume">Resume</label>
    <input id="resume" type="file" aria-required="true">
  </div>
  <div class="field">
    <label for="question_1">How did you hear about this job?<span aria-hidden="true">*</span></label>
    <input id="question_1" type="text" aria-required="true">
  </div>
  <div class="field">
    <label for="question_2">Do you now or will you in the future require immigration sponsorship?<span aria-hidden="true">*</span></label>
    <input id="question_2" type="text" role="combobox" aria-required="true">
  </div>
  <div class="field">
    <label for="question_3">Why are you interested in this role?<span aria-hidden="true">*</span></label>
    <textarea id="question_3" aria-required="true"></textarea>
  </div>
  <div class="field">
    <label for="question_4">What's your favorite hobby?</label>
    <input id="question_4" type="text" aria-required="false">
  </div>
  <fieldset class="checkbox">
    <legend>Please review and acknowledge our Candidate Privacy Policy<span class="required">*</span></legend>
    <div class="checkbox__wrapper">
      <input id="question_5[]" name="question_5[]" type="checkbox" required>
      <label for="question_5[]">Acknowledge/Confirm</label>
    </div>
  </fieldset>
  <fieldset class="checkbox" aria-required="true">
    <legend>Which offices could you work from?<span class="required">*</span></legend>
    <label for="question_6[]_a">San Francisco</label>
    <input id="question_6[]_a" name="question_6[]" type="checkbox">
    <label for="question_6[]_b">Remote</label>
    <input id="question_6[]_b" name="question_6[]" type="checkbox">
  </fieldset>
  <div class="field">
    <label for="gender">Gender</label>
    <input id="gender" type="text" role="combobox" aria-required="false">
  </div>
  <div class="field">
    <label for="hispanic_ethnicity">Are you Hispanic/Latino?</label>
    <input id="hispanic_ethnicity" type="text" role="combobox" aria-required="false">
  </div>
  <button type="submit">Submit Application</button>
</form>
</body></html>
"""


def _profile(**overrides) -> ApplicantProfile:
    fields = dict(
        identity=Identity(full_name="Jane Ann Doe", email="jane@example.com", phone="555-1234", location="Remote"),
        links=Links(linkedin="", github="", portfolio=""),
        work_authorization=WorkAuthorization(
            status_label="Authorized to work", requires_sponsorship_now=False, requires_sponsorship_future=False,
        ),
        preferences=Preferences(),
    )
    fields.update(overrides)
    return ApplicantProfile(**fields)


class GreenhouseFormFillTest(unittest.TestCase):
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

    def _value(self, selector: str) -> str:
        return self.page.locator(selector).input_value()

    def test_standard_identity_fields_fill_from_profile(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        self.assertEqual(self._value("#first_name"), "Jane")
        self.assertEqual(self._value("#last_name"), "Ann Doe")
        self.assertEqual(self._value("#email"), "jane@example.com")
        self.assertEqual(self._value("#phone"), "555-1234")
        self.assertEqual(self._value("#candidate-location"), "Remote")

        statuses = {r.label: r.status for r in results}
        self.assertEqual(statuses["First Name"], "filled")
        self.assertEqual(statuses["Last Name"], "filled")
        self.assertEqual(statuses["Location (City)"], "filled")

    def test_country_has_no_confident_match_and_needs_input(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        country = next(r for r in results if r.label == "Country")
        self.assertEqual(country.status, "needs_input")
        self.assertEqual(self._value("#country"), "")

    def test_sponsorship_combobox_fills_from_profile(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        sponsorship = next(r for r in results if "sponsorship" in r.label.lower())
        self.assertEqual(sponsorship.status, "filled")
        self.assertEqual(sponsorship.value, "No")

    def test_sponsorship_with_unknown_profile_answer_needs_input(self):
        profile = _profile(work_authorization=WorkAuthorization(requires_sponsorship_now=None, requires_sponsorship_future=None))
        results = fill_greenhouse_form(self.page, profile, prepared_answers=[])
        sponsorship = next(r for r in results if "sponsorship" in r.label.lower())
        self.assertEqual(sponsorship.status, "needs_input")

    def test_prepared_answer_fills_matching_custom_question(self):
        prepared = [{"question_text": "Why are you interested in this role?", "answer": "Because of the mission."}]
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=prepared)
        why_role = next(r for r in results if "interested in this role" in r.label.lower())
        self.assertEqual(why_role.status, "filled")
        self.assertEqual(self._value("#question_3"), "Because of the mission.")

    def test_required_custom_question_with_no_match_is_needs_input(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        how_heard = next(r for r in results if "hear about this job" in r.label.lower())
        self.assertEqual(how_heard.status, "needs_input")

    def test_optional_custom_question_with_no_match_is_skipped(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        hobby = next(r for r in results if "hobby" in r.label.lower())
        self.assertEqual(hobby.status, "skipped")

    def test_legal_attestation_checkbox_is_never_touched(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        legal = next(r for r in results if "acknowledge" in r.label.lower())
        self.assertEqual(legal.status, "skipped")
        self.assertFalse(self.page.locator('[id="question_5[]"]').is_checked())

    def test_multi_option_checkbox_group_is_never_guessed(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        offices = next(r for r in results if "offices" in r.label.lower())
        self.assertEqual(offices.status, "needs_input")
        for option in self.page.locator('input[name="question_6[]"]').all():
            self.assertFalse(option.is_checked())

    def test_sensitive_gender_field_is_never_auto_answered_without_policy(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        gender = next(r for r in results if r.label == "Gender")
        self.assertEqual(gender.status, "skipped")
        self.assertEqual(self._value("#gender"), "")

    def test_sensitive_ethnicity_field_is_never_auto_answered_without_policy(self):
        results = fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        ethnicity = next(r for r in results if "hispanic" in r.label.lower())
        self.assertEqual(ethnicity.status, "skipped")
        self.assertEqual(self._value("#hispanic_ethnicity"), "")

    def test_sensitive_field_with_explicit_policy_is_filled(self):
        results = fill_greenhouse_form(self.page, _profile(demographic_response_policy="prefer_not_to_answer"), prepared_answers=[])
        gender = next(r for r in results if r.label == "Gender")
        self.assertEqual(gender.status, "filled")

    def test_no_submit_button_is_ever_clicked(self):
        clicked = {"value": False}
        self.page.expose_function("_record_submit", lambda: clicked.update(value=True))
        self.page.evaluate("document.querySelector('button[type=submit]').addEventListener('click', () => window._record_submit())")
        fill_greenhouse_form(self.page, _profile(), prepared_answers=[])
        self.assertFalse(clicked["value"])
        self.assertEqual(self.page.locator("button[type=submit], input[type=submit]").count(), 1)


class GreenhouseResumeUploadTest(unittest.TestCase):
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

    def test_resume_uploads_exactly_one_matching_file(self):
        pdf_path = Path(self._tmp.name) / "resume.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake resume content")

        uploaded, error = upload_resume(self.page, str(pdf_path))
        self.assertTrue(uploaded)
        self.assertIsNone(error)

        handle = self.page.locator("#resume").element_handle()
        self.assertEqual(self.page.evaluate("el => el.files.length", handle), 1)
        self.assertEqual(self.page.evaluate("el => el.files[0].name", handle), "resume.pdf")

    def test_missing_file_input_reports_a_clean_error(self):
        self.page.set_content("<html><body><form></form></body></html>")
        uploaded, error = upload_resume(self.page, "/tmp/does-not-matter.pdf")
        self.assertFalse(uploaded)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
