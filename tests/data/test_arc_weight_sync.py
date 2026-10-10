"""Palier D — `scripts/arc_weight_sync.py` : poids du jour lu dans Garmin Connect (#222).

Pur calcul : aucun appel Garmin, aucun modèle. Verrouille le choix de la pesée (la plus
ancienne du jour), l'absence de report d'un jour sur l'autre, la priorité de la valeur
déclarée par l'athlète, le signalement unique d'un écart > 1 kg et le rattrapage.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_weight_sync as W  # noqa: E402

DAY = "2026-10-10"


def _daily(*measurements, day=DAY):
    """Forme de `get_daily_weigh_ins` (garmin-mcp, weight_management.py)."""
    return {"date": day, "measurement_count": len(measurements), "measurements": list(measurements)}


def _m(kg, ts=None, **extra):
    m = {"weight_grams": kg * 1000, "weight_kg": kg, "source_type": "INDEX_SCALE"}
    if ts is not None:
        m["timestamp_gmt"] = ts
    m.update(extra)
    return m


class WeightSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        (self.ws / "medical").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def health(self, day=DAY, **keys):
        data = {"arc": 1, "kind": "health", "date": day, "morning_check": "full", **keys}
        (self.ws / "medical" / f"{day}_health.md").write_text(
            f"# Santé — {day}\n\n```arc\n{json.dumps(data)}\n```\n", encoding="utf-8")

    def plan(self, payload):
        return W.build_plan(payload, self.ws)

    def test_earliest_weigh_in_of_the_day_wins(self):
        self.health()
        out = self.plan({"garmin": _daily(_m(71.8, ts=1760100000000), _m(71.2, ts=1760070000000))})
        day = out["days"][0]
        self.assertEqual(day["action"], "write")
        self.assertEqual(day["set"], {"weight_kg": 71.2, "weight_origin": "garmin"})
        self.assertEqual(out["weighed_by_garmin"], [DAY])

    def test_grams_only_and_implausible_values(self):
        self.health()
        out = self.plan({"garmin": _daily({"weight_grams": 70450}, {"weight_kg": 0.07})})
        self.assertEqual(out["days"][0]["set"]["weight_kg"], 70.45)
        self.assertEqual(len(out["warnings"]), 1)

    def test_no_weigh_in_writes_nothing(self):
        self.health(day="2026-10-09", weight_kg=70.0, weight_origin="garmin")
        self.health()
        out = self.plan({"garmin": f"No weight measurements found for {DAY}.", "date": DAY})
        self.assertEqual(out["days"][0]["action"], "none")
        self.assertEqual(out["days"][0]["set"], {})
        self.assertEqual(out["weighed_by_garmin"], [])

    def test_missing_file_is_created_unless_backfill(self):
        out = self.plan({"garmin": _daily(_m(70.0))})
        self.assertEqual(out["days"][0]["action"], "write")
        self.assertTrue(out["days"][0]["create"])
        out = self.plan({"garmin": _daily(_m(70.0)), "existing_only": True})
        self.assertEqual(out["days"][0]["action"], "skip_no_file")

    def test_garmin_value_unchanged_or_updated(self):
        self.health(weight_kg=70.0, weight_origin="garmin")
        self.assertEqual(self.plan({"garmin": _daily(_m(70.0))})["days"][0]["action"], "unchanged")
        day = self.plan({"garmin": _daily(_m(69.6))})["days"][0]
        self.assertEqual((day["action"], day["set"]), ("update", {"weight_kg": 69.6}))

    def test_athlete_value_wins_small_gap_silent(self):
        self.health(weight_kg=70.0, weight_origin="chat")
        day = self.plan({"garmin": _daily(_m(70.8))})["days"][0]
        self.assertEqual(day["action"], "keep_athlete")
        self.assertEqual(day["set"], {})
        self.assertIsNone(day["flag"])

    def test_legacy_value_without_origin_is_the_athlete(self):
        self.health(weight_kg=70.0)
        self.assertEqual(self.plan({"garmin": _daily(_m(70.3))})["days"][0]["action"], "keep_athlete")

    def test_large_gap_flagged_once(self):
        self.health(weight_kg=70.0, weight_origin="chat")
        day = self.plan({"garmin": _daily(_m(71.5))})["days"][0]
        self.assertEqual(day["set"], {"weight_garmin_kg": 71.5})
        self.assertEqual(day["flag"], {"athlete_kg": 70.0, "garmin_kg": 71.5, "diff_kg": 1.5})
        self.health(weight_kg=70.0, weight_origin="chat", weight_garmin_kg=71.5)
        day = self.plan({"garmin": _daily(_m(71.5))})["days"][0]
        self.assertEqual((day["set"], day["flag"]), ({}, None))

    def test_range_backfill_covers_every_day(self):
        self.health(day="2026-10-01")
        self.health(day="2026-10-02", weight_kg=70.0, weight_origin="chat")
        raw = {"date_range": {"start": "2026-10-01", "end": "2026-10-03"},
               "measurements": [{"date": "2026-10-02", "weight_kg": 70.2},
                                {"date": "2026-10-01", "weight_kg": 70.4}]}
        out = self.plan({"garmin": json.dumps(raw), "existing_only": True})
        actions = {d["date"]: d["action"] for d in out["days"]}
        self.assertEqual(actions, {"2026-10-01": "write", "2026-10-02": "keep_athlete", "2026-10-03": "none"})

    def test_declared_beats_garmin_and_keeps_it_aside(self):
        self.health(weight_kg=71.5, weight_origin="garmin")
        day = self.plan({"declared": {"date": DAY, "weight_kg": 70.0}})["days"][0]
        self.assertEqual(day["action"], "declare")
        self.assertEqual(day["set"], {"weight_kg": 70.0, "weight_origin": "chat", "weight_garmin_kg": 71.5})
        self.assertIsNotNone(day["flag"])
        self.health(weight_kg=70.0, weight_origin="chat", weight_garmin_kg=70.5)
        day = self.plan({"declared": {"date": DAY, "weight_kg": 70.2}})["days"][0]
        self.assertEqual(day["remove"], ["weight_garmin_kg"])

    def test_declared_rejects_implausible(self):
        with self.assertRaises(W.WeightSyncError):
            self.plan({"declared": {"date": DAY, "weight_kg": 700}})

    def test_planned_keys_pass_the_contract(self):
        self.health()
        day = self.plan({"garmin": _daily(_m(70.0))})["days"][0]
        data = {"arc": 1, "kind": "health", "date": DAY, "morning_check": "full", **day["set"]}
        self.assertEqual(C.validate(data)[0], [])

    def test_cli_with_inline_garmin(self):
        self.health()
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/arc_weight_sync.py"), "plan", "--workspace", str(self.ws),
             "--garmin", json.dumps(_daily(_m(70.0)))], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout)["days"][0]["action"], "write")

    def test_cli_stdin_accepts_raw_reply_and_no_data_text(self):
        self.health()
        script = [sys.executable, str(REPO / "scripts/arc_weight_sync.py"), "plan", "--workspace", str(self.ws)]
        proc = subprocess.run(script, input=json.dumps(_daily(_m(70.0))), capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout)["days"][0]["action"], "write")
        proc = subprocess.run(script + ["--date", DAY], input=f"No weight measurements found for {DAY}.",
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout)["days"][0]["action"], "none")


class HealthWeightContractTest(unittest.TestCase):
    BASE = {"arc": 1, "kind": "health", "date": DAY, "morning_check": "full"}

    def errors(self, **keys):
        return C.validate({**self.BASE, **keys})[0]

    def test_origin_values(self):
        self.assertEqual(self.errors(weight_kg=70.0, weight_origin="garmin"), [])
        self.assertEqual(self.errors(weight_kg=70.0, weight_origin="chat", weight_garmin_kg=71.5), [])
        self.assertTrue(self.errors(weight_kg=70.0, weight_origin="balance"))

    def test_origin_requires_weight(self):
        self.assertTrue(self.errors(weight_origin="garmin"))
        self.assertTrue(self.errors(weight_garmin_kg=71.5))

    def test_garmin_kept_aside_only_when_athlete_wins(self):
        self.assertTrue(self.errors(weight_kg=70.0, weight_origin="garmin", weight_garmin_kg=71.5))


if __name__ == "__main__":
    unittest.main()
