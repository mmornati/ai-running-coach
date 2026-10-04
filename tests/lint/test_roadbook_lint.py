"""Palier B — roadbook imprimable (#187) : parité docs / prompts / contrat / feuille d'impression.

Lecture statique, aucun modèle ni réseau. Verrouille ce qu'un oubli casserait en silence : la vue
documentée, le prompt du stratège qui annonce le roadbook et les clés `take`/`emergency` qu'il doit
écrire, le contrat qui les accepte, et la feuille d'impression (A4, sans navigation, jetons forcés
en clair) sans laquelle un PDF sortirait sombre.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestRoadbookDocs(unittest.TestCase):
    def test_views_documents_the_roadbook_view(self):
        views = read("docs/dashboard/views.md")
        self.assertRegex(views, r"(?m)^## Roadbook$")
        self.assertIn("window.print()", views)
        self.assertIn("| Roadbook |", views)
        self.assertIn("#/roadbook", views)

    def test_strategist_prompt_and_doc_announce_the_roadbook(self):
        for rel in ("agents/course-strategist.md", "docs/agents/course-strategist.md"):
            text = read(rel)
            with self.subTest(file=rel):
                self.assertIn("#/roadbook", text)
                self.assertIn("`take`", text)
                self.assertIn("`emergency`", text)

    def test_contract_accepts_and_documents_the_new_keys(self):
        skill = read("skills/workspace-data-contract/SKILL.md")
        code = read("scripts/arc_contract.py")
        for key in ("take", "emergency", "notes", "nutrition_plan"):
            self.assertIn(f"`{key}`", skill, key)
            self.assertIn(f'"{key}"', code, key)

    def test_readme_lists_the_feature(self):
        self.assertIn("Roadbook imprimable", read("README.md"))


class TestRoadbookWiring(unittest.TestCase):
    def test_route_and_trail_shape_link(self):
        app = read("web/js/app.js")
        self.assertRegex(app, r"roadbook: viewRoadbook")
        self.assertIn('href="#/roadbook"', app)
        self.assertIn('from "./roadbook.js"', app)

    def test_api_route_registered(self):
        self.assertIn('"/api/roadbook": api_roadbook', read("scripts/arc_serve.py"))

    def test_page_script_is_csp_clean_and_local(self):
        js = read("web/js/roadbook.js")
        self.assertNotRegex(js, r"\sstyle\s*=")
        self.assertNotRegex(js, r"https?://")
        self.assertIn("window.print()", js)


class TestPrintStylesheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        css = read("web/css/app.css")
        start = css.index("@media print {")
        cls.print_css = css[start:]

    def test_a4_portrait_page(self):
        self.assertIn("@page { size: A4 portrait;", self.print_css)

    def test_chrome_is_hidden(self):
        hidden = re.search(r"([^{}]*)\{\s*display:\s*none\s*!important;?\s*\}", self.print_css)
        self.assertIsNotNone(hidden)
        for sel in (".top", ".nav", ".rb-controls"):
            self.assertIn(sel, hidden.group(1))

    def test_theme_tokens_are_forced_light_whatever_the_screen_theme(self):
        self.assertRegex(self.print_css, r':root\[data-theme="dark"\]')
        self.assertIn("--bg: #fff", self.print_css)
        self.assertIn("--ink: #000", self.print_css)

    def test_one_scenario_per_page_when_printing_all(self):
        self.assertRegex(self.print_css, r"\.rb-all \.rb-sheet\s*\{[^}]*break-before:\s*page")

    def test_tables_stay_readable_across_pages(self):
        self.assertIn("table-header-group", self.print_css)
        self.assertRegex(self.print_css, r"\.rb-table tr\s*\{\s*break-inside:\s*avoid")
        self.assertRegex(self.print_css, r"font-size:\s*(8\.5|9|9\.5|10)pt")


if __name__ == "__main__":
    unittest.main()
