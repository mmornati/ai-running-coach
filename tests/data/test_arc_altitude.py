"""Palier D — altitude (#185, épopée #170) : pénalité de course et métrique d'exposition.

Familles : forme du facteur (seuil, linéarité, plafond), modulation par l'acclimatation
déclarée et par l'exposition à l'entraînement, composition avec chaleur et nuit, ordre des
scénarios, non-régression octet pour octet sous le seuil, métrique d'exposition sur échantillons
synthétiques (dont l'altitude manquante).
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_altitude as AL  # noqa: E402
import arc_index as I  # noqa: E402
import arc_race_pacing as RP  # noqa: E402
from tests.data.test_arc_race_pacing import (  # noqa: E402
    PERSONAL_BINS, _UltraClimbFlatDescentProfile, _straight_course,
)

TODAY = date(2026, 9, 23)


class _Offset:
    """Profil du test de pacing décalé de `offset_m` (parcours « en altitude »)."""

    def __init__(self, base, offset_m):
        self.base, self.offset_m, self.total_m = base, offset_m, base.total_m

    def __call__(self, d):
        return self.base(d) + self.offset_m


def _pts(offset_m):
    return _straight_course(_Offset(_UltraClimbFlatDescentProfile(), offset_m), step_m=25.0)


def _kw(**over):
    kw = dict(aid_stations=[{"km": 20.0, "name": "R1"}, {"km": 60.0, "name": "R2", "stop_s": 300}],
              fade_pct=4.0, intensity_factor=1.1, intensity_source="riegel", race_date="2026-06-20",
              segment_m=750.0)
    kw.update(over)
    return kw


class TestFactorShape(unittest.TestCase):
    def test_no_effect_up_to_threshold_or_unknown(self):
        self.assertEqual(AL.altitude_time_factor(None), 1.0)
        self.assertEqual(AL.altitude_time_factor(0.0), 1.0)
        self.assertEqual(AL.altitude_time_factor(AL.ALTITUDE_THRESHOLD_M), 1.0)

    def test_increasing_with_altitude_and_matches_literature_slope(self):
        f2000 = AL.altitude_time_factor(2000.0)
        f2500 = AL.altitude_time_factor(2500.0)
        self.assertGreater(f2000, 1.0)
        self.assertGreater(f2500, f2000)
        # 1 000 m au-dessus du seuil : perte de VO2max de 6,3 % -> temps x 1/(1 - 0,063)
        self.assertAlmostEqual(AL.altitude_time_factor(2500.0), 1.0 / (1.0 - 0.063), places=6)

    def test_capped_far_above(self):
        self.assertEqual(AL.altitude_time_factor(6000.0), AL.altitude_time_factor(AL.ALTITUDE_CAP_M))

    def test_tunable_threshold_and_slope(self):
        self.assertEqual(AL.altitude_time_factor(1800.0, threshold_m=2000.0), 1.0)
        self.assertGreater(AL.altitude_time_factor(2500.0, loss_pct_per_1000m=7.5),
                           AL.altitude_time_factor(2500.0, loss_pct_per_1000m=4.6))


class TestSectionExcess(unittest.TestCase):
    """Revue #185 : excédent moyen pondéré par la distance (effet non linéaire du seuil, densité
    de points GPX), plutôt que l'altitude moyenne des points."""

    def test_section_crossing_threshold_is_penalised_for_its_high_part(self):
        # col 1 200 -> 2 800 m à pente constante : altitude moyenne 2 000 m
        d = [i * 100.0 for i in range(17)]
        a = [1200.0 + i * 100.0 for i in range(17)]
        ex = AL.excess_above(a, d)
        self.assertAlmostEqual(ex, 1300.0 ** 2 / 2 / 1600.0, delta=1.0)   # ≈ 528 m, > 500 m (moyenne − seuil)
        self.assertGreater(AL.altitude_time_factor(1500.0 + ex), AL.altitude_time_factor(2000.0))
        # section moyenne 1 500 m qui franchit le seuil : pénalité faible mais non nulle
        self.assertGreater(AL.excess_above([1000.0, 2000.0], [0.0, 1000.0]), 0.0)

    def test_point_density_does_not_bias(self):
        # 1 km à 1 500 m puis 1 km à 2 500 m, la partie basse 10 fois plus densément échantillonnée
        d = [i * 10.0 for i in range(101)] + [1000.0 + i * 100.0 for i in range(1, 11)]
        a = [1500.0] * 101 + [2500.0] * 10
        self.assertAlmostEqual(AL.excess_above(a, d), 500.0, delta=55.0)

    def test_cap_pointwise_and_missing(self):
        self.assertEqual(AL.excess_above([9000.0, 9000.0], [0.0, 10.0]), AL.ALTITUDE_CAP_M - 1500.0)
        self.assertIsNone(AL.excess_above([None, None], [0.0, 10.0]))
        self.assertEqual(AL.excess_above([None, 1600.0], [0.0, 10.0]), 100.0)


