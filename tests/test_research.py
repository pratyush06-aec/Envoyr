"""Unit tests for Envoyr Documentation Research Engine."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envoyr.cli import main
from envoyr.models import TaskState
from envoyr.research import research_toolchain
from envoyr.storage import Storage


class TestResearchEngine(unittest.TestCase):
    def test_midnight_research_on_windows(self):
        profile = research_toolchain("Configure Midnight development environment", target_os="windows")
        self.assertEqual(profile.name, "Midnight Network Toolchain")
        self.assertEqual(profile.target_os, "windows")
        self.assertEqual(profile.recommended_adapter, "remote")
        self.assertTrue(any("midnight.network" in s for s in profile.sources))

        prereq_names = [p.name for p in profile.prerequisites]
        self.assertIn("rust", prereq_names)
        self.assertIn("compact", prereq_names)
        self.assertIn("build-essential", prereq_names)

        self.assertTrue(len(profile.install_steps) >= 4)
        self.assertIn("compact --version", profile.smoke_tests)

    def test_midnight_research_on_linux(self):
        profile = research_toolchain("Setup Midnight", target_os="linux")
        self.assertEqual(profile.recommended_adapter, "local")

    def test_rust_research(self):
        profile = research_toolchain("Install Rust language", target_os="windows")
        self.assertEqual(profile.name, "Rust Toolchain")
        self.assertEqual(profile.recommended_adapter, "local")
        self.assertTrue(any("rust-lang.org" in s for s in profile.sources))

    def test_cli_research_command(self):
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["research", "Midnight toolchain"])
            self.assertEqual(ret, 0)
            val = out.getvalue()
            self.assertIn("Midnight Network Toolchain", val)
            self.assertIn("Cited Sources:", val)
            self.assertIn("Prerequisites:", val)

    def test_cli_setup_invokes_research_and_creates_planned_task(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.db"
            with patch("sys.stdout", new=io.StringIO()) as out:
                ret = main(["--db-path", str(db_path), "setup", "Configure Midnight on Windows"])
                self.assertEqual(ret, 0)
                output = out.getvalue()
                self.assertIn("Researching official documentation", output)
                self.assertIn("Selected execution path: REMOTE adapter", output)
                self.assertIn("Synthesized Execution Plan", output)
                self.assertIn("Task state is now PLANNED", output)

            storage = Storage(db_path)
            tasks = storage.list_tasks()
            self.assertEqual(len(tasks), 1)
            task = storage.get_task(tasks[0].id)
            self.assertEqual(task.state, TaskState.PLANNED)
            self.assertEqual(task.adapter, "remote")
            self.assertIn("Midnight Network Toolchain", task.research_summary)
            self.assertEqual(len(task.steps), 5)


if __name__ == "__main__":
    unittest.main()
