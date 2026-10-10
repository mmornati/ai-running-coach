"""Palier A — `coach doctor` (#31) : diagnostic d'installation en une commande.

Chaque cas verrouille un statut par vérification pour un scénario donné, dans
le bac à sable (`tests/lib/sandbox.py`) — jamais contre le vrai HOME ou la
vraie crontab du contributeur. `--tokens-dir` et `--now` rendent le check
`garmin_token` déterministe sans dépendre de l'horloge de la machine.
"""

from __future__ import annotations

import json
import os
import re
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

    def test_fit_sample_files_never_trigger_a_false_deleted_warning(self):
        """Régression (#42, revue PR #87, blocker 2) : `activities/fit/*.json` (échantillons
        FIT, table dédiée `sample_file`) ne doit JAMAIS apparaître dans `source_file`
        (celui-ci est comparé à `arc_index.discover()`, qui ne liste que les Markdown du
        contrat) — sinon chaque fichier FIT ingéré déclencherait un faux « fichier(s)
        supprimé(s) » permanent, jamais nettoyé même par --rebuild."""
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text(
                "# Séance\n\n```arc\n"
                '{"arc": 1, "kind": "activity", "date": "2026-09-24", "sport": "trail", '
                '"duration_s": 3600, "distance_m": 10000, "garmin_activity_id": 90000000005}\n'
                "```\n"
            )
            fit_dir = activities / "fit"
            fit_dir.mkdir(parents=True, exist_ok=True)
            (fit_dir / "90000000005.json").write_text(json.dumps({
                "activity_id": 90000000005,
                "records": [{"t_s": t, "distance_m": float(t) * 2.5, "altitude_m": 0.0,
                             "hr_bpm": 140.0, "speed_ms": 2.5, "cadence_spm": 170.0} for t in range(10)],
            }))
            self._build_real_index(sb)

            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "ok", check)

            # Idem après --rebuild : le bug historique ne se serait jamais résorbé.
            proc = sb.run(["python3", str(sb.repo / "scripts" / "arc_index.py"), "--rebuild"])
            self.assertSucceeded(proc)
            proc = sb.script("coach_doctor.py", "--json", "--tokens-dir", str(_fresh_tokens_dir(sb)))
            check = _find(json.loads(proc.stdout), "index_freshness")
            self.assertEqual(check["status"], "ok", check)


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

    def test_orphan_fit_sample_never_counted_as_out_of_contract(self):
        """Régression (#42, revue PR #87, blocker 2) : un fichier FIT sans activité
        correspondante (`activities/fit/999….json`) est une situation normale (FIT
        téléchargé avant le Markdown) — jamais une dette de contrat comptée par
        `out_of_contract`, qui ne doit voir QUE le fichier Markdown réellement hors
        contrat ci-dessous (comptage à « 1 », pas « 2 »)."""
        with Sandbox() as sb:
            activities = sb.repo / "activities"
            activities.mkdir(parents=True, exist_ok=True)
            (activities / "2026-09-24_running.md").write_text(
                "# Séance sans bloc ```arc — hors contrat\n\nTexte libre uniquement.\n"
            )
            fit_dir = activities / "fit"
            fit_dir.mkdir(parents=True, exist_ok=True)
            (fit_dir / "999999999999.json").write_text(json.dumps({
                "activity_id": 999999999999,
                "records": [{"t_s": 0, "distance_m": 0.0, "altitude_m": 0.0,
                             "hr_bpm": 140.0, "speed_ms": 2.5, "cadence_spm": 170.0}],
            }))
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


