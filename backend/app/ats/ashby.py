"""Ashby application-form filling.

Verified against a real Ashby posting (OpenAI's `/application` page):
every field -- standard or custom -- lives in a
`.ashby-application-form-field-entry` block with a `data-field-path`
attribute (a stable `_systemfield_*` name for standard fields, an opaque
UUID for custom ones) and one `.ashby-application-form-question-title`
label. Standard identity/contact fields are matched by `data-field-path`;
anything else falls back to label-text matching via `app.ats.field_matcher`,
exactly like Lever. A field entry with more than one radio/checkbox input
(Ashby's multi-option radio-group/checkbox-group questions) is never
guessed at -- always left for the user. A single checkbox is Ashby's
boolean-question widget (checked = "Yes"); filled only when the applicant
profile has an explicit true/false answer for that category. Never fills
or even inspects a submit button.
"""

from pathlib import Path

from playwright.sync_api import Locator, Page

from app.ats.field_matcher import (
    is_legal_attestation_field,
    is_sensitive_field,
    is_sponsorship_question,
    match_known_field,
    match_prepared_answer,
)
from app.ats.models import FilledField

# A plain single-control field entry carries both this class and
# `data-field-path`; a multi-option radio-group/checkbox-group entry (real
# multi-choice questions, and Ashby's own EEOC gender/race/veteran/
# disability fields) carries only `data-field-path` -- no matching class.
# Selecting on the attribute alone catches both; selecting on the class
# would silently miss every group question and every EEOC field instead of
# reporting them as skipped/needs-input.
FIELD_ENTRY_SELECTOR = "[data-field-path]"
LABEL_SELECTOR = ".ashby-application-form-question-title"
RESUME_FIELD_PATH = "_systemfield_resume"

# Ashby's own `data-field-path` -- far more reliable than label text for
# the handful of fields Ashby always names the same way; anything else
# falls back to label matching.
_FIELD_PATH_CATEGORY: dict[str, str] = {
    "_systemfield_name": "full_name",
    "_systemfield_name_first": "first_name",
    "_systemfield_name_last": "last_name",
    "_systemfield_email": "email",
    "_systemfield_location": "location",
    "_systemfield_phone": "phone",
}

TEXT_PROFILE_CATEGORIES = (
    "full_name", "first_name", "last_name", "email", "phone", "location", "linkedin", "github", "portfolio",
)
BOOLEAN_CATEGORIES = ("work_authorization", "sponsorship")


def profile_value_for_category(profile, category: str) -> str:
    if category == "full_name":
        return profile.identity.full_name
    if category == "first_name":
        parts = profile.identity.full_name.split()
        return parts[0] if parts else ""
    if category == "last_name":
        parts = profile.identity.full_name.split()
        return " ".join(parts[1:]) if len(parts) > 1 else ""
    if category == "email":
        return profile.identity.email
    if category == "phone":
        return profile.identity.phone
    if category == "location":
        return profile.identity.location
    if category == "linkedin":
        return profile.links.linkedin
    if category == "github":
        return profile.links.github
    if category == "portfolio":
        return profile.links.portfolio
    if category == "work_authorization":
        return profile.work_authorization.status_label
    return ""


def _boolean_value_for_category(profile, category: str) -> bool | None:
    """Only for a genuine yes/no question -- `None` means the profile
    doesn't have a confident answer, which must never be guessed at."""
    if category == "sponsorship":
        now = profile.work_authorization.requires_sponsorship_now
        future = profile.work_authorization.requires_sponsorship_future
        if now is None and future is None:
            return None
        return bool(now) or bool(future)
    if category == "work_authorization":
        return profile.work_authorization.authorized_to_work
    return None


def _fill_control(control: Locator, value: str) -> bool:
    tag = control.evaluate("e => e.tagName.toLowerCase()")
    try:
        if tag == "select":
            control.select_option(label=value)
        else:
            control.fill(value)
        return True
    except Exception:
        return False


