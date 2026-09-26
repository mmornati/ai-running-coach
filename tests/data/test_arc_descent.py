"""Palier D — Efficacité en descente par classe de pente (#47).

Familles de tests :
- `arc_descent.grade_class_descent`/`DESCENT_GRADE_CLASSES` : bornes, alignement
  PARTIEL avec `arc_climb.GRADE_CLASSES` (#46) — scindé au-delà de -20 % (revue
  de code, le coût de Minetti n'est pas monotone en descente).
- `arc_descent.reference_gap_speed_ms` : référence plate, repli hors forte
  descente, invariance au reste du parcours (BLOQUANT, revue de code).
- `arc_descent.descent_speed_by_grade_class` : vitesse/allure synthétique à
  vérité connue, seuil minimal par classe (durée OU distance), échantillons à
  l'arrêt exclus, trou de signal jamais comblé, pente moyenne exposée.
- `arc_descent.descent_report` : restriction à la famille course à pied,
  raisons/`reason_code`/`applicable` explicites, robustesse au bruit sur un
  plat, indicateur = 1,0 sur une descente synthétique bâtie à partir d'une
  référence plate réelle (pas une référence auto-référentielle).
- `arc_index` : table `activity_descent_class`, colonnes
  `activity.descent_reference_*`, CLI `descent --activity`/`descent --weeks`,
  garde-fou de `compute_metrics`.
- `arc_metrics.descent_trend` : regroupement par `activity_id` (jamais
  `(date, name, sport)`, revue de code should-fix 3).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_descent as DS  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_index as I  # noqa: E402
import arc_metrics as M  # noqa: E402


def _series_at_constant_grade(*, grade, speed_ms, duration_s, gap_speed_ms, resolution_s=5.0, t0=0.0):
    """Série DÉJÀ augmentée (comme `arc_gap.gap_sample_series` le ferait), à
    pente et vitesse CONSTANTES — vérité connue, sans dépendre de la fenêtre de
    calcul de pente réelle (`arc_elevation.grade_series`), testée séparément."""
    n = int(duration_s // resolution_s) + 1
    return [{"t_s": t0 + i * resolution_s, "speed_ms": speed_ms, "grade": grade, "gap_speed_ms": gap_speed_ms}
            for i in range(n)]


def _segment(t0, dist0, alt0, *, duration_s, grade, speed_ms, resolution_s=5.0,
             hr_bpm=140.0, cadence_spm=165.0):
    """Un tronçon à pente et vitesse CONSTANTES, échantillons FIT bruts, en
    repartant de `(t0, dist0, alt0)` — brique de base pour composer une séance
    complète (plat + montée + descente...) sans trou de signal. Rend
    `(records, (t_fin, dist_fin, alt_fin))`."""
    out = []
    t, dist, alt = t0, dist0, alt0
    n = int(duration_s // resolution_s) + 1
    for _ in range(n):
        out.append({"t_s": t, "distance_m": round(dist, 2), "altitude_m": round(alt, 2),
                     "speed_ms": speed_ms, "hr_bpm": hr_bpm, "cadence_spm": cadence_spm})
        t += resolution_s
        dist += speed_ms * resolution_s
        alt += grade * speed_ms * resolution_s
    return out, (t, dist, alt)


def _route(segments, *, alt0=1000.0, resolution_s=5.0):
    """Concatène des tronçons `(duration_s, grade, speed_ms)` en une seule
    séance continue (jamais de trou de signal entre deux tronçons)."""
    out = []
    t = dist = 0.0
    alt = alt0
    for duration_s, grade, speed_ms in segments:
        recs, (t, dist, alt) = _segment(t, dist, alt, duration_s=duration_s, grade=grade,
                                         speed_ms=speed_ms, resolution_s=resolution_s)
        out.extend(recs)
    return out


def _linear_descent_samples(*, duration_s, grade, speed_ms, resolution_s=5, alt0=1000.0):
    """Descente linéaire SEULE (pas de plat, pas de hors-forte-descente) — sert
    UNIQUEMENT à vérifier qu'une telle séance n'a plus de référence du tout
    (voir `TestReferenceGapSpeed`/`ASSUMPTIONS["reference"]`). Tout le reste des
    tests utilise `_route`/`_flat_then_descent_samples`, qui incluent un tronçon
    plat exploitable comme référence."""
    return _route([(duration_s, grade, speed_ms)], alt0=alt0, resolution_s=resolution_s)


def _flat_then_descent_samples(*, descent_duration_s, grade, speed_ms,
                                flat_duration_s=360.0, flat_speed_ms=2.7, resolution_s=5, alt0=1000.0):
    """Un tronçon PLAT (`flat_duration_s`, défaut 360 s = 6 min, au-dessus de
    `arc_descent.MIN_REFERENCE_DURATION_S`) puis une descente linéaire à pente
    et vitesse constantes — la référence « plat » (`arc_descent.
    reference_gap_speed_ms`, BLOQUANT revue de code) a besoin d'un tel tronçon
    pour être calculable : une descente seule (`_linear_descent_samples`) n'en a
    PLUS aucune."""
    return _route([(flat_duration_s, 0.0, flat_speed_ms), (descent_duration_s, grade, speed_ms)],
                  alt0=alt0, resolution_s=resolution_s)


class TestGradeClassDescentBoundaries(unittest.TestCase):
    def test_flat_and_uphill_are_not_classified(self):
        self.assertIsNone(DS.grade_class_descent(None))
        self.assertIsNone(DS.grade_class_descent(0.0))
        self.assertIsNone(DS.grade_class_descent(0.12))  # montée : jamais classée ici

    def test_below_min_descent_grade_is_not_classified(self):
        self.assertIsNone(DS.grade_class_descent(-0.02))

    def test_each_class_boundary(self):
        self.assertEqual(DS.grade_class_descent(-0.05), "-5 à -10 %")
        self.assertEqual(DS.grade_class_descent(-0.099), "-5 à -10 %")
        self.assertEqual(DS.grade_class_descent(-0.10), "-10 à -15 %")
        self.assertEqual(DS.grade_class_descent(-0.15), "-15 à -20 %")
        self.assertEqual(DS.grade_class_descent(-0.25), "-20 à -30 %")
        self.assertEqual(DS.grade_class_descent(-0.35), "< -30 %")

    def test_classes_mirror_arc_climb_grade_classes_only_up_to_20_percent(self):
        """#46 (`arc_climb.ASSUMPTIONS["grade_classes"]`) anticipait cette
        réutilisation, mais SEULEMENT pour les 3 classes intermédiaires — voir
        `ASSUMPTIONS["grade_classes"]` : au-delà de -20 %, le coût de Minetti
        n'est pas monotone en descente (contrairement à la montée), donc PAS de
        miroir direct de la classe ascendante `>20%` (scindée en deux ici)."""
        import arc_climb as VC
        ascending_mid = [(lo, hi) for lo, hi, _ in VC.GRADE_CLASSES[1:4]]
        descending_mid = [(lo, hi) for lo, hi, _ in DS.DESCENT_GRADE_CLASSES[:3]]
        self.assertEqual(ascending_mid, descending_mid)
        # Au-delà de -20 %, DEUX classes distinctes (pas de miroir avec l'ascendant).
        self.assertEqual([(lo, hi) for lo, hi, _ in DS.DESCENT_GRADE_CLASSES[3:]],
                          [(0.20, 0.30), (0.30, float("inf"))])


class TestReferenceGapSpeed(unittest.TestCase):
    """BLOQUANT, revue de code #47 : la référence ne doit JAMAIS être l'allure
    GAP de toute la séance (se contamine avec l'effort des descentes/montées à
    mesurer) — elle doit venir des sections plates, ou à défaut hors forte
    descente, de LA MÊME séance."""

    def test_flat_section_is_used_as_reference(self):
        samples = _flat_then_descent_samples(descent_duration_s=180, grade=-0.12, speed_ms=3.4,
                                              flat_duration_s=360, flat_speed_ms=2.7)
        series = G.gap_sample_series(samples)
        speed, source = DS.reference_gap_speed_ms(series)
        self.assertIsNotNone(speed)
        self.assertEqual(source, "flat")
        # Sur un plat, GAP == vitesse mesurée (C(0)/C(0) == 1) : la référence doit
        # donc être proche de la vitesse plate imposée (2,7 m/s).
        self.assertAlmostEqual(speed, 2.7, delta=0.05)

    def test_falls_back_to_non_descent_when_no_flat_section_is_long_enough(self):
        """Un profil de trail montagnard sans replat suffisant (ici : une montée
        puis une descente, aucun tronçon plat) replie sur TOUT ce qui n'est pas
        une forte descente (`pente > -MIN_DESCENT_GRADE`, donc la montée) —
        jamais sur la descente elle-même."""
        samples = _route([(400, 0.10, 2.0), (200, -0.12, 3.0)])
        series = G.gap_sample_series(samples)
        speed, source = DS.reference_gap_speed_ms(series)
        self.assertIsNotNone(speed)
        self.assertEqual(source, "non_descent")

    def test_pure_descent_alone_has_no_reference_at_all(self):
        """Aucun plat, aucun hors-forte-descente : `(None, None)`, jamais une
        valeur bruitée sur presque rien (voir ASSUMPTIONS['reference'])."""
        samples = _linear_descent_samples(duration_s=600, grade=-0.12, speed_ms=3.0)
        series = G.gap_sample_series(samples)
        speed, source = DS.reference_gap_speed_ms(series)
        self.assertIsNone(speed)
        self.assertIsNone(source)

    def test_short_flat_below_threshold_falls_back_to_non_descent(self):
        """Un plat de seulement 2 minutes (sous `MIN_REFERENCE_DURATION_S`,
        5 min) n'est PAS retenu comme référence — repli sur le hors-forte-
        descente (ici une montée) plutôt qu'une référence plate bruitée."""
        samples = _route([(120, 0.0, 2.7), (400, 0.10, 2.0), (200, -0.12, 3.0)])
        series = G.gap_sample_series(samples)
        speed, source = DS.reference_gap_speed_ms(series)
        self.assertIsNotNone(speed)
        self.assertEqual(source, "non_descent")


