"""Palier A — suivi du cycle menstruel opt-in (#166) : `install.sh --cycle-tracking`.

Verrouille : aucun outil `get_menstrual_*` dans la liste blanche par défaut ; ajout
UNIQUEMENT quand le mode résolu est `garmin` (option explicite OU configuration existante) ;
un rerun sans option ne touche ni n'ajoute rien de plus que ce que dit la configuration ;
repasser à `off` retire les outils ; `--cycle-tracking` est la seule façon dont l'installeur
écrit `[health].cycle_tracking` ; valeur invalide refusée.
"""

from __future__ import annotations

import json

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

DARWIN = {"ARC_FAKE_UNAME": "Darwin"}
CYCLE_TOOLS = ("get_menstrual_data_for_date", "get_menstrual_calendar_data")


def _tools(sb) -> list:
    mcp = json.loads((sb.repo / ".mcp.json").read_text())
    return mcp["mcpServers"]["garmin"]["env"]["GARMIN_ENABLED_TOOLS"].split(",")


def _user_toml(sb) -> str:
    path = sb.repo / "config/workspace.user.toml"
    return path.read_text() if path.exists() else ""


class TestCycleTrackingInstall(InstallAsserts):

    def test_default_install_exposes_no_menstrual_tool_and_writes_no_key(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertNotIn(tool, _tools(sb))
            self.assertNotIn("cycle_tracking", _user_toml(sb))

    def test_explicit_garmin_adds_the_two_tools_and_persists_the_key(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--cycle-tracking", "garmin", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertIn(tool, _tools(sb))
            self.assertNotIn("get_pregnancy_summary", _tools(sb))
            self.assertIn('cycle_tracking = "garmin"', _user_toml(sb))

    def test_rerun_without_option_is_idempotent_and_keeps_the_opt_in(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--cycle-tracking", "garmin", **DARWIN))
            first = _tools(sb)
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            self.assertEqual(_tools(sb), first)
            self.assertEqual(_user_toml(sb).count("cycle_tracking"), 1)

    def test_config_set_by_hand_is_honoured_without_the_option(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text('[health]\ncycle_tracking = "garmin"\n')
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertIn(tool, _tools(sb))

    def test_back_to_off_removes_the_tools(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--cycle-tracking", "garmin", **DARWIN))
            self.assertSucceeded(sb.install("--preset", "laptop", "--cycle-tracking", "off", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertNotIn(tool, _tools(sb))
            self.assertIn('cycle_tracking = "off"', _user_toml(sb))

    def test_manual_mode_exposes_no_tool(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--cycle-tracking", "manual", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertNotIn(tool, _tools(sb))
            self.assertIn('cycle_tracking = "manual"', _user_toml(sb))

    def test_invalid_config_value_is_treated_as_off_never_a_failure(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text('[health]\ncycle_tracking = "oui"\n')
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertNotIn(tool, _tools(sb))

    def test_invalid_cli_value_is_refused(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--cycle-tracking", "peut-etre", **DARWIN)
            self.assertNotEqual(proc.returncode, 0)

    def test_default_whitelist_is_exactly_the_constant(self):
        # Revue #166 : sans opt-in, la liste exposée est À L'IDENTIQUE la constante historique —
        # aucun outil ajouté, retiré ni réordonné pour un utilisateur existant.
        import re
        constant = re.search(r'^GARMIN_TOOL_WHITELIST="([^"]+)"',
                             (self.repo_root() / "install.sh").read_text(), re.M).group(1)
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            self.assertEqual(",".join(_tools(sb)), constant)

    def test_config_value_is_case_insensitive_like_arc_cycle(self):
        # Revue #166 : « Garmin » vaut « garmin » pour scripts/arc_cycle.py (les agents) — l'installeur
        # doit exposer les mêmes outils, sinon les agents les appelleraient sans qu'ils existent.
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text('[health]\ncycle_tracking = " Garmin "\n')
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for tool in CYCLE_TOOLS:
                self.assertIn(tool, _tools(sb))

    def test_garmin_mode_with_intervals_source_exposes_nothing_and_succeeds(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--source", "intervals", "--cycle-tracking", "garmin", **DARWIN)
            self.assertSucceeded(proc)
            self.assertNotIn("get_menstrual", (sb.repo / ".mcp.json").read_text())

    @staticmethod
    def repo_root():
        from tests.lib.sandbox import REPO_ROOT
        return REPO_ROOT
