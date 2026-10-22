"""Palier B — cohérence de l'audit COROS (#168).

Jusqu'au 3 octobre 2026, les noms d'outils du MCP officiel COROS n'étaient
connus que par un projet tiers (« non vérifiés »). Le 22 octobre 2026, une
session authentifiée a relevé la vraie liste (`docs/coros.md`, « Session
authentifiée ») : seuls les noms de CETTE liste peuvent apparaître dans un
prompt, un agent, un skill, un script ou l'installeur. Un nom rapporté par le
tiers mais absent de la liste relevée (`querySleepData`) n'apparaît jamais hors
de la doc.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOC = REPO / "docs" / "coros.md"
SKILL = REPO / "skills" / "coros-workout-scheduling" / "SKILL.md"

UNVERIFIED = "### Noms d'outils rapportés par un tiers (non vérifiés)"
VERIFIED = "## Session authentifiée (22 octobre 2026)"
NAME_RE = re.compile(r"`((?:query|get|download|analyze|create|update|schedule)[A-Z][A-Za-z]+)`")

# Outils de calendrier que le skill a le droit d'appeler (les autres ne sont pas utilisés).
SKILL_CALLS = {"queryTrainingSchedule", "createScheduledWorkout",
               "queryScheduledWorkoutDetails", "updateScheduledWorkout"}


def _section(title: str) -> str:
    tail = DOC.read_text(encoding="utf-8").partition(title)[2]
    return tail.split("\n## ", 1)[0]


def _verified_names() -> set[str]:
    """Noms du tableau de la liste relevée (lignes `|` seulement, pas la prose)."""
    rows = [l for l in _section(VERIFIED).splitlines() if l.startswith("|")]
    return set(NAME_RE.findall("\n".join(rows)))


def _unverified_names() -> set[str]:
    return set(NAME_RE.findall(_section(UNVERIFIED)))


class TestCorosAudit(unittest.TestCase):
    def test_verified_list_has_the_34_tools(self):
        self.assertEqual(len(_verified_names()), 34, sorted(_verified_names()))
        self.assertIn("34 outils", _section(VERIFIED))

    def test_third_party_names_are_verified_or_flagged_absent(self):
        missing = _unverified_names() - _verified_names()
        self.assertEqual(missing, {"querySleepData"})
        self.assertIn("sauf `querySleepData`", _section(VERIFIED))

    def test_third_party_section_stays_marked_unverified(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("(non vérifié)", _section(UNVERIFIED))
        self.assertNotRegex(text, r"outil[s]? vérifié[s]?\b(?! par)")

    def test_only_verified_names_in_prompts_and_code(self):
        roots = ["AGENTS.md", "install.sh", "scripts", ".github", "skills", "agents",
                 "config", "templates"]
        banned = _unverified_names() - _verified_names()
        self.assertTrue(banned)
        for root in roots:
            p = REPO / root
            files = [p] if p.is_file() else (list(p.rglob("*")) if p.exists() else [])
            for f in files:
                if not f.is_file() or f.suffix in (".png", ".jpg", ".db", ".pyc"):
                    continue
                try:
                    body = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for name in sorted(banned):
                    self.assertNotIn(name, body, f"{name} (jamais relevé) dans {f.relative_to(REPO)}")

    def test_skill_calls_only_the_calendar_tools(self):
        text = SKILL.read_text(encoding="utf-8")
        for name in SKILL_CALLS:
            self.assertIn(name, text)
        self.assertTrue(SKILL_CALLS <= _verified_names())
        self.assertIn("Never headless", text)
        self.assertIn('explicit "oui"', text)
        self.assertIn("arc_coros_workout.py validate", text)

    def test_doc_in_nav_and_decision_recorded(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("coros.md", nav)
        self.assertIn("skills/coros-workout-scheduling.md", nav)
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("Décision", text)
        self.assertIn("mcpeu.coros.com/mcp", _section(VERIFIED))


if __name__ == "__main__":
    unittest.main()
