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
    non_technical_summary: str | None = None

    @property
    def display_category(self) -> str:
        """Returns a non-technical, human-friendly category label."""
        categories = {
            "PATH_OR_BINARY_MISSING": "Environment Setup / Program Path",
            "PERMISSION_DENIED": "Permissions / System Access",
            "NETWORK_TRANSIENT": "Network / Internet Connection",
            "COMPILATION_ERROR": "Build / Package Compilation",
            "WSL_COMMAND_IN_LINUX": "Environment Configuration (WSL)",
            "UNKNOWN_ERROR": "Installation Interruption",
        }
        return categories.get(self.failure_type, self.failure_type.replace("_", " ").title())

    @property
    def display_summary(self) -> str:
        """Returns a plain-English, non-technical explanation for end users."""
        if self.non_technical_summary:
            return self.non_technical_summary
        if self.failure_type == "PATH_OR_BINARY_MISSING":
            return "The installed program could not be located in your current terminal session because the environment path needs to be refreshed."
        if self.failure_type == "PERMISSION_DENIED":
            return "The installer required elevated administrative permissions to write files to the destination directory."
        if self.failure_type == "NETWORK_TRANSIENT":
            return "A temporary network glitch or timeout occurred while downloading packages from the remote server."
        if self.failure_type == "COMPILATION_ERROR":
            return "The package build process stopped due to missing development dependencies or compiler version differences."
        if self.failure_type == "WSL_COMMAND_IN_LINUX":
            return "A command intended to launch Linux was run from inside Linux where the environment was already active."
        return self.analysis


def diagnose_failure(
    command: str,
    stderr: str,
    stdout: str,
    researcher: Any | None = None,
) -> HealingDiagnosis:
    """Analyze error output to identify root causes and remediation actions."""
    combined = (stderr + " " + stdout).lower()

    # Redundant WSL wrapper detection
    if "wsl: command not found" in combined or (command.strip().startswith("wsl") and "command not found" in combined):
        return HealingDiagnosis(
            failure_type="WSL_COMMAND_IN_LINUX",
            analysis="A Windows WSL launcher command was invoked inside the Linux subsystem where the environment is already active.",
            suggested_fix="Execute commands natively within Linux without prefixing 'wsl'.",
            can_auto_heal=True,
            remediation_command="uname -a && whoami",
            non_technical_summary="A Windows-specific command was executed inside the Linux environment. Envoyr can automatically adapt and run this natively.",
        )

    # Dynamic AI diagnosis if researcher agent is available
    if researcher and hasattr(researcher, "diagnose_failure"):
        try:
            agent_diag = researcher.diagnose_failure(command, stderr, stdout)
            if agent_diag:
                return agent_diag
        except Exception:
            pass

    if any(p in combined for p in ["not recognized", "command not found", "no such file or directory"]):
        return HealingDiagnosis(
            failure_type="PATH_OR_BINARY_MISSING",
            analysis="The required binary is missing from PATH or not yet exported to the current shell session.",
            suggested_fix="Refresh environment variables, add ~/.cargo/bin or %USERPROFILE%\\.cargo\\bin to PATH, or restart terminal.",
            can_auto_heal=False,
            non_technical_summary="The required binary could not be found in the current terminal session. The system path may need to be updated.",
        )

    if any(p in combined for p in ["permission denied", "access is denied", "operation not permitted"]):
        return HealingDiagnosis(
            failure_type="PERMISSION_DENIED",
            analysis="Operation requires elevated privileges or elevated file system access.",
            suggested_fix="Rerun using administrator/root privileges or check filesystem write permissions.",
            can_auto_heal=False,
            non_technical_summary="The installer needs administrator/root permissions to modify files in this directory.",
        )

    if any(p in combined for p in ["connection refused", "network unreachable", "timeout", "timed out", "could not resolve host"]):
        return HealingDiagnosis(
            failure_type="NETWORK_TRANSIENT",
            analysis="Network connection failed or timed out reaching remote upstream.",
            suggested_fix="Verify internet connectivity and proxy/firewall settings, then retry.",
            can_auto_heal=True,
            non_technical_summary="A temporary network connection issue occurred while downloading files from the server.",
        )

    if any(p in combined for p in ["error: could not compile", "syntax error", "compilation failed"]):
        return HealingDiagnosis(
            failure_type="COMPILATION_ERROR",
            analysis="Contract or toolchain compilation failed during verification.",
            suggested_fix="Inspect compiler error diagnostics, verify toolchain version compatibility, and review contract syntax.",
            can_auto_heal=False,
            non_technical_summary="Building the component failed due to compiler errors or missing dependencies.",
        )

    return HealingDiagnosis(
        failure_type="UNKNOWN_ERROR",
        analysis="Command exited with unexpected error output.",
        suggested_fix="Inspect step stderr logs and run manual inspection in the targeted environment.",
        can_auto_heal=False,
        non_technical_summary="An unexpected error occurred during execution.",
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
