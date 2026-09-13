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
from app.resume.master import DEFAULT_MASTER_RESUME_PATH, MasterResumeError, load_master_resume
from app.resume.tailor import tailor_resume


def generate_resume_version(
    connection: sqlite3.Connection,
    job_row: sqlite3.Row,
    *,
    master_resume_path: str | Path = DEFAULT_MASTER_RESUME_PATH,
    resumes_root: Path = storage.DEFAULT_RESUMES_ROOT,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> sqlite3.Row:
    """Generate and persist a brand-new resume version for one job.

    Raises `MasterResumeError` if no valid master resume exists yet -- the
    API turns that into the `master_resume_missing` error state. Never
    raises for a missing/failed LaTeX compiler: that's recorded on the
    returned row as `compiler_status` (`unavailable`/`failed`) instead, so a
    compiler-less machine can still generate and inspect LaTeX source.
    """
    master = load_master_resume(master_resume_path)
    tailored, analysis = tailor_resume(master, job_row["description"])
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
    )
    return database.get_resume_version(connection, resume_id)
