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

    Méthode : Plews et al. (2012) pour le passage au log et le CV du lnRMSSD hebdomadaire ;
    Plews, Laursen & Buchheit (2013) pour la largeur de bande ± 0,5 ET. Kiviniemi et al.
    (2007) n'est cité que comme précédent de l'entraînement guidé par une bande individuelle
    (± 1 ET sur la puissance HF, pas le rMSSD) — pas comme source de cette bande ni du CV.
    Voir `M.ASSUMPTIONS["hrv_baseline"]` pour le détail complet.

    La référence 60 j est NON chevauchante avec la moyenne courte : elle se termine
    `HRV_LN_WINDOW_DAYS` (7) jours avant le jour évalué (`ANCHOR` ci-dessous), donc un
    décalage (offset) de 0 à 6 relève de la moyenne courte, 7 à 66 de la référence.
    """

    ANCHOR = date(2026, 3, 1)   # le jour évalué : « day » dans hrv_baseline_series

    def point(self, values_by_offset: dict) -> dict:
        """`values_by_offset` : décalage en jours AVANT `ANCHOR` (0 = `ANCHOR` lui-même) ->
        HRV brut en ms. Un décalage absent du dict est un jour SANS mesure (jamais 0 ms)."""
        by_date = {(self.ANCHOR - timedelta(days=k)).isoformat(): v for k, v in values_by_offset.items()}
        return M.hrv_baseline_series(by_date, self.ANCHOR, self.ANCHOR)[0]

    def test_constant_hrv_gives_flat_band_and_normal_status(self):
        """67 jours (0 à 66) à 60 ms pile : moyenne 7 j = ln(60), référence 60 j identique
        (écart-type nul) → bande [60, 60] et statut « dans la norme » (ni sous, ni au-dessus)."""
        p = self.point({k: 60.0 for k in range(67)})
        self.assertAlmostEqual(p["hrv_ln_mean7"], math.log(60), places=4)
        self.assertEqual(p["hrv_personal_mean7_ms"], 60.0)
        self.assertEqual(p["hrv_cv7_pct"], 0.0)
        self.assertEqual(p["hrv_personal_low_ms"], 60.0)
        self.assertEqual(p["hrv_personal_high_ms"], 60.0)
        self.assertEqual(p["hrv_personal_status"], "dans_la_norme")

    def test_missing_days_are_not_zero(self):
        """Fenêtre courte (offsets 0 à 6) : mesures présentes seulement à 0, 1, 3, 5, 6 (5 sur
        7, au-dessus du seuil) — 2 et 4 sont des jours SANS mesure, jamais un 0. Aucune donnée
        de référence (offsets ≥ 7) : la moyenne courte doit rester calculable sur ces seules
        5 valeurs.

        Calcul à la main (5 valeurs : 60, 64, 58, 70, 50 ms) :
        - moyenne de ln = (ln60 + ln64 + ln58 + ln70 + ln50) / 5 ≈ 4,0948
        - écart-type (population) de ces mêmes ln ≈ 0,1116 → CV 7 j = 100 × 0,1116 / 4,0948 ≈ 2,7 %

        Si les jours 2 et 4 comptaient pour 0 ms, `math.log(0)` lèverait `ValueError` — la
        fonction ne doit ni planter, ni diviser par 7 (nombre de jours de la fenêtre) au lieu
        de 5 (nombre de mesures réellement présentes) : cette dernière erreur donnerait une
        moyenne de ln ≈ 2,9249 (4,0948 × 5/7), très différente de la valeur attendue.
        """
        p = self.point({0: 60.0, 1: 64.0, 3: 58.0, 5: 70.0, 6: 50.0})
        self.assertAlmostEqual(p["hrv_ln_mean7"], 4.0948, places=4)
        self.assertAlmostEqual(p["hrv_cv7_pct"], 2.7, places=1)
        self.assertEqual(p["hrv_personal_mean7_ms"], 60.0)
        self.assertEqual(p["hrv_personal_status"], "en_construction", "pas de référence du tout ici")

    def test_five_of_seven_valid_days_is_enough(self):
        """Exactement `HRV_LN_MIN_VALID_DAYS` (5) jours mesurés sur les 7 derniers : la
        moyenne courte doit être calculée, pas rejetée."""
        p = self.point({0: 60.0, 1: 60.0, 2: 60.0, 3: 60.0, 4: 60.0})
        self.assertIsNotNone(p["hrv_ln_mean7"])

    def test_four_of_seven_valid_days_gives_none(self):
        """Un de moins (4 sur 7, juste sous le seuil) : rien n'est calculé plutôt qu'une
        moyenne bruitée sur trop peu de points."""
        p = self.point({0: 60.0, 1: 60.0, 2: 60.0, 3: 60.0})
        self.assertIsNone(p["hrv_ln_mean7"])
        self.assertIsNone(p["hrv_cv7_pct"])
        self.assertIsNone(p["hrv_personal_mean7_ms"])
        self.assertIsNone(p["hrv_personal_status"])
        self.assertIsNone(p["hrv_personal_low_ms"])

    def test_thirty_of_sixty_reference_days_is_enough(self):
        """Moyenne courte au complet (offsets 0-6) + exactement `HRV_REF_MIN_VALID_DAYS`
        (30) jours de référence (offsets 7 à 36) : la bande doit être calculée, le statut
        ne doit plus être « en construction »."""
        values = {k: 60.0 for k in range(7)}
        values.update({k: 60.0 for k in range(7, 37)})   # offsets 7..36 inclus = 30 jours
        p = self.point(values)
        self.assertNotEqual(p["hrv_personal_status"], "en_construction")
        self.assertEqual(p["hrv_personal_low_ms"], 60.0)
        self.assertEqual(p["hrv_personal_high_ms"], 60.0)

    def test_twenty_nine_of_sixty_reference_days_gives_under_construction(self):
        """Un jour de référence de moins (29 sur 60, offsets 7 à 35) : statut « en
        construction », jamais un statut sous/dans/au-dessus deviné trop tôt."""
        values = {k: 60.0 for k in range(7)}
        values.update({k: 60.0 for k in range(7, 36)})   # offsets 7..35 inclus = 29 jours
        p = self.point(values)
        self.assertEqual(p["hrv_personal_status"], "en_construction")
        self.assertIsNone(p["hrv_personal_low_ms"])
        self.assertIsNone(p["hrv_personal_high_ms"])

    def test_reference_window_does_not_overlap_the_short_window(self):
        """Les offsets 0 à 6 (moyenne courte) sont exclus de la référence, même quand ils
        portent des valeurs très différentes du reste de l'historique : une référence à 60 ms
        pile sur 60 j (offsets 7-66) donne une bande [60, 60] quelle que soit la valeur des
        7 derniers jours — si la fenêtre de référence les incluait par erreur, la bande
        s'élargirait ou se déplacerait pour les absorber."""
        values = {k: 60.0 for k in range(7, 67)}         # référence : 60 j pile à 60 ms
        values.update({0: 200.0, 1: 200.0, 2: 200.0, 3: 200.0, 4: 200.0, 5: 200.0, 6: 200.0})
        p = self.point(values)
        self.assertEqual(p["hrv_personal_low_ms"], 60.0)
        self.assertEqual(p["hrv_personal_high_ms"], 60.0)
        self.assertEqual(p["hrv_personal_status"], "au_dessus", "200 ms est loin au-dessus de 60")

    def test_known_values_below_band(self):
        """Moyenne courte (offsets 0-6) : alternance 50/70/50/70/50/70/50 (quatre fois 50,
        trois fois 70). Référence (offsets 7-66, 60 jours, NON chevauchante) : 60 ms pile.

        Calcul à la main :
        - moyenne de ln (7 valeurs) = (4×ln(50) + 3×ln(70)) / 7 ≈ 4,056225
        - écart-type (population) de ces mêmes ln ≈ 0,166511 → CV 7 j = 100 × 0,166511 / 4,056225 ≈ 4,1 %
          (CV calculé sur ln, PAS sur les valeurs brutes — Plews et al. 2012 ; à ne pas confondre
          avec le CV ≈ 16,9 % qu'on obtiendrait sur les valeurs brutes 50/70)
        - référence : 60 valeurs à ln(60) pile → moyenne ln(60) ≈ 4,094345, écart-type nul
        - bande ± 0,5 ET : [ln(60), ln(60)] en ln, soit [60,0 ; 60,0] ms (exp)
        - la moyenne courte (4,056225) est SOUS la borne basse (4,094345) → statut « sous »
        """
        values = {i: v for i, v in enumerate([50.0, 70.0, 50.0, 70.0, 50.0, 70.0, 50.0])}
        values.update({k: 60.0 for k in range(7, 67)})
        p = self.point(values)
        self.assertAlmostEqual(p["hrv_ln_mean7"], 4.056225, places=4)
        self.assertAlmostEqual(p["hrv_personal_mean7_ms"], 57.8, places=1)
        self.assertAlmostEqual(p["hrv_cv7_pct"], 4.1, places=1)
        self.assertEqual(p["hrv_personal_low_ms"], 60.0)
        self.assertEqual(p["hrv_personal_high_ms"], 60.0)
        self.assertEqual(p["hrv_personal_status"], "sous")


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


