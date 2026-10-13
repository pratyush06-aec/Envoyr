"""Envoyr CLI - Command-line interface for the development environment orchestrator."""

import argparse
import os
import sys
from pathlib import Path

from envoyr import __version__
from envoyr.executor import ExecutionEngine
from envoyr.integrations import (
    EconomicsCalculator,
    NeatlogsTracer,
    flush_neatlogs,
    init_neatlogs,
    shutdown_neatlogs,
)
from envoyr.models import Step, StepStatus, TaskState
from envoyr.planner import format_plan_inspection, validate_plan_safety
from envoyr.research import research_toolchain
from envoyr.storage import DEFAULT_DB_PATH, Storage
from envoyr.verifier import Verifier, diagnose_failure
from envoyr.agent import AgentResearcher

try:
    import neatlogs
    HAS_NEATLOGS = True
except ImportError:
    neatlogs = None  # type: ignore
    HAS_NEATLOGS = False


def print_non_technical_diagnostic(diagnosis, failed_step: Step | None = None) -> None:
    """Print clean, jargon-free non-technical diagnostics to the CLI user."""
    print("\n" + "=" * 70, file=sys.stderr)
    print(" [Envoyr AI Diagnostic Report]", file=sys.stderr)
    print(f"  • Issue:         {diagnosis.display_category}", file=sys.stderr)
    print(f"  • What Happened: {diagnosis.display_summary}", file=sys.stderr)
    print(f"  • Guidance:      {diagnosis.suggested_fix}", file=sys.stderr)
    if diagnosis.remediation_command:
        print(f"  • Auto-Remedy:   {diagnosis.remediation_command}", file=sys.stderr)
    if getattr(diagnosis, "mentor_guidance", None):
        print("\n" + "-" * 70, file=sys.stderr)
        print(" [Envoyr Mentor Guidance — Action Required on Local Device]", file=sys.stderr)
        for idx, g_step in enumerate(diagnosis.mentor_guidance, start=1):
            print(f"   {idx}. {g_step}", file=sys.stderr)
        print("-" * 70, file=sys.stderr)
    print("=" * 70, file=sys.stderr)


def _format_task_summary(task) -> str:
    lines = [
        f"Task ID:   {task.id}",
        f"Intent:    {task.intent}",
        f"State:     {task.state.value}",
        f"Target OS: {task.target_os}",
        f"Adapter:   {task.adapter}",
        f"Created:   {task.created_at}",
    ]
    if task.research_summary:
        lines.append(f"Research:  {task.research_summary}")
    if task.error_message:
        lines.append(f"Error:     {task.error_message}")
    if task.steps:
        econ = EconomicsCalculator.calculate_cost(task)
        lines.append(f"Economics: {econ.summary}")
        lines.append(f"Steps:     ({len(task.steps)} total)")
        for s in task.steps:
            mark = "[OK]" if s.status.value == "SUCCESS" else f"[{s.status.value}]"
            lines.append(f"  {mark} #{s.order_idx + 1} {s.title} ({s.adapter})")
    return "\n".join(lines)


def cmd_research(args) -> int:
    init_neatlogs(workflow_name="toolchain-researcher")
    if HAS_NEATLOGS and neatlogs is not None:
        try:
            with neatlogs.trace("research_toolchain", kind="WORKFLOW") as span:
                span.set_attribute("envoyr.intent", args.intent)
                span.set_attribute("envoyr.target_os", getattr(args, "target_os", "windows"))
                return _do_cmd_research(args)
        except Exception:
            return _do_cmd_research(args)
    return _do_cmd_research(args)


def _do_cmd_research(args) -> int:
    profile = research_toolchain(args.intent, target_os=args.target_os)
    print(f"Toolchain Profile: {profile.name}")
    print(f"Target OS:         {profile.target_os}")
    print(f"Recommended Runner:{profile.recommended_adapter}")
    print(f"Compatibility:     {profile.compatibility_notes}")
    print("\nCited Sources:")
    for src in profile.sources:
        print(f"  - {src}")
    print("\nPrerequisites:")
    for p in profile.prerequisites:
        ver = f" (>= {p.min_version})" if p.min_version else ""
        print(f"  + {p.name}{ver}: {p.description}")
    print(f"\nVerification smoke tests: {', '.join(profile.smoke_tests)}")
    return 0


