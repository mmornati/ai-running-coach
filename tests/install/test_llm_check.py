"""Palier A — `arc_llm.py check` et `coach_doctor --probe-llm` : diagnostic de la connexion IA (#268).

Faux serveurs locaux sur 127.0.0.1 (OpenRouter /api/v1/key, Anthropic /v1/models, compatible OpenAI
/models). Aucun réseau réel. Verrouille :
  - la détection du fournisseur et chaque cas : valide, 401, 402, crédit épuisé, palier gratuit à 0,
    réseau coupé, jeton d'abonnement présent / absent / échu / de mauvais type, droits des fichiers ;
  - qu'aucune valeur de secret n'apparaît (table et JSON, stdout et stderr) ;
  - qu'AUCUN appel réseau n'est fait sans --probe (arc_llm.py) ni sans --probe-llm (coach_doctor) ;
  - la traduction des erreurs du chat avec les mêmes mots et l'action « check ».
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.local_http import HTTPServer as LocalHTTPServer

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "arc_llm.py"
DOCTOR = REPO / "scripts" / "coach_doctor.py"
SECRET = "sk-or-v1-CHECK-SECRET-VALUE-9876543210"
TOKEN = "eyJ-FAKE-ACCESS-TOKEN-NEVER-PRINTED"
REFRESH = "FAKE-REFRESH-TOKEN-NEVER-PRINTED"
FREE_MODEL = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
PAID_MODEL = "openrouter/deepseek/deepseek-v4.1-flash"


class FakeProviders:
    """Un seul faux serveur : /api/v1/key (OpenRouter), /v1/models (Anthropic), /models (compatible OpenAI)."""

    def __init__(self, key_json=None, key_status: int = 200, models_status: int = 200) -> None:
        self.key_json = key_json if key_json is not None else {
            "label": "AI Running Coach", "limit": None, "limit_remaining": None, "usage": 0.1, "is_free_tier": False,
            "free_model_daily_requests": {"used": 3, "limit": 50, "remaining": 47}}
        self.key_status = key_status
        self.models_status = models_status
        self.hits: list = []
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

            def do_GET(self):
                outer.hits.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                if self.path.startswith("/api/v1/key"):
                    if outer.key_status != 200:
                        return self._send(outer.key_status, {"error": {"message": "refused " + SECRET}})
                    return self._send(200, {"data": outer.key_json})
                if self.path.startswith("/v1/models") or self.path.startswith("/models"):
                    if outer.models_status != 200:
                        return self._send(outer.models_status, {"error": {"message": "refused"}})
                    return self._send(200, {"data": [{"id": "m1"}]})
                self._send(404, {})

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


def _closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d" % port


def _fake_opencode(directory: Path) -> Path:
    """Faux binaire `opencode` à la version testée : le diagnostic ne dépend pas de l'OpenCode de la machine (absent en CI)."""
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from arc_llm_check import tested_version
    finally:
        sys.path.pop(0)
    path = Path(directory) / "opencode"
    path.write_text("#!/bin/sh\necho %s\n" % tested_version(), encoding="utf-8")
    path.chmod(0o755)
    return path


class Env:
    """Workspace + llm.env + variables d'environnement isolés (jamais le vrai HOME)."""

    def __init__(self, toml: str, llm_env: str = "", env_mode: int = 0o600) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.workspace = self.root / "ws"
        (self.workspace / "config").mkdir(parents=True)
        (self.workspace / "config/workspace.user.toml").write_text(toml, encoding="utf-8")
        self.llm_env = self.root / "llm.env"
        if llm_env:
            self.llm_env.write_text(llm_env, encoding="utf-8")
            self.llm_env.chmod(env_mode)
        self.extra: dict = {"ARC_OPENCODE_BIN": str(_fake_opencode(self.root))}

    def close(self) -> None:
        self.dir.cleanup()

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENROUTER", "ANTHROPIC", "OPENAI", "ARC_"))}
        env.pop("OPENCODE_DISABLE_DEFAULT_PLUGINS", None)
        env["ARC_LLM_ENV"] = str(self.llm_env)
        env["HOME"] = str(self.root)
        env.update(self.extra)
        return env

    def check(self, *args: str):
        proc = subprocess.run([sys.executable, str(SCRIPT), "check", "--workspace", str(self.workspace), *args],
                              capture_output=True, text=True, timeout=60, env=self.env())
        return proc

    def report(self, *args: str) -> dict:
        proc = self.check("--json", *args)
        assert proc.stdout.strip(), proc.stderr
        return json.loads(proc.stdout)


