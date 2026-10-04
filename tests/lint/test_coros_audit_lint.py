"""Palier B — cohérence de l'audit COROS (#168).

Les noms d'outils du MCP officiel COROS ne sont PAS vérifiés à la source
(`tools/list` exige OAuth) : ils ne doivent apparaître que dans `docs/coros.md`,
sous la rubrique « non vérifiés », et jamais dans un prompt, un agent, un skill,
un script ou l'installeur (sinon ils seraient traités comme une correspondance).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOC = REPO / "docs" / "coros.md"
NAMES = (
    "querySportRecords", "getActivityDetail", "queryActivityLapData",
    "queryActivityFitFileDownloadUrls", "downloadActivityFitFiles", "querySleepHrv",
    "querySleepData", "queryRestingHeartRate", "queryTrainingLoadAssessment",
    "queryRecoveryStatus", "queryFitnessAssessmentOverview",
)


SECTION = "### Noms d'outils rapportés par un tiers (non vérifiés)"


def _documented_names() -> set[str]:
    """Identifiants camelCase cités dans la section « non vérifiés » (lus dans la doc)."""
    tail = DOC.read_text(encoding="utf-8").partition(SECTION)[2]
    section = tail.split("\n## ", 1)[0]
    return set(re.findall(r"`((?:query|get|download|analyze)[A-Z][A-Za-z]+)`", section))


class TestCorosAudit(unittest.TestCase):
    def test_documented_names_cover_reference_list(self):
        # Garde-fou de l'extraction : la liste figée doit rester un sous-ensemble.
        self.assertTrue(set(NAMES) <= _documented_names())
    def test_tool_names_only_in_unverified_section(self):
        text = DOC.read_text(encoding="utf-8")
        head, sep, tail = text.partition(SECTION)
        self.assertTrue(sep, "section « non vérifiés » absente")
        section = tail.split("\n## ", 1)[0]
        for name in NAMES:
            self.assertNotIn(name, head, f"{name} hors de la section non vérifiée")
            self.assertIn(name, section)

    def test_every_tool_row_is_marked_unverified(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("(non vérifié)", text)
        self.assertNotRegex(text, r"outil[s]? vérifié[s]?\b(?! par)")

    def test_names_absent_from_prompts_and_code(self):
        roots = ["AGENTS.md", "install.sh", "scripts", ".claude", ".github", "skills", "agents",
                 "config", "templates"]
        names = set(NAMES) | _documented_names()
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
                for name in sorted(names):
                    self.assertFalse(name in body, f"{name} dans {f.relative_to(REPO)}")

    def test_doc_in_nav_and_decision_recorded(self):
        self.assertIn("coros.md", (REPO / "mkdocs.yml").read_text(encoding="utf-8"))
        self.assertIn("Décision", DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
