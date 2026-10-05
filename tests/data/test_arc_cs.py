"""Palier D — vitesse critique (CS), D′ et courbe allure-durée en GAP (#169).

Fonctions pures de `scripts/arc_cs.py` sur des échantillons SYNTHÉTIQUES à vérité connue (efforts qui
obéissent exactement à `d = CS·t + D′`), plus l'intégration index/CLI (`arc_index.pace_curve`) et la
cible d'intervalles en % de CS (`arc_workout_targets`). Aucune donnée réelle.

- courbe d'une séance : meilleure fenêtre retrouvée, GAP sur une montée constante (vitesse mesurée plus
  basse, GAP plus haute), trous de signal jamais interpolés, séance sans altitude écartée ;
- `best_of` : bornes de fenêtre incluses, meilleur parmi plusieurs séances ;
- `fit_cs` : CS/D′ retrouvées (sans bruit, avec bruit), refus explicites (points, dispersion, D′ nul/
  hors plage, CS non positive, ajustement médiocre), jamais d'extrapolation ;
- tendance, comparaison au seuil lactique, budget D′ ;
- index : `pace_curve` de bout en bout sur des fichiers FIT synthétiques, cible `cs_target`.
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_cs as CS  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_index as I  # noqa: E402
import arc_workout_targets as T  # noqa: E402

RES = 5.0
EASY = 2.5


def _samples(segments, resolution_s=RES, slope=0.0):
    """`segments` : liste de (durée_s, vitesse_ms) ; échantillons normalisés à 5 s, altitude liée à
    la distance par `slope` (fraction), `covered_s` = pas."""
    out, t, dist = [], 0.0, 0.0
    for dur, v in segments:
        for _ in range(int(round(dur / resolution_s))):
            out.append({"t_s": t, "distance_m": dist, "altitude_m": slope * dist, "speed_ms": v,
                        "covered_s": resolution_s})
            t += resolution_s
            dist += v * resolution_s
    return out


def _effort_activity(duration_s, speed, warmup_s=600, cooldown_s=300):
    return _samples([(warmup_s, EASY), (duration_s, speed), (cooldown_s, EASY)])


def _points(cs, d_prime, durations=(180, 300, 480, 720, 1200)):
    return [{"duration_s": t, "speed_ms": cs + d_prime / t} for t in durations]


class TestActivityCurve(unittest.TestCase):
    def test_finds_the_known_effort_window(self):
        res = CS.activity_curve(_effort_activity(300, 5.0))
        self.assertAlmostEqual(res["curve"][300], 5.0, delta=0.02)
        # une fenêtre plus courte tenue à 5,0 m/s est aussi retrouvée à 5,0 ; une plus longue est diluée
        self.assertAlmostEqual(res["curve"][120], 5.0, delta=0.02)
        self.assertLess(res["curve"][600], 5.0)
        self.assertGreater(res["curve"][600], EASY)

    def test_curve_is_non_increasing_in_duration(self):
        curve = CS.activity_curve(_effort_activity(720, 4.4))["curve"]
        speeds = [curve[d] for d in sorted(curve)]
        self.assertTrue(all(a >= b - 1e-9 for a, b in zip(speeds, speeds[1:])))

    def test_hilly_constant_effort_is_flat_equivalent(self):
        # +5 % constant à 3 m/s mesurés : le GAP est plus haut que la vitesse mesurée (Minetti).
        res = CS.activity_curve(_samples([(1500, 3.0)], slope=0.05))
        expected = G.gap_speed_ms(3.0, 0.05)
        self.assertGreater(expected, 3.0)
        self.assertAlmostEqual(res["curve"][600], expected, delta=0.02 * expected)

    def test_signal_gap_is_never_interpolated(self):
        # 300 s à 4 m/s, TROU de 60 s, 300 s à 5 m/s.
        first = _samples([(300, 4.0)])
        second = _samples([(300, 5.0)])
        dist0 = first[-1]["distance_m"] + 4.0 * RES + 60 * 4.0
        shifted = [{**s, "t_s": s["t_s"] + 360.0, "distance_m": s["distance_m"] + dist0} for s in second]
        res = CS.activity_curve(first + shifted)
        self.assertAlmostEqual(res["curve"][300], 5.0, delta=0.02)
        self.assertNotIn(600, res["curve"])   # toute fenêtre de 10 min enjambe le trou (couverture 90 %)

    def test_small_signal_gap_averages_over_covered_time(self):
        # 10 min à 5 m/s avec un trou de 20 s au milieu (3 % < 5 %) : la fenêtre reste retenue et sa
        # vitesse est la moyenne sur le temps COUVERT (5,0), pas la distance divisée par 10 min (4,83).
        first = _samples([(300, 5.0)])
        second = _samples([(300, 5.0)])
        shift = 320.0
        dist0 = first[-1]["distance_m"] + 5.0 * RES + 20 * 5.0
        shifted = [{**s, "t_s": s["t_s"] + shift, "distance_m": s["distance_m"] + dist0} for s in second]
        res = CS.activity_curve(first + shifted)
        self.assertAlmostEqual(res["curve"][600], 5.0, delta=0.02)

    def test_no_altitude_activity_is_skipped_with_reason(self):
        flat_no_alt = [{k: v for k, v in s.items() if k != "altitude_m"} for s in _effort_activity(300, 5.0)]
        res = CS.activity_curve(flat_no_alt)
        self.assertEqual(res["curve"], {})
        self.assertEqual(res["reason_code"], "no_grade")

    def test_empty_samples(self):
        self.assertEqual(CS.activity_curve([])["reason_code"], "no_samples")

    def test_activity_shorter_than_duration_has_no_entry(self):
        res = CS.activity_curve(_samples([(100, 4.0)]))
        self.assertNotIn(300, res["curve"])
        self.assertIn(60, res["curve"])


class TestBestOf(unittest.TestCase):
    TODAY = date(2026, 9, 25)

    def test_window_bounds_and_best_selection(self):
        curves = [
            {"date": "2026-09-25", "ref": 1, "curve": {300: 4.0}},                   # dernier jour inclus
            {"date": "2026-08-15", "ref": 2, "curve": {300: 4.5}},                   # 41 j avant : dans 42 j
            {"date": "2026-08-14", "ref": 3, "curve": {300: 9.9}},                   # 42 j avant : hors 42 j
            {"date": "2026-10-01", "ref": 4, "curve": {300: 9.9}},                   # futur
        ]
        rows = CS.best_of(curves, self.TODAY, 42)
        self.assertEqual([r["ref"] for r in rows], [2])
        self.assertAlmostEqual(rows[0]["pace_s_km"], 1000 / 4.5)
        self.assertEqual(CS.best_of(curves, self.TODAY, 90)[0]["ref"], 3)

    def test_empty(self):
        self.assertEqual(CS.best_of([], self.TODAY, 90), [])


class TestFitCs(unittest.TestCase):
    def test_recovers_known_cs_and_d_prime_exactly(self):
        fit = CS.fit_cs(_points(4.0, 200.0))
        self.assertEqual(fit["status"], "ok")
        self.assertTrue(fit["valid"])
        self.assertAlmostEqual(fit["cs_ms"], 4.0, places=3)
        self.assertAlmostEqual(fit["d_prime_m"], 200.0, delta=0.5)
        self.assertAlmostEqual(fit["r2"], 1.0, places=3)
        self.assertEqual(fit["n_points"], 5)
        self.assertEqual(fit["quality"], "bonne")
        self.assertAlmostEqual(fit["cs_pace_s_km"], 250.0, delta=0.2)

    def test_recovers_within_tolerance_with_noise(self):
        rng = random.Random(7)
        pts = [{"duration_s": p["duration_s"], "speed_ms": p["speed_ms"] * (1 + rng.uniform(-0.01, 0.01))}
               for p in _points(3.8, 250.0)]
        fit = CS.fit_cs(pts)
        self.assertEqual(fit["status"], "ok", fit["reason"])
        self.assertAlmostEqual(fit["cs_ms"], 3.8, delta=0.15)
        self.assertAlmostEqual(fit["d_prime_m"], 250.0, delta=120.0)
        self.assertGreater(fit["see_m"], 0.0)

    def test_end_to_end_from_synthetic_activities(self):
        cs, dp = 4.2, 220.0
        curves = []
        for i, t in enumerate((180, 300, 480, 720, 1200)):
            res = CS.activity_curve(_effort_activity(t, cs + dp / t))
            curves.append({"date": (date(2026, 9, 25) - timedelta(days=3 * i)).isoformat(), "ref": i,
                           "curve": res["curve"]})
        fit = CS.fit_cs(CS.best_of(curves, date(2026, 9, 25), 90))
        self.assertEqual(fit["status"], "ok", fit["reason"])
        self.assertAlmostEqual(fit["cs_ms"], cs, delta=0.06)
        self.assertAlmostEqual(fit["d_prime_m"], dp, delta=40.0)

    def test_refuses_with_too_few_points(self):
        fit = CS.fit_cs(_points(4.0, 200.0, durations=(300, 900)))
        self.assertEqual(fit["status"], "refused")
        self.assertEqual(fit["reason_code"], "insufficient_points")
        self.assertIsNone(fit["cs_ms"])
        self.assertIn("insuffisantes", fit["reason"])

    def test_points_outside_the_3_to_20_min_range_are_ignored(self):
        fit = CS.fit_cs(_points(4.0, 200.0, durations=(30, 60, 120, 300, 2700, 3600)))
        self.assertEqual(fit["reason_code"], "insufficient_points")
        self.assertEqual(fit["n_points"], 1)

    def test_refuses_when_all_points_come_from_one_session(self):
        pts = [{**p, "ref": 1} for p in _points(4.0, 200.0)]
        self.assertEqual(CS.fit_cs(pts)["reason_code"], "single_source")
        two = [{**p, "ref": i % 2} for i, p in enumerate(_points(4.0, 200.0))]
        self.assertEqual(CS.fit_cs(two)["status"], "ok")

    def test_refuses_when_durations_are_too_close(self):
        fit = CS.fit_cs(_points(4.0, 200.0, durations=(600, 720, 900)))
        self.assertEqual(fit["reason_code"], "insufficient_span")

    def test_refuses_flat_curve_as_non_maximal_efforts(self):
        fit = CS.fit_cs([{"duration_s": t, "speed_ms": 3.5} for t in (180, 300, 600, 1200)])
        self.assertEqual(fit["reason_code"], "d_prime_out_of_range")
        self.assertIsNone(fit["d_prime_m"])

    def test_refuses_absurd_d_prime(self):
        fit = CS.fit_cs(_points(3.0, 2500.0))
        self.assertEqual(fit["reason_code"], "d_prime_out_of_range")

    def test_refuses_poor_fit(self):
        pts = [{"duration_s": 180, "speed_ms": 5.0}, {"duration_s": 300, "speed_ms": 4.0},
               {"duration_s": 600, "speed_ms": 4.9}, {"duration_s": 1200, "speed_ms": 3.2}]
        fit = CS.fit_cs(pts)
        self.assertEqual(fit["status"], "refused")
        self.assertIn(fit["reason_code"], ("poor_fit", "d_prime_out_of_range", "non_positive_cs"))

    def test_no_points_at_all(self):
        self.assertEqual(CS.fit_cs([])["reason_code"], "insufficient_points")

    def test_quality_follows_parameter_uncertainty_not_r2(self):
        # Revue de code #169 : le R² d'une régression distance-durée dépasse 0,99 même pour des efforts
        # peu cohérents ; le niveau de qualité se juge sur l'erreur standard RELATIVE de CS et D′.
        exact = CS.fit_cs(_points(4.0, 200.0))
        self.assertEqual(exact["quality"], "bonne")
        self.assertAlmostEqual(exact["d_prime_se_m"], 0.0, delta=0.1)
        # ±2 % alternés sur la vitesse : R² ≈ 0,999 (l'ancien critère aurait dit « bonne »), D′ à ±40 %.
        noisy = CS.fit_cs([{"duration_s": p["duration_s"], "speed_ms": p["speed_ms"] * (1 + e)}
                           for p, e in zip(_points(3.8, 150.0), (0.02, -0.02, 0.02, -0.02, 0.02))])
        self.assertEqual(noisy["status"], "ok", noisy["reason"])
        self.assertGreater(noisy["r2"], 0.99)                    # R² trompeusement excellent…
        self.assertGreater(noisy["d_prime_se_pct"], 10.0)        # … mais D′ mal déterminée
        self.assertEqual(noisy["quality"], "faible")
        # erreur standard de l'ordonnée : see·√(1/n + t̄²/Sxx)
        ts = [p["duration_s"] for p in noisy["points"]]
        mt = sum(ts) / len(ts)
        sxx = sum((t - mt) ** 2 for t in ts)
        dists = [p["distance_m"] for p in noisy["points"]]
        fitted = [p["fitted_m"] for p in noisy["points"]]
        see = (sum((d - f) ** 2 for d, f in zip(dists, fitted)) / (len(ts) - 2)) ** 0.5
        self.assertAlmostEqual(noisy["d_prime_se_m"], see * (1 / len(ts) + mt * mt / sxx) ** 0.5, delta=1.0)


class TestBudgetTrendThreshold(unittest.TestCase):
    def test_d_prime_budget(self):
        fit = CS.fit_cs(_points(4.0, 200.0))
        self.assertAlmostEqual(CS.d_prime_budget_s(fit, 4.5), 400.0, delta=2.0)
        self.assertIsNone(CS.d_prime_budget_s(fit, 3.9))      # sous la CS : D′ non entamée
        self.assertIsNone(CS.d_prime_budget_s(None, 4.5))
        self.assertIsNone(CS.d_prime_budget_s({"valid": False}, 4.5))

    def test_threshold_comparison_flags_but_never_picks(self):
        fit = CS.fit_cs(_points(4.0, 200.0))
        close = CS.compare_threshold(fit, 3.95)
        self.assertTrue(close["available"])
        self.assertFalse(close["diverges"])
        far = CS.compare_threshold(fit, 3.5)
        self.assertTrue(far["diverges"])
        self.assertGreater(far["delta_pct"], 5.0)
        self.assertNotIn("preferred", far)
        self.assertFalse(CS.compare_threshold(fit, None)["available"])
        # unité mal convertie (Garmin rend parfois une vitesse 10 fois plus petite) ou NaN : refus, jamais comparé
        self.assertFalse(CS.compare_threshold(fit, 0.39)["available"])
        self.assertFalse(CS.compare_threshold(fit, float("nan"))["available"])
        self.assertFalse(CS.compare_threshold(fit, float("inf"))["available"])
        self.assertFalse(CS.compare_threshold({"valid": False}, 3.5)["available"])

    def test_trend_improves_and_refuses_without_data(self):
        today = date(2026, 9, 25)
        curves = []
        for months_ago, cs in ((0, 4.3), (3, 4.0)):
            day = today - timedelta(days=months_ago * 30 + 5)
            for part, durs in enumerate(((180, 300), (720, 1200))):   # deux séances par période
                curves.append({"date": day.isoformat(), "ref": f"{months_ago}-{part}",
                               "curve": {t: cs + 200.0 / t for t in durs}})
        trend = CS.cs_trend(curves, today, days=140)
        self.assertEqual(trend[-1]["date"], today.isoformat())
        self.assertEqual(trend[-1]["status"], "ok")
        ok = [p for p in trend if p["status"] == "ok"]
        self.assertGreaterEqual(len(ok), 2)
        self.assertLess(ok[0]["cs_ms"], ok[-1]["cs_ms"])
        refused = [p for p in trend if p["status"] != "ok"]
        self.assertTrue(all(p["cs_ms"] is None and p["reason_code"] for p in refused))

    def test_build_report_empty_is_honest(self):
        rep = CS.build_report([], date(2026, 9, 25))
        self.assertEqual(rep["n_activities"], 0)
        self.assertEqual(rep["current"]["status"], "refused")
        self.assertIsNotNone(rep["reason"])
        self.assertEqual([w["window_days"] for w in rep["windows"]], [42, 90, 365])


class TestCsTargets(unittest.TestCase):
    def test_targets_only_with_valid_fit(self):
        fit = CS.fit_cs(_points(4.0, 200.0))
        thr = T.cs_target_for_intensity("threshold", fit)
        self.assertAlmostEqual(thr["speed_low_ms"], 3.8, places=2)
        self.assertAlmostEqual(thr["speed_high_ms"], 4.0, places=2)
        self.assertIsNone(thr["d_prime_budget_s"])             # sous/à la CS : pas de budget D′
        vo2 = T.cs_target_for_intensity("vo2max", fit)
        self.assertGreater(vo2["speed_high_ms"], 4.0)
        self.assertGreater(vo2["d_prime_budget_s"], 0)
        self.assertLess(vo2["pace_fast_s_km"], vo2["pace_slow_s_km"])

    def test_refused_fit_or_unmapped_intensity_gives_no_speed(self):
        refused = CS.fit_cs(_points(4.0, 200.0, durations=(300, 900)))
        r = T.cs_target_for_intensity("vo2max", refused)
        self.assertIsNone(r["speed_low_ms"])
        self.assertEqual(r["reason_code"], "insufficient_points")
        self.assertEqual(T.cs_target_for_intensity("vo2max", None)["reason_code"], "no_cs_fit")
        self.assertEqual(T.cs_target_for_intensity("endurance", CS.fit_cs(_points(4.0, 200.0)))["reason_code"],
                         "unmapped_intensity")

    def test_build_session_targets_adds_cs_target_only_when_requested(self):
        session = {"date": "2026-09-30", "sport": "running", "title": "Seuil", "intensity": "threshold"}
        athlete = {"hr_max_bpm": 190, "hr_rest_bpm": 50}
        without = T.build_session_targets(session, athlete=athlete, bins=[])
        self.assertIsNone(without["cs_target"])
        fit = CS.fit_cs(_points(4.0, 200.0))
        withfit = T.build_session_targets(session, athlete=athlete, bins=[], cs_fit=fit)
        self.assertIsNotNone(withfit["cs_target"]["speed_low_ms"])
        self.assertIsNotNone(withfit["hr_target"])   # en complément des zones FC, jamais à leur place


class TestCsTargetHeat(unittest.TestCase):
    """#169 × #171 : `targets --heat` ralentit la cible en % de CS du même facteur que l'allure plate."""

    SESSION = {"date": "2026-09-30", "sport": "running", "title": "Seuil", "intensity": "threshold", "outdoor": True}
    ATHLETE = {"hr_max_bpm": 190, "hr_rest_bpm": 50}

    def _targets(self):
        return T.build_session_targets(self.SESSION, athlete=self.ATHLETE, bins=[], cs_fit=CS.fit_cs(_points(4.0, 200.0)))

    def test_hot_day_slows_cs_target_by_the_heat_factor(self):
        res = T.apply_heat(self._targets(), self.SESSION, temp_c=27.0, slot="morning")
        adj_heat = res["heat_adjustment"]
        self.assertTrue(adj_heat["applies"] and adj_heat["intensity_maintained"])
        factor = adj_heat["factor"]
        self.assertGreater(factor, 1.0)
        cs = res["cs_target"]
        self.assertAlmostEqual(cs["speed_low_ms"], 3.8, places=2)            # cible d'origine intacte
        self.assertAlmostEqual(cs["adjusted"]["speed_low_ms"], cs["speed_low_ms"] / factor)
        self.assertAlmostEqual(cs["adjusted"]["speed_high_ms"], cs["speed_high_ms"] / factor)
        self.assertEqual(cs["adjusted"]["factor"], factor)
        self.assertGreater(cs["adjusted"]["pace_slow_s_km"], cs["pace_slow_s_km"])   # plus lent
        self.assertNotIn("d_prime_budget_s", cs["adjusted"])                       # jamais recalculé
        self.assertIsNotNone(res["hr_target"])                                     # FC inchangée

    def test_cool_or_red_day_gives_no_adjusted_cs_target(self):
        cool = T.apply_heat(self._targets(), self.SESSION, temp_c=15.0)
        self.assertNotIn("adjusted", cool["cs_target"])
        red = T.apply_heat(self._targets(), self.SESSION, temp_c=34.0, slot="midday", category="red")
        self.assertFalse(red["heat_adjustment"]["intensity_maintained"])
        self.assertNotIn("adjusted", red["cs_target"])

    def test_refused_fit_is_never_adjusted(self):
        result = T.build_session_targets(self.SESSION, athlete=self.ATHLETE, bins=[], cs_fit={"valid": False})
        res = T.apply_heat(result, self.SESSION, temp_c=28.0, slot="midday")
        self.assertIsNone(res["cs_target"]["speed_low_ms"])
        self.assertNotIn("adjusted", res["cs_target"])


