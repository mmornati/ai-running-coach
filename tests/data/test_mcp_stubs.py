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
import re
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

    def test_error_401_matches_real_garmin_mcp_wording_without_a_remedy(self):
        """Texte fidèle à ce que `garmin_mcp` rend RÉELLEMENT (vérifié dans le
        paquet vendored, voir `mcp_stub_common.auth_expired_text`) : mention du
        401 et de « Authentication failed », mais AUCUN remède — c'est à
        l'agent de le proposer, pas au stub de le souffler (cas
        `health-token-expired`, `must_match` générique sur la
        reconnaissance de la panne)."""
        text = common.resolve_content(
            name="get_hrv_data", default={}, overrides={"get_hrv_data": {"error": "401"}},
            fixtures_dir=self.fixtures_dir,
        )
        self.assertIn("401", text)
        self.assertIn("Authentication failed", text)
        self.assertNotIn("garmin-mcp-auth", text)
        # Pas de JSON : c'est un texte d'erreur, comme le vrai garmin_mcp (voir
        # `mcp_stub_common.auth_expired_text`) — un `json.loads` doit échouer.
        with self.assertRaises(json.JSONDecodeError):
            json.loads(text)

    def test_error_kind_accepts_a_toml_integer(self):
        """`error = 401` (entier TOML, faute de frappe plausible) doit être
        traité comme `error = "401"`, pas planter le stub."""
        text = common.resolve_content(
            name="get_hrv_data", default={}, overrides={"get_hrv_data": {"error": 401}},
            fixtures_dir=self.fixtures_dir,
        )
        self.assertIn("Authentication failed", text)

    def test_file_override_rejects_path_traversal(self):
        for malicious in ("../../../../AGENTS.md", "/etc/hosts", "../stub-responses/../../AGENTS.md"):
            with self.subTest(file=malicious):
                with self.assertRaises(ValueError):
                    common.resolve_content(
                        name="get_hrv_data", default={}, overrides={"get_hrv_data": {"file": malicious}},
                        fixtures_dir=self.fixtures_dir,
                    )

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

    def test_tools_list_is_a_subset_of_the_real_whitelist(self):
        """Les cas d'éval scriptent des outils par leur nom : chaque nom que le
        stub connaît doit exister dans `GARMIN_TOOL_WHITELIST`
        (`install.sh`) — direction volontaire : le stub n'a pas besoin
        d'implémenter TOUT ce que le vrai serveur expose, mais ne doit
        inventer aucun nom qui n'existerait pas côté réel."""
        install_sh = (REPO / "install.sh").read_text(encoding="utf-8")
        match = re.search(r'GARMIN_TOOL_WHITELIST="([^"]+)"', install_sh)
        self.assertIsNotNone(match, "GARMIN_TOOL_WHITELIST introuvable dans install.sh")
        whitelist = set(match.group(1).split(","))
        # Extension opt-in (#167) : le stub connaît aussi les outils de nutrition, jamais dans la
        # liste par défaut mais ajoutés par `resolve_nutrition_sync` — noms réels, pas inventés.
        extra = re.search(r'GARMIN_NUTRITION_TOOLS="([^"]+)"', install_sh)
        self.assertIsNotNone(extra, "GARMIN_NUTRITION_TOOLS introuvable dans install.sh")
        whitelist |= set(extra.group(1).split(","))

        proc = self.start()
        self.initialize(proc)
        self.send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        response = self.recv(proc)
        names = {tool["name"] for tool in response["result"]["tools"]}

        unknown = names - whitelist
        self.assertFalse(unknown, f"outil(s) stub absent(s) de GARMIN_TOOL_WHITELIST : {sorted(unknown)}")
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
        self.assertIn("Authentication failed", text)
        self.assertNotIn("garmin-mcp-auth", text)

    def test_injected_timeout_end_to_end_gets_no_response_but_the_stub_survives(self):
        proc = self.start(stub_config={"get_hrv_data": {"error": "timeout", "delay": 0.05}})
        self.initialize(proc)
        self.call(proc, "get_hrv_data")
        # On laisse passer largement le délai injecté (0.05s) : toujours rien...
        self.assertIsNone(self.recv(proc, timeout=0.5))
        # ...mais le process n'est pas mort pour autant : un appel suivant
        # obtient toujours une réponse normale (item #10 de la revue de #26).
        self.send(proc, {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}})
        self.assertIsNotNone(self.recv(proc, timeout=2.0))

    def test_notification_gets_no_response(self):
        proc = self.start()
        self.send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self.assertIsNone(self.recv(proc, timeout=0.5))

    def test_unknown_method_is_a_json_rpc_error(self):
        proc = self.start()
        self.send(proc, {"jsonrpc": "2.0", "id": 9, "method": "does/not-exist", "params": {}})
        response = self.recv(proc)
        self.assertEqual(response["error"]["code"], -32601)

    def test_non_object_json_line_does_not_kill_the_stub(self):
        """Une ligne JSON valide mais qui n'est pas un objet (`[1, 2]`, `"x"`,
        `42`) n'a pas de `.get()` — elle ne doit pas planter la boucle."""
        proc = self.start()
        proc.stdin.write("[1, 2, 3]\n")
        proc.stdin.write('"just a string"\n')
        proc.stdin.write("42\n")
        proc.stdin.flush()
        # Aucune des trois n'a d'id : rien ne doit répondre, mais le process
        # doit rester vivant et répondre normalement ensuite.
        self.assertIsNone(self.recv(proc, timeout=0.5))
        response = self.initialize(proc)
        self.assertEqual(response["result"]["protocolVersion"], common.PROTOCOL_VERSION)

    def test_a_malformed_call_does_not_kill_the_stub(self):
        """Un `[stub.garmin.<outil>]` mal réglé (ici : `error` inconnu) ne doit
        faire échouer QUE cet appel — le process continue de répondre aux
        suivants (item #3 de la revue de #26)."""
        proc = self.start(stub_config={"get_hrv_data": {"error": "teapot"}})
        self.initialize(proc)
        self.call(proc, "get_hrv_data")
        response = self.recv(proc)
        self.assertEqual(response["error"]["code"], -32603)

        # Le stub tourne toujours : un appel normal ensuite fonctionne.
        self.call(proc, "get_rhr_day", request_id=3)
        response = self.recv(proc)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["restingHeartRate"], 49)

    def test_a_missing_stub_response_file_does_not_kill_the_stub(self):
        proc = self.start(stub_config={"get_hrv_data": {"file": "does-not-exist.json"}})
        self.initialize(proc)
        self.call(proc, "get_hrv_data")
        response = self.recv(proc)
        self.assertEqual(response["error"]["code"], -32603)
        self.send(proc, {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}})
        self.assertIsNotNone(self.recv(proc, timeout=2.0))


