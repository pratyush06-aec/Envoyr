"""Unit tests for Envoyr Dynamic LLM Agent & Research Engine."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from envoyr.agent.heuristic import synthesize_heuristic_profile
from envoyr.agent.provider import LLMClient
from envoyr.agent.researcher import AgentResearcher
from envoyr.cli import main
from envoyr.models import TaskState
from envoyr.storage import Storage


class TestLLMClient(unittest.TestCase):
    def test_unconfigured_state(self):
        client = LLMClient(gemini_api_key="", openai_api_key="")
        self.assertFalse(client.is_configured)
        self.assertEqual(client.provider_name, "none")
        with self.assertRaises(RuntimeError):
            client.generate("test prompt")

    def test_provider_name_detection(self):
        c1 = LLMClient(gemini_api_key="test_gemini_key")
        self.assertTrue(c1.is_configured)
        self.assertEqual(c1.provider_name, "gemini")

        c2 = LLMClient(gemini_api_key="", openai_api_key="test_openai_key")
        self.assertTrue(c2.is_configured)
        self.assertEqual(c2.provider_name, "openai")

        c3 = LLMClient(groq_api_key="gsk_mock_key")
        self.assertTrue(c3.is_configured)
        self.assertEqual(c3.provider_name, "groq")
        self.assertEqual(c3.groq_base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(c3.groq_model, "llama-3.3-70b-versatile")

    def test_json_extraction_from_markdown_fences(self):
        fenced = "```json\n{\"name\": \"TestTool\", \"steps\": [1, 2]}\n```"
        extracted = LLMClient._extract_json(fenced)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["name"], "TestTool")

        raw = "Some introductory text {\"status\": \"ok\"} trailing text"
        extracted_raw = LLMClient._extract_json(raw)
        self.assertIsNotNone(extracted_raw)
        self.assertEqual(extracted_raw["status"], "ok")

        invalid = "no json here"
        self.assertIsNone(LLMClient._extract_json(invalid))


class TestAgentResearcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_agent.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_heuristic_fallback_for_bun(self):
        profile = synthesize_heuristic_profile("Install Bun runtime on Windows", target_os="windows")
        self.assertEqual(profile.name, "Bun Runtime")
        self.assertEqual(profile.recommended_adapter, "local")
        self.assertIn("bun --version", profile.smoke_tests)

    def test_heuristic_fallback_for_zig(self):
        profile = synthesize_heuristic_profile("Configure Zig compiler", target_os="windows")
        self.assertEqual(profile.name, "Zig Compiler & Toolchain")
        self.assertIn("zig version", profile.smoke_tests)

    def test_heuristic_fallback_for_custom_unknown_tool(self):
        profile = synthesize_heuristic_profile("Setup Mojo programming language", target_os="windows")
        self.assertIn("Mojo", profile.name)
        self.assertEqual(len(profile.install_steps), 1)
        self.assertIn("mojo --version", profile.smoke_tests)

    def test_researcher_with_mocked_llm(self):
        mock_client = MagicMock(spec=LLMClient)
        mock_client.is_configured = True
        mock_client.generate_json.return_value = {
            "name": "Custom Dynamic Toolchain",
            "recommended_adapter": "remote",
            "sources": ["https://example.com/docs"],
            "compatibility_notes": "Requires isolated remote worker.",
            "prerequisites": [{"name": "tool_dep", "description": "dep desc"}],
            "install_steps": [
                {"order": 0, "title": "Run installer", "command": "curl -sL https://example.com | sh"}
            ],
            "smoke_tests": ["custom-tool --version"],
        }

        researcher = AgentResearcher(llm_client=mock_client, storage=self.storage)
        profile = researcher.research("Setup Custom Dynamic Toolchain on Windows", target_os="windows")

        self.assertEqual(profile.name, "Custom Dynamic Toolchain")
        self.assertEqual(profile.recommended_adapter, "remote")
        self.assertEqual(len(profile.install_steps), 1)
        self.assertIn("custom-tool --version", profile.smoke_tests)

        # Verify profile was cached in storage
        cached = self.storage.get_cached_profile("Setup Custom Dynamic Toolchain on Windows", "windows")
        self.assertIsNotNone(cached)
        self.assertIn("Custom Dynamic Toolchain", cached)

    def test_cli_prompt_shorthand_routing(self):
        # Verify user can run: envoyr "Install Bun runtime" -y
        # without explicit 'setup' subcommand
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main([
                "Install Bun runtime",
                "--db-path", str(self.db_path),
                "-y",
                "--no-prompt",
            ])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Researching official documentation", output)
            self.assertIn("Bun", output)
            self.assertIn("automatically approved", output)

        tasks = self.storage.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].state, TaskState.APPROVED)


if __name__ == "__main__":
    unittest.main()
