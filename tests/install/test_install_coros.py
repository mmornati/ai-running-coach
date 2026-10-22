"""Palier A — montre COROS : `install.sh --coros` déclare le relais MCP local pour toutes les IA.

Verrouille : sans l'option, rien n'est écrit ni dit (opt-in strict) ; avec, le serveur `coros`
pointe vers `scripts/arc_coros_mcp.py` dans chaque config d'IA, à côté de la source (jamais à sa
place), est approuvé pour Claude Code et `[coros].mcp = "relay"` est écrit ; aucune connexion
n'est lancée sans terminal (le message dit la commande à lancer) ; un rerun sans option garde le
relais ; `--no-coros` le retire, mais jamais une entrée `coros` ajoutée à la main (URL + OAuth du
client) ; `--dry-run` n'écrit rien.
"""

from __future__ import annotations

import json

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

DARWIN = {"ARC_FAKE_UNAME": "Darwin"}
BASE = ("--preset", "laptop", "--no-auth")


def _servers(path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data.get("mcpServers") or data.get("mcp") or {}


def _user_toml(sb) -> str:
    path = sb.repo / "config/workspace.user.toml"
    return path.read_text() if path.exists() else ""


class TestCorosInstall(InstallAsserts):

    def test_default_install_has_no_coros(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, **DARWIN)
            self.assertSucceeded(proc)
            self.assertNotIn("coros", _servers(sb.repo / ".mcp.json"))
            self.assertNotIn("[coros]", _user_toml(sb))
            self.assertNotIn("COROS", proc.stdout + proc.stderr)

    def test_coros_declares_the_relay_next_to_the_source(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--source", "intervals", "--coros", **DARWIN)
            self.assertSucceeded(proc)
            servers = _servers(sb.repo / ".mcp.json")
            self.assertIn("intervals", servers)
            self.assertTrue(servers["coros"]["command"].endswith("scripts/arc_coros_mcp.py"))
            self.assertNotIn("url", servers["coros"])
            self.assertIn('mcp = "relay"', _user_toml(sb))
            out = proc.stdout + proc.stderr
            self.assertIn("arc_coros_auth.py login", out)
            self.assertIn("Serveur MCP coros approuvé", out)

    def test_rerun_keeps_and_no_coros_removes_only_our_relay(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--coros", **DARWIN))
            self.assertSucceeded(sb.install(*BASE, **DARWIN))
            self.assertIn("coros", _servers(sb.repo / ".mcp.json"))
            self.assertSucceeded(sb.install(*BASE, "--no-coros", **DARWIN))
            self.assertNotIn("coros", _servers(sb.repo / ".mcp.json"))
            self.assertIn('mcp = "off"', _user_toml(sb))

    def test_no_coros_keeps_a_hand_added_coros_server(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, **DARWIN))
            cfg = sb.repo / ".mcp.json"
            data = json.loads(cfg.read_text())
            data["mcpServers"]["coros"] = {"type": "http", "url": "https://mcpeu.coros.com/mcp"}
            cfg.write_text(json.dumps(data))
            self.assertSucceeded(sb.install(*BASE, "--no-coros", **DARWIN))
            self.assertEqual(_servers(cfg)["coros"]["url"], "https://mcpeu.coros.com/mcp")

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree(sb.home)
            proc = sb.install("--dry-run", "--no-auth", "--coros", **DARWIN)
            self.assertSucceeded(proc)
            self.assertIn("[coros].mcp = relay", proc.stdout + proc.stderr)
            self.assertEqual(sb.tree(sb.home), before)
            self.assertNotIn("coros", _servers(sb.repo / ".mcp.json"))
