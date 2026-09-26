"""Palier A — API VAM (#46) sur un workspace de bac à sable dédié.

Revue de code #46 (nit) : plutôt que de modifier le fixture golden partagé
(`tests/data/golden/dashboard_api_*.json`, dont les collines synthétiques
restent volontairement sous les seuils de détection — voir
`tests/install/test_dashboard_golden.py::_fixed_altitude_m`), ce fichier
construit son PROPRE petit workspace de bac à sable avec une montée FIT
injectée à la main sur une seule activité, et lance un vrai serveur
(`Server`/`Sandbox`, même infrastructure que `test_dashboard.py`) pour
vérifier `/api/activity/<id>.climbs` et `/api/vam` de bout en bout — sans
alourdir le golden pour un cas qui n'a besoin que de son propre fixture.
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


def _write_climb_fit(ws, garmin_id: int, *, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                      resolution_s=5) -> None:
    """Montée linéaire déterministe (vérité connue : gain/durée = VAM imposée),
    écrite à la main comme `test_dashboard_golden.py::_write_fixed_fit_samples`
    — jamais le générateur aléatoire `sample_session`, pour un résultat
    reproductible octet pour octet."""
    n = duration_s // resolution_s + 1
    speed = distance_m / duration_s
    records = []
    for i in range(n):
        t = i * resolution_s
        frac = min(1.0, t / duration_s)
        records.append({"t_s": float(t), "distance_m": round(distance_m * frac, 2),
                         "altitude_m": round(gain_m * frac, 2), "hr_bpm": 150.0,
                         "speed_ms": speed, "cadence_spm": 160.0})
    fit_dir = ws / "activities/fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{garmin_id}.json").write_text(
        json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")


def _first_trail_garmin_id(ws) -> int:
    """`garmin_activity_id` de la première activité trail trouvée — jamais codé
    en dur, comme `test_dashboard_golden.py::_write_fixed_fit_samples`."""
    for path in sorted((ws / "activities").glob("*_trail.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'"garmin_activity_id":\s*(\d+)', text)
        if match:
            return int(match.group(1))
    raise AssertionError("aucune activité trail à garmin_activity_id dans le workspace de bac à sable")


class TestVamApi(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=20, sport="trail", seed=3,
                         today=datetime.date.fromisoformat(TODAY))
        self.garmin_id = _first_trail_garmin_id(self.ws)
        _write_climb_fit(self.ws, self.garmin_id)
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

    def test_activity_detail_exposes_the_injected_climb(self):
        activity_id = self._activity_id()
        status, body, _ = self.server.get(f"/api/activity/{activity_id}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        climbs = payload["climbs"]
        self.assertIsNone(climbs["reason"])
        self.assertEqual(len(climbs["climbs"]), 1)
        climb = climbs["climbs"][0]
        self.assertAlmostEqual(climb["vam_elapsed_m_h"], 600.0, delta=15.0)
        self.assertEqual(climb["grade_class"], "5-10%")
        self.assertIn("5-10%", climbs["vam_by_grade_class"])

    def test_vam_endpoint_reports_the_activity_in_its_trend(self):
        status, body, _ = self.server.get("/api/vam")
        self.assertEqual(status, 200)
        trend = json.loads(body)
        matches = [p for p in trend["points"] if p.get("best_climb_vam_elapsed_m_h") is not None]
        self.assertEqual(len(matches), 1, trend["points"])
        self.assertAlmostEqual(matches[0]["best_climb_vam_elapsed_m_h"], 600.0, delta=15.0)
        self.assertGreaterEqual(trend["best_vam_10min_m_h"], 500.0)

    def test_non_run_activity_climbs_have_an_explicit_reason_and_no_error(self):
        """Revue de code #46, should-fix 5 : une activité hors famille course à pied
        rend une `reason` explicite plutôt qu'un `climbs: []` muet."""
        # `build()` (profil trail) écrit toujours au moins une séance de renforcement.
        activities = json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]
        strength = next((a for a in activities if a["sport"] == "strength"), None)
        if strength is None:
            self.skipTest("aucune séance de renforcement dans ce workspace synthétique")
        payload = json.loads(self.server.get(f"/api/activity/{strength['id']}")[1])
        climbs = payload["climbs"]
        self.assertEqual(climbs["climbs"], [])
        self.assertIsNotNone(climbs["reason"])
        self.assertIn("course à pied", climbs["reason"])
