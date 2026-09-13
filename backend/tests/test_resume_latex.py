"""LaTeX escaping and rendering."""

import unittest

from app.resume.latex import escape_latex, render_latex
from app.resume.master import load_master_resume
from app.resume.tailor import tailor_resume
from tests.support import make_master_resume_dict


def _load():
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume_master.json"
        path.write_text(json.dumps(make_master_resume_dict()))
        return load_master_resume(path)


class EscapeLatexTest(unittest.TestCase):
    def test_escapes_every_special_character(self):
        self.assertEqual(escape_latex("&"), r"\&")
        self.assertEqual(escape_latex("%"), r"\%")
        self.assertEqual(escape_latex("$"), r"\$")
        self.assertEqual(escape_latex("#"), r"\#")
        self.assertEqual(escape_latex("_"), r"\_")
        self.assertEqual(escape_latex("{"), r"\{")
        self.assertEqual(escape_latex("}"), r"\}")
        self.assertEqual(escape_latex("~"), r"\textasciitilde{}")
        self.assertEqual(escape_latex("^"), r"\textasciicircum{}")
        self.assertEqual(escape_latex("\\"), r"\textbackslash{}")

    def test_does_not_double_escape_backslash_replacement_text(self):
        # A naive sequential str.replace() chain would re-escape the "\"
        # introduced by an earlier replacement (e.g. "%" -> "\%" -> the
        # backslash then gets caught by a later "\\" -> "\\textbackslash{}"
        # rule). A single-pass char map must not do that.
        result = escape_latex("100% & $5")
        self.assertNotIn("textbackslash", result)
        self.assertEqual(result, r"100\% \& \$5")

    def test_plain_text_is_unchanged(self):
        self.assertEqual(escape_latex("React TypeScript"), "React TypeScript")

    def test_injected_command_like_text_is_neutralized(self):
        malicious = "\\input{/etc/passwd}"
        result = escape_latex(malicious)
        self.assertNotIn("\\input", result)


class RenderLatexTest(unittest.TestCase):
    def setUp(self):
        self.master = _load()

    def test_render_produces_complete_document(self):
        tailored, _ = tailor_resume(self.master, "React TypeScript")
        latex = render_latex(tailored)
        self.assertIn(r"\documentclass", latex)
        self.assertIn(r"\begin{document}", latex)
        self.assertIn(r"\end{document}", latex)
        self.assertIn("Test Candidate", latex)

    def test_no_unresolved_placeholder_tokens_remain(self):
        tailored, _ = tailor_resume(self.master, "React")
        latex = render_latex(tailored)
        self.assertNotIn("<<", latex)
        self.assertNotIn(">>", latex)

    def test_rendering_is_deterministic_for_the_same_input(self):
        tailored, _ = tailor_resume(self.master, "React TypeScript Python")
        self.assertEqual(render_latex(tailored), render_latex(tailored))

    def test_special_characters_in_bullet_text_are_escaped_in_output(self):
        payload = make_master_resume_dict()
        payload["experience"][0]["bullets"][0]["text"] = "Improved throughput by 50% & cut costs using C#"
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resume_master.json"
            path.write_text(json.dumps(payload))
            master = load_master_resume(path)

        tailored, _ = tailor_resume(master, "React")
        latex = render_latex(tailored)
        self.assertIn(r"50\%", latex)
        self.assertIn(r"\&", latex)


if __name__ == "__main__":
    unittest.main()
