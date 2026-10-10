"""Palier B — home trainer / MyWhoosh : opt-in strict (`[home_trainer]` à « off » par
défaut), documenté, et règles de sécurité tenues dans les prompts (aucune mention à
« off », mot de passe jamais dans le chat, aucune écriture MyWhoosh en headless ni
sans « oui » explicite)."""

from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestConfig(unittest.TestCase):
    def test_off_by_default(self):
        conf = tomllib.loads(_read("config/workspace.toml"))
        self.assertEqual(conf["home_trainer"]["platform"], "off")
        self.assertEqual(conf["home_trainer"]["mywhoosh_calendar"], "off")
        self.assertEqual(C.VIRTUAL_PLATFORMS, ("mywhoosh",))

    def test_documented(self):
        doc = _read("docs/configuration.md")
        self.assertIn("[home_trainer]", doc)
        for key in ("platform", "mywhoosh_calendar"):
            self.assertIn(key, doc)
        self.assertIn("[home_trainer].platform", _read("AGENTS.md"))


class TestPrompts(unittest.TestCase):
    def test_coach_gates_on_platform_and_never_mentions_it_off(self):
        coach = _read("agents/coach.md")
        self.assertIn('[home_trainer].platform = "mywhoosh"', coach)
        self.assertRegex(coach, r"at `off`[^.]*never mention")
        self.assertIn("never in headless", coach)
        self.assertIn("mywhoosh-route", coach)

    def test_skill_safety_rules(self):
        skill = _read("skills/mywhoosh-route/SKILL.md")
        self.assertIn('[home_trainer].platform = "mywhoosh"', skill)
        self.assertRegex(skill, r"\*\*jamais\*\* demander le\s+mot de passe dans le chat")
        self.assertIn("jamais en headless", skill)
        self.assertIn("« oui » explicite", skill)
        self.assertIn("arc_index.py power-hr", skill)

    def test_route_in_garmin_workout_documented(self):
        sched = _read("skills/garmin-workout-scheduling/SKILL.md")
        self.assertIn("## Home trainer route (MyWhoosh)", sched)
        self.assertIn("garmin_workout_name", sched)

    def test_contract_skill_documents_new_keys(self):
        contract = _read("skills/workspace-data-contract/SKILL.md")
        for key in ("virtual_route", "avg_power_w", "normalized_power_w"):
            self.assertIn(key, contract)

    def test_profile_template_has_bike_section(self):
        tpl = _read("templates/Runner_Profile.template.md")
        self.assertIn("### Vélo & home trainer", tpl)
        # « Masse du vélo », jamais « Poids … » : le libellé « poids » est celui de l'athlète.
        self.assertFalse(re.search(r"\*\*Poids du v[ée]lo", tpl))


if __name__ == "__main__":
    unittest.main()
