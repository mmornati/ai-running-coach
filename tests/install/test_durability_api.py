"""Palier A — API durabilité sur les sorties longues (#48) sur un workspace de
bac à sable dédié.

Même motif que `test_descent_api.py` (#47) : plutôt que de modifier le fixture
golden partagé (`tests/data/golden/dashboard_api_*.json`, dont les sorties
longues synthétiques restent volontairement sous les 90 minutes de mouvement
requises), ce fichier construit son PROPRE petit workspace de bac à sable avec
une longue sortie FIT à fade connu (`tests.lib.synthetic.sample_session`, la
même vérité que `tests/data/test_arc_durability.py`) injectée à la main sur
une seule activité, et lance un vrai serveur (`Server`/`Sandbox`, même
infrastructure que `test_dashboard.py`) pour vérifier
`/api/activity/<id>.durability` et `/api/durability` de bout en bout.
"""

from __future__ import annotations

import datetime
import json
import re

from tests.install.test_dashboard import Server
from tests.lib.sandbox import Sandbox
from tests.lib.asserts import InstallAsserts
from tests.lib.synthetic import build, sample_session

TODAY = "2026-09-23"
LONG_DURATION_S = 6000  # 100 min > arc_metrics.LONG_RUN_MIN_DURATION_S (90 min)


def _write_durability_fit(ws, garmin_id: int) -> None:
    """Sortie longue plate à fade GAP de 8 % imposé (même générateur, mêmes
    paramètres que `tests/data/test_arc_durability.py::TestImposedFadeMatchesSyntheticGenerator`)
    — vérité connue, déterministe (`noise=False`)."""
    records, _truth = sample_session(seed=4, duration_s=LONG_DURATION_S, fade_pct=8.0, noise=False)
    fit_dir = ws / "activities/fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{garmin_id}.json").write_text(
        json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")


def _first_trail_garmin_id(ws) -> int:
    """`garmin_activity_id` de la première activité trail trouvée — jamais codé
    en dur, comme `test_descent_api.py::_first_trail_garmin_id`."""
    for path in sorted((ws / "activities").glob("*_trail.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'"garmin_activity_id":\s*(\d+)', text)
        if match:
            return int(match.group(1))
    raise AssertionError("aucune activité trail à garmin_activity_id dans le workspace de bac à sable")


class TestDurabilityApi(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=20, sport="trail", seed=5,
                         today=datetime.date.fromisoformat(TODAY))
        self.garmin_id = _first_trail_garmin_id(self.ws)
        _write_durability_fit(self.ws, self.garmin_id)
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

    def test_activity_detail_exposes_the_injected_fade(self):
        activity_id = self._activity_id()
        status, body, _ = self.server.get(f"/api/activity/{activity_id}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        durability = payload["durability"]
        self.assertIsNone(durability["reason"])
        self.assertIsNone(durability["reason_code"])
        self.assertTrue(durability["applicable"])
        self.assertIsNotNone(durability["gap_fade_pct"])
        self.assertAlmostEqual(durability["gap_fade_pct"], 8.0, delta=0.5)
        self.assertIsNotNone(durability["ef_fade_pct"])
        self.assertIsNotNone(durability["hr_first_third_bpm"])
        self.assertIsNotNone(durability["hr_middle_third_bpm"])
        self.assertIsNotNone(durability["hr_last_third_bpm"])
        # Colonnes brutes de l'activité (même discipline que `decoupling_pct`) :
        # exposées directement sur l'objet activité, pas seulement sous la clé
        # dédiée `durability`, pour que l'UI (fiche séance) les affiche comme un
        # fait de séance sans appel supplémentaire.
        self.assertAlmostEqual(payload["activity"]["durability_gap_fade_pct"], 8.0, delta=0.5)

    def test_durability_endpoint_reports_the_activity_in_its_trend(self):
        status, body, _ = self.server.get("/api/durability")
        self.assertEqual(status, 200)
        trend = json.loads(body)
        matches = [p for p in trend["points"] if p.get("gap_fade_pct") is not None]
        self.assertEqual(len(matches), 1, trend["points"])
        self.assertAlmostEqual(matches[0]["gap_fade_pct"], 8.0, delta=0.5)
        self.assertEqual(trend["measured_n"], 1)
        self.assertAlmostEqual(trend["avg_gap_fade_pct"], 8.0, delta=0.5)

    def test_non_run_activity_durability_has_an_explicit_reason_and_no_error(self):
        """Même discipline que `test_descent_api.py`/`test_vam_api.py` : une
        activité hors famille course à pied rend une `reason`/`reason_code`
        explicites (`applicable: false`) plutôt qu'un champ muet."""
        activities = json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]
        strength = next((a for a in activities if a["sport"] == "strength"), None)
        if strength is None:
            self.skipTest("aucune séance de renforcement dans ce workspace synthétique")
        payload = json.loads(self.server.get(f"/api/activity/{strength['id']}")[1])
        durability = payload["durability"]
        self.assertIsNone(durability["gap_fade_pct"])
        self.assertIsNotNone(durability["reason"])
        self.assertIn("course à pied", durability["reason"])
        self.assertEqual(durability["reason_code"], "not_run_family")
        self.assertFalse(durability["applicable"])

    def test_short_trail_activity_has_an_explicit_too_short_reason(self):
        """Une activité trail SANS le FIT injecté (donc trop courte pour être
        une sortie longue, ou sans échantillon du tout) rend une raison
        explicite plutôt qu'un champ muet — jamais confondue avec la réussite."""
        activities = json.loads(self.server.get("/api/activities?limit=500")[1])["activities"]
        other_trail = next((a for a in activities
                             if a["sport"] == "trail" and a["id"] != self._activity_id()), None)
        if other_trail is None:
            self.skipTest("une seule activité trail dans ce workspace synthétique")
        payload = json.loads(self.server.get(f"/api/activity/{other_trail['id']}")[1])
        durability = payload["durability"]
        self.assertIsNone(durability["gap_fade_pct"])
        self.assertIsNotNone(durability["reason"])
        self.assertTrue(durability["applicable"])