class TestEffortKmItra(unittest.TestCase):
    """#35 — distance effort ITRA (km + D+/100) pour sports de course."""

    def test_running_with_elevation(self):
        """10 km + 500 m D+ → 10 + 5 = 15,0 km-effort."""
        activity = {"sport": "running", "distance_m": 10000, "elevation_gain_m": 500}
        self.assertEqual(M.effort_km_itra(activity), 15.0)

    def test_trail_with_elevation(self):
        """21,1 km + 0 m D+ → 21,1 km-effort (pas d'arrondi artificiel à 21)."""
        activity = {"sport": "trail", "distance_m": 21100, "elevation_gain_m": 0}
        self.assertEqual(M.effort_km_itra(activity), 21.1)

    def test_hiking_with_elevation(self):
        """5 km + 300 m D+ → 5 + 3 = 8,0 km-effort."""
        activity = {"sport": "hiking", "distance_m": 5000, "elevation_gain_m": 300}
        self.assertEqual(M.effort_km_itra(activity), 8.0)

    def test_walking_with_elevation(self):
        """3 km + 200 m D+ → 3 + 2 = 5,0 km-effort."""
        activity = {"sport": "walking", "distance_m": 3000, "elevation_gain_m": 200}
        self.assertEqual(M.effort_km_itra(activity), 5.0)

    def test_missing_distance_returns_none(self):
        """Pas de distance : l'activité ne compte pas (None, pas 0)."""
        activity = {"sport": "trail", "elevation_gain_m": 500}
        self.assertIsNone(M.effort_km_itra(activity))

    def test_missing_elevation_uses_zero(self):
        """Pas de D+ : utiliser 0 pour le calcul."""
        activity = {"sport": "running", "distance_m": 10000}
        self.assertEqual(M.effort_km_itra(activity), 10.0)

    def test_non_running_sport_returns_none(self):
        """Indoor cycling 30 km : n'est pas un sport de course, ne compte pas."""
        activity = {"sport": "indoor_cycling", "distance_m": 30000, "elevation_gain_m": 0}
        self.assertIsNone(M.effort_km_itra(activity))

    def test_rounding_to_one_decimal(self):
        """Le résultat est arrondi à une décimale. 20,0 km + 697 m D+ → 26,97 → 27,0."""
        activity = {"sport": "trail", "distance_m": 20000, "elevation_gain_m": 697}
        self.assertEqual(M.effort_km_itra(activity), 27.0)