class TestPaceCurveIndex(unittest.TestCase):
    CS_MS, D_PRIME = 4.1, 210.0
    TODAY = "2026-09-25"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-cs-index-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _activity(self, gid, day, durations):
        # `gid` entier = Garmin ; chaîne `i<chiffres>` = intervals.icu (#68), `s<chiffres>` = Strava (#164).
        col = ("garmin_activity_id" if isinstance(gid, int)
               else "intervals_activity_id" if gid.startswith("i") else "strava_activity_id")
        fields = (f'"arc": 1, "kind": "activity", "date": "{day}", "sport": "running", '
                  f'"duration_s": 1500, "distance_m": 5000, "{col}": {json.dumps(gid)}')
        (self.ws / "activities" / f"{day}_running.md").write_text(
            f"# Titre\n\n```arc\n{{{fields}}}\n```\n", encoding="utf-8")
        fit = self.ws / "activities" / "fit"
        fit.mkdir(exist_ok=True)
        records = _effort_activity(durations, self.CS_MS + self.D_PRIME / durations)
        (fit / f"{gid}.json").write_text(json.dumps({"activity_id": gid, "records": records}), encoding="utf-8")

    def _index(self):
        I.index_workspace(self.conn, self.ws, self.TODAY)

    def test_insufficient_data_is_refused_not_extrapolated(self):
        # Un seul effort de 10 min : la courbe entière vient d'UNE séance (dilution par la course facile
        # au-delà de 10 min) — refus explicite, jamais une CS déduite d'un seul effort.
        self._activity(910000001, "2026-09-20", 600)
        self._index()
        rep = I.pace_curve(self.conn, date.fromisoformat(self.TODAY))
        self.assertEqual(rep["n_activities"], 1)
        self.assertEqual(rep["current"]["status"], "refused")
        self.assertEqual(rep["current"]["reason_code"], "single_source")
        self.assertIsNone(rep["current"]["cs_ms"])

    def test_known_cs_is_recovered_end_to_end_and_cli_matches(self):
        for i, t in enumerate((180, 300, 480, 720, 1200)):
            day = (date.fromisoformat(self.TODAY) - timedelta(days=4 + 5 * i)).isoformat()
            self._activity(910000010 + i, day, t)
        self._index()
        rep = I.pace_curve(self.conn, date.fromisoformat(self.TODAY), lt_speed_ms=3.6)
        fit = rep["current"]
        self.assertEqual(fit["status"], "ok", fit["reason"])
        self.assertAlmostEqual(fit["cs_ms"], self.CS_MS, delta=0.08)
        self.assertAlmostEqual(fit["d_prime_m"], self.D_PRIME, delta=45.0)
        self.assertTrue(rep["threshold_check"]["diverges"])
        self.assertEqual({w["window_days"] for w in rep["windows"]}, {42, 90, 365})
        # même sortie par la CLI
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["pace-curve", "--workspace", str(self.ws), "--memory", "--today", self.TODAY,
                           "--lt-speed-ms", "3.6", "--json"])
        self.assertEqual(code, 0)
        cli = json.loads(buf.getvalue())
        self.assertEqual(cli["current"]["cs_ms"], fit["cs_ms"])

    def test_curve_cache_gives_identical_report_and_follows_sample_changes(self):
        for i, t in enumerate((180, 300, 480, 720, 1200)):
            day = (date.fromisoformat(self.TODAY) - timedelta(days=4 + 5 * i)).isoformat()
            self._activity(910000020 + i, day, t)
        self._index()
        today = date.fromisoformat(self.TODAY)
        cache = {}
        plain = I.pace_curve(self.conn, today)
        cold = I.pace_curve(self.conn, today, curve_cache=cache)
        self.assertEqual(len(cache), 5)
        warm = I.pace_curve(self.conn, today, curve_cache=cache)
        self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(cold, sort_keys=True))
        self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(warm, sort_keys=True))
        # échantillons modifiés (FIT re-téléchargé) : nouvelle empreinte, courbe recalculée — jamais périmée
        self._activity(910000020, (today - timedelta(days=4)).isoformat(), 180)
        fit_path = self.ws / "activities" / "fit" / "910000020.json"
        data = json.loads(fit_path.read_text(encoding="utf-8"))
        for r in data["records"]:
            r["speed_ms"] = r["speed_ms"] * 1.1
            r["distance_m"] = r["distance_m"] * 1.1
        fit_path.write_text(json.dumps(data), encoding="utf-8")
        self._index()
        fresh = I.pace_curve(self.conn, today)
        cached = I.pace_curve(self.conn, today, curve_cache=cache)
        self.assertEqual(json.dumps(fresh, sort_keys=True), json.dumps(cached, sort_keys=True))
        self.assertNotEqual(fresh["windows"][1]["curve"][3]["speed_ms"], plain["windows"][1]["curve"][3]["speed_ms"])
        # séance retirée : l'entrée est oubliée (taille bornée)
        fit_path.unlink()
        for md in (self.ws / "activities").glob("*.md"):
            if "910000020" in md.read_text(encoding="utf-8"):
                md.unlink()
        self._index()
        I.pace_curve(self.conn, today, curve_cache=cache)
        self.assertNotIn(910000020, cache)

    def test_strava_and_intervals_sourced_samples_are_used(self):
        # #164 : séances Strava (`s<chiffres>`) et intervals.icu (`i<chiffres>`) mêlées à Garmin — toutes
        # comptent (REF_COLUMNS), avec ou sans cache, jamais écartées en silence.
        refs = ("s9100000001", "s9100000002", "i9100000003", 910000034, "s9100000005")
        for i, (ref, t) in enumerate(zip(refs, (180, 300, 480, 720, 1200))):
            day = (date.fromisoformat(self.TODAY) - timedelta(days=4 + 5 * i)).isoformat()
            self._activity(ref, day, t)
        self._index()
        today = date.fromisoformat(self.TODAY)
        rep = I.pace_curve(self.conn, today)
        self.assertEqual(rep["n_activities"], 5)
        self.assertEqual(rep["current"]["status"], "ok", rep["current"]["reason"])
        self.assertAlmostEqual(rep["current"]["cs_ms"], self.CS_MS, delta=0.08)
        best_refs = {r["ref"] for r in rep["windows"][1]["curve"]}
        self.assertIn("s9100000005", best_refs)
        cache = {}
        cached = I.pace_curve(self.conn, today, curve_cache=cache)
        self.assertEqual(json.dumps(rep, sort_keys=True), json.dumps(cached, sort_keys=True))
        self.assertIn("s9100000001", cache)

    def test_no_activities(self):
        self._index()
        rep = I.pace_curve(self.conn, date.fromisoformat(self.TODAY))
        self.assertEqual(rep["n_activities"], 0)
        self.assertEqual(rep["current"]["status"], "refused")

    def test_assumptions_exposed_with_cs_prefix(self):
        self._index()
        meta = json.loads(self.conn.execute("SELECT value FROM meta WHERE key = 'assumptions'").fetchone()[0])
        for key in CS.ASSUMPTIONS:
            self.assertIn(f"cs_{key}", meta)


if __name__ == "__main__":
    unittest.main()