class TestWatchHeartbeat(InstallAsserts):
    """Mode surveillance : le cron existe, mais le watcher a-t-il tourné récemment ?"""

    NOW = "2026-09-27T09:00:00+00:00"
    CRON = '*/15 * * * * ARC_WORKSPACE="/ws" python3 "/e/scripts/garmin_watch.py" >/dev/null 2>&1 # ai-running-coach daily-sync\n'

    def _check(self, sb: Sandbox, last_check_utc: str | None):
        from datetime import datetime

        ws = sb.root / "ws"
        (ws / "logs").mkdir(parents=True)
        if last_check_utc is not None:
            # Le watcher écrit l'heure LOCALE naïve : même conversion que le doctor.
            local = datetime.fromisoformat(last_check_utc).astimezone().replace(tzinfo=None)
            (ws / "logs/.watch-state.json").write_text(json.dumps({
                "last_check": local.isoformat(timespec="seconds"),
                "runs": {"date": local.date().isoformat(), "count": 2},
            }))
        sb.set_crontab(self.CRON)
        proc = sb.script(
            "coach_doctor.py", "--json", "--workspace", str(ws), "--tokens-dir", str(_fresh_tokens_dir(sb)),
            ARC_FAKE_UNAME="Linux", ARC_DOCTOR_NOW=self.NOW,
        )
        return _find(json.loads(proc.stdout), "daily_sync_scheduled")

    def test_recent_heartbeat_is_ok(self):
        with Sandbox() as sb:
            check = self._check(sb, "2026-09-27T08:50:00+00:00")
            self.assertEqual(check["status"], "ok")
            self.assertIn("10 min", check["message"])
            self.assertIn("2 run(s)", check["message"])

    def test_stale_heartbeat_is_warning(self):
        with Sandbox() as sb:
            check = self._check(sb, "2026-09-27T07:00:00+00:00")
            self.assertEqual(check["status"], "warning")
            self.assertIn("silencieuse", check["message"])

    def test_never_ran_is_warning(self):
        with Sandbox() as sb:
            check = self._check(sb, None)
            self.assertEqual(check["status"], "warning")
            self.assertIn("jamais", check["message"])


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


class TestFitReader(InstallAsserts):
    """`fitparse` dans l'environnement MCP de la source : sans lui, les FIT
    téléchargés ne sont jamais lus (KPI fins vides). Cas typique : installation
    intervals.icu mise à jour par `git pull` sans relancer `install.sh`.
    L'interpréteur de l'outil est simulé par un script qui réussit ou échoue
    l'`import fitparse` — aucune dépendance au vrai paquet."""

    def _fake_tool_python(self, sb, tool, *, has_fitparse):
        py = sb.home / f".local/share/uv/tools/{tool}/bin/python3"
        py.parent.mkdir(parents=True)
        py.write_text(f"#!/bin/sh\nexit {0 if has_fitparse else 1}\n")
        py.chmod(0o755)

    def _check(self, sb, source=None):
        if source:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text(f'[data]\nsource = "{source}"\n')
        proc = sb.script("coach_doctor.py", "--json", "--workspace", str(sb.repo),
                         "--tokens-dir", str(_fresh_tokens_dir(sb)), "--check", "fit_reader")
        return proc, _find(json.loads(proc.stdout), "fit_reader")

    def test_intervals_env_without_fitparse_is_a_warning_with_the_install_fix(self):
        with Sandbox() as sb:
            self._fake_tool_python(sb, "intervals-icu-mcp", has_fitparse=False)
            proc, check = self._check(sb, "intervals")
            self.assertSucceeded(proc)   # warning : jamais un code de sortie en échec
            self.assertEqual(check["status"], "warning")
            self.assertIn("fitparse", check["message"])
            self.assertEqual(check["fix"], "./install.sh --source intervals")

    def test_intervals_env_with_fitparse_is_ok(self):
        with Sandbox() as sb:
            self._fake_tool_python(sb, "intervals-icu-mcp", has_fitparse=True)
            _, check = self._check(sb, "intervals")
            self.assertEqual(check["status"], "ok")

    def test_missing_environment_is_a_warning(self):
        with Sandbox() as sb:
            _, check = self._check(sb, "intervals")
            self.assertEqual(check["status"], "warning")
            self.assertIn("intervals-icu-mcp", check["message"])

    def test_default_source_checks_the_garmin_environment(self):
        with Sandbox() as sb:
            self._fake_tool_python(sb, "garmin-mcp", has_fitparse=True)
            _, check = self._check(sb)
            self.assertEqual(check["status"], "ok")
            self.assertIn("garmin-mcp", check["message"])


