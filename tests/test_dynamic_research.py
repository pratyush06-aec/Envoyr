"""Tests for Dynamic Research, LLM Diagnostics, and Self-Healing Verifier."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from envoyr.agent.provider import LLMClient
from envoyr.agent.researcher import AgentResearcher
from envoyr.executor import BaseAdapter, ExecutionResult
from envoyr.models import StepStatus, TaskState
from envoyr.storage import Storage
from envoyr.verifier import HealingDiagnosis, Verifier, diagnose_failure


class MockAdapterWithHealing(BaseAdapter):
    """Adapter that simulates an initial failure followed by success after remediation."""

    def __init__(self, failure_cmd: str, remediation_cmd: str):
        self.failure_cmd = failure_cmd
        self.remediation_cmd = remediation_cmd
        self.remediation_run = False
        self.history: list[str] = []

    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        self.history.append(command)
        if command == self.remediation_cmd:
            self.remediation_run = True
            return ExecutionResult(exit_code=0, stdout="Remediation applied", stderr="", duration_ms=10)
        if command == self.failure_cmd:
            if self.remediation_run:
                return ExecutionResult(exit_code=0, stdout="Success after healing", stderr="", duration_ms=10)
            return ExecutionResult(exit_code=1, stdout="", stderr="error: library libssl not found", duration_ms=10)
        return ExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=5)


class TestDynamicResearchAndSelfHealing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_dynamic.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dynamic_research_arbitrary_prompt(self):
        """Test synthesizing profile for an arbitrary language without pre-fed profile."""
        researcher = AgentResearcher(storage=self.storage)
        profile = researcher.research("Install Nim programming language and Choosenim", target_os="windows")

        self.assertIsNotNone(profile)
        self.assertIn("nim", profile.name.lower())
        self.assertTrue(len(profile.install_steps) > 0)
        self.assertTrue(len(profile.smoke_tests) > 0)

    def test_dynamic_research_llm_caching(self):
        """Test that LLM synthesis is parsed and saved to SQLite research_cache."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_configured = True
        mock_llm.generate_json.return_value = {
            "name": "Odin Language",
            "recommended_adapter": "local",
            "sources": ["https://odin-lang.org/docs/install/"],
            "compatibility_notes": "Native Windows zip package.",
            "prerequisites": [],
            "install_steps": [
                {"order": 0, "title": "Download Odin", "command": "curl -LO https://odin-lang.org/dist/odin.zip"},
                {"order": 1, "title": "Extract Odin", "command": "tar -xf odin.zip"},
            ],
            "smoke_tests": ["odin version"],
        }

        researcher = AgentResearcher(llm_client=mock_llm, storage=self.storage)
        profile = researcher.research("Setup Odin language compiler", target_os="windows")

        self.assertEqual(profile.name, "Odin Language")
        self.assertEqual(len(profile.install_steps), 2)
        self.assertEqual(profile.smoke_tests, ["odin version"])

        # Second call should fetch directly from SQLite cache without calling LLM
        mock_llm.generate_json.reset_mock()
        cached_profile = researcher.research("Setup Odin language compiler", target_os="windows")
        self.assertEqual(cached_profile.name, "Odin Language")
        mock_llm.generate_json.assert_not_called()

    def test_agent_diagnose_failure_with_mock_llm(self):
        """Test that AgentResearcher can diagnose complex failures with LLM reasoning."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_configured = True
        mock_llm.generate_json.return_value = {
            "failure_type": "MISSING_OPENSSL_HEADERS",
            "analysis": "The C compiler cannot locate OpenSSL development headers.",
            "suggested_fix": "Install libssl-dev or set OPENSSL_DIR.",
            "can_auto_heal": True,
            "remediation_command": "sudo apt-get install -y libssl-dev",
        }

        researcher = AgentResearcher(llm_client=mock_llm)
        diagnosis = researcher.diagnose_failure(
            command="cargo build --release",
            stderr="Could not find OpenSSL header files",
            stdout="",
        )

        self.assertIsNotNone(diagnosis)
        self.assertEqual(diagnosis.failure_type, "MISSING_OPENSSL_HEADERS")
        self.assertTrue(diagnosis.can_auto_heal)
        self.assertEqual(diagnosis.remediation_command, "sudo apt-get install -y libssl-dev")

    def test_verifier_self_healing_with_remediation(self):
        """Test Verifier executing remediation command and successfully auto-healing."""
        task = self.storage.create_task("setup crystal", target_os="linux", adapter="mock")
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)
        self.storage.transition_task(task.id, TaskState.EXECUTING)
        self.storage.transition_task(task.id, TaskState.VERIFYING)

        failed_cmd = "crystal --version"
        remediation_cmd = "sudo apt-get install -y libssl-dev"
        adapter = MockAdapterWithHealing(failure_cmd=failed_cmd, remediation_cmd=remediation_cmd)

        mock_researcher = MagicMock(spec=AgentResearcher)
        mock_researcher.diagnose_failure.return_value = HealingDiagnosis(
            failure_type="MISSING_LIBSSL",
            analysis="libssl shared object is missing.",
            suggested_fix="Install libssl package.",
            can_auto_heal=True,
            remediation_command=remediation_cmd,
        )

        verifier = Verifier(
            storage=self.storage,
            adapters={"mock": adapter},
            researcher=mock_researcher,
        )

        passed, results, diagnosis = verifier.verify_task(
            task_id=task.id,
            smoke_tests=[failed_cmd],
            max_healing_retries=1,
        )

        self.assertTrue(passed)
        self.assertTrue(adapter.remediation_run)
        self.assertIn(remediation_cmd, adapter.history)
        task_reloaded = self.storage.get_task(task.id)
        self.assertEqual(task_reloaded.state, TaskState.COMPLETED)
        transitions = self.storage.get_transitions(task.id)
        self.assertIn("self-healing", transitions[-1].reason)

    def test_normalize_wsl_command(self):
        from envoyr.executor import normalize_wsl_command

        self.assertEqual(normalize_wsl_command("wsl -d Ubuntu"), "uname -a && whoami")
        self.assertEqual(normalize_wsl_command("wsl.exe -d Ubuntu"), "uname -a && whoami")
        self.assertEqual(normalize_wsl_command("wsl"), "uname -a && whoami")
        self.assertEqual(normalize_wsl_command("wsl.exe"), "uname -a && whoami")
        self.assertEqual(normalize_wsl_command("wsl ~"), "uname -a && whoami")
        self.assertEqual(normalize_wsl_command("wsl sudo apt update"), "sudo apt update")
        self.assertEqual(normalize_wsl_command("wsl -d Ubuntu sudo apt update"), "sudo apt update")
        self.assertEqual(normalize_wsl_command("sudo apt-get update -y"), "sudo apt-get update -y")
        self.assertEqual(normalize_wsl_command("curl -fsSL https://get.modular.com | sh -"), "curl -fsSL https://get.modular.com | sh -")

    def test_execution_engine_self_healing_during_step_execution(self):
        from envoyr.executor import ExecutionEngine
        from envoyr.models import Step

        task = self.storage.create_task("setup wsl tool", target_os="windows", adapter="mock")
        step1 = Step(
            id=f"{task.id}-step-1",
            task_id=task.id,
            order_idx=0,
            title="Install package",
            command="install-pkg",
            adapter="mock",
        )
        self.storage.add_steps(task.id, [step1])
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)

        adapter = MockAdapterWithHealing(failure_cmd="install-pkg", remediation_cmd="fix-env")
        mock_researcher = MagicMock(spec=AgentResearcher)
        mock_researcher.diagnose_failure.return_value = HealingDiagnosis(
            failure_type="ENV_ERROR",
            analysis="Environment missing package configuration.",
            suggested_fix="Run fix-env script.",
            can_auto_heal=True,
            remediation_command="fix-env",
            non_technical_summary="Setup environment needs initialization.",
        )

        engine = ExecutionEngine(
            storage=self.storage,
            adapters={"mock": adapter},
            researcher=mock_researcher,
            max_healing_retries=1,
        )
        updated_task = engine.run_task(task.id)

        self.assertEqual(updated_task.state, TaskState.VERIFYING)
        self.assertTrue(adapter.remediation_run)
        step_reloaded = self.storage.get_task(task.id).steps[0]
        self.assertEqual(step_reloaded.status, StepStatus.SUCCESS)

    def test_wsl_diagnose_failure_and_non_technical_summary(self):
        diag = diagnose_failure("wsl -d Ubuntu", "bash: line 1: wsl: command not found", "")
        self.assertEqual(diag.failure_type, "WSL_COMMAND_IN_LINUX")
        self.assertTrue(diag.can_auto_heal)
        self.assertEqual(diag.display_category, "Environment Configuration (WSL)")
        self.assertIn("Linux environment", diag.display_summary)
        self.assertIsNotNone(diag.remediation_command)

        # Test CLI non-technical diagnostic printer
        import io
        from contextlib import redirect_stderr
        from envoyr.cli import print_non_technical_diagnostic

        f = io.StringIO()
        with redirect_stderr(f):
            print_non_technical_diagnostic(diag)
        output = f.getvalue()
        self.assertIn("[Envoyr AI Diagnostic Report]", output)
        self.assertIn("Environment Configuration (WSL)", output)
        self.assertIn("Guidance:", output)


if __name__ == "__main__":
    unittest.main()
