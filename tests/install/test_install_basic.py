"""Palier A — installation nominale, idempotence, dry-run."""

from __future__ import annotations

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

IDE_CONFIGS = [
    ".mcp.json",
    ".cursor/mcp.json",
    ".windsurf/mcp_config.json",
]
WORK_DIRS = ["activities", "medical", "nutrition", "planning", "rapports", "resources"]


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