class TestIntervalsMcpPin(InstallAsserts):
    """#165 : le serveur intervals.icu installé par `uv tool` est-il au commit épinglé par install.sh ?
    Une installation antérieure (eddmann@cb91d4a) expose des outils sans préfixe `icu_` : ⚠️ + commande
    de mise à jour. Origine lue dans le `direct_url.json` de l'environnement — simulé ici."""

    LEGACY = "https://github.com/eddmann/intervals-icu-mcp"
    FORK = "https://github.com/hhopke/intervals-icu-mcp"

    @staticmethod
    def _pinned_commit(sb):
        text = (sb.repo / "install.sh").read_text(encoding="utf-8")
        return re.search(r'^INTERVALS_MCP_REF="git\+[^@"]+@([0-9a-f]{40})"', text, re.MULTILINE).group(1)

    def _fake_install(self, sb, url, commit):
        env = sb.home / ".local/share/uv/tools/intervals-icu-mcp"
        py = env / "bin/python3"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
        dist = env / "lib/python3.12/site-packages/intervals_icu_mcp-5.5.0.dist-info"
        dist.mkdir(parents=True)
        (dist / "direct_url.json").write_text(json.dumps({"url": url, "vcs_info": {"vcs": "git", "commit_id": commit}}))

    def _check(self, sb, source="intervals"):
        if source:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text(f'[data]\nsource = "{source}"\n')
        proc = sb.script("coach_doctor.py", "--json", "--workspace", str(sb.repo),
                         "--tokens-dir", str(_fresh_tokens_dir(sb)), "--check", "intervals_mcp_pin")
        return proc, _find(json.loads(proc.stdout), "intervals_mcp_pin")

    def test_legacy_url_written_with_dot_git_is_still_the_legacy_server(self):
        with Sandbox() as sb:
            self._fake_install(sb, self.LEGACY + ".git/", "cb91d4a0f3b4dc21f57421e029c07a8e9af11649")
            _, check = self._check(sb)
            self.assertEqual(check["status"], "warning")

    def test_legacy_eddmann_install_is_a_warning_with_the_update_command(self):
        with Sandbox() as sb:
            self._fake_install(sb, self.LEGACY, "cb91d4a0f3b4dc21f57421e029c07a8e9af11649")
            proc, check = self._check(sb)
            self.assertSucceeded(proc)   # warning : jamais un code de sortie en échec
            self.assertEqual(check["status"], "warning")
            self.assertIn("eddmann", check["message"])
            self.assertIn("icu_", check["message"])
            self.assertEqual(check["fix"], "./install.sh --source intervals")

    def test_install_at_the_pinned_commit_is_ok(self):
        with Sandbox() as sb:
            self._fake_install(sb, self.FORK, self._pinned_commit(sb))
            _, check = self._check(sb)
            self.assertEqual(check["status"], "ok")

    def test_pinned_install_with_world_readable_credentials_is_a_warning(self):
        with Sandbox() as sb:
            self._fake_install(sb, self.FORK, self._pinned_commit(sb))
            env_dir = sb.home / ".config/ai-running-coach/intervals-icu-mcp"
            env_dir.mkdir(parents=True)
            env_file = env_dir / ".env"
            env_file.write_text("INTERVALS_ICU_API_KEY=secret-value\n")
            env_file.chmod(0o644)
            proc, check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertTrue(check["fix"].startswith("chmod 600 "))
            self.assertNotIn("secret-value", proc.stdout)
            env_file.chmod(0o600)
            _, check = self._check(sb)
            self.assertEqual(check["status"], "ok")

    def test_older_fork_commit_is_informational(self):
        with Sandbox() as sb:
            self._fake_install(sb, self.FORK, "0" * 40)
            _, check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertEqual(check["fix"], "./install.sh --source intervals")

    def test_custom_origin_is_left_alone(self):
        with Sandbox() as sb:
            self._fake_install(sb, "https://example.org/my-fork", "1" * 40)
            _, check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertIsNone(check["fix"])

    def test_unreadable_origin_is_informational(self):
        with Sandbox() as sb:
            _, check = self._check(sb)          # aucun environnement uv
            self.assertEqual(check["status"], "info")

    def test_garmin_source_is_not_applicable_even_with_a_legacy_install(self):
        """Critère d'acceptation : les utilisateurs `[data].source = "garmin"` (défaut) ne sont pas touchés."""
        with Sandbox() as sb:
            self._fake_install(sb, self.LEGACY, "cb91d4a0f3b4dc21f57421e029c07a8e9af11649")
            for source in (None, "garmin"):
                _, check = self._check(sb, source or "garmin")
                self.assertEqual(check["status"], "info")
                self.assertIsNone(check["fix"])


