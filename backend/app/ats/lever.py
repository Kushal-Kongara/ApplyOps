"""Lever application-form filling.

Verified against a real Lever posting's `/apply` page: every field --
standard or custom -- lives in a `.application-question` block containing
one `.application-label` and one input/textarea/select. Standard fields
are matched by their stable `name` attribute (`name`, `email`, `phone`,
`location`, `urls[LinkedIn]`, `urls[GitHub]`, `urls[Portfolio]`); anything
else (custom questions, `org`, `urls[Other]`) falls back to label-text
matching via `app.ats.field_matcher`. Never fills or even inspects a
submit button.
"""

from playwright.sync_api import Locator, Page

from app.ats.field_matcher import (
    is_legal_attestation_field,
    is_sensitive_field,
    match_known_field,
    match_prepared_answer,
)
from app.ats.models import FilledField

RESUME_FILE_INPUT_NAME = "resume"

# Lever's own field `name` attribute -> applicant-profile category. Far
# more reliable than label text for the fields Lever always names the
# same way; anything not listed here falls back to label matching.
_NAME_ATTRIBUTE_CATEGORY: dict[str, str] = {
    "name": "full_name",
    "email": "email",
    "phone": "phone",
    "location": "location",
    "urls[LinkedIn]": "linkedin",
    "urls[GitHub]": "github",
    "urls[Portfolio]": "portfolio",
}

PROFILE_CATEGORIES = ("full_name", "email", "phone", "location", "linkedin", "github", "portfolio")
MOTIVATION_CATEGORIES = ("role_motivation", "company_motivation", "experience")


def profile_value_for_category(profile, category: str) -> str:
    if category == "full_name":
        return profile.identity.full_name
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
    if category == "relocation":
        return profile.preferences.relocation
    return ""


def _fill_control(control: Locator, value: str) -> bool:
    """Fill a text/textarea input or best-effort select a matching select
    option. Returns whether the fill was attempted (not proof it stuck --
    the real verification report says explicitly what actually landed)."""
    tag = control.evaluate("e => e.tagName.toLowerCase()")
    try:
        if tag == "select":
            control.select_option(label=value)
        else:
            control.fill(value)
        return True
    except Exception:
        return False


def fill_lever_form(page: Page, profile, prepared_answers: list[dict]) -> list[FilledField]:
    """Fill every recognized `.application-question` field on an already-
    loaded Lever `/apply` page. `prepared_answers` is a list of
    `{"question_text": str, "answer": str | None}` from an application
    preparation. Never touches the resume upload (see `upload_resume`) or
    any submit button.
    """
    results: list[FilledField] = []
    blocks = page.locator(".application-question").all()
    prepared_texts = [a["question_text"] for a in prepared_answers]

    for block in blocks:
        label_el = block.locator(".application-label").first
        if label_el.count() == 0:
            continue
        label_text = label_el.inner_text().strip().rstrip("✱").strip()
        if not label_text:
            continue

        control = block.locator("input:not([type=file]):not([type=hidden]), textarea, select").first
        if control.count() == 0:
            continue  # e.g. the resume upload block, or the LinkedIn-SSO block

        name_attr = control.get_attribute("name") or ""
        required = control.get_attribute("required") is not None

        if is_legal_attestation_field(label_text):
            # Never even reported as a "skip" for visibility purposes here
            # beyond what the caller wants -- but still worth surfacing so
            # the user knows it was deliberately left alone.
            results.append(FilledField(label=label_text, status="skipped", reason="legal/attestation — left for you"))
            continue

        if is_sensitive_field(label_text):
            policy_value = None
            if getattr(profile, "demographic_response_policy", None) == "prefer_not_to_answer":
                policy_value = "Prefer not to answer"
            if policy_value and _fill_control(control, policy_value):
                results.append(FilledField(label=label_text, status="filled", value=policy_value))
            else:
                results.append(FilledField(label=label_text, status="skipped", reason="sensitive/demographic — needs your input"))
            continue

        category = _NAME_ATTRIBUTE_CATEGORY.get(name_attr) or match_known_field(label_text)

        if category in PROFILE_CATEGORIES or category in ("work_authorization", "relocation"):
            value = profile_value_for_category(profile, category)
            if value and _fill_control(control, value):
                results.append(FilledField(label=label_text, status="filled", value=value))
            elif required:
                results.append(FilledField(label=label_text, status="needs_input", reason="no value in applicant profile"))
            else:
                results.append(FilledField(label=label_text, status="skipped", reason="optional, no value in applicant profile"))
            continue

        if category in MOTIVATION_CATEGORIES:
            idx = match_prepared_answer(label_text, prepared_texts)
            if idx is not None and prepared_answers[idx].get("answer"):
                answer = prepared_answers[idx]["answer"]
                if _fill_control(control, answer):
                    results.append(FilledField(label=label_text, status="filled", value=answer))
                    continue
            results.append(FilledField(label=label_text, status="needs_input", reason="no prepared answer available"))
            continue

        # Not a known category -- try matching directly against prepared
        # question text before giving up (a custom Lever question can be
        # worded exactly like a prepared one without matching a synonym).
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
    """Upload the approved resume PDF to Lever's resume file input.
    Returns `(uploaded, error)`."""
    try:
        file_input = page.locator(f"input[type=file][name={RESUME_FILE_INPUT_NAME!r}]").first
        if file_input.count() == 0:
            return False, "resume upload field not found on this form"
        file_input.set_input_files(pdf_path)
        return True, None
    except Exception as exc:
        return False, str(exc)
