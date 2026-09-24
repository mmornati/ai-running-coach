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
from datetime import datetime, timedelta
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox

NOW = "2026-09-24T12:00:00+00:00"
NOW_DT = datetime.fromisoformat(NOW)
NEXT_DAY = "2026-09-25T12:00:00+00:00"
DAY_AFTER = "2026-09-26T12:00:00+00:00"

TOKEN_VALIDITY_FALLBACK_DAYS = 182  # scripts/coach_doctor.py — tenu au même défaut
TOKEN_ALERT_TITLE = "🔑 Tokens Garmin"  # préfixe commun du titre envoyé par check_token_alert()


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

    def _write_raw_notifications_config(self, sb: Sandbox, body: str) -> None:
        """Comme `_configure_notifications`, mais avec le corps de la section
        écrit tel quel — nécessaire pour les cas malformés/malveillants où le
        rendu générique (qui quote/joint proprement) ne reproduirait pas le
        TOML exact à verrouiller."""
        config_dir = sb.repo / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "workspace.user.toml").write_text(f"[notifications]\n{body}\n")

    def _curl_messages(self, sb: Sandbox) -> list:
        return [args for _, args in sb.stub_calls("curl")]

    def _token_alert_calls(self, sb: Sandbox) -> list:
        """Filtre les envois `curl` sur le TITRE réellement posé par
        `check_token_alert()` — pas sur un simple décompte total des appels
        `curl`, qui inclurait aussi le résumé de fin de synchronisation s'il
        devait un jour porter du texte non vide."""
        return [c for c in self._curl_messages(sb) if TOKEN_ALERT_TITLE in c]


