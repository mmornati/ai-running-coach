"""Palier D — pénalité de nuit dans le pacing de course (#184, épopée #170).

Familles de tests : fraction/facteur de nuit par section, convergence de l'itération,
cohérence des trois scénarios, résumé « frontale », indisponibilité explicite (entrées
manquantes), course de jour, et non-régression octet pour octet sans nuit (empreinte figée
AVANT la refonte, voir `GOLDEN_NO_NIGHT_SHA256`).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_race_pacing as RP  # noqa: E402
import arc_solar as S  # noqa: E402
from tests.data.test_arc_race_pacing import (  # noqa: E402
    PERSONAL_BINS, _ClimbFlatDescentProfile, _UltraClimbFlatDescentProfile, _straight_course,
)

# Empreinte du plan (hors `assumptions` et hors la clé additive `night`) produit par la version
# d'avant #184 pour `_golden_kwargs()` : la sortie sans nuit doit rester identique.
GOLDEN_NO_NIGHT_SHA256 = "d038f4096dcab4bb88529fbe1b22579d1646d7b28a6d39a14e2008b967f7e867"

# Zone fictive du dépôt (Pacifique sud, lat -40 / lon -140) : fuseau fixe UTC-9, sans heure d'été.
TZ = "Etc/GMT+9"
RACE_DATE = "2026-06-20"
DST_TZ = "America/Anchorage"  # changement d'heure, décalage plausible pour lon -140 (contrôle du fuseau)  # hiver austral : coucher civil ≈ 17:32 locale, aube civile ≈ 07:11


def _ultra_pts():
    return _straight_course(_UltraClimbFlatDescentProfile(), step_m=25.0)


def _kwargs(**over):
    kw = dict(aid_stations=[{"km": 20.0, "name": "R1"}, {"km": 60.0, "name": "R2", "stop_s": 300}],
              fade_pct=4.0, temp_max_c=None, acclimated=None, intensity_factor=1.1,
              intensity_source="riegel", race_date=RACE_DATE, segment_m=750.0)
    kw.update(over)
    return kw


def _golden_kwargs():
    return dict(aid_stations=[{"km": 20.0, "name": "R1", "cutoff": "14:00"}, {"km": 60.0, "name": "R2", "stop_s": 300}],
                fade_pct=4.0, fade_source="generic", temp_max_c=27.0, acclimated=False, intensity_factor=1.1,
                intensity_source="riegel", start_time="22:00", race_date="2026-06-20", segment_m=750.0,
                weight_kg=70.0, weight_source="profile", pack_kg=3.0)


class _FixedMask:
    """Masque fictif : nuit pour tout instant avant `until` (secondes après `start`)."""

    def __init__(self, start, until_s):
        self.start, self.until_s = start, until_s

    def night_seconds(self, t0, t1):
        a, b = (t0 - self.start).total_seconds(), (t1 - self.start).total_seconds()
        return max(0.0, min(b, self.until_s) - min(a, self.until_s))


class TestNightPenalty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pts = _ultra_pts()
        cls.base = RP.build_race_plan(cls.pts, PERSONAL_BINS, start_time="16:00", **_kwargs())
        cls.night = RP.build_race_plan(cls.pts, PERSONAL_BINS, start_time="16:00", tz=TZ, **_kwargs())

    def test_status_and_per_section_fields(self):
        self.assertEqual(self.night["night"]["status"], "night")
        for seg in self.night["segments"]:
            for key in ("night_fraction", "night_factor"):
                self.assertEqual(set(seg[key]), set(RP.SCENARIOS))

    def test_daylight_sections_unchanged_and_night_sections_penalised(self):
        first, last = self.night["segments"][0], self.night["segments"][-1]
        self.assertEqual(first["night_fraction"]["realistic"], 0.0)
        self.assertEqual(first["night_factor"]["realistic"], 1.0)
        self.assertEqual(first["predicted_time_s"], self.base["segments"][0]["predicted_time_s"])
        self.assertGreater(last["night_fraction"]["realistic"], 0.99)
        self.assertGreater(self.night["totals"]["time_s"]["realistic"], self.base["totals"]["time_s"]["realistic"])

    def test_flat_full_night_factor_is_the_base_penalty(self):
        flat = [s for s in self.night["segments"] if abs(s["grade_mean_pct"]) < 0.5
                and s["night_fraction"]["realistic"] > 0.99]
        self.assertTrue(flat)
        for seg in flat:
            self.assertAlmostEqual(seg["night_factor"]["realistic"], 1.0 + RP.NIGHT_BASE_PENALTY_PCT / 100.0, places=3)

    def test_steeper_descent_is_penalised_more(self):
        steep = [s for s in self.night["segments"] if s["grade_mean_pct"] < -2.5
                 and s["night_fraction"]["realistic"] > 0.99]
        self.assertTrue(steep)
        self.assertGreater(steep[0]["night_factor"]["realistic"], 1.0 + RP.NIGHT_BASE_PENALTY_PCT / 100.0)

    def test_penalty_fraction_function(self):
        f = RP.night_penalty_fraction
        self.assertAlmostEqual(f(5.0), 0.05)
        self.assertAlmostEqual(f(None), 0.05)
        self.assertAlmostEqual(f(-2.0), 0.05)           # sous la pente « franche »
        self.assertAlmostEqual(f(-7.0), 0.05 + 0.03)    # 0,6 × (7 − 2) = 3 points
        self.assertAlmostEqual(f(-40.0), 0.05 + 0.08)   # plafond du supplément
        self.assertAlmostEqual(f(-40.0, base_pct=0.0, descent_extra_max_pct=0.0), 0.0)

    def test_tunable_coefficients(self):
        zero = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ,
                                  night_penalty_pct=0.0, night_descent_extra_max_pct=0.0, **_kwargs())
        self.assertEqual(zero["totals"], self.base["totals"])
        strong = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ,
                                    night_penalty_pct=10.0, **_kwargs())
        self.assertGreater(strong["totals"]["time_s"]["realistic"], self.night["totals"]["time_s"]["realistic"])

    def test_iteration_converges_and_is_a_fixed_point(self):
        info = self.night["night"]
        self.assertTrue(info["converged"])
        self.assertLessEqual(info["iterations"], RP.NIGHT_MAX_ITERATIONS)
        for seg in self.night["segments"]:
            pen = RP.night_penalty_fraction(seg["grade_mean_pct"])
            for s in RP.SCENARIOS:
                self.assertAlmostEqual(seg["night_factor"][s], 1.0 + seg["night_fraction"][s] * pen, delta=2e-3)

    def test_iteration_bound_is_respected(self):
        segs = RP.predict_segments(RP.segment_course(self.pts), PERSONAL_BINS, intensity_factor=1.1)
        start = datetime(2026, 6, 20, 16, 0, tzinfo=timezone(timedelta(hours=-9)))
        mask = _FixedMask(start, 3 * 3600)
        _, info = RP.apply_night_penalty(segs, [], start, mask, max_iterations=1)
        self.assertEqual(info["iterations"], 1)

    def test_scenario_order_per_section_and_total(self):
        for seg in self.night["segments"]:
            t = seg["predicted_time_s"]
            self.assertGreaterEqual(t["safe"], t["realistic"])
            self.assertGreaterEqual(t["realistic"], t["ambitious"])
        tot = self.night["totals"]["time_s"]
        self.assertGreater(tot["safe"], tot["realistic"])
        self.assertGreater(tot["realistic"], tot["ambitious"])

    def test_scenario_order_is_clamped_when_a_penalty_would_invert_it(self):
        # Sections à descente raide : l'ambitieux, déjà de nuit, serait plus lent que le réaliste, qui
        # sort de la nuit — le plan doit rester ordonné et le dire.
        def seg(i, t_safe, t_real, t_amb, grade):
            return {"id": f"s{i}", "km_start": float(i), "km_end": i + 1.0, "distance_m": 1000.0,
                    "grade_mean_pct": grade,
                    "predicted_time_s": {"safe": t_safe, "realistic": t_real, "ambitious": t_amb},
                    "pace_s_km": {"safe": t_safe, "realistic": t_real, "ambitious": t_amb}}
        segs = [seg(0, 1000, 1000, 600, 0.0), seg(1, 700, 700, 690, -15.0)]
        start = datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc)
        mask = _FixedMask(start, 1300)
        out, info = RP.apply_night_penalty(segs, [], start, mask)
        for s in out:
            t = s["predicted_time_s"]
            self.assertGreaterEqual(t["safe"], t["realistic"])
            self.assertGreaterEqual(t["realistic"], t["ambitious"])
        self.assertGreaterEqual(info["clamped_segments"], 1)

    def test_aid_stops_shift_the_clock(self):
        # Un long arrêt au ravito déplace la suite de la course vers la nuit.
        no_stop = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ,
                                     **_kwargs(aid_stations=[{"km": 5.0, "name": "R1", "stop_s": 1}]))
        long_stop = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ,
                                       **_kwargs(aid_stations=[{"km": 5.0, "name": "R1", "stop_s": 7200}]))
        night_s = lambda p: sum(s["night_fraction"]["realistic"] * s["predicted_time_s"]["realistic"]  # noqa: E731
                                for s in p["segments"])
        self.assertGreater(night_s(long_stop), night_s(no_stop))

    def test_lamp_summary_per_scenario(self):
        for scenario, info in self.night["night"]["scenarios"].items():
            self.assertGreater(info["night_duration_s"], 0)
            self.assertIn("h de nuit, frontale requise de 17:3", info["summary"], scenario)
            self.assertTrue(info["lamp_from"].startswith("2026-06-20T17:3"))
            self.assertTrue(info["lamp_until"].endswith("-09:00"))
        # le plus lent finit plus tard, donc plus de nuit
        s = self.night["night"]["scenarios"]
        self.assertGreater(s["safe"]["night_duration_s"], s["ambitious"]["night_duration_s"])

    def test_gear_hint_points_to_equipment_check(self):
        self.assertIn("equipment --race-plan", self.night["night"]["gear_hint"])

    def test_cutoffs_use_penalised_times(self):
        plan = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ,
                                  **_kwargs(aid_stations=[{"km": 80.0, "name": "R", "cutoff": "+00:00"}]))
        base = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00",
                                  **_kwargs(aid_stations=[{"km": 80.0, "name": "R", "cutoff": "+00:00"}]))
        self.assertLess(plan["cutoffs"][0]["realistic"]["margin_s"], base["cutoffs"][0]["realistic"]["margin_s"])

    def test_plan_json_serialisable(self):
        json.dumps(self.night)


class TestNightUnavailableOrDaylight(unittest.TestCase):
    def setUp(self):
        self.pts = _ultra_pts()
        self.base = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", **_kwargs())

    def _same_as_base(self, plan):
        for key in ("segments", "totals", "segment_passages", "aid_station_passages", "cutoffs"):
            self.assertEqual(plan[key], self.base[key], key)

    def test_missing_timezone(self):
        plan = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", **_kwargs())
        self.assertEqual(plan["night"]["status"], "unavailable")
        self.assertEqual(plan["night"]["reason"], "no_timezone")
        self.assertIn("--tz", plan["night"]["note"])
        self.assertEqual(plan["warnings"], self.base["warnings"])

    def test_start_time_not_explicit(self):
        plan = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ,
                                  start_time_known=False, **_kwargs())
        self.assertEqual(plan["night"]["reason"], "no_start_time")
        self._same_as_base(plan)

    def test_missing_race_date(self):
        plan = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ, **_kwargs(race_date=None))
        self.assertEqual(plan["night"]["reason"], "no_race_date")

    def test_disabled(self):
        plan = RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz=TZ, night_enabled=False,
                                  **_kwargs())
        self.assertEqual(plan["night"]["status"], "disabled")
        self._same_as_base(plan)

    def test_unknown_timezone_raises(self):
        with self.assertRaises(ValueError):
            RP.build_race_plan(self.pts, PERSONAL_BINS, start_time="16:00", tz="Nowhere/Land", **_kwargs())

    def test_daylight_race_has_no_night_fields_and_identical_times(self):
        pts = _straight_course(_ClimbFlatDescentProfile())
        kw = _kwargs(aid_stations=[])
        base = RP.build_race_plan(pts, PERSONAL_BINS, start_time="09:00", **kw)
        plan = RP.build_race_plan(pts, PERSONAL_BINS, start_time="09:00", tz=TZ, **kw)
        self.assertEqual(plan["night"]["status"], "daylight")
        for key in ("segments", "totals", "segment_passages"):
            self.assertEqual(plan[key], base[key], key)
        for seg in plan["segments"]:
            self.assertNotIn("night_fraction", seg)
        self.assertIn("frontale non requise", plan["night"]["scenarios"]["realistic"]["summary"])

    def test_cli_rejects_out_of_range_options(self):
        with self.assertRaises(ValueError):
            RP._validate_night_pct(-1.0, 5.0, "--night-penalty-pct")
        with self.assertRaises(ValueError):
            RP._validate_night_pct(float("nan"), 5.0, "--night-penalty-pct")
        self.assertEqual(RP._validate_night_pct(None, 5.0, "x"), 5.0)


class _RollingProfile:
    """Montées/descentes à 6 % sur 10 km, en boucle (ultra de ~30 h)."""

    def __init__(self, total_m):
        self.total_m = total_m

    def __call__(self, d):
        x = d % 20000.0
        return 1000.0 + (x * 0.06 if x <= 10000.0 else 600.0 - (x - 10000.0) * 0.06)


def _long_pts(total_m, lat=-40.0, lon=-140.0, step_m=100.0):
    """Trace rectiligne fictive (zone conventionnelle du dépôt, jamais un parcours réel)."""
    m_per_deg = 111320.0 * math.cos(math.radians(lat))
    prof = _RollingProfile(total_m)
    return [{"lat": lat, "lon": lon + i * step_m / m_per_deg, "ele": prof(min(i * step_m, total_m))}
            for i in range(int(total_m / step_m) + 1)]


def _long_kwargs(total_km, **over):
    kw = dict(aid_stations=[{"km": float(k), "name": f"R{k}", "stop_s": 600} for k in range(20, total_km, 20)],
              fade_pct=4.0, temp_max_c=None, acclimated=None, intensity_factor=1.0,
              intensity_source="riegel", segment_m=750.0)
    kw.update(over)
    return kw


class TestNightClockMultiDayAndDst(unittest.TestCase):
    """Revue #184 : horloge absolue (UTC) à travers minuit, deux nuits et le changement d'heure."""

    @classmethod
    def setUpClass(cls):
        cls.pts = _long_pts(250000.0)
        # Zone fictive (lon -140 ≈ UTC-9,3 solaire) : fuseau à changement d'heure plausible pour
        # cette longitude = America/Anchorage (01/11/2026 02:00 AKDT UTC-8 -> 01:00 AKST UTC-9).
        # Départ 18:00 la veille au soir : la course traverse le changement d'heure.
        cls.dst = RP.build_race_plan(cls.pts, PERSONAL_BINS, start_time="18:00", race_date="2026-10-31",
                                       tz=DST_TZ, **_long_kwargs(250))
        # Même instant de départ, fuseau FIXE UTC-8 : le temps écoulé doit être identique.
        cls.fixed = RP.build_race_plan(cls.pts, PERSONAL_BINS, start_time="18:00", race_date="2026-10-31",
                                       tz="Etc/GMT+8", **_long_kwargs(250))

    def test_dst_change_does_not_shift_the_elapsed_clock(self):
        for key in ("segments", "totals", "segment_passages"):
            self.assertEqual(self.dst[key], self.fixed[key], key)
        for s in RP.SCENARIOS:
            self.assertEqual(self.dst["night"]["scenarios"][s]["night_duration_s"],
                             self.fixed["night"]["scenarios"][s]["night_duration_s"])

    def test_local_display_follows_the_dst_offset(self):
        safe_dst = self.dst["night"]["scenarios"]["safe"]
        safe_fixed = self.fixed["night"]["scenarios"]["safe"]
        # Fin de la 1re nuit : même instant, affiché 04:3x en AKST (UTC-9) et 05:3x en UTC-8.
        self.assertIn("à 04:3", safe_dst["summary"])
        self.assertIn("à 05:3", safe_fixed["summary"])
        self.assertTrue(safe_dst["lamp_from"].endswith("-08:00"))
        self.assertTrue(safe_dst["lamp_until"].endswith("-09:00"))

    def test_thirty_hour_race_crosses_two_nights(self):
        safe = self.dst["night"]["scenarios"]["safe"]
        self.assertGreater(self.dst["totals"]["time_s"]["safe"], 26 * 3600)
        self.assertEqual(safe["summary"].count(" à "), 2, safe["summary"])  # deux fenêtres de nuit
        self.assertIn("(J+1); ", safe["summary"])
        fractions = [seg["night_fraction"]["safe"] for seg in self.dst["segments"]]
        states = []
        for f in fractions:  # jour -> nuit -> jour -> nuit
            st = "N" if f > 0.99 else ("D" if f < 0.01 else None)
            if st and (not states or states[-1] != st):
                states.append(st)
        self.assertEqual(states[:4], ["D", "N", "D", "N"])
        self.assertTrue(self.dst["night"]["converged"])
        for seg in self.dst["segments"]:
            t = seg["predicted_time_s"]
            self.assertGreaterEqual(t["safe"], t["realistic"])
            self.assertGreaterEqual(t["realistic"], t["ambitious"])

    def test_no_timezone_warning_for_a_plausible_zone(self):
        self.assertNotIn("timezone_warning", self.dst["night"])


