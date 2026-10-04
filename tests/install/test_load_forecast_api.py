"""Palier A — `/api/load-forecast` (#172) sur un workspace de bac à sable et un vrai serveur.

Un historique de 130 jours (au-delà du plancher d'historique de R1, 84 j) + la semaine courante
planifiée du workspace synthétique + son objectif : la projection est calculable. Avec un historique
court, l'API dit l'état honnête (`insufficient_history`) au lieu d'inventer un chiffre. Le golden du
tableau de bord (`test_dashboard_golden.py`) verrouille de son côté la forme sur le workspace court.
"""

from __future__ import annotations

import datetime
import json
import re

from tests.install.test_dashboard import Server
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-09-24"


class TestLoadForecastApi(InstallAsserts):
    server = None

    def tearDown(self):
        if self.server:
            self.server.stop()

    def _serve(self, days):
        sb = Sandbox().__enter__()
        self.addCleanup(sb.__exit__, None, None, None)
        ws = build(sb.root / "ws", days=days, sport="trail", seed=12345, today=datetime.date.fromisoformat(TODAY))
        self.server = Server(sb, ["python3", str(sb.repo / "scripts/arc_serve.py"), "--workspace", str(ws),
                                  "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url)
        return ws

    def _get(self, path):
        status, body, _ = self.server.get(path)
        return status, json.loads(body)

    def test_projection_with_long_history(self):
        ws = self._serve(130)
        status, data = self._get("/api/load-forecast")
        self.assertEqual(status, 200)
        objective = (ws / "planning/active_objective.md").read_text(encoding="utf-8")
        race = re.search(r"\*\*Date\*\* : (\d{4}-\d{2}-\d{2})", objective).group(1)
        self.assertEqual(data["race_date"], race)
        self.assertTrue(data["is_estimate"])
        self.assertIn(data["status"], ("ok", "target_past", "no_plan"))
        if data["status"] == "ok":
            self.assertEqual(data["race_day"]["date"], race)
            self.assertTrue(data["series"][-1]["projected"])
            self.assertGreaterEqual(data["weeks_unplanned"], 0)
        text = json.dumps(data)
        self.assertIsNone(re.search(r"\b(CTL|ATL|TSB|TSS)\b", text))
        self.assertNotIn(str(ws), text)

    def test_until_parameter_and_invalid_date(self):
        self._serve(130)
        status, data = self._get("/api/load-forecast?until=2026-09-27")
        self.assertEqual(status, 200)
        self.assertEqual(data["target_date"], "2026-09-27")
        self.assertEqual(data["status"], "ok")
        self.assertIsNone(data["race_day"])
        self.assertEqual(data["end"]["date"], "2026-09-27")
        status, bad = self._get("/api/load-forecast?until=nimporte")
        self.assertEqual(status, 200)
        self.assertEqual(bad["status"], "invalid_until")

    def test_short_history_is_honest(self):
        self._serve(40)
        status, data = self._get("/api/load-forecast")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "insufficient_history")
        self.assertNotIn("race_day", data)
        self.assertIn("84", data["reason"])
