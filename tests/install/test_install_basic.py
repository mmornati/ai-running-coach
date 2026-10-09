"""Palier A — installation nominale, idempotence, dry-run."""

from __future__ import annotations

import json

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

IDE_CONFIGS = [
    ".mcp.json",
    ".gemini/settings.json",
    ".cursor/mcp.json",
    ".cursor/cli.json",
    ".windsurf/mcp_config.json",
]
WORK_DIRS = ["activities", "medical", "nutrition", "planning", "rapports", "resources", "gear"]


class TestFreshInstall(InstallAsserts):
    def test_fresh_install(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth")
            self.assertSucceeded(proc, "install.sh --no-auth")

            for rel in IDE_CONFIGS:
                self.assertIsFile(sb.repo / rel)
            self.assertIsFile(sb.home / ".config/opencode/opencode.json")
            self.assertIsFile(sb.repo / "config/workspace.user.toml")

            for name in WORK_DIRS:
                self.assertTrue((sb.repo / name).is_dir(), f"{name}/ manquant")

            self.assertPopulated(sb.repo / ".claude/agents", minimum=4)
            self.assertPopulated(sb.repo / ".claude/skills", minimum=9)
            self.assertPopulated(sb.repo / ".github/agents", minimum=4)
            self.assertPopulated(sb.repo / ".opencode/agents", minimum=4)
            self.assertPopulated(sb.repo / ".gemini/commands", minimum=3)

    def test_mcp_server_approved_for_claude(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            projects = sb.claude_json().get("projects", {})
            self.assertIn(str(sb.repo), projects, f"projet absent de ~/.claude.json : {projects}")
            self.assertIn("garmin", projects[str(sb.repo)].get("enabledMcpjsonServers", []))

    def test_garmin_auth_runs_when_no_tokens(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install())
            self.assertCalled(sb, "uv", "run garmin-mcp-auth")

    def test_explicit_sync_runner_is_persisted(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--daily-sync", "--sync-runner", "gemini", ARC_FAKE_UNAME="Darwin")
            self.assertSucceeded(proc)
            config = (sb.repo / "config/workspace.user.toml").read_text()
            self.assertIn('[sync]', config)
            self.assertIn('runner = "gemini"', config)

    def test_cursor_headless_permissions_protect_the_engine(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "cursor"))
            permissions = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]
            self.assertIn("Write(activities/**)", permissions["allow"])
            self.assertIn("Write(scripts/**)", permissions["deny"])
            self.assertIn("Write(.mcp.json)", permissions["deny"])

    def test_cursor_permissions_deny_remote_writes_of_the_source(self):
        """La synchro headless lance `cursor-agent --force` : les écritures distantes doivent être refusées."""
        for args, server, tool in (((), "garmin", "schedule_workouts"),
                                   (("--source", "intervals"), "intervals", "icu_create_event"),
                                   (("--source", "strava"), "strava", "star-segment")):
            with self.subTest(server=server), Sandbox() as sb:
                self.assertSucceeded(sb.install("--no-auth", "--ide", "cursor", *args))
                permissions = json.loads((sb.repo / ".cursor/cli.json").read_text())["permissions"]
                self.assertIn(f"Mcp({server}:{tool})", permissions["deny"])

    def test_cursor_permissions_keep_user_rules(self):
        """Une réinstallation complète les listes allow/deny, sans effacer les règles de l'utilisateur."""
        with Sandbox() as sb:
            (sb.repo / ".cursor").mkdir()
            (sb.repo / ".cursor/cli.json").write_text(json.dumps({
                "editor": {"vimMode": True},
                "permissions": {"allow": ["Shell(ls)"], "deny": ["Shell(curl)"]},
            }))
            self.assertSucceeded(sb.install("--no-auth", "--ide", "cursor"))
            data = json.loads((sb.repo / ".cursor/cli.json").read_text())
            self.assertEqual(data["editor"], {"vimMode": True})
            self.assertIn("Shell(ls)", data["permissions"]["allow"])
            self.assertIn("Shell(curl)", data["permissions"]["deny"])
            self.assertIn("Write(activities/**)", data["permissions"]["allow"])
            self.assertIn("Write(scripts/**)", data["permissions"]["deny"])


class TestIdempotency(InstallAsserts):
    def test_second_run_changes_nothing(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth"), "premier passage")
            before = sb.tree()
            self.assertSucceeded(sb.install("--no-auth"), "second passage")
            after = sb.tree()
            self.assertTreeUnchanged(before, after, "une seconde installation a modifié l'arbre")


class TestDryRun(InstallAsserts):
    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree()
            proc = sb.install("--dry-run", "--no-auth")
            self.assertSucceeded(proc, "install.sh --dry-run")
            self.assertTreeUnchanged(before, sb.tree(), "--dry-run a écrit sur le disque")

    def test_dry_run_leanproxy_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree()
            proc = sb.install("--dry-run", "--no-auth", "--use-leanproxy")
            self.assertSucceeded(proc)
            self.assertTreeUnchanged(before, sb.tree(), "--dry-run --use-leanproxy a écrit sur le disque")

    def test_dry_run_does_not_claim_verified_tokens(self):
        """Le contrôle de tokens renvoie 0 en dry-run : ne pas prétendre l'avoir vérifié."""
        with Sandbox() as sb:
            (sb.home / ".garminconnect").mkdir()
            (sb.home / ".garminconnect/garmin_tokens.json").write_text("{}")
            proc = sb.install("--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputLacks(proc, "Tokens Garmin valides (vérifiés)")
