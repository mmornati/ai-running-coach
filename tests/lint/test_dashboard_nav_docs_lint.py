"""Palier B — parité nav/docs du tableau de bord (#50, nit de revue de code).

Aucun modèle, aucun réseau : lecture statique de `web/js/app.js` et de
`docs/dashboard/views.md`. Attrape la classe de bug que cette PR (#50) a
introduite en pratique : une entrée de nav ajoutée (« Analyse ») sans que la
documentation soit mise à jour au même moment — ici, les deux évoluent
ensemble, un futur oubli échouerait avant la revue plutôt qu'après.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
APP_JS = REPO / "web/js/app.js"
VIEWS_MD = REPO / "docs/dashboard/views.md"

# Routes de `ROUTES` (`web/js/app.js`) qui ne sont volontairement PAS des entrées
# de nav directes : atteintes par un lien depuis une autre vue plutôt que par
# l'onglet de gauche. `views.md` les documente quand même, ailleurs que par une
# entrée de nav (`## Rapports` couvre `rapport`, la fiche d'un rapport précis ;
# `## Décisions` couvre `decision`, le détail d'une décision précise (#55), même
# motif ; `fichiers` a son propre titre malgré son libellé de nav construit
# dynamiquement, voir NAV_LABEL_OVERRIDES ci-dessous).
ROUTES_WITHOUT_NAV_ENTRY = {"rapport", "fichiers", "decision"}

# `fichiers` n'a pas de libellé fixe dans `renderNav` (construit avec le nombre de
# fichiers hors contrat, `${s.incomplete_files} fichier(s) hors contrat`) — son
# titre de doc réel ne peut donc pas être lu depuis `items`.
NAV_LABEL_OVERRIDES = {"fichiers": "Fichiers hors contrat"}


def _nav_items() -> list[tuple[str, str]]:
    """Extrait `[route, libellé]` du tableau `items` de `renderNav` (`web/js/app.js`)
    — jamais une liste recopiée à la main, qui divergerait silencieusement du vrai
    tableau de nav à la première entrée ajoutée sans mettre ce test à jour."""
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const items = \[(.*?)\];", source, re.DOTALL)
    assert match, "tableau `items` de renderNav introuvable dans web/js/app.js"
    return re.findall(r'\["([a-z]*)", "([^"]+)"\]', match.group(1))


def _routes_keys() -> list[str]:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const ROUTES = \{(.*?)\n\};", source, re.DOTALL)
    assert match, "table ROUTES introuvable dans web/js/app.js"
    return re.findall(r'(?:^|[,{]\s*)"?([a-zA-Z]*)"?\s*:', match.group(1))


def _doc_headings() -> set[str]:
    return set(re.findall(r"^## (.+)$", VIEWS_MD.read_text(encoding="utf-8"), re.MULTILINE))


class TestDashboardNavDocsParity(unittest.TestCase):
    def test_every_nav_label_has_a_matching_heading_in_views_md(self):
        headings = _doc_headings()
        for route, label in _nav_items():
            self.assertIn(label, headings,
                          f"entrée de nav « {label} » (#/{route}) sans « ## {label} » dans docs/dashboard/views.md")

    def test_every_route_is_a_nav_entry_or_a_known_sub_route(self):
        nav_routes = {route for route, _ in _nav_items()}
        for key in _routes_keys():
            self.assertTrue(key in nav_routes or key in ROUTES_WITHOUT_NAV_ENTRY,
                            f"route ROUTES.{key!r} n'est ni une entrée de nav ni dans ROUTES_WITHOUT_NAV_ENTRY "
                            "(tests/lint/test_dashboard_nav_docs_lint.py) — nouvelle route à documenter/classer")

    def test_fichiers_override_still_matches_a_heading(self):
        """`fichiers` (nav dynamique, jamais un libellé fixe) : verrouillé séparément
        via `NAV_LABEL_OVERRIDES` plutôt que d'échapper silencieusement au test
        ci-dessus faute de libellé extractible."""
        headings = _doc_headings()
        for route, label in NAV_LABEL_OVERRIDES.items():
            self.assertIn(label, headings, f"« {label} » (#/{route}) sans « ## {label} » dans docs/dashboard/views.md")


if __name__ == "__main__":
    unittest.main()
