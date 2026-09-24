"""Palier A — `coach doctor` (#31) : diagnostic d'installation en une commande.

Chaque cas verrouille un statut par vérification pour un scénario donné, dans
le bac à sable (`tests/lib/sandbox.py`) — jamais contre le vrai HOME ou la
vraie crontab du contributeur. `--tokens-dir` et `--now` rendent le check
`garmin_token` déterministe sans dépendre de l'horloge de la machine.
"""

from __future__ import annotations

import json
import os
import sys
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
    (tokens_dir / "garmin_tokens.json").write_text(json.dumps({
        "di_token": "fake-jwt-not-a-real-secret",
        "di_refresh_token": "fake-refresh-not-a-real-secret",
        "di_client_id": "fake-client-id",
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
        """`garmin_tokens.json` (le VRAI client vendored par `garmin-mcp`) n'a
        aucune échéance explicite exploitable (voir docstring du module)."""
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

    def test_legacy_file_wins_over_leftover_oauth2_file(self):
        """RÉGRESSION (revue PR #76) : un `oauth2_token.json` obsolète, laissé
        par une ancienne installation, ne doit JAMAIS l'emporter sur le
        `garmin_tokens.json` réellement lu par `garmin-mcp` — sinon un faux
        « expiré depuis 1045 jours » masquerait des tokens parfaitement
        valides."""
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-both"
            tokens_dir.mkdir()
            # Le fichier réel : frais (mtime = maintenant -> valide ~6 mois).
            (tokens_dir / "garmin_tokens.json").write_text(json.dumps({
                "di_token": "fake-jwt-not-a-real-secret",
                "di_refresh_token": "fake-refresh-not-a-real-secret",
                "di_client_id": "fake-client-id",
            }))
            # Le reliquat : une échéance explicite très ancienne, qui ne doit
            # jamais être lue puisque `garmin-mcp` ne lit pas ce fichier.
            stale_expiry = NOW_DT - timedelta(days=1045)
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "refresh_token_expires_at": _epoch(stale_expiry),
            }))
            proc = self._run(sb, tokens_dir)
            self.assertSucceeded(proc, "le fichier réel (garmin_tokens.json) est frais")
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertEqual(check["source"], "mtime_fallback")
            self.assertGreater(check["days_left"], 0)

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
            (tokens_dir / "garmin_tokens.json").write_text(json.dumps({
                "di_token": secret,
                "di_refresh_token": secret,
                "di_client_id": "fake-client-id",
            }))
            for extra_args in (["--json"], []):
                proc = sb.script(
                    "coach_doctor.py", *extra_args, "--now", NOW, "--tokens-dir", str(tokens_dir),
                )
                self.assertOutputLacks(proc, secret)


class TestGarminTokenMalformedInputs(InstallAsserts):
    """Fichiers de tokens corrompus/inattendus : jamais de trace Python, un
    statut `error`/`missing` propre à la place."""

    def _run(self, sb: Sandbox, tokens_dir):
        return sb.script("coach_doctor.py", "--json", "--now", NOW, "--tokens-dir", str(tokens_dir))

    def test_oauth2_json_is_a_list_not_object(self):
        """Un `oauth2_token.json` structurellement invalide (ex. JSON qui
        parse mais rend une liste, pas un objet) doit retomber proprement sur
        le repli mtime plutôt que planter `dict.get` sur une liste."""
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-list"
            tokens_dir.mkdir()
            (tokens_dir / "oauth2_token.json").write_text(json.dumps(["not", "an", "object"]))
            proc = self._run(sb, tokens_dir)
            self.assertNotIn("Traceback", proc.stderr)
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertEqual(check["source"], "mtime_fallback")

    def test_epoch_in_milliseconds_does_not_crash(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-ms"
            tokens_dir.mkdir()
            far_future_ms = _epoch(NOW_DT + timedelta(days=60)) * 1000
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "refresh_token_expires_at": far_future_ms,
            }))
            proc = self._run(sb, tokens_dir)
            self.assertNotIn("Traceback", proc.stderr)
            # Une valeur aberrante (hors plage) doit retomber proprement sur
            # le repli mtime plutôt que planter `datetime.fromtimestamp`.
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertIn(check["source"], ("mtime_fallback", "missing"))

    def test_bool_expiry_field_is_ignored(self):
        with Sandbox() as sb:
            tokens_dir = sb.root / "tokens-bool"
            tokens_dir.mkdir()
            (tokens_dir / "oauth2_token.json").write_text(json.dumps({
                "refresh_token_expires_at": True,
            }))
            proc = self._run(sb, tokens_dir)
            self.assertNotIn("Traceback", proc.stderr)
            check = _find(json.loads(proc.stdout), "garmin_token")
            self.assertNotEqual(check["source"], "explicit")


