"""Configuration validation tests."""

import json
import tempfile
import unittest
from pathlib import Path

from app.config import ConfigError, load_sources

VALID = [
    {"type": "greenhouse", "company": "Adobe", "identifier": "adobe"},
    {"type": "ashby", "company": "Example Startup", "identifier": "example"},
    {"type": "lever", "company": "Example Labs", "identifier": "example"},
]


class LoadSourcesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def write_config(self, payload) -> Path:
        path = self.tmp_path / "sources.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
        )
        return path

    def test_loads_valid_sources(self):
        sources = load_sources(self.write_config(VALID))

        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[0].type, "greenhouse")
        self.assertEqual(sources[0].company, "Adobe")
        self.assertEqual(sources[0].identifier, "adobe")

    def test_example_config_file_is_valid(self):
        example = Path(__file__).resolve().parents[1] / "config" / "sources.example.json"

        self.assertEqual(len(load_sources(example)), 3)

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.tmp_path / "nope.json")

        self.assertIn("not found", str(ctx.exception))

    def test_invalid_json(self):
        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config("{not json"))

        self.assertIn("not valid JSON", str(ctx.exception))

    def test_top_level_must_be_a_list(self):
        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config({"type": "greenhouse"}))

        self.assertIn("JSON list", str(ctx.exception))

    def test_empty_list(self):
        with self.assertRaises(ConfigError):
            load_sources(self.write_config([]))

    def test_unsupported_source_type(self):
        payload = [{"type": "workday", "company": "Adobe", "identifier": "adobe"}]

        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config(payload))

        self.assertIn("unsupported source type", str(ctx.exception))
        self.assertIn("greenhouse", str(ctx.exception))

    def test_empty_company(self):
        payload = [{"type": "greenhouse", "company": "  ", "identifier": "adobe"}]

        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config(payload))

        self.assertIn("'company' is required", str(ctx.exception))

    def test_empty_identifier(self):
        payload = [{"type": "greenhouse", "company": "Adobe", "identifier": ""}]

        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config(payload))

        self.assertIn("'identifier' is required", str(ctx.exception))

    def test_duplicate_identifier_for_same_source(self):
        payload = [
            {"type": "greenhouse", "company": "Adobe", "identifier": "adobe"},
            {"type": "greenhouse", "company": "Adobe Systems", "identifier": "Adobe"},
        ]

        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config(payload))

        self.assertIn("duplicate source", str(ctx.exception))

    def test_duplicate_company_for_same_source(self):
        payload = [
            {"type": "greenhouse", "company": "Adobe", "identifier": "adobe"},
            {"type": "greenhouse", "company": "adobe", "identifier": "adobe-labs"},
        ]

        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config(payload))

        self.assertIn("already", str(ctx.exception))

    def test_same_identifier_on_different_sources_is_allowed(self):
        payload = [
            {"type": "ashby", "company": "Example Startup", "identifier": "example"},
            {"type": "lever", "company": "Example Labs", "identifier": "example"},
        ]

        self.assertEqual(len(load_sources(self.write_config(payload))), 2)

    def test_entry_must_be_an_object(self):
        with self.assertRaises(ConfigError) as ctx:
            load_sources(self.write_config(["greenhouse"]))

        self.assertIn("JSON object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
