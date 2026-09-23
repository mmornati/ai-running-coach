"""Palier D — contrat de données : le skill et le validateur disent la même chose.

Le schéma exécutable vit dans `scripts/arc_contract.py`, sa documentation pour les
agents dans `skills/workspace-data-contract/SKILL.md`. S'ils divergent, un agent
écrit ce que le skill décrit et le validateur le refuse — ou l'inverse, en silence.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402

SKILL = (REPO / "skills/workspace-data-contract/SKILL.md").read_text(encoding="utf-8")


class TestSkillMatchesSchema(unittest.TestCase):
    def test_every_skill_example_validates(self):
        """Un exemple du skill qui ne valide pas apprend aux agents à écrire faux."""
        blocks = C.find_blocks(SKILL)
        self.assertGreater(len(blocks), 8)
        for raw in blocks:
            data = json.loads(raw)
            errors, warnings = C.validate(data)
            self.assertEqual(errors + warnings, [], f"exemple {data.get('kind')} :\n{raw[:200]}")

    def test_every_kind_has_an_example(self):
        kinds = {json.loads(b)["kind"] for b in C.find_blocks(SKILL)}
        self.assertEqual(set(C.KINDS) - kinds, set(), "types sans exemple dans le skill")

    def test_every_key_is_documented(self):
        """Une clé du schéma absente du skill ne sera jamais écrite par un agent."""
        documented = set(re.findall(r"`([a-z_]+)`", SKILL))
        for kind in list(C.SCHEMA) + list(C.SUBSCHEMA):
            self.assertEqual(C.documented_keys(kind) - documented, set(), f"clés non documentées ({kind})")
        self.assertEqual(set(C.SPLIT_COLUMNS) - documented, set(), "colonnes de splits non documentées")


class TestValidator(unittest.TestCase):
    def base(self, **extra):
        return {"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, **extra}

    def test_error_names_the_key(self):
        errors, _ = C.validate(self.base(avg_hr_bpm="148 bpm"))
        self.assertTrue(any("avg_hr_bpm" in e for e in errors), errors)

    def test_units_are_si_numbers(self):
        """« 12,4 km » dans le bloc : c'est exactement ce que le contrat supprime."""
        errors, _ = C.validate(self.base(distance_m="12,4 km"))
        self.assertTrue(errors)

    def test_null_is_not_zero(self):
        """Une mesure absente (null) est admise ; elle n'est pas convertie en 0."""
        errors, _ = C.validate(self.base(recovery_hr_bpm=None, missing_reason={"recovery_hr_bpm": "validée trop tôt"}))
        self.assertEqual(errors, [])

    def test_unknown_key_is_warned(self):
        _, warnings = C.validate(self.base(avg_hr=148))
        self.assertTrue(any("avg_hr" in w for w in warnings))

    def test_splits_follow_declared_header(self):
        """L'en-tête est dans la donnée : une ligne plus courte est une erreur, pas un décalage muet."""
        errors, _ = C.validate(self.base(splits_cols=["km", "duration_s", "avg_hr_bpm"], splits=[[1, 358, 120], [2, 372]]))
        self.assertTrue(any("splits[1]" in e for e in errors), errors)

    def test_verdict_requires_reason(self):
        errors, _ = C.validate({"arc": 1, "kind": "health", "date": "2026-09-20", "morning_check": "full", "verdict": "red"})
        self.assertTrue(any("verdict_reason" in e for e in errors))

    def test_two_blocks_rejected(self):
        with self.assertRaises(C.ContractError):
            C.extract_block("# T\n\n```arc\n{}\n```\n\n```arc\n{}\n```\n")

    def test_block_is_found_after_title(self):
        text = '# Séance\n\n```arc\n{"arc": 1}\n```\n\nTexte.'
        self.assertEqual(C.extract_block(text), {"arc": 1})
        self.assertEqual(C.body_after_block(text), "# Séance\n\nTexte.")


if __name__ == "__main__":
    unittest.main()