def _by_id(report: dict, check_id: str, scope: str = None) -> dict:
    for c in report["checks"]:
        if c["id"] == check_id and (scope is None or scope in c["scope"].split("+")):
            return c
    raise AssertionError("point %s absent : %s" % (check_id, [c["id"] for c in report["checks"]]))


def _toml(chat_model: str = PAID_MODEL, key_env: str = "OPENROUTER_API_KEY", sync_runner: str = "opencode",
          sync_model: str = "", extra_chat: str = "", extra_sync: str = "") -> str:
    return ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "%s"\napi_key_env = "%s"\n%s\n'
            '[sync]\nrunner = "%s"\nmodel = "%s"\napi_key_env = "%s"\n%s\n'
            % (chat_model, key_env, extra_chat, sync_runner, sync_model or chat_model, key_env, extra_sync))


class OpenRouterTests(InstallAsserts):
    def setUp(self):
        self.env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(self.env.close)

    def test_valid_key_with_credit(self):
        with FakeProviders({"label": "AI Running Coach", "limit": 10, "limit_remaining": 7.5, "is_free_tier": False}) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            proc = self.env.check("--json", "--probe")
            report = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(report["ok"])
            self.assertEqual(_by_id(report, "probe")["status"], "ok")
            self.assertEqual(_by_id(report, "credit")["status"], "ok")
            self.assertIn("7,50 $", _by_id(report, "credit")["message"])
            self.assertEqual(fake.hits[0]["headers"]["authorization"], "Bearer " + SECRET)
            self.assertEqual({c["scope"] for c in report["checks"] if c["id"] == "probe"}, {"chat+sync"})

    def test_key_refused_401(self):
        with FakeProviders(key_status=401) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            proc = self.env.check("--json", "--probe")
            report = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 1)
            item = _by_id(report, "probe")
            self.assertEqual((item["status"], item["action_kind"]), ("error", "reconnect_openrouter"))
            self.assertIn("arc_llm.py connect openrouter", item["action"])

    def test_no_credit_402(self):
        with FakeProviders(key_status=402) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            proc = self.env.check("--json", "--probe")
            item = _by_id(json.loads(proc.stdout), "probe")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual((item["status"], item["action_kind"]), ("error", "add_credit"))
            self.assertIn("https://openrouter.ai/settings/credits", item["action"])

    def test_key_limit_exhausted(self):
        with FakeProviders({"label": "x", "limit": 5, "limit_remaining": 0, "is_free_tier": False}) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            proc = self.env.check("--json", "--probe")
            item = _by_id(json.loads(proc.stdout), "credit")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual((item["status"], item["action_kind"]), ("error", "add_credit"))

    def test_low_credit_warns(self):
        with FakeProviders({"label": "x", "limit": 5, "limit_remaining": 0.4, "is_free_tier": False}) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            proc = self.env.check("--json", "--probe")
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(_by_id(json.loads(proc.stdout), "credit")["status"], "warn")

    def test_no_credit_ever_bought_warns_on_paid_model(self):
        with FakeProviders({"label": "x", "limit": None, "limit_remaining": None, "is_free_tier": True}) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            item = _by_id(self.env.report("--probe"), "credit")
            self.assertEqual((item["status"], item["action_kind"]), ("warn", "add_credit"))

    def test_network_down_is_a_warning_not_a_failure(self):
        self.env.extra["ARC_OPENROUTER_BASE_URL"] = _closed_port_url()
        proc = self.env.check("--json", "--probe")
        item = _by_id(json.loads(proc.stdout), "probe")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual((item["status"], item["action_kind"]), ("warn", "retry"))

    def test_missing_key_is_an_error_without_probe(self):
        env = Env(_toml(), "")
        self.addCleanup(env.close)
        proc = env.check("--json")
        item = _by_id(json.loads(proc.stdout), "key")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual((item["status"], item["action_kind"]), ("error", "reconnect_openrouter"))

    def test_loose_env_file_mode_warns_with_chmod_action(self):
        env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET, env_mode=0o644)
        self.addCleanup(env.close)
        item = _by_id(env.report(), "env_mode")
        self.assertEqual(item["status"], "warn")
        self.assertIn("chmod 600", item["action"])
        self.assertIn(str(env.llm_env), item["action"])

    def test_no_network_without_probe(self):
        with FakeProviders() as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            report = self.env.report()
            self.assertEqual(fake.hits, [])
            self.assertFalse(report["probe"])
            self.assertEqual(_by_id(report, "probe")["status"], "info")