class TestReferenceInvarianceAcrossRouteContent(unittest.TestCase):
    """BLOQUANT, revue de code #47 : une MÊME descente (même pente, même
    vitesse) doit obtenir la MÊME efficacité quel que soit le reste du
    parcours — avant ce correctif, la référence (allure GAP de toute la
    séance) se contaminait avec l'effort fourni ailleurs, si bien qu'une
    descente identique notait différemment selon le relief environnant
    (mesuré, avant correctif : 0,68 à 0,89 pour la même descente), et une
    descente plus longue changeait SA PROPRE efficacité en pesant plus lourd
    dans sa propre référence."""

    GRADE = -0.12
    DESCENT_SPEED = 3.4
    FLAT_SPEED = 2.7

    def test_same_descent_scores_the_same_regardless_of_extra_climb_and_length(self):
        # Route A : plat (6 min) + descente (3 min).
        route_a = _route([(360, 0.0, self.FLAT_SPEED), (180, self.GRADE, self.DESCENT_SPEED)])
        # Route B : MÊME plat (6 min) + montée additionnelle (10 min, absente de A) +
        # LA MÊME descente mais DEUX FOIS PLUS LONGUE (6 min) + un peu de plat final.
        route_b = _route([
            (360, 0.0, self.FLAT_SPEED),
            (600, 0.10, 2.0),
            (360, self.GRADE, self.DESCENT_SPEED),
            (120, 0.0, self.FLAT_SPEED),
        ])
        report_a = DS.descent_report(route_a, "trail")
        report_b = DS.descent_report(route_b, "trail")
        self.assertIsNone(report_a["reason"])
        self.assertIsNone(report_b["reason"])
        cls = "-10 à -15 %"
        self.assertIn(cls, report_a["classes"])
        self.assertIn(cls, report_b["classes"])
        eff_a = report_a["classes"][cls]["efficiency"]
        eff_b = report_b["classes"][cls]["efficiency"]
        self.assertAlmostEqual(eff_a, eff_b, delta=0.02,
                                msg=f"efficacité A={eff_a} vs B={eff_b} — la référence ne doit "
                                    "jamais varier avec le reste du parcours")
        # Les deux routes doivent aussi avoir choisi la même SOURCE de référence
        # (le plat, présent identique dans les deux routes).
        self.assertEqual(report_a["reference_source"], "flat")
        self.assertEqual(report_b["reference_source"], "flat")


