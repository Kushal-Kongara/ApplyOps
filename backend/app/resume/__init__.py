"""On-demand, evidence-bound tailored resume generation.

No LLM, no fabrication: every tailored resume is a selection/reordering of
`resume_master.json`, rendered to LaTeX and optionally compiled to PDF by a
local compiler if one is installed. See `app/resume/master.py` for the
master-resume source of truth and `app/resume/tailor.py` for the (fully
deterministic, keyword-based) tailoring algorithm.
"""

from app.resume.master import MasterResumeError, load_master_resume
from app.resume.models import MasterResume, TailoredResume, TailoringAnalysis
from app.resume.tailor import tailor_resume

__all__ = [
    "MasterResumeError",
    "load_master_resume",
    "MasterResume",
    "TailoredResume",
    "TailoringAnalysis",
    "tailor_resume",
]