class FreeTierTests(InstallAsserts):
    def setUp(self):
        self.env = Env(_toml(FREE_MODEL), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(self.env.close)

    def _quota(self, remaining):
        return {"label": "x", "limit": None, "limit_remaining": None, "is_free_tier": True,
                "free_model_daily_requests": {"used": 50 - remaining, "limit": 50, "remaining": remaining}}

    def test_remaining_requests_ok(self):
        with FakeProviders(self._quota(41)) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            report = self.env.report("--probe")
            self.assertEqual(report["targets"][0]["provider"], "openrouter-free")
            item = _by_id(report, "free_quota")
            self.assertEqual(item["status"], "ok")
            self.assertIn("41 sur 50", item["message"])
            self.assertNotEqual(_by_id(report, "credit")["status"], "error")

    def test_quota_exhausted_says_wait_until_tomorrow(self):
        with FakeProviders(self._quota(0)) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            proc = self.env.check("--json", "--probe")
            item = _by_id(json.loads(proc.stdout), "free_quota")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual((item["status"], item["action_kind"]), ("error", "wait"))
            self.assertIn("demain", item["action"])

    def test_few_requests_left_warns(self):
        with FakeProviders(self._quota(3)) as fake:
            self.env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            self.assertEqual(_by_id(self.env.report("--probe"), "free_quota")["status"], "warn")


class ApiKeyProviderTests(InstallAsserts):
    def test_anthropic_models_endpoint_valid_and_refused(self):
        toml = '[chat]\nenabled = true\nbackend = "claude"\nmodel = "claude-sonnet-5-5"\napi_key_env = "ANTHROPIC_API_KEY"\n[sync]\nrunner = "claude"\n'
        env = Env(toml, "ANTHROPIC_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        with FakeProviders() as fake:
            env.extra["ARC_ANTHROPIC_BASE_URL"] = fake.url
            report = env.report("--probe")
            self.assertEqual(report["targets"][0]["provider"], "anthropic")
            self.assertEqual(_by_id(report, "probe", "chat")["status"], "ok")
            hit = fake.hits[0]
            self.assertTrue(hit["path"].startswith("/v1/models"))
            self.assertEqual(hit["headers"]["x-api-key"], SECRET)
            self.assertEqual(hit["headers"]["anthropic-version"], "2023-06-01")
            fake.models_status = 401
            fake.hits.clear()
            proc = env.check("--json", "--probe")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(_by_id(json.loads(proc.stdout), "probe", "chat")["status"], "error")

    def test_openai_compatible_models_endpoint(self):
        with FakeProviders() as fake:
            toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "mistral/mistral-large"\n'
                    'api_key_env = "MISTRAL_API_KEY"\nbase_url = "%s"\n[sync]\nrunner = "claude"\n' % (fake.url + "/v1"))
            env = Env(toml, "MISTRAL_API_KEY=%s\n" % SECRET)
            self.addCleanup(env.close)
            report = env.report("--probe")
            self.assertEqual(report["targets"][0]["provider"], "openai-compatible")
            self.assertEqual(_by_id(report, "probe", "chat")["status"], "ok")
            self.assertEqual(fake.hits[0]["path"], "/v1/models")
            self.assertEqual(fake.hits[0]["headers"]["authorization"], "Bearer " + SECRET)
            fake.models_status = 401
            proc = env.check("--json", "--probe")
            self.assertEqual(proc.returncode, 1)

    def test_api_network_down_warns(self):
        toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "mistral/x"\n'
                'api_key_env = "MISTRAL_API_KEY"\nbase_url = "%s/v1"\n[sync]\nrunner = "claude"\n' % _closed_port_url())
        env = Env(toml, "MISTRAL_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        proc = env.check("--json", "--probe")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(_by_id(json.loads(proc.stdout), "probe", "chat")["status"], "warn")

    def test_non_loopback_test_override_is_refused(self):
        toml = '[chat]\nenabled = true\nbackend = "claude"\nmodel = "claude-sonnet-5-5"\napi_key_env = "ANTHROPIC_API_KEY"\n[sync]\nrunner = "claude"\n'
        env = Env(toml, "ANTHROPIC_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        env.extra["ARC_ANTHROPIC_BASE_URL"] = "http://example.com"
        proc = env.check("--json", "--probe")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(_by_id(json.loads(proc.stdout), "probe", "chat")["status"], "error")

    def test_sync_on_assistant_subscription_and_mixed_providers(self):
        toml = '[chat]\nenabled = true\nbackend = "mock"\nmodel = "x"\n[sync]\nrunner = "codex"\n'
        env = Env(toml)
        self.addCleanup(env.close)
        report = env.report()
        self.assertEqual([t["provider"] for t in report["targets"]], ["mock", "assistant"])
        self.assertEqual(_by_id(report, "mixed_providers")["status"], "info")

    def test_config_error_is_reported_not_raised(self):
        env = Env("[chat\nenabled =")
        self.addCleanup(env.close)
        proc = env.check("--json")
        self.assertIn(proc.returncode, (0, 1))
        report = json.loads(proc.stdout)
        self.assertTrue(report["checks"])
        if sys.version_info >= (3, 11):          # `tomllib` présent : la syntaxe invalide est refusée
            self.assertEqual((proc.returncode, _by_id(report, "config")["status"]), (1, "error"))

    def test_keyless_local_server_is_not_an_error_and_is_probed_without_auth(self):
        with FakeProviders() as fake:
            toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "ollama/llama3"\napi_key_env = ""\n'
                    'base_url = "%s/v1"\n[sync]\nrunner = "opencode"\nmodel = "ollama/llama3"\napi_key_env = ""\nbase_url = "%s/v1"\n'
                    % (fake.url, fake.url))
            env = Env(toml)
            self.addCleanup(env.close)
            proc = env.check("--json", "--probe")
            report = json.loads(proc.stdout)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(_by_id(report, "key")["status"], "info")
            self.assertEqual(_by_id(report, "probe")["status"], "ok")
            self.assertEqual(fake.hits[0]["path"], "/v1/models")
            self.assertNotIn("authorization", fake.hits[0]["headers"])
            self.assertFalse([c for c in report["checks"] if c["id"] == "key_config"])

    def test_keyless_remote_server_is_informational_and_not_probed(self):
        toml = ('[sync]\nrunner = "opencode"\nmodel = "x/y"\napi_key_env = ""\n'
                'base_url = "https://user:pass-word-123@example.invalid:8443/v1"\n')
        env = Env(toml)
        self.addCleanup(env.close)
        proc = env.check("--json", "--probe")
        self.assertEqual(proc.returncode, 0)
        item = _by_id(json.loads(proc.stdout), "key")
        self.assertEqual(item["status"], "info")
        self.assertIn("example.invalid:8443", item["message"])
        self.assertNotIn("pass-word-123", proc.stdout + proc.stderr)

    def test_base_url_userinfo_is_never_printed(self):
        with FakeProviders() as fake:
            host = fake.url.replace("http://", "")
            toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "m/x"\napi_key_env = "MY_KEY"\n'
                    'base_url = "http://user:pass-word-123@%s/v1"\n[sync]\nrunner = "claude"\n' % host)
            env = Env(toml, "MY_KEY=%s\n" % SECRET)
            self.addCleanup(env.close)
            proc = env.check("--probe")
            self.assertNotIn("pass-word-123", proc.stdout + proc.stderr)

    def test_other_opencode_provider_with_a_key_gets_the_presence_check(self):
        toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "mistral/large"\napi_key_env = "MISTRAL_API_KEY"\n'
                '[sync]\nrunner = "claude"\n')
        env = Env(toml)
        self.addCleanup(env.close)
        proc = env.check("--json")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(_by_id(json.loads(proc.stdout), "key")["status"], "error")
        env2 = Env(toml, "MISTRAL_API_KEY=%s\n" % SECRET)
        self.addCleanup(env2.close)
        self.assertEqual(_by_id(env2.report(), "key")["status"], "ok")

    def test_malformed_http_response_is_a_warning_not_a_crash(self):
        import threading as th
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)

        def serve():
            for _ in range(2):
                try:
                    conn, _addr = srv.accept()
                    conn.recv(4096)
                    conn.sendall(b"not http at all\r\n\r\n")
                    conn.close()
                except OSError:
                    return

        th.Thread(target=serve, daemon=True).start()
        self.addCleanup(srv.close)
        env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        env.extra["ARC_OPENROUTER_BASE_URL"] = "http://127.0.0.1:%d" % srv.getsockname()[1]
        proc = env.check("--json", "--probe")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(_by_id(json.loads(proc.stdout), "probe")["status"], "warn")

    def test_scrub_is_recursive_and_ignores_short_values(self):
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import arc_llm_check
        finally:
            sys.path.pop(0)
        value = {"a": ["xx-SECRET-VALUE-xx", {"b": "ok"}], "n": 3}
        self.assertEqual(arc_llm_check._scrub(value, ["SECRET-VALUE"]), {"a": ["xx-[masqué]-xx", {"b": "ok"}], "n": 3})
        self.assertEqual(arc_llm_check._scrub({"a": "abc ok"}, ["ab"]), {"a": "abc ok"})


