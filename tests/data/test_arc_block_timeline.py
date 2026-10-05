"""Palier D — frise du bloc (#193) : logique pure `arc_block_timeline` et `/api/block`."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_block_timeline as BT  # noqa: E402
import arc_plan_templates as PS  # noqa: E402
import arc_serve as S  # noqa: E402


def wk(start, phase=None, wtype=None, dur=None):
    return {"week_start": start, "phase": phase, "week_type": wtype, "target_duration_s": dur,
            "target_distance_m": None, "target_elevation_m": None}


class TestClassify(unittest.TestCase):
    def test_labels_match_skeleton(self):
        self.assertEqual(BT.PHASE_LABELS_FR, PS.PHASE_LABELS_FR)

    def test_known_ignoring_case_and_accents(self):
        self.assertEqual(BT.classify_phase("Affûtage"), "taper")
        self.assertEqual(BT.classify_phase("  developpement "), "development")
        self.assertEqual(BT.classify_phase("base"), "base")

    def test_free_text_is_never_guessed(self):
        self.assertEqual(BT.classify_phase("Base spécifique"), "other")
        self.assertEqual(BT.classify_phase(None), "unknown")
        self.assertEqual(BT.classify_phase("  "), "unknown")


class TestSelectBlock(unittest.TestCase):
    def test_run_containing_current_week(self):
        starts = ["2026-08-03", "2026-09-28", "2026-10-05", "2026-10-12"]
        self.assertEqual(BT.select_block(starts, date(2026, 10, 7)), ["2026-09-28", "2026-10-05", "2026-10-12"])

    def test_next_upcoming_then_latest_past(self):
        self.assertEqual(BT.select_block(["2026-08-03", "2026-11-02"], date(2026, 10, 7)), ["2026-11-02"])
        self.assertEqual(BT.select_block(["2026-08-03", "2026-08-10"], date(2026, 10, 7)), ["2026-08-03", "2026-08-10"])
        self.assertEqual(BT.select_block([], date(2026, 10, 7)), [])


    def test_single_gap_bridged_only_between_skeleton_weeks(self):
        """Une semaine sans fichier entre deux semaines du squelette (`week_type`) ne coupe pas le bloc."""
        starts = ["2026-09-28", "2026-10-12", "2026-10-19"]
        skel = ["2026-09-28", "2026-10-12", "2026-10-19"]
        self.assertEqual(BT.select_block(starts, date(2026, 10, 14), skel),
                         ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"])
        # Voisine écrite à la main (sans week_type) : le trou coupe.
        self.assertEqual(BT.select_block(starts, date(2026, 10, 14), ["2026-10-12", "2026-10-19"]),
                         ["2026-10-12", "2026-10-19"])
        # Deux semaines manquantes : le trou coupe, même entre semaines du squelette.
        self.assertEqual(BT.select_block(["2026-09-21", "2026-10-12"], date(2026, 10, 14), ["2026-09-21", "2026-10-12"]),
                         ["2026-10-12"])


class TestBuild(unittest.TestCase):
    def test_missing_week_is_flagged_never_filled(self):
        weeks = [wk("2026-09-28", "Base", "build", 18000), wk("2026-10-12", "Base", "build", 19000)]
        done = {"2026-10-05": {"duration_s": 4000, "distance_m": 9000, "elevation_m": 50, "sessions": 1}}
        out = BT.build(weeks, done, None, date(2026, 10, 14))
        gap = out["weeks"][1]
        self.assertEqual([w["week_start"] for w in out["weeks"]], ["2026-09-28", "2026-10-05", "2026-10-12"])
        self.assertFalse(gap["planned"])
        self.assertEqual((gap["phase"], gap["phase_label"]), ("missing", "Semaine sans plan"))
        self.assertIsNone(gap["target_duration_s"])
        self.assertEqual(gap["done"]["duration_s"], 4000)   # le réalisé reste compté
        self.assertEqual((out["missing_weeks"], out["unknown_weeks"]), (1, 0))
        self.assertTrue(out["weeks"][0]["planned"])

    def test_statuses_done_light_race_and_unknown(self):
        weeks = [wk("2026-09-28"), wk("2026-10-05", "Base", "build", 18000), wk("2026-10-12", "Récupération", "recovery", 9000),
                 wk("2026-10-19", "Affûtage", "race", 7200)]
        done = {"2026-09-28": {"duration_s": 3600, "distance_m": 10000, "elevation_m": 100, "sessions": 2},
                "2026-10-05": {"duration_s": 5000, "distance_m": 0, "elevation_m": 0, "sessions": 1}}
        out = BT.build(weeks, done, "2026-10-21", date(2026, 10, 7), "Course")
        w = out["weeks"]
        self.assertEqual([x["status"] for x in w], ["past", "current", "future", "future"])
        self.assertEqual(w[0]["phase"], "unknown")
        self.assertEqual(w[0]["phase_label"], "Phase inconnue")
        self.assertEqual(out["unknown_weeks"], 1)
        self.assertTrue(w[2]["light"])
        self.assertTrue(w[1]["done"]["partial"])
        self.assertNotIn("done", w[2])
        self.assertTrue(w[3]["is_race_week"])
        self.assertEqual(out["race"], {"date": "2026-10-21", "name": "Course", "week_start": "2026-10-19",
                                       "in_block": True, "days_left": 14})

    def test_race_outside_block_and_no_plan(self):
        out = BT.build([wk("2026-10-05", "Base")], {}, "2027-03-01", date(2026, 10, 7))
        self.assertFalse(out["race"]["in_block"])
        empty = BT.build([], {}, None, date(2026, 10, 7))
        self.assertEqual(empty["status"], "no_plan")


class TestApiBlock(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-block-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_week_type_indexed_and_served(self):
        data = {"arc": 1, "kind": "week", "week_start": "2026-09-28", "location": "X", "phase": "Base",
                "week_type": "recovery", "target_duration_s": 7200, "sessions": []}
        (self.ws / "planning/Semaine_2026-09-28.md").write_text(
            f"# Semaine\n\n```arc\n{json.dumps(data)}\n```\n", encoding="utf-8")
        store = S.Store(self.ws, memory=True, today="2026-09-30")
        out = S.api_block(store, {})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["weeks"][0]["week_type"], "recovery")
        self.assertTrue(out["weeks"][0]["light"])
        self.assertEqual(out["weeks"][0]["phase"], "base")

    def test_done_matches_week_view_totals(self):
        """Le réalisé de la frise = la carte « Réalisé » de /api/week (mêmes activités, repos sans effet)."""
        data = {"arc": 1, "kind": "week", "week_start": "2026-09-28", "phase": "Base", "target_duration_s": 7200,
                "sessions": []}
        (self.ws / "planning/Semaine_2026-09-28.md").write_text(
            f"# Semaine\n\n```arc\n{json.dumps(data)}\n```\n", encoding="utf-8")
        for day, sport, dur, dist in (("2026-09-28", "running", 3000, 9000), ("2026-09-29", "strength", 1800, None),
                                      ("2026-09-30", "rest", None, None), ("2026-10-05", "running", 999, 3000)):
            act = {"arc": 1, "kind": "activity", "date": day, "sport": sport}
            if dur:
                act["duration_s"] = dur
            if dist:
                act["distance_m"] = dist
            (self.ws / f"activities/{day}_{sport}.md").write_text(
                f"# S\n\n```arc\n{json.dumps(act)}\n```\n", encoding="utf-8")
        store = S.Store(self.ws, memory=True, today="2026-10-01")
        done = S.api_block(store, {})["weeks"][0]["done"]
        week = S.api_week(store, {"start": ["2026-09-28"]})
        self.assertEqual(done["duration_s"], sum(a["duration_s"] or 0 for a in week["activities"]))
        self.assertEqual(done["distance_m"], sum(a["distance_m"] or 0 for a in week["activities"]))
        self.assertEqual((done["duration_s"], done["sessions"]), (4800, 2))

    def test_no_plan(self):
        store = S.Store(self.ws, memory=True, today="2026-09-30")
        self.assertEqual(S.api_block(store, {})["status"], "no_plan")


if __name__ == "__main__":
    unittest.main()
