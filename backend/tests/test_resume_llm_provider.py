"""Tests for `OllamaResumeProvider` and `build_provider_from_env`. No real
network calls — `httpx.MockTransport` stands in for the Ollama server,
same pattern `tests/support.py` already uses for collector tests."""

import json
import unittest

import httpx

from app.resume.llm_provider import RewriteRequest, ResumeLLMProviderError
from app.resume.ollama_provider import DEFAULT_MODEL, OllamaResumeProvider, build_provider_from_env


def _generate_handler(rewritten_bullet: str, claims_used: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "model": "test-model",
            "response": json.dumps({"rewritten_bullet": rewritten_bullet, "claims_used": claims_used or []}),
            "done": True,
        }
        return httpx.Response(200, json=body, request=request)

    return handler


def _tags_handler(models: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": m} for m in models]}, request=request)

    return handler


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


SAMPLE_REQUEST = RewriteRequest(
    job_title="Software Engineer",
    jd_excerpt="React and TypeScript required.",
    original_bullet="Built features using React and TypeScript.",
    allowed_facts=["React", "TypeScript"],
    target_emphasis=["React"],
)


class BuildProviderFromEnvTest(unittest.TestCase):
    def test_unconfigured_when_env_var_missing(self):
        self.assertIsNone(build_provider_from_env(env={}))

    def test_unconfigured_when_provider_is_something_else(self):
        self.assertIsNone(build_provider_from_env(env={"APPLYOPS_LLM_PROVIDER": "openai"}))

    def test_configured_reads_base_url_and_model_from_env(self):
        provider = build_provider_from_env(env={
            "APPLYOPS_LLM_PROVIDER": "ollama",
            "APPLYOPS_OLLAMA_BASE_URL": "http://10.0.0.5:11434",
            "APPLYOPS_OLLAMA_MODEL": "llama3.1",
        })
        self.assertIsNotNone(provider)
        self.assertEqual(provider.base_url, "http://10.0.0.5:11434")
        self.assertEqual(provider.model, "llama3.1")

    def test_configured_falls_back_to_defaults_when_only_provider_is_set(self):
        provider = build_provider_from_env(env={"APPLYOPS_LLM_PROVIDER": "ollama"})
        self.assertIsNotNone(provider)
        self.assertEqual(provider.model, DEFAULT_MODEL)

    def test_provider_name_matching_is_case_insensitive(self):
        self.assertIsNotNone(build_provider_from_env(env={"APPLYOPS_LLM_PROVIDER": "Ollama"}))


class OllamaProviderStatusTest(unittest.TestCase):
    def test_reachable_reports_installed_models(self):
        provider = OllamaResumeProvider(client=_client(_tags_handler(["llama3.1", "mistral"])), model="llama3.1")
        status = provider.status()
        self.assertTrue(status.reachable)
        self.assertTrue(status.configured)
        self.assertEqual(status.model, "llama3.1")
        self.assertEqual(status.available_models, ["llama3.1", "mistral"])
        self.assertIsNone(status.error)

    def test_unreachable_connection_error_is_sanitized(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused to 10.0.0.5", request=request)

        provider = OllamaResumeProvider(client=_client(refuse))
        status = provider.status()
        self.assertFalse(status.reachable)
        self.assertIsNotNone(status.error)
        self.assertNotIn("10.0.0.5", status.error)

    def test_timeout_is_reported_as_unreachable(self):
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        provider = OllamaResumeProvider(client=_client(slow))
        status = provider.status()
        self.assertFalse(status.reachable)
        self.assertIn("time", status.error.lower())

    def test_connection_reset_is_reported_as_unreachable(self):
        def reset(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("Connection reset by peer", request=request)

        provider = OllamaResumeProvider(client=_client(reset))
        status = provider.status()
        self.assertFalse(status.reachable)
        self.assertIsNotNone(status.error)

    def test_http_error_status_is_reported_as_unreachable(self):
        def server_error(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        provider = OllamaResumeProvider(client=_client(server_error))
        status = provider.status()
        self.assertFalse(status.reachable)


class OllamaProviderGenerateRewriteTest(unittest.TestCase):
    def test_valid_structured_response_is_parsed(self):
        provider = OllamaResumeProvider(
            client=_client(_generate_handler("Rewritten bullet text.", ["React"])), model="llama3.1",
        )
        response = provider.generate_rewrite(SAMPLE_REQUEST)
        self.assertEqual(response.rewritten_bullet, "Rewritten bullet text.")
        self.assertEqual(response.claims_used, ["React"])

    def test_connection_failure_raises_provider_error(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        provider = OllamaResumeProvider(client=_client(refuse))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)

    def test_timeout_raises_provider_error(self):
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        provider = OllamaResumeProvider(client=_client(slow))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)

    def test_connection_reset_mid_response_raises_provider_error(self):
        # A connection dropping mid-response (httpx.ReadError, e.g. "Connection
        # reset by peer") is neither a ConnectError nor a TimeoutException --
        # this must still become a clean ResumeLLMProviderError, not an
        # unhandled httpx exception.
        def reset(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("Connection reset by peer", request=request)

        provider = OllamaResumeProvider(client=_client(reset))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)

    def test_malformed_json_response_raises_provider_error(self):
        def bad(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"model": "x", "response": "not valid json", "done": True}, request=request)

        provider = OllamaResumeProvider(client=_client(bad))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)

    def test_missing_rewritten_bullet_field_raises_provider_error(self):
        def bad(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"model": "x", "response": json.dumps({"claims_used": []}), "done": True}, request=request)

        provider = OllamaResumeProvider(client=_client(bad))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)

    def test_missing_response_field_entirely_raises_provider_error(self):
        def bad(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"model": "x", "done": True}, request=request)

        provider = OllamaResumeProvider(client=_client(bad))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)

    def test_http_error_status_raises_provider_error(self):
        def server_error(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        provider = OllamaResumeProvider(client=_client(server_error))
        with self.assertRaises(ResumeLLMProviderError):
            provider.generate_rewrite(SAMPLE_REQUEST)


if __name__ == "__main__":
    unittest.main()
