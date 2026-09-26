"""Palier A — API efficacité en descente (#47) sur un workspace de bac à sable dédié.

Même motif que `test_vam_api.py` (#46) : plutôt que de modifier le fixture golden
partagé (`tests/data/golden/dashboard_api_*.json`, dont les collines synthétiques
restent volontairement sous les seuils de détection — voir
`tests/install/test_dashboard_golden.py::_write_fixed_fit_samples`), ce fichier
construit son PROPRE petit workspace de bac à sable avec une descente FIT injectée
à la main sur une seule activité, et lance un vrai serveur (`Server`/`Sandbox`,
même infrastructure que `test_dashboard.py`) pour vérifier
`/api/activity/<id>.descent` et `/api/descent` de bout en bout.
"""

from __future__ import annotations

import datetime
import json
import re

from tests.install.test_dashboard import Server
from tests.lib.sandbox import Sandbox
from tests.lib.asserts import InstallAsserts
from tests.lib.synthetic import build

TODAY = "2026-09-23"


def _write_descent_fit(ws, garmin_id: int, *, duration_s=600, grade=-0.12, speed_ms=3.0,
                        resolution_s=5, alt0=1000.0) -> None:
    """Descente linéaire déterministe (vérité connue : vitesse imposée) — écrite
    à la main comme `test_vam_api.py::_write_climb_fit`, jamais le générateur
    aléatoire `sample_session`, pour un résultat reproductible octet pour octet."""
    n = duration_s // resolution_s + 1
    records = []
    dist = 0.0
    alt = alt0
    for i in range(n):
        records.append({"t_s": float(i * resolution_s), "distance_m": round(dist, 2),
                         "altitude_m": round(alt, 2), "hr_bpm": 140.0,
                         "speed_ms": speed_ms, "cadence_spm": 165.0})
        dist += speed_ms * resolution_s
        alt += grade * speed_ms * resolution_s
    fit_dir = ws / "activities/fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{garmin_id}.json").write_text(
        json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")


def _first_trail_garmin_id(ws) -> int:
    """`garmin_activity_id` de la première activité trail trouvée — jamais codé
    en dur, comme `test_vam_api.py::_first_trail_garmin_id`."""
    for path in sorted((ws / "activities").glob("*_trail.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'"garmin_activity_id":\s*(\d+)', text)
        if match:
            return int(match.group(1))
    raise AssertionError("aucune activité trail à garmin_activity_id dans le workspace de bac à sable")


class TestDescentApi(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=20, sport="trail", seed=5,
                         today=datetime.date.fromisoformat(TODAY))
        self.garmin_id = _first_trail_garmin_id(self.ws)
        _write_descent_fit(self.ws, self.garmin_id)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def _activity_id(self) -> int:
        activities = json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]
        for a in activities:
            row = json.loads(self.server.get(f"/api/activity/{a['id']}")[1])
            if row["activity"].get("garmin_activity_id") == self.garmin_id:
                return a["id"]
        raise AssertionError(f"aucune activité indexée pour garmin_activity_id={self.garmin_id}")

    def test_activity_detail_exposes_the_injected_descent(self):
        activity_id = self._activity_id()
        status, body, _ = self.server.get(f"/api/activity/{activity_id}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        descent = payload["descent"]
        self.assertIsNone(descent["reason"])
        self.assertTrue(descent["classes"])
        self.assertIsNotNone(descent["reference_gap_pace_s_km"])
        for cls, v in descent["classes"].items():
            self.assertIsNotNone(v["efficiency"], cls)
            self.assertIsNotNone(v["mean_pace_s_km"], cls)

    def test_descent_endpoint_reports_the_activity_in_its_trend(self):
        status, body, _ = self.server.get("/api/descent")
        self.assertEqual(status, 200)
        trend = json.loads(body)
        matches = [p for p in trend["points"] if p.get("avg_efficiency") is not None]
        self.assertEqual(len(matches), 1, trend["points"])
        self.assertTrue(trend["classes"])

    def test_non_run_activity_descent_has_an_explicit_reason_and_no_error(self):
        """Même discipline que `test_vam_api.py`, should-fix 5 de #46 : une
        activité hors famille course à pied rend une `reason` explicite plutôt
        qu'un `classes: {}` muet."""
        activities = json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]
        strength = next((a for a in activities if a["sport"] == "strength"), None)
        if strength is None:
            self.skipTest("aucune séance de renforcement dans ce workspace synthétique")
        payload = json.loads(self.server.get(f"/api/activity/{strength['id']}")[1])
        descent = payload["descent"]
        self.assertEqual(descent["classes"], {})
        self.assertIsNotNone(descent["reason"])
        self.assertIn("course à pied", descent["reason"])
