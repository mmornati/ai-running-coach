"""Palier D — allure ajustée à la pente, GAP (#44).

Familles de tests :
- `arc_elevation.grade_series`/`smooth_moving_average` : pente sur fenêtre de
  distance (jamais une différence brute entre deux échantillons de 5 s), trous
  de signal jamais traversés, robustesse à un bruit d'altitude injecté.
- `arc_gap.minetti_cost`/`gap_speed_ms` : valeurs de référence du modèle de
  Minetti et al. 2002 (calculées à la main dans les docstrings ci-dessous),
  clampage hors de ±45 %, identité sur le plat.
- Séances SYNTHÉTIQUES construites à partir du modèle de Minetti lui-même
  (PAS `tests.lib.synthetic.sample_session`, dont le `default_slope_factor`
  n'est volontairement PAS Minetti — voir `tests/README.md`) : le GAP doit
  recouvrer la vitesse « plat équivalent » imposée à la génération.
- `arc_gap.split_gap_paces`/`split_boundaries` : mapping des échantillons aux
  splits par distance cumulée.
- `arc_index` : `activity.gap_pace_s_km`/`activity_split.gap_pace_s_km`
  recalculés à l'indexation, restreints à la famille course à pied, CLI
  `gap --activity`.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_elevation as E  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_index as I  # noqa: E402


# ---------------------------------------------------------------------------
# arc_elevation : lissage et pente
# ---------------------------------------------------------------------------


class TestSmoothMovingAverage(unittest.TestCase):
    def test_ignores_none_in_window(self):
        out = E.smooth_moving_average([1.0, None, 3.0], taps=3)
        self.assertAlmostEqual(out[0], 1.0)   # fenêtre [1.0, None] au bord -> None ignoré
        self.assertAlmostEqual(out[1], 2.0)   # fenêtre [1.0, None, 3.0] -> (1+3)/2
        self.assertAlmostEqual(out[2], 3.0)   # fenêtre [None, 3.0] au bord -> None ignoré

    def test_all_none_window_stays_none(self):
        out = E.smooth_moving_average([None, None], taps=3)
        self.assertEqual(out, [None, None])

    def test_taps_one_is_identity(self):
        values = [1.0, 2.0, None, 4.0]
        self.assertEqual(E.smooth_moving_average(values, taps=1), values)


class TestGradeSeries(unittest.TestCase):
    def _flat(self, n=60, dt=5, speed=2.7):
        return [{"t_s": t * dt, "distance_m": t * dt * speed, "altitude_m": 0.0,
                  "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0} for t in range(n)]

    def test_flat_grade_is_zero(self):
        series = E.grade_series(self._flat())
        interior = [s["grade"] for s in series[3:-3]]
        self.assertTrue(all(g is not None for g in interior))
        for g in interior:
            self.assertAlmostEqual(g, 0.0, places=9)

    def test_constant_uphill_grade_recovered(self):
        # 10 % de pente constante : altitude = distance * 0.10.
        samples = [{"t_s": t * 5, "distance_m": t * 5 * 2.0, "altitude_m": t * 5 * 2.0 * 0.10,
                    "hr_bpm": 150.0, "speed_ms": 2.0, "cadence_spm": 170.0} for t in range(60)]
        series = E.grade_series(samples)
        interior = [s["grade"] for s in series[5:-5]]
        self.assertTrue(all(g is not None for g in interior))
        for g in interior:
            self.assertAlmostEqual(g, 0.10, places=6)

    def test_short_segment_is_none(self):
        # 3 points sur 10 m au total : jamais assez pour `min_window_m` (20 m défaut).
        samples = [{"t_s": t, "distance_m": t * 5.0, "altitude_m": 0.0, "hr_bpm": None,
                    "speed_ms": None, "cadence_spm": None} for t in range(3)]
        series = E.grade_series(samples)
        self.assertTrue(all(s["grade"] is None for s in series))

    def test_gap_never_bridged(self):
        """Une pause de 60 s (>> max_gap_s=30 s) sépare un plat et un plateau à +20 m :
        la pente ne doit jamais être calculée à travers ce saut d'altitude."""
        before = [{"t_s": t * 5, "distance_m": t * 5 * 2.7, "altitude_m": 0.0,
                    "hr_bpm": 150.0, "speed_ms": 2.7, "cadence_spm": 170.0} for t in range(60)]
        after_t0 = before[-1]["t_s"] + 65  # > 30 s de trou
        after = [{"t_s": after_t0 + t * 5, "distance_m": before[-1]["distance_m"] + t * 5 * 2.7,
                  "altitude_m": 20.0, "hr_bpm": 150.0, "speed_ms": 2.7, "cadence_spm": 170.0}
                 for t in range(60)]
        series = E.grade_series(before + after, max_gap_s=30.0)
        # Le premier échantillon après le trou (et ses voisins immédiats, dans le
        # même segment que le plateau, désormais plat à +20 m) doit rester à
        # pente nulle, jamais une pente géante calculée contre le point d'AVANT
        # le trou.
        first_after = next(s for s in series if s["t_s"] == after_t0)
        idx = series.index(first_after)
        for s in series[idx:idx + 5]:
            self.assertIsNotNone(s["grade"])
            self.assertAlmostEqual(s["grade"], 0.0, places=6)

    def test_zero_or_negative_distance_delta_is_handled(self):
        """Distance qui stagne puis recule légèrement (bruit GPS/capteur figé) :
        jamais d'exception, jamais une pente infinie."""
        samples = [
            {"t_s": 0, "distance_m": 0.0, "altitude_m": 0.0, "hr_bpm": None, "speed_ms": None, "cadence_spm": None},
            {"t_s": 5, "distance_m": 10.0, "altitude_m": 1.0, "hr_bpm": None, "speed_ms": None, "cadence_spm": None},
            {"t_s": 10, "distance_m": 10.0, "altitude_m": 1.0, "hr_bpm": None, "speed_ms": None, "cadence_spm": None},
            {"t_s": 15, "distance_m": 9.5, "altitude_m": 1.0, "hr_bpm": None, "speed_ms": None, "cadence_spm": None},
            {"t_s": 20, "distance_m": 40.0, "altitude_m": 2.0, "hr_bpm": None, "speed_ms": None, "cadence_spm": None},
        ]
        series = E.grade_series(samples)  # ne doit lever aucune exception
        self.assertEqual(len(series), 5)


