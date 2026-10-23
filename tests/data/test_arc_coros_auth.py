"""Palier D — connexion COROS propre au projet et relais MCP stdio.

Familles de tests :
- jetons : écriture en 600 dans un dossier 700, rafraîchissement sous la marge
  seulement, rotation du jeton de rafraîchissement gardée, un 401 ne rafraîchit
  qu'une fois même si un autre processus l'a déjà fait, jamais connecté = sortie 2 ;
- relais : liste blanche et lecture seule sur `tools/list` ET `tools/call`, 401 →
  rafraîchissement + un seul nouvel essai, session expirée rouverte, réponse SSE,
  notification sans réponse ;
- CLI : `login` refusé en headless, `status` sans réseau, aucun jeton affiché.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_coros_auth as A  # noqa: E402
import arc_coros_mcp as M  # noqa: E402

CLIENT = {"client_id": "cid", "base_url": "https://mcp.example", "redirect_uri": "http://127.0.0.1:8765/callback",
          "token_endpoint": "https://mcp.example/oauth2/token",
          "authorization_endpoint": "https://mcp.example/oauth2/authorize"}
SECRET = "SECRET-ACCESS-TOKEN"


class _Dir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "coros"
        patcher = mock.patch.dict(os.environ, {"ARC_COROS_DIR": str(self.dir)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def connect(self, expires_in_s: float, access=SECRET, refresh="R1"):
        A._write_private(A._client_file(), CLIENT)
        A._write_private(A._tokens_file(), {"access_token": access, "refresh_token": refresh,
                                            "expires_at": int(time.time() + expires_in_s)})


def _refresh_ok(new_access="A2", new_refresh="R2"):
    calls = []

    def post(url, form=None, body=None, headers=None, timeout=None):
        calls.append(form)
        return 200, {}, json.dumps({"access_token": new_access, "refresh_token": new_refresh, "expires_in": 2592000})
    return post, calls


class TestTokens(_Dir):
    def test_private_permissions(self):
        self.connect(30 * 86400)
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
        for name in ("client.json", "tokens.json"):
            self.assertEqual(stat.S_IMODE((self.dir / name).stat().st_mode), 0o600)
        self.assertEqual(A.status_info()["loose_permissions"], [])

    def test_fresh_token_is_not_refreshed(self):
        self.connect(20 * 86400)
        post, calls = _refresh_ok()
        with mock.patch.object(A, "http_post", post):
            self.assertEqual(A.access_token(), SECRET)
        self.assertEqual(calls, [])

    def test_token_near_expiry_is_refreshed_and_rotation_kept(self):
        self.connect(2 * 86400)
        post, calls = _refresh_ok()
        with mock.patch.object(A, "http_post", post):
            self.assertEqual(A.access_token(), "A2")
        self.assertEqual(calls[0]["grant_type"], "refresh_token")
        self.assertEqual(calls[0]["refresh_token"], "R1")
        stored = json.loads((self.dir / "tokens.json").read_text())
        self.assertEqual(stored["refresh_token"], "R2")
        self.assertGreater(stored["expires_at"], time.time() + 29 * 86400)

    def test_rejected_token_refreshes_once_only(self):
        """Un 401 sur un jeton déjà remplacé par un autre processus ne rafraîchit pas à nouveau :
        ce serait réutiliser un jeton de rafraîchissement consommé."""
        self.connect(20 * 86400, access="NEW")
        post, calls = _refresh_ok()
        with mock.patch.object(A, "http_post", post):
            self.assertEqual(A.access_token(rejected="OLD"), "NEW")
            self.assertEqual(calls, [])
            self.assertEqual(A.access_token(rejected="NEW"), "A2")
        self.assertEqual(len(calls), 1)

    def test_refresh_refused_says_login(self):
        self.connect(0)
        with mock.patch.object(A, "http_post", lambda *a, **k: (400, {}, '{"error":"invalid_grant"}')):
            with self.assertRaises(A.CorosAuthError) as ctx:
                A.access_token()
        self.assertIn("arc_coros_auth.py login", str(ctx.exception))
        self.assertEqual(ctx.exception.code, 3)

    def test_not_connected_is_exit_2(self):
        with self.assertRaises(A.CorosAuthError) as ctx:
            A.access_token()
        self.assertEqual(ctx.exception.code, 2)


class TestParse(unittest.TestCase):
    def test_json_and_sse(self):
        self.assertEqual(A.parse_mcp_body('{"id":1}'), [{"id": 1}])
        sse = 'event: message\ndata: {"id":1,"result":{}}\n\nevent: message\ndata: {"id":2}\n\n'
        self.assertEqual([m["id"] for m in A.parse_mcp_body(sse)], [1, 2])
        self.assertEqual(A.parse_mcp_body(""), [])


class FakeServer:
    """Serveur MCP COROS simulé : enregistre les requêtes, répond selon un script."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def __call__(self, url, body=None, headers=None, form=None, timeout=None):
        self.sent.append((body, dict(headers or {})))
        return self.responses.pop(0)


