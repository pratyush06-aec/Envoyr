"""Planner & Policy Gate for Envoyr.

Synthesizes dependency-ordered Directed Acyclic Graphs (DAGs) of discrete operations,
evaluates commands against strict policy allowlists/safety rules, and enforces human-in-the-loop review.
"""

from enum import Enum


class RiskLevel(str, Enum):
    SAFE = "SAFE"          # Read-only, inspection, version check
    MODIFY = "MODIFY"      # Toolchain/package installation, env export
    CRITICAL = "CRITICAL"  # System configuration or privileged action
    BLOCKED = "BLOCKED"    # Destructive or strictly forbidden action


# Strict policy denylist of destructive command patterns
BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=",
    "> /dev/sd",
    "shutdown",
    "reboot",
]


def assess_command_risk(command: str) -> RiskLevel:
    """Assess risk level of a shell command against policy allowlists and safety rules."""
    cmd_lower = command.strip().lower()

    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return RiskLevel.BLOCKED

    # Safe inspection commands
    if any(cmd_lower.startswith(prefix) for prefix in ["echo ", "which ", "where ", "uname", "whoami", "cat "]) or "--version" in cmd_lower:
        return RiskLevel.SAFE

    # Privileged/critical system modifications
    if "sudo " in cmd_lower or "chmod 777" in cmd_lower or "/etc/" in cmd_lower:
        return RiskLevel.CRITICAL

    return RiskLevel.MODIFY


def topological_sort_steps(steps: list) -> list:
    """Order steps honoring prerequisite dependencies in DAG.
    linear dependency order; multi-parent DAG upgrade in Phase 9
    """
    def _order_key(step):
        if hasattr(step, "order_idx"):
            return step.order_idx
        if isinstance(step, dict):
            return step.get("order", step.get("order_idx", 0))
        return 0

    return sorted(steps, key=_order_key)


def validate_plan_safety(steps: list) -> tuple[bool, str | None]:
    """Ensure no step in the plan contains a BLOCKED command."""
    for s in steps:
        cmd = getattr(s, "command", s.get("command", "") if isinstance(s, dict) else "")
        risk = assess_command_risk(cmd)
        if risk == RiskLevel.BLOCKED:
            return False, f"Policy violation: command '{cmd}' is blocked by safety gate"
    return True, None


def format_plan_inspection(task_id: str, steps: list) -> str:
    """Format execution DAG for human interactive inspection."""
    border = "=" * 65
    divider = "-" * 45
    lines = [
        border,
        f" Execution Plan Inspection for Task: {task_id}",
        border,
    ]
    for idx, s in enumerate(steps):
        cmd = getattr(s, "command", None) if hasattr(s, "command") else (s.get("command", "") if isinstance(s, dict) else "")
        title = getattr(s, "title", None) if hasattr(s, "title") else (s.get("title", "") if isinstance(s, dict) else "")
        adapter = getattr(s, "adapter", None) if hasattr(s, "adapter") else (s.get("adapter", "local") if isinstance(s, dict) else "local")
        risk = assess_command_risk(cmd or "")
        lines.append(f" Step {idx + 1}: {title}")
        lines.append(f"   Adapter: {adapter}")
        lines.append(f"   Command: {cmd}")
        lines.append(f"   Risk:    [{risk.value}]")
        lines.append(f"   {divider}")
    return "\n".join(lines)
