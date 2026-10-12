"""Heuristic Fallback Synthesizer for Envoyr.

Generates realistic ToolchainProfile structures when operating offline, in unit tests,
or when no LLM API key is present.
"""

import re
from envoyr.research import Prerequisite, ToolchainProfile


# Heuristic tool registry for common developer toolchains
TOOL_DATABASE: dict[str, dict] = {
    "bun": {
        "name": "Bun Runtime",
        "sources": ["https://bun.sh/docs/installation"],
        "windows_adapter": "local",
        "linux_adapter": "local",
        "notes": "Bun provides native Windows and Linux support.",
        "prereqs": [{"name": "powershell", "description": "PowerShell 5.1+"}],
        "windows_steps": [
            {"order": 0, "title": "Install Bun via official powershell script", "command": "powershell -c \"irm bun.sh/install.ps1 | iex\""},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Bun via official shell script", "command": "curl -fsSL https://bun.sh/install | bash"},
        ],
        "smoke": ["bun --version"],
    },
    "zig": {
        "name": "Zig Compiler & Toolchain",
        "sources": ["https://ziglang.org/learn/getting-started/"],
        "windows_adapter": "local",
        "linux_adapter": "local",
        "notes": "Zig ships standalone portable binaries for Windows and Linux.",
        "prereqs": [{"name": "winget", "description": "Windows Package Manager"}],
        "windows_steps": [
            {"order": 0, "title": "Install Zig compiler via winget", "command": "winget install -e --id zig.zig --silent"},
        ],
        "linux_steps": [
            {"order": 0, "title": "Download and extract Zig", "command": "snap install zig --classic --beta || apt-get install -y zig"},
        ],
        "smoke": ["zig version"],
    },
    "gleam": {
        "name": "Gleam Language",
        "sources": ["https://gleam.run/getting-started/installing-gleam/"],
        "windows_adapter": "local",
        "linux_adapter": "local",
        "notes": "Gleam compiles to Erlang BEAM bytecode or JavaScript.",
        "prereqs": [{"name": "erlang", "description": "Erlang OTP runtime"}],
        "windows_steps": [
            {"order": 0, "title": "Install Gleam compiler via winget", "command": "winget install -e --id Gleam.Gleam --silent"},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Gleam compiler via package manager", "command": "apt-get update && apt-get install -y gleam"},
        ],
        "smoke": ["gleam --version"],
    },
    "elixir": {
        "name": "Elixir & Erlang BEAM",
        "sources": ["https://elixir-lang.org/install.html"],
        "windows_adapter": "local",
        "linux_adapter": "local",
        "notes": "Supported natively across Windows and Linux.",
        "prereqs": [{"name": "erlang", "description": "Erlang OTP runtime"}],
        "windows_steps": [
            {"order": 0, "title": "Install Elixir via winget", "command": "winget install -e --id Elixir.Elixir --silent"},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Elixir and Erlang", "command": "apt-get update && apt-get install -y elixir erlang"},
        ],
        "smoke": ["elixir --version"],
    },
    "midnight": {
        "name": "Midnight Network Toolchain",
        "sources": [
            "https://docs.midnight.network/develop/tutorial/building/prerequisites",
            "https://docs.midnight.network/develop/reference/compact/compiler",
        ],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "notes": "Compact compiler and Midnight proofs require Linux glibc/toolchain. On Windows without Docker Desktop, Remote Linux Worker is recommended.",
        "prereqs": [
            {"name": "build-essential", "description": "C/C++ compilation toolchain"},
            {"name": "rust", "min_version": "1.80.0", "description": "Rust language toolchain"},
            {"name": "compact", "min_version": "0.2.1", "description": "Midnight Compact smart-contract compiler"},
        ],
        "windows_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami"},
            {"order": 1, "title": "Install base build dependencies", "command": "apt-get update && apt-get install -y build-essential pkg-config libssl-dev curl"},
            {"order": 2, "title": "Install Rust toolchain", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"},
            {"order": 3, "title": "Install Midnight Compact CLI", "command": "cargo install --git https://github.com/midnight-ntwrk/compact.git compact-cli"},
            {"order": 4, "title": "Configure PATH and environment", "command": "export PATH=\"$HOME/.cargo/bin:$PATH\""},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install build dependencies", "command": "apt-get update && apt-get install -y build-essential pkg-config libssl-dev curl"},
            {"order": 1, "title": "Install Rust toolchain", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"},
            {"order": 2, "title": "Install Midnight Compact CLI", "command": "cargo install --git https://github.com/midnight-ntwrk/compact.git compact-cli"},
        ],
        "smoke": ["rustc --version", "cargo --version", "compact --version", "compact --help"],
    },
    "foundry": {
        "name": "Foundry Ethereum Toolchain",
        "sources": ["https://book.getfoundry.sh/getting-started/installation"],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "notes": "Foundry toolchain (forge, cast, anvil) is natively optimized for Linux.",
        "prereqs": [
            {"name": "curl", "description": "Command-line data transfer tool"},
            {"name": "git", "description": "Distributed version control system"},
            {"name": "foundryup", "min_version": "1.0.0", "description": "Foundry toolchain installer"},
        ],
        "windows_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami"},
            {"order": 1, "title": "Install base dependencies", "command": "apt-get update && apt-get install -y curl git build-essential"},
            {"order": 2, "title": "Install Foundryup installer", "command": "curl -L https://foundry.paradigm.xyz | bash"},
            {"order": 3, "title": "Execute foundryup", "command": "export PATH=\"$HOME/.foundry/bin:$PATH\" && foundryup"},
            {"order": 4, "title": "Configure PATH in profile", "command": "export PATH=\"$HOME/.foundry/bin:$PATH\""},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Foundry", "command": "curl -L https://foundry.paradigm.xyz | bash && foundryup"},
        ],
        "smoke": ["forge --version", "cast --version", "anvil --version"],
    },
    "solana": {
        "name": "Solana Toolchain",
        "sources": ["https://docs.solanalabs.com/cli/install"],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "notes": "Solana CLI and cargo-build-sbf require Linux toolchains for BPF compilation.",
        "prereqs": [
            {"name": "build-essential", "description": "Base C/C++ compilation toolchain"},
            {"name": "solana-cli", "min_version": "1.18.0", "description": "Solana command-line tools"},
        ],
        "windows_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami"},
            {"order": 1, "title": "Install prerequisite build packages", "command": "apt-get update && apt-get install -y build-essential pkg-config libudev-dev curl"},
            {"order": 2, "title": "Install Solana CLI suite", "command": "sh -c \"$(curl -sSfL https://release.anza.xyz/stable/install)\""},
            {"order": 3, "title": "Configure PATH for Solana binaries", "command": "export PATH=\"$HOME/.local/share/solana/install/active_release/bin:$PATH\""},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Solana CLI", "command": "sh -c \"$(curl -sSfL https://release.anza.xyz/stable/install)\""},
        ],
        "smoke": ["solana --version"],
    },
    "cosmwasm": {
        "name": "CosmWasm Toolchain",
        "sources": ["https://docs.cosmwasm.com/docs/getting-started/installation"],
        "windows_adapter": "remote",
        "linux_adapter": "local",
        "notes": "CosmWasm contract compilation relies on wasm32-unknown-unknown target.",
        "prereqs": [
            {"name": "rust", "min_version": "1.75.0", "description": "Rust language toolchain with wasm32 target"},
            {"name": "cargo-generate", "min_version": "0.18.0", "description": "Cargo project template generator"},
        ],
        "windows_steps": [
            {"order": 0, "title": "Initialize worker environment", "command": "uname -a && whoami"},
            {"order": 1, "title": "Install build tools and curl", "command": "apt-get update && apt-get install -y build-essential curl pkg-config libssl-dev"},
            {"order": 2, "title": "Install Rust and wasm32 target", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && export PATH=\"$HOME/.cargo/bin:$PATH\" && rustup target add wasm32-unknown-unknown"},
            {"order": 3, "title": "Install cargo-generate", "command": "cargo install cargo-generate --features vendored-openssl"},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Rust with wasm32 target", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && rustup target add wasm32-unknown-unknown"},
            {"order": 1, "title": "Install cargo-generate", "command": "cargo install cargo-generate"},
        ],
        "smoke": ["rustc --version", "cargo --version"],
    },
    "rust": {
        "name": "Rust Toolchain",
        "sources": ["https://www.rust-lang.org/tools/install"],
        "windows_adapter": "local",
        "linux_adapter": "local",
        "notes": "Supported natively across Windows, Linux, and macOS.",
        "prereqs": [
            {"name": "rustup", "min_version": "1.27.0", "description": "The Rust toolchain installer"}
        ],
        "windows_steps": [
            {"order": 0, "title": "Install Rustup", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"},
        ],
        "linux_steps": [
            {"order": 0, "title": "Install Rustup", "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"},
        ],
        "smoke": ["rustc --version", "cargo --version"],
    },
}


