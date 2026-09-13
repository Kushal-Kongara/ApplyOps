"""`app.resume.service.generate_resume_version`: the orchestration that ties
master-resume loading, tailoring, LaTeX rendering, and compilation together.
Compiler `which`/`run` are always mocked here — no real LaTeX install needed.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import database
from app.resume.llm_provider import ProviderStatus, RewriteRequest, RewriteResponse, ResumeLLMProvider, ResumeLLMProviderError
from app.resume.master import MasterResumeError
from app.resume.service import InvalidResumeModeError, LLMUnavailableError, generate_resume_version
from tests.support import make_job, make_master_resume_dict


class FakeReachableProvider(ResumeLLMProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, rewrite_fn=None):
        self._rewrite_fn = rewrite_fn or (lambda req: RewriteResponse(rewritten_bullet=req.original_bullet))

    def generate_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        return self._rewrite_fn(request)

    def status(self) -> ProviderStatus:
        return ProviderStatus(provider=self.name, configured=True, reachable=True, model=self.model)


class FakeUnreachableProvider(ResumeLLMProvider):
    name = "fake"
    model = "fake-model"

    def generate_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        raise ResumeLLMProviderError("should never be called")

    def status(self) -> ProviderStatus:
        return ProviderStatus(provider=self.name, configured=True, reachable=False, error="simulated unreachable")


class GenerateResumeVersionTest(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(self.connection, [make_job(external_id="1", description="Looking for a React and Python engineer.")])
        self.job_row = database.get_job(self.connection, "greenhouse:acme:1")

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

        self.master_path = self.tmp_path / "resume_master.json"
        self.master_path.write_text(json.dumps(make_master_resume_dict()))
        self.resumes_root = self.tmp_path / "resumes"

    def test_missing_master_resume_raises_master_resume_error(self):
        with self.assertRaises(MasterResumeError):
            generate_resume_version(
                self.connection, self.job_row,
                master_resume_path=self.tmp_path / "does_not_exist.json",
                resumes_root=self.resumes_root,
                which=lambda name: None,
            )

    def test_generates_version_one_with_no_compiler_available(self):
        row = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root,
            which=lambda name: None,
        )
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["compiler_status"], "unavailable")
        self.assertIsNone(row["pdf_path"])
        self.assertIn("Test Candidate", row["latex_source"])

    def test_tailoring_analysis_is_persisted_and_reflects_the_jd(self):
        row = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root,
            which=lambda name: None,
        )
        analysis = json.loads(row["tailoring_analysis"])
        self.assertIn("React", analysis["strong_matches"])

    def test_regeneration_creates_a_new_version_and_keeps_the_old_one(self):
        v1 = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        v2 = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        self.assertEqual(v1["version"], 1)
        self.assertEqual(v2["version"], 2)
        self.assertIsNotNone(database.get_resume_version(self.connection, v1["id"]))

    def test_deterministic_regeneration_with_unchanged_inputs_yields_identical_content(self):
        v1 = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        v2 = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        self.assertEqual(v1["latex_source"], v2["latex_source"])

    def test_successful_mocked_compilation_records_compiled_status_and_pdf_path(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            (Path(cwd) / "resume.pdf").write_bytes(b"%PDF-fake")
            return subprocess.CompletedProcess(argv, 0, stdout="Output written on resume.pdf (1 page).", stderr="")

        row = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root,
            which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run,
        )
        self.assertEqual(row["compiler_status"], "compiled")
        self.assertEqual(row["page_count"], 1)
        self.assertTrue(Path(row["pdf_path"]).exists())

    def test_failed_mocked_compilation_records_failed_status(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="! Emergency stop.")

        row = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root,
            which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run,
        )
        self.assertEqual(row["compiler_status"], "failed")
        self.assertIsNone(row["pdf_path"])

    def test_different_jobs_get_isolated_version_histories(self):
        database.upsert_jobs(self.connection, [make_job(external_id="2", description="Needs a Python dev.")])
        other_job = database.get_job(self.connection, "greenhouse:acme:2")

        generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        row = generate_resume_version(
            self.connection, other_job,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        self.assertEqual(row["version"], 1)

    def test_invalid_mode_raises_before_any_version_is_created(self):
        with self.assertRaises(InvalidResumeModeError):
            generate_resume_version(
                self.connection, self.job_row, mode="bogus",
                master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
            )
        self.assertEqual(database.list_resume_versions(self.connection, "greenhouse:acme:1"), [])

    def test_default_mode_is_deterministic(self):
        row = generate_resume_version(
            self.connection, self.job_row,
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
        )
        self.assertEqual(row["generation_mode"], "deterministic")
        self.assertIsNone(row["llm_provider"])


class LLMEnhancedGenerationTest(unittest.TestCase):
    def setUp(self):
        self.connection = database.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.upsert_jobs(
            self.connection,
            [make_job(external_id="1", description="Looking for a React and TypeScript engineer for customer-facing work.")],
        )
        self.job_row = database.get_job(self.connection, "greenhouse:acme:1")

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.master_path = self.tmp_path / "resume_master.json"
        self.master_path.write_text(json.dumps(make_master_resume_dict()))
        self.resumes_root = self.tmp_path / "resumes"

    def test_llm_unavailable_raises_before_any_version_is_created(self):
        with self.assertRaises(LLMUnavailableError):
            generate_resume_version(
                self.connection, self.job_row, mode="llm_enhanced",
                master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
                llm_provider=FakeUnreachableProvider(),
            )
        self.assertEqual(database.list_resume_versions(self.connection, "greenhouse:acme:1"), [])

    def test_no_provider_configured_and_none_injected_raises_llm_unavailable(self):
        with self.assertRaises(LLMUnavailableError):
            generate_resume_version(
                self.connection, self.job_row, mode="llm_enhanced",
                master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
                llm_provider=None,
            )

    def test_accepted_rewrite_is_reflected_in_generation_metadata_and_latex(self):
        provider = FakeReachableProvider(
            lambda req: RewriteResponse(rewritten_bullet="Built customer-facing product features using React and TypeScript.")
        )
        row = generate_resume_version(
            self.connection, self.job_row, mode="llm_enhanced",
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
            llm_provider=provider,
        )
        self.assertEqual(row["generation_mode"], "llm_enhanced")
        self.assertEqual(row["llm_provider"], "fake")
        self.assertEqual(row["llm_model"], "fake-model")
        self.assertEqual(row["rewrite_attempted"], 1)
        self.assertEqual(row["rewrite_accepted"], 1)
        self.assertEqual(row["rewrite_rejected"], 0)
        self.assertIn("customer-facing product features", row["latex_source"])

    def test_rejected_rewrite_falls_back_but_version_still_generates(self):
        provider = FakeReachableProvider(lambda req: RewriteResponse(rewritten_bullet=req.original_bullet + " Deployed via Kubernetes."))
        row = generate_resume_version(
            self.connection, self.job_row, mode="llm_enhanced",
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
            llm_provider=provider,
        )
        self.assertEqual(row["rewrite_accepted"], 0)
        self.assertEqual(row["rewrite_rejected"], 1)
        self.assertNotIn("Kubernetes", row["latex_source"])

    def test_provider_failure_does_not_corrupt_version_state(self):
        class MidStreamFailingProvider(FakeReachableProvider):
            def generate_rewrite(self, request):
                raise ResumeLLMProviderError("transient failure mid-rewrite")

        row = generate_resume_version(
            self.connection, self.job_row, mode="llm_enhanced",
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
            llm_provider=MidStreamFailingProvider(),
        )
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["rewrite_attempted"], 1)
        self.assertEqual(row["rewrite_accepted"], 0)
        versions = database.list_resume_versions(self.connection, "greenhouse:acme:1")
        self.assertEqual(len(versions), 1)

    def test_rewrite_provenance_is_persisted(self):
        provider = FakeReachableProvider(
            lambda req: RewriteResponse(rewritten_bullet="Built customer-facing product features using React and TypeScript.")
        )
        row = generate_resume_version(
            self.connection, self.job_row, mode="llm_enhanced",
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
            llm_provider=provider,
        )
        provenance = json.loads(row["rewrite_provenance"])
        self.assertEqual(len(provenance), 1)
        self.assertIn("evidence_id", provenance[0])
        self.assertIn("original_text", provenance[0])
        self.assertEqual(provenance[0]["validation_status"], "accepted")

    def test_deterministic_mode_is_unaffected_by_llm_availability(self):
        row = generate_resume_version(
            self.connection, self.job_row, mode="deterministic",
            master_resume_path=self.master_path, resumes_root=self.resumes_root, which=lambda name: None,
            llm_provider=FakeUnreachableProvider(),
        )
        self.assertEqual(row["generation_mode"], "deterministic")
        self.assertEqual(row["rewrite_attempted"], 0)


if __name__ == "__main__":
    unittest.main()
