"""Serveur ntfy factice : enregistre chaque POST reçu, sans jamais toucher au réseau.

Les en-têtes encodés en RFC 2047 (`=?UTF-8?B?…?=`, envoyés par `scripts/arc_notify.py` pour
un titre avec accents ou emoji) sont décodés comme le fait ntfy, pour que les tests lisent le
texte affiché sur le téléphone.
"""

from __future__ import annotations

import email.header
import threading
import time
from http.server import BaseHTTPRequestHandler

from tests.lib.local_http import HTTPServer


def decode_header(value: str) -> str:
    if "=?" not in value:
        return value
    return "".join(part.decode(charset or "utf-8") if isinstance(part, bytes) else part
                   for part, charset in email.header.decode_header(value))


class FakeNtfy:
    """Chaque message reçu : {"path", "headers" (décodés), "body"}."""

    def __init__(self):
        received = self.received = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                received.append({"path": self.path,
                                 "headers": {k: decode_header(v) for k, v in self.headers.items()},
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