def fill_ashby_form(page: Page, profile, prepared_answers: list[dict]) -> list[FilledField]:
    """Fill every recognized field on an already-loaded Ashby
    `/application` page. Never touches the resume upload (see
    `upload_resume`) or any submit button."""
    results: list[FilledField] = []
    prepared_texts = [a["question_text"] for a in prepared_answers]
    entries = page.locator(FIELD_ENTRY_SELECTOR).all()

    for entry in entries:
        field_path = entry.get_attribute("data-field-path") or ""
        if field_path == RESUME_FIELD_PATH:
            continue  # handled by upload_resume

        label_el = entry.locator(LABEL_SELECTOR).first
        if label_el.count() == 0:
            continue
        label_text = label_el.inner_text().strip()
        if not label_text:
            continue
        required = "required" in (label_el.get_attribute("class") or "").lower()

        if is_legal_attestation_field(label_text):
            results.append(FilledField(label=label_text, status="skipped", reason="legal/attestation — left for you"))
            continue

        choice_inputs = entry.locator("input[type=radio], input[type=checkbox]").all()
        is_multi_choice = len(choice_inputs) > 1
        control = None if is_multi_choice else entry.locator(
            "input:not([type=file]):not([type=hidden]), textarea, select"
        ).first
        if not is_multi_choice and control.count() == 0:
            continue

        if is_sensitive_field(label_text):
            policy_value = None
            if getattr(profile, "demographic_response_policy", None) == "prefer_not_to_answer":
                policy_value = "Prefer not to answer"
            if not is_multi_choice and policy_value and _fill_control(control, policy_value):
                results.append(FilledField(label=label_text, status="filled", value=policy_value))
            else:
                results.append(FilledField(label=label_text, status="skipped", reason="sensitive/demographic — needs your input"))
            continue

        if is_multi_choice:
            results.append(FilledField(
                label=label_text,
                status="needs_input" if required else "skipped",
                reason="multiple-choice question — needs your review" if required else "optional, multiple-choice question",
            ))
            continue

        category = (
            _FIELD_PATH_CATEGORY.get(field_path)
            or match_known_field(label_text)
            or ("sponsorship" if is_sponsorship_question(label_text) else None)
        )

        if category in TEXT_PROFILE_CATEGORIES:
            value = profile_value_for_category(profile, category)
            if value and _fill_control(control, value):
                results.append(FilledField(label=label_text, status="filled", value=value))
            elif required:
                results.append(FilledField(label=label_text, status="needs_input", reason="no value in applicant profile"))
            else:
                results.append(FilledField(label=label_text, status="skipped", reason="optional, no value in applicant profile"))
            continue

        if category in BOOLEAN_CATEGORIES:
            input_type = (control.get_attribute("type") or "").lower()
            if input_type == "checkbox":
                bool_value = _boolean_value_for_category(profile, category)
                if bool_value is None:
                    reason = "no clear yes/no answer in applicant profile"
                    results.append(FilledField(label=label_text, status="needs_input" if required else "skipped", reason=reason))
                else:
                    try:
                        control.set_checked(bool_value)
                        results.append(FilledField(label=label_text, status="filled", value="Yes" if bool_value else "No"))
                    except Exception:
                        results.append(FilledField(label=label_text, status="needs_input", reason="could not set checkbox"))
            else:
                value = profile_value_for_category(profile, category)
                if value and _fill_control(control, value):
                    results.append(FilledField(label=label_text, status="filled", value=value))
                elif required:
                    results.append(FilledField(label=label_text, status="needs_input", reason="no value in applicant profile"))
                else:
                    results.append(FilledField(label=label_text, status="skipped", reason="optional, no value in applicant profile"))
            continue

        # Not a known category -- try matching directly against prepared
        # question text before giving up.
        idx = match_prepared_answer(label_text, prepared_texts)
        if idx is not None and prepared_answers[idx].get("answer"):
            answer = prepared_answers[idx]["answer"]
            if _fill_control(control, answer):
                results.append(FilledField(label=label_text, status="filled", value=answer))
                continue

        if required:
            results.append(FilledField(label=label_text, status="needs_input", reason="no confident match"))
        else:
            results.append(FilledField(label=label_text, status="skipped", reason="optional, no confident match"))

    return results


def upload_resume(page: Page, pdf_path: str) -> tuple[bool, str | None]:
    """Upload the approved resume PDF to Ashby's resume file input.
    Verifies exactly one file lands with the expected filename. Returns
    `(uploaded, error)`."""
    try:
        file_input = page.locator(f'[id="{RESUME_FIELD_PATH}"]').first
        if file_input.count() == 0:
            return False, "resume upload field not found on this form"
        file_input.set_input_files(pdf_path)

        file_count = file_input.evaluate("el => el.files.length")
        if file_count != 1:
            return False, f"expected exactly 1 uploaded file, found {file_count}"

        uploaded_name = file_input.evaluate("el => el.files[0].name")
        expected_name = Path(pdf_path).name
        if uploaded_name != expected_name:
            return False, f"uploaded filename {uploaded_name!r} does not match approved resume {expected_name!r}"

        return True, None
    except Exception as exc:
        return False, str(exc)
