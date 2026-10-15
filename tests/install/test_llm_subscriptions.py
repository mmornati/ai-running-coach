"""Palier A — abonnements ChatGPT / GitHub Copilot (#266) : catalogue, installation, connexion, sync.

Aucun réseau, aucun vrai OpenCode : le stub `tests/lib/stubs/opencode` joue `providers login`
(lignes « Go to: » / « Enter code: », faux auth.json) et `run`. Verrouille :
  - le catalogue (chatgpt, copilot) et sa cohérence avec les constantes d'install.sh ;
  - `install.sh --llm chatgpt|copilot` (clés posées, avertissements « ancien → nouveau », magasin 700,
    --connect, non-régression d'un rerun et des autres fournisseurs) ;
  - `arc_llm.py login` (relais adresse/code, PTY pour Copilot, enfant tué, refus en headless),
    `with-lock`, `auth-status` ;
  - `daily-sync.sh` : XDG_DATA_HOME seulement avec la clé, verrou ChatGPT, aucun coût en euros,
    jeton absent = notification (jamais de login), erreurs du fournisseur traduites.
"""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "arc_llm.py"
STUB = STUBS_DIR / "opencode"
TODAY = date.today().isoformat()
BASE = ("--no-auth", "--ide", "claude")


def _llm(sb: Sandbox, *args: str, **env) -> subprocess.CompletedProcess:
    return sb.run([sys.executable, str(SCRIPT), *args], **env)


def _auth(store: Path, provider: str = "openai") -> None:
    """Faux jeton (valeurs factices) dans `<store>/opencode/auth.json`."""
    target = store / "opencode"
    target.mkdir(parents=True, exist_ok=True)
    (target / "auth.json").write_text(json.dumps({provider: {
        "type": "oauth", "refresh": "r-fake", "access": "a-fake", "expires": 4102444800000}}))
    (target / "auth.json").chmod(0o600)


# --------------------------------------------------------------------------- catalogue

