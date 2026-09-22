"""Palier A — sélection du staff (`--agents`, `--no-medical`).

La propriété la moins évidente et la plus importante : **désactiver un agent sur
une installation existante doit le retirer**. Un catalogue qui ne fait qu'ajouter
rendrait la désactivation silencieusement inopérante.
"""

from __future__ import annotations

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

ALL = {"coach", "medical", "nutritionist", "course-strategist"}
SURFACES = (".claude/agents", ".opencode/agents", ".github/agents")


class AgentSelectionCase(InstallAsserts):
    def installed(self, sb: Sandbox, surface: str = ".claude/agents") -> set:
        directory = sb.repo / surface
        if not directory.is_dir():
            return set()
        return {p.stem for p in directory.glob("*.md") if p.exists()}

    def enabled_in_config(self, sb: Sandbox) -> list:
        proc = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get",
                       "--workspace", str(sb.repo), "--section", "agents", "--key", "enabled"])
        self.assertSucceeded(proc)
        return proc.stdout.split()


class TestDefaults(AgentSelectionCase):
    def test_everything_by_default(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth"))
            for surface in SURFACES:
                with self.subTest(surface=surface):
                    self.assertEqual(self.installed(sb, surface), ALL)


class TestExplicitSelection(AgentSelectionCase):
    def test_no_medical(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--no-medical"))
            self.assertEqual(self.installed(sb), ALL - {"medical"})
            self.assertNotIn("medical", self.enabled_in_config(sb))

    def test_explicit_list(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--agents", "coach,nutritionist"))
            self.assertEqual(self.installed(sb), {"coach", "nutritionist"})
            self.assertEqual(sorted(self.enabled_in_config(sb)), ["coach", "nutritionist"])

    def test_applies_to_every_surface(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--no-medical"))
            for surface in SURFACES:
                with self.subTest(surface=surface):
                    self.assertNotIn("medical", self.installed(sb, surface))

    def test_unknown_agent_is_rejected(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--agents", "coach,kinesitherapeute")
            self.assertFailed(proc)
            self.assertOutputContains(proc, "kinesitherapeute")

    def test_coach_cannot_be_dropped(self):
        """Le coach planifie et pousse vers Garmin : sans lui, rien ne fonctionne."""
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--agents", "medical,nutritionist")
            self.assertFailed(proc)
            self.assertOutputContains(proc, "coach")


class TestReconfiguration(AgentSelectionCase):
    def test_disabling_removes_an_installed_agent(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth"))
            self.assertIn("medical", self.installed(sb))

            self.assertSucceeded(sb.install("--no-auth", "--no-medical"))
            self.assertNotIn("medical", self.installed(sb), "l'agent désactivé est resté installé")

    def test_reenabling_brings_it_back(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--agents", "coach"))
            self.assertEqual(self.installed(sb), {"coach"})
            self.assertSucceeded(sb.install("--no-auth", "--agents", "coach,medical"))
            self.assertEqual(self.installed(sb), {"coach", "medical"})

    def test_config_is_honoured_without_a_flag(self):
        """Une fois écrit, [agents].enabled pilote les réinstallations suivantes."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--agents", "coach,medical"))
            self.assertSucceeded(sb.install("--no-auth"))
            self.assertEqual(self.installed(sb), {"coach", "medical"})

    def test_no_dangling_symlinks(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--no-medical"))
            for surface in SURFACES:
                directory = sb.repo / surface
                for entry in directory.iterdir():
                    with self.subTest(link=str(entry)):
                        self.assertTrue(entry.exists(), f"lien mort : {entry}")

    def test_selection_survives_a_plain_rerun(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--no-medical"))
            before = sb.tree()
            self.assertSucceeded(sb.install("--no-auth"))
            self.assertTreeUnchanged(before, sb.tree(), "réinstallation non idempotente")


class TestSkillsAreNotFiltered(AgentSelectionCase):
    def test_all_skills_remain_available(self):
        """Les skills sont chargés à la demande : les filtrer n'apporterait rien."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--agents", "coach"))
            self.assertPopulated(sb.repo / ".claude/skills", minimum=9)
