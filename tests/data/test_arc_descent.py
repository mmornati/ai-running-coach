"""Palier D — Efficacité en descente par classe de pente (#47).

Familles de tests :
- `arc_descent.grade_class_descent`/`DESCENT_GRADE_CLASSES` : bornes, alignement
  avec `arc_climb.GRADE_CLASSES` (#46).
- `arc_descent.descent_speed_by_grade_class` : vitesse/allure synthétique à
  vérité connue, indicateur d'efficacité = 1,0 quand l'athlète court exactement
  à la vitesse prédite par le modèle, seuil minimal par classe (durée OU
  distance), échantillons à l'arrêt exclus, trou de signal jamais comblé.
- `arc_descent.descent_report` : restriction à la famille course à pied,
  raisons explicites, robustesse au bruit sur un plat.
- `arc_index` : table `activity_descent_class` recalculée à l'indexation, CLI
  `descent --activity`/`descent --weeks`, garde-fou de `compute_metrics`.
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


def _series_at_constant_grade(*, grade, speed_ms, duration_s, gap_speed_ms, resolution_s=5.0, t0=0.0):
    """Série DÉJÀ augmentée (comme `arc_gap.gap_sample_series` le ferait), à
    pente et vitesse CONSTANTES — vérité connue, sans dépendre de la fenêtre de
    calcul de pente réelle (`arc_elevation.grade_series`), testée séparément."""
    n = int(duration_s // resolution_s) + 1
    return [{"t_s": t0 + i * resolution_s, "speed_ms": speed_ms, "grade": grade, "gap_speed_ms": gap_speed_ms}
            for i in range(n)]


def _linear_descent_samples(*, duration_s, grade, speed_ms, resolution_s=5, alt0=1000.0):
    """Échantillons FIT bruts (t_s/distance_m/altitude_m/speed_ms) d'une descente
    linéaire à pente et vitesse constantes — pour les tests de bout en bout
    (`descent_report`, `arc_index`), qui passent par le vrai calcul de pente
    fenêtrée (`arc_elevation.grade_series`)."""
    n = duration_s // resolution_s + 1
    out = []
    dist = 0.0
    alt = alt0
    for i in range(n):
        out.append({"t_s": float(i * resolution_s), "distance_m": round(dist, 2), "altitude_m": round(alt, 2),
                     "speed_ms": speed_ms, "hr_bpm": 140.0, "cadence_spm": 165.0})
        dist += speed_ms * resolution_s
        alt += grade * speed_ms * resolution_s
    return out


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
        self.assertEqual(DS.grade_class_descent(-0.25), "< -20 %")

    def test_classes_mirror_arc_climb_grade_classes(self):
        """#46 (`arc_climb.ASSUMPTIONS["grade_classes"]`) anticipait explicitement
        cette réutilisation : les bornes doivent rester identiques, seul le
        signe et le libellé changent (voir `ASSUMPTIONS["grade_classes"]`)."""
        import arc_climb as VC
        ascending = [(lo, hi) for lo, hi, _ in VC.GRADE_CLASSES[1:]]
        descending = [(lo, hi) for lo, hi, _ in DS.DESCENT_GRADE_CLASSES]
        self.assertEqual(ascending, descending)


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

    def test_efficiency_is_exactly_one_when_matching_the_models_prediction(self):
        """Critère d'acceptation de #47 : indicateur = 1,0 quand l'athlète court
        exactement à la vitesse prédite par le modèle relativement à la
        référence plate — ici la référence EST la vitesse GAP imposée, donc le
        ratio doit être exactement 1,0 (aux arrondis près)."""
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
        samples = _linear_descent_samples(duration_s=600, grade=-0.10, speed_ms=3.0)
        report = DS.descent_report(samples, "indoor_cycling")
        self.assertEqual(report["classes"], {})
        self.assertIn("course à pied", report["reason"])

    def test_hiking_is_included_in_the_run_family(self):
        samples = _linear_descent_samples(duration_s=600, grade=-0.10, speed_ms=1.5)
        report = DS.descent_report(samples, "hiking")
        self.assertIsNone(report["reason"])

    def test_no_samples_has_an_explicit_reason(self):
        report = DS.descent_report([], "trail")
        self.assertIn("aucun échantillon FIT", report["reason"])

    def test_downhill_run_produces_a_qualifying_class_with_a_reference(self):
        samples = _linear_descent_samples(duration_s=600, grade=-0.12, speed_ms=3.0)
        report = DS.descent_report(samples, "trail")
        self.assertIsNone(report["reason"])
        self.assertTrue(report["classes"])
        self.assertIsNotNone(report["reference_gap_pace_s_km"])
        for cls, v in report["classes"].items():
            self.assertIsNotNone(v["efficiency"], cls)

    def test_flat_noise_produces_no_qualifying_class_but_an_explicit_reason(self):
        """Robustesse au bruit (comme `arc_climb`/#46) : un jitter d'altitude de
        quelques dizaines de centimètres sur un parcours plat ne doit jamais
        produire de fausse classe de pente descendante."""
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
        self.assertIsNotNone(report["reason"])


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
        records = _linear_descent_samples(**kwargs)
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
        self.write_fit_descent(self.GARMIN_ID, duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(r["efficiency"] is not None for r in rows))

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
        rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])

    def test_strength_sport_excluded_even_with_samples(self):
        self.write_activity(self.GARMIN_ID, sport="strength")
        self.write_fit_descent(self.GARMIN_ID, duration_s=600, grade=-0.12, speed_ms=3.0)
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

    def test_no_samples_has_an_explicit_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.index()
        report = I.activity_descent_report(self.conn, self.GARMIN_ID)
        self.assertIn("aucun échantillon FIT ingéré", report["reason"])

    def test_success_report_has_classes_and_no_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        report = I.activity_descent_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertTrue(report["classes"])
        self.assertIsNotNone(report["reference_gap_pace_s_km"])

    def test_cli_descent_activity_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        code = I.main(["descent", "--activity", str(self.GARMIN_ID),
                        "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)

    def test_cli_descent_trend_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        code = I.main(["descent", "--workspace", str(self.ws), "--memory", "--today", "2026-09-25"])
        self.assertEqual(code, 0)

    def test_descent_trend_includes_the_activitys_qualifying_classes(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_descent(self.GARMIN_ID, duration_s=600, grade=-0.12, speed_ms=3.0)
        self.index()
        from datetime import date
        trend = I.descent_trend(self.conn, date(2026, 9, 25))
        self.assertGreaterEqual(len(trend["points"]), 1)
        self.assertTrue(trend["classes"])


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
        self.write_fit_descent(self.GARMIN_ID_BROKEN, duration_s=600, grade=-0.12, speed_ms=3.0)
        self.write_activity(self.GARMIN_ID_OK, day="2026-09-20")
        self.write_fit_descent(self.GARMIN_ID_OK, duration_s=600, grade=-0.12, speed_ms=3.0)

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
        broken_rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (broken["id"],)).fetchall()
        self.assertEqual(broken_rows, [])

        ok = self.activity_row(self.GARMIN_ID_OK)
        ok_rows = self.conn.execute(
            "SELECT * FROM activity_descent_class WHERE activity_id = ?", (ok["id"],)).fetchall()
        self.assertTrue(ok_rows)

    def test_arc_strict_metrics_env_reraises_instead_of_swallowing(self):
        import os
        self.write_activity(self.GARMIN_ID_BROKEN)
        self.write_fit_descent(self.GARMIN_ID_BROKEN, duration_s=600, grade=-0.12, speed_ms=3.0)

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
