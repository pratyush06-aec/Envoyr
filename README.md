# Envoyr

> *From intent to environment.*

An AI-powered development environment orchestrator.

## Problem

Developers frequently encounter tools unavailable natively on their operating system, complex dependency requirements, inconsistent documentation, and installation failures requiring extensive debugging.

## Vision

Envoyr accepts natural-language setup requests, researches official documentation, plans an appropriate environment, requests human approvals, executes operations safely, recovers from failures, and verifies the final environment.

## Architecture & Lifecycle

```
Natural Language Intent
        │
        ▼
[ Research & Profiling ] ──► Fetches official documentation, matrices, and prerequisites
        │
        ▼
[ Dependency Planning ]  ──► Generates dependency-ordered execution DAG and safety rules
        │
        ▼
[ Human Approval Gate ]  ──► Interactive inspection and explicit consent before execution
        │
        ▼
[ Controlled Execution ] ──► Local or remote workers with sandboxing, allowlists, and timeouts
        │
        ▼
[ Verify & Self-Heal ]   ──► Executes smoke tests; triggers bounded diagnostics and recovery
```

### Core Principles

- **Safety-First Execution:** No destructive or unreviewed actions. Commands are mapped against strict policy allowlists with explicit human approval checkpoints.
- **Evidence-Grounded Planning:** Toolchain requirements and installation steps are derived from authoritative, cited documentation rather than speculative agent behavior.
- **Host Agnostic & Lightweight:** Enables developers on low-resource machines or native Windows setups to spin up complex, Linux-dependent toolchains without mandatory Docker Desktop installs.
- **Bounded Self-Healing:** Automated failure diagnosis with bounded retry limits and actionable escalation when interventions fail.

## Component Breakdown

Envoyr is composed of five decoupled core subsystems:

- **CLI & Task Engine:** Orchestrates state machine transitions, maintains typed task contracts, and tracks execution history via local SQLite persistence.
- **Documentation Research Engine:** Queries official upstream documentation, resolves OS compatibility matrices, and extracts prerequisite dependencies with source citations.
- **Planner & Policy Gate:** Synthesizes dependency-ordered Directed Acyclic Graphs (DAGs) of discrete operations, enforcing human-in-the-loop review before any command executes.
- **Controlled Execution Adapters:** Dispatches approved steps through isolated runners (native PowerShell, WSL, or remote Linux cloud micro-VMs) with strict execution timeouts, stdout/stderr capture, and allowlists.
- **Verification & Healing Engine:** Runs post-installation smoke tests and health checks. If an error occurs, it analyzes logs to formulate bounded recovery plans.

## Example Workflow

```shell
$ envoyr setup "Configure Midnight development environment on Windows"

[1/5] Researching official Midnight documentation...
      ✓ Retrieved documentation from midnight.network
      ✓ Resolved prerequisite toolchain: Rust 1.80+, Compact compiler, Docker/remote worker
      ✓ Verified Windows compatibility path: Remote Linux Worker recommended

[2/5] Synthesized Execution Plan:
      ┌── Step 1: Initialize remote Linux worker session
      ├── Step 2: Install toolchain dependencies (build-essential, pkg-config)
      ├── Step 3: Install Compact CLI v0.2.1
      └── Step 4: Configure environment variables & verify PATH

[?] Proceed with execution? [y/N/inspect]: y

[3/5] Executing plan...
      [✓] Step 1: Remote session established (latency: 32ms)
      [✓] Step 2: Toolchain dependencies installed (38s)
      [✓] Step 3: Compact CLI v0.2.1 installed (14s)
      [✓] Step 4: Environment configured

[4/5] Running verification smoke tests...
      ✓ `compact --version` -> 0.2.1 (OK)
      ✓ Midnight test contract compilation passed

[5/5] Success! Environment ready.
```

## Execution Adapters

- **Local Host / WSL:** Executes directly on developer machines where native packages or WSL2 are supported and sufficient.
- **Remote Linux Worker:** Spawns a lightweight, disposable remote Linux container or micro-VM over an encrypted connection—enabling seamless setups on low-spec Windows laptops without requiring local Docker Desktop.

## Implementation Architecture

- **Phase 0 — Repository and Development Foundation:** Establish repository structure, reproducible environment, documentation, and testing.
- **Phase 1 — CLI and Structured Task Model:** Implement CLI, typed task contracts, SQLite persistence, and state transition validation.
- **Phase 2 — Documentation Research:** Retrieve official documentation, extract prerequisites, and generate toolchain profiles with source citations.
- **Phase 3 — Planning and Human-in-the-Loop:** Generate dependency-ordered execution plans with policy enforcement and human approval gates.
- **Phase 4 — Controlled Execution Engine:** Execute approved actions through controlled adapters with timeouts, output capture, and allowlists.
- **Phase 5 — Verification and Self-Healing:** Implement the execution-diagnosis-recovery loop with bounded retries and smoke tests.
- **Phase 6 — Remote Linux Execution:** Provide remote Linux execution worker for low-spec Windows laptops without Docker Desktop.
- **Phase 7 — Multi-Toolchain Profiles:** Research, plan, execute, and verify development environments across Windows and Linux.
- **Phase 8 — Productization and Interactive Demo:** Streamlined CLI with end-to-end `envoyr demo` showcase, rich diagnostics, and interactive REPL.

## Current Status

- **Completed Capabilities:**
  - **Task Model & Persistence:** Typed task contracts, SQLite persistence (`tasks`, `steps`, `state_transitions`), state transition validation engine, and `envoyr` CLI (`setup`, `list`, `status`, `history`, `transition`).
  - **Documentation Research Engine:** Upstream doc retrieval, cited sources, OS compatibility matrix, prerequisite derivation, and toolchain profiling.
  - **Planning & Safety Gate:** DAG topological ordering, safety blocked-pattern denylist, plan inspection, and approval gate (`plan`, `approve`, `reject`).
  - **Controlled Execution Engine:** Multi-adapter runner (`LocalAdapter`, `WSLAdapter`, `RemoteAdapter`) with per-step timeouts, stdout/stderr capture, and fail-fast task status updates (`envoyr run`).
  - **Verification & Bounded Self-Healing:** Post-installation smoke test runner, root-cause error diagnostics (`PATH_OR_BINARY_MISSING`, `PERMISSION_DENIED`, `NETWORK_TRANSIENT`, `COMPILATION_ERROR`), and automated retry recovery (`envoyr verify`).
  - **Remote Linux Micro-VM Execution:** Offloaded execution for complex Linux-dependent developer toolchains (e.g. Midnight on Windows without Docker Desktop) via configurable SSH and isolated micro-VM sandboxes.
  - **Developer Toolchains:** Evidence-grounded research and profile synthesis for Midnight Network, Foundry (Ethereum EVM), Solana CLI, CosmWasm, Bun, Rust, and Python.
  - **Interactive REPL & Shorthand Routing:** Natural language-first CLI interface (`envoyr "<prompt>"`, interactive `envoyr>` REPL).
  - **Dynamic AI Agent Engine:** Zero-dependency standard-library LLM provider (`Gemini` & `Groq`/`OpenAI`), live agent research loop, SQLite persistent research cache, dynamic error diagnosis, and autonomous remediation loop.
  - **Test Suite Status:** Comprehensive test suite across 9 test suites (`test_tasks`, `test_research`, `test_planner`, `test_executor`, `test_verifier`, `test_midnight`, `test_toolchains`, `test_agent`, `test_dynamic_research`), 100% passing.