class CatalogTests(InstallAsserts):
    def _providers(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "providers", "--json"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        return {p["id"]: p for p in json.loads(proc.stdout)["providers"]}

    def test_subscription_rows(self):
        providers = self._providers()
        for pid, oc in (("chatgpt", "openai"), ("copilot", "github-copilot")):
            row = providers[pid]
            self.assertEqual(row["kind"], "subscription")
            self.assertEqual(row["key_env"], "")
            self.assertEqual(row["opencode_provider"], oc)
            self.assertTrue(row["chat_model"].startswith(oc + "/"))
            self.assertTrue(row["sync_model"].startswith(oc + "/"))
        self.assertTrue(providers["chatgpt"]["refreshes_tokens"])
        self.assertFalse(providers["copilot"]["refreshes_tokens"])

    def test_install_constants_match_catalog(self):
        text = (REPO / "install.sh").read_text(encoding="utf-8")

        def const(name):
            return re.search(r'^%s="([^"]*)"' % name, text, re.M).group(1)

        providers = self._providers()
        self.assertEqual(const("LLM_CHATGPT_CHAT_MODEL"), providers["chatgpt"]["chat_model"])
        self.assertEqual(const("LLM_CHATGPT_SYNC_MODEL"), providers["chatgpt"]["sync_model"])
        self.assertEqual(const("LLM_COPILOT_CHAT_MODEL"), providers["copilot"]["chat_model"])
        self.assertEqual(const("LLM_COPILOT_SYNC_MODEL"), providers["copilot"]["sync_model"])


# --------------------------------------------------------------------------- install.sh

class InstallSubscriptionTests(InstallAsserts):
    def _toml(self, sb: Sandbox) -> str:
        return (sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8")

    def test_chatgpt_sets_chat_and_sync_without_key(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "chatgpt")
            self.assertSucceeded(proc)
            toml = self._toml(sb)
            store = str(sb.home / ".local/share/ai-running-coach/opencode")
            self.assertEqual(toml.count('opencode_data_dir = "%s"' % store), 2, toml)
            self.assertIn('backend = "opencode"', toml)
            self.assertIn('model = "openai/gpt-5.4-mini"', toml)
            self.assertIn('model = "openai/gpt-5.4"', toml)
            self.assertIn('runner = "opencode"', toml)
            self.assertEqual(toml.count('api_key_env = ""'), 2, toml)
            # magasin dédié en mode 700 ; aucun fichier de clés créé
            mode = stat.S_IMODE(os.stat(store).st_mode)
            self.assertEqual(mode, 0o700)
            self.assertFalse((sb.home / ".config/ai-running-coach/llm.env").exists())
            self.assertOutputContains(proc, "ChatGPT Plus ou Pro")
            self.assertOutputContains(proc, "usage_not_included")
            self.assertOutputContains(proc, "arc_llm.py login chatgpt")

    def test_copilot_models_and_model_override(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "copilot", "--model", "claude-haiku-5.5"))
            toml = self._toml(sb)
            self.assertIn('model = "github-copilot/claude-haiku-5.5"', toml)       # chat : préfixe ajouté
            self.assertIn('model = "github-copilot/claude-sonnet-5.5"', toml)      # sync : catalogue
            self.assertIn("Copilot Free", sb.install(*BASE, "--llm", "copilot").stdout)

    def test_switching_from_openrouter_warns_old_to_new(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter"))
            proc = sb.install(*BASE, "--llm", "chatgpt")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "[chat].model : openrouter/deepseek/deepseek-v4.1-flash → openai/gpt-5.4-mini")
            self.assertOutputContains(proc, "[sync].api_key_env : OPENROUTER_API_KEY →")
            self.assertOutputContains(proc, "Pour revenir")

    def test_base_url_refused(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "chatgpt", "--base-url", "http://x/v1")
            self.assertFailed(proc)
            self.assertOutputContains(proc, "--base-url")

    def test_connect_now_valid_for_subscriptions_only_with_llm(self):
        with Sandbox() as sb:
            self.assertFailed(sb.install(*BASE, "--connect"))
            self.assertFailed(sb.install(*BASE, "--llm", "anthropic", "--connect"))

    def test_dry_run_prints_login_and_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree()
            proc = sb.install(*BASE, "--llm", "chatgpt", "--connect", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "arc_llm.py login chatgpt --data-dir")
            self.assertEqual(sb.tree(), before)
            self.assertEqual([a for n, a in sb.stub_calls("opencode") if "login" in a], [])

    def test_connect_without_tty_gives_the_command(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE, "--llm", "copilot", "--connect")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "terminal interactif")
            self.assertNotIn(("opencode", "providers login -p github-copilot -m Login with GitHub Copilot"),
                             sb.stub_calls())

    def test_other_providers_and_plain_rerun_do_not_touch_the_store_key(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "openrouter"))
            self.assertNotIn("opencode_data_dir", self._toml(sb))
            self.assertSucceeded(sb.install(*BASE))
            self.assertNotIn("opencode_data_dir", self._toml(sb))
            self.assertSucceeded(sb.install(*BASE, "--llm", "chatgpt"))
            before = self._toml(sb)
            self.assertSucceeded(sb.install(*BASE))      # rerun sans option : rien ne bouge
            self.assertEqual(self._toml(sb), before)

    def test_llm_choice_is_remembered_for_updates(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE, "--llm", "chatgpt"))
            remembered = sb.home / ".config/ai-running-coach/install-args"
            self.assertIn("chatgpt", remembered.read_text())


# --------------------------------------------------------------------------- arc_llm.py login / lock

