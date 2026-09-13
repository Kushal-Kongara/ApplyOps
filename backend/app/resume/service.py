"""Orchestrates one resume generation: master resume -> tailoring -> LaTeX ->
compile -> persisted version. Kept out of `app.api` so the API stays a thin
HTTP layer, consistent with how the rest of this app separates concerns.
"""

import shutil
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from app import database
from app.resume import storage
from app.resume.compiler import CompileResult, LatexCompilerUnavailableError, compile_latex
from app.resume.latex import render_latex
from app.resume.llm_provider import ResumeLLMProvider
from app.resume.master import DEFAULT_MASTER_RESUME_PATH, MasterResumeError, load_master_resume
from app.resume.ollama_provider import build_provider_from_env
from app.resume.rewriter import rewrite_tailored_resume
from app.resume.tailor import tailor_resume

VALID_GENERATION_MODES = ("deterministic", "llm_enhanced")
DEFAULT_GENERATION_MODE = "deterministic"


class InvalidResumeModeError(ValueError):
    """Raised when `generate_resume_version` is asked for an unsupported
    `mode`. The API turns this into a 400 `invalid_mode` response."""


class LLMUnavailableError(RuntimeError):
    """Raised when `mode="llm_enhanced"` is requested but no provider is
    configured, or the configured provider isn't reachable. Generation is
    refused rather than silently falling back — an `llm_enhanced` version
    that never actually ran an LLM would be a lie about its own metadata."""


def generate_resume_version(
    connection: sqlite3.Connection,
    job_row: sqlite3.Row,
    *,
    mode: str = DEFAULT_GENERATION_MODE,
    master_resume_path: str | Path = DEFAULT_MASTER_RESUME_PATH,
    resumes_root: Path = storage.DEFAULT_RESUMES_ROOT,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    llm_provider: ResumeLLMProvider | None = None,
) -> sqlite3.Row:
    """Generate and persist a brand-new resume version for one job.

    Raises `MasterResumeError` if no valid master resume exists yet -- the
    API turns that into the `master_resume_missing` error state. Never
    raises for a missing/failed LaTeX compiler: that's recorded on the
    returned row as `compiler_status` (`unavailable`/`failed`) instead, so a
    compiler-less machine can still generate and inspect LaTeX source.

    `mode="llm_enhanced"` attempts a bounded set of LLM rewrites on top of
    the exact same deterministic tailoring `mode="deterministic"` (the
    default) uses — see `app/resume/rewriter.py`. `llm_provider` is
    injectable for tests; in production it's built from
    `APPLYOPS_LLM_PROVIDER`/`APPLYOPS_OLLAMA_*` env vars the first time it's
    needed. Raises `InvalidResumeModeError`/`LLMUnavailableError` before any
    version is created — a bad request never produces a half-built row.
    """
    if mode not in VALID_GENERATION_MODES:
        raise InvalidResumeModeError(
            f"Unsupported resume generation mode '{mode}'. Supported modes: {', '.join(VALID_GENERATION_MODES)}."
        )

    master = load_master_resume(master_resume_path)
    tailored, analysis = tailor_resume(master, job_row["description"])

    rewrite_attempts: list = []
    provider_name: str | None = None
    model_name: str | None = None

    if mode == "llm_enhanced":
        provider = llm_provider if llm_provider is not None else build_provider_from_env()
        if provider is None:
            raise LLMUnavailableError(
                "No LLM provider is configured. Set APPLYOPS_LLM_PROVIDER=ollama (and APPLYOPS_OLLAMA_BASE_URL/"
                "APPLYOPS_OLLAMA_MODEL) to enable llm_enhanced generation."
            )
        provider_status = provider.status()
        if not provider_status.reachable:
            raise LLMUnavailableError(provider_status.error or f"The configured {provider.name} provider is not reachable.")

        tailored, rewrite_attempts = rewrite_tailored_resume(
            tailored, analysis, job_row["title"], job_row["description"], provider,
        )
        provider_name = provider.name
        model_name = provider.model

    latex_source = render_latex(tailored)

    job_unique_key = job_row["unique_key"]
    version = database.next_resume_version(connection, job_unique_key)
    build_dir = storage.ensure_version_dir(job_unique_key, version, resumes_root)

    pdf_path: str | None = None
    page_count: int | None = None
    try:
        result: CompileResult = compile_latex(latex_source, build_dir, which=which, run=run)
    except LatexCompilerUnavailableError as exc:
        compiler_status = "unavailable"
        compile_log = str(exc)
    else:
        compile_log = result.log
        if result.success:
            compiler_status = "compiled"
            page_count = result.page_count
            pdf_file = build_dir / "resume.pdf"
            pdf_path = str(pdf_file)
        else:
            compiler_status = "failed"

    resume_id = database.insert_resume_version(
        connection,
        job_unique_key=job_unique_key,
        version=version,
        latex_source=latex_source,
        pdf_path=pdf_path,
        compiler_status=compiler_status,
        compile_log=compile_log,
        page_count=page_count,
        tailoring_analysis=asdict(analysis),
        generation_mode=mode,
        llm_provider=provider_name,
        llm_model=model_name,
        rewrite_attempted=len(rewrite_attempts),
        rewrite_accepted=sum(1 for a in rewrite_attempts if a.validation_status == "accepted"),
        rewrite_rejected=sum(1 for a in rewrite_attempts if a.validation_status in ("rejected", "error")),
        rewrite_provenance=[asdict(a) for a in rewrite_attempts],
    )
    return database.get_resume_version(connection, resume_id)
