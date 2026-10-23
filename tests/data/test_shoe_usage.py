"""Palier D — profil d'usage par paire (#300, épopée #297) : `arc_shoe_usage` (fonctions pures) et
`arc_index.py shoe-usage` / `gear_detail().usage` sur des workspaces bâtis avec le VRAI indexeur.

Fixtures SYNTHÉTIQUES, workspaces temporaires passés en `--workspace`, base en mémoire : jamais le
workspace réel. Lecture seule vérifiée (aucun fichier créé ni modifié).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_shoe_usage as SU  # noqa: E402

TODAY = "2026-10-23"
PROFILE = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
           "- Route A — usage: route — id: road-a\n- Route B — usage: route — id: road-b\n"
           "- Trail A — usage: trail — id: trail-a\n")


def block_file(data: dict) -> str:
    return f"# Fichier\n\n```arc\n{json.dumps(data, ensure_ascii=False)}\n```\n\nTexte.\n"


def day(offset: int, base: str = "2026-09-01") -> str:
    return (date.fromisoformat(base) + timedelta(days=offset)).isoformat()


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.write("planning/Runner_Profile.md", PROFILE)

    def write(self, rel: str, text: str) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_(self, d: str, gear_id=None, sport="running", km=10.0, dur=3000, gain=None, loss=None, gct=None, **extra):
        data = {"arc": 1, "kind": "activity", "date": d, "sport": sport, "distance_m": km * 1000, "duration_s": dur}
        if gear_id:
            data["gear_id"] = gear_id
        if gain is not None:
            data["elevation_gain_m"] = gain
        if loss is not None:
            data["elevation_loss_m"] = loss
        if gct is not None:
            data["avg_ground_contact_s"] = gct
            data["avg_vertical_oscillation_m"] = 0.09
        data.update(extra)
        self.write(f"activities/{d}_{sport}.md", block_file(data))

    def pain(self, d: str, location="genou droit", score=4):
        self.write(f"medical/{d}_health.md", block_file({
            "arc": 1, "kind": "health", "date": d, "morning_check": "full",
            "pain": [{"location": location, "score": score}]}))

    def rain(self, d: str, mm: float):
        self.write(f"medical/{d}_meteo.md", block_file({
            "arc": 1, "kind": "weather", "date": d, "location": "Lille", "category": "yellow", "precip_mm": mm}))

    def conn(self):
        conn = I.open_db(self.ws, memory=True)
        I.index_workspace(conn, self.ws, TODAY)
        return conn

    def cli(self, *extra) -> tuple:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", TODAY, "shoe-usage", *extra])
        return code, buf.getvalue()

    def report(self) -> dict:
        code, out = self.cli()
        self.assertEqual(code, 0)
        return json.loads(out)

    def pair(self, gid: str) -> dict:
        return next(p for p in self.report()["pairs"] if p["gear_id"] == gid)


class TestUsage(Workspace):
    def setUp(self):
        super().setUp()
        for i in range(4):     # route : 4 x 10 km à 5:00/km
            self.run_(day(i * 2), "road-a")
        self.run_(day(9), "road-a", km=21.5, dur=8100)          # longue : > 90 min
        self.run_(day(20), "trail-a", sport="trail", km=20, dur=12000, gain=1000, loss=900)
        self.run_(day(22), "trail-a", sport="trail", km=10, dur=6000, gain=400, loss=500)
        self.rain(day(0), 6.0)
        self.rain(day(2), 0.2)

    def test_terrain_and_elevation(self):
        road, trail = self.pair("road-a"), self.pair("trail-a")
        self.assertEqual(road["usage"]["sessions"], 5)
        self.assertEqual(road["usage"]["terrain"]["road"]["share_km"], 1.0)
        self.assertEqual(road["usage"]["terrain"]["trail"]["share_km"], 0.0)
        self.assertNotIn("d_plus_m_per_km", road["usage"])           # aucune donnée -> omis, jamais 0
        self.assertEqual(trail["usage"]["terrain"]["trail"]["share_km"], 1.0)
        self.assertEqual(trail["usage"]["d_plus_m_per_km"], round(1400 / 30, 1))
        self.assertEqual(trail["usage"]["d_minus_m_per_km"], round(1400 / 30, 1))

    def test_same_activities_as_mileage(self):
        mileage = I.gear_mileage(self.conn(), date.fromisoformat(TODAY))
        for p in self.report()["pairs"]:
            shoe = next(s for s in mileage["shoes"] if s["gear_id"] == p["gear_id"])
            self.assertEqual(p["usage"]["distance_m"], shoe["distance_m"])

    def test_distance_distribution_long_runs_and_pace(self):
        u = self.pair("road-a")["usage"]
        buckets = {b["label"]: b["sessions"] for b in u["distance_distribution"]}
        self.assertEqual(buckets["10–15 km"], 4)
        self.assertEqual(buckets["21–30 km"], 1)
        self.assertEqual(u["long_runs"], {"sessions": 1, "share_sessions": 0.2, "threshold_s": 5400})
        self.assertEqual(u["mean_pace_s_km"], round((4 * 3000 + 8100) / 61.5))
        self.assertEqual(u["period"], {"first_date": day(0), "last_date": day(9), "days": 10})

    def test_wet_share_only_on_sessions_with_weather(self):
        u = self.pair("road-a")["usage"]
        self.assertEqual(u["wet"], {"sessions": 1, "with_weather": 2, "share": 0.5})
        self.assertNotIn("wet", self.pair("trail-a")["usage"])        # aucune météo ces jours-là

    def test_races_use_planned_intensity(self):
        monday = date.fromisoformat(day(20))
        monday -= timedelta(days=monday.weekday())
        self.write(f"planning/Semaine_{monday.isoformat()}.md", block_file({
            "arc": 1, "kind": "week", "week_start": monday.isoformat(), "location": "Lille",
            "sessions": [{"date": day(20), "sport": "trail", "title": "Course", "intensity": "race"}]}))
        self.assertEqual(self.pair("trail-a")["usage"]["races"]["sessions"], 1)

    def test_unknown_gear_is_an_error(self):
        code, out = self.cli("--gear", "nope")
        self.assertEqual(code, 1)
        self.assertIn("paire inconnue", json.loads(out)["error"])


class TestGaitBands(Workspace):
    def setUp(self):
        super().setUp()
        # road-a : 3 séances à 5:00/km (tranche 5:00-5:30), GCT 0,240 ; 1 séance à 6:30/km (hors effectif).
        for i in range(3):
            self.run_(day(i), "road-a", gct=0.240)
        self.run_(day(5), "road-a", dur=3900, gct=0.260)
        # road-b : 3 séances dans la MÊME tranche (GCT 0,250) ; 2 séances à 4:00/km, tranche seule.
        for i in range(3):
            self.run_(day(10 + i), "road-b", dur=3100, gct=0.250)
        for i in range(2):
            self.run_(day(15 + i), "road-b", dur=2400, gct=0.200)

    def band(self, gid: str, lo: int) -> dict:
        return next(b for b in self.pair(gid)["gait"]["bands"] if b["band_lo_s_km"] == lo)

    def test_comparison_only_in_the_same_band(self):
        b = self.band("road-a", 300)
        self.assertEqual(b["status"], "ok")
        self.assertEqual(b["metrics"]["ground_contact_s"], {"mean": 0.24, "n": 3})
        others = b["others"]
        self.assertEqual([o["gear_id"] for o in others], ["road-b"])
        self.assertEqual(others[0]["metrics"]["ground_contact_s"]["mean"], 0.25)
        # la tranche rapide de road-b n'est comparée à rien de road-a
        fast = self.band("road-b", 240)
        self.assertEqual(fast["status"], "insufficient")
        self.assertNotIn("others", fast)
        self.assertNotIn("metrics", fast)

    def test_insufficient_band_is_labelled(self):
        slow = self.band("road-a", 390)
        self.assertEqual(slow["status"], "insufficient")
        self.assertEqual(slow["reason"], "données insuffisantes")
        self.assertEqual(slow["sessions"], 1)

    def test_band_helpers(self):
        self.assertEqual(SU.pace_band(299.9), (270, 300))
        self.assertEqual(SU.pace_band(300), (300, 330))
        self.assertEqual(SU.band_label(300, 330), "5:00–5:30/km")


class TestPain(Workspace):
    def test_window_exposure_and_no_trend_under_five(self):
        self.run_(day(0), "road-a")
        self.run_(day(3), "road-b")
        self.pain(day(2), "genou droit")        # 2 j après road-a -> road-a
        self.pain(day(3), "genou droit")        # même zone, jours consécutifs -> même épisode
        self.pain(day(10), "mollet")            # aucune séance dans les 48 h -> non rattaché
        rep = self.report()
        a = next(p for p in rep["pairs"] if p["gear_id"] == "road-a")["pain"]
        b = next(p for p in rep["pairs"] if p["gear_id"] == "road-b")["pain"]
        self.assertEqual(a["episodes"], 1)
        self.assertEqual(b["episodes"], 0)
        self.assertEqual(a["recent"][0]["run_date"], day(0))
        self.assertEqual(rep["pain_episodes_without_run"], 1)
        self.assertEqual(a["exposure"], {"sessions": 1, "distance_m": 10000})
        self.assertFalse(a["trend_allowed"])
        self.assertNotIn("per_100km", a)
        self.assertIn("effectif trop faible", a["warning"])
        self.assertIn("Corrélation, pas causalité", a["note"])

    def test_five_episodes_give_a_rate(self):
        for i in range(5):
            self.run_(day(i * 5), "road-a")
            self.pain(day(i * 5 + 1), f"zone {i}")
        pain = self.pair("road-a")["pain"]
        self.assertEqual(pain["episodes"], 5)
        self.assertTrue(pain["trend_allowed"])
        self.assertEqual(pain["per_100km"], 10.0)              # 5 épisodes / 50 km
        self.assertEqual(pain["per_100_sessions"], 100.0)

    def test_four_episodes_no_rate(self):
        for i in range(4):
            self.run_(day(i * 5), "road-a")
            self.pain(day(i * 5 + 1), f"zone {i}")
        pain = self.pair("road-a")["pain"]
        self.assertEqual(pain["episodes"], 4)
        self.assertFalse(pain["trend_allowed"])

    def test_zero_score_is_not_an_episode(self):
        self.run_(day(0), "road-a")
        self.pain(day(1), "genou", score=0)
        self.assertEqual(self.pair("road-a")["pain"]["episodes"], 0)

    def test_episode_after_unassigned_run_is_unattributable(self):
        self.run_(day(0), "road-a")
        self.run_(day(2))                    # sans gear_id, pas de paire par défaut
        self.pain(day(3), "genou")
        rep = self.report()
        self.assertEqual(rep["pain_episodes_run_without_pair"], 1)
        self.assertEqual(next(p for p in rep["pairs"] if p["gear_id"] == "road-a")["pain"]["episodes"], 0)


class TestUnassigned(Workspace):
    def test_runs_without_gear_in_period_are_flagged(self):
        self.run_(day(0), "road-a")
        self.run_(day(3))                     # sans gear_id : dans la période
        self.run_(day(8), "road-a")
        self.run_(day(30))                    # hors période : ignorée
        p = self.pair("road-a")
        self.assertEqual(p["unassigned"]["runs"], 1)
        self.assertEqual(p["unassigned"]["distance_m"], 10000)
        self.assertFalse(p["pain"]["reliable"])
        self.assertIn("pas fiable", p["pain"]["warning_unassigned"])

    def test_default_pair_credit_is_counted_apart(self):
        self.write("planning/Runner_Profile.md", PROFILE.replace("id: road-a", "id: road-a (par défaut)"))
        self.run_(day(0), "road-a")
        self.run_(day(3))
        self.run_(day(8), "road-a")
        p = self.pair("road-a")
        self.assertEqual(p["unassigned"]["runs"], 0)
        self.assertEqual(p["unassigned"]["default_attributed_runs"], 1)
        self.assertEqual(p["usage"]["sessions"], 3)


class TestRole(Workspace):
    def usage(self, road=0, trail=0, long_share=0.0, races=0, pace=330):
        return {"sessions": road + trail, "terrain": {
            "road": {"sessions": road, "distance_m": road * 10000, "share_km": None},
            "trail": {"sessions": trail, "distance_m": trail * 10000, "share_km": None}},
            "long_runs": {"share_sessions": long_share}, "races": {"sessions": races}, "mean_pace_s_km": pace}

    def role(self, usage, ref=330):
        return SU.deduce_role(usage, ref)["role"]

    def test_rules(self):
        self.assertEqual(self.role(self.usage(trail=6, long_share=0.5)), "trail_long")
        self.assertEqual(self.role(self.usage(trail=6, long_share=0.1)), "trail")
        self.assertEqual(self.role(self.usage(road=6, pace=300)), "road_tempo")
        self.assertEqual(self.role(self.usage(road=6, pace=330)), "road_easy")
        self.assertEqual(self.role(self.usage(road=3, trail=3)), "mixed")
        self.assertEqual(self.role(self.usage(road=3)), "insufficient_data")
        self.assertEqual(self.role(self.usage(road=2, races=2)), "race")
        self.assertEqual(self.role(self.usage(road=1, races=1)), "insufficient_data")   # < 2 séances

    def test_role_in_report(self):
        for i in range(6):
            self.run_(day(i), "trail-a", sport="trail", km=20, dur=12000, gain=900, loss=900)
        role = self.pair("trail-a")["role"]
        self.assertEqual(role["role"], "trail_long")
        self.assertIn("approximation du projet", role["note"])


class TestFeedbackWearAndDetail(Workspace):
    def setUp(self):
        super().setUp()
        self.run_(day(0), "road-a", shoe_feedback={"comfort": 7, "issues": [{"kind": "blister"}]})
        self.write("gear/2026-09-05_road-a_inspection.md", block_file({
            "arc": 1, "kind": "gear_inspection", "date": "2026-09-05", "gear_id": "road-a", "condition": "yellow",
            "photos": ["gear/photos/x.jpg"]}))

    def test_feedback_summary_is_reused(self):
        fb = self.pair("road-a")["feedback"]
        self.assertEqual(fb["comfort"]["mean"], 7)
        self.assertEqual(fb["issue_counts"], {"blister": 1})
        self.assertIsNone(self.pair("road-b")["feedback"])

    def test_last_inspection(self):
        self.assertEqual(self.pair("road-a")["wear"]["condition"], "yellow")
        self.assertIsNone(self.pair("road-b")["wear"])

    def test_gear_detail_carries_usage_and_matches_cli(self):
        detail = I.gear_detail(self.conn(), "road-a", date.fromisoformat(TODAY))
        self.assertEqual(detail["usage"], self.pair("road-a"))

    def test_text_output(self):
        code, out = self.cli("--text")
        self.assertEqual(code, 0)
        self.assertIn("road-a — Route A", out)
        self.assertIn("rôle déduit", out)
        self.assertIn("Corrélation, pas causalité", out)

    def test_read_only(self):
        def snapshot():
            return {p.relative_to(self.ws).as_posix(): p.stat().st_mtime_ns for p in self.ws.rglob("*") if p.is_file()}
        before = snapshot()
        self.cli()
        self.cli("--gear", "road-a", "--text")
        self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()
