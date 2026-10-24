"""Palier B — skills `shoe-selection` et `shoes` (#302) : frontmatter, commande Gemini générée,
référencement (AGENTS.md, index des skills, nav mkdocs, pages de doc, README, coach) et garde-fous de
comportement qui n'existent que par le prompt : interactif uniquement, jamais d'achat/prix/affiliation,
mention médicale (veto `medical` seulement s'il est activé), sources et types obligatoires, aucune valeur
inventée, le confort décide, jamais une prévention de blessure, rien d'écrit sans l'accord de l'athlète.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def front(text: str) -> str:
    return re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL).group(1)


SEL = read("skills/shoe-selection/SKILL.md")
CMD = read("skills/shoes/SKILL.md")


class TestFrontmatter(unittest.TestCase):
    def test_selection_is_a_plain_skill(self):
        f = front(SEL)
        self.assertRegex(f, r"(?m)^name: shoe-selection$")
        self.assertNotIn("gemini_command", f, "la commande courte est le skill `shoes`")
        self.assertLessEqual(len(re.search(r"(?m)^description: (.*)$", f).group(1)), 1024)

    def test_shoes_is_the_short_command(self):
        f = front(CMD)
        self.assertRegex(f, r"(?m)^name: shoes$")
        self.assertRegex(f, r'(?m)^gemini_command: "true"$')
        self.assertLessEqual(len(re.search(r"(?m)^description: (.*)$", f).group(1)), 1024)

    def test_gemini_command_is_generated_from_the_skill(self):
        toml = read("config/gemini/commands/shoes.toml")
        self.assertIn("skills/shoes/SKILL.md", toml)
        self.assertIn("# `/shoes [rôle]`", toml)
        self.assertFalse((REPO / "config/gemini/commands/shoe-selection.toml").exists())


class TestReferenced(unittest.TestCase):
    def test_agents_md_docs_nav_readme(self):
        agents = read("AGENTS.md")
        self.assertIn("- `shoes` —", agents)
        self.assertIn("- `shoe-selection` —", agents)
        self.assertIn("`/shoes` (#302)", agents)
        for rel in ("docs/skills.md", "mkdocs.yml"):
            self.assertIn("skills/shoes.md", read(rel))
            self.assertIn("skills/shoe-selection.md", read(rel))
        self.assertTrue((REPO / "docs/skills/shoes.md").is_file())
        self.assertTrue((REPO / "docs/skills/shoe-selection.md").is_file())
        self.assertIn("/shoes", read("README.md"))
        self.assertIn('href="skills/shoes/"', read("docs/index.md"))
        self.assertIn("## Choisir la prochaine paire : `/shoes`", read("docs/shoes.md"))

    def test_coach_mandate_is_based_on_the_skill(self):
        coach = read("agents/coach.md")
        section = coach[coach.index("### SHOE SUGGESTION MANDATE"):coach.index("### WEATHER-AWARE PLANNING")]
        for needle in ("`shoe-selection`", "/shoes", "shoe-usage", "shoe-specs", "shoe-needs",
                       "Only when the profile declares **at least 2 non-retired pairs**",
                       "ONE short line « Chaussures :", "never headless", "No purchase, no affiliate link, no price",
                       "never presented as injury prevention", "ce n'est pas un avis médical"):
            self.assertIn(needle, section)
        self.assertIn("`shoe-selection`", read("config/gemini/commands/coach.toml"))
        self.assertIn("| `shoes` |", coach)
        self.assertIn("| `shoe-selection` |", coach)


class TestGuardrails(unittest.TestCase):
    def test_interactive_only_never_headless_never_setup(self):
        for text in (SEL, CMD):
            self.assertRegex(text, r"(?i)interactive? uniquement")
            self.assertIn("headless", text)
            self.assertRegex(text, r"(?i)ne propose jamais `/coach-setup`")
        self.assertIn("garmin-daily-sync", SEL)

    def test_no_purchase_no_affiliate_no_price(self):
        for text in (SEL, CMD):
            self.assertRegex(text, r"(?i)aucun achat")
            self.assertRegex(text, r"(?i)lien d'affiliation")
            self.assertRegex(text, r"(?i)\bprix\b")

    def test_never_presented_as_injury_prevention_and_not_medical_advice(self):
        self.assertRegex(SEL, r"(?i)jamais une prévention de blessure")
        self.assertRegex(SEL, r"(?i)ce n'est pas un avis médical")
        self.assertRegex(SEL, r"(?i)corrélation, pas causalité")

    def test_medical_veto_only_if_enabled(self):
        self.assertIn("`medical` figure dans `[agents].enabled`", SEL)
        self.assertRegex(SEL, r"(?i)lui déléguer")
        self.assertRegex(SEL, r"(?i)veto[\s\S]{0,60}respecté")
        self.assertRegex(SEL, r"(?i)`medical` n'est pas dans `\[agents\]\.enabled`[\s\S]{0,80}ne pas l'appeler ni le mentionner")
        self.assertIn("Respond in", SEL)

    def test_sources_and_types_are_mandatory_and_nothing_is_invented(self):
        self.assertRegex(SEL, r"(?i)aucune caractéristique inventée")
        self.assertIn("`measured`", SEL)
        self.assertIn("`manufacturer`", SEL)
        self.assertRegex(SEL, r"(?i)url consultée")
        self.assertRegex(SEL, r"(?i)`retrieved`")
        self.assertRegex(SEL, r"(?i)la mesure prime sur la marque")
        self.assertRegex(SEL, r"(?i)jamais\s+estimée ni reprise d'un modèle voisin")
        self.assertRegex(SEL, r"(?i)introuvable")
        self.assertRegex(SEL, r"(?i)jamais de scraping automatisé")

    def test_comfort_decides_and_break_in_and_rotation(self):
        self.assertIn("Essayer en magasin : le confort décide", SEL)
        self.assertRegex(SEL, r"(?i)30 à 50 km")
        self.assertRegex(SEL, r"(?i)approximation du projet")
        self.assertRegex(SEL, r"(?i)au moins 2 paires")
        self.assertRegex(SEL, r"confort\s+→\s+continuité\s+→\s+garde-fous\s+blessures\s+→\s+adéquation\s+au\s+terrain")

    def test_continuity_first_with_version_comparison(self):
        self.assertIn("would_rebuy = yes", SEL)
        self.assertIn("comfort_overall >= 7", SEL)
        self.assertIn("version actuelle du même modèle", SEL)
        self.assertRegex(SEL, r"(?i)comparer toujours")
        self.assertIn("yes_with_change", SEL)
        self.assertIn("change_wanted", SEL)
        self.assertLess(SEL.index("## 2. Continuité d'abord"), SEL.index("## 3. Sinon"))

    def test_search_path_uses_ranges_and_three_to_five_models(self):
        self.assertIn("arc_index.py shoe-needs --role R", SEL)
        self.assertRegex(SEL, r"3 à 5 modèles")
        self.assertRegex(SEL, r"(?i)écarts aux plages signalés")
        lab = SEL.index("RunRepeat")
        self.assertLess(lab, SEL.index("page de la marque", lab))

    def test_only_cli_json_is_consumed(self):
        for cmd in ("shoe-needs", "shoe-specs", "shoe-feedback", "shoe-usage", "inspections", "arc_index.py gear"):
            self.assertIn(cmd, SEL)
        self.assertRegex(SEL, r"(?i)ne calcule rien")

    def test_nothing_written_without_the_athletes_ok(self):
        self.assertRegex(SEL, r"(?i)aucune écriture dans `gear/` avant l'\*\*accord explicite\*\*")
        self.assertRegex(SEL, r"(?i)sans oui explicite, rien n'est écrit")
        self.assertIn("athlete_validated: true", SEL)
        self.assertIn("gear/AAAA-MM-JJ_shoe_recommendation_<rôle>.md", SEL)
        self.assertIn("workspace-data-contract", SEL)
        self.assertIn("arc_index.py --validate", SEL)

    def test_role_resolution_never_guesses(self):
        self.assertRegex(SEL, r"(?i)jamais de devinette")
        self.assertRegex(CMD, r"(?i)jamais de devinette")
        for role in ("trail_long", "trail", "road_easy", "road_tempo", "race", "mixed_long", "mixed"):
            self.assertIn(f"`{role}`", SEL)

    def test_no_forbidden_science_claims(self):
        text = SEL + CMD
        self.assertNotRegex(text, r"(?i)pronation[\s\S]{0,40}(prescri|choisir la stabilit)")
        self.assertRegex(SEL, r"(?i)pas de prescription par type de pied")
        self.assertRegex(SEL, r"(?i)à \*\*surveiller\*\* après le\s+changement, jamais un critère de choix")


class TestContractDocs(unittest.TestCase):
    def test_contract_skill_documents_the_kind(self):
        contract = read("skills/workspace-data-contract/SKILL.md")
        self.assertIn("### `shoe_recommendation`", contract)
        self.assertIn("`shoe_recommendation` | `gear/YYYY-MM-DD_shoe_recommendation_<rôle>.md`", contract)
        self.assertIn("shoe_recommendation", read("docs/skills/workspace-data-contract.md"))


if __name__ == "__main__":
    unittest.main()
