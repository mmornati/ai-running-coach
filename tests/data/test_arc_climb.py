"""Palier D — VAM sur les montées détectées (#46).

Familles de tests :
- `arc_climb.detect_climbs` : montée synthétique à vérité connue (300 m en
  30 min -> 600 m/h, critère d'acceptation de l'issue), robustesse au bruit sur
  un parcours plat (aucune fausse montée), fusion de deux montées séparées par
  un petit creux, trou de signal jamais franchi, arrêt au milieu d'une montée
  (VAM temps écoulé vs temps de mouvement), classes de pente.
- `arc_climb.best_vam_windows` : meilleure VAM sur des fenêtres de 10/20 min.
- `arc_climb.climb_report` : restriction à la famille course à pied, raisons
  explicites.
- `arc_index` : table `activity_climb`, colonnes `activity.best_vam_*`
  recalculées à l'indexation, CLI `vam --activity`/`vam --weeks`.
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

import arc_climb as VC  # noqa: E402
import arc_index as I  # noqa: E402


def _linear_climb_samples(*, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                           resolution_s=5, speed_ms=None, hr_bpm=150.0):
    """Montée synthétique parfaitement linéaire (altitude et distance
    proportionnelles au temps) — vérité connue : gain/durée = VAM imposée."""
    n = duration_s // resolution_s + 1
    speed = speed_ms if speed_ms is not None else distance_m / duration_s
    out = []
    for i in range(n):
        t = i * resolution_s
        frac = min(1.0, t / duration_s)
        out.append({
            "t_s": float(t),
            "distance_m": distance_m * frac,
            "altitude_m": gain_m * frac,
            "speed_ms": speed,
            "hr_bpm": hr_bpm,
            "cadence_spm": 160.0,
        })
    return out


class TestSyntheticClimbKnownVam(unittest.TestCase):
    """Critère d'acceptation de #46 : montée synthétique de 300 m en 30 min -> 600 m/h."""

    def test_300m_in_30min_gives_600_m_per_hour(self):
        samples = _linear_climb_samples(duration_s=1800, gain_m=300.0, distance_m=3600.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1)
        c = climbs[0]
        # Tolérance : le lissage d'altitude (3 points) rogne légèrement les deux
        # bords d'une rampe parfaitement linéaire (voir arc_climb.ASSUMPTIONS
        # ["detection"]) — quelques m/h d'écart, jamais plusieurs dizaines.
        self.assertAlmostEqual(c["vam_elapsed_m_h"], 600.0, delta=5.0)
        self.assertAlmostEqual(c["gain_m"], 300.0, delta=2.0)
        self.assertAlmostEqual(c["avg_grade"], 300.0 / 3600.0, delta=0.002)
        self.assertEqual(c["grade_class"], "5-10%")

    def test_report_matches_detect_climbs(self):
        samples = _linear_climb_samples()
        report = VC.climb_report(samples, "trail")
        self.assertIsNone(report["reason"])
        self.assertEqual(len(report["climbs"]), 1)
        self.assertAlmostEqual(report["best_climb_vam_elapsed_m_h"], 600.0, delta=5.0)


class TestNoiseRobustnessOnFlat(unittest.TestCase):
    def test_small_jitter_on_flat_creates_no_climb(self):
        """Bruit d'altitude de ±1 m sur un parcours plat : aucune fausse montée
        (le seuil de détection, 50 m de gain net, est très au-dessus du bruit)."""
        import random
        rng = random.Random(7)
        n = 400
        samples = []
        for i in range(n):
            t = i * 5
            samples.append({
                "t_s": float(t), "distance_m": t * 2.7,
                "altitude_m": rng.uniform(-1.0, 1.0),
                "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0,
            })
        climbs = VC.detect_climbs(samples)
        self.assertEqual(climbs, [])