class TestAcclimation(unittest.TestCase):
    def test_declared_days_ramp_and_cap(self):
        self.assertEqual(AL.altitude_credit(None, None)["total"], 0.0)
        self.assertAlmostEqual(AL.altitude_credit(7, None)["declared"], 0.25)
        self.assertAlmostEqual(AL.altitude_credit(14, None)["total"], 0.5)
        self.assertAlmostEqual(AL.altitude_credit(100, None)["total"], 0.5)

    def test_training_credit_smaller_and_capped_total(self):
        self.assertAlmostEqual(AL.altitude_credit(None, 10.0)["training"], 0.25)
        self.assertAlmostEqual(AL.altitude_credit(None, 50.0)["training"], 0.25)
        self.assertEqual(AL.altitude_credit(14, 10.0)["total"], 0.5)   # plafonné, jamais d'annulation

    def test_credit_reduces_but_never_cancels_penalty(self):
        none = AL.altitude_time_factor(2800.0, credit=0.0)
        full = AL.altitude_time_factor(2800.0, credit=0.5)
        self.assertLess(full, none)
        self.assertGreater(full, 1.0)

    def test_training_hours_from_report(self):
        rep = {"status": "exposed", "windows": {"28": {"thresholds": {"1500": {"duration_s": 7200}}}}}
        self.assertAlmostEqual(AL.training_hours_ge(rep), 2.0)
        self.assertIsNone(AL.training_hours_ge({"status": "no_altitude"}))
        self.assertIsNone(AL.training_hours_ge(None))


