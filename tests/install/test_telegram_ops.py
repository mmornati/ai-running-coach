"""Palier A — bot Telegram (#174) : installation, service, diagnostic, résumé du daily-sync.

Dans le bac à sable, sans réseau : l'API Telegram est un faux serveur local
(`tests/lib/telegram_stub.py`), `systemctl`/`launchctl` sont des stubs, aucun vrai jeton.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox
from tests.lib.telegram_stub import FAKE_TOKEN, TelegramStub

BASE_FLAGS = ("--no-auth", "--ide", "claude", "--no-daily-sync", "--no-remote-control")


def _cfg(sb: Sandbox, section: str, key: str) -> str:
    proc = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get", "--workspace", str(sb.repo),
                   "--section", section, "--key", key, "--default", "<absent>"])
    return proc.stdout.strip()


def _user_toml(sb: Sandbox, body: str) -> None:
    (sb.repo / "config").mkdir(exist_ok=True)
    (sb.repo / "config/workspace.user.toml").write_text(body, encoding="utf-8")


def _token_file(sb: Sandbox, mode: int = 0o600, token: str = FAKE_TOKEN) -> Path:
    path = sb.home / ".config/ai-running-coach/telegram.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TELEGRAM_BOT_TOKEN={token}\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _doctor(sb: Sandbox, **env) -> dict:
    proc = sb.script("coach_doctor.py", "--json", "--check", "telegram", **env)
    assert proc.returncode in (0, 1), proc.stderr
    assert FAKE_TOKEN not in proc.stdout + proc.stderr, "le jeton ne doit jamais être affiché"
    return json.loads(proc.stdout)["checks"][0]


class TestInstallTelegram(InstallAsserts):
    def test_linux_installs_unit_config_and_token_stub(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE_FLAGS, "--telegram", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            unit = sb.home / ".config/systemd/user/ai-running-coach-telegram.service"
            self.assertIsFile(unit)
            self.assertFileContains(unit, "coach-telegram.sh run")
            self.assertFileLacks(unit, "TELEGRAM_BOT_TOKEN")
            self.assertFileLacks(unit, "EnvironmentFile")
            self.assertCalled(sb, "systemctl", "--user enable --now ai-running-coach-telegram")
            self.assertEqual(_cfg(sb, "telegram", "enabled"), "true")
            env_file = sb.home / ".config/ai-running-coach/telegram.env"
            self.assertIsFile(env_file)
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
            self.assertFileContains(env_file, "# TELEGRAM_BOT_TOKEN=")
            self.assertOutputContains(proc, "Jeton absent")
            self.assertOutputContains(proc, "allowed_chat_ids est vide")

    def test_macos_installs_a_launch_agent(self):
        with Sandbox() as sb:
            proc = sb.install(*BASE_FLAGS, "--telegram", ARC_FAKE_UNAME="Darwin")
            self.assertSucceeded(proc)
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.telegram.plist"
            self.assertIsFile(plist)
            self.assertFileContains(plist, "coach-telegram.sh")
            self.assertCalled(sb, "launchctl", "bootstrap")

    def test_no_service_without_the_flag(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE_FLAGS, ARC_FAKE_UNAME="Linux"))
            self.assertFalse((sb.home / ".config/systemd/user/ai-running-coach-telegram.service").exists())
            self.assertFalse((sb.home / ".config/ai-running-coach/telegram.env").exists())
            self.assertEqual(_cfg(sb, "telegram", "enabled"), "false")

    def test_rerun_is_idempotent_and_never_overwrites_user_config(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "123456", ARC_FAKE_UNAME="Linux"))
            token = _token_file(sb)
            _user_toml(sb, (sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8")
                       + '\n[notifications]\nntfy_topic = "mon-sujet-perso"\n')
            before = sb.tree(sb.home, sb.repo / "config")
            self.assertSucceeded(sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "123456", ARC_FAKE_UNAME="Linux"))
            after = sb.tree(sb.home, sb.repo / "config")
            for key in sorted(set(before) | set(after)):
                if key.endswith(("stub.log",)):
                    continue
                self.assertEqual(before.get(key), after.get(key), f"{key} modifié par un rerun")
            self.assertIn(FAKE_TOKEN, token.read_text(), "le jeton déjà posé n'est jamais touché")
            self.assertEqual(_cfg(sb, "notifications", "ntfy_topic"), "mon-sujet-perso")
            self.assertEqual(_cfg(sb, "telegram", "allowed_chat_ids"), "123456")

    def test_plain_rerun_without_flag_leaves_telegram_untouched(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "42", ARC_FAKE_UNAME="Linux"))
            before = (sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8")
            self.assertSucceeded(sb.install(*BASE_FLAGS, ARC_FAKE_UNAME="Linux"))
            self.assertEqual((sb.repo / "config/workspace.user.toml").read_text(encoding="utf-8"), before)

    def test_chat_id_is_appended_not_replaced(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "111", ARC_FAKE_UNAME="Linux"))
            self.assertSucceeded(sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "222", ARC_FAKE_UNAME="Linux"))
            self.assertEqual(_cfg(sb, "telegram", "allowed_chat_ids").split(), ["111", "222"])

    def test_no_secret_lands_in_any_written_file(self):
        with Sandbox() as sb:
            _token_file(sb)
            self.assertSucceeded(sb.install(*BASE_FLAGS, "--telegram", ARC_FAKE_UNAME="Linux"))
            token_path = sb.home / ".config/ai-running-coach/telegram.env"
            for root in (sb.home, sb.repo / "config"):
                for path in root.rglob("*"):
                    if path.is_file() and path != token_path:
                        self.assertNotIn(FAKE_TOKEN, path.read_text(encoding="utf-8", errors="replace"), str(path))

    def test_bad_chat_id_and_orphan_chat_id_fail_fast(self):
        with Sandbox() as sb:
            self.assertFailed(sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "abc"))
            self.assertFailed(sb.install(*BASE_FLAGS, "--telegram-chat-id", "123"), "sans --telegram")

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree(sb.home)
            proc = sb.install(*BASE_FLAGS, "--telegram", "--telegram-chat-id", "1", "--dry-run", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            self.assertEqual(sb.tree(sb.home), before)
            self.assertOutputContains(proc, "[dry-run]")
            self.assertEqual(_cfg(sb, "telegram", "enabled"), "false")


class TestCoachTelegramScript(InstallAsserts):
    def test_install_then_uninstall(self):
        for uname, unit_rel in (("Linux", ".config/systemd/user/ai-running-coach-telegram.service"),
                                ("Darwin", "Library/LaunchAgents/com.ai-running-coach.telegram.plist")):
            with self.subTest(uname=uname), Sandbox() as sb:
                self.assertSucceeded(sb.script("coach-telegram.sh", "install", ARC_FAKE_UNAME=uname))
                self.assertIsFile(sb.home / unit_rel)
                self.assertSucceeded(sb.script("coach-telegram.sh", "uninstall", ARC_FAKE_UNAME=uname))
                self.assertFalse((sb.home / unit_rel).exists())

    def test_dry_run_install_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree(sb.home)
            proc = sb.script("coach-telegram.sh", "--dry-run", "install", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            self.assertEqual(sb.tree(sb.home), before)

    def test_help_documents_usage(self):
        with Sandbox() as sb:
            proc = sb.script("coach-telegram.sh", "--help")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "coach-telegram.sh install")
            self.assertOutputContains(proc, "jamais dans\nle TOML")

    def test_run_refuses_to_start_unconfigured(self):
        with Sandbox() as sb:
            proc = sb.script("coach-telegram.sh", "run")
            self.assertFailed(proc)
            self.assertOutputContains(proc, "[telegram].enabled")


class TestDoctorTelegram(InstallAsserts):
    def test_disabled_is_info(self):
        with Sandbox() as sb:
            self.assertEqual(_doctor(sb)["status"], "info")

    def test_enabled_without_anything_warns_on_each_gap(self):
        with Sandbox() as sb:
            _user_toml(sb, "[telegram]\nenabled = true\n")
            check = _doctor(sb, ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["status"], "warning", "jamais error")
            for fragment in ("allowed_chat_ids est vide", "fichier du jeton absent", "aucun service installé"):
                self.assertIn(fragment, check["message"])

    def test_loose_token_permissions_are_flagged(self):
        with Sandbox() as sb:
            _user_toml(sb, '[telegram]\nenabled = true\nallowed_chat_ids = ["1"]\n')
            _token_file(sb, mode=0o644)
            check = _doctor(sb, ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["status"], "warning")
            self.assertIn("lisible par d'autres", check["message"])
            self.assertNotIn(FAKE_TOKEN, json.dumps(check))

    def test_malformed_token_is_flagged_without_echo(self):
        with Sandbox() as sb:
            _user_toml(sb, '[telegram]\nenabled = true\nallowed_chat_ids = ["1"]\n')
            _token_file(sb, token="n'importe-quoi-SECRETVALUE")
            check = _doctor(sb, ARC_FAKE_UNAME="Linux")
            self.assertIn("format inattendu", check["message"])
            self.assertNotIn("SECRETVALUE", json.dumps(check))

    def test_installed_but_silent_then_alive(self):
        with Sandbox() as sb:
            _user_toml(sb, '[telegram]\nenabled = true\nallowed_chat_ids = ["1"]\n')
            _token_file(sb)
            unit = sb.home / ".config/systemd/user/ai-running-coach-telegram.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("[Service]\n")
            check = _doctor(sb, ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["status"], "warning")
            self.assertIn("sans signe de vie", check["message"])
            beat = sb.repo / ".arc/telegram/heartbeat"
            beat.parent.mkdir(parents=True)
            beat.write_text("x")
            check = _doctor(sb, ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["status"], "ok", check)
            old = time.time() - 3600
            os.utime(beat, (old, old))
            self.assertEqual(_doctor(sb, ARC_FAKE_UNAME="Linux")["status"], "warning")

    def test_bridge_without_chat_is_flagged(self):
        with Sandbox() as sb:
            _user_toml(sb, '[telegram]\nenabled = true\nchat_bridge = true\nallowed_chat_ids = ["1"]\n')
            _token_file(sb)
            check = _doctor(sb, ARC_FAKE_UNAME="Linux")
            self.assertIn("[chat].enabled = false", check["message"])


class TestDailySyncSendsTelegramSummary(InstallAsserts):
    CONFIG = """\
