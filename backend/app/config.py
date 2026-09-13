"""Loading and validating the source configuration file."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.collectors import SUPPORTED_SOURCES


class ConfigError(ValueError):
    """Raised when the source configuration file cannot be used."""


@dataclass(frozen=True, slots=True)
class SourceConfig:
    type: str
    company: str
    identifier: str


def load_sources(path: str | Path) -> list[SourceConfig]:
    """Read and validate the configured sources, or raise `ConfigError`."""
    config_path = Path(path)

    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {config_path}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {config_path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, list):
        raise ConfigError(f"{config_path} must contain a JSON list of sources.")

    if not payload:
        raise ConfigError(f"{config_path} contains no sources.")

    sources: list[SourceConfig] = []
    seen_identifiers: dict[tuple[str, str], int] = {}
    seen_companies: dict[tuple[str, str], int] = {}

    for index, entry in enumerate(payload):
        source = _parse_entry(entry, index, config_path)

        identifier_key = (source.type, source.identifier.lower())
        company_key = (source.type, source.company.lower())

        if identifier_key in seen_identifiers:
            first = seen_identifiers[identifier_key]
            raise ConfigError(
                f"{config_path} entry {index}: duplicate source "
                f"'{source.type}/{source.identifier}' already configured at entry {first}."
            )
        if company_key in seen_companies:
            first = seen_companies[company_key]
            raise ConfigError(
                f"{config_path} entry {index}: company '{source.company}' is already "
                f"configured for source '{source.type}' at entry {first}."
            )

        seen_identifiers[identifier_key] = index
        seen_companies[company_key] = index
        sources.append(source)

    return sources


def _parse_entry(entry: Any, index: int, config_path: Path) -> SourceConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"{config_path} entry {index}: each source must be a JSON object.")

    source_type = _required_string(entry.get("type"), "type", index, config_path).lower()
    if source_type not in SUPPORTED_SOURCES:
        supported = ", ".join(SUPPORTED_SOURCES)
        raise ConfigError(
            f"{config_path} entry {index}: unsupported source type '{source_type}'. "
            f"Supported types: {supported}."
        )

    company = _required_string(entry.get("company"), "company", index, config_path)
    identifier = _required_string(entry.get("identifier"), "identifier", index, config_path)

    return SourceConfig(type=source_type, company=company, identifier=identifier)


def _required_string(value: Any, field: str, index: int, config_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{config_path} entry {index}: '{field}' is required and must be a non-empty string."
        )
    return value.strip()
