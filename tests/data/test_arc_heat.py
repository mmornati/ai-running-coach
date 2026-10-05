"""Palier D — chaleur : coefficients partagés et cibles de séance ajustées (#171).

Familles de tests :
- Source unique : `arc_race_pacing` ré-exporte les constantes/fonctions de
  `arc_heat` (mêmes objets), et le pacing de course reste identique (valeurs
  figées AVANT la refonte).
- `heat_adjustment` : table par type de séance / température / acclimatation,
  🔴 -> déplacer ou alléger, FC jamais touchée, humidité absente -> repli dit.
- `apply_heat` / CLI `targets --heat` : allure ralentie, trace conforme au
  contrat `arc`, météo lue depuis l'index.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_contract as C  # noqa: E402
import arc_heat as H  # noqa: E402
import arc_race_pacing as RP  # noqa: E402
import arc_workout_targets as T  # noqa: E402


class TestSharedCoefficients(unittest.TestCase):
    def test_race_pacing_reuses_arc_heat_objects(self):
        self.assertIs(RP.heat_time_factor, H.heat_time_factor)
        for name in ("HEAT_HOT_C", "HEAT_COLD_C", "HEAT_HOT_TIME_FACTOR", "HEAT_COLD_TIME_FACTOR",
                     "HEAT_UNACCLIMATED_EXTRA_FACTOR", "HEAT_ACCLIMATION_MIN_HOT_SESSIONS"):
            self.assertEqual(getattr(RP, name), getattr(H, name), name)

    def test_race_pacing_heat_factor_unchanged(self):
        """Valeurs figées AVANT la refonte (#171) : la course ne bouge pas."""
        self.assertEqual(RP.heat_time_factor(None)[0], 1.0)
        self.assertEqual(RP.heat_time_factor(25.0)[0], 1.0)          # borne exclue
        self.assertAlmostEqual(RP.heat_time_factor(25.1)[0], 1.10)
        self.assertAlmostEqual(RP.heat_time_factor(30.0, acclimated=False)[0], 1.10 * 1.05)
        self.assertAlmostEqual(RP.heat_time_factor(30.0, acclimated=True)[0], 1.10)
        self.assertAlmostEqual(RP.heat_time_factor(4.9)[0], 1.05)    # froid : course seulement
        self.assertEqual(RP.heat_time_factor(5.0)[0], 1.0)
        factor, notes = RP.heat_time_factor(30.0, acclimated=False)
        self.assertEqual(len(notes), 2)
        self.assertIn("chaleur prévue (30 °C > 25 °C) : temps × 1.1 (approximation du projet)", notes[0])

    def test_assumption_heat_of_race_pacing_still_present(self):
        self.assertIn("temps × 1.10", RP.ASSUMPTIONS["heat"])
        self.assertIn("heat_training", H.ASSUMPTIONS)
        self.assertIn("10.1249/mss.0b013e31802d3aba", H.ASSUMPTIONS["heat_training"])


class TestClassify(unittest.TestCase):
    def test_types(self):
        run = {"sport": "running", "outdoor": True}
        self.assertEqual(H.classify_session({**run, "intensity": "endurance", "planned_duration_s": 2700}), "easy")
        self.assertEqual(H.classify_session({**run, "intensity": "endurance", "planned_duration_s": 5400}), "long")
        self.assertEqual(H.classify_session({**run, "intensity": "recovery"}), "easy")
        for intensity in ("tempo", "threshold", "vo2max"):
            self.assertEqual(H.classify_session({**run, "intensity": intensity}), "quality")
        self.assertEqual(H.classify_session({**run, "intensity": "race"}), "race_pace")

    def test_untouched_sessions(self):
        self.assertEqual(H.classify_session({"sport": "strength", "intensity": "strength"}), "none")
        self.assertEqual(H.classify_session({"sport": "indoor_cycling", "intensity": "endurance"}), "none")
        self.assertEqual(H.classify_session({"sport": "running", "intensity": "vo2max", "outdoor": False}), "none")
        self.assertEqual(H.classify_session({"sport": "running"}), "none")


class TestCategory(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(H.category_from_temp(22.0), "green")
        self.assertEqual(H.category_from_temp(22.1), "yellow")
        self.assertEqual(H.category_from_temp(28.0), "yellow")
        self.assertEqual(H.category_from_temp(28.1), "orange")
        self.assertEqual(H.category_from_temp(32.0), "orange")
        self.assertEqual(H.category_from_temp(32.1), "red")
        self.assertIsNone(H.category_from_temp(None))

    def test_dew_point(self):
        self.assertAlmostEqual(H.dew_point_c(30.0, 100.0), 30.0, places=1)
        self.assertAlmostEqual(H.dew_point_c(25.0, 50.0), 13.9, places=1)
        self.assertIsNone(H.dew_point_c(25.0, None))
        self.assertIsNone(H.dew_point_c(25.0, 0))


class TestOtherCategory(unittest.TestCase):
    def test_non_thermal_thresholds(self):
        self.assertIsNone(H.category_from_other(None))
        self.assertEqual(H.category_from_other({"wind_kmh": 10}), "green")
        self.assertEqual(H.category_from_other({"wind_kmh": 25}), "yellow")
        self.assertEqual(H.category_from_other({"wind_kmh": 40}), "orange")
        self.assertEqual(H.category_from_other({"wind_kmh": 55}), "red")
        self.assertEqual(H.category_from_other({"precip_mm": 20}), "red")
        self.assertEqual(H.category_from_other({"uv_index": 9}), "orange")
        self.assertEqual(H.category_from_other({"thunderstorm": True}), "red")


class TestHeatAdjustment(unittest.TestCase):
    def test_cool_day_no_change(self):
        for stype in ("easy", "long", "quality", "race_pace"):
            adj = H.heat_adjustment(stype, temp_c=18.0)
            self.assertFalse(adj["applies"], stype)
            self.assertEqual(adj["factor"], 1.0)
            self.assertEqual(adj["action"], "none")

    def test_exactly_threshold_is_not_hot(self):
        self.assertFalse(H.heat_adjustment("easy", temp_c=25.0)["applies"])

    def test_cold_is_out_of_scope(self):
        adj = H.heat_adjustment("easy", temp_c=2.0)
        self.assertFalse(adj["applies"])
        self.assertEqual(adj["factor"], 1.0)

    def test_none_type_untouched_even_at_red(self):
        adj = H.heat_adjustment("none", temp_c=40.0, category="red")
        self.assertFalse(adj["applies"])
        self.assertEqual(adj["action"], "none")

    def test_easy_and_long_slow_pace_keep_duration(self):
        for stype in ("easy", "long"):
            adj = H.heat_adjustment(stype, temp_c=27.0)
            self.assertTrue(adj["applies"])
            self.assertEqual(adj["action"], "slow_pace")
            self.assertAlmostEqual(adj["factor"], 1.10)
            self.assertTrue(adj["duration_kept"])
            self.assertTrue(adj["hr_target_unchanged"])
            self.assertIn("FC inchangée", adj["step_note"])

    def test_same_factor_as_race(self):
        for acclimated in (None, True, False):
            adj = H.heat_adjustment("easy", temp_c=29.0, acclimated=acclimated)
            self.assertAlmostEqual(adj["factor"], RP.heat_time_factor(29.0, acclimated=acclimated)[0], places=4)

    def test_unacclimated_extra(self):
        adj = H.heat_adjustment("easy", temp_c=27.0, acclimated=False)
        self.assertAlmostEqual(adj["factor"], 1.155, places=3)
        self.assertIn("acclimatation faible", adj["reason"])
        unknown = H.heat_adjustment("easy", temp_c=27.0, acclimated=None)
        self.assertAlmostEqual(unknown["factor"], 1.10)
        self.assertTrue(any("acclimatation inconnue" in n for n in unknown["notes"]))

    def test_quality_prefers_cool_slot_then_lowers_pace(self):
        mid = H.heat_adjustment("quality", temp_c=29.0, slot="midday")
        self.assertEqual(mid["action"], "prefer_cool_slot")
        self.assertTrue(mid["intensity_maintained"])
        self.assertTrue(any("créneau frais" in r for r in mid["recommendations"]))
        morning = H.heat_adjustment("quality", temp_c=27.0, slot="morning")
        self.assertEqual(morning["action"], "lower_pace_targets")
        self.assertAlmostEqual(morning["factor"], 1.10)

    def test_red_quality_never_maintained(self):
        for stype in ("quality", "race_pace"):
            adj = H.heat_adjustment(stype, temp_c=34.0, slot="midday")
            self.assertEqual(adj["category"], "red")
            self.assertEqual(adj["action"], "reschedule_or_lighten")
            self.assertFalse(adj["intensity_maintained"])
            self.assertEqual(adj["lightened_intensity"], "endurance")
            self.assertIn("🔴", adj["reason"])

    def test_red_from_provided_category_at_mild_temperature(self):
        adj = H.heat_adjustment("quality", temp_c=20.0, category="red")   # ex. orage
        self.assertTrue(adj["applies"])
        self.assertEqual(adj["action"], "reschedule_or_lighten")
        self.assertEqual(adj["factor"], 1.0)

    def test_red_easy_reschedules_or_indoor(self):
        adj = H.heat_adjustment("easy", temp_c=35.0)
        self.assertEqual(adj["action"], "reschedule_or_indoor")

    def test_worst_category_wins(self):
        self.assertEqual(H.heat_adjustment("easy", temp_c=26.0, category="orange")["category"], "orange")
        self.assertEqual(H.heat_adjustment("easy", temp_c=30.0, category="green")["category"], "orange")

    def test_feels_like_replaces_temperature_when_higher(self):
        adj = H.heat_adjustment("easy", temp_c=24.0, feels_like_c=27.0)
        self.assertTrue(adj["applies"])
        self.assertEqual(adj["temp_c"], 27.0)
        self.assertEqual(adj["temp_basis"], "feels_like")
        lower = H.heat_adjustment("easy", temp_c=27.0, feels_like_c=24.0)
        self.assertEqual(lower["temp_basis"], "temperature")

    def test_humidity_absent_falls_back_and_says_so(self):
        adj = H.heat_adjustment("easy", temp_c=28.0)
        self.assertIsNone(adj["dew_point_c"])
        self.assertTrue(any("température seule" in n for n in adj["notes"]))
        with_h = H.heat_adjustment("easy", temp_c=28.0, humidity_pct=70.0)
        self.assertIsNotNone(with_h["dew_point_c"])
        self.assertEqual(with_h["factor"], adj["factor"])   # informatif : aucune correction

    def test_no_weather_no_adjustment(self):
        adj = H.heat_adjustment("quality", temp_c=None)
        self.assertFalse(adj["applies"])
        self.assertEqual(adj["factor"], 1.0)

    def test_hydration_links_sweat_rate(self):
        adj = H.heat_adjustment("long", temp_c=30.0, sweat_rate_l_h=0.9)
        hyd = adj["hydration"]
        self.assertTrue(hyd["sodium_reminder"])
        self.assertEqual(hyd["sweat_rate_l_h"], 0.9)
        self.assertEqual(hyd["multiplier"], H.HYDRATION_ORANGE_MULTIPLIER)
        self.assertEqual(hyd["long_min_l_h"], H.HYDRATION_LONG_MIN_L_H)
        self.assertIn("0.9 L/h", hyd["text"])
        mild = H.heat_adjustment("easy", temp_c=26.0)["hydration"]
        self.assertIsNone(mild["multiplier"])
        self.assertIsNone(mild["sweat_rate_l_h"])

    def test_pace_helpers(self):
        self.assertAlmostEqual(H.slow_pace_s_km(300.0, 1.1), 330.0)
        self.assertAlmostEqual(H.slow_speed_ms(3.3, 1.1), 3.0)
        self.assertIsNone(H.slow_pace_s_km(None, 1.1))
        self.assertIsNone(H.slow_speed_ms(0, 1.1))


class TestApplyHeat(unittest.TestCase):
    def _result(self):
        return {"intensity": "endurance", "sport": "running",
                "hr_target": {"bounds_bpm": [134, 148], "zone": 2},
                "pace_target": {"speed_low_ms": 2.85, "speed_high_ms": 3.15,
                                "pace_low_s_km": 317.5, "pace_high_s_km": 350.9},
                "hill_repeats": None}

    def test_hr_unchanged_pace_slowed(self):
        session = {"sport": "running", "intensity": "endurance", "planned_duration_s": 2700, "outdoor": True}
        res = T.apply_heat(self._result(), session, temp_c=28.0)
        self.assertEqual(res["hr_target"], {"bounds_bpm": [134, 148], "zone": 2})
        adj = res["pace_target"]["adjusted"]
        self.assertAlmostEqual(adj["speed_low_ms"], 2.85 / 1.10)
        self.assertAlmostEqual(adj["speed_high_ms"], 3.15 / 1.10)
        self.assertGreater(adj["pace_high_s_km"], res["pace_target"]["pace_high_s_km"])   # plus lent
        self.assertLessEqual(adj["speed_low_ms"], adj["speed_high_ms"])
        self.assertEqual(res["pace_target"]["speed_low_ms"], 2.85)   # cible d'origine intacte

    def test_cool_day_has_no_adjusted_and_no_trace(self):
        session = {"sport": "running", "intensity": "endurance", "outdoor": True}
        res = T.apply_heat(self._result(), session, temp_c=15.0)
        self.assertNotIn("adjusted", res["pace_target"])
        self.assertNotIn("trace", res)

    def test_red_quality_drops_pace_and_traces(self):
        session = {"sport": "running", "intensity": "vo2max", "outdoor": True}
        res = T.apply_heat({"hr_target": {}, "pace_target": {}, "hill_repeats": None}, session,
                           temp_c=34.0, declared_pace_s_km=240.0, slot="midday", category="red")
        self.assertIsNone(res["declared_pace"]["adjusted_pace_s_km"])
        trace = res["trace"]["heat_adjustment"]
        self.assertEqual(trace["action"], "reschedule_or_lighten")
        self.assertEqual(trace["category"], "red")

    def test_declared_pace_slowed_for_quality(self):
        session = {"sport": "running", "intensity": "threshold", "outdoor": True}
        res = T.apply_heat({"hr_target": {}, "pace_target": {}}, session, temp_c=27.0,
                           declared_pace_s_km=270.0, slot="morning")
        self.assertAlmostEqual(res["declared_pace"]["adjusted_pace_s_km"], 297.0)

    def test_trace_matches_contract(self):
        session = {"sport": "running", "intensity": "endurance", "outdoor": True}
        res = T.apply_heat(self._result(), session, temp_c=28.0, acclimated=False, slot="midday",
                           humidity_pct=60.0)
        week = {"arc": 1, "kind": "week", "week_start": "2026-09-28", "location": "Tournai",
                "sessions": [{"date": "2026-09-30", "sport": "running", "title": "Footing",
                              "intensity": "endurance", "heat_adjustment": res["trace"]["heat_adjustment"]}]}
        errors, warnings = C.validate(week)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_contract_rejects_bad_heat_action(self):
        week = {"arc": 1, "kind": "week", "week_start": "2026-09-28", "location": "Tournai",
                "sessions": [{"date": "2026-09-30", "sport": "running", "title": "x",
                              "heat_adjustment": {"factor": 1.1, "temp_c": 28, "action": "bogus"}}]}
        errors, _ = C.validate(week)
        self.assertTrue(errors)


class TestCliHeat(unittest.TestCase):
    def _workspace(self, tmp: str, *, category="red", tmax=34.0) -> Path:
        ws = Path(tmp)
        (ws / "planning").mkdir(parents=True)
        (ws / "medical").mkdir()
        (ws / "planning" / "Runner_Profile.md").write_text(
            "# Profil de l'athlète\n\n## Physiologie\n\n"
            "- **FC max** : 190\n- **FC de repos de référence** : 50\n", encoding="utf-8")
        (ws / "medical" / "2026-09-30_meteo.md").write_text(
            "# Météo\n\n```arc\n" + json.dumps({
                "arc": 1, "kind": "weather", "date": "2026-09-30", "location": "Tournai", "category": category,
                "temp_min_c": 20, "temp_max_c": tmax, "humidity_pct": 55, "best_slot": "morning"}) + "\n```\n",
            encoding="utf-8")
        return ws

    def _run(self, ws: Path, *extra: str) -> dict:
        out = io.StringIO()
        with redirect_stdout(out):
            code = T.main(["targets", "--heat", "--workspace", str(ws), "--memory", "--today", "2026-09-30", *extra])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_red_day_vma_is_moved_or_lightened(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            res = self._run(ws, "--slot", "midday", "--session", json.dumps(
                {"date": "2026-09-30", "sport": "running", "title": "VMA", "intensity": "vo2max", "outdoor": True}))
            adj = res["heat_adjustment"]
            self.assertEqual(adj["action"], "reschedule_or_lighten")
            self.assertFalse(adj["intensity_maintained"])
            self.assertEqual(adj["category"], "red")
            self.assertEqual(adj["temp_c"], 34.0)
            self.assertEqual(adj["slot"], "midday")
            self.assertEqual(res["trace"]["heat_adjustment"]["action"], "reschedule_or_lighten")

    def test_morning_slot_uses_min_temperature_and_ignores_day_category(self):
        """Jour 🔴 à midi (34 °C) mais créneau matin à 20 °C : pas d'ajustement."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            res = self._run(ws, "--slot", "morning", "--session", json.dumps(
                {"date": "2026-09-30", "sport": "running", "title": "VMA", "intensity": "vo2max",
                 "outdoor": True}))
            self.assertEqual(res["heat_adjustment"]["temp_c"], 20.0)
            self.assertFalse(res["heat_adjustment"]["applies"])
            self.assertNotIn("trace", res)

    def test_non_thermal_red_from_weather_file_still_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            (ws / "medical" / "2026-09-30_meteo.md").write_text(
                "# Météo\n\n```arc\n" + json.dumps({
                    "arc": 1, "kind": "weather", "date": "2026-09-30", "location": "Tournai",
                    "category": "red", "temp_min_c": 15, "temp_max_c": 20, "thunderstorm": True}) + "\n```\n",
                encoding="utf-8")
            res = self._run(ws, "--session", json.dumps(
                {"date": "2026-09-30", "sport": "running", "title": "VMA", "intensity": "vo2max", "outdoor": True}))
            self.assertEqual(res["heat_adjustment"]["action"], "reschedule_or_lighten")

    def test_explicit_temp_overrides_and_hr_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            base = self._run(ws, "--session", json.dumps(
                {"date": "2026-09-30", "sport": "trail", "title": "Footing", "intensity": "endurance"}),
                "--temp-c", "27", "--category", "yellow")
            self.assertEqual(base["hr_target"]["bounds_bpm"], [134, 148])
            self.assertEqual(base["heat_adjustment"]["action"], "slow_pace")
            self.assertAlmostEqual(base["heat_adjustment"]["factor"], 1.10)

    def _weather(self, ws: Path, **fields) -> None:
        block = {"arc": 1, "kind": "weather", "date": "2026-09-30", "location": "Tournai", "category": "orange"}
        block.update(fields)
        (ws / "medical" / "2026-09-30_meteo.md").write_text(
            "# Météo\n\n```arc\n" + json.dumps(block) + "\n```\n", encoding="utf-8")

    def test_daily_feels_like_not_applied_to_morning_slot(self):
        """Revue de code #171 : le ressenti du fichier est journalier (proche du pic) — l'appliquer au
        créneau matin (évalué sur `temp_min_c`) annulerait le bénéfice du créneau frais."""
        session = json.dumps({"date": "2026-09-30", "sport": "running", "title": "Footing",
                              "intensity": "endurance", "outdoor": True})
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            self._weather(ws, temp_min_c=18, temp_max_c=30, feels_like_c=33)
            morning = self._run(ws, "--slot", "morning", "--session", session)["heat_adjustment"]
            self.assertEqual(morning["temp_c"], 18.0)
            self.assertFalse(morning["applies"])
            self.assertTrue(any("ressenti du jour non appliqué" in n for n in morning["notes"]))
            midday = self._run(ws, "--slot", "midday", "--session", session)["heat_adjustment"]
            self.assertEqual((midday["temp_c"], midday["temp_basis"]), (33.0, "feels_like"))
            explicit = self._run(ws, "--slot", "morning", "--feels-like-c", "27", "--session", session)
            self.assertEqual(explicit["heat_adjustment"]["temp_c"], 27.0)   # option explicite : appliquée

    def test_trace_omits_unknown_temperature(self):
        """🔴 dû au seul orage, sans température : `temp_c` omis de la trace (jamais 0 fictif)."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            self._weather(ws, category="red", thunderstorm=True)
            res = self._run(ws, "--session", json.dumps(
                {"date": "2026-09-30", "sport": "running", "title": "VMA", "intensity": "vo2max", "outdoor": True}))
            trace = res["trace"]["heat_adjustment"]
            self.assertNotIn("temp_c", trace)
            self.assertEqual(trace["action"], "reschedule_or_lighten")
            week = {"arc": 1, "kind": "week", "week_start": "2026-09-28", "location": "Tournai",
                    "sessions": [{"date": "2026-09-30", "sport": "running", "title": "VMA",
                                  "intensity": "vo2max", "heat_adjustment": trace}]}
            self.assertEqual(C.validate(week)[0], [])
            notes = res["heat_adjustment"]["notes"]
            self.assertFalse(any("humidité absente" in n for n in notes), notes)

    def test_without_heat_flag_output_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                T.main(["targets", "--workspace", str(ws), "--memory", "--session", json.dumps(
                    {"date": "2026-09-30", "sport": "trail", "title": "Footing", "intensity": "endurance"})])
            res = json.loads(out.getvalue())
            self.assertNotIn("heat_adjustment", res)
            self.assertNotIn("trace", res)


if __name__ == "__main__":
    unittest.main()
