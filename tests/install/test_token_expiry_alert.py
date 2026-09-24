"""Palier A — alerte ntfy avant expiration des tokens Garmin (#32).

`scripts/daily-sync.sh` appelle `coach_doctor.py --check garmin_token --json`
avant chaque synchronisation et journalise, au plus une fois par jour, une
alerte ntfy quand l'échéance estimée approche (`[notifications].token_alert_days`,
défaut J-14 puis J-3). Ces tests tournent dans le bac à sable
(`tests/lib/sandbox.py`) : `curl` est stubbé (voir `tests/lib/stubs/curl`), donc
`scripts/notify.sh` n'atteint jamais un vrai serveur ntfy — on vérifie le
contenu réellement envoyé via `sb.stub_calls("curl")`.

`ARC_DOCTOR_NOW` (lu directement par `coach_doctor.py`, jamais un flag de
`daily-sync.sh`) rend l'échéance et la date du jour déterministes sans dépendre
de l'horloge de la machine — y compris pour simuler « le lendemain » sans stub
de `date`.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox

NOW = "2026-09-24T12:00:00+00:00"
NOW_DT = datetime.fromisoformat(NOW)
NEXT_DAY = "2026-09-25T12:00:00+00:00"
DAY_AFTER = "2026-09-26T12:00:00+00:00"

TOKEN_VALIDITY_FALLBACK_DAYS = 182  # scripts/coach_doctor.py — tenu au même défaut


def _tokens_dir_with_days_left(sb: Sandbox, days_left: int, name: str = "tokens") -> Path:
    """Un `garmin_tokens.json` dont le mtime donne `days_left` jours restants
    (repli mtime, seul chemin réellement exercé par `garmin-mcp` — voir
    `scripts/coach_doctor.py`), à un instant `NOW_DT` fixe."""
    tokens_dir = sb.root / name
    tokens_dir.mkdir(exist_ok=True)
    legacy = tokens_dir / "garmin_tokens.json"
    legacy.write_text('{"di_token": "x", "di_refresh_token": "y", "di_client_id": "z"}')
    mtime_dt = NOW_DT - timedelta(days=(TOKEN_VALIDITY_FALLBACK_DAYS - days_left))
    mtime = mtime_dt.timestamp()
    os.utime(legacy, (mtime, mtime))
    return tokens_dir


class TokenAlertSandbox(InstallAsserts):
    """Base : workspace ntfy-only (pas de git_autocommit, pas de .mcp.json —
    hors sujet ici), exécuteur `claude` stubbé (aucun appel réel)."""

    def _configure_notifications(self, sb: Sandbox, **notif_kwargs) -> None:
        lines = ["[notifications]"]
        for key, value in {"provider": "ntfy", "ntfy_topic": "test-topic", **notif_kwargs}.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            elif isinstance(value, list):
                rendered = ", ".join(str(v) for v in value)
                lines.append(f"{key} = [{rendered}]")
            else:
                lines.append(f'{key} = "{value}"')
        config_dir = sb.repo / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "workspace.user.toml").write_text("\n".join(lines) + "\n")

    def _run(self, sb: Sandbox, tokens_dir: Path, now: str, **env):
        return sb.script(
            "daily-sync.sh",
            GARMIN_TOKENS_DIR=str(tokens_dir),
            ARC_DOCTOR_NOW=now,
            **env,
        )

    def _curl_messages(self, sb: Sandbox) -> list:
        return [args for _, args in sb.stub_calls("curl")]


class TestTokenAlertThresholds(TokenAlertSandbox):
    def test_far_from_expiry_sends_no_alert(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 20)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            self.assertNotCalled(sb, "curl")

    def test_j14_tier_sends_one_alert_with_renewal_command(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 alerte, vu {calls}")
            self.assertIn("uv run garmin-mcp-auth", calls[0])
            self.assertIn("10 jour", calls[0])

    def test_j3_tier_sends_one_alert(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 alerte, vu {calls}")
            self.assertIn("uv run garmin-mcp-auth", calls[0])

    def test_expired_tokens_send_one_alert(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, -5)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 alerte, vu {calls}")
            self.assertIn("expiré", calls[0].lower())
            self.assertIn("uv run garmin-mcp-auth", calls[0])

    def test_custom_thresholds_are_honoured(self):
        with Sandbox() as sb:
            self._configure_notifications(sb, token_alert_days=[30])
            tokens_dir = _tokens_dir_with_days_left(sb, 20)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            # 20 <= 30 (seuil personnalisé, unique -> aussi le seuil "urgent") : une alerte.
            self.assertEqual(len(self._curl_messages(sb)), 1)


class TestTokenAlertOncePerDay(TokenAlertSandbox):
    def test_same_day_rerun_does_not_repeat(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertEqual(len(self._curl_messages(sb)), 1, "une seule alerte pour deux runs le même jour")

    def test_next_day_more_urgent_tier_alerts_again(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            # Le lendemain, les mêmes tokens ont 2 jours de moins : palier J-3.
            tokens_dir_2 = _tokens_dir_with_days_left(sb, 2, name="tokens-day2")
            self.assertSucceeded(self._run(sb, tokens_dir_2, NEXT_DAY))
            self.assertEqual(len(self._curl_messages(sb)), 2, "un changement de palier doit réalerter")

    def test_j3_tier_alerts_daily_until_renewed(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))  # même jour : pas de 2e alerte
            self.assertEqual(len(self._curl_messages(sb)), 1)

            tokens_dir_2 = _tokens_dir_with_days_left(sb, 1, name="tokens-day2")
            self.assertSucceeded(self._run(sb, tokens_dir_2, NEXT_DAY))
            self.assertEqual(len(self._curl_messages(sb)), 2, "le palier le plus urgent doit réalerter chaque jour")

    def test_renewal_clears_state_and_resumes_alerting_later(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertEqual(len(self._curl_messages(sb)), 1)

            # Renouvellement : tokens frais, bien au-dessus de tous les seuils.
            renewed = _tokens_dir_with_days_left(sb, 180, name="tokens-renewed")
            self.assertSucceeded(self._run(sb, renewed, NEXT_DAY))
            self.assertEqual(len(self._curl_messages(sb)), 1, "pas d'alerte : tokens renouvelés")

            # Nouvelle échéance qui approche à nouveau plus tard : ré-alerte normalement.
            tokens_dir_3 = _tokens_dir_with_days_left(sb, 2, name="tokens-day3")
            self.assertSucceeded(self._run(sb, tokens_dir_3, DAY_AFTER))
            self.assertEqual(len(self._curl_messages(sb)), 2)


class TestTokenAlertDisableSwitch(TokenAlertSandbox):
    def test_token_alerts_false_sends_nothing(self):
        with Sandbox() as sb:
            self._configure_notifications(sb, token_alerts=False)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            self.assertNotCalled(sb, "curl")

    def test_provider_none_is_a_noop(self):
        with Sandbox() as sb:
            self._configure_notifications(sb, provider="none")
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            self.assertNotCalled(sb, "curl")


class TestDoctorCrashNeverBlocksSync(TokenAlertSandbox):
    def test_broken_doctor_still_lets_sync_proceed(self):
        """Un `coach_doctor.py` qui plante (ici : un `python3` bidon) ne doit
        jamais faire échouer `daily-sync.sh` — seulement priver l'utilisateur
        de l'alerte, avec une trace dans le journal.

        `daily-sync.sh` préfixe volontairement son PATH avec
        `$HOME/.local/bin` (pour trouver `claude`/`codex`/`uv` sur une machine
        cron à PATH minimal) : c'est là, PAS via un simple override de PATH du
        test, qu'un faux `python3` doit être placé pour primer sur le vrai
        (et sur les stubs)."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)

            fake_bin = sb.home / ".local" / "bin"
            fake_bin.mkdir(parents=True)
            fake_python3 = fake_bin / "python3"
            fake_python3.write_text("#!/usr/bin/env bash\necho 'boom' >&2\nexit 9\n")
            fake_python3.chmod(0o755)

            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc, "la synchronisation doit continuer malgré un coach doctor cassé")
            self.assertNotCalled(sb, "curl")
            self.assertOutputContains(proc, "coach doctor indisponible")
            logs = list((sb.repo / "logs").glob("sync-*.log"))
            self.assertTrue(logs, "aucun journal de synchronisation écrit")


