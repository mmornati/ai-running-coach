"""Palier A — roadbook imprimable (#187) : `/api/roadbook` et page `#/roadbook` servies pour de vrai.

Un vrai `arc_serve.py` sur un workspace synthétique auquel on ajoute un plan de course issu du vrai
`arc_race_pacing` (`tests/lib/roadbook_plan.py`). Vérifie le modèle servi (sections, passages,
barrières, nuit, matériel), la sélection du plan/scénario, les cas d'absence, et que les fichiers
statiques de la page (JS, feuille d'impression A4) sont bien servis sous la CSP du tableau de bord.
"""

from __future__ import annotations

import datetime
import json
import re

from tests.install.test_dashboard import Server
from tests.lib import roadbook_plan as R
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-06-12"


class _RoadbookSandbox(InstallAsserts):
    with_plan = True

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=20, sport="trail", seed=7,
                        today=datetime.date.fromisoformat(TODAY))
        if self.with_plan:
            (self.ws / "planning/2026-06-10_plan_course.md").write_text(
                R.plan_markdown(R.persisted_plan()), encoding="utf-8")
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def roadbook(self, query=""):
        status, body, _ = self.server.get(f"/api/roadbook{query}")
        return status, json.loads(body)


class TestRoadbookApi(_RoadbookSandbox):
    def test_default_plan_serves_the_three_scenarios(self):
        status, rb = self.roadbook()
        self.assertEqual(status, 200)
        self.assertEqual(rb["status"], "ok")
        self.assertEqual(rb["plan"], "planning/2026-06-10_plan_course.md")
        self.assertEqual(rb["header"]["race_name"], R.RACE_NAME)
        self.assertEqual(rb["header"]["start_clock"], "16:00")
        for s in ("safe", "realistic", "ambitious"):
            sc = rb["scenarios"][s]
            self.assertTrue(sc["available"])
            self.assertEqual([r["to_name"] for r in sc["sections"]], ["Ravito du Col", "Base de vie", "Arrivée"])
        self.assertEqual(rb["scenarios"]["realistic"]["sections"][0]["cutoff"]["status"], "tendu")
        self.assertEqual(rb["scenarios"]["realistic"]["sections"][1]["night"], "full")
        self.assertEqual(rb["plans"], [{"path": "planning/2026-06-10_plan_course.md",
                                        "race_name": R.RACE_NAME, "race_date": R.RACE_DATE}])

    def test_gear_is_checked_against_the_inventory(self):
        _, rb = self.roadbook()
        entries = {e["entry"]: e["status"] for e in rb["gear"]["entries"]}
        self.assertEqual(set(entries), {"Frontale", "Couverture de survie", "Gobelet"})
        # inventaire synthétique sans ces objets : jamais « ok » par défaut
        self.assertTrue(all(v in ("missing", "category_match", "never_used", "alert") for v in entries.values()), entries)
        self.assertEqual(rb["emergency"], R.persisted_plan()["emergency"])

    def test_scenario_param_keeps_only_that_scenario(self):
        _, rb = self.roadbook("?scenario=safe")
        self.assertEqual(list(rb["scenarios"]), ["safe"])
        self.assertEqual(rb["default_scenario"], "safe")

    def test_unknown_scenario_falls_back_to_all_with_a_warning(self):
        _, rb = self.roadbook("?scenario=nope")
        self.assertEqual(len(rb["scenarios"]), 3)
        self.assertTrue(any("nope" in w for w in rb["warnings"]))

    def test_plan_param_selects_by_path_and_unknown_plan_is_reported(self):
        _, rb = self.roadbook("?plan=planning/2026-06-10_plan_course.md")
        self.assertEqual(rb["status"], "ok")
        status, rb = self.roadbook("?plan=planning/absent.md")
        self.assertEqual(status, 200)
        self.assertEqual(rb["status"], "plan_not_found")
        self.assertEqual(len(rb["plans"]), 1)

    def test_page_assets_are_served_under_the_csp(self):
        status, body, headers = self.server.get("/js/roadbook.js")
        self.assertEqual(status, 200)
        self.assertIn(b"window.print()", body)
        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        _, css, _ = self.server.get("/css/app.css")
        css = css.decode("utf-8")
        self.assertIn("@page { size: A4 portrait", css)
        self.assertRegex(css, r"@media print\s*\{")
        # aucune écriture dans le workspace : l'API roadbook est en lecture seule
        self.assertEqual(self.server.get("/api/roadbook", method="POST")[0], 405)

    def test_roadbook_js_has_no_inline_style_or_external_url(self):
        _, body, _ = self.server.get("/js/roadbook.js")
        js = body.decode("utf-8")
        self.assertNotRegex(js, r"\sstyle\s*=")
        self.assertNotRegex(js, r"https?://")
        self.assertNotRegex(js, r"\beval\(|new Function\(")
        self.assertTrue(re.search(r"window\.print\(\)", js))


class TestRoadbookWithoutPlan(_RoadbookSandbox):
    with_plan = False

    def test_no_plan_is_explicit(self):
        status, rb = self.roadbook()
        self.assertEqual(status, 200)
        self.assertEqual(rb["status"], "no_plan")
        self.assertEqual(rb["plans"], [])
        self.assertIn("course-strategist", rb["message"])
