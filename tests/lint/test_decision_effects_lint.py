"""Palier B — le bilan « effet des décisions » (#175) reste une corrélation, jamais un assouplissement."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_decision_effects as DE  # noqa: E402

PROMPTS = ("agents/coach.md", "skills/why/SKILL.md")


def _section(rel: str, marker: str) -> str:
    text = (REPO / rel).read_text(encoding="utf-8")
    assert marker in text, f"{rel} : « {marker} » introuvable"
    return text.split(marker, 1)[1].split("\n###", 1)[0]


class TestPromptsCiteTheSynthesisSafely(unittest.TestCase):
    def test_prompts_use_the_script_and_state_the_three_guards(self):
        for rel in PROMPTS:
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("arc_index.py decision-effects", text, rel)
            low = text.lower()
            self.assertIn("correlation is not causation", low, rel)
            self.assertRegex(text, r"NEVER[^.]*relax a `block` guardrail, a medical\s+decision or a red verdict", rel)
            self.assertIn("trend_allowed", text, rel)

    def test_no_prompt_lets_the_synthesis_relax_a_guardrail(self):
        """Toute phrase qui relie le bilan à un assouplissement doit être une interdiction."""
        for rel in PROMPTS:
            text = (REPO / rel).read_text(encoding="utf-8")
            for m in re.finditer(r"[^.\n]*decision-effects[^.\n]*(relax|override|ignore)[^.\n]*", text, re.I):
                self.assertRegex(m.group(0), r"(?i)never|not", f"{rel} : {m.group(0)!r}")

    def test_docs_carry_the_same_guards(self):
        for rel in ("docs/skills/why.md", "docs/agents/coach.md", "docs/dashboard/views.md", "AGENTS.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertRegex(text, r"(?i)corrélation, pas causalité", rel)
            self.assertRegex(text, r"(?i)(n'assouplit\W+jamais|jamais\W[^.]*assouplir)", rel)
            self.assertIn("5 cas", text, rel)


class TestAssumptionsAndCaveat(unittest.TestCase):
    def test_caveat_and_assumptions_state_the_limits(self):
        self.assertIn("Corrélation, pas causalité", DE.CAVEAT)
        self.assertIn("block", DE.CAVEAT)
        for key in ("not_causal", "windows", "thresholds", "combination", "sample", "scope", "storage"):
            self.assertIn(key, DE.ASSUMPTIONS)
        self.assertIn("APPROXIMATIONS DU PROJET", DE.ASSUMPTIONS["thresholds"])
        self.assertEqual(DE.MIN_SAMPLE_FOR_TREND, 5)

    def test_metrics_assumption_mentions_it(self):
        import arc_metrics as M
        self.assertIn("CORRÉLATION, PAS CAUSALITÉ", M.ASSUMPTIONS["decision_effects"])

    def test_every_trigger_has_a_plan(self):
        import arc_contract as C
        self.assertEqual(set(DE.TRIGGER_PLAN), set(C.DECISION_TRIGGER))
        for plan in DE.TRIGGER_PLAN.values():
            for signal in plan["signals"]:
                self.assertIn(signal, DE.SIGNALS)

    def test_docs_do_not_use_forbidden_causal_wording(self):
        for rel in ("docs/dashboard/views.md", "docs/skills/why.md"):
            text = (REPO / rel).read_text(encoding="utf-8").lower()
            self.assertNotIn("a prouvé que", text, rel)


if __name__ == "__main__":
    unittest.main()