class TestDataSourceAware(InstallAsserts):
    """`[data].source = "intervals"` (#68) : ni `garmin_token` ni `garmin_mcp`
    ne doivent rapporter une panne — l'athlète n'a jamais eu de compte
    Garmin, ces deux vérifications n'ont rien à évaluer (revue PR #116)."""

    def test_garmin_checks_become_info_under_intervals_source(self):
        with Sandbox() as sb:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text('[data]\nsource = "intervals"\n')
            proc = sb.script(
                "coach_doctor.py", "--json", "--workspace", str(sb.repo),
                "--tokens-dir", str(sb.root / "tokens-absent"),
            )
            self.assertSucceeded(proc)
            payload = json.loads(proc.stdout)
            token_check = _find(payload, "garmin_token")
            mcp_check = _find(payload, "garmin_mcp")
            self.assertEqual(token_check["status"], "info")
            self.assertEqual(mcp_check["status"], "info")
            self.assertNotIn("expires_at", token_check)

    def test_garmin_checks_run_normally_under_default_source(self):
        with Sandbox() as sb:
            proc = sb.script(
                "coach_doctor.py", "--json", "--workspace", str(sb.repo),
                "--tokens-dir", str(sb.root / "tokens-absent"),
            )
            # Tokens absents => statut non "info" (avertissement/erreur réel),
            # PAS le succès de commande : seul le comportement du check
            # garmin_token nous intéresse ici, pas le code de sortie global.
            payload = json.loads(proc.stdout)
            token_check = _find(payload, "garmin_token")
            self.assertNotEqual(token_check["status"], "info")
            self.assertIn("expires_at", token_check)


class TestWeightSync(InstallAsserts):
    """#222 — `weight_sync` : liste blanche des pesées, statique, jamais un avertissement."""

    def _check(self, sb, tools=None):
        if tools is not None:
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {
                "command": "garmin-mcp", "args": ["stdio"], "env": {"GARMIN_ENABLED_TOOLS": tools}}}}))
        proc = sb.script("coach_doctor.py", "--json", "--check", "weight_sync",
                         "--tokens-dir", str(_fresh_tokens_dir(sb)))
        self.assertSucceeded(proc)
        return _find(json.loads(proc.stdout), "weight_sync")

    def test_old_whitelist_is_info_with_reinstall_fix(self):
        with Sandbox() as sb:
            check = self._check(sb, "get_activities,get_gear")
            self.assertEqual(check["status"], "info")
            self.assertIn("get_daily_weigh_ins", check["message"])
            self.assertIn("install.sh", check["fix"])

    def test_current_whitelist_is_ok(self):
        with Sandbox() as sb:
            self.assertEqual(self._check(sb, "get_activities,get_daily_weigh_ins,get_weigh_ins")["status"], "ok")

    def test_unreadable_whitelist_is_ok(self):
        with Sandbox() as sb:
            self.assertEqual(self._check(sb)["status"], "ok")

    def test_non_garmin_source_is_info(self):
        with Sandbox() as sb:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text('[data]\nsource = "strava"\n')
            self.assertEqual(self._check(sb)["status"], "info")


