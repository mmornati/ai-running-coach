"""Palier A — conversation Telegram sur abonnement (Claude Code Channels, #337),
scripts/coach-telegram-chat.sh et check `telegram_chat` du doctor.

Aucun vrai jeton, aucun réseau : `claude`, `bun`, `tmux`, `systemctl`, `launchctl` sont des stubs.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

PLUGIN_TOKEN = "111111:PLUGIN-secret-AAAAAAAAAAAAAAAAAAAA"
BOT_TOKEN = "222222:BOT-secret-BBBBBBBBBBBBBBBBBBBBBBB"
SECRETS = (PLUGIN_TOKEN, BOT_TOKEN, "PLUGIN-secret", "BOT-secret")

# Un jeton présent dans l'environnement du contributeur fausserait les cas « sans jeton ».
NO_ENV_TOKEN = {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_STATE_DIR": "", "ANTHROPIC_API_KEY": ""}


def _telegram_state(sb: Sandbox, allow_from=("4242",), policy="allowlist", token=PLUGIN_TOKEN) -> Path:
    """État du plugin Telegram tel que l'écrivent /telegram:configure et /telegram:access."""
    state = sb.home / ".claude/channels/telegram"
    state.mkdir(parents=True, exist_ok=True)
    if token:
        (state / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
    if allow_from is not None:
        (state / "access.json").write_text(json.dumps({"dmPolicy": policy, "allowFrom": list(allow_from)}))
    return state


def _bot_token_file(sb: Sandbox, token: str = BOT_TOKEN) -> Path:
    """Fichier du jeton du bot « un geste » ([telegram].token_file par défaut)."""
    path = sb.home / ".config/ai-running-coach/telegram.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
    path.chmod(0o600)
    return path


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in sorted(root.rglob("*")) if p.is_file()}


