"""Palier A — trace d'une séance pour la carte de la page séance (`/api/activity/<id>/track`)
et fond de carte (`[dashboard].map_tiles` → en-tête Content-Security-Policy).

Même discipline que `test_climb_segment_api.py` : un petit bac à sable dédié, échantillons FIT
écrits à la main avec des coordonnées FICTIVES (Pacifique Sud, loin de toute côte — voir
`tests/lint/test_synthetic_no_real_data.py::SAFE_LAT_RANGE`/`SAFE_LON_RANGE`), plutôt que
d'alourdir le golden partagé.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import arc_gap as G  # noqa: E402
from tests.install.test_dashboard import Server  # noqa: E402
from tests.lib.sandbox import Sandbox  # noqa: E402
from tests.lib.asserts import InstallAsserts  # noqa: E402
from tests.lib.synthetic import build  # noqa: E402

TODAY = "2026-09-26"


def _write_fit(ws, garmin_id: int, *, n: int, gps: bool, start_lat=-40.0, start_lon=-135.0) -> None:
    records = []
    for i in range(n):
        rec = {"t_s": float(i * 5), "distance_m": float(i * 15), "altitude_m": 100.0 + i % 50,
               "hr_bpm": 140.0, "speed_ms": 3.0, "cadence_spm": 170.0,
               "ground_contact_s": 0.25, "vertical_oscillation_m": 0.08}
        if gps:
            rec["lat_deg"] = start_lat + i * 1e-4
            rec["lon_deg"] = start_lon + i * 1e-4
        records.append(rec)
    fit_dir = ws / "activities/fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{garmin_id}.json").write_text(json.dumps({"activity_id": garmin_id, "records": records}),
                                               encoding="utf-8")


def _garmin_ids(ws, kind: str) -> list[int]:
    ids = []
    for path in sorted((ws / "activities").glob(f"*_{kind}.md")):
        match = re.search(r'"garmin_activity_id":\s*(\d+)', path.read_text(encoding="utf-8"))
        if match:
            ids.append(int(match.group(1)))
    return ids


class _TrackSandbox(InstallAsserts):
    user_toml_extra = ""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=25, sport="trail", seed=5,
                        today=datetime.date.fromisoformat(TODAY))
        if self.user_toml_extra:
            user = self.ws / "config/workspace.user.toml"
            user.write_text(user.read_text(encoding="utf-8") + self.user_toml_extra, encoding="utf-8")
        ids = _garmin_ids(self.ws, "trail")
        self.assertGreaterEqual(len(ids), 3, "il faut au moins trois séances trail dans ce bac à sable")
        self.gps_id, self.indoor_id, self.long_id = ids[0], ids[1], ids[2]
        _write_fit(self.ws, self.gps_id, n=400, gps=True)
        _write_fit(self.ws, self.indoor_id, n=100, gps=False)
        _write_fit(self.ws, self.long_id, n=4000, gps=True)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def _activity_id_for(self, garmin_id: int) -> int:
        for a in json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]:
            row = json.loads(self.server.get(f"/api/activity/{a['id']}")[1])
            if row["activity"].get("garmin_activity_id") == garmin_id:
                return a["id"]
        raise AssertionError(f"aucune activité indexée pour garmin_activity_id={garmin_id}")


class TestActivityTrackApi(_TrackSandbox):
    def test_track_with_gps_returns_parallel_columns_and_bounds(self):
        status, body, _ = self.server.get(f"/api/activity/{self._activity_id_for(self.gps_id)}/track")
        self.assertEqual(status, 200)
        track = json.loads(body)
        self.assertTrue(track["has_gps"])
        self.assertNotIn("reason_code", track)
        n = track["points"]
        self.assertGreater(n, 10)
        for key in ("d", "t", "lat", "lon", "alt", "hr", "spd", "cad"):
            self.assertEqual(len(track[key]), n, key)
        (lat0, lon0), (lat1, lon1) = track["bounds"]
        self.assertLess(lat0, lat1)
        self.assertLess(lon0, lon1)
        self.assertTrue(-46.0 <= lat0 <= -34.0)

    def test_track_carries_gap_factor_for_run_family(self):
        """`gf` = C(pente)/C(0) (`arc_gap.gap_factor`) aligné sur les autres colonnes — la carte
        en tire son mode « GAP ». Le profil de `_write_fit` monte de 1 m tous les 15 m (6,7 %) puis
        retombe d'un coup : en pleine montée, le facteur est celui de cette pente."""
        track = json.loads(self.server.get(f"/api/activity/{self._activity_id_for(self.gps_id)}/track")[1])
        self.assertEqual(len(track["gf"]), track["points"])
        known = [v for v in track["gf"] if v is not None]
        self.assertGreater(len(known), track["points"] // 2)
        expected = G.gap_factor(1 / 15)
        self.assertGreater(expected, 1.0)
        close = [v for v in known if abs(v - expected) < 0.01]
        self.assertGreater(len(close), len(known) // 2)

    def test_track_is_capped_and_keeps_the_finish(self):
        aid = self._activity_id_for(self.long_id)
        track = json.loads(self.server.get(f"/api/activity/{aid}/track")[1])
        self.assertLessEqual(track["points"], 1501)
        full = json.loads(self.server.get(f"/api/activity/{aid}")[1])
        self.assertIsNotNone(full)
        self.assertEqual(track["t"][-1], max(t for t in track["t"] if t is not None))

    def test_points_parameter_lowers_the_cap(self):
        aid = self._activity_id_for(self.long_id)
        self.assertLessEqual(json.loads(self.server.get(f"/api/activity/{aid}/track?points=50")[1])["points"], 51)
        self.assertGreater(json.loads(self.server.get(f"/api/activity/{aid}/track?points=abc")[1])["points"], 1000)

    def test_track_without_gps_keeps_streams_but_no_coordinates(self):
        track = json.loads(self.server.get(f"/api/activity/{self._activity_id_for(self.indoor_id)}/track")[1])
        self.assertEqual(track["reason_code"], "no_gps")
        self.assertFalse(track["has_gps"])
        self.assertNotIn("lat", track)
        self.assertGreater(len(track["hr"]), 0)

    def test_track_without_samples(self):
        others = [a["id"] for a in json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]]
        with_fit = {self._activity_id_for(g) for g in (self.gps_id, self.indoor_id, self.long_id)}
        aid = next(i for i in others if i not in with_fit)
        track = json.loads(self.server.get(f"/api/activity/{aid}/track")[1])
        self.assertEqual(track["reason_code"], "no_samples")

    def test_unknown_activity_is_404(self):
        self.assertEqual(self.server.get("/api/activity/999999/track")[0], 404)

    def test_activity_detail_carries_session_gait_but_never_coordinates(self):
        status, body, _ = self.server.get(f"/api/activity/{self._activity_id_for(self.gps_id)}")
        payload = json.loads(body)
        gait = payload["gait"]
        self.assertAlmostEqual(gait["values"]["ground_contact_s"]["value"], 0.25, places=3)
        self.assertEqual(payload["pain"], [])
        # Seule `/track` expose une position (`arc_climb_match.ASSUMPTIONS["privacy"]`).
        self.assertNotIn(b'"lat"', body)
        self.assertNotIn(b'"lat_deg"', body)

    def test_default_tiles_are_allowed_by_csp(self):
        _, _, headers = self.server.get("/")
        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("img-src 'self' data: https://*.tile.opentopomap.org;", csp)
        settings = json.loads(self.server.get("/api/summary")[1])["settings"]
        self.assertIn("{z}", settings["map_tiles"])
        self.assertTrue(settings["map_attribution"])


class TestActivityTrackNoTiles(_TrackSandbox):
    user_toml_extra = '\n[dashboard]\nmap_tiles = ""\n'

    def test_empty_map_tiles_keeps_csp_local(self):
        _, _, headers = self.server.get("/")
        self.assertIn("img-src 'self' data:;", headers.get("Content-Security-Policy", ""))
        self.assertEqual(json.loads(self.server.get("/api/summary")[1])["settings"]["map_tiles"], "")
