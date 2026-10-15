"""Palier A — essai gratuit OpenRouter (`--llm openrouter-free`, #267).

Verrouille, dans le bac à sable (aucun réseau réel, aucun LLM réel) :
  - la configuration écrite par `install.sh --llm openrouter-free` (modèle `:free`, backend/runner
    opencode, même clé qu'openrouter) et ses avertissements (quota, confidentialité, ZDR, 0 €) ;
  - `[sync].mode = "watch"` proposé SEULEMENT si l'athlète ne l'a pas déjà posé (jamais écrasé) ;
  - la cohérence constante d'install.sh / catalogue de `scripts/arc_llm.py` ;
  - `arc_llm.py free-quota` (faux serveur local, clé jamais affichée) ;
  - les notifications distinctes de la sync (quota du jour, limite momentanée, ZDR).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.install.test_llm_chat_ops import (SECRET, _curl_calls, _events_file, _run_sync, _stub_opencode,
                                             _write_config, _write_llm_env)
from tests.lib.asserts import InstallAsserts
from tests.lib.local_http import HTTPServer as LocalHTTPServer
from tests.lib.sandbox import Sandbox

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "arc_llm.py"
BASE = ("--no-auth", "--ide", "claude")
FREE_MODEL = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"


def _toml(sb: Sandbox) -> str:
    return (sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8")


class CatalogTests(InstallAsserts):
    def test_install_constant_matches_catalog(self):
        text = (REPO / "install.sh").read_text(encoding="utf-8")
        const = re.search(r'^LLM_OPENROUTER_FREE_MODEL="([^"]*)"', text, re.M).group(1)
        proc = subprocess.run([sys.executable, str(SCRIPT), "providers", "--json"], capture_output=True, text=True, timeout=30)
        free = {p["id"]: p for p in json.loads(proc.stdout)["providers"]}["openrouter-free"]
        self.assertEqual(const, free["chat_model"])
        self.assertEqual(const, free["sync_model"])
        self.assertEqual(free["kind"], "free")
        self.assertEqual(free["key_env"], "OPENROUTER_API_KEY")
        self.assertTrue(const.endswith(":free"))
        for alt in free["alternatives"]:
            self.assertTrue(alt.endswith(":free") and alt.startswith("openrouter/"), alt)
        self.assertEqual(free["benchmark"]["date"], "2026-10-15")
        for field in ("quota", "privacy", "monthly_cost"):
            self.assertTrue(free[field])


class InstallFreeTests(InstallAsserts):
    def test_writes_chat_and_sync_config_and_says_the_limits(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "openrouter-free")
            self.assertSucceeded(proc)
            toml = _toml(sb)
            self.assertEqual(toml.count('model = "%s"' % FREE_MODEL), 2, toml)
            self.assertIn('backend = "opencode"', toml)
            self.assertIn('runner = "opencode"', toml)
            self.assertEqual(toml.count('api_key_env = "OPENROUTER_API_KEY"'), 2, toml)
            self.assertNotIn("daily_budget_eur", toml)          # gratuit : pas de budget en euros
            self.assertNotIn("opencode_data_dir", toml)         # clé API, pas un abonnement
            self.assertTrue((sb.home / ".config/ai-running-coach/llm.env").exists())
            self.assertOutputContains(proc, "0 € (aucun budget en euros)")
            self.assertOutputContains(proc, "50 requêtes par jour")
            self.assertOutputContains(proc, "environ un /log et quelques questions par jour")
            self.assertOutputContains(proc, "CONFIDENTIALITÉ")
            self.assertOutputContains(proc, "NVIDIA")
            self.assertOutputContains(proc, "https://openrouter.ai/settings/privacy")
            self.assertOutputContains(proc, "ZDR")
            self.assertOutputContains(proc, "à vérifier")
            self.assertOutputLacks(proc, "la plupart des modèles gratuits")

    def test_sync_watch_is_proposed_when_not_set(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "openrouter-free")
            self.assertSucceeded(proc)
            self.assertIn('mode = "watch"', _toml(sb))
            self.assertOutputContains(proc, '[sync].mode = "watch"')

    def test_existing_sync_mode_is_preserved(self):
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nmode = "schedule"\n')
            proc = sb.install(*BASE, "--llm", "openrouter-free")
            self.assertSucceeded(proc)
            self.assertIn('mode = "schedule"', _toml(sb))
            self.assertNotIn('mode = "watch"', _toml(sb))
            self.assertOutputContains(proc, "déjà posé")
        # relance : une valeur posée ensuite par l'athlète n'est jamais retouchée non plus
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter-free"))
            toml = _toml(sb).replace('mode = "watch"', 'mode = "schedule"')
            (sb.repo / "config/workspace.user.toml").write_text(toml, encoding="utf-8")
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter-free"))
            self.assertIn('mode = "schedule"', _toml(sb))

    def test_custom_free_model_and_paid_model_refused(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter-free", "--model", "cohere/north-mini-code:free"))
            self.assertIn('model = "openrouter/cohere/north-mini-code:free"', _toml(sb))
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "openrouter-free", "--model", "deepseek/deepseek-v4.1-flash")
            self.assertFailed(proc)
            self.assertOutputContains(proc, ":free")

    def test_connect_is_the_openrouter_connect(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "openrouter-free", "--connect", "--dry-run")
            self.assertSucceeded(proc)
            self.assertIn("arc_llm.py connect openrouter", proc.stdout)
            self.assertNotIn("open", [name for name, _ in sb.stub_calls()])

    def test_plain_openrouter_and_plain_rerun_unchanged(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "openrouter")
            self.assertSucceeded(proc)
            self.assertNotIn("watch", _toml(sb))
            self.assertNotIn("CONFIDENTIALITÉ", proc.stdout + proc.stderr)
            before = _toml(sb)
            self.assertSucceeded(sb.install(*BASE))
            self.assertEqual(_toml(sb), before)

    def test_scheduler_already_installed_is_reinstalled_in_watch_mode(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--daily-sync", ARC_FAKE_UNAME="Linux"))
            self.assertIn("daily-sync.sh", sb.crontab())
            proc = sb.install(*BASE, "--llm", "openrouter-free", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            ours = [l for l in sb.crontab().splitlines() if "ai-running-coach daily-sync" in l]
            self.assertEqual(len(ours), 1, sb.crontab())
            self.assertIn("garmin_watch.py", ours[0])
            self.assertOutputContains(proc, "réinstallation")

    def test_no_scheduler_installed_says_how_to_apply_watch(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "openrouter-free", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            self.assertEqual(sb.crontab(), "")
            self.assertOutputContains(proc, "--daily-sync")

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--daily-sync", ARC_FAKE_UNAME="Linux"))
            before, cron = sb.tree(), sb.crontab()
            proc = sb.install(*BASE, "--llm", "openrouter-free", "--dry-run", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            self.assertEqual(sb.tree(), before)
            self.assertEqual(sb.crontab(), cron)
            self.assertOutputContains(proc, "[sync].mode = watch")

    def test_non_garmin_source_keeps_fixed_hours(self):
        with Sandbox() as sb:
            _write_config(sb, '[data]\nsource = "intervals"\n')
            proc = sb.install(*BASE, "--llm", "openrouter-free")
            self.assertSucceeded(proc)
            self.assertNotIn('mode = "watch"', _toml(sb))
            self.assertOutputContains(proc, "heures fixes")

    def test_switching_provider_reminds_that_watch_stays(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter-free"))
            proc = sb.install(*BASE, "--llm", "openrouter")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "reste « watch »")
            self.assertIn('mode = "watch"', _toml(sb))
        with Sandbox() as sb:      # sans essai gratuit préalable : aucun rappel
            self.assertOutputLacks(sb.install(*BASE, "--llm", "openrouter"), "reste « watch »")

    def test_remembered_for_updates(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter-free"))
            self.assertIn("openrouter-free", (sb.home / ".config/ai-running-coach/install-args").read_text())


class _FakeKey:
    def __init__(self, body, status=200):
        outer = self
        self.auth = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.auth.append(self.headers.get("Authorization"))
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = LocalHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FreeQuotaTests(InstallAsserts):
    def _run(self, fake, env_file, *extra):
        env = dict(os.environ, ARC_OPENROUTER_BASE_URL=fake.url)
        env.pop("ARC_LLM_ENV", None)
        env.pop("OPENROUTER_API_KEY", None)
        return subprocess.run([sys.executable, str(SCRIPT), "free-quota", "--env-file", str(env_file), *extra],
                              env=env, capture_output=True, text=True, timeout=30)

    def test_remaining_requests_and_no_secret(self):
        with Sandbox() as sb:
            env_file = _write_llm_env(sb, "OPENROUTER_API_KEY=%s\n" % SECRET)
            fake = _FakeKey({"data": {"label": "x", "is_free_tier": True,
                                      "free_model_daily_requests": {"used": 12, "limit": 50, "remaining": 38}}})
            try:
                proc = self._run(fake, env_file, "--json")
            finally:
                fake.close()
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual((data["used"], data["limit"], data["remaining"]), (12, 50, 38))
            self.assertIn("38 sur 50", data["message"])
            self.assertEqual(fake.auth, ["Bearer " + SECRET])
            self.assertNotIn(SECRET, proc.stdout + proc.stderr)

    def test_unavailable_without_key_or_field(self):
        with Sandbox() as sb:
            env_file = _write_llm_env(sb, "# OPENROUTER_API_KEY=\n")
            fake = _FakeKey({"data": {}})
            try:
                self.assertEqual(self._run(fake, env_file).returncode, 1)
                self.assertEqual(fake.auth, [])                 # pas de clé : aucun appel
                env_file = _write_llm_env(sb, "OPENROUTER_API_KEY=%s\n" % SECRET)
                proc = self._run(fake, env_file, "--json")
            finally:
                fake.close()
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(json.loads(proc.stdout)["ok"])
            self.assertNotIn(SECRET, proc.stdout + proc.stderr)


FREE_SYNC = """\
[sync]
runner = "opencode"
model = "%s"
api_key_env = "OPENROUTER_API_KEY"
[notifications]
provider = "ntfy"
ntfy_topic = "test-topic"
""" % FREE_MODEL


class SyncFailureTests(InstallAsserts):
    def _failing_sync(self, sb, status, message, config=FREE_SYNC):
        _write_config(sb, config)
        _write_llm_env(sb, "OPENROUTER_API_KEY=%s\n" % SECRET)
        _stub_opencode(sb)
        out = _events_file(sb, [{"type": "error", "error": {
            "name": "APIError", "data": {"statusCode": status, "message": message}}}])
        proc = _run_sync(sb, ARC_STUB_OPENCODE_OUT=str(out), ARC_STUB_OPENCODE_RC="1")
        self.assertFailed(proc)
        return " ".join(_curl_calls(sb))

    def test_daily_quota_has_its_own_notification(self):
        with Sandbox() as sb:
            calls = self._failing_sync(sb, 429, "Rate limit exceeded: free-models-per-day. Add 10 credits")
            self.assertIn("quota gratuit du jour atteint", calls)
            self.assertIn("50 requêtes par jour", calls)
            self.assertNotIn("Authentification Garmin", calls)

    def test_minute_or_upstream_limit_is_distinct_from_quota(self):
        with Sandbox() as sb:
            calls = self._failing_sync(sb, 429, "Provider returned error")
            self.assertIn("modèle gratuit saturé", calls)
            self.assertNotIn("quota gratuit du jour atteint", calls)

    def test_privacy_setting_404_has_its_own_notification_free_and_paid(self):
        with Sandbox() as sb:
            calls = self._failing_sync(sb, 404, "No endpoints available: 0 endpoints match, ZDR violation")
            self.assertIn("réglage de confidentialité", calls)
            self.assertIn("NVIDIA", calls)
            self.assertNotIn("Authentification Garmin", calls)
        with Sandbox() as sb:
            paid = FREE_SYNC.replace(FREE_MODEL, "openrouter/deepseek/deepseek-v4.1-flash")
            calls = self._failing_sync(sb, 404, "No endpoints found matching your data policy", paid)
            self.assertIn("réglage de confidentialité", calls)
            self.assertNotIn("NVIDIA", calls)

    def test_per_minute_body_with_daily_upsell_is_not_the_daily_quota(self):
        with Sandbox() as sb:
            calls = self._failing_sync(sb, 429, "Rate limit exceeded: free-models-per-min. Add 10 credits to unlock "
                                                "1000 free model requests per day")
            self.assertIn("modèle gratuit saturé", calls)
            self.assertNotIn("quota gratuit du jour atteint", calls)

    def test_429_on_a_paid_model_keeps_historical_behaviour(self):
        with Sandbox() as sb:
            paid = FREE_SYNC.replace(FREE_MODEL, "openrouter/deepseek/deepseek-v4.1-flash")
            calls = self._failing_sync(sb, 429, "Rate limit exceeded", paid)
            self.assertNotIn("quota gratuit", calls)
            self.assertNotIn("modèle gratuit saturé", calls)

    def test_401_and_402_still_distinct_on_a_free_model(self):
        with Sandbox() as sb:
            self.assertIn("clé openrouter refusée", self._failing_sync(sb, 401, "User not found."))
        with Sandbox() as sb:
            self.assertIn("crédits openrouter épuisés", self._failing_sync(sb, 402, "Insufficient credits."))
