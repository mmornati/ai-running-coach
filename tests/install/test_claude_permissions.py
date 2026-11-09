"""`coach_config.py set-claude-permissions` : pré-autorisations de Claude Code interactif."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts/coach_config.py"


def run(path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "set-claude-permissions", "--file", str(path), *extra],
                          capture_output=True, text=True)


class TestClaudePermissions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "settings.json"

    def perms(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))["permissions"]

    def test_default_allows_reads_and_asks_for_writes(self):
        self.assertEqual(run(self.path).returncode, 0)
        p = self.perms()
        self.assertIn("mcp__garmin__get_*", p["allow"])
        self.assertIn("mcp__leanproxy__garmin__get_*", p["allow"])
        self.assertIn("WebSearch", p["allow"])
        self.assertIn("mcp__garmin__schedule_*", p["ask"])
        self.assertNotIn("mcp__garmin__schedule_*", p["allow"])

    def test_deletes_downloads_and_script_writes_always_ask(self):
        for mode in ("ask", "allow"):
            with self.subTest(mode=mode):
                run(self.path, "--remote-writes", mode)
                p = self.perms()
                for rule in ("mcp__garmin__delete_*", "mcp__garmin__download_*", "mcp__strava__disconnect-strava",
                             "Bash(python3 scripts/arc_index.py *--write*)"):
                    self.assertIn(rule, p["ask"])
                    self.assertNotIn(rule, p["allow"])

    def test_no_read_rule_matches_a_write_tool(self):
        run(self.path, "--remote-writes", "allow")
        for rule in self.perms()["allow"]:
            if rule.startswith("mcp__") and ("get_" in rule or "query" in rule or "list_" in rule or "search_" in rule):
                self.assertNotRegex(rule, r"(schedule|upload|create|delete|update|add_)")

    def test_switching_mode_leaves_nothing_behind_and_keeps_user_rules(self):
        self.path.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"], "deny": ["Read(.env)"]}, "x": 1}),
                             encoding="utf-8")
        run(self.path, "--remote-writes", "allow")
        self.assertIn("mcp__garmin__schedule_*", self.perms()["allow"])
        run(self.path)
        p = self.perms()
        self.assertNotIn("mcp__garmin__schedule_*", p["allow"])
        self.assertIn("mcp__garmin__schedule_*", p["ask"])
        self.assertIn("Bash(ls)", p["allow"])
        self.assertEqual(p["deny"], ["Read(.env)", "Bash(python3 *..*)"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["x"], 1)

    def test_idempotent(self):
        run(self.path)
        out = run(self.path)
        self.assertIn("inchangé", out.stdout)

    def test_web_domains_mode_uses_the_policy_domain_list(self):
        run(self.path, "--web", "domains")
        allow = self.perms()["allow"]
        self.assertNotIn("WebFetch", allow)
        self.assertIn("WebSearch", allow)
        self.assertIn("WebFetch(domain:wttr.in)", allow)

    def test_script_rules_are_exact_and_traversal_is_denied(self):
        """Edit sur les dossiers de données + joker de scripts = exécution de code écrit par le modèle."""
        run(self.path)
        p = self.perms()
        bash = [r for r in p["allow"] if r.startswith("Bash(")]
        self.assertIn("Bash(python3 scripts/arc_index.py *)", bash)
        self.assertFalse([r for r in bash if "*.py" in r or "/*/" in r], bash)
        self.assertIn("Bash(python3 *..*)", p["deny"])

    def test_ask_flag_scripts_reject_option_abbreviations(self):
        """`--wr` ne doit pas contourner la règle ask `*--write*` : abréviations argparse interdites."""
        for script in ("arc_index.py", "arc_race_debrief.py", "garmin_gear_backfill.py"):
            with self.subTest(script=script):
                text = (REPO / "scripts" / script).read_text(encoding="utf-8")
                self.assertIn("allow_abbrev=False", text)

    def test_invalid_values_are_refused(self):
        self.assertNotEqual(run(self.path, "--remote-writes", "yes").returncode, 0)


if __name__ == "__main__":
    unittest.main()