class TestEffortKmWeekTotal(unittest.TestCase):
    """#35 (revue PR 80) — agrégation hebdomadaire du km-effort ITRA, telle qu'utilisée par
    `scripts/arc_serve.py::api_load` pour cumuler les activités d'une semaine."""

    def test_filters_sport_and_sums_run_like_activities(self):
        """Trail (20 km + 697 m D+) et hiking (5 km + 4 m D+) comptent ; indoor_cycling
        (30 km) est un sport hors famille course et ne contribue pas au total."""
        week = [
            {"sport": "trail", "distance_m": 20000, "elevation_gain_m": 697},
            {"sport": "hiking", "distance_m": 5000, "elevation_gain_m": 4},
            {"sport": "indoor_cycling", "distance_m": 30000, "elevation_gain_m": 0},
        ]
        self.assertEqual(M.effort_km_week_total(week), round(26.97 + 5.04, 1))

    def test_rounds_once_on_the_raw_sum_not_the_sum_of_rounded_activities(self):
        """Deux activités à 5,04 km-effort brut chacune : arrondies séparément puis
        sommées, cela donne 5,0 + 5,0 = 10,0 (le bug corrigé après revue de la PR 80,
        qui faisait dériver le total hebdomadaire du vrai résultat) ; en sommant les
        valeurs brutes puis en arrondissant une seule fois, le total correct est 10,1."""
        week = [{"sport": "running", "distance_m": 5000, "elevation_gain_m": 4},
                {"sport": "running", "distance_m": 5000, "elevation_gain_m": 4}]
        wrong_sum_of_rounded = sum(M.effort_km_itra(a) for a in week)
        self.assertEqual(wrong_sum_of_rounded, 10.0, "arrondir avant de sommer dérive du vrai total")
        self.assertEqual(M.effort_km_week_total(week), 10.1)

    def test_each_week_is_computed_from_its_own_activities_only(self):
        """Une activité du lundi suivant ne doit jamais entrer dans le total de la semaine
        courante : `api_load` doit passer à cette fonction les activités déjà réparties par
        semaine (bucket par lundi), jamais la liste complète sur plusieurs semaines — sans
        quoi l'arrondi unique (voir le test précédent) se ferait sur la mauvaise fenêtre."""
        week1 = [{"sport": "running", "distance_m": 5000, "elevation_gain_m": 4}]      # semaine courante
        week2 = [{"sport": "running", "distance_m": 5000, "elevation_gain_m": 4}]      # lundi suivant
        self.assertEqual(M.effort_km_week_total(week1), 5.0)
        self.assertEqual(M.effort_km_week_total(week2), 5.0)
        # Si les deux semaines étaient fusionnées avant l'arrondi (bug de bucket), le total
        # de la semaine courante s'en trouverait faussé : 10,1 au lieu de 5,0 + 5,0 = 10,0.
        merged = M.effort_km_week_total(week1 + week2)
        self.assertNotEqual(merged, M.effort_km_week_total(week1) + M.effort_km_week_total(week2))
        self.assertEqual(merged, 10.1)


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


class TestWeightMerge(unittest.TestCase):
    """#36 — fusion des deux sources de poids : `health.weight_kg` (mesure du matin) gagne
    toujours sur `nutrition.weight_kg`. Voir `M.ASSUMPTIONS["weight_merge"]`."""

    def test_health_wins_when_both_present_and_differ(self):
        self.assertEqual(M.merge_weight_kg(70.2, 71.0), 70.2)

    def test_health_wins_even_when_nutrition_is_smaller(self):
        """La priorité est à la SOURCE (santé), jamais à la valeur la plus petite ou la plus
        récemment écrite : un nutrition plus « propre » ne doit pas prendre le dessus."""
        self.assertEqual(M.merge_weight_kg(71.0, 70.2), 71.0)

    def test_falls_back_to_nutrition_when_health_missing(self):
        self.assertEqual(M.merge_weight_kg(None, 68.5), 68.5)

    def test_none_when_both_missing(self):
        """Absence des deux sources : `None`, jamais 0 (un 0 kg fausserait une moyenne)."""
        self.assertIsNone(M.merge_weight_kg(None, None))

    def test_health_present_alone(self):
        self.assertEqual(M.merge_weight_kg(70.0, None), 70.0)


class TestWeightAvg7Series(unittest.TestCase):
    """#36 — moyenne mobile 7 j du poids fusionné : jours manquants jamais comptés 0,
    seuil de jours pesés avant d'afficher quoi que ce soit."""

    START = date(2026, 6, 1)

    def series(self, weights_by_offset: dict, days: int = 10):
        """`weights_by_offset` : décalage en jours depuis `START` -> poids fusionné (kg).
        Un décalage absent est un jour sans pesée (jamais 0 kg)."""
        by_date = {(self.START + timedelta(days=k)).isoformat(): v for k, v in weights_by_offset.items()}
        return M.weight_avg7_series(by_date, self.START, self.START + timedelta(days=days - 1))

    def test_missing_days_are_not_zero_in_the_average(self):
        """Fenêtre 0-6 : pesées présentes seulement à 0, 2, 4, 6 (70, 69, 68, 67 kg) — 1, 3, 5
        sont des jours SANS pesée. Moyenne attendue sur les 4 valeurs présentes seulement :
        (70 + 69 + 68 + 67) / 4 = 68,5 — pas 274/7 ≈ 39,1 (ce que donnerait un jour manquant
        compté comme 0 kg)."""
        s = self.series({0: 70.0, 2: 69.0, 4: 68.0, 6: 67.0})
        self.assertEqual(s[6]["weight_avg7_kg"], 68.5)
        self.assertIsNone(s[1]["weight_kg"], "jour sans pesée : poids fusionné absent, jamais 0")

    def test_below_min_valid_days_gives_none(self):
        """`WEIGHT_AVG_MIN_VALID_DAYS` (3) moins un (2 pesées sur 7) : moyenne à `None`
        plutôt qu'une valeur bruitée sur trop peu de points."""
        s = self.series({0: 70.0, 3: 69.0})
        self.assertIsNone(s[6]["weight_avg7_kg"])

    def test_exactly_min_valid_days_is_enough(self):
        """Exactement `WEIGHT_AVG_MIN_VALID_DAYS` (3) pesées sur les 7 derniers jours : la
        moyenne doit être calculée, pas rejetée."""
        s = self.series({0: 70.0, 3: 69.0, 6: 68.0})
        self.assertAlmostEqual(s[6]["weight_avg7_kg"], 69.0)

    def test_window_slides_and_drops_old_values(self):
        """Une pesée ancienne (70 kg, offset 0) sort de la fenêtre 7 j du jour à l'offset 10
        (fenêtre = offsets 4-10) : elle ne doit plus peser sur la moyenne à ce moment-là,
        qui ne porte alors que sur les trois pesées à 60 kg (offsets 8, 9, 10)."""
        s = self.series({0: 70.0, 8: 60.0, 9: 60.0, 10: 60.0}, days=11)
        self.assertAlmostEqual(s[10]["weight_avg7_kg"], 60.0)


