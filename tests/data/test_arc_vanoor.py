"""Palier D — `scripts/arc_vanoor.py` : validation des étapes contre les limites du format
`vanoor.workout/1`, rattachement à la semaine planifiée, plan de course par segment, opt-in
`[vanoor].export` et dossier de sortie. Données synthétiques, aucun appel réseau."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_vanoor as V  # noqa: E402

WEEK = {
    "arc": 1, "kind": "week", "week_start": "2030-03-04",
    "sessions": [
        {"date": "2030-03-04", "sport": "strength", "title": "Gainage", "planned_duration_s": 1200,
         "intensity": "strength", "status": "planned"},
        {"date": "2030-03-05", "sport": "running", "title": "Endurance 40 min", "planned_duration_s": 2400,
         "intensity": "endurance", "status": "planned"},
        {"date": "2030-03-07", "sport": "running", "title": "Fractionné", "planned_duration_s": 3000,
         "intensity": "vo2max", "status": "done"},
        {"date": "2030-03-09", "sport": "trail", "title": "Sortie longue", "planned_duration_s": 5400,
         "intensity": "endurance", "status": "planned"},
        {"date": "2030-03-09", "sport": "trail", "title": "Footing du soir", "planned_duration_s": 1800,
         "intensity": "recovery", "status": "planned"},
    ],
}

PLAN = {
    "segments": [
        {"id": "s01", "km_start": 0.0, "km_end": 1.2, "distance_m": 1200, "grade_mean_pct": 6.0,
         "predicted_time_s": {"realistic": 720, "ambitious": 660}, "pace_s_km": {"realistic": 600, "ambitious": 550}},
        {"id": "s02", "km_start": 1.2, "km_end": 3.0, "distance_m": 1800, "grade_mean_pct": -0.5,
         "predicted_time_s": {"realistic": 720, "ambitious": 650}, "pace_s_km": {"realistic": 400, "ambitious": 361}},
        {"id": "s03", "km_start": 3.0, "km_end": 4.0, "distance_m": 1000, "grade_mean_pct": -6.0,
         "predicted_time_s": {"realistic": 330, "ambitious": 300}, "pace_s_km": {"realistic": 330, "ambitious": 300}},
    ],
    "aid_stations": [{"km": 2.5, "name": "Le Col"}],
}

ENDURANCE = {"type": "split", "label": "Endurance", "duration": 2400, "target": "hr_range",
             "minBpm": 130, "maxBpm": 145}


def split(**kw):
    base = {"type": "split", "label": "Bloc", "duration": 600, "target": "open"}
    base.update(kw)
    return base


class TestSteps(unittest.TestCase):
    def test_valid_targets(self):
        steps = V.normalize_steps([
            split(target="conversational"),
            split(target="pace", secondsPerKm=300, toleranceSeconds=10),
            split(target="hr_zone", zone=2),
            ENDURANCE,
            {"type": "repeat", "count": 4, "steps": [
                {"type": "split", "label": "Vite", "distance": 400, "target": "pace", "secondsPerKm": 240},
                split(label="Trot", duration=90)]},
            {"type": "nutrition", "trigger": "elapsed", "seconds": 2700,
             "items": [{"name": "gel", "quantity": 1, "unit": "pcs"}]},
        ], "t")
        self.assertEqual(len(steps), 6)
        self.assertEqual(steps[4]["count"], 4)

    def test_pace_range_becomes_center_and_tolerance(self):
        step = V.normalize_split(split(target="pace", paceRange=[461, 417]), "t")
        self.assertEqual((step["secondsPerKm"], step["toleranceSeconds"]), (439, 22))
        self.assertNotIn("paceRange", step)

    def test_distance_xor_duration(self):
        with self.assertRaisesRegex(V.VanoorError, "jamais les deux"):
            V.normalize_split(split(distance=100), "t")
        with self.assertRaisesRegex(V.VanoorError, "jamais les deux"):
            V.normalize_split({"type": "split", "label": "x", "target": "open"}, "t")

    def test_limits(self):
        for bad, msg in (
            (split(target="pace", secondsPerKm=1300), "1200"),
            (split(duration=90000), "86400"),
            (split(target="hr_zone", zone=6), "zone"),
            (split(target="hr_range", minBpm=150, maxBpm=140), "inférieur"),
            (split(target="effort"), "target"),
            (split(label=" "), "label"),
        ):
            with self.subTest(msg=msg), self.assertRaisesRegex(V.VanoorError, msg):
                V.normalize_split(bad, "t")

    def test_repeat_rules(self):
        with self.assertRaisesRegex(V.VanoorError, "que des « split »"):
            V.normalize_steps([{"type": "repeat", "count": 2, "steps": [
                {"type": "nutrition", "trigger": "position", "items": [{"name": "eau", "quantity": 1, "unit": "sip"}]}]}],
                "t")
        with self.assertRaisesRegex(V.VanoorError, "30"):
            V.normalize_steps([{"type": "repeat", "count": 31, "steps": [split()]}], "t")
        with self.assertRaisesRegex(V.VanoorError, "max 20"):
            V.normalize_steps([{"type": "repeat", "count": 2, "steps": [split()] * 21}], "t")

    def test_step_cap(self):
        V.normalize_steps([split()] * 100, "t")
        with self.assertRaisesRegex(V.VanoorError, "101 étapes"):
            V.normalize_steps([split()] * 101, "t")

    def test_nutrition(self):
        with self.assertRaisesRegex(V.VanoorError, "unit"):
            V.normalize_nutrition({"trigger": "position", "items": [{"name": "gel", "quantity": 1, "unit": "x"}]}, "t")
        with self.assertRaisesRegex(V.VanoorError, "meters"):
            V.normalize_nutrition({"trigger": "distance", "items": [{"name": "gel", "quantity": 1, "unit": "pcs"}]}, "t")


class TestWeek(unittest.TestCase):
    def test_build_names_folder_and_order(self):
        request = {"sessions": [
            {"session": "2030-03-09:Sortie longue", "steps": [ENDURANCE]},
            {"session": "2030-03-05", "steps": [ENDURANCE]},
        ]}
        doc, missing = V.build_week(WEEK, request, "fr")
        self.assertEqual([w["name"] for w in doc["workouts"]],
                         ["Mar 05/03 · Endurance 40 min", "Sam 09/03 · Sortie longue"])
        self.assertEqual({w["folder"] for w in doc["workouts"]}, {"Semaine du 04/03"})
        # La séance déjà faite et le renforcement ne sont jamais « manquants ».
        self.assertEqual(missing, [{"date": "2030-03-09", "title": "Footing du soir"}])
        self.assertEqual(V.validate_document(doc), [])

    def test_ambiguous_day_and_unknown_session(self):
        with self.assertRaisesRegex(V.VanoorError, "préciser @index"):
            V.build_week(WEEK, {"sessions": [{"session": "2030-03-09", "steps": [ENDURANCE]}]}, "fr")
        with self.assertRaisesRegex(V.VanoorError, "absente"):
            V.build_week(WEEK, {"sessions": [{"session": "2030-03-06", "steps": [ENDURANCE]}]}, "fr")
        doc, _ = V.build_week(WEEK, {"sessions": [{"session": "2030-03-09@1", "steps": [ENDURANCE]}]}, "fr")
        self.assertEqual(doc["workouts"][0]["name"], "Sam 09/03 · Footing du soir")

    def test_non_running_and_duplicates_refused(self):
        with self.assertRaisesRegex(V.VanoorError, "strength"):
            V.build_week(WEEK, {"sessions": [{"session": "2030-03-04", "steps": [ENDURANCE]}]}, "fr")
        with self.assertRaisesRegex(V.VanoorError, "deux fois"):
            V.build_week(WEEK, {"sessions": [{"session": "2030-03-05", "steps": [ENDURANCE]},
                                             {"session": "2030-03-05", "steps": [ENDURANCE]}]}, "fr")

    def test_english_labels(self):
        doc, _ = V.build_week(WEEK, {"sessions": [{"session": "2030-03-05", "steps": [ENDURANCE]}]}, "en")
        self.assertEqual(doc["workouts"][0]["name"], "Tue 05/03 · Endurance 40 min")
        self.assertEqual(doc["workouts"][0]["folder"], "Week of 04/03")


class TestRace(unittest.TestCase):
    def test_one_step_per_segment_and_aid_reminder(self):
        doc, warnings = V.build_race(PLAN, "Trail test", ["realistic", "ambitious"], "fr")
        self.assertEqual(warnings, [])
        self.assertEqual([w["name"] for w in doc["workouts"]],
                         ["Trail test · réaliste 0h29", "Trail test · ambitieux 0h26"])
        steps = doc["workouts"][0]["steps"]
        self.assertEqual([s["label"] for s in steps[:3]],
                         ["Montée km 0,0-1,2", "Roulant km 1,2-3,0", "Descente km 3,0-4,0"])
        self.assertEqual([s["toleranceSeconds"] for s in steps[:3]], [30, 20, 20])
        self.assertEqual(steps[1]["secondsPerKm"], 400)
        self.assertEqual(steps[3], {"type": "nutrition", "trigger": "distance", "meters": 2500,
                                    "items": [{"name": "Ravito Le Col", "quantity": 1, "unit": "pcs"}]})
        self.assertEqual(V.validate_document(doc), [])

    def test_pace_out_of_bounds_becomes_by_feel(self):
        plan = {"segments": [dict(PLAN["segments"][0], pace_s_km={"realistic": 1500})]}
        doc, warnings = V.build_race(plan, "Ultra", ["realistic"], "fr")
        step = doc["workouts"][0]["steps"][0]
        self.assertEqual(step["target"], "conversational")
        self.assertIn("marche", step["label"])
        self.assertEqual(len(warnings), 1)

    def test_plan_without_segments(self):
        with self.assertRaisesRegex(V.VanoorError, "sans segments"):
            V.build_race({"segments": []}, "X", ["realistic"], "fr")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Résolu : sous macOS, /var est un lien vers /private/var et le script résout le workspace.
        self.ws = Path(self.tmp.name).resolve()
        (self.ws / "planning").mkdir()
        (self.ws / "config").mkdir()
        (self.ws / "planning/Semaine_2030-03-04.md").write_text(
            "# Semaine\n\n```arc\n" + json.dumps(WEEK) + "\n```\n", encoding="utf-8")
        (self.ws / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, body: str) -> None:
        (self.ws / "config/workspace.user.toml").write_text(body, encoding="utf-8")

    def run_cli(self, *argv, stdin: str = ""):
        out = io.StringIO()
        fake_stdin = io.StringIO(stdin)
        fake_stdin.isatty = lambda: False
        with patch.object(sys, "stdin", fake_stdin), redirect_stdout(out):
            code = V.main(["--workspace", str(self.ws), *argv])
        return code, json.loads(out.getvalue())

    def week_request(self) -> str:
        return json.dumps({"sessions": [{"session": "2030-03-05", "steps": [ENDURANCE]}]})

    def test_disabled_by_default_writes_nothing(self):
        code, out = self.run_cli("week", "--week", "planning/Semaine_2030-03-04.md", stdin=self.week_request())
        self.assertEqual((code, out["status"]), (2, "disabled"))
        self.assertFalse((self.ws / "exports").exists())

    def test_dry_run_allowed_when_disabled(self):
        code, out = self.run_cli("week", "--week", "planning/Semaine_2030-03-04.md", "--dry-run",
                                 stdin=self.week_request())
        self.assertEqual((code, out["status"]), (0, "dry_run"))
        self.assertEqual(out["document"]["schema"], V.SCHEMA)
        self.assertFalse((self.ws / "exports").exists())

    def test_unknown_value_is_off(self):
        self.config('[vanoor]\nexport = "yes"\n')
        code, _ = self.run_cli("week", "--week", "planning/Semaine_2030-03-04.md", stdin=self.week_request())
        self.assertEqual(code, 2)

    def test_writes_to_default_dir(self):
        self.config('[vanoor]\nexport = "on"\n')
        code, out = self.run_cli("week", "--week", "planning/Semaine_2030-03-04.md", stdin=self.week_request())
        self.assertEqual((code, out["status"]), (0, "written"))
        path = self.ws / "exports/vanoor/weeks/semaine-2030-03-04.vanoor"
        self.assertEqual(Path(out["path"]), path)
        self.assertEqual(V.validate_document(json.loads(path.read_text(encoding="utf-8"))), [])
        self.assertEqual([m["title"] for m in out["missing"]], ["Sortie longue", "Footing du soir"])

    def test_writes_to_configured_dir(self):
        self.config('[vanoor]\nexport = "on"\noutput_dir = "sync/Vanoor"\n')
        code, out = self.run_cli("race", "--plan", "plan.json", "--name", "Trail des Écureuils",
                                 "--race-date", "2030-04-01", "--scenario", "realistic")
        self.assertEqual(code, 0)
        self.assertEqual(Path(out["path"]), self.ws / "sync/Vanoor/races/course-2030-04-01-trail-des-ecureuils.vanoor")
        self.assertEqual(len(out["workouts"]), 1)

    def test_errors_are_reported_not_raised(self):
        self.config('[vanoor]\nexport = "on"\n')
        bad = json.dumps({"sessions": [{"session": "2030-03-05", "steps": [split(target="pace")]}]})
        code, out = self.run_cli("week", "--week", "planning/Semaine_2030-03-04.md", stdin=bad)
        self.assertEqual((code, out["status"]), (1, "error"))
        self.assertIn("secondsPerKm", out["error"])
        code, out = self.run_cli("week", "--week", "planning/Semaine_2030-03-04.md", stdin="")
        self.assertEqual(code, 1)

    def test_validate(self):
        good = self.ws / "ok.vanoor"
        good.write_text(json.dumps({"schema": V.SCHEMA, "workouts": [{"name": "x", "steps": [ENDURANCE]}]}),
                        encoding="utf-8")
        self.assertEqual(self.run_cli("validate", str(good))[0], 0)
        bad = self.ws / "bad.vanoor"
        bad.write_text(json.dumps({"schema": "autre", "workouts": []}), encoding="utf-8")
        code, out = self.run_cli("validate", str(bad))
        self.assertEqual((code, out["status"]), (1, "invalid"))


if __name__ == "__main__":
    unittest.main()
