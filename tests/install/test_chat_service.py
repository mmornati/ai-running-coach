"""Palier A — service de chat de bout en bout (`scripts/arc_chat.py`, backend `mock`).

Un vrai serveur HTTP sur un port libre, un workspace temporaire, le backend
scripté `arc_chat_mock`. Aucun modèle, aucun réseau : le « ntfy » est un petit
serveur local qui enregistre ce qu'il reçoit (jamais le vrai ntfy).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.lib.local_http import HTTPServer

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat as C  # noqa: E402
from arc_chat_mock import MockBackend  # noqa: E402

CSRF = {"X-ARC-Chat": "1"}


class FakeNtfy:
    """Serveur ntfy factice : enregistre chaque POST reçu."""

    def __init__(self):
        received = self.received = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                received.append({"path": self.path, "headers": dict(self.headers),
                                 "body": self.rfile.read(length).decode("utf-8")})
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def wait(self, count=1, timeout=3.0):
        deadline = time.monotonic() + timeout
        while len(self.received) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.received


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return None


class ChatCase(unittest.TestCase):
    """Fournit `self.start(**cfg)` : serveur mock prêt, arrêté automatiquement."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        original_log, C.log = C.log, lambda message: None        # journal du service : muet en test
        self.addCleanup(lambda: setattr(C, "log", original_log))
        self._stops = []
        self.addCleanup(lambda: [stop() for stop in self._stops])

    def start(self, notif=None, **over):
        cfg = dict(C.CHAT_DEFAULTS)
        cfg.update({"enabled": True, "backend": "mock", "approval_wait_s": 5, "ntfy_delay_s": 0,
                    "rate_limit_per_min": 0, "mock_slow_s": 5})
        factory = over.pop("backend_factory", MockBackend)
        cfg.update(over)
        httpd, service = C.make_server(self.ws, cfg, factory(self.ws, cfg), notif or {"provider": "none"}, port=0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

        def stop():
            httpd.shutdown()
            httpd.server_close()

        self._stops.append(stop)
        self.service = service
        self.port = httpd.server_address[1]
        return service

    # -- client -------------------------------------------------------------------

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        hdrs.setdefault("Host", host or f"127.0.0.1:{self.port}")
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=payload, headers=hdrs)
            res = conn.getresponse()
            raw = res.read().decode("utf-8")
            try:
                data = json.loads(raw)
            except ValueError:
                data = raw
            return res.status, dict(res.getheaders()), data
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, headers=None, **kw):
        return self.request("POST", path, body if body is not None else {}, dict(CSRF, **(headers or {})), **kw)

    def new_session(self):
        status, _, data = self.post("/api/chat/sessions")
        self.assertEqual(status, 200)
        return data["id"]

    def stream(self, sid, text, on_event=None, headers=None):
        """Envoie un message et lit le flux SSE jusqu'à la fin. Renvoie (statut, en-têtes, [(type, données)])."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        hdrs = dict(CSRF, **{"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"}, **(headers or {}))
        conn.request("POST", f"/api/chat/sessions/{sid}/messages", body=json.dumps({"text": text}), headers=hdrs)
        res = conn.getresponse()
        events = []
        if res.status != 200:
            return res.status, dict(res.getheaders()), json.loads(res.read().decode("utf-8"))
        etype = None
        for raw in res:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                etype = line[7:]
            elif line.startswith("data: "):
                events.append((etype, json.loads(line[6:])))
                if on_event:
                    on_event(events[-1])
        conn.close()
        return res.status, dict(res.getheaders()), events

    def stream_in_thread(self, sid, text):
        """Flux lu en tâche de fond ; `box['events']` se remplit, `box['approval']` reçoit la demande."""
        box = {"events": [], "approval": threading.Event(), "finished": threading.Event()}

        def on_event(item):
            box["events"].append(item)
            if item[0] == "approval_request":
                box["approval"].set()

        def run():
            try:
                box["status"], box["headers"], _ = self.stream(sid, text, on_event)
            finally:
                box["finished"].set()

        threading.Thread(target=run, daemon=True).start()
        return box

    @staticmethod
    def types(events):
        return [t for t, _ in events]


class TestTurns(ChatCase):
    def test_tour_complet_en_sse_et_persistance(self):
        self.start()
        sid = self.new_session()
        status, headers, events = self.stream(sid, "Bonjour coach")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/event-stream"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Accel-Buffering"], "no")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        types = self.types(events)
        for expected in ("text_delta", "tool_start", "tool_end", "file_written", "usage", "done"):
            self.assertIn(expected, types)
        self.assertEqual(events[-1], ("done", {"reason": "end_turn"}))
        self.assertNotIn("user_message", types)                  # stocké, jamais diffusé
        self.assertEqual(dict(events)["file_written"]["path"], "planning/2026-10-01_decision_mock.md")
        # relecture de la session
        _, _, detail = self.get(f"/api/chat/sessions/{sid}")
        self.assertEqual(detail["events"][0]["type"], "user_message")
        self.assertEqual(detail["events"][0]["data"], {"text": "Bonjour coach"})
        self.assertEqual(detail["title"], "Bonjour coach")
        self.assertNotIn("backend_state", detail)
        self.assertAlmostEqual(detail["cost_eur"], 0.01)
        _, _, listing = self.get("/api/chat/sessions")
        self.assertEqual([s["id"] for s in listing["sessions"]], [sid])
        self.assertEqual(listing["sessions"][0]["pending_approvals"], 0)
        _, _, status_body = self.get("/api/chat/status")
        self.assertEqual((status_body["enabled"], status_body["backend"], status_body["user"]),
                         (True, "mock", "local"))
        self.assertAlmostEqual(status_body["budget"]["spent_eur"], 0.01)
        # fichiers sous .arc/chat, dont la dépense
        chat_dir = self.ws / ".arc/chat"
        self.assertTrue((chat_dir / "sessions" / f"{sid}.jsonl").is_file())
        self.assertEqual(len(list(chat_dir.glob("spend-*.json"))), 1)

    def test_erreurs_de_route(self):
        self.start()
        sid = self.new_session()
        self.assertEqual(self.get("/api/chat/sessions/inconnu1234")[0], 404)
        self.assertEqual(self.get("/api/chat/approvals/inconnu1234")[0], 404)
        self.assertEqual(self.get("/api/chat/nimporte")[0], 404)
        self.assertEqual(self.post(f"/api/chat/sessions/{sid}/messages", {"text": "  "})[0], 400)
        self.assertEqual(self.post("/api/chat/sessions/inconnu1234/messages", {"text": "x"})[0], 404)
        self.assertEqual(self.post("/api/chat/approvals/inconnu1234", {"decision": "allow"})[0], 404)
        self.assertEqual(self.post("/api/chat/approvals/inconnu1234", {"decision": "peutetre"})[0], 400)
        self.assertEqual(self.request("PUT", "/api/chat/sessions", {}, CSRF)[0], 405)
        status, _, health = self.get("/api/chat/healthz")
        self.assertEqual((status, health["ok"]), (200, True))
        self.assertEqual(self.get("/healthz")[0], 200)

    def test_tour_concurrent_refuse_puis_interruption(self):
        self.start()
        sid = self.new_session()
        box = self.stream_in_thread(sid, "réponse lente svp")
        self.assertTrue(wait_for(lambda: self.get(f"/api/chat/sessions/{sid}")[2]["running"]))
        status, _, body = self.post(f"/api/chat/sessions/{sid}/messages", {"text": "autre"})
        self.assertEqual(status, 409)
        self.assertIn("error", body)
        status, _, body = self.post(f"/api/chat/sessions/{sid}/interrupt")
        self.assertEqual((status, body["running"]), (200, True))
        self.assertTrue(box["finished"].wait(3))
        self.assertEqual(box["events"][-1], ("done", {"reason": "interrupted"}))
        # la session est libre à nouveau
        self.assertEqual(self.stream(sid, "ok")[2][-1], ("done", {"reason": "end_turn"}))
        self.assertFalse(self.post(f"/api/chat/sessions/{sid}/interrupt")[2]["running"])

    def test_budget_epuise_sans_appeler_le_backend(self):
        self.start(daily_budget_eur=0.015)
        sid = self.new_session()
        self.assertEqual(self.stream(sid, "un")[2][-1], ("done", {"reason": "end_turn"}))    # 0,01 €
        self.stream(sid, "deux")                                                              # 0,02 € : plafond franchi
        _, _, events = self.stream(sid, "trois")
        self.assertEqual(self.types(events), ["error", "done"])
        self.assertEqual(events[1][1], {"reason": "budget"})
        self.assertIn("Budget", events[0][1]["message"])
        _, _, detail = self.get(f"/api/chat/sessions/{sid}")
        self.assertAlmostEqual(detail["cost_eur"], 0.02)                                     # le 3e tour n'a rien coûté

    def test_limite_de_debit(self):
        self.start(rate_limit_per_min=2)
        sid = self.new_session()
        self.assertEqual(self.stream(sid, "1")[0], 200)
        self.assertEqual(self.stream(sid, "2")[0], 200)
        status, _, body = self.stream(sid, "3")
        self.assertEqual(status, 429)
        self.assertIn("error", body)
        # le refus libère bien la session
        self.assertEqual(self.post(f"/api/chat/sessions/{sid}/interrupt")[2]["running"], False)


class TestApprovals(ChatCase):
    def approval_id(self, box):
        self.assertTrue(box["approval"].wait(3))
        return next(d["approval_id"] for t, d in box["events"] if t == "approval_request")

    def test_approbation_acceptee_depuis_la_page(self):
        self.start()
        sid = self.new_session()
        box = self.stream_in_thread(sid, "planifie ma séance de jeudi")
        aid = self.approval_id(box)
        _, _, detail = self.get(f"/api/chat/approvals/{aid}")
        self.assertEqual(detail["status"], "waiting")
        self.assertEqual(detail["tool"], "mcp:garmin.schedule_workouts")
        self.assertNotIn("token_hashes", detail)
        self.assertNotIn("input", detail)
        _, _, listing = self.get("/api/chat/sessions")
        self.assertEqual(listing["sessions"][0]["pending_approvals"], 1)
        request = next(d for t, d in box["events"] if t == "approval_request")
        self.assertEqual(request["diff"][1], {"op": "+", "text": "Jeudi : EF 45 min"})
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "allow"})[0], 200)
        self.assertTrue(box["finished"].wait(3))
        events = box["events"]
        self.assertIn(("approval_resolved", {"approval_id": aid, "decision": "allow"}), events)
        self.assertIn("mcp:garmin.schedule_workouts", [d.get("name") for t, d in events if t == "tool_start"])
        self.assertEqual(events[-1], ("done", {"reason": "end_turn"}))
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "allowed")
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "deny"})[0], 409)   # déjà traitée

    def test_approbation_refusee(self):
        self.start()
        sid = self.new_session()
        box = self.stream_in_thread(sid, "planifie")
        aid = self.approval_id(box)
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "deny"})[0], 200)
        self.assertTrue(box["finished"].wait(3))
        self.assertIn(("approval_resolved", {"approval_id": aid, "decision": "deny"}), box["events"])
        self.assertNotIn("mcp:garmin.schedule_workouts", [d.get("name") for t, d in box["events"] if t == "tool_start"])
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "denied")

    def test_annulation_du_tour_refuse_la_proposition(self):
        self.start()
        sid = self.new_session()
        box = self.stream_in_thread(sid, "planifie")
        aid = self.approval_id(box)
        self.post(f"/api/chat/sessions/{sid}/interrupt")
        self.assertTrue(box["finished"].wait(3))
        self.assertEqual(box["events"][-1][0], "done")
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "cancelled")
        log = self.get(f"/api/chat/sessions/{sid}")[2]["events"]
        resolved = [e["data"] for e in log if e["type"] == "approval_resolved"]
        self.assertEqual(resolved[-1], {"approval_id": aid, "decision": "cancelled"})

    def test_pending_puis_reprise_asynchrone(self):
        self.start(approval_wait_s=0.3)
        sid = self.new_session()
        _, _, events = self.stream(sid, "planifie ma séance")
        self.assertEqual(events[-1], ("done", {"reason": "pending_approval"}))
        aid = next(d["approval_id"] for t, d in events if t == "approval_request")
        self.assertIn(("approval_resolved", {"approval_id": aid, "decision": "pending"}), events)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "pending")
        self.assertEqual(self.get("/api/chat/sessions")[2]["sessions"][0]["pending_approvals"], 1)
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "allow"})[0], 200)

        def resumed():
            log = self.get(f"/api/chat/sessions/{sid}")[2]["events"]
            dones = [e for e in log if e["type"] == "done"]
            return log if len(dones) == 2 else None

        log = wait_for(resumed)
        self.assertIsNotNone(log, "la reprise n'a pas eu lieu")
        synthetic = [e for e in log if e["type"] == "user_message" and e["data"].get("synthetic")]
        self.assertEqual(len(synthetic), 1)
        self.assertTrue(synthetic[0]["data"]["text"].startswith(f"[approbation] L'athlète a approuvé la proposition {aid} "))
        # seul l'appel approuvé (même hash) est exécuté, sans nouvelle demande
        self.assertEqual(sum(1 for e in log if e["type"] == "approval_request"), 1)
        self.assertIn("mcp:garmin.schedule_workouts", [e["data"].get("name") for e in log if e["type"] == "tool_start"])
        self.assertEqual(self.get("/api/chat/sessions")[2]["sessions"][0]["pending_approvals"], 0)

    def test_pending_refuse_ne_reprend_pas(self):
        self.start(approval_wait_s=0.2)
        sid = self.new_session()
        _, _, events = self.stream(sid, "planifie")
        aid = next(d["approval_id"] for t, d in events if t == "approval_request")
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "deny"})[0], 200)
        time.sleep(0.3)
        log = self.get(f"/api/chat/sessions/{sid}")[2]["events"]
        self.assertEqual(sum(1 for e in log if e["type"] == "done"), 1)
        self.assertEqual(log[-1]["data"], {"approval_id": aid, "decision": "deny"})

    def test_pending_expire(self):
        self.start(approval_wait_s=0.2, approval_ttl_s=0.4)
        sid = self.new_session()
        _, _, events = self.stream(sid, "planifie")
        aid = next(d["approval_id"] for t, d in events if t == "approval_request")
        time.sleep(0.5)
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "allow"})[0], 410)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "expired")


class TestNtfyQuickApprove(ChatCase):
    def setUp(self):
        super().setUp()
        self.ntfy = FakeNtfy()
        self.addCleanup(self.ntfy.close)

    def start_ntfy(self, **over):
        token_file = self.ws / "ntfy.token"
        token_file.write_text("tk-test\n", encoding="utf-8")
        notif = {"provider": "ntfy", "ntfy_url": self.ntfy.url, "ntfy_topic": "coach-test",
                 "ntfy_token_file": str(token_file) if over.pop("with_token_file", True) else ""}
        cfg = {"public_url": "https://coach.example.com", "approval_wait_s": 0.3, "ntfy_token_ttl_s": 60}
        cfg.update(over)
        return self.start(notif=notif, **cfg)

    def pending_with_tokens(self):
        sid = self.new_session()
        _, _, events = self.stream(sid, "planifie ma séance")
        aid = next(d["approval_id"] for t, d in events if t == "approval_request")
        sent = self.ntfy.wait(1)
        self.assertEqual(len(sent), 1)
        actions = sent[-1]["headers"]["Actions"]
        tokens = dict((m[1], m[0]) for m in re.findall(r"/api/chat/approve/([^/,\s]+)/(allow|deny)", actions))
        return sid, aid, tokens, sent[-1]

    def token_post(self, token, action, headers=CSRF):
        return self.request("POST", f"/api/chat/approve/{token}/{action}", {}, dict(headers))

    def test_notification_sans_valeur_de_sante_avec_actions(self):
        self.start_ntfy()
        sid, aid, tokens, message = self.pending_with_tokens()
        self.assertEqual(message["path"], "/coach-test")
        self.assertEqual(message["body"], "Jeudi 1er octobre : footing EF 45 min")
        self.assertIn("confirmation demandée", message["headers"]["Title"])
        self.assertEqual(message["headers"]["Authorization"], "Bearer tk-test")
        actions = message["headers"]["Actions"]
        self.assertIn(f"view, Ouvrir, https://coach.example.com/chat.html#approval={aid}", actions)
        self.assertEqual(set(tokens), {"allow", "deny"})
        self.assertIn("method=POST, headers.X-ARC-Chat=1, clear=true", actions)
        # aucun jeton en clair sur le disque
        self.assertNotIn(tokens["allow"].split(".")[1], (self.ws / ".arc/chat/approvals.json").read_text(encoding="utf-8"))

    def test_jeton_a_usage_unique_reprend_la_session(self):
        self.start_ntfy()
        sid, aid, tokens, _ = self.pending_with_tokens()
        status, _, body = self.token_post(tokens["allow"], "allow")     # sans SSO, sans Origin
        self.assertEqual((status, body), (200, {"ok": True, "decision": "allow"}))
        self.assertTrue(wait_for(lambda: sum(1 for e in self.get(f"/api/chat/sessions/{sid}")[2]["events"]
                                             if e["type"] == "done") == 2))
        # rejeu et jeton jumeau : brûlés
        self.assertEqual(self.token_post(tokens["allow"], "allow")[0], 410)
        self.assertEqual(self.token_post(tokens["deny"], "deny")[0], 410)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "allowed")

    def test_jeton_refus(self):
        self.start_ntfy()
        sid, aid, tokens, _ = self.pending_with_tokens()
        self.assertEqual(self.token_post(tokens["deny"], "deny")[0], 200)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "denied")
        self.assertEqual(self.token_post(tokens["allow"], "allow")[0], 410)

    def test_jeton_deja_utilise_via_la_page(self):
        self.start_ntfy()
        sid, aid, tokens, _ = self.pending_with_tokens()
        self.assertEqual(self.post(f"/api/chat/approvals/{aid}", {"decision": "deny"})[0], 200)
        self.assertEqual(self.token_post(tokens["allow"], "allow")[0], 410)

    def test_jeton_expire(self):
        self.start_ntfy(ntfy_token_ttl_s=0.05)
        sid, aid, tokens, _ = self.pending_with_tokens()
        time.sleep(0.1)
        self.assertEqual(self.token_post(tokens["allow"], "allow")[0], 410)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "pending")    # rien n'a été appliqué

    def test_jeton_refuse_si_la_charge_a_change(self):
        self.start_ntfy()
        sid, aid, tokens, _ = self.pending_with_tokens()
        path = self.ws / ".arc/chat/approvals.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data[aid]["input"] = {"workouts": [{"date": "2026-12-25", "name": "Autre chose"}]}
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.token_post(tokens["allow"], "allow")[0], 409)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "pending")

    def test_jeton_inconnu_et_en_tete_obligatoire(self):
        self.start_ntfy()
        sid, aid, tokens, _ = self.pending_with_tokens()
        self.assertEqual(self.token_post(f"{aid}.faux", "allow")[0], 404)
        self.assertEqual(self.token_post(tokens["allow"], "allow", headers={})[0], 403)      # X-ARC-Chat manquant
        self.assertEqual(self.token_post(tokens["allow"], "peutetre")[0], 404)
        self.assertEqual(self.get(f"/api/chat/approvals/{aid}")[2]["status"], "pending")

    def test_sans_quick_approve_seul_le_bouton_ouvrir(self):
        self.start_ntfy(ntfy_quick_approve=False)
        sid = self.new_session()
        self.stream(sid, "planifie")
        actions = self.ntfy.wait(1)[-1]["headers"]["Actions"]
        self.assertIn("view, Ouvrir", actions)
        self.assertNotIn("http,", actions)

    def test_ntfy_desactive(self):
        self.start_ntfy(ntfy_approvals=False)
        sid = self.new_session()
        self.stream(sid, "planifie")
        time.sleep(0.2)
        self.assertEqual(self.ntfy.received, [])
        self.assertFalse(self.get("/api/chat/status")[2]["ntfy"])

    def test_push_immediat_sans_onglet_puis_reponse_dans_le_delai(self):
        """Avec un onglet attaché et un délai de 60 s, rien n'est envoyé tant que l'athlète répond vite."""
        self.start_ntfy(ntfy_delay_s=60, approval_wait_s=5)
        sid = self.new_session()
        box = self.stream_in_thread(sid, "planifie")
        self.assertTrue(box["approval"].wait(3))
        aid = next(d["approval_id"] for t, d in box["events"] if t == "approval_request")
        time.sleep(0.3)
        self.assertEqual(self.ntfy.received, [])
        self.post(f"/api/chat/approvals/{aid}", {"decision": "allow"})
        self.assertTrue(box["finished"].wait(3))
        self.assertEqual(self.ntfy.received, [])


class TestSecurity(ChatCase):
    def test_csrf(self):
        self.start()
        status, _, _ = self.request("POST", "/api/chat/sessions", {}, {})
        self.assertEqual(status, 403)                                                    # sans X-ARC-Chat
        self.assertEqual(self.post("/api/chat/sessions", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/api/chat/sessions", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.post("/api/chat/sessions", headers={"Sec-Fetch-Site": "same-origin"})[0], 200)
        good_origin = {"Origin": f"http://127.0.0.1:{self.port}"}
        self.assertEqual(self.post("/api/chat/sessions", headers=good_origin)[0], 200)
        sid = self.new_session()
        self.assertEqual(self.request("POST", f"/api/chat/sessions/{sid}/messages", {"text": "x"}, {})[0], 403)
        self.assertEqual(self.request("POST", "/api/chat/approvals/x", {"decision": "allow"}, {})[0], 403)

    def test_host_non_autorise(self):
        self.start()
        self.assertEqual(self.get("/api/chat/status", host="evil.example")[0], 403)
        self.assertEqual(self.get("/api/chat/status", host="evil.example:8765")[0], 403)
        # Mode local : relais du tableau de bord, boucle locale acceptée sur tout port.
        self.assertEqual(self.get("/api/chat/status", host="localhost:8765")[0], 200)
        self.assertEqual(self.get("/api/chat/status", host=f"localhost:{self.port}")[0], 200)

    def test_ecoute_locale_refusee_hors_boucle(self):
        with self.assertRaises(C.ConfigError):
            self.start(listen="0.0.0.0")

    def test_mode_proxy_exige_l_identite(self):
        self.start(auth="proxy", allowed_users=["marco"], auth_header="Remote-User")
        status, _, body = self.get("/api/chat/status")
        self.assertEqual(status, 401)
        self.assertIn("error", body)
        self.assertEqual(self.post("/api/chat/sessions")[0], 401)
        self.assertEqual(self.get("/api/chat/status", headers={"Remote-User": "intrus"})[0], 403)
        status, _, body = self.get("/api/chat/status", headers={"Remote-User": "marco"})
        self.assertEqual((status, body["user"]), (200, "marco"))
        self.assertEqual(self.post("/api/chat/sessions", headers={"Remote-User": "marco"})[0], 200)
        # /healthz depuis la boucle locale : sans identité
        self.assertEqual(self.get("/api/chat/healthz")[0], 200)
        # la route à jeton n'a pas besoin d'identité (mais le jeton doit être valide)
        self.assertEqual(self.request("POST", "/api/chat/approve/x.y/allow", {}, CSRF)[0], 404)

    def test_mode_proxy_source_non_fiable(self):
        self.start(auth="proxy", trusted_proxies=["10.9.9.9"])
        self.assertEqual(self.get("/api/chat/status", headers={"X-authentik-username": "marco"})[0], 403)
        self.assertEqual(self.request("POST", "/api/chat/approve/x.y/allow", {}, CSRF)[0], 403)
        self.assertEqual(self.get("/api/chat/healthz")[0], 200)                          # boucle locale : toujours


class TestProcess(unittest.TestCase):
    def test_ligne_url_et_healthz(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ARC_LLM_ENV=str(Path(tmp) / "absent.env"))
            proc = subprocess.Popen([sys.executable, str(REPO / "scripts/arc_chat.py"), "--workspace", tmp,
                                     "--port", "0", "--backend", "mock"], env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                line = proc.stdout.readline()
                self.assertRegex(line, r"^URL: http://127\.0\.0\.1:\d+/$")
                port = int(re.search(r":(\d+)/", line).group(1))
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/api/chat/healthz")
                res = conn.getresponse()
                self.assertEqual((res.status, json.loads(res.read())["ok"]), (200, True))
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                proc.stdout.close()
                proc.stderr.close()

    def test_refus_de_demarrer_en_local_hors_boucle(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, str(REPO / "scripts/arc_chat.py"), "--workspace", tmp,
                                   "--port", "0", "--backend", "mock", "--listen", "0.0.0.0"],
                                  capture_output=True, text=True, timeout=20,
                                  env=dict(os.environ, ARC_LLM_ENV=str(Path(tmp) / "absent.env")))
            self.assertEqual(done.returncode, 1)
            self.assertIn("boucle locale", done.stderr)


if __name__ == "__main__":
    unittest.main()
