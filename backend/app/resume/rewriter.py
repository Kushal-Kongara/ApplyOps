"""Selects a bounded set of high-relevance bullets and attempts an LLM
rewrite of each, one bullet at a time — never the whole resume in one call.

Every accepted rewrite replaces that bullet's text in the returned
`TailoredResume`; every rejected or failed attempt leaves the original,
already-verbatim-from-master-resume text in place. Nothing here can ever
produce a bullet whose text didn't come from either the master resume
directly or a rewrite that passed `app/resume/validator.py`.
"""

from dataclasses import replace

from app.matching.text import normalize_text
from app.resume.evidence import build_evidence_vocabulary, recognized_facts
from app.resume.llm_provider import RewriteRequest, ResumeLLMProvider, ResumeLLMProviderError
from app.resume.models import MasterResume, RewriteAttempt, TailoredExperienceEntry, TailoredResume, TailoringAnalysis
from app.resume.validator import validate_rewrite

# A resume-wide cap, not a per-job tuning knob: keeps DGX load and latency
# bounded, and keeps rewrites focused on the bullets that actually matter
# for this job rather than rewriting an entire resume's worth of content.
MAX_REWRITES_PER_RESUME = 6

# How much of the job description is shown as reference context per
# rewrite call. Short on purpose — this is context, not instructions, and a
# short excerpt is cheaper to keep clearly delimited and inert.
JD_EXCERPT_MAX_CHARS = 800


def _bullet_facts(bullet_text: str, vocabulary: dict[str, list[str]]) -> list[str]:
    """Technology/skill names this bullet's own text already demonstrates —
    the only facts a rewrite of this bullet is allowed to state. `vocabulary`
    should come from `build_evidence_vocabulary()` so a master-resume-only
    skill (no job-matching alias) is still recognized here."""
    return list(recognized_facts(normalize_text(bullet_text), vocabulary))


def _select_bullets_for_rewrite(
    tailored: TailoredResume, analysis: TailoringAnalysis, vocabulary: dict[str, list[str]], max_rewrites: int
) -> list[tuple[str, str, str]]:
    """The most relevant bullet from each experience entry (tailoring
    already sorted each entry's bullets by relevance — index 0 is the
    strongest), skipping entries with no JD relevance at all, capped at
    `max_rewrites` total. Returns `(entry_id, bullet.evidence_id, bullet.text)`.
    """
    candidates: list[tuple[str, str, str]] = []
    strong_matches_normalized = {normalize_text(s) for s in analysis.strong_matches}

    for entry in tailored.experience:
        if entry.id not in analysis.selected_experience:
            continue
        top_bullet = entry.bullets[0]
        facts = _bullet_facts(top_bullet.text, vocabulary)
        if not any(normalize_text(fact) in strong_matches_normalized for fact in facts):
            continue
        candidates.append((entry.id, top_bullet.evidence_id, top_bullet.text))

    return candidates[:max_rewrites]


def rewrite_tailored_resume(
    tailored: TailoredResume,
    analysis: TailoringAnalysis,
    master: MasterResume,
    job_title: str,
    job_description: str,
    provider: ResumeLLMProvider,
    max_rewrites: int = MAX_REWRITES_PER_RESUME,
) -> tuple[TailoredResume, list[RewriteAttempt]]:
    """Attempt to rewrite a bounded set of the most job-relevant bullets.

    `master` is the same master resume `tailored`/`analysis` were built
    from — it's the source of truth for `build_evidence_vocabulary()`, so a
    skill listed there is recognized as evidence even without a matching
    job-matching alias.

    Returns a new `TailoredResume` (accepted rewrites applied, everything
    else untouched) plus the full list of attempts — accepted, rejected,
    and errored alike.
    """
    vocabulary = build_evidence_vocabulary(master)
    selected = _select_bullets_for_rewrite(tailored, analysis, vocabulary, max_rewrites)
    if not selected:
        return tailored, []

    jd_excerpt = job_description.strip()[:JD_EXCERPT_MAX_CHARS]
    strong_matches_normalized = {normalize_text(s) for s in analysis.strong_matches}

    accepted_text_by_evidence_id: dict[str, str] = {}
    attempts: list[RewriteAttempt] = []

    for _entry_id, evidence_id, original_text in selected:
        allowed_facts = _bullet_facts(original_text, vocabulary)
        target_emphasis = [fact for fact in allowed_facts if normalize_text(fact) in strong_matches_normalized]

        request = RewriteRequest(
            job_title=job_title,
            jd_excerpt=jd_excerpt,
            original_bullet=original_text,
            allowed_facts=allowed_facts,
            target_emphasis=target_emphasis,
        )

        try:
            response = provider.generate_rewrite(request)
        except ResumeLLMProviderError as exc:
            attempts.append(
                RewriteAttempt(
                    evidence_id=evidence_id, original_text=original_text, rewritten_text=None,
                    validation_status="error", validation_reasons=[str(exc)],
                    provider=provider.name, model=provider.model,
                )
            )
            continue

        result = validate_rewrite(
            original_text, response.rewritten_bullet, allowed_facts,
            target_emphasis=target_emphasis, evidence_vocabulary=vocabulary,
        )
        if result.accepted:
            accepted_text_by_evidence_id[evidence_id] = response.rewritten_bullet
            attempts.append(
                RewriteAttempt(
                    evidence_id=evidence_id, original_text=original_text, rewritten_text=response.rewritten_bullet,
                    validation_status="accepted", validation_reasons=[],
                    provider=provider.name, model=provider.model,
                )
            )
        else:
            attempts.append(
                RewriteAttempt(
                    evidence_id=evidence_id, original_text=original_text, rewritten_text=response.rewritten_bullet,
                    validation_status="rejected", validation_reasons=result.reasons,
                    provider=provider.name, model=provider.model,
                )
            )

    if not accepted_text_by_evidence_id:
        return tailored, attempts

    new_experience: list[TailoredExperienceEntry] = []
    for entry in tailored.experience:
        new_bullets = [
            replace(bullet, text=accepted_text_by_evidence_id[bullet.evidence_id])
            if bullet.evidence_id in accepted_text_by_evidence_id
            else bullet
            for bullet in entry.bullets
        ]
        new_experience.append(replace(entry, bullets=new_bullets))

    return replace(tailored, experience=new_experience), attempts
