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
import arc_legacy as L  # noqa: E402
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


class TestHrvBaseline(unittest.TestCase):
    """#34 — ligne de base HRV personnelle : moyenne 7 j de ln(HRV) vs référence 60 j ± 0,5 ET.

    Méthode : Plews, Laursen & Buchheit (2013) ; Kiviniemi et al. (2007). Voir
    `M.ASSUMPTIONS["hrv_baseline"]` pour le détail complet.
    """

    START = date(2026, 1, 1)

    def series(self, values_by_offset: dict, days: int):
        """`values_by_offset` : décalage (jours depuis START) -> HRV en ms. Un décalage
        absent du dict est un jour SANS mesure (pas une mesure à 0 ms)."""
        by_date = {(self.START + timedelta(days=k)).isoformat(): v for k, v in values_by_offset.items()}
        return M.hrv_baseline_series(by_date, self.START, self.START + timedelta(days=days - 1))

    def test_constant_hrv_gives_flat_band_and_normal_status(self):
        """65 jours à 60 ms pile : moyenne 7 j = ln(60), référence 60 j identique (écart-type
        nul) → bande [60, 60] et statut « dans la norme » (ni sous, ni au-dessus)."""
        s = self.series({k: 60.0 for k in range(65)}, 65)
        last = s[-1]
        self.assertAlmostEqual(last["hrv_ln_mean7"], math.log(60), places=4)
        self.assertEqual(last["hrv_cv7_pct"], 0.0)
        self.assertEqual(last["hrv_personal_low_ms"], 60.0)
        self.assertEqual(last["hrv_personal_high_ms"], 60.0)
        self.assertEqual(last["hrv_personal_status"], "dans_la_norme")

    def test_missing_days_are_not_zero(self):
        """Sur les 53 premiers jours, seul un jour sur deux porte une mesure (60 ms) ; les
        7 derniers jours sont tous mesurés (60 ms aussi). Si les jours sans mesure comptaient
        pour 0, la moyenne et l'écart-type de la fenêtre de référence 60 j seraient tirés vers
        le bas et non nuls — ici tout est à 60, donc la bande doit rester [60, 60] pile."""
        values = {k: 60.0 for k in range(0, 53, 2)}   # ~27 jours mesurés sur 53
        values.update({k: 60.0 for k in range(53, 60)})  # 7 derniers jours, tous mesurés
        s = self.series(values, 60)
        last = s[-1]
        self.assertNotEqual(last["hrv_personal_status"], "en_construction",
                            "assez de jours mesurés (34 ≥ 30) pour une référence, même incomplète")
        self.assertEqual(last["hrv_personal_low_ms"], 60.0)
        self.assertEqual(last["hrv_personal_high_ms"], 60.0)
        self.assertEqual(last["hrv_personal_status"], "dans_la_norme")

    def test_fewer_than_five_of_seven_days_gives_none(self):
        """Seulement 3 jours mesurés sur les 7 derniers : sous le seuil (`HRV_LN_MIN_VALID_DAYS`
        = 5), rien n'est calculé plutôt qu'une moyenne bruitée sur 3 points."""
        values = {k: 55.0 for k in range(40)}
        for k in (36, 37, 38, 39):   # on retire 4 des 7 derniers jours (33 à 39)
            del values[k]
        s = self.series(values, 40)
        last = s[-1]
        self.assertIsNone(last["hrv_ln_mean7"])
        self.assertIsNone(last["hrv_cv7_pct"])
        self.assertIsNone(last["hrv_personal_status"])
        self.assertIsNone(last["hrv_personal_low_ms"])

    def test_short_history_gives_under_construction(self):
        """10 jours d'historique seulement : la moyenne 7 j est calculable (7 jours mesurés
        ≥ 5) mais la référence 60 j ne l'est pas (10 jours < `HRV_REF_MIN_VALID_DAYS` = 30) :
        statut « en construction », jamais un statut sous/dans/au-dessus deviné trop tôt."""
        s = self.series({k: 60.0 for k in range(10)}, 10)
        last = s[-1]
        self.assertIsNotNone(last["hrv_ln_mean7"])
        self.assertEqual(last["hrv_personal_status"], "en_construction")
        self.assertIsNone(last["hrv_personal_low_ms"])
        self.assertIsNone(last["hrv_personal_high_ms"])

    def test_known_values_below_band(self):
        """53 jours à 60 ms, puis 7 jours alternant 50/70/50/70/50/70/50 (mêmes 7 jours pour
        la moyenne courte ET compris dans la référence 60 j).

        Calcul à la main (valeurs brutes des 7 derniers jours : quatre fois 50, trois fois 70) :
        - moyenne brute = (4×50 + 3×70) / 7 = 410/7 ≈ 58,5714
        - écart-type (population) ≈ 9,8974 → CV 7 j = 100 × 9,8974 / 58,5714 ≈ 16,90 %
        - moyenne de ln : (4×ln(50) + 3×ln(70)) / 7 ≈ 4,056225

        Référence 60 j (53 × ln(60) + les 7 valeurs ci-dessus) :
        - moyenne ≈ 4,089897, écart-type (population) ≈ 0,058176
        - bande ± 0,5 ET : [4,060809 ; 4,118985] en ln, soit [58,0 ; 61,5] ms (exp, arrondi)
        - la moyenne courte (4,056225) est SOUS la borne basse (4,060809) → statut « sous »
        """
        values = {k: 60.0 for k in range(53)}
        values.update({53 + i: v for i, v in enumerate([50.0, 70.0, 50.0, 70.0, 50.0, 70.0, 50.0])})
        s = self.series(values, 60)
        last = s[-1]
        self.assertAlmostEqual(last["hrv_ln_mean7"], 4.056225, places=4)
        self.assertAlmostEqual(last["hrv_cv7_pct"], 16.9, places=1)
        self.assertAlmostEqual(last["hrv_personal_low_ms"], 58.0, places=1)
        self.assertAlmostEqual(last["hrv_personal_high_ms"], 61.5, places=1)
        self.assertEqual(last["hrv_personal_status"], "sous")


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

    # -- Régressions signalées en revue de la PR #78 -----------------------

    def test_rest_sessions_excluded_from_denominator(self):
        """Une semaine entièrement faite ne doit pas tomber à 50 % à cause des jours de repos."""
        sessions = [
            self.session("2026-09-14", sport="rest", title="Repos"),
            self.session("2026-09-15", planned_duration_s=2400, status="done"),
            self.session("2026-09-16", sport="rest", title="Repos"),
            self.session("2026-09-17", planned_duration_s=3000, status="done"),
        ]
        activities = [self.activity("2026-09-15", duration_s=2400), self.activity("2026-09-17", duration_s=3000)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_rest"], 2)
        self.assertEqual(c["sessions_planned"], 2, "les 2 jours de repos ne doivent pas compter au dénominateur")
        self.assertEqual(c["sessions_pct"], 100.0)

    def test_rest_sessions_excluded_through_legacy_parser(self):
        """Reproduction exacte du signalement : semaine héritée, tout fait, repos non planifiés comme sport."""
        text = (
            "| Jour | Séance | Réalisée |\n"
            "|---|---|---|\n"
            "| Lundi | Repos | |\n"
            "| Mardi | Footing 40 min | oui |\n"
            "| Mercredi | Repos | |\n"
            "| Jeudi | Fractionné 50 min | oui |\n"
        )
        week = L.legacy_week(text, "Semaine_2026-09-14.md", "running")
        sessions = week["sessions"]
        self.assertEqual({s["sport"] for s in sessions if s["title"] == "Repos"}, {"rest"})
        activities = [
            self.activity("2026-09-15", duration_s=2400),
            self.activity("2026-09-17", duration_s=3000),
        ]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_rest"], 2)
        self.assertEqual(c["sessions_planned"], 2)
        self.assertEqual(c["sessions_pct"], 100.0, "2 séances sur 2 faites : jamais 50 %")

    def test_intensity_rest_also_excludes_non_rest_sport(self):
        """`intensity == "rest"` exclut aussi, même sans `sport == "rest"`."""
        sessions = [self.session("2026-09-14", sport="running", intensity="rest", title="Footing très facile")]
        c = M.week_compliance(sessions, [], self.TODAY)
        self.assertIsNone(c, "une seule séance, de repos : plus aucune séance à compter")

    def test_todays_session_without_activity_is_pending_not_missed(self):
        """Le matin même, sans activité encore enregistrée : en attente, pas manquée."""
        today = date(2026, 9, 18)
        sessions = [self.session("2026-09-18", planned_duration_s=1800)]
        c = M.week_compliance(sessions, [], today)
        self.assertEqual(c["sessions_planned"], 0, "une séance du jour encore incertaine ne compte pas déjà manquée")
        self.assertEqual(c["sessions_pending"], 1)
        self.assertEqual(c["sessions_done"], 0)

    def test_todays_session_with_activity_still_counts_done(self):
        today = date(2026, 9, 18)
        sessions = [self.session("2026-09-18", planned_duration_s=1800)]
        activities = [self.activity("2026-09-18", duration_s=1800)]
        c = M.week_compliance(sessions, activities, today)
        self.assertEqual(c["sessions_done"], 1)
        self.assertEqual(c["sessions_pending"], 0)

    def test_done_without_matched_activity_excluded_from_ratio_only(self):
        """`done` explicite sans activité chiffrée : compte en séance faite, hors ratio des deux côtés."""
        sessions = [self.session("2026-09-14", planned_duration_s=1800, status="done")]
        c = M.week_compliance(sessions, [], self.TODAY)
        self.assertEqual(c["sessions_done"], 1)
        self.assertEqual(c["sessions_pct"], 100.0)
        self.assertIsNone(c["duration_ratio"], "aucune activité chiffrée : le ratio ne doit pas être artificiellement à 0")

    def test_explicit_done_reserves_its_activity_before_auto_match(self):
        """Une séance sans statut ne doit pas voler l'activité d'une séance `done` explicite du même jour."""
        sessions = [
            self.session("2026-09-14", sport="running", title="Footing (statut absent)"),
            self.session("2026-09-14", sport="trail", title="Sortie longue", planned_duration_s=3600, status="done"),
        ]
        activities = [self.activity("2026-09-14", sport="trail", duration_s=3600)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        # La séance `done` explicite doit récupérer l'unique activité trail : ratio exact à 1.
        self.assertEqual(c["duration_ratio"], 1.0)
        # La séance sans statut, sport `running`, ne trouve plus rien à apparier une fois
        # l'activité trail réservée (compatible par famille, mais déjà consommée) : manquée.
        self.assertEqual(c["sessions_done"], 1)
        self.assertEqual(c["sessions_planned"], 2)

    def test_strength_intensity_goes_to_other_bucket(self):
        """`strength` (contrat INTENSITY) n'est ni facile ni qualité : bucket `other`, jamais perdu."""
        sessions = [
            self.session("2026-09-14", intensity="endurance", planned_duration_s=1800, status="done"),
            self.session("2026-09-15", intensity="strength", planned_duration_s=2400, status="done"),
        ]
        activities = [self.activity("2026-09-14", duration_s=1800), self.activity("2026-09-15", sport="strength", duration_s=2400)]
        c = M.week_compliance(sessions, activities, self.TODAY)
        total_bucketed = sum(v["sessions_planned"] for v in c["by_intensity"].values())
        self.assertEqual(total_bucketed, c["sessions_planned"], "easy + quality + other doit reconstituer le total")
        self.assertEqual(c["by_intensity"]["other"]["sessions_planned"], 1)
        self.assertEqual(c["by_intensity"]["other"]["sessions_done"], 1)

    def test_hiking_matches_planned_trail_session(self):
        """Une sortie trail remplacée par une randonnée (mauvais temps…) doit pouvoir compter faite."""
        sessions = [self.session("2026-09-14", sport="trail")]     # pas de statut
        activities = [self.activity("2026-09-14", sport="hiking")]
        c = M.week_compliance(sessions, activities, self.TODAY)
        self.assertEqual(c["sessions_done"], 1)


if __name__ == "__main__":
    unittest.main()