class TestGarminMcpReachability(InstallAsserts):
    def test_presence_only_by_default_is_ok(self):
        """Par défaut : présence/exécutabilité seulement (voir revue PR #76,
        blocage n°2) — aucun process `garmin-mcp` réel n'est lancé, donc le
        stub muet (`tests/lib/stubs/garmin-mcp`, qui sort immédiatement) est
        déjà suffisant pour un ✅."""
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertEqual(check["status"], "ok")
            self.assertIn("présente", check["message"])

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

    def test_probe_mcp_successful_handshake_is_ok(self):
        """`--probe-mcp` lance un vrai serveur : ici un stub minimal qui
        répond correctement à `initialize`, pour couvrir le chemin ✅ du
        handshake (distinct de la simple présence)."""
        with Sandbox() as sb:
            responder = sb.root / "responder_mcp.py"
            responder.write_text(
                "import sys, json\n"
                "line = sys.stdin.readline()\n"
                "req = json.loads(line)\n"
                "print(json.dumps({'jsonrpc': '2.0', 'id': req.get('id', 1), 'result': {}}))\n"
                "sys.stdout.flush()\n"
            )
            (sb.repo / ".mcp.json").write_text(json.dumps({
                "mcpServers": {"garmin": {"command": sys.executable, "args": [str(responder)], "env": {}}}
            }))
            proc = sb.script(
                "coach_doctor.py", "--json", "--probe-mcp", "--tokens-dir", str(_fresh_tokens_dir(sb)),
            )
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertEqual(check["status"], "ok")

    def test_probe_mcp_timeout_kills_process_group(self):
        """Un serveur qui ne répond jamais doit rendre un ⚠️ borné dans le
        temps (`ARC_MCP_PROBE_TIMEOUT_S`, levier de test) — ET son groupe de
        process (petits-enfants compris) doit être terminé, pas seulement le
        process de tête (revue PR #76, blocage n°2 : `start_new_session` +
        `os.killpg`)."""
        with Sandbox() as sb:
            pid_file = sb.root / "child.pid"
            sleeper = sb.root / "slow_mcp.py"
            sleeper.write_text(
                "import subprocess, sys, time\n"
                f"child = subprocess.Popen(['sleep', '60'])\n"
                f"with open({str(pid_file)!r}, 'w') as f:\n"
                "    f.write(str(child.pid))\n"
                "time.sleep(60)\n"
            )
            (sb.repo / ".mcp.json").write_text(json.dumps({
                "mcpServers": {"garmin": {"command": sys.executable, "args": [str(sleeper)], "env": {}}}
            }))
            start = time.time()
            proc = sb.script(
                "coach_doctor.py", "--json", "--probe-mcp", "--tokens-dir", str(_fresh_tokens_dir(sb)),
                ARC_MCP_PROBE_TIMEOUT_S="1",
            )
            elapsed = time.time() - start
            self.assertLess(elapsed, 20, "le probe doit respecter son propre timeout")
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertEqual(check["status"], "warning")
            # Laisser un instant au système pour terminer le groupe après SIGKILL.
            deadline = time.time() + 3
            while not pid_file.exists() and time.time() < deadline:
                time.sleep(0.1)
            self.assertTrue(pid_file.exists(), "le petit-enfant n'a jamais démarré")
            child_pid = int(pid_file.read_text().strip())
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)


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

    def test_multiline_bullet_after_unfilled_field_is_not_a_false_positive(self):
        """RÉGRESSION (revue PR #76, should-fix n°3) : une regex `.*` naïve
        sur `:\\s*(.*)$` peut « voir » la puce suivante comme la valeur de la
        précédente selon comment le texte est reformaté. `arc_legacy.parse_profile`
        (même analyseur que l'index) ne doit pas se laisser abuser."""
        with Sandbox() as sb:
            profile = sb.repo / "planning" / "Runner_Profile.md"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(
                "## Physiologie\n\n"
                "- **FC max** : <!-- à renseigner -->\n"
                "- **FC de repos de référence** : 48\n"
            )
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "athlete_profile")
            self.assertEqual(check["status"], "info")
            self.assertIn("FC max", check["message"])


class TestConfigFilesTomlValidation(InstallAsserts):
    def test_invalid_toml_is_error(self):
        with Sandbox() as sb:
            (sb.repo / "config" / "workspace.user.toml").write_text("[notifications\nprovider = ntfy\n")
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertFailed(proc)
            check = _find(json.loads(proc.stdout), "config_files")
            self.assertEqual(check["status"], "error")

    def test_missing_workspace_toml_is_error_even_with_user_toml_present(self):
        """Nit (revue PR #76) : un `workspace.user.toml` sans les défauts
        versionnés à côté est aussi cassé qu'une absence totale de config."""
        with Sandbox() as sb:
            (sb.repo / "config" / "workspace.toml").unlink()
            (sb.repo / "config" / "workspace.user.toml").write_text('[language]\ndocuments = "fr"\n')
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertFailed(proc)
            check = _find(json.loads(proc.stdout), "config_files")
            self.assertEqual(check["status"], "error")

    def test_python_below_311_is_warning_not_false_ok(self):
        """Should-fix n°4 (revue PR #76) : `ARC_FORCE_TOML_FALLBACK` verrouille
        le chemin < 3.11 sans dépendre de la version de Python de la machine
        de test — un TOML par ailleurs valide doit rester un avertissement
        explicite, pas un ✅ qui prétendrait avoir validé strictement."""
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)),
                ARC_FORCE_TOML_FALLBACK="1",
            )
            self.assertSucceeded(proc)
            check = _find(json.loads(proc.stdout), "config_files")
            self.assertEqual(check["status"], "warning")
            self.assertIn("3.11", check["message"])


