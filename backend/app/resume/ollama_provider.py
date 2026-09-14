"""Ollama implementation of `ResumeLLMProvider`.

Talks to a local-network Ollama server (typically running on a DGX) over
plain HTTP. Uses an injectable `httpx.Client` — same pattern as
`app/collectors/base.py` — so tests never make a real network call.
"""

import os
import time

import httpx

from app.resume.llm_provider import (
    AnswerRequest,
    AnswerResponse,
    ProviderStatus,
    RewriteRequest,
    RewriteResponse,
    ResumeLLMProvider,
    ResumeLLMProviderError,
)
from app.resume.rewrite_prompt import build_rewrite_prompt, parse_rewrite_response

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1"
DEFAULT_TIMEOUT_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 5.0
# One retry for a transient connection failure only — never for a timeout
# (a slow model is not a reason to double the wait) and never more than
# once, so a genuinely offline DGX fails fast instead of retry-storming it.
MAX_CONNECT_RETRIES = 1


def is_configured(provider_name: str | None) -> bool:
    return (provider_name or "").strip().lower() == "ollama"


class OllamaResumeProvider(ResumeLLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout_seconds = timeout_seconds
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=CONNECT_TIMEOUT_SECONDS, read=self.timeout_seconds, write=self.timeout_seconds, pool=5.0)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        attempts = 0
        last_error: Exception | None = None

        while attempts <= MAX_CONNECT_RETRIES:
            attempts += 1
            try:
                if self._client is not None:
                    return self._client.request(method, url, **kwargs)
                with httpx.Client(timeout=self._timeout()) as client:
                    return client.request(method, url, **kwargs)
            except httpx.ConnectError as exc:
                last_error = exc
                if attempts <= MAX_CONNECT_RETRIES:
                    time.sleep(0.2)
                    continue
                raise
            except httpx.TimeoutException:
                raise

        raise last_error  # pragma: no cover - unreachable, loop always returns or raises

    def _generate_json_response(self, prompt: str) -> str:
        """POST one non-streaming `/api/generate` call and return the raw
        text Ollama put in `response`. Shared by `generate_rewrite` and
        `generate_answer` — same endpoint, same JSON-forcing options, same
        error handling; only the prompt (and how the caller parses the
        returned text) differs."""
        try:
            response = self._request(
                "POST",
                "/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    # Hybrid-reasoning models (e.g. Qwen3) otherwise put their
                    # actual output in a separate "thinking" field and leave
                    # "response" empty even with format="json" -- this asks
                    # for the direct answer in "response", which is the only
                    # field this provider ever reads. A no-op for models
                    # without a thinking mode (e.g. Llama 3.2).
                    "think": False,
                    "options": {"temperature": 0.2},
                },
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ResumeLLMProviderError("Could not connect to the configured Ollama server.") from exc
        except httpx.TimeoutException as exc:
            raise ResumeLLMProviderError("Ollama did not respond in time.") from exc
        except httpx.TransportError as exc:
            # Broader than ConnectError/TimeoutException -- covers a
            # connection dropping mid-response (e.g. "Connection reset by
            # peer"), which is neither a connect failure nor a timeout but
            # is exactly as transient and exactly as much "no rewrite,"
            # never a reason to invent one.
            raise ResumeLLMProviderError("The connection to Ollama was interrupted.") from exc
        except httpx.HTTPStatusError as exc:
            raise ResumeLLMProviderError(f"Ollama returned an error (HTTP {exc.response.status_code}).") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise ResumeLLMProviderError("Ollama's response was not valid JSON.") from exc

        raw_text = body.get("response") if isinstance(body, dict) else None
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ResumeLLMProviderError("Ollama's response did not include a 'response' field.")
        return raw_text

    def generate_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        raw_text = self._generate_json_response(build_rewrite_prompt(request))
        try:
            rewritten_bullet, claims_used = parse_rewrite_response(raw_text)
        except ValueError as exc:
            raise ResumeLLMProviderError(f"Ollama's rewrite output was malformed: {exc}") from exc

        return RewriteResponse(rewritten_bullet=rewritten_bullet, claims_used=claims_used)

    def generate_answer(self, request: AnswerRequest) -> AnswerResponse:
        from app.application_prep.prompt import build_answer_prompt, parse_answer_response

        raw_text = self._generate_json_response(build_answer_prompt(request))
        try:
            answer_text, claims_used = parse_answer_response(raw_text)
        except ValueError as exc:
            raise ResumeLLMProviderError(f"Ollama's answer output was malformed: {exc}") from exc

        return AnswerResponse(answer_text=answer_text, claims_used=claims_used)

    def status(self) -> ProviderStatus:
        try:
            response = self._request("GET", "/api/tags")
            response.raise_for_status()
        except httpx.ConnectError:
            return ProviderStatus(
                provider=self.name, configured=True, reachable=False, model=self._model,
                error="Could not connect to the configured Ollama server.",
            )
        except httpx.TimeoutException:
            return ProviderStatus(
                provider=self.name, configured=True, reachable=False, model=self._model,
                error="Ollama did not respond in time.",
            )
        except httpx.TransportError:
            return ProviderStatus(
                provider=self.name, configured=True, reachable=False, model=self._model,
                error="The connection to Ollama was interrupted.",
            )
        except httpx.HTTPStatusError as exc:
            return ProviderStatus(
                provider=self.name, configured=True, reachable=False, model=self._model,
                error=f"Ollama returned an error (HTTP {exc.response.status_code}).",
            )

        available_models = None
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("models"), list):
                available_models = [
                    m.get("name") for m in body["models"] if isinstance(m, dict) and isinstance(m.get("name"), str)
                ]
        except ValueError:
            available_models = None

        return ProviderStatus(
            provider=self.name, configured=True, reachable=True, model=self._model, available_models=available_models,
        )


def build_provider_from_env(env: dict[str, str] | None = None) -> OllamaResumeProvider | None:
    """Construct the configured provider from environment variables, or
    `None` if `APPLYOPS_LLM_PROVIDER` isn't set to a supported value.

    Only "ollama" is supported this phase — this function is the one place
    a future provider (Nebius/OpenAI/Anthropic) would be added, without the
    resume service or API needing to change.
    """
    env = env if env is not None else os.environ
    provider_name = env.get("APPLYOPS_LLM_PROVIDER", "")
    if not is_configured(provider_name):
        return None

    base_url = env.get("APPLYOPS_OLLAMA_BASE_URL", DEFAULT_BASE_URL)
    model = env.get("APPLYOPS_OLLAMA_MODEL", DEFAULT_MODEL)
    timeout_seconds = float(env.get("APPLYOPS_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    return OllamaResumeProvider(base_url=base_url, model=model, timeout_seconds=timeout_seconds)