class TestMergeAcrossSmallDip(unittest.TestCase):
    def test_two_climbs_separated_by_small_dip_are_merged(self):
        """Deux montées de 60 m chacune, séparées par un creux de 5 m sur 50 m
        (sous MERGE_MAX_DIP_LOSS_M/MERGE_MAX_DIP_DIST_M) : fusionnées en UNE
        seule montée de gain net ~115 m (60 - 5 + 60)."""
        samples = []
        t = 0
        alt = 0.0
        dist = 0.0

        def emit():
            samples.append({"t_s": float(t), "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})

        emit()
        # montée 1 : +60 m sur 600 m (10 %)
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        # creux : -5 m sur 50 m
        for _ in range(10):
            t += 5
            dist += 5.0
            alt -= 0.5
            emit()
        # montée 2 : +60 m sur 600 m
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        self.assertAlmostEqual(climbs[0]["gain_m"], 115.0, delta=3.0)

    def test_dip_too_big_keeps_climbs_separate(self):
        """Même profil, mais un creux de 20 m (au-dessus de
        MERGE_MAX_DIP_LOSS_M=10) : deux montées DISTINCTES."""
        samples = []
        t = 0
        alt = 0.0
        dist = 0.0

        def emit():
            samples.append({"t_s": float(t), "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})

        emit()
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        for _ in range(40):
            t += 5
            dist += 5.0
            alt -= 0.5
            emit()
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 2, climbs)


class TestSignalGapNeverBridged(unittest.TestCase):
    def test_climb_split_by_a_signal_gap_is_two_climbs(self):
        """Un trou de signal (> arc_climb.MAX_GAP_S) au milieu d'une montée continue
        ne doit JAMAIS être comblé : deux montées détectées séparément, jamais
        recollées en une seule, même si le profil d'altitude semble continu."""
        samples = []
        t = 0.0
        alt = 0.0
        dist = 0.0
        for _ in range(120):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 1.0  # 10 % sur 1200 m -> 120 m de D+
        # trou de signal : 5 minutes sans échantillon (> MAX_GAP_S = 30 s)
        t += 300
        for _ in range(120):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 1.0
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 2, climbs)
        # Aucune des deux montées ne doit avoir une durée qui inclut le trou : la
        # somme des deux durées écoulées reste nettement sous la durée totale
        # écoulée (qui, elle, inclut les 300 s de trou).
        total_elapsed = samples[-1]["t_s"] - samples[0]["t_s"]
        self.assertLess(sum(c["duration_elapsed_s"] for c in climbs), total_elapsed - 250.0)


class TestStopInsideClimb(unittest.TestCase):
    def test_long_stop_lowers_elapsed_vam_but_not_moving_vam(self):
        """Un arrêt de 10 minutes au milieu d'une montée fait chuter la VAM
        « temps écoulé » sans changer la VAM « temps de mouvement » — voir
        `arc_climb.ASSUMPTIONS["vam_basis"]`."""
        samples = []
        t = 0.0
        alt = 0.0
        dist = 0.0
        # première moitié de la montée : +150 m sur 15 min
        for _ in range(180):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 0.833333
        # arrêt de 10 minutes (vitesse nulle, altitude/distance figées)
        for _ in range(120):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 0.0, "hr_bpm": 100.0, "cadence_spm": 0.0})
            t += 5
        # seconde moitié : encore +150 m sur 15 min
        for _ in range(180):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 0.833333
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        c = climbs[0]
        # Temps écoulé total ~40 min (30 min de montée + 10 min d'arrêt) -> VAM
        # écoulée basse ; temps de mouvement ~30 min -> VAM de mouvement haute.
        self.assertLess(c["vam_elapsed_m_h"], c["vam_moving_m_h"])
        self.assertAlmostEqual(c["vam_moving_m_h"], 600.0, delta=15.0)
        self.assertAlmostEqual(c["vam_elapsed_m_h"], 450.0, delta=15.0)


