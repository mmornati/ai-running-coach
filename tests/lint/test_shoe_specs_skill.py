"""Palier B — skill `shoe-specs` (#298) : frontmatter, référencement (AGENTS.md, index des skills, nav
mkdocs, page de doc, coach, commande Gemini générée) et garde-fous de comportement qui n'existent que
par le prompt : aucune écriture sans validation ligne par ligne, jamais en headless, aucune valeur
inventée ni reprise d'un modèle voisin, version jamais devinée, recherche à la demande sans scraping,
ordre laboratoire -> marque -> revendeurs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills/shoe-specs/SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")
FRONT = re.match(r"\A---\n(.*?)\n---\n", TEXT, re.DOTALL).group(1)


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestShoeSpecsSkill(unittest.TestCase):
    def test_frontmatter(self):
        self.assertRegex(FRONT, r"(?m)^name: shoe-specs$")
        description = re.search(r"(?m)^description: (.*)$", FRONT).group(1)
        self.assertLessEqual(len(description), 1024)
        self.assertNotIn("gemini_command", FRONT, "ce n'est pas une commande courte")

    def test_referenced_everywhere(self):
        self.assertIn("- `shoe-specs` —", read("AGENTS.md"))
        self.assertIn("skills/shoe-specs.md", read("docs/skills.md"))
        self.assertIn("skills/shoe-specs.md", read("mkdocs.yml"))
        self.assertIn("shoes.md", read("mkdocs.yml"))
        self.assertTrue((REPO / "docs/skills/shoe-specs.md").is_file())
        self.assertTrue((REPO / "docs/shoes.md").is_file())
        self.assertIn("shoes.md", read("docs/workspace.md"))
        self.assertIn("`shoe-specs`", read("agents/coach.md"))
        self.assertIn("`shoe-specs`", read("config/gemini/commands/coach.toml"))

    def test_no_write_without_line_by_line_validation(self):
        self.assertRegex(TEXT, r"(?i)aucune écriture sans validation")
        self.assertRegex(TEXT, r"(?i)validation ligne par ligne|ligne par ligne")
        self.assertRegex(TEXT, r"(?i)seulement alors")
        self.assertRegex(TEXT, r"(?i)un « ok » global")

    def test_never_headless_and_interactive_only(self):
        self.assertRegex(TEXT, r"(?i)jamais en headless")
        self.assertIn("garmin-daily-sync", TEXT)
        self.assertRegex(TEXT, r"(?i)interactif uniquement")

    def test_no_invented_value_and_no_neighbour_model_value(self):
        self.assertRegex(TEXT, r"(?i)aucune valeur inventée")
        self.assertRegex(TEXT, r"(?i)reste \*\*absente\*\*|restera absente")
        self.assertRegex(TEXT, r"(?i)jamais reprise d'un modèle voisin")
        self.assertRegex(TEXT, r"(?i)indice[\s\S]{0,120}jamais persistée")

    def test_version_is_never_guessed(self):
        self.assertRegex(TEXT, r"(?i)date de lancement")
        self.assertRegex(TEXT, r"(?i)date\s+d'achat")
        self.assertRegex(TEXT, r"(?i)jamais de devinette")

    def test_search_order_lab_then_brand_then_retailers(self):
        lab = TEXT.index("RunRepeat")
        self.assertIn("RTINGS", TEXT)
        brand = TEXT.index("Page de la marque")
        retail = TEXT.index("revendeurs", brand)
        self.assertLess(lab, brand)
        self.assertLess(brand, retail)
        self.assertRegex(TEXT, r"(?i)1 à 2 revendeurs")

    def test_on_demand_web_search_without_scraping(self):
        self.assertRegex(TEXT, r"(?i)à la demande")
        self.assertRegex(TEXT, r"(?i)pas de scraping automatisé")
        self.assertRegex(TEXT, r"(?i)conditions d'utilisation de RunRepeat")

    def test_validation_table_shows_source_type_and_spread(self):
        for needle in ("Valeur proposée", "Source (URL)", "Type", "Écart entre sources", "aberration",
                       "measured", "manufacturer", "la mesure prime sur la marque", "écart marque/labo"):
            self.assertIn(needle, TEXT)

    def test_questions_cover_the_assisted_entry(self):
        for needle in ("Marque", "modèle exact", "Version ou année", "Pointure", "Date d'achat",
                       "étiquette de languette"):
            self.assertIn(needle, TEXT)

    def test_writes_the_contract_file_and_validates_it(self):
        self.assertIn("gear/specs/<gear_id>.md", TEXT)
        self.assertIn("workspace-data-contract", TEXT)
        self.assertIn("arc_index.py --validate", TEXT)
        self.assertIn("arc_index.py shoe-specs", TEXT)

    def test_minimalist_index_is_athlete_scored_and_never_partial(self):
        self.assertIn("Esculier", TEXT)
        self.assertRegex(TEXT, r"(?i)indisponible")
        self.assertRegex(TEXT, r"(?i)jamais une valeur\s+partielle")

    def test_no_purchase_advice(self):
        self.assertRegex(TEXT, r"(?i)aucun lien d'affiliation")
        self.assertRegex(TEXT, r"(?i)ni un avis médical")

    def test_skill_does_not_cite_a_function_the_agent_cannot_call(self):
        self.assertNotIn("select_value", TEXT)
        self.assertRegex(TEXT, r"(?i)priorité : ce que l'athlète a choisi")

    def test_athlete_keeps_the_brand_value_path_is_documented(self):
        self.assertIn('`basis: "manufacturer"`', TEXT)
        self.assertRegex(TEXT, r"(?i)la mesure ET la valeur de la marque")
        self.assertIn("`basis`", read("skills/workspace-data-contract/SKILL.md"))

    def test_one_sheet_per_pair_and_profile_flag_are_documented(self):
        self.assertRegex(TEXT, r"(?i)une seule fiche par paire")
        self.assertIn("in_profile", TEXT)
        self.assertIn("unknown_gear", TEXT)

    def test_coach_wiring_keeps_the_guardrails(self):
        coach = read("agents/coach.md")
        section = coach[coach.index("### SHOE SPEC SHEETS"):coach.index("### GEAR INSPECTION MANDATE")]
        for needle in ("interactive only", "line-by-line validation", "never headless", "Never invent"):
            self.assertIn(needle, section)

    def test_docs_shoes_keeps_the_evidence_placeholder_for_the_next_story(self):
        self.assertIn("## Ce que disent les preuves", read("docs/shoes.md"))


if __name__ == "__main__":
    unittest.main()
