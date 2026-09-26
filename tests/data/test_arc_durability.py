"""Palier D — durabilité sur les sorties longues (#48, épopée #21).

Familles de tests :
- `arc_durability.durability_report` sur des séances à vérité connue :
  - `tests.lib.synthetic.sample_session(fade_pct=...)` (fade imposé sur le
    dernier tiers de la séance ENTIÈRE, jamais post-échauffement — voir
    `tests/README.md` sur la comparaison « comme avec comme ») ; les sessions
    de ces tests durent assez longtemps (100 min) et le fade démarre à
    `2 * duration_s / 3`, alors que `arc_durability` exclut d'abord les 10
    premières minutes d'échauffement puis découpe le RESTE en trois tiers —
    les deux frontières ne coïncident pas exactement, mais avec une séance
    plate et sans bruit (`noise=False`), le dernier tiers RÉELLEMENT utilisé
    par `arc_durability` tombe entièrement dans la zone déjà faded du
    générateur (`t >= 2 * duration_s / 3`) pour une durée assez longue — voir
    le calcul dans `_check_boundaries_fit` ci-dessous — si bien que
    `gap_fade_pct` mesuré retombe sur `fade_pct` demandé, à l'arrondi près.
  - une séance FLATE artisanale (vitesse constante par palier) pour vérifier
    l'exclusion de l'échauffement de façon indépendante du générateur
    aléatoire (même motif que `TestWarmupExclusion` dans
    `test_arc_decoupling.py`, #45).
- Éligibilité : famille hors course à pied, durée insuffisante, aucun
  échantillon, portion/FC insuffisante sur le premier ou le dernier tiers, FC
  incomplète, pente trop asymétrique entre le premier et le dernier tiers,
  pente forte/marche exclues du calcul MAIS jamais de la séance entière.
- `arc_index` : colonnes `activity.durability_*` recalculées à l'indexation,
  CLI `durability`, tendance sur les sorties longues, garde/nettoyage en cas
  d'échec inattendu d'un calcul dérivé (même discipline que #46/#47).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_durability as DU  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_index as I  # noqa: E402
from tests.lib.synthetic import sample_session  # noqa: E402


LONG_DURATION_S = 6000  # 100 min > arc_metrics.LONG_RUN_MIN_DURATION_S (90 min)


def _report_from_records(records, sport="trail"):
    return DU.durability_report(records, sport)


class TestImposedFadeMatchesSyntheticGenerator(unittest.TestCase):
    """Critère d'acceptation de l'issue #48 : fade imposé de 8 % -> mesuré 8 ± 0,5."""

    def test_imposed_8_pct_fade_on_flat_course(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        report = _report_from_records(records)
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["gap_fade_pct"], 8.0, delta=0.5)
        # FC constante (pas de dérive imposée) sur un parcours plat -> le fade EF
        # doit retomber sur le même chiffre que le fade GAP (EF = GAP / FC, FC
        # identique aux deux tiers comparés).
        self.assertAlmostEqual(report["ef_fade_pct"], report["gap_fade_pct"], delta=0.1)

    def test_flat_identity_no_fade_is_near_zero(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=0.0, noise=False)
        report = _report_from_records(records)
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["gap_fade_pct"], 0.0, delta=0.5)
        self.assertAlmostEqual(report["ef_fade_pct"], 0.0, delta=0.5)

    def test_hr_by_third_is_reported(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        report = _report_from_records(records)
        self.assertIsNotNone(report["hr_first_third_bpm"])
        self.assertIsNotNone(report["hr_middle_third_bpm"])
        self.assertIsNotNone(report["hr_last_third_bpm"])


class TestWarmupExclusion(unittest.TestCase):
    def _flat_session_with_slow_warmup(self, duration_s=LONG_DURATION_S, warmup_s=600, warmup_speed=1.0,
                                        steady_speed=2.78, fade_pct=8.0):
        """Séance plate, artisanale : vitesse anormalement basse pendant
        `warmup_s` (jambes pas encore lancées), puis vitesse stable, puis
        fade imposé À PARTIR de `2/3 * duration_s` (frontière volontairement
        alignée sur le fade du dernier tiers RÉELLEMENT utilisé par
        `arc_durability`, voir le docstring du module)."""
        fade_start = 2 * duration_s / 3.0
        records = []
        for t in range(duration_s):
            if t < warmup_s:
                speed = warmup_speed
            elif t < fade_start:
                speed = steady_speed
            else:
                speed = steady_speed * (1 - fade_pct / 100.0)
            records.append({"t_s": float(t), "distance_m": t * speed, "altitude_m": 0.0,
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
        return records

    def test_excluding_warmup_changes_the_measured_value(self):
        records = self._flat_session_with_slow_warmup()
        with_warmup_excluded = DU.durability_report(records, "trail")["gap_fade_pct"]

        original_warmup = DU.WARMUP_S
        try:
            DU.WARMUP_S = 0.0
            without_exclusion = DU.durability_report(records, "trail")["gap_fade_pct"]
        finally:
            DU.WARMUP_S = original_warmup

        self.assertIsNotNone(with_warmup_excluded)
        self.assertIsNotNone(without_exclusion)
        self.assertNotAlmostEqual(with_warmup_excluded, without_exclusion, delta=0.01)
        self.assertLess(abs(with_warmup_excluded - 8.0), abs(without_exclusion - 8.0))
        self.assertAlmostEqual(with_warmup_excluded, 8.0, delta=0.5)


class TestStoppedSamplesExcluded(unittest.TestCase):
    def test_pause_does_not_distort_the_measurement(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        records = [dict(r) for r in records]
        # Pause de deux minutes vers le tiers du milieu (n'affecte donc ni le
        # premier ni le dernier tiers directement, mais déplace le temps de
        # mouvement cumulé qui sert à situer les frontières).
        mid = len(records) // 2
        for r in records[mid:mid + 120]:
            r["speed_ms"] = 0.0
        report = DU.durability_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["gap_fade_pct"], 8.0, delta=0.5)


class TestHrCoverage(unittest.TestCase):
    def test_hr_dropout_in_last_third_is_ineligible_with_explicit_reason(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=0.0, noise=False)
        records = [dict(r) for r in records]
        # Post-échauffement (600 s), le dernier tiers occupe environ
        # [4200, 6000) — un décrochage de 8 minutes dépasse largement les 20 %
        # de couverture manquante tolérés (MIN_HR_COVERAGE_FRAC = 0.8).
        for r in records:
            if 4300 <= r["t_s"] < 4300 + 480:
                r["hr_bpm"] = None
        report = DU.durability_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIsNone(report["gap_fade_pct"])
        self.assertIn("FC incomplète", report["reason"])
        self.assertEqual(report["reason_code"], "hr_incomplete")

    def test_full_hr_coverage_is_eligible(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=0.0, noise=False)
        report = DU.durability_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])


class TestGradeAsymmetry(unittest.TestCase):
    def _climb_first_flat_last_records(self, duration_s=LONG_DURATION_S, climb_grade=0.10, speed=2.2):
        """Grosse montée dans le premier tiers (post-échauffement), plat dans
        le dernier — critère d'acceptation de #48 : « asymétrique (grosse
        montée dans le premier tiers) -> raison »."""
        records = []
        distance = altitude = 0.0
        for t in range(duration_s):
            grade = climb_grade if 600 <= t < 2400 else 0.0
            distance += speed
            altitude += speed * grade
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
        return records

    def test_big_climb_confined_to_first_third_is_ineligible(self):
        records = self._climb_first_flat_last_records()
        report = DU.durability_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIsNone(report["gap_fade_pct"])
        self.assertEqual(report["reason_code"], "grade_asymmetry")

    def _two_grade_thirds_records(self, duration_s=LONG_DURATION_S, grade1=0.0145, grade3=-0.0145,
                                   target_gap=2.7, hr=150.0):
        """Pente moyenne `grade1` dans le premier tiers post-échauffement,
        `grade3` dans le dernier, effort adapté à la pente (GAP constant,
        comme `test_arc_decoupling._two_grade_halves_records`) pour isoler la
        frontière d'asymétrie sans confondre avec un vrai fade."""
        records = []
        distance = altitude = 0.0
        for t in range(duration_s):
            if t < 2400:
                grade = grade1
            elif t >= 4200:
                grade = grade3
            else:
                grade = 0.0
            cost = G.minetti_cost(grade)
            speed = target_gap * G.MINETTI_FLAT_COST / cost
            distance += speed
            altitude += speed * grade
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                             "hr_bpm": hr, "speed_ms": speed, "cadence_spm": 170.0})
        return records

    def test_just_under_asymmetry_threshold_is_eligible(self):
        records = self._two_grade_thirds_records(grade1=0.0145, grade3=-0.0145)  # écart = 2,9 pts
        report = DU.durability_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])

    def test_just_over_asymmetry_threshold_is_ineligible(self):
        records = self._two_grade_thirds_records(grade1=0.0155, grade3=-0.0155)  # écart = 3,1 pts
        report = DU.durability_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertEqual(report["reason_code"], "grade_asymmetry")


