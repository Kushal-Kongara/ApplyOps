"""Loading and validating the candidate profile used for match scoring.

The profile drives every scoring component in `app/matching/`, but it is
deliberately not a place for identity: no name, email, phone number, or
immigration documents belong here — the profile only describes *what kind
of role* to look for, never *who is looking*.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# If a profile file ever contains one of these keys, something has gone
# wrong upstream — reject it rather than silently store personal data.
_FORBIDDEN_KEYS = {
    "name", "full_name", "first_name", "last_name", "email", "phone",
    "phone_number", "address", "ssn", "date_of_birth", "dob",
    "immigration_status", "visa_status", "passport", "passport_number",
    "national_id",
}

_REQUIRED_STRING_LIST_FIELDS = ("target_titles", "primary_locations", "primary_skills")
_OPTIONAL_STRING_LIST_FIELDS = ("excluded_title_terms", "secondary_skills")


class ProfileError(ValueError):
    """Raised when the profile file cannot be used."""


@dataclass(frozen=True, slots=True)
class Profile:
    profile_id: str
    years_experience: int
    target_titles: list[str]
    primary_locations: list[str]
    allow_remote_us: bool
    allow_relocation_us: bool
    # Split by importance rather than one flat list — see
    # app/matching/skills.py for why that changes how the score behaves.
    primary_skills: list[str]
    secondary_skills: list[str]
    excluded_title_terms: list[str]


def load_profile(path: str | Path) -> Profile:
    """Read and validate the profile file, or raise `ProfileError`."""
    profile_path = Path(path)

    try:
        raw = profile_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProfileError(f"Profile file not found: {profile_path}") from exc
    except OSError as exc:
        raise ProfileError(f"Could not read profile file {profile_path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{profile_path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProfileError(f"{profile_path} must contain a JSON object.")

    forbidden_present = _FORBIDDEN_KEYS & payload.keys()
    if forbidden_present:
        fields = ", ".join(sorted(forbidden_present))
        raise ProfileError(
            f"{profile_path} contains personal-identity fields that don't belong in a "
            f"match profile: {fields}. Remove them — this file only describes what kind "
            f"of role to look for."
        )

    profile_id = _required_string(payload.get("profile_id"), "profile_id", profile_path)
    years_experience = _required_non_negative_int(
        payload.get("years_experience"), "years_experience", profile_path
    )

    string_lists: dict[str, list[str]] = {}
    for field in _REQUIRED_STRING_LIST_FIELDS:
        string_lists[field] = _required_string_list(payload.get(field), field, profile_path)
    for field in _OPTIONAL_STRING_LIST_FIELDS:
        string_lists[field] = _optional_string_list(payload.get(field, []), field, profile_path)

    allow_remote_us = _required_bool(payload.get("allow_remote_us"), "allow_remote_us", profile_path)
    allow_relocation_us = _required_bool(
        payload.get("allow_relocation_us"), "allow_relocation_us", profile_path
    )

    return Profile(
        profile_id=profile_id,
        years_experience=years_experience,
        target_titles=string_lists["target_titles"],
        primary_locations=string_lists["primary_locations"],
        allow_remote_us=allow_remote_us,
        allow_relocation_us=allow_relocation_us,
        primary_skills=string_lists["primary_skills"],
        secondary_skills=string_lists["secondary_skills"],
        excluded_title_terms=string_lists["excluded_title_terms"],
    )


def _required_string(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{path}: '{field}' is required and must be a non-empty string.")
    return value.strip()


def _required_non_negative_int(value: Any, field: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(f"{path}: '{field}' is required and must be an integer.")
    if value < 0:
        raise ProfileError(f"{path}: '{field}' must not be negative.")
    return value


def _required_bool(value: Any, field: str, path: Path) -> bool:
    if not isinstance(value, bool):
        raise ProfileError(f"{path}: '{field}' is required and must be true or false.")
    return value


def _required_string_list(value: Any, field: str, path: Path) -> list[str]:
    items = _optional_string_list(value, field, path)
    if not items:
        raise ProfileError(f"{path}: '{field}' must be a non-empty list of strings.")
    return items


def _optional_string_list(value: Any, field: str, path: Path) -> list[str]:
    if not isinstance(value, list):
        raise ProfileError(f"{path}: '{field}' must be a list of strings.")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ProfileError(f"{path}: '{field}[{index}]' must be a non-empty string.")
        items.append(item.strip())
    return items
