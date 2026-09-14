"""`fill_ashby_form`/`upload_resume` against a real (headless) Chromium page
loaded with a synthetic Ashby-shaped form -- the actual DOM structure
verified against a real OpenAI Ashby posting
(`.ashby-application-form-field-entry` with a `data-field-path` attribute,
a `.ashby-application-form-question-title` label, and one control per
entry -- multiple radio/checkbox inputs for a real multi-option question).
Real Playwright, no network call and no mocking of the library itself --
just local HTML content, so this stays fast and doesn't depend on any live
site."""

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
from app.ats.ashby import fill_ashby_form, upload_resume

FORM_HTML = """
<html><body>
<div id="job-application-form">
  <div class="ashby-application-form-field-entry" data-field-path="_systemfield_name">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="_systemfield_name">Name</label>
    <input type="text" name="_systemfield_name" id="_systemfield_name" required>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="_systemfield_email">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="_systemfield_email">Email</label>
    <input type="email" name="_systemfield_email" id="_systemfield_email" required>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="_systemfield_resume">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="_systemfield_resume">Resume</label>
    <input type="file" id="_systemfield_resume" required>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="_systemfield_location">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="_systemfield_location">Where are you currently located?</label>
    <input type="text" role="combobox" required>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="phone-uuid">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="phone-uuid">Phone Number</label>
    <input type="tel" id="phone-uuid" required>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="linkedin-uuid">
    <label class="ashby-application-form-question-title" for="linkedin-uuid">LinkedIn</label>
    <input type="text" id="linkedin-uuid">
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="sponsorship-uuid">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="sponsorship-uuid">Will you now or in the future require sponsorship for employment visa status in the United States?</label>
    <input type="checkbox" id="sponsorship-uuid">
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="why-uuid">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="why-uuid">Why are you interested in this role?</label>
    <textarea id="why-uuid" required></textarea>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="hobby-uuid">
    <label class="ashby-application-form-question-title" for="hobby-uuid">What's your favorite hobby?</label>
    <input type="text" id="hobby-uuid">
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="gender-uuid">
    <fieldset>
      <label class="ashby-application-form-question-title" for="gender-uuid">Gender</label>
      <input type="radio" name="gender-uuid" value="Male">
      <input type="radio" name="gender-uuid" value="Female">
      <input type="radio" name="gender-uuid" value="Decline to self-identify">
    </fieldset>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="office-uuid">
    <fieldset>
      <label class="_required_f7cvd_91 ashby-application-form-question-title" for="office-uuid">Which office could you work from?</label>
      <input type="checkbox" name="office-uuid" value="San Francisco">
      <input type="checkbox" name="office-uuid" value="Remote">
    </fieldset>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="attest-uuid">
    <label class="_required_f7cvd_91 ashby-application-form-question-title" for="attest-uuid">I certify that the above information is true</label>
    <input type="checkbox" id="attest-uuid">
  </div>
</div>
</body></html>
"""


def _profile(**overrides) -> ApplicantProfile:
    fields = dict(
        identity=Identity(full_name="Jane Doe", email="jane@example.com", phone="555-1234", location="Remote"),
        links=Links(linkedin="https://linkedin.com/in/jane", github="", portfolio=""),
        work_authorization=WorkAuthorization(
            status_label="Authorized to work", requires_sponsorship_now=False, requires_sponsorship_future=False,
        ),
        preferences=Preferences(),
    )
    fields.update(overrides)
    return ApplicantProfile(**fields)


