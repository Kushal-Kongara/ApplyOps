"""Loading and validating the local applicant-facts profile.

Mirrors `app/resume/master.py`'s loading style deliberately: same "read
JSON, validate, raise a clear error" shape, same kind of local, private,
gitignored configuration file.
"""

import json
from pathlib import Path
from typing import Any

from app.application_prep.models import (
    ApplicantProfile,
    EducationEntry,
    Identity,
    Links,
    Preferences,
    SalaryExpectation,
    WorkAuthorization,
)

DEFAULT_APPLICANT_PROFILE_PATH = Path("config/applicant_profile.json")


class ApplicantProfileError(ValueError):
    """Raised when the applicant profile file is missing or malformed.
    Every message here is meant to be shown to the user as-is."""


def load_applicant_profile(path: str | Path = DEFAULT_APPLICANT_PROFILE_PATH) -> ApplicantProfile:
    """Read and validate the applicant profile, or raise `ApplicantProfileError`.

    Application preparation must fail cleanly here (`applicant_profile_missing`)
    -- never fall back to guessed personal facts -- until a real profile exists.
    """
    profile_path = Path(path)

    try:
        raw = profile_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ApplicantProfileError(
            f"No applicant profile found at {profile_path}. Copy "
            f"{profile_path.parent / 'applicant_profile.example.json'} to {profile_path} "
            "and fill it in with your real, truthful personal details before preparing an application."
        ) from exc
    except OSError as exc:
        raise ApplicantProfileError(f"Could not read applicant profile {profile_path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApplicantProfileError(f"{profile_path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ApplicantProfileError(f"{profile_path} must contain a JSON object.")

    identity = _parse_identity(payload.get("identity", {}), profile_path)
    links = _parse_links(payload.get("links", {}), profile_path)
    work_authorization = _parse_work_authorization(payload.get("work_authorization", {}), profile_path)
    preferences = _parse_preferences(payload.get("preferences", {}), profile_path)
    education = _parse_education(payload.get("education", []), profile_path)
    demographic_response_policy = payload.get("demographic_response_policy")
    if demographic_response_policy is not None and not isinstance(demographic_response_policy, str):
        raise ApplicantProfileError(f"{profile_path}: 'demographic_response_policy' must be a string if present.")
    custom_facts = payload.get("custom_facts", {})
    if not isinstance(custom_facts, dict) or not all(isinstance(v, str) for v in custom_facts.values()):
        raise ApplicantProfileError(f"{profile_path}: 'custom_facts' must be an object of string values.")

    return ApplicantProfile(
        identity=identity,
        links=links,
        work_authorization=work_authorization,
        preferences=preferences,
        education=education,
        demographic_response_policy=demographic_response_policy,
        custom_facts=custom_facts,
    )


def _optional_string(value: Any, field: str, path: Path) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApplicantProfileError(f"{path}: '{field}' must be a string.")
    return value.strip()


def _optional_bool(value: Any, field: str, path: Path) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ApplicantProfileError(f"{path}: '{field}' must be true, false, or null.")
    return value


def _parse_identity(value: Any, path: Path) -> Identity:
    if not isinstance(value, dict):
        raise ApplicantProfileError(f"{path}: 'identity' must be an object.")
    return Identity(
        full_name=_optional_string(value.get("full_name"), "identity.full_name", path),
        email=_optional_string(value.get("email"), "identity.email", path),
        phone=_optional_string(value.get("phone"), "identity.phone", path),
        location=_optional_string(value.get("location"), "identity.location", path),
    )


def _parse_links(value: Any, path: Path) -> Links:
    if not isinstance(value, dict):
        raise ApplicantProfileError(f"{path}: 'links' must be an object.")
    return Links(
        linkedin=_optional_string(value.get("linkedin"), "links.linkedin", path),
        github=_optional_string(value.get("github"), "links.github", path),
        portfolio=_optional_string(value.get("portfolio"), "links.portfolio", path),
    )


def _parse_work_authorization(value: Any, path: Path) -> WorkAuthorization:
    if not isinstance(value, dict):
        raise ApplicantProfileError(f"{path}: 'work_authorization' must be an object.")
    return WorkAuthorization(
        authorized_to_work=_optional_bool(value.get("authorized_to_work"), "work_authorization.authorized_to_work", path),
        requires_sponsorship_now=_optional_bool(
            value.get("requires_sponsorship_now"), "work_authorization.requires_sponsorship_now", path
        ),
        requires_sponsorship_future=_optional_bool(
            value.get("requires_sponsorship_future"), "work_authorization.requires_sponsorship_future", path
        ),
        status_label=_optional_string(value.get("status_label"), "work_authorization.status_label", path),
    )


def _parse_salary_expectation(value: Any, path: Path) -> SalaryExpectation:
    if value is None:
        return SalaryExpectation()
    if not isinstance(value, dict):
        raise ApplicantProfileError(f"{path}: 'preferences.salary_expectation' must be an object if present.")
    mode = value.get("mode", "user_input")
    if not isinstance(mode, str) or not mode.strip():
        raise ApplicantProfileError(f"{path}: 'preferences.salary_expectation.mode' must be a non-empty string.")
    min_value = value.get("min")
    max_value = value.get("max")
    if min_value is not None and not isinstance(min_value, int):
        raise ApplicantProfileError(f"{path}: 'preferences.salary_expectation.min' must be an integer if present.")
    if max_value is not None and not isinstance(max_value, int):
        raise ApplicantProfileError(f"{path}: 'preferences.salary_expectation.max' must be an integer if present.")
    return SalaryExpectation(mode=mode.strip(), min=min_value, max=max_value)


def _parse_preferences(value: Any, path: Path) -> Preferences:
    if not isinstance(value, dict):
        raise ApplicantProfileError(f"{path}: 'preferences' must be an object.")
    return Preferences(
        relocation=_optional_string(value.get("relocation"), "preferences.relocation", path),
        remote=_optional_string(value.get("remote"), "preferences.remote", path),
        start_availability=_optional_string(value.get("start_availability"), "preferences.start_availability", path),
        salary_expectation=_parse_salary_expectation(value.get("salary_expectation"), path),
    )


def _parse_education(value: Any, path: Path) -> list[EducationEntry]:
    if not isinstance(value, list):
        raise ApplicantProfileError(f"{path}: 'education' must be a list.")
    entries = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ApplicantProfileError(f"{path}: education[{index}] must be an object.")
        entries.append(
            EducationEntry(
                school=_optional_string(item.get("school"), f"education[{index}].school", path),
                degree=_optional_string(item.get("degree"), f"education[{index}].degree", path),
                graduation_year=_optional_string(item.get("graduation_year"), f"education[{index}].graduation_year", path),
            )
        )
    return entries
