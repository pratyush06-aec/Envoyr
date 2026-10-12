"""Unit tests for Phase 9: Additional Linux-dependent developer toolchains."""

import io
import unittest
from unittest.mock import patch

from envoyr.cli import main
from envoyr.research import research_toolchain


class TestAdditionalToolchains(unittest.TestCase):
    def test_foundry_research_profile_on_windows(self):
        profile = research_toolchain("Configure Foundry Ethereum toolchain", target_os="windows")
        self.assertEqual(profile.name, "Foundry Ethereum Toolchain")
        self.assertEqual(profile.recommended_adapter, "remote")
        self.assertTrue(any("foundry" in s.lower() for s in profile.sources))

        prereq_names = [p.name for p in profile.prerequisites]
        self.assertIn("foundryup", prereq_names)
        self.assertIn("curl", prereq_names)

        self.assertIn("forge --version", profile.smoke_tests)
        self.assertIn("anvil --version", profile.smoke_tests)

    def test_foundry_research_profile_on_linux(self):
        profile = research_toolchain("Install forge and cast", target_os="linux")
        self.assertEqual(profile.recommended_adapter, "local")

    def test_solana_research_profile_on_windows(self):
        profile = research_toolchain("Setup Solana development environment", target_os="windows")
        self.assertEqual(profile.name, "Solana Toolchain")
        self.assertEqual(profile.recommended_adapter, "remote")
        self.assertTrue(any("solana" in s.lower() for s in profile.sources))

        prereq_names = [p.name for p in profile.prerequisites]
        self.assertIn("solana-cli", prereq_names)
        self.assertIn("solana --version", profile.smoke_tests)

    def test_cosmwasm_research_profile_on_windows(self):
        profile = research_toolchain("Setup CosmWasm smart contract environment", target_os="windows")
        self.assertEqual(profile.name, "CosmWasm Toolchain")
        self.assertEqual(profile.recommended_adapter, "remote")
        self.assertTrue(any("cosmwasm" in s.lower() for s in profile.sources))

        prereq_names = [p.name for p in profile.prerequisites]
        self.assertIn("cargo-generate", prereq_names)
        self.assertIn("rust", prereq_names)

    def test_cli_research_foundry(self):
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["research", "Foundry toolchain on Windows"])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Foundry Ethereum Toolchain", output)
            self.assertIn("forge --version", output)

    def test_cli_research_solana(self):
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = main(["research", "Solana environment"])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Solana Toolchain", output)
            self.assertIn("solana --version", output)


if __name__ == "__main__":
    unittest.main()
