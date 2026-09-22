"""Palier A — un test par défaut trouvé lors de l'audit de l'installation.

Chaque cas nomme le défaut qu'il verrouille (voir le plan, phase 0).
"""

from __future__ import annotations

import json

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

FOREIGN_OPENCODE_CONFIG = json.dumps(
    {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "un-autre-serveur": {
                "type": "local",
                "command": ["autre-mcp"],
                "enabled": True,
            }
        },
    },
    indent=2,
)


class TestLinkCatalogs(InstallAsserts):
    """0.9 — `.claude/` créé par l'IDE avant l'installation."""

    def test_preexisting_claude_dir_still_gets_agents(self):
        with Sandbox() as sb:
            (sb.repo / ".claude").mkdir()
            proc = sb.install("--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertPopulated(sb.repo / ".claude/agents", minimum=4)
            self.assertPopulated(sb.repo / ".claude/skills", minimum=9)

    def test_preexisting_agents_dir_is_not_nested(self):
        """Un vrai dossier .claude/agents ne doit pas recevoir un lien imbriqué."""
        with Sandbox() as sb:
            (sb.repo / ".claude/agents").mkdir(parents=True)
            proc = sb.install("--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertFalse(
                (sb.repo / ".claude/agents/agents").exists(),
                "lien imbriqué .claude/agents/agents créé",
            )
            self.assertPopulated(sb.repo / ".claude/agents", minimum=4)


class TestMcpConfigMerge(InstallAsserts):
    """0.7 — les écritures de config MCP doivent fusionner, pas remplacer."""

    def test_preserves_foreign_mcp_server(self):
        with Sandbox() as sb:
            cfg = sb.home / ".config/opencode/opencode.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(FOREIGN_OPENCODE_CONFIG)

            self.assertSucceeded(sb.install("--no-auth", "--ide", "opencode"))

            data = json.loads(cfg.read_text())
            self.assertIn("un-autre-serveur", data.get("mcp", {}), f"serveur tiers perdu : {data}")
            self.assertIn("garmin", data.get("mcp", {}), f"serveur garmin absent : {data}")

    def test_mode_switch_keeps_both_servers(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth"), "installation directe")
            self.assertSucceeded(sb.install("--no-auth", "--use-leanproxy"), "bascule passerelle")

            data = json.loads((sb.repo / ".mcp.json").read_text())
            servers = data.get("mcpServers", {})
            self.assertIn("leanproxy", servers, f".mcp.json : {data}")
            self.assertIn("garmin", servers, f"serveur garmin supprimé par la bascule : {data}")


class TestClaudeJsonSafety(InstallAsserts):
    """0.6 — ~/.claude.json est l'état global de l'utilisateur."""

    def test_malformed_claude_json_is_not_destroyed(self):
        with Sandbox() as sb:
            store = sb.home / ".claude.json"
            original = '{"projects": {"a": 1}, oops'
            store.write_text(original)

            proc = sb.install("--no-auth", "--ide", "claude")

            self.assertEqual(
                store.read_text(), original, "~/.claude.json corrompu écrasé sans sauvegarde"
            )
            self.assertOutputContains(proc, ".claude.json")

    def test_backup_written_before_mutation(self):
        with Sandbox() as sb:
            store = sb.home / ".claude.json"
            store.write_text(json.dumps({"projects": {}, "garde": "moi"}))
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))

            self.assertIsFile(sb.home / ".claude.json.bak")
            self.assertEqual(json.loads((sb.home / ".claude.json.bak").read_text())["garde"], "moi")
            self.assertEqual(sb.claude_json()["garde"], "moi", "clés existantes perdues")

    def test_non_ascii_claude_json_survives_c_locale(self):
        with Sandbox() as sb:
            store = sb.home / ".claude.json"
            store.write_text(json.dumps({"projects": {}, "note": "séance à Chamonix"}), encoding="utf-8")
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(sb.claude_json()["note"], "séance à Chamonix")


class TestWorkspacePointer(InstallAsserts):
    """0.4 — le pointeur de workspace pilote le cron déjà installé."""

    def test_pointer_not_clobbered_without_flag(self):
        with Sandbox() as sb:
            pointer = sb.home / ".config/ai-running-coach/workspace"
            pointer.parent.mkdir(parents=True)
            pointer.write_text("/le/vrai/workspace\n")

            self.assertSucceeded(sb.install("--no-auth"))

            self.assertEqual(
                pointer.read_text().strip(),
                "/le/vrai/workspace",
                "une installation sans --workspace a repointé le workspace mémorisé",
            )

    def test_pointer_written_when_flag_given(self):
        with Sandbox() as sb:
            ws = sb.root / "workspace-prive"
            ws.mkdir()
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))
            pointer = sb.home / ".config/ai-running-coach/workspace"
            self.assertEqual(pointer.read_text().strip(), str(ws))

    def test_pointer_created_on_first_run(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth"))
            pointer = sb.home / ".config/ai-running-coach/workspace"
            self.assertEqual(pointer.read_text().strip(), str(sb.repo))


class TestWorkspaceMode(InstallAsserts):
    """0.5 — le .gitignore généré doit couvrir la config personnelle."""

    def test_generated_gitignore_protects_personal_config(self):
        with Sandbox() as sb:
            ws = sb.root / "workspace-prive"
            ws.mkdir()
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))

            gitignore = ws / ".gitignore"
            self.assertFileContains(gitignore, "config/workspace.user.toml")
            self.assertIsFile(ws / "config/workspace.user.toml")

    def test_catalogs_are_populated(self):
        with Sandbox() as sb:
            ws = sb.root / "workspace-prive"
            ws.mkdir()
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))
            self.assertPopulated(ws / "agents", minimum=4)
            self.assertPopulated(ws / "skills", minimum=9)


class TestArgumentParsing(InstallAsserts):
    def test_missing_flag_value_is_a_clean_error(self):
        with Sandbox() as sb:
            proc = sb.install("--ide")
            self.assertFailed(proc, "--ide sans valeur")
            self.assertOutputLacks(proc, "unbound variable")

    def test_unknown_flag_is_rejected(self):
        with Sandbox() as sb:
            proc = sb.install("--nimporte-quoi")
            self.assertFailed(proc)

    def test_help_exits_zero(self):
        with Sandbox() as sb:
            proc = sb.install("--help")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "--workspace")