class TestGradeClasses(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(VC.grade_class(0.03), "<5%")
        self.assertEqual(VC.grade_class(0.05), "5-10%")
        self.assertEqual(VC.grade_class(0.09), "5-10%")
        self.assertEqual(VC.grade_class(0.10), "10-15%")
        self.assertEqual(VC.grade_class(0.17), "15-20%")
        self.assertEqual(VC.grade_class(0.25), ">20%")
        self.assertIsNone(VC.grade_class(None))

    def test_vam_by_grade_class_groups_and_averages(self):
        climbs = [
            {"grade_class": "5-10%", "vam_elapsed_m_h": 500.0},
            {"grade_class": "5-10%", "vam_elapsed_m_h": 600.0},
            {"grade_class": ">20%", "vam_elapsed_m_h": 300.0},
            {"grade_class": None, "vam_elapsed_m_h": None},
        ]
        by_class = VC.vam_by_grade_class(climbs)
        self.assertEqual(by_class["5-10%"], {"count": 2, "avg_vam_elapsed_m_h": 550.0})
        self.assertEqual(by_class[">20%"], {"count": 1, "avg_vam_elapsed_m_h": 300.0})
        self.assertNotIn(None, by_class)


class TestBestVamWindows(unittest.TestCase):
    def test_best_10_and_20_min_windows(self):
        samples = _linear_climb_samples(duration_s=1800, gain_m=300.0, distance_m=3600.0)
        climbs = VC.detect_climbs(samples)
        windows = VC.best_vam_windows(samples, climbs)
        # Rampe linéaire : la meilleure fenêtre de 10 ou 20 min donne (à peu près)
        # la même VAM que la montée entière (600 m/h), jamais plus.
        self.assertAlmostEqual(windows["vam_best_10min_m_h"], 600.0, delta=10.0)
        self.assertAlmostEqual(windows["vam_best_20min_m_h"], 600.0, delta=10.0)
        self.assertLessEqual(windows["vam_best_10min_m_h"], 620.0)

    def test_climb_shorter_than_window_gives_none(self):
        samples = _linear_climb_samples(duration_s=300, gain_m=60.0, distance_m=500.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1)
        windows = VC.best_vam_windows(samples, climbs)
        self.assertIsNone(windows["vam_best_10min_m_h"])
        self.assertIsNone(windows["vam_best_20min_m_h"])


class TestClimbReportSportRestriction(unittest.TestCase):
    def test_non_run_family_has_explicit_reason(self):
        samples = _linear_climb_samples()
        report = VC.climb_report(samples, "indoor_cycling")
        self.assertEqual(report["climbs"], [])
        self.assertIn("course à pied", report["reason"])

    def test_hiking_is_included_in_run_family(self):
        samples = _linear_climb_samples()
        report = VC.climb_report(samples, "hiking")
        self.assertIsNone(report["reason"])
        self.assertEqual(len(report["climbs"]), 1)

    def test_no_samples_has_explicit_reason(self):
        report = VC.climb_report([], "trail")
        self.assertEqual(report["climbs"], [])
        self.assertIn("aucun échantillon", report["reason"])

    def test_flat_run_has_no_climbs_but_no_error(self):
        samples = [{"t_s": float(t), "distance_m": t * 2.7, "altitude_m": 0.0,
                    "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0}
                   for t in range(0, 3600, 5)]
        report = VC.climb_report(samples, "running")
        self.assertIsNone(report["reason"])
        self.assertEqual(report["climbs"], [])
        self.assertIsNone(report["best_climb_vam_elapsed_m_h"])


# ---------------------------------------------------------------------------
# arc_index : table activity_climb, colonnes best_vam_*, CLI
# ---------------------------------------------------------------------------


def _arc_activity(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-climb-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=1800, distance_m=3600,
                        sport="trail"):
        self.write(f"activities/{day}_{sport}.md", _arc_activity(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, '
            f'"garmin_activity_id": {garmin_id}}}'
        ))

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_fit_climb(self, garmin_id, **kwargs):
        records = _linear_climb_samples(**kwargs)
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def activity_row(self, garmin_id):
        return self.conn.execute(
            "SELECT * FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()


class TestActivityClimbTable(Workspace):
    GARMIN_ID = 90000000046

    def test_climb_detected_and_stored(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID, duration_s=1800, gain_m=300.0, distance_m=3600.0)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(act["best_climb_vam_elapsed_m_h"])
        self.assertAlmostEqual(act["best_climb_vam_elapsed_m_h"], 600.0, delta=5.0)
        self.assertIsNotNone(act["best_vam_10min_m_h"])
        rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["idx"], 1)

    def test_flat_activity_has_no_climb_rows(self):
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
        self.assertIsNone(act["best_climb_vam_elapsed_m_h"])
        rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])

    def test_strength_sport_excluded_even_with_samples(self):
        self.write_activity(self.GARMIN_ID, sport="strength")
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(act["best_climb_vam_elapsed_m_h"])


class TestActivityClimbReportAndCli(Workspace):
    GARMIN_ID = 90000000047

    def test_unknown_activity_has_explicit_reason(self):
        self.index()
        report = I.activity_climb_report(self.conn, 123)
        self.assertEqual(report["climbs"], [])
        self.assertIsNotNone(report["reason"])

    def test_non_run_family_has_explicit_reason(self):
        self.write_activity(self.GARMIN_ID, sport="indoor_cycling")
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        report = I.activity_climb_report(self.conn, self.GARMIN_ID)
        self.assertIn("course à pied", report["reason"])

    def test_no_samples_has_explicit_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.index()
        report = I.activity_climb_report(self.conn, self.GARMIN_ID)
        self.assertIn("aucun échantillon FIT ingéré", report["reason"])

    def test_success_report_has_climb_and_no_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        report = I.activity_climb_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertEqual(len(report["climbs"]), 1)
        self.assertIn("5-10%", report["vam_by_grade_class"])

    def test_cli_vam_activity_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        code = I.main(["vam", "--activity", str(self.GARMIN_ID),
                        "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)

    def test_cli_vam_trend_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        code = I.main(["vam", "--workspace", str(self.ws), "--memory", "--today", "2026-09-25"])
        self.assertEqual(code, 0)

    def test_vam_trend_includes_activity_without_duration_threshold(self):
        """Contrairement à `decoupling_trend`, `vam_trend` n'exige AUCUNE durée
        minimale : une sortie courte de 30 min avec une montée détectée doit
        apparaître dans la tendance."""
        self.write_activity(self.GARMIN_ID, duration_s=1800)
        self.write_fit_climb(self.GARMIN_ID, duration_s=1800, gain_m=300.0, distance_m=3600.0)
        self.index()
        from datetime import date
        trend = I.vam_trend(self.conn, date(2026, 9, 25))
        self.assertEqual(trend["activities_n"], 1)
        self.assertEqual(trend["with_climb_n"], 1)
        self.assertIsNotNone(trend["avg_best_climb_vam_elapsed_m_h"])


if __name__ == "__main__":
    unittest.main()