class TestKnownDescentSpeedPerClass(unittest.TestCase):
    """Critère d'acceptation de #47 : descente synthétique à allure imposée par
    classe -> vitesse/allure exacte retrouvée."""

    def test_speed_and_pace_match_the_imposed_value(self):
        series = _series_at_constant_grade(grade=-0.08, speed_ms=3.0, duration_s=600, gap_speed_ms=2.0)
        out = DS.descent_speed_by_grade_class(series)
        self.assertIn("-5 à -10 %", out)
        c = out["-5 à -10 %"]
        self.assertAlmostEqual(c["mean_speed_ms"], 3.0, places=2)
        self.assertAlmostEqual(c["mean_pace_s_km"], 1000.0 / 3.0, places=0)
        self.assertAlmostEqual(c["duration_moving_s"], 600.0, delta=5.0)
        self.assertAlmostEqual(c["mean_grade"], -0.08, places=3)

    def test_efficiency_on_a_manufactured_series_with_a_matching_reference(self):
        """Cas unitaire de contrôle (pas le critère d'acceptation lui-même — voir
        `TestDescentReportEfficiencyEqualsOneOnARealFlatPlusDescentRoute`
        ci-dessous pour la version bout en bout, sur une VRAIE référence
        calculée, pas fournie à la main) : sur une série DÉJÀ augmentée à pente
        et GAP constants, fournir directement la vitesse GAP correspondante
        comme référence donne bien 1,0 — vérifie que l'arithmétique de
        `descent_speed_by_grade_class` (division par la référence) est
        correcte, indépendamment de la façon dont la référence est calculée."""
        grade, speed = -0.12, 3.5
        gap_speed = G.gap_speed_ms(speed, grade)
        series = _series_at_constant_grade(grade=grade, speed_ms=speed, duration_s=600, gap_speed_ms=gap_speed)
        out = DS.descent_speed_by_grade_class(series, reference_gap_speed_ms=gap_speed)
        c = out["-10 à -15 %"]
        self.assertAlmostEqual(c["efficiency"], 1.0, places=6)

    def test_efficiency_is_none_without_a_reference(self):
        series = _series_at_constant_grade(grade=-0.08, speed_ms=3.0, duration_s=600, gap_speed_ms=2.0)
        out = DS.descent_speed_by_grade_class(series, reference_gap_speed_ms=None)
        self.assertIsNone(out["-5 à -10 %"]["efficiency"])


