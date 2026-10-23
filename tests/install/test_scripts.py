"""Palier A — scripts compagnons (setup-ntfy, coach-remote, notify)."""

from __future__ import annotations

import gzip
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


ROTATE_MARKER = "# ai-running-coach logrotate"


class TestCoachRemoteLogRotation(InstallAsserts):
    """Le journal de `claude remote-control` grossit sans fin (245 Mo en 12 jours).

    Rotation par copie + troncature : le processus garde le descripteur ouvert en
    ajout, on ne le redémarre pas.
    """

    @staticmethod
    def _log(sb: Sandbox) -> Path:
        path = sb.repo / "logs/remote-control.log"
        path.parent.mkdir(exist_ok=True)
        return path

    def test_below_threshold_is_untouched(self):
        with Sandbox() as sb:
            log = self._log(sb)
            log.write_text("petit journal\n")
            self.assertSucceeded(sb.script("coach-remote.sh", "rotate-log"))
            self.assertEqual(log.read_text(), "petit journal\n")
            self.assertFalse(log.with_name("remote-control.log.1").exists())

    def test_copytruncate_keeps_three_generations(self):
        with Sandbox() as sb:
            log = self._log(sb)
            # Le fichier reste le même inode : un écrivain en mode ajout continue.
            log.touch()
            inode = log.stat().st_ino
            for n in range(1, 6):
                with log.open("a") as fh:
                    fh.write(f"génération {n}\n" * 10)
                self.assertSucceeded(
                    sb.script("coach-remote.sh", "rotate-log", ARC_REMOTE_LOG_MAX_BYTES="50")
                )
                self.assertEqual(log.stat().st_size, 0, "journal non tronqué")
                self.assertEqual(log.stat().st_ino, inode, "journal remplacé au lieu d'être tronqué")
            d = log.parent
            self.assertIn("génération 5", (d / "remote-control.log.1").read_text())
            self.assertIn("génération 4", gzip.decompress((d / "remote-control.log.2.gz").read_bytes()).decode())
            self.assertIn("génération 3", gzip.decompress((d / "remote-control.log.3.gz").read_bytes()).decode())
            self.assertFalse((d / "remote-control.log.4.gz").exists(), "plus de 3 générations gardées")

    def test_url_falls_back_to_rotated_log(self):
        with Sandbox() as sb:
            log = self._log(sb)
            log.write_text("reconnexion…\n")
            log.with_name("remote-control.log.1").write_text(
                "Remote Control session started https://claude.ai/code/session_abc123\n"
            )
            proc = sb.script("coach-remote.sh", "url")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "https://claude.ai/code/session_abc123")

    def test_url_without_any_url_fails(self):
        with Sandbox() as sb:
            self._log(sb).write_text("rien\n")
            self.assertFailed(sb.script("coach-remote.sh", "url"), "url sans URL dans le journal")

    def test_systemd_install_adopts_manual_cron_line(self):
        with Sandbox() as sb:
            manual = (
                "23 * * * * /usr/sbin/logrotate -s $HOME/.local/state/logrotate/x.state "
                f"$HOME/.config/logrotate/ai-running-coach.conf {ROTATE_MARKER}\n"
            )
            sb.set_crontab("0 6 * * * autre-tache\n" + manual)
            for _ in range(2):
                self.assertSucceeded(
                    sb.script("coach-remote.sh", "install", ARC_FAKE_UNAME="Linux"),
                    "install systemd",
                )
            table = sb.crontab()
            self.assertEqual(table.count(ROTATE_MARKER), 1, f"ligne de rotation doublée :\n{table}")
            self.assertIn("coach-remote.sh\" rotate-log", table)
            self.assertIn("0 6 * * * autre-tache", table)

            self.assertSucceeded(sb.script("coach-remote.sh", "uninstall", ARC_FAKE_UNAME="Linux"))
            table = sb.crontab()
            self.assertNotIn(ROTATE_MARKER, table)
            self.assertIn("0 6 * * * autre-tache", table)

    def test_launchd_install_schedules_rotation_agent(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.script("coach-remote.sh", "install", ARC_FAKE_UNAME="Darwin"))
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.remote-logrotate.plist"
            self.assertFileContains(plist, "<string>rotate-log</string>")
            self.assertFileContains(plist, "<key>StartInterval</key>")
            self.assertTrue(
                any("bootstrap" in args and "remote-logrotate" in args
                    for _, args in sb.stub_calls("launchctl")),
                "agent de rotation non chargé",
            )
            self.assertNotIn(ROTATE_MARKER, sb.crontab(), "launchd ne doit pas passer par la crontab")

            self.assertSucceeded(sb.script("coach-remote.sh", "uninstall", ARC_FAKE_UNAME="Darwin"))
            self.assertFalse(plist.exists(), "agent de rotation laissé après uninstall")
