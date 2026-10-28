"""Palier B — commande courte `/inspection` (#149) : frontmatter, commande Gemini générée,
référencement (AGENTS.md, index des skills, nav mkdocs, page de doc), garde-fous de comportement
(interactive seulement, jamais `/coach-setup`, jamais deviné) et cohérence des compteurs de skills.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills/inspection/SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")
FRONT = re.match(r"\A---\n(.*?)\n---\n", TEXT, re.DOTALL).group(1)


class TestInspectionSkill(unittest.TestCase):
    def test_frontmatter(self):
        self.assertRegex(FRONT, r"(?m)^name: inspection$")
        self.assertRegex(FRONT, r'(?m)^gemini_command: "true"$')
        description = re.search(r"(?m)^description: (.*)$", FRONT).group(1)
        self.assertLessEqual(len(description), 1024)

    def test_gemini_command_is_generated_from_the_skill(self):
        toml = (REPO / "config/gemini/commands/inspection.toml").read_text(encoding="utf-8")
        self.assertIn("skills/inspection/SKILL.md", toml)
        self.assertIn("# `/inspection [paire]`", toml)

    def test_listed_in_agents_md_docs_and_nav(self):
        self.assertIn("- `inspection` —", (REPO / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("skills/inspection.md", (REPO / "docs/skills.md").read_text(encoding="utf-8"))
        self.assertIn("skills/inspection.md", (REPO / "mkdocs.yml").read_text(encoding="utf-8"))
        self.assertTrue((REPO / "docs/skills/inspection.md").is_file())
        self.assertIn("inspection.md", (REPO / "docs/skills/gear-inspection.md").read_text(encoding="utf-8"))

    def test_homepage_and_readme_mention_the_command(self):
        index = (REPO / "docs/index.md").read_text(encoding="utf-8")
        self.assertIn('href="skills/inspection/"', index)
        self.assertIn("assets/dashboard/materiel.webp", index)
        self.assertIn("/inspection", (REPO / "README.md").read_text(encoding="utf-8"))

    def test_interactive_only_and_never_proposes_setup(self):
        self.assertRegex(TEXT, r"(?i)interactive uniquement")
        self.assertIn("headless", TEXT)
        self.assertRegex(TEXT, r"(?i)ne propose jamais `/coach-setup`")

    def test_never_guesses_and_never_writes_without_photo_or_description(self):
        self.assertRegex(TEXT, r"(?i)jamais de devinette")
        self.assertRegex(TEXT, r"(?i)jamais d'écriture d'un fichier `gear/…_inspection\.md` sans photo")

    def test_points_to_the_engine_commands_and_the_dropbox(self):
        self.assertIn("arc_index.py inspections --unreferenced-photos", TEXT)
        self.assertIn("gear/photos/", TEXT)
        self.assertIn("garmin_gear_backfill.py", TEXT)
        self.assertIn("gear-inspection", TEXT)

    def test_does_not_promise_phone_photo_upload(self):
        self.assertRegex(TEXT, r"(?i)à valider")
        self.assertRegex(TEXT, r"(?i)ne jamais le\s+promettre")

    def test_dropbox_rules_never_delete_nor_leave_the_folder(self):
        skill = (REPO / "skills/gear-inspection/SKILL.md").read_text(encoding="utf-8")
        for text in (TEXT, skill):
            self.assertRegex(text, r"(?i)ne jamais supprimer")
            self.assertRegex(text, r"(?i)ne jamais déplacer")

    def test_never_overwrites_and_explains_unsupported_formats(self):
        skill = (REPO / "skills/gear-inspection/SKILL.md").read_text(encoding="utf-8")
        coach = (REPO / "agents/coach.md").read_text(encoding="utf-8")
        for text in (TEXT, skill):
            self.assertRegex(text, r"(?i)jamais d'écrasement")
            self.assertIn("mv -n", text)
            self.assertIn("ignored_files", text)
            self.assertIn("HEIC", text)
        self.assertIn("NEVER overwrite", coach)
        self.assertIn("HEIC", (REPO / "docs/skills/inspection.md").read_text(encoding="utf-8"))
        self.assertIn("HEIC", (REPO / "docs/mobile.md").read_text(encoding="utf-8"))

    def test_resolution_uses_declared_and_backfill_only_for_garmin_source(self):
        self.assertIn("`declared`", TEXT)
        self.assertIn('[data].source = "garmin"', TEXT)


class TestSkillCountsConsistent(unittest.TestCase):
    """Les compteurs de skills des pages vivantes suivent le nombre réel de dossiers skills/."""

    def test_counts_match_the_directory(self):
        count = len(list((REPO / "skills").glob("*/SKILL.md")))
        words = {19: "Dix-neuf", 20: "Vingt", 21: "Vingt et un", 22: "Vingt-deux", 23: "Vingt-trois", 24: "Vingt-quatre", 25: "Vingt-cinq", 26: "Vingt-six", 27: "Vingt-sept", 28: "Vingt-huit", 29: "Vingt-neuf"}
        self.assertIn(f"**{count} skills**", (REPO / "README.md").read_text(encoding="utf-8"))
        self.assertIn(f"**{count} skills**", (REPO / "docs/skills.md").read_text(encoding="utf-8"))
        self.assertIn(f"## {words[count]} skills", (REPO / "docs/index.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
