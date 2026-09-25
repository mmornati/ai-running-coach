"""Palier D — `/api/nutrition` : fusion de poids (#36), doublons même jour, et sémantique
« valeur du jour même » pour la moyenne 7 j / l'écart à la cible.

Workspace minimal écrit à la main (fichiers ```arc, pas de sous-processus) — même
approche que `tests/data/test_arc_index.py` — plutôt qu'un serveur HTTP réel : ce
module n'a besoin que de `arc_serve.Store` + `arc_serve.api_nutrition` en process.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_serve as S  # noqa: E402


def arc(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte.\n"


class NutritionApi(unittest.TestCase):
    TODAY = "2026-06-30"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-nutrition-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        (self.ws / rel).write_text(text, encoding="utf-8")

    def api(self, days=60) -> dict:
        store = S.Store(self.ws, memory=True, today=self.TODAY)
        return S.api_nutrition(store, {"days": [str(days)]})

    def weight_of(self, resp: dict, date: str):
        return next((p["weight_kg_merged"] for p in resp["weight_series"] if p["date"] == date), "ABSENT")


class TestSameDayDuplicates(NutritionApi):
    """#36 review : deux fichiers pour la même date (le contrat n'interdit pas le
    doublon) doivent départager de façon déterministe et DOCUMENTÉE — jamais l'ordre
    arbitraire que rendrait SQLite sans tri explicite. Voir
    `M.ASSUMPTIONS["weight_merge"]` : le `source_path` le plus grand par ordre
    alphabétique gagne, dans le même sens pour le poids ET pour la cible.
    """

    def test_two_health_files_same_day_breaks_tie_by_source_path(self):
        """`medical/2026-06-30_a_health.md` (70,0 kg) et `..._b_health.md` (75,0 kg) :
        `_b_` est alphabétiquement après `_a_`, donc 75,0 kg doit gagner — jamais
        70,0 (l'autre fichier), jamais une moyenne des deux (72,5)."""
        self.write("medical/2026-06-30_a_health.md",
                   arc('{"arc": 1, "kind": "health", "date": "2026-06-30", "morning_check": "full", "weight_kg": 70.0}'))
        self.write("medical/2026-06-30_b_health.md",
                   arc('{"arc": 1, "kind": "health", "date": "2026-06-30", "morning_check": "full", "weight_kg": 75.0}'))
        resp = self.api()
        self.assertEqual(self.weight_of(resp, "2026-06-30"), 75.0)

    def test_two_nutrition_files_same_day_breaks_tie_by_source_path(self):
        """Même règle côté nutrition, sans aucun fichier santé ce jour-là (branche
        nutrition du merge exercée seule) : `..._b_nutrition.md` (67,0 kg) gagne sur
        `..._a_nutrition.md` (65,0 kg)."""
        self.write("nutrition/2026-06-30_a_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "weight_kg": 65.0}'))
        self.write("nutrition/2026-06-30_b_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "weight_kg": 67.0}'))
        resp = self.api()
        self.assertEqual(self.weight_of(resp, "2026-06-30"), 67.0)

    def test_health_still_wins_over_nutrition_despite_source_path_order(self):
        """`nutrition/2026-06-30_z_nutrition.md` (source_path alphabétiquement APRÈS le
        fichier santé) ne doit pas l'emporter : la priorité santé > nutrition
        (`weight_merge`) est une règle à part, appliquée AVANT le départage de
        doublons intra-source, jamais contournée par un nom de fichier qui trierait
        plus loin."""
        self.write("medical/2026-06-30_a_health.md",
                   arc('{"arc": 1, "kind": "health", "date": "2026-06-30", "morning_check": "full", "weight_kg": 70.0}'))
        self.write("nutrition/2026-06-30_z_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "weight_kg": 99.0}'))
        resp = self.api()
        self.assertEqual(self.weight_of(resp, "2026-06-30"), 70.0)

    def test_two_nutrition_files_same_day_target_weight_breaks_tie_the_same_way(self):
        """Cible (`target_weight_kg`) : même sens de départage que le poids — le
        `source_path` le plus grand par ordre alphabétique gagne (`..._b_` sur
        `..._a_`), pour rester cohérent plutôt que d'inverser le sens entre les deux
        champs du même fichier."""
        self.write("nutrition/2026-06-30_a_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "target_weight_kg": 60.0}'))
        self.write("nutrition/2026-06-30_b_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "target_weight_kg": 67.0}'))
        resp = self.api()
        self.assertEqual(resp["weight"]["target_kg"], 67.0)

    def test_most_recent_date_wins_over_source_path_for_target(self):
        """La cible la plus RÉCENTE prime toujours sur le nom de fichier : une cible
        du 20 (quel que soit son `source_path`) doit céder devant une cible du 25."""
        self.write("nutrition/2026-06-25_z_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-20", "target_weight_kg": 60.0}'))
        self.write("nutrition/2026-06-25_a_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-25", "target_weight_kg": 65.0}'))
        resp = self.api()
        self.assertEqual(resp["weight"]["target_kg"], 65.0)


class TestAvg7AndGapAreAsOfToday(NutritionApi):
    """#36 review : `weight.avg7_kg` / `weight.gap_kg` doivent être la valeur DU JOUR
    (aujourd'hui), jamais la dernière moyenne non nulle trouvée n'importe où plus tôt
    dans la fenêtre affichée — sans quoi une moyenne vieille de plusieurs semaines
    s'afficherait comme si elle datait d'aujourd'hui.
    """

    def test_old_average_is_not_reported_as_current(self):
        """Trois pesées 40 jours avant aujourd'hui (hors de la fenêtre 7 j se terminant
        aujourd'hui) : `avg7_kg` doit être `None` aujourd'hui, jamais la moyenne
        (fausse-actuelle) calculée sur ces vieilles valeurs."""
        for d in ("2026-05-18", "2026-05-19", "2026-05-20"):
            self.write(f"medical/{d}_health.md",
                      arc(f'{{"arc": 1, "kind": "health", "date": "{d}", "morning_check": "full", "weight_kg": 80.0}}'))
        self.write("nutrition/2026-06-30_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "target_weight_kg": 67.0}'))
        resp = self.api()
        self.assertIsNone(resp["weight"]["avg7_kg"])
        self.assertIsNone(resp["weight"]["avg7_date"])
        self.assertIsNone(resp["weight"]["gap_kg"], "pas de moyenne du jour -> pas d'écart à la cible non plus")

    def test_recent_average_is_reported_with_its_date(self):
        """Trois pesées dans les 7 derniers jours (dont aujourd'hui) : `avg7_kg` doit
        être défini, daté d'aujourd'hui (`avg7_date`), et l'écart à la cible calculé."""
        for d in ("2026-06-28", "2026-06-29", "2026-06-30"):
            self.write(f"medical/{d}_health.md",
                      arc(f'{{"arc": 1, "kind": "health", "date": "{d}", "morning_check": "full", "weight_kg": 70.0}}'))
        self.write("nutrition/2026-06-30_nutrition.md",
                   arc('{"arc": 1, "kind": "nutrition", "date": "2026-06-30", "target_weight_kg": 67.0}'))
        resp = self.api()
        self.assertEqual(resp["weight"]["avg7_kg"], 70.0)
        self.assertEqual(resp["weight"]["avg7_date"], "2026-06-30")
        self.assertEqual(resp["weight"]["gap_kg"], 3.0)


if __name__ == "__main__":
    unittest.main()