class TestCoachTelegramChat(InstallAsserts):
    def _no_secret(self, proc) -> None:
        for secret in SECRETS:
            self.assertNotIn(secret, proc.stdout + proc.stderr, "un jeton ne doit jamais être affiché")

    def test_refuses_to_start_unless_allowlisted(self):
        with Sandbox() as sb:
            _telegram_state(sb, policy="pairing")
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run", **NO_ENV_TOKEN)
            self.assertFailed(proc, "politique pairing")
            self.assertOutputContains(proc, "allowlist")

    def test_pairing_mode_starts_the_channel(self):
        with Sandbox() as sb:
            _telegram_state(sb, allow_from=None)
            proc = sb.script("coach-telegram-chat.sh", "run", "--pairing", "--dry-run", **NO_ENV_TOKEN)
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "--channels plugin:telegram@claude-plugins-official")
            self.assertOutputContains(proc, "expérimental")

    def test_refuses_leanproxy_mode(self):
        """mcp__leanproxy__* porterait aussi les suppressions interdites depuis Telegram."""
        with Sandbox() as sb:
            _telegram_state(sb)
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"leanproxy": {"command": "x"}}}))
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run", **NO_ENV_TOKEN)
            self.assertFailed(proc, "mode leanproxy")
            self.assertOutputContains(proc, "leanproxy")

    def test_refuses_an_api_key(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run",
                             **{**NO_ENV_TOKEN, "ANTHROPIC_API_KEY": "sk-test"})
            self.assertFailed(proc, "clé d'API définie")
            self.assertOutputContains(proc, "ANTHROPIC_API_KEY")
            self.assertNotIn("sk-test", proc.stdout + proc.stderr)

    def test_refuses_an_unknown_permission_mode(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            (sb.repo / "config/workspace.user.toml").write_text('[telegram_chat]\npermission_mode = "bypassPermissions"\n')
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run", **NO_ENV_TOKEN)
            self.assertFailed(proc, "bypassPermissions")
            self.assertOutputContains(proc, "permission_mode invalide")

    # -- bot distinct ---------------------------------------------------------
    def test_refuses_the_same_bot_token_as_the_one_gesture_bot(self):
        """Deux processus en long polling sur le même bot : erreur 409. Refus net, sans afficher de jeton."""
        with Sandbox() as sb:
            _telegram_state(sb, token=BOT_TOKEN)
            _bot_token_file(sb, BOT_TOKEN)
            for action in (("run", "--dry-run"), ("install", "--dry-run")):
                proc = sb.script("coach-telegram-chat.sh", *action, **NO_ENV_TOKEN, ARC_FAKE_UNAME="Linux")
                self.assertFailed(proc, "jeton identique")
                self.assertOutputContains(proc, "409")
                self.assertOutputContains(proc, "BotFather")
                self._no_secret(proc)

    def test_refuses_the_same_token_exported_in_the_environment(self):
        with Sandbox() as sb:
            _telegram_state(sb, token=None)
            _bot_token_file(sb, BOT_TOKEN)
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run",
                             **{**NO_ENV_TOKEN, "TELEGRAM_BOT_TOKEN": BOT_TOKEN})
            self.assertFailed(proc, "jeton exporté identique")
            self.assertOutputContains(proc, "409")
            self._no_secret(proc)

    def test_honours_a_custom_token_file_with_a_tilde(self):
        with Sandbox() as sb:
            _telegram_state(sb, token=BOT_TOKEN)
            custom = sb.home / "secrets/bot.env"
            custom.parent.mkdir()
            custom.write_text(f"export TELEGRAM_BOT_TOKEN='{BOT_TOKEN}'\n")
            (sb.repo / "config/workspace.user.toml").write_text('[telegram]\ntoken_file = "~/secrets/bot.env"\n')
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run", **NO_ENV_TOKEN)
            self.assertFailed(proc, "jeton identique via un fichier personnalisé")
            self._no_secret(proc)

    def test_distinct_tokens_start_normally(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            _bot_token_file(sb)
            proc = sb.script("coach-telegram-chat.sh", "run", "--dry-run", **NO_ENV_TOKEN)
            self.assertSucceeded(proc)
            self._no_secret(proc)

    # -- permissions ------------------------------------------------------------
    def test_install_merges_permissions_without_losing_existing_rules(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            settings = sb.repo / ".claude/settings.local.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))
            proc = sb.script("coach-telegram-chat.sh", "install", **NO_ENV_TOKEN, ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            perms = json.loads(settings.read_text())["permissions"]
            allow, ask, deny = perms["allow"], perms["ask"], perms["deny"]
            self.assertIn("Bash(ls:*)", allow)
            self.assertIn("mcp__garmin__get_sleep_data", allow)
            self.assertIn("mcp__garmin__schedule_workouts", ask)
            self.assertNotIn("mcp__garmin__schedule_workouts", allow)
            self.assertIn("mcp__garmin__delete_workout", deny)
            self.assertFalse(set(allow) & set(deny), "règle à la fois autorisée et interdite")
            self.assertFalse(set(allow) & set(ask), "règle à la fois autorisée et soumise à approbation")
            hooks = json.loads(settings.read_text())["hooks"]["PreToolUse"]
            self.assertEqual(len(hooks), 1)
            self.assertIn("arc_telegram_hook.py", hooks[0]["hooks"][0]["command"])
            # Idempotent : un second install n'ajoute ni règle ni hook.
            self.assertSucceeded(sb.script("coach-telegram-chat.sh", "install", **NO_ENV_TOKEN, ARC_FAKE_UNAME="Linux"))
            again = json.loads(settings.read_text())
            self.assertEqual(again["permissions"]["allow"], allow)
            self.assertEqual(len(again["hooks"]["PreToolUse"]), 1)

    # -- services ----------------------------------------------------------------
    def test_linux_install_writes_a_systemd_unit_on_a_dedicated_tmux_socket(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            proc = sb.script("coach-telegram-chat.sh", "install", **NO_ENV_TOKEN, ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            unit = sb.home / ".config/systemd/user/ai-running-coach-telegram-chat.service"
            self.assertIsFile(unit)
            self.assertFileContains(unit, "-L coach-telegram-chat new-session")
            self.assertFileLacks(unit, "TELEGRAM_BOT_TOKEN")
            self.assertIsFile(sb.home / ".config/systemd/user/ai-running-coach-telegram-chat-restart.timer")
            self.assertCalled(sb, "systemctl", "--user enable --now ai-running-coach-telegram-chat")
            self.assertCalled(sb, "loginctl", "enable-linger")
            # Le service du bot « un geste » n'est jamais touché.
            self.assertFalse((sb.home / ".config/systemd/user/ai-running-coach-telegram.service").exists())

    def test_macos_install_writes_a_launch_agent(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            proc = sb.script("coach-telegram-chat.sh", "install", **NO_ENV_TOKEN, ARC_FAKE_UNAME="Darwin")
            self.assertSucceeded(proc)
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.telegram-chat.plist"
            self.assertIsFile(plist)
            self.assertFileContains(plist, "coach-telegram-chat.sh")
            self.assertFileContains(plist, "AbandonProcessGroup")
            self.assertCalled(sb, "launchctl", "bootstrap")

    def test_uninstall_removes_the_service_files(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            self.assertSucceeded(sb.script("coach-telegram-chat.sh", "install", **NO_ENV_TOKEN, ARC_FAKE_UNAME="Linux"))
            self.assertSucceeded(sb.script("coach-telegram-chat.sh", "uninstall", **NO_ENV_TOKEN, ARC_FAKE_UNAME="Linux"))
            self.assertFalse((sb.home / ".config/systemd/user/ai-running-coach-telegram-chat.service").exists())

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            for uname in ("Linux", "Darwin"):
                before = (_tree(sb.home), _tree(sb.repo))
                calls_before = len(sb.stub_calls())
                proc = sb.script("coach-telegram-chat.sh", "--dry-run", "install", **NO_ENV_TOKEN, ARC_FAKE_UNAME=uname)
                self.assertSucceeded(proc)
                self.assertOutputContains(proc, "[dry-run]")
                self.assertEqual(before, (_tree(sb.home), _tree(sb.repo)), f"--dry-run a écrit des fichiers ({uname})")
                self.assertFalse((sb.repo / ".claude/settings.local.json").exists())
                self.assertFalse((sb.repo / "logs").exists())
                mutating = [c for c in sb.stub_calls()[calls_before:]
                            if c[0] in ("systemctl", "launchctl", "loginctl", "tmux")
                            and not c[1].startswith(("--user show-environment", "--user is-active", "-L coach-telegram-chat has-session"))]
                self.assertEqual(mutating, [], "--dry-run ne doit lancer aucun service")


class TestDoctorTelegramChat(InstallAsserts):
    def _check(self, sb: Sandbox, **env) -> dict:
        proc = sb.script("coach_doctor.py", "--json", "--check", "telegram_chat", **{**NO_ENV_TOKEN, **env})
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        for secret in SECRETS:
            self.assertNotIn(secret, proc.stdout + proc.stderr, "un jeton ne doit jamais être affiché")
        return json.loads(proc.stdout)["checks"][0]

    def _unit(self, sb: Sandbox) -> None:
        unit = sb.home / ".config/systemd/user/ai-running-coach-telegram-chat.service"
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text("[Unit]\n")

    def _live_tmux(self, sb: Sandbox) -> str:
        """Un faux `tmux` dont la session existe : en tête de PATH pour le doctor."""
        bindir = sb.root / "livebin"
        bindir.mkdir(exist_ok=True)
        fake = bindir / "tmux"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        return f"{bindir}:{os.environ.get('PATH', '')}"

    def test_not_installed_is_informational(self):
        with Sandbox() as sb:
            check = self._check(sb, ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["id"], "telegram_chat")
            self.assertEqual(check["status"], "info")
            self.assertIn("coach-telegram-chat.sh install", check["fix"])

    def test_healthy_setup_is_ok(self):
        with Sandbox() as sb:
            _telegram_state(sb)
            _bot_token_file(sb)
            self._unit(sb)
            check = self._check(sb, ARC_FAKE_UNAME="Linux", PATH=self._live_tmux(sb))
            self.assertEqual(check["status"], "ok", check["message"])

    def test_same_token_is_flagged_without_showing_it(self):
        with Sandbox() as sb:
            _telegram_state(sb, token=BOT_TOKEN)
            _bot_token_file(sb, BOT_TOKEN)
            self._unit(sb)
            check = self._check(sb, ARC_FAKE_UNAME="Linux", PATH=self._live_tmux(sb))
            self.assertEqual(check["status"], "warning")
            self.assertIn("409", check["message"])
            self.assertIn("BotFather", check["message"])

    def test_pairing_policy_and_missing_session_are_flagged(self):
        with Sandbox() as sb:
            _telegram_state(sb, policy="pairing")
            self._unit(sb)
            check = self._check(sb, ARC_FAKE_UNAME="Linux")      # stub tmux : aucune session
            self.assertEqual(check["status"], "warning")
            self.assertIn("allowlist", check["message"])
            self.assertIn("session tmux absente", check["message"])

    def test_missing_plugin_token_is_flagged(self):
        with Sandbox() as sb:
            _telegram_state(sb, token=None)
            self._unit(sb)
            check = self._check(sb, ARC_FAKE_UNAME="Linux", PATH=self._live_tmux(sb))
            self.assertEqual(check["status"], "warning")
            self.assertIn("plugin Telegram non configuré", check["message"])

    def test_missing_prerequisites_are_flagged(self):
        # Le doctor cherche aussi dans /opt/homebrew/bin, /usr/local/bin et ~/.local/bin : sur une machine
        # qui y a l'un de ces outils, « introuvable » ne peut pas être provoqué depuis le bac à sable.
        present = [t for t in ("claude", "bun", "tmux")
                   if any(os.access(os.path.join(d, t), os.X_OK) for d in ("/opt/homebrew/bin", "/usr/local/bin"))]
        if present:
            self.skipTest(f"{', '.join(present)} installé hors PATH (le doctor y cherche aussi)")
        with Sandbox() as sb:
            _telegram_state(sb)
            self._unit(sb)
            check = self._check(sb, ARC_FAKE_UNAME="Linux", PATH=str(sb.isolated_bin(("claude", "bun", "tmux"))))
            self.assertEqual(check["status"], "warning")
            for tool in ("claude", "bun", "tmux"):
                self.assertIn(f"{tool} introuvable", check["message"])
