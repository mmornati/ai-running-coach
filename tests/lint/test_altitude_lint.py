"""Palier B — cohérence docs/prompt de l'altitude (#185) : le prompt de l'agent, les docs, l'AGENTS.md
et le README parlent de la même chose que le code (options CLI, source citée, honnêteté sur
l'approximation, route API)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_race_pacing as RP  # noqa: E402


def read(rel):
    return " ".join((REPO / rel).read_text(encoding="utf-8").split())   # retours à la ligne neutralisés


class TestAltitudeDocs(unittest.TestCase):
    def test_cli_options_exist_and_are_documented(self):
        help_text = RP.build_arg_parser().format_help()
        agent = read("agents/course-strategist.md")
        docs = read("docs/agents/course-strategist.md")
        for opt in ("--altitude-acclimated-days", "--altitude-threshold-m", "--altitude-loss-pct", "--no-altitude"):
            self.assertIn(opt, help_text, opt)
            self.assertIn(opt, docs, opt)
        self.assertIn("--altitude-acclimated-days", agent)
        self.assertIn("--no-altitude", agent)

    def test_literature_cited_and_translation_labelled(self):
        for rel in ("docs/agents/course-strategist.md",):
            text = read(rel)
            self.assertIn("10.1007/s00421-005-0081-9", text)
            self.assertIn("Wehrlin", text)
            self.assertIn("approximation du projet", text)
        self.assertIn("approximation du projet", read("agents/course-strategist.md"))

    def test_prompt_never_assumes_acclimation(self):
        agent = read("agents/course-strategist.md")
        self.assertIn("NON acclimaté", agent)
        self.assertIn("below_threshold", agent)

    def test_exposure_surfaces_documented(self):
        views = read("docs/dashboard/views.md")
        self.assertIn("### Exposition à l'altitude", views)
        self.assertIn("altitude-exposure", views)
        self.assertIn("/api/altitude-exposure", views)
        self.assertIn("altitude-exposure", read("docs/skills.md"))
        self.assertIn("altitude-exposure", read("AGENTS.md"))
        self.assertIn("Altitude en ultra", read("README.md"))

    def test_cross_link_anchor_matches_heading(self):
        views = read("docs/dashboard/views.md")
        m = re.search(r"course-strategist\.md#([a-z0-9-]+)", views)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "penalite-daltitude-185")
        self.assertIn("## Pénalité d'altitude (#185)", read("docs/agents/course-strategist.md"))

    def test_contract_knows_the_segment_fields(self):
        skill = read("skills/workspace-data-contract/SKILL.md")
        self.assertIn("`altitude_m`, `altitude_factor`", skill)


if __name__ == "__main__":
    unittest.main()