class TestAuthFailureExplicitNotification(TokenAlertSandbox):
    """Un vrai 401 Garmin (texte réel de `garminconnect`/`garmin_mcp`, voir
    `tests/evals/mcp_stub_common.py::auth_expired_text`) doit produire une
    notification explicite avec la commande de renouvellement, à la place du
    message d'échec générique."""

    def _fake_claude(self, sb: Sandbox, stdout: str, exit_code: int = 0) -> Path:
        fake_bin = sb.root / "fake-claude-bin"
        fake_bin.mkdir(exist_ok=True)
        fake_claude = fake_bin / "claude"
        fake_claude.write_text(
            "#!/usr/bin/env bash\n"
            f"cat <<'EOF'\n{stdout}\nEOF\n"
            f"exit {exit_code}\n"
        )
        fake_claude.chmod(0o755)
        return fake_bin

    def test_401_in_successful_run_output_triggers_explicit_alert(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)  # loin de l'échéance : pas de bruit du palier J-14/J-3
            auth_text = (
                "Error retrieving sleep data: Authentication failed: "
                "401 Client Error: Unauthorized for url: https://connect.garmin.com/x\n"
                "```resume\nERREUR : tokens Garmin expirés\n```\n"
            )
            fake_bin = self._fake_claude(sb, auth_text, exit_code=0)
            path = f"{fake_bin}:{STUBS_DIR}:{os.environ.get('PATH', '')}"
            proc = self._run(sb, tokens_dir, NOW, PATH=path)
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertTrue(calls, "aucune notification envoyée")
            self.assertTrue(
                any("garmin-mcp-auth" in c and ("401" in c or "authentification" in c.lower() or "Authentification" in c)
                    for c in calls),
                f"pas de notification explicite d'authentification : {calls}",
            )

    def test_401_causing_run_failure_gets_explicit_alert_not_generic(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)
            auth_text = "Authentication failed: 401 Client Error: Unauthorized for url: https://connect.garmin.com/x"
            fake_bin = self._fake_claude(sb, auth_text, exit_code=1)
            path = f"{fake_bin}:{STUBS_DIR}:{os.environ.get('PATH', '')}"
            proc = self._run(sb, tokens_dir, NOW, PATH=path)
            self.assertFailed(proc, "le code de sortie du runner doit rester propagé")
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1)
            self.assertIn("garmin-mcp-auth", calls[0])
            self.assertNotIn("Sync Garmin échouée", calls[0])