class TestTimezonePlausibility(unittest.TestCase):
    def test_far_off_zone_warns_without_refusing(self):
        pts = _long_pts(20000.0)
        plan = RP.build_race_plan(pts, PERSONAL_BINS, start_time="18:00", race_date="2026-10-24",
                                  tz="America/New_York", **_long_kwargs(20))  # UTC-4 pour lon -140
        self.assertIn("timezone_warning", plan["night"])
        self.assertIn("America/New_York", plan["night"]["timezone_warning"])
        self.assertIn(plan["night"]["timezone_warning"], plan["warnings"])

    def test_wraparound_near_the_date_line(self):
        start = datetime(2026, 6, 20, 8, 0, tzinfo=S.resolve_timezone("Pacific/Kiritimati"))  # UTC+14
        self.assertIsNone(RP.timezone_plausibility_warning(start, -157.4, "Pacific/Kiritimati"))
        start = datetime(2026, 6, 20, 8, 0, tzinfo=S.resolve_timezone("Europe/Paris"))
        self.assertIsNotNone(RP.timezone_plausibility_warning(start, -61.0, "Europe/Paris"))  # Antilles

    def test_short_night_is_summarised_in_minutes(self):
        start = datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc)
        mask = S.NightMask(start, start + timedelta(hours=2), -40.0, -140.0)
        ref = mask.night_windows(start, start + timedelta(hours=2))
        if not ref:  # garde : ce cas doit bien contenir une courte nuit
            self.skipTest("pas de nuit dans la fenêtre de référence")
        first = ref[0][0]
        end_s = (first - start).total_seconds() + 120.0
        info = RP.night_scenario_summary(mask, start, end_s, timezone.utc)
        self.assertIn("2 min de nuit", info["summary"])


class TestByteIdenticalWithoutNight(unittest.TestCase):
    def test_plan_without_night_matches_pre_184_fingerprint(self):
        plan = RP.build_race_plan(_ultra_pts(), PERSONAL_BINS, **_golden_kwargs())
        self.assertEqual(plan["night"]["status"], "unavailable")
        plan.pop("assumptions")
        plan.pop("night")
        plan.pop("altitude")   # clé additive (#185) : parcours sous 1 500 m, aucun effet
        text = json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), GOLDEN_NO_NIGHT_SHA256)

    def test_assumptions_document_the_night_model(self):
        text = RP.ASSUMPTIONS["night"]
        for needle in ("--tz", "approximation", "NIGHT_BASE_PENALTY_PCT", "arc_solar"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
