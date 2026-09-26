"""Palier A — garde-fou déterministe sur le bloc ```resume``` (#56).

`skills/garmin-daily-sync/SKILL.md` promet un bloc de 5 lignes maximum, où la
ligne « Pourquoi : » (raison de l'ajustement) REMPLACE la ligne « Alerte : »
plutôt que de s'y ajouter. `scripts/daily-sync.sh::enforce_resume_cap` est le
filet de sécurité côté shell : si un run produit malgré tout plus de 5 lignes,
il tronque — en préservant en priorité une ligne « Pourquoi : » si elle
existe — avant d'envoyer la notification.

Ces tests stubbent `claude` (comme `TestAuthFailureExplicitNotification` dans
`tests/install/test_token_expiry_alert.py`) pour fixer la sortie de l'agent et
vérifient ce qui atteint réellement `curl` (donc `scripts/notify.sh`), pas ce
que l'agent aurait dû produire.
"""

from __future__ import annotations

from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox


class ResumeCapSandbox(InstallAsserts):
    def _configure_notifications(self, sb: Sandbox) -> None:
        config_dir = sb.repo / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "workspace.user.toml").write_text(
            '[notifications]\nprovider = "ntfy"\nntfy_topic = "test-topic"\n'
        )

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
        import os

        return f"{fake_bin}:{STUBS_DIR}:{os.environ.get('PATH', '')}"

    def _run(self, sb: Sandbox, stdout: str, exit_code: int = 0):
        fake_bin = self._fake_claude(sb, stdout, exit_code=exit_code)
        return sb.script("daily-sync.sh", PATH=self._path_with_fake_claude(fake_bin))

    def _notified_message(self, sb: Sandbox) -> str:
        """Corps envoyé à `curl --data-binary` (donc le message de
        `scripts/notify.sh`).

        `Sandbox.stub_calls` découpe `$ARC_STUB_LOG` ligne à ligne : un
        message MULTI-LIGNE (le bloc ```resume```, justement) y casse la
        convention `nom<TAB>args` dès sa deuxième ligne — chaque ligne
        supplémentaire du message se retrouve sans tabulation, donc rejetée
        par `stub_calls`. On lit le journal brut à la place : un seul appel
        `curl` est attendu par run (asserté ci-dessous), toujours le DERNIER
        écrit (la notification finale) — tout ce qui suit `--data-binary `
        dans le fichier est donc le message tel qu'envoyé, newlines
        comprises.
        """
        raw = sb.stub_log.read_text()
        self.assertEqual(
            raw.count("curl\t"), 1, f"attendu exactement 1 appel curl, journal :\n{raw}"
        )
        marker = "--data-binary "
        self.assertIn(marker, raw, f"aucun --data-binary dans le journal :\n{raw}")
        return raw.split(marker, 1)[1]


class TestResumeCapPreservesPourquoi(ResumeCapSandbox):
    def test_oversized_block_is_truncated_but_keeps_pourquoi(self):
        """Un bloc à 6 lignes (agent qui déraperait) doit être ramené à 5,
        SANS perdre la ligne « Pourquoi : » même si le dépassement l'aurait
        sinon fait tomber hors des lignes gardées."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            final_message = (
                "```resume\n"
                "Séances : à jour\n"
                "Sommeil : 5 h 10, score 41\n"
                "HRV : 31 ms — effondrée (baseline 48-74)\n"
                "Readiness : 22\n"
                "Alerte : FIT non téléchargé (1 séance)\n"
                "Pourquoi : verdict rouge (HRV effondrée) — séance VO2max à revoir "
                "(r5_quality_after_red)\n"
                "```\n"
            )
            proc = self._run(sb, final_message)
            self.assertSucceeded(proc)
            message = self._notified_message(sb)
            self.assertIn("Pourquoi :", message)
            self.assertIn("r5_quality_after_red", message)
            non_empty_lines = [l for l in message.splitlines() if l.strip()]
            self.assertLessEqual(
                len(non_empty_lines), 5,
                f"le bloc envoyé dépasse 5 lignes : {non_empty_lines}",
            )
            # La ligne « Pourquoi : » doit être la dernière conservée.
            self.assertTrue(
                non_empty_lines[-1].startswith("Pourquoi :"),
                f"« Pourquoi : » doit rester la dernière ligne gardée : {non_empty_lines}",
            )

    def test_conforming_five_line_block_passes_through_unchanged(self):
        """Un bloc déjà conforme (<= 5 lignes, `Pourquoi :` en 5e ligne comme
        le prescrit le SKILL.md) ne doit rien perdre — le garde-fou n'est
        qu'un filet de sécurité, pas le mécanisme normal."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            final_message = (
                "```resume\n"
                "Séances : à jour\n"
                "Sommeil : 5 h 10, score 41\n"
                "HRV : 31 ms — effondrée (baseline 48-74)\n"
                "Readiness : 22\n"
                "Pourquoi : verdict rouge (HRV effondrée) — séance VO2max à revoir "
                "(r5_quality_after_red)\n"
                "```\n"
            )
            proc = self._run(sb, final_message)
            self.assertSucceeded(proc)
            message = self._notified_message(sb)
            for line in ("Séances : à jour", "Readiness : 22", "r5_quality_after_red"):
                self.assertIn(line, message)
            non_empty_lines = [l for l in message.splitlines() if l.strip()]
            self.assertEqual(len(non_empty_lines), 5)

    def test_block_without_pourquoi_keeps_first_five_lines(self):
        """Sans ligne « Pourquoi : », le garde-fou garde simplement les 5
        premières lignes — comportement de repli, pas de règle spéciale."""
        with Sandbox() as sb:
            self._configure_notifications(sb)
            final_message = (
                "```resume\n"
                "Séances : 1 nouvelle — trail 12,3 km\n"
                "Sommeil : 7 h 42, score 81\n"
                "HRV : 62 ms — équilibré (baseline 58-66)\n"
                "Readiness : 74\n"
                "Alerte : FIT non téléchargé (1 séance)\n"
                "Extra : une ligne en trop qui ne devrait jamais exister\n"
                "```\n"
            )
            proc = self._run(sb, final_message)
            self.assertSucceeded(proc)
            message = self._notified_message(sb)
            self.assertNotIn("une ligne en trop", message)
            non_empty_lines = [l for l in message.splitlines() if l.strip()]
            self.assertLessEqual(len(non_empty_lines), 5)
            self.assertEqual(non_empty_lines[0], "Séances : 1 nouvelle — trail 12,3 km")
