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


class TestFitKpiFields(unittest.TestCase):
    """#51, revue de code : `time_in_zone_s` et `decoupling_pct` ne sont pas de
    simples `obj`/`num` — un objet mal formé ou une plage physiologiquement
    absurde doit être signalé, pas recopié tel quel dans l'index."""

    def base(self, **extra):
        return {"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "running",
                "duration_s": 4200, **extra}

    def test_valid_time_in_zone_passes(self):
        errors, warnings = C.validate(self.base(time_in_zone_s={"z1": 1470, "z2": 1470, "z3": 1260}))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_unknown_zone_key_is_warned(self):
        _, warnings = C.validate(self.base(time_in_zone_s={"z1": 100, "zz": 50}))
        self.assertTrue(any("time_in_zone_s.zz" in w for w in warnings), warnings)

    def test_negative_seconds_is_an_error(self):
        errors, _ = C.validate(self.base(time_in_zone_s={"z1": -5}))
        self.assertTrue(any("time_in_zone_s.z1" in e for e in errors), errors)

    def test_non_numeric_seconds_is_an_error(self):
        errors, _ = C.validate(self.base(time_in_zone_s={"z9": "x", "z1": "x"}))
        # `z9` échoue déjà comme clé inconnue (avertissement) ; `z1` doit échouer
        # comme valeur non numérique (erreur), pas être silencieusement accepté.
        self.assertTrue(any("time_in_zone_s.z1" in e for e in errors), errors)

    def test_seconds_above_duration_s_is_an_error(self):
        errors, _ = C.validate(self.base(duration_s=3600, time_in_zone_s={"z1": 4000}))
        self.assertTrue(any("time_in_zone_s.z1" in e and "3600" in e for e in errors), errors)

    def test_seconds_equal_to_duration_s_is_accepted(self):
        errors, _ = C.validate(self.base(duration_s=3600, time_in_zone_s={"z1": 3600}))
        self.assertEqual(errors, [])

    def test_decoupling_pct_within_range_is_silent(self):
        errors, warnings = C.validate(self.base(decoupling_pct=12.9))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_decoupling_pct_negative_within_range_is_silent(self):
        """Une dérive négative (« monte en régime ») reste physiologiquement plausible."""
        errors, warnings = C.validate(self.base(decoupling_pct=-8.0))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_decoupling_pct_far_out_of_range_is_a_warning_not_an_error(self):
        errors, warnings = C.validate(self.base(decoupling_pct=250.0))
        self.assertEqual(errors, [])
        self.assertTrue(any("decoupling_pct" in w for w in warnings), warnings)

    def test_decoupling_pct_wrong_type_is_an_error(self):
        errors, _ = C.validate(self.base(decoupling_pct="12%"))
        self.assertTrue(any("decoupling_pct" in e for e in errors), errors)

    def test_best_climb_vam_m_h_valid(self):
        errors, _ = C.validate(self.base(best_climb_vam_m_h=620))
        self.assertEqual(errors, [])

    def test_best_climb_vam_m_h_negative_is_rejected(self):
        errors, _ = C.validate(self.base(best_climb_vam_m_h=-10))
        self.assertTrue(any("best_climb_vam_m_h" in e for e in errors), errors)