class TestWeightSlope(unittest.TestCase):
    """#36 — pente 4 semaines (kg/semaine), régression des moindres carrés sur les valeurs
    fusionnées PRÉSENTES (pas la moyenne lissée)."""

    DAY = date(2026, 6, 28)   # jour évalué ; fenêtre = les 28 jours qui précèdent, lui inclus

    def by_date(self, weights_by_offset_before_day: dict) -> dict:
        """`weights_by_offset_before_day` : nombre de jours AVANT `DAY` (0 = `DAY`) -> poids."""
        return {(self.DAY - timedelta(days=k)).isoformat(): v for k, v in weights_by_offset_before_day.items()}

    def test_hand_computed_linear_loss(self):
        """Perte parfaitement linéaire de 70 kg (il y a 27 j, début de fenêtre) à 69 kg
        (aujourd'hui) pesée chaque jour : 27 intervalles d'un jour sur la fenêtre, pente
        = -1 kg / 27 j × 7 = -7/27 ≈ -0,2593 kg/semaine, exact (points parfaitement alignés)."""
        weights = {k: 69.0 + k * (1.0 / 27) for k in range(28)}   # offset 0 = 69,0 (aujourd'hui) ... offset 27 = 70,0 (il y a 4 semaines)
        by_date = self.by_date(weights)
        slope = M.weight_slope_kg_per_week(by_date, self.DAY)
        self.assertAlmostEqual(slope, -7 / 27, places=3)

    def test_flat_weight_gives_zero_slope(self):
        weights = {k: 68.0 for k in range(28)}
        slope = M.weight_slope_kg_per_week(self.by_date(weights), self.DAY)
        self.assertAlmostEqual(slope, 0.0, places=6)

    def test_below_min_points_gives_none(self):
        """`WEIGHT_SLOPE_MIN_POINTS` (5) moins un (4 pesées dans la fenêtre de 28 j) :
        pas de pente plutôt qu'une régression sur trop peu de points."""
        weights = {0: 70.0, 7: 69.5, 14: 69.0, 21: 68.5}
        slope = M.weight_slope_kg_per_week(self.by_date(weights), self.DAY)
        self.assertIsNone(slope)

    def test_exactly_min_points_is_enough(self):
        weights = {0: 70.0, 7: 69.5, 14: 69.0, 21: 68.5, 27: 68.0}
        slope = M.weight_slope_kg_per_week(self.by_date(weights), self.DAY)
        self.assertIsNotNone(slope)

    def test_below_min_span_gives_none_even_with_enough_points(self):
        """5 pesées (assez pour `WEIGHT_SLOPE_MIN_POINTS`) mais toutes groupées sur 4 jours
        (offsets 0 à 3, sous `WEIGHT_SLOPE_MIN_SPAN_DAYS` = 14) : pas de pente. Sans ce
        second seuil, une régression sur un intervalle aussi court serait extrapolée à tort
        sur 4 semaines entières."""
        weights = {0: 70.0, 1: 69.9, 2: 69.8, 3: 69.7, 4: 69.6}
        slope = M.weight_slope_kg_per_week(self.by_date(weights), self.DAY)
        self.assertIsNone(slope)

    def test_exactly_min_span_is_enough(self):
        """5 pesées (`WEIGHT_SLOPE_MIN_POINTS`), écart de pile `WEIGHT_SLOPE_MIN_SPAN_DAYS`
        (14 j) entre la première et la dernière : la pente doit être calculée, pas
        rejetée."""
        weights = {0: 70.0, 3: 69.8, 6: 69.6, 10: 69.3, 14: 69.0}
        slope = M.weight_slope_kg_per_week(self.by_date(weights), self.DAY)
        self.assertIsNotNone(slope)

    def test_missing_days_never_counted_as_zero(self):
        """Une pesée quotidienne complète sur 28 j sauf un trou (offset 14 absent) : le trou
        ne doit jamais entrer dans la régression comme un poids de 0 kg — la pente resterait
        alors proche de la vraie tendance (légère baisse), pas explosée par un faux 0."""
        weights = {k: 68.0 + k * 0.02 for k in range(28) if k != 14}   # k = jours avant DAY : plus loin dans le passé, plus lourd -> perte
        slope = M.weight_slope_kg_per_week(self.by_date(weights), self.DAY)
        self.assertAlmostEqual(slope, -0.02 * 7, places=2)


class TestWeightTargetGap(unittest.TestCase):
    """#36 — écart (kg) entre la moyenne 7 j et la cible : positif = au-dessus de la cible."""

    def test_above_target_is_positive(self):
        self.assertEqual(M.weight_target_gap_kg(70.0, 67.0), 3.0)

    def test_below_target_is_negative(self):
        self.assertEqual(M.weight_target_gap_kg(65.0, 67.0), -2.0)

    def test_none_when_average_missing(self):
        self.assertIsNone(M.weight_target_gap_kg(None, 67.0))

    def test_none_when_target_missing(self):
        self.assertIsNone(M.weight_target_gap_kg(70.0, None))


