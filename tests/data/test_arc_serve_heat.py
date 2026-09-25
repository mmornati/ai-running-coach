"""Palier D — `/api/summary.heat_acclimation` (#38) : review PR #83.

Workspace minimal écrit à la main (fichiers ```arc, pas de sous-processus) — même
approche que `tests/data/test_arc_serve_nutrition.py` — plutôt qu'un serveur HTTP réel.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_metrics as M  # noqa: E402
import arc_serve as S  # noqa: E402


def arc(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte.\n"


class HeatApi(unittest.TestCase):
    TODAY = "2026-09-23"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-heat-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        (self.ws / rel).write_text(text, encoding="utf-8")

    def activity(self, day: str, sport: str = "running", duration_s: float = 3600, location: str = None) -> None:
        loc = f', "location": "{location}"' if location else ""
        self.write(f"activities/{day}_{sport}.md",
                  arc(f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
                      f'"duration_s": {duration_s}{loc}}}'))

    def weather(self, day: str, temp_max_c: float, location: str = "Tournai") -> None:
        self.write(f"medical/{day}_meteo.md",
                  arc(f'{{"arc": 1, "kind": "weather", "date": "{day}", "location": "{location}", '
                      f'"category": "orange", "temp_max_c": {temp_max_c}}}'))

    def objective(self, race_date: str, location: str) -> None:
        self.write("planning/active_objective.md",
                  "# Objectif\n\n| Champ | Valeur |\n|:--|:--|\n| **Course** | Course test |\n"
                  f"| **Date** | {race_date} |\n| **Lieu course** | {location} |\n")

    def summary(self, config_toml: str = None) -> dict:
        if config_toml is not None:
            (self.ws / "config").mkdir(parents=True, exist_ok=True)
            self.write("config/workspace.toml", config_toml)
        store = S.Store(self.ws, memory=True, today=self.TODAY)
        return S.api_summary(store, {})


class TestObjectiveForecastHot(HeatApi):
    """review #2 : le fichier météo unique du jour est presque toujours celui du LIEU
    D'ENTRAÎNEMENT (le skill `weather-forecast` le fetch en priorité) — il ne doit
    jamais répondre pour la météo d'une course lointaine sans correspondance de lieu."""

    def test_true_when_race_location_matches_a_hot_forecast(self):
        self.objective("2026-09-25", "Chamonix")
        self.weather("2026-09-25", 28, location="Chamonix")
        heat = self.summary()["heat_acclimation"]
        self.assertIs(heat["objective_forecast_hot"], True)

    def test_false_when_race_location_matches_a_cool_forecast(self):
        self.objective("2026-09-25", "Chamonix")
        self.weather("2026-09-25", 12, location="Chamonix")
        heat = self.summary()["heat_acclimation"]
        self.assertIs(heat["objective_forecast_hot"], False)

    def test_none_when_no_forecast_exists_for_the_race_date(self):
        self.objective("2026-12-25", "Chamonix")   # trop loin : wttr.in n'a rien encore
        heat = self.summary()["heat_acclimation"]
        self.assertIsNone(heat["objective_forecast_hot"])

    def test_none_when_the_only_weather_file_is_the_training_location_not_the_race(self):
        """Repro exacte du bug signalé : course à Chamonix, mais le seul fichier météo
        du jour est celui du lieu d'ENTRAÎNEMENT (Tournai) à 28°C. Avant le correctif,
        `pick_weather` prenait ce fichier faute d'alternative (« un seul fichier => il
        s'applique ») et rendait `True` à tort. Doit rendre `None` : pas de prévision
        connue pour la course elle-même."""
        self.objective("2026-09-25", "Chamonix")
        self.weather("2026-09-25", 28, location="Tournai")
        heat = self.summary()["heat_acclimation"]
        self.assertIsNone(heat["objective_forecast_hot"])

    def test_none_without_an_objective(self):
        heat = self.summary()["heat_acclimation"]
        self.assertIsNone(heat["objective_forecast_hot"])

    def test_none_when_objective_has_no_location(self):
        self.write("planning/active_objective.md",
                  "# Objectif\n\n| Champ | Valeur |\n|:--|:--|\n| **Course** | Course test |\n"
                  "| **Date** | 2026-09-25 |\n")
        self.weather("2026-09-25", 30, location="Tournai")
        heat = self.summary()["heat_acclimation"]
        self.assertIsNone(heat["objective_forecast_hot"])

    def test_matches_normalized_location_with_country_suffix(self):
        self.objective("2026-09-25", "Chamonix")
        self.weather("2026-09-25", 30, location="Chamonix, France")
        heat = self.summary()["heat_acclimation"]
        self.assertIs(heat["objective_forecast_hot"], True)


class TestHeatAcclimationSummaryFields(HeatApi):
    """Champs additifs de `/api/summary.heat_acclimation` et respect du seuil configuré,
    lus via `Store.heat_acclimation` (pas de SQL dupliqué — review #9)."""

    def test_fields_present_and_use_configured_threshold(self):
        self.activity("2026-09-20", duration_s=4000)
        self.weather("2026-09-20", 27)
        heat = self.summary("[health]\nheat_threshold_c = 30.0\n")["heat_acclimation"]
        self.assertEqual(heat["threshold_c"], 30.0)
        self.assertEqual(heat["hot_sessions"], 0, "27°C < seuil configuré 30°C")
        self.assertEqual(heat["window_days"], M.HEAT_WINDOW_DAYS)
        self.assertIn("sessions_without_weather", heat)
        self.assertIn("sessions_considered", heat)
        self.assertIn("hot_duration_s", heat)

    def test_invalid_threshold_in_config_does_not_crash_the_dashboard(self):
        """Review #1, vérifié au niveau API cette fois : un `workspace.toml` invalide ne
        doit jamais faire échouer `/api/summary` (donc tout le tableau de bord)."""
        self.activity("2026-09-20", duration_s=3600)
        self.weather("2026-09-20", 30)
        heat = self.summary('[health]\nheat_threshold_c = "chaud"\n')["heat_acclimation"]
        self.assertEqual(heat["threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertEqual(heat["hot_sessions"], 1)

    def test_settings_reflect_the_same_resolved_threshold(self):
        """`settings.heat_threshold_c` (servi séparément dans `/api/summary`) et
        `heat_acclimation.threshold_c` doivent toujours être LA MÊME valeur résolue —
        jamais deux lectures indépendantes qui pourraient diverger."""
        summary = self.summary("[health]\nheat_threshold_c = 22.0\n")
        self.assertEqual(summary["settings"]["heat_threshold_c"], 22.0)
        self.assertEqual(summary["heat_acclimation"]["threshold_c"], 22.0)


if __name__ == "__main__":
    unittest.main()
