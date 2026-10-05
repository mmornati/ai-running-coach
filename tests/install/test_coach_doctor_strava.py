"""Palier A — `coach_doctor.py` avec `[data].source = "strava"` (#164) : check `strava_connection`.

Les valeurs de jetons ci-dessous sont des chaînes factices ; on vérifie aussi qu'AUCUNE n'apparaît
dans la sortie (le doctor ne lit jamais la valeur d'un secret).
"""

from __future__ import annotations

import json
import os

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

SECRETS = ("FAKE-ACCESS-TOKEN", "FAKE-REFRESH-TOKEN", "FAKE-CLIENT-SECRET")


def _find(payload, check_id):
    return next(c for c in payload["checks"] if c["id"] == check_id)


def _setup(sb: Sandbox, *, source="strava", wrapper=True, mcp=True, tokens=None, mode=0o600):
    (sb.repo / "config").mkdir(exist_ok=True)
    (sb.repo / "config/workspace.user.toml").write_text(f'[data]\nsource = "{source}"\n')
    if wrapper:
        w = sb.home / ".config/ai-running-coach/strava-mcp/run.sh"
        w.parent.mkdir(parents=True, exist_ok=True)
        w.write_text("#!/bin/sh\n")
    if mcp:
        (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"strava": {"command": "x", "args": []}}}))
    if tokens is not None:
        t = sb.home / ".config/strava-mcp/config.json"
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(json.dumps(tokens))
        os.chmod(t, mode)


FULL = {"clientId": "1", "clientSecret": "FAKE-CLIENT-SECRET", "accessToken": "FAKE-ACCESS-TOKEN",
        "refreshToken": "FAKE-REFRESH-TOKEN", "expiresAt": 1}


class TestStravaConnection(InstallAsserts):
    def _check(self, sb, **kw):
        proc = sb.script("coach_doctor.py", "--json", "--workspace", str(sb.repo),
                         "--tokens-dir", str(sb.root / "tokens-absent"), **kw)
        for secret in SECRETS:
            self.assertNotIn(secret, proc.stdout + proc.stderr)
        return _find(json.loads(proc.stdout), "strava_connection")

    def test_not_applicable_for_other_sources(self):
        for source in ("garmin", "intervals"):
            with self.subTest(source=source), Sandbox() as sb:
                _setup(sb, source=source)
                self.assertEqual(self._check(sb)["status"], "info")

    def test_garmin_checks_are_info_under_strava(self):
        with Sandbox() as sb:
            _setup(sb, tokens=FULL)
            proc = sb.script("coach_doctor.py", "--json", "--workspace", str(sb.repo),
                             "--tokens-dir", str(sb.root / "tokens-absent"))
            payload = json.loads(proc.stdout)
            for check_id in ("garmin_token", "garmin_mcp", "fit_reader", "gear_sync", "gear_history"):
                self.assertEqual(_find(payload, check_id)["status"], "info", check_id)

    def test_healthy_connection_is_ok_and_prints_no_secret(self):
        with Sandbox() as sb:
            _setup(sb, tokens=FULL)
            check = self._check(sb)
            self.assertEqual(check["status"], "ok", check)

    def test_not_connected_is_an_error_pointing_at_connect_strava(self):
        with Sandbox() as sb:
            _setup(sb, tokens=None)
            check = self._check(sb)
            self.assertEqual(check["status"], "error")
            self.assertIn("connect-strava", check["fix"])

    def test_missing_refresh_token_is_an_error(self):
        with Sandbox() as sb:
            _setup(sb, tokens={**FULL, "refreshToken": ""})
            self.assertEqual(self._check(sb)["status"], "error")

    def test_missing_client_credentials_is_a_warning(self):
        with Sandbox() as sb:
            _setup(sb, tokens={"accessToken": "FAKE-ACCESS-TOKEN", "refreshToken": "FAKE-REFRESH-TOKEN"})
            self.assertEqual(self._check(sb)["status"], "warning")

    def test_world_readable_token_file_is_a_warning_with_chmod_fix(self):
        with Sandbox() as sb:
            _setup(sb, tokens=FULL, mode=0o644)
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("chmod 600", check["fix"])

    def test_missing_wrapper_or_server_entry_is_an_error(self):
        with Sandbox() as sb:
            _setup(sb, tokens=FULL, wrapper=False)
            self.assertEqual(self._check(sb)["status"], "error")
        with Sandbox() as sb:
            _setup(sb, tokens=FULL, mcp=False)
            self.assertEqual(self._check(sb)["status"], "error")

    def test_single_check_selector(self):
        with Sandbox() as sb:
            _setup(sb, tokens=FULL)
            proc = sb.script("coach_doctor.py", "--json", "--check", "strava_connection",
                             "--workspace", str(sb.repo))
            self.assertEqual(json.loads(proc.stdout)["checks"][0]["id"], "strava_connection")
