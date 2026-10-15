"""Palier A — `scripts/arc_llm.py` : catalogue et connexion OpenRouter en un clic (#265).

Un faux serveur OpenRouter écoute sur 127.0.0.1 (ARC_OPENROUTER_BASE_URL). Aucun réseau réel,
aucun navigateur (--no-browser : le test joue le rôle du navigateur). Verrouille :
  - le flux PKCE (S256, state, callback loopback) et l'écriture de llm.env ;
  - refus de l'athlète, state invalide, délai dépassé, échange en 4xx/5xx, mode --headless ;
  - qu'aucune clé n'apparaît dans stdout/stderr ;
  - la cohérence catalogue / constantes d'install.sh, et `install.sh --connect`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.local_http import HTTPServer as LocalHTTPServer
from tests.lib.sandbox import Sandbox

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "arc_llm.py"
SECRET_KEY = "sk-or-v1-FAKE-SECRET-KEY-0123456789"


class FakeOpenRouter:
    """Faux OpenRouter : POST /api/v1/auth/keys et GET /api/v1/key."""

    def __init__(self, exchange_status: int = 200, key_status: int = 200, is_free_tier: bool = True,
                 free_quota: bool = True) -> None:
        self.free_quota = free_quota
        self.exchange_status = exchange_status
        self.key_status = key_status
        self.is_free_tier = is_free_tier
        self.exchanges: list = []
        self.key_auth: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.exchanges.append(json.loads(self.rfile.read(length) or b"{}"))
                if outer.exchange_status == 200:
                    self._send(200, {"key": SECRET_KEY, "user_id": "u1"})
                else:
                    self._send(outer.exchange_status, {"error": {"message": "nope " + SECRET_KEY}})

            def do_GET(self):
                outer.key_auth.append(self.headers.get("Authorization"))
                if outer.key_status != 200:
                    self._send(outer.key_status, {"error": {"message": "refused"}})
                    return
                data = {"label": "AI Running Coach", "limit": None, "limit_remaining": None,
                        "usage": 0.12, "is_free_tier": outer.is_free_tier}
                if outer.free_quota:
                    data["free_model_daily_requests"] = {"used": 3, "limit": 50, "remaining": 47}
                self._send(200, {"data": data})

        self.server = LocalHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _spawn(fake: FakeOpenRouter, env_file: Path, *extra: str, stdin: bool = False):
    env = dict(os.environ, ARC_OPENROUTER_BASE_URL=fake.url, HOME=str(env_file.parent))
    env.pop("ARC_LLM_ENV", None)
    return subprocess.Popen(
        [sys.executable, str(SCRIPT), "connect", "openrouter", "--json", "--no-browser",
         "--env-file", str(env_file), *extra],
        env=env, text=True, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _auth_url(proc) -> str:
    """Lit la progression JSON sur stderr jusqu'à l'événement auth_url ; garde le reste."""
    while True:
        line = proc.stderr.readline()
        if not line:
            raise AssertionError("pas d'événement auth_url")
        event = json.loads(line)
        if event.get("event") == "auth_url":
            return event["url"]


def _finish(proc, timeout: int = 30):
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _callback(auth_url: str, **query) -> str:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(auth_url).query)
    return q["callback_url"][0] + "?" + urllib.parse.urlencode(query)


class ConnectOpenRouterTests(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        self.env_file = self.sb.home / ".config/ai-running-coach/llm.env"

    def assertNoSecret(self, *texts: str) -> None:
        for t in texts:
            self.assertNotIn(SECRET_KEY, t)
            self.assertNotIn("FAKE-SECRET", t)

    def test_success_pkce_and_env_file(self):
        self.env_file.parent.mkdir(parents=True)
        self.env_file.write_text("# commentaire\nOTHER_KEY=keep-me\n# OPENROUTER_API_KEY=\nANTHROPIC_API_KEY=abc\n")
        self.env_file.chmod(0o644)
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertTrue(url.startswith(fake.url + "/auth?"))
            self.assertEqual(q["code_challenge_method"], ["S256"])
            self.assertIn("127.0.0.1", q["callback_url"][0])
            self.assertTrue(q["state"][0])
            status, page = _get(_callback(url, code="the-code", state=q["state"][0]))
            self.assertEqual(status, 200)
            self.assertIn("Autorisation reçue", page)
            self.assertNotIn("connecté", page)
            rc, out, err = _finish(proc)
            exchange = fake.exchanges[0]
        self.assertEqual(rc, 0, err)
        # PKCE : le défi publié est bien le S256 du vérificateur envoyé à l'échange.
        digest = hashlib.sha256(exchange["code_verifier"].encode()).digest()
        self.assertEqual(base64.urlsafe_b64encode(digest).decode().rstrip("="), q["code_challenge"][0])
        self.assertEqual(exchange["code"], "the-code")
        self.assertEqual(exchange["code_challenge_method"], "S256")
        result = json.loads(out)
        self.assertTrue(result["ok"])
        self.assertTrue(result["is_free_tier"])
        self.assertEqual(result["label"], "AI Running Coach")
        self.assertIn("47 requête(s) restante(s) aujourd'hui sur 50", result["message"])
        self.assertNotIn("1 000", result["message"])
        self.assertEqual(fake.key_auth, ["Bearer " + SECRET_KEY])
        self.assertNoSecret(out, err)
        text = self.env_file.read_text()
        self.assertIn("OPENROUTER_API_KEY=" + SECRET_KEY, text)
        self.assertEqual(text.count("OPENROUTER_API_KEY="), 1)
        self.assertIn("OTHER_KEY=keep-me", text)
        self.assertIn("ANTHROPIC_API_KEY=abc", text)
        self.assertIn("# commentaire", text)
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)

    def test_new_file_and_directory_modes(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="c", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 0, err)
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.env_file.parent.stat().st_mode), 0o700)

    def test_existing_active_key_replaced(self):
        self.env_file.parent.mkdir(parents=True)
        self.env_file.write_text("OPENROUTER_API_KEY=old-value\nX=1\n")
        with FakeOpenRouter(is_free_tier=False) as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="c", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 0, err)
        text = self.env_file.read_text()
        self.assertNotIn("old-value", text)
        self.assertEqual(text.count("OPENROUTER_API_KEY="), 1)
        self.assertIn("X=1", text)
        self.assertFalse(json.loads(out)["is_free_tier"])

    def test_neutral_message_without_free_quota(self):
        with FakeOpenRouter(free_quota=False) as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="c", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 0, err)
        self.assertIn("quota gratuit non communiqué", json.loads(out)["message"])

    def test_denial_without_state_or_code(self):
        # OpenRouter ne renvoie ni code ni state quand l'athlète refuse.
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            status, page = _get(_callback(url))
            self.assertIn("annulée", page)
            rc, out, err = _finish(proc)
            self.assertEqual(fake.exchanges, [])
        self.assertEqual(rc, 3)
        self.assertFalse(self.env_file.exists())

    def test_idle_connection_does_not_block_callback(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            port = urllib.parse.urlsplit(q["callback_url"][0]).port
            idle = socket.create_connection(("127.0.0.1", port))  # préconnexion muette
            try:
                started = time.monotonic()
                _get(_callback(url, code="c", state=q["state"][0]))
                rc, out, err = _finish(proc)
                self.assertLess(time.monotonic() - started, 20)
            finally:
                idle.close()
        self.assertEqual(rc, 0, err)

    def test_timeout_enforced_with_idle_connection(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file, "--timeout", "2")
            url = _auth_url(proc)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            port = urllib.parse.urlsplit(q["callback_url"][0]).port
            idle = socket.create_connection(("127.0.0.1", port))
            try:
                started = time.monotonic()
                rc, out, err = _finish(proc)
                self.assertLess(time.monotonic() - started, 15)
            finally:
                idle.close()
        self.assertEqual(rc, 4)

    def test_non_ascii_state_is_rejected_not_crashing(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            status, _ = _get(_callback(url, code="evil", state="éè"))
            self.assertEqual(status, 400)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="good", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 0, err)
        self.assertNotIn("Traceback", err)

    def test_symlinked_env_file_keeps_the_link(self):
        real = self.sb.home / "dotfiles/llm.env"
        real.parent.mkdir(parents=True)
        real.write_text("KEEP=1\n")
        real.chmod(0o600)
        self.env_file.parent.mkdir(parents=True)
        self.env_file.symlink_to(real)
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="c", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 0, err)
        self.assertTrue(self.env_file.is_symlink())
        self.assertIn("OPENROUTER_API_KEY=" + SECRET_KEY, real.read_text())
        self.assertIn("KEEP=1", real.read_text())
        self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o600)

    def test_non_utf8_env_file_gives_clear_error(self):
        self.env_file.parent.mkdir(parents=True)
        self.env_file.write_bytes(b"A=\xff\xfe\n")
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 2)
        self.assertIn("UTF-8", json.loads(out)["message"])
        self.assertNotIn("Traceback", err)

    def test_sigint_exits_cleanly(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            _auth_url(proc)
            proc.send_signal(signal.SIGINT)
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 130)
        self.assertEqual(json.loads(out)["error"], "interrupted")
        self.assertNotIn("Traceback", err)
        self.assertFalse(self.env_file.exists())

    def test_user_denial(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            status, page = _get(_callback(url, error="access_denied"))
            self.assertIn("annulée", page)
            rc, out, err = _finish(proc)
            self.assertEqual(fake.exchanges, [])
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(out)["error"], "denied")
        self.assertFalse(self.env_file.exists())

    def test_bad_state_rejected_then_good_state_accepted(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            status, _ = _get(_callback(url, code="evil", state="forged"))
            self.assertEqual(status, 400)
            status, _ = _get(_callback(url, code="evil"))
            self.assertEqual(status, 400)
            self.assertEqual(fake.exchanges, [])
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="good", state=state))
            rc, out, err = _finish(proc)
            self.assertEqual(fake.exchanges[0]["code"], "good")
        self.assertEqual(rc, 0, err)

    def test_timeout(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file, "--timeout", "1")
            _auth_url(proc)
            rc, out, err = _finish(proc)
            self.assertEqual(fake.exchanges, [])
        self.assertEqual(rc, 4)
        self.assertEqual(json.loads(out)["error"], "timeout")
        self.assertFalse(self.env_file.exists())

    def test_exchange_errors_write_nothing(self):
        for status in (403, 500):
            with self.subTest(status=status):
                with FakeOpenRouter(exchange_status=status) as fake:
                    proc = _spawn(fake, self.env_file)
                    url = _auth_url(proc)
                    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
                    _get(_callback(url, code="c", state=state))
                    rc, out, err = _finish(proc)
                self.assertEqual(rc, 5)
                self.assertEqual(json.loads(out)["http_status"], status)
                self.assertNoSecret(out, err)
                self.assertFalse(self.env_file.exists())

    def test_unverified_key_is_stored_with_exit_6(self):
        with FakeOpenRouter(key_status=401) as fake:
            proc = _spawn(fake, self.env_file)
            url = _auth_url(proc)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="c", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 6)
        self.assertEqual(json.loads(out)["error"], "unverified")
        self.assertIn("OPENROUTER_API_KEY=" + SECRET_KEY, self.env_file.read_text())
        self.assertNoSecret(out, err)

    def test_headless_paste(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file, "--headless", stdin=True)
            url = _auth_url(proc)
            self.assertNotIn("callback_url", url)
            self.assertIn("code_challenge=", url)
            out, err = proc.communicate("pasted-code\n", timeout=30)
            exchange = fake.exchanges[0]
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(exchange["code"], "pasted-code")
        self.assertNoSecret(out, err)
        self.assertTrue(json.loads(out)["ok"])

    def test_headless_empty_paste_is_denial(self):
        with FakeOpenRouter() as fake:
            proc = _spawn(fake, self.env_file, "--headless", stdin=True)
            _auth_url(proc)
            out, err = proc.communicate("\n", timeout=30)
        self.assertEqual(proc.returncode, 3)

    def test_base_url_override_refused_outside_loopback(self):
        env = dict(os.environ, ARC_OPENROUTER_BASE_URL="https://evil.example.com")
        proc = subprocess.run([sys.executable, str(SCRIPT), "connect", "openrouter", "--json", "--no-browser",
                               "--env-file", str(self.env_file)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(self.env_file.exists())

    def test_unknown_provider_is_usage_error(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "connect", "nope"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)

    def test_default_env_file_from_arc_llm_env(self):
        target = self.sb.home / "elsewhere/llm.env"
        with FakeOpenRouter() as fake:
            env = dict(os.environ, ARC_OPENROUTER_BASE_URL=fake.url, ARC_LLM_ENV=str(target))
            proc = subprocess.Popen([sys.executable, str(SCRIPT), "connect", "openrouter", "--json", "--no-browser"],
                                    env=env, text=True, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            url = _auth_url(proc)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            _get(_callback(url, code="c", state=state))
            rc, out, err = _finish(proc)
        self.assertEqual(rc, 0, err)
        self.assertIn("OPENROUTER_API_KEY=", target.read_text())


class CatalogTests(InstallAsserts):
    def test_providers_json(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "providers", "--json"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        providers = {p["id"]: p for p in json.loads(proc.stdout)["providers"]}
        self.assertEqual(set(providers), {"openrouter", "anthropic", "openai"})
        for p in providers.values():
            for field in ("label", "kind", "chat_model", "sync_model", "key_env", "monthly_cost", "privacy", "docs"):
                self.assertIn(field, p)
        self.assertEqual(providers["openrouter"]["kind"], "oauth")

    def test_runs_on_python39(self):
        py = shutil.which("python3.9") or ("/usr/bin/python3" if os.path.exists("/usr/bin/python3") else None)
        if not py:
            self.skipTest("pas de Python 3.9 disponible")
        version = subprocess.run([py, "-c", "import sys;print(sys.version_info[:2] <= (3, 9))"],
                                 capture_output=True, text=True).stdout.strip()
        if version != "True":
            self.skipTest("Python 3.9 absent (python3.9 / /usr/bin/python3 plus récent)")
        proc = subprocess.run([py, str(SCRIPT), "providers", "--json"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(subprocess.run([py, "-m", "py_compile", str(SCRIPT)], capture_output=True).returncode, 0)

    def test_install_constants_match_catalog(self):
        text = (REPO / "install.sh").read_text(encoding="utf-8")

        def const(name):
            return re.search(r'^%s="([^"]*)"' % name, text, re.M).group(1)

        proc = subprocess.run([sys.executable, str(SCRIPT), "providers", "--json"], capture_output=True, text=True, timeout=30)
        providers = {p["id"]: p for p in json.loads(proc.stdout)["providers"]}
        self.assertEqual(const("LLM_OPENROUTER_MODEL"), providers["openrouter"]["chat_model"])
        self.assertEqual(const("LLM_OPENROUTER_MODEL"), providers["openrouter"]["sync_model"])
        self.assertEqual(const("LLM_ANTHROPIC_CHAT_MODEL"), providers["anthropic"]["chat_model"])
        self.assertEqual(const("LLM_ANTHROPIC_SYNC_MODEL"), providers["anthropic"]["sync_model"])
        self.assertIn('key_var="OPENROUTER_API_KEY"', text)
        self.assertIn('key_var="ANTHROPIC_API_KEY"', text)
        self.assertIn('key_var="OPENAI_API_KEY"', text)
        self.assertEqual({p["key_env"] for p in providers.values()},
                         {"OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"})


class InstallConnectTests(InstallAsserts):
    BASE = ("--no-auth", "--ide", "claude")

    def test_connect_requires_openrouter(self):
        with Sandbox() as sb:
            proc = sb.install(*self.BASE, "--connect")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("--connect", proc.stdout + proc.stderr)
            proc = sb.install(*self.BASE, "--llm", "anthropic", "--connect")
            self.assertNotEqual(proc.returncode, 0)

    def test_dry_run_prints_command_and_opens_nothing(self):
        with Sandbox() as sb:
            before = sb.tree()
            proc = sb.install(*self.BASE, "--llm", "openrouter", "--connect", "--dry-run")
            self.assertSucceeded(proc)
            self.assertIn("arc_llm.py connect openrouter", proc.stdout)
            self.assertEqual(sb.tree(), before)
            self.assertNotIn("open", [name for name, _ in sb.stub_calls()])

    def test_without_tty_gives_the_command_and_does_not_connect(self):
        with Sandbox() as sb:
            proc = sb.install(*self.BASE, "--llm", "openrouter", "--connect")
            self.assertSucceeded(proc)
            self.assertIn("terminal interactif", proc.stdout + proc.stderr)
            env_file = sb.home / ".config/ai-running-coach/llm.env"
            self.assertNotIn("OPENROUTER_API_KEY=sk", env_file.read_text())

    def test_connect_not_remembered_for_updates(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*self.BASE, "--llm", "openrouter", "--connect"))
            remembered = sb.home / ".config/ai-running-coach/install-args"
            self.assertTrue(remembered.exists())
            self.assertNotIn("--connect", remembered.read_text())
            self.assertIn("openrouter", remembered.read_text())

    def test_no_connect_unchanged(self):
        with Sandbox() as sb:
            proc = sb.install(*self.BASE, "--llm", "openrouter", "--dry-run")
            self.assertSucceeded(proc)
            self.assertNotIn("arc_llm.py", proc.stdout)
            self.assertNotIn("terminal interactif", proc.stdout + proc.stderr)