def synthesize_heuristic_profile(intent: str, target_os: str = "windows") -> ToolchainProfile:
    """Synthesize toolchain profile from intent using heuristic rules."""
    intent_lower = intent.lower()

    # Search for known match
    matched_key = None
    for key in TOOL_DATABASE:
        if key in intent_lower:
            matched_key = key
            break

    if not matched_key:
        # Check aliases
        if any(w in intent_lower for w in ["compact"]):
            matched_key = "midnight"
        elif any(w in intent_lower for w in ["forge", "anvil", "cast"]):
            matched_key = "foundry"
        elif any(w in intent_lower for w in ["agave"]):
            matched_key = "solana"
        elif any(w in intent_lower for w in ["wasmd"]):
            matched_key = "cosmwasm"

    if matched_key and matched_key in TOOL_DATABASE:
        data = TOOL_DATABASE[matched_key]
        is_windows = target_os.lower() == "windows"
        adapter = data["windows_adapter"] if is_windows else data["linux_adapter"]
        raw_steps = data["windows_steps"] if is_windows else data["linux_steps"]

        steps = [
            {
                "order": s["order"],
                "title": s["title"],
                "command": s["command"],
                "adapter": adapter,
            }
            for s in raw_steps
        ]

        prereqs = [
            Prerequisite(
                name=p["name"],
                min_version=p.get("min_version"),
                description=p.get("description", ""),
                install_command=p.get("install_command", ""),
            )
            for p in data["prereqs"]
        ]

        return ToolchainProfile(
            name=data["name"],
            target_os=target_os,
            recommended_adapter=adapter,
            sources=list(data["sources"]),
            compatibility_notes=data["notes"],
            prerequisites=prereqs,
            install_steps=steps,
            smoke_tests=list(data["smoke"]),
        )

    # Completely unknown toolchain: dynamically extract candidate name and build generic profile
    # Example: "Install Mojo programming language" -> name="Mojo"
    words = re.findall(r"\b[A-Za-z0-9_\-\.]+\b", intent)
    skip_words = {"install", "setup", "configure", "environment", "toolchain", "on", "windows", "linux", "dev", "the", "a", "an", "with", "for"}
    candidates = [w for w in words if w.lower() not in skip_words]
    target_tool = candidates[0] if candidates else "custom-tool"
    clean_name = target_tool.capitalize()

    is_windows = target_os.lower() == "windows"
    cmd = (
        f"winget install -e --id {clean_name}.{clean_name} --silent || choco install {target_tool.lower()} -y"
        if is_windows
        else f"apt-get update && apt-get install -y {target_tool.lower()}"
    )

    return ToolchainProfile(
        name=f"{clean_name} Environment",
        target_os=target_os,
        recommended_adapter="local",
        sources=[f"https://github.com/topics/{target_tool.lower()}"],
        compatibility_notes=f"Dynamically generated installation plan for {clean_name}.",
        prerequisites=[Prerequisite(name=target_tool.lower(), description=f"{clean_name} binaries")],
        install_steps=[
            {
                "order": 0,
                "title": f"Install {clean_name}",
                "command": cmd,
                "adapter": "local",
            }
        ],
        smoke_tests=[f"{target_tool.lower()} --version"],
    )
