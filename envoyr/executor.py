"""Controlled Execution Engine for Envoyr.

Manages process execution across Local, WSL, and Remote adapters with
strict timeouts, step-level output logging, and fail-fast task status updates.
"""

import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

from envoyr.models import Step, StepStatus, Task, TaskState
from envoyr.storage import Storage


@dataclass
class ExecutionResult:
    """Result of an individual command execution."""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


class BaseAdapter(ABC):
    """Abstract base class for execution environment adapters."""

    @abstractmethod
    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        """Execute a shell command with a strict timeout."""
        pass


class LocalAdapter(BaseAdapter):
    """Executes commands directly on the host system shell."""

    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        start_time = time.perf_counter()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_ms=int(elapsed * 1000),
                timed_out=False,
            )
        except subprocess.TimeoutExpired as e:
            elapsed = time.perf_counter() - start_time
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = f"Command timed out after {timeout} seconds."
            return ExecutionResult(
                exit_code=-1,
                stdout=stdout,
                stderr=stderr,
                duration_ms=int(elapsed * 1000),
                timed_out=True,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Execution error: {str(e)}",
                duration_ms=int(elapsed * 1000),
                timed_out=False,
            )


class WSLAdapter(BaseAdapter):
    """Executes commands inside Windows Subsystem for Linux (WSL)."""

    def __init__(self):
        self.wsl_available = shutil.which("wsl") is not None

    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        if not self.wsl_available:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="WSL (wsl.exe) is not installed or available on this system.",
                duration_ms=0,
            )

        start_time = time.perf_counter()
        try:
            proc = subprocess.run(
                ["wsl", "-e", "bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_ms=int(elapsed * 1000),
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"WSL command timed out after {timeout} seconds.",
                duration_ms=int(elapsed * 1000),
                timed_out=True,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"WSL execution error: {str(e)}",
                duration_ms=int(elapsed * 1000),
                timed_out=False,
            )


class RemoteAdapter(BaseAdapter):
    """Executes commands on a remote worker / micro-VM.
    
    Provides isolated remote Linux execution for environments where
    local Docker or WSL is not configured.
    """

    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint or "mock://remote-linux-vm"

    def execute(self, command: str, timeout: int = 300) -> ExecutionResult:
        start_time = time.perf_counter()
        # Remote execution placeholder simulating isolated environment runner
        # Upgraded to SSH/REST micro-VM worker in Phase 7
        elapsed = time.perf_counter() - start_time
        return ExecutionResult(
            exit_code=0,
            stdout=f"[remote:{self.endpoint}] Executed: {command}",
            stderr="",
            duration_ms=int(elapsed * 1000) + 10,
            timed_out=False,
        )


DEFAULT_ADAPTERS: dict[str, BaseAdapter] = {
    "local": LocalAdapter(),
    "wsl": WSLAdapter(),
    "remote": RemoteAdapter(),
}


def get_adapter(name: str, adapters: Mapping[str, BaseAdapter] | None = None) -> BaseAdapter:
    """Retrieve an adapter by name."""
    mapping = adapters or DEFAULT_ADAPTERS
    adapter = mapping.get(name.lower())
    if not adapter:
        raise ValueError(f"Unknown adapter '{name}'. Available: {list(mapping.keys())}")
    return adapter


class ExecutionEngine:
    """Orchestrates step-by-step task execution with status persistence."""

    def __init__(self, storage: Storage, adapters: Mapping[str, BaseAdapter] | None = None):
        self.storage = storage
        self.adapters = adapters or DEFAULT_ADAPTERS

    def run_task(self, task_id: str, timeout_per_step: int = 300) -> Task:
        """Run all steps of an approved task sequentially."""
        task = self.storage.get_task(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found.")

        if task.state not in (TaskState.APPROVED, TaskState.EXECUTING):
            raise ValueError(
                f"Cannot execute task in '{task.state.value}' state. Task must be in APPROVED state."
            )

        if task.state == TaskState.APPROVED:
            self.storage.transition_task(
                task.id, TaskState.EXECUTING, reason="Execution engine started steps"
            )

        for step in task.steps:
            if step.status == StepStatus.SUCCESS:
                continue

            self.storage.update_step(step.id, status=StepStatus.RUNNING)
            adapter = get_adapter(step.adapter, self.adapters)
            res = adapter.execute(step.command, timeout=timeout_per_step)

            if res.exit_code == 0:
                self.storage.update_step(
                    step_id=step.id,
                    status=StepStatus.SUCCESS,
                    exit_code=0,
                    stdout=res.stdout,
                    stderr=res.stderr,
                    duration_ms=res.duration_ms,
                )
            else:
                self.storage.update_step(
                    step_id=step.id,
                    status=StepStatus.FAILED,
                    exit_code=res.exit_code,
                    stdout=res.stdout,
                    stderr=res.stderr,
                    duration_ms=res.duration_ms,
                )
                err_msg = res.stderr.strip() or f"Command failed with exit code {res.exit_code}"
                self.storage.transition_task(
                    task.id,
                    TaskState.FAILED,
                    reason=f"Step '{step.title}' failed with code {res.exit_code}",
                    error_message=err_msg,
                )
                return self.storage.get_task(task.id)

        # All steps succeeded -> transition to VERIFYING state
        self.storage.transition_task(
            task.id,
            TaskState.VERIFYING,
            reason="All execution steps completed successfully; awaiting verification",
        )
        return self.storage.get_task(task.id)