class TestGearSync(InstallAsserts):
    """#133 — `gear_sync` : vérification STATIQUE (liste blanche de `.mcp.json` + profil), jamais d'appel Garmin."""

    PROFILE = (
        "# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
        "- Nike Pegasus — id: pegasus — garmin: a1b2c3d4e5f60718293a4b5c6d7e8f90\n"
        "- Salomon S/Lab — id: slab\n"
        "- Vieille paire — id: vieille (retirée)\n"
    )

    def _check(self, sb):
        proc = sb.script("coach_doctor.py", "--json", "--check", "gear_sync",
                         "--tokens-dir", str(_fresh_tokens_dir(sb)))
        self.assertSucceeded(proc)
        return _find(json.loads(proc.stdout), "gear_sync")

    def _mcp(self, sb, tools):
        (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {
            "command": "garmin-mcp", "args": ["stdio"], "env": {"GARMIN_ENABLED_TOOLS": tools}}}}))

    def _profile(self, sb, text):
        path = sb.repo / "planning" / "Runner_Profile.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_old_whitelist_is_warning_with_reinstall_fix(self):
        with Sandbox() as sb:
            self._mcp(sb, "get_activities,get_sleep_data")
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("get_gear", check["message"])
            self.assertIn("install.sh", check["fix"])

    def test_unlinked_active_pair_is_info_and_retired_ignored(self):
        with Sandbox() as sb:
            self._mcp(sb, "get_gear,get_activity_gear")
            self._profile(sb, self.PROFILE)
            check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertIn("Salomon S/Lab", check["message"])
            self.assertNotIn("Pegasus", check["message"])
            self.assertNotIn("Vieille", check["message"])

    def test_all_linked_is_ok(self):
        with Sandbox() as sb:
            self._mcp(sb, "get_gear,get_activity_gear")
            self._profile(sb, "# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: a1b2c3d4e5f60718293a4b5c6d7e8f90\n")
            self.assertEqual(self._check(sb)["status"], "ok")

    def test_unreadable_whitelist_is_never_a_warning(self):
        with Sandbox() as sb:
            self._profile(sb, "# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: a1b2c3d4e5f60718293a4b5c6d7e8f90\n")
            check = self._check(sb)
            self.assertEqual(check["status"], "ok")
            self.assertIn("non lue", check["message"])
            self.assertNotIn("autoris", check["message"])

    def test_intervals_source_is_info(self):
        with Sandbox() as sb:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text('[data]\nsource = "intervals"\n')
            check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertIn("get_gear_list", check["message"])

    def test_invalid_mcp_json_never_claims_the_tools_are_allowed(self):
        with Sandbox() as sb:
            (sb.repo / ".mcp.json").write_text("{pas du json")
            self._profile(sb, "# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: a1b2c3d4e5f60718293a4b5c6d7e8f90\n")
            check = self._check(sb)
            self.assertNotIn("autoris", check["message"])
            self.assertIn("non lue", check["message"])

    def test_leanproxy_yaml_whitelist_is_read_and_fix_is_manual(self):
        with Sandbox() as sb:
            yaml_path = sb.home / ".config" / "leanproxy_servers.yaml"
            yaml_path.parent.mkdir(parents=True, exist_ok=True)
            yaml_path.write_text('servers:\n  - name: garmin\n    env:\n      - GARMIN_ENABLED_TOOLS: "get_activities"\n')
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("leanproxy", check["message"])
            self.assertIn("leanproxy_servers.yaml", check["fix"])
            self.assertIn("n'écrit", check["message"])

    def test_malformed_garmin_segment_is_flagged_not_reported_missing(self):
        with Sandbox() as sb:
            self._mcp(sb, "get_gear,get_activity_gear")
            self._profile(sb, "# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: abc\n- Salomon S/Lab\n")
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("illisible", check["message"])
            self.assertIn("Nike Pegasus", check["message"])

    def test_duplicate_uuid_across_bullets_is_flagged(self):
        with Sandbox() as sb:
            self._mcp(sb, "get_gear,get_activity_gear")
            uuid = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
            self._profile(sb, f"# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: {uuid}\n- Salomon S/Lab — garmin: {uuid}\n")
            check = self._check(sb)
            self.assertEqual(check["status"], "warning")
            self.assertIn("même uuid", check["message"])

    def test_ignored_pair_is_never_reclaimed(self):
        with Sandbox() as sb:
            self._mcp(sb, "get_gear,get_activity_gear")
            self._profile(sb, "# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: a1b2c3d4e5f60718293a4b5c6d7e8f90\n"
                          "- Brooks Ghost — garmin: c0ffee00c0ffee00c0ffee00c0ffee00 (ignorée)\n")
            self.assertEqual(self._check(sb)["status"], "ok")


