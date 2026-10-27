#!/usr/bin/env python3
"""Cartes d'approbation lisibles pour les écritures Garmin.

Une carte qui ne montre que `{"scheduled_workout_ids": [1783059687, …]}` ne laisse
rien à vérifier : le service retient, depuis les RÉSULTATS des lectures Garmin de
la conversation, le nom et la date de chaque identifiant, et la carte les affiche.
Un identifiant jamais lu est signalé, pas deviné.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_chat_tools as T  # noqa: E402

SCHEDULED = {
    "count": 3,
    "date_range": {"start": "2026-10-12", "end": "2026-10-18"},
    "scheduled_workouts": [
        {"date": "2026-10-13", "scheduled_workout_id": 1783059687, "workout_id": 1703712516,
         "name": "Footing Z2 10km", "sport": "running", "completed": False},
        {"date": "2026-10-14", "scheduled_workout_id": 1783059702, "workout_id": 1703714537,
         "name": "Fiche R1 - Renfo Entretien Phase 3", "sport": "strength_training", "completed": False},
        {"date": "2026-10-15", "scheduled_workout_id": 1807285005, "workout_id": 1718173896,
         "name": "HT Z2 50 min", "sport": "cycling", "completed": False},
    ],
}


def texts(diff):
    return [(line["op"], line["text"]) for line in diff]


class TestCatalogue(unittest.TestCase):
    def setUp(self):
        self.state: dict = {}
        T.remember_result(self.state, "mcp:garmin.get_scheduled_workouts", json.dumps(SCHEDULED, indent=2))
        self.catalog = self.state[T.CATALOG_KEY]

    def test_desinscription_montre_date_et_nom(self):
        inp = {"scheduled_workout_ids": [1783059687, 1783059702]}
        self.assertEqual(T.approval_summary("mcp:garmin.unschedule_workouts", inp, self.catalog),
                         "Garmin : retirer 2 séances du calendrier")
        self.assertEqual(texts(T.approval_diff("mcp:garmin.unschedule_workouts", inp, self.catalog)),
                         [("-", "mar. 13/10 · Footing Z2 10km"),
                          ("-", "mer. 14/10 · Fiche R1 - Renfo Entretien Phase 3")])

    def test_identifiant_jamais_lu_signale(self):
        inp = {"scheduled_workout_ids": [1783059687, 42]}
        summary = T.approval_summary("mcp:garmin.unschedule_workouts", inp, self.catalog)
        self.assertIn("1 non identifiée", summary)
        diff = texts(T.approval_diff("mcp:garmin.unschedule_workouts", inp, self.catalog))
        self.assertIn(("-", "entrée de calendrier 42 — non identifiée dans cette conversation"), diff)
        self.assertTrue(diff[-1][1].startswith("⚠"))

    def test_sans_catalogue_rien_n_est_invente(self):
        diff = texts(T.approval_diff("mcp:garmin.unschedule_workout", {"scheduled_workout_id": 7}, None))
        self.assertEqual(diff[0], ("-", "entrée de calendrier 7 — non identifiée dans cette conversation"))

    def test_planification_par_identifiant_et_inline(self):
        T.remember_result(self.state, "mcp:garmin.upload_workout",
                          json.dumps({"status": "success", "workout_id": 555, "name": "Côtes 8 × 90 s"}))
        inp = {"schedules": [{"workout_id": 555, "calendar_date": "2026-10-17"},
                             {"calendar_date": "2026-10-16", "workout_data": {"workoutName": "EF 45 min"}}]}
        self.assertEqual(T.approval_summary("mcp:garmin.schedule_workouts", inp, self.catalog),
                         "Garmin : ajouter 2 séances au calendrier")
        self.assertEqual(texts(T.approval_diff("mcp:garmin.schedule_workouts", inp, self.catalog)),
                         [("+", "ven. 16/10 · EF 45 min (nouvelle séance)"),
                          ("+", "sam. 17/10 · Côtes 8 × 90 s")])

    def test_schedule_week_reprend_les_noms_lus(self):
        inp = {"week": [{"date": "2026-10-15", "workout_id": 1718173896}]}
        self.assertEqual(texts(T.approval_diff("mcp:garmin.schedule_week", inp, self.catalog)),
                         [("+", "jeu. 15/10 · HT Z2 50 min")])

    def test_suppression_de_bibliotheque(self):
        inp = {"workout_ids": [1703712516]}
        self.assertEqual(T.approval_summary("mcp:garmin.delete_workouts", inp, self.catalog),
                         "Garmin : supprimer définitivement 1 séance de la bibliothèque")
        self.assertEqual(texts(T.approval_diff("mcp:garmin.delete_workouts", inp, self.catalog)),
                         [("-", "Footing Z2 10km")])

    def test_resultat_en_blocs_et_doublement_encode(self):
        state: dict = {}
        wrapped = [{"type": "text", "text": json.dumps(json.dumps(SCHEDULED))}]
        T.remember_result(state, "mcp:garmin.get_scheduled_workouts", wrapped)
        self.assertIn("1783059687", state[T.CATALOG_KEY]["scheduled"])

    def test_hors_garmin_et_texte_libre_ignores(self):
        state: dict = {}
        T.remember_result(state, "mcp:intervals.icu_get_events", json.dumps(SCHEDULED))
        T.remember_result(state, "mcp:garmin.get_scheduled_workouts", "No workouts scheduled.")
        self.assertEqual(state.get(T.CATALOG_KEY, {}).get("scheduled", {}), {})

    def test_catalogue_borne(self):
        state: dict = {}
        many = {"scheduled_workouts": [{"date": "2026-10-13", "scheduled_workout_id": i, "name": f"S{i}"}
                                       for i in range(T.MAX_CATALOG + 10)]}
        T.remember_result(state, "mcp:garmin.get_scheduled_workouts", json.dumps(many))
        sched = state[T.CATALOG_KEY]["scheduled"]
        self.assertEqual(len(sched), T.MAX_CATALOG)
        self.assertNotIn("0", sched)

    def test_autres_outils_gardent_le_json(self):
        diff = texts(T.approval_diff("mcp:garmin.add_gear_to_activity", {"activity_id": 1}, self.catalog))
        self.assertEqual(diff[0], ("+", "{"))


class TestGate(unittest.TestCase):
    def test_gate_utilise_le_catalogue_de_la_session(self):
        state: dict = {}
        T.remember_result(state, "mcp:garmin.get_scheduled_workouts", json.dumps(SCHEDULED))
        seen = []

        class Ctx:
            backend_state = state

            def decide(self, tool, inp):
                return "ask"

            def request_approval(self, tool, inp, summary, diff):
                seen.append((summary, diff))
                return "allow"

        self.assertEqual(T.gate(Ctx(), "mcp:garmin.unschedule_workouts",
                                {"scheduled_workout_ids": [1807285005]})[0], "allow")
        summary, diff = seen[0]
        self.assertEqual(summary, "Garmin : retirer 1 séance du calendrier")
        self.assertEqual(texts(diff), [("-", "jeu. 15/10 · HT Z2 50 min")])


    def test_refus_shell_oriente_vers_les_outils_fichiers(self):
        # Un `ls` refusé ne doit pas faire abandonner la tâche : le message pointe vers les outils fichiers.
        class Ctx:
            def decide(self, tool, inp):
                return "deny"

        decision, message = T.gate(Ctx(), "shell", {"command": "ls medical/ | tail -5"})
        self.assertEqual((decision, message), ("deny", T.REFUSAL_SHELL))
        self.assertIn("poursuis la tâche", message)
        self.assertEqual(T.gate(Ctx(), "web.search", {"query": "x"}), ("deny", T.REFUSAL_DENY))


class TestClaudeBackend(unittest.TestCase):
    """Bout en bout : le résultat d'une lecture SDK alimente la carte de l'écriture suivante."""

    def test_lecture_puis_desinscription(self):
        import test_arc_chat_claude as TC  # même faux SDK que les autres tests du backend

        case = TC.ClaudeBackendCase("run")
        case.setUp()
        try:
            script = [
                ("msg", TC.MB.AssistantMessage([TC.make_fake_sdk([], {}).ToolUseBlock(
                    "t1", "mcp__garmin__get_scheduled_workouts", {"start_date": "2026-10-12",
                                                                   "end_date": "2026-10-18"})])),
                ("msg", TC.make_fake_sdk([], {}).UserMessage([TC.make_fake_sdk([], {}).ToolResultBlock(
                    "t1", [{"type": "text", "text": json.dumps(SCHEDULED)}])])),
                ("tool", "t2", "mcp__garmin__unschedule_workouts", {"scheduled_workout_ids": [1783059687]}),
            ]
            backend, _, _ = case.backend(script)
            h = TC.Harness(case.ws, decisions={"mcp:garmin.unschedule_workouts": "ask"})
            backend.run_turn(h.ctx, "retire le footing")
            self.assertEqual(len(h.approvals), 1)
            _, _, summary, diff = h.approvals[0]
            self.assertEqual(summary, "Garmin : retirer 1 séance du calendrier")
            self.assertEqual(texts(diff), [("-", "mar. 13/10 · Footing Z2 10km")])
            self.assertIn("1783059687", h.ctx.backend_state[T.CATALOG_KEY]["scheduled"])
        finally:
            case._restore()


class TestOpenCodeBackend(unittest.TestCase):
    """Bout en bout côté OpenCode (backend du service en production)."""

    def test_lecture_puis_desinscription(self):
        import test_arc_chat_opencode as TO

        case = TO.OpenCodeCase("run")
        case.setUp()
        try:
            (case.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {"command": "garmin-mcp"}}}))

            def part(call, tool, state):
                return {"sessionID": "$SESSION", "part": {
                    "type": "tool", "tool": tool, "callID": call, "id": f"p_{call}", "messageID": "msg_9",
                    "sessionID": "$SESSION", "state": state}}

            sc = {"before_permission": [
                {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION",
                                                                      "status": {"type": "busy"}}},
                {"id": "e2", "type": "message.part.updated", "properties": part(
                    "cR", "garmin_get_scheduled_workouts",
                    {"status": "completed", "input": {"start_date": "2026-10-12", "end_date": "2026-10-18"},
                     "output": json.dumps(SCHEDULED, indent=2)})},
                {"id": "e3", "type": "message.part.updated", "properties": part(
                    "cW", "garmin_unschedule_workouts",
                    {"status": "running", "input": {"scheduled_workout_ids": [1783059702]}})},
                {"id": "e4", "type": "permission.asked", "properties": {
                    "id": "per_w", "sessionID": "$SESSION", "permission": "garmin_unschedule_workouts",
                    "patterns": ["*"], "metadata": {}, "always": [],
                    "tool": {"messageID": "msg_9", "callID": "cW"}}}],
                "after": {"once": [{"id": "e5", "type": "session.idle", "properties": {"sessionID": "$SESSION"}}]}}
            h = case.run_turn(sc, TO.Harness(case.ws, {"mcp:garmin.unschedule_workouts": "ask"}, "allow"))
            self.assertEqual(len(h.approvals), 1)
            _, _, summary, diff = h.approvals[0]
            self.assertEqual(summary, "Garmin : retirer 1 séance du calendrier")
            self.assertEqual(texts(diff), [("-", "mer. 14/10 · Fiche R1 - Renfo Entretien Phase 3")])
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
