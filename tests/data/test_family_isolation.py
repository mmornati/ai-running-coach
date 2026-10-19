"""Palier D — mode famille (#127) : registre, identité et ISOLATION entre membres.

Deux vrais workspaces fictifs (Alice, Bob) aux données distinctes, indexés, servis par le vrai
`arc_serve.Handler` / `arc_chat.FamilyHandler` sur une socket de boucle locale. La garantie testée :
l'en-tête d'identité de A ne renvoie JAMAIS de donnée de B, sur CHAQUE route.
"""

from __future__ import annotations

import http.client
import http.server
import json
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat as C  # noqa: E402
import arc_chat_mock as M  # noqa: E402
import arc_family as F  # noqa: E402
import arc_serve as S  # noqa: E402
from arc_chat_policy import Policy  # noqa: E402
from coach_config import ConfigError  # noqa: E402
from tests.lib.local_http import ThreadingHTTPServer  # noqa: E402

HEADER = "X-authentik-username"
MARK = {"alice": "ALICEMARK", "bob": "BOBMARK"}
ACT_ID = {"alice": 1111, "bob": 2222}


def arc(block: dict, body: str = "Texte.") -> str:
    return f"# Titre\n\n```arc\n{json.dumps(block)}\n```\n\n{body}\n"


def make_workspace(root: Path, member: str, extra_config: str = "") -> Path:
    ws = root / f"coach-{member}"
    for d in ("activities", "medical", "nutrition", "planning", "rapports", "gear/photos", "config"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    mark = MARK[member]
    day = "2026-09-20" if member == "alice" else "2026-09-19"
    (ws / f"activities/{day}_trail.md").write_text(arc(
        {"arc": 1, "kind": "activity", "date": day, "sport": "trail", "duration_s": 3600,
         "distance_m": 10000, "garmin_activity_id": ACT_ID[member], "location": f"Col-{mark}",
         "gear_id": f"pegasus-{member}"}, f"Sortie {mark}."), encoding="utf-8")
    (ws / f"planning/{day}_decision_{mark.lower()}.md").write_text(arc(
        {"arc": 1, "kind": "decision", "date": day, "created_at": f"{day}T07:10:00+02:00",
         "trigger": "morning_check", "summary": f"Décision {mark}.", "outcome": "applied"}), encoding="utf-8")
    (ws / f"rapports/{day}_rapport.md").write_text(arc(
        {"arc": 1, "kind": "report", "date": day, "report_type": "weekly", "title": f"Bilan {mark}"},
        f"Rapport {mark}."), encoding="utf-8")
    (ws / "planning/Runner_Profile.md").write_text(
        f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n- Pegasus {mark} — id: pegasus-{member} (par défaut)\n",
        encoding="utf-8")
    photo = f"gear/photos/{day}_pegasus-{member}_semelle.png"
    (ws / photo).write_bytes(b"\x89PNG-" + mark.encode())
    (ws / f"gear/{day}_pegasus-{member}_inspection.md").write_text(arc(
        {"arc": 1, "kind": "gear_inspection", "date": day, "gear_id": f"pegasus-{member}",
         "condition": "yellow", "photos": [photo]}), encoding="utf-8")
    (ws / "config/workspace.user.toml").write_text(extra_config, encoding="utf-8")
    return ws


class FamilyCase(unittest.TestCase):
    """Deux membres, un registre dont le proxy de confiance est la boucle locale."""

    TRUSTED = ["127.0.0.1"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def registry(self, trusted=None, extra_family: str = "", workspaces=None) -> F.Registry:
        workspaces = workspaces or {m: make_workspace(self.root, m) for m in ("alice", "bob")}
        trusted = self.TRUSTED if trusted is None else trusted
        lines = [f"[family]\ntrusted_proxies = {json.dumps(trusted)}\nallowed_hosts = [\"coach.example.org\"]\n"
                 f"{extra_family}\n"]
        for member, ws in workspaces.items():
            lines.append(f'[members.{member}]\nworkspace = "{ws}"\ndisplay_name = "{member.title()}"\n')
        path = self.root / "family.toml"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.workspaces = workspaces
        return F.load_registry(path)


# ---------------------------------------------------------------------------
# Registre et identité
# ---------------------------------------------------------------------------

class TestRegistry(FamilyCase):
    def load(self, text: str) -> F.Registry:
        path = self.root / "r.toml"
        path.write_text(text, encoding="utf-8")
        return F.load_registry(path)

    def test_registre_valide(self):
        registry = self.registry()
        self.assertEqual(list(registry.members), ["alice", "bob"])
        self.assertEqual(registry.members["alice"].display_name, "Alice")
        self.assertEqual(registry.lookup("alice").id, "alice")
        self.assertIsNone(registry.lookup("ALICE"))                    # comparaison EXACTE
        self.assertIsNone(registry.lookup("../coach-bob"))

    def test_alias_d_identite(self):
        ws = make_workspace(self.root, "alice")
        registry = self.load(f'[members.alice]\nworkspace = "{ws}"\nidentities = ["Alice.Martin"]\n')
        self.assertEqual(registry.lookup("Alice.Martin").id, "alice")

    def test_refus_de_registre_invalide(self):
        a, b = make_workspace(self.root, "alice"), make_workspace(self.root, "bob")
        bad = {
            "workspace relatif": '[members.alice]\nworkspace = "coach-alice"\n',
            "workspace inexistant": f'[members.alice]\nworkspace = "{self.root}/nope"\n',
            "identifiant invalide": f'[members."Alice B"]\nworkspace = "{a}"\n',
            "doublon de workspace": f'[members.alice]\nworkspace = "{a}"\n[members.bob]\nworkspace = "{a}"\n',
            "workspace imbriqué": f'[members.alice]\nworkspace = "{self.root}"\n[members.bob]\nworkspace = "{b}"\n',
            "alias en collision": (f'[members.alice]\nworkspace = "{a}"\nidentities = ["bob"]\n'
                                   f'[members.bob]\nworkspace = "{b}"\n'),
            "registre vide": "[family]\n",
        }
        for label, text in bad.items():
            with self.subTest(label), self.assertRaises(ConfigError):
                self.load(text)

    def test_sans_proxy_de_confiance_on_refuse_de_servir(self):
        registry = self.registry(trusted=[])
        with self.assertRaises(ConfigError):
            registry.require_trusted_proxies()
        with self.assertRaises(ConfigError):
            C.FamilyChat(registry)
        with self.assertRaises(ConfigError):
            S.serve(None, 0, family=registry)

    def test_chemin_du_registre(self):
        self.assertEqual(F.resolve_registry_path("/x/f.toml", {}), Path("/x/f.toml"))
        self.assertEqual(F.resolve_registry_path(None, {"ARC_FAMILY": "/y/f.toml"}), Path("/y/f.toml"))
        self.assertEqual(F.resolve_registry_path(None, {}).name, "family.toml")

    def test_authenticate_member(self):
        registry = self.registry()
        ok = F.authenticate_member(registry, "127.0.0.1", {HEADER: "alice"})
        self.assertEqual((ok[0].id, ok[1]), ("alice", 0))
        for peer, headers in (("127.0.0.1", {}), ("127.0.0.1", {HEADER: "mallory"}), ("127.0.0.1", {HEADER: ""}),
                              ("192.0.2.9", {HEADER: "alice"}), ("not-an-ip", {HEADER: "alice"})):
            member, status, message = F.authenticate_member(registry, peer, headers)
            self.assertEqual((member, status, message), (None, 403, F.DENIED), (peer, headers))
        self.assertNotIn("alice", F.DENIED)                             # aucun nom de membre dans le refus


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------

class DashboardCase(FamilyCase):
    def start(self, registry: F.Registry):
        handler = type("FamilyDashHandler", (S.Handler,), {})
        handler.family = S.FamilyStores(registry, memory=True, today="2026-09-23")
        handler.store = None
        handler.chat_port = None
        handler.tile_src = ""
        httpd = S.Server(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        handler.allowed_hosts = S.host_allowlist(port, ["coach.example.org"])
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            handler.family.stop_all()
        self.addCleanup(stop)
        return port

    def get(self, port, path, user=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        headers = {"Host": "coach.example.org"}
        if user is not None:
            headers[HEADER] = user
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body


class TestDashboardIsolation(DashboardCase):
    def setUp(self):
        super().setUp()
        self.port = self.start(self.registry())

    def all_get_paths(self):
        """Toutes les routes GET de données du tableau de bord : la table + les routes dynamiques."""
        paths = sorted(S.ROUTES) + ["/api/version", "/api/sync-status", "/api/whoami", "/media/gear-photo",
                                    "/api/activity/1", "/api/activity/1/track", "/api/activity/2", "/api/climb-segment/1", "/api/gear/pegasus-alice",
                                    "/api/gear/pegasus-bob", f"/api/decision/2026-09-20_decision_alicemark",
                                    f"/api/decision/2026-09-19_decision_bobmark", "/api/inconnue-future"]
        return paths

    def test_chaque_route_exige_une_identite(self):
        """Une route ajoutée plus tard (même inconnue) sans résolution d'identité ferait échouer ce test :
        TOUT `/api/*` et `/media/*` sans identité valide répond 403 AVANT tout aiguillage."""
        for path in self.all_get_paths():
            for label, user in (("sans en-tête", None), ("inconnu", "mallory"), ("vide", "")):
                with self.subTest(path=path, cas=label):
                    status, body = self.get(self.port, path, user)
                    self.assertEqual(status, 403)
                    for text in (b"alice", b"bob", b"ALICEMARK", b"BOBMARK", b"1111", b"2222"):
                        self.assertNotIn(text, body)               # aucune donnée, aucun nom de membre

    def test_table_des_routes_couverte(self):
        # Chaque clé de ROUTES figure dans la liste testée (une route ajoutée sans test = échec ici).
        self.assertTrue(set(S.ROUTES) <= set(self.all_get_paths()))

    def test_aucune_donnee_croisee_sur_aucune_route(self):
        for me, other in (("alice", "bob"), ("bob", "alice")):
            for path in self.all_get_paths():
                query = path + ("?path=" + f"gear/photos/2026-09-1{'9' if other == 'bob' else '0'}"
                                f"_pegasus-{other}_semelle.png" if path == "/media/gear-photo" else "")
                with self.subTest(me=me, path=path):
                    status, body = self.get(self.port, query, me)
                    text = body.decode("utf-8", "replace")
                    self.assertNotIn(MARK[other], text)
                    self.assertNotIn(f"pegasus-{other}", text)
                    self.assertNotIn(MARK[other].lower(), text.lower())
                    self.assertNotIn(f"coach-{other}", text)        # ni chemin de l'autre workspace
                    self.assertNotIn(str(ACT_ID[other]), text)

    def test_chacun_voit_ses_propres_donnees(self):
        # Garde-fou du test précédent : les données existent bel et bien et sont servies au bon membre.
        for me in ("alice", "bob"):
            status, body = self.get(self.port, "/api/activities", me)
            self.assertEqual(status, 200)
            self.assertIn(f"Col-{MARK[me]}", body.decode())
            status, body = self.get(self.port, "/api/activity/1", me)     # id d'index : « 1 » chez chacun
            self.assertEqual(status, 200)
            self.assertIn(f"Col-{MARK[me]}", body.decode())
            self.assertIn(str(ACT_ID[me]), body.decode())

    def test_activite_de_l_autre_introuvable(self):
        self.assertEqual(self.get(self.port, "/api/activity/2", "alice")[0], 404)   # une seule séance chez chacun
        self.assertEqual(self.get(self.port, "/api/activity/2", "bob")[0], 404)
        self.assertEqual(self.get(self.port, "/api/gear/pegasus-bob", "alice")[0], 404)
        self.assertEqual(self.get(self.port, "/api/decision/2026-09-19_decision_bobmark", "alice")[0], 404)

    def test_photo_de_l_autre_introuvable(self):
        own = "/media/gear-photo?path=gear/photos/2026-09-20_pegasus-alice_semelle.png"
        theirs = "/media/gear-photo?path=gear/photos/2026-09-19_pegasus-bob_semelle.png"
        status, body = self.get(self.port, own, "alice")
        self.assertEqual(status, 200)
        self.assertIn(b"ALICEMARK", body)
        self.assertEqual(self.get(self.port, theirs, "alice")[0], 404)
        self.assertEqual(self.get(self.port, own, "bob")[0], 404)

    def test_whoami(self):
        status, body = self.get(self.port, "/api/whoami", "bob")
        self.assertEqual((status, json.loads(body)), (200, {"member": "bob", "display_name": "Bob"}))

    def test_healthz_et_statique_anonymes_sans_donnee(self):
        status, body = self.get(self.port, "/healthz")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))
        status, body = self.get(self.port, "/")
        self.assertEqual(status, 200)
        for text in (b"alice", b"bob", b"ALICEMARK"):
            self.assertNotIn(text, body)

    def test_ecritures_toujours_refusees(self):
        self.assertEqual(self.get(self.port, "/api/summary", "alice", method="POST")[0], 405)

    def test_host_non_autorise_refuse(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/summary", headers={"Host": "evil.example", HEADER: "alice"})
        self.assertEqual(conn.getresponse().status, 403)

    def test_un_store_par_membre_ouvert_a_la_demande(self):
        registry = self.registry()
        stores = S.FamilyStores(registry, memory=True, today="2026-09-23")
        self.addCleanup(stores.stop_all)
        self.assertEqual(stores._stores, {})                           # rien d'ouvert au démarrage
        alice = stores.store(registry.members["alice"])
        self.assertIs(alice, stores.store(registry.members["alice"]))
        self.assertEqual(set(stores._stores), {"alice"})               # bob jamais ouvert sans requête de bob
        self.assertNotEqual(stores.store(registry.members["bob"]).workspace, alice.workspace)


class TestDashboardUntrustedSource(DashboardCase):
    def test_en_tete_usurpe_depuis_une_adresse_hors_trusted_proxies(self):
        # Le pair (127.0.0.1) n'est PAS un proxy de confiance : même un en-tête valide est refusé.
        port = self.start(self.registry(trusted=["203.0.113.9"]))
        for path in ("/api/summary", "/api/activities", "/api/whoami", "/media/gear-photo"):
            status, body = self.get(port, path, "alice")
            self.assertEqual(status, 403, path)
            self.assertNotIn(b"ALICEMARK", body)

    def test_cidr_et_nom_d_hote(self):
        port = self.start(self.registry(trusted=["127.0.0.0/8"]))
        self.assertEqual(self.get(port, "/api/whoami", "alice")[0], 200)


class TestDashboardChatProxy(DashboardCase):
    """`/api/chat/*` via le tableau de bord : identité exigée, en-tête relayé tel quel, jeton ntfy exempté."""

    def test_identite_exigee_et_en_tete_relaye(self):
        seen = []

        class Upstream(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get(HEADER)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_POST = do_GET

            def log_message(self, *a):
                pass

        up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        self.addCleanup(up.server_close)
        self.addCleanup(up.shutdown)
        registry = self.registry(extra_family=f"chat_port = {up.server_address[1]}")
        handler = type("H", (S.Handler,), {})
        handler.family = S.FamilyStores(registry, memory=True, today="2026-09-23")
        handler.chat_port = up.server_address[1]
        handler.tile_src = ""
        httpd = S.Server(("127.0.0.1", 0), handler)
        handler.allowed_hosts = S.host_allowlist(httpd.server_address[1], ["coach.example.org"])
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(handler.family.stop_all)
        port = httpd.server_address[1]
        self.assertEqual(self.get(port, "/api/chat/status")[0], 403)
        self.assertEqual(self.get(port, "/api/chat/status", "mallory")[0], 403)
        self.assertEqual(seen, [])                                      # rien n'a atteint le chat
        self.assertEqual(self.get(port, "/api/chat/status", "alice")[0], 200)
        self.assertEqual(seen, [("/api/chat/status", "alice")])         # en-tête relayé tel quel
        # route à jeton : source de confiance seulement (le jeton, lié au membre, est vérifié par le chat)
        self.assertEqual(self.get(port, "/api/chat/approve/alice~abc.def/allow")[0], 200)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

SCENARIO = {
    "chunk_chars": 50, "chunk_delay_s": 0.01,
    "turns": [{"match": ".*", "steps": [
        {"text": "Salut."},
        {"approval": {"tool": "mcp:garmin.schedule_workouts", "input": {"w": 1}, "summary": "S",
                      "diff": [{"op": "+", "text": "x"}], "allow": [{"text": "Fait."}],
                      "deny": [{"text": "Non."}], "pending": [{"text": "Attente."}]}},
    ]}],
}


class ChatCase(FamilyCase):
    TOPIC = {"alice": "topic-alice", "bob": "topic-bob"}

    def registry(self, **kw):
        token_file = self.root / "ntfy.token"
        token_file.write_text("tk_x\n", encoding="utf-8")
        workspaces = {m: make_workspace(
            self.root, m,
            f'[chat]\nntfy_delay_s = 0\npublic_url = "https://coach.example.org"\n'
            f'[notifications]\nprovider = "ntfy"\nntfy_topic = "{self.TOPIC[m]}"\n'
            f'ntfy_token_file = "{token_file}"\n') for m in ("alice", "bob")}
        return super().registry(workspaces=workspaces, **kw)

    def start(self, registry, backend_scenario=SCENARIO):
        scenario = self.root / "scenario.json"
        scenario.write_text(json.dumps(backend_scenario), encoding="utf-8")

        def factory(member, cfg):
            return M.MockBackend(member.workspace, {"mock_scenario": str(scenario), "mock_scenario_speed": 1000})

        self.sent = []
        patcher = mock.patch.object(C, "send_ntfy", lambda notif, title, body, actions="", timeout=10:
                                    self.sent.append((notif["ntfy_topic"], actions)) or True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fam = C.FamilyChat(registry, factory)
        httpd = C.make_family_server(self.fam, 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address[1]

    def call(self, port, method, path, user=None, body=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        headers = {"Host": "coach.example.org", "X-ARC-Chat": "1", "Content-Type": "application/json"}
        if user is not None:
            headers[HEADER] = user
        headers.update(extra or {})
        conn.request(method, path, body=json.dumps(body if body is not None else {}), headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw.decode("utf-8", "replace")

    def new_session(self, port, user):
        status, data = self.call(port, "POST", "/api/chat/sessions", user)
        self.assertEqual(status, 200)
        return data["id"]


class TestChatIsolation(ChatCase):
    def setUp(self):
        super().setUp()
        self.registry_ = self.registry()
        self.port = self.start(self.registry_)

    def wait_approval(self, user):
        svc = self.fam.services[user]
        for _ in range(200):
            pending = [r for r in svc.approvals._load().values()]
            if pending:
                return pending[0]["session_id"], list(svc.approvals._load())[0]
            time.sleep(0.05)
        self.fail("aucune proposition créée")

    def test_chaque_service_a_son_workspace_sa_politique_ses_sessions(self):
        a, b = self.fam.services["alice"], self.fam.services["bob"]
        self.assertEqual(a.workspace, self.workspaces["alice"])
        self.assertEqual(b.workspace, self.workspaces["bob"])
        self.assertIsNot(a.backend, b.backend)
        self.assertIsNot(a.policy, b.policy)
        self.assertNotEqual(a.sessions.dir, b.sessions.dir)
        self.assertEqual(a.notif["ntfy_topic"], "topic-alice")           # ntfy du workspace du membre
        self.assertEqual(b.notif["ntfy_topic"], "topic-bob")

    def test_identite_exigee_sur_chaque_route_de_chat(self):
        sid = self.new_session(self.port, "alice")
        routes = [("GET", "/api/chat/status"), ("GET", "/api/chat/sessions"), ("GET", f"/api/chat/sessions/{sid}"),
                  ("GET", "/api/chat/approvals/abcdef123456"), ("GET", "/api/chat/inconnue-future"),
                  ("POST", "/api/chat/sessions"), ("POST", f"/api/chat/sessions/{sid}/messages"),
                  ("POST", f"/api/chat/sessions/{sid}/interrupt"), ("POST", "/api/chat/approvals/abcdef123456"),
                  ("POST", "/api/chat/llm-check")]
        for method, path in routes:
            for user in (None, "mallory", ""):
                with self.subTest(method=method, path=path, user=user):
                    status, body = self.call(self.port, method, path, user, {"text": "x", "decision": "allow"})
                    self.assertEqual(status, 403)
                    self.assertNotIn("alice", json.dumps(body))
                    self.assertNotIn(sid, json.dumps(body))

    def test_aucune_donnee_croisee_sessions(self):
        sid = self.new_session(self.port, "alice")
        status, listing = self.call(self.port, "GET", "/api/chat/sessions", "bob")
        self.assertEqual((status, listing), (200, {"sessions": []}))
        self.assertEqual(self.call(self.port, "GET", f"/api/chat/sessions/{sid}", "bob")[0], 404)
        self.assertEqual(self.call(self.port, "POST", f"/api/chat/sessions/{sid}/messages", "bob",
                                   {"text": "bonjour"})[0], 404)
        self.assertEqual(self.call(self.port, "POST", f"/api/chat/sessions/{sid}/interrupt", "bob")[0], 404)
        self.assertEqual(self.call(self.port, "GET", f"/api/chat/sessions/{sid}", "alice")[0], 200)
        # aucun fichier de session de A dans le dossier de B
        self.assertFalse(list((self.workspaces["bob"] / ".arc/chat").glob(f"*{sid}*")))

    def test_statut_et_budget_par_membre(self):
        _, a = self.call(self.port, "GET", "/api/chat/status", "alice")
        _, b = self.call(self.port, "GET", "/api/chat/status", "bob")
        self.assertEqual((a["user"], b["user"]), ("alice", "bob"))

    def test_approbation_de_a_invisible_et_indecidable_par_b(self):
        sid = self.new_session(self.port, "alice")
        threading.Thread(target=lambda: self.call(self.port, "POST", f"/api/chat/sessions/{sid}/messages",
                                                  "alice", {"text": "bonjour"}), daemon=True).start()
        _, aid = self.wait_approval("alice")
        self.assertEqual(self.call(self.port, "GET", f"/api/chat/approvals/{aid}", "bob")[0], 404)
        self.assertEqual(self.call(self.port, "POST", f"/api/chat/approvals/{aid}", "bob",
                                   {"decision": "allow"})[0], 404)
        self.assertEqual(self.call(self.port, "GET", f"/api/chat/approvals/{aid}", "alice")[0], 200)
        self.assertIn(self.fam.services["alice"].approvals.get(aid)["status"], ("waiting", "pending"))
        self.assertEqual(self.call(self.port, "POST", f"/api/chat/approvals/{aid}", "alice",
                                   {"decision": "deny"})[0], 200)

    def test_jeton_ntfy_lie_au_membre(self):
        """Le lien ntfy de A porte `alice~…` ; refait pour B (préfixe changé, jeton nu, jeton de B inventé),
        il est refusé et la proposition de A reste ouverte. Le lien de A, lui, fonctionne."""
        sid = self.new_session(self.port, "alice")
        threading.Thread(target=lambda: self.call(self.port, "POST", f"/api/chat/sessions/{sid}/messages",
                                                  "alice", {"text": "bonjour"}), daemon=True).start()
        _, aid = self.wait_approval("alice")
        for _ in range(100):
            if self.sent:
                break
            time.sleep(0.05)
        topic, actions = self.sent[0]
        self.assertEqual(topic, "topic-alice")                           # push sur le topic de A, pas de B
        link = re.search(r"/api/chat/approve/([^/]+)/allow", actions)
        token = link.group(1)
        self.assertTrue(token.startswith("alice~"))
        _, _, bare = token.partition("~")
        post = lambda t: self.call(self.port, "POST", f"/api/chat/approve/{t}/allow")        # noqa: E731 — sans identité
        for forged in (f"bob~{bare}", bare, "bob~" + bare.split(".")[0] + ".x", "carol~" + bare, "~" + bare):
            with self.subTest(forged=forged[:12]):
                self.assertIn(post(forged)[0], (404, 410))
        self.assertIn(self.fam.services["alice"].approvals.get(aid)["status"], ("waiting", "pending"))
        # même base copiée chez B : l'empreinte inclut le membre → inutilisable
        self.assertEqual(self.fam.services["bob"].approvals.verify_token(bare, "allow")[0], "unknown")
        self.assertEqual(post(token)[0], 200)
        self.assertEqual(self.fam.services["alice"].approvals.get(aid)["status"], "allowed")

    def test_route_a_jeton_refusee_hors_proxy_de_confiance(self):
        fam = C.FamilyChat(self.registry(trusted=["203.0.113.9"]), lambda m, c: M.MockBackend(m.workspace, {}))
        httpd = C.make_family_server(fam, 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_address[1]
        self.assertEqual(self.call(port, "POST", "/api/chat/approve/alice~abcdefgh.secret/allow")[0], 403)
        self.assertEqual(self.call(port, "GET", "/api/chat/status", "alice")[0], 403)     # en-tête usurpé
        self.assertEqual(self.call(port, "POST", "/api/chat/sessions", "alice")[0], 403)

    def test_healthz_anonyme_depuis_la_boucle_locale_sans_donnee(self):
        status, body = self.call(self.port, "GET", "/api/chat/healthz")
        self.assertEqual((status, body), (200, {"ok": True, "members": 2}))


class TestChatBudget(ChatCase):
    def test_plafond_du_foyer_en_plus_du_budget_de_chaque_membre(self):
        registry = self.registry(extra_family="daily_budget_eur = 3.0")
        self.start(registry)
        a, b = self.fam.services["alice"], self.fam.services["bob"]
        self.assertEqual(float(a.cfg["daily_budget_eur"]), 2.0)           # budget propre inchangé
        a.spend.add(1.5)
        b.spend.add(1.0)
        self.assertAlmostEqual(self.fam.household_remaining(), 0.5)
        self.assertAlmostEqual(a.remaining_budget(), 0.5)                # min(propre 0.5, foyer 0.5)
        self.assertAlmostEqual(b.remaining_budget(), 0.5)                # propre 1.0, foyer 0.5
        self.assertFalse(b.budget_exhausted())
        a.spend.add(0.5)
        self.assertTrue(a.budget_exhausted())                            # propre 2.0 atteint
        self.assertTrue(b.budget_exhausted())                            # foyer 3.0 atteint alors que B a 1.0 €
        self.assertEqual(b.remaining_budget(), 0.0)

    def test_sans_plafond_comportement_mono_membre(self):
        self.start(self.registry())
        a = self.fam.services["alice"]
        self.assertIsNone(a.household_remaining)
        a.spend.add(1.0)
        self.assertAlmostEqual(a.remaining_budget(), 1.0)


class TestPolicyJail(FamilyCase):
    def test_la_politique_de_a_refuse_tout_chemin_du_workspace_de_b(self):
        registry = self.registry()
        alice, bob = registry.members["alice"].workspace, registry.members["bob"].workspace
        policy = Policy.load(C.ENGINE, alice)
        own = "activities/2026-09-20_trail.md"
        self.assertEqual(policy.decide("fs.read", {"path": own}), "allow")
        foreign = [str(bob / "activities/2026-09-19_trail.md"), str(bob), "../coach-bob/activities/2026-09-19_trail.md",
                   str(bob / "planning/Runner_Profile.md")]
        for path in foreign:
            with self.subTest(path=path):
                self.assertEqual(policy.decide("fs.read", {"path": path}), "deny")
                self.assertEqual(policy.decide("fs.write", {"path": path}), "deny")
                self.assertEqual(policy.decide("fs.list", {"path": path}), "deny")
        # lien symbolique de A vers le workspace de B : suivi, puis refusé
        link = alice / "planning" / "lien-bob"
        link.symlink_to(bob)
        self.assertEqual(policy.decide("fs.read", {"path": "planning/lien-bob/activities/2026-09-19_trail.md"}), "deny")
        self.assertEqual(policy.decide("shell", {"command": f"python3 scripts/arc_index.py --workspace {bob}"}), "deny")

    def test_une_politique_par_membre(self):
        registry = self.registry()
        fam = C.FamilyChat(registry, lambda m, c: M.MockBackend(m.workspace, {}))
        a, b = fam.services["alice"].policy, fam.services["bob"].policy
        self.assertEqual(a.workspace, registry.members["alice"].workspace.resolve())
        self.assertEqual(b.workspace, registry.members["bob"].workspace.resolve())
        bob_file = str(registry.members["bob"].workspace / "activities/2026-09-19_trail.md")
        self.assertEqual(a.decide("fs.read", {"path": bob_file}), "deny")
        self.assertEqual(b.decide("fs.read", {"path": bob_file}), "allow")


class TestMonoAthleteInchange(FamilyCase):
    """Sans `--family`, ni le serveur ni le chat ne changent : jetons sans préfixe, empreinte historique."""

    def test_empreinte_de_jeton_historique(self):
        self.assertEqual(C.token_digest("id", "h", "s"), C.token_digest("id", "h", "s", ""))
        self.assertNotEqual(C.token_digest("id", "h", "s", "alice"), C.token_digest("id", "h", "s"))
        self.assertNotEqual(C.token_digest("id", "h", "s", "alice"), C.token_digest("id", "h", "s", "bob"))

    def test_chat_mono_athlete_sans_prefixe(self):
        ws = make_workspace(self.root, "alice")
        cfg = dict(C.CHAT_DEFAULTS)
        svc = C.ChatService(ws, cfg, M.MockBackend(ws, {}))
        self.assertEqual(svc.token_prefix, "")
        self.assertIsNone(svc.household_remaining)
        self.assertEqual(svc.approvals.member, "")

    def test_handler_sans_famille(self):
        self.assertIsNone(S.Handler.family)
        self.assertNotIn("--family", sys.argv)


if __name__ == "__main__":
    unittest.main()