class TestGearHistory(InstallAsserts):
    """#145 — `gear_history` : information STATIQUE (blocs `arc` de `activities/`, aucun appel Garmin) quand
    beaucoup de séances portent un `garmin_activity_id` et aucune de `gear_id`."""

    def _activities(self, sb, n, gear_on=0):
        folder = sb.repo / "activities"
        folder.mkdir(exist_ok=True)
        for i in range(n):
            extra = {"gear_id": "pegasus", "gear_source": "chat"} if i < gear_on else {}
            block = {"arc": 1, "kind": "activity", "date": f"2026-03-{i + 1:02d}", "sport": "trail",
                     "duration_s": 3600, "garmin_activity_id": 1000 + i, **extra}
            (folder / f"2026-03-{i + 1:02d}_trail.md").write_text(f"# S\n\n```arc\n{json.dumps(block)}\n```\n")

    def _check(self, sb):
        proc = sb.script("coach_doctor.py", "--json", "--check", "gear_history",
                         "--tokens-dir", str(_fresh_tokens_dir(sb)))
        self.assertSucceeded(proc)
        return _find(json.loads(proc.stdout), "gear_history")

    def test_many_ids_no_gear_is_info_pointing_to_backfill(self):
        with Sandbox() as sb:
            self._activities(sb, 8)
            check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertIn("8 séance(s) sur 8", check["message"])
            self.assertIn("garmin_gear_backfill.py", check["fix"])

    def test_one_declared_gear_id_does_not_silence_the_signal(self):
        with Sandbox() as sb:
            self._activities(sb, 8, gear_on=1)
            check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertIn("7 séance(s) sur 8", check["message"])

    def test_mostly_attributed_or_few_activities_is_ok(self):
        with Sandbox() as sb:
            self._activities(sb, 8, gear_on=5)     # 3/8 sans gear_id : sous le seuil de 50 %
            self.assertEqual(self._check(sb)["status"], "ok")
        with Sandbox() as sb:
            self._activities(sb, 8, gear_on=4)     # exactement 50 % : pas « plus de la moitié »
            self.assertEqual(self._check(sb)["status"], "ok")
        with Sandbox() as sb:
            self._activities(sb, 3)
            self.assertEqual(self._check(sb)["status"], "ok")

    def test_intervals_source_is_info_without_backfill_hint(self):
        with Sandbox() as sb:
            (sb.repo / "config").mkdir(exist_ok=True)
            (sb.repo / "config/workspace.user.toml").write_text('[data]\nsource = "intervals"\n')
            self._activities(sb, 8)
            check = self._check(sb)
            self.assertEqual(check["status"], "info")
            self.assertIsNone(check["fix"])


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
                "gear_sync", "gear_history", "fit_reader", "intervals_mcp_pin",
                "llm_config", "chat_service", "opencode_cli", "strava_connection", "telegram", "weight_sync", "openwearables",
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


