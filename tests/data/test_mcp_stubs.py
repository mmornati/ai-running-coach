"""Palier D — stubs MCP `garmin` et `intervals` (#26).

Deux niveaux :

- unitaire, sans sous-processus, contre `mcp_stub_common` directement
  (chargement de la config, résolution des overrides, erreurs injectées) ;
- protocole, en parlant JSON-RPC 2.0 à un vrai sous-processus du stub, pour
  verrouiller le cadrage (`initialize`, `tools/list`, `tools/call`,
  notifications) et la non-régression des cas sans section `[stub]`.

Le test « timeout » borne volontairement son délai (`delay` très court) : on
vérifie le mécanisme, pas la durée réelle qu'un cas d'éval choisirait.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO / "tests" / "evals"
sys.path.insert(0, str(EVALS_DIR))
import mcp_stub_common as common  # noqa: E402


class TestLoadStubConfig(unittest.TestCase):
    ENV_VAR = "ARC_STUB_CONFIG_TEST"

    def tearDown(self):
        os.environ.pop(self.ENV_VAR, None)

    def test_no_env_var_is_empty_config(self):
        """Non-régression : un cas sans section `[stub]` ne passe pas la variable —
        le stub doit alors se comporter exactement comme avant #26."""
        os.environ.pop(self.ENV_VAR, None)
        self.assertEqual(common.load_stub_config(self.ENV_VAR), {})

    def test_missing_file_is_empty_config(self):
        os.environ[self.ENV_VAR] = "/nonexistent/path/stub.json"
        self.assertEqual(common.load_stub_config(self.ENV_VAR), {})

    def test_valid_file_is_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stub.json"
            path.write_text(json.dumps({"get_hrv_data": {"error": "401"}}), encoding="utf-8")
            os.environ[self.ENV_VAR] = str(path)
            self.assertEqual(common.load_stub_config(self.ENV_VAR), {"get_hrv_data": {"error": "401"}})


