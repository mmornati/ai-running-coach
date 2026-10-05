"""Palier B — cohérence statique du suivi du cycle menstruel opt-in (#166).

Aucun modèle : on verrouille que (1) les outils `get_menstrual_*` ne sont jamais dans la liste
blanche par défaut, (2) tout prompt qui parle du cycle pose la garde « off = aucune mention »,
et la règle « jamais un assouplissement d'un verdict rouge », (3) le défaut de configuration est
`off`, (4) les noms d'outils cités existent dans le code épinglé de garmin-mcp (vérifiés à la main
dans `src/garmin_mcp/womens_health.py`, ici figés comme valeurs attendues).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TOOLS = ("get_menstrual_data_for_date", "get_menstrual_calendar_data")


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestDefaultsStayOff(unittest.TestCase):
    def test_default_whitelist_has_no_menstrual_tool(self):
        install = read("install.sh")
        m = re.search(r'^GARMIN_TOOL_WHITELIST="([^"]+)"', install, re.M)
        self.assertTrue(m)
        for tool in TOOLS:
            self.assertNotIn(tool, m.group(1).split(","))

    def test_cycle_tools_constant_matches_the_verified_names(self):
        m = re.search(r'^GARMIN_CYCLE_TOOLS="([^"]+)"', read("install.sh"), re.M)
        self.assertTrue(m)
        self.assertEqual(tuple(m.group(1).split(",")), TOOLS)

    def test_whitelist_extension_only_inside_resolve_cycle_tracking(self):
        install = read("install.sh")
        hits = [i for i, line in enumerate(install.splitlines())
                if 'GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,$GARMIN_CYCLE_TOOLS"' in line]
        self.assertEqual(len(hits), 1)
        # Aucune AUTRE extension de la liste blanche que les deux opt-in connus (#166 cycle,
        # #167 nutrition, chacun verrouillé dans son propre lint) : une troisième doit être revue.
        extensions = sorted(line.strip() for line in install.splitlines()
                            if 'GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,' in line)
        self.assertEqual(extensions, sorted([
            'GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,$GARMIN_CYCLE_TOOLS"',
            'GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,$GARMIN_NUTRITION_TOOLS"',
        ]))
        body = install[install.index("resolve_cycle_tracking() {"):]
        self.assertIn('[[ "$CYCLE_TRACKING" == "garmin" ]]', body.split("persist_cycle_tracking")[0])

    def test_shared_config_default_is_off(self):
        self.assertRegex(read("config/workspace.toml"), r'(?m)^cycle_tracking = "off"')

    def test_setup_question_defaults_to_off_and_is_neutral(self):
        text = read("config/setup-questions.toml")
        block = text[text.index("[cycle_tracking]"):]
        self.assertIn('default = "off"', block)
        self.assertNotRegex(block.lower(), r"\b(femme|athlète féminine|madame)\b")


class TestPromptsGateOnOff(unittest.TestCase):
    FILES = ("agents/coach.md", "agents/medical.md", "agents/nutritionist.md",
             "skills/weather-forecast/SKILL.md", "skills/log/SKILL.md", "skills/coach-setup/SKILL.md")

    def test_every_prompt_mentioning_the_cycle_gates_on_off(self):
        for rel in self.FILES:
            text = read(rel)
            self.assertIn("cycle_tracking", text, rel)
            self.assertRegex(text, r"(?i)`off`", rel)
            self.assertRegex(text, r"(?i)(no mention|aucune mention|never raise|never infer|ne tentez jamais|jamais présumée)", rel)

    def test_context_never_rule_never_diagnosis_never_relaxes_red(self):
        coach = read("agents/coach.md")
        self.assertRegex(coach, r"(?i)never a diagnosis")
        self.assertRegex(coach, r"(?i)never.{0,80}relax a verdict")
        medical = read("agents/medical.md")
        self.assertRegex(medical, r"(?i)never relaxes a red verdict|never lowers a bar and never relaxes a red verdict")
        self.assertRegex(medical, r"(?i)never a diagnosis")

    def test_red_s_wording_is_a_vigilance_signal_with_consultation(self):
        medical = read("agents/medical.md")
        self.assertIn("RED-S", medical)
        self.assertRegex(medical, r"(?i)healthcare professional")
        self.assertIn("signal de vigilance", medical)

    def test_menstrual_tools_cited_only_where_gated(self):
        for path in list((REPO / "agents").glob("*.md")) + list((REPO / "skills").glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            if any(t in text for t in TOOLS):
                self.assertIn("cycle_tracking", text, path.name)

    def test_headless_sync_does_not_fetch_cycle_data_itself(self):
        text = read("skills/garmin-daily-sync/SKILL.md")
        for tool in TOOLS:
            self.assertNotIn(tool, text)


class TestDocs(unittest.TestCase):
    def test_page_exists_and_cites_verified_sources_only(self):
        page = read("docs/cycle-menstruel.md")
        self.assertIn("10.1136/bjsports-2023-106994", page)
        self.assertIn("10.1007/s40279-020-01319-3", page)
        self.assertRegex(page, r"(?i)ne remplace pas un avis médical")

    def test_documented_in_config_agents_table_and_nav(self):
        self.assertIn("cycle_tracking", read("AGENTS.md"))
        self.assertIn("cycle_tracking", read("docs/configuration.md"))
        self.assertIn("cycle-menstruel.md", read("mkdocs.yml"))
        self.assertIn("cycle-menstruel.md", read("README.md"))


if __name__ == "__main__":
    unittest.main()