def _store(root: Path, entries: dict, dir_mode: int = 0o700, file_mode: int = 0o600) -> Path:
    store = root / "store"
    (store / "opencode").mkdir(parents=True)
    auth = store / "opencode/auth.json"
    auth.write_text(json.dumps(entries), encoding="utf-8")
    auth.chmod(file_mode)
    store.chmod(dir_mode)
    return store


def _oauth(expires: int) -> dict:
    return {"type": "oauth", "refresh": REFRESH, "access": TOKEN, "expires": expires, "accountId": "acct-xyz"}


class SubscriptionTests(InstallAsserts):
    def _env(self, provider_model: str, store: Path, **kw) -> Env:
        toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "%s"\napi_key_env = ""\nopencode_data_dir = "%s"\n'
                '[sync]\nrunner = "opencode"\nmodel = "%s"\napi_key_env = ""\nopencode_data_dir = "%s"\n'
                % (provider_model, store, provider_model, store))
        env = Env(toml)
        self.addCleanup(env.close)
        return env

    def test_chatgpt_token_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() + 3 * 3600) * 1000))})
            env = self._env("openai/gpt-5.4-mini", store)
            proc = env.check("--json")
            report = json.loads(proc.stdout)
            self.assertEqual(report["targets"][0]["provider"], "chatgpt")
            self.assertEqual(_by_id(report, "auth")["status"], "ok")
            self.assertEqual(_by_id(report, "expiry")["status"], "ok")
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn(TOKEN, proc.stdout + proc.stderr)
            self.assertNotIn(REFRESH, proc.stdout + proc.stderr)
            self.assertNotIn("acct-xyz", proc.stdout)

    def test_chatgpt_access_token_past_is_informational(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() - 7200) * 1000))})
            env = self._env("openai/gpt-5.4-mini", store)
            item = _by_id(env.report(), "expiry")
            self.assertEqual(item["status"], "info")
            self.assertIn("arc_llm.py login chatgpt", item["action"])
            self.assertIn(str(store), item["action"])

    def test_chatgpt_missing_entry_is_error_with_login_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"github-copilot": _oauth(0)})
            env = self._env("openai/gpt-5.4-mini", store)
            proc = env.check("--json")
            item = _by_id(json.loads(proc.stdout), "auth")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual((item["status"], item["action_kind"]), ("error", "reconnect_chatgpt"))
            self.assertIn("login chatgpt --data-dir", item["action"])

    def test_missing_store_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env("github-copilot/gpt-5.4-mini", Path(tmp) / "nope")
            proc = env.check("--json")
            item = _by_id(json.loads(proc.stdout), "auth")
            self.assertEqual((proc.returncode, item["action_kind"]), (1, "reconnect_copilot"))

    def test_copilot_has_no_expiry_and_api_type_is_not_an_account_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"github-copilot": _oauth(0)})
            env = self._env("github-copilot/gpt-5.4-mini", store)
            report = env.report()
            self.assertEqual(report["targets"][0]["provider"], "copilot")
            self.assertEqual(_by_id(report, "auth")["status"], "ok")
            self.assertEqual(_by_id(report, "expiry")["status"], "info")
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"openai": {"type": "api", "key": TOKEN}})
            env = self._env("openai/gpt-5.4-mini", store)
            proc = env.check("--json")
            # une clé API saisie à la main n'est pas une connexion de compte : le coach ne l'utilise pas
            self.assertEqual(_by_id(json.loads(proc.stdout), "auth")["status"], "error")
            self.assertNotIn(TOKEN, proc.stdout)

    def test_store_and_auth_file_modes_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() + 3600) * 1000))}, dir_mode=0o755, file_mode=0o644)
            env = self._env("openai/gpt-5.4-mini", store)
            report = env.report()
            self.assertEqual(_by_id(report, "store_mode")["status"], "warn")
            self.assertIn("chmod 700", _by_id(report, "store_mode")["action"])
            self.assertEqual(_by_id(report, "auth_mode")["status"], "warn")
            self.assertIn("chmod 600", _by_id(report, "auth_mode")["action"])

    def test_disable_default_plugins_warns_for_subscriptions_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() + 3600) * 1000))})
            env = self._env("openai/gpt-5.4-mini", store)
            env.extra["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "1"
            self.assertEqual(_by_id(env.report(), "opencode_plugins")["status"], "warn")
        other = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(other.close)
        other.extra["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "1"
        self.assertFalse([c for c in other.report()["checks"] if c["id"] == "opencode_plugins"])

    def test_subscription_never_calls_the_network(self):
        with tempfile.TemporaryDirectory() as tmp, FakeProviders() as fake:
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() + 3600) * 1000))})
            env = self._env("openai/gpt-5.4-mini", store)
            env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            env.extra["ARC_OPENAI_BASE_URL"] = fake.url
            env.report("--probe")
            self.assertEqual(fake.hits, [])