class TestIntervalsStubFraming(StubProcessTestCase):
    SCRIPT = EVALS_DIR / "stub_intervals_mcp.py"

    def test_initialize(self):
        proc = self.start()
        response = self.initialize(proc)
        self.assertEqual(response["result"]["serverInfo"]["name"], "intervals-stub")

    def test_tools_call_default_wellness(self):
        # Nom et forme vérifiés (#68, revue PR #116) contre hhopke/intervals-icu-mcp (#165, outils préfixés `icu_`) :
        # snake_case, enveloppe `{"data": {...}, "metadata": {...}}`
        # (`ResponseBuilder.build_response`), champ imbriqué `heart.resting_hr`
        # sous `data` (PAS `restingHR` plat, PAS de kebab-case, PAS un objet
        # racine sans enveloppe — hypothèses antérieures non vérifiées).
        proc = self.start()
        self.initialize(proc)
        self.call(proc, "icu_get_wellness_for_date")
        response = self.recv(proc)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("metadata", payload)
        self.assertIn("resting_hr", payload["data"]["heart"])

    def _payload(self, tool, arguments=None):
        proc = self.start()
        self.initialize(proc)
        self.call(proc, tool, arguments or {})
        response = self.recv(proc)
        return json.loads(response["result"]["content"][0]["text"])

    def test_tool_names_carry_the_icu_prefix(self):
        """#165 : le fork hhopke préfixe TOUS ses outils `icu_` — le stub aussi, jamais l'ancien nom nu."""
        proc = self.start()
        self.initialize(proc)
        self.send(proc, {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}})
        names = [t["name"] for t in self.recv(proc)["result"]["tools"]]
        self.assertTrue(names)
        self.assertTrue(all(n.startswith("icu_") for n in names), names)

    def test_workout_write_echoes_the_parse_result_without_workout_doc(self):
        structured = self._payload("icu_create_event", {
            "start_date": "2026-10-05", "name": "Endurance", "category": "WORKOUT",
            "description": "Main Set\n- 60m 140-150bpm"})
        self.assertTrue(structured["data"]["workout_parsed"])
        self.assertGreaterEqual(structured["data"]["workout_steps"], 1)
        self.assertNotIn("workout_doc", structured["data"])
        plain = self._payload("icu_create_event", {
            "start_date": "2026-10-05", "name": "Endurance", "category": "WORKOUT",
            "description": "Cible FC : 140-150 bpm"})
        self.assertFalse(plain["data"]["workout_parsed"])
        self.assertIn("workout_parse_hint", plain["data"])
        self.assertNotIn("workout_steps", plain["data"])

    def test_write_echo_uses_the_response_keys_of_the_real_server(self):
        """`_event_to_dict` du fork : `type` (jamais `event_type`) et `start_date` dans la réponse."""
        data = self._payload("icu_create_event", {
            "start_date": "2026-10-05", "name": "Endurance", "category": "WORKOUT",
            "event_type": "Run", "duration_seconds": 3600})["data"]
        self.assertEqual(data["type"], "Run")
        self.assertNotIn("event_type", data)
        self.assertEqual(data["start_date"], "2026-10-05")
        self.assertEqual(data["duration_seconds"], 3600)

    def test_bulk_create_lists_each_created_event_with_its_parse_echo(self):
        events = json.dumps([
            {"start_date_local": "2026-10-05", "name": "Endurance", "category": "WORKOUT",
             "event_type": "Run", "description": "Main Set 4x\n- 8m 160-168bpm\n- 3m intensity=rest"},
            {"start_date_local": "2026-10-07", "name": "Repos", "category": "NOTE"},
        ])
        data = self._payload("icu_bulk_create_events", {"events": events})["data"]
        self.assertEqual([e["start_date"] for e in data["events"]], ["2026-10-05", "2026-10-07"])
        self.assertTrue(data["events"][0]["workout_parsed"])
        self.assertEqual(data["events"][0]["workout_steps"], 2)
        self.assertNotIn("workout_parsed", data["events"][1])

    def test_delete_event_returns_the_deleted_skipped_envelope(self):
        data = self._payload("icu_delete_event", {"event_id": 42})["data"]
        self.assertEqual(data["deleted"], [42])
        self.assertEqual(data["skipped"], [])

    def test_shares_the_call_log_format_with_garmin(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "calls.log"
            proc = self.start(tool_log=log_path)
            self.initialize(proc)
            self.call(proc, "icu_get_recent_activities")
            self.recv(proc)
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(entries[0]["tool"], "icu_get_recent_activities")
            self.assertEqual(entries[0]["server"], "intervals")

    def test_injected_error_matches_garmin_semantics(self):
        # `error = "empty"` vide tout le gabarit `default` — ici l'enveloppe
        # entière (`{"data": ..., "metadata": ...}`), pas seulement `data` :
        # écart de fidélité assumé et documenté en tête de stub_intervals_mcp.py.
        proc = self.start(stub_config={"icu_get_wellness_for_date": {"error": "empty"}})
        self.initialize(proc)
        self.call(proc, "icu_get_wellness_for_date")
        response = self.recv(proc)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload, {})


