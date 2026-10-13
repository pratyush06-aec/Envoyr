"""Dynamic Agentic Researcher for Envoyr.

Orchestrates real-time LLM-driven research, documentation discovery, and toolchain profiling
for arbitrary natural language user intents.
"""

import json
from typing import Any
from envoyr.agent.heuristic import synthesize_heuristic_profile
from envoyr.agent.provider import LLMClient
from envoyr.research import Prerequisite, ToolchainProfile, fetch_url_text

try:
    import neatlogs
    HAS_NEATLOGS = True
except ImportError:
    neatlogs = None  # type: ignore
    HAS_NEATLOGS = False


SYSTEM_PROMPT = """You are Envoyr, an elite AI development environment orchestrator.
Your goal is to transform a natural language developer intent into a typed, verified execution plan.

Guidelines:
1. Target OS compatibility:
   - If target OS is Windows and the toolchain requires Linux glibc, Linux BPF, or lacks reliable Windows builds (e.g. Midnight Compact, complex Linux kernel tools), recommend 'remote' (isolated Linux cloud worker / micro-VM).
   - If natively supported on Windows (e.g. Rust, Bun, Python, Node, Zig), recommend 'local'.
2. Safety:
   - Provide minimal, idempotent, official commands.
   - Do NOT include dangerous commands (rm -rf /, format, drop db).
3. Verification:
   - Always provide 1 to 3 smoke test commands (e.g. 'tool --version', 'tool --help') to verify successful installation.
4. WSL Execution:
   - If recommended_adapter is 'wsl', install_steps commands MUST be native Linux/bash commands (e.g. 'sudo apt-get update -y', 'curl -fsSL https://... | bash').
   - NEVER prefix commands with 'wsl', 'wsl.exe', or 'wsl -d <distro>' because the adapter runs inside WSL directly.
   - Always include non-interactive flags (e.g. -y for apt-get).
5. Windows Package Managers & Shell:
   - On Windows Chocolatey, use correct official package identifiers (e.g. Kotlin compiler is 'kotlinc', not 'kotlin').
   - For package manager installation steps, make them idempotent (e.g. 'choco --version || <install script>').
   - Any PowerShell one-liners must be executable via 'powershell -NoProfile -ExecutionPolicy Bypass -Command "..."'.

You MUST respond strictly with valid JSON without additional conversational text.
Schema:
{
  "name": "Toolchain Name",
  "recommended_adapter": "local" | "wsl" | "remote",
  "sources": ["https://official-docs-url..."],
  "compatibility_notes": "Compatibility summary",
  "prerequisites": [
    {"name": "tool", "min_version": "1.0", "description": "brief desc", "install_command": "cmd"}
  ],
  "install_steps": [
    {"order": 0, "title": "Step title", "command": "shell command"}
  ],
  "smoke_tests": ["binary --version"]
}
"""