# ---------------------------------------------------------------------------
# arc_gap : coût de Minetti, GAP par échantillon
# ---------------------------------------------------------------------------


class TestMinettiCost(unittest.TestCase):
    def test_flat_cost_is_3_6(self):
        """C(0) = 155.4*0 - 30.4*0 - 43.3*0 + 46.3*0 + 19.5*0 + 3.6 = 3.6 (le
        terme constant du polynôme, littéralement)."""
        self.assertEqual(G.minetti_cost(0.0), 3.6)

    def test_uphill_10_percent_matches_hand_computation(self):
        """C(0.10), calculé à la main (i=0.1, i²=0.01, i³=0.001, i⁴=0.0001, i⁵=0.00001) :
        155.4×0.00001 − 30.4×0.0001 − 43.3×0.001 + 46.3×0.01 + 19.5×0.1 + 3.6
        = 0.001554 − 0.00304 − 0.0433 + 0.463 + 1.95 + 3.6 = 5.968214 J/kg/m."""
        self.assertAlmostEqual(G.minetti_cost(0.10), 5.968214, places=6)

    def test_downhill_10_percent_matches_hand_computation(self):
        """C(-0.10) : mêmes puissances qu'au-dessus, signe alterné sur les impairs :
        −0.001554 − 0.00304 + 0.0433 + 0.463 − 1.95 + 3.6 = 2.151706 J/kg/m —
        moins cher que le plat, comme attendu pour une pente négative modérée."""
        self.assertAlmostEqual(G.minetti_cost(-0.10), 2.151706, places=6)
        self.assertLess(G.minetti_cost(-0.10), G.minetti_cost(0.0))

    def test_clamped_beyond_valid_range(self):
        """Au-delà de ±45 %, la pente est clampée : C(0.9) == C(0.45), jamais une
        extrapolation du polynôme (qui diverge violemment au-delà)."""
        self.assertEqual(G.minetti_cost(0.9), G.minetti_cost(0.45))
        self.assertEqual(G.minetti_cost(-0.9), G.minetti_cost(-0.45))

    def test_none_grade_is_none_cost(self):
        self.assertIsNone(G.minetti_cost(None))


