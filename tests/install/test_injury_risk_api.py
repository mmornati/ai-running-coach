"""Palier A — API du drapeau composite de risque de blessure (#57) sur un
workspace de bac à sable dédié.

Même motif que `test_decisions_api.py` : plutôt qu'un golden fragile (la
sortie dépend d'un historique réel qui varie avec `days`/`seed`), ce fichier
vérifie la FORME de `/api/injury-risk` (niveau valide, facteurs, disclaimer
non-diagnostique) et qu'une douleur déclarée via le champ contractuel
`health.pain` fait bien apparaître un facteur `pain` qui contribue.
"""

from __future__ import annotations

import datetime
import json

from tests.install.test_dashboard import Server
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-09-24"


class TestInjuryRiskApi(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        self.ws = build(self.sb.root / "ws", days=40, sport="trail", seed=12345,
                        today=datetime.date.fromisoformat(TODAY))
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.stop()

    def _start_server(self):
        # `ARC_DASHBOARD_REFRESH_S="0"` (même motif que
        # `test_dashboard.test_new_file_appears_without_restart`) : un test écrit
        # un fichier santé APRÈS le démarrage du serveur (douleur déclarée), il a
        # donc besoin d'une réindexation à chaque requête plutôt que la fenêtre de
        # 30 s par défaut.
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY],
                             ARC_DASHBOARD_REFRESH_S="0")
        self.assertIsNotNone(self.server.url,
                             self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def _get_json(self, path):
        status, body, _ = self.server.get(path)
        return status, (json.loads(body) if body else None)

    def test_returns_a_valid_level_with_factors_and_disclaimer(self):
        self._start_server()
        status, payload = self._get_json("/api/injury-risk")
        self.assertEqual(status, 200)
        self.assertIn(payload["level"], ("low", "moderate", "high"))
        self.assertIsInstance(payload["factors"], list)
        self.assertTrue(payload["factors"])
        for factor in payload["factors"]:
            self.assertIn("id", factor)
            self.assertIn("contributes", factor)
        self.assertIn("signal de vigilance", payload["disclaimer"].lower())
        self.assertNotIn(str(self.ws), json.dumps(payload))

    def test_declared_pain_contributes_to_the_flag(self):
        (self.ws / f"medical/{TODAY}_health.md").write_text(
            "# Santé\n\n```arc\n"
            + json.dumps({"arc": 1, "kind": "health", "date": TODAY, "morning_check": "full",
                          "pain": [{"location": "genou droit", "score": 8}],
                          "verdict": "amber", "verdict_reason": "Douleur au genou signalée."})
            + "\n```\n\nDouleur au genou signalée ce matin.\n",
            encoding="utf-8",
        )
        self._start_server()
        status, payload = self._get_json("/api/injury-risk")
        self.assertEqual(status, 200)
        self.assertIn(payload["level"], ("moderate", "high"))
        pain_factor = next(f for f in payload["factors"] if f["id"] == "pain")
        self.assertTrue(pain_factor["contributes"])
        self.assertEqual(pain_factor["observed"], 8)
