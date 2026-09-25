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


class TestGearSweatFuel(unittest.TestCase):
    """#39 : gear_id, carbs_g, fluid_intake_ml, weight_pre_kg/weight_post_kg."""

    def base(self, **extra):
        return {"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, **extra}

    def test_valid_fields_pass(self):
        errors, warnings = C.validate(self.base(
            gear_id="hoka-speedgoat-5-bleue", carbs_g=72, fluid_intake_ml=900,
            weight_pre_kg=70.2, weight_post_kg=69.1))
        self.assertEqual(errors + warnings, [])

    def test_gear_id_must_be_a_slug(self):
        errors, _ = C.validate(self.base(gear_id="Hoka Speedgoat 5"))
        self.assertTrue(any("gear_id" in e for e in errors), errors)

    def test_gear_id_too_long_is_rejected(self):
        errors, _ = C.validate(self.base(gear_id="a" * (C.GEAR_ID_MAX_LEN + 1)))
        self.assertTrue(any("gear_id" in e for e in errors), errors)

    def test_gear_id_empty_string_is_rejected(self):
        errors, _ = C.validate(self.base(gear_id=""))
        self.assertTrue(any("gear_id" in e for e in errors), errors)

    def test_carbs_g_negative_is_rejected(self):
        errors, _ = C.validate(self.base(carbs_g=-5))
        self.assertTrue(any("carbs_g" in e for e in errors), errors)

    def test_carbs_g_above_plausible_max_is_rejected(self):
        errors, _ = C.validate(self.base(carbs_g=C.CARBS_G_PLAUSIBLE_MAX + 1))
        self.assertTrue(any("carbs_g" in e for e in errors), errors)

    def test_carbs_g_at_plausible_max_is_accepted(self):
        errors, _ = C.validate(self.base(carbs_g=C.CARBS_G_PLAUSIBLE_MAX))
        self.assertEqual(errors, [])

    def test_carbs_g_as_string_is_rejected(self):
        """« bool traité comme un nombre » et « chaîne traitée comme un nombre » sont les deux
        pièges classiques d'un contrat JSON : `True` est un `int` en Python, `"72"` ressemble à
        un nombre à l'œil. Les deux doivent être refusés, pas silencieusement acceptés."""
        errors, _ = C.validate(self.base(carbs_g="72"))
        self.assertTrue(any("carbs_g" in e for e in errors), errors)

    def test_carbs_g_bool_is_rejected(self):
        errors, _ = C.validate(self.base(carbs_g=True))
        self.assertTrue(any("carbs_g" in e for e in errors), errors)

    def test_fluid_intake_ml_negative_is_rejected(self):
        errors, _ = C.validate(self.base(fluid_intake_ml=-1))
        self.assertTrue(any("fluid_intake_ml" in e for e in errors), errors)

    def test_fluid_intake_ml_above_plausible_max_is_rejected(self):
        errors, _ = C.validate(self.base(fluid_intake_ml=C.FLUID_INTAKE_ML_PLAUSIBLE_MAX + 1))
        self.assertTrue(any("fluid_intake_ml" in e for e in errors), errors)

    def test_weight_pre_kg_below_plausible_min_is_rejected(self):
        errors, _ = C.validate(self.base(weight_pre_kg=C.BODY_WEIGHT_KG_PLAUSIBLE[0] - 1))
        self.assertTrue(any("weight_pre_kg" in e for e in errors), errors)

    def test_weight_post_kg_above_plausible_max_is_rejected(self):
        errors, _ = C.validate(self.base(weight_post_kg=C.BODY_WEIGHT_KG_PLAUSIBLE[1] + 1))
        self.assertTrue(any("weight_post_kg" in e for e in errors), errors)

    def test_weight_post_above_pre_within_tolerance_is_silent(self):
        errors, warnings = C.validate(self.base(weight_pre_kg=70.0, weight_post_kg=70.5))
        self.assertEqual(errors + warnings, [])

    def test_weight_post_above_pre_beyond_tolerance_warns_not_errors(self):
        """La pesée peut être imprécise (habits, balance) : un avertissement, pas un rejet."""
        errors, warnings = C.validate(self.base(weight_pre_kg=70.0, weight_post_kg=71.5))
        self.assertEqual(errors, [])
        self.assertTrue(any("weight_post_kg" in w for w in warnings), warnings)


class TestGearSlug(unittest.TestCase):
    """`arc_contract.gear_slug()` : règle PARTAGÉE entre #39 (validation), #40 (lecture
    du profil) et le coach (choix du `gear_id` d'une activité)."""

    def test_lowercases_and_hyphenates_spaces(self):
        self.assertEqual(C.gear_slug("Hoka Speedgoat 5 Bleue"), "hoka-speedgoat-5-bleue")

    def test_strips_accents(self):
        self.assertEqual(C.gear_slug("Adidas Adizero Évo Été"), "adidas-adizero-evo-ete")

    def test_collapses_punctuation_to_a_single_hyphen(self):
        self.assertEqual(C.gear_slug("Salomon S/Lab --- Ultra !!"), "salomon-s-lab-ultra")

    def test_trims_leading_and_trailing_hyphens(self):
        self.assertEqual(C.gear_slug("  -Nike Pegasus- "), "nike-pegasus")

    def test_truncates_to_max_length(self):
        slug = C.gear_slug("a" * 60)
        self.assertLessEqual(len(slug), C.GEAR_ID_MAX_LEN)
        self.assertEqual(slug, "a" * C.GEAR_ID_MAX_LEN)

    def test_truncation_does_not_leave_a_trailing_hyphen(self):
        # 39 lettres + un tiret juste à la coupe (40e caractère) : le tiret de fin
        # laissé par la coupe doit être retiré, pas gardé tel quel.
        label = "a" * 39 + "-" + "b" * 10
        slug = C.gear_slug(label)
        self.assertFalse(slug.endswith("-"), slug)
        self.assertLessEqual(len(slug), C.GEAR_ID_MAX_LEN)

    def test_no_alphanumeric_content_gives_empty_string(self):
        self.assertEqual(C.gear_slug("   !!! --- "), "")

    def test_output_always_matches_the_contract_pattern(self):
        """Un slug dérivé doit toujours être accepté par le validateur (sauf vide)."""
        slug = C.gear_slug("Hoka Speedgoat 5 Bleue")
        errors, _ = C.validate({"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail",
                                "duration_s": 3600, "gear_id": slug})
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