class AgentResearcher:
    """Researches developer intents using LLM reasoning and live doc context."""

    def __init__(self, llm_client: LLMClient | None = None, storage: Any | None = None):
        self.llm_client = llm_client or LLMClient()
        self.storage = storage

    def research(self, intent: str, target_os: str = "windows") -> ToolchainProfile:
        """Synthesize a complete toolchain profile for any natural language intent."""
        if HAS_NEATLOGS and neatlogs is not None:
            try:
                with neatlogs.trace("agent_researcher", kind="AGENT") as span:
                    span.set_attribute("envoyr.intent", intent)
                    span.set_attribute("envoyr.target_os", target_os)
                    profile = self._do_research(intent, target_os=target_os)
                    span.set_attribute("envoyr.profile.name", profile.name)
                    span.set_attribute("envoyr.profile.adapter", profile.recommended_adapter)
                    span.set_attribute("envoyr.profile.steps_count", len(profile.install_steps))
                    return profile
            except Exception:
                return self._do_research(intent, target_os=target_os)
        return self._do_research(intent, target_os=target_os)

    def _do_research(self, intent: str, target_os: str = "windows") -> ToolchainProfile:
        # 1. Check local persistent SQLite cache
        if self.storage:
            try:
                cached_str = self.storage.get_cached_profile(intent, target_os)
                if cached_str:
                    data = json.loads(cached_str)
                    return self._parse_profile(data, target_os=target_os)
            except Exception:
                pass

        profile: ToolchainProfile | None = None

        # 2. Dynamic LLM synthesis
        if self.llm_client.is_configured:
            prompt = (
                f"Developer Setup Intent: {intent}\n"
                f"Target Operating System: {target_os}\n"
                f"Generate an evidence-grounded installation DAG and smoke verification plan."
            )
            try:
                data = self.llm_client.generate_json(
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT,
                    timeout=25.0,
                )
                if data and isinstance(data, dict) and "name" in data and "install_steps" in data:
                    profile = self._parse_profile(data, target_os=target_os)
                    if self.storage:
                        self.storage.save_cached_profile(intent, target_os, profile.to_json())
            except Exception:
                profile = None

        # 3. Intelligent heuristic fallback
        if not profile:
            profile = synthesize_heuristic_profile(intent, target_os=target_os)

        return profile

    def _parse_profile(self, data: dict, target_os: str) -> ToolchainProfile:
        """Convert parsed JSON into typed ToolchainProfile."""
        adapter = data.get("recommended_adapter", "local").lower()
        if adapter not in ("local", "wsl", "remote"):
            adapter = "local"

        prereqs = [
            Prerequisite(
                name=p.get("name", "dependency"),
                min_version=p.get("min_version"),
                description=p.get("description", ""),
                install_command=p.get("install_command", ""),
            )
            for p in data.get("prerequisites", [])
        ]

        steps = []
        for idx, s in enumerate(data.get("install_steps", [])):
            cmd = s.get("command", "echo done")
            if adapter == "wsl":
                from envoyr.executor import normalize_wsl_command
                cmd = normalize_wsl_command(cmd)
            steps.append({
                "order": s.get("order", idx),
                "title": s.get("title", f"Step {idx + 1}"),
                "command": cmd,
                "adapter": adapter,
            })

        smoke_tests = data.get("smoke_tests", [])
        if not smoke_tests:
            smoke_tests = ["echo environment ready"]

        return ToolchainProfile(
            name=data.get("name", "Custom Environment"),
            target_os=target_os,
            recommended_adapter=adapter,
            sources=data.get("sources", ["https://github.com"]),
            compatibility_notes=data.get("compatibility_notes", "Synthesized by Envoyr AI Agent."),
            prerequisites=prereqs,
            install_steps=steps,
            smoke_tests=smoke_tests,
        )

    def diagnose_failure(self, command: str, stderr: str, stdout: str) -> Any | None:
        """Diagnose an unexpected failure using LLM reasoning if configured."""
        if not self.llm_client.is_configured:
            return None
        if HAS_NEATLOGS and neatlogs is not None:
            try:
                with neatlogs.trace("agent_diagnose_failure", kind="AGENT") as span:
                    span.set_attribute("envoyr.command", command[:500])
                    res = self._do_diagnose_failure(command, stderr, stdout)
                    if res:
                        span.set_attribute("envoyr.diagnosis.failure_type", getattr(res, "failure_type", "UNKNOWN"))
                        span.set_attribute("envoyr.diagnosis.can_auto_heal", getattr(res, "can_auto_heal", False))
                    return res
            except Exception:
                return self._do_diagnose_failure(command, stderr, stdout)
        return self._do_diagnose_failure(command, stderr, stdout)

    def _do_diagnose_failure(self, command: str, stderr: str, stdout: str) -> Any | None:
        from envoyr.verifier import HealingDiagnosis
        prompt = (
            f"A command failed during toolchain setup/verification.\n"
            f"Failed Command: {command}\n"
            f"Stderr:\n{stderr[:1500]}\n"
            f"Stdout:\n{stdout[:500]}\n\n"
            f"Analyze the root cause and provide structured remediation with a clear, non-technical explanation for developers."
        )
        system_prompt = (
            "You are Envoyr's diagnostic engine. Respond strictly with JSON in this schema:\n"
            "{\n"
            '  "failure_type": "string (e.g. MISSING_DEPENDENCY, PORT_CONFLICT, CONFIG_ERROR)",\n'
            '  "analysis": "1-2 sentence root cause explanation",\n'
            '  "non_technical_summary": "Plain English, jargon-free explanation for a non-technical user describing what went wrong",\n'
            '  "suggested_fix": "Clear instruction or next step for the developer",\n'
            '  "can_auto_heal": boolean,\n'
            '  "remediation_command": "safe shell command to run if auto-healing is possible, or null"\n'
            "}"
        )
        try:
            data = self.llm_client.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout=20.0,
            )
            if data and isinstance(data, dict) and "analysis" in data:
                return HealingDiagnosis(
                    failure_type=data.get("failure_type", "AI_DIAGNOSED_ERROR"),
                    analysis=data.get("analysis", "Error diagnosed by Envoyr Agent."),
                    suggested_fix=data.get("suggested_fix", "Review error logs and configuration."),
                    can_auto_heal=bool(data.get("can_auto_heal", False)),
                    remediation_command=data.get("remediation_command"),
                    non_technical_summary=data.get("non_technical_summary"),
                )
        except Exception:
            pass
        return None
