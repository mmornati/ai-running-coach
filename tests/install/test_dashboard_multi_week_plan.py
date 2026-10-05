"""Palier A — vue Semaine sur un plan multi-semaines (#69).

Le tableau de bord (`/api/week`) doit lire un fichier `planning/Semaine_*.md`
qui porte PLUSIEURS semaines (`weeks[]`) exactement comme un fichier par
semaine : une entrée par lundi, retrouvée par sa propre date. Le serveur tourne
pour de vrai (comme `tests/install/test_dashboard.py`), sur le workspace
synthétique standard (`tests/lib/synthetic.build`) auquel on ajoute, APRÈS
démarrage, un fichier multi-semaines écrit à la main — sans toucher aux
fichiers `planning/Semaine_*.md` du golden existant (`tests/data/golden/
dashboard_api_*.json`, tier A #28) : cette histoire n'y touche pas, ses
assertions vivent dans ce fichier séparé.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from tests.install.test_dashboard import Server
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

TODAY = "2026-09-23"
CURRENT_MONDAY = date.fromisoformat(TODAY) - timedelta(days=date.fromisoformat(TODAY).weekday())  # 2026-09-21


def _week_block(week_start: str, sessions: list, **extra) -> dict:
    return {"week_start": week_start, "location": "Tournai", "sessions": sessions, **extra}


class TestMultiWeekPlanView(InstallAsserts):
    """`build()` (jours=14) écrit déjà `planning/Semaine_<CURRENT_MONDAY>.md` (semaine
    courante, fichier DÉDIÉ) — on ajoute un plan multi-semaines distinct qui couvre
    deux semaines FUTURES, non écrites par `build()` (aucune collision), pour
    verrouiller l'éclatement par semaine sans dépendre du golden existant."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=14,
                        today=date.fromisoformat(TODAY))
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY],
                             ARC_DASHBOARD_REFRESH_S="0")
        self.assertIsNotNone(self.server.url,
                              self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def _ok_files(self) -> int:
        return json.loads(self.server.get("/api/summary")[1])["files"].get("ok", 0)

    def _write_multi_week_plan(self, rel: str, weeks: list) -> None:
        """Écrit le plan PUIS attend que le fil d'index l'ait pris en compte.

        Une requête ne réindexe jamais (`Store`, verrouillé par
        `tests/data/test_arc_serve_perf.test_requests_never_trigger_a_reindex`) :
        le fichier n'apparaît qu'au passage SUIVANT du fil d'arrière-plan. Lire
        aussitôt après l'écriture faisait dépendre le test d'une course — gagnée
        seulement si l'écriture tombait dans le premier index, avant que
        `discover()` n'ait parcouru `planning/` (instable sur `macos-latest`).
        Écriture atomique (`os.replace`) : le fil ne lit jamais un fichier à
        moitié écrit ; attente bornée sur le compte de fichiers au contrat."""
        before = self._ok_files()
        block = {"arc": 1, "kind": "week", "weeks": weeks}
        target = self.ws / rel
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(
            f"# Plan multi-semaines\n\n```arc\n{json.dumps(block, ensure_ascii=False)}\n```\n\nTexte du coach.\n",
            encoding="utf-8")
        os.replace(tmp, target)
        deadline = time.monotonic() + 15
        while self._ok_files() <= before:
            self.assertLess(time.monotonic(), deadline, f"{rel} jamais indexé par le fil d'arrière-plan")
            time.sleep(0.05)

    def test_each_week_of_a_multi_week_file_is_served_individually(self):
        week1 = (CURRENT_MONDAY + timedelta(weeks=3)).isoformat()
        week2 = (CURRENT_MONDAY + timedelta(weeks=4)).isoformat()
        self._write_multi_week_plan("planning/Semaine_multi.md", [
            _week_block(week1, [{"date": (date.fromisoformat(week1) + timedelta(days=1)).isoformat(),
                                  "sport": "running", "title": "Footing S+3",
                                  "planned_duration_s": 3000, "intensity": "endurance", "status": "planned"}],
                        phase="Transition"),
            _week_block(week2, [{"date": (date.fromisoformat(week2) + timedelta(days=3)).isoformat(),
                                  "sport": "trail", "title": "Sortie longue S+4",
                                  "planned_distance_m": 26000, "intensity": "endurance", "status": "planned"}],
                        phase="Transition"),
        ])

        status, body, _ = self.server.get(f"/api/week?start={week1}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["week"]["week_start"], week1)
        self.assertEqual(payload["week"]["phase"], "Transition")
        self.assertEqual([s["title"] for s in payload["sessions"]], ["Footing S+3"])

        status, body, _ = self.server.get(f"/api/week?start={week2}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["week"]["week_start"], week2)
        self.assertEqual([s["title"] for s in payload["sessions"]], ["Sortie longue S+4"])
        # Les deux semaines apparaissent dans la liste des semaines connues.
        self.assertIn(week1, payload["known_weeks"])
        self.assertIn(week2, payload["known_weeks"])
        # `shadowed` (#69, revue de code, nit) : toujours 0 ici (déjà filtré côté
        # SQL) — ne doit jamais être sérialisé dans la réponse HTTP.
        self.assertNotIn("shadowed", payload["week"])
        self.assertTrue(all("shadowed" not in s for s in payload["sessions"]))

    def test_dedicated_file_wins_over_colliding_multi_week_entry(self):
        """`build()` a déjà écrit `planning/Semaine_<CURRENT_MONDAY>.md` (fichier
        DÉDIÉ de la semaine courante). Un plan multi-semaines qui la recouvre
        incidemment ne doit JAMAIS masquer les séances du fichier dédié dans
        `/api/week` — priorité au fichier dédié (#69, voir SKILL.md)."""
        current = CURRENT_MONDAY.isoformat()
        self._write_multi_week_plan("planning/Semaine_avant.md", [
            _week_block(current, [{"date": current, "sport": "running", "title": "INTRUS — ne doit pas apparaître",
                                    "intensity": "endurance", "status": "planned"}]),
        ])
        status, body, _ = self.server.get(f"/api/week?start={current}")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        titles = [s["title"] for s in payload["sessions"]]
        self.assertNotIn("INTRUS — ne doit pas apparaître", titles)
        self.assertGreater(len(titles), 0, "la semaine dédiée du golden a bien ses propres séances")

        # L'écart reste visible côté fichiers (#69, `issues`/backfill) : le fichier
        # perdant continue à exister, il est seulement écarté de la vue Semaine.
        files = json.loads(self.server.get("/api/files")[1])["items"]
        avant = next(item for item in files if item["path"] == "planning/Semaine_avant.md")
        self.assertTrue(any("collision" in issue for issue in avant["issues"]), avant["issues"])
        # Revue de code (2e tour) : ce fichier est déjà VALIDE au contrat (une
        # collision, pas une dette de contrat) — `collision` doit le dire, et
        # `/api/summary` ne doit jamais le compter dans `incomplete_files`
        # (« N fichier(s) hors contrat »), un libellé qui serait faux ici.
        self.assertTrue(avant["collision"])
        summary = json.loads(self.server.get("/api/summary")[1])
        self.assertEqual(summary["incomplete_files"], 0)
        self.assertEqual(summary["week_collisions_count"], 1)
