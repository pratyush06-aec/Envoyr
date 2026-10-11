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
