"""Palier A — poussée des apports vers Garmin opt-in (#167) : `install.sh --nutrition-sync`.

Verrouille : aucun outil de journal alimentaire/hydratation dans la liste blanche par défaut (liste
exposée = constante historique, à l'identique) ; ajout UNIQUEMENT quand le mode résolu est `ask`
(option explicite OU configuration existante) avec la source Garmin ; un rerun sans option
n'écrit rien et reste idempotent ; repasser à `off` retire les outils ; `--nutrition-sync` est la
seule façon dont l'installeur écrit `[nutrition].garmin_sync` ; valeur invalide refusée ; les outils
destructifs ne sont jamais exposés ; composition avec l'opt-in cycle (#166).
"""

from __future__ import annotations

import json
import re

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import REPO_ROOT, Sandbox

DARWIN = {"ARC_FAKE_UNAME": "Darwin"}
NUTRITION_TOOLS = ("get_custom_foods", "get_custom_food_serving_units", "get_nutrition_daily_food_log",
                   "get_nutrition_daily_meals", "get_hydration_data", "create_custom_food", "log_custom_food",
                   "log_food", "add_hydration_data")
NEVER_EXPOSED = ("delete_food_log", "update_custom_food", "upsert_and_log")


def _tools(sb) -> list:
    mcp = json.loads((sb.repo / ".mcp.json").read_text())
    return mcp["mcpServers"]["garmin"]["env"]["GARMIN_ENABLED_TOOLS"].split(",")


def _user_toml(sb) -> str:
    path = sb.repo / "config/workspace.user.toml"
    return path.read_text() if path.exists() else ""


class TestNutritionSyncInstall(InstallAsserts):

    def test_default_install_exposes_no_nutrition_tool_and_writes_no_key(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in NUTRITION_TOOLS:
                self.assertNotIn(tool, _tools(sb))
            self.assertNotIn("garmin_sync", _user_toml(sb))

    def test_default_whitelist_is_exactly_the_constant(self):
        constant = re.search(r'^GARMIN_TOOL_WHITELIST="([^"]+)"', (REPO_ROOT / "install.sh").read_text(), re.M).group(1)
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            self.assertEqual(",".join(_tools(sb)), constant)

    def test_explicit_ask_adds_the_tools_and_persists_the_key(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--nutrition-sync", "ask", **DARWIN))
            for tool in NUTRITION_TOOLS:
                self.assertIn(tool, _tools(sb))
            for tool in NEVER_EXPOSED:
                self.assertNotIn(tool, _tools(sb))
            self.assertIn('garmin_sync = "ask"', _user_toml(sb))

    def test_rerun_without_option_is_idempotent_and_keeps_the_opt_in(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--nutrition-sync", "ask", **DARWIN))
            first, toml = _tools(sb), _user_toml(sb)
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            self.assertEqual(_tools(sb), first)
            self.assertEqual(_user_toml(sb), toml)
            self.assertEqual(_user_toml(sb).count("garmin_sync"), 1)

    def test_config_set_by_hand_is_honoured_without_the_option_and_writes_nothing(self):
        with Sandbox() as sb:
            hand = '[nutrition]\ngarmin_sync = " ASK "\n'
            (sb.repo / "config/workspace.user.toml").write_text(hand)
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in NUTRITION_TOOLS:
                self.assertIn(tool, _tools(sb))
            self.assertEqual(_user_toml(sb).count("garmin_sync"), 1)

    def test_back_to_off_removes_the_tools(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--nutrition-sync", "ask", **DARWIN))
            self.assertSucceeded(sb.install("--preset", "laptop", "--nutrition-sync", "off", **DARWIN))
            for tool in NUTRITION_TOOLS:
                self.assertNotIn(tool, _tools(sb))
            self.assertIn('garmin_sync = "off"', _user_toml(sb))

    def test_invalid_config_value_is_treated_as_off_never_a_failure(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text('[nutrition]\ngarmin_sync = "oui"\n')
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in NUTRITION_TOOLS:
                self.assertNotIn(tool, _tools(sb))

    def test_invalid_cli_value_is_refused(self):
        with Sandbox() as sb:
            self.assertNotEqual(sb.install("--preset", "laptop", "--nutrition-sync", "auto", **DARWIN).returncode, 0)

    def test_intervals_source_exposes_nothing_and_succeeds(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--source", "intervals", "--nutrition-sync", "ask", **DARWIN))
            self.assertNotIn("create_custom_food", (sb.repo / ".mcp.json").read_text())

    def test_strava_source_exposes_nothing_says_why_and_succeeds(self):
        """#164 : Strava n'a ni journal alimentaire ni hydratation — rien d'exposé, et l'installeur le dit."""
        with Sandbox() as sb:
            proc = sb.install("--source", "strava", "--nutrition-sync", "ask", "--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            mcp = (sb.repo / ".mcp.json").read_text()
            for tool in NUTRITION_TOOLS:
                self.assertNotIn(tool, mcp)
            self.assertIn("indisponible avec [data].source = « strava »", proc.stdout + proc.stderr)
            self.assertIn('garmin_sync = "ask"', _user_toml(sb))

    def test_composes_with_cycle_tracking(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--cycle-tracking", "garmin",
                                            "--nutrition-sync", "ask", **DARWIN))
            self.assertIn("get_menstrual_data_for_date", _tools(sb))
            self.assertIn("log_food", _tools(sb))


class TestNutritionSyncRefusedBehindLeanproxy(InstallAsserts):
    """La passerelle ne permet pas d'interdire les écritures en headless (outil unique `invoke_tool`) :
    `ask` n'y expose jamais les outils nutrition."""

    def _leanproxy_yaml(self, sb) -> str:
        path = sb.home / ".config/leanproxy_servers.yaml"
        return path.read_text() if path.exists() else ""

    def test_explicit_ask_with_leanproxy_is_refused_before_any_write(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--use-leanproxy", "--nutrition-sync", "ask", **DARWIN)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("leanproxy", proc.stdout + proc.stderr)
            self.assertNotIn("garmin_sync", _user_toml(sb))
            self.assertNotIn("log_food", self._leanproxy_yaml(sb))

    def test_config_ask_with_leanproxy_exposes_nothing_and_succeeds(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text('[nutrition]\ngarmin_sync = "ask"\n')
            proc = sb.install("--preset", "laptop", "--use-leanproxy", **DARWIN)
            self.assertSucceeded(proc)
            yaml = self._leanproxy_yaml(sb)
            self.assertIn("GARMIN_ENABLED_TOOLS", yaml)
            for tool in NUTRITION_TOOLS:
                self.assertNotIn(tool, yaml)