class TestSteepAndWalkingExcludedWithoutRejecting(unittest.TestCase):
    def test_steep_excursions_in_both_thirds_do_not_reject_the_session(self):
        """Deux brèves montées à 16 % (au-delà du seuil de 12 %), l'une dans le
        premier tiers, l'autre dans le dernier — exclues du calcul du fade
        (`arc_durability.ASSUMPTIONS['steep_grade_and_walking']`) mais NE
        DOIVENT PAS rejeter la séance entière : critère d'acceptation de #48."""
        records, _truth = sample_session(
            seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False,
            segments=((2000, 300, 16), (13000, 300, 16)))
        report = DU.durability_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["gap_fade_pct"], 8.0, delta=1.0)

    def test_walking_section_excluded_without_rejecting(self):
        """Une section marchée (cadence sous `arc_decoupling.WALKING_CADENCE_SPM`)
        au milieu du premier tiers reste exclue du calcul mais laisse assez de
        course exploitable pour rester éligible."""
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        records = [dict(r) for r in records]
        for r in records:
            if 1200 <= r["t_s"] < 1500:
                r["cadence_spm"] = 100.0
                r["speed_ms"] = 1.2
        report = DU.durability_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])


class TestEligibility(unittest.TestCase):
    def test_too_short_is_ineligible(self):
        records, _truth = sample_session(duration_s=3600, fade_pct=8.0, noise=False)
        report = DU.durability_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("durée de mouvement insuffisante", report["reason"])
        self.assertEqual(report["reason_code"], "too_short")

    def test_non_run_family_is_ineligible_and_not_applicable(self):
        records, _truth = sample_session(duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        report = DU.durability_report(records, "strength")
        self.assertFalse(report["eligible"])
        self.assertEqual(report["reason_code"], "not_run_family")
        self.assertFalse(report["applicable"])

    def test_no_samples_is_ineligible(self):
        report = DU.durability_report([], "trail")
        self.assertFalse(report["eligible"])
        self.assertEqual(report["reason_code"], "no_samples")
        self.assertTrue(report["applicable"])

    def test_unknown_sport_treated_as_not_run_family(self):
        records, _truth = sample_session(duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        report = DU.durability_report(records, None)
        self.assertFalse(report["applicable"])


# ---------------------------------------------------------------------------
# `arc_index` : colonnes, CLI, tendance, garde
# ---------------------------------------------------------------------------


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-durability-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=LONG_DURATION_S, distance_m=16000,
                        sport="trail", name="Sortie longue"):
        self.write(f"activities/{day}_{sport}_{garmin_id}.md", (
            "# Sortie\n\n```arc\n" + json.dumps({
                "arc": 1, "kind": "activity", "date": day, "sport": sport, "name": name,
                "duration_s": duration_s, "distance_m": distance_m, "garmin_activity_id": garmin_id,
            }) + "\n```\n"))

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_fit_records(self, garmin_id, records):
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def activity_row(self, garmin_id):
        return self.conn.execute(
            "SELECT * FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()


class TestActivityDurabilityColumns(Workspace):
    GARMIN_ID = 90000000148

    def test_eligible_long_run_gets_durability_columns(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=LONG_DURATION_S)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(row["durability_gap_fade_pct"])
        self.assertAlmostEqual(row["durability_gap_fade_pct"], 8.0, delta=0.5)
        self.assertIsNotNone(row["durability_ef_fade_pct"])
        self.assertIsNotNone(row["durability_hr_first_third_bpm"])
        self.assertIsNotNone(row["durability_hr_middle_third_bpm"])
        self.assertIsNotNone(row["durability_hr_last_third_bpm"])
        self.assertIsNone(row["durability_reason"])
        self.assertIsNone(row["durability_reason_code"])

    def test_too_short_run_has_no_durability_but_an_explicit_reason(self):
        records, _truth = sample_session(duration_s=3600, fade_pct=8.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=3600)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(row["durability_gap_fade_pct"])
        self.assertIn("durée de mouvement insuffisante", row["durability_reason"])
        self.assertEqual(row["durability_reason_code"], "too_short")

    def test_strength_sport_excluded_even_with_samples(self):
        records, _truth = sample_session(duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=LONG_DURATION_S, sport="strength")
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(row["durability_gap_fade_pct"])


class TestActivityDurabilityReportAndCli(Workspace):
    GARMIN_ID = 90000000149

    def test_unknown_activity_has_explicit_reason(self):
        self.index()
        report = I.activity_durability_report(self.conn, 123)
        self.assertIsNone(report["gap_fade_pct"])
        self.assertIsNotNone(report["reason"])
        self.assertEqual(report["reason_code"], "unknown_activity")

    def test_success_report_has_no_reason(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=LONG_DURATION_S)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        report = I.activity_durability_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertIsNotNone(report["gap_fade_pct"])

    def test_cli_durability_command_activity(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=LONG_DURATION_S)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["durability", "--activity", str(self.GARMIN_ID),
                            "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["garmin_activity_id"], self.GARMIN_ID)

    def test_cli_durability_command_trend(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["durability", "--workspace", str(self.ws), "--memory", "--weeks", "12"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["window_weeks"], 12)


class TestDurabilityTrend(Workspace):
    def test_long_runs_appear_in_trend_with_measured_average(self):
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_activity(90000000150, day="2026-09-13", duration_s=LONG_DURATION_S)
        self.write_fit_records(90000000150, records)
        self.index()
        trend = I.durability_trend(self.conn, __import__("datetime").date(2026, 9, 25))
        self.assertEqual(trend["long_runs"], 1)
        self.assertEqual(trend["measured_n"], 1)
        self.assertAlmostEqual(trend["avg_gap_fade_pct"], 8.0, delta=0.5)
        self.assertEqual(trend["points"][0]["sport"], "trail")

    def test_short_runs_are_excluded_from_trend(self):
        records, _truth = sample_session(duration_s=3600, fade_pct=8.0, noise=False)
        self.write_activity(90000000151, day="2026-09-13", duration_s=3600)
        self.write_fit_records(90000000151, records)
        self.index()
        trend = I.durability_trend(self.conn, __import__("datetime").date(2026, 9, 25))
        self.assertEqual(trend["long_runs"], 0)


class TestComputeMetricsSurvivesAnUnexpectedDurabilityCrash(Workspace):
    """Même défense en profondeur que #46/#47 (revue de code) : un bug
    inattendu dans le calcul de durabilité ne doit jamais faire échouer
    `index_workspace` pour toutes les activités, et doit nettoyer toute trace
    partielle de l'activité en échec."""

    GARMIN_ID_BROKEN = 90000000152
    GARMIN_ID_OK = 90000000153

    def test_one_activitys_crash_never_stops_indexing_the_rest(self):
        previous_strict = os.environ.pop("ARC_STRICT_METRICS", None)

        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_activity(self.GARMIN_ID_BROKEN, day="2026-09-19", duration_s=LONG_DURATION_S)
        self.write_fit_records(self.GARMIN_ID_BROKEN, records)
        self.write_activity(self.GARMIN_ID_OK, day="2026-09-20", duration_s=LONG_DURATION_S)
        self.write_fit_records(self.GARMIN_ID_OK, records)

        original = I.DU.durability_report_from_series
        calls = {"n": 0}

        def _boom(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("bug injecté par le test (#48)")
            return original(*args, **kwargs)

        I.DU.durability_report_from_series = _boom
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.index()
        finally:
            I.DU.durability_report_from_series = original
            if previous_strict is None:
                os.environ.pop("ARC_STRICT_METRICS", None)
            else:
                os.environ["ARC_STRICT_METRICS"] = previous_strict

        self.assertIn("bug injecté par le test (#48)", stderr.getvalue())

        broken = self.activity_row(self.GARMIN_ID_BROKEN)
        self.assertIsNone(broken["durability_gap_fade_pct"])
        self.assertIsNone(broken["durability_ef_fade_pct"])
        self.assertIsNone(broken["durability_hr_first_third_bpm"])
        self.assertIsNone(broken["durability_hr_middle_third_bpm"])
        self.assertIsNone(broken["durability_hr_last_third_bpm"])
        self.assertIsNone(broken["durability_reason_code"])
        # Défense en profondeur partagée avec GAP/découplage/VAM/descente : la
        # ligne entière de champs dérivés est remise à NULL, pas seulement les
        # colonnes de durabilité.
        self.assertIsNone(broken["gap_pace_s_km"])
        self.assertIsNone(broken["decoupling_pct"])

        ok = self.activity_row(self.GARMIN_ID_OK)
        self.assertIsNotNone(ok["durability_gap_fade_pct"])

    def test_arc_strict_metrics_env_reraises_instead_of_swallowing(self):
        self.write_activity(self.GARMIN_ID_BROKEN, duration_s=LONG_DURATION_S)
        records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
        self.write_fit_records(self.GARMIN_ID_BROKEN, records)

        original = I.DU.durability_report_from_series

        def _boom(*args, **kwargs):
            raise RuntimeError("bug injecté par le test (#48)")

        previous_strict = os.environ.get("ARC_STRICT_METRICS")
        os.environ["ARC_STRICT_METRICS"] = "1"
        I.DU.durability_report_from_series = _boom
        try:
            with self.assertRaises(RuntimeError):
                self.index()
        finally:
            I.DU.durability_report_from_series = original
            if previous_strict is None:
                os.environ.pop("ARC_STRICT_METRICS", None)
            else:
                os.environ["ARC_STRICT_METRICS"] = previous_strict


if __name__ == "__main__":
    unittest.main()
