"""Renders a `TailoredResume` into LaTeX source.

Uses a plain-text `<<TOKEN>>` placeholder template rather than a templating
engine like Jinja2 — Jinja's `{{ }}` / `{% %}` syntax collides constantly
with LaTeX's own heavy use of `{` and `}`, so a custom placeholder avoids a
whole class of escaping bugs. Every value substituted into the template is
escaped exactly once via `escape_latex`.
"""

from pathlib import Path

from app.resume.models import TailoredResume

TEMPLATE_PATH = Path(__file__).parent / "templates" / "resume.tex"

# Order matters only in that `\` must be escaped first — otherwise the
# backslash introduced by escaping (e.g. `%` -> `\%`) would itself get
# escaped on a later pass. Doing this as a single character-by-character
# pass (see `escape_latex` below) instead of sequential `str.replace()`
# calls sidesteps that class of bug entirely: each input character is
# looked up and replaced exactly once, so there is no "later pass" for a
# replacement's own backslash to be caught by.
_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters so arbitrary text (job-derived or
    not) can never break compilation or inject LaTeX commands."""
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in text)


def _bullets_block(bullets, indent: str = "    ") -> str:
    if not bullets:
        return ""
    items = "\n".join(f"{indent}\\item {escape_latex(b.text)}" for b in bullets)
    return f"{indent}\\begin{{itemize}}\n{items}\n{indent}\\end{{itemize}}"


def _experience_block(experience) -> str:
    parts = []
    for entry in experience:
        dates = escape_latex(f"{entry.start_date} -- {entry.end_date}".strip(" -"))
        location = escape_latex(entry.location)
        parts.append(
            "\\resumeEntry"
            f"{{{escape_latex(entry.title)}}}"
            f"{{{escape_latex(entry.company)}}}"
            f"{{{dates}}}"
            f"{{{location}}}\n"
            f"{_bullets_block(entry.bullets)}"
        )
    return "\n\n".join(parts)


def _projects_block(projects) -> str:
    parts = []
    for project in projects:
        technologies = escape_latex(", ".join(project.technologies))
        parts.append(
            "\\resumeProject"
            f"{{{escape_latex(project.name)}}}"
            f"{{{technologies}}}\n"
            f"{_bullets_block(project.bullets)}"
        )
    return "\n\n".join(parts)


def _education_block(education) -> str:
    parts = []
    for entry in education:
        dates = escape_latex(f"{entry.start_date} -- {entry.end_date}".strip(" -"))
        parts.append(
            "\\resumeEntry"
            f"{{{escape_latex(entry.degree)}}}"
            f"{{{escape_latex(entry.school)}}}"
            f"{{{dates}}}"
            f"{{{escape_latex(entry.location)}}}"
        )
    return "\n\n".join(parts)


def _achievements_block(achievements) -> str:
    if not achievements:
        return ""
    items = "\n".join(f"    \\item {escape_latex(a.text)}" for a in achievements)
    return f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}"


def _contact_line(contact) -> str:
    parts = [escape_latex(contact.email)]
    if contact.phone:
        parts.append(escape_latex(contact.phone))
    if contact.linkedin:
        parts.append(escape_latex(contact.linkedin))
    if contact.github:
        parts.append(escape_latex(contact.github))
    return " \\quad|\\quad ".join(parts)


def render_latex(resume: TailoredResume) -> str:
    """Render a `TailoredResume` into complete LaTeX document source."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    optional_sections = []
    if resume.projects:
        optional_sections.append(
            "\\section*{Projects}\n" + _projects_block(resume.projects)
        )
    if resume.achievements:
        optional_sections.append(
            "\\section*{Achievements}\n" + _achievements_block(resume.achievements)
        )

    replacements = {
        "<<NAME>>": escape_latex(resume.contact.name),
        "<<HEADLINE>>": escape_latex(resume.contact.headline),
        "<<CONTACT_LINE>>": _contact_line(resume.contact),
        "<<SUMMARY>>": escape_latex(resume.summary),
        "<<SKILLS>>": escape_latex(", ".join(resume.skills)),
        "<<EXPERIENCE>>": _experience_block(resume.experience),
        "<<EDUCATION>>": _education_block(resume.education),
        "<<OPTIONAL_SECTIONS>>": "\n\n".join(optional_sections),
    }

    for token, value in replacements.items():
        template = template.replace(token, value)
    return template
