"""Documentation Research Engine for Envoyr.

Derives toolchain requirements, OS compatibility matrices, prerequisite
dependencies, and verification smoke tests from authoritative sources.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field


@dataclass
class Prerequisite:
    name: str
    min_version: str | None = None
    description: str = ""
    install_command: str = ""


@dataclass
class ToolchainProfile:
    name: str
    target_os: str
    recommended_adapter: str  # local, wsl, remote
    sources: list[str] = field(default_factory=list)
    compatibility_notes: str = ""
    prerequisites: list[Prerequisite] = field(default_factory=list)
    install_steps: list[dict] = field(default_factory=list)
    smoke_tests: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


# Curated upstream knowledge base for rapid offline derivation
# shortcut: offline curated registry; upgrade to dynamic web-agent scraper in Phase 9
KNOWN_PROFILES: dict[str, dict] = {
    "midnight": {
        "name": "Midnight Network Toolchain",
        "sources": [
            "https://docs.midnight.network/develop/tutorial/building/prerequisites",
            "https://docs.midnight.network/develop/reference/compact/compiler",
        ],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "compatibility_notes": "Compact compiler and Midnight proofs require Linux glibc/toolchain. On Windows without Docker Desktop, Remote Linux Worker is recommended.",
        "prerequisites": [
            {"name": "build-essential", "description": "C/C++ compilation toolchain", "install_command": "apt-get update && apt-get install -y build-essential pkg-config libssl-dev"},
            {"name": "curl", "description": "Command-line tool for transferring data", "install_command": "apt-get install -y curl"},
            {"name": "rust", "min_version": "1.80.0", "description": "Rust language toolchain", "install_command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"},
            {"name": "compact", "min_version": "0.2.1", "description": "Midnight Compact smart-contract compiler", "install_command": "cargo install --git https://github.com/midnight-ntwrk/compact.git compact-cli"},
        ],
        "install_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami", "adapter": "remote"},
            {"order": 1, "title": "Install base build dependencies", "command": "apt-get update && apt-get install -y build-essential pkg-config libssl-dev curl", "adapter": "remote"},
            {"order": 2, "title": "Install Rust toolchain", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y", "adapter": "remote"},
            {"order": 3, "title": "Install Midnight Compact CLI", "command": "cargo install --git https://github.com/midnight-ntwrk/compact.git compact-cli", "adapter": "remote"},
            {"order": 4, "title": "Configure PATH and environment", "command": "export PATH=\"$HOME/.cargo/bin:$PATH\"", "adapter": "remote"},
        ],
        "smoke_tests": [
            "rustc --version",
            "cargo --version",
            "compact --version",
        ],
    },
    "rust": {
        "name": "Rust Toolchain",
        "sources": ["https://www.rust-lang.org/tools/install"],
        "windows_adapter": "local",
        "linux_adapter": "local",
        "compatibility_notes": "Supported natively across Windows, Linux, and macOS.",
        "prerequisites": [
            {"name": "rustup", "min_version": "1.27.0", "description": "The Rust toolchain installer", "install_command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"}
        ],
        "install_steps": [
            {"order": 0, "title": "Install Rustup", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y", "adapter": "local"}
        ],
        "smoke_tests": ["rustc --version", "cargo --version"],
    },
}


def fetch_url_text(url: str, timeout_sec: float = 3.0) -> str | None:
    """Safely fetch text from an authoritative upstream URL."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Envoyr-Research-Engine/0.1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # Strip tags and normalize whitespace
            text = re.sub(r"<[^>]+>", " ", raw)
            return " ".join(text.split())
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def research_toolchain(intent: str, target_os: str = "windows") -> ToolchainProfile:
    """Analyze natural-language setup intent and generate evidence-grounded profile."""
    intent_lower = intent.lower()

    key = "midnight" if "midnight" in intent_lower or "compact" in intent_lower else "rust"
    raw = KNOWN_PROFILES.get(key, KNOWN_PROFILES["rust"])

    recommended_adapter = (
        raw["windows_adapter"] if target_os.lower() == "windows" else raw["linux_adapter"]
    )

    prereqs = [
        Prerequisite(
            name=p["name"],
            min_version=p.get("min_version"),
            description=p.get("description", ""),
            install_command=p.get("install_command", ""),
        )
        for p in raw["prerequisites"]
    ]

    # Map steps adapting to the selected adapter
    steps = []
    for s in raw["install_steps"]:
        step_dict = dict(s)
        step_dict["adapter"] = recommended_adapter
        steps.append(step_dict)

    return ToolchainProfile(
        name=raw["name"],
        target_os=target_os,
        recommended_adapter=recommended_adapter,
        sources=list(raw["sources"]),
        compatibility_notes=raw["compatibility_notes"],
        prerequisites=prereqs,
        install_steps=steps,
        smoke_tests=list(raw["smoke_tests"]),
    )
