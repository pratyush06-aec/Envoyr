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
            "compact --help",
        ],
    },
    "foundry": {
        "name": "Foundry Ethereum Toolchain",
        "sources": [
            "https://book.getfoundry.sh/getting-started/installation",
        ],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "compatibility_notes": "Foundry toolchain (forge, cast, anvil) is natively optimized for Linux. On Windows, Remote Linux Worker or WSL is recommended.",
        "prerequisites": [
            {"name": "curl", "description": "Command-line data transfer tool", "install_command": "apt-get install -y curl"},
            {"name": "git", "description": "Distributed version control system", "install_command": "apt-get install -y git"},
            {"name": "foundryup", "min_version": "1.0.0", "description": "Foundry toolchain installer", "install_command": "curl -L https://foundry.paradigm.xyz | bash"},
        ],
        "install_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami", "adapter": "remote"},
            {"order": 1, "title": "Install base dependencies", "command": "apt-get update && apt-get install -y curl git build-essential", "adapter": "remote"},
            {"order": 2, "title": "Install Foundryup installer", "command": "curl -L https://foundry.paradigm.xyz | bash", "adapter": "remote"},
            {"order": 3, "title": "Execute foundryup", "command": "export PATH=\"$HOME/.foundry/bin:$PATH\" && foundryup", "adapter": "remote"},
            {"order": 4, "title": "Configure PATH in profile", "command": "export PATH=\"$HOME/.foundry/bin:$PATH\"", "adapter": "remote"},
        ],
        "smoke_tests": [
            "forge --version",
            "cast --version",
            "anvil --version",
        ],
    },
    "solana": {
        "name": "Solana Toolchain",
        "sources": [
            "https://docs.solanalabs.com/cli/install",
        ],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "compatibility_notes": "Solana CLI and cargo-build-sbf require Linux toolchains for Berkeley Packet Filter compilation.",
        "prerequisites": [
            {"name": "build-essential", "description": "Base C/C++ compilation toolchain", "install_command": "apt-get install -y build-essential pkg-config libudev-dev"},
            {"name": "curl", "description": "Command-line data transfer tool", "install_command": "apt-get install -y curl"},
            {"name": "solana-cli", "min_version": "1.18.0", "description": "Solana command-line tools", "install_command": "sh -c \"$(curl -sSfL https://release.anza.xyz/stable/install)\""},
        ],
        "install_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami", "adapter": "remote"},
            {"order": 1, "title": "Install prerequisite build packages", "command": "apt-get update && apt-get install -y build-essential pkg-config libudev-dev curl", "adapter": "remote"},
            {"order": 2, "title": "Install Solana CLI suite", "command": "sh -c \"$(curl -sSfL https://release.anza.xyz/stable/install)\"", "adapter": "remote"},
            {"order": 3, "title": "Configure PATH for Solana binaries", "command": "export PATH=\"$HOME/.local/share/solana/install/active_release/bin:$PATH\"", "adapter": "remote"},
        ],
        "smoke_tests": [
            "solana --version",
        ],
    },
    "cosmwasm": {
        "name": "CosmWasm Toolchain",
        "sources": [
            "https://docs.cosmwasm.com/docs/getting-started/installation",
        ],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "compatibility_notes": "CosmWasm smart contract compilation relies on wasm32-unknown-unknown target and cargo-generate.",
        "prerequisites": [
            {"name": "rust", "min_version": "1.75.0", "description": "Rust language toolchain with wasm32 target", "install_command": "rustup target add wasm32-unknown-unknown"},
            {"name": "cargo-generate", "min_version": "0.18.0", "description": "Cargo project template generator", "install_command": "cargo install cargo-generate"},
        ],
        "install_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami", "adapter": "remote"},
            {"order": 1, "title": "Install build tools and curl", "command": "apt-get update && apt-get install -y build-essential curl pkg-config libssl-dev", "adapter": "remote"},
            {"order": 2, "title": "Install Rust and wasm32 target", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && export PATH=\"$HOME/.cargo/bin:$PATH\" && rustup target add wasm32-unknown-unknown", "adapter": "remote"},
            {"order": 3, "title": "Install cargo-generate", "command": "cargo install cargo-generate --features vendored-openssl", "adapter": "remote"},
        ],
        "smoke_tests": [
            "rustc --version",
            "cargo --version",
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
    """Analyze natural-language setup intent and generate evidence-grounded profile.

    Delegates to dynamic AgentResearcher (which leverages live LLM reasoning
    when configured, or intelligent heuristic synthesis when offline).
    """
    from envoyr.agent.researcher import AgentResearcher

    researcher = AgentResearcher()
    return researcher.research(intent, target_os=target_os)
