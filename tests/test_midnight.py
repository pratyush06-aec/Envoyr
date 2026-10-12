"""End-to-End orchestration tests for Phase 8: Midnight Toolchain Profile."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envoyr.cli import main
from envoyr.executor import ExecutionEngine, RemoteAdapter
from envoyr.integrations import EconomicsCalculator
from envoyr.models import TaskState
from envoyr.research import research_toolchain
from envoyr.storage import Storage
from envoyr.verifier import Verifier, diagnose_failure


class TestMidnightEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_midnight.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_midnight_research_profile_derivation(self):
        profile = research_toolchain("Configure Midnight on Windows", target_os="windows")
        self.assertEqual(profile.name, "Midnight Network Toolchain")
        self.assertEqual(profile.recommended_adapter, "remote")
        self.assertTrue(any("compact" in s.lower() for s in profile.sources))

        # Validate prerequisites include Rust 1.80+ and Compact compiler 0.2.1+
        prereqs = {p.name: p for p in profile.prerequisites}
        self.assertIn("rust", prereqs)
        self.assertEqual(prereqs["rust"].min_version, "1.80.0")
        self.assertIn("compact", prereqs)
        self.assertEqual(prereqs["compact"].min_version, "0.2.1")

        # Smoke tests must include compact compiler checks
        self.assertIn("compact --version", profile.smoke_tests)
        self.assertIn("compact --help", profile.smoke_tests)

    def test_midnight_end_to_end_cli_lifecycle(self):
        # 1. Setup Midnight on Windows via CLI
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main([
                "--db-path", str(self.db_path),
                "setup", "Configure Midnight development environment on Windows",
                "--no-prompt",
            ])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Researching official documentation", output)
            self.assertIn("Selected execution path: REMOTE adapter", output)
            self.assertIn("Task state is now PLANNED", output)

        tasks = self.storage.list_tasks()
        self.assertEqual(len(tasks), 1)
        task_id = tasks[0].id
        task = self.storage.get_task(task_id)
        self.assertEqual(task.state, TaskState.PLANNED)
        self.assertEqual(task.adapter, "remote")
        self.assertEqual(len(task.steps), 5)

        # 2. Plan Inspection
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "plan", task_id])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Install Midnight Compact CLI", output)
            self.assertIn("Plan policy check: PASSED", output)

        # 3. Human Approval Gate
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "approve", task_id])
            self.assertEqual(ret, 0)
            self.assertIn("approved for execution", out.getvalue())

        task = self.storage.get_task(task_id)
        self.assertEqual(task.state, TaskState.APPROVED)

        # 4. Execution & Verification via Remote Runner
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "run", task_id])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Executing 5 step(s)", output)
            self.assertIn("Running verification smoke tests", output)
            self.assertIn("compact --version", output)
            self.assertIn("All verification tests passed", output)
            self.assertIn("[Economics]", output)

        task = self.storage.get_task(task_id)
        self.assertEqual(task.state, TaskState.COMPLETED)
        for s in task.steps:
            self.assertEqual(s.status.value, "SUCCESS")

        # 5. Economics Modeling (CFO.ai)
        econ = EconomicsCalculator.calculate_cost(task)
        self.assertEqual(econ.adapter, "remote")
        self.assertGreaterEqual(econ.estimated_cost_usd, 0.0)

    def test_midnight_compilation_failure_diagnosis(self):
        diagnosis = diagnose_failure(
            "compact compile contract.compact",
            stderr="Error: could not compile contract due to syntax error in declaration",
            stdout="",
        )
        self.assertEqual(diagnosis.failure_type, "COMPILATION_ERROR")
        self.assertFalse(diagnosis.can_auto_heal)
        self.assertIn("syntax", diagnosis.suggested_fix)

    def test_cli_demo_command(self):
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "demo"])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Envoyr — End-to-End Environment Orchestrator Demo", output)
            self.assertIn("Selected execution path: REMOTE adapter", output)
            self.assertIn("Executing 5 step(s)", output)
            self.assertIn("compact --version", output)
            self.assertIn("Success! Environment ready.", output)
            self.assertIn("[Economics]", output)


if __name__ == "__main__":
    unittest.main()

