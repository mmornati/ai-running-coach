"""Palier D — débrief post-course : plan vs réalisé, par segment (#61, épopée #23).

Fixture minimale : un plan à 4 segments d'1 km (allure planifiée constante
300 s/km, scénario réaliste) et une activité à splits kilométriques — même
granularité que les segments, pour que les bornes de segment coïncident
EXACTEMENT avec des points de split réels (`resolution: "high"`, voir
`ASSUMPTIONS["resolution"]`).

Une seconde fixture, reprise TELLE QUELLE du repro de revue de code (#61,
premier tour de relecture) — un vrai plan `scripts/arc_race_pacing.py plan`
sur un GPX synthétique de 10,29 km, segmentation par défaut (750 m), 2
ravitos — sert de non-régression sur les trois BLOQUANTS de cette relecture :
dernier split partiel, arrêts ravito planifiés, et segments plus courts que
la granularité des splits.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_race_debrief as D  # noqa: E402
import arc_samples as SA  # noqa: E402


def _plan(*, aid_stations=None):
    """4 segments d'1 km, allure planifiée constante 300 s/km (scénario réaliste)
    — même granularité que les splits de l'activité fixture, pour que le
    « premier tiers » (#61, `FAST_START_FRACTION`) recouvre au moins un
    segment entier, et que chaque borne de segment coïncide avec un split réel
    (`resolution: "high"`)."""
    segments = []
    for i in range(4):
        segments.append({
            "id": f"s0{i + 1}", "km_start": float(i), "km_end": float(i + 1), "distance_m": 1000.0,
            "predicted_time_s": {"safe": 330, "realistic": 300, "ambitious": 275},
            "pace_s_km": {"safe": 330, "realistic": 300, "ambitious": 275},
        })
    plan = {
        "arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "Trail Fictif",
        "race_date": "2026-09-27",
        "segments": segments,
    }
    if aid_stations is not None:
        plan["aid_stations"] = aid_stations
        plan["scenarios"] = {"realistic": 1200 + sum(a.get("stop_s", 90.0) for a in aid_stations)}
    return plan


def _activity(splits, *, carbs_g=None, duration_s=None, distance_m=None, date="2026-09-27"):
    has_explicit_distance = any(len(s) > 2 for s in splits)
    total_distance = distance_m
    if total_distance is None:
        total_distance = sum(s[2] if len(s) > 2 else 1000.0 for s in splits)
    data = {
        "arc": 1, "kind": "activity", "date": date, "sport": "trail",
        "duration_s": duration_s if duration_s is not None else sum(s[1] for s in splits),
        "distance_m": total_distance,
    }
    if has_explicit_distance:
        data["splits_cols"] = ["km", "duration_s", "distance_m"]
        data["splits"] = [[sp[0], sp[1], (sp[2] if len(sp) > 2 else 1000.0)] for sp in splits]
    else:
        data["splits_cols"] = ["km", "duration_s"]
        data["splits"] = [[k, d] for k, d, *_ in splits]
    if carbs_g is not None:
        data["carbs_g"] = carbs_g
    return data


class TestBuildActualCheckpoints(unittest.TestCase):
    def test_on_plan_checkpoints(self):
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        checkpoints = D.build_actual_checkpoints(activity)
        self.assertEqual(checkpoints[0], (0.0, 0.0))
        self.assertEqual(checkpoints[-1], (4000.0, 1200.0))

    def test_missing_duration_raises(self):
        activity = {"splits_cols": ["km", "duration_s"], "splits": [[1, None]]}
        with self.assertRaises(D.DebriefError):
            D.build_actual_checkpoints(activity)

    def test_no_splits_raises(self):
        with self.assertRaises(D.DebriefError):
            D.build_actual_checkpoints({"splits_cols": [], "splits": []})

    def test_last_partial_split_inferred_from_activity_distance(self):
        """#61, revue de code, BLOQUANT 1 : sans distance_m explicite sur le
        dernier split, la distance doit être DÉDUITE de activity.distance_m −
        1000·(n−1), jamais un 1000 m par défaut qui fausserait tout l'alignement."""
        activity = {
            "distance_m": 10288, "splits_cols": ["km", "duration_s"],
            "splits": [[i + 1, 330] for i in range(10)] + [[11, 95]],
        }
        checkpoints = D.build_actual_checkpoints(activity)
        self.assertAlmostEqual(checkpoints[-1][0], 10288.0, places=1)
        # Le dernier segment doit faire 288 m (10288 - 10*1000), pas 1000 m.
        self.assertAlmostEqual(checkpoints[-1][0] - checkpoints[-2][0], 288.0, places=1)

    def test_last_partial_split_matches_explicit_distance(self):
        """Même activité, mais avec distance_m explicite sur chaque split —
        doit donner EXACTEMENT le même résultat que l'inférence ci-dessus."""
        activity_explicit = {
            "distance_m": 10288, "splits_cols": ["km", "duration_s", "distance_m"],
            "splits": [[i + 1, 330, 1000.0] for i in range(10)] + [[11, 95, 288.5]],
        }
        checkpoints = D.build_actual_checkpoints(activity_explicit)
        self.assertAlmostEqual(checkpoints[-1][0], 10288.5, places=1)

    def test_inconsistent_distance_raises(self):
        """activity.distance_m incohérent avec le nombre de splits (dernier
        split déduit hors plage plausible) : erreur explicite, jamais une
        distance fantaisiste silencieuse."""
        activity = {
            "distance_m": 500, "splits_cols": ["km", "duration_s"],
            "splits": [[1, 300], [2, 300]],
        }
        with self.assertRaises(D.DebriefError):
            D.build_actual_checkpoints(activity)

    def test_missing_activity_distance_warns(self):
        warnings = []
        activity = {"splits_cols": ["km", "duration_s"], "splits": [[1, 300], [2, 150]]}
        D.build_actual_checkpoints(activity, warnings)
        self.assertTrue(any("1000 m supposé" in w for w in warnings))


class TestSegmentResolution(unittest.TestCase):
    def test_boundaries_on_real_checkpoints_are_high_resolution(self):
        checkpoints = [(0.0, 0.0), (1000.0, 300.0), (2000.0, 600.0)]
        seg = {"km_start": 0.0, "km_end": 1.0}
        self.assertEqual(D.segment_resolution(seg, checkpoints), "high")

    def test_short_segment_interpolated_inside_a_wide_interval_is_low(self):
        checkpoints = [(0.0, 0.0), (1000.0, 300.0)]
        seg = {"km_start": 0.3, "km_end": 0.6}  # ni 0.3 ni 0.6 km ne sont des points réels
        self.assertEqual(D.segment_resolution(seg, checkpoints), "low")

    def test_long_segment_spanning_multiple_intervals_is_high_even_if_interpolated(self):
        checkpoints = [(0.0, 0.0), (500.0, 150.0), (1000.0, 300.0), (1500.0, 450.0), (2000.0, 600.0)]
        seg = {"km_start": 0.3, "km_end": 1.9}  # interpolé aux deux bornes, mais >> 2x l'intervalle
        self.assertEqual(D.segment_resolution(seg, checkpoints), "high")


class TestOnPlan(unittest.TestCase):
    """Course courue exactement à l'allure planifiée (600 s/segment) : deltas nuls."""

    def test_zero_delta_and_no_findings_beyond_info(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        self.assertEqual(len(result["segments"]), 4)
        for seg in result["segments"]:
            self.assertEqual(seg["resolution"], "high")
            self.assertAlmostEqual(seg["delta_s"], 0.0, places=1)
            self.assertAlmostEqual(seg["delta_pct"], 0.0, places=1)
        self.assertAlmostEqual(result["totals"]["delta_pct"], 0.0, places=1)
        codes = [f["code"] for f in result["findings"]]
        self.assertIn("ecart_temps_total", codes)
        self.assertNotIn("depart_trop_rapide", codes)
        self.assertEqual(result["suggested_profile_updates"], [])
        self.assertEqual(result["warnings"], [])

    def test_segment_ids_cited(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        ids = [s["id"] for s in result["segments"]]
        self.assertEqual(ids, ["s01", "s02", "s03", "s04"])


class TestAidStationPlannedStops(unittest.TestCase):
    """#61, revue de code, BLOQUANT 2 : `predicted_time_s` (#59) EXCLUT les
    arrêts ravito — un temps de split écoulé (qui, lui, inclut un arrêt réel)
    comparé tel quel au `predicted_time_s` brut fausse tout : ravito assigné à
    aucun segment => faux delta, faux fade, faux `depart_trop_rapide`."""

    def test_planned_stop_added_to_segment_reaching_the_station(self):
        aid_stations = [{"km": 2.0, "name": "Ravito"}]
        plan = _plan(aid_stations=aid_stations)
        # Allure EXACTEMENT planifiée, plus l'arrêt ravito réel de 90 s au km 2.
        activity = _activity([(1, 300), (2, 390), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        seg2 = next(s for s in result["segments"] if s["id"] == "s02")
        self.assertAlmostEqual(seg2["planned_time_s"], 390.0, places=1)
        self.assertAlmostEqual(seg2["delta_s"], 0.0, places=1)
        self.assertAlmostEqual(result["totals"]["delta_pct"], 0.0, places=1)
        codes = [f["code"] for f in result["findings"]]
        self.assertNotIn("depart_trop_rapide", codes)
        self.assertEqual(result["suggested_profile_updates"], [])

    def test_custom_stop_s_is_honoured(self):
        aid_stations = [{"km": 2.0, "name": "Ravito", "stop_s": 45.0}]
        plan = _plan(aid_stations=aid_stations)
        activity = _activity([(1, 300), (2, 345), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        seg2 = next(s for s in result["segments"] if s["id"] == "s02")
        self.assertAlmostEqual(seg2["planned_time_s"], 345.0, places=1)
        self.assertAlmostEqual(seg2["delta_s"], 0.0, places=1)

    def test_two_stations_twelve_km_repro(self):
        """Repro exact de la revue de code : 12x1 km à 300 s/km, arrêts de 90 s
        au km 7 et au km 10 — course parfaitement sur plan une fois les
        arrêts comptés côté plan. Avant le correctif : +209 s de faux delta
        total et un faux `depart_trop_rapide`."""
        segments = []
        for i in range(12):
            segments.append({
                "id": f"s{i + 1:02d}", "km_start": float(i), "km_end": float(i + 1), "distance_m": 1000.0,
                "predicted_time_s": {"realistic": 300}, "pace_s_km": {"realistic": 300},
            })
        plan = {
            "arc": 1, "kind": "race_plan", "date": "2026-01-01", "race_name": "X", "race_date": "2026-01-08",
            "scenarios": {"realistic": 12 * 300 + 2 * 90},
            "aid_stations": [{"km": 7.0, "name": "A1"}, {"km": 10.0, "name": "A2"}],
            "segments": segments,
        }
        durations = [300, 300, 300, 300, 300, 300, 390, 300, 300, 390, 300, 300]
        activity = _activity([(i + 1, d) for i, d in enumerate(durations)], date="2026-01-08")
        result = D.build_race_debrief(plan, activity)
        self.assertAlmostEqual(result["totals"]["delta_s"], 0.0, places=1)
        self.assertEqual(result["findings"], [
            {"code": "ecart_temps_total", "severity": "info",
             "message": "Temps total réalisé +0.0 % vs plan (plus lent que prévu)."}
        ])
        self.assertEqual(result["suggested_profile_updates"], [])
        self.assertAlmostEqual(result["fade"]["vs_plan_pct"], 0.0, places=1)


class TestFastStartFade(unittest.TestCase):
    """Premier segment couru bien plus vite que prévu (240 s/km au lieu de 300),
    second bien plus lentement (400 s/km) : départ trop rapide + fade net."""

    def test_fast_start_finding_fires(self):
        plan = _plan()
        activity = _activity([(1, 220), (2, 220), (3, 420), (4, 420)])
        result = D.build_race_debrief(plan, activity)
        codes = [f["code"] for f in result["findings"]]
        self.assertIn("depart_trop_rapide", codes)
        self.assertTrue(any(u["rationale"] == "depart_trop_rapide" for u in result["suggested_profile_updates"]))
        # Premiers segments nettement plus rapides que le plan, derniers nettement plus lents.
        self.assertLess(result["segments"][0]["delta_pct"], 0)
        self.assertGreater(result["segments"][-1]["delta_pct"], 0)
        self.assertIn("fade", result)
        self.assertGreater(result["fade"]["vs_plan_pct"], 0)

    def test_no_finding_without_fade(self):
        """Un léger écart d'allure sans fade réel ne doit pas déclencher le drapeau."""
        plan = _plan()
        # Allure quasi identique au plan sur les deux segments : pas de fade.
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        codes = [f["code"] for f in result["findings"]]
        self.assertNotIn("depart_trop_rapide", codes)

    def test_fast_start_never_paid_for_does_not_fire(self):
        """#61, revue de code, 3ᵉ tour, BLOQUANT : un départ rapide jamais
        « payé » plus tard (le reste de la course reste sur plan, voire plus
        rapide) n'est pas un problème — même si le fade en résultant paraît
        dégradé. Repro exact de la revue : 12x1 km à 300 s/km, km 1-4 à 282 s
        puis EXACTEMENT sur plan ensuite (total -72 s, jamais de contrepartie)."""
        segments = []
        for i in range(12):
            segments.append({
                "id": f"s{i + 1:02d}", "km_start": float(i), "km_end": float(i + 1), "distance_m": 1000.0,
                "predicted_time_s": {"realistic": 300}, "pace_s_km": {"realistic": 300},
            })
        plan = {"arc": 1, "kind": "race_plan", "date": "2026-01-01", "race_name": "X", "race_date": "2026-01-08",
                "scenarios": {"realistic": 3600}, "segments": segments}
        durations = [282, 282, 282, 282] + [300] * 8
        activity = _activity([(i + 1, d) for i, d in enumerate(durations)], date="2026-01-08")
        result = D.build_race_debrief(plan, activity)
        self.assertAlmostEqual(result["totals"]["delta_s"], -72.0, places=1)
        codes = [f["code"] for f in result["findings"]]
        self.assertNotIn("depart_trop_rapide", codes)
        self.assertEqual(result["suggested_profile_updates"], [])

    def test_low_resolution_segments_excluded_from_finding(self):
        """Des segments SOUS la granularité des splits (750 m contre 1 km),
        même avec un vrai départ rapide, ne doivent PAS alimenter le drapeau
        (#61, revue de code, BLOQUANT 3) — la précision manque."""
        segments = [
            {"id": "s01", "km_start": 0.0, "km_end": 0.5, "distance_m": 500.0,
             "predicted_time_s": {"realistic": 150}, "pace_s_km": {"realistic": 300}},
            {"id": "s02", "km_start": 0.5, "km_end": 1.0, "distance_m": 500.0,
             "predicted_time_s": {"realistic": 150}, "pace_s_km": {"realistic": 300}},
            {"id": "s03", "km_start": 1.0, "km_end": 1.5, "distance_m": 500.0,
             "predicted_time_s": {"realistic": 150}, "pace_s_km": {"realistic": 300}},
            {"id": "s04", "km_start": 1.5, "km_end": 2.0, "distance_m": 500.0,
             "predicted_time_s": {"realistic": 150}, "pace_s_km": {"realistic": 300}},
        ]
        plan = {"arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "X",
                "race_date": "2026-09-27", "segments": segments}
        # Toujours 1 split par km (granularité 1000 m) : chaque segment de
        # 500 m a AU MOINS une borne interpolée dans un intervalle de 1000 m,
        # jamais >= 2x cet intervalle -> "low" partout.
        activity = _activity([(1, 220), (2, 420)])
        result = D.build_race_debrief(plan, activity)
        for seg in result["segments"]:
            self.assertEqual(seg["resolution"], "low")
        codes = [f["code"] for f in result["findings"]]
        self.assertNotIn("depart_trop_rapide", codes)


class TestDistanceMismatch(unittest.TestCase):
    """L'activité mesure 4.2 km pour un plan à 4 km (mésalignement GPS) : les
    splits sont mis à l'échelle proportionnellement, jamais le temps."""

    def test_scaling_applied_and_warned(self):
        plan = _plan()
        activity = _activity([(1, 315, 1050.0), (2, 315, 1050.0), (3, 315, 1050.0), (4, 315, 1050.0)])
        result = D.build_race_debrief(plan, activity)
        self.assertAlmostEqual(result["alignment"]["actual_distance_m"], 4200.0, places=1)
        self.assertAlmostEqual(result["alignment"]["plan_distance_m"], 4000.0, places=1)
        self.assertGreater(result["alignment"]["mismatch_pct"], 3.0)
        self.assertFalse(result["alignment"]["truncated"])
        self.assertTrue(any("échelle" in w for w in result["warnings"]))
        # Le watch a mesuré 1050 m par km réel (5 % de plus que le plan) : une
        # fois les distances cumulées mises à l'échelle sur le total du plan
        # (jamais le temps), le même temps (315 s) se retrouve réparti sur un
        # kilomètre plus court côté plan -> une allure ~5 % plus lente que
        # celle du plan (300 s/km), cohérent avec l'écart de distance mesuré.
        for seg in result["segments"]:
            self.assertAlmostEqual(seg["delta_pct"], 5.0, delta=1.0)

    def test_no_warning_within_tolerance(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        self.assertEqual(result["warnings"], [])

    def test_extreme_mismatch_is_treated_as_truncated_not_scaled(self):
        """Repli #5, should-fix : un écart > 10 % ressemble à un abandon, pas
        à du bruit GPS — jamais mis à l'échelle, segments non atteints marqués."""
        plan = _plan()
        activity = _activity([(1, 300), (2, 300)], distance_m=2000.0)
        result = D.build_race_debrief(plan, activity)
        self.assertTrue(result["alignment"]["truncated"])
        self.assertEqual(result["alignment"]["scale_factor"], 1.0)
        statuses = [s.get("status") for s in result["segments"]]
        self.assertEqual(statuses, [None, None, "not_reached", "not_reached"])
        self.assertNotIn("fade", result)
        self.assertTrue(any("abandon" in w or "tronqué" in w for w in result["warnings"]))


class TestMissingNutritionAndWeather(unittest.TestCase):
    def test_carbs_and_weather_omitted_when_absent(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity)
        self.assertNotIn("carbs", result)
        self.assertNotIn("weather", result)
        self.assertNotIn("aid_station_times", result)

    def test_carbs_from_activity_when_long_enough(self):
        plan = _plan()
        # Durée totale > 90 min (LONG_RUN_MIN_DURATION_S) pour que
        # arc_metrics.carbs_per_hour_g rende une valeur.
        activity = _activity([(1, 1400), (2, 1400), (3, 1400), (4, 1400)], carbs_g=100)
        result = D.build_race_debrief(plan, activity, carbs_target_g_h=70.0)
        self.assertIn("carbs", result)
        self.assertIn("actual_g_h", result["carbs"])
        self.assertEqual(result["carbs"]["planned_g_h"], 70.0)

    def test_carbs_under_target_finding(self):
        plan = _plan()
        activity = _activity([(1, 1400), (2, 1400), (3, 1400), (4, 1400)], carbs_g=40)
        result = D.build_race_debrief(plan, activity, carbs_target_g_h=80.0)
        codes = [f["code"] for f in result["findings"]]
        self.assertIn("glucides_sous_objectif", codes)

    def test_weather_both_present(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        planned = {"arc": 1, "kind": "weather", "date": "2026-09-20", "location": "X",
                   "category": "green", "temp_max_c": 18.0}
        actual = {"arc": 1, "kind": "weather", "date": "2026-09-27", "location": "X",
                  "category": "orange", "temp_max_c": 29.0}
        result = D.build_race_debrief(plan, activity, planned_weather=planned, actual_weather=actual)
        self.assertEqual(result["weather"]["planned"]["temp_max_c"], 18.0)
        self.assertEqual(result["weather"]["actual"]["temp_max_c"], 29.0)


class TestActivityDateVsRaceDate(unittest.TestCase):
    def test_mismatched_dates_warn(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)], date="2026-09-28")
        result = D.build_race_debrief(plan, activity)
        self.assertTrue(any("date de l'activité" in w for w in result["warnings"]))

    def test_matching_dates_no_warning(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)], date="2026-09-27")
        result = D.build_race_debrief(plan, activity)
        self.assertFalse(any("date de l'activité" in w for w in result["warnings"]))


class TestZeroPlannedTime(unittest.TestCase):
    """NIT, revue de code #61 : un `predicted_time_s` à 0 (donnée de plan
    aberrante) ne doit jamais faire planter le calcul (division par zéro dans
    `delta_pct`, ou `TypeError` dans la moyenne pondérée du premier tiers)."""

    def test_zero_predicted_time_does_not_crash(self):
        segments = [
            {"id": "s01", "km_start": 0.0, "km_end": 1.0, "distance_m": 1000.0,
             "predicted_time_s": {"realistic": 0}, "pace_s_km": {"realistic": 0}},
            {"id": "s02", "km_start": 1.0, "km_end": 2.0, "distance_m": 1000.0,
             "predicted_time_s": {"realistic": 300}, "pace_s_km": {"realistic": 300}},
        ]
        plan = {"arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "X",
                "race_date": "2026-09-27", "segments": segments}
        activity = _activity([(1, 250), (2, 300)])
        result = D.build_race_debrief(plan, activity)  # ne doit lever aucune exception
        seg1 = next(s for s in result["segments"] if s["id"] == "s01")
        self.assertNotIn("delta_s", seg1)
        self.assertNotIn("delta_pct", seg1)


class TestNoPlan(unittest.TestCase):
    def test_missing_segments_raises_clear_error(self):
        plan = {"arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "X", "race_date": "2026-09-27"}
        activity = _activity([(1, 300)])
        with self.assertRaises(D.DebriefError) as ctx:
            D.build_race_debrief(plan, activity)
        self.assertIn("segments", str(ctx.exception))

    def test_load_block_missing_file(self):
        with self.assertRaises(D.DebriefError):
            D.load_block(Path("/nonexistent/plan.md"), expected_kind="race_plan")

    def test_load_block_wrong_kind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.md"
            path.write_text('# T\n\n```arc\n{"arc": 1, "kind": "activity", "date": "2026-09-20", '
                             '"sport": "trail", "duration_s": 10}\n```\n', encoding="utf-8")
            with self.assertRaises(D.DebriefError):
                D.load_block(path, expected_kind="race_plan")


class TestAidStationTimes(unittest.TestCase):
    def test_stop_detected_near_station(self):
        plan_aid = [{"km": 2.0, "name": "Ravito"}]
        samples = [
            {"t_s": 0, "distance_m": 0.0, "speed_ms": 3.0},
            {"t_s": 10, "distance_m": 1900.0, "speed_ms": 3.0},
            {"t_s": 20, "distance_m": 2000.0, "speed_ms": 0.1},
            {"t_s": 50, "distance_m": 2000.0, "speed_ms": 0.1},
            {"t_s": 60, "distance_m": 2005.0, "speed_ms": 3.0},
        ]
        result = D.aid_station_times(plan_aid, samples)
        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(result[0]["actual_stop_s"], 20.0)

    def test_no_stop_near_station_omitted(self):
        plan_aid = [{"km": 2.0, "name": "Ravito"}]
        samples = [{"t_s": t, "distance_m": t * 100.0, "speed_ms": 3.0} for t in range(0, 40, 10)]
        result = D.aid_station_times(plan_aid, samples)
        self.assertEqual(result, [])

    def test_fit_key_absent_without_arg(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity, fit_samples=None)
        self.assertNotIn("aid_station_times", result)

    def test_autopause_gap_detected_without_speed_field(self):
        """#61, revue de code, BLOQUANT 4 : une auto-pause Garmin peut ne rien
        enregistrer pendant l'arrêt — la détection doit fonctionner même sans
        `speed_ms` du tout, sur le seul écart distance quasi nulle."""
        plan_aid = [{"km": 1.0, "name": "Ravito"}]
        samples = [
            {"t_s": 0, "distance_m": 0.0},
            {"t_s": 100, "distance_m": 1000.0},
            {"t_s": 130, "distance_m": 1002.0},  # 30 s d'écart, 2 m parcourus -> auto-pause
            {"t_s": 200, "distance_m": 1700.0},
        ]
        result = D.aid_station_times(plan_aid, samples)
        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(result[0]["actual_stop_s"], 30.0)

    def test_autopause_gap_detected_in_realistic_1hz_stream(self):
        """#61, revue de code, BLOQUANT 2 : repro exact de la 2ᵉ revue de code —
        un flux RÉALISTE à 1 Hz (un échantillon par seconde, allure constante
        3,33 m/s), avec un unique écart de 91 s à la distance 3000 m ne
        couvrant que 3,3 m (auto-pause qui n'enregistre RIEN pendant l'arrêt).
        L'ancienne mécanique (ancrage + saut) « absorbait » l'échantillon juste
        AVANT l'écart par bonds de 2 (chaque pas normal, 3,33 m, restait déjà
        sous `STOP_DISTANCE_EPS_M`) et ne testait donc jamais la paire qui
        enjambe réellement l'arrêt — `detect_stops` rendait `[]` malgré un
        arrêt de 91 s bien réel."""
        speed = 1000.0 / 300.0  # 3.33 m/s, un split de 300 s/km
        samples = [{"t_s": t, "distance_m": round(t * speed, 2), "speed_ms": speed} for t in range(900)]
        gap_start_distance = samples[-1]["distance_m"]
        # Écart de 91 s : le prochain échantillon n'arrive qu'à t=990, avec
        # seulement 3,3 m de distance supplémentaire (aucun échantillon
        # intermédiaire — l'auto-pause n'a RIEN enregistré pendant l'arrêt).
        samples.append({"t_s": 990, "distance_m": round(gap_start_distance + 3.3, 2), "speed_ms": speed})
        resume_distance = samples[-1]["distance_m"]
        samples.extend({"t_s": 990 + k, "distance_m": round(resume_distance + k * speed, 2), "speed_ms": speed}
                        for k in range(1, 200))
        stops = D.detect_stops(samples)
        self.assertEqual(len(stops), 1, stops)
        mid_m, start_t, duration = stops[0]
        self.assertAlmostEqual(start_t, 899, delta=1)
        self.assertGreaterEqual(duration, 90.0)

    def test_samples_missing_distance_are_skipped(self):
        """#61, revue de code, BLOQUANT 4 : une distance manquante ne doit
        jamais lever de TypeError, seulement être ignorée."""
        samples = [
            {"t_s": 0, "distance_m": 0.0, "speed_ms": 3.0},
            {"t_s": 5, "distance_m": None, "speed_ms": None},
            {"t_s": 10, "distance_m": 30.0, "speed_ms": 3.0},
        ]
        # Ne doit pas lever d'exception.
        D.detect_stops(samples)


class TestFitSampleAlignment(unittest.TestCase):
    """#61, revue de code, BLOQUANT 3/4 : `--fit` doit aligner directement sur
    les échantillons (résolution fine), pas sur les splits km, et accepter le
    format brut fitparse via `arc_samples.normalise_records`."""

    def test_aid_station_exactly_on_segment_boundary(self):
        """#61, revue de code, 3ᵉ tour, should-fix 4 : un ravito PILE sur une
        borne de segment (8x750 m, ravito au km 3.0 = fin de s04/début de s05)
        avec un arrêt réel dans les échantillons FIT. Avant le correctif,
        `_interpolate_cum_time` rendait la PREMIÈRE valeur trouvée à cette
        distance (avant l'arrêt) pour la requête de fin de s04 ET la même
        valeur pour le début de s05, faisant déborder l'arrêt entier sur s05 :
        s04 -28.6 %, s05 +40 % sur une course par ailleurs parfaite."""
        segments = []
        for i in range(8):
            segments.append({
                "id": f"s{i + 1:02d}", "km_start": round(i * 0.75, 3), "km_end": round((i + 1) * 0.75, 3),
                "distance_m": 750.0, "predicted_time_s": {"realistic": 225}, "pace_s_km": {"realistic": 300},
            })
        plan = {"arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "X", "race_date": "2026-09-27",
                "aid_stations": [{"km": 3.0, "name": "R"}], "segments": segments}
        speed = 750.0 / 225.0  # 300 s/km exactement
        samples = [{"t_s": t, "distance_m": round(t * speed, 3), "speed_ms": speed} for t in range(900)]
        # Arrêt réel de 90 s pile à 3000 m (fin de s04 = début de s05).
        stop_t0 = samples[-1]["t_s"] + 1
        samples.extend({"t_s": stop_t0 + k, "distance_m": 3000.0, "speed_ms": 0.0} for k in range(90))
        resume_t0 = samples[-1]["t_s"] + 1
        samples.extend({"t_s": resume_t0 + k, "distance_m": round(3000.0 + k * speed, 3), "speed_ms": speed}
                        for k in range(901))  # jusqu'à 6000 m pile (900 * speed = 3000 m restants)
        activity = _activity([(1, 300)], distance_m=6000.0, date="2026-09-27")
        result = D.build_race_debrief(plan, activity, fit_samples=samples)
        by_id = {s["id"]: s for s in result["segments"]}
        self.assertAlmostEqual(by_id["s04"]["delta_pct"], 0.0, delta=1.0)
        self.assertAlmostEqual(by_id["s05"]["delta_pct"], 0.0, delta=1.0)

    def test_build_checkpoints_from_samples(self):
        samples = [{"t_s": 0, "distance_m": 100.0}, {"t_s": 30, "distance_m": 200.0},
                   {"t_s": 60, "distance_m": 300.0}]
        checkpoints = D.build_checkpoints_from_samples(samples)
        self.assertEqual(checkpoints[0], (0.0, 0.0))
        self.assertEqual(checkpoints[-1], (200.0, 60.0))

    def test_no_usable_samples_raises(self):
        with self.assertRaises(D.DebriefError):
            D.build_checkpoints_from_samples([{"t_s": 0, "distance_m": None}])

    def test_fine_samples_give_high_resolution_short_segments(self):
        segments = [
            {"id": "s01", "km_start": 0.0, "km_end": 0.1, "distance_m": 100.0,
             "predicted_time_s": {"realistic": 30}, "pace_s_km": {"realistic": 300}},
            {"id": "s02", "km_start": 0.1, "km_end": 0.2, "distance_m": 100.0,
             "predicted_time_s": {"realistic": 30}, "pace_s_km": {"realistic": 300}},
        ]
        plan = {"arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "X",
                "race_date": "2026-09-27", "segments": segments}
        samples = [{"t_s": t, "distance_m": t * (100.0 / 30.0)} for t in range(0, 61, 5)]
        activity = _activity([(1, 60)], distance_m=200.0)
        result = D.build_race_debrief(plan, activity, fit_samples=samples)
        self.assertEqual(result["time_basis"], "fit_samples")
        for seg in result["segments"]:
            self.assertEqual(seg["resolution"], "high")

    def test_normalise_records_raw_fitparse_format_is_accepted(self):
        """Le format brut de `skills/fit-download/scripts/download_fit.py`
        (timestamp/distance/speed) doit fonctionner via `arc_samples.normalise_records`,
        pas seulement le format déjà normalisé."""
        raw = {"records": [{"timestamp": t, "distance": t * 3.0, "speed": 3.0} for t in range(10)]}
        normalised = SA.normalise_records(raw, sport="running")
        self.assertTrue(normalised)
        self.assertIn("t_s", normalised[0])
        self.assertIn("distance_m", normalised[0])


class TestLoadFitSamples(unittest.TestCase):
    def test_none_path_returns_none(self):
        self.assertIsNone(D._load_fit_samples(None))

    def test_missing_file_raises(self):
        with self.assertRaises(D.DebriefError):
            D._load_fit_samples(Path("/nonexistent/fit.json"))

    def test_invalid_json_raises_debrief_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(D.DebriefError):
                D._load_fit_samples(path)

    def test_unusable_samples_yield_empty_list_not_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text(json.dumps({"records": []}), encoding="utf-8")
            result = D._load_fit_samples(path)
            self.assertEqual(result, [])

    def test_empty_samples_warn_and_fall_back_to_splits(self):
        plan = _plan()
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        result = D.build_race_debrief(plan, activity, fit_samples=[])
        self.assertEqual(result["time_basis"], "elapsed_assumed")
        self.assertTrue(any("aucun échantillon exploitable" in w for w in result["warnings"]))


class TestRealPlanNonRegression(unittest.TestCase):
    """Non-régression sur le repro réel de la première revue de code (#61) : un
    vrai plan `scripts/arc_race_pacing.py plan` sur un GPX synthétique de
    10,29 km (segmentation par défaut 750 m, 2 ravitos aux km 5 et 8) et une
    activité couru exactement à l'allure planifiée plus les arrêts ravito
    prévus. Fixtures : `tests/data/fixtures/race_debrief/{plan,activity}.json`."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures" / "race_debrief"

    def _load(self, name):
        return json.loads((self.FIXTURES / name).read_text(encoding="utf-8"))

    def test_on_plan_race_gives_near_zero_deltas_and_no_findings(self):
        plan = self._load("plan.json")
        activity = self._load("activity.json")
        result = D.build_race_debrief(plan, activity)
        # Course courue exactement sur plan. Ravito 2 (km 8) porte un arrêt
        # RÉEL de 120 s dans l'activité, différent du défaut générique
        # (`DEFAULT_AID_STATION_STOP_S`, 90 s) — la fixture du plan déclare
        # donc explicitement `"stop_s": 120` sur ce ravito (#61, should-fix 5 :
        # le contrat permet de le persister). Le débrief ne compare JAMAIS son
        # temps planifié recalculé au `scenarios` du plan lui-même au-delà d'un
        # simple avertissement (> 5 % d'écart, voir `build_race_debrief`) — ce
        # n'est pas la source du résidu ici. Sans ce `stop_s` explicite, le
        # repli sur le défaut (90 s au lieu de 120 s) manquait 30 s à l'arrêt
        # réel, d'où le résidu de ~29 s observé avant ce correctif. Avec le
        # bon arrêt déclaré, le delta total tombe à ~1 s.
        self.assertLessEqual(abs(result["totals"]["delta_s"]), 2.0)
        codes = [f["code"] for f in result["findings"]]
        self.assertNotIn("depart_trop_rapide", codes)
        self.assertEqual(result["suggested_profile_updates"], [])
        # Tous les segments du plan réel (750 m) sont plus courts que la
        # granularité des splits (1 km) : "low" partout, jamais utilisés pour
        # justifier un finding (BLOQUANT 3) même si leur delta individuel
        # (interpolation) reste bruité.
        for seg in result["segments"]:
            self.assertEqual(seg["resolution"], "low")

    def test_last_partial_split_without_distance_matches_explicit_one(self):
        plan = self._load("plan.json")
        activity_no_dist = self._load("activity.json")
        result_a = D.build_race_debrief(plan, activity_no_dist)
        self.assertAlmostEqual(result_a["alignment"]["actual_distance_m"], 10288.0, places=0)


class TestNightErrorSummary(unittest.TestCase):
    """Erreur des sections de nuit séparée de celle des sections de jour (#184, prépare #188)."""

    def _night_plan(self):
        plan = _plan()
        for i, seg in enumerate(plan["segments"]):
            night = 1.0 if i >= 2 else 0.0
            seg["night_fraction"] = {"safe": night, "realistic": night, "ambitious": night}
        return plan

    def test_night_sections_error_reported_separately(self):
        activity = _activity([(1, 300), (2, 300), (3, 330), (4, 330)])
        result = D.build_race_debrief(self._night_plan(), activity)
        night = result["night"]
        self.assertEqual(night["night_segments"], 2)
        self.assertEqual(night["day_segments"], 2)
        self.assertAlmostEqual(night["night_delta_pct"], 10.0, places=1)
        self.assertAlmostEqual(night["day_delta_pct"], 0.0, places=1)
        self.assertAlmostEqual(night["night_minus_day_pct"], 10.0, places=1)

    def test_plan_without_night_fraction_has_no_night_key(self):
        activity = _activity([(1, 300), (2, 300), (3, 300), (4, 300)])
        self.assertNotIn("night", D.build_race_debrief(_plan(), activity))


if __name__ == "__main__":
    unittest.main()
