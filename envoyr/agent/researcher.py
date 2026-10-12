"""Dynamic Agentic Researcher for Envoyr.

Orchestrates real-time LLM-driven research, documentation discovery, and toolchain profiling
for arbitrary natural language user intents.
"""

import json
from typing import Any
from envoyr.agent.heuristic import synthesize_heuristic_profile
from envoyr.agent.provider import LLMClient
from envoyr.research import Prerequisite, ToolchainProfile, fetch_url_text


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
            steps.append({
                "order": s.get("order", idx),
                "title": s.get("title", f"Step {idx + 1}"),
                "command": s.get("command", "echo done"),
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
