"""Unit tests for Envoyr task contracts, SQLite persistence, and CLI."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envoyr.cli import main
from envoyr.models import Step, StepStatus, TaskState
from envoyr.storage import Storage


class TestEnvoyrTaskEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tasks.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_get_task(self):
        task = self.storage.create_task(
            intent="Configure Midnight development environment on Windows",
            target_os="windows",
            adapter="remote",
        )
        self.assertIsNotNone(task.id)
        self.assertEqual(task.state, TaskState.PENDING)
        self.assertEqual(task.target_os, "windows")
        self.assertEqual(task.adapter, "remote")

        fetched = self.storage.get_task(task.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, task.id)
        self.assertEqual(fetched.intent, task.intent)
        self.assertEqual(fetched.state, TaskState.PENDING)

    def test_valid_state_transitions(self):
        task = self.storage.create_task(intent="Test transitions")
        tid = task.id

        # PENDING -> RESEARCHING
        self.storage.transition_task(tid, TaskState.RESEARCHING, reason="Start doc lookup")
        self.assertEqual(self.storage.get_task(tid).state, TaskState.RESEARCHING)

        # RESEARCHING -> PLANNED
        self.storage.transition_task(tid, TaskState.PLANNED, reason="Plan generated")
        self.assertEqual(self.storage.get_task(tid).state, TaskState.PLANNED)

        # PLANNED -> APPROVED
        self.storage.transition_task(tid, TaskState.APPROVED, reason="Human approved")
        self.assertEqual(self.storage.get_task(tid).state, TaskState.APPROVED)

        # APPROVED -> EXECUTING
        self.storage.transition_task(tid, TaskState.EXECUTING, reason="Execution dispatched")
        self.assertEqual(self.storage.get_task(tid).state, TaskState.EXECUTING)

        # EXECUTING -> VERIFYING
        self.storage.transition_task(tid, TaskState.VERIFYING, reason="Execution complete")
        self.assertEqual(self.storage.get_task(tid).state, TaskState.VERIFYING)

        # VERIFYING -> COMPLETED
        self.storage.transition_task(tid, TaskState.COMPLETED, reason="Smoke tests passed")
        self.assertEqual(self.storage.get_task(tid).state, TaskState.COMPLETED)

        # Verify audit history
        history = self.storage.get_transitions(tid)
        self.assertEqual(len(history), 7)  # 1 initial + 6 transitions
        self.assertEqual(history[-1].to_state, TaskState.COMPLETED.value)

    def test_invalid_state_transition_raises_value_error(self):
        task = self.storage.create_task(intent="Test invalid transition")
        tid = task.id

        # Direct jump from PENDING to COMPLETED is forbidden
        with self.assertRaises(ValueError) as ctx:
            self.storage.transition_task(tid, TaskState.COMPLETED)
        self.assertIn("Invalid transition from PENDING to COMPLETED", str(ctx.exception))

    def test_completed_state_is_terminal(self):
        task = self.storage.create_task(intent="Terminal state test")
        tid = task.id
        self.storage.transition_task(tid, TaskState.RESEARCHING)
        self.storage.transition_task(tid, TaskState.PLANNED)
        self.storage.transition_task(tid, TaskState.APPROVED)
        self.storage.transition_task(tid, TaskState.EXECUTING)
        self.storage.transition_task(tid, TaskState.VERIFYING)
        self.storage.transition_task(tid, TaskState.COMPLETED)

        with self.assertRaises(ValueError):
            self.storage.transition_task(tid, TaskState.EXECUTING)

    def test_steps_persistence_and_update(self):
        task = self.storage.create_task(intent="Step execution test")
        step1 = Step(
            id="s1",
            task_id=task.id,
            order_idx=0,
            title="Install Compact CLI",
            command="cargo install compact",
            adapter="remote",
        )
        self.storage.add_steps(task.id, [step1])

        t = self.storage.get_task(task.id)
        self.assertEqual(len(t.steps), 1)
        self.assertEqual(t.steps[0].status, StepStatus.PENDING)

        self.storage.update_step(
            step_id="s1",
            status=StepStatus.SUCCESS,
            exit_code=0,
            stdout="Installed compact 0.2.1",
            duration_ms=1420,
        )

        t_updated = self.storage.get_task(task.id)
        self.assertEqual(t_updated.steps[0].status, StepStatus.SUCCESS)
        self.assertEqual(t_updated.steps[0].exit_code, 0)
        self.assertEqual(t_updated.steps[0].stdout, "Installed compact 0.2.1")
        self.assertEqual(t_updated.steps[0].duration_ms, 1420)

    def test_cli_lifecycle(self):
        db_arg = f"--db-path={self.db_path}"

        # 1. Setup
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "setup", "Install Rust and Compact"])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Envoyr initialized task:", output)

        tasks = self.storage.list_tasks()
        self.assertEqual(len(tasks), 1)
        tid = tasks[0].id

        # 2. List
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "list"])
            self.assertEqual(ret, 0)
            self.assertIn(tid, out.getvalue())

        # 3. Status
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "status", tid])
            self.assertEqual(ret, 0)
            self.assertIn("PENDING", out.getvalue())

        # 4. Transition
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(
                ["--db-path", str(self.db_path), "transition", tid, "RESEARCHING", "--reason", "cli test"]
            )
            self.assertEqual(ret, 0)
            self.assertIn("transitioned to RESEARCHING", out.getvalue())

        # 5. History
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["--db-path", str(self.db_path), "history", tid])
            self.assertEqual(ret, 0)
            self.assertIn("PENDING -> RESEARCHING", out.getvalue())


if __name__ == "__main__":
    unittest.main()
