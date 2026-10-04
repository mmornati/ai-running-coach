"""Palier B — bibliothèque de renforcement (#191) : docs, navigation, prompt du coach, et surtout aucune
clé Garmin non vérifiée dans les données ni dans la doc.

Lecture statique : la page `docs/strength.md` existe, est dans la nav, cite chaque programme et chaque
exercice livrés et seulement des sources vérifiées ; le prompt du coach et AGENTS.md pointent vers la
commande ; les données vivent dans `config/strength/` (pas dans `resources/`, exclu du dépôt)."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import arc_strength as SG  # noqa: E402

DOC_MD = (REPO / "docs/strength.md").read_text(encoding="utf-8")
EXERCISES, PROGRAMMES = SG.load_library()
WHITELIST_TOKENS = set(SG.GARMIN_VERIFIED) | {x for xs in SG.GARMIN_VERIFIED.values() for x in xs}
GARMIN_LIKE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\b(?:CARDIO|SQUAT|LUNGE|PLANK|PLYO|CARRY|CORE|CRUNCH)\b")


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


class TestNoUnverifiedGarminNames(unittest.TestCase):
    def test_data_files_only_carry_whitelisted_garmin_keys(self):
        for name in ("exercises.json", "programmes.json"):
            data = json.loads((REPO / "config/strength" / name).read_text(encoding="utf-8"))
            for s in strings(data):
                for token in GARMIN_LIKE.findall(s):
                    self.assertIn(token, WHITELIST_TOKENS, f"{name} : « {token} » absent de GARMIN_VERIFIED")

    def test_doc_page_only_cites_whitelisted_garmin_keys(self):
        for token in GARMIN_LIKE.findall(DOC_MD):
            if token == "GARMIN_VERIFIED":      # le nom de la liste blanche elle-même
                continue
            self.assertIn(token, WHITELIST_TOKENS, f"docs/strength.md : « {token} »")

    def test_data_shipped_with_the_engine_not_in_resources(self):
        self.assertTrue((REPO / "config/strength/exercises.json").is_file())
        self.assertTrue((REPO / "config/strength/programmes.json").is_file())


class TestStrengthDocs(unittest.TestCase):
    def test_page_is_in_the_mkdocs_nav(self):
        self.assertRegex((REPO / "mkdocs.yml").read_text(encoding="utf-8"), r"(?m)^\s*- [^\n]+: strength\.md$")

    def test_page_lists_every_programme_and_exercise(self):
        for p in PROGRAMMES["programmes"]:
            self.assertIn(f"`{p['id']}`", DOC_MD, p["id"])
        for eid in EXERCISES:
            self.assertIn(f"`{eid}`", DOC_MD, eid)

    def test_page_names_the_command_the_caveat_and_the_confirmation_rule(self):
        self.assertIn("arc_index.py strength", DOC_MD)
        self.assertIn("approximations du projet", DOC_MD)
        self.assertIn("aucun diagnostic", DOC_MD)
        self.assertIn("jamais en mode headless", DOC_MD)
        self.assertIn("GARMIN_VERIFIED", DOC_MD)

    def test_only_verified_references_are_cited(self):
        dois = set(re.findall(r"doi:(10\.[^\s)\]]+)", DOC_MD))
        self.assertEqual(dois, {"10.1007/s40279-017-0835-7", "10.1007/s40279-014-0157-y"})
        self.assertEqual({s["doi"] for s in PROGRAMMES["sources"]}, dois)

    def test_coach_prompt_and_docs_are_wired(self):
        coach = (REPO / "agents/coach.md").read_text(encoding="utf-8")
        self.assertIn("arc_index.py strength", coach)
        self.assertIn("Never invent the exercises", coach)
        self.assertIn("approximation du projet", coach)
        self.assertIn("arc_index.py strength", (REPO / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("strength.md", (REPO / "docs/agents/coach.md").read_text(encoding="utf-8"))
        self.assertIn("strength.md", (REPO / "docs/skills/garmin-workout-scheduling.md").read_text(encoding="utf-8"))
        self.assertIn("strength.md", (REPO / "docs/skills.md").read_text(encoding="utf-8"))
        self.assertIn("docs/strength.md", (REPO / "README.md").read_text(encoding="utf-8"))
        self.assertIn("strength", (REPO / "skills/garmin-workout-scheduling/SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("strength", (REPO / "skills/intervals-icu-best-practices/SKILL.md").read_text(encoding="utf-8"))

    def test_push_confirmation_rules_are_not_weakened(self):
        coach = (REPO / "agents/coach.md").read_text(encoding="utf-8")
        self.assertIn('explicit "yes" in the conversation, never headless', coach)


if __name__ == "__main__":
    unittest.main()