class TestDescentReportEfficiencyEqualsOneOnARealFlatPlusDescentRoute(unittest.TestCase):
    """Critère d'acceptation de #47 (indicateur = 1,0 à l'allure prédite par le
    modèle) — revue de code, should-fix 7 : la version précédente de ce test
    fournissait une référence auto-référentielle (calculée depuis la classe
    elle-même), ce qui aurait fait passer N'IMPORTE QUELLE formule. Ici, la
    référence est calculée par le VRAI pipeline (`descent_report` ->
    `reference_gap_speed_ms`) à partir d'un tronçon plat séparé, et la vitesse
    de descente est choisie pour correspondre exactement à la prédiction du
    modèle à partir de CETTE référence — `v_flat × C(0)/C(pente)`."""

    def test_descent_at_the_models_predicted_speed_scores_close_to_one(self):
        grade = -0.12
        v_flat = 2.7
        predicted_descent_speed = v_flat * G.MINETTI_FLAT_COST / G.minetti_cost(grade)
        samples = _flat_then_descent_samples(descent_duration_s=300, grade=grade,
                                              speed_ms=predicted_descent_speed,
                                              flat_duration_s=360, flat_speed_ms=v_flat)
        report = DS.descent_report(samples, "trail")
        self.assertIsNone(report["reason"])
        self.assertEqual(report["reference_source"], "flat")
        cls = "-10 à -15 %"
        self.assertIn(cls, report["classes"])
        # Tolérance large (fenêtrage de la pente, `arc_elevation.grade_series`,
        # lisse la transition plat -> descente sur quelques dizaines de mètres) :
        # le cœur du test est que l'écart à 1,0 reste faible, pas nul au bit près.
        self.assertAlmostEqual(report["classes"][cls]["efficiency"], 1.0, delta=0.05)


class TestMinimumThresholdPerClass(unittest.TestCase):
    """Critère d'acceptation de #47 : « classes sans assez de données -> absentes »."""

    def test_class_absent_below_both_thresholds(self):
        # 60 s à 1 m/s -> 60 m : sous MIN_CLASS_DURATION_S (120 s) ET MIN_CLASS_DISTANCE_M (300 m).
        series = _series_at_constant_grade(grade=-0.08, speed_ms=1.0, duration_s=60, gap_speed_ms=0.8)
        out = DS.descent_speed_by_grade_class(series)
        self.assertEqual(out, {})

    def test_class_present_when_only_the_distance_threshold_is_met(self):
        # 60 s à 10 m/s -> 600 m (>= 300 m) alors que la durée (60 s) reste sous 120 s :
        # UN SEUL des deux seuils suffit (jamais les deux exigés ensemble).
        series = _series_at_constant_grade(grade=-0.08, speed_ms=10.0, duration_s=60, gap_speed_ms=8.0)
        out = DS.descent_speed_by_grade_class(series)
        self.assertIn("-5 à -10 %", out)

    def test_class_present_when_only_the_duration_threshold_is_met(self):
        # 150 s (>= 120 s) à 1 m/s -> 150 m, sous 300 m.
        series = _series_at_constant_grade(grade=-0.08, speed_ms=1.0, duration_s=150, gap_speed_ms=0.8)
        out = DS.descent_speed_by_grade_class(series)
        self.assertIn("-5 à -10 %", out)


