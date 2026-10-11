"""Palier B — cohérence statique de la source de santé opt-in `[health].source` (#221).

Même esprit que `test_cycle_lint.py` : aucun modèle. On verrouille que tout prompt (agent ou skill) qui
parle d'Open Wearables pose la garde « `primary` = aucune mention, aucun appel de plus », que la commande
`arc_openwearables.py health-day` n'est citée que dans des fichiers gardés, que le bilan matinal n'écrit
jamais une clé propre à Garmin dans un fichier Open Wearables, et que les cas d'évaluation correspondants
n'ont aucune date en dur.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
# Fichiers qui parlent d'Open Wearables sans devoir porter la garde : le diagnostic (contrôle propre à
# l'installation, ℹ️ « non utilisé » à `primary`) et le contrat de données (schéma des clés, pas une consigne
# de comportement).
EXEMPT = {"skills/coach-doctor/SKILL.md", "skills/workspace-data-contract/SKILL.md"}
MENTION = re.compile(r"arc_openwearables|Open ?Wearables", re.IGNORECASE)
GUARD = re.compile(r"(?i)(never mention|aucune mention|ne jamais mention|never raise|ignore this paragraph)")
GARMIN_ONLY = ("body_battery", "stress_avg", "sleep_score", "readiness_score")


def prompt_files() -> list:
    return sorted(list((REPO / "agents").glob("*.md")) + list((REPO / "skills").glob("*/SKILL.md")))


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def gated_files() -> list:
    return [p for p in prompt_files() if rel(p) not in EXEMPT and MENTION.search(p.read_text(encoding="utf-8"))]


class TestPromptsGateOnPrimary(unittest.TestCase):
    def test_there_are_gated_files(self):
        names = {rel(p) for p in gated_files()}
        for expected in ("agents/coach.md", "agents/medical.md", "skills/garmin-daily-sync/SKILL.md"):
            self.assertIn(expected, names)

    def test_every_prompt_mentioning_open_wearables_gates_on_primary(self):
        for path in gated_files():
            text = path.read_text(encoding="utf-8")
            self.assertIn("[health].source", text, rel(path))
            self.assertIn("primary", text, rel(path))
            self.assertRegex(text, GUARD, f"{rel(path)} : pas de garde « aucune mention à primary »")

    def test_health_day_is_cited_only_in_gated_files(self):
        gated = {rel(p) for p in gated_files()}
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            if "health-day" not in text:
                continue
            name = rel(path)
            self.assertTrue(name in gated or name in EXEMPT, f"{name} cite health-day sans garde [health].source")
            if name in gated:
                # La garde précède la première citation de la commande.
                self.assertLess(text.index("[health].source"), text.index("health-day"), name)

    def test_stamping_rule_lives_outside_the_gated_section(self):
        """`health_source` pour garmin/intervals vaut à `primary` aussi : jamais dans un passage « sans objet à primary »."""
        for name in ("agents/coach.md", "agents/medical.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            m = re.search(r"(?m)^- \*\*(?:Stamp the origin|Origin) of every measurement[^\n]*", text)
            self.assertIsNotNone(m, name)
            self.assertNotRegex(m.group(0), r"(?i)open ?wearables", f"{name} : la règle d'estampille doit être sans mention d'OW")
            self.assertIn("`garmin`", m.group(0), name)
            self.assertIn("`intervals`", m.group(0), name)
            after = {"agents/coach.md": "### MORNING HEALTH CHECK MANDATE", "agents/medical.md": "### DATA MANAGEMENT MANDATES"}[name]
            self.assertGreater(m.start(), text.index(after), f"{name} : l'estampille doit suivre {after}, hors du passage gardé")
            # Déplacée, pas dupliquée : aucune ancienne formulation dans le passage gardé.
            self.assertEqual(len(re.findall(r"Independently of this key|Whatever the source, a health file", text)), 0, name)

    def test_no_garmin_only_key_is_written_in_an_open_wearables_file(self):
        """Les prompts gardés disent que ces clés ne vont jamais dans un fichier Open Wearables."""
        for name in ("agents/coach.md", "agents/medical.md", "skills/garmin-daily-sync/SKILL.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            for key in GARMIN_ONLY:
                self.assertIn(key, text, f"{name} : {key} jamais nommée dans la règle « rien de propre à Garmin »")
            self.assertRegex(text, r"(?i)(get_body_battery)", name)
            self.assertRegex(text, r"(?i)(get_stress_data)", name)

    def test_no_night_is_defined_the_same_way_everywhere(self):
        for name in ("agents/coach.md", "agents/medical.md", "skills/garmin-daily-sync/SKILL.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertIn("sleep_total_s", text, name)
            self.assertIn("hrv_sdnn_ms", text, name)
            self.assertNotIn("no night and no measure", text, name)

    def test_exit_2_is_handled(self):
        for name in ("agents/coach.md", "agents/medical.md", "skills/garmin-daily-sync/SKILL.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertIn("configuration incomplète", text, name)


class TestOpenWearablesEvalCases(unittest.TestCase):
    def test_no_hardcoded_date_in_health_cases(self):
        date = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
        for path in sorted((REPO / "tests" / "evals" / "cases").glob("health-*.toml")):
            self.assertIsNone(date.search(path.read_text(encoding="utf-8")), f"{path.name} : date en dur")

    def test_primary_case_would_catch_a_silent_call(self):
        text = (REPO / "tests" / "evals" / "cases" / "health-primary-no-mention.toml").read_text(encoding="utf-8")
        self.assertRegex(text, r'(?m)^source = "primary"')
        self.assertIn("[stub.openwearables.", text)
        self.assertIn("tools_not_called", text)
        self.assertIn("ow_sleep_summary", text)


if __name__ == "__main__":
    unittest.main()
