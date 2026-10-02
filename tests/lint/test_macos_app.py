"""Contrats statiques de l'application macOS et de son DMG."""

from __future__ import annotations

import plistlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "macos/AI-Running-Coach/AI_Running_CoachApp.swift"
BUILD = ROOT / "scripts/build-macos-dmg.sh"
PLIST = ROOT / "macos/AI-Running-Coach/Info.plist"
DMG_WORKFLOW = ROOT / ".github/workflows/macos-dmg.yml"
TAG_WORKFLOW = ROOT / ".github/workflows/tag.yml"


class TestMacApp(unittest.TestCase):
    def test_required_sources_exist(self):
        for path in (SOURCE, BUILD, PLIST, ROOT / "docs/macos.md"):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"fichier macOS absent : {path}")

    def test_app_is_both_installer_and_launcher(self):
        text = SOURCE.read_text(encoding="utf-8")
        for contract in (
            "Installer mon coach",
            "Tableau de bord",
            "Connecter mon compte",
            "coach_doctor.py",
            "scripts/dashboard.sh",
            "--no-auth",
            "--apply-profile",
            "--apply-shoes",
            "--apply-objective",
            '"--llm", "openrouter"',
            '"--chat"',
            '"Prénom / surnom"',
            '"Années de pratique"',
            '"Disponibilité hebdomadaire"',
            '"Lieu par défaut"',
            '"VO2max (Garmin)"',
            '"Sports croisés pratiqués"',
            '"Ce qui me motive"',
            '"Objectif principal"',
            '"Lieu d\'entraînement par défaut"',
            "Parler au coach",
            "Compléter mon profil et mon objectif",
            "OPENROUTER_API_KEY",
            "ensureExternalAssistant",
            "launchExternalCoach",
            "https://claude.ai/install.sh",
            "https://gh.io/copilot-install",
            "https://opencode.ai/v2/install",
            "https://cursor.com/install",
            "@google/gemini-cli",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)

    def test_every_profile_label_exists_in_the_official_template(self):
        text = SOURCE.read_text(encoding="utf-8")
        block = text.split("let candidates: [String: String] = [", 1)[1].split("\n        ]", 1)[0]
        labels = set(re.findall(r'^\s+"([^"]+)": selected\.', block, flags=re.MULTILINE))
        template = (ROOT / "templates/Runner_Profile.template.md").read_text(encoding="utf-8")
        template_labels = set(re.findall(r"^- \*\*([^*]+)\*\*\s*:", template, flags=re.MULTILINE))
        self.assertTrue(labels, "aucun champ de profil détecté dans l'application")
        self.assertEqual(template_labels, labels, "le parcours graphique ne couvre pas tout le profil officiel")

    def test_every_objective_label_exists_in_the_official_template(self):
        text = SOURCE.read_text(encoding="utf-8")
        start = text.index('private func applyObjective')
        block = text[start:].split("let candidates: [String: String] = [", 1)[1].split("\n        ]", 1)[0]
        labels = set(re.findall(r'^\s+"([^"]+)": selected\.', block, flags=re.MULTILINE))
        template = (ROOT / "templates/active_objective.template.md").read_text(encoding="utf-8")
        template_labels = set(re.findall(r"^- \*\*([^*]+)\*\*\s*:", template, flags=re.MULTILINE))
        self.assertTrue(labels, "aucun champ d'objectif détecté dans l'application")
        self.assertEqual(set(), labels - template_labels, "l'application invente un libellé absent du modèle")

    def test_private_key_is_not_passed_on_the_command_line(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn('appendingPathComponent("llm.env")', text)
        self.assertIn('attributes: [.posixPermissions: 0o600]', text)
        self.assertIn('.posixPermissions: 0o600', text)
        self.assertNotIn('"--api-key", selected.openRouterAPIKey', text)

    def test_guided_assistants_are_installed_and_launched_without_manual_cd(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("static var guidedCases", text)
        self.assertIn("try await ensureExternalAssistant(selected.ide)", text)
        self.assertIn('cd \\(shellQuote(workspaceURL.path))', text)
        self.assertIn('tell application \\"Terminal\\" to do script', text)
        self.assertIn('Label("Parler au coach avec \\(model.externalAssistantTitle)', text)

    def test_integrated_chat_configures_opencode_agents_and_skills(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("selected.chatChoice == .integrated ? .opencode : selected.ide", text)
        self.assertIn("integratedChatEnabled ? IDEChoice.opencode.rawValue : choices.ide.rawValue", text)

    def test_full_coach_setup_choices_are_not_hardcoded(self):
        text = SOURCE.read_text(encoding="utf-8")
        for configured in (
            '"coaching.intensity": selected.coachingIntensity.rawValue',
            '"coaching.verbosity": selected.coachingVerbosity.rawValue',
            '"sport.disciplines": selected.disciplines',
            '"language.documents": selected.documentsLanguage',
            '"language.responses": selected.responsesLanguage',
            '"athlete.units": selected.units.rawValue',
        ):
            with self.subTest(configured=configured):
                self.assertIn(configured, text)

    def test_personal_data_is_not_bundled(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn('git -C "$ROOT" ls-files -z', text)
        for directory in ("activities", "medical", "nutrition", "planning", "rapports", "gear", "resources"):
            self.assertIn(f"':(exclude){directory}/**'", text)
        self.assertIn("':(exclude)config/workspace.user.toml'", text)
        self.assertIn("':(exclude)tests/**'", text)

    def test_public_distribution_hooks_are_present(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn("ARC_CODESIGN_IDENTITY", text)
        self.assertIn("ARC_NOTARY_PROFILE", text)
        self.assertIn("notarytool submit", text)
        self.assertIn("stapler staple", text)
        self.assertIn("lipo -create", text)

    def test_release_workflow_builds_after_the_official_release(self):
        dmg = DMG_WORKFLOW.read_text(encoding="utf-8")
        tag = TAG_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_call:", dmg)
        self.assertNotIn("gh release create", dmg)
        self.assertIn("uses: ./.github/workflows/macos-dmg.yml", tag)
        self.assertIn("needs: [tag, release]", tag)

    def test_dashboard_reuses_the_discovered_url(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("private var dashboardBaseURL: URL?", text)
        self.assertNotIn('let destination = openChat ? "http://127.0.0.1:8765', text)

    def test_plist_is_valid_after_placeholder_substitution(self):
        raw = PLIST.read_text(encoding="utf-8").replace("__VERSION__", "0.2.0").replace("__BUILD__", "1")
        payload = plistlib.loads(raw.encode())
        self.assertEqual(payload["CFBundlePackageType"], "APPL")
        self.assertEqual(payload["LSMinimumSystemVersion"], "13.0")
        self.assertIn("Terminal", payload["NSAppleEventsUsageDescription"])


if __name__ == "__main__":
    unittest.main()
