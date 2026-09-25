"""Palier D — régression graphique #41 (revue de code, BLOCKER 1).

`web/js/chart.js` n'a pas de suite de tests JS (aucun paquet npm dans ce dépôt,
`CONTRIBUTING.md` : stdlib uniquement) : ce module shelle vers `node` (déjà
utilisé pour `node --check` avant toute PR) pour exécuter le module ES pur
`chart.js` et vérifier le SVG qu'il rend — sans DOM, sans dépendance, sans
navigateur. Ignoré si `node` est absent de la machine plutôt qu'en échec
(même discipline que le reste du palier D face à un outil optionnel).

Le bug verrouillé ici : `web/js/app.js::fuelingSection` (#41) trace le taux de
sudation sur les sorties longues, une série CRIBLÉE de trous (toutes les
sorties longues ne sont pas pesées). `chart.js::pathFrom` construit une ligne
en coupant à chaque `null` (`pen = false`) — un point non-`null` **isolé**
entre deux `null` (aucun voisin immédiat) ne produit alors qu'un simple « M »
sans « L » à la suite : un sous-tracé d'un seul point qu'aucun navigateur ne
rend. Un graphique `type: "line"` sur cette série perdait donc silencieusement
tout point de sudation isolé (le cas le plus fréquent avec si peu de pesées).
Fixé en traçant la sudation en `type: "dots"` (comme les glucides/h) plutôt
qu'en `line` : un point isolé reste un cercle, toujours rendu.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHART_JS = REPO / "web/js/chart.js"

NODE = shutil.which("node")


def _render_svg(layer: dict, *, axis_opts: dict | None = None) -> str:
    """Exécute `chart.js::timeChart` dans un sous-processus `node` pur (module ES,
    aucun DOM) et rend le SVG produit, pour une série de 5 points."""
    dates = ["2026-08-01", "2026-08-08", "2026-08-15", "2026-08-22", "2026-08-29"]
    script = f"""
import {{ timeChart }} from {json.dumps(CHART_JS.as_posix())};
const dates = {json.dumps(dates)};
const layer = {json.dumps(layer)};
const opts = {json.dumps(axis_opts or {"height": 200, "y2": {"zero": True}})};
const r = timeChart(dates, [layer], [], opts);
console.log(JSON.stringify(r.svg));
"""
    result = subprocess.run([NODE, "--input-type=module", "-e", script],
                             capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise AssertionError(f"node a échoué : {result.stderr}")
    return json.loads(result.stdout.strip())


@unittest.skipUnless(NODE, "node absent de la machine — voir CONTRIBUTING.md (node --check)")
class TestFuelingSweatChart(unittest.TestCase):
    """#41 — `fuelingSection` (`web/js/app.js`) doit rendre CHAQUE sortie pesée,
    même une sudation isolée entre deux sorties non pesées."""

    # 5 sorties longues : sudation pesée seulement aux offsets 0 et 3 — AUCUN
    # voisin immédiat pour l'une ou l'autre (le cas qui cassait `type: "line"`).
    SPARSE_SWEAT = [1.2, None, None, 0.8, None]

    def test_dots_layer_renders_one_circle_per_non_null_value(self):
        """Le layer réellement utilisé par `fuelingSection` (#41) : `type: "dots"`,
        axe secondaire — jamais `type: "line"` (voir docstring du module)."""
        svg = _render_svg({"type": "dots", "values": self.SPARSE_SWEAT,
                           "cls": "dot dot--sweat", "axis": "y2", "r": 3.2})
        self.assertEqual(svg.count('class="dot dot--sweat"'), 2)

    def test_isolated_point_visible_even_at_the_very_first_index(self):
        """Cas limite : le tout premier point de la série est isolé (rien à
        l'index -1 par construction), et pourtant doit rester rendu."""
        svg = _render_svg({"type": "dots", "values": [0.5, None, None, None, None],
                           "cls": "dot dot--sweat", "axis": "y2", "r": 3.2})
        self.assertEqual(svg.count('class="dot dot--sweat"'), 1)

    def test_line_layer_on_the_same_sparse_series_loses_isolated_points(self):
        """Documente le bug lui-même (revue de code #41, BLOCKER 1) : un `type:
        "line"` sur cette même série ne produit AUCUN segment visible pour un
        point isolé (`pathFrom` : « M » sans « L » à la suite) — exactement
        pourquoi `fuelingSection` n'utilise plus jamais `line` pour la sudation."""
        svg = _render_svg({"type": "line", "values": self.SPARSE_SWEAT,
                           "cls": "line line--sweat", "axis": "y2"})
        self.assertNotIn("L", svg.split('class="line line--sweat"')[1].split('"/>')[0])


if __name__ == "__main__":
    unittest.main()