class TestGapSpeed(unittest.TestCase):
    def test_flat_identity(self):
        self.assertAlmostEqual(G.gap_speed_ms(2.7, 0.0), 2.7, places=9)

    def test_uphill_slower_equivalent_speed_is_higher(self):
        # Sur une montée, le coût est plus élevé -> vitesse GAP > vitesse mesurée
        # (la même vitesse mesurée en montée "vaudrait" plus vite sur du plat).
        self.assertGreater(G.gap_speed_ms(2.0, 0.10), 2.0)

    def test_moderate_downhill_lower_equivalent_speed(self):
        self.assertLess(G.gap_speed_ms(2.0, -0.10), 2.0)

    def test_none_inputs(self):
        self.assertIsNone(G.gap_speed_ms(None, 0.0))
        self.assertIsNone(G.gap_speed_ms(2.0, None))


# ---------------------------------------------------------------------------
# Séances synthétiques dérivées DIRECTEMENT du modèle de Minetti (pas
# `tests.lib.synthetic.sample_session`, voir tests/README.md et la docstring
# du module) : le GAP doit recouvrer la vitesse « plat équivalent » imposée.
# ---------------------------------------------------------------------------


def _minetti_samples(grade: float, flat_equivalent_speed_ms: float, *, n=90, dt=5):
    """Échantillons synthétiques : vitesse mesurée = vitesse « plat équivalent »
    imposée / (C(pente)/C(0)) — l'inverse exact de `gap_speed_ms`, pour que le
    GAP recalculé retrouve `flat_equivalent_speed_ms`."""
    cost_ratio = G.minetti_cost(grade) / G.minetti_cost(0.0)
    measured_speed = flat_equivalent_speed_ms / cost_ratio
    samples = []
    dist = 0.0
    alt = 0.0
    for t in range(n):
        samples.append({"t_s": t * dt, "distance_m": dist, "altitude_m": alt,
                         "hr_bpm": 150.0, "speed_ms": measured_speed, "cadence_spm": 170.0})
        dist += measured_speed * dt
        alt += measured_speed * dt * grade
    return samples


class TestActivityGapRecoversFlatEquivalent(unittest.TestCase):
    FLAT_EQUIV_SPEED = 2.8  # m/s -> allure plat équivalente imposée

    def test_flat(self):
        samples = _minetti_samples(0.0, self.FLAT_EQUIV_SPEED)
        pace = G.activity_gap_pace_s_km(samples)
        self.assertAlmostEqual(pace, 1000.0 / self.FLAT_EQUIV_SPEED, delta=1.0)

    def test_15_percent_uphill(self):
        samples = _minetti_samples(0.15, self.FLAT_EQUIV_SPEED)
        pace = G.activity_gap_pace_s_km(samples)
        expected = 1000.0 / self.FLAT_EQUIV_SPEED
        self.assertAlmostEqual(pace, expected, delta=expected * 0.02)  # ±2 % (effets de bord de fenêtre)

    def test_15_percent_downhill(self):
        samples = _minetti_samples(-0.15, self.FLAT_EQUIV_SPEED)
        pace = G.activity_gap_pace_s_km(samples)
        expected = 1000.0 / self.FLAT_EQUIV_SPEED
        self.assertAlmostEqual(pace, expected, delta=expected * 0.02)