TOOLS = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [
    {"name": "queryTrainingSchedule"}, {"name": "createScheduledWorkout"}, {"name": "querySleepHrv"}]}}


def _relay(server, env=None, tokens=None):
    tokens = tokens if tokens is not None else iter(["T1", "T2", "T3", "T4"])
    seen = []

    def token(rejected=None):
        seen.append(rejected)
        return next(tokens)
    relay = M.Relay(post=server, token=token, url="https://mcp.example/mcp", env=env or {})
    return relay, seen


class TestRelay(unittest.TestCase):
    def test_tools_filtered_by_read_only_and_whitelist(self):
        server = FakeServer([(200, {}, json.dumps(TOOLS))] * 2)
        relay, _ = _relay(server, env={"COROS_READ_ONLY": "1"})
        names = [t["name"] for t in relay.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[0]["result"]["tools"]]
        self.assertEqual(names, ["queryTrainingSchedule", "querySleepHrv"])
        relay, _ = _relay(server, env={"COROS_ENABLED_TOOLS": "querySleepHrv, createScheduledWorkout"})
        names = [t["name"] for t in relay.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[0]["result"]["tools"]]
        self.assertEqual(names, ["createScheduledWorkout", "querySleepHrv"])

    def test_headless_sync_is_read_only(self):
        """daily-sync.sh exporte ARC_HEADLESS=1 : le relais refuse les écritures, quel que soit l'exécuteur."""
        server = FakeServer([(200, {}, json.dumps(TOOLS))])
        relay, _ = _relay(server, env={"ARC_HEADLESS": "1", "COROS_ENABLED_TOOLS": "createScheduledWorkout,querySleepHrv"})
        names = [t["name"] for t in relay.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[0]["result"]["tools"]]
        self.assertEqual(names, ["querySleepHrv"])

    def test_write_tools_match_the_sync_deny_list(self):
        import subprocess
        out = subprocess.run(["bash", "-c", f'. "{REPO}/scripts/lib/sync_tools.sh"; sync_write_tools coros'],
                             capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(set(out), set(M.WRITE_TOOLS))

    def test_forbidden_call_never_reaches_coros(self):
        server = FakeServer([])
        relay, _ = _relay(server, env={"COROS_READ_ONLY": "1"})
        out = relay.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                            "params": {"name": "updateScheduledWorkout", "arguments": {}}})
        self.assertIn("non autorisé", out[0]["error"]["message"])
        self.assertEqual(server.sent, [])

    def test_write_tools_list_matches_doc(self):
        doc = (REPO / "docs" / "coros.md").read_text(encoding="utf-8")
        for name in M.WRITE_TOOLS:
            self.assertIn(f"`{name}`", doc)

    def test_401_refreshes_and_retries_once(self):
        server = FakeServer([(401, {}, ""), (200, {}, '{"jsonrpc":"2.0","id":3,"result":{"content":[]}}')])
        relay, seen = _relay(server)
        out = relay.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "queryTrainingSchedule", "arguments": {}}})
        self.assertEqual(out[0]["id"], 3)
        self.assertEqual(seen, [None, "T1"])
        self.assertEqual([h["Authorization"] for _, h in server.sent], ["Bearer T1", "Bearer T2"])

    def test_session_and_protocol_headers_follow_initialize(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        server = FakeServer([(200, {"mcp-session-id": "S1"}, '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}'),
                             (202, {}, ""), (200, {}, json.dumps(TOOLS))])
        relay, _ = _relay(server)
        relay.handle(init)
        self.assertEqual(relay.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}), [])
        relay.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        headers = server.sent[-1][1]
        self.assertEqual(headers["Mcp-Session-Id"], "S1")
        self.assertEqual(headers["MCP-Protocol-Version"], "2025-06-18")

    def test_expired_session_is_reopened(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        server = FakeServer([
            (200, {"mcp-session-id": "S1"}, '{"jsonrpc":"2.0","id":1,"result":{}}'),
            (404, {}, ""),                                                   # session S1 expirée
            (200, {"mcp-session-id": "S2"}, '{"jsonrpc":"2.0","id":1,"result":{}}'),  # initialize rejoué
            (202, {}, ""),                                                   # notifications/initialized
            (200, {}, json.dumps(TOOLS))])
        relay, _ = _relay(server, tokens=iter(["T"] * 10))
        relay.handle(init)
        out = relay.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(out[0]["result"]["tools"]), 3)
        self.assertEqual(relay.session, "S2")
        self.assertEqual(server.sent[-1][1]["Mcp-Session-Id"], "S2")

    def test_not_connected_answers_with_login_hint(self):
        def token(rejected=None):
            raise A.CorosAuthError("COROS non connecté — lancez : python3 scripts/arc_coros_auth.py login", 2)
        relay = M.Relay(post=FakeServer([]), token=token, url="https://mcp.example/mcp", env={})
        out = relay.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn("arc_coros_auth.py login", out[0]["error"]["message"])


