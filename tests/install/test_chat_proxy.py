"""Palier A — proxy local `/api/chat/*` de `arc_serve.py` vers le service de chat.

Un faux service amont (port 0) diffuse du SSE lentement ; le vrai `arc_serve.py`
tourne sur un workspace de bac à sable avec `[chat] enabled = true`. Aucun modèle,
aucun réseau externe.
"""

from __future__ import annotations

import datetime
import http.client
import json
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.install.test_dashboard import Server
from tests.lib.asserts import InstallAsserts
from tests.lib.local_http import ThreadingHTTPServer
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-09-23"
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import arc_chat  # noqa: E402
import arc_serve  # noqa: E402
from arc_chat_mock import MockBackend  # noqa: E402


class FakeChat(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        FakeChat.seen.append(("GET", self.path, dict(self.headers), b""))
        body = b'{"enabled": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        FakeChat.seen.append(("POST", self.path, dict(self.headers), self._read()))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        for i in range(3):
            self.wfile.write(f'event: text_delta\ndata: {{"text": "{i}"}}\n\n'.encode())
            self.wfile.flush()
            time.sleep(0.4)
        self.wfile.write(b"event: done\ndata: {}\n\n")
        self.wfile.flush()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChatProxyBase(InstallAsserts):
    chat_enabled = True

    def setUp(self):
        FakeChat.seen = []
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), FakeChat)
        self.up.daemon_threads = True
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.port = self.up.server_address[1]
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=10, today=datetime.date.fromisoformat(TODAY))
        self._configure(self.port)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url)
        self.host, self.dport = self.server.url.split("//")[1].rstrip("/").split(":")

    def _configure(self, port):
        user = self.ws / "config/workspace.user.toml"
        prev = user.read_text(encoding="utf-8") if user.exists() else ""
        user.write_text(prev + f"\n[chat]\nenabled = {str(self.chat_enabled).lower()}\nport = {port}\n",
                        encoding="utf-8")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)
        self.up.shutdown()
        self.up.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(self.host, int(self.dport), timeout=15)
        conn.request(method, path, body=body, headers=headers or {})
        return conn, conn.getresponse()