class LoginTests(InstallAsserts):
    def _login(self, sb: Sandbox, provider: str, store: Path, *extra: str, **env):
        return _llm(sb, "login", provider, "--data-dir", str(store), "--no-browser", "--json",
                    "--opencode-bin", str(STUB), *extra, **env)

    def test_chatgpt_relays_url_and_code_and_uses_the_coach_store(self):
        with Sandbox() as sb:
            store = sb.root / "store"
            proc = self._login(sb, "chatgpt", store)
            self.assertSucceeded(proc)
            events = [json.loads(line) for line in proc.stderr.splitlines() if line.startswith("{")]
            self.assertIn({"event": "login_url", "message": "Ouvrez cette adresse : https://auth.example.test/device",
                           "url": "https://auth.example.test/device"}, events)
            self.assertTrue(any(e.get("code") == "ABCD-1234" for e in events), events)
            self.assertNotIn("\x1b", proc.stdout + proc.stderr)           # ANSI retiré
            self.assertEqual(json.loads(proc.stdout)["ok"], True)
            self.assertEqual(stat.S_IMODE(os.stat(store).st_mode), 0o700)
            call = [a for n, a in sb.stub_calls("opencode") if a.startswith("providers login")]
            self.assertEqual(call, ["providers login -p openai -m ChatGPT Pro/Plus (headless)"])
            self.assertTrue(any("XDG_DATA_HOME=%s" % store in a for _, a in sb.stub_calls("opencode")))
            # auth-status : présence seulement
            status = _llm(sb, "auth-status", "chatgpt", "--data-dir", str(store), "--json")
            self.assertEqual(json.loads(status.stdout)["present"], True)
            self.assertNotIn("stub-refresh", status.stdout)

    def test_browser_method_label(self):
        with Sandbox() as sb:
            proc = self._login(sb, "chatgpt", sb.root / "s", "--browser")
            self.assertSucceeded(proc)
            self.assertIn("providers login -p openai -m ChatGPT Pro/Plus (browser)",
                          [a for _, a in sb.stub_calls("opencode")])

    def test_copilot_through_a_pty_answers_the_deployment_menu(self):
        with Sandbox() as sb:
            store = sb.root / "store"
            proc = self._login(sb, "copilot", store)       # stdin n'est pas un terminal -> pseudo-terminal
            self.assertSucceeded(proc)
            self.assertTrue(any(json.loads(l).get("code") == "ABCD-1234"
                                for l in proc.stderr.splitlines() if l.startswith("{") and "code" in l))
            self.assertTrue((store / "opencode/auth.json").is_file())

    def test_failed_login_is_exit_3_and_writes_no_token(self):
        with Sandbox() as sb:
            store = sb.root / "store"
            proc = self._login(sb, "chatgpt", store, ARC_STUB_OPENCODE_LOGIN="fail")
            self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
            self.assertFalse((store / "opencode/auth.json").exists())

    def test_timeout_kills_the_child(self):
        with Sandbox() as sb:
            pidfile = sb.root / "pid"
            proc = self._login(sb, "chatgpt", sb.root / "s", "--timeout", "2",
                               ARC_STUB_OPENCODE_LOGIN="hang", ARC_STUB_OPENCODE_PIDFILE=str(pidfile))
            self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
            pid = int(pidfile.read_text())
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_sigterm_kills_the_child(self):
        with Sandbox() as sb:
            pidfile = sb.root / "pid"
            env = sb.env(ARC_STUB_OPENCODE_LOGIN="hang", ARC_STUB_OPENCODE_PIDFILE=str(pidfile))
            proc = subprocess.Popen([sys.executable, str(SCRIPT), "login", "chatgpt", "--data-dir", str(sb.root / "s"),
                                     "--no-browser", "--opencode-bin", str(STUB)],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(50):
                if pidfile.exists() and pidfile.read_text().strip():
                    break
                time.sleep(0.1)
            child = int(pidfile.read_text())
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=20)
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)

    def test_refused_in_headless(self):
        with Sandbox() as sb:
            proc = self._login(sb, "chatgpt", sb.root / "s", ARC_HEADLESS="1")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(sb.stub_calls("opencode"), [])

    def test_missing_opencode_binary(self):
        with Sandbox() as sb:
            proc = _llm(sb, "login", "chatgpt", "--data-dir", str(sb.root / "s"), "--opencode-bin", "/nonexistent/opencode")
            self.assertEqual(proc.returncode, 2)


class LockTests(InstallAsserts):
    def test_with_lock_serialises_and_times_out_with_75(self):
        with Sandbox() as sb:
            store = sb.root / "store"
            holder = subprocess.Popen(
                [sys.executable, str(SCRIPT), "with-lock", "--data-dir", str(store), "--", "sleep", "4"],
                env=sb.env())
            try:
                lock = store / ".arc-auth.lock"
                for _ in range(50):
                    if lock.exists():
                        break
                    time.sleep(0.1)
                time.sleep(0.3)
                started = time.monotonic()
                waiter = _llm(sb, "with-lock", "--data-dir", str(store), "--timeout", "1", "--", "echo", "never")
                self.assertEqual(waiter.returncode, 75, waiter.stderr)
                self.assertNotIn("never", waiter.stdout)
                self.assertLess(time.monotonic() - started, 3.5)
                holder.wait(timeout=20)
                after = _llm(sb, "with-lock", "--data-dir", str(store), "--timeout", "5", "--", "echo", "ok")
                self.assertEqual((after.returncode, after.stdout.strip()), (0, "ok"))
                self.assertEqual(stat.S_IMODE(os.stat(store).st_mode), 0o700)
            finally:
                if holder.poll() is None:
                    holder.kill()

    def test_with_lock_passes_the_exit_code_through(self):
        with Sandbox() as sb:
            proc = _llm(sb, "with-lock", "--data-dir", str(sb.root / "s"), "--", "sh", "-c", "exit 7")
            self.assertEqual(proc.returncode, 7)

    def test_auth_status_absent(self):
        with Sandbox() as sb:
            proc = _llm(sb, "auth-status", "copilot", "--data-dir", str(sb.root / "s"))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("login copilot", proc.stdout)


