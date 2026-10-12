import unittest
from envoyr.cli import _format_task_summary
from envoyr.integrations import EconomicsCalculator, NeatlogsTracer
from envoyr.models import Step, StepStatus, Task, TaskState


class TestIntegrations(unittest.TestCase):
    def test_neatlogs_tracer_graceful_offline(self):
        tracer = NeatlogsTracer(api_key=None, endpoint=None)
        res = tracer.record_event("test_event", "task-1", {"status": "ok"})
        self.assertFalse(res)

    def test_economics_calculator_local(self):
        task = Task(
            id="task-local",
            intent="setup rust",
            adapter="local",
            steps=[
                Step("s1", "task-local", 0, "S1", "cmd 1", "local", StepStatus.SUCCESS, duration_ms=2000),
                Step("s2", "task-local", 1, "S2", "cmd 2", "local", StepStatus.SUCCESS, duration_ms=3000),
            ],
        )
        report = EconomicsCalculator.calculate_cost(task)
        self.assertEqual(report.duration_ms, 5000)
        self.assertEqual(report.estimated_cost_usd, 0.0)
        self.assertGreater(report.cost_saved_usd, 0.0)
        self.assertIn("Compute: $0.00000", report.summary)

    def test_economics_calculator_remote(self):
        task = Task(
            id="task-remote",
            intent="setup midnight",
            adapter="remote",
            steps=[
                Step("s1", "task-remote", 0, "S1", "cmd 1", "remote", StepStatus.SUCCESS, duration_ms=10000),
            ],
        )
        report = EconomicsCalculator.calculate_cost(task)
        self.assertEqual(report.duration_ms, 10000)
        self.assertGreater(report.estimated_cost_usd, 0.0)
        self.assertIn("Compute: $", report.summary)

    def test_task_summary_displays_economics(self):
        task = Task(
            id="task-summary-test",
            intent="setup rust",
            state=TaskState.COMPLETED,
            adapter="local",
            steps=[
                Step("s1", "task-summary-test", 0, "S1", "cmd 1", "local", StepStatus.SUCCESS, duration_ms=1500),
            ],
        )
        text = _format_task_summary(task)
        self.assertIn("Economics: Compute: $0.00000", text)

    def test_load_env_file_parses_variables(self):
        import os
        import tempfile
        from pathlib import Path
        from envoyr.cli import load_env_file

        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".env") as f:
            f.write("# Sample comment\nTEST_EXTRACTED_SECRET=\"secret_value_123\"\nANOTHER_KEY=plain_val\n")
            f_path = Path(f.name)

        try:
            load_env_file(f_path)
            self.assertEqual(os.environ.get("TEST_EXTRACTED_SECRET"), "secret_value_123")
            self.assertEqual(os.environ.get("ANOTHER_KEY"), "plain_val")
        finally:
            if f_path.exists():
                f_path.unlink()
            os.environ.pop("TEST_EXTRACTED_SECRET", None)
            os.environ.pop("ANOTHER_KEY", None)


if __name__ == "__main__":
    unittest.main()
