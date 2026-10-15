"""Palier A — scripts compagnons (arc_notify : setup-ntfy/notify, coach-remote)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox


class TestSetupNtfy(InstallAsserts):
    """0.1 — la génération du sujet aléatoire tue le script."""

    def test_interactive_run_completes(self):
        with Sandbox() as sb:
            (sb.repo / "config").mkdir(exist_ok=True)
            # réponses : serveur public (défaut), sujet suggéré (défaut)
            proc = sb.run_pty(
                [str(sb.repo / "scripts/setup-ntfy.sh"), "--no-test"],
                answers=["", ""],
            )
            self.assertSucceeded(proc, "setup-ntfy.sh interactif")

            cfg = sb.repo / "config/workspace.user.toml"
            self.assertFileContains(cfg, "[notifications]")
            self.assertFileContains(cfg, 'provider = "ntfy"')

            topic = re.search(r'ntfy_topic = "([^"]+)"', cfg.read_text())
            self.assertIsNotNone(topic, "aucun ntfy_topic écrit")
            self.assertRegex(
                topic.group(1),
                r"^running-coach-[a-z0-9]{8}$",
                "le sujet suggéré n'a pas été généré correctement",
            )

    def test_generated_topics_are_random(self):
        """Le générateur de sujet survit à `set -euo pipefail` et varie.

        Le pipeline `tr < /dev/urandom | head -c 8` rend bien 141 (SIGPIPE),
        mais il est imbriqué dans un argument de `printf`, où ce statut est
        écarté. Ce test verrouille la propriété qui compte : si quelqu'un
        réécrit `random_topic` en affectation directe (`v="$(...)"`), le statut
        redevient celui de la commande et le script meurt — ici.
        """
        topics = set()
        for _ in range(2):
            with Sandbox() as sb:
                proc = sb.run_pty(
                    [str(sb.repo / "scripts/setup-ntfy.sh"), "--no-test"],
                    answers=["", ""],
                )
                self.assertSucceeded(proc, "setup-ntfy.sh interactif")
                cfg = (sb.repo / "config/workspace.user.toml").read_text()
                match = re.search(r'ntfy_topic = "([^"]+)"', cfg)
                self.assertIsNotNone(match, f"aucun sujet écrit :\n{cfg}")
                topics.add(match.group(1))
        self.assertEqual(len(topics), 2, f"sujets identiques sur deux exécutions : {topics}")

    def test_non_interactive_requires_topic(self):
        with Sandbox() as sb:
            proc = sb.script("setup-ntfy.sh", "--no-test")
            self.assertFailed(proc, "mode non interactif sans --topic")
            self.assertOutputContains(proc, "--topic")

    def test_explicit_flags_write_config(self):
        with Sandbox() as sb:
            proc = sb.script(
                "setup-ntfy.sh",
                "--url", "https://ntfy.example.com",
                "--topic", "mon-sujet-secret",
                "--no-test",
            )
            self.assertSucceeded(proc)
            cfg = sb.repo / "config/workspace.user.toml"
            self.assertFileContains(cfg, 'ntfy_topic = "mon-sujet-secret"')
            self.assertFileContains(cfg, 'ntfy_url = "https://ntfy.example.com"')

    def test_rerun_does_not_duplicate_section(self):
        with Sandbox() as sb:
            for topic in ("premier", "second"):
                self.assertSucceeded(
                    sb.script("setup-ntfy.sh", "--url", "https://ntfy.sh",
                              "--topic", topic, "--no-test")
                )
            cfg = (sb.repo / "config/workspace.user.toml").read_text()
            self.assertEqual(cfg.count("[notifications]"), 1, f"section dupliquée :\n{cfg}")
            self.assertIn('ntfy_topic = "second"', cfg)

    def test_config_is_not_lost_on_failure(self):
        """La config personnelle ne doit pas disparaître si l'écriture échoue."""
        with Sandbox() as sb:
            cfg = sb.repo / "config/workspace.user.toml"
            cfg.parent.mkdir(exist_ok=True)
            cfg.write_text('[language]\ndocuments = "en"\n')
            self.assertSucceeded(
                sb.script("setup-ntfy.sh", "--url", "https://ntfy.sh", "--topic", "t", "--no-test")
            )
            self.assertFileContains(cfg, 'documents = "en"')


