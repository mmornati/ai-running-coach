"""Palier D — cycle de vie des chaussures Garmin : une paire retirée dans Garmin Connect APRÈS la création
de sa puce était encore « À surveiller » / « Inspection conseillée ». Verrouille : normalisation de
`get_gear` (MCP et brut), instantané `.arc/garmin_gear.json`, statut effectif (retraite Garmin immédiate,
profil jamais annulé), désaccords, `(retirée AAAA-MM-JJ)`, attribution par défaut jusqu'à la date de
retraite, CLI `garmin-gear-status` (écriture du profil refusée en headless), rattrapage, doctor.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_garmin_gear as GG  # noqa: E402
import arc_index as I  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_metrics as M  # noqa: E402
import coach_doctor as D  # noqa: E402
import garmin_gear_backfill as B  # noqa: E402

TODAY = "2026-10-23"
U1 = "a1" * 16
U2 = "b2" * 16
U3 = "c3" * 16


def mcp_gear(*items) -> dict:
    """Forme du serveur MCP `garmin-mcp` (`gear_management.get_gear`)."""
    return {"gear_count": len(items), "gear": list(items)}


def mcp_shoe(uuid=U1, name="Ultra Glide", status="active", end=None, typ="Shoes"):
    return {"uuid": uuid, "name": name, "full_name": None, "type": typ, "status": status,
            "date_begin": "2025-08-11", "date_end": end}


def gear(text: str) -> list:
    return L.parse_gear("### Chaussures\n\n" + text + "\n")


class TestParseRetiredDate(unittest.TestCase):
    def test_marker_with_and_without_date(self):
        self.assertNotIn("retired_date", gear("- Pegasus (retirée)")[0])
        g = gear("- Pegasus (retirée 2026-10-12)")[0]
        self.assertTrue(g["retired"])
        self.assertEqual(g["retired_date"], "2026-10-12")
        self.assertEqual(g["name"], "Pegasus")
        self.assertEqual(gear("- Pegasus (retiree le 2026-10-12)")[0]["retired_date"], "2026-10-12")

    def test_invalid_date_keeps_pair_retired(self):
        g = gear("- Pegasus (retirée 2026-13-40)")[0]
        self.assertTrue(g["retired"])
        self.assertNotIn("retired_date", g)


class TestNormalize(unittest.TestCase):
    def test_mcp_form_shoes_only(self):
        out = GG.normalize_garmin_shoes(mcp_gear(mcp_shoe(status="retired", end="2026-10-12"),
                                                 mcp_shoe(U2, typ="Bike")))
        self.assertEqual(out, [{"uuid": U1, "name": "Ultra Glide", "status": "retired",
                                "date_begin": "2025-08-11", "date_end": "2026-10-12"}])

    def test_raw_garminconnect_form(self):
        raw = [{"uuid": U1.upper(), "displayName": None, "customMakeModel": "salomon ultra Glide 3",
                "gearTypeName": "Shoes", "gearStatusName": "retired", "dateEnd": "2026-10-12T00:00:00.0"}]
        out = GG.normalize_garmin_shoes(json.dumps(raw))
        self.assertEqual(out[0]["uuid"], U1)
        self.assertEqual(out[0]["status"], "retired")
        self.assertEqual(out[0]["date_end"], "2026-10-12")
        self.assertEqual(out[0]["name"], "salomon ultra Glide 3")

    def test_unreadable_payload_raises(self):
        for bad in ("not json", "{}", "42"):
            with self.subTest(bad=bad), self.assertRaises(GG.GarminGearError):
                GG.normalize_garmin_shoes(bad)


class TestEffectiveStatus(unittest.TestCase):
    def cache(self, *shoes):
        return {"version": 1, "shoes": GG.normalize_garmin_shoes(mcp_gear(*shoes))}

    def test_garmin_retirement_is_immediate(self):
        st = GG.effective_status(gear(f"- Ultra Glide — garmin: {U1}"),
                                 self.cache(mcp_shoe(status="retired", end="2026-10-12")))
        self.assertEqual(st["ultra-glide"], {"retired": True, "retired_source": "garmin",
                                             "retired_date": "2026-10-12", "garmin_status": "retired"})

    def test_without_snapshot_profile_rules(self):
        self.assertEqual(GG.effective_status(gear(f"- Ultra Glide — garmin: {U1}"), None),
                         {"ultra-glide": {"retired": False}})

    def test_profile_retirement_never_undone_by_garmin(self):
        st = GG.effective_status(gear(f"- Ultra Glide — garmin: {U1} (retirée)"), self.cache(mcp_shoe()))
        self.assertEqual(st["ultra-glide"]["retired_source"], "profile")
        self.assertTrue(st["ultra-glide"]["retired"])

    def test_profile_retired_without_date_takes_garmin_end_date(self):
        st = GG.effective_status(gear(f"- Ultra Glide — garmin: {U1} (retirée)"),
                                 self.cache(mcp_shoe(status="retired", end="2026-10-12")))
        self.assertEqual(st["ultra-glide"]["retired_date"], "2026-10-12")

    def test_ignored_and_duplicate_uuid_are_never_touched(self):
        profile = gear(f"- Vieille — garmin: {U1} (ignorée)\n- A — garmin: {U2}\n- B — garmin: {U2}")
        st = GG.effective_status(profile, self.cache(mcp_shoe(status="retired"), mcp_shoe(U2, status="retired")))
        self.assertFalse(any(v["retired"] for v in st.values()))

    def test_drift_both_directions(self):
        profile = gear(f"- Ultra Glide — garmin: {U1}\n- Pegasus — garmin: {U2} (retirée)\n- Speedgoat — garmin: {U3}")
        drift = GG.status_drift(profile, self.cache(mcp_shoe(status="retired", end="2026-10-12"),
                                                    mcp_shoe(U2, "Pegasus"), mcp_shoe(U3, "Speedgoat")))
        self.assertEqual([(d["gear_id"], d["kind"]) for d in drift],
                         [("pegasus", "active_in_garmin"), ("ultra-glide", "retired_in_garmin")])
        self.assertEqual(drift[1]["marker"], "(retirée 2026-10-12)")


class TestAttribution(unittest.TestCase):
    def act(self, day, km=10):
        return {"sport": "running", "distance_m": km * 1000, "date": day}

    def test_retired_default_with_date_keeps_its_career(self):
        defs = [{"gear_id": "ultra", "default": True, "retired": True, "retired_date": "2026-10-12",
                 "start_date": "2025-08-11"}]
        res = M.gear_mileage([self.act("2025-08-01"), self.act("2026-09-01"), self.act("2026-10-12"),
                              self.act("2026-10-20")], defs)
        self.assertEqual(res["shoes"][0]["distance_m"], 20000)     # avant `depuis` et après la retraite : exclues
        self.assertNotIn("over_threshold", res["shoes"][0])
        self.assertTrue(any("par défaut" in w for w in res["warnings"]))

    def test_new_default_with_start_wins_over_retired_one(self):
        defs = [{"gear_id": "ultra", "default": True, "retired": True, "retired_date": "2026-10-12"},
                {"gear_id": "speedgoat", "default": True, "start_date": "2026-10-01"}]
        res = {s["gear_id"]: s["distance_m"] for s in M.gear_mileage(
            [self.act("2026-09-20"), self.act("2026-10-05"), self.act("2026-10-20")], defs)["shoes"]}
        self.assertEqual(res, {"ultra": 10000, "speedgoat": 20000})

    def test_retired_default_without_date_unchanged(self):
        defs = [{"gear_id": "ultra", "default": True, "retired": True}]
        self.assertEqual(M.gear_mileage([self.act("2026-09-01")], defs)["shoes"][0]["distance_m"], 0)

    def test_retired_pair_over_threshold_never_alerts(self):
        defs = [{"gear_id": "ultra", "retired": True, "retired_source": "garmin", "threshold_m": 800000}]
        acts = [dict(self.act("2026-09-01", 948), gear_id="ultra")]
        shoe = M.gear_mileage(acts, defs)["shoes"][0]
        self.assertFalse(shoe["alert"])
        self.assertTrue(shoe["over_threshold"])
        self.assertEqual(shoe["retired_source"], "garmin")


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-garmin-gear-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "planning"):
            (self.ws / d).mkdir(parents=True)
        self.write_profile(f"- Ultra Glide — depuis 2025-08-11 — alerte 800 km — id: ultra-glide — garmin: {U1}\n"
                           f"- Speedgoat — garmin: {U2}")
        data = {"arc": 1, "kind": "activity", "date": "2026-09-01", "sport": "running", "duration_s": 3600,
                "distance_m": 948000, "gear_id": "ultra-glide"}
        (self.ws / "activities/2026-09-01_running.md").write_text(
            f"# Course\n\n```arc\n{json.dumps(data)}\n```\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_profile(self, bullets):
        (self.ws / "planning/Runner_Profile.md").write_text(
            f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n{bullets}\n", encoding="utf-8")

    def snapshot(self, status="retired", end="2026-10-12"):
        resp = self.tmp / "get_gear.json"
        resp.write_text(json.dumps(mcp_gear(mcp_shoe(status=status, end=end), mcp_shoe(U2, "Speedgoat"))))
        return resp

    def cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--today", TODAY, *argv])
        return code, json.loads(buf.getvalue())

    def shoe(self):
        _, out = self.cli("gear")
        return next(s for s in out["shoes"] if s["gear_id"] == "ultra-glide")


class TestIndexAndCli(Workspace):
    def test_before_snapshot_pair_is_alerting(self):
        shoe = self.shoe()
        self.assertTrue(shoe["alert"])
        self.assertFalse(shoe["retired"])

    def test_garmin_retirement_silences_alert_and_inspection(self):
        code, out = self.cli("garmin-gear-status", "--garmin-gear-json", str(self.snapshot()))
        self.assertEqual(code, 0)
        self.assertEqual(out["drift"][0]["kind"], "retired_in_garmin")
        self.assertTrue((self.ws / GG.CACHE_REL).is_file())
        shoe = self.shoe()
        self.assertEqual((shoe["retired"], shoe["alert"], shoe["retired_source"], shoe["retired_date"]),
                         (True, False, "garmin", "2026-10-12"))
        _, insp = self.cli("inspections")
        self.assertNotIn("ultra-glide", insp["due"])
        declared = next(g for g in insp["declared"] if g["gear_id"] == "ultra-glide")
        self.assertEqual(declared["retired_source"], "garmin")

    def test_snapshot_reactivation_and_removal_are_recomputed(self):
        self.cli("garmin-gear-status", "--garmin-gear-json", str(self.snapshot()))
        self.cli("garmin-gear-status", "--garmin-gear-json", str(self.snapshot(status="active", end=None)))
        self.assertFalse(self.shoe()["retired"])
        self.cli("garmin-gear-status", "--garmin-gear-json", str(self.snapshot()))
        (self.ws / GG.CACHE_REL).unlink()
        self.assertFalse(self.shoe()["retired"])

    def test_mark_retired_refused_headless_then_written(self):
        resp = str(self.snapshot())
        with mock.patch.dict(os.environ, {"ARC_HEADLESS": "1"}):
            code, out = self.cli("garmin-gear-status", "--garmin-gear-json", resp, "--mark-retired", "ultra-glide")
        self.assertEqual(code, 1)
        self.assertIn("ARC_HEADLESS", out["mark_retired"]["error"])
        self.assertNotIn("retirée", (self.ws / "planning/Runner_Profile.md").read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARC_HEADLESS", None)
            code, out = self.cli("garmin-gear-status", "--mark-retired", "ultra-glide")
        self.assertEqual(code, 0)
        self.assertTrue(out["mark_retired"]["written"])
        self.assertEqual(out["drift"], [])
        text = (self.ws / "planning/Runner_Profile.md").read_text(encoding="utf-8")
        self.assertIn(f"garmin: {U1} (retirée 2026-10-12)", text)
        shoe = self.shoe()
        self.assertEqual(shoe["retired_source"], "profile")

    def test_mark_retired_only_for_drift(self):
        os.environ.pop("ARC_HEADLESS", None)
        code, out = self.cli("garmin-gear-status", "--mark-retired", "speedgoat")
        self.assertEqual(code, 1)
        self.assertIn("error", out["mark_retired"])

    def test_bad_payload_is_a_config_error(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{}")
        with self.assertRaises(I.ConfigError):
            self.cli("garmin-gear-status", "--garmin-gear-json", str(bad))

    def test_doctor_reports_garmin_retirement(self):
        self.cli("garmin-gear-status", "--garmin-gear-json", str(self.snapshot()))
        check = D.check_gear_sync(self.ws, {"data": {"source": "garmin"}})
        self.assertEqual(check["status"], "info")
        self.assertIn("Ultra Glide", check["message"])


class TestBackfillRetirement(unittest.TestCase):
    def raw(self, status):
        return {"uuid": U1, "displayName": "Ultra Glide", "gearTypeName": "Shoes", "gearStatusName": status,
                "dateBegin": "2025-08-11T00:00:00.0", "dateEnd": "2026-10-12T00:00:00.0", "maximumMeters": 800000}

    def plan(self, status, profile):
        shoes = B.normalize_shoes([self.raw(status)])
        acts = {U1: {"activities": B.normalize_gear_activities(
            [{"activityId": 1, "startTimeLocal": "2026-09-01 07:00:00", "distance": 10000}]), "error": None,
            "truncated": False}}
        files = [{"path": "activities/2026-09-01_running.md", "date": "2026-09-01", "garmin_activity_id": 1,
                  "distance_m": 10000, "gear_id": "ultra-glide", "gear_source": "garmin", "has_block": True}]
        return B.plan(shoes, acts, files, L.parse_gear(profile))

    def test_existing_linked_bullet_gets_retirement(self):
        profile = f"### Chaussures\n\n- Ultra Glide — id: ultra-glide — garmin: {U1}\n"
        result = self.plan("retired", profile)
        self.assertEqual(result["retirements"], [{"uuid": U1, "gear_id": "ultra-glide", "name": "Ultra Glide",
                                                  "date_end": "2026-10-12"}])
        self.assertIn("retirée dans Garmin", B.render_report(result))
        self.assertEqual(self.plan("active", profile)["retirements"], [])
        self.assertEqual(self.plan("retired", profile.rstrip("\n") + " (retirée)\n")["retirements"], [])

    def test_apply_writes_only_the_marker(self):
        tmp = Path(tempfile.mkdtemp(prefix="arc-bf-ret-"))
        try:
            profile = tmp / "planning/Runner_Profile.md"
            profile.parent.mkdir(parents=True)
            text = f"# P\n\n### Chaussures\n\n- Ultra Glide — id: ultra-glide — garmin: {U1}\n- Autre\n"
            profile.write_text(text, encoding="utf-8")
            result = self.plan("retired", text)
            result["assignments"] = []
            out = B.apply_plan(tmp, profile, result, validate=lambda p: (True, [], []))
            self.assertEqual(out["retired"], ["ultra-glide"])
            self.assertEqual(profile.read_text(encoding="utf-8"),
                             text.replace(f"garmin: {U1}\n", f"garmin: {U1} (retirée 2026-10-12)\n"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_marker_helper(self):
        text = "### Chaussures\r\n\r\n- A — id: a\r\n- B (retirée)\r\n"
        self.assertIn("- A — id: a (retirée)\r\n", B.append_retired_marker(text, "a"))
        self.assertIsNone(B.append_retired_marker(text, "b"))       # déjà retirée
        self.assertIsNone(B.append_retired_marker(text, "zzz"))


if __name__ == "__main__":
    unittest.main()
