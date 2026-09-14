"""Provider-agnostic contract for rewriting one resume bullet, and for
generating one application-question answer, at a time.

`ResumeLLMProvider` is the only thing `app/resume/rewriter.py` and
`app/application_prep/generator.py` depend on — adding Nebius/OpenAI/Anthropic
later means writing one new class here, never touching the rewriter,
validators, or either service. `OllamaResumeProvider`
(`app/resume/ollama_provider.py`) is the only implementation this phase adds.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RewriteRequest:
    """Everything one bullet-rewrite call is allowed to see. Deliberately
    narrow: one bullet, the facts it's already allowed to state, and which
    of those facts matter most for this job — never the whole resume, never
    raw unfiltered JD text as instructions."""

    job_title: str
    jd_excerpt: str
    original_bullet: str
    allowed_facts: list[str]
    target_emphasis: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RewriteResponse:
    rewritten_bullet: str
    claims_used: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    """Everything one application-question answer call is allowed to see —
    the question, minimal job context, and the specific facts/evidence it's
    allowed to draw from. Never the whole resume, never raw unfiltered JD
    text as instructions."""

    question_text: str
    job_title: str
    company: str
    jd_excerpt: str
    allowed_facts: list[str]
    evidence_bullets: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AnswerResponse:
    answer_text: str
    claims_used: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    configured: bool
    reachable: bool
    model: str | None = None
    error: str | None = None
    available_models: list[str] | None = None


class ResumeLLMProviderError(RuntimeError):
    """Raised when a provider cannot produce a usable rewrite — unreachable,
    timed out, or returned something that isn't parseable structured output.
    Callers (the rewriter) treat this as "no rewrite," never as a reason to
    invent one."""


class ResumeLLMProvider(ABC):
    name: str

    @abstractmethod
    def generate_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        """Rewrite one bullet. Raises `ResumeLLMProviderError` on any
        failure — never returns a partial or best-effort guess."""
        raise NotImplementedError

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Cheap connectivity/configuration check — used by the `/api/llm/status`
        endpoint and by the resume service before attempting any rewrites."""
        raise NotImplementedError

    @property
    @abstractmethod
    def model(self) -> str:
        raise NotImplementedError

    def generate_answer(self, request: AnswerRequest) -> AnswerResponse:
        """Generate one application-question answer. Not `@abstractmethod`
        so existing `ResumeLLMProvider` subclasses (including test fakes
        written before this method existed) don't break — a provider that
        doesn't override this simply can't be used for answer generation.
        Raises `ResumeLLMProviderError` on any failure, exactly like
        `generate_rewrite`."""
        raise NotImplementedError(f"{type(self).__name__} does not implement generate_answer().")
