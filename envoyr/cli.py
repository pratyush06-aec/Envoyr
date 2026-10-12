"""Envoyr CLI - Command-line interface for the development environment orchestrator."""

import argparse
import sys
from pathlib import Path

from envoyr import __version__
from envoyr.models import TaskState
from envoyr.storage import DEFAULT_DB_PATH, Storage


def _format_task_summary(task) -> str:
    lines = [
        f"Task ID:   {task.id}",
        f"Intent:    {task.intent}",
        f"State:     {task.state.value}",
        f"Target OS: {task.target_os}",
        f"Adapter:   {task.adapter}",
        f"Created:   {task.created_at}",
    ]
    if task.error_message:
        lines.append(f"Error:     {task.error_message}")
    if task.steps:
        lines.append(f"Steps:     ({len(task.steps)} total)")
        for s in task.steps:
            mark = "[✓]" if s.status.value == "SUCCESS" else f"[{s.status.value}]"
            lines.append(f"  {mark} #{s.order_idx + 1} {s.title} ({s.adapter})")
    return "\n".join(lines)


def cmd_setup(args) -> int:
    storage = Storage(args.db_path)
    task = storage.create_task(
        intent=args.intent,
        target_os=args.target_os,
        adapter=args.adapter,
    )
    print(f"Envoyr initialized task: {task.id}")
    print(f"State: {task.state.value}")
    print(f"Target OS: {task.target_os} | Adapter: {task.adapter}")
    print(f"Intent: {task.intent}")
    return 0


def cmd_list(args) -> int:
    storage = Storage(args.db_path)
    tasks = storage.list_tasks(limit=args.limit)
    if not tasks:
        print("No tasks found.")
        return 0
    print(f"{'TASK ID':<14} {'STATE':<13} {'ADAPTER':<10} {'INTENT'}")
    print("-" * 70)
    for t in tasks:
        intent = (t.intent[:40] + "...") if len(t.intent) > 43 else t.intent
        print(f"{t.id:<14} {t.state.value:<13} {t.adapter:<10} {intent}")
    return 0


def cmd_status(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    print(_format_task_summary(task))
    return 0


def cmd_history(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    transitions = storage.get_transitions(args.task_id)
    print(f"State transition history for {args.task_id}:")
    for tr in transitions:
        reason_str = f" - {tr.reason}" if tr.reason else ""
        print(f"  [{tr.timestamp}] {tr.from_state} -> {tr.to_state}{reason_str}")
    return 0


def cmd_transition(args) -> int:
    storage = Storage(args.db_path)
    try:
        to_state = TaskState(args.state.upper())
    except ValueError:
        valid_states = [s.value for s in TaskState]
        print(f"Error: Unknown state '{args.state}'. Valid: {', '.join(valid_states)}", file=sys.stderr)
        return 1

    try:
        task = storage.transition_task(args.task_id, to_state, reason=args.reason)
        print(f"Task {task.id} transitioned to {task.state.value}")
        return 0
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="envoyr",
        description="Envoyr - AI-powered development environment orchestrator",
    )
    parser.add_argument("--version", action="version", version=f"envoyr {__version__}")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to SQLite database file (default: {DEFAULT_DB_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    p_setup = subparsers.add_parser("setup", help="Initialize a new setup task from intent")
    p_setup.add_argument("intent", help="Natural language setup intent")
    p_setup.add_argument("--target-os", default="windows", help="Target OS (default: windows)")
    p_setup.add_argument(
        "--adapter",
        default="local",
        choices=["local", "wsl", "remote"],
        help="Execution adapter (default: local)",
    )
    p_setup.set_defaults(func=cmd_setup)

    # list
    p_list = subparsers.add_parser("list", help="List recent tasks")
    p_list.add_argument("--limit", type=int, default=20, help="Max tasks to show")
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = subparsers.add_parser("status", help="Show details of a specific task")
    p_status.add_argument("task_id", help="Task identifier")
    p_status.set_defaults(func=cmd_status)

    # history
    p_hist = subparsers.add_parser("history", help="Show state transition audit log")
    p_hist.add_argument("task_id", help="Task identifier")
    p_hist.set_defaults(func=cmd_history)

    # transition
    p_trans = subparsers.add_parser("transition", help="Transition task to next state")
    p_trans.add_argument("task_id", help="Task identifier")
    p_trans.add_argument("state", help="Target state name")
    p_trans.add_argument("--reason", default=None, help="Reason for transition")
    p_trans.set_defaults(func=cmd_transition)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
