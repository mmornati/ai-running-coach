"""Palier A — montre COROS : `install.sh --coros` déclare le relais MCP local pour toutes les IA.

Verrouille : sans l'option, rien n'est écrit ni dit (opt-in strict) ; avec, le serveur `coros`
pointe vers `scripts/arc_coros_mcp.py` dans chaque config d'IA, à côté de la source (jamais à sa
place), est approuvé pour Claude Code et `[coros].mcp = "relay"` est écrit ; aucune connexion
n'est lancée sans terminal (le message dit la commande à lancer) ; un rerun sans option garde le
relais ; `--no-coros` le retire, mais jamais une entrée `coros` ajoutée à la main (URL + OAuth du
client) ; `--dry-run` n'écrit rien. En synchronisation sans tête, les 7 outils d'écriture COROS
sont refusés par leur nom pour chaque exécuteur (Claude, Copilot, OpenCode, Cursor) et OpenCode
lance le relais en lecture seule ; sans relais, rien n'est ajouté.
"""

from __future__ import annotations

import json
import re

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


COROS_WRITES = {"createScheduledWorkout", "updateScheduledWorkout", "scheduleWorkout", "createSingleWorkout",
                "updateWorkoutDetails", "createTrainingPlan", "updateTrainingPlan"}


class TestCorosHeadlessSync(InstallAsserts):

    def _sync(self, sb, runner):
        return sb.script("daily-sync.sh", "--dry-run", "--runner", runner, ARC_WORKSPACE=str(sb.repo))

    def test_every_runner_denies_coros_writes(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--source", "intervals", "--coros", **DARWIN))
            deny = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]["deny"]
            self.assertTrue({f"Mcp(coros:{t})" for t in COROS_WRITES} <= set(deny))
            out = self._sync(sb, "claude").stdout
            self.assertEqual(set(re.findall(r"mcp__coros__(\w+)", out)), COROS_WRITES)
            self.assertNotIn("mcp__coros,", out)
            out = self._sync(sb, "copilot").stdout
            self.assertEqual(set(re.findall(r"--deny-tool=coros\((\w+)\)", out)), COROS_WRITES)
            out = self._sync(sb, "opencode").stdout
            config = json.JSONDecoder().raw_decode(out[out.index("{", out.index("contenu :")):])[0]
            self.assertEqual(config["mcp"]["coros"]["environment"]["COROS_READ_ONLY"], "1")
            self.assertTrue({f"coros_{t}" for t in COROS_WRITES} <= {k for k, v in config["permission"].items() if v == "deny"})

    def test_without_relay_nothing_about_coros(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--source", "intervals", **DARWIN))
            self.assertNotIn("coros", self._sync(sb, "claude").stdout)
            self.assertNotIn("coros", self._sync(sb, "copilot").stdout)


class TestCorosSource(InstallAsserts):
    """`--source coros` (#168) : le relais devient le serveur primaire, comme garmin-mcp pour Garmin."""

    def test_source_coros_makes_the_relay_primary(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--source", "coros", **DARWIN)
            self.assertSucceeded(proc)
            servers = _servers(sb.repo / ".mcp.json")
            self.assertTrue(servers["coros"]["command"].endswith("scripts/arc_coros_mcp.py"))
            for other in ("garmin", "intervals", "strava"):
                self.assertNotIn(other, servers)
            toml = _user_toml(sb)
            self.assertIn('source = "coros"', toml)
            self.assertIn('mcp = "relay"', toml)
            self.assertIn("arc_coros_auth.py login", proc.stdout + proc.stderr)
            # Cursor : les écritures de la source COROS refusées une seule fois (pas de doublon relais).
            deny = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]["deny"]
            self.assertTrue({f"Mcp(coros:{t})" for t in COROS_WRITES} <= set(deny))
            coros_denies = [d for d in deny if d.startswith("Mcp(coros:")]
            self.assertEqual(len(coros_denies), len(set(coros_denies)))

    def test_switching_to_coros_removes_garmin_and_back(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, **DARWIN))
            self.assertIn("garmin", _servers(sb.repo / ".mcp.json"))
            self.assertSucceeded(sb.install(*BASE, "--source", "coros", **DARWIN))
            servers = _servers(sb.repo / ".mcp.json")
            self.assertNotIn("garmin", servers)
            self.assertIn("coros", servers)
            # Retour à Garmin : le relais reste (montre COROS gardée, [coros].mcp = "relay").
            self.assertSucceeded(sb.install(*BASE, "--source", "garmin", **DARWIN))
            servers = _servers(sb.repo / ".mcp.json")
            self.assertIn("garmin", servers)
            self.assertIn("coros", servers)

    def test_no_coros_is_refused_with_source_coros(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--source", "coros", "--no-coros", **DARWIN)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("--no-coros est incompatible avec --source coros", proc.stdout + proc.stderr)

    def test_dry_run_mentions_the_fit_reader_and_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree(sb.home)
            proc = sb.install("--dry-run", "--no-auth", "--source", "coros", **DARWIN)
            self.assertSucceeded(proc)
            out = proc.stdout + proc.stderr
            self.assertIn("fit-reader", out)
            self.assertIn("[coros].mcp = relay", out)
            self.assertEqual(sb.tree(sb.home), before)


class TestCorosSourceHeadlessSync(InstallAsserts):

    def _sync(self, sb, runner):
        return sb.script("daily-sync.sh", "--dry-run", "--runner", runner, ARC_WORKSPACE=str(sb.repo))

    def test_claude_reads_coros_and_never_writes(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--source", "coros", **DARWIN))
            proc = self._sync(sb, "claude")
            self.assertSucceeded(proc)
            out = proc.stdout
            self.assertIn("mcp__coros,", out)
            self.assertEqual(set(re.findall(r"mcp__coros__(\w+)", out)), COROS_WRITES)
            for other in ("mcp__garmin", "mcp__intervals", "mcp__leanproxy"):
                self.assertNotIn(other, out)
            self.assertIn("Synchronisation COROS", out)

    def test_copilot_and_gemini_and_opencode(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--source", "coros", **DARWIN))
            out = self._sync(sb, "copilot").stdout
            self.assertIn("--allow-tool=coros", out)
            denies = re.findall(r"--deny-tool=coros\((\w+)\)", out)
            self.assertEqual(sorted(denies), sorted(COROS_WRITES))  # une seule fois chacun
            out = self._sync(sb, "opencode").stdout
            config = json.JSONDecoder().raw_decode(out[out.index("{", out.index("contenu :")):])[0]
            self.assertEqual(config["mcp"]["coros"]["environment"]["COROS_READ_ONLY"], "1")
            self.assertNotIn("garmin", config["mcp"])

    def test_openwearables_health_denies_coros_health_tools(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--source", "coros", **DARWIN))
            with open(sb.repo / "config/workspace.user.toml", "a") as fh:
                fh.write('\n[health]\nsource = "openwearables"\n\n[health.openwearables]\nprovider = "oura"\n')
            out = self._sync(sb, "claude").stdout
            for tool in ("querySleepHrv", "queryRestingHeartRate", "queryRecoveryStatus", "querySleepOverview"):
                self.assertIn(f"mcp__coros__{tool}", out)
            self.assertNotIn("mcp__coros__querySportRecords", out)

    def test_trigger_accepts_a_coros_activity_id(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--source", "coros", **DARWIN))
            proc = sb.script("daily-sync.sh", "--dry-run", "--runner", "claude",
                             "--trigger", "morning,activity:c481221836600803431", ARC_WORKSPACE=str(sb.repo))
            self.assertSucceeded(proc)
            self.assertIn("trigger=morning,activity:c481221836600803431", proc.stdout)


class TestCorosChatPolicy(InstallAsserts):
    """Chat (#168) : lectures COROS permises, écritures soumises à l'approbation de l'athlète."""

    def test_reads_allowed_writes_ask(self):
        import sys
        import tempfile
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo / "scripts"))
        from arc_chat_policy import Policy
        with tempfile.TemporaryDirectory() as tmp:
            policy = Policy.load(repo, Path(tmp).resolve())
            for tool in ("querySportRecords", "querySleepHrv", "queryRecoveryStatus", "getActivityDetail",
                         "queryTrainingSchedule"):
                self.assertEqual(policy.decide(f"mcp:coros.{tool}", {}), "allow", tool)
            for tool in COROS_WRITES | {"downloadActivityFitFiles"}:
                self.assertEqual(policy.decide(f"mcp:coros.{tool}", {}), "ask", tool)
