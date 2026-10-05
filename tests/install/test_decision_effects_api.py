"""Palier A — `/api/decision-effects` (#175) de bout en bout sur le workspace synthétique.

Même infrastructure que `test_decisions_api.py` : vrai serveur, bac à sable. Le jeu de décisions
synthétique est RÉCENT (la plus ancienne date d'il y a < 10 jours) : la plupart des fenêtres ne sont
pas écoulées, d'où des `insufficient_data` honnêtes plutôt qu'un effet inventé.
"""

from __future__ import annotations

import datetime
import json

from tests.install.test_dashboard import Server
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-09-23"


class TestDecisionEffectsApi(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        self.ws = build(self.sb.root / "ws", days=40, sport="trail", seed=12345,
                        today=datetime.date.fromisoformat(TODAY))
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.addCleanup(self.server.stop)
        self.assertIsNotNone(self.server.url,
                             self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def _get(self, path):
        status, body, _ = self.server.get(path)
        return status, (json.loads(body) if body else None)

    def test_shape_and_caveat(self):
        status, payload = self._get("/api/decision-effects")
        self.assertEqual(status, 200)
        self.assertEqual(payload["days"], 180)
        self.assertEqual(payload["min_sample_for_trend"], 5)
        self.assertIn("Corrélation, pas causalité", payload["caveat"])
        self.assertNotIn(str(self.ws), json.dumps(payload))
        decisions = self._get("/api/decisions?all=1")[1]["decisions"]
        self.assertEqual({e["id"] for e in payload["effects"]}, {d["id"] for d in decisions})
        for ev in payload["effects"]:
            self.assertIn(ev["effect"], ("improved", "neutral", "worsened", "insufficient_data"))

    def test_proposed_and_superseded_are_insufficient_with_reason(self):
        _, payload = self._get("/api/decision-effects")
        for ev in payload["effects"]:
            if ev["outcome"] in ("proposed", "superseded"):
                self.assertEqual(ev["effect"], "insufficient_data")
                self.assertEqual(ev["reason_code"], ev["outcome"])

    def test_small_samples_never_carry_a_trend(self):
        _, payload = self._get("/api/decision-effects")
        for group in payload["synthesis"]:
            self.assertFalse(group["trend_allowed"])
            self.assertIsNone(group["trend"])

    def test_trigger_filter_and_bad_trigger_ignored(self):
        _, payload = self._get("/api/decision-effects?trigger=guardrail")
        self.assertTrue(payload["effects"])
        self.assertTrue(all(e["trigger"] == "guardrail" for e in payload["effects"]))
        status, payload = self._get("/api/decision-effects?trigger=n-importe-quoi")
        self.assertEqual(status, 200)
        self.assertIsNone(payload["trigger"])

    def test_days_window(self):
        _, payload = self._get("/api/decision-effects?days=1")
        self.assertEqual(payload["days"], 1)
        self.assertTrue(all(e["date"] == TODAY for e in payload["effects"]))
