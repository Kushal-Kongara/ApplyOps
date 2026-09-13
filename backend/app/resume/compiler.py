"""Compiles LaTeX source to PDF using whatever local compiler is available.

No auto-install: if nothing is found, callers get `LatexCompilerUnavailableError`
and the API surfaces a clean `latex_compiler_unavailable` state -- LaTeX
generation itself still works without a compiler present.

Security: fixed, allow-listed executable names only, never `shell=True`,
never a user-influenced command string -- the LaTeX source is written to a
file and the compiler is pointed at that fixed filename inside a fixed
working directory, so nothing job/JD-derived ever reaches argv or a shell.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_TIMEOUT_SECONDS = 30
_SOURCE_FILENAME = "resume.tex"
_PDF_FILENAME = "resume.pdf"

# Checked in order; first one found on PATH wins. Each entry is a full
# argv template -- never a shell string -- with the fixed source filename
# and the compiler's own required flags only.
_COMPILER_CANDIDATES: list[tuple[str, list[str]]] = [
    ("latexmk", ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", _SOURCE_FILENAME]),
    ("tectonic", ["tectonic", _SOURCE_FILENAME]),
    ("pdflatex", ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", _SOURCE_FILENAME]),
]

_PAGE_COUNT_RE = re.compile(r"Output written on .*\((\d+) pages?")


class LatexCompilerUnavailableError(RuntimeError):
    """No supported LaTeX compiler (latexmk/tectonic/pdflatex) found on PATH."""


@dataclass(frozen=True, slots=True)
class CompileResult:
    success: bool
    pdf_bytes: bytes | None
    page_count: int | None
    log: str


def detect_compiler(which: Callable[[str], str | None] = shutil.which) -> tuple[str, list[str]] | None:
    """Return (name, argv_template) for the first available compiler, or
    None if none is installed. Injectable `which` for testing."""
    for name, argv in _COMPILER_CANDIDATES:
        if which(name):
            return name, argv
    return None


def compile_latex(
    latex_source: str,
    build_dir: Path,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> CompileResult:
    """Compile `latex_source` inside `build_dir` (must already exist).

    `which` and `run` are injectable so tests never depend on a real LaTeX
    install: a test can fake "no compiler found" or fake a successful/failed
    compilation without touching the filesystem's actual PATH or spawning a
    real process.
    """
    compiler = detect_compiler(which)
    if compiler is None:
        raise LatexCompilerUnavailableError(
            "No LaTeX compiler found (checked latexmk, tectonic, pdflatex). "
            "Install one locally to enable PDF compilation -- LaTeX source "
            "generation works without it. See README for install instructions."
        )
    name, argv = compiler

    source_path = build_dir / _SOURCE_FILENAME
    source_path.write_text(latex_source, encoding="utf-8")

    try:
        completed = run(
            argv,
            cwd=str(build_dir),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        log = f"{name} timed out after {_TIMEOUT_SECONDS}s.\n{exc.stdout or ''}\n{exc.stderr or ''}"
        return CompileResult(success=False, pdf_bytes=None, page_count=None, log=log)

    log = (completed.stdout or "") + "\n" + (completed.stderr or "")
    pdf_path = build_dir / _PDF_FILENAME

    if completed.returncode != 0 or not pdf_path.exists():
        return CompileResult(success=False, pdf_bytes=None, page_count=None, log=log)

    page_count = _parse_page_count(log)
    return CompileResult(success=True, pdf_bytes=pdf_path.read_bytes(), page_count=page_count, log=log)


def _parse_page_count(log: str) -> int | None:
    match = _PAGE_COUNT_RE.search(log)
    return int(match.group(1)) if match else None