# --------------------------------------------------------------------------- daily-sync.sh

SYNC_TOML = """\
[sync]
runner = "opencode"
model = "{model}"
api_key_env = ""
opencode_data_dir = "{store}"
daily_budget_eur = 0.5
{extra}
[notifications]
provider = "ntfy"
ntfy_topic = "test-topic"
"""


def _prime_opencode(sb: Sandbox) -> None:
    bin_dir = sb.home / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "opencode"
    target.write_text(f'#!/usr/bin/env bash\nexec "{STUB}" "$@"\n')
    target.chmod(0o755)


def _sync(sb: Sandbox, *args: str, **env):
    tokens = sb.root / "tokens"
    tokens.mkdir(exist_ok=True)
    return sb.script("daily-sync.sh", *args, GARMIN_TOKENS_DIR=str(tokens), **env)


def _curl(sb: Sandbox) -> list:
    return [a for _, a in sb.stub_calls("curl")]


class SyncSubscriptionTests(InstallAsserts):
    def _setup(self, sb: Sandbox, model="openai/gpt-5.4", connected=True, extra="", key_env=""):
        store = sb.root / "store"
        body = SYNC_TOML.format(model=model, store=store, extra=extra)
        body = body.replace('api_key_env = ""', 'api_key_env = "%s"' % key_env)
        (sb.repo / "config").mkdir(exist_ok=True)
        (sb.repo / "config/workspace.user.toml").write_text(body, encoding="utf-8")
        _prime_opencode(sb)
        if connected:
            _auth(store, "openai" if model.startswith("openai/") else "github-copilot")
        return store

    def test_run_uses_the_coach_store_and_the_lock_and_counts_no_euro(self):
        with Sandbox() as sb:
            store = self._setup(sb)
            proc = _sync(sb, ARC_STUB_OPENCODE_COST="0.9")
            self.assertSucceeded(proc)
            env_line = [a for _, a in sb.stub_calls("opencode") if a.startswith("env ")][0]
            self.assertIn("XDG_DATA_HOME=%s" % store, env_line)
            self.assertTrue(any("Sync OK (stub)" in c for c in _curl(sb)), _curl(sb))
            self.assertFalse((sb.repo / f"logs/.sync-spend-{TODAY}").exists())    # coût rapporté ignoré
            self.assertTrue((store / ".arc-auth.lock").exists())                    # exécuté sous with-lock
            self.assertEqual(stat.S_IMODE(os.stat(store).st_mode), 0o700)
            self.assertIn("forfait ChatGPT", proc.stdout + proc.stderr)

    def test_copilot_has_no_lock(self):
        with Sandbox() as sb:
            store = self._setup(sb, model="github-copilot/claude-sonnet-5.5")
            self.assertSucceeded(_sync(sb))
            self.assertFalse((store / ".arc-auth.lock").exists())
            env_line = [a for _, a in sb.stub_calls("opencode") if a.startswith("env ")][0]
            self.assertIn("XDG_DATA_HOME=%s" % store, env_line)

    def test_budget_never_blocks_a_subscription_run(self):
        with Sandbox() as sb:
            self._setup(sb)
            (sb.repo / "logs").mkdir(exist_ok=True)
            (sb.repo / f"logs/.sync-spend-{TODAY}").write_text("99\n")
            proc = _sync(sb)
            self.assertSucceeded(proc)
            self.assertTrue(sb.stub_calls("opencode"))

    def test_dry_run_says_subscription_and_hides_budget(self):
        with Sandbox() as sb:
            store = self._setup(sb)
            proc = _sync(sb, "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "abonnement ChatGPT")
            self.assertOutputContains(proc, "XDG_DATA_HOME=%s" % store)
            self.assertOutputContains(proc, "with-lock")
            self.assertOutputLacks(proc, "budget :")
            self.assertEqual(sb.stub_calls("opencode"), [])

    def test_missing_token_notifies_and_never_logs_in(self):
        with Sandbox() as sb:
            self._setup(sb, connected=False)
            proc = _sync(sb)
            self.assertFailed(proc)
            self.assertTrue(any("arc_llm.py login chatgpt" in c for c in _curl(sb)), _curl(sb))
            self.assertEqual(sb.stub_calls("opencode"), [])          # ni run ni `providers login`

    def test_unset_key_is_unchanged(self):
        """Sans [sync].opencode_data_dir : magasin global, coût compté, aucun verrou (non-régression)."""
        with Sandbox() as sb:
            body = ('[sync]\nrunner = "opencode"\nmodel = "openai/gpt-5.4"\napi_key_env = ""\n'
                    '[notifications]\nprovider = "ntfy"\nntfy_topic = "t"\n')
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text(body)
            _prime_opencode(sb)
            self.assertSucceeded(_sync(sb, ARC_STUB_OPENCODE_COST="0.5"))
            env_line = [a for _, a in sb.stub_calls("opencode") if a.startswith("env ")][0]
            self.assertIn("XDG_DATA_HOME=unset", env_line)
            self.assertAlmostEqual(float((sb.repo / f"logs/.sync-spend-{TODAY}").read_text()), 0.5 * 0.92, places=3)

    def test_api_key_mode_ignores_the_store(self):
        """Une clé API (même vers openai/…) n'est jamais un abonnement : le magasin reste inutilisé."""
        with Sandbox() as sb:
            self._setup(sb, key_env="OPENAI_API_KEY")
            llm_env = sb.home / ".config/ai-running-coach/llm.env"
            llm_env.parent.mkdir(parents=True, exist_ok=True)
            llm_env.write_text("OPENAI_API_KEY=sk-test-123\n")
            llm_env.chmod(0o600)
            self.assertSucceeded(_sync(sb, ARC_STUB_OPENCODE_COST="0.5"))
            env_line = [a for _, a in sb.stub_calls("opencode") if a.startswith("env ")][0]
            self.assertIn("XDG_DATA_HOME=unset", env_line)
            self.assertTrue((sb.repo / f"logs/.sync-spend-{TODAY}").exists())

    def _failing(self, sb: Sandbox, message: str, name: str = "APIError", status=None) -> subprocess.CompletedProcess:
        data = {"message": message}
        if status is not None:
            data["statusCode"] = status
        out = sb.root / "oc-out.jsonl"
        out.write_text(json.dumps({"type": "error", "error": {"name": name, "data": data}}) + "\n")
        return _sync(sb, ARC_STUB_OPENCODE_OUT=str(out), ARC_STUB_OPENCODE_RC="1")

    def test_provider_errors_become_actionable_notifications(self):
        cases = [
            ("Token refresh failed: 401", "econnectez-vous", "arc_llm.py login chatgpt"),
            ("usage_not_included: To use Codex with your ChatGPT plan, upgrade to Plus", "usage_not_included", "ChatGPT Plus ou Pro"),
            ("insufficient_quota: Quota exceeded. Check your plan", "limites de votre forfait", "renouvellent"),
        ]
        for message, *needles in cases:
            with Sandbox() as sb:
                self._setup(sb)
                self.assertFailed(self._failing(sb, message))
                joined = " ".join(_curl(sb))
                for needle in needles:
                    self.assertIn(needle, joined, message)
                self.assertNotIn("clé API", joined)

    def test_copilot_403_asks_to_reconnect(self):
        with Sandbox() as sb:
            self._setup(sb, model="github-copilot/claude-sonnet-5.5")
            self.assertFailed(self._failing(sb, "Forbidden", status=403))
            joined = " ".join(_curl(sb))
            self.assertIn("arc_llm.py login copilot", joined)

    def test_lock_timeout_postpones_without_failing(self):
        with Sandbox() as sb:
            store = self._setup(sb)
            holder = subprocess.Popen([sys.executable, str(SCRIPT), "with-lock", "--data-dir", str(store), "--", "sleep", "8"],
                                      env=sb.env())
            try:
                for _ in range(50):
                    if (store / ".arc-auth.lock").exists():
                        break
                    time.sleep(0.1)
                time.sleep(0.3)
                # attente ramenée à 1 s : le script lit la constante, on la surcharge par sed dans la copie
                script = sb.repo / "scripts/daily-sync.sh"
                script.write_text(script.read_text().replace("STORE_LOCK_WAIT_S=300", "STORE_LOCK_WAIT_S=1"))
                proc = _sync(sb)
                self.assertSucceeded(proc)
                self.assertTrue(any("reportée" in c for c in _curl(sb)), _curl(sb))
                self.assertEqual([a for _, a in sb.stub_calls("opencode") if a.startswith("env ")], [])
            finally:
                holder.kill()
                holder.wait(timeout=10)

    def test_headless_sync_never_calls_login(self):
        text = (REPO / "scripts/daily-sync.sh").read_text(encoding="utf-8")
        self.assertNotIn("providers login", text)
        self.assertNotIn("arc_llm.py\" login", text)
