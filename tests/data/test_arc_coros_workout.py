"""Palier D — séances COROS : construction des sections et validation avant poussée.

Familles de tests :
- `section` : FC en bpm entiers, vitesse m/s convertie en allure s/km (lente ->
  rapide), une seule cible de durée/distance/D+, une seule cible d'intensité.
- `validate_course` : la séance réellement poussée et relue le 2026-10-22 est
  valide ; règles du schéma (pas de durée en trail, pas de renforcement, groupes
  sans cible ni imbrication, un seul format d'intensité, bornes).
- CLI : `validate` rend 1 sur une séance invalide, `section` rend du JSON.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_coros_workout as W  # noqa: E402

# Séance poussée sur un compte réel puis relue à l'identique (queryScheduledWorkoutDetails).
PUSHED = {
    "sportType": 1, "courseName": "Endurance fondamentale 40 min + 4 lignes droites",
    "courseDescription": "40 min en aisance respiratoire, puis 4 lignes droites à la sensation.",
    "sections": [
        {"sectionType": 2, "targetType": 2, "targetValue": 2400,
         "intensityType": 1, "intensityValueStart": 137, "intensityValueEnd": 149},
        {"intervalGroup": True, "repeats": 4, "sets": [
            {"sectionType": 2, "targetType": 1, "targetValue": 100},
            {"sectionType": 3, "targetType": 2, "targetValue": 60}]},
    ],
}


def _course(sport=1, sections=None):
    return {"sportType": sport, "courseName": "Séance", "courseDescription": "Consigne.",
            "sections": sections or [W.section(duration_s=600, hr_bpm=[130, 140])]}


class TestSection(unittest.TestCase):
    def test_hr_section_rounds_and_orders_bounds(self):
        sec = W.section(duration_s=2400.4, hr_bpm=[149.4, 136.6])
        self.assertEqual(sec, {"sectionType": 2, "targetType": 2, "targetValue": 2400,
                               "intensityType": 1, "intensityValueStart": 137, "intensityValueEnd": 149})

    def test_speed_is_converted_to_pace_slow_then_fast(self):
        sec = W.section(distance_m=1000, speed_ms=[2.5, 2.2])
        self.assertEqual((sec["intensityValueStart"], sec["intensityValueEnd"]), (455, 400))
        self.assertEqual(sec["intensityType"], 2)

    def test_exactly_one_goal_and_one_intensity(self):
        with self.assertRaises(ValueError):
            W.section(duration_s=60, distance_m=100)
        with self.assertRaises(ValueError):
            W.section()
        with self.assertRaises(ValueError):
            W.section(duration_s=60, hr_bpm=[120, 130], speed_ms=[2.5, 3.0])

    def test_no_target_section_has_no_intensity_keys(self):
        sec = W.section(section_type="recovery", duration_s=60)
        self.assertEqual(sec, {"sectionType": 3, "targetType": 2, "targetValue": 60})

    def test_non_positive_speed_is_refused(self):
        with self.assertRaises(ValueError):
            W.speed_ms_to_pace_s_km(0)


class TestValidateCourse(unittest.TestCase):
    def test_pushed_session_is_valid(self):
        self.assertEqual(W.validate_course(PUSHED), [])

    def test_trail_refuses_time_target(self):
        errors = W.validate_course(_course(sport=5))
        self.assertTrue(any("targetType 2" in e for e in errors), errors)
        self.assertEqual(W.validate_course(_course(sport=5, sections=[
            W.section(climb_m=30, hr_bpm=[160, 170])])), [])

    def test_strength_is_not_pushable(self):
        self.assertTrue(W.validate_course(_course(sport=4)))

    def test_group_container_carries_no_target_and_no_nesting(self):
        group = {"intervalGroup": True, "repeats": 3, "targetType": 2,
                 "sets": [{"intervalGroup": True, "repeats": 2, "sets": []}]}
        errors = W.validate_course(_course(sections=[group]))
        self.assertTrue(any("groupe" in e for e in errors), errors)
        self.assertTrue(any("imbriqués" in e for e in errors), errors)

    def test_group_members_are_training_or_recovery_only(self):
        group = {"intervalGroup": True, "repeats": 2,
                 "sets": [W.section(section_type="warmup", duration_s=60)]}
        self.assertTrue(W.validate_course(_course(sections=[group])))

    def test_repeats_bounds(self):
        group = {"intervalGroup": True, "repeats": 21, "sets": [W.section(duration_s=60)]}
        self.assertTrue(any("repeats" in e for e in W.validate_course(_course(sections=[group]))))

    def test_one_intensity_format_only(self):
        sec = W.section(duration_s=600, hr_bpm=[130, 140])
        sec["sectionIntensity"] = 2
        self.assertTrue(any("exactement un format" in e for e in W.validate_course(_course(sections=[sec]))))

    def test_intensity_fields_need_intensity_type(self):
        sec = {"sectionType": 2, "targetType": 2, "targetValue": 600, "sectionIntensity": 2}
        self.assertTrue(W.validate_course(_course(sections=[sec])))

    def test_bounds_and_percent_order(self):
        hr = {"sectionType": 2, "targetType": 2, "targetValue": 600,
              "intensityType": 1, "intensityValueStart": 20, "intensityValueEnd": 140}
        pct = {"sectionType": 2, "targetType": 2, "targetValue": 600,
               "intensityType": 1, "intensityPercentStart": 90, "intensityPercentEnd": 85}
        self.assertTrue(W.validate_course(_course(sections=[hr])))
        self.assertTrue(W.validate_course(_course(sections=[pct])))

    def test_running_power_only_in_watts(self):
        sec = {"sectionType": 2, "targetType": 2, "targetValue": 600,
               "intensityType": 4, "sectionIntensity": 3}
        self.assertTrue(W.validate_course(_course(sections=[sec])))

    def test_effort_pace_pct_is_trail_only_and_never_absolute(self):
        sec = {"sectionType": 2, "targetType": 1, "targetValue": 1000,
               "intensityType": 3, "intensityValueStart": 300, "intensityValueEnd": 320}
        self.assertTrue(W.validate_course(_course(sport=1, sections=[sec])))
        self.assertTrue(W.validate_course(_course(sport=5, sections=[sec])))

    def test_free_mode_has_no_target_value(self):
        sec = {"sectionType": 1, "targetType": 4, "targetValue": 300}
        self.assertTrue(W.validate_course(_course(sections=[sec])))
        del sec["targetValue"]
        self.assertEqual(W.validate_course(_course(sections=[sec])), [])

    def test_course_level_fields_and_names(self):
        bad = dict(PUSHED, dayNo=0, courseName="x" * 101)
        errors = W.validate_course(bad)
        self.assertTrue(any("dayNo" in e for e in errors))
        self.assertTrue(any("courseName" in e for e in errors))


class TestCli(unittest.TestCase):
    def _run(self, argv, stdin=""):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out):
            code = W.main(argv)
        return code, out.getvalue()

    def test_validate_exit_codes(self):
        code, out = self._run(["validate"], json.dumps(PUSHED))
        self.assertEqual((code, json.loads(out)["valid"]), (0, True))
        code, out = self._run(["validate"], json.dumps(_course(sport=5)))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["valid"])

    def test_section_prints_json(self):
        code, out = self._run(["section", "--duration-s", "2400", "--hr", "137", "149"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["intensityValueEnd"], 149)


if __name__ == "__main__":
    unittest.main()


class TestThreshold(unittest.TestCase):
    def test_coros_threshold_pace_to_speed(self):
        # « Threshold Pace: 4:12 /km » relevé le 2026-10-22 = 252 s/km.
        self.assertEqual(W.pace_to_speed_ms("4:12 /km"), 3.968)
        self.assertEqual(W.pace_to_speed_ms("4:12"), 3.968)
        for bad in ("4.12", "", "0:30", "4:75", "25:00"):
            with self.assertRaises(ValueError):
                W.pace_to_speed_ms(bad)

    def test_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(W.main(["threshold", "--pace", "4:12"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"lt_speed_ms": 3.968, "pace_s_per_km": 252, "source": "COROS"})