class TestSleepDebt(unittest.TestCase):
    """#37 — dette de sommeil 7 j : nuits manquantes jamais comptées 0 h, seuil de
    nuits mesurées avant d'afficher quoi que ce soit, besoin par défaut 7 h 30,
    nuits excédentaires plafonnées à 0 (jamais de dette négative/compensée)."""

    DAY = date(2026, 6, 28)   # jour évalué ; fenêtre = les 7 jours qui précèdent, lui inclus

    def by_date(self, sleep_h_by_offset_before_day: dict) -> dict:
        """`sleep_h_by_offset_before_day` : nb de jours AVANT `DAY` (0 = `DAY`) -> heures dormies."""
        return {(self.DAY - timedelta(days=k)).isoformat(): h * 3600 for k, h in sleep_h_by_offset_before_day.items()}

    def test_hand_computed_debt_over_four_nights(self):
        """4 nuits à 5 h (offsets 0-3), besoin 7 h 30 : dette = 4 × 2,5 h = 10 h, exactement
        au seuil minimal de nuits (`SLEEP_DEBT_MIN_NIGHTS` = 4) — doit être calculée, pas
        rejetée."""
        by_date = self.by_date({0: 5.0, 1: 5.0, 2: 5.0, 3: 5.0})
        result = M.sleep_debt_7d(by_date, self.DAY)
        self.assertEqual(result["nights_counted"], 4)
        self.assertAlmostEqual(result["sleep_debt_7d_s"], 4 * 2.5 * 3600)
        self.assertEqual(result["sleep_need_s"], M.SLEEP_NEED_DEFAULT_S)

    def test_missing_nights_are_not_zero(self):
        """Fenêtre de 7 j avec seulement 4 nuits mesurées (offsets 0, 2, 4, 6) à 6 h : les 3
        nuits absentes ne doivent JAMAIS entrer dans la somme comme des manques de 7 h 30
        (ce qui donnerait 4 × 1,5 h + 3 × 7,5 h = 28,5 h) — seule la dette des nuits
        mesurées compte : 4 × 1,5 h = 6 h."""
        by_date = self.by_date({0: 6.0, 2: 6.0, 4: 6.0, 6: 6.0})
        result = M.sleep_debt_7d(by_date, self.DAY)
        self.assertEqual(result["nights_counted"], 4)
        self.assertAlmostEqual(result["sleep_debt_7d_s"], 4 * 1.5 * 3600)

    def test_below_min_nights_gives_none_but_still_reports_the_count(self):
        """`SLEEP_DEBT_MIN_NIGHTS` (4) moins un (3 nuits mesurées) : `sleep_debt_7d_s` doit
        être `None`, mais `nights_counted` reste rendu (3) — l'appelant doit pouvoir dire
        « il manque des nuits », pas seulement « pas de valeur »."""
        by_date = self.by_date({0: 5.0, 1: 5.0, 2: 5.0})
        result = M.sleep_debt_7d(by_date, self.DAY)
        self.assertIsNone(result["sleep_debt_7d_s"])
        self.assertEqual(result["nights_counted"], 3)

    def test_surplus_nights_are_floored_not_netted(self):
        """3 nuits à 10 h (excédent de 2,5 h chacune) et 4 nuits à 5 h (déficit de 2,5 h
        chacune) : une dette « nette » donnerait 0 (les excédents annuleraient les
        déficits). La dette attendue ne compte QUE les déficits, plafonnés à 0 par nuit
        excédentaire : 4 × 2,5 h = 10 h, jamais 0 ni une valeur négative."""
        by_date = self.by_date({0: 10.0, 1: 10.0, 2: 10.0, 3: 5.0, 4: 5.0, 5: 5.0, 6: 5.0})
        result = M.sleep_debt_7d(by_date, self.DAY)
        self.assertEqual(result["nights_counted"], 7)
        self.assertAlmostEqual(result["sleep_debt_7d_s"], 4 * 2.5 * 3600)

    def test_no_debt_when_sleep_meets_need(self):
        by_date = self.by_date({k: 7.5 for k in range(7)})
        result = M.sleep_debt_7d(by_date, self.DAY)
        self.assertEqual(result["sleep_debt_7d_s"], 0)

    def test_custom_need_from_profile(self):
        """Besoin non par défaut (8 h, ex. profil « Besoin de sommeil »), 7 nuits à 6 h :
        dette = 7 × 2 h = 14 h."""
        by_date = self.by_date({k: 6.0 for k in range(7)})
        result = M.sleep_debt_7d(by_date, self.DAY, need_s=8 * 3600)
        self.assertEqual(result["sleep_need_s"], 8 * 3600)
        self.assertAlmostEqual(result["sleep_debt_7d_s"], 7 * 2 * 3600)

    def test_window_slides_and_drops_old_nights(self):
        """Une nuit ancienne très déficitaire (offset 6, 8 j avant `DAY` avec `days=9`... en
        fait vérifie qu'une nuit hors fenêtre 7 j n'est plus comptée) : seules les 7 nuits
        les plus récentes entrent dans le calcul."""
        # offset 7 = 8e jour avant DAY, HORS de la fenêtre de 7 j (offsets 0-6) : une nuit
        # à 1 h (fortement déficitaire) ne doit donc PAS peser sur la dette du jour évalué.
        by_date = self.by_date({0: 7.5, 1: 7.5, 2: 7.5, 3: 7.5, 7: 1.0})
        result = M.sleep_debt_7d(by_date, self.DAY)
        self.assertEqual(result["nights_counted"], 4, "la nuit à l'offset 7 est hors fenêtre")
        self.assertEqual(result["sleep_debt_7d_s"], 0)

    def test_series_matches_pointwise_computation(self):
        by_date = self.by_date({0: 5.0, 1: 5.0, 2: 5.0, 3: 5.0})
        start = self.DAY - timedelta(days=1)
        series = M.sleep_debt_series(by_date, start, self.DAY)
        self.assertEqual(len(series), 2)
        self.assertEqual(series[-1]["date"], self.DAY.isoformat())
        self.assertEqual(series[-1]["sleep_debt_7d_s"], M.sleep_debt_7d(by_date, self.DAY)["sleep_debt_7d_s"])


class TestNormalizeLocation(unittest.TestCase):
    """#38 — `normalize_location` : nom de ville avant la virgule, accents et casse
    ignorés, pour que `pick_weather`/`pick_weather_strict` reconnaissent le même lieu
    écrit différemment par l'activité et par le fichier météo."""

    def test_strips_country_suffix(self):
        self.assertEqual(M.normalize_location("Annecy, France"), M.normalize_location("Annecy"))

    def test_ignores_accents_and_case(self):
        self.assertEqual(M.normalize_location("Mègève"), M.normalize_location("megeve"))

    def test_none_and_empty_are_none(self):
        self.assertIsNone(M.normalize_location(None))
        self.assertIsNone(M.normalize_location(""))
        self.assertIsNone(M.normalize_location("   "))

    def test_different_cities_do_not_match(self):
        self.assertNotEqual(M.normalize_location("Annecy"), M.normalize_location("Chamonix"))


