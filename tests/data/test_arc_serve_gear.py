"""Palier D — `/api/summary.gear` (#40) : kilométrage chaussures et alerte d'usure.

Workspace minimal écrit à la main (fichiers ```arc, pas de sous-processus) — même
approche que `tests/data/test_arc_serve_heat.py`.
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


class GearApi(unittest.TestCase):
    TODAY = "2026-09-23"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-gear-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        (self.ws / rel).write_text(text, encoding="utf-8")

    def profile(self, gear_bullets: str) -> None:
        self.write("planning/Runner_Profile.md",
                  f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n{gear_bullets}\n")

    def activity(self, day: str, sport: str = "trail", distance_m: float = 10000, gear_id: str = None) -> None:
        gid = f', "gear_id": "{gear_id}"' if gear_id else ""
        self.write(f"activities/{day}_{sport}.md",
                  arc(f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
                      f'"duration_s": 3600, "distance_m": {distance_m}{gid}}}'))

    def summary(self) -> dict:
        store = S.Store(self.ws, memory=True, today=self.TODAY)
        return S.api_summary(store, {})


class TestGearSummary(GearApi):
    def test_declared_shoes_appear_even_without_activity(self):
        self.profile("- Hoka Speedgoat 5 — id: speedgoat")
        gear = self.summary()["gear"]
        self.assertEqual(gear["shoes"], [{
            "gear_id": "speedgoat", "name": "Hoka Speedgoat 5", "distance_m": 0,
            "threshold_m": 700000.0, "start_date": None, "default": False, "retired": False, "alert": False,
        }])
        self.assertEqual(gear["unknown"], [])

    def test_default_shoe_absorbs_activities_without_gear_id(self):
        self.profile("- Hoka Speedgoat 5 — id: speedgoat (par défaut)")
        self.activity("2026-09-20", distance_m=15000)
        gear = self.summary()["gear"]
        self.assertEqual(gear["shoes"][0]["distance_m"], 15000)

    def test_alert_true_past_threshold(self):
        self.profile("- Hoka Speedgoat 5 — alerte 20 km — id: speedgoat")
        self.activity("2026-09-20", distance_m=25000, gear_id="speedgoat")
        gear = self.summary()["gear"]
        self.assertTrue(gear["shoes"][0]["alert"])

    def test_unknown_gear_id_surfaces_separately(self):
        self.profile("- Hoka Speedgoat 5 — id: speedgoat")
        self.activity("2026-09-20", distance_m=8000, gear_id="jamais-vue")
        gear = self.summary()["gear"]
        self.assertEqual(gear["unknown"], [{"gear_id": "jamais-vue", "distance_m": 8000}])

    def test_retired_shoe_excluded_from_alert(self):
        self.profile("- Hoka Speedgoat 5 — alerte 10 km — id: speedgoat (retirée)")
        self.activity("2026-09-20", distance_m=50000, gear_id="speedgoat")
        gear = self.summary()["gear"]
        self.assertFalse(gear["shoes"][0]["alert"])
        self.assertTrue(gear["shoes"][0]["retired"])

    def test_no_profile_gear_section_is_empty_not_an_error(self):
        gear = self.summary()["gear"]
        self.assertEqual(gear, {"shoes": [], "unknown": [], "warnings": []})


if __name__ == "__main__":
    unittest.main()