class TestOpenWearables(InstallAsserts):
    """#220 — `openwearables` : configuration + clé d'API (mode 600, valeur jamais affichée) sans réseau ;
    avec `--probe-ow`, UN `arc_openwearables.py check`. Hors opt-in : `info`, rien d'alarmant."""

    SECRET = "sk-0123456789abcdef0123456789abcdef"      # = FAKE_KEY du faux serveur

    def _setup(self, sb, provider="oura", mode=0o600, source="openwearables", key=True, base="http://127.0.0.1:9"):
        (sb.repo / "config").mkdir(exist_ok=True)
        lines = []
        if source:
            lines += ["[health]", f'source = "{source}"', ""]
        lines += ["[health.openwearables]", f'provider = "{provider}"', f'base_url = "{base}"',
                  f'api_key_file = "{sb.root / "ow.key"}"']
        (sb.repo / "config/workspace.user.toml").write_text("\n".join(lines) + "\n")
        key_file = sb.root / "ow.key"
        if key:
            key_file.write_text(self.SECRET + "\n")
            key_file.chmod(mode)
        return key_file

    def _run(self, sb, *extra, **env):
        proc = sb.script("coach_doctor.py", "--json", "--check", "openwearables",
                         "--tokens-dir", str(_fresh_tokens_dir(sb)), *extra, **env)
        out = json.loads(proc.stdout)
        self.assertNotIn(self.SECRET, proc.stdout + proc.stderr)
        return proc, _find(out, "openwearables")

    def _bundle(self, hours_ago=2):
        import copy
        from tests.data.test_arc_openwearables import load
        bundle = copy.deepcopy(load("oura"))
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        bundle["connections"][0]["last_synced_at"] = stamp
        return bundle

    def test_not_opted_in_is_info_and_calm(self):
        with Sandbox() as sb:
            for source in (None, "primary"):
                self._setup(sb, source=source, key=False)
                proc, check = self._run(sb, "--probe-ow")
                self.assertEqual(check["status"], "info")
                self.assertEqual(proc.returncode, 0)
                self.assertNotIn("clé", check["message"])

    def test_default_run_makes_no_network_call_and_is_ok_when_configured(self):
        with Sandbox() as sb:
            self._setup(sb)
            proc, check = self._run(sb)
            self.assertEqual(check["status"], "ok", check)
            self.assertIn("--probe-ow", check["message"])
            self.assertIn("0.9.0", check["message"])

    def test_mode_644_is_an_error_with_chmod_fix(self):
        with Sandbox() as sb:
            self._setup(sb, mode=0o644)
            proc, check = self._run(sb)
            self.assertEqual(check["status"], "error")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("chmod 600", check["fix"])

    def test_missing_key_file_is_an_error(self):
        with Sandbox() as sb:
            self._setup(sb, key=False)
            proc, check = self._run(sb)
            self.assertEqual(check["status"], "error")
            self.assertIn("install.sh", check["fix"])

    def test_empty_unknown_and_refused_providers_are_flagged(self):
        with Sandbox() as sb:
            for provider, word in (("", "vide"), ("ouraa", "inconnu"), ("garmin", "refusé"), ("strava", "refusé")):
                self._setup(sb, provider=provider)
                _, check = self._run(sb)
                self.assertEqual(check["status"], "error", provider)
                self.assertIn(word, check["message"])
                self.assertIn("docs/open-wearables.md#installation", check["fix"])

    def test_nominal_probe_is_ok_with_the_tested_version(self):
        from tests.data.test_arc_openwearables import OWStub
        with Sandbox() as sb, OWStub(self._bundle(2)) as stub:
            self._setup(sb, base=stub.base)
            proc, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "ok", check)
            self.assertRegex(check["message"], r"il y a [12] h")
            self.assertIn("testée : 0.9.0", check["message"])
            self.assertTrue(stub.log)

    def test_rejected_key_is_an_error_without_leaking_it(self):
        from tests.data.test_arc_openwearables import OWStub
        with Sandbox() as sb, OWStub(self._bundle(2), key="une-autre-cle") as stub:
            self._setup(sb, base=stub.base)
            proc, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "error")
            self.assertIn("401", check["message"])
            self.assertEqual(proc.returncode, 1)

    def test_dead_instance_is_an_error(self):
        with Sandbox() as sb:
            self._setup(sb, base="http://127.0.0.1:9")
            _, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "error")
            self.assertIn("injoignable", check["message"])

    def test_stale_sync_is_a_warning(self):
        from tests.data.test_arc_openwearables import OWStub
        with Sandbox() as sb, OWStub(self._bundle(100)) as stub:
            self._setup(sb, base=stub.base)
            proc, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "warning")
            self.assertIn("stale_after_h", check["message"])
            self.assertEqual(proc.returncode, 0)

    def test_inactive_provider_and_unknown_shape_are_warnings(self):
        from tests.data.test_arc_openwearables import OWStub
        bundle = self._bundle(2)
        bundle["connections"][0]["status"] = "expired"
        with Sandbox() as sb, OWStub(bundle) as stub:
            self._setup(sb, base=stub.base)
            _, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "warning")
            self.assertIn("non actif", check["message"])
        bundle = self._bundle(2)
        bundle["sleep"] = {"data": [{"unexpected": 1}], "pagination": {}}
        with Sandbox() as sb, OWStub(bundle) as stub:
            self._setup(sb, base=stub.base)
            _, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "warning")
            self.assertIn("non testée", check["message"])

    def test_two_users_without_user_id_is_a_warning(self):
        from tests.data.test_arc_openwearables import OWStub, load
        bundle = self._bundle(2)
        two = load("users_two")
        bundle["users"] = two["users"] if "users" in two else two
        with Sandbox() as sb, OWStub(bundle) as stub:
            self._setup(sb, base=stub.base)
            _, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "warning")
            self.assertIn("user_id", check["fix"])

    def test_sdk_provider_without_connection_is_info_not_an_error(self):
        from tests.data.test_arc_openwearables import OWStub
        bundle = self._bundle(2)
        bundle["connections"] = []
        with Sandbox() as sb, OWStub(bundle) as stub:
            self._setup(sb, provider="apple", base=stub.base)
            proc, check = self._run(sb, "--probe-ow")
            self.assertEqual(check["status"], "info", check)
            self.assertIn("inconnue", check["message"])
            self.assertEqual(proc.returncode, 0)
