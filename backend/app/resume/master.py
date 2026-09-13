"""Loading and validating the master resume — the one file every tailored
resume is generated from.

Mirrors `app/profile.py`'s loading style deliberately (same kind of
"read JSON, validate, raise a clear error" shape) — this is the same kind
of local, private, gitignored configuration file the profile already is.
"""

import json
from pathlib import Path
from typing import Any

from app.resume.models import (
    Achievement,
    Bullet,
    Contact,
    EducationEntry,
    ExperienceEntry,
    MasterResume,
    ProjectEntry,
)

DEFAULT_MASTER_RESUME_PATH = Path("config/resume_master.json")


class MasterResumeError(ValueError):
    """Raised when the master resume file is missing or malformed.

    Every message here is meant to be shown to the user as-is — it should
    always say exactly what's missing and where to put it right.
    """


def load_master_resume(path: str | Path = DEFAULT_MASTER_RESUME_PATH) -> MasterResume:
    """Read and validate the master resume, or raise `MasterResumeError`.

    Generation must fail cleanly here — never fall back to inventing
    content — until a truthful `resume_master.json` exists.
    """
    resume_path = Path(path)

    try:
        raw = resume_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MasterResumeError(
            f"No master resume found at {resume_path}. Copy "
            f"{resume_path.parent / 'resume_master.example.json'} to {resume_path} "
            "and fill it in with your real, truthful experience before generating a resume."
        ) from exc
    except OSError as exc:
        raise MasterResumeError(f"Could not read master resume {resume_path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MasterResumeError(f"{resume_path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MasterResumeError(f"{resume_path} must contain a JSON object.")

    seen_ids: set[str] = set()

    def _claim_id(entity_id: Any, where: str) -> str:
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise MasterResumeError(f"{resume_path}: {where} is missing a non-empty 'id'.")
        if entity_id in seen_ids:
            raise MasterResumeError(
                f"{resume_path}: duplicate id '{entity_id}' at {where} — every evidence id must be unique."
            )
        seen_ids.add(entity_id)
        return entity_id

    contact = _parse_contact(payload.get("contact"), resume_path)
    summary = _required_string(payload.get("summary"), "summary", resume_path)
    experience = _parse_experience(payload.get("experience"), resume_path, _claim_id)
    skills = _parse_skills(payload.get("skills"), resume_path)
    education = _parse_education(payload.get("education"), resume_path, _claim_id)
    projects = _parse_projects(payload.get("projects", []), resume_path, _claim_id)
    achievements = _parse_achievements(payload.get("achievements", []), resume_path, _claim_id)

    return MasterResume(
        contact=contact,
        summary=summary,
        experience=experience,
        skills=skills,
        education=education,
        projects=projects,
        achievements=achievements,
    )


def _required_string(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MasterResumeError(f"{path}: '{field}' is required and must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any, field: str, path: Path) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MasterResumeError(f"{path}: '{field}' must be a string.")
    return value.strip()


def _parse_contact(value: Any, path: Path) -> Contact:
    if not isinstance(value, dict):
        raise MasterResumeError(f"{path}: 'contact' is required and must be an object.")
    return Contact(
        name=_required_string(value.get("name"), "contact.name", path),
        headline=_optional_string(value.get("headline"), "contact.headline", path),
        email=_required_string(value.get("email"), "contact.email", path),
        phone=_optional_string(value.get("phone"), "contact.phone", path),
        linkedin=_optional_string(value.get("linkedin"), "contact.linkedin", path),
        github=_optional_string(value.get("github"), "contact.github", path),
    )


def _parse_bullets(value: Any, where: str, path: Path, claim_id) -> list[Bullet]:
    if not isinstance(value, list) or not value:
        raise MasterResumeError(f"{path}: {where}.bullets must be a non-empty list.")
    bullets: list[Bullet] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MasterResumeError(f"{path}: {where}.bullets[{index}] must be an object.")
        bullet_id = claim_id(item.get("id"), f"{where}.bullets[{index}]")
        text = _required_string(item.get("text"), f"{where}.bullets[{index}].text", path)
        bullets.append(Bullet(id=bullet_id, text=text))
    return bullets


def _parse_experience(value: Any, path: Path, claim_id) -> list[ExperienceEntry]:
    if not isinstance(value, list) or not value:
        raise MasterResumeError(f"{path}: 'experience' must be a non-empty list.")
    entries: list[ExperienceEntry] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MasterResumeError(f"{path}: experience[{index}] must be an object.")
        where = f"experience[{index}]"
        entry_id = claim_id(item.get("id"), where)
        entries.append(
            ExperienceEntry(
                id=entry_id,
                company=_required_string(item.get("company"), f"{where}.company", path),
                title=_required_string(item.get("title"), f"{where}.title", path),
                start_date=_optional_string(item.get("start_date"), f"{where}.start_date", path),
                end_date=_optional_string(item.get("end_date"), f"{where}.end_date", path),
                location=_optional_string(item.get("location"), f"{where}.location", path),
                bullets=_parse_bullets(item.get("bullets"), where, path, claim_id),
            )
        )
    return entries


def _parse_projects(value: Any, path: Path, claim_id) -> list[ProjectEntry]:
    if not isinstance(value, list):
        raise MasterResumeError(f"{path}: 'projects' must be a list.")
    entries: list[ProjectEntry] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MasterResumeError(f"{path}: projects[{index}] must be an object.")
        where = f"projects[{index}]"
        entry_id = claim_id(item.get("id"), where)
        technologies = item.get("technologies", [])
        if not isinstance(technologies, list) or not all(isinstance(t, str) for t in technologies):
            raise MasterResumeError(f"{path}: {where}.technologies must be a list of strings.")
        entries.append(
            ProjectEntry(
                id=entry_id,
                name=_required_string(item.get("name"), f"{where}.name", path),
                technologies=[t.strip() for t in technologies],
                bullets=_parse_bullets(item.get("bullets"), where, path, claim_id),
            )
        )
    return entries


def _parse_skills(value: Any, path: Path) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not value:
        raise MasterResumeError(f"{path}: 'skills' must be a non-empty object of category -> list of strings.")
    skills: dict[str, list[str]] = {}
    for category, items in value.items():
        if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
            raise MasterResumeError(f"{path}: skills.{category} must be a list of non-empty strings.")
        skills[category] = [i.strip() for i in items]
    return skills


def _parse_education(value: Any, path: Path, claim_id) -> list[EducationEntry]:
    if not isinstance(value, list) or not value:
        raise MasterResumeError(f"{path}: 'education' must be a non-empty list.")
    entries: list[EducationEntry] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MasterResumeError(f"{path}: education[{index}] must be an object.")
        where = f"education[{index}]"
        entry_id = claim_id(item.get("id"), where)
        entries.append(
            EducationEntry(
                id=entry_id,
                school=_required_string(item.get("school"), f"{where}.school", path),
                degree=_required_string(item.get("degree"), f"{where}.degree", path),
                start_date=_optional_string(item.get("start_date"), f"{where}.start_date", path),
                end_date=_optional_string(item.get("end_date"), f"{where}.end_date", path),
                location=_optional_string(item.get("location"), f"{where}.location", path),
            )
        )
    return entries


def _parse_achievements(value: Any, path: Path, claim_id) -> list[Achievement]:
    if not isinstance(value, list):
        raise MasterResumeError(f"{path}: 'achievements' must be a list.")
    achievements: list[Achievement] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MasterResumeError(f"{path}: achievements[{index}] must be an object.")
        where = f"achievements[{index}]"
        entry_id = claim_id(item.get("id"), where)
        achievements.append(Achievement(id=entry_id, text=_required_string(item.get("text"), f"{where}.text", path)))
    return achievements