class TestResolveContent(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = EVALS_DIR / "fixtures"

    def test_no_override_returns_default_json(self):
        default = {"date": "2026-01-01", "restingHeartRate": 49}
        text = common.resolve_content(
            name="get_rhr_day", default=default, overrides={}, fixtures_dir=self.fixtures_dir,
        )
        self.assertEqual(json.loads(text), default)

    def test_file_override_reads_fixture_verbatim(self):
        text = common.resolve_content(
            name="get_hrv_data", default={"status": "BALANCED"},
            overrides={"get_hrv_data": {"file": "hrv-collapsed.json"}},
            fixtures_dir=self.fixtures_dir,
        )
        payload = json.loads(text)
        self.assertEqual(payload["status"], "LOW")
        self.assertEqual(payload["lastNightAvg"], 31)

    def test_file_override_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            common.resolve_content(
                name="get_hrv_data", default={}, overrides={"get_hrv_data": {"file": "does-not-exist.json"}},
                fixtures_dir=self.fixtures_dir,
            )

    def test_error_401_mentions_the_renewal_command(self):
        """Le message doit orienter vers `uv run garmin-mcp-auth` (voir
        `docs/troubleshooting.md`) — c'est ce que le cas `health-token-expired`
        vérifie côté agent."""
        text = common.resolve_content(
            name="get_hrv_data", default={}, overrides={"get_hrv_data": {"error": "401"}},
            fixtures_dir=self.fixtures_dir,
        )
        self.assertIn("garmin-mcp-auth", text)
        self.assertIn("401", text)
        # Pas de JSON : c'est un texte d'erreur, comme le vrai garmin_mcp (voir
        # `mcp_stub_common.auth_expired_text`) — un `json.loads` doit échouer.
        with self.assertRaises(json.JSONDecodeError):
            json.loads(text)

    def test_error_empty_matches_default_shape(self):
        list_text = common.resolve_content(
            name="get_activities", default=[{"activityId": 1}], overrides={"get_activities": {"error": "empty"}},
            fixtures_dir=self.fixtures_dir,
        )
        self.assertEqual(json.loads(list_text), [])

        dict_text = common.resolve_content(
            name="get_hrv_data", default={"status": "BALANCED"}, overrides={"get_hrv_data": {"error": "empty"}},
            fixtures_dir=self.fixtures_dir,
        )
        self.assertEqual(json.loads(dict_text), {})

    def test_error_timeout_drops_the_request(self):
        with self.assertRaises(common.DropRequest):
            common.resolve_content(
                name="get_hrv_data", default={},
                overrides={"get_hrv_data": {"error": "timeout", "delay": 0.01}},
                fixtures_dir=self.fixtures_dir,
            )

    def test_error_timeout_is_capped(self):
        """Un `delay` déraisonnable ne doit jamais dépasser la borne dure —
        c'est elle qui garantit qu'un cas mal réglé ne bloque pas la suite."""
        original_cap = common.MAX_TIMEOUT_DELAY_S
        common.MAX_TIMEOUT_DELAY_S = 0.05
        try:
            start = __import__("time").monotonic()
            with self.assertRaises(common.DropRequest):
                common.resolve_content(
                    name="get_hrv_data", default={},
                    overrides={"get_hrv_data": {"error": "timeout", "delay": 30}},
                    fixtures_dir=self.fixtures_dir,
                )
            elapsed = __import__("time").monotonic() - start
            self.assertLess(elapsed, 1.0, "le délai aurait dû être plafonné, pas honoré tel quel")
        finally:
            common.MAX_TIMEOUT_DELAY_S = original_cap

    def test_unknown_error_kind_raises(self):
        with self.assertRaises(ValueError):
            common.resolve_content(
                name="get_hrv_data", default={}, overrides={"get_hrv_data": {"error": "teapot"}},
                fixtures_dir=self.fixtures_dir,
            )


class StubProcessTestCase(unittest.TestCase):
    """Base : parle JSON-RPC à un vrai sous-processus du stub."""

    SCRIPT = None  # défini par les sous-classes

    def start(self, *, tool_log=None, stub_config=None):
        env = dict(os.environ)
        env.pop("ARC_TOOL_LOG", None)
        env.pop("ARC_STUB_CONFIG", None)
        if tool_log is not None:
            env["ARC_TOOL_LOG"] = str(tool_log)
        if stub_config is not None:
            config_path = Path(tempfile.mkstemp(suffix=".json")[1])
            config_path.write_text(json.dumps(stub_config), encoding="utf-8")
            self.addCleanup(config_path.unlink, missing_ok=True)
            env["ARC_STUB_CONFIG"] = str(config_path)
        proc = subprocess.Popen(
            [sys.executable, str(self.SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self.addCleanup(self._stop, proc)
        return proc

    @staticmethod
    def _stop(proc):
        proc.stdin.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    @staticmethod
    def send(proc, obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    @staticmethod
    def recv(proc, timeout=5.0):
        """Une ligne JSON, ou None si rien n'arrive dans le délai — c'est ce
        qui permet de tester un « timeout » injecté sans bloquer la suite."""
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if not ready:
            return None
        line = proc.stdout.readline()
        return json.loads(line) if line else None

    def initialize(self, proc):
        self.send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        return self.recv(proc)

    def call(self, proc, name, arguments=None, request_id=2):
        self.send(proc, {
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })


class TestGarminStubFraming(StubProcessTestCase):
    SCRIPT = EVALS_DIR / "stub_garmin_mcp.py"

    def test_initialize(self):
        proc = self.start()
        response = self.initialize(proc)
        self.assertEqual(response["result"]["protocolVersion"], common.PROTOCOL_VERSION)
        self.assertEqual(response["result"]["serverInfo"]["name"], "garmin-stub")

    def test_tools_list_includes_known_tool_names(self):
        """Les cas d'éval scriptent des outils par leur nom : ils doivent
        matcher `GARMIN_TOOL_WHITELIST` d'`install.sh`, pas une invention du stub."""
        proc = self.start()
        self.initialize(proc)
        self.send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        response = self.recv(proc)
        names = {tool["name"] for tool in response["result"]["tools"]}
        for expected in ("get_hrv_data", "get_rhr_day", "get_training_readiness", "get_activities"):
            self.assertIn(expected, names)

    def test_tools_call_default_is_backward_compatible(self):
        """Sans `ARC_STUB_CONFIG` (donc sans section `[stub]` dans le cas), un
        appel rend exactement la donnée canned d'avant #26."""
        proc = self.start()
        self.initialize(proc)
        self.call(proc, "get_rhr_day")
        response = self.recv(proc)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("restingHeartRate", payload)
        self.assertEqual(payload["restingHeartRate"], 49)

    def test_tools_call_logs_the_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "calls.log"
            proc = self.start(tool_log=log_path)
            self.initialize(proc)
            self.call(proc, "get_hrv_data", {"date": "2026-01-01"})
            self.recv(proc)
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["tool"], "get_hrv_data")
            self.assertEqual(entries[0]["server"], "garmin")
            self.assertEqual(entries[0]["arguments"], {"date": "2026-01-01"})

    def test_injected_401_end_to_end(self):
        proc = self.start(stub_config={"get_hrv_data": {"error": "401"}})
        self.initialize(proc)
        self.call(proc, "get_hrv_data")
        response = self.recv(proc)
        text = response["result"]["content"][0]["text"]
        self.assertIn("garmin-mcp-auth", text)

    def test_injected_timeout_end_to_end_gets_no_response(self):
        proc = self.start(stub_config={"get_hrv_data": {"error": "timeout", "delay": 0.05}})
        self.initialize(proc)
        self.call(proc, "get_hrv_data")
        # On laisse passer largement le délai injecté (0.05s) : toujours rien.
        self.assertIsNone(self.recv(proc, timeout=0.5))

    def test_notification_gets_no_response(self):
        proc = self.start()
        self.send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self.assertIsNone(self.recv(proc, timeout=0.5))

    def test_unknown_method_is_a_json_rpc_error(self):
        proc = self.start()
        self.send(proc, {"jsonrpc": "2.0", "id": 9, "method": "does/not-exist", "params": {}})
        response = self.recv(proc)
        self.assertEqual(response["error"]["code"], -32601)


class TestIntervalsStubFraming(StubProcessTestCase):
    SCRIPT = EVALS_DIR / "stub_intervals_mcp.py"

    def test_initialize(self):
        proc = self.start()
        response = self.initialize(proc)
        self.assertEqual(response["result"]["serverInfo"]["name"], "intervals-stub")

    def test_tools_call_default_wellness(self):
        proc = self.start()
        self.initialize(proc)
        self.call(proc, "get-wellness-for-date")
        response = self.recv(proc)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("restingHR", payload)

    def test_shares_the_call_log_format_with_garmin(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "calls.log"
            proc = self.start(tool_log=log_path)
            self.initialize(proc)
            self.call(proc, "get-recent-activities")
            self.recv(proc)
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(entries[0]["tool"], "get-recent-activities")
            self.assertEqual(entries[0]["server"], "intervals")

    def test_injected_error_matches_garmin_semantics(self):
        proc = self.start(stub_config={"get-wellness-for-date": {"error": "empty"}})
        self.initialize(proc)
        self.call(proc, "get-wellness-for-date")
        response = self.recv(proc)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload, {})


if __name__ == "__main__":
    unittest.main()