[sync]
runner = "opencode"
model = "openrouter/deepseek/deepseek-v4.1-flash"
api_key_env = "OPENROUTER_API_KEY"

[notifications]
provider = "ntfy"
ntfy_topic = "test-topic"

[telegram]
enabled = true
allowed_chat_ids = ["4242"]
"""

    def _prepare(self, sb: Sandbox, extra: str = "") -> None:
        _user_toml(sb, self.CONFIG + extra)
        env = sb.home / ".config/ai-running-coach/llm.env"
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text("OPENROUTER_API_KEY=sk-test-not-real\n")
        env.chmod(0o600)
        _token_file(sb)
        bin_dir = sb.home / ".local/bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "opencode").write_text(f'#!/usr/bin/env bash\nexec "{STUBS_DIR / "opencode"}" "$@"\n')
        (bin_dir / "opencode").chmod(0o755)

    def _sync(self, sb: Sandbox, stub: TelegramStub):
        tokens = sb.root / "tokens"
        tokens.mkdir(exist_ok=True)
        return sb.script("daily-sync.sh", GARMIN_TOKENS_DIR=str(tokens), ARC_TELEGRAM_API_BASE=stub.base)

    def test_summary_goes_to_telegram_with_buttons_and_to_ntfy(self):
        with Sandbox() as sb, TelegramStub() as stub:
            self._prepare(sb)
            self.assertSucceeded(self._sync(sb, stub))
            sent = stub.sent()
            self.assertEqual(len(sent), 1, stub.calls)
            self.assertEqual(sent[0]["chat_id"], "4242")
            self.assertIn("Sync OK (stub)", sent[0]["text"])
            data = [b["callback_data"] for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
            self.assertTrue(any(d.startswith("pn:") for d in data), data)
            self.assertTrue(any("Sync OK (stub)" in args for _, args in sb.stub_calls("curl")), "ntfy intact")

    def test_telegram_failure_never_fails_the_sync(self):
        with Sandbox() as sb, TelegramStub() as stub:
            self._prepare(sb)
            stub.fail_next["sendMessage"] = (500, "boom", None)
            proc = self._sync(sb, stub)
            self.assertSucceeded(proc)
            self.assertTrue(any("Sync OK (stub)" in args for _, args in sb.stub_calls("curl")))

    def test_disabled_by_default_sends_nothing(self):
        with Sandbox() as sb, TelegramStub() as stub:
            self._prepare(sb)
            _user_toml(sb, self.CONFIG.replace("enabled = true", "enabled = false"))
            self.assertSucceeded(self._sync(sb, stub))
            self.assertEqual(stub.calls, [])

    def test_send_summary_flag_off(self):
        with Sandbox() as sb, TelegramStub() as stub:
            self._prepare(sb)
            _user_toml(sb, self.CONFIG + "send_summary = false\n")
            self.assertSucceeded(self._sync(sb, stub))
            self.assertEqual(stub.calls, [])