class TestMcpJsonMalformedInputs(InstallAsserts):
    """`.mcp.json` mal formé (liste au lieu d'objet, args en chaîne, env non
    stringifiable...) : jamais de trace Python (revue PR #76, should-fix n°5)."""

    def test_mcp_servers_as_list_falls_back_to_default(self):
        with Sandbox() as sb:
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": []}))
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertNotIn("Traceback", proc.stderr)
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertIn(check["status"], ("ok", "error"))

    def test_args_as_string_falls_back_to_default(self):
        with Sandbox() as sb:
            (sb.repo / ".mcp.json").write_text(json.dumps({
                "mcpServers": {"garmin": {"command": "garmin-mcp", "args": "stdio"}}
            }))
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertNotIn("Traceback", proc.stderr)
            check = _find(json.loads(proc.stdout), "garmin_mcp")
            self.assertEqual(check["status"], "ok")

    def test_non_string_env_values_are_dropped(self):
        with Sandbox() as sb:
            (sb.repo / ".mcp.json").write_text(json.dumps({
                "mcpServers": {"garmin": {"command": "garmin-mcp", "args": ["stdio"], "env": {"X": 1}}}
            }))
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            self.assertNotIn("Traceback", proc.stderr)
            self.assertSucceeded(proc)


class TestNowArgument(InstallAsserts):
    def test_trailing_z_is_accepted_on_any_python(self):
        with Sandbox() as sb:
            tokens_dir = _fresh_tokens_dir(sb)
            proc = sb.script(
                "coach_doctor.py", "--json", "--now", "2026-09-24T12:00:00Z", "--tokens-dir", str(tokens_dir),
            )
            self.assertSucceeded(proc)

    def test_garbage_now_is_a_clean_error_not_a_traceback(self):
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--json", "--now", "not-a-date",
                "--tokens-dir", str(_fresh_tokens_dir(sb)),
            )
            self.assertFailed(proc)
            self.assertNotIn("Traceback", proc.stderr)


class TestIndexFreshness(InstallAsserts):
    def _build_real_index(self, sb: Sandbox) -> None:
        proc = sb.run(["python3", str(sb.repo / "scripts" / "arc_index.py")])
        self.assertSucceeded(proc, "construction de l'index réel via arc_index.py")

    def test_no_index_is_info(self):
        with Sandbox() as sb:
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "info")

    def test_stale_index_against_real_index_is_warning(self):
        """Palier PR #76 (should-fix n°6) : contre un VRAI index construit par
        `arc_index.py`, pas une base vide qui tombe sur la branche
        « illisible » sans jamais exercer la logique de fraîcheur."""
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text("# Séance\n")
            self._build_real_index(sb)

            # Un fichier plus récent que l'index construit ci-dessus.
            time.sleep(1.1)
            (activities / "2026-09-25_running.md").write_text("# Séance suivante\n")

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "warning")

    def test_fresh_index_against_real_index_is_ok(self):
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text("# Séance\n")
            self._build_real_index(sb)

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "ok")

    def test_deleted_file_still_in_index_is_warning(self):
        """Nit (revue PR #76) : un fichier supprimé du workspace mais encore
        référencé dans `.arc/coach.db` doit être détecté, pas seulement un
        index « plus vieux » qu'un fichier existant."""
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            doomed = activities / "2026-09-24_running.md"
            doomed.write_text("# Séance\n")
            self._build_real_index(sb)
            doomed.unlink()

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "warning")
            self.assertIn("supprimé", check["message"])


class TestOutOfContract(InstallAsserts):
    def test_out_of_contract_counted_against_real_index(self):
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text(
                "# Séance sans bloc ```arc — hors contrat\n\nTexte libre uniquement.\n"
            )
            proc = sb.run(["python3", str(sb.repo / "scripts" / "arc_index.py")])
            self.assertSucceeded(proc)

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "out_of_contract")
            self.assertEqual(check["status"], "warning")
            self.assertIn("1 fichier", check["message"])


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

    def test_single_check_flag_runs_only_that_check(self):
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--json", "--check", "garmin_token",
                "--tokens-dir", str(_fresh_tokens_dir(sb)),
            )
            self.assertSucceeded(proc)
            payload = json.loads(proc.stdout)
            self.assertEqual([c["id"] for c in payload["checks"]], ["garmin_token"])


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
