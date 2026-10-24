"""Palier B — moteur de règles des chaussures (#301) : `config/shoes/rules.json` (niveau de preuve et
référence exigés par règle, références vérifiées, pas de marque ni de modèle) et `docs/shoes.md`
(synthèse des preuves, références complètes, limites, mention « pas un avis médical »)."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_shoe_needs as SN  # noqa: E402

RULES = json.loads((REPO / "config/shoes/rules.json").read_text(encoding="utf-8"))
DOC = (REPO / "docs/shoes.md").read_text(encoding="utf-8")
BRANDS = ("salomon", "kiprun", "hoka", "nike", "adidas", "asics", "brooks", "altra", "saucony", "decathlon", "vaporfly")


class TestRulesFile(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(SN.validate_rules(RULES), [])

    def test_every_rule_has_confidence_and_a_reference_or_a_rationale(self):
        for r in RULES["rules"]:
            self.assertIn(r["confidence"], SN.CONFIDENCE_ORDER, r["id"])
            if r["confidence"] in ("none", "expert_opinion"):
                self.assertTrue(r.get("rationale", "").strip(), r["id"])
            else:
                self.assertTrue(r["references"], r["id"])

    def test_references_are_https_and_documented_as_verified(self):
        for sid, s in RULES["sources"].items():
            self.assertTrue(s["url"].startswith("https://"), sid)
            self.assertTrue(s["verified"].strip(), sid)

    def test_no_brand_or_model_in_rules(self):
        text = json.dumps(RULES, ensure_ascii=False).lower()
        for brand in BRANDS:
            self.assertNotIn(brand, text, brand)

    def test_states_it_is_not_medical_advice(self):
        self.assertIn("pas un avis médical", RULES["disclaimer"])

    def test_dropped_citations_are_listed(self):
        dropped = " ".join(d["citation"] for d in RULES["unverified_dropped"])
        for name in ("Chambon", "Kulmala", "trail"):
            self.assertIn(name, dropped)

    def test_rules_have_a_handler(self):
        self.assertEqual(sorted(r["id"] for r in RULES["rules"]), sorted(SN.HANDLED_RULES))


class TestDocs(unittest.TestCase):
    def test_evidence_section_replaces_the_placeholder(self):
        self.assertIn("## Ce que disent les preuves", DOC)
        self.assertNotIn("À compléter par la story #301", DOC)
        self.assertIn("pas un avis médical", DOC)
        self.assertIn("### Limites", DOC)

    def test_every_source_url_of_the_rules_is_in_the_docs(self):
        for sid, s in RULES["sources"].items():
            self.assertIn(s["url"], DOC, sid)

    def test_command_is_documented(self):
        self.assertIn("shoe-needs --role", DOC)
        self.assertIn("config/shoes/rules.json", DOC)
        self.assertIn("shoe-needs --role", (REPO / "AGENTS.md").read_text(encoding="utf-8"))

    def test_docs_name_no_brand(self):
        section = DOC[DOC.index("## Besoins pour la prochaine paire"):].lower()
        for brand in BRANDS:
            self.assertNotRegex(section, rf"\b{brand}\b", brand)

    def test_confidence_levels_are_all_mentioned(self):
        for level in SN.CONFIDENCE_ORDER:
            self.assertIn(level, DOC)


if __name__ == "__main__":
    unittest.main()