class TestNotify(InstallAsserts):
    """`scripts/arc_notify.py send` et sa cale `notify.sh` : ce qui arrive réellement chez ntfy."""

    def _config(self, sb: Sandbox, extra: str = "") -> None:
        cfg = sb.repo / "config/workspace.user.toml"
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(f'[notifications]\nprovider = "ntfy"\nntfy_topic = "sujet-test"\n{extra}')

    def test_shim_and_module_send_the_same_notification(self):
        for argv in (["scripts/notify.sh"], ["python3", "scripts/arc_notify.py", "send"]):
            with self.subTest(argv=argv[-1]), Sandbox() as sb:
                self._config(sb)
                cmd = [str(sb.repo / argv[0])] if len(argv) == 1 else [argv[0], str(sb.repo / argv[1]), argv[2]]
                proc = sb.run(cmd + ["--title", "🏃 Sync Garmin — à jour", "--priority", "4",
                                     "--tags", "running,warning", "Séances : à jour\nHRV : 52 ms"])
                self.assertSucceeded(proc)
                self.assertOutputContains(proc, "Notification envoyée")
                [call] = sb.ntfy_calls()
                self.assertEqual(call["path"], "/sujet-test")
                self.assertEqual(call["headers"]["Title"], "🏃 Sync Garmin — à jour")
                self.assertEqual(call["headers"]["Priority"], "4")
                self.assertEqual(call["headers"]["Tags"], "running,warning")
                self.assertEqual(call["body"], "Séances : à jour\nHRV : 52 ms")

    def test_message_starting_with_a_dash_is_a_message(self):
        with Sandbox() as sb:
            self._config(sb)
            proc = sb.script("notify.sh", "--title", "T", "-5 km aujourd'hui")
            self.assertSucceeded(proc)
            self.assertEqual(sb.ntfy_calls()[0]["body"], "-5 km aujourd'hui")

    def test_message_from_stdin(self):
        with Sandbox() as sb:
            self._config(sb)
            self.assertSucceeded(sb.script("notify.sh", "--title", "T", stdin="depuis stdin\n"))
            self.assertEqual(sb.ntfy_calls()[0]["body"], "depuis stdin\n")

    def test_token_is_sent_as_bearer_without_whitespace(self):
        with Sandbox() as sb:
            token = sb.home / "ntfy.token"
            token.write_text("tk_abc \n")
            self._config(sb, f'ntfy_token_file = "{token}"\n')
            self.assertSucceeded(sb.script("notify.sh", "x"))
            self.assertEqual(sb.ntfy_calls()[0]["headers"]["Authorization"], "Bearer tk_abc")

    def test_exit_codes(self):
        with Sandbox() as sb:                                  # provider none : 0, rien d'envoyé
            proc = sb.script("notify.sh", "x")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "Notifications désactivées")
            self.assertEqual(sb.ntfy_calls(), [])
        with Sandbox() as sb:                                  # sujet absent : 1
            cfg = sb.repo / "config/workspace.user.toml"
            cfg.parent.mkdir(exist_ok=True)
            cfg.write_text('[notifications]\nprovider = "ntfy"\n')
            proc = sb.script("notify.sh", "x")
            self.assertEqual(proc.returncode, 1)
            self.assertOutputContains(proc, "ntfy_topic manquant")
        with Sandbox() as sb:                                  # fichier token absent : 1
            self._config(sb, 'ntfy_token_file = "~/absent.token"\n')
            self.assertEqual(sb.script("notify.sh", "x").returncode, 1)
        with Sandbox() as sb:                                  # serveur injoignable : 2
            self._config(sb)
            proc = sb.script("notify.sh", "x", ARC_NTFY_URL="http://127.0.0.1:9")
            self.assertEqual(proc.returncode, 2)
            self.assertOutputContains(proc, "Échec de l'envoi")
        with Sandbox() as sb:                                  # aucun message : 1
            self._config(sb)
            self.assertEqual(sb.script("notify.sh").returncode, 1)

    def test_setup_keeps_the_rest_of_the_file_and_the_original_backup(self):
        with Sandbox() as sb:
            cfg = sb.repo / "config/workspace.user.toml"
            cfg.parent.mkdir(exist_ok=True)
            original = '# mes réglages\n[language]\ndocuments = "en"\n\n[notifications]\nprovider = "none"\n'
            cfg.write_text(original)
            self.assertSucceeded(sb.run(["python3", str(sb.repo / "scripts/arc_notify.py"), "setup",
                                         "--url", "https://ntfy.example.com/", "--topic", "t2", "--no-test"]))
            text = cfg.read_text()
            self.assertIn("# mes réglages", text)
            self.assertIn('documents = "en"', text)
            self.assertIn('provider = "ntfy"', text)
            self.assertIn('ntfy_url = "https://ntfy.example.com"', text)
            self.assertEqual(text.count("[notifications]"), 1)
            self.assertEqual((cfg.parent / "workspace.user.toml.bak").read_text(), original)


# `coach-remote.sh:41` rajoute /opt/homebrew/bin et /usr/local/bin au PATH, hors
# de portée du bac à sable. Sur une machine qui y a screen ou tmux, « aucun
# backend » n'est pas une situation atteignable : le test le dit plutôt que de
# se croire vert. Le lint du palier B verrouille la régression partout.
HARDCODED_PATH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


def _backend_tool_on_host() -> str | None:
    for directory in HARDCODED_PATH_DIRS:
        for tool in ("screen", "tmux"):
            if (Path(directory) / tool).exists():
                return f"{directory}/{tool}"
    return None


class TestCoachRemote(InstallAsserts):
    """0.2 — `die` dans `$(backend)` transforme une erreur fatale en succès."""

    def setUp(self):
        found = _backend_tool_on_host()
        if found:
            self.skipTest(
                f"{found} est présent et coach-remote.sh rajoute ce dossier au PATH : "
                "« aucun backend » n'est pas atteignable sur cette machine."
            )

    def test_no_backend_fails_loudly(self):
        with Sandbox() as sb:
            proc = sb.run(
                [str(sb.repo / "scripts/coach-remote.sh"), "status"],
                hide=("systemctl", "screen", "tmux"),
                ARC_FAKE_UNAME="Linux",
            )
            self.assertFailed(proc, "coach-remote.sh sans backend disponible")
            self.assertOutputContains(proc, "systemd")

    def test_no_backend_install_does_not_claim_success(self):
        with Sandbox() as sb:
            proc = sb.run(
                [str(sb.repo / "scripts/coach-remote.sh"), "install"],
                hide=("systemctl", "screen", "tmux"),
                ARC_FAKE_UNAME="Linux",
            )
            self.assertFailed(proc, "install sans backend")
            self.assertOutputLacks(proc, "Sur le téléphone")


class TestCoachRemotePrompts(InstallAsserts):
    def test_accepts_spelled_out_yes(self):
        """« oui » doit être accepté comme « o » (sinon on relance claude pour rien)."""
        with Sandbox() as sb:
            proc = sb.run_pty(
                [str(sb.repo / "scripts/coach-remote.sh"), "install"],
                answers=["oui"],
                ARC_FAKE_UNAME="Darwin",
            )
            self.assertOutputLacks(proc, "Lancement interactif")
