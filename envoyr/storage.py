"""SQLite persistence and state transition validation for Envoyr tasks."""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from envoyr.models import (
    Step,
    StepStatus,
    StateTransition,
    Task,
    TaskState,
    VALID_TRANSITIONS,
)

DEFAULT_DB_PATH = Path(".envoyr") / "tasks.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    intent TEXT NOT NULL,
                    state TEXT NOT NULL,
                    target_os TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    research_summary TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    order_idx INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    command TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                """
            )

    def create_task(
        self,
        intent: str,
        target_os: str = "windows",
        adapter: str = "local",
        task_id: str | None = None,
    ) -> Task:
        tid = task_id or uuid.uuid4().hex[:12]
        now = _now_iso()
        task = Task(
            id=tid,
            intent=intent,
            state=TaskState.PENDING,
            target_os=target_os,
            adapter=adapter,
            created_at=now,
            updated_at=now,
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, intent, state, target_os, adapter, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task.id, task.intent, task.state.value, task.target_os, task.adapter, now, now),
            )
            conn.execute(
                """
                INSERT INTO state_transitions (task_id, from_state, to_state, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task.id, "NONE", TaskState.PENDING.value, "Task initialized", now),
            )
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self._get_connection() as conn:
            t_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not t_row:
                return None
            s_rows = conn.execute(
                "SELECT * FROM steps WHERE task_id = ? ORDER BY order_idx ASC",
                (task_id,),
            ).fetchall()

        steps = [
            Step(
                id=r["id"],
                task_id=r["task_id"],
                order_idx=r["order_idx"],
                title=r["title"],
                command=r["command"],
                adapter=r["adapter"],
                status=StepStatus(r["status"]),
                exit_code=r["exit_code"],
                stdout=r["stdout"],
                stderr=r["stderr"],
                duration_ms=r["duration_ms"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in s_rows
        ]
        return Task(
            id=t_row["id"],
            intent=t_row["intent"],
            state=TaskState(t_row["state"]),
            target_os=t_row["target_os"],
            adapter=t_row["adapter"],
            research_summary=t_row["research_summary"],
            error_message=t_row["error_message"],
            created_at=t_row["created_at"],
            updated_at=t_row["updated_at"],
            steps=steps,
        )

    def list_tasks(self, limit: int = 20) -> list[Task]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Task(
                id=r["id"],
                intent=r["intent"],
                state=TaskState(r["state"]),
                target_os=r["target_os"],
                adapter=r["adapter"],
                research_summary=r["research_summary"],
                error_message=r["error_message"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def transition_task(
        self,
        task_id: str,
        to_state: TaskState,
        reason: str | None = None,
        error_message: str | None = None,
    ) -> Task:
        task = self.get_task(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        current = task.state
        allowed = VALID_TRANSITIONS.get(current, set())
        if to_state not in allowed:
            raise ValueError(
                f"Invalid transition from {current.value} to {to_state.value} (allowed: {[s.value for s in allowed]})"
            )

        now = _now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET state = ?, error_message = COALESCE(?, error_message), updated_at = ?
                WHERE id = ?
                """,
                (to_state.value, error_message, now, task_id),
            )
            conn.execute(
                """
                INSERT INTO state_transitions (task_id, from_state, to_state, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, current.value, to_state.value, reason, now),
            )

        task.state = to_state
        task.updated_at = now
        if error_message:
            task.error_message = error_message
        return task

    def add_steps(self, task_id: str, steps: Sequence[Step]) -> None:
        now = _now_iso()
        with self._get_connection() as conn:
            for s in steps:
                conn.execute(
                    """
                    INSERT INTO steps (id, task_id, order_idx, title, command, adapter, status, exit_code, stdout, stderr, duration_ms, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        s.id,
                        task_id,
                        s.order_idx,
                        s.title,
                        s.command,
                        s.adapter,
                        s.status.value,
                        s.exit_code,
                        s.stdout,
                        s.stderr,
                        s.duration_ms,
                        s.created_at or now,
                        s.updated_at or now,
                    ),
                )

    def update_step(
        self,
        step_id: str,
        status: StepStatus,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        duration_ms: int = 0,
    ) -> None:
        now = _now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE steps
                SET status = ?, exit_code = ?, stdout = ?, stderr = ?, duration_ms = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, exit_code, stdout, stderr, duration_ms, now, step_id),
            )

    def get_transitions(self, task_id: str) -> list[StateTransition]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM state_transitions WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            StateTransition(
                id=r["id"],
                task_id=r["task_id"],
                from_state=r["from_state"],
                to_state=r["to_state"],
                reason=r["reason"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]
