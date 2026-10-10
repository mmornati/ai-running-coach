"""Palier B — cohérence de la carte « Home trainer » : la route `/api/power-hr` existe côté serveur,
est documentée dans la vue Matériel, et la carte du tableau de bord l'appelle."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_serve  # noqa: E402


def read(rel):
    return " ".join((REPO / rel).read_text(encoding="utf-8").split())   # retours à la ligne neutralisés


class TestPowerHrSurfaces(unittest.TestCase):
    def test_route_registered(self):
        self.assertIn("/api/power-hr", arc_serve.ROUTES)
        self.assertIs(arc_serve.ROUTES["/api/power-hr"], arc_serve.api_power_hr)

    def test_documented_in_views(self):
        views = read("docs/dashboard/views.md")
        self.assertIn("### Home trainer", views)
        self.assertIn("python3 scripts/arc_index.py power-hr", views)
        self.assertIn("/api/power-hr", views)
        self.assertIn("approximation du projet", views)
        # La sous-section vit sous « ## Matériel », avant la vue suivante.
        self.assertLess(views.index("## Matériel"), views.index("### Home trainer"))
        self.assertLess(views.index("### Home trainer"), views.index("## Trail Shape"))

    def test_dashboard_card_calls_route(self):
        app = read("web/js/app.js")
        self.assertIn('api("power-hr")', app)
        self.assertIn('id="home-trainer"', app)
        self.assertIn("la FC reste la consigne", app)


if __name__ == "__main__":
    unittest.main()