class OpenCodeBinaryTests(InstallAsserts):
    def test_missing_opencode_is_an_error_and_old_version_is_informational(self):
        env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        env.extra["ARC_OPENCODE_BIN"] = str(env.root / "absent-opencode")
        proc = env.check("--json")
        item = _by_id(json.loads(proc.stdout), "opencode")
        self.assertTrue(item["status"] in ("error", "warn"))
        fake_bin = env.root / "opencode"
        fake_bin.write_text("#!/bin/sh\necho 0.0.1\n", encoding="utf-8")
        fake_bin.chmod(0o755)
        env.extra["ARC_OPENCODE_BIN"] = str(fake_bin)
        item = _by_id(env.report(), "opencode")
        self.assertEqual(item["status"], "info")
        self.assertIn("0.0.1", item["message"])


class NoSecretTests(InstallAsserts):
    def test_no_secret_in_any_output_table_or_json(self):
        with FakeProviders(key_status=401) as fake, tempfile.TemporaryDirectory() as tmp:
            for flags in ((), ("--json",), ("--probe",), ("--json", "--probe")):
                env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
                self.addCleanup(env.close)
                env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
                proc = env.check(*flags)
                self.assertNotIn(SECRET, proc.stdout + proc.stderr, flags)
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() + 3600) * 1000))})
            toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "openai/gpt-5.4"\napi_key_env = ""\nopencode_data_dir = "%s"\n'
                    '[sync]\nrunner = "claude"\n' % store)
            env = Env(toml)
            self.addCleanup(env.close)
            for flags in ((), ("--json", "--probe")):
                proc = env.check(*flags)
                for secret in (TOKEN, REFRESH):
                    self.assertNotIn(secret, proc.stdout + proc.stderr)


