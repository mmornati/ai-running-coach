"""Palier D — #50, revue de code (should-fix 2) : `daysToWeeksPeriod` (`web/js/app.js`)
convertit l'ancien paramètre `jours` de « Forme & charge » (`#/forme?jours=…`, #47)
vers le sélecteur EN SEMAINES d'Analyse (12/26/52, « 3 mois »/« 6 mois »/« 1 an »).

Un simple `Math.round(jours / 7)` (première version de #50) produisait des valeurs
comme 13 semaines pour `jours=90`, qu'aucun des trois boutons de la vue n'offre : le
sélecteur restait sans état actif après une redirection depuis un ancien lien. Ce
test exécute la fonction RÉELLEMENT utilisée par `route()` — pas une réimplémentation
Python qui pourrait diverger silencieusement — via `node`, en l'extrayant du fichier
source (même discipline que `test_dashboard_chart_fueling.py` pour `chart.js` : pas
de DOM à simuler pour une fonction pure, donc pas besoin d'importer tout `app.js`,
qui exécute `boot()` au chargement et échouerait hors navigateur)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP_JS = REPO / "web/js/app.js"
NODE = shutil.which("node")

_SOURCE = APP_JS.read_text(encoding="utf-8")
# `[\s\S]*?^\}` (multiligne, jusqu'à la première accolade fermante EN DÉBUT DE
# LIGNE) plutôt que `[^}]*\}` : le corps contient lui-même un objet littéral
# (`{ 90: 12, ... }`), dont l'accolade fermante arrêterait un `[^}]*` bien avant
# la fin réelle de la fonction.
_MATCH = re.search(r"^function daysToWeeksPeriod\([^)]*\)\s*\{[\s\S]*?^\}", _SOURCE, re.MULTILINE)


def _call(days):
    """Exécute `daysToWeeksPeriod` (extraite telle quelle de `web/js/app.js`) dans un
    sous-processus `node` pur, pour une seule valeur de `days`."""
    assert _MATCH, "daysToWeeksPeriod introuvable dans web/js/app.js"
    script = f"{_MATCH.group(0)}\nconsole.log(JSON.stringify(daysToWeeksPeriod({json.dumps(days)})));"
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise AssertionError(f"node a échoué : {result.stderr}")
    return json.loads(result.stdout.strip())


@unittest.skipUnless(NODE, "node absent de la machine — voir CONTRIBUTING.md (node --check)")
class TestDaysToWeeksPeriod(unittest.TestCase):
    def test_function_exists_in_source(self):
        self.assertIsNotNone(_MATCH, "daysToWeeksPeriod introuvable dans web/js/app.js")

    def test_exact_matches_for_the_three_historical_periods(self):
        """#/forme n'a jamais offert que 90/180/365 j (#43) : ces trois valeurs
        doivent retomber exactement sur les trois fenêtres offertes par Analyse."""
        self.assertEqual(_call(90), 12)
        self.assertEqual(_call(180), 26)
        self.assertEqual(_call(365), 52)

    def test_result_is_always_one_of_the_offered_periods(self):
        """Revue de code #50 : quelle que soit la valeur de `jours` d'un vieux lien,
        le résultat doit être l'une des trois valeurs QUE LE SÉLECTEUR OFFRE — jamais
        une fenêtre orpheline sans bouton actif."""
        for days in (1, 30, 45, 60, 89, 91, 120, 150, 179, 181, 250, 300, 364, 366, 400, 1000):
            self.assertIn(_call(days), (12, 26, 52), f"jours={days}")

    def test_nearest_offered_value_for_arbitrary_days(self):
        # 45 j (~6,4 sem.) plus proche de 12 sem. (84 j) que de 26 sem. (182 j).
        self.assertEqual(_call(45), 12)
        # 300 j (~42,9 sem.) plus proche de 52 sem. (364 j) que de 26 sem. (182 j).
        self.assertEqual(_call(300), 52)


if __name__ == "__main__":
    unittest.main()
