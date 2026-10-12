"""Typed task contracts and state transition rules."""

from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.RESEARCHING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.RESEARCHING: {TaskState.PLANNED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.PLANNED: {TaskState.APPROVED, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.APPROVED: {TaskState.EXECUTING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.EXECUTING: {TaskState.VERIFYING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.EXECUTING},
    TaskState.FAILED: {TaskState.RESEARCHING, TaskState.EXECUTING, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.CANCELLED: set(),
}


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class Step:
    id: str
    task_id: str
    order_idx: int
    title: str
    command: str
    adapter: str = "local"
    status: StepStatus = StepStatus.PENDING
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class StateTransition:
    id: int | None
    task_id: str
    from_state: str
    to_state: str
    reason: str | None
    timestamp: str


@dataclass
class Task:
    id: str
    intent: str
    state: TaskState = TaskState.PENDING
    target_os: str = "windows"
    adapter: str = "local"
    research_summary: str | None = None
    error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""
    steps: list[Step] = field(default_factory=list)