class DoctorTests(InstallAsserts):
    def _doctor(self, env: Env, *flags: str) -> dict:
        proc = subprocess.run([sys.executable, str(DOCTOR), "--workspace", str(env.workspace), "--check", "llm_config",
                               "--json", *flags], capture_output=True, text=True, timeout=60, env=env.env())
        self.assertNotIn(SECRET, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)["checks"][0]

    def test_static_by_default_no_network_then_probe_llm_contacts_provider(self):
        env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        with FakeProviders(key_status=401) as fake:
            env.extra["ARC_OPENROUTER_BASE_URL"] = fake.url
            check = self._doctor(env)
            self.assertEqual(fake.hits, [])
            self.assertEqual(check["status"], "ok")
            check = self._doctor(env, "--probe-llm")
            self.assertEqual(len(fake.hits), 1)
            self.assertEqual(check["status"], "warning")
            self.assertIn("refusée", check["message"])
            self.assertIn("arc_llm.py connect openrouter", check["fix"])

    def test_subscription_without_token_is_a_warning_even_static(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            store.mkdir()
            toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "openai/gpt-5.4"\napi_key_env = ""\nopencode_data_dir = "%s"\n'
                    '[sync]\nrunner = "claude"\n' % store)
            env = Env(toml)
            self.addCleanup(env.close)
            check = self._doctor(env)
            self.assertEqual(check["status"], "warning")
            self.assertIn("login chatgpt", check["fix"])

    def test_doctor_survives_a_failing_diagnostic(self):
        env = Env(_toml(), "OPENROUTER_API_KEY=%s\n" % SECRET)
        self.addCleanup(env.close)
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import arc_llm_check
            import coach_doctor
        finally:
            sys.path.pop(0)
        original = arc_llm_check.run_checks

        def boom(*a, **k):
            raise RuntimeError("diagnostic cassé")

        arc_llm_check.run_checks = boom
        try:
            self.assertIsNone(coach_doctor._llm_diagnostic(env.workspace, False))
            config = {"chat": {"enabled": True, "backend": "opencode", "model": "openrouter/x/y", "api_key_env": "OPENROUTER_API_KEY"},
                      "sync": {"runner": "claude"}}
            check = coach_doctor.check_llm_config(config, env.workspace, True)
            self.assertNotIn("aucun problème détecté", check["message"])
            self.assertIn("indisponible", check["message"])
            self.assertNotEqual(check["status"], "error")
        finally:
            arc_llm_check.run_checks = original


