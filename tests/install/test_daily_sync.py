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
