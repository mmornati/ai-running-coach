"""Palier B — cohérence de la doc COROS (#168).

Le 22 octobre 2026, une session authentifiée a relevé la vraie liste des outils du
MCP officiel COROS (`docs/coros.md`, « Les outils ») : seuls les noms de CETTE
liste peuvent apparaître dans un prompt, un agent, un skill, un script ou
l'installeur. `querySleepData`, rapporté par un projet tiers avant cette session,
n'existe pas et n'apparaît nulle part. COROS se branche directement : la doc et le
skill ne passent plus par Intervals.icu.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOC = REPO / "docs" / "coros.md"
SKILL = REPO / "skills" / "coros-workout-scheduling" / "SKILL.md"
SKILL_DOC = REPO / "docs" / "skills" / "coros-workout-scheduling.md"

VERIFIED = "## Les outils (relevés le 22 octobre 2026, revus le 23)"
# Retirés par COROS depuis le relevé (constaté le 23/10/2026 : 33 outils) : cités dans la doc comme
# retirés, jamais appelés ailleurs.
RETIRED = {"analyzeActivityDetail"}
NAME_RE = re.compile(r"`((?:query|get|download|analyze|create|update|schedule)[A-Z][A-Za-z]+)`")
NEVER_SEEN = {"querySleepData"}

# Outils de calendrier que le skill appelle (les autres ne sont pas utilisés).
SKILL_CALLS = {"queryTrainingSchedule", "createScheduledWorkout", "queryScheduledWorkoutDetails",
               "updateScheduledWorkout", "queryWorkoutLibrary", "scheduleWorkout"}


def _section(title: str) -> str:
    tail = DOC.read_text(encoding="utf-8").partition(title)[2]
    return tail.split("\n## ", 1)[0]


def _verified_names() -> set[str]:
    """Noms du tableau de la liste relevée (lignes `|` seulement, pas la prose)."""
    rows = [l for l in _section(VERIFIED).splitlines() if l.startswith("|")]
    return set(NAME_RE.findall("\n".join(rows))) - RETIRED


class TestCorosAudit(unittest.TestCase):
    def test_verified_list_has_the_33_tools(self):
        self.assertEqual(len(_verified_names()), 33, sorted(_verified_names()))
        self.assertFalse(NEVER_SEEN & _verified_names())

    def test_only_verified_names_in_prompts_and_code(self):
        roots = ["AGENTS.md", "install.sh", "scripts", ".github", "skills", "agents",
                 "config", "templates", "docs"]
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
                for name in sorted(NEVER_SEEN):
                    self.assertNotIn(name, body, f"{name} (jamais relevé) dans {f.relative_to(REPO)}")
                if root in ("skills", "agents", "AGENTS.md") and "coros" in body.lower():
                    for name in set(NAME_RE.findall(body)) - _verified_names():
                        if name[0].islower() and any(c.isupper() for c in name) and "_" not in name:
                            self.fail(f"{name} absent de la liste relevée, dans {f.relative_to(REPO)}")

    def test_skill_calls_only_the_calendar_tools(self):
        text = SKILL.read_text(encoding="utf-8")
        for name in SKILL_CALLS:
            self.assertIn(name, text)
        self.assertTrue(SKILL_CALLS <= _verified_names())
        self.assertIn("Never headless", text)
        self.assertIn('explicit "oui"', text)
        self.assertIn("arc_coros_workout.py validate", text)

    def test_coros_stands_alone(self):
        """COROS se branche par son MCP officiel : ni le skill, ni sa doc, ni la page COROS
        ne passent par Intervals.icu ; un seul chemin vers la montre."""
        for path in (SKILL, SKILL_DOC, DOC):
            self.assertNotIn("intervals", path.read_text(encoding="utf-8").lower(), path)
        self.assertIn("## One path to the watch", SKILL.read_text(encoding="utf-8"))
        icu = (REPO / "skills/intervals-icu-best-practices/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("COROS", icu)
        # FC en bpm absolus : sans cible sur la montre (constaté le 22/10/2026) -> % LTHR.
        self.assertIn("--icu-lthr-bpm", icu)
        self.assertNotRegex(icu, r"- \d+[ms] \d+-\d+bpm")

    def test_doc_in_nav(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("coros.md", nav)
        self.assertIn("skills/coros-workout-scheduling.md", nav)
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("## En bref", text)
        self.assertIn("mcpeu.coros.com/mcp", text)


if __name__ == "__main__":
    unittest.main()
