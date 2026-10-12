import tempfile
import unittest
from pathlib import Path

from envoyr.cli import main
from envoyr.executor import BaseAdapter, ExecutionResult
from envoyr.models import Step, StepStatus, TaskState
from envoyr.storage import Storage
from envoyr.verifier import Verifier, diagnose_failure


class MockVerifierAdapter(BaseAdapter):
    def __init__(self, responses: dict[str, ExecutionResult]):
        self.responses = responses
        self.call_counts: dict[str, int] = {}

    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        self.call_counts[command] = self.call_counts.get(command, 0) + 1
        if command in self.responses:
            return self.responses[command]
        return ExecutionResult(exit_code=0, stdout="mock ok", stderr="", duration_ms=5)


class TestVerifierEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_verifier.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_diagnose_failure_patterns(self):
        d1 = diagnose_failure("rustc", "rustc: command not found", "")
        self.assertEqual(d1.failure_type, "PATH_OR_BINARY_MISSING")
        self.assertFalse(d1.can_auto_heal)

        d2 = diagnose_failure("docker", "'docker' is not recognized as an internal or external command", "")
        self.assertEqual(d2.failure_type, "PATH_OR_BINARY_MISSING")

        d3 = diagnose_failure("curl", "Permission denied", "")
        self.assertEqual(d3.failure_type, "PERMISSION_DENIED")

        d4 = diagnose_failure("curl", "Connection timed out", "")
        self.assertEqual(d4.failure_type, "NETWORK_TRANSIENT")
        self.assertTrue(d4.can_auto_heal)

    def test_verification_success_transitions_to_completed(self):
        task = self.storage.create_task("setup dev", target_os="windows", adapter="mock")
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)
        self.storage.transition_task(task.id, TaskState.EXECUTING)
        self.storage.transition_task(task.id, TaskState.VERIFYING)

        adapter = MockVerifierAdapter({
            "rustc --version": ExecutionResult(0, "rustc 1.85.0", "", 10),
            "cargo --version": ExecutionResult(0, "cargo 1.85.0", "", 10),
        })
        verifier = Verifier(self.storage, adapters={"mock": adapter})
        passed, results, diagnosis = verifier.verify_task(
            task.id, smoke_tests=["rustc --version", "cargo --version"]
        )

        self.assertTrue(passed)
        self.assertEqual(len(results), 2)
        self.assertIsNone(diagnosis)

        task_reloaded = self.storage.get_task(task.id)
        self.assertEqual(task_reloaded.state, TaskState.COMPLETED)

    def test_verification_failure_with_diagnostics(self):
        task = self.storage.create_task("setup dev", target_os="windows", adapter="mock")
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)
        self.storage.transition_task(task.id, TaskState.EXECUTING)
        self.storage.transition_task(task.id, TaskState.VERIFYING)

        adapter = MockVerifierAdapter({
            "rustc --version": ExecutionResult(1, "", "rustc: command not found", 10),
        })
        verifier = Verifier(self.storage, adapters={"mock": adapter})
        passed, results, diagnosis = verifier.verify_task(
            task.id, smoke_tests=["rustc --version"], max_healing_retries=0
        )

        self.assertFalse(passed)
        self.assertIsNotNone(diagnosis)
        self.assertEqual(diagnosis.failure_type, "PATH_OR_BINARY_MISSING")

        task_reloaded = self.storage.get_task(task.id)
        self.assertEqual(task_reloaded.state, TaskState.FAILED)
        self.assertIn("PATH", task_reloaded.error_message)

    def test_cli_verify_command(self):
        task = self.storage.create_task("setup rust", target_os="windows", adapter="local")
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)
        self.storage.transition_task(task.id, TaskState.EXECUTING)
        self.storage.transition_task(task.id, TaskState.VERIFYING)

        # Smoke tests against python (which is guaranteed installed on host)
        verifier = Verifier(self.storage)
        passed, _, _ = verifier.verify_task(task.id, smoke_tests=["python --version"])
        self.assertTrue(passed)

        task_after = self.storage.get_task(task.id)
        self.assertEqual(task_after.state, TaskState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
