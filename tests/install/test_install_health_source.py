"""Palier A — santé du bilan matinal chez Open Wearables : `install.sh --health-source` (#220).

Verrouille : la configuration écrite ([health].source, [health.openwearables]) ; la clé d'API en mode 600,
hors dépôt, jamais affichée ni passée en argument ; AUCUN serveur MCP déclaré ni retiré (.mcp.json
inchangé) ; valeurs invalides refusées (dont garmin/strava comme fournisseur) ; retour à `primary` sans
perte de l'URL ni de la clé ; un rerun sans option ne touche à rien ; opt-in strict (aucune mention sans
l'option).
"""

from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

DARWIN = {"ARC_FAKE_UNAME": "Darwin"}
URL = "http://127.0.0.1:8000"
SECRET = "ow_test_SECRET_0123456789abcdef"
BASE = ("--preset", "laptop", "--no-auth")
OW = ("--health-source", "openwearables", "--ow-url", URL, "--ow-provider", "oura")


def _user_toml(sb) -> str:
    path = sb.repo / "config/workspace.user.toml"
    return path.read_text() if path.exists() else ""


def _key_path(sb) -> Path:
    return sb.home / ".config/ai-running-coach/openwearables.key"


def _key_source(sb) -> Path:
    path = sb.root / "ow-key-source.txt"
    path.write_text(SECRET + "\n")
    return path


def _mcp_snapshot(sb) -> dict:
    out = {}
    for name in (".mcp.json", "opencode.json"):
        path = sb.repo / name
        out[name] = path.read_bytes() if path.exists() else None
    return out