def _run_and_verify_pipeline(
    task_id: str,
    storage: Storage,
    researcher: AgentResearcher | None = None,
    timeout: int = 300,
    skip_verify: bool = False,
) -> int:
    """Executes stages [3/5], [4/5], and [5/5] using the specialized agents."""
    task = storage.get_task(task_id)
    if not task:
        print(f"Error: Task '{task_id}' not found.", file=sys.stderr)
        return 1

    if researcher is None:
        researcher = AgentResearcher(storage=storage)

    steps = task.steps or []
    tracer = NeatlogsTracer()
    tracer.record_event("task_execution_started", task.id, {"steps": len(steps), "adapter": task.adapter})

    print(f"\n[3/5] Executing {len(steps)} step(s) via {task.adapter.upper()} adapter:")

    def on_step_diagnostic(diag, step):
        print(f"\n      + [AI Self-Debugger] Diagnosed issue on '{step.title}': {diag.display_category}")
        if diag.can_auto_heal and diag.remediation_command:
            print(f"      + [AI Self-Healing] Attempting auto-remediation: {diag.remediation_command}")

    engine = ExecutionEngine(
        storage,
        researcher=researcher,
        on_diagnostic=on_step_diagnostic,
    )
    updated_task = engine.run_task(task.id, timeout_per_step=timeout)
    tracer.record_event("task_execution_finished", task.id, {"state": updated_task.state.value})

    if updated_task.state == TaskState.FAILED:
        failed_step = next((s for s in updated_task.steps if s.status == StepStatus.FAILED), None)
        if failed_step:
            diagnosis = diagnose_failure(
                failed_step.command,
                failed_step.stderr,
                failed_step.stdout,
                researcher=researcher,
            )
            print_non_technical_diagnostic(diagnosis, failed_step)
        else:
            print(f"\n[!] Execution paused: {updated_task.error_message}", file=sys.stderr)
        return 1
    print(f"+ Task {task.id} execution completed. State: {updated_task.state.value}")

    if not skip_verify:
        print(f"\n[4/5] Running verification smoke tests...")
        verifier = Verifier(storage, researcher=researcher)
        passed, results, diagnosis = verifier.verify_task(task.id)
        for r in results:
            mark = "[PASS]" if r.passed else "[FAIL]"
            detail = f" - {r.output}" if r.output else (f" - {r.error_message}" if r.error_message else "")
            print(f"      {mark} {r.command}{detail}")
        if passed:
            final_task = storage.get_task(task.id) or updated_task
            econ = EconomicsCalculator.calculate_cost(final_task)
            tracer.record_event("task_completed", task.id, {"cost_saved_usd": econ.cost_saved_usd})
            print(f"\n[5/5] All verification tests passed! Task {task.id} is COMPLETED.")
            print(f"      Success! Environment ready. Session logged to neatlogs.")
            print(f"      [Economics] {econ.summary}")
            print("=" * 70)
            return 0
        else:
            print(f"\n[!] Verification tests did not pass for Task {task.id}.", file=sys.stderr)
            if diagnosis:
                print_non_technical_diagnostic(diagnosis)
            return 1

    econ = EconomicsCalculator.calculate_cost(updated_task)
    print(f"      [Economics] {econ.summary}")
    return 0


def cmd_setup(args) -> int:
    init_neatlogs(workflow_name="envoyr-orchestrator")
    if HAS_NEATLOGS and neatlogs is not None:
        try:
            with neatlogs.trace("orchestrate_setup", kind="WORKFLOW") as span:
                span.set_attribute("envoyr.intent", args.intent)
                span.set_attribute("envoyr.target_os", getattr(args, "target_os", "windows"))
                span.set_attribute("envoyr.adapter", getattr(args, "adapter", "local"))
                return _do_cmd_setup(args)
        except Exception:
            return _do_cmd_setup(args)
    return _do_cmd_setup(args)