class TestRacePenalty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.low = RP.build_race_plan(_pts(0.0), PERSONAL_BINS, **_kw())
        cls.off = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, altitude_enabled=False, **_kw())
        cls.high = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, **_kw())

    def test_below_threshold_plan_is_unchanged_except_additive_key(self):
        self.assertEqual(self.low["altitude"]["status"], "below_threshold")
        disabled = RP.build_race_plan(_pts(0.0), PERSONAL_BINS, altitude_enabled=False, **_kw())
        for plan in (self.low, disabled):
            self.assertEqual(plan["altitude"]["status"] in ("below_threshold", "disabled"), True)
        a = {k: v for k, v in self.low.items() if k != "altitude"}
        b = {k: v for k, v in disabled.items() if k != "altitude"}
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        for seg in self.low["segments"]:
            self.assertNotIn("altitude_factor", seg)

    def test_above_threshold_slows_every_scenario(self):
        self.assertEqual(self.high["altitude"]["status"], "applied")
        for s in RP.SCENARIOS:
            self.assertGreater(self.high["totals"]["time_s"][s], self.off["totals"]["time_s"][s])
            self.assertGreater(self.high["altitude"]["time_added_s"][s], 0)
        self.assertTrue(any("altitude :" in w for w in self.high["warnings"]))

    def test_section_factors_follow_mean_altitude(self):
        factors = [(seg["altitude_m"], seg["altitude_factor"]) for seg in self.high["segments"]]
        for alt, f in factors:
            # sections entièrement au-dessus du seuil : excédent moyen = altitude moyenne − seuil
            self.assertAlmostEqual(f, AL.altitude_time_factor(alt), delta=2e-3)
        high_alt = max(factors)[1]
        low_alt = min(factors)[1]
        self.assertGreater(high_alt, low_alt)

    def test_scenario_order_preserved(self):
        for seg in self.high["segments"]:
            t = seg["predicted_time_s"]
            self.assertGreaterEqual(t["safe"], t["realistic"])
            self.assertGreaterEqual(t["realistic"], t["ambitious"])
        tt = self.high["totals"]["time_s"]
        self.assertGreaterEqual(tt["safe"], tt["realistic"])
        self.assertGreaterEqual(tt["realistic"], tt["ambitious"])

    def test_acclimation_declared_reduces_penalty(self):
        acc = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, altitude_acclimated_days=14, **_kw())
        self.assertLess(acc["totals"]["time_s"]["realistic"], self.high["totals"]["time_s"]["realistic"])
        self.assertGreater(acc["totals"]["time_s"]["realistic"], self.off["totals"]["time_s"]["realistic"])
        self.assertEqual(acc["altitude"]["acclimation"]["credit"]["declared"], 0.5)

    def test_training_exposure_reduces_penalty(self):
        exposure = {"status": "exposed", "as_of": "2026-06-10",
                    "windows": {"28": {"thresholds": {"1500": {"duration_s": 36000}}}}}
        trained = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, altitude_exposure=exposure, **_kw())
        self.assertLess(trained["totals"]["time_s"]["realistic"], self.high["totals"]["time_s"]["realistic"])
        self.assertEqual(trained["altitude"]["acclimation"]["credit"]["training"], 0.25)
        self.assertTrue(trained["altitude"]["acclimation"]["training_credited"])

    def test_training_exposure_not_credited_far_from_race_or_without_date(self):
        """Revue #185 : une exposition mesurée des semaines avant la course (ou sans date de course,
        ou sans date de mesure) n'est jamais créditée — l'acclimatation se perd."""
        base = {"status": "exposed", "windows": {"28": {"thresholds": {"1500": {"duration_s": 36000}}}}}
        cases = [({**base, "as_of": "2026-05-01"}, "2026-06-20"),   # 50 j avant
                 ({**base, "as_of": "2026-06-25"}, "2026-06-20"),   # course passée
                 (base, "2026-06-20"),                              # date de mesure inconnue
                 ({**base, "as_of": "2026-06-10"}, None)]           # date de course inconnue
        for exposure, race_date in cases:
            plan = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, altitude_exposure=exposure,
                                      **_kw(race_date=race_date))
            acc = plan["altitude"]["acclimation"]
            self.assertEqual(acc["credit"]["training"], 0.0, (exposure.get("as_of"), race_date))
            self.assertFalse(acc["training_credited"])
            self.assertIn("non créditée", acc["note"])
        ok, _ = AL.training_credit_lead({"as_of": "2026-06-06"}, "2026-06-20")
        self.assertTrue(ok)   # borne incluse : 14 j
        ok, _ = AL.training_credit_lead({"as_of": "2026-06-05"}, "2026-06-20")
        self.assertFalse(ok)

    def test_warning_says_default_on_and_how_to_opt_out(self):
        w = [x for x in self.high["warnings"] if x.startswith("altitude :")][0]
        self.assertIn("--no-altitude", w)
        self.assertIn("par défaut", w)

    def test_composes_with_heat(self):
        hot_low = RP.build_race_plan(_pts(0.0), PERSONAL_BINS, temp_max_c=30.0, acclimated=False, **_kw())
        hot_high = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, temp_max_c=30.0, acclimated=False, **_kw())
        ratio = hot_high["totals"]["time_s"]["realistic"] / hot_low["totals"]["time_s"]["realistic"]
        plain_ratio = self.high["totals"]["time_s"]["realistic"] / self.off["totals"]["time_s"]["realistic"]
        self.assertGreater(ratio, 1.0)
        self.assertAlmostEqual(ratio, plain_ratio, delta=0.01)   # facteurs multiplicatifs : effets indépendants

    def test_composes_with_night(self):
        kw = _kw(race_date="2026-06-20")
        night_off = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, start_time="16:00", tz="Etc/GMT+9",
                                       altitude_enabled=False, **kw)
        night_on = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, start_time="16:00", tz="Etc/GMT+9", **kw)
        self.assertEqual(night_on["night"]["status"], "night")
        self.assertGreater(night_on["totals"]["time_s"]["realistic"], night_off["totals"]["time_s"]["realistic"])
        for seg in night_on["segments"]:
            self.assertIn("night_factor", seg)
            self.assertIn("altitude_factor", seg)
            t = seg["predicted_time_s"]
            self.assertGreaterEqual(t["safe"], t["realistic"])
            self.assertGreaterEqual(t["realistic"], t["ambitious"])

    def test_no_elevation_is_explicit(self):
        flat = [{"lat": p["lat"], "lon": p["lon"], "ele": None} for p in _pts(0.0)]
        plan = RP.build_race_plan(flat, PERSONAL_BINS, **_kw())
        self.assertEqual(plan["altitude"]["status"], "no_elevation")

    def test_assumptions_document_source_and_approximation(self):
        text = RP.ASSUMPTIONS["altitude"]
        for needle in ("Wehrlin", "10.1007/s00421-005-0081-9", "approximation du projet", "6,3"):
            self.assertIn(needle, text)

    def test_dem_source_label(self):
        plan = json.loads(json.dumps(self.high))
        plan["elevation_dem"] = {"status": "ok"}
        RP._note_elevation_source(plan)
        self.assertEqual(plan["altitude"]["elevation_source"], "dem")
        plan2 = json.loads(json.dumps(self.high))
        plan2["elevation_dem"] = {"status": "unavailable"}
        RP._note_elevation_source(plan2)
        self.assertEqual(plan2["altitude"]["elevation_source"], "gpx")

    def test_personal_scale_multiplies_surcharge(self):
        """#188 x #185 : `altitude_scale` multiplie le SURCOÛT (facteur − 1) de chaque section —
        la grandeur qu'estime `arc_pacing_calibration` — et il est consigné dans `pacing_personal`."""
        scaled = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, altitude_scale=2.0, **_kw())
        for a, b in zip(self.high["segments"], scaled["segments"]):
            self.assertAlmostEqual(b["altitude_factor"] - 1.0, 2.0 * (a["altitude_factor"] - 1.0), delta=2e-4)
        self.assertGreater(scaled["totals"]["time_s"]["realistic"], self.high["totals"]["time_s"]["realistic"])
        self.assertEqual(scaled["pacing_personal"], {"altitude_scale": 2.0})
        self.assertEqual(scaled["altitude"]["parameters"]["personal_scale"], 2.0)
        self.assertNotIn("pacing_personal", self.high)
        tt = scaled["totals"]["time_s"]
        self.assertGreaterEqual(tt["safe"], tt["realistic"])
        self.assertGreaterEqual(tt["realistic"], tt["ambitious"])

    def test_personal_scale_absent_effect_below_threshold_or_disabled(self):
        for pts, enabled in ((_pts(0.0), True), (_pts(1500.0), False)):
            plan = RP.build_race_plan(pts, PERSONAL_BINS, altitude_scale=2.0, altitude_enabled=enabled, **_kw())
            ref = RP.build_race_plan(pts, PERSONAL_BINS, altitude_enabled=enabled, **_kw())
            self.assertEqual(json.dumps(plan, sort_keys=True), json.dumps(ref, sort_keys=True))
        unit = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, altitude_scale=1.0, **_kw())
        self.assertEqual(json.dumps(unit, sort_keys=True), json.dumps(self.high, sort_keys=True))

    def test_composes_with_technicity(self):
        """#186 x #185 : technicité puis altitude, facteurs multiplicatifs, ordre des scénarios gardé."""
        tech = {"declared": [{"km_start": 0.0, "km_end": 200.0, "coef": 1.25}], "ways": None,
                "osm_requested": False}
        both = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, technicity=tech, **_kw())
        tech_only = RP.build_race_plan(_pts(1500.0), PERSONAL_BINS, technicity=tech, altitude_enabled=False,
                                       **_kw())
        ratio = both["totals"]["time_s"]["realistic"] / tech_only["totals"]["time_s"]["realistic"]
        plain = self.high["totals"]["time_s"]["realistic"] / self.off["totals"]["time_s"]["realistic"]
        self.assertAlmostEqual(ratio, plain, delta=0.01)
        for seg in both["segments"]:
            self.assertIn("technicity", seg)
            self.assertIn("altitude_factor", seg)
            t = seg["predicted_time_s"]
            self.assertGreaterEqual(t["safe"], t["realistic"])
            self.assertGreaterEqual(t["realistic"], t["ambitious"])


