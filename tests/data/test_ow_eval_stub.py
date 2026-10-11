"""Palier D — serveur HTTP factice Open Wearables des évals (#221, épopée #216).

Sur le modèle de `test_mcp_stubs.py` (cadrage d'un vrai sous-processus du stub, journal d'appels partagé,
erreurs injectées) mais pour un serveur HTTP : `tests/evals/stub_openwearables_http.py`, lancé par
`runner.build_workspace` quand un cas déclare `[stub.openwearables.*]`.

Le test le plus important lance le VRAI client (`scripts/arc_openwearables.py`) contre le faux serveur monté par
le runner pour le cas `health-ow-full-strava` : il verrouille que la configuration du workspace de test, le
fichier de clé (mode 600), les dates relatives et les noms stables du journal suffisent à une lecture complète.
Aucun modèle, aucun accès réseau (127.0.0.1).
"""

from __future__ import annotations

import json
import os
import select
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.evals import runner, stub_openwearables_http as stub  # noqa: E402

KEY = "sk-test-0000000000000000000000000000"
USER = "00000000-0000-4000-8000-0000000000a1"


class StubProcess:
    """Le faux serveur en sous-processus, avec un journal d'appels et une configuration par cas."""

    def __init__(self, tmp: Path, config: dict | None = None, provider: str = "oura"):
        self.log = tmp / "calls.log"
        env = dict(os.environ, ARC_TOOL_LOG=str(self.log), ARC_OW_STUB_PROVIDER=provider, ARC_OW_STUB_KEY=KEY,
                   ARC_STUB_CONFIG="")
        if config:
            path = tmp / "stub.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            env["ARC_STUB_CONFIG"] = str(path)
        self.proc = subprocess.Popen([sys.executable, str(runner.HTTP_STUB_SCRIPTS["openwearables"])],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready, _, _ = select.select([self.proc.stdout], [], [], 15)
        line = self.proc.stdout.readline().strip() if ready else ""
        if not line.startswith("PORT="):
            self.stop()
            raise AssertionError(f"le stub n'a pas annoncé son port : {line!r}")
        self.base = f"http://127.0.0.1:{int(line.split('=', 1)[1])}"

    def get(self, path: str, key: str | None = KEY, timeout: float = 5.0):
        request = urllib.request.Request(self.base + path, headers={"X-Open-Wearables-API-Key": key} if key else {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}")

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=5)
        if self.proc.stdout:
            self.proc.stdout.close()


class StubTestCase(unittest.TestCase):
    def start(self, config: dict | None = None, provider: str = "oura") -> StubProcess:
        tmp = tempfile.TemporaryDirectory(prefix="arc-ow-stub-")
        self.addCleanup(tmp.cleanup)
        server = StubProcess(Path(tmp.name), config, provider)
        self.addCleanup(server.stop)
        return server


class TestFraming(StubTestCase):
    def test_serves_every_endpoint_with_the_real_shapes(self):
        server = self.start()
        status, users = server.get("/api/v1/users?limit=100")
        self.assertEqual((status, users["total"], users["items"][0]["id"]), (200, 1, USER))
        status, connections = server.get(f"/api/v1/users/{USER}/connections")
        self.assertEqual((status, connections[0]["provider"], connections[0]["status"]), (200, "oura", "active"))
        status, sleep = server.get(f"/api/v1/users/{USER}/summaries/sleep")
        self.assertEqual(status, 200)
        self.assertEqual(sleep["data"][0]["avg_hrv_rmssd_ms"], 48.2)
        status, series = server.get(f"/api/v1/users/{USER}/timeseries?types=resting_heart_rate")
        self.assertEqual([s["type"] for s in series["data"]], ["resting_heart_rate"])
        status, none = server.get(f"/api/v1/users/{USER}/timeseries?types=heart_rate_variability_rmssd")
        self.assertEqual(none["data"], [])
        status, scores = server.get(f"/api/v1/users/{USER}/health-scores")
        self.assertEqual({(s["category"], s["provider"]) for s in scores["data"]},
                         {("readiness", "oura"), ("sleep", "oura"), ("readiness", "internal"), ("strain", "whoop")})
        self.assertEqual(server.get("/api/v1/nope")[0], 404)

    def test_dates_are_relative_to_the_run_never_frozen(self):
        server = self.start()
        today = datetime.now().astimezone().date().isoformat()
        sleep = server.get(f"/api/v1/users/{USER}/summaries/sleep")[1]["data"][0]
        self.assertEqual(sleep["date"], today)
        self.assertTrue(sleep["end_time"].startswith(today) or sleep["end_time"] < f"{today}T24")
        synced = server.get(f"/api/v1/users/{USER}/connections")[1][0]["last_synced_at"]
        age = datetime.now().astimezone() - datetime.fromisoformat(synced.replace("Z", "+00:00"))
        self.assertLess(age.total_seconds(), 3 * 3600)           # synchronisé récemment : jamais « périmé »

    def test_api_key_is_required(self):
        server = self.start()
        self.assertEqual(server.get("/api/v1/users", key=None)[0], 401)
        self.assertEqual(server.get("/api/v1/users", key="autre")[0], 401)

    def test_apple_provider_has_sdnn_only_and_no_scores(self):
        server = self.start(provider="apple")
        sleep = server.get(f"/api/v1/users/{USER}/summaries/sleep")[1]["data"][0]
        self.assertEqual(sleep["avg_hrv_sdnn_ms"], 52.0)
        self.assertIsNone(sleep["avg_hrv_rmssd_ms"])
        self.assertEqual(server.get(f"/api/v1/users/{USER}/connections")[1], [])
        self.assertEqual(server.get(f"/api/v1/users/{USER}/health-scores")[1]["data"], [])

    def test_unknown_provider_refuses_to_start(self):
        env = dict(os.environ, ARC_OW_STUB_PROVIDER="garmin")
        done = subprocess.run([sys.executable, str(runner.HTTP_STUB_SCRIPTS["openwearables"])], env=env,
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 2)


class TestCallLog(StubTestCase):
    def test_every_request_is_logged_with_a_stable_name_in_the_shared_format(self):
        server = self.start()
        server.get("/api/v1/users?limit=100")
        server.get(f"/api/v1/users/{USER}/connections")
        server.get(f"/api/v1/users/{USER}/summaries/sleep?start_date=2026-10-01&end_date=2026-10-03")
        server.get(f"/api/v1/users/{USER}/timeseries?types=resting_heart_rate&provider=oura")
        server.get(f"/api/v1/users/{USER}/health-scores")
        server.get(f"/api/v1/users/{USER}/summaries/recovery")
        calls = server.calls()
        self.assertEqual([c["tool"] for c in calls], ["ow_users", "ow_connections", "ow_sleep_summary",
                                                       "ow_timeseries", "ow_health_scores", "ow_recovery_summary"])
        self.assertTrue(all(c["server"] == "openwearables" for c in calls))
        self.assertEqual(calls[2]["arguments"], {"start_date": "2026-10-01", "end_date": "2026-10-03"})
        self.assertEqual(sorted(name for name, _ in stub.TOOLS), sorted(c["tool"] for c in calls))

    def test_a_rejected_key_is_still_logged(self):
        server = self.start()
        server.get("/api/v1/users", key="autre")
        self.assertEqual([c["tool"] for c in server.calls()], ["ow_users"])


class TestInjectedErrors(StubTestCase):
    def test_401(self):
        server = self.start({"ow_users": {"error": "401"}})
        self.assertEqual(server.get("/api/v1/users")[0], 401)
        self.assertEqual(server.get(f"/api/v1/users/{USER}/connections")[0], 200)     # seul l'endpoint scripté

    def test_empty_is_a_well_formed_empty_answer(self):
        server = self.start({"ow_sleep_summary": {"error": "empty"}, "ow_connections": {"error": "empty"},
                             "ow_users": {"error": "empty"}})
        self.assertEqual(server.get("/api/v1/users")[1]["items"], [])
        self.assertEqual(server.get(f"/api/v1/users/{USER}/connections")[1], [])
        status, sleep = server.get(f"/api/v1/users/{USER}/summaries/sleep")
        self.assertEqual((status, sleep["data"]), (200, []))
        self.assertIn("pagination", sleep)

    def test_timeout_never_answers_then_the_server_keeps_serving(self):
        server = self.start({"ow_users": {"error": "timeout", "delay": 0.4}})
        with self.assertRaises(Exception):          # connexion coupée sans réponse (RemoteDisconnected)
            server.get("/api/v1/users", timeout=5)
        self.assertEqual(server.get(f"/api/v1/users/{USER}/connections")[0], 200)

    def test_file_override_substitutes_relative_placeholders_and_stays_in_stub_responses(self):
        base = runner.FIXTURES_DIR / "stub-responses"
        probe = base / "ow-probe-test.json"
        probe.write_text(json.dumps({"day": "{{TODAY}}", "old": "{{TODAY-2}}", "sync": "{{NOW-1h}}", "tz": "{{TZ}}"}),
                         encoding="utf-8")
        self.addCleanup(probe.unlink)
        server = self.start({"ow_users": {"file": "ow-probe-test.json"},
                             "ow_connections": {"file": "../../../../README.md"}})
        status, payload = server.get("/api/v1/users")
        today = datetime.now().astimezone().date()
        self.assertEqual((status, payload["day"]), (200, today.isoformat()))
        self.assertEqual(payload["old"], (today - timedelta(days=2)).isoformat())
        self.assertRegex(payload["sync"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertRegex(payload["tz"], r"^[+-]\d{2}:\d{2}$")
        self.assertEqual(server.get(f"/api/v1/users/{USER}/connections")[0], 500)     # évasion de dossier refusée

    def test_unknown_error_kind_answers_500_without_killing_the_server(self):
        server = self.start({"ow_users": {"error": "boom"}})
        self.assertEqual(server.get("/api/v1/users")[0], 500)
        self.assertEqual(server.get(f"/api/v1/users/{USER}/connections")[0], 200)


class TestRunnerWiring(unittest.TestCase):
    """Le runner lance le stub, écrit la configuration et la clé, puis l'arrête : lecture complète par le vrai client."""

    def read_with_real_client(self, case_id: str, extra_env: dict | None = None):
        cases = {c["id"]: c for c in runner.load_cases()}
        tmp = tempfile.TemporaryDirectory(prefix="arc-ow-wiring-")
        self.addCleanup(tmp.cleanup)
        case = cases[case_id]
        workspace = runner.build_workspace(Path(tmp.name), case)
        self.addCleanup(runner.stop_http_stubs, workspace)
        env = dict(os.environ, ARC_WORKSPACE=str(workspace), ARC_TOOL_LOG=str(workspace / ".tool-calls.log"),
                   **(extra_env or {}))
        done = subprocess.run([sys.executable, "scripts/arc_openwearables.py", "health-day", "--json"],
                              cwd=str(workspace), env=env, capture_output=True, text=True, timeout=60)
        return case, workspace, done

    def test_full_strava_case_is_read_end_to_end(self):
        case, workspace, done = self.read_with_real_client("health-ow-full-strava")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        arc = payload["arc"]
        self.assertEqual((arc["health_source"], arc["health_provider"]), ("openwearables", "oura"))
        self.assertEqual(arc["hrv_overnight_ms"], 48.2)
        self.assertEqual(arc["resting_hr_bpm"], 47)
        scores = {(s["category"], s["value"], s["scale_max"]) for s in arc["provider_scores"]}
        self.assertEqual(scores, {("readiness", 82, 100), ("sleep", 77, 100)})       # `internal` et `whoop` écartés
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["freshness"]["status"], "active")
        self.assertFalse(payload["freshness"]["stale"])
        logged = (workspace / ".tool-calls.log").read_text(encoding="utf-8")
        for name in ("ow_users", "ow_connections", "ow_sleep_summary", "ow_timeseries", "ow_health_scores"):
            self.assertIn(name, logged)
        self.assertNotIn("ow_recovery_summary", logged)              # endpoint obsolète : le client ne l'appelle jamais
        config = (workspace / "config" / "workspace.user.toml").read_text(encoding="utf-8")
        self.assertIn('source = "openwearables"', config)
        self.assertIn("[health.openwearables]", config)
        key_file = Path(next(l for l in config.splitlines() if l.startswith("api_key_file")).split('"')[1])
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        self.assertFalse(str(key_file).startswith(str(workspace)))   # hors du workspace que l'agent explore

    def test_not_synced_case_has_no_night(self):
        case, workspace, done = self.read_with_real_client("health-ow-not-synced-headless")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        self.assertNotIn("sleep_total_s", payload["arc"])
        self.assertNotIn("hrv_overnight_ms", payload["arc"])
        self.assertIn("hrv_overnight_ms", payload["unavailable"])

    def test_unreachable_case_exits_3_quickly(self):
        # `run_case` pose ARC_OW_TIMEOUT pour l'agent quand le cas scripte un timeout OW : on fait de même.
        case, workspace, done = self.read_with_real_client(
            "health-ow-unreachable", {"ARC_OW_TIMEOUT": runner.OW_CLIENT_TIMEOUT_S})
        self.assertTrue(runner._uses_ow_timeout(case))
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["error"]["code"], "unreachable")

    def test_apple_case_gives_sdnn_and_no_rmssd(self):
        case, workspace, done = self.read_with_real_client("health-ow-apple-sdnn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual(payload["arc"]["hrv_sdnn_ms"], 52)
        self.assertNotIn("hrv_overnight_ms", payload["arc"])
        self.assertIn("hrv_overnight_ms", payload["unavailable"])

    def test_stop_http_stubs_is_idempotent_and_cases_without_a_stub_start_nothing(self):
        cases = {c["id"]: c for c in runner.load_cases()}
        with tempfile.TemporaryDirectory(prefix="arc-ow-nostub-") as tmp:
            workspace = runner.build_workspace(Path(tmp), cases["health-full-triad"])
            self.assertNotIn(str(workspace), runner._HTTP_STUBS)
            user_toml = workspace / "config" / "workspace.user.toml"
            self.assertTrue(not user_toml.exists() or "openwearables" not in user_toml.read_text(encoding="utf-8"))
            runner.stop_http_stubs(workspace)
            runner.stop_http_stubs(workspace)

    def test_primary_case_keeps_primary_but_a_stub_runs_to_log_a_silent_call(self):
        cases = {c["id"]: c for c in runner.load_cases()}
        with tempfile.TemporaryDirectory(prefix="arc-ow-primary-") as tmp:
            workspace = runner.build_workspace(Path(tmp), cases["health-primary-no-mention"])
            try:
                self.assertIn(str(workspace), runner._HTTP_STUBS)
                config = (workspace / "config" / "workspace.user.toml").read_text(encoding="utf-8")
                self.assertIn('source = "primary"', config)
                self.assertNotIn('source = "openwearables"', config)
            finally:
                runner.stop_http_stubs(workspace)

    def test_a_failure_after_the_stub_started_stops_it(self):
        cases = {c["id"]: c for c in runner.load_cases()}
        started = []
        real_start = runner._start_http_stubs

        def spy(*args, **kwargs):
            result = real_start(*args, **kwargs)
            started.extend(p for procs in runner._HTTP_STUBS.values() for p in procs)
            return result

        with tempfile.TemporaryDirectory(prefix="arc-ow-fail-") as tmp:
            with mock.patch.object(runner, "_start_http_stubs", spy), \
                    mock.patch.object(runner, "_write_fake_tokens", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    runner.build_workspace(Path(tmp), cases["health-ow-full-strava"])
        self.assertTrue(started and all(p.poll() is not None for p in started))

    def test_subtable_numbers_are_bare_and_top_level_ones_keep_the_historical_string(self):
        toml = runner._overrides_to_toml({"sync": {"lookback_days": 3},
                                          "health": {"openwearables": {"stale_after_h": 36, "provider": "oura"}}})
        self.assertIn('lookback_days = "3"', toml)
        self.assertIn("stale_after_h = 36", toml)
        self.assertIn('provider = "oura"', toml)

    def test_a_started_stub_is_stopped(self):
        cases = {c["id"]: c for c in runner.load_cases()}
        with tempfile.TemporaryDirectory(prefix="arc-ow-stop-") as tmp:
            workspace = runner.build_workspace(Path(tmp), cases["health-ow-full-strava"])
            procs = list(runner._HTTP_STUBS[str(workspace)])
            self.assertTrue(procs and all(p.poll() is None for p in procs))
            runner.stop_http_stubs(workspace)
            self.assertTrue(all(p.poll() is not None for p in procs))
            self.assertNotIn(str(workspace), runner._HTTP_STUBS)


if __name__ == "__main__":
    unittest.main()
