"""Filesystem layout for generated resume artifacts.

Paths are always built from a hash of the job's stable internal key -- never
from raw company/title strings -- so nothing job-description-derived ever
reaches a filesystem path.
"""

import hashlib
from pathlib import Path

DEFAULT_RESUMES_ROOT = Path("data/resumes")


def job_key_hash(job_unique_key: str) -> str:
    return hashlib.sha256(job_unique_key.encode("utf-8")).hexdigest()[:20]


def version_dir(job_unique_key: str, version: int, root: Path = DEFAULT_RESUMES_ROOT) -> Path:
    return root / job_key_hash(job_unique_key) / f"v{version}"


def ensure_version_dir(job_unique_key: str, version: int, root: Path = DEFAULT_RESUMES_ROOT) -> Path:
    path = version_dir(job_unique_key, version, root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def latex_path(job_unique_key: str, version: int, root: Path = DEFAULT_RESUMES_ROOT) -> Path:
    return version_dir(job_unique_key, version, root) / "resume.tex"


def pdf_path(job_unique_key: str, version: int, root: Path = DEFAULT_RESUMES_ROOT) -> Path:
    return version_dir(job_unique_key, version, root) / "resume.pdf"