class TestAltitudeScaleCli(unittest.TestCase):
    """`arc_race_pacing.py plan` en sous-processus : `[pacing.personal].altitude_scale` lu,
    `--altitude-loss-pct` prioritaire, `--no-altitude` l'ignore."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        gpx = ['<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
               '<trk><trkseg>']
        for p in _pts(1500.0):
            gpx.append(f'<trkpt lat="{p["lat"]}" lon="{p["lon"]}"><ele>{p["ele"]}</ele></trkpt>')
        gpx.append("</trkseg></trk></gpx>")
        cls.gpx = cls.root / "course.gpx"
        cls.gpx.write_text("".join(gpx), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _plan(self, toml: str, *extra: str) -> dict:
        import subprocess
        ws = Path(tempfile.mkdtemp(dir=self.root))
        (ws / "config").mkdir()
        if toml:
            (ws / "config" / "workspace.user.toml").write_text(toml, encoding="utf-8")
        cmd = [sys.executable, str(REPO / "scripts" / "arc_race_pacing.py"), "plan", "--gpx", str(self.gpx),
               "--workspace", str(ws), "--memory", "--race-date", "2026-06-20", *extra]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_precedence(self):
        toml = "[pacing.personal]\naltitude_scale = 1.5\n"
        base = self._plan("")
        pers = self._plan(toml)
        self.assertEqual(pers["pacing_personal"], {"altitude_scale": 1.5})
        self.assertEqual(pers["altitude"]["status"], "applied")
        self.assertEqual(pers["altitude"]["parameters"]["personal_scale"], 1.5)
        for a, b in zip(base["segments"], pers["segments"]):
            self.assertAlmostEqual(b["altitude_factor"] - 1.0, 1.5 * (a["altitude_factor"] - 1.0), delta=2e-4)
        # --altitude-loss-pct (CLI) prime : l'échelle personnelle n'est pas appliquée
        cli = self._plan(toml, "--altitude-loss-pct", "6.3")
        self.assertNotIn("pacing_personal", cli)
        self.assertEqual(cli["totals"], base["totals"])
        off = self._plan(toml, "--no-altitude")
        self.assertNotIn("pacing_personal", off)
        self.assertEqual(off["altitude"]["status"], "disabled")


class TestExposureReport(unittest.TestCase):
    def rows(self):
        return [
            {"date": "2026-09-20", "max_altitude_m": 2100.0, "altitude_s": 3600.0, "above_s": {1500: 3000.0, 2000: 600.0}},
            {"date": "2026-09-05", "max_altitude_m": 1600.0, "altitude_s": 3600.0, "above_s": {1500: 1200.0, 2000: 0.0}},
            {"date": "2026-09-21", "max_altitude_m": 300.0, "altitude_s": 3600.0, "above_s": {1500: 0.0, 2000: 0.0}},
            {"date": "2026-09-22", "max_altitude_m": None, "altitude_s": None, "above_s": {}},
        ]

    def test_as_of_is_the_window_end(self):
        """Revue #185 : la date de fin de fenêtre sert à décider si l'exposition est créditée."""
        self.assertEqual(AL.exposure_report(self.rows(), TODAY)["as_of"], TODAY.isoformat())

    def test_windows_and_thresholds(self):
        rep = AL.exposure_report(self.rows(), TODAY)
        self.assertEqual(rep["status"], "exposed")
        w14, w28 = rep["windows"]["14"], rep["windows"]["28"]
        self.assertEqual(w14["sessions"], 3)           # 09-05 hors de la fenêtre de 14 j
        self.assertEqual(w28["sessions"], 4)
        self.assertEqual(w28["thresholds"]["1500"]["sessions"], 2)
        self.assertEqual(w28["thresholds"]["1500"]["duration_s"], 4200)
        self.assertEqual(w28["thresholds"]["2000"]["sessions"], 1)
        self.assertEqual(w28["max_altitude_m"], 2100)

    def test_missing_altitude_is_not_zero_exposure(self):
        w28 = AL.exposure_report(self.rows(), TODAY)["windows"]["28"]
        self.assertEqual(w28["sessions_without_altitude"], 1)
        self.assertEqual(w28["sessions_with_altitude"], 3)

    def test_short_blip_does_not_count_as_session(self):
        rows = [{"date": "2026-09-20", "max_altitude_m": 1520.0, "altitude_s": 3600.0,
                 "above_s": {1500: 60.0, 2000: 0.0}}]
        w = AL.exposure_report(rows, TODAY)["windows"]["28"]["thresholds"]["1500"]
        self.assertEqual((w["sessions"], w["duration_s"]), (0, 60))

    def test_states(self):
        self.assertEqual(AL.exposure_report([], TODAY)["status"], "no_activity")
        only_missing = [{"date": "2026-09-20", "max_altitude_m": None, "altitude_s": None, "above_s": {}}]
        self.assertEqual(AL.exposure_report(only_missing, TODAY)["status"], "no_altitude")
        low = [{"date": "2026-09-20", "max_altitude_m": 200.0, "altitude_s": 3600.0, "above_s": {1500: 0.0, 2000: 0.0}}]
        self.assertEqual(AL.exposure_report(low, TODAY)["status"], "none")