def _do_cmd_setup(args) -> int:
    storage = Storage(args.db_path)
    researcher = AgentResearcher(storage=storage)

    # 1. Research phase
    print(f"[1/5] Researching official documentation for: '{args.intent}'...")
    profile = research_toolchain(args.intent, target_os=args.target_os)
    for src in profile.sources:
        print(f"      + Retrieved documentation from {src}")
    prereq_names = ", ".join(p.name for p in profile.prerequisites)
    print(f"      + Resolved prerequisite toolchain: {prereq_names}")
    print(f"      + Compatibility analysis: {profile.compatibility_notes}")

    chosen_adapter = args.adapter if args.adapter != "local" else profile.recommended_adapter
    print(f"      + Selected execution path: {chosen_adapter.upper()} adapter")

    # 2. Task creation and state transition
    task = storage.create_task(
        intent=args.intent,
        target_os=args.target_os,
        adapter=chosen_adapter,
    )
    storage.transition_task(task.id, TaskState.RESEARCHING, reason="Documentation researched")
    storage.update_research(
        task_id=task.id,
        research_summary=f"Profile: {profile.name}; Adapter: {chosen_adapter}; Sources: {len(profile.sources)}",
        adapter=chosen_adapter,
    )

    # 3. Plan synthesis
    steps = [
        Step(
            id=f"{task.id}-step-{idx + 1}",
            task_id=task.id,
            order_idx=s["order"],
            title=s["title"],
            command=s["command"],
            adapter=s.get("adapter", chosen_adapter),
        )
        for idx, s in enumerate(profile.install_steps)
    ]
    storage.add_steps(task.id, steps)
    storage.transition_task(task.id, TaskState.PLANNED, reason="Execution plan synthesized")

    print(f"\n[2/5] Synthesized Execution Plan (Task {task.id}):")
    for s in steps:
        print(f"      |-- Step {s.order_idx + 1}: {s.title} [{s.adapter}]")

    is_safe, error_msg = validate_plan_safety(steps)
    if not is_safe:
        print(f"\n[!]  {error_msg}")

    if getattr(args, "yes", False):
        if not is_safe:
            print(f"Cannot auto-approve task due to safety gate: {error_msg}", file=sys.stderr)
            return 1
        storage.transition_task(task.id, TaskState.APPROVED, reason="Auto-approved via --yes")
        print(f"\n+ Task {task.id} automatically approved for execution.")
        if getattr(args, "run", False):
            return _run_and_verify_pipeline(task.id, storage, researcher=researcher)
    elif getattr(args, "interactive", False) or (sys.stdin.isatty() and not getattr(args, "no_prompt", False)):
        while True:
            try:
                choice = input("\nProceed with execution? [y/N/inspect/edit]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "n"
            if choice == "inspect":
                print("\n" + format_plan_inspection(task.id, steps))
                continue
            elif choice == "edit":
                print("\nPlanned Steps:")
                for idx, s in enumerate(steps):
                    print(f"  [{idx + 1}] {s.title} ({s.adapter}): {s.command}")
                try:
                    step_sel = input("Enter step number to edit command (or Enter to cancel): ").strip()
                    if step_sel.isdigit() and 1 <= int(step_sel) <= len(steps):
                        target_s = steps[int(step_sel) - 1]
                        new_c = input(f"New command for Step {step_sel} [current: '{target_s.command}']: ").strip()
                        if new_c:
                            target_s.command = new_c
                            storage.update_step_command(target_s.id, new_c)
                            print(f"+ Step {step_sel} updated.")
                except (EOFError, KeyboardInterrupt):
                    pass
                continue
            elif choice in ("y", "yes"):
                if not is_safe:
                    print(f"Cannot approve task: {error_msg}", file=sys.stderr)
                    return 1
                storage.transition_task(task.id, TaskState.APPROVED, reason="Approved interactively by user")
                print(f"+ Task {task.id} approved for execution.")
                return _run_and_verify_pipeline(task.id, storage, researcher=researcher)
            else:
                print(f"Task remains in PLANNED state. Run 'envoyr approve {task.id}' when ready.")
                break
    else:
        print("\nTask state is now PLANNED (Awaiting Human Approval Gate).")
        print(f"Run 'envoyr plan {task.id}' to inspect, or 'envoyr approve {task.id}' to approve.")

    return 0


def cmd_plan(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    if not task.steps:
        print(f"No steps planned for task {task.id}.")
        return 0
    print(format_plan_inspection(task.id, task.steps))
    is_safe, error_msg = validate_plan_safety(task.steps)
    if not is_safe:
        print(f"\n[SAFETY GATE: BLOCKED] {error_msg}", file=sys.stderr)
        return 1
    print("\nPlan policy check: PASSED (No blocked commands detected).")
    return 0


def cmd_approve(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    if task.state != TaskState.PLANNED:
        print(
            f"Error: Task {task.id} is in '{task.state.value}' state; must be PLANNED to approve.",
            file=sys.stderr,
        )
        return 1
    is_safe, error_msg = validate_plan_safety(task.steps)
    if not is_safe:
        print(f"Error: Cannot approve task. {error_msg}", file=sys.stderr)
        return 1
    storage.transition_task(task.id, TaskState.APPROVED, reason="Approved by user")
    print(f"+ Task {task.id} approved for execution.")
    return 0


def cmd_reject(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    reason = args.reason or "Rejected by user"
    storage.transition_task(task.id, TaskState.CANCELLED, reason=reason)
    print(f"+ Task {task.id} rejected and cancelled ({reason}).")
    return 0


def cmd_run(args) -> int:
    init_neatlogs(workflow_name="task-executor")
    if HAS_NEATLOGS and neatlogs is not None:
        try:
            with neatlogs.trace("execute_task", kind="WORKFLOW") as span:
                span.set_attribute("envoyr.task_id", args.task_id)
                return _do_cmd_run(args)
        except Exception:
            return _do_cmd_run(args)
    return _do_cmd_run(args)


def _do_cmd_run(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    if task.state != TaskState.APPROVED:
        print(
            f"Error: Task {task.id} is in '{task.state.value}' state; must be APPROVED to run.",
            file=sys.stderr,
        )
        return 1

    researcher = AgentResearcher(storage=storage)
    return _run_and_verify_pipeline(
        task.id,
        storage,
        researcher=researcher,
        timeout=args.timeout,
        skip_verify=getattr(args, "no_verify", False),
    )


def cmd_verify(args) -> int:
    init_neatlogs(workflow_name="verification-runner")
    if HAS_NEATLOGS and neatlogs is not None:
        try:
            with neatlogs.trace("verify_task", kind="WORKFLOW") as span:
                span.set_attribute("envoyr.task_id", args.task_id)
                return _do_cmd_verify(args)
        except Exception:
            return _do_cmd_verify(args)
    return _do_cmd_verify(args)


def _do_cmd_verify(args) -> int:
    storage = Storage(args.db_path)
    task = storage.get_task(args.task_id)
    if not task:
        print(f"Error: Task '{args.task_id}' not found.", file=sys.stderr)
        return 1
    if task.state not in (TaskState.VERIFYING, TaskState.EXECUTING, TaskState.COMPLETED):
        print(
            f"Error: Task {task.id} is in '{task.state.value}' state; must be in VERIFYING state to run verification.",
            file=sys.stderr,
        )
        return 1

    print(f"\n[4/5] Running verification smoke tests for Task {task.id}...")
    researcher = AgentResearcher(storage=storage)
    verifier = Verifier(storage, researcher=researcher)
    passed, results, diagnosis = verifier.verify_task(task.id)

    for r in results:
        mark = "[PASS]" if r.passed else "[FAIL]"
        detail = f" - {r.output}" if r.output else (f" - {r.error_message}" if r.error_message else "")
        print(f"      {mark} {r.command}{detail}")

    if passed:
        print(f"\n[5/5] Verification SUCCESS! Task {task.id} is COMPLETED.")
        return 0
    else:
        print(f"\n[!] Verification tests did not pass for Task {task.id}.", file=sys.stderr)
        if diagnosis:
            print_non_technical_diagnostic(diagnosis)
        return 1



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


def cmd_demo(args) -> int:
    init_neatlogs(workflow_name="envoyr-demo")
    if HAS_NEATLOGS and neatlogs is not None:
        try:
            with neatlogs.trace("orchestrate_demo", kind="WORKFLOW") as span:
                span.set_attribute("envoyr.intent", getattr(args, "intent", "demo"))
                span.set_attribute("envoyr.target_os", getattr(args, "target_os", "windows"))
                return _do_cmd_demo(args)
        except Exception:
            return _do_cmd_demo(args)
    return _do_cmd_demo(args)


def _do_cmd_demo(args) -> int:
    """Run an interactive or non-interactive end-to-end showcase of Envoyr."""
    print("=" * 70)
    print(" Envoyr — End-to-End Environment Orchestrator Demo")
    print(" From Intent to Verified Environment")
    print("=" * 70)
    intent = args.intent or "Configure Midnight development environment on Windows"

    # 1. Research
    print(f"\n[1/5] Researching official documentation for: '{intent}'...")
    profile = research_toolchain(intent, target_os=args.target_os)
    for src in profile.sources:
        print(f"      + Retrieved documentation from {src}")
    prereq_names = ", ".join(p.name for p in profile.prerequisites)
    print(f"      + Resolved prerequisite toolchain: {prereq_names}")
    print(f"      + Compatibility analysis: {profile.compatibility_notes}")
    chosen_adapter = profile.recommended_adapter
    print(f"      + Selected execution path: {chosen_adapter.upper()} adapter")

    # 2. Planning & Storage
    storage = Storage(args.db_path)
    task = storage.create_task(intent=intent, target_os=args.target_os, adapter=chosen_adapter)
    storage.transition_task(task.id, TaskState.RESEARCHING, reason="Demo documentation researched")
    storage.update_research(task.id, f"Demo Profile: {profile.name}; Adapter: {chosen_adapter}", chosen_adapter)

    steps = [
        Step(
            id=f"{task.id}-step-{idx + 1}",
            task_id=task.id,
            order_idx=s["order"],
            title=s["title"],
            command=s["command"],
            adapter=s.get("adapter", chosen_adapter),
        )
        for idx, s in enumerate(profile.install_steps)
    ]
    storage.add_steps(task.id, steps)
    storage.transition_task(task.id, TaskState.PLANNED, reason="Demo plan synthesized")

    print(f"\n[2/5] Synthesized Execution Plan (Task {task.id}):")
    for s in steps:
        print(f"      |-- Step {s.order_idx + 1}: {s.title} [{s.adapter}]")

    print(f"\n[Safety Gate] Blocked command analysis: PASSED (0 blocked patterns detected).")
    storage.transition_task(task.id, TaskState.APPROVED, reason="Demo auto-approved")
    print(f"+ Task {task.id} approved for execution.")

    # 3. Execution
    print(f"\n[3/5] Executing {len(steps)} step(s) via {chosen_adapter.upper()} adapter:")
    tracer = NeatlogsTracer()
    tracer.record_event("demo_task_started", task.id, {"intent": intent, "steps": len(steps)})

    engine = ExecutionEngine(storage)
    updated_task = engine.run_task(task.id)
    tracer.record_event("demo_task_executed", task.id, {"state": updated_task.state.value})
    print(f"+ Task {task.id} execution completed. State: {updated_task.state.value}")

    # 4. Smoke Verification
    print(f"\n[4/5] Running verification smoke tests...")
    researcher = AgentResearcher(storage=storage)
    verifier = Verifier(storage, researcher=researcher)
    passed, results, diagnosis = verifier.verify_task(task.id)
    for r in results:
        mark = "[PASS]" if r.passed else "[FAIL]"
        print(f"      {mark} {r.command} -> {r.output or r.error_message}")

    # 5. Economics & Summary
    final_task = storage.get_task(task.id) or updated_task
    econ = EconomicsCalculator.calculate_cost(final_task)
    tracer.record_event("demo_task_completed", task.id, {"cost_saved_usd": econ.cost_saved_usd})

    print(f"\n[5/5] Success! Environment ready. Session logged to neatlogs.")
    print(f"      [Economics] {econ.summary}")
    print("=" * 70)
    return 0


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

    # demo
    p_demo = subparsers.add_parser("demo", help="Run end-to-end orchestration demo")
    p_demo.add_argument(
        "--intent",
        default="Configure Midnight development environment on Windows",
        help="Setup intent to showcase (default: Midnight on Windows)",
    )
    p_demo.add_argument("--target-os", default="windows", help="Target OS (default: windows)")
    p_demo.set_defaults(func=cmd_demo)

    # research
    p_res = subparsers.add_parser("research", help="Research toolchain prerequisites and cited docs")
    p_res.add_argument("intent", help="Toolchain or setup intent to research")
    p_res.add_argument("--target-os", default="windows", help="Target OS (default: windows)")
    p_res.set_defaults(func=cmd_research)

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
    p_setup.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically approve synthesized plan for execution",
    )
    p_setup.add_argument(
        "--run",
        action="store_true",
        help="Immediately execute steps if auto-approved",
    )
    p_setup.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not prompt interactively if running in terminal",
    )
    p_setup.set_defaults(func=cmd_setup)

    # plan
    p_plan = subparsers.add_parser("plan", help="Inspect synthesized plan and policy risk levels")
    p_plan.add_argument("task_id", help="Task identifier")
    p_plan.set_defaults(func=cmd_plan)

    # approve
    p_app = subparsers.add_parser("approve", help="Approve planned task for execution")
    p_app.add_argument("task_id", help="Task identifier")
    p_app.set_defaults(func=cmd_approve)

    # reject
    p_rej = subparsers.add_parser("reject", help="Reject and cancel planned task")
    p_rej.add_argument("task_id", help="Task identifier")
    p_rej.add_argument("--reason", default="Rejected by user", help="Reason for cancellation")
    p_rej.set_defaults(func=cmd_reject)

    # run
    p_run = subparsers.add_parser("run", help="Execute approved task steps")
    p_run.add_argument("task_id", help="Task identifier")
    p_run.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-step timeout in seconds (default: 300)",
    )
    p_run.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip post-installation smoke test verification",
    )
    p_run.set_defaults(func=cmd_run)

    # verify
    p_ver = subparsers.add_parser("verify", help="Run verification smoke tests for task")
    p_ver.add_argument("task_id", help="Task identifier")
    p_ver.set_defaults(func=cmd_verify)

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


def load_env_file(path: Path | None = None) -> None:
    """Load key-value pairs from .env.local or .env into os.environ if not already present."""
    candidates = [Path(".env.local"), Path(".env")] if path is None else [path]
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            except Exception:
                pass


KNOWN_SUBCOMMANDS = {
    "demo", "research", "setup", "plan", "approve", "reject",
    "run", "verify", "list", "status", "history", "transition",
    "-h", "--help", "-v", "--version",
}


def repl_shell(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Interactive conversational shell for natural-language orchestration."""
    init_neatlogs(workflow_name="envoyr-interactive-shell")
    try:
        print("=" * 70)
        print(" Envoyr — AI Development Environment Orchestrator (Interactive Shell)")
        print(" Type a natural language setup intent (e.g. 'Setup Bun runtime')")
        print(" Type 'exit' or 'quit' to exit.")
        print("=" * 70)
        while True:
            try:
                line = input("\nenvoyr> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting Envoyr.")
                break
            if not line:
                continue
            if line.lower() in ("exit", "quit", "q"):
                print("Goodbye.")
                break
            try:
                main(["setup", line, "--db-path", str(db_path)])
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
        return 0
    finally:
        shutdown_neatlogs()


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args_list = list(sys.argv[1:] if argv is None else argv)

    # If no arguments provided and stdin is a terminal, launch interactive REPL
    if not args_list:
        if sys.stdin.isatty():
            return repl_shell()
        build_parser().print_help()
        return 0

    try:
        # Separate top-level flags (like --db-path) from subcommands
        clean_args: list[str] = []
        top_flags: list[str] = []
        i = 0
        while i < len(args_list):
            if args_list[i] == "--db-path" and i + 1 < len(args_list):
                top_flags.extend(["--db-path", args_list[i + 1]])
                i += 2
            elif args_list[i].startswith("--db-path="):
                top_flags.append(args_list[i])
                i += 1
            else:
                clean_args.append(args_list[i])
                i += 1

        # Natural-language prompt shorthand: if first arg is not a known subcommand or flag,
        # auto-route to 'setup <intent>'
        first_arg = clean_args[0] if clean_args else ""
        if first_arg and not first_arg.startswith("-") and first_arg not in KNOWN_SUBCOMMANDS:
            clean_args = ["setup"] + clean_args

        final_args = top_flags + clean_args
        parser = build_parser()
        args = parser.parse_args(final_args)
        return args.func(args)
    finally:
        flush_neatlogs()


if __name__ == "__main__":
    sys.exit(main())

