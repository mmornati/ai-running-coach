"""Palier B — export Vanoor : opt-in strict (`[vanoor].export` à « off » par défaut), documenté,
et règles tenues dans les prompts (aucune mention à « off », cibles personnelles jamais
inventées, export et non push)."""

from __future__ import annotations

import sys
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_vanoor as V  # noqa: E402


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestConfig(unittest.TestCase):
    def test_off_by_default(self):
        conf = tomllib.loads(_read("config/workspace.toml"))
        self.assertEqual(conf["vanoor"]["export"], "off")
        self.assertEqual(conf["vanoor"]["output_dir"], "")

    def test_documented(self):
        doc = _read("docs/configuration.md")
        self.assertIn("[vanoor]", doc)
        for key in ("export", "output_dir"):
            self.assertIn(key, doc)
        self.assertIn("[vanoor].export", _read("AGENTS.md"))
        self.assertIn("Vanoor", _read("docs/marques.md"))

    def test_exports_are_gitignored(self):
        self.assertIn("/exports/", _read(".gitignore").splitlines())


class TestActivation(unittest.TestCase):
    def test_coach_setup_can_enable_it_on_request(self):
        setup = _read("skills/coach-setup/SKILL.md")
        self.assertIn("Vanoor", setup.split("---")[1], "la description du skill doit déclencher sur la demande")
        self.assertIn("--section vanoor --key export --value on", setup)
        self.assertIn("[vanoor].output_dir", setup)

    def test_docs_say_how_to_enable_it(self):
        for rel in ("docs/skills/vanoor-export.md", "docs/configuration.md"):
            self.assertIn("active l'export", _read(rel), rel)


class TestPrompts(unittest.TestCase):
    def test_agents_gate_on_export_and_never_mention_it_off(self):
        coach = _read("agents/coach.md")
        self.assertIn('[vanoor].export = "on"', coach)
        self.assertRegex(coach, r"at `off`[^.]*never mention Vanoor")
        self.assertIn("vanoor-export", coach)
        self.assertIn("arc_workout_targets.py", coach)
        strategist = _read("agents/course-strategist.md")
        self.assertIn('[vanoor].export = "on"', strategist)
        self.assertIn("python3 scripts/arc_vanoor.py race", strategist)

    def test_skill_rules(self):
        skill = _read("skills/vanoor-export/SKILL.md")
        self.assertIn('[vanoor].export = "on"', skill)
        self.assertIn("jamais", skill)
        self.assertIn("hr_target.bounds_bpm", skill)
        # Les zones de l'app ne sont pas celles du profil : toujours la plage en bpm.
        self.assertRegex(skill, r"\*\*jamais\*\* `hr_zone`")
        for command in ("arc_vanoor.py week", "arc_vanoor.py race", "arc_vanoor.py\nvalidate"):
            self.assertIn(command.split("\n")[0], skill)

    def test_skill_documents_the_script_limits(self):
        skill = _read("skills/vanoor-export/SKILL.md")
        limits = V.VANOOR_LIMITS
        for figure in (limits["workouts_per_file"], limits["steps_per_workout"], limits["splits_per_repeat"]):
            self.assertIn(str(figure), skill)


if __name__ == "__main__":
    unittest.main()
