"""Palier D — métriques : valeurs de référence connues, et accord avec les profils de sport.

Ces calculs ne sont jamais demandés au modèle ; ce fichier est leur seul garde-fou.
"""

from __future__ import annotations

import math
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_metrics as M  # noqa: E402


class TestForm(unittest.TestCase):
    def series(self, loads: dict, days: int):
        start = date(2026, 1, 1)
        return M.daily_series({(start + timedelta(days=k)).isoformat(): v for k, v in loads.items()},
                              start, start + timedelta(days=days - 1))

    def test_constant_load_converges(self):
        """120 j à charge constante 100 : condition et fatigue → 100, forme → 0 (solutions analytiques)."""
        s = self.series({k: 100.0 for k in range(120)}, 120)
        last = s[-1]
        self.assertAlmostEqual(last["fitness"], 100 * (1 - math.exp(-120 / 42)), delta=0.05)
        self.assertAlmostEqual(last["fatigue"], 100.0, delta=0.05)
        self.assertLess(abs(last["form"]), 7)

    def test_rest_after_block_gives_positive_form(self):
        """Six semaines de charge puis dix jours de repos : la forme devient positive."""
        s = self.series({k: 80.0 for k in range(42)}, 52)
        self.assertLess(s[41]["form"], 0)
        self.assertGreater(s[-1]["form"], 0)

    def test_acwr_needs_history(self):
        """Une première séance après une coupure ne produit pas un ACWR de 4."""
        s = self.series({0: 100.0}, 5)
        self.assertTrue(all(p["acwr"] is None for p in s), [p["acwr"] for p in s])

    def test_monotony_undefined_on_flat_week(self):
        s = self.series({k: 50.0 for k in range(7)}, 7)
        self.assertIsNone(s[-1]["monotony"])


class TestLoad(unittest.TestCase):
    ATHLETE = {"hr_max_bpm": 188, "hr_rest_bpm": 48}

    def test_trimp_reference(self):
        """60 min à FC 150 (FCr 0,729) : 60 × 0,729 × 0,64 × e^(1,92 × 0,729) ≈ 113,3."""
        self.assertAlmostEqual(M.trimp_banister(3600, 150, 48, 188), 113.3, delta=0.2)

    def test_srpe_fallback_without_hr(self):
        load, source = M.session_load({"sport": "strength", "duration_s": 2400, "rpe": 6}, self.ATHLETE)
        self.assertEqual(source, "srpe")
        self.assertAlmostEqual(load, 40 * 6 * M.RPE_TO_TRIMP)

    def test_estimated_when_nothing_known(self):
        _, source = M.session_load({"sport": "strength", "duration_s": 2400}, self.ATHLETE)
        self.assertEqual(source, "estimated")


class TestSportProfiles(unittest.TestCase):
    def test_trail_equivalence_matches_sport_profile(self):
        """La constante D+ du code doit rester celle de `config/sports/trail.md`."""
        text = (REPO / "config/sports/trail.md").read_text(encoding="utf-8")
        m = re.search(r"1000 m D\+ ≈ (\d+(?:,\d+)?) à (\d+(?:,\d+)?) km plat", text)
        self.assertIsNotNone(m, "règle d'équivalence introuvable dans config/sports/trail.md")
        lo, hi = (float(g.replace(",", ".")) for g in m.groups())
        self.assertEqual(M.TRAIL_FLAT_KM_PER_1000M, (lo, hi))

    def test_road_ignores_elevation(self):
        run = {"sport": "running", "distance_m": 10000, "elevation_gain_m": 500}
        trail = dict(run, sport="trail")
        self.assertEqual(M.effort_distance_m(run), 10000)
        self.assertEqual(M.effort_distance_m(trail), 10000 + 500 * M.TRAIL_FLAT_M_PER_M_DPLUS)


class TestPerformance(unittest.TestCase):
    def test_vdot_matches_daniels_tables(self):
        self.assertAlmostEqual(M.vdot(5000, 20 * 60), 49.8, delta=0.1)
        marathon = M.predict_time_vdot(50, 42195)
        self.assertAlmostEqual(marathon, 3 * 3600 + 10 * 60 + 49, delta=60)

    def test_vo2max_skips_walking_and_easy_runs(self):
        athlete = {"hr_max_bpm": 177}
        ultra = {"sport": "trail", "distance_m": 109709, "elevation_gain_m": 1992, "duration_s": 55610, "moving_duration_s": 51993, "avg_hr_bpm": 125}
        easy = {"sport": "running", "distance_m": 8176, "duration_s": 2937, "avg_hr_bpm": 121}
        tempo = {"sport": "running", "distance_m": 12820, "duration_s": 4011, "avg_hr_bpm": 140}
        self.assertIsNone(M.vo2max_effective(ultra, athlete), "un ultra marché ne dit rien de la VO2max")
        self.assertIsNone(M.vo2max_effective(easy, athlete), "footing < 70 % FC max : relation trop lâche")
        self.assertIsNotNone(M.vo2max_effective(tempo, athlete))

    def test_trend_weight_is_capped(self):
        """Un ultra de 15 h ne doit pas écraser un mois de séances."""
        est = [("2026-09-01", 50.0, 3600), ("2026-09-13", 40.0, 55000)]
        # plafond 90 min : (50 × 60 + 40 × 90) / 150 = 44,0 — sans plafond, 40,6
        self.assertAlmostEqual(M.vo2max_trend(est, "2026-09-20"), 44.0)

    def test_partial_last_split_is_not_a_record(self):
        """25,19 km en 26 splits : le 26ᵉ (190 m) n'est pas un record du kilomètre."""
        splits = [{"km": k, "duration_s": 360} for k in range(1, 26)] + [{"km": 26, "duration_s": 60}]
        best = M.best_efforts([{"date": "2025-05-31", "sport": "trail", "distance_m": 25190, "splits": splits}])
        self.assertEqual(best[1]["time_s"], 360)


if __name__ == "__main__":
    unittest.main()
