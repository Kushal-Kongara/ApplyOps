"""Greenhouse application-form filling.

Verified against a real Greenhouse posting (Cloudflare's job board page --
the posting page itself embeds the full application form, no separate
`/apply` URL): every field lives as one `<label for="...">` paired with a
control sharing that `id` -- standard fields use Greenhouse's own stable
ids (`first_name`, `last_name`, `email`, `phone`, `candidate-location`,
`resume`); everything else (custom "question_<id>" fields, EEOC fields)
falls back to label-text matching via `app.ats.field_matcher`, exactly
like Lever and Ashby. Several "select"-shaped fields (location, gender,
work authorization/sponsorship, EEOC categories) render as a plain
`role="combobox"` text input backed by a JS dropdown rather than a native
`<select>` -- filled by typing the value only, never confirmed with Enter
(inside a `<form>`, Enter in a single-line text input is the browser's own
default "submit" key, so the typed value is left for the user to confirm
in the dropdown themselves). A
label whose control shares its `name` with more than one radio/checkbox
(a real multi-option question) is never guessed at -- always left for the
user. Never fills or even inspects a submit button.
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

RESUME_FIELD_ID = "resume"

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
    if category == "sponsorship":
        now = profile.work_authorization.requires_sponsorship_now
        future = profile.work_authorization.requires_sponsorship_future
        if now is None and future is None:
            return None
        return bool(now) or bool(future)
    if category == "work_authorization":
        return profile.work_authorization.authorized_to_work
    return None


def _fill_control(page: Page, control: Locator, value: str) -> bool:
    """Fill a text/textarea input, a native `<select>`, or a
    combobox-style text input backed by a JS dropdown (Greenhouse's own
    location/EEOC/yes-no widgets). Deliberately never presses Enter --
    inside a `<form>` that submits the whole application, since Enter in a
    single-line text input is the browser's own default "submit" key."""
    tag = control.evaluate("e => e.tagName.toLowerCase()")
    role = (control.get_attribute("role") or "").lower()
    try:
        if tag == "select":
            control.select_option(label=value)
        elif role == "combobox":
            control.click()
            control.fill(value)
            page.wait_for_timeout(150)
        else:
            control.fill(value)
        return True
    except Exception:
        return False


def fill_greenhouse_form(page: Page, profile, prepared_answers: list[dict]) -> list[FilledField]:
    """Fill every recognized field on an already-loaded Greenhouse
    application page. Never touches the resume upload (see
    `upload_resume`) or any submit button."""
    results: list[FilledField] = []
    prepared_texts = [a["question_text"] for a in prepared_answers]
    seen_ids: set[str] = set()

    for label_el in page.locator("form label[for]").all():
        control_id = label_el.get_attribute("for") or ""
        if not control_id or control_id in seen_ids:
            continue
        seen_ids.add(control_id)

        control = page.locator(f'[id="{control_id}"]').first
        if control.count() == 0:
            continue

        tag = control.evaluate("e => e.tagName.toLowerCase()")
        input_type = (control.get_attribute("type") or "").lower()
        if tag == "input" and input_type in ("file", "hidden"):
            continue  # resume/cover-letter upload handled by upload_resume

        name_attr = control.get_attribute("name") or ""
        group_members = (
            page.locator(f'input[name="{name_attr}"]').all()
            if input_type in ("radio", "checkbox") and name_attr else []
        )
        is_multi_choice = len(group_members) > 1

        if is_multi_choice:
            # A real multi-option question -- Greenhouse gives each option
            # its own per-option label (e.g. "San Francisco"), with the
            # actual question text on the enclosing fieldset's <legend>.
            # Mark every sibling option seen now so the loop reports the
            # group exactly once, under the real question text.
            for member in group_members:
                member_id = member.get_attribute("id")
                if member_id:
                    seen_ids.add(member_id)
            group_info = control.evaluate(
                """el => {
                    const fs = el.closest('fieldset');
                    const legend = fs ? fs.querySelector('legend') : null;
                    return { text: legend ? legend.innerText : null, required: fs ? fs.getAttribute('aria-required') === 'true' : false };
                }"""
            )
            label_text = (group_info.get("text") or label_el.inner_text()).strip().rstrip("*").strip()
            required = bool(group_info.get("required"))
        else:
            label_text = label_el.inner_text().strip().rstrip("*").strip()
            required = control.get_attribute("aria-required") == "true" or control.get_attribute("required") is not None

        if not label_text:
            continue

        if is_legal_attestation_field(label_text):
            results.append(FilledField(label=label_text, status="skipped", reason="legal/attestation — left for you"))
            continue

        if is_sensitive_field(label_text):
            policy_value = None
            if getattr(profile, "demographic_response_policy", None) == "prefer_not_to_answer":
                policy_value = "Prefer not to answer"
            if not is_multi_choice and policy_value and _fill_control(page, control, policy_value):
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

        category = match_known_field(label_text) or ("sponsorship" if is_sponsorship_question(label_text) else None)

        if category in TEXT_PROFILE_CATEGORIES:
            value = profile_value_for_category(profile, category)
            if value and _fill_control(page, control, value):
                results.append(FilledField(label=label_text, status="filled", value=value))
            elif required:
                results.append(FilledField(label=label_text, status="needs_input", reason="no value in applicant profile"))
            else:
                results.append(FilledField(label=label_text, status="skipped", reason="optional, no value in applicant profile"))
            continue

        if category in BOOLEAN_CATEGORIES:
            bool_value = _boolean_value_for_category(profile, category)
            if bool_value is None:
                reason = "no clear yes/no answer in applicant profile"
                results.append(FilledField(label=label_text, status="needs_input" if required else "skipped", reason=reason))
            else:
                text_value = "Yes" if bool_value else "No"
                if _fill_control(page, control, text_value):
                    results.append(FilledField(label=label_text, status="filled", value=text_value))
                else:
                    results.append(FilledField(label=label_text, status="needs_input", reason="could not select an answer"))
            continue

        # Not a known category -- try matching directly against prepared
        # question text before giving up.
        idx = match_prepared_answer(label_text, prepared_texts)
        if idx is not None and prepared_answers[idx].get("answer"):
            answer = prepared_answers[idx]["answer"]
            if _fill_control(page, control, answer):
                results.append(FilledField(label=label_text, status="filled", value=answer))
                continue

        if required:
            results.append(FilledField(label=label_text, status="needs_input", reason="no confident match"))
        else:
            results.append(FilledField(label=label_text, status="skipped", reason="optional, no confident match"))

    return results


def upload_resume(page: Page, pdf_path: str) -> tuple[bool, str | None]:
    """Upload the approved resume PDF to Greenhouse's resume file input.
    Verifies exactly one file lands with the expected filename. Returns
    `(uploaded, error)`."""
    try:
        file_input = page.locator(f'[id="{RESUME_FIELD_ID}"]').first
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
