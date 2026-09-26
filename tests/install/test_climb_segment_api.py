"""Palier A — API identité de montée entre séances (#49) sur un workspace de bac à
sable dédié — même discipline que `test_vam_api.py` (#46) : son propre petit
workspace avec deux montées FIT injectées à la main (même trace GPS, la seconde 5 %
plus rapide) plutôt que d'alourdir le golden partagé (`tests/install/
test_dashboard_golden.py`), dont les collines synthétiques restent volontairement sous
les seuils de détection. Coordonnées FICTIVES (Pacifique Sud, loin de toute côte — voir
`tests/lint/test_synthetic_no_real_data.py::SAFE_LAT_RANGE`/`SAFE_LON_RANGE`).
"""

from __future__ import annotations

import datetime
import json
import re

from tests.install.test_dashboard import Server
from tests.lib.sandbox import Sandbox
from tests.lib.asserts import InstallAsserts
from tests.lib.synthetic import build

TODAY = "2026-09-26"


def _write_climb_fit(ws, garmin_id: int, *, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                      start_lat=-40.0, start_lon=-135.0, bearing=(0.01, 0.01), resolution_s=5) -> None:
    """Montée linéaire déterministe avec une trace GPS explicite — même construction
    que `test_vam_api.py::_write_climb_fit`, avec `lat_deg`/`lon_deg` en plus (#49)."""
    n = duration_s // resolution_s + 1
    speed = distance_m / duration_s
    dlat, dlon = bearing
    records = []
    for i in range(n):
        t = i * resolution_s
        frac = min(1.0, t / duration_s)
        records.append({"t_s": float(t), "distance_m": round(distance_m * frac, 2),
                         "altitude_m": round(gain_m * frac, 2), "hr_bpm": 150.0,
                         "speed_ms": speed, "cadence_spm": 160.0,
                         "lat_deg": start_lat + dlat * frac, "lon_deg": start_lon + dlon * frac})
    fit_dir = ws / "activities/fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{garmin_id}.json").write_text(
        json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")


def _trail_garmin_ids(ws) -> list[int]:
    ids = []
    for path in sorted((ws / "activities").glob("*_trail.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'"garmin_activity_id":\s*(\d+)', text)
        if match:
            ids.append(int(match.group(1)))
    return ids


class TestClimbSegmentApi(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=25, sport="trail", seed=5,
                         today=datetime.date.fromisoformat(TODAY))
        garmin_ids = _trail_garmin_ids(self.ws)
        self.assertGreaterEqual(len(garmin_ids), 2, "il faut au moins deux séances trail dans ce bac à sable")
        self.garmin_a, self.garmin_b = garmin_ids[0], garmin_ids[1]
        # Même montée (même trace GPS), la seconde 5 % plus rapide (1710 s vs 1800 s) —
        # critère d'acceptation de #49.
        _write_climb_fit(self.ws, self.garmin_a, duration_s=1800)
        _write_climb_fit(self.ws, self.garmin_b, duration_s=1710)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def _activity_id_for(self, garmin_id: int) -> int:
        activities = json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]
        for a in activities:
            row = json.loads(self.server.get(f"/api/activity/{a['id']}")[1])
            if row["activity"].get("garmin_activity_id") == garmin_id:
                return a["id"]
        raise AssertionError(f"aucune activité indexée pour garmin_activity_id={garmin_id}")

    def test_activity_detail_exposes_segment_id_and_no_progression_on_first_occurrence(self):
        activity_id = self._activity_id_for(self.garmin_a)
        status, body, _ = self.server.get(f"/api/activity/{activity_id}")
        self.assertEqual(status, 200)
        climbs = json.loads(body)["climbs"]["climbs"]
        self.assertEqual(len(climbs), 1)
        self.assertIsNotNone(climbs[0]["segment_id"])
        self.assertIsNone(climbs[0]["vs_previous_pct"])
        self.assertIsNone(climbs[0]["vs_best_pct"])
        # Confidentialité (#49) : jamais de coordonnée brute dans la réponse HTTP — clé
        # JSON entre guillemets (jamais une sous-chaîne nue : "plat"/"Montée" contiennent
        # eux-mêmes "lat"/"lon", faux positifs sans rapport avec une coordonnée GPS).
        self.assertNotIn(b'"lat"', body)
        self.assertNotIn(b'"lon"', body)
        self.assertNotIn(b'"lat_deg"', body)
        self.assertNotIn(b'"lon_deg"', body)

    def test_second_occurrence_reports_five_percent_progression(self):
        id_a = self._activity_id_for(self.garmin_a)
        id_b = self._activity_id_for(self.garmin_b)
        climbs_a = json.loads(self.server.get(f"/api/activity/{id_a}")[1])["climbs"]["climbs"]
        climbs_b = json.loads(self.server.get(f"/api/activity/{id_b}")[1])["climbs"]["climbs"]
        self.assertEqual(climbs_a[0]["segment_id"], climbs_b[0]["segment_id"])
        self.assertAlmostEqual(climbs_b[0]["vs_previous_pct"], 5.0, delta=0.5)
        self.assertAlmostEqual(climbs_b[0]["vs_best_pct"], 5.0, delta=0.5)

    def test_climb_segments_endpoint_lists_the_shared_segment(self):
        status, body, _ = self.server.get("/api/climb-segments")
        self.assertEqual(status, 200)
        segments = json.loads(body)["segments"]
        matching = [s for s in segments if s["occurrences"] >= 2]
        self.assertEqual(len(matching), 1, segments)
        self.assertEqual(matching[0]["occurrences"], 2)
        # Confidentialité (#49) : id + lieu + profil seulement, jamais de coordonnée (clé
        # JSON entre guillemets, voir le commentaire ci-dessus).
        self.assertNotIn(b'"lat"', body)
        self.assertNotIn(b'"lon"', body)

    def test_climb_segment_history_endpoint_lists_both_occurrences_in_date_order(self):
        segments = json.loads(self.server.get("/api/climb-segments")[1])["segments"]
        segment_id = next(s["segment_id"] for s in segments if s["occurrences"] >= 2)
        status, body, _ = self.server.get(f"/api/climb-segment/{segment_id}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIsNone(payload["reason"])
        self.assertEqual(len(payload["occurrences"]), 2)
        dates = [o["date"] for o in payload["occurrences"]]
        self.assertEqual(dates, sorted(dates))
        self.assertIsNone(payload["occurrences"][0]["vs_previous_pct"])
        self.assertAlmostEqual(payload["occurrences"][1]["vs_previous_pct"], 5.0, delta=0.5)

    def test_unknown_segment_id_has_an_explicit_reason_not_a_500(self):
        status, body, _ = self.server.get("/api/climb-segment/999999")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIsNone(payload["segment"])
        self.assertEqual(payload["reason_code"], "unknown_segment")
