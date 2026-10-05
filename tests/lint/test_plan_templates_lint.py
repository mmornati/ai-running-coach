"""Palier B — gabarits de périodisation (#189) : docs, navigation, prompt du coach.

Lecture statique : la page `docs/plans.md` existe, est dans la nav, cite chaque gabarit livré
et seulement des sources vérifiées ; le prompt du coach et AGENTS.md pointent vers la commande."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import arc_plan_templates as PT  # noqa: E402

PLANS_MD = (REPO / "docs/plans.md").read_text(encoding="utf-8")


class TestPlanTemplatesDocs(unittest.TestCase):
    def test_page_is_in_the_mkdocs_nav(self):
        self.assertRegex((REPO / "mkdocs.yml").read_text(encoding="utf-8"), r"(?m)^\s*- [^\n]+: plans\.md$")

    def test_page_lists_every_shipped_template(self):
        for t in PT.load_templates():
            self.assertIn(f"`{t['id']}`", PLANS_MD, t["id"])

    def test_page_names_the_command_and_the_caveat(self):
        self.assertIn("arc_index.py plan-templates", PLANS_MD)
        self.assertIn("approximations du projet", PLANS_MD)

    def test_only_verified_references_are_cited(self):
        dois = set(re.findall(r"doi:(10\.[^\]\s)]+)", PLANS_MD))
        self.assertEqual(dois, {"10.1249/01.MSS.0000074448.73931.11", "10.1123/ijspp.5.3.276"})

    def test_coach_prompt_and_agent_docs_are_wired(self):
        coach = (REPO / "agents/coach.md").read_text(encoding="utf-8")
        self.assertIn("plan-templates", coach)
        self.assertIn("never overrides", coach)
        self.assertIn("plan-templates", (REPO / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("plans.md", (REPO / "docs/agents/coach.md").read_text(encoding="utf-8"))
        self.assertIn("plan-templates", (REPO / "docs/skills.md").read_text(encoding="utf-8"))
        self.assertIn("docs/plans.md", (REPO / "README.md").read_text(encoding="utf-8"))

    def test_skeleton_generator_is_documented_and_wired(self):
        """#190 : `plan-skeleton` dans la page, le prompt du coach (dry run, écriture sur accord, jamais
        d'écrasement), AGENTS.md, le README et les docs de l'agent."""
        self.assertIn("arc_index.py plan-skeleton", PLANS_MD)
        self.assertIn("#le-squelette-de-bloc-plan-skeleton", PLANS_MD)
        self.assertIn("## Le squelette de bloc (`plan-skeleton`)", PLANS_MD)
        for token in ("too_short", "no_history", "lead_in", "--write", "Aucun écrasement"):
            self.assertIn(token, PLANS_MD, token)
        coach = (REPO / "agents/coach.md").read_text(encoding="utf-8")
        self.assertIn("plan-skeleton", coach)
        self.assertIn("Write ONLY after an explicit yes", coach)
        self.assertIn("never overwrites", coach)
        self.assertIn("plan-skeleton", (REPO / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("plan-skeleton", (REPO / "README.md").read_text(encoding="utf-8"))
        self.assertIn("plan-skeleton", (REPO / "docs/agents/coach.md").read_text(encoding="utf-8"))
        self.assertIn("plan-skeleton", (REPO / "docs/skills.md").read_text(encoding="utf-8"))
        self.assertNotIn("is NOT available yet (#190)", coach)

    def test_skeleton_contract_keys_are_documented(self):
        import arc_contract as C
        skill = (REPO / "skills/workspace-data-contract/SKILL.md").read_text(encoding="utf-8")
        for key in ("week_type", "quality_sessions", "long_run_target_s", "strength_emphasis"):
            self.assertIn(key, C.SCHEMA["week"]["optional"])
            self.assertIn(key, C.SUBSCHEMA["week_entry"]["optional"])
            self.assertIn(f"`{key}`", skill)
        self.assertIn("placeholder", C.SUBSCHEMA["session"]["optional"])
        self.assertIn("`placeholder`", skill)

    def test_templates_are_shipped_with_the_engine_not_in_resources(self):
        self.assertTrue(any((REPO / "config/plans").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
