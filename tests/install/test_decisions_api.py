"""Palier A — API du journal des décisions (#55) sur un workspace de bac à sable dédié.

Même motif que `test_descent_api.py`/`test_vam_api.py` : plutôt que d'alourdir le
fixture golden partagé, ce fichier construit son propre petit workspace synthétique
(`tests.lib.synthetic.build`, qui écrit désormais un jeu de décisions déterministe
dès que `days >= 10`, voir son docstring) et lance un vrai serveur
(`Server`/`Sandbox`, même infrastructure que `test_dashboard.py`) pour vérifier
`/api/decisions` et `/api/decision/<id>` de bout en bout : filtres (déclencheur,
résultat, fenêtre glissante), exclusion `active`, détail (règles, sources
résolues, chaîne `supersedes`), 404 sur un id inconnu et refus d'une tentative de
remontée de répertoire glissée dans l'id d'URL.
"""

from __future__ import annotations

import datetime
import json

from tests.install.test_dashboard import Server
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import _block, build

TODAY = "2026-09-23"


class TestDecisionsApi(InstallAsserts):
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

    def _get_json(self, path):
        status, body, _ = self.server.get(path)
        return status, (json.loads(body) if body else None)

    # -- liste -----------------------------------------------------------

    def test_lists_all_decisions_newest_first(self):
        status, payload = self._get_json("/api/decisions")
        self.assertEqual(status, 200)
        decisions = payload["decisions"]
        self.assertEqual(len(decisions), 4)
        dates = [d["date"] for d in decisions]
        self.assertEqual(dates, sorted(dates, reverse=True))
        # Aucun chemin absolu du bac à sable ne doit fuiter dans la réponse.
        self.assertNotIn(str(self.ws), json.dumps(payload))

    def test_filters_by_trigger(self):
        status, payload = self._get_json("/api/decisions?trigger=guardrail")
        self.assertEqual(status, 200)
        self.assertTrue(payload["decisions"])
        for d in payload["decisions"]:
            self.assertEqual(d["trigger"], "guardrail")

    def test_filters_by_outcome(self):
        status, payload = self._get_json("/api/decisions?outcome=proposed")
        self.assertEqual(status, 200)
        self.assertTrue(payload["decisions"])
        for d in payload["decisions"]:
            self.assertEqual(d["outcome"], "proposed")

    def test_active_excludes_superseded(self):
        status, all_payload = self._get_json("/api/decisions")
        status_active, active_payload = self._get_json("/api/decisions?active=1")
        self.assertEqual(status, 200)
        self.assertEqual(status_active, 200)
        self.assertGreater(len(all_payload["decisions"]), len(active_payload["decisions"]))
        for d in active_payload["decisions"]:
            self.assertNotEqual(d["outcome"], "superseded")

    def test_days_window(self):
        status, payload = self._get_json("/api/decisions?days=2")
        self.assertEqual(status, 200)
        for d in payload["decisions"]:
            self.assertGreaterEqual(d["date"], "2026-09-22")

    def test_each_item_carries_resolved_rules_and_sources(self):
        status, payload = self._get_json("/api/decisions?trigger=guardrail&outcome=applied")
        self.assertEqual(status, 200)
        decision = payload["decisions"][0]
        self.assertEqual(decision["rules"][0]["rule_id"], "r1_acwr_projected")
        self.assertIn("ACWR", decision["rules"][0]["label"])
        self.assertEqual(decision["rules"][0]["default_severity"], "warn")
        self.assertTrue(decision["rules"][0]["doc_url"].startswith("https://"))
        self.assertEqual(decision["source_links"][0]["kind"], "health")
        self.assertEqual(decision["source_links"][0]["route"], "#/sante")

    # -- détail ------------------------------------------------------------

    def test_detail_of_todays_decision(self):
        status, payload = self._get_json("/api/decisions")
        today_decision = next(d for d in payload["decisions"] if d["date"] == TODAY)
        status, detail = self._get_json(f"/api/decision/{today_decision['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["trigger"], "morning_check")
        self.assertEqual(detail["outcome"], "applied")
        self.assertEqual(detail["before"]["intensity"], "vo2max")
        self.assertEqual(detail["after"]["intensity"], "recovery")
        self.assertIsNotNone(detail["session_ref_route"])
        self.assertTrue(detail["session_ref_route"].startswith("#/semaine?debut="))
        self.assertIn("Bilan matinal", detail["body_html"])
        self.assertNotIn(str(self.ws), json.dumps(detail))

    def test_detail_exposes_supersedes_chain_both_ways(self):
        status, payload = self._get_json("/api/decisions?trigger=guardrail&outcome=applied")
        newer = payload["decisions"][0]
        self.assertIsNotNone(newer.get("supersedes"))
        status, detail = self._get_json(f"/api/decision/{newer['id']}")
        self.assertEqual(status, 200)
        self.assertIsNotNone(detail["supersedes_info"])
        self.assertEqual(detail["supersedes_info"]["outcome"], "superseded")
        older_id = detail["supersedes_info"]["id"]
        status, older_detail = self._get_json(f"/api/decision/{older_id}")
        self.assertEqual(status, 200)
        self.assertEqual(older_detail["outcome"], "superseded")
        self.assertEqual(len(older_detail["superseded_by"]), 1)
        self.assertEqual(older_detail["superseded_by"][0]["id"], newer["id"])

    # -- sécurité ------------------------------------------------------------

    def test_unknown_id_is_404(self):
        status, payload = self._get_json("/api/decision/2026-09-23_decision_nope-jamais-ecrite")
        self.assertEqual(status, 404)

    def test_malformed_id_is_404_not_500(self):
        for bad_id in ("nope", "2026-09-23", "2026-09-23_decision_", "../../etc/passwd"):
            status, _, _ = self.server.get(f"/api/decision/{bad_id}")
            self.assertEqual(status, 404, bad_id)

    def test_path_traversal_attempt_in_id_is_rejected(self):
        for attempt in (
            "..%2f..%2f..%2fetc%2fpasswd",
            "2026-09-23_decision_..%2f..%2fplanning%2factive_objective",
            "%2e%2e%2fplanning%2factive_objective",
        ):
            status, body, _ = self.server.get(f"/api/decision/{attempt}")
            self.assertEqual(status, 404, attempt)
            self.assertNotIn(b"active_objective", body)
            self.assertNotIn(b"course visee", body.lower())

    def test_no_absolute_path_ever_leaks_in_any_response(self):
        for path in ("/api/decisions", "/api/decisions?active=1"):
            status, body, _ = self.server.get(path)
            self.assertEqual(status, 200)
            self.assertNotIn(str(self.ws).encode(), body)
            self.assertNotIn(str(self.sb.root).encode(), body)


class TestDecisionsApiPlacementEdgeCases(InstallAsserts):
    """#55, revue de code : un fichier `decision` mal placé (sous-dossier de
    `planning/`) ou au slug mal formé (point) reste indexable — `classify()`
    reste permissif par conception (le bloc ```arc fait foi) — mais son
    identifiant `/api/decision/<id>` doit rester cohérent avec ce qui est
    RÉELLEMENT listé par `/api/decisions` : un sous-dossier ne doit plus
    produire un 404 sur un lien affiché par le journal ; un slug pointé reste
    un cas connu, documenté, et signalé par `validate_file` (verrouillé côté
    palier D dans `tests/data/test_arc_index.py`)."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        self.ws = build(self.sb.root / "ws", days=40, sport="trail", seed=12345,
                        today=datetime.date.fromisoformat(TODAY))
        subfolder_decision = {
            "arc": 1, "kind": "decision", "date": "2026-09-01",
            "created_at": "2026-09-01T07:00:00+02:00", "trigger": "guardrail",
            "summary": "Décision archivée dans un sous-dossier.", "outcome": "applied",
        }
        (self.ws / "planning/archive").mkdir(parents=True, exist_ok=True)
        (self.ws / "planning/archive/2026-09-01_decision_ancienne.md").write_text(
            "# Décision archivée\n\n" + _block(subfolder_decision) + "\nTexte libre.\n", encoding="utf-8")
        dotted_decision = {
            "arc": 1, "kind": "decision", "date": "2026-09-02",
            "created_at": "2026-09-02T07:00:00+02:00", "trigger": "guardrail",
            "summary": "Décision au slug pointé.", "outcome": "applied",
        }
        (self.ws / "planning/2026-09-02_decision_dotted.v2.md").write_text(
            "# Décision au slug pointé\n\n" + _block(dotted_decision) + "\nTexte libre.\n", encoding="utf-8")
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.addCleanup(self.server.stop)
        self.assertIsNotNone(self.server.url,
                             self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def _get_json(self, path):
        status, body, _ = self.server.get(path)
        return status, (json.loads(body) if body else None)

    def test_subfolder_decision_is_listed_and_its_detail_resolves(self):
        status, payload = self._get_json("/api/decisions?days=3650")
        listed = next((d for d in payload["decisions"] if d["summary"] == "Décision archivée dans un sous-dossier."), None)
        self.assertIsNotNone(listed, payload["decisions"])
        status, detail = self._get_json(f"/api/decision/{listed['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["summary"], "Décision archivée dans un sous-dossier.")

    def test_dotted_slug_decision_is_listed_but_its_natural_id_404s(self):
        """Limite CONNUE et documentée (`validate_file` avertit, voir palier D) :
        `arc_serve.DECISION_ID_RE` n'accepte structurellement aucun point dans un
        id — la décision reste visible dans le journal, sans lien de détail
        exploitable, plutôt qu'un lien qui pointerait par erreur vers un autre
        fichier."""
        status, payload = self._get_json("/api/decisions?days=3650")
        listed = next((d for d in payload["decisions"] if d["summary"] == "Décision au slug pointé."), None)
        self.assertIsNotNone(listed, payload["decisions"])
        self.assertIn(".", listed["id"])
        status, _ = self._get_json(f"/api/decision/{listed['id']}")
        self.assertEqual(status, 404)


class TestDecisionsApiDefaultWindow(InstallAsserts):
    """#55, revue de code (nit) : `/api/decisions` sans `days` ni `all=1` ne doit
    plus rendre tout le journal (un workspace ancien finirait par en charger des
    centaines à chaque ouverture de la vue) — fenêtre par défaut de 90 j, `all=1`
    pour l'historique complet à la demande."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        self.ws = build(self.sb.root / "ws", days=40, sport="trail", seed=12345,
                        today=datetime.date.fromisoformat(TODAY))
        old_decision = {
            "arc": 1, "kind": "decision", "date": "2026-01-01",
            "created_at": "2026-01-01T07:00:00+01:00", "trigger": "guardrail",
            "summary": "Décision vieille de plus de 90 jours.", "outcome": "applied",
        }
        (self.ws / "planning/2026-01-01_decision_ancienne-annee.md").write_text(
            "# Vieille décision\n\n" + _block(old_decision) + "\nTexte libre.\n", encoding="utf-8")
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.addCleanup(self.server.stop)
        self.assertIsNotNone(self.server.url,
                             self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def _get_json(self, path):
        status, body, _ = self.server.get(path)
        return status, (json.loads(body) if body else None)

    def test_bare_route_defaults_to_90_days_and_excludes_the_old_one(self):
        status, payload = self._get_json("/api/decisions")
        self.assertEqual(status, 200)
        self.assertEqual(payload["days"], 90)
        summaries = [d["summary"] for d in payload["decisions"]]
        self.assertNotIn("Décision vieille de plus de 90 jours.", summaries)

    def test_all_1_returns_the_full_journal_including_the_old_one(self):
        status, payload = self._get_json("/api/decisions?all=1")
        self.assertEqual(status, 200)
        self.assertIsNone(payload["days"])
        summaries = [d["summary"] for d in payload["decisions"]]
        self.assertIn("Décision vieille de plus de 90 jours.", summaries)

    def test_explicit_days_still_overrides_the_default(self):
        status, payload = self._get_json("/api/decisions?days=3650")
        self.assertEqual(status, 200)
        self.assertEqual(payload["days"], 3650)
        summaries = [d["summary"] for d in payload["decisions"]]
        self.assertIn("Décision vieille de plus de 90 jours.", summaries)


if __name__ == "__main__":
    import unittest
    unittest.main()
