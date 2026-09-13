"""Deterministic, evidence-bound resume tailoring.

No LLM here on purpose (see phase spec: no paid-LLM dependency for v1). This
is pure keyword scoring against the master resume's own text — it can only
select, reorder, and report on facts that are already in `MasterResume`. It
never rephrases and never invents: every `TailoredBullet.text` is a verbatim
copy of a `Bullet.text` from the master resume, carrying that bullet's own
`id` as `evidence_id`.

Reuses the matching package's own alias table and normalizer (read-only) so
"React.js" in a JD and "React" in the master resume are recognized as the
same skill, consistent with how job matching already treats them.
"""

from app.matching.aliases import SKILL_ALIASES
from app.matching.text import any_phrase_matches, normalize_text
from app.resume.models import (
    MasterResume,
    TailoredBullet,
    TailoredExperienceEntry,
    TailoredProjectEntry,
    TailoredResume,
    TailoringAnalysis,
)

# Extra common technologies not already covered by `SKILL_ALIASES` (which is
# scoped to this candidate's own skill set). Scoped to tailoring only — this
# does not affect job matching/scoring elsewhere in the app. Purpose: give
# `unsupported_requirements` real names to report (e.g. "Go") rather than
# silently ignoring JD keywords the candidate has no alias entry for.
_EXTRA_KEYWORDS: dict[str, list[str]] = {
    "Go": ["golang", "go"],
    "Rust": ["rust"],
    "C++": ["c plus plus", "c"],
    "C#": ["c sharp"],
    ".NET": ["dotnet", "net"],
    "Kubernetes": ["kubernetes", "k8s"],
    "GraphQL": ["graphql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Kafka": ["kafka"],
    "Terraform": ["terraform"],
    "GCP": ["gcp", "google cloud platform", "google cloud"],
    "Azure": ["azure"],
    "MySQL": ["mysql"],
    "Angular": ["angular"],
    "Vue": ["vue", "vuejs", "vue js"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring": ["spring", "spring boot"],
    "gRPC": ["grpc"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
}


def _flatten_skills(skills: dict[str, list[str]]) -> list[str]:
    """Master skills, categories in declared order, de-duplicated by name
    (case-insensitive) while keeping each skill's first-seen spelling."""
    seen: dict[str, str] = {}
    for items in skills.values():
        for item in items:
            key = item.strip().lower()
            if key not in seen:
                seen[key] = item.strip()
    return list(seen.values())


def _keyword_universe() -> dict[str, list[str]]:
    universe = {name: [normalize_text(p) for p in phrases] for name, phrases in SKILL_ALIASES.items()}
    for name, phrases in _EXTRA_KEYWORDS.items():
        universe.setdefault(name, [normalize_text(p) for p in phrases])
    return universe


def tailor_resume(master: MasterResume, job_description: str) -> tuple[TailoredResume, TailoringAnalysis]:
    """Select/reorder master-resume content for one job description.

    Returns the tailored resume plus the analysis explaining why — never the
    other way around: nothing in the analysis can add a claim the tailored
    resume itself doesn't already carry (or vice versa).
    """
    jd_normalized = normalize_text(job_description)
    keyword_universe = _keyword_universe()
    flat_skills = _flatten_skills(master.skills)
    flat_skills_normalized = {normalize_text(s) for s in flat_skills}

    jd_keywords = [name for name, phrases in keyword_universe.items() if any_phrase_matches(jd_normalized, phrases)]

    strong_matches: list[str] = []
    supported_but_underemphasized: list[str] = []
    unsupported_requirements: list[str] = []

    all_bullet_texts_normalized = [
        normalize_text(bullet.text) for entry in master.experience for bullet in entry.bullets
    ] + [normalize_text(bullet.text) for project in master.projects for bullet in project.bullets]

    for keyword in jd_keywords:
        phrases = keyword_universe[keyword]
        demonstrated_in_bullet = any(any_phrase_matches(text, phrases) for text in all_bullet_texts_normalized)
        if demonstrated_in_bullet:
            strong_matches.append(keyword)
        elif any_phrase_matches(" ".join(flat_skills_normalized), phrases) or normalize_text(keyword) in flat_skills_normalized:
            supported_but_underemphasized.append(keyword)
        else:
            unsupported_requirements.append(keyword)

    supported_keyword_phrases = [
        phrase
        for name in (strong_matches + supported_but_underemphasized)
        for phrase in keyword_universe[name]
    ]

    def _bullet_relevance(bullet_text_normalized: str) -> int:
        return sum(1 for phrase in supported_keyword_phrases if any_phrase_matches(bullet_text_normalized, [phrase]))

    tailored_experience: list[TailoredExperienceEntry] = []
    experience_scores: list[tuple[str, int]] = []
    for entry in master.experience:
        scored_bullets = [(_bullet_relevance(normalize_text(b.text)), b) for b in entry.bullets]
        scored_bullets.sort(key=lambda pair: pair[0], reverse=True)
        tailored_bullets = [TailoredBullet(text=b.text, evidence_id=b.id) for _, b in scored_bullets]
        tailored_experience.append(
            TailoredExperienceEntry(
                id=entry.id,
                company=entry.company,
                title=entry.title,
                start_date=entry.start_date,
                end_date=entry.end_date,
                location=entry.location,
                bullets=tailored_bullets,
            )
        )
        experience_scores.append((entry.id, sum(score for score, _ in scored_bullets)))

    tailored_projects: list[TailoredProjectEntry] = []
    project_scores: list[tuple[str, int]] = []
    for project in master.projects:
        scored_bullets = [(_bullet_relevance(normalize_text(b.text)), b) for b in project.bullets]
        scored_bullets.sort(key=lambda pair: pair[0], reverse=True)
        tailored_bullets = [TailoredBullet(text=b.text, evidence_id=b.id) for _, b in scored_bullets]
        tailored_projects.append(
            TailoredProjectEntry(id=project.id, name=project.name, technologies=project.technologies, bullets=tailored_bullets)
        )
        project_scores.append((project.id, sum(score for score, _ in scored_bullets)))

    def _skill_relevance(skill: str) -> tuple[int, int]:
        skill_normalized = normalize_text(skill)
        if any(skill_normalized == normalize_text(name) or any_phrase_matches(skill_normalized, keyword_universe[name]) for name in strong_matches):
            return (0, 0)
        if any(skill_normalized == normalize_text(name) or any_phrase_matches(skill_normalized, keyword_universe[name]) for name in supported_but_underemphasized):
            return (1, 0)
        return (2, flat_skills.index(skill))

    ordered_skills = sorted(flat_skills, key=_skill_relevance)

    selected_experience = [entry_id for entry_id, score in sorted(experience_scores, key=lambda p: p[1], reverse=True) if score > 0]
    selected_projects = [proj_id for proj_id, score in sorted(project_scores, key=lambda p: p[1], reverse=True) if score > 0]

    tailored_resume = TailoredResume(
        contact=master.contact,
        summary=master.summary,
        skills=ordered_skills,
        experience=tailored_experience,
        education=list(master.education),
        projects=tailored_projects,
        achievements=list(master.achievements),
    )
    analysis = TailoringAnalysis(
        strong_matches=strong_matches,
        supported_but_underemphasized=supported_but_underemphasized,
        unsupported_requirements=unsupported_requirements,
        selected_experience=selected_experience,
        selected_projects=selected_projects,
    )
    return tailored_resume, analysis
