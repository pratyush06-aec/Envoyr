import tempfile
import unittest
from pathlib import Path

from envoyr.cli import main
from envoyr.models import Step, StepStatus, TaskState
from envoyr.planner import (
    RiskLevel,
    assess_command_risk,
    format_plan_inspection,
    topological_sort_steps,
    validate_plan_safety,
)
from envoyr.storage import Storage


class TestPlannerAndPolicyGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_planner.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_risk_level_assessment(self):
        self.assertEqual(assess_command_risk("rm -rf /"), RiskLevel.BLOCKED)
        self.assertEqual(assess_command_risk("rm -rf /*"), RiskLevel.BLOCKED)
        self.assertEqual(assess_command_risk("mkfs.ext4 /dev/sda1"), RiskLevel.BLOCKED)
        self.assertEqual(assess_command_risk("dd if=/dev/zero of=/dev/sda"), RiskLevel.BLOCKED)

        self.assertEqual(assess_command_risk("echo hello"), RiskLevel.SAFE)
        self.assertEqual(assess_command_risk("cargo --version"), RiskLevel.SAFE)
        self.assertEqual(assess_command_risk("which docker"), RiskLevel.SAFE)

        self.assertEqual(assess_command_risk("sudo apt-get install curl"), RiskLevel.CRITICAL)
        self.assertEqual(assess_command_risk("chmod 777 /var/run"), RiskLevel.CRITICAL)

        self.assertEqual(assess_command_risk("cargo install midnight-cli"), RiskLevel.MODIFY)

    def test_plan_safety_validation(self):
        safe_steps = [
            Step(id="1", task_id="t1", order_idx=0, title="Check", command="echo 1", adapter="local"),
            Step(id="2", task_id="t1", order_idx=1, title="Build", command="cargo build", adapter="local"),
        ]
        is_safe, err = validate_plan_safety(safe_steps)
        self.assertTrue(is_safe)
        self.assertIsNone(err)

        unsafe_steps = [
            Step(id="1", task_id="t1", order_idx=0, title="Check", command="echo 1", adapter="local"),
            Step(id="2", task_id="t1", order_idx=1, title="Delete", command="rm -rf /", adapter="local"),
        ]
        is_safe, err = validate_plan_safety(unsafe_steps)
        self.assertFalse(is_safe)
        self.assertIn("blocked", err.lower())

    def test_topological_sort_steps(self):
        steps = [
            {"id": "2", "order": 2, "title": "Step 2"},
            {"id": "1", "order": 1, "title": "Step 1"},
            {"id": "0", "order": 0, "title": "Step 0"},
        ]
        sorted_steps = topological_sort_steps(steps)
        self.assertEqual([s["order"] for s in sorted_steps], [0, 1, 2])

    def test_format_plan_inspection(self):
        steps = [
            Step(id="1", task_id="t-1", order_idx=0, title="Install tool", command="cargo install tool", adapter="local"),
        ]
        text = format_plan_inspection("t-1", steps)
        self.assertIn("Execution Plan Inspection for Task: t-1", text)
        self.assertIn("Step 1: Install tool", text)
        self.assertIn("[MODIFY]", text)

    def test_cli_plan_command(self):
        task = self.storage.create_task("setup rust", target_os="windows", adapter="local")
        self.storage.add_steps(
            task.id,
            [Step(id="s1", task_id=task.id, order_idx=0, title="Ver", command="cargo --version", adapter="local")],
        )
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)

        ret = main(["--db-path", str(self.db_path), "plan", task.id])
        self.assertEqual(ret, 0)

    def test_cli_approve_and_reject_commands(self):
        # 1. Test approve
        task = self.storage.create_task("setup rust", target_os="windows", adapter="local")
        self.storage.add_steps(
            task.id,
            [Step(id="s1", task_id=task.id, order_idx=0, title="Ver", command="cargo --version", adapter="local")],
        )
        self.storage.transition_task(task.id, TaskState.RESEARCHING)
        self.storage.transition_task(task.id, TaskState.PLANNED)

        ret = main(["--db-path", str(self.db_path), "approve", task.id])
        self.assertEqual(ret, 0)
        task_approved = self.storage.get_task(task.id)
        self.assertEqual(task_approved.state, TaskState.APPROVED)

        # 2. Test reject
        task2 = self.storage.create_task("setup go", target_os="windows", adapter="local")
        self.storage.transition_task(task2.id, TaskState.RESEARCHING)
        self.storage.transition_task(task2.id, TaskState.PLANNED)

        ret = main(["--db-path", str(self.db_path), "reject", task2.id, "--reason", "Not needed anymore"])
        self.assertEqual(ret, 0)
        task2_rejected = self.storage.get_task(task2.id)
        self.assertEqual(task2_rejected.state, TaskState.CANCELLED)

    def test_cli_setup_with_auto_approve_flag(self):
        ret = main(["--db-path", str(self.db_path), "setup", "rust", "--yes"])
        self.assertEqual(ret, 0)
        tasks = self.storage.list_tasks(limit=1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].state, TaskState.APPROVED)


if __name__ == "__main__":
    unittest.main()