class ChatErrorVocabularyTests(InstallAsserts):
    def setUp(self):
        sys.path.insert(0, str(REPO / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(REPO / "scripts")))
        import arc_chat_opencode
        import arc_llm
        self.O, self.L = arc_chat_opencode, arc_llm

    def tr(self, status, message, model=PAID_MODEL, sub=None):
        return self.O.OpenCodeBackend._translate_error({"name": "APIError", "data": {"statusCode": status, "message": message}}, sub, "", model)

    def test_openrouter_401_402_429_carry_the_action_and_the_diagnostic(self):
        m401 = self.tr(401, "Unauthorized")
        self.assertIn("arc_llm.py connect openrouter", m401)
        self.assertIn(self.L.DIAG_COMMAND, m401)
        m402 = self.tr(402, "Insufficient credits")
        self.assertIn("https://openrouter.ai/settings/credits", m402)
        self.assertIn(self.L.DIAG_COMMAND, m402)
        self.assertIn(self.L.DIAG_COMMAND, self.tr(429, "Rate limit exceeded"))
        self.assertNotIn("connect openrouter", self.tr(401, "Unauthorized", "anthropic/claude"))

    def test_subscription_and_free_errors_carry_the_diagnostic(self):
        chatgpt = self.L.provider("chatgpt")
        self.assertIn(self.L.DIAG_COMMAND, self.tr(401, "Token refresh failed: 400", "openai/gpt-5.4", chatgpt))
        self.assertIn(self.L.DIAG_COMMAND, self.tr(429, "Rate limit", FREE_MODEL))
        self.assertIn(self.L.DIAG_COMMAND, self.tr(404, "No endpoints: ZDR violation", FREE_MODEL))

    def test_with_diag_is_idempotent(self):
        once = self.L.with_diag("Message.")
        self.assertEqual(self.L.with_diag(once), once)
        self.assertIsNone(self.L.with_diag(None))

    def test_claude_backend_messages_carry_the_diagnostic(self):
        import arc_chat_claude
        msg = arc_chat_claude.ClaudeBackend._translate_exception(object(), RuntimeError("401 authentication failed"))
        self.assertIn(self.L.DIAG_COMMAND, msg)
        msg = arc_chat_claude.ClaudeBackend._translate_exception(object(), RuntimeError("Credit balance is too low"))
        self.assertIn(self.L.DIAG_COMMAND, msg)


class ChatRouteTests(InstallAsserts):
    """POST /api/chat/llm-check : mêmes garde-fous que les autres POST, statique par défaut."""

    def test_route_static_probe_on_request_and_csrf(self):
        from tests.install.test_chat_service import ChatCase

        class Case(ChatCase):
            def runTest(self):
                pass

        case = Case()
        case.setUp()
        try:
            (case.ws / "config").mkdir()
            (case.ws / "config/workspace.user.toml").write_text(_toml(), encoding="utf-8")
            llm_env = case.ws / "llm.env"
            llm_env.write_text("OPENROUTER_API_KEY=%s\n" % SECRET, encoding="utf-8")
            llm_env.chmod(0o600)
            old = {k: os.environ.get(k) for k in ("ARC_LLM_ENV", "ARC_OPENROUTER_BASE_URL")}
            os.environ["ARC_LLM_ENV"] = str(llm_env)
            try:
                with FakeProviders(key_status=401) as fake:
                    os.environ["ARC_OPENROUTER_BASE_URL"] = fake.url
                    case.start()
                    status, _, data = case.request("POST", "/api/chat/llm-check", {"probe": True})
                    self.assertEqual(status, 403)                      # sans X-ARC-Chat
                    self.assertEqual(fake.hits, [])
                    status, _, data = case.post("/api/chat/llm-check", {})
                    self.assertEqual(status, 200)
                    self.assertEqual(fake.hits, [])                    # statique par défaut
                    self.assertEqual(_by_id(data, "probe")["status"], "info")
                    status, _, data = case.post("/api/chat/llm-check", {"probe": True})
                    self.assertEqual((status, len(fake.hits)), (200, 1))
                    self.assertEqual(_by_id(data, "probe")["status"], "error")
                    self.assertNotIn(SECRET, json.dumps(data))
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        finally:
            case.doCleanups()


