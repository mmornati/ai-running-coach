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

    def test_long_lap_is_not_a_kilometre(self):
        """Tours Garmin d'une séance structurée : un pas de 2 km en 7:00 n'est pas un
        « kilomètre en 7:00 », et ne doit pas entrer dans une fenêtre de 5 km."""
        splits = [{"km": 1, "duration_s": 300, "distance_m": 1000},
                  {"km": 2, "duration_s": 420, "distance_m": 2000}] + \
                 [{"km": k, "duration_s": 330, "distance_m": 1000} for k in range(3, 9)]
        best = M.best_efforts([{"date": "2026-09-23", "sport": "running", "distance_m": 9000, "splits": splits}])
        self.assertEqual(best[1]["time_s"], 300)
        self.assertEqual(best[5]["time_s"], 5 * 330, "la fenêtre de 5 km ne peut pas enjamber le tour de 2 km")


class TestWeekCompliance(unittest.TestCase):
    """#33 — conformité plan vs réalisé, fixtures à ratios connus."""

    TODAY = date(2026, 9, 20)          # dimanche : la semaine du 14 est entièrement passée

    def session(self, day, sport="running", title="Footing", **kw):
        s = {"date": day, "sport": sport, "title": title}
        s.update(kw)
        return s

    def activity(self, day, sport="running", duration_s=1800, elevation_gain_m=None, **kw):
        a = {"date": day, "sport": sport, "duration_s": duration_s, "elevation_gain_m": elevation_gain_m}
        a.update(kw)
        return a

    def test_no_plan_gives_none(self):
        """Semaine sans aucune séance : KPI absent, jamais 0."""
        self.assertIsNone(M.week_compliance([], [], self.TODAY))

    def test_known_ratios_done_and_missed(self):
        """2 séances planifiées, 1 faite (durée à 120 %), 1 manquée : 50 %, ratio durée 0,6."""
        sessions = [
            self.session("2026-09-14", planned_duration_s=1800, status="done"),
            self.session("2026-09-15", planned_duration_s=1200, status="missed"),
        ]
        activities = [self.activity("2026-09-14", duration_s=2160)]      # 120 % de la première
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_planned"], 2)
        self.assertEqual(c["sessions_done"], 1)
        self.assertEqual(c["sessions_pct"], 50.0)
        # (2160 + 0) / (1800 + 1200) = 0.72
        self.assertAlmostEqual(c["duration_ratio"], 0.72)

    def test_cancelled_excluded_from_denominator(self):
        """Une annulation (médicale ou non — le contrat n'a pas de motif) sort du calcul."""
        sessions = [
            self.session("2026-09-14", planned_duration_s=1800, status="done"),
            self.session("2026-09-15", planned_duration_s=1200, status="cancelled"),
        ]
        activities = [self.activity("2026-09-14", duration_s=1800)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_planned"], 1, "la séance annulée ne doit pas compter au dénominateur")
        self.assertEqual(c["sessions_pct"], 100.0)
        self.assertEqual(c["sessions_cancelled"], 1)
        self.assertEqual(c["duration_ratio"], 1.0)

    def test_moved_excluded_unless_a_session_exists_at_the_new_date(self):
        """`moved` sort du calcul ; si le coach a écrit la séance réelle ailleurs, elle compte pour elle-même."""
        sessions = [
            self.session("2026-09-14", planned_duration_s=1800, status="moved"),
            self.session("2026-09-16", planned_duration_s=1800, status="done"),
        ]
        activities = [self.activity("2026-09-16", duration_s=1800)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_moved"], 1)
        self.assertEqual(c["sessions_planned"], 1, "seule la séance réellement datée compte")
        self.assertEqual(c["sessions_done"], 1)

    def test_future_session_not_counted_missed(self):
        """Séance du reste de la semaine en cours (date > aujourd'hui) : jamais « manquée »."""
        today = date(2026, 9, 16)                     # mercredi
        sessions = [self.session("2026-09-18", status="planned")]         # vendredi : à venir
        c = M.week_compliance(sessions, [], today)
        self.assertEqual(c["sessions_planned"], 0, "une séance future ne doit pas compter au dénominateur")
        self.assertEqual(c["sessions_future"], 1)

    def test_matching_without_explicit_status(self):
        """Statut absent + activité du même jour et famille de sport compatible → faite."""
        sessions = [self.session("2026-09-14", sport="trail")]     # pas de `status`
        activities = [self.activity("2026-09-14", sport="running")]   # route/trail interchangeables
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_done"], 1)

    def test_matching_without_activity_is_missed(self):
        sessions = [self.session("2026-09-14")]
        c = M.week_compliance(sessions, [], self.TODAY)
        self.assertEqual(c["sessions_done"], 0)
        self.assertEqual(c["sessions_planned"], 1)

    def test_multiple_sessions_and_activities_same_day(self):
        """Deux séances le même jour, deux activités : appariement un-pour-un, pas de double compte."""
        sessions = [
            self.session("2026-09-14", sport="running", title="Footing matin"),
            self.session("2026-09-14", sport="strength", title="Renfo soir"),
        ]
        activities = [
            self.activity("2026-09-14", sport="running", duration_s=1800),
            self.activity("2026-09-14", sport="strength", duration_s=2400),
        ]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_planned"], 2)
        self.assertEqual(c["sessions_done"], 2)

    def test_intensity_split_easy_vs_quality(self):
        sessions = [
            self.session("2026-09-14", intensity="endurance", planned_duration_s=3600, status="done"),
            self.session("2026-09-15", intensity="vo2max", planned_duration_s=1800, status="missed"),
        ]
        activities = [self.activity("2026-09-14", duration_s=3600)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["by_intensity"]["easy"]["sessions_pct"], 100.0)
        self.assertEqual(c["by_intensity"]["quality"]["sessions_pct"], 0.0)

    def test_elevation_ratio(self):
        sessions = [self.session("2026-09-14", planned_elevation_m=1000, status="done")]
        activities = [self.activity("2026-09-14", elevation_gain_m=800)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertAlmostEqual(c["elevation_ratio"], 0.8)


if __name__ == "__main__":
    unittest.main()
