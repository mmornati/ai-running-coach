"""Palier A — source de données `--source strava` (#164).

Verrouille : le serveur MCP est enregistré via le WRAPPER du projet (jamais `npx` en direct ni un
secret dans la config), la source est persistée, un rerun est idempotent, le changement de source
retire l'ancienne entrée, `--use-leanproxy` est refusé, `--dry-run` n'écrit rien, et les
installations garmin / intervals existantes restent strictement inchangées.
"""

from __future__ import annotations

import json
import subprocess

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox
from tests.install.test_install_source import _mcp_servers, _source


class TestSourceStrava(InstallAsserts):
    def test_registers_the_wrapper_not_npx_and_no_secret(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "strava", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("strava", servers)
            self.assertNotIn("garmin", servers)
            self.assertNotIn("intervals", servers)
            self.assertTrue(servers["strava"]["command"].endswith("strava-mcp/run.sh"), servers["strava"])
            self.assertNotIn("env", servers["strava"])
            wrapper = sb.home / ".config/ai-running-coach/strava-mcp/run.sh"
            self.assertIsFile(wrapper)
            self.assertTrue(wrapper.stat().st_mode & 0o111, "wrapper non exécutable")
            text = wrapper.read_text(encoding="utf-8")
            self.assertIn("exec npx -y @r-huijts/strava-mcp-server@1.2.1", text)
            self.assertIn('"$@"', text)
            # cron/launchd (PATH minimal, Node.js de nvm absent) : le dossier de npx est figé.
            stubs = STUBS_DIR.resolve()
            self.assertIn("export PATH=", text)
            self.assertIn(str(stubs), text.replace("\\", ""))
            check = subprocess.run(["bash", "-n", str(wrapper)], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_persists_source_and_rerun_is_idempotent(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "strava", "--no-auth", "--ide", "claude"))
            self.assertEqual(_source(sb), "strava")
            first = (sb.repo / ".mcp.json").read_text(encoding="utf-8")
            toml = (sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8")
            # Rerun SANS --source : ne revient jamais à garmin, ne réécrit rien d'autre.
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_source(sb), "strava")
            self.assertEqual((sb.repo / ".mcp.json").read_text(encoding="utf-8"), first)
            self.assertEqual((sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8"), toml)
            self.assertEqual(toml.count("[data]"), 1)

    def test_no_python_tooling_is_installed(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "strava", "--no-auth", "--ide", "claude"))
            log = sb.stub_log.read_text(encoding="utf-8")
            self.assertNotIn("uv\t", log, "uv n'a rien à faire pour la source strava")
            self.assertNotIn("garmin_mcp", log)
            self.assertNotIn("intervals-icu-mcp", log)

    def test_cycle_tracking_garmin_with_strava_exposes_no_tool_and_says_why(self):
        """#166 × #164 : Strava n'a aucune donnée de cycle — pas de serveur garmin, pas d'outil
        get_menstrual_*, un avertissement propre à Strava (pas un conseil « intervals »)."""
        with Sandbox() as sb:
            result = sb.install("--source", "strava", "--cycle-tracking", "garmin", "--no-auth", "--ide", "claude")
            self.assertSucceeded(result)
            self.assertEqual(set(_mcp_servers(sb)), {"strava"})
            self.assertNotIn("get_menstrual", (sb.repo / ".mcp.json").read_text(encoding="utf-8"))
            self.assertIn("Strava n'expose aucune donnée de cycle", result.stdout + result.stderr)

    def test_leanproxy_rejected_with_strava_source(self):
        with Sandbox() as sb:
            proc = sb.install("--source", "strava", "--use-leanproxy", "--no-auth", "--dry-run")
            self.assertFailed(proc, "--use-leanproxy + --source strava aurait dû être rejeté")
            self.assertOutputContains(proc, "strava")

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "strava", "--dry-run", "--ide", "claude"))
            self.assertFalse((sb.repo / ".mcp.json").exists())
            self.assertFalse((sb.repo / "config/workspace.user.toml").exists())
            self.assertFalse((sb.home / ".config/ai-running-coach/strava-mcp/run.sh").exists())

    def test_missing_node_is_an_explicit_failure(self):
        with Sandbox() as sb:
            proc = sb.install("--source", "strava", "--no-auth", "--ide", "claude", hide=("node", "npx"))
            self.assertFailed(proc, "node absent aurait dû faire échouer l'installation")
            self.assertOutputContains(proc, "Node.js")

    def test_connect_instructions_are_printed_when_not_connected(self):
        with Sandbox() as sb:
            proc = sb.install("--source", "strava", "--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "connect-strava")

    def test_already_connected_account_is_recognised_and_untouched(self):
        with Sandbox() as sb:
            tokens = sb.home / ".config/strava-mcp/config.json"
            tokens.parent.mkdir(parents=True)
            tokens.write_text('{"accessToken": "A", "refreshToken": "R"}', encoding="utf-8")
            proc = sb.install("--source", "strava", "--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "déjà connecté")
            self.assertEqual(json.loads(tokens.read_text()), {"accessToken": "A", "refreshToken": "R"})


class TestSwitchingWithStrava(InstallAsserts):
    def test_garmin_to_strava_removes_garmin(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertSucceeded(sb.install("--source", "strava", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("strava", servers)
            self.assertNotIn("garmin", servers)

    def test_strava_to_garmin_and_to_intervals_remove_the_wrapper_entry(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "strava", "--no-auth", "--ide", "claude"))
            self.assertSucceeded(sb.install("--source", "garmin", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("garmin", servers)
            self.assertNotIn("strava", servers)
            self.assertSucceeded(sb.install("--source", "strava", "--no-auth", "--ide", "claude"))
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("intervals", servers)
            self.assertNotIn("strava", servers)

    def test_hand_added_official_connector_entry_survives_a_plain_garmin_rerun(self):
        """Le connecteur officiel (`claude mcp add --transport http strava-mcp …`) s'ajoute à la
        main : un rerun d'install.sh ne doit jamais l'effacer."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            cfg = sb.repo / ".mcp.json"
            data = json.loads(cfg.read_text())
            data["mcpServers"]["strava"] = {"type": "http", "url": "https://mcp.strava.com/mcp"}
            cfg.write_text(json.dumps(data))
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_mcp_servers(sb)["strava"]["url"], "https://mcp.strava.com/mcp")


class TestGarminAndIntervalsUnchanged(InstallAsserts):
    def test_default_install_has_no_strava_trace(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertNotIn("strava", _mcp_servers(sb))
            self.assertNotIn("[data]", (sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8"))
            self.assertFalse((sb.home / ".config/ai-running-coach/strava-mcp").exists())

    def test_intervals_install_has_no_strava_trace(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            self.assertEqual(sorted(_mcp_servers(sb)), ["intervals"])
            self.assertFalse((sb.home / ".config/ai-running-coach/strava-mcp").exists())