class TestDecision(unittest.TestCase):
    """#54 : nouveau type `decision` — traçabilité d'un ajustement du coach."""

    def base(self, **extra):
        return {
            "arc": 1, "kind": "decision", "date": "2026-09-22", "created_at": "2026-09-22T07:10:00+02:00",
            "trigger": "morning_check", "summary": "HRV basse : séance de qualité allégée.",
            "outcome": "applied", **extra,
        }

    def test_minimal_valid_decision_passes(self):
        errors, warnings = C.validate(self.base())
        self.assertEqual(errors + warnings, [])

    def test_full_decision_passes(self):
        errors, warnings = C.validate(self.base(
            inputs={"hrv_personal_status": "sous", "readiness_score": 52},
            rule_ids=["r5_quality_after_red"],
            sources=["medical/2026-09-22_health.md", "resources/running/acwr.md"],
            before={"date": "2026-09-22", "sport": "trail", "title": "Côtes 8 x 90 s",
                    "intensity": "vo2max", "planned_duration_s": 4200},
            after={"intensity": "recovery", "planned_duration_s": 2400, "status": "planned"},
            session_ref={"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-22"},
            garmin_workout_id=998877,
        ))
        self.assertEqual(errors + warnings, [])

    def test_missing_required_key_is_an_error(self):
        data = self.base()
        del data["summary"]
        errors, _ = C.validate(data)
        self.assertTrue(any("summary" in e for e in errors), errors)

    def test_unknown_trigger_is_rejected(self):
        errors, _ = C.validate(self.base(trigger="coach_whim"))
        self.assertTrue(any("trigger" in e for e in errors), errors)

    def test_unknown_outcome_is_rejected(self):
        errors, _ = C.validate(self.base(outcome="ignored"))
        self.assertTrue(any("outcome" in e for e in errors), errors)

    def test_rule_id_bad_format_is_rejected(self):
        errors, _ = C.validate(self.base(rule_ids=["acwr_too_high"]))
        self.assertTrue(any("rule_ids" in e for e in errors), errors)

    def test_rule_id_unknown_number_still_matches_pattern(self):
        """Un futur `r8_...` (règle pas encore créée) ne doit pas être rejeté par le
        contrat : seul le FORMAT est validé, jamais la liste vivante des règles
        (voir la note dans arc_contract.py sur le cycle d'import avec arc_guardrails)."""
        errors, _ = C.validate(self.base(rule_ids=["r8_future_rule"]))
        self.assertEqual(errors, [])

    def test_rule_ids_not_a_list_is_rejected(self):
        errors, _ = C.validate(self.base(rule_ids="r1_acwr_projected"))
        self.assertTrue(any("rule_ids" in e for e in errors), errors)

    def test_source_url_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["https://example.com/x"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_absolute_path_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["/etc/passwd"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_parent_traversal_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["../../etc/passwd"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_relative_workspace_path_is_accepted(self):
        errors, warnings = C.validate(self.base(sources=["medical/2026-09-22_health.md"]))
        self.assertEqual(errors + warnings, [])

    def test_before_wrong_type_is_rejected(self):
        errors, _ = C.validate(self.base(before="séance annulée"))
        self.assertTrue(any("before" in e for e in errors), errors)

    def test_before_unknown_key_is_warned(self):
        _, warnings = C.validate(self.base(before={"duration_s": 3600}))
        self.assertTrue(any("before.duration_s" in w for w in warnings), warnings)

    def test_before_bad_intensity_is_rejected(self):
        errors, _ = C.validate(self.base(before={"intensity": "max_effort"}))
        self.assertTrue(any("before.intensity" in e for e in errors), errors)

    def test_after_cancellation_status_only_is_valid(self):
        """Une annulation ne change que `status`, tout le reste est facultatif."""
        errors, warnings = C.validate(self.base(after={"status": "cancelled"}))
        self.assertEqual(errors + warnings, [])

    def test_session_ref_missing_required_key_is_rejected(self):
        errors, _ = C.validate(self.base(session_ref={"week": "planning/Semaine_2026-09-21.md"}))
        self.assertTrue(any("session_ref" in e and "date" in e for e in errors), errors)

    def test_session_ref_wrong_type_is_rejected(self):
        errors, _ = C.validate(self.base(session_ref="Semaine_2026-09-21.md"))
        self.assertTrue(any("session_ref" in e for e in errors), errors)

    def test_created_at_before_date_is_fine(self):
        """Écrite la veille au soir pour le lendemain : aucune borne basse."""
        errors, warnings = C.validate(self.base(
            date="2026-09-22", created_at="2026-09-21T21:30:00+02:00"))
        self.assertEqual(errors + warnings, [])

    def test_created_at_same_day_is_fine(self):
        errors, warnings = C.validate(self.base(
            date="2026-09-22", created_at="2026-09-22T23:59:00+02:00"))
        self.assertEqual(errors + warnings, [])

    def test_created_at_far_in_the_future_is_rejected(self):
        errors, _ = C.validate(self.base(
            date="2026-09-20", created_at="2026-09-25T08:00:00+02:00"))
        self.assertTrue(any("created_at" in e for e in errors), errors)

    def test_garmin_workout_id_must_be_a_positive_integer(self):
        errors, _ = C.validate(self.base(garmin_workout_id=-5))
        self.assertTrue(any("garmin_workout_id" in e for e in errors), errors)

    # -- #100, revue de code : fuseau obligatoire sur created_at -------------

    def test_created_at_naive_is_rejected(self):
        errors, _ = C.validate(self.base(created_at="2026-09-22T07:10:00"))
        self.assertTrue(any("created_at" in e for e in errors), errors)

    def test_created_at_with_z_is_accepted(self):
        errors, warnings = C.validate(self.base(
            date="2026-09-22", created_at="2026-09-22T07:10:00Z"))
        self.assertEqual(errors + warnings, [])

    def test_created_at_with_offset_is_accepted(self):
        errors, warnings = C.validate(self.base(
            date="2026-09-22", created_at="2026-09-22T07:10:00+02:00"))
        self.assertEqual(errors + warnings, [])

    # -- #100, revue de code : chemins relatifs au workspace durcis ----------

    def test_source_backslash_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["C:\\Users\\x.md"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_windows_drive_letter_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["C:/Users/x.md"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_leading_tilde_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["~/secret.md"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_mailto_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["mailto:a@b"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_file_scheme_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["file:/etc/passwd"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_double_slash_empty_segment_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["resources//x.md"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    def test_source_windows_style_traversal_is_rejected(self):
        errors, _ = C.validate(self.base(sources=["..\\..\\etc\\passwd"]))
        self.assertTrue(any("sources" in e for e in errors), errors)

    # -- `supersedes` (#100, revue de code) -----------------------------------

    def test_supersedes_valid_path_is_accepted(self):
        errors, warnings = C.validate(self.base(
            supersedes="planning/2026-09-21_decision_allegement.md"))
        self.assertEqual(errors + warnings, [])

    def test_supersedes_absolute_path_is_rejected(self):
        errors, _ = C.validate(self.base(supersedes="/etc/passwd"))
        self.assertTrue(any("supersedes" in e for e in errors), errors)

    def test_supersedes_backslash_is_rejected(self):
        errors, _ = C.validate(self.base(supersedes="planning\\2026-09-21_decision_allegement.md"))
        self.assertTrue(any("supersedes" in e for e in errors), errors)

    def test_supersedes_tilde_is_rejected(self):
        errors, _ = C.validate(self.base(supersedes="~/x.md"))
        self.assertTrue(any("supersedes" in e for e in errors), errors)

    def test_supersedes_colon_is_rejected(self):
        errors, _ = C.validate(self.base(supersedes="C:/x.md"))
        self.assertTrue(any("supersedes" in e for e in errors), errors)

    def test_supersedes_dot_segment_is_rejected(self):
        errors, _ = C.validate(self.base(supersedes="planning/./x.md"))
        self.assertTrue(any("supersedes" in e for e in errors), errors)

    def test_supersedes_parent_segment_is_rejected(self):
        errors, _ = C.validate(self.base(supersedes="planning/../x.md"))
        self.assertTrue(any("supersedes" in e for e in errors), errors)

    # -- `session_ref.week` durci comme `sources`/`supersedes` (#100) --------

    def test_session_ref_week_backslash_is_rejected(self):
        errors, _ = C.validate(self.base(
            session_ref={"week": "planning\\Semaine_2026-09-21.md", "date": "2026-09-22"}))
        self.assertTrue(any("session_ref.week" in e for e in errors), errors)

    def test_session_ref_week_tilde_is_rejected(self):
        errors, _ = C.validate(self.base(
            session_ref={"week": "~/Semaine_2026-09-21.md", "date": "2026-09-22"}))
        self.assertTrue(any("session_ref.week" in e for e in errors), errors)

    def test_session_ref_week_valid_path_is_accepted(self):
        errors, warnings = C.validate(self.base(
            session_ref={"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-22"}))
        self.assertEqual(errors + warnings, [])


class TestGuardrailRuleIdsMatchContractPattern(unittest.TestCase):
    """#100, revue de code : `arc_guardrails.RULE_IDS` et `arc_contract.RULE_ID_RE`
    ne doivent jamais diverger silencieusement — un `rule_id` réel qui ne
    matcherait plus le motif validé côté contrat casserait `decision.rule_ids`
    pour toute nouvelle décision qui le cite."""

    def test_every_known_rule_id_matches_the_contract_pattern(self):
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "scripts"))
        import arc_guardrails as G  # noqa: E402  (import tardif : évite le cycle au chargement du module)

        self.assertGreater(len(G.RULE_IDS), 0)
        for rule_id in G.RULE_IDS:
            self.assertRegex(rule_id, C.RULE_ID_RE, f"rule_id {rule_id!r} ne matche pas RULE_ID_RE")


if __name__ == "__main__":
    unittest.main()