class TestHeatAcclimation(unittest.TestCase):
    """#38 — acclimatation à la chaleur : jointure activité outdoor / météo du même
    jour sur 14 j, sports indoor exclus, séance sans météo ignorée (jamais froide),
    seuil borne incluse, plusieurs fichiers météo le même jour."""

    END = date(2026, 7, 15)   # jour évalué ; fenêtre = les 14 jours qui précèdent, lui inclus

    def offset(self, k: int) -> str:
        """Date ISO à `k` jours AVANT `END` (0 = `END`)."""
        return (self.END - timedelta(days=k)).isoformat()

    def act(self, offset_days: int, sport: str = "running", duration_s: float = 3600, location: str = None) -> dict:
        d = {"date": self.offset(offset_days), "sport": sport, "duration_s": duration_s}
        if location is not None:
            d["location"] = location
        return d

    def wx(self, offset_days: int, temp_max_c: float, location: str = "Tournai") -> dict:
        return {"date": self.offset(offset_days), "location": location, "temp_max_c": temp_max_c}

    def test_hand_computed_count_and_duration(self):
        """2 séances outdoor chaudes (28°C, 30°C) sur 3 : durée cumulée = somme des deux
        chaudes seulement, la 3e (24°C) reste sous le seuil par défaut (25°C)."""
        activities = [self.act(0, duration_s=3000), self.act(1, duration_s=4000), self.act(2, duration_s=5000)]
        weather = [self.wx(0, 28), self.wx(1, 30), self.wx(2, 24)]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 2)
        self.assertEqual(result["hot_duration_s"], 3000 + 4000)
        self.assertEqual(result["sessions_considered"], 3)
        self.assertEqual(result["sessions_without_weather"], 0)
        self.assertEqual(result["threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertEqual(result["window_days"], M.HEAT_WINDOW_DAYS)

    def test_indoor_sports_are_excluded(self):
        """Renforcement, vélo indoor, home trainer, elliptique : jamais compté même par
        temps caniculaire — seuls sports SANS variante indoor déclarée sont outdoor."""
        activities = [
            self.act(0, sport="strength"), self.act(1, sport="indoor_cycling"),
            self.act(2, sport="home_trainer"), self.act(3, sport="elliptical"),
            self.act(4, sport="rest", duration_s=0),
        ]
        weather = [self.wx(k, 32) for k in range(5)]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 0)
        self.assertEqual(result["sessions_considered"], 0)
        self.assertEqual(result["sessions_without_weather"], 0)

    def test_outdoor_sports_without_an_explicit_indoor_variant_count(self):
        """running, trail, hiking, walking, cycling, swimming, rowing : outdoor par défaut
        (voir ASSUMPTIONS["heat_acclimation"])."""
        sports = ("running", "trail", "hiking", "walking", "cycling", "swimming", "rowing")
        activities = [self.act(i, sport=sp) for i, sp in enumerate(sports)]
        weather = [self.wx(i, 30) for i in range(len(sports))]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], len(sports))
        self.assertEqual(result["sessions_considered"], len(sports))

    def test_missing_weather_is_ignored_not_counted_cold(self):
        """Un jour sans AUCUN fichier météo : la séance n'est ni chaude ni comptée dans
        `sessions_considered` — elle va dans `sessions_without_weather`, séparément."""
        activities = [self.act(0), self.act(1)]
        weather = [self.wx(0, 30)]   # rien pour offset(1)
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 1)
        self.assertEqual(result["sessions_considered"], 1)
        self.assertEqual(result["sessions_without_weather"], 1)

    def test_threshold_boundary_is_inclusive(self):
        """`temp_max_c` exactement égal au seuil (25.0 par défaut) compte comme chaude."""
        activities = [self.act(0)]
        weather = [self.wx(0, 25.0)]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 1)

        activities = [self.act(0)]
        weather = [self.wx(0, 24.999)]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 0)
        self.assertEqual(result["sessions_considered"], 1)

    def test_custom_threshold(self):
        """Seuil configurable ([health].heat_threshold_c) : 30°C avec seuil 30 compte,
        29.9°C ne compte pas."""
        result = M.heat_acclimation([self.act(0)], [self.wx(0, 30.0)], self.END, threshold_c=30.0)
        self.assertEqual(result["hot_sessions"], 1)
        result = M.heat_acclimation([self.act(0)], [self.wx(0, 29.9)], self.END, threshold_c=30.0)
        self.assertEqual(result["hot_sessions"], 0)

    def test_window_edges_14_days(self):
        """Offset 13 (14e jour, dans la fenêtre) compte ; offset 14 (15e jour, hors
        fenêtre) ne compte pas — fenêtre glissante de EXACTEMENT 14 jours, `END` inclus."""
        result = M.heat_acclimation([self.act(13)], [self.wx(13, 30)], self.END)
        self.assertEqual(result["sessions_considered"], 1)
        self.assertEqual(result["hot_sessions"], 1)

        result = M.heat_acclimation([self.act(14)], [self.wx(14, 30)], self.END)
        self.assertEqual(result["sessions_considered"], 0)
        self.assertEqual(result["hot_sessions"], 0)
        self.assertEqual(result["sessions_without_weather"], 0, "hors fenêtre : ni compté ni « sans météo »")

    def test_multiple_weather_files_same_day_prefers_matching_location(self):
        """Deux lieux météo le même jour : la séance prend celui qui correspond à son
        propre lieu (insensible à la casse), jamais l'autre."""
        activities = [self.act(0, location="Tournai")]
        weather = [self.wx(0, 32, location="Palma"), self.wx(0, 18, location="tournai")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 0, "doit prendre Tournai (18°C), pas Palma (32°C)")
        self.assertEqual(result["sessions_considered"], 1)

    def test_multiple_weather_files_same_day_no_match_counts_as_without_weather(self):
        """Deux lieux météo le même jour, aucun ne correspond au lieu de la séance (ou
        séance sans lieu renseigné) : pas de météo devinée, comptée à part."""
        activities = [self.act(0, location="Lille")]
        weather = [self.wx(0, 32, location="Palma"), self.wx(0, 18, location="Tournai")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["sessions_considered"], 0)
        self.assertEqual(result["sessions_without_weather"], 1)

    def test_multiple_weather_files_same_day_no_match_but_all_agree_hot(self):
        """Deux lieux météo le même jour, aucun ne correspond au lieu de la séance, mais
        les DEUX s'accordent sur « chaude » (30°C, 32°C) : le verdict est retenu quand
        même — peu importe lequel des deux lieux est le bon."""
        activities = [self.act(0, location="Lille")]
        weather = [self.wx(0, 32, location="Palma"), self.wx(0, 30, location="Tournai")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["sessions_considered"], 1)
        self.assertEqual(result["hot_sessions"], 1)
        self.assertEqual(result["sessions_without_weather"], 0)

    def test_multiple_weather_files_same_day_no_match_but_all_agree_not_hot(self):
        """Même logique côté « pas chaud » (18°C, 20°C, seuil 25°C)."""
        activities = [self.act(0, location="Lille")]
        weather = [self.wx(0, 18, location="Palma"), self.wx(0, 20, location="Tournai")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["sessions_considered"], 1)
        self.assertEqual(result["hot_sessions"], 0)
        self.assertEqual(result["sessions_without_weather"], 0)

    def test_multiple_weather_files_same_day_disagreement_stays_without_weather(self):
        """Aucune correspondance de lieu ET désaccord (32°C vs 18°C) : pas de verdict
        deviné, comptée à part — reproduit le test existant, verrouille la régression."""
        activities = [self.act(0, location="Lille")]
        weather = [self.wx(0, 32, location="Palma"), self.wx(0, 18, location="Tournai")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["sessions_considered"], 0)
        self.assertEqual(result["sessions_without_weather"], 1)

    def test_location_matching_ignores_country_suffix_and_accents(self):
        """« Annecy » (activité) doit reconnaître « Annecy, France » (météo) — comparaison
        sur le nom de ville avant la virgule, accents et casse ignorés."""
        activities = [self.act(0, location="Annecy")]
        weather = [self.wx(0, 32, location="Annecy, France"), self.wx(0, 18, location="Megève")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 1, "doit prendre Annecy (32°C), pas Megève")

        activities = [self.act(0, location="Megeve")]   # sans accent côté activité
        weather = [self.wx(0, 32, location="Annecy"), self.wx(0, 18, location="Mègève, France")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 0, "doit prendre Megève (18°C) malgré l'accent/la virgule")

    def test_single_weather_file_applies_regardless_of_location_text(self):
        """Un seul fichier météo ce jour-là : il s'applique, même si son `location` ne
        correspond pas exactement à celui de l'activité (lieu imprécis, alias)."""
        activities = [self.act(0, location="Lille")]
        weather = [self.wx(0, 30, location="Villeneuve-d'Ascq")]
        result = M.heat_acclimation(activities, weather, self.END)
        self.assertEqual(result["hot_sessions"], 1)
        self.assertEqual(result["sessions_without_weather"], 0)

    def test_pick_weather_strict_never_falls_back_to_the_lone_file(self):
        """`pick_weather_strict` (utilisé pour la météo de la course d'un objectif) NE
        reprend PAS le raccourci « un seul fichier => il s'applique » de `pick_weather` :
        un fichier météo de Tournai (lieu d'entraînement) ne doit jamais répondre pour
        une course à Chamonix."""
        self.assertIsNone(M.pick_weather_strict([self.wx(0, 28, location="Tournai")], "Chamonix"))
        self.assertIsNone(M.pick_weather_strict([self.wx(0, 28, location="Tournai")], None))
        self.assertIsNone(M.pick_weather_strict([], "Chamonix"))

    def test_pick_weather_strict_matches_normalized_location(self):
        rows = [self.wx(0, 28, location="Tournai"), self.wx(0, 12, location="Chamonix, France")]
        found = M.pick_weather_strict(rows, "chamonix")
        self.assertIsNotNone(found)
        self.assertEqual(found["temp_max_c"], 12)

    def test_zero_hot_sessions_is_a_valid_result(self):
        """Aucun seuil minimal de séances avant affichage (contrairement à sleep_debt) :
        0 séance chaude est une réponse en soi."""
        result = M.heat_acclimation([], [], self.END)
        self.assertEqual(result["hot_sessions"], 0)
        self.assertEqual(result["hot_duration_s"], 0)
        self.assertEqual(result["sessions_considered"], 0)
        self.assertEqual(result["sessions_without_weather"], 0)