class TestTokenAlertThresholds(TokenAlertSandbox):
    def test_far_from_expiry_sends_no_alert(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 20)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            self.assertEqual(self._token_alert_calls(sb), [])

    def test_j14_tier_sends_one_alert_with_renewal_command(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            calls = self._token_alert_calls(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 alerte, vu {calls}")
            self.assertIn("uv run garmin-mcp-auth", calls[0])
            self.assertIn("10 jour", calls[0])

    def test_j3_tier_sends_one_alert(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            calls = self._token_alert_calls(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 alerte, vu {calls}")
            self.assertIn("uv run garmin-mcp-auth", calls[0])

    def test_expired_tokens_send_one_alert(self):
        """Le nombre de jours affiché suit le même arrondi vers le bas que
        `coach_doctor.py` (`timedelta.days`) : un token expiré depuis 5 jours
        pile affiche bien 5, jamais 4 (arrondi au plus proche) ni 6."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, -5)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            calls = self._token_alert_calls(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 alerte, vu {calls}")
            self.assertIn("expiré", calls[0].lower())
            self.assertIn("5 jour", calls[0])
            self.assertIn("uv run garmin-mcp-auth", calls[0])

    def test_custom_thresholds_are_honoured(self):
        with Sandbox() as sb:
            self._configure_notifications(sb, token_alert_days=[30])
            tokens_dir = _tokens_dir_with_days_left(sb, 20)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            # 20 <= 30 (seuil personnalisé, unique -> aussi le seuil "urgent") : une alerte.
            self.assertEqual(len(self._token_alert_calls(sb)), 1)

    def test_empty_threshold_list_disables_expiry_alerts(self):
        """`token_alert_days = []` désactive l'alerte d'expiration (mais pas la
        notification 401 explicite, hors sujet ici) — comportement documenté
        dans `config/workspace.toml` et `docs/troubleshooting.md`."""
        with Sandbox() as sb:
            self._configure_notifications(sb, token_alert_days=[])
            tokens_dir = _tokens_dir_with_days_left(sb, -5)  # même expiré : aucun seuil configuré
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            self.assertEqual(self._token_alert_calls(sb), [])


class TestMalformedThresholdsAreRejectedSafely(TokenAlertSandbox):
    """RÉGRESSION (revue PR #77) : `token_alert_days` vient de la config —
    potentiellement modifiée par un utilisateur ou un outil tiers. Une valeur
    non entière ne doit ni tuer le script (« unbound variable » sous `set -u`
    dans la comparaison arithmétique `[[ -le ]]`, qui faisait mourir le doctor
    AVANT la synchronisation, silencieusement, code de sortie 0) ni s'exécuter
    comme une substitution de commande (un jeton façon indice de tableau,
    ex. `HOME[$(commande)]`, atteignant `[[ -le ]]`)."""

    def test_non_numeric_threshold_does_not_abort_the_sync(self):
        with Sandbox() as sb:
            self._write_raw_notifications_config(
                sb,
                'provider = "ntfy"\nntfy_topic = "test-topic"\ntoken_alerts = true\n'
                "token_alert_days = [14, three]\n",
            )
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc, "un seuil non numérique ne doit pas faire échouer daily-sync.sh")
            self.assertOutputContains(proc, "token_alert_days")
            # Le seuil valide restant (14) doit quand même produire une alerte.
            calls = self._token_alert_calls(sb)
            self.assertEqual(len(calls), 1, f"le seuil numérique valide doit rester actif : {calls}")

    def test_command_substitution_payload_is_never_executed(self):
        with Sandbox() as sb:
            payload_marker = sb.root / "pwned-arc32"
            self.assertFalse(payload_marker.exists())
            self._write_raw_notifications_config(
                sb,
                'provider = "ntfy"\nntfy_topic = "test-topic"\ntoken_alerts = true\n'
                f'token_alert_days = ["HOME[$(touch {payload_marker})]", 14]\n',
            )
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            proc = self._run(sb, tokens_dir, NOW)
            self.assertSucceeded(proc)
            self.assertFalse(
                payload_marker.exists(),
                "la charge utile placée dans token_alert_days a été exécutée !",
            )
            # Le seuil 14, valide, doit tout de même déclencher l'alerte normale.
            self.assertEqual(len(self._token_alert_calls(sb)), 1)


class TestTokenAlertOncePerDay(TokenAlertSandbox):
    def test_same_day_rerun_does_not_repeat(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertEqual(
                len(self._token_alert_calls(sb)), 1, "une seule alerte pour deux runs le même jour"
            )

    def test_next_day_more_urgent_tier_alerts_again(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 10)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            # Le lendemain, les mêmes tokens ont 2 jours de moins : palier J-3.
            tokens_dir_2 = _tokens_dir_with_days_left(sb, 2, name="tokens-day2")
            self.assertSucceeded(self._run(sb, tokens_dir_2, NEXT_DAY))
            self.assertEqual(
                len(self._token_alert_calls(sb)), 2, "un changement de palier doit réalerter"
            )

    def test_j3_tier_alerts_daily_until_renewed(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))  # même jour : pas de 2e alerte
            self.assertEqual(len(self._token_alert_calls(sb)), 1)

            tokens_dir_2 = _tokens_dir_with_days_left(sb, 1, name="tokens-day2")
            self.assertSucceeded(self._run(sb, tokens_dir_2, NEXT_DAY))
            self.assertEqual(
                len(self._token_alert_calls(sb)), 2, "le palier le plus urgent doit réalerter chaque jour"
            )

    def test_renewal_clears_state_and_resumes_alerting_later(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 2)
            self.assertSucceeded(self._run(sb, tokens_dir, NOW))
            self.assertEqual(len(self._token_alert_calls(sb)), 1)

            # Renouvellement : tokens frais, bien au-dessus de tous les seuils.
            renewed = _tokens_dir_with_days_left(sb, 180, name="tokens-renewed")
            self.assertSucceeded(self._run(sb, renewed, NEXT_DAY))
            self.assertEqual(len(self._token_alert_calls(sb)), 1, "pas d'alerte : tokens renouvelés")

            # Nouvelle échéance qui approche à nouveau plus tard : ré-alerte normalement.
            tokens_dir_3 = _tokens_dir_with_days_left(sb, 2, name="tokens-day3")
            self.assertSucceeded(self._run(sb, tokens_dir_3, DAY_AFTER))
            self.assertEqual(len(self._token_alert_calls(sb)), 2)


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
    """Un vrai 401 Garmin doit produire une notification explicite avec la
    commande de renouvellement, à la place du message d'échec générique — et
    UNIQUEMENT un vrai 401 Garmin, jamais un 401 sans rapport (ex. le runner
    Codex lui-même en échec d'authentification côté OpenAI).

    Deux façons dont le texte peut atteindre le journal, couvertes séparément
    (voir le commentaire de `detect_auth_failure` dans `daily-sync.sh`) :
    - un exécuteur qui restitue la sortie brute d'un outil MCP (ex. `codex
      exec` en mode verbeux) : le texte réel de `garminconnect`/`garmin_mcp`
      (`tests/evals/mcp_stub_common.py::auth_expired_text`) ;
    - le runner par défaut, `claude -p --output-format text`, qui ne restitue
      QUE le message final de l'agent : la formulation `ERREUR : …` que
      `skills/garmin-daily-sync/SKILL.md` impose à l'agent d'écrire lui-même.
    """

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

    def _path_with_fake_claude(self, fake_bin: Path) -> str:
        return f"{fake_bin}:{STUBS_DIR}:{os.environ.get('PATH', '')}"

    def test_realistic_claude_runner_only_sees_the_skill_wording(self):
        """`claude -p` ne restitue jamais le texte brut d'un outil MCP : c'est
        la formulation `ERREUR : …` du skill, et seulement elle, qui doit
        déclencher l'alerte avec ce runner (défaut du projet)."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)  # loin de l'échéance : pas de bruit J-14/J-3
            final_message = (
                "Séances : aucune nouvelle\n"
                "```resume\n"
                "ERREUR : tokens Garmin expirés — relancer uv run garmin-mcp-auth\n"
                "```\n"
            )
            fake_bin = self._fake_claude(sb, final_message, exit_code=0)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 notification, vu {calls}")
            self.assertIn("Authentification Garmin refusée", calls[0])
            self.assertIn("garmin-mcp-auth", calls[0])

    def test_verbose_runner_with_raw_garmin_error_text(self):
        """Représente un exécuteur qui restitue la sortie brute d'un outil MCP
        (ex. `codex exec` en mode verbeux) : le texte réel émis par
        `garminconnect`/`garmin_mcp` doit être reconnu même sans la
        formulation du skill."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)
            raw_tool_output = (
                "Error retrieving sleep data: Authentication failed: "
                "401 Client Error: Unauthorized for url: https://connect.garmin.com/x\n"
            )
            fake_bin = self._fake_claude(sb, raw_tool_output, exit_code=0)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 notification, vu {calls}")
            self.assertIn("Authentification Garmin refusée", calls[0])
            self.assertIn("garmin-mcp-auth", calls[0])

    def test_401_causing_run_failure_gets_explicit_alert_not_generic(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)
            auth_text = "Authentication failed: 401 Client Error: Unauthorized for url: https://connect.garmin.com/x"
            fake_bin = self._fake_claude(sb, auth_text, exit_code=1)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertFailed(proc, "le code de sortie du runner doit rester propagé")
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1)
            self.assertIn("garmin-mcp-auth", calls[0])
            self.assertNotIn("Sync Garmin échouée", calls[0])

    def test_unrelated_401_is_not_mistaken_for_a_garmin_auth_failure(self):
        """Un 401 générique — ici, un runner Codex qui échoue à s'authentifier
        contre son propre backend — ne doit JAMAIS déclencher l'alerte Garmin
        explicite : le message d'échec générique reste de mise."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)
            codex_style_401 = "unexpected status 401 Unauthorized: {\"error\":\"invalid_token\"}"
            fake_bin = self._fake_claude(sb, codex_style_401, exit_code=1)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertFailed(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 notification, vu {calls}")
            self.assertNotIn("Authentification Garmin refusée", calls[0])
            self.assertIn("Sync Garmin échouée", calls[0])
            self.assertNotIn("garmin-mcp-auth", calls[0])

    def test_erreur_line_about_network_issue_on_success_is_not_mistaken_for_auth(self):
        """RÉGRESSION (revue PR #77) : une ligne `ERREUR` qui ne fait que
        MENTIONNER les tokens Garmin en passant, sans dire qu'ils sont
        expirés/invalides/refusés, ne doit pas se voir requalifiée en refus
        d'authentification — ici un simple timeout réseau vers le MCP."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)
            final_message = (
                "```resume\n"
                "ERREUR : MCP garmin injoignable (timeout réseau) — token Garmin non vérifié\n"
                "```\n"
            )
            fake_bin = self._fake_claude(sb, final_message, exit_code=0)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertSucceeded(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 notification, vu {calls}")
            self.assertNotIn("Authentification Garmin refusée", calls[0])
            self.assertNotIn("Authentification Garmin — action requise", calls[0])
            self.assertIn("timeout réseau", calls[0])

    def test_erreur_line_about_network_issue_on_failure_does_not_claim_401(self):
        """RÉGRESSION (revue PR #77) : sur un run en échec, une ligne `ERREUR`
        qui décrit une panne réseau (DNS) ne doit jamais être requalifiée en
        « (401) » — un vrai problème réseau serait alors masqué par une fausse
        piste d'authentification."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, 60)
            final_message = "ERREUR : échec du rafraîchissement des tokens Garmin (DNS)"
            fake_bin = self._fake_claude(sb, final_message, exit_code=1)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertFailed(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(len(calls), 1, f"attendu 1 notification, vu {calls}")
            self.assertNotIn("(401)", calls[0])
            self.assertIn("Sync Garmin échouée", calls[0])

    def test_no_duplicate_notification_when_token_alert_already_fired(self):
        """Si l'alerte d'expiration (tokens expirés) est déjà partie ce run,
        et que la synchronisation échoue ensuite sur ce même 401, on ne
        double pas avec une seconde notification pour le même problème."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            tokens_dir = _tokens_dir_with_days_left(sb, -5)  # expiré : check_token_alert va alerter
            auth_text = "Authentication failed: 401 Client Error: Unauthorized for url: https://connect.garmin.com/x"
            fake_bin = self._fake_claude(sb, auth_text, exit_code=1)
            proc = self._run(sb, tokens_dir, NOW, PATH=self._path_with_fake_claude(fake_bin))
            self.assertFailed(proc)
            calls = self._curl_messages(sb)
            self.assertEqual(
                len(calls), 1,
                f"une seule notification attendue (alerte d'expiration), pas de doublon 401 : {calls}",
            )
            self.assertIn("expiré", calls[0].lower())
