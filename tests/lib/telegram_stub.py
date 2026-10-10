"""Faux serveur de l'API Bot Telegram (palier D/A) : aucun réseau, aucun vrai jeton.

Démarre un `ThreadingHTTPServer` en boucle locale qui répond comme `api.telegram.org`
(`/bot<jeton>/<méthode>`), enregistre chaque appel et sert une file d'updates scriptée.
Un mauvais jeton reçoit 401, comme le vrai service.

    with TelegramStub() as stub:
        stub.queue_update({"message": {...}})
        os.environ["ARC_TELEGRAM_API_BASE"] = stub.base
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler

from tests.lib.local_http import ThreadingHTTPServer

FAKE_TOKEN = "123456789:AAFakeTokenForTestsOnly_0123456789abcdefg"


class TelegramStub:
    def __init__(self, token: str = FAKE_TOKEN):
        self.token = token
        self.calls: list = []            # [(méthode, params)]
        self.updates: list = []          # updates en attente (avec update_id)
        self.fail_next: dict = {}        # méthode -> (code, description, parameters)
        self._next_id = 100
        self._next_message_id = 1000
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                params = json.loads(self.rfile.read(length) or b"{}")
                prefix = f"/bot{stub.token}/"
                if not self.path.startswith(prefix):
                    return self._send({"ok": False, "error_code": 401, "description": "Unauthorized"}, 401)
                method = self.path[len(prefix):]
                with stub._lock:
                    stub.calls.append((method, params))
                    failure = stub.fail_next.pop(method, None)
                    if failure:
                        code, description, extra = failure
                        body = {"ok": False, "error_code": code, "description": description}
                        if extra:
                            body["parameters"] = extra
                        return self._send(body, code)
                    if method == "getUpdates":
                        offset = int(params.get("offset") or 0)
                        stub.updates = [u for u in stub.updates if u["update_id"] >= offset]
                        if not stub.updates:
                            time.sleep(0.02)
                        return self._send({"ok": True, "result": list(stub.updates)})
                    if method == "sendMessage":
                        stub._next_message_id += 1
                        return self._send({"ok": True, "result": {"message_id": stub._next_message_id}})
                    return self._send({"ok": True, "result": True})

            def _send(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "TelegramStub":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def queue_update(self, update: dict) -> int:
        with self._lock:
            self._next_id += 1
            self.updates.append(dict(update, update_id=self._next_id))
            return self._next_id

    def sent(self, method: str = "sendMessage") -> list:
        with self._lock:
            return [p for m, p in self.calls if m == method]

    def texts(self) -> list:
        return [p.get("text", "") for p in self.sent("sendMessage")]