class TestNoiseRobustness(unittest.TestCase):
    """Critère d'acceptation #44 : sur un plat, un bruit d'altitude injecté
    (±1 m, capteur barométrique) ne doit pas faire dévier le GAP AGRÉGÉ de
    l'allure réelle au-delà d'une tolérance raisonnable — voir
    `arc_elevation.ASSUMPTIONS["noise_robustness"]` pour pourquoi l'agrégat
    (et non l'échantillon isolé) est le bon niveau de test."""

    def test_flat_with_altitude_jitter_stays_close_to_actual_pace(self):
        rng = random.Random(20260925)
        speed = 2.7
        samples = [{"t_s": t * 5, "distance_m": t * 5 * speed, "altitude_m": rng.uniform(-1.0, 1.0),
                    "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0} for t in range(360)]
        gap_pace = G.activity_gap_pace_s_km(samples)
        actual_pace = 1000.0 / speed
        self.assertAlmostEqual(gap_pace, actual_pace, delta=actual_pace * 0.03)  # ±3 %


class TestStoppedSamplesExcludedFromActivityGap(unittest.TestCase):
    """Revue #89 : un plat avec un arrêt de 5 minutes (feu rouge, ravitaillement)
    ne doit JAMAIS gonfler l'allure GAP de la séance entière — celle-ci doit
    rester comparable à l'allure sur temps de MOUVEMENT (comme `moving_duration_s`
    ailleurs dans le tableau de bord), jamais à l'allure sur temps total."""

    def _flat_with_stop(self, speed=2.7, moving_n=240, stopped_n=60):
        samples = [{"t_s": t * 5, "distance_m": t * 5 * speed, "altitude_m": 0.0,
                    "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0} for t in range(moving_n)]
        stop_t0 = samples[-1]["t_s"] + 5
        stop_distance = samples[-1]["distance_m"]
        samples += [{"t_s": stop_t0 + t * 5, "distance_m": stop_distance, "altitude_m": 0.0,
                     "hr_bpm": 90.0, "speed_ms": 0.0, "cadence_spm": 0.0} for t in range(stopped_n)]
        resume_t0 = samples[-1]["t_s"] + 5
        samples += [{"t_s": resume_t0 + t * 5, "distance_m": stop_distance + t * 5 * speed, "altitude_m": 0.0,
                     "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0} for t in range(moving_n)]
        return samples

    def test_activity_gap_ignores_the_stop(self):
        speed = 2.7
        samples = self._flat_with_stop(speed=speed)
        gap_pace = G.activity_gap_pace_s_km(samples)
        moving_pace = 1000.0 / speed
        self.assertAlmostEqual(gap_pace, moving_pace, delta=moving_pace * 0.02)

    def test_including_stopped_samples_would_have_inflated_the_pace(self):
        """Contre-preuve : SANS l'exclusion (`exclude_stopped=False`), la même
        séance rend une allure GAP nettement plus lente — la régression que ce
        correctif ferme (feu rouge = allure GAP artificiellement dégradée)."""
        speed = 2.7
        samples = self._flat_with_stop(speed=speed)
        series = G.gap_sample_series(samples)
        excluded = G.activity_gap_pace_from_series(series, exclude_stopped=True)
        included = G.activity_gap_pace_from_series(series, exclude_stopped=False)
        self.assertGreater(included, excluded)


class TestSplitDistanceDrift(unittest.TestCase):
    """Revue #89 : la distance totale déclarée par les splits (Markdown) peut
    différer de la distance réellement mesurée par la montre (FIT) — le dernier
    split ne doit jamais perdre les derniers échantillons de la séance pour
    autant."""

    def test_last_split_absorbs_the_extra_distance(self):
        samples = _minetti_samples(0.0, 2.8, n=250)  # ~1400 m réellement parcourus
        splits = [{"km": 1, "distance_m": 1000.0}]     # ne déclare que 1000 m
        paces = G.split_gap_paces(samples, splits)
        # Sans l'extension de la borne, les échantillons au-delà de 1000 m
        # seraient perdus (hors de toute plage) et le split resterait calculé
        # sur une fraction seulement de la séance réellement parcourue.
        bounds = G.split_boundaries(splits, actual_total_m=samples[-1]["distance_m"])
        self.assertEqual(bounds[-1]["end_m"], samples[-1]["distance_m"])
        self.assertIsNotNone(paces[1])

    def test_boundaries_unchanged_when_declared_distance_is_larger(self):
        bounds = G.split_boundaries([{"km": 1, "distance_m": 1000.0}], actual_total_m=800.0)
        self.assertEqual(bounds[-1]["end_m"], 1000.0)  # jamais réduite, seulement étendue


# ---------------------------------------------------------------------------
# Splits : bornes de distance cumulée et GAP par split
# ---------------------------------------------------------------------------


class TestSplitBoundaries(unittest.TestCase):
    def test_cumulative_from_distance_m(self):
        bounds = G.split_boundaries([{"km": 1, "distance_m": 1000.0}, {"km": 2, "distance_m": 950.0}])
        self.assertEqual(bounds, [
            {"km": 1, "start_m": 0.0, "end_m": 1000.0},
            {"km": 2, "start_m": 1000.0, "end_m": 1950.0},
        ])

    def test_missing_distance_defaults_to_1000(self):
        bounds = G.split_boundaries([{"km": 1, "distance_m": None}, {"km": 2, "distance_m": 500.0}])
        self.assertEqual(bounds[0]["end_m"], 1000.0)
        self.assertEqual(bounds[1]["start_m"], 1000.0)
        self.assertEqual(bounds[1]["end_m"], 1500.0)

    def test_sorted_by_km_regardless_of_input_order(self):
        bounds = G.split_boundaries([{"km": 2, "distance_m": 1000.0}, {"km": 1, "distance_m": 1000.0}])
        self.assertEqual([b["km"] for b in bounds], [1, 2])


class TestSplitGapPaces(unittest.TestCase):
    def test_two_splits_flat_then_uphill(self):
        flat = _minetti_samples(0.0, 2.8, n=100)
        # Split 1 (0-1000 m, ~ km 1) est plat ; split 2 (1000 m et au-delà) grimpe à 15 %.
        uphill = _minetti_samples(0.15, 2.8, n=100)
        offset_dist = flat[-1]["distance_m"] + flat[-1]["speed_ms"] * 5
        offset_t = flat[-1]["t_s"] + 5
        for i, s in enumerate(uphill):
            s["t_s"] += offset_t
            s["distance_m"] += offset_dist
            s["altitude_m"] += flat[-1]["altitude_m"]
        samples = flat + uphill
        splits = [{"km": 1, "distance_m": 1000.0}, {"km": 2, "distance_m": samples[-1]["distance_m"] - 1000.0}]
        paces = G.split_gap_paces(samples, splits)
        self.assertIn(1, paces)
        self.assertIn(2, paces)
        self.assertAlmostEqual(paces[1], 1000.0 / 2.8, delta=5.0)
        self.assertAlmostEqual(paces[2], 1000.0 / 2.8, delta=5.0)

    def test_empty_inputs(self):
        self.assertEqual(G.split_gap_paces([], []), {})
        self.assertEqual(G.split_gap_paces([{"t_s": 0}], []), {})

    def test_split_without_any_sample_in_range_is_none(self):
        samples = _minetti_samples(0.0, 2.7, n=20)  # séance courte, ne couvre qu'un seul split
        splits = [{"km": 1, "distance_m": 1000.0}, {"km": 2, "distance_m": 1000.0}]
        paces = G.split_gap_paces(samples, splits)
        self.assertIsNone(paces.get(2))


# ---------------------------------------------------------------------------
# arc_index : intégration (colonnes stockées, restriction famille course à
# pied, CLI `gap --activity`).
# ---------------------------------------------------------------------------


def _arc_activity(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-gap-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=1800, distance_m=4860,
                        sport="trail", splits=None):
        extra = ""
        if splits is not None:
            cols = ["km", "distance_m", "duration_s"]
            rows = [[s.get(c) for c in cols] for s in splits]
            extra = f', "splits_cols": {json.dumps(cols)}, "splits": {json.dumps(rows)}'
        self.write(f"activities/{day}_{sport}.md", _arc_activity(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, '
            f'"garmin_activity_id": {garmin_id}{extra}}}'
        ))

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_fit(self, garmin_id, n=360, speed=2.7):
        records = [{"t_s": t * 5, "distance_m": t * 5 * speed, "altitude_m": 0.0, "hr_bpm": 150.0,
                    "speed_ms": speed, "cadence_spm": 170.0} for t in range(n)]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def write_fit_no_altitude(self, garmin_id, n=360, speed=2.7):
        """Séance avec échantillons FIT ingérés mais SANS altitude exploitable
        (tapis de course, capteur barométrique absent) : la pente reste `None`
        partout, donc le GAP aussi — un cas distinct de « aucun échantillon »."""
        records = [{"t_s": t * 5, "distance_m": t * 5 * speed, "altitude_m": None, "hr_bpm": 150.0,
                    "speed_ms": speed, "cadence_spm": 170.0} for t in range(n)]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def activity_row(self, garmin_id):
        return self.conn.execute(
            "SELECT * FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()


class TestActivityGapPaceColumn(Workspace):
    GARMIN_ID = 90000000042

    def test_run_family_with_samples_gets_gap_pace(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(row["gap_pace_s_km"])
        self.assertAlmostEqual(row["gap_pace_s_km"], 1000.0 / 2.7, delta=1.0)

    def test_no_samples_means_no_gap_pace(self):
        self.write_activity(self.GARMIN_ID)
        self.index()
        self.assertIsNone(self.activity_row(self.GARMIN_ID)["gap_pace_s_km"])

    def test_strength_sport_excluded_even_with_samples(self):
        self.write_activity(self.GARMIN_ID, sport="strength")
        self.write_fit(self.GARMIN_ID)
        self.index()
        self.assertIsNone(self.activity_row(self.GARMIN_ID)["gap_pace_s_km"])

    def test_splits_get_their_own_gap_pace(self):
        splits = [{"km": 1, "distance_m": 1000.0, "duration_s": 370},
                  {"km": 2, "distance_m": 500.0, "duration_s": 185}]
        self.write_activity(self.GARMIN_ID, distance_m=1500, splits=splits)
        self.write_fit(self.GARMIN_ID, n=280)
        self.index()
        activity_id = self.activity_row(self.GARMIN_ID)["id"]
        rows = {r["km"]: r["gap_pace_s_km"] for r in self.conn.execute(
            "SELECT km, gap_pace_s_km FROM activity_split WHERE activity_id = ?", (activity_id,))}
        self.assertEqual(set(rows), {1, 2})
        self.assertIsNotNone(rows[1])
        self.assertIsNotNone(rows[2])


class TestActivityGapReportAndCli(Workspace):
    GARMIN_ID = 90000000043

    def test_unknown_activity_has_explicit_reason(self):
        self.index()
        report = I.activity_gap_report(self.conn, 123)
        self.assertIsNone(report["gap_pace_s_km"])
        self.assertIsNotNone(report["reason"])

    def test_non_run_family_has_explicit_reason(self):
        self.write_activity(self.GARMIN_ID, sport="indoor_cycling")
        self.write_fit(self.GARMIN_ID)
        self.index()
        report = I.activity_gap_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["gap_pace_s_km"])
        self.assertIn("course à pied", report["reason"])

    def test_no_samples_has_explicit_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.index()
        report = I.activity_gap_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["gap_pace_s_km"])
        self.assertIn("aucun échantillon FIT ingéré", report["reason"])

    def test_samples_without_usable_altitude_has_a_distinct_reason(self):
        """Revue #89 : « des échantillons existent mais aucune pente n'est
        calculable » (tapis de course, capteur baro absent) doit être
        distinguable de « aucun échantillon du tout » — deux causes très
        différentes à corriger côté athlète, même symptôme (aucun chiffre)."""
        self.write_activity(self.GARMIN_ID)
        self.write_fit_no_altitude(self.GARMIN_ID)
        self.index()
        report = I.activity_gap_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["gap_pace_s_km"])
        self.assertIn("échantillons FIT ingérés", report["reason"])
        self.assertNotIn("aucun échantillon FIT ingéré", report["reason"])

    def test_success_report_has_no_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID)
        self.index()
        report = I.activity_gap_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertIsNotNone(report["gap_pace_s_km"])

    def test_cli_gap_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID)
        self.index()
        code = I.main(["gap", "--activity", str(self.GARMIN_ID),
                        "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
