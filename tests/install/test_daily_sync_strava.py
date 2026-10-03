"""Palier A — `daily-sync.sh` et politique du chat avec `[data].source = "strava"` (#164).

Le run non surveillé lit Strava mais n'agit jamais : `connect-strava` (navigateur + port local),
`disconnect-strava` (efface les jetons) et `star-segment` (écriture) sont interdits.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from arc_chat_policy import Policy  # noqa: E402

ACTING_TOOLS = ("connect-strava", "disconnect-strava", "star-segment")


class TestStravaHeadless(InstallAsserts):
    def _workspace(self, sb: Sandbox, source: str) -> Path:
        ws = sb.root / "workspace"
        (ws / "config").mkdir(parents=True)
        (ws / "logs").mkdir()
        (ws / "config/workspace.user.toml").write_text(
            f'[sync]\nrunner = "claude"\n\n[notifications]\nprovider = "none"\n\n[data]\nsource = "{source}"\n')
        return ws

    def test_strava_server_allowed_and_acting_tools_forbidden(self):
        with Sandbox() as sb:
            proc = sb.script("daily-sync.sh", "--dry-run", ARC_WORKSPACE=str(self._workspace(sb, "strava")))
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "mcp__strava")
            self.assertOutputContains(proc, "--disallowedTools")
            for tool in ACTING_TOOLS:
                self.assertOutputContains(proc, f"mcp__strava__{tool}")
            for other in ("mcp__garmin", "mcp__intervals", "mcp__leanproxy"):
                self.assertOutputLacks(proc, other)
            self.assertOutputContains(proc, "Synchronisation Strava")

    def test_python_hardening_is_kept(self):
        with Sandbox() as sb:
            proc = sb.script("daily-sync.sh", "--dry-run", ARC_WORKSPACE=str(self._workspace(sb, "strava")))
            self.assertOutputLacks(proc, "Bash(python3:*)")
            for rule in ("Edit(scripts/**)", "Edit(.mcp.json)", "Bash(python3 scripts/*)"):
                self.assertOutputContains(proc, rule)

    def test_opencode_config_denies_the_acting_tools(self):
        with Sandbox() as sb:
            ws = self._workspace(sb, "strava")
            (ws / ".mcp.json").write_text(json.dumps(
                {"mcpServers": {"strava": {"command": "/x/run.sh", "args": []}}}))
            (ws / "config/workspace.user.toml").write_text(
                '[sync]\nrunner = "opencode"\nmodel = "openrouter/x/y"\n\n[notifications]\nprovider = "none"\n\n'
                '[data]\nsource = "strava"\n')
            proc = sb.script("daily-sync.sh", "--dry-run", ARC_WORKSPACE=str(ws))
            self.assertSucceeded(proc)
            for tool in ACTING_TOOLS:
                self.assertOutputContains(proc, f'"strava_{tool}": "deny"')


class TestStravaChatPolicy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ws = Path(self._tmp.name).resolve()
        self.policy = Policy.load(REPO, ws)

    def test_read_tools_are_allowed(self):
        for tool in ("get-recent-activities", "get-activity-streams", "get-athlete-zones",
                     "check-strava-connection", "list-athlete-clubs"):
            self.assertEqual(self.policy.decide(f"mcp:strava.{tool}", {}), "allow", tool)

    def test_acting_tools_always_ask(self):
        for tool in ACTING_TOOLS:
            self.assertEqual(self.policy.decide(f"mcp:strava.{tool}", {}), "ask", tool)

    def test_unknown_strava_tool_asks_and_unknown_server_is_denied(self):
        self.assertEqual(self.policy.decide("mcp:strava.something-new", {}), "ask")
        self.assertEqual(self.policy.decide("mcp:strava2.get-x", {}), "deny")

    def test_existing_garmin_decisions_unchanged(self):
        self.assertEqual(self.policy.decide("mcp:garmin.get_rhr_day", {}), "allow")
        self.assertEqual(self.policy.decide("mcp:garmin.schedule_workouts", {}), "ask")
        self.assertEqual(self.policy.decide("mcp:intervals.get_wellness_for_date", {}), "allow")


if __name__ == "__main__":
    unittest.main()
