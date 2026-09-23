"""Palier A — planification de la synchronisation (crontab et launchd).

Les deux chemins sont testés sur les deux OS grâce au stub `uname`.
"""

from __future__ import annotations

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

EXISTING_CRONTAB = """\
# ma crontab à moi
0 9 * * 1 /usr/local/bin/sauvegarde.sh

30 2 * * * /usr/local/bin/menage.sh
"""


class TestCrontab(InstallAsserts):
    """0.8 — ne jamais perdre la crontab de l'utilisateur."""

    def test_preserves_existing_entries(self):
        with Sandbox() as sb:
            sb.set_crontab(EXISTING_CRONTAB)
            proc = sb.install("--no-auth", "--daily-sync", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)

            crontab = sb.crontab()
            self.assertIn("sauvegarde.sh", crontab, f"entrée existante perdue :\n{crontab}")
            self.assertIn("menage.sh", crontab, f"entrée existante perdue :\n{crontab}")
            self.assertIn("ai-running-coach daily-sync", crontab)

    def test_backs_up_before_writing(self):
        with Sandbox() as sb:
            sb.set_crontab(EXISTING_CRONTAB)
            self.assertSucceeded(sb.install("--no-auth", "--daily-sync", ARC_FAKE_UNAME="Linux"))
            backups = list((sb.home / ".config/ai-running-coach").glob("crontab-*.bak"))
            self.assertTrue(backups, "aucune sauvegarde de crontab écrite avant modification")
            self.assertIn("sauvegarde.sh", backups[0].read_text())

    def test_read_failure_aborts_instead_of_replacing(self):
        with Sandbox() as sb:
            sb.set_crontab(EXISTING_CRONTAB)
            proc = sb.install(
                "--no-auth", "--daily-sync", ARC_FAKE_UNAME="Linux", ARC_STUB_FAIL="crontab"
            )
            self.assertFailed(proc, "échec de lecture de la crontab")
            self.assertEqual(
                sb.crontab(), EXISTING_CRONTAB, "la crontab a été remplacée malgré l'erreur de lecture"
            )

    def test_no_existing_crontab_is_not_an_error(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--daily-sync", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc, "installation sans crontab préalable")
            self.assertIn("ai-running-coach daily-sync", sb.crontab())

    def test_rerun_does_not_duplicate_entries(self):
        with Sandbox() as sb:
            for _ in range(2):
                self.assertSucceeded(
                    sb.install("--no-auth", "--daily-sync", ARC_FAKE_UNAME="Linux")
                )
            occurrences = sb.crontab().count("ai-running-coach daily-sync")
            self.assertEqual(occurrences, 2, f"attendu 2 lignes (2 horaires), vu {occurrences}")

    def test_workspace_path_with_space_is_quoted(self):
        with Sandbox() as sb:
            ws = sb.root / "Mon Workspace"
            ws.mkdir()
            self.assertSucceeded(
                sb.install("--no-auth", "--daily-sync", "--workspace", str(ws), ARC_FAKE_UNAME="Linux")
            )
            crontab = sb.crontab()
            self.assertIn("Mon Workspace", crontab)
            self.assertRegex(
                crontab,
                r"ARC_WORKSPACE=(\"[^\"]*Mon Workspace[^\"]*\"|'[^']*Mon Workspace[^']*')",
                f"chemin avec espace non protégé dans la crontab :\n{crontab}",
            )


class TestLaunchd(InstallAsserts):
    """0.3 — ~/Library/LaunchAgents peut ne pas exister."""

    def test_creates_launchagents_dir(self):
        with Sandbox() as sb:
            self.assertFalse((sb.home / "Library/LaunchAgents").exists())
            proc = sb.install("--no-auth", "--daily-sync", ARC_FAKE_UNAME="Darwin")
            self.assertSucceeded(proc, "--daily-sync sans ~/Library/LaunchAgents")
            self.assertIsFile(
                sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist"
            )

    def test_plist_escapes_xml_special_chars(self):
        with Sandbox() as sb:
            ws = sb.root / "sport & trail"
            ws.mkdir()
            self.assertSucceeded(
                sb.install("--no-auth", "--daily-sync", "--workspace", str(ws), ARC_FAKE_UNAME="Darwin")
            )
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist"
            content = plist.read_text()
            self.assertIn("&amp;", content, "esperluette non échappée dans le plist")
            self._assert_valid_xml(content)

    def test_plist_is_valid_xml(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--daily-sync", ARC_FAKE_UNAME="Darwin"))
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist"
            self._assert_valid_xml(plist.read_text())

    def _assert_valid_xml(self, content: str) -> None:
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(content)
        except ET.ParseError as exc:
            self.fail(f"plist XML invalide : {exc}\n{content}")


class TestGitSyncBetweenMachines(InstallAsserts):
    """La machine coach doit intégrer ce que le portable a poussé.

    Défaut verrouillé : `daily-sync.sh` commitait puis poussait sans jamais tirer.
    Un seul push venu du portable (fichiers mis au contrat, plan écrit hors cron)
    rendait tous les push suivants de la machine coach impossibles.
    """

    def _git(self, sb, cwd, *args):
        proc = sb.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd)
        self.assertSucceeded(proc, "git " + " ".join(args))
        return proc

    def _setup(self, sb):
        remote = sb.root / "remote.git"
        self._git(sb, sb.root, "init", "-q", "--bare", "-b", "main", str(remote))
        server = sb.root / "coach"
        self._git(sb, sb.root, "clone", "-q", str(remote), str(server))
        (server / "config").mkdir()
        (server / "config/workspace.user.toml").write_text(
            '[sync]\nrunner = "claude"\ngit_autocommit = true\n\n[notifications]\nprovider = "none"\n'
        )
        (server / ".gitignore").write_text("/logs/\n/config/workspace.user.toml\n")
        (server / "activities").mkdir()
        (server / "activities/2026-09-20_running.md").write_text("# Séance\n")
        self._git(sb, server, "add", "-A")
        self._git(sb, server, "commit", "-q", "-m", "init")
        self._git(sb, server, "push", "-q", "-u", "origin", "main")
        laptop = sb.root / "portable"
        self._git(sb, sb.root, "clone", "-q", str(remote), str(laptop))
        return remote, server, laptop

    def test_sync_pulls_laptop_push_then_pushes(self):
        with Sandbox() as sb:
            remote, server, laptop = self._setup(sb)
            # Le portable pousse une mise au contrat…
            (laptop / "activities/2026-09-20_running.md").write_text("# Séance\n\n```arc\n{}\n```\n")
            self._git(sb, laptop, "commit", "-q", "-am", "arc: contrat")
            self._git(sb, laptop, "push", "-q")
            # … pendant que la machine coach a produit un nouveau fichier.
            (server / "medical").mkdir()
            (server / "medical/2026-09-23_health.md").write_text("# Santé\n")

            proc = sb.script("daily-sync.sh", ARC_WORKSPACE=str(server))
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "push origin")
            self.assertIn("```arc", (server / "activities/2026-09-20_running.md").read_text(),
                          "la machine coach n'a pas intégré le push du portable")
            log = self._git(sb, laptop, "fetch", "-q")
            log = self._git(sb, laptop, "log", "--format=%s", "origin/main").stdout
            self.assertIn("arc: contrat", log)
            self.assertRegex(log.splitlines()[0], r"^sync: ", "le commit de sync n'est pas au sommet du remote")