class TestExposureIndex(unittest.TestCase):
    """Bout en bout : fichiers d'activité + FIT synthétiques -> index -> `altitude_exposure`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-alt-"))
        self.ws = self.tmp / "ws"
        for d in ("activities/fit", "medical", "nutrition", "planning", "rapports", "gear"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def activity(self, day, gid, altitudes=None, sport="trail"):
        data = {"arc": 1, "kind": "activity", "date": day, "sport": sport, "duration_s": 3600,
                "distance_m": 10000, "garmin_activity_id": gid}
        (self.ws / f"activities/{day}_{sport}.md").write_text(f"# S\n\n```arc\n{json.dumps(data)}\n```\n", encoding="utf-8")
        if altitudes is not None:
            records = [{"t_s": i * 5, "distance_m": i * 15.0, "speed_ms": 3.0, "altitude_m": a}
                       for i, a in enumerate(altitudes)]
            (self.ws / f"activities/fit/{gid}.json").write_text(
                json.dumps({"activity_id": gid, "records": records}), encoding="utf-8")

    def report(self, **kw):
        I.index_workspace(self.conn, self.ws, TODAY.isoformat())
        return I.altitude_exposure(self.conn, TODAY, **kw)

    def test_synthetic_samples(self):
        self.activity("2026-09-20", 1, [1000.0] * 100 + [2100.0] * 200)   # 200 x 5 s >= 2000 m = 1000 s
        self.activity("2026-09-21", 2, [200.0] * 300)
        self.activity("2026-09-22", 3)                                      # sans échantillon
        rep = self.report()
        w = rep["windows"]["28"]
        self.assertEqual(rep["status"], "exposed")
        self.assertEqual(w["sessions"], 3)
        self.assertEqual(w["sessions_without_altitude"], 1)
        self.assertEqual(w["thresholds"]["2000"]["sessions"], 1)
        self.assertGreater(w["thresholds"]["2000"]["duration_s"], 0)
        self.assertGreaterEqual(w["thresholds"]["1500"]["duration_s"], w["thresholds"]["2000"]["duration_s"])
        self.assertEqual(w["max_altitude_m"], 2100)

    def test_indoor_sessions_are_not_missing_altitude(self):
        """Revue #185 : une séance de renforcement n'a pas d'altitude à mesurer — elle n'est ni
        comptée comme séance ni comme « sans altitude »."""
        self.activity("2026-09-20", 1, [2100.0] * 200)
        self.activity("2026-09-21", 2, sport="strength")
        w = self.report()["windows"]["28"]
        self.assertEqual(w["sessions"], 1)
        self.assertEqual(w["sessions_without_altitude"], 0)

    def test_empty_workspace(self):
        self.assertEqual(self.report()["status"], "no_activity")

    def test_days_option_single_window(self):
        self.activity("2026-09-20", 1, [2100.0] * 200)
        rep = self.report(days=7)
        self.assertEqual(list(rep["windows"]), ["7"])

    def test_cli(self):
        self.activity("2026-09-20", 1, [2100.0] * 200)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", TODAY.isoformat(),
                           "altitude-exposure", "--days", "14"])
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["status"], "exposed")


if __name__ == "__main__":
    unittest.main()