class TestStoppedSamplesExcluded(unittest.TestCase):
    def test_a_stop_in_the_middle_never_lowers_the_mean_speed(self):
        """Voir `ASSUMPTIONS["moving_only"]` : un arrêt (vitesse sous
        `arc_gap.STOPPED_SPEED_MS`) est exclu de l'agrégat, jamais compté comme
        un instant de descente très lente."""
        first = _series_at_constant_grade(grade=-0.11, speed_ms=3.0, duration_s=300, gap_speed_ms=2.0)
        stop_t0 = first[-1]["t_s"] + 5.0
        stop = [{"t_s": stop_t0 + i * 5.0, "speed_ms": 0.0, "grade": -0.11, "gap_speed_ms": 0.0}
                for i in range(60)]  # 5 minutes d'arrêt
        second_t0 = stop[-1]["t_s"] + 5.0
        second = _series_at_constant_grade(grade=-0.11, speed_ms=3.0, duration_s=300, gap_speed_ms=2.0, t0=second_t0)
        out = DS.descent_speed_by_grade_class(first + stop + second)
        c = out["-10 à -15 %"]
        self.assertAlmostEqual(c["mean_speed_ms"], 3.0, places=2)


class TestSignalGapNeverInflatesDuration(unittest.TestCase):
    def test_a_large_time_gap_between_two_chunks_is_never_counted_as_moving_time(self):
        """Même discipline que `arc_gap.weighted_average`/`arc_metrics.
        _time_weighted_buckets` : chaque échantillon pèse au plus
        `resolution_s`, jamais l'écart brut jusqu'au suivant — un trou de
        signal de 30 minutes entre deux morceaux de descente ne doit donc
        JAMAIS gonfler `duration_moving_s` de 1800 s."""
        first = _series_at_constant_grade(grade=-0.09, speed_ms=3.0, duration_s=300, gap_speed_ms=2.0)
        gap_t0 = first[-1]["t_s"] + 1800.0  # trou de signal de 30 minutes
        second = _series_at_constant_grade(grade=-0.09, speed_ms=3.0, duration_s=300, gap_speed_ms=2.0, t0=gap_t0)
        out = DS.descent_speed_by_grade_class(first + second)
        c = out["-5 à -10 %"]
        self.assertLess(c["duration_moving_s"], 650.0, c)


