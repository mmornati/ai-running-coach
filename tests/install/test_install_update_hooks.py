"""Palier A — ce qu'install.sh prépare pour les mises à jour : options mémorisées
(relues par scripts/update-coach.sh) et hook « nouvelle version » de Claude Code."""

from __future__ import annotations

import json

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

HOOK_SCRIPT = "scripts/arc_update_check.py"


def update_hooks(settings: dict) -> list:
    return [hook for entry in settings.get("hooks", {}).get("SessionStart", [])
            for hook in entry.get("hooks", []) if HOOK_SCRIPT in hook.get("command", "")]


class TestInstallArgs(InstallAsserts):
    def test_options_are_remembered_after_a_successful_install(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            args = (sb.home / ".config/ai-running-coach/install-args").read_text(encoding="utf-8")
            self.assertEqual(args.splitlines(), ["--ide", "claude"], "--no-auth ne se rejoue pas")

    def test_plain_rerun_keeps_remembered_options(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude", "--no-medical"))
            self.assertSucceeded(sb.install("--no-auth"))
            args = (sb.home / ".config/ai-running-coach/install-args").read_text(encoding="utf-8")
            self.assertEqual(args.splitlines(), ["--ide", "claude", "--no-medical"])

    def test_new_options_replace_remembered_ones(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertSucceeded(sb.install("--no-auth", "--ide", "opencode"))
            args = (sb.home / ".config/ai-running-coach/install-args").read_text(encoding="utf-8")
            self.assertEqual(args.splitlines(), ["--ide", "opencode"])

    def test_relative_paths_are_remembered_as_absolute(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude", "--workspace", "./ws-relatif",
                                            cwd=sb.home))
            args = (sb.home / ".config/ai-running-coach/install-args").read_text(encoding="utf-8")
            self.assertEqual(args.splitlines(), ["--ide", "claude", "--workspace", f"{sb.home}/ws-relatif"])

    def test_dry_run_remembers_nothing(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--dry-run"))
            self.assertFalse((sb.home / ".config/ai-running-coach/install-args").exists())


class TestClaudeUpdateHook(InstallAsserts):
    def test_hook_installed_once_and_user_hooks_kept(self):
        with Sandbox() as sb:
            settings_path = sb.repo / ".claude/settings.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            mine = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo bonjour"}]}
            settings_path.write_text(json.dumps({"hooks": {"SessionStart": [mine]}}), encoding="utf-8")

            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))   # idempotent

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn(mine, settings["hooks"]["SessionStart"], "hook de l'utilisateur perdu")
            hooks = update_hooks(settings)
            self.assertEqual(len(hooks), 1, settings)
            self.assertIn("--hook", hooks[0]["command"])
            self.assertIn(str(sb.repo), hooks[0]["command"])
