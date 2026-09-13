"""LaTeX compiler detection and invocation — fully mocked, so these tests
never depend on a real LaTeX install being present."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from app.resume.compiler import CompileResult, LatexCompilerUnavailableError, compile_latex, detect_compiler


class DetectCompilerTest(unittest.TestCase):
    def test_returns_none_when_nothing_is_installed(self):
        self.assertIsNone(detect_compiler(which=lambda name: None))

    def test_prefers_latexmk_over_pdflatex(self):
        found = detect_compiler(which=lambda name: f"/usr/bin/{name}" if name in ("latexmk", "pdflatex") else None)
        self.assertEqual(found[0], "latexmk")

    def test_falls_back_to_pdflatex_when_only_it_is_present(self):
        found = detect_compiler(which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None)
        self.assertEqual(found[0], "pdflatex")


class CompileLatexTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.build_dir = Path(self._tmp.name)

    def test_no_compiler_available_raises_clean_error(self):
        with self.assertRaises(LatexCompilerUnavailableError):
            compile_latex("src", self.build_dir, which=lambda name: None)

    def test_successful_compilation_returns_pdf_bytes_and_page_count(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            (Path(cwd) / "resume.pdf").write_bytes(b"%PDF-1.4 fake pdf bytes")
            return subprocess.CompletedProcess(
                argv, 0, stdout="Output written on resume.pdf (2 pages, 999 bytes).", stderr=""
            )

        result = compile_latex(
            "src", self.build_dir, which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run
        )
        self.assertTrue(result.success)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.pdf_bytes, b"%PDF-1.4 fake pdf bytes")

    def test_nonzero_return_code_is_a_failed_compile_not_an_exception(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="! Undefined control sequence.")

        result = compile_latex(
            "src", self.build_dir, which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.pdf_bytes)
        self.assertIn("Undefined control sequence", result.log)

    def test_missing_pdf_despite_zero_return_code_is_treated_as_failure(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        result = compile_latex(
            "src", self.build_dir, which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run
        )
        self.assertFalse(result.success)

    def test_timeout_is_handled_without_raising(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

        result = compile_latex(
            "src", self.build_dir, which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run
        )
        self.assertFalse(result.success)
        self.assertIn("timed out", result.log)

    def test_source_is_written_to_the_build_directory(self):
        def fake_run(argv, cwd, capture_output, text, timeout):
            (Path(cwd) / "resume.pdf").write_bytes(b"%PDF")
            return subprocess.CompletedProcess(argv, 0, stdout="Output written on resume.pdf (1 page).", stderr="")

        compile_latex(
            "\\documentclass{article}", self.build_dir,
            which=lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None, run=fake_run,
        )
        self.assertEqual((self.build_dir / "resume.tex").read_text(), "\\documentclass{article}")


if __name__ == "__main__":
    unittest.main()