class TestGearMileage(unittest.TestCase):
    """#40 — `arc_metrics.gear_mileage` : attribution, seuils, chaussure inconnue,
    retraite. Voir `ASSUMPTIONS["gear_mileage"]` pour la méthode complète."""

    def shoe(self, gear_id, **kw):
        return {"gear_id": gear_id, "name": kw.pop("name", gear_id), **kw}

    def act(self, sport="running", distance_m=10000, gear_id=None):
        d = {"sport": sport, "distance_m": distance_m}
        if gear_id is not None:
            d["gear_id"] = gear_id
        return d

    def test_explicit_gear_id_is_summed(self):
        gear = [self.shoe("a"), self.shoe("b")]
        acts = [self.act(gear_id="a", distance_m=5000), self.act(gear_id="a", distance_m=3000),
                self.act(gear_id="b", distance_m=1000)]
        result = M.gear_mileage(acts, gear)
        by_id = {s["gear_id"]: s["distance_m"] for s in result["shoes"]}
        self.assertEqual(by_id, {"a": 8000, "b": 1000})

    def test_activity_without_gear_id_falls_back_to_default(self):
        gear = [self.shoe("a", default=True), self.shoe("b")]
        acts = [self.act(distance_m=5000)]
        result = M.gear_mileage(acts, gear)
        by_id = {s["gear_id"]: s["distance_m"] for s in result["shoes"]}
        self.assertEqual(by_id, {"a": 5000, "b": 0})

    def test_activity_without_gear_id_and_no_default_is_ignored(self):
        """Critère d'acceptation #40 : sans chaussure par défaut déclarée, une
        séance sans `gear_id` n'est ni comptée ni signalée."""
        gear = [self.shoe("a")]
        result = M.gear_mileage([self.act(distance_m=5000)], gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 0)
        self.assertEqual(result["unknown"], [])

    def test_unknown_gear_id_is_reported_not_dropped(self):
        result = M.gear_mileage([self.act(gear_id="jamais-declaree", distance_m=4000)], [self.shoe("a")])
        self.assertEqual(result["unknown"], [{"gear_id": "jamais-declaree", "distance_m": 4000}])
        self.assertEqual(result["shoes"][0]["distance_m"], 0)

    def test_non_wear_sport_never_counted_even_with_explicit_gear_id(self):
        result = M.gear_mileage([self.act(sport="cycling", gear_id="a", distance_m=50000)], [self.shoe("a")])
        self.assertEqual(result["shoes"][0]["distance_m"], 0)

    def test_hiking_counts_as_wear(self):
        result = M.gear_mileage([self.act(sport="hiking", gear_id="a", distance_m=12000)], [self.shoe("a")])
        self.assertEqual(result["shoes"][0]["distance_m"], 12000)

    def test_activity_without_distance_is_ignored(self):
        result = M.gear_mileage([{"sport": "running", "gear_id": "a"}], [self.shoe("a")])
        self.assertEqual(result["shoes"][0]["distance_m"], 0)

    def test_threshold_boundary_is_inclusive(self):
        gear = [self.shoe("a", threshold_m=700000)]
        below = M.gear_mileage([self.act(distance_m=699999, gear_id="a")], gear)
        at = M.gear_mileage([self.act(distance_m=700000, gear_id="a")], gear)
        self.assertFalse(below["shoes"][0]["alert"])
        self.assertTrue(at["shoes"][0]["alert"])

    def test_default_threshold_applies_when_not_declared(self):
        gear = [self.shoe("a")]
        result = M.gear_mileage([self.act(distance_m=M.GEAR_ALERT_THRESHOLD_M_DEFAULT, gear_id="a")], gear)
        self.assertTrue(result["shoes"][0]["alert"])
        self.assertEqual(result["shoes"][0]["threshold_m"], M.GEAR_ALERT_THRESHOLD_M_DEFAULT)

    def test_retired_shoe_never_alerts_even_past_threshold(self):
        gear = [self.shoe("a", retired=True, threshold_m=1000)]
        result = M.gear_mileage([self.act(distance_m=5000, gear_id="a")], gear)
        self.assertFalse(result["shoes"][0]["alert"])

    def test_retired_default_is_not_used_for_attribution(self):
        """Une chaussure retirée, même marquée `(par défaut)`, ne doit jamais
        récupérer les séances sans `gear_id` — priorité retraite avant défaut."""
        gear = [self.shoe("a", default=True, retired=True)]
        result = M.gear_mileage([self.act(distance_m=5000)], gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 0)
        self.assertEqual(result["unknown"], [])

    def test_start_date_is_informational_not_a_filter(self):
        """Une activité portant le `gear_id` compte même datée avant `depuis` :
        voir `ASSUMPTIONS["gear_mileage"]`."""
        gear = [self.shoe("a", start_date="2026-06-01")]
        result = M.gear_mileage([self.act(gear_id="a", distance_m=5000)], gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 5000)

    def test_declared_shoe_with_no_activity_still_listed_at_zero(self):
        result = M.gear_mileage([], [self.shoe("a")])
        self.assertEqual(result["shoes"], [{
            "gear_id": "a", "name": "a", "distance_m": 0, "threshold_m": M.GEAR_ALERT_THRESHOLD_M_DEFAULT,
            "start_date": None, "default": False, "retired": False, "alert": False,
        }])

    # -- revue PR #85, blocker 1 : date `depuis` filtre l'attribution PAR DÉFAUT --

    def test_default_shoe_start_date_excludes_earlier_gearless_activities(self):
        """Repro exacte du bug signalé : une chaussure par défaut déclarée
        `depuis` hier ne doit pas hériter de tout l'historique sans `gear_id`
        (des années d'activités d'avant #39, où `gear_id` n'existait pas)."""
        gear = [self.shoe("clifton", default=True, start_date="2026-09-15")]
        acts = [self.act(distance_m=10000)] * 96
        for a in acts:
            a["date"] = "2025-01-15"   # bien avant `depuis`
        result = M.gear_mileage(acts, gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 0)
        self.assertFalse(result["shoes"][0]["alert"])

    def test_default_shoe_start_date_includes_later_gearless_activities(self):
        gear = [self.shoe("clifton", default=True, start_date="2026-09-15")]
        acts = [self.act(distance_m=10000)]
        acts[0]["date"] = "2026-09-20"   # après `depuis`
        result = M.gear_mileage(acts, gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 10000)

    def test_default_shoe_start_date_boundary_is_inclusive(self):
        gear = [self.shoe("clifton", default=True, start_date="2026-09-15")]
        acts = [self.act(distance_m=10000)]
        acts[0]["date"] = "2026-09-15"   # égal à `depuis`
        result = M.gear_mileage(acts, gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 10000)

    def test_default_shoe_without_start_date_has_no_filter(self):
        """Sans `depuis` déclaré, comportement inchangé : tout historique compte."""
        gear = [self.shoe("clifton", default=True)]
        acts = [self.act(distance_m=10000)]
        acts[0]["date"] = "2020-01-01"
        result = M.gear_mileage(acts, gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 10000)

    def test_default_shoe_missing_activity_date_is_excluded_when_start_date_set(self):
        """Sans `date` sur l'activité, impossible de vérifier `>= depuis` : on
        n'attribue PAS, plutôt que de risquer la même surestimation silencieuse."""
        gear = [self.shoe("clifton", default=True, start_date="2026-09-15")]
        result = M.gear_mileage([self.act(distance_m=10000)], gear)   # pas de "date"
        self.assertEqual(result["shoes"][0]["distance_m"], 0)

    def test_explicit_gear_id_never_filtered_by_default_shoe_start_date(self):
        """L'explicite du `gear_id` prime toujours — seule l'attribution PAR
        DÉFAUT est filtrée par `depuis` (voir ASSUMPTIONS)."""
        gear = [self.shoe("clifton", default=True, start_date="2026-09-15")]
        acts = [self.act(gear_id="clifton", distance_m=10000)]
        acts[0]["date"] = "2025-01-15"   # avant `depuis`, mais gear_id explicite
        result = M.gear_mileage(acts, gear)
        self.assertEqual(result["shoes"][0]["distance_m"], 10000)

    # -- revue PR #85, blocker 2 : collision de slug signalée --------------

    def test_collision_base_surfaces_a_warning(self):
        gear = [self.shoe("hoka-speedgoat-5", name="Hoka Speedgoat 5"),
                self.shoe("hoka-speedgoat-5-2", name="Hoka Speedgoat 5", collision_base="hoka-speedgoat-5")]
        result = M.gear_mileage([], gear)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("hoka-speedgoat-5", result["warnings"][0])

    def test_no_collision_no_warnings(self):
        result = M.gear_mileage([], [self.shoe("a"), self.shoe("b")])
        self.assertEqual(result["warnings"], [])

    # -- revue PR #85, nit : sérialisation du seuil normalisée --------------

    def test_threshold_is_always_an_int(self):
        gear = [self.shoe("a", threshold_m=500000.0), self.shoe("b")]
        result = M.gear_mileage([], gear)
        for shoe in result["shoes"]:
            self.assertIsInstance(shoe["threshold_m"], int)


if __name__ == "__main__":
    unittest.main()
