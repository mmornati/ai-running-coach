"""Palier A — `coach doctor` (#31) : diagnostic d'installation en une commande.

Chaque cas verrouille un statut par vérification pour un scénario donné, dans
le bac à sable (`tests/lib/sandbox.py`) — jamais contre le vrai HOME ou la
vraie crontab du contributeur. `--tokens-dir` et `--now` rendent le check
`garmin_token` déterministe sans dépendre de l'horloge de la machine.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

NOW = "2026-09-24T12:00:00+00:00"
NOW_DT = datetime.fromisoformat(NOW)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _fresh_tokens_dir(sb: Sandbox):
    """Un répertoire de tokens valides très longtemps — pour les tests qui ne
    portent pas sur `garmin_token` et ne veulent pas que ce check fasse
    échouer la commande (code de sortie) pour une raison hors-sujet."""
    tokens_dir = sb.root / "tokens-fresh-fixture"
    tokens_dir.mkdir(exist_ok=True)
    (tokens_dir / "oauth2_token.json").write_text(json.dumps({
        "refresh_token_expires_at": _epoch(NOW_DT + timedelta(days=300)),
    }))
    return tokens_dir


class TestGarminTokenAges(InstallAsserts):
    """Tokens de différents âges — via le champ explicite `garth` et via mtime."""

    def _run(self, sb: Sandbox, tokens_dir):
        return sb.script(
            "coach_doctor.py", "--json", "--now", NOW, "--tokens-dir", str(tokens_dir),
        )

    def test_explicit_expiry_far_future_is_ok(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-fresh"
            tokens_dir.mkdir()
            expires = NOW_DT + timedelta(days=60)
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "access_token": "fake-access-token-not-a-real-secret",
                "refresh_token": "fake-refresh-token-not-a-real-secret",
                "refresh_token_expires_at": _epoch(expires),
            }))
            proc = self._run(sb, tokens_dir)
            self.assertSucceeded(proc)
            payload = json.loads(proc.stdout)
            check = _find(payload, "garmin_token")
            self.assertEqual(check["status"], "ok")
            self.assertEqual(check["source"], "explicit")
            self.assertEqual(check["days_left"], 60)

    def test_explicit_expiry_soon_is_warning(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-warn"
            tokens_dir.mkdir()
            expires = NOW_DT + timedelta(days=5)
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "refresh_token_expires_at": _epoch(expires),
            }))
            proc = self._run(sb, tokens_dir)
            self.assertSucceeded(proc, "un warning ne doit pas faire échouer la commande")
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertEqual(check["status"], "warning")
            self.assertEqual(check["days_left"], 5)
            self.assertEqual(check["fix"], "uv run garmin-mcp-auth")

    def test_explicit_expiry_past_is_error(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-expired"
            tokens_dir.mkdir()
            expires = NOW_DT - timedelta(days=3)
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "refresh_token_expires_at": _epoch(expires),
            }))
            proc = self._run(sb, tokens_dir)
            self.assertFailed(proc, "un token expiré doit faire échouer la commande")
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["ok"])
            check = _find(payload, "garmin_token")
            self.assertEqual(check["status"], "error")
            self.assertLess(check["days_left"], 0)

    def test_missing_tokens_is_error(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-absent"   # jamais créé
            proc = self._run(sb, tokens_dir)
            self.assertFailed(proc)
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertEqual(check["status"], "error")
            self.assertEqual(check["source"], "missing")
            self.assertIsNone(check["expires_at"])
            self.assertIsNone(check["days_left"])

    def test_legacy_format_falls_back_to_mtime(self):
        """`garmin_tokens.json` (vendored client) n'a pas d'échéance explicite."""
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-legacy"
            tokens_dir.mkdir()
            legacy = tokens_dir / "garmin_tokens.json"
            legacy.write_text(json.dumps({
                "di_token": "fake-jwt-not-a-real-secret",
                "di_refresh_token": "fake-jwt-refresh-not-a-real-secret",
                "di_client_id": "fake-client-id",
            }))
            # mtime : il y a 170 jours (< fenêtre de 182 jours) -> encore valide,
            # mais l'échéance estimée tombe dans moins de 14 jours -> warning.
            past = time.time() - 170 * 86400
            os.utime(legacy, (past, past))
            proc = sb.script(
                "coach_doctor.py", "--json", "--tokens-dir", str(tokens_dir),
            )
            self.assertSucceeded(proc)
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertEqual(check["source"], "mtime_fallback")
            self.assertEqual(check["status"], "warning")

    def test_never_leaks_token_secret_values(self):
        secret = "TOTALLY-SECRET-REFRESH-TOKEN-VALUE-DO-NOT-LEAK"
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-secret"
            tokens_dir.mkdir()
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "access_token": secret,
                "refresh_token": secret,
                "refresh_token_expires_at": _epoch(NOW_DT + timedelta(days=100)),
            }))
            for extra_args in (["--json"], []):
                proc = sb.script(
                    "coach_doctor.py", *extra_args, "--now", NOW, "--tokens-dir", str(tokens_dir),
                )
                self.assertOutputLacks(proc, secret)


class TestGarminMcpReachability(InstallAsserts):
    def test_stub_present_but_silent_is_warning(self):
        """Le stub `garmin-mcp` (tests/lib/stubs) sort immédiatement, sans
        parler MCP : présent mais muet -> avertissement, pas une erreur."""
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertEqual(check["status"], "warning")

    def test_command_missing_is_error(self):
        with Sandbox() as sb:
            proc = sb.run(
                [str(sb.repo / "scripts" / "coach_doctor.py"), "--json",
                 "--tokens-dir", str(_fresh_tokens_dir(sb))],
                hide=("garmin-mcp",),
            )
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertEqual(check["status"], "error")
            self.assertIn("introuvable", check["message"])


class TestAthleteProfile(InstallAsserts):
    def test_missing_profile_is_warning(self):
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "athlete_profile")
            self.assertEqual(check["status"], "warning")

    def test_incomplete_profile_is_info(self):
        with Sandbox() as sb:
            profile = sb.repo / "planning" / "Runner_Profile.md"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(
                "# Profil de l'athlète\n\n## Physiologie\n\n"
                "- **FC max** : 190\n"
                "- **FC de repos de référence** : <!-- votre ligne de base -->\n"
            )
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "athlete_profile")
            self.assertEqual(check["status"], "info")
            self.assertIn("FC de repos", check["message"])

    def test_complete_profile_is_ok(self):
        with Sandbox() as sb:
            profile = sb.repo / "planning" / "Runner_Profile.md"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(
                "## Physiologie\n\n- **FC max** : 190\n- **FC de repos de référence** : 48\n"
            )
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "athlete_profile")
            self.assertEqual(check["status"], "ok")


class TestIndexFreshness(InstallAsserts):
    def test_no_index_is_info(self):
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "info")

    def test_stale_index_is_warning(self):
        with Sandbox() as sb:
            arc_dir = sb.repo / ".arc"
            arc_dir.mkdir(parents=True, exist_ok=True)
            db = arc_dir / "coach.db"
            db.write_text("")
            old = time.time() - 1000
            os.utime(db, (old, old))

            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text("# Séance\n")

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "warning")

    def test_fresh_index_is_ok(self):
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text("# Séance\n")

            arc_dir = sb.repo / ".arc"
            arc_dir.mkdir(parents=True, exist_ok=True)
            (arc_dir / "coach.db").write_text("")   # mtime = maintenant, après le fichier

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "ok")


class TestDailySyncScheduled(InstallAsserts):
    def test_no_crontab_is_info_never_error(self):
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)),
                ARC_FAKE_UNAME="Linux",
            )
            self.assertSucceeded(proc)
            check = _find(json.loads(proc.stdout), "daily_sync_scheduled")
            self.assertEqual(check["status"], "info")

    def test_crontab_with_marker_is_ok(self):
        with Sandbox() as sb:
            sb.set_crontab("15 7 * * * /path/to/daily-sync.sh # ai-running-coach daily-sync\n")
            proc = sb.script(
                "coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)),
                ARC_FAKE_UNAME="Linux",
            )
            check = _find(json.loads(proc.stdout), "daily_sync_scheduled")
            self.assertEqual(check["status"], "ok")

    def test_launchd_plist_present_is_ok(self):
        with Sandbox() as sb:
            plist_dir = sb.home / "Library" / "LaunchAgents"
            plist_dir.mkdir(parents=True)
            (plist_dir / "com.ai-running-coach.daily-sync.plist").write_text("<plist/>")
            proc = sb.script(
                "coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)),
                ARC_FAKE_UNAME="Darwin",
            )
            check = _find(json.loads(proc.stdout), "daily_sync_scheduled")
            self.assertEqual(check["status"], "ok")

    def test_launchd_plist_absent_is_info(self):
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)),
                ARC_FAKE_UNAME="Darwin",
            )
            check = _find(json.loads(proc.stdout), "daily_sync_scheduled")
            self.assertEqual(check["status"], "info")


class TestNtfyConfigured(InstallAsserts):
    def test_disabled_by_default_is_info(self):
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "ntfy_configured")
            self.assertEqual(check["status"], "info")

    def test_enabled_without_topic_is_warning(self):
        with Sandbox() as sb:
            (sb.repo / "config" / "workspace.user.toml").write_text(
                '[notifications]\nprovider = "ntfy"\n'
            )
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "ntfy_configured")
            self.assertEqual(check["status"], "warning")

    def test_enabled_with_topic_is_ok(self):
        with Sandbox() as sb:
            (sb.repo / "config" / "workspace.user.toml").write_text(
                '[notifications]\nprovider = "ntfy"\nntfy_topic = "coach-test-topic"\n'
            )
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "ntfy_configured")
            self.assertEqual(check["status"], "ok")


class TestConfigFiles(InstallAsserts):
    def test_invalid_toml_is_error(self):
        with Sandbox() as sb:
            (sb.repo / "config" / "workspace.user.toml").write_text("[notifications\nprovider = ntfy\n")
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertFailed(proc)
            check = _find(json.loads(proc.stdout), "config_files")
            self.assertEqual(check["status"], "error")


class TestJsonSchema(InstallAsserts):
    def test_schema_shape(self):
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertSucceeded(proc)
            payload = json.loads(proc.stdout)
            self.assertIsInstance(payload["generated_at"], str)
            self.assertIsInstance(payload["workspace"], str)
            self.assertIsInstance(payload["ok"], bool)
            self.assertIsInstance(payload["checks"], list)
            expected_ids = {
                "garmin_token", "garmin_mcp", "config_files", "athlete_profile",
                "index_freshness", "out_of_contract", "daily_sync_scheduled", "ntfy_configured",
            }
            self.assertEqual({c["id"] for c in payload["checks"]}, expected_ids)
            for check in payload["checks"]:
                self.assertIsInstance(check["id"], str)
                self.assertIn(check["status"], ("ok", "warning", "error", "info"))
                self.assertIsInstance(check["message"], str)
                self.assertTrue(check["fix"] is None or isinstance(check["fix"], str))
            token_check = _find(payload, "garmin_token")
            self.assertIn("expires_at", token_check)
            self.assertIn("days_left", token_check)
            self.assertIn("source", token_check)


class TestExitCode(InstallAsserts):
    def test_zero_when_nothing_erroring_but_warnings_present(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-warn"
            tokens_dir.mkdir()
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "refresh_token_expires_at": _epoch(NOW_DT + timedelta(days=5)),
            }))
            proc = sb.script(
                "coach_doctor.py", "--now", NOW, "--tokens-dir", str(tokens_dir),
            )
            # Un ⚠️ (token proche de l'échéance) ne doit jamais faire échouer la commande.
            self.assertSucceeded(proc)

    def test_nonzero_when_any_error(self):
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--now", NOW, "--tokens-dir", str(sb.root / "absent"),
            )
            self.assertFailed(proc)


def _find(payload: dict, check_id: str) -> dict:
    for check in payload["checks"]:
        if check["id"] == check_id:
            return check
    raise AssertionError(f"check {check_id!r} absent de {payload['checks']}")