class AshbyFormFillTest(unittest.TestCase):
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

    def test_standard_fields_fill_from_profile_by_field_path(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        self.assertEqual(self._value("#_systemfield_name"), "Jane Doe")
        self.assertEqual(self._value("#_systemfield_email"), "jane@example.com")
        self.assertEqual(self._value("#phone-uuid"), "555-1234")
        self.assertEqual(self._value("#linkedin-uuid"), "https://linkedin.com/in/jane")

        statuses = {r.label: r.status for r in results}
        self.assertEqual(statuses["Name"], "filled")
        self.assertEqual(statuses["Email"], "filled")
        self.assertEqual(statuses["Phone Number"], "filled")

    def test_location_combobox_fills_by_field_path(self):
        fill_ashby_form(self.page, _profile(), prepared_answers=[])
        self.assertEqual(self._value('[data-field-path="_systemfield_location"] input'), "Remote")

    def test_optional_field_with_no_profile_value_is_skipped(self):
        results = fill_ashby_form(self.page, _profile(links=Links(linkedin="", github="", portfolio="")), prepared_answers=[])
        linkedin = next(r for r in results if r.label == "LinkedIn")
        self.assertEqual(linkedin.status, "skipped")

    def test_sponsorship_boolean_checkbox_fills_from_profile(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        sponsorship = next(r for r in results if "sponsorship" in r.label.lower())
        self.assertEqual(sponsorship.status, "filled")
        self.assertEqual(sponsorship.value, "No")
        self.assertFalse(self.page.locator("#sponsorship-uuid").is_checked())

    def test_sponsorship_checkbox_checked_when_profile_says_yes(self):
        profile = _profile(work_authorization=WorkAuthorization(requires_sponsorship_now=True, requires_sponsorship_future=True))
        results = fill_ashby_form(self.page, profile, prepared_answers=[])
        sponsorship = next(r for r in results if "sponsorship" in r.label.lower())
        self.assertEqual(sponsorship.status, "filled")
        self.assertEqual(sponsorship.value, "Yes")
        self.assertTrue(self.page.locator("#sponsorship-uuid").is_checked())

    def test_sponsorship_with_unknown_profile_answer_needs_input(self):
        profile = _profile(work_authorization=WorkAuthorization(requires_sponsorship_now=None, requires_sponsorship_future=None))
        results = fill_ashby_form(self.page, profile, prepared_answers=[])
        sponsorship = next(r for r in results if "sponsorship" in r.label.lower())
        self.assertEqual(sponsorship.status, "needs_input")
        self.assertFalse(self.page.locator("#sponsorship-uuid").is_checked())

    def test_prepared_answer_fills_matching_custom_question(self):
        prepared = [{"question_text": "Why are you interested in this role?", "answer": "Because of the mission."}]
        results = fill_ashby_form(self.page, _profile(), prepared_answers=prepared)
        why_role = next(r for r in results if "interested in this role" in r.label.lower())
        self.assertEqual(why_role.status, "filled")
        self.assertEqual(self._value("#why-uuid"), "Because of the mission.")

    def test_custom_question_with_no_prepared_answer_is_needs_input(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        why_role = next(r for r in results if "interested in this role" in r.label.lower())
        self.assertEqual(why_role.status, "needs_input")

    def test_optional_custom_question_with_no_match_is_skipped(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        hobby = next(r for r in results if "hobby" in r.label.lower())
        self.assertEqual(hobby.status, "skipped")

    def test_sensitive_radio_group_is_never_auto_answered_without_policy(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        gender = next(r for r in results if r.label == "Gender")
        self.assertEqual(gender.status, "skipped")
        for option in self.page.locator('input[name="gender-uuid"]').all():
            self.assertFalse(option.is_checked())

    def test_multi_option_checkbox_group_is_never_guessed(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        office = next(r for r in results if "office" in r.label.lower())
        self.assertEqual(office.status, "needs_input")
        for option in self.page.locator('input[name="office-uuid"]').all():
            self.assertFalse(option.is_checked())

    def test_legal_attestation_checkbox_is_never_touched(self):
        results = fill_ashby_form(self.page, _profile(), prepared_answers=[])
        legal = next(r for r in results if "certify" in r.label.lower())
        self.assertEqual(legal.status, "skipped")
        self.assertFalse(self.page.locator("#attest-uuid").is_checked())

    def test_no_submit_button_is_ever_present_in_the_form_or_clicked(self):
        self.assertEqual(self.page.locator("button[type=submit], input[type=submit]").count(), 0)
        fill_ashby_form(self.page, _profile(), prepared_answers=[])
        self.assertEqual(self.page.locator("button[type=submit], input[type=submit]").count(), 0)


class AshbyResumeUploadTest(unittest.TestCase):
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

        handle = self.page.locator("#_systemfield_resume").element_handle()
        self.assertEqual(self.page.evaluate("el => el.files.length", handle), 1)
        self.assertEqual(self.page.evaluate("el => el.files[0].name", handle), "resume.pdf")

    def test_missing_file_input_reports_a_clean_error(self):
        self.page.set_content("<html><body><form></form></body></html>")
        uploaded, error = upload_resume(self.page, "/tmp/does-not-matter.pdf")
        self.assertFalse(uploaded)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
