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

[5/5] Success! Environment ready. Session logged to neatlogs.
```

## Execution Adapters

- **Local Host / WSL:** Executes directly on developer machines where native packages or WSL2 are supported and sufficient.
- **Remote Linux Worker:** Spawns a lightweight, disposable remote Linux container or micro-VM over an encrypted connection—enabling seamless setups on low-spec Windows laptops without requiring local Docker Desktop.

## Implementation Plan

- **Phase 0 — Repository and Development Foundation:** Establish repository structure, reproducible environment, documentation, and Entire tracking.
- **Phase 1 — CLI and Structured Task Model:** Implement CLI, typed task contracts, SQLite persistence, and state transition validation.
- **Phase 2 — Documentation Research:** Retrieve official documentation, extract prerequisites, and generate toolchain profiles with source citations.
- **Phase 3 — Planning and Human-in-the-Loop:** Generate dependency-ordered execution plans with policy enforcement and human approval gates.
- **Phase 4 — Controlled Execution Engine:** Execute approved actions through controlled adapters with timeouts, output capture, and allowlists.
- **Phase 5 — Verification and Self-Healing:** Implement the execution-diagnosis-recovery loop with bounded retries and smoke tests.
- **Phase 6 — Mandatory Integrations:** Integrate neatlogs for observability, Entire for coding workflow, and cfo.ai for economics modeling.
- **Phase 7 — Remote Linux Execution:** Provide remote Linux execution worker for low-spec Windows laptops without Docker Desktop.
- **Phase 8 — Midnight Toolchain Profile:** Research, plan, execute, and verify the Midnight development environment on Windows.
- **Phase 9 — Additional Toolchains:** Expand support to additional Linux-dependent developer toolchains.
- **Phase 10 — Productization and Demo:** Polish CLI experience, error reporting, execution summaries, and end-to-end demo.

## Required Integrations

- **Entire:** Coding-session context, reviewable changes, and checkpoints
- **neatlogs:** Agent workflow tracing, observability, and debugging
- **cfo.ai:** Infrastructure economics and business sustainability modeling

## Initial Target

A verified developer-toolchain setup workflow, starting with Midnight on Windows without requiring Docker Desktop locally.

## Current Status

- **Completed Milestones:**
  - **Phase 0 — Repository and Development Foundation:** Repository setup, pyproject.toml, standard library architecture, and test suite.
  - **Phase 1 — CLI and Structured Task Model:** Typed task contracts, SQLite persistence (`tasks`, `steps`, `state_transitions`), state transition validation engine, and `envoyr` CLI (`setup`, `list`, `status`, `history`, `transition`).
  - **Phase 2 — Documentation Research Engine:** Upstream doc retrieval, cited sources, OS compatibility matrix, prerequisite derivation, and toolchain profiling.
  - **Phase 3 — Planning & Human-in-the-Loop Gate:** DAG topological ordering, safety blocked-pattern denylist, plan inspection, and approval gate (`plan`, `approve`, `reject`).
  - **Phase 4 — Controlled Execution Engine:** Multi-adapter runner (`LocalAdapter`, `WSLAdapter`, `RemoteAdapter`) with per-step timeouts, stdout/stderr capture, and fail-fast task status updates (`envoyr run`).
  - **Phase 5 — Verification & Bounded Self-Healing:** Post-installation smoke test runner, root-cause error diagnostics (`PATH_OR_BINARY_MISSING`, `PERMISSION_DENIED`, `NETWORK_TRANSIENT`), and automated retry recovery (`envoyr verify`).
  - **Phase 6 — Ecosystem Integrations:** Structured telemetry event streaming via `NeatlogsTracer` and compute unit economics / cost savings calculation via `EconomicsCalculator` (cfo.ai).
  - **Phase 7 — Remote Linux Micro-VM Execution:** Offloaded execution for complex Linux-dependent developer toolchains (e.g. Midnight on Windows without Docker Desktop) via configurable SSH and isolated micro-VM sandboxes.
  - **Phase 8 — Midnight Toolchain Profile:** End-to-end orchestration for the Midnight Network toolchain on Windows, verifying Rustup, Compact compiler, contract compilation diagnostics, and remote execution.
  - **Phase 9 — Additional Developer Toolchains:** Expanded evidence-grounded research and profile synthesis to Foundry (Ethereum EVM), Solana CLI, and CosmWasm smart contracts.
  - **Phase 10 — Productization & Interactive Demo:** Streamlined CLI with end-to-end `envoyr demo` showcase, rich diagnostics, CFO.ai unit economics savings reports, and neatlogs telemetry traces.
  - **Dynamic AI Orchestrator Agent:** Natural language-first CLI interface (`envoyr "<prompt>"`, interactive `envoyr>` REPL), zero-dependency standard-library LLM provider (`Gemini` & `OpenAI`/`Ollama`), live agent research loop, and SQLite persistent research cache.
- **Test Suite Status:** 52 unit tests across 9 test suites (`test_tasks`, `test_research`, `test_planner`, `test_executor`, `test_verifier`, `test_integrations`, `test_midnight`, `test_toolchains`, `test_agent`), 100% passing.
- **Observability & Workflow:** Integrated with Entire for session checkpoints, neatlogs for agent execution tracing, and cfo.ai for unit economics modeling.