class TestClient(unittest.TestCase):
    """`arc_coros_mcp.Client` : appels d'outils sans IA (download_fit.py, garmin_watch.py)."""

    INIT = (200, {"mcp-session-id": "S1"}, '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}')

    def _answer(self, msg_id, text):
        return (200, {}, json.dumps({"jsonrpc": "2.0", "id": msg_id,
                                     "result": {"content": [{"type": "text", "text": text}]}}))

    def test_text_encoded_as_json_string_is_decoded(self):
        """Constaté le 23/10/2026 : COROS rend « "Sport Records…\\n…" » (chaîne JSON)."""
        server = FakeServer([self.INIT, (202, {}, ""), self._answer(2, json.dumps("Sport Records\n1. Run"))])
        relay, _ = _relay(server, tokens=iter(["T"] * 5))
        self.assertEqual(M.Client(relay).call("querySportRecords"), "Sport Records\n1. Run")

    def test_plain_text_is_kept_and_session_opened_once(self):
        server = FakeServer([self.INIT, (202, {}, ""), self._answer(2, "a"), self._answer(3, '"quoted" text')])
        relay, _ = _relay(server, tokens=iter(["T"] * 5))
        client = M.Client(relay)
        self.assertEqual(client.call("queryDevices"), "a")
        self.assertEqual(client.call("queryDevices"), '"quoted" text')
        self.assertEqual([b.get("method") for b, _ in server.sent],
                         ["initialize", "notifications/initialized", "tools/call", "tools/call"])

    def test_login_required_is_flagged(self):
        def token(rejected=None):
            raise A.CorosAuthError("COROS non connecté — lancez : python3 scripts/arc_coros_auth.py login", 2)
        relay = M.Relay(post=FakeServer([]), token=token, url="https://mcp.example/mcp", env={})
        with self.assertRaises(M.CallError) as ctx:
            M.Client(relay).call("querySportRecords")
        self.assertTrue(ctx.exception.login_required)

    def test_network_error_is_not_a_login_problem(self):
        def token(rejected=None):
            raise A.CorosAuthError("COROS injoignable (timed out)", 3)
        relay = M.Relay(post=FakeServer([]), token=token, url="https://mcp.example/mcp", env={})
        with self.assertRaises(M.CallError) as ctx:
            M.Client(relay).call("querySportRecords")
        self.assertFalse(ctx.exception.login_required)

    def test_read_only_client_cannot_write(self):
        server = FakeServer([self.INIT, (202, {}, "")])
        relay, _ = _relay(server, env={"COROS_READ_ONLY": "1"}, tokens=iter(["T"] * 5))
        with self.assertRaises(M.CallError):
            M.Client(relay).call("createScheduledWorkout", {"date": "20261024"})
        self.assertNotIn("tools/call", [b.get("method") for b, _ in server.sent])


class TestCli(_Dir):
    def test_login_refused_headless(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"ARC_HEADLESS": "1"}), redirect_stderr(err):
            self.assertEqual(A.main(["login"]), 2)
        self.assertIn("jamais en headless", err.getvalue())

    def test_status_never_prints_token(self):
        self.connect(10 * 86400)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(A.main(["status", "--json"]), 0)
        info = json.loads(out.getvalue())
        self.assertTrue(info["connected"])
        self.assertNotIn(SECRET, out.getvalue())
        self.assertNotIn("R1", out.getvalue())

    def test_status_not_connected_exit_2(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(A.main(["status"]), 2)


if __name__ == "__main__":
    unittest.main()