class TestDescentReportSportRestrictionAndReasons(unittest.TestCase):
    def test_non_run_family_has_an_explicit_reason(self):
        samples = _flat_then_descent_samples(descent_duration_s=600, grade=-0.10, speed_ms=3.0)
        report = DS.descent_report(samples, "indoor_cycling")
        self.assertEqual(report["classes"], {})
        self.assertIn("course à pied", report["reason"])
        self.assertEqual(report["reason_code"], "not_run_family")
        self.assertFalse(report["applicable"])

    def test_hiking_is_included_in_the_run_family(self):
        samples = _flat_then_descent_samples(descent_duration_s=600, grade=-0.10, speed_ms=1.5,
                                              flat_speed_ms=1.3)
        report = DS.descent_report(samples, "hiking")
        self.assertIsNone(report["reason"])
        self.assertTrue(report["applicable"])

    def test_no_samples_has_an_explicit_reason(self):
        report = DS.descent_report([], "trail")
        self.assertIn("aucun échantillon FIT", report["reason"])
        self.assertEqual(report["reason_code"], "no_samples")

    def test_pure_descent_without_reference_has_an_explicit_reason(self):
        """Revue de code, BLOQUANT : une descente SEULE (aucun plat, aucun
        hors-forte-descente exploitable) n'a plus de référence — `reason_code`
        distingue explicitement ce cas (`"no_reference"`) de l'absence de
        classe qualifiante par ailleurs (`"no_qualifying_class"`)."""
        samples = _linear_descent_samples(duration_s=600, grade=-0.12, speed_ms=3.0)
        report = DS.descent_report(samples, "trail")
        self.assertEqual(report["classes"], {})
        self.assertEqual(report["reason_code"], "no_reference")
        self.assertIsNone(report["reference_gap_pace_s_km"])
        self.assertIsNone(report["reference_source"])

    def test_downhill_run_produces_a_qualifying_class_with_a_reference(self):
        samples = _flat_then_descent_samples(descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        report = DS.descent_report(samples, "trail")
        self.assertIsNone(report["reason"])
        self.assertIsNone(report["reason_code"])
        self.assertTrue(report["applicable"])
        self.assertTrue(report["classes"])
        self.assertIsNotNone(report["reference_gap_pace_s_km"])
        self.assertEqual(report["reference_source"], "flat")
        for cls, v in report["classes"].items():
            self.assertIsNotNone(v["efficiency"], cls)
            self.assertIsNotNone(v["mean_grade"], cls)

    def test_flat_noise_produces_no_qualifying_class_but_an_explicit_reason(self):
        """Robustesse au bruit (comme `arc_climb`/#46) : un jitter d'altitude de
        quelques dizaines de centimètres sur un parcours plat ne doit jamais
        produire de fausse classe de pente descendante — la référence, elle,
        reste calculable (le plat bruité EST un plat)."""
        import random
        rng = random.Random(11)
        samples = []
        t, dist = 0.0, 0.0
        for _ in range(400):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": rng.uniform(-0.3, 0.3),
                             "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0})
            t += 5
            dist += 2.7 * 5
        report = DS.descent_report(samples, "trail")
        self.assertEqual(report["classes"], {})
        self.assertEqual(report["reason_code"], "no_qualifying_class")
        self.assertIsNotNone(report["reference_gap_pace_s_km"])


# ---------------------------------------------------------------------------
# arc_metrics.descent_trend : regroupement par activity_id
# ---------------------------------------------------------------------------


class TestDescentTrendGroupsByActivityId(unittest.TestCase):
    def test_two_same_day_same_name_activities_are_not_merged(self):
        """Revue de code, should-fix 3, BLOQUANT : deux séances DISTINCTES le
        même jour, même nom générique (deux sorties bi-quotidiennes) doivent
        rester deux entrées séparées dans `activities` — jamais fusionnées par
        une clé `(date, name, sport)`."""
        from datetime import date
        rows = [
            {"activity_id": 101, "date": "2026-09-20", "sport": "trail", "name": "Trail",
             "grade_class": "-10 à -15 %", "efficiency": 0.80, "mean_pace_s_km": 300.0},
            {"activity_id": 202, "date": "2026-09-20", "sport": "trail", "name": "Trail",
             "grade_class": "-10 à -15 %", "efficiency": 0.95, "mean_pace_s_km": 280.0},
        ]
        trend = M.descent_trend(rows, date(2026, 9, 25))
        self.assertEqual(len(trend["activities"]), 2, trend["activities"])
        ids = {p["activity_id"] for p in trend["activities"]}
        self.assertEqual(ids, {101, 202})

    def test_avg_efficiency_all_classes_is_documented_and_never_the_default_ui_metric(self):
        """Should-fix 2 : le champ blended existe (renommé, sans ambiguïté) mais
        `classes` (le détail par classe) est le résultat qui doit porter
        l'information exploitable — vérifie juste que les deux coexistent,
        `classes` restant peuplé indépendamment de `activities`."""
        from datetime import date
        rows = [
            {"activity_id": 1, "date": "2026-09-20", "sport": "trail", "name": "Trail",
             "grade_class": "-5 à -10 %", "efficiency": 0.9, "mean_pace_s_km": 300.0},
        ]
        trend = M.descent_trend(rows, date(2026, 9, 25))
        self.assertIn("avg_efficiency_all_classes", trend["activities"][0])
        self.assertIn("-5 à -10 %", trend["classes"])


class TestDescentTrendCarriesReferenceSource(unittest.TestCase):
    """Revue de code (post-approbation, should-fix) : `"flat"` et son repli
    `"non_descent"` ne sont PAS sur la même échelle (mesuré : 0,664 en `flat`
    contre 0,548 en `non_descent` pour la MÊME descente) — un point de tendance
    doit porter sa source pour que l'UI puisse les distinguer visuellement,
    jamais les mélanger comme s'ils étaient de même nature."""

    def test_reference_source_is_carried_on_each_class_point(self):
        from datetime import date
        rows = [
            {"activity_id": 1, "date": "2026-09-18", "sport": "trail", "name": "Trail A",
             "reference_source": "flat", "grade_class": "-10 à -15 %", "efficiency": 0.664,
             "mean_pace_s_km": 300.0},
            {"activity_id": 2, "date": "2026-09-20", "sport": "trail", "name": "Trail B",
             "reference_source": "non_descent", "grade_class": "-10 à -15 %", "efficiency": 0.548,
             "mean_pace_s_km": 300.0},
        ]
        trend = M.descent_trend(rows, date(2026, 9, 25))
        points = trend["classes"]["-10 à -15 %"]["points"]
        sources = {p["date"]: p["reference_source"] for p in points}
        self.assertEqual(sources, {"2026-09-18": "flat", "2026-09-20": "non_descent"})

    def test_reference_source_is_none_when_the_row_does_not_carry_it(self):
        """Défense en profondeur pour un ancien appelant qui n'aurait pas encore
        la colonne dans sa requête SQL — jamais une exception."""
        from datetime import date
        rows = [{"activity_id": 1, "date": "2026-09-20", "sport": "trail", "name": "Trail",
                  "grade_class": "-5 à -10 %", "efficiency": 0.9, "mean_pace_s_km": 300.0}]
        trend = M.descent_trend(rows, date(2026, 9, 25))
        self.assertIsNone(trend["classes"]["-5 à -10 %"]["points"][0]["reference_source"])


# ---------------------------------------------------------------------------
# arc_index : table activity_descent_class, CLI, garde-fou
# ---------------------------------------------------------------------------


def _arc_activity(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-descent-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=1800, distance_m=3600, sport="trail"):
        self.write(f"activities/{day}_{sport}.md", _arc_activity(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, "garmin_activity_id": {garmin_id}}}'
        ))

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_fit_descent(self, garmin_id, **kwargs):
        records = _flat_then_descent_samples(**kwargs)
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def activity_row(self, garmin_id):
        return self.conn.execute(
            "SELECT * FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()


class TestActivityDescentClassTable(Workspace):
    GARMIN_ID = 90000000047

    def test_descent_detected_and_stored(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertEqual(act["descent_reference_source"], "flat")
        self.assertIsNotNone(act["descent_reference_gap_pace_s_km"])
        rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(r["efficiency"] is not None for r in rows))
        self.assertTrue(all(r["mean_grade"] is not None for r in rows))

    def test_flat_activity_has_no_descent_class_rows(self):
        self.write_activity(self.GARMIN_ID)
        records = [{"t_s": float(t), "distance_m": t * 2.7, "altitude_m": 0.0,
                    "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0}
                   for t in range(0, 1800, 5)]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{self.GARMIN_ID}.json").write_text(
            json.dumps({"activity_id": self.GARMIN_ID, "records": records}), encoding="utf-8")
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        # Un parcours entièrement plat A une référence (le plat lui-même), mais
        # aucune classe descendante qualifiante.
        self.assertEqual(act["descent_reference_source"], "flat")
        rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])

    def test_pure_descent_activity_has_no_reference_and_no_rows(self):
        """Une activité dont le FIT ne contient QU'une descente (aucun plat,
        aucun hors-forte-descente) n'a ni référence ni ligne de classe."""
        self.write_activity(self.GARMIN_ID)
        records = _linear_descent_samples(duration_s=600, grade=-0.12, speed_ms=3.0)
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{self.GARMIN_ID}.json").write_text(
            json.dumps({"activity_id": self.GARMIN_ID, "records": records}), encoding="utf-8")
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(act["descent_reference_gap_pace_s_km"])
        self.assertIsNone(act["descent_reference_source"])
        rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])

    def test_strength_sport_excluded_even_with_samples(self):
        self.write_activity(self.GARMIN_ID, sport="strength")
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])