class ChatRouteGuardTests(InstallAsserts):
    """Authentification, limite de débit, cache de la sonde et charge utile de /api/chat/llm-check."""

    def _case(self):
        from tests.install.test_chat_service import ChatCase

        class Case(ChatCase):
            def runTest(self):
                pass

        case = Case()
        case.setUp()
        self.addCleanup(case.doCleanups)
        (case.ws / "config").mkdir()
        (case.ws / "config/workspace.user.toml").write_text(_toml(), encoding="utf-8")
        llm_env = case.ws / "llm.env"
        llm_env.write_text("OPENROUTER_API_KEY=%s\n" % SECRET, encoding="utf-8")
        llm_env.chmod(0o600)
        bin_dir = tempfile.TemporaryDirectory()
        self.addCleanup(bin_dir.cleanup)
        for name, value in (("ARC_LLM_ENV", str(llm_env)), ("ARC_OPENCODE_BIN", str(_fake_opencode(Path(bin_dir.name))))):
            old = os.environ.get(name)
            os.environ[name] = value
            self.addCleanup(lambda name=name, old=old: os.environ.pop(name, None) if old is None else os.environ.__setitem__(name, old))
        return case

    def test_proxy_mode_requires_identity(self):
        case = self._case()
        case.start(auth="proxy", allowed_users=["marco"], auth_header="Remote-User")
        self.assertEqual(case.post("/api/chat/llm-check", {})[0], 401)
        self.assertEqual(case.post("/api/chat/llm-check", {}, headers={"Remote-User": "intrus"})[0], 403)
        self.assertEqual(case.post("/api/chat/llm-check", {}, headers={"Remote-User": "marco"})[0], 200)

    def test_rate_limited_and_probe_results_cached(self):
        case = self._case()
        with FakeProviders() as fake:
            old = os.environ.get("ARC_OPENROUTER_BASE_URL")
            os.environ["ARC_OPENROUTER_BASE_URL"] = fake.url
            self.addCleanup(lambda: os.environ.pop("ARC_OPENROUTER_BASE_URL", None) if old is None
                            else os.environ.__setitem__("ARC_OPENROUTER_BASE_URL", old))
            case.start()
            for _ in range(5):
                status, _, data = case.post("/api/chat/llm-check", {"probe": True})
                self.assertEqual(status, 200)
            self.assertEqual(len(fake.hits), 1)              # cache de 30 s : un seul appel au fournisseur
            self.assertNotIn("workspace", data)              # pas de chemin absolu dans la charge utile
            self.assertEqual(case.post("/api/chat/llm-check", {})[0], 200)
            status, _, body = case.post("/api/chat/llm-check", {})
            self.assertEqual(status, 429)
            self.assertIn("error", body)


class AppMappingTests(InstallAsserts):
    """Contrôle de texte du code Swift (compilé en CI macOS, pas ici) : la reconnexion d'abonnement vient du diagnostic."""

    def test_subscription_reconnect_uses_the_check_item_not_preferences(self):
        text = (REPO / "macos/AI-Running-Coach/AI_Running_CoachApp.swift").read_text(encoding="utf-8")
        start = text.index("func performConnectionAction")
        body = text[start:text.index("private func reconnectOpenRouter", start)]
        self.assertIn('case "reconnect_chatgpt", "reconnect_copilot"', body)
        self.assertIn("item.dataDir", body)
        self.assertNotIn("savedChatProvider", body)
        self.assertIn("connectionReconnecting", text)
        reconnect = text[text.index("private func reconnectOpenRouter"):text.index("func retryLastOperation")]
        self.assertIn("savedTitle", reconnect)                    # restitue l'état de l'écran d'installation
        self.assertIn("connectOpenRouter()", reconnect)           # même flux que l'installation (lien, annulation)
        self.assertIn("cancelConnection", text[text.index("func closeConnectionCheck"):][:200])      # n'écrase pas l'écran d'installation

    def test_error_result_is_not_cached_so_a_fixed_key_is_retested(self):
        case = ChatRouteGuardTests._case(self)
        with FakeProviders(key_status=401) as fake:
            old = os.environ.get("ARC_OPENROUTER_BASE_URL")
            os.environ["ARC_OPENROUTER_BASE_URL"] = fake.url
            self.addCleanup(lambda: os.environ.pop("ARC_OPENROUTER_BASE_URL", None) if old is None
                            else os.environ.__setitem__("ARC_OPENROUTER_BASE_URL", old))
            case.start()
            for _ in range(3):
                self.assertEqual(case.post("/api/chat/llm-check", {"probe": True})[0], 200)
            self.assertEqual(len(fake.hits), 3)

    def test_doctor_fix_lists_every_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp), {"openai": _oauth(int((time.time() + 3600) * 1000))}, dir_mode=0o755, file_mode=0o644)
            toml = ('[chat]\nenabled = true\nbackend = "opencode"\nmodel = "openai/gpt-5.4"\napi_key_env = ""\nopencode_data_dir = "%s"\n'
                    '[sync]\nrunner = "claude"\n' % store)
            env = Env(toml)
            self.addCleanup(env.close)
            proc = subprocess.run([sys.executable, str(DOCTOR), "--workspace", str(env.workspace), "--check", "llm_config", "--json"],
                                  capture_output=True, text=True, timeout=60, env=env.env())
            fix = json.loads(proc.stdout)["checks"][0]["fix"]
            self.assertIn("chmod 700", fix)
            self.assertIn("chmod 600", fix)
