import tempfile
import unittest
from pathlib import Path

from envoyr.cli import main
from envoyr.executor import (
    BaseAdapter,
    ExecutionEngine,
    ExecutionResult,
    LocalAdapter,
    RemoteAdapter,
    WSLAdapter,
    get_adapter,
)
from envoyr.models import Step, StepStatus, TaskState
from envoyr.storage import Storage


class MockAdapter(BaseAdapter):
    def __init__(self, should_fail: bool = False, exit_code: int = 1, error_msg: str = "Mock error"):
        self.should_fail = should_fail
        self.exit_code = exit_code
        self.error_msg = error_msg
        self.executed_commands: list[str] = []

    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        self.executed_commands.append(command)
        if self.should_fail:
            return ExecutionResult(
                exit_code=self.exit_code,
                stdout="",
                stderr=self.error_msg,
                duration_ms=10,
            )
        return ExecutionResult(
            exit_code=0,
            stdout=f"mocked: {command}",
            stderr="",
            duration_ms=15,
        )


class TestExecutionEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_executor.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_local_adapter_success_and_failure(self):
        adapter = LocalAdapter()
        # Safe echo command
        res = adapter.execute("python -c \"print('hello envoyr')\"", timeout=10)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("hello envoyr", res.stdout)
        self.assertFalse(res.timed_out)

        # Failing command
        res_fail = adapter.execute("python -c \"import sys; sys.exit(42)\"", timeout=10)
        self.assertEqual(res_fail.exit_code, 42)

    def test_local_adapter_timeout(self):
        adapter = LocalAdapter()
        res = adapter.execute("python -c \"import time; time.sleep(5)\"", timeout=1)
        self.assertEqual(res.exit_code, -1)
        self.assertTrue(res.timed_out)
        self.assertIn("timed out", res.stderr.lower())

    def test_remote_adapter(self):
        adapter = RemoteAdapter(endpoint="mock://test-vm")
        res = adapter.execute("cargo install envoyr", timeout=30)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("mock://test-vm", res.stdout)

    def test_get_adapter_lookup(self):
        self.assertIsInstance(get_adapter("local"), LocalAdapter)
        self.assertIsInstance(get_adapter("remote"), RemoteAdapter)
        with self.assertRaises(ValueError):
            get_adapter("nonexistent-adapter")

    def test_execution_engine_sequential_success(self):
        task = self.storage.create_task("setup dev", target_os="windows", adapter="mock")
        steps = [
            Step(id="s1", task_id=task.id, order_idx=0, title="Step 1", command="cmd 1", adapter="mock"),
            Step(id="s2", task_id=task.id, order_idx=1, title="Step 2", command="cmd 2", adapter="mock"),
        ]
        self.storage.add_steps(task.id, steps)
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)

        mock_adapter = MockAdapter()
        engine = ExecutionEngine(self.storage, adapters={"mock": mock_adapter})
        updated = engine.run_task(task.id)

        self.assertEqual(updated.state, TaskState.VERIFYING)
        self.assertEqual(len(mock_adapter.executed_commands), 2)

        # Check step status in DB
        reloaded = self.storage.get_task(task.id)
        for s in reloaded.steps:
            self.assertEqual(s.status, StepStatus.SUCCESS)
            self.assertEqual(s.exit_code, 0)
            self.assertIn("mocked: cmd", s.stdout)

    def test_execution_engine_fail_fast(self):
        task = self.storage.create_task("setup fail", target_os="windows", adapter="mock")
        steps = [
            Step(id="s1", task_id=task.id, order_idx=0, title="Step 1", command="fail cmd", adapter="mock"),
            Step(id="s2", task_id=task.id, order_idx=1, title="Step 2", command="never run", adapter="mock"),
        ]
        self.storage.add_steps(task.id, steps)
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)

        mock_adapter = MockAdapter(should_fail=True, exit_code=2, error_msg="Step crashed")
        engine = ExecutionEngine(self.storage, adapters={"mock": mock_adapter})
        updated = engine.run_task(task.id)

        self.assertEqual(updated.state, TaskState.FAILED)
        self.assertEqual(len(mock_adapter.executed_commands), 1)

        reloaded = self.storage.get_task(task.id)
        self.assertEqual(reloaded.steps[0].status, StepStatus.FAILED)
        self.assertEqual(reloaded.steps[1].status, StepStatus.PENDING)

    def test_cli_run_command(self):
        task = self.storage.create_task("setup local", target_os="windows", adapter="local")
        steps = [
            Step(id="s1", task_id=task.id, order_idx=0, title="Echo", command="python -c \"print('ok')\"", adapter="local"),
        ]
        self.storage.add_steps(task.id, steps)
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)
        self.storage.transition_task(task.id, TaskState.APPROVED)

        ret = main(["--db-path", str(self.db_path), "run", task.id])
        self.assertEqual(ret, 0)

        task_after = self.storage.get_task(task.id)
        self.assertEqual(task_after.state, TaskState.VERIFYING)


if __name__ == "__main__":
    unittest.main()