class TestRunnerStubWiring(unittest.TestCase):
    """`runner.build_workspace` : câblage du fichier de config et de la
    variable d'environnement (items #7/#8 de la revue de #26)."""

    def setUp(self):
        sys.path.insert(0, str(REPO))
        from tests.evals import runner  # noqa: PLC0415 - import tardif, après sys.path

        self.runner = runner

    def test_config_file_lives_outside_the_workspace(self):
        """L'agent testé n'a accès qu'au workspace (cwd de `run_case`) — le
        fichier qui scripte le scénario de panne ne doit pas être à sa portée."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = {
                "id": "wiring-test", "prompt": "x", "fixture": "empty",
                "stub": {"garmin": {"get_hrv_data": {"error": "401"}}},
            }
            workspace = self.runner.build_workspace(root, case)
            manifest = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
            config_path = Path(manifest["mcpServers"]["garmin"]["env"]["ARC_STUB_CONFIG"])
            self.assertTrue(config_path.is_file())
            self.assertNotIn(workspace.resolve(), config_path.resolve().parents)

    def test_config_env_var_is_always_present_even_when_empty(self):
        """Un cas sans `[stub]` doit quand même déclarer `ARC_STUB_CONFIG`
        (vide) — pour qu'un export resté dans l'environnement de l'appelant
        ne fuite jamais dans le stub."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = {"id": "wiring-test-2", "prompt": "x", "fixture": "empty"}
            workspace = self.runner.build_workspace(root, case)
            manifest = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mcpServers"]["garmin"]["env"]["ARC_STUB_CONFIG"], "")

    def test_timeout_sentinel_is_never_treated_as_unauthenticated(self):
        """Un `subprocess.TimeoutExpired` (cas qui scripte `error = "timeout"`)
        rend `returncode == -1` avec parfois un relais de 401 dans la sortie
        partielle (« ... Unauthorized ... ») — ça ne doit jamais déclencher le
        *skip* « runner pas authentifié » (item #3 de la revue de #26)."""
        result = {
            "returncode": -1,
            "output": "Impossible de récupérer la HRV : 401 Unauthorized (relais)",
            "stderr": "le runner n'a pas répondu sous 300s (TimeoutExpired)",
            "tool_calls": "", "workspace": Path("/dev/null"),
        }
        self.assertFalse(self.runner.looks_unauthenticated(result))


if __name__ == "__main__":
    unittest.main()