class TestHealthSourceInstall(InstallAsserts):

    def test_default_install_writes_nothing_and_says_nothing(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, **DARWIN)
            self.assertSucceeded(proc)
            toml = _user_toml(sb)
            self.assertNotIn("openwearables", toml)
            self.assertNotIn("[health", toml)
            self.assertFalse(_key_path(sb).exists())
            self.assertNotIn("Open Wearables", proc.stdout + proc.stderr)

    def test_dry_run_prints_the_keys_and_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree(sb.home)
            proc = sb.install("--dry-run", "--no-auth", *OW, **DARWIN)
            self.assertSucceeded(proc)
            out = proc.stdout + proc.stderr
            self.assertIn("[health].source = openwearables", out)
            self.assertIn(f"[health.openwearables].base_url = {URL}", out)
            self.assertIn("[health.openwearables].provider = oura", out)
            self.assertIn("Open Wearables (oura)", out)
            self.assertEqual(sb.tree(sb.home), before)
            self.assertNotIn("openwearables", _user_toml(sb))

    def test_install_writes_config_and_key_mode_600_never_printed(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, *OW, "--ow-key-file", str(_key_source(sb)), **DARWIN)
            self.assertSucceeded(proc)
            toml = _user_toml(sb)
            self.assertIn('source = "openwearables"', toml)
            self.assertIn("[health.openwearables]", toml)
            self.assertIn(f'base_url = "{URL}"', toml)
            self.assertIn('provider = "oura"', toml)
            self.assertNotIn(SECRET, toml)
            key = _key_path(sb)
            self.assertEqual(key.read_text().strip(), SECRET)
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertNotIn(SECRET, proc.stdout + proc.stderr)
            self.assertIn("Open Wearables (oura)", proc.stdout + proc.stderr)
            # Jamais dans le dépôt ni dans l'argv de la pile de stubs.
            for path in sb.repo.rglob("*"):
                if path.is_file() and path.suffix in (".json", ".toml", ".env", ".md", ".sh"):
                    self.assertNotIn(SECRET, path.read_text(errors="replace"), str(path))
            self.assertNotIn(SECRET, sb.stub_log.read_text())

    def test_no_mcp_server_declared_or_removed(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, **DARWIN))
            before = _mcp_snapshot(sb)
            self.assertSucceeded(sb.install(*BASE, *OW, "--ow-key-file", str(_key_source(sb)), **DARWIN))
            self.assertEqual(_mcp_snapshot(sb), before)
            mcp = json.loads((sb.repo / ".mcp.json").read_text())
            self.assertFalse([n for n in mcp["mcpServers"] if "wearable" in n.lower()])

    def test_rerun_without_option_keeps_everything_and_does_not_reprompt(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, *OW, "--ow-key-file", str(_key_source(sb)), **DARWIN))
            toml, key = _user_toml(sb), _key_path(sb).read_text()
            proc = sb.install(*BASE, **DARWIN)
            self.assertSucceeded(proc)
            self.assertEqual(_user_toml(sb), toml)
            self.assertEqual(_key_path(sb).read_text(), key)
            self.assertIn("Open Wearables (oura)", proc.stdout + proc.stderr)   # récap : santé config

    def test_user_added_config_is_preserved(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text(
                '[health]\ncycle_tracking = "manual"\n\n[health.openwearables]\nstale_after_h = 12\n')
            self.assertSucceeded(sb.install(*BASE, *OW, **DARWIN))
            toml = _user_toml(sb)
            self.assertIn('cycle_tracking = "manual"', toml)
            self.assertIn("stale_after_h = 12", toml)
            self.assertIn('provider = "oura"', toml)
            self.assertEqual(toml.count("[health.openwearables]"), 1)

    def test_back_to_primary_keeps_url_provider_and_key(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, *OW, "--ow-key-file", str(_key_source(sb)), **DARWIN))
            self.assertSucceeded(sb.install(*BASE, "--health-source", "primary", **DARWIN))
            toml = _user_toml(sb)
            self.assertIn('source = "primary"', toml)
            self.assertIn(f'base_url = "{URL}"', toml)
            self.assertIn('provider = "oura"', toml)
            self.assertEqual(_key_path(sb).read_text().strip(), SECRET)

    def test_missing_key_only_warns_without_a_tty(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, *OW, **DARWIN)
            self.assertSucceeded(proc)
            self.assertFalse(_key_path(sb).exists())
            self.assertIn("Clé d'API Open Wearables absente", proc.stdout + proc.stderr)

    def test_key_prompt_is_silent_on_a_terminal_and_file_is_600(self):
        with Sandbox() as sb:
            proc = sb.run_pty([str(sb.repo / "install.sh"), "--preset", "laptop", "--auth", *OW],
                              answers=[SECRET], timeout=120, **DARWIN)
            key = _key_path(sb)
            # Le pty renvoie en écho ce qu'on lui écrit AVANT que le script coupe l'écho : on ne juge donc
            # que le résultat (clé enregistrée, mode 600, ni dans les stubs ni dans la configuration).
            self.assertTrue(key.exists(), proc.stdout)
            self.assertEqual(key.read_text().strip(), SECRET)
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertNotIn(SECRET, sb.stub_log.read_text())
            self.assertNotIn(SECRET, _user_toml(sb))

    def test_invalid_values_are_refused(self):
        with Sandbox() as sb:
            for args in (
                ("--health-source", "intervals"),
                ("--health-source", "openwearables", "--ow-provider", "oura"),
                ("--health-source", "openwearables", "--ow-url", URL),
                ("--health-source", "openwearables", "--ow-url", "ftp://x", "--ow-provider", "oura"),
                ("--health-source", "openwearables", "--ow-url", "http://u:p@h", "--ow-provider", "oura"),
                ("--health-source", "openwearables", "--ow-url", URL, "--ow-provider", "inconnu"),
                ("--health-source", "primary", "--ow-url", URL),
                ("--ow-url", URL),
                ("--health-source", "openwearables", "--ow-url", URL, "--ow-provider", "oura",
                 "--ow-key-file", "/nonexistent/key"),
            ):
                proc = sb.install("--dry-run", *BASE, *args, **DARWIN)
                self.assertNotEqual(proc.returncode, 0, args)
            self.assertNotIn("openwearables", _user_toml(sb))

    def test_garmin_and_strava_providers_are_refused_with_the_reason(self):
        with Sandbox() as sb:
            proc = sb.install("--dry-run", *BASE, "--health-source", "openwearables", "--ow-url", URL,
                              "--ow-provider", "garmin", **DARWIN)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("en direct", proc.stdout + proc.stderr)
            proc = sb.install("--dry-run", *BASE, "--health-source", "openwearables", "--ow-url", URL,
                              "--ow-provider", "strava", **DARWIN)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("aucune donnée de santé", proc.stdout + proc.stderr)

    def test_provider_list_matches_the_python_module(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import arc_health_source
        text = (Path(__file__).resolve().parents[2] / "install.sh").read_text()
        match = re.search(r'^OW_PROVIDERS="([^"]+)"', text, re.M)
        self.assertEqual(tuple(match.group(1).split()), arc_health_source.PROVIDERS)


class TestHealthSourceReview(InstallAsserts):
    """Corrections de revue (#220)."""

    def test_values_read_back_from_config_are_validated(self):
        for toml in ('[health.openwearables]\nprovider = "garmin"\nbase_url = "http://127.0.0.1:8000"\n',
                     '[health.openwearables]\nprovider = "oura"\nbase_url = "http://u:p@h"\n',
                     '[health.openwearables]\nprovider = "ouraa"\nbase_url = "http://127.0.0.1:8000"\n'):
            with self.subTest(toml=toml), Sandbox() as sb:
                (sb.repo / "config/workspace.user.toml").write_text(toml)
                proc = sb.install("--dry-run", *BASE, "--health-source", "openwearables", **DARWIN)
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_api_key_file_inside_repo_or_workspace_is_refused(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text(
                f'[health.openwearables]\napi_key_file = "{sb.repo}/secrets/ow.key"\n')
            proc = sb.install("--dry-run", *BASE, *OW, **DARWIN)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("hors de l'un comme de l'autre", proc.stdout + proc.stderr)
            self.assertFalse((sb.repo / "secrets").exists())

    def test_present_but_empty_value_wins_over_the_shared_default(self):
        with Sandbox() as sb:
            shared = sb.repo / "config/workspace.toml"
            shared.write_text(shared.read_text().replace(
                'base_url = ""', 'base_url = "http://192.168.1.10:8000"', 1))
            (sb.repo / "config/workspace.user.toml").write_text('[health.openwearables]\nbase_url = ""\n')
            proc = sb.install("--dry-run", *BASE, "--health-source", "openwearables",
                              "--ow-provider", "oura", **DARWIN)
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("--ow-url", proc.stdout + proc.stderr)

    def test_help_lists_the_openwearables_options(self):
        with Sandbox() as sb:
            proc = sb.install("--help", **DARWIN)
            out = proc.stdout + proc.stderr
            for option in ("--health-source", "--ow-url", "--ow-provider", "--ow-key-file"):
                self.assertIn(option, out)

    def test_key_directory_is_created_under_a_private_umask(self):
        text = (Path(__file__).resolve().parents[2] / "install.sh").read_text()
        self.assertIn('( umask 077; mkdir -p "$(dirname "$key_file")" )', text)

    def test_cursor_denies_garmin_health_tools_with_openwearables_and_removes_only_them_on_primary(self):
        health = ("get_hrv_data", "get_rhr_day", "get_sleep_data", "get_training_readiness")
        with Sandbox() as sb:
            (sb.repo / ".cursor").mkdir()
            (sb.repo / ".cursor/cli.json").write_text(json.dumps({"permissions": {"deny": ["Shell(curl)"]}}))
            self.assertSucceeded(sb.install(*BASE, "--ide", "cursor", **DARWIN))
            deny = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]["deny"]
            for tool in health:
                self.assertNotIn(f"Mcp(garmin:{tool})", deny, "défaut : aucun refus santé")
            self.assertSucceeded(sb.install(*BASE, "--ide", "cursor", *OW, **DARWIN))
            deny = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]["deny"]
            for tool in health + ("get_body_battery", "get_stress_data"):
                self.assertIn(f"Mcp(garmin:{tool})", deny)
            self.assertIn("Mcp(garmin:schedule_workouts)", deny)
            # Retour à « primary » : seules ces entrées partent, les règles de l'utilisateur restent.
            self.assertSucceeded(sb.install(*BASE, "--ide", "cursor", "--health-source", "primary", **DARWIN))
            deny = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]["deny"]
            for tool in health:
                self.assertNotIn(f"Mcp(garmin:{tool})", deny)
            self.assertIn("Shell(curl)", deny)
            self.assertIn("Mcp(garmin:schedule_workouts)", deny)
