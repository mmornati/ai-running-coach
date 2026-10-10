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
import arc_serve  # noqa: E402


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