class TestChatProxyEnabled(ChatProxyBase):
    def test_get_is_relayed_without_cors(self):
        conn, res = self.request("GET", "/api/chat/status")
        self.assertEqual(res.status, 200)
        self.assertEqual(json.loads(res.read()), {"enabled": True})
        self.assertIsNone(res.getheader("Access-Control-Allow-Origin"))
        conn.close()

    def test_post_streams_chunks_as_they_come_and_forwards_headers(self):
        origin = f"http://{self.host}:{self.dport}"
        conn, res = self.request(
            "POST", "/api/chat/sessions/abc/messages", body=json.dumps({"text": "salut"}),
            headers={"Content-Type": "application/json", "X-ARC-Chat": "1",
                     "Origin": origin, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(res.status, 200)
        self.assertEqual(res.getheader("Content-Type"), "text/event-stream")
        start = time.monotonic()
        first = res.fp.readline()                      # premier bloc bien avant la fin (~1,2 s)
        self.assertIn(b"text_delta", first)
        self.assertLess(time.monotonic() - start, 0.35)
        rest = res.read()
        self.assertIn(b"event: done", rest)
        conn.close()
        method, path, headers, body = FakeChat.seen[-1]
        self.assertEqual((method, path), ("POST", "/api/chat/sessions/abc/messages"))
        self.assertEqual(json.loads(body), {"text": "salut"})
        lower = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(lower["x-arc-chat"], "1")
        self.assertEqual(lower["sec-fetch-site"], "same-origin")
        self.assertEqual(lower["origin"], origin)
        self.assertEqual(lower["host"], f"{self.host}:{self.dport}")

    def test_foreign_host_is_refused_before_proxying(self):
        conn, res = self.request("POST", "/api/chat/sessions", body="{}",
                                 headers={"Host": "evil.example", "X-ARC-Chat": "1"})
        self.assertEqual(res.status, 403)
        conn.close()
        self.assertEqual(FakeChat.seen, [])

    def test_other_posts_stay_read_only(self):
        conn, res = self.request("POST", "/api/summary", body="{}")
        self.assertEqual(res.status, 405)
        conn.close()

    def test_summary_settings_expose_chat_enabled(self):
        conn, res = self.request("GET", "/api/summary")
        self.assertTrue(json.loads(res.read())["settings"]["chat_enabled"])
        conn.close()


class TestChatProxyUpstreamDown(ChatProxyBase):
    def _configure(self, port):
        super()._configure(_free_port())               # port où personne n'écoute

    def test_502_json_when_service_is_unreachable(self):
        conn, res = self.request("GET", "/api/chat/status")
        self.assertEqual(res.status, 502)
        self.assertIn("coach-chat.sh start", json.loads(res.read())["error"])
        conn.close()


class TestChatProxyDisabled(ChatProxyBase):
    chat_enabled = False

    def test_no_proxy_when_chat_is_disabled(self):
        conn, res = self.request("GET", "/api/chat/status")
        self.assertEqual(res.status, 404)
        res.read()
        conn.close()
        conn, res = self.request("POST", "/api/chat/sessions", body="{}", headers={"X-ARC-Chat": "1"})
        self.assertEqual(res.status, 405)
        conn.close()
        self.assertEqual(FakeChat.seen, [])

    def test_summary_settings_hide_chat(self):
        conn, res = self.request("GET", "/api/summary")
        self.assertFalse(json.loads(res.read())["settings"]["chat_enabled"])
        conn.close()


class TestChatProxyAttachments(ChatProxyBase):
    """Pièces jointes (#342) à travers le proxy : un VRAI service de chat derrière `arc_serve.py`."""

    LIMIT = 3 * 1024 * 1024
    GPX = (b'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk/></gpx>')

    def _configure(self, port):
        cfg = dict(arc_chat.CHAT_DEFAULTS, enabled=True, backend="mock", rate_limit_per_min=0,
                   upload_max_bytes=self.LIMIT)
        original, arc_chat.log = arc_chat.log, lambda message: None
        self.addCleanup(lambda: setattr(arc_chat, "log", original))
        httpd, self.service = arc_chat.make_server(self.ws, cfg, MockBackend(self.ws, cfg), None, port=0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        user = self.ws / "config/workspace.user.toml"
        prev = user.read_text(encoding="utf-8") if user.exists() else ""
        user.write_text(prev + f"\n[chat]\nenabled = true\nport = {httpd.server_address[1]}\n"
                        f"upload_max_bytes = {self.LIMIT}\n", encoding="utf-8")

    def upload(self, sid, data, name="sortie.gpx", length=None):
        headers = {"X-ARC-Chat": "1", "Content-Type": "application/octet-stream",
                   "X-Filename": name, "Content-Length": str(len(data) if length is None else length)}
        conn = http.client.HTTPConnection(self.host, int(self.dport), timeout=15)
        conn.request("POST", f"/api/chat/sessions/{sid}/attachments", body=data, headers=headers)
        res = conn.getresponse()
        body = json.loads(res.read() or b"{}")
        conn.close()
        return res.status, body

    def new_session(self):
        conn, res = self.request("POST", "/api/chat/sessions", body="{}", headers={"X-ARC-Chat": "1"})
        sid = json.loads(res.read())["id"]
        conn.close()
        return sid

    def test_upload_traverse_le_proxy_avec_son_nom_et_arrive_dans_le_workspace(self):
        sid = self.new_session()
        status, body = self.upload(sid, self.GPX, "Ma sortie.gpx")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kind"], "gpx")
        self.assertTrue(body["path"].startswith("planning/inbox/") and body["path"].endswith("_ma-sortie.gpx"))
        self.assertEqual((self.ws / body["path"]).read_bytes(), self.GPX)

    def test_fichier_plus_gros_que_le_plafond_refuse_sans_lire_le_corps(self):
        sid = self.new_session()
        conn = http.client.HTTPConnection(self.host, int(self.dport), timeout=15)
        conn.putrequest("POST", f"/api/chat/sessions/{sid}/attachments")
        for name, value in (("X-ARC-Chat", "1"), ("X-Filename", "a.gpx"), ("Content-Length", str(self.LIMIT + 1))):
            conn.putheader(name, value)
        conn.endheaders()                                   # aucun octet de corps envoyé
        res = conn.getresponse()
        self.assertEqual(res.status, 413)
        res.read()
        conn.close()

    def test_les_routes_json_gardent_un_plafond_modeste(self):
        sid = self.new_session()
        conn = http.client.HTTPConnection(self.host, int(self.dport), timeout=15)
        conn.putrequest("POST", f"/api/chat/sessions/{sid}/messages")
        for name, value in (("X-ARC-Chat", "1"), ("Content-Type", "application/json"),
                            ("Content-Length", str(arc_serve.CHAT_BODY_MAX + 1))):
            conn.putheader(name, value)
        conn.endheaders()
        res = conn.getresponse()
        self.assertEqual(res.status, 413)
        res.read()
        conn.close()

    def test_refus_du_service_avec_corps_de_2_mo_atteignent_le_client(self):
        """Avant correction : 502 « service injoignable » ou reset, car le service fermait avec le corps non lu."""
        sid = self.new_session()
        big = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
        status, body = self.upload(sid, big, "IMG_1.HEIC")
        self.assertEqual(status, 415, body)
        self.assertIn("JPEG", body["error"])
        status, body = self.upload("inconnue123456", big, "photo.jpg")
        self.assertEqual(status, 404, body)
        self.service.upload_limiter.per_min = 1
        self.assertEqual(self.upload(sid, big, "photo.jpg")[0], 200)
        status, body = self.upload(sid, big, "photo.jpg")
        self.assertEqual(status, 429, body)
        self.assertIn("Trop de fichiers", body["error"])

    def test_413_du_proxy_avec_corps_reel(self):
        sid = self.new_session()
        status, body = self.upload(sid, b"\xff\xd8\xff" + b"\x00" * (4 * 1024 * 1024), "photo.jpg")
        self.assertEqual(status, 413, body)
        self.assertIn("error", body)

    def test_413_du_service_avec_corps_reel_via_le_proxy(self):
        sid = self.new_session()
        self.service.cfg["upload_max_bytes"] = 1000                 # le proxy laisse passer, le service refuse
        status, body = self.upload(sid, b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024), "photo.jpg")
        self.assertEqual(status, 413, body)
        self.assertIn("1 Ko", body["error"])

    def test_client_qui_coupe_en_cours_d_envoi_ne_laisse_rien(self):
        sid = self.new_session()
        conn = http.client.HTTPConnection(self.host, int(self.dport), timeout=15)
        conn.putrequest("POST", f"/api/chat/sessions/{sid}/attachments")
        for name, value in (("X-ARC-Chat", "1"), ("X-Filename", "a.gpx"), ("Content-Length", "100000")):
            conn.putheader(name, value)
        conn.endheaders(self.GPX)
        conn.close()                                          # coupe après 100 octets sur 100000
        inbox = self.ws / "planning/inbox"
        # État observable : le service a créé le temporaire (le dossier existe), puis il doit l'avoir supprimé.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not inbox.exists():
            time.sleep(0.05)
        self.assertTrue(inbox.exists(), "le service n'a jamais reçu l'envoi")
        while time.monotonic() < deadline and any(inbox.iterdir()):
            time.sleep(0.05)
        self.assertEqual([p.name for p in inbox.iterdir()], [])

    def test_client_qui_s_arrete_au_milieu_est_libere_en_temps_borne(self):
        """10 Ko sur 2 Mo annoncés puis plus rien : le proxy répond (408) après son délai d'inactivité, sans
        attendre les 60 s du service, et le fil est libéré (une requête suivante passe)."""
        sid = self.new_session()
        sock = socket.create_connection((self.host, int(self.dport)), timeout=30)
        self.addCleanup(sock.close)
        head = (f"POST /api/chat/sessions/{sid}/attachments HTTP/1.1\r\nHost: {self.host}:{self.dport}\r\n"
                f"X-ARC-Chat: 1\r\nX-Filename: a.gpx\r\nContent-Length: {2 * 1024 * 1024}\r\n\r\n").encode()
        sock.sendall(head + b"<" * 10240)
        started = time.monotonic()
        reply = b""
        while b"\r\n\r\n" not in reply:
            chunk = sock.recv(65536)
            if not chunk:
                break
            reply += chunk
        elapsed = time.monotonic() - started
        self.assertIn(b" 408 ", reply.split(b"\r\n")[0], reply)
        self.assertLess(elapsed, 25)
        self.assertEqual(self.new_session() is not None, True)             # le serveur répond encore
        inbox = self.ws / "planning/inbox"
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and inbox.exists() and any(inbox.iterdir()):
            time.sleep(0.05)
        self.assertEqual([p.name for p in inbox.iterdir()] if inbox.exists() else [], [])

    def test_contenu_refuse_par_le_service_est_relaye(self):
        sid = self.new_session()
        status, body = self.upload(sid, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "faux.gpx")
        self.assertEqual(status, 415, body)
        self.assertFalse((self.ws / "planning/inbox").exists() and any((self.ws / "planning/inbox").iterdir()))


class TestChatProxyPort(unittest.TestCase):
    def test_only_on_loopback_and_when_enabled(self):
        on = {"chat": {"enabled": True, "port": 9000}}
        self.assertEqual(arc_serve.chat_proxy_port(on, "127.0.0.1"), 9000)
        self.assertIsNone(arc_serve.chat_proxy_port(on, "0.0.0.0"))
        self.assertIsNone(arc_serve.chat_proxy_port({"chat": {"enabled": False}}, "127.0.0.1"))
        self.assertIsNone(arc_serve.chat_proxy_port({}, "127.0.0.1"))
        self.assertEqual(arc_serve.chat_proxy_port({"chat": {"enabled": True}}, "127.0.0.1"), 8766)
        self.assertIsNone(arc_serve.chat_proxy_port({"chat": {"enabled": True, "port": "x"}}, "127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