class TestActivityDescentReportAndCli(Workspace):
    GARMIN_ID = 90000000147

    def test_unknown_activity_has_an_explicit_reason(self):
        self.index()
        report = I.activity_descent_report(self.conn, 123)
        self.assertEqual(report["classes"], {})
        self.assertIsNotNone(report["reason"])
        self.assertEqual(report["reason_code"], "unknown_activity")

    def test_no_samples_has_an_explicit_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.index()
        report = I.activity_descent_report(self.conn, self.GARMIN_ID)
        self.assertIn("aucun échantillon FIT ingéré", report["reason"])
        self.assertEqual(report["reason_code"], "no_samples")

    def test_success_report_has_classes_and_no_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        report = I.activity_descent_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertTrue(report["classes"])
        self.assertIsNotNone(report["reference_gap_pace_s_km"])
        self.assertEqual(report["reference_source"], "flat")

    def test_cli_descent_activity_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        code = I.main(["descent", "--activity", str(self.GARMIN_ID),
                        "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)

    def test_cli_descent_trend_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        code = I.main(["descent", "--workspace", str(self.ws), "--memory", "--today", "2026-09-25"])
        self.assertEqual(code, 0)

    def test_descent_trend_includes_the_activitys_qualifying_classes(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        from datetime import date
        trend = I.descent_trend(self.conn, date(2026, 9, 25))
        self.assertGreaterEqual(len(trend["activities"]), 1)
        self.assertTrue(trend["classes"])

    def test_descent_trend_carries_reference_source_from_the_activity_row(self):
        """Revue de code (post-approbation, should-fix) : `arc_index.descent_trend`
        doit SÉLECTIONNER `a.descent_reference_source` — sans quoi la tendance ne
        pourrait jamais distinguer un point `"flat"` d'un point `"non_descent"`
        (échelles différentes, voir `arc_descent.ASSUMPTIONS["reference"]`)."""
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        from datetime import date
        trend = I.descent_trend(self.conn, date(2026, 9, 25))
        point = trend["classes"]["-10 à -15 %"]["points"][0]
        self.assertEqual(point["reference_source"], "flat")


class TestComputeMetricsSurvivesAnUnexpectedDescentCrash(Workspace):
    """Même défense en profondeur que #46 (revue de code #46, 3e/4e passe) :
    un bug inattendu dans le calcul de descente ne doit jamais faire échouer
    `index_workspace` pour toutes les activités."""

    GARMIN_ID_BROKEN = 90000000148
    GARMIN_ID_OK = 90000000149

    def test_one_activitys_crash_never_stops_indexing_the_rest(self):
        import contextlib
        import io
        import os
        previous_strict = os.environ.pop("ARC_STRICT_METRICS", None)

        self.write_activity(self.GARMIN_ID_BROKEN, day="2026-09-19")
        self.write_fit_descent(self.GARMIN_ID_BROKEN, descent_duration_s=600, grade=-0.12, speed_ms=3.0)
        self.write_activity(self.GARMIN_ID_OK, day="2026-09-20")
        self.write_fit_descent(self.GARMIN_ID_OK, descent_duration_s=600, grade=-0.12, speed_ms=3.0)

        original = I.DS.descent_speed_by_grade_class
        calls = {"n": 0}

        def _boom(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("bug injecté par le test (#47)")
            return original(*args, **kwargs)

        I.DS.descent_speed_by_grade_class = _boom
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.index()
        finally:
            I.DS.descent_speed_by_grade_class = original
            if previous_strict is None:
                os.environ.pop("ARC_STRICT_METRICS", None)
            else:
                os.environ["ARC_STRICT_METRICS"] = previous_strict

        self.assertIn("bug injecté par le test (#47)", stderr.getvalue())

        broken = self.activity_row(self.GARMIN_ID_BROKEN)
        self.assertIsNone(broken["gap_pace_s_km"])
        self.assertIsNone(broken["best_climb_vam_elapsed_m_h"])
        self.assertIsNone(broken["descent_reference_gap_pace_s_km"])
        self.assertIsNone(broken["descent_reference_source"])
        broken_rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (broken["id"],)).fetchall()
        self.assertEqual(broken_rows, [])

        ok = self.activity_row(self.GARMIN_ID_OK)
        self.assertIsNotNone(ok["descent_reference_gap_pace_s_km"])
        ok_rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (ok["id"],)).fetchall()
        self.assertTrue(ok_rows)

    def test_arc_strict_metrics_env_reraises_instead_of_swallowing(self):
        import os
        self.write_activity(self.GARMIN_ID_BROKEN)
        self.write_fit_descent(self.GARMIN_ID_BROKEN, descent_duration_s=600, grade=-0.12, speed_ms=3.0)

        original = I.DS.descent_speed_by_grade_class

        def _boom(*args, **kwargs):
            raise RuntimeError("bug injecté par le test (#47)")

        previous_strict = os.environ.get("ARC_STRICT_METRICS")
        os.environ["ARC_STRICT_METRICS"] = "1"
        I.DS.descent_speed_by_grade_class = _boom
        try:
            with self.assertRaises(RuntimeError):
                self.index()
        finally:
            I.DS.descent_speed_by_grade_class = original
            if previous_strict is None:
                os.environ.pop("ARC_STRICT_METRICS", None)
            else:
                os.environ["ARC_STRICT_METRICS"] = previous_strict


if __name__ == "__main__":
    unittest.main()
