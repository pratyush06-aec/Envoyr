"""Verification & Self-Healing Engine for Envoyr.

Runs post-installation smoke tests and provides bounded diagnostic self-healing
with automated recovery attempts before escalating to the human mentor.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from envoyr.executor import BaseAdapter, ExecutionResult, get_adapter
from envoyr.models import Task, TaskState
from envoyr.research import research_toolchain
from envoyr.storage import Storage


@dataclass
class VerificationResult:
    """Result of an individual smoke test command."""
    command: str
    passed: bool
    output: str
    error_message: str | None = None


@dataclass
class HealingDiagnosis:
    """Diagnostic root-cause assessment and remediation recommendation."""
    failure_type: str
    analysis: str
    suggested_fix: str
    can_auto_heal: bool
    remediation_command: str | None = None


def diagnose_failure(
    command: str,
    stderr: str,
    stdout: str,
    researcher: Any | None = None,
) -> HealingDiagnosis:
    """Analyze error output to identify root causes and remediation actions."""
    combined = (stderr + " " + stdout).lower()

    if any(p in combined for p in ["not recognized", "command not found", "no such file or directory"]):
        return HealingDiagnosis(
            failure_type="PATH_OR_BINARY_MISSING",
            analysis="The required binary is missing from PATH or not yet exported to the current shell session.",
            suggested_fix="Refresh environment variables, add ~/.cargo/bin or %USERPROFILE%\\.cargo\\bin to PATH, or restart terminal.",
            can_auto_heal=False,
        )

    if any(p in combined for p in ["permission denied", "access is denied", "operation not permitted"]):
        return HealingDiagnosis(
            failure_type="PERMISSION_DENIED",
            analysis="Operation requires elevated privileges or elevated file system access.",
            suggested_fix="Rerun using administrator/root privileges or check filesystem write permissions.",
            can_auto_heal=False,
        )

    if any(p in combined for p in ["connection refused", "network unreachable", "timeout", "timed out", "could not resolve host"]):
        return HealingDiagnosis(
            failure_type="NETWORK_TRANSIENT",
            analysis="Network connection failed or timed out reaching remote upstream.",
            suggested_fix="Verify internet connectivity and proxy/firewall settings, then retry.",
            can_auto_heal=True,
        )

    if any(p in combined for p in ["error: could not compile", "syntax error", "compilation failed"]):
        return HealingDiagnosis(
            failure_type="COMPILATION_ERROR",
            analysis="Contract or toolchain compilation failed during verification.",
            suggested_fix="Inspect compiler error diagnostics, verify toolchain version compatibility, and review contract syntax.",
            can_auto_heal=False,
        )

    # Dynamic AI diagnosis if researcher agent is available
    if researcher and hasattr(researcher, "diagnose_failure"):
        try:
            agent_diag = researcher.diagnose_failure(command, stderr, stdout)
            if agent_diag:
                return agent_diag
        except Exception:
            pass

    return HealingDiagnosis(
        failure_type="UNKNOWN_ERROR",
        analysis="Command exited with unexpected error output.",
        suggested_fix="Inspect step stderr logs and run manual inspection in the targeted environment.",
        can_auto_heal=False,
    )


class Verifier:
    """Runs smoke tests against verified environments and applies bounded self-healing."""

    def __init__(
        self,
        storage: Storage,
        adapters: Mapping[str, BaseAdapter] | None = None,
        researcher: Any | None = None,
    ):
        self.storage = storage
        self.adapters = adapters
        self.researcher = researcher

    def verify_task(
        self,
        task_id: str,
        smoke_tests: list[str] | None = None,
        max_healing_retries: int = 1,
    ) -> tuple[bool, list[VerificationResult], HealingDiagnosis | None]:
        task = self.storage.get_task(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found.")

        if task.state not in (TaskState.VERIFYING, TaskState.EXECUTING, TaskState.COMPLETED):
            raise ValueError(
                f"Task {task.id} is in '{task.state.value}' state. Must be in VERIFYING state to verify."
            )

        if not smoke_tests:
            profile = research_toolchain(task.intent, target_os=task.target_os)
            smoke_tests = profile.smoke_tests

        adapter = get_adapter(task.adapter, self.adapters)
        results: list[VerificationResult] = []
        all_passed = True
        first_failure: tuple[str, ExecutionResult] | None = None

        for cmd in smoke_tests:
            res = adapter.execute(cmd, timeout=60)
            if res.exit_code == 0:
                results.append(
                    VerificationResult(
                        command=cmd,
                        passed=True,
                        output=res.stdout.strip(),
                    )
                )
            else:
                all_passed = False
                results.append(
                    VerificationResult(
                        command=cmd,
                        passed=False,
                        output=res.stdout.strip(),
                        error_message=res.stderr.strip() or f"Failed with exit code {res.exit_code}",
                    )
                )
                if not first_failure:
                    first_failure = (cmd, res)

        if all_passed:
            self.storage.transition_task(
                task.id,
                TaskState.COMPLETED,
                reason="All post-install verification smoke tests passed",
            )
            return True, results, None

        # Diagnose the failure
        cmd, res = first_failure  # type: ignore
        diagnosis = diagnose_failure(cmd, res.stderr, res.stdout, researcher=self.researcher)

        # Attempt self-healing retry if auto-healable and retries available
        if diagnosis.can_auto_heal and max_healing_retries > 0:
            if diagnosis.remediation_command:
                adapter.execute(diagnosis.remediation_command, timeout=60)
            retry_res = adapter.execute(cmd, timeout=60)
            if retry_res.exit_code == 0:
                self.storage.transition_task(
                    task.id,
                    TaskState.COMPLETED,
                    reason="Verification passed after self-healing automated retry",
                )
                return True, results, diagnosis

        self.storage.transition_task(
            task.id,
            TaskState.FAILED,
            reason=f"Verification failed on command: '{cmd}' ({diagnosis.failure_type})",
            error_message=f"{diagnosis.analysis} Fix: {diagnosis.suggested_fix}",
        )
        return False, results, diagnosis
