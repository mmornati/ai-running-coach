"""Palier A — `coach_doctor.py` : check `coros_connection` (montre COROS, `./install.sh --coros`).

Statique : relais déclaré dans .mcp.json, pas masqué par une entrée `coros` ajoutée à la main dans
Claude Code (portée locale), jetons du projet avec jeton de rafraîchissement, droits 700/600. Les
valeurs de jetons sont factices et ne doivent JAMAIS apparaître dans la sortie.
"""

from __future__ import annotations

import json
import os
import time

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

SECRETS = ("FAKE-COROS-ACCESS", "FAKE-COROS-REFRESH")


def _setup(sb, *, relay=True, mcp=True, tokens=True, refresh=True, mode=0o600, local_override=False):
    (sb.repo / "config").mkdir(exist_ok=True)
    (sb.repo / "config/workspace.user.toml").write_text(
        '[data]\nsource = "intervals"\n' + ('\n[coros]\nmcp = "relay"\n' if relay else ""))
    if mcp:
        (sb.repo / ".mcp.json").write_text(json.dumps(
            {"mcpServers": {"coros": {"command": str(sb.repo / "scripts/arc_coros_mcp.py"), "args": []}}}))
    if local_override:
        (sb.home / ".claude.json").write_text(json.dumps(
            {"projects": {str(sb.repo): {"mcpServers": {"coros": {"type": "http", "url": "https://mcpeu.coros.com/mcp"}}}}}))
    if tokens:
        d = sb.home / ".config/ai-running-coach/coros"
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        (d / "client.json").write_text('{"client_id": "x"}')
        tok = {"access_token": "FAKE-COROS-ACCESS", "expires_at": int(time.time()) + 20 * 86400}
        if refresh:
            tok["refresh_token"] = "FAKE-COROS-REFRESH"
        (d / "tokens.json").write_text(json.dumps(tok))
        for f in ("client.json", "tokens.json"):
            os.chmod(d / f, mode)


class TestCorosSourceDoctor(InstallAsserts):
    """`[data].source = "coros"` (#168) : relais obligatoire, contrôles Garmin non applicables."""

    def _payload(self, sb, *checks):
        args = ["--json", "--workspace", str(sb.repo), "--tokens-dir", str(sb.root / "tokens-absent")]
        for check in checks:
            args += ["--check", check]
        proc = sb.script("coach_doctor.py", *args)
        for secret in SECRETS:
            self.assertNotIn(secret, proc.stdout + proc.stderr)
        return {c["id"]: c for c in json.loads(proc.stdout)["checks"]}

    def test_source_coros_without_relay_is_an_error(self):
        with Sandbox() as sb:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text('[data]\nsource = "coros"\n')
            check = self._payload(sb, "coros_connection")["coros_connection"]
            self.assertEqual(check["status"], "error")
            self.assertEqual(check["fix"], "./install.sh --source coros")

    def test_garmin_checks_are_info_and_fit_reader_points_to_coros(self):
        with Sandbox() as sb:
            _setup(sb)
            (sb.repo / "config/workspace.user.toml").write_text('[data]\nsource = "coros"\n\n[coros]\nmcp = "relay"\n')
            checks = self._payload(sb)
            for check_id in ("garmin_token", "garmin_mcp", "gear_sync", "gear_history"):
                self.assertEqual(checks[check_id]["status"], "info", check_id)
            self.assertEqual(checks["coros_connection"]["status"], "ok", checks["coros_connection"])
            self.assertEqual(checks["fit_reader"]["status"], "warning")
            self.assertEqual(checks["fit_reader"]["fix"], "./install.sh --source coros")


class TestCorosConnection(InstallAsserts):
    def _check(self, sb):
        proc = sb.script("coach_doctor.py", "--json", "--workspace", str(sb.repo),
                         "--tokens-dir", str(sb.root / "tokens-absent"), "--check", "coros_connection")
        for secret in SECRETS:
            self.assertNotIn(secret, proc.stdout + proc.stderr)
        return next(c for c in json.loads(proc.stdout)["checks"] if c["id"] == "coros_connection")

    def test_info_without_relay(self):
        with Sandbox() as sb:
            _setup(sb, relay=False, mcp=False, tokens=False)
            self.assertEqual(self._check(sb)["status"], "info")

    def test_ok_when_connected(self):
        with Sandbox() as sb:
            _setup(sb)
            check = self._check(sb)
            self.assertEqual(check["status"], "ok", check)
            self.assertIn("valable", check["message"])

    def test_relay_missing_from_mcp_json(self):
        with Sandbox() as sb:
            _setup(sb, mcp=False)
            check = self._check(sb)
            self.assertEqual(check["status"], "error")
            self.assertEqual(check["fix"], "./install.sh --coros")

    def test_hand_added_server_masks_the_relay(self):
        with Sandbox() as sb:
            _setup(sb, local_override=True)
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("claude mcp remove coros", check["fix"])

    def test_not_connected_and_no_refresh_token(self):
        with Sandbox() as sb:
            _setup(sb, tokens=False)
            self.assertIn("arc_coros_auth.py login", self._check(sb)["fix"])
        with Sandbox() as sb:
            _setup(sb, refresh=False)
            self.assertEqual(self._check(sb)["status"], "error")

    def test_loose_permissions(self):
        with Sandbox() as sb:
            _setup(sb, mode=0o644)
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("chmod", check["fix"])
