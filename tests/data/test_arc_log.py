"""Palier D — `scripts/arc_log.py` : arithmétique, correspondance catalogue et
fusion pour `/log` (#67).

Le LLM ne fait que l'extraction d'entités (quel produit, quelle quantité, quelle
douleur...) ; toute la conversion catalogue, les sommes et la fusion avec un
fichier existant sont ici, en pur stdlib, pour être exactes, idempotentes et
testables sans jamais invoquer de modèle.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_guardrails  # noqa: E402
import arc_index  # noqa: E402
import arc_log as L  # noqa: E402

CATALOGUE_MD = """
# Catalogue produits — test

| Produit | Portion | Glucides |
|---|---|---|
| Gel Fixture Test | 1 sachet (40 g) | 32 g |
| Barre Fixture Energie | 1 barre (50 g) | 28 g |
| Barre Fixture Recup | 1 barre (60 g) | 20 g |
| Barres Fixture Plurielles | 1 barre (45 g) | 24 g |
"""


class TestNormalizeAndParsing(unittest.TestCase):
    def test_normalize_name_strips_accents_and_case(self):
        self.assertEqual(L.normalize_name("Gel Énergétique"), "gel energetique")


class TestParseQuantity(unittest.TestCase):
    def test_accepts_comma_decimal(self):
        self.assertEqual(L.parse_quantity("2"), 2.0)
        self.assertEqual(L.parse_quantity("0,5"), 0.5)
        self.assertEqual(L.parse_quantity(3), 3.0)

    def test_rejects_garbage(self):
        with self.assertRaises(L.ArcLogError):
            L.parse_quantity("beaucoup")

    def test_rejects_negative_string(self):
        with self.assertRaises(L.ArcLogError):
            L.parse_quantity("-2")

    def test_rejects_negative_number(self):
        with self.assertRaises(L.ArcLogError):
            L.parse_quantity(-1)

    def test_fraction_et_demi(self):
        self.assertEqual(L.parse_quantity("1 et demi"), 1.5)
        self.assertEqual(L.parse_quantity("2 et demie"), 2.5)

    def test_fraction_unicode_half(self):
        self.assertEqual(L.parse_quantity("1½"), 1.5)
        self.assertEqual(L.parse_quantity("½"), 0.5)

    def test_word_numbers(self):
        self.assertEqual(L.parse_quantity("un"), 1.0)
        self.assertEqual(L.parse_quantity("deux"), 2.0)
        self.assertEqual(L.parse_quantity("trois"), 3.0)

    def test_word_number_with_fraction(self):
        self.assertEqual(L.parse_quantity("un et demi"), 1.5)

    def test_fullmatch_rejects_trailing_garbage(self):
        """"3 x 40 g" ne doit JAMAIS silencieusement redevenir 3 : la portion
        "40 g" contredirait peut-être le catalogue — ancré par `fullmatch`,
        cette forme composée n'est pas reconnue pour une quantité d'item."""
        with self.assertRaises(L.ArcLogError):
            L.parse_quantity("3 x 40 g")

    def test_out_of_ten_score_form(self):
        """"3/10" (douleur) et "7/10" (RPE) partagent ce même parseur —
        revue de code : ne doivent JAMAIS ressortir `unknown`."""
        self.assertEqual(L.parse_quantity("3/10"), 3.0)
        self.assertEqual(L.parse_quantity("7/10"), 7.0)
        self.assertEqual(L.parse_quantity("3 / 10"), 3.0)

    def test_decimal_with_fraction_suffix_is_rejected(self):
        """Nit (revue de code) : "1.5½" combine déjà une décimale ET une
        fraction — ambigu, ne doit surtout pas silencieusement devenir 2.0."""
        with self.assertRaises(L.ArcLogError):
            L.parse_quantity("1.5½")
        with self.assertRaises(L.ArcLogError):
            L.parse_quantity("1,5 et demi")


class TestParseVolumeMl(unittest.TestCase):
    def test_plain_ml(self):
        self.assertEqual(L.parse_volume_ml("500 ml"), 500.0)
        self.assertEqual(L.parse_volume_ml("750ml"), 750.0)

    def test_liters_comma_decimal(self):
        self.assertEqual(L.parse_volume_ml("0,5 l"), 500.0)
        self.assertEqual(L.parse_volume_ml("1l"), 1000.0)
        self.assertEqual(L.parse_volume_ml("1,5 litres"), 1500.0)

    def test_centiliters_and_deciliters(self):
        self.assertEqual(L.parse_volume_ml("50cl"), 500.0)
        self.assertEqual(L.parse_volume_ml("5 dl"), 500.0)

    def test_multiplication_n_x_m_unit(self):
        self.assertEqual(L.parse_volume_ml("2 x 500 ml"), 1000.0)
        self.assertEqual(L.parse_volume_ml("3 x 40 cl"), 1200.0)

    def test_fraction_forms(self):
        self.assertEqual(L.parse_volume_ml("1 et demi litre"), 1500.0)
        self.assertEqual(L.parse_volume_ml("1½ l"), 1500.0)
        self.assertEqual(L.parse_volume_ml("½ litre"), 500.0)

    def test_word_numbers(self):
        self.assertEqual(L.parse_volume_ml("un litre"), 1000.0)
        self.assertEqual(L.parse_volume_ml("deux litres"), 2000.0)

    def test_bare_number_is_rejected_not_millilitres(self):
        """Revue de code : un nombre nu ("500") n'est plus supposé être en
        millilitres — sans unité, c'est une ambiguïté à faire trancher par
        l'agent (`fluids.unknown`), jamais une valeur devinée."""
        with self.assertRaises(L.ArcLogError):
            L.parse_volume_ml(500)
        with self.assertRaises(L.ArcLogError):
            L.parse_volume_ml("500")

    def test_unrecognized_unit_is_rejected(self):
        """"1 bidon" : "bidon" n'est pas une unité de volume reconnue —
        refusé, jamais 1 ml."""
        with self.assertRaises(L.ArcLogError):
            L.parse_volume_ml("1 bidon")

    def test_mass_unit_is_rejected(self):
        """"3 x 40 g" : "g" est une unité de MASSE, pas de volume — refusé,
        jamais 3 ml."""
        with self.assertRaises(L.ArcLogError):
            L.parse_volume_ml("3 x 40 g")

    def test_negative_is_rejected(self):
        with self.assertRaises(L.ArcLogError):
            L.parse_volume_ml("-500 ml")

    def test_fraction_without_unit_is_rejected(self):
        """"1 et demi" seul (sans unité) reste ambigu comme volume — refusé,
        jamais silencieusement 1 (ou 1.5) ml. Contraste avec
        `TestParseQuantity.test_fraction_et_demi`, où la même phrase EST
        valide pour une quantité d'item solide (pas de notion d'unité)."""
        with self.assertRaises(L.ArcLogError):
            L.parse_volume_ml("1 et demi")


class TestCatalogueParsing(unittest.TestCase):
    def test_parse_catalogue_extracts_name_and_carbs(self):
        products = L.parse_catalogue(CATALOGUE_MD)
        names = {p["name"]: p["carbs_g"] for p in products}
        self.assertEqual(names["Gel Fixture Test"], 32.0)
        self.assertEqual(names["Barre Fixture Energie"], 28.0)
        self.assertEqual(len(products), 4)

    def test_parse_catalogue_ignores_rows_without_carbs_number(self):
        text = "| Produit | Portion | Glucides |\n|---|---|---|\n| Mystère | ras | à préciser |\n"
        self.assertEqual(L.parse_catalogue(text), [])


class TestProductMatching(unittest.TestCase):
    def setUp(self):
        self.catalogue = L.parse_catalogue(CATALOGUE_MD)

    def test_exact_match_case_and_accent_insensitive(self):
        status, product = L.match_product("gel fixture test", self.catalogue)
        self.assertEqual(status, "matched")
        self.assertEqual(product["name"], "Gel Fixture Test")

    def test_plural_query_matches_singular_catalogue_entry(self):
        status, product = L.match_product("Gels Fixture Test", self.catalogue)
        self.assertEqual(status, "matched")
        self.assertEqual(product["name"], "Gel Fixture Test")

    def test_singular_query_matches_plural_catalogue_entry(self):
        """Singularisation des DEUX côtés (revue de code) : un catalogue saisi
        au pluriel ("Barres Fixture Plurielles") reste trouvable par une
        requête au singulier."""
        status, product = L.match_product("barre fixture plurielle", self.catalogue)
        self.assertEqual(status, "matched")
        self.assertEqual(product["name"], "Barres Fixture Plurielles")

    def test_partial_word_match_single_candidate(self):
        status, product = L.match_product("gel", self.catalogue)
        self.assertEqual(status, "matched")
        self.assertEqual(product["name"], "Gel Fixture Test")

    def test_ambiguous_partial_match_returns_all_candidates(self):
        status, candidates = L.match_product("barre", self.catalogue)
        self.assertEqual(status, "ambiguous")
        self.assertIn("Barre Fixture Energie", candidates)
        self.assertIn("Barre Fixture Recup", candidates)

    def test_unknown_product_not_in_catalogue(self):
        status, result = L.match_product("pate de fruit", self.catalogue)
        self.assertEqual(status, "unknown")
        self.assertIsNone(result)

    def test_unknown_when_catalogue_empty(self):
        status, result = L.match_product("gel", [])
        self.assertEqual(status, "unknown")
        self.assertIsNone(result)


class TestComputeNutrition(unittest.TestCase):
    def setUp(self):
        self.catalogue = L.parse_catalogue(CATALOGUE_MD)

    def test_sums_carbs_for_multiple_matched_items(self):
        items = [{"product": "gels", "qty": "2"}, {"product": "Barre Fixture Energie", "qty": 1}]
        result = L.compute_nutrition(items, self.catalogue)
        self.assertEqual(result["carbs_g"], 32.0 * 2 + 28.0)
        self.assertEqual(len(result["matched"]), 2)
        self.assertEqual(result["unknown"], [])
        self.assertEqual(result["ambiguous"], [])

    def test_confirmation_data_names_matched_product(self):
        result = L.compute_nutrition([{"product": "gels", "qty": "2"}], self.catalogue)
        self.assertEqual(result["matched"][0]["matched_product"], "Gel Fixture Test")
        self.assertEqual(result["matched"][0]["carbs_g"], 64.0)

    def test_unknown_product_never_invents_carbs(self):
        items = [{"product": "pate de fruit maison", "qty": "1"}]
        result = L.compute_nutrition(items, self.catalogue)
        self.assertIsNone(result["carbs_g"])
        self.assertEqual(len(result["unknown"]), 1)
        self.assertEqual(result["unknown"][0]["reason"], "unknown_product")

    def test_ambiguous_product_never_invents_carbs(self):
        items = [{"product": "barre", "qty": "1"}]
        result = L.compute_nutrition(items, self.catalogue)
        self.assertIsNone(result["carbs_g"])
        self.assertEqual(len(result["ambiguous"]), 1)

    def test_no_catalogue_marks_items_unknown_with_reason(self):
        result = L.compute_nutrition([{"product": "gel", "qty": "1"}], [])
        self.assertIsNone(result["carbs_g"])
        self.assertEqual(result["unknown"][0]["reason"], "no_catalogue")

    def test_unparseable_quantity_marks_item_unknown_not_fatal(self):
        result = L.compute_nutrition([{"product": "gel", "qty": "beaucoup"}], self.catalogue)
        self.assertIsNone(result["carbs_g"])
        self.assertEqual(len(result["unknown"]), 1)

    def test_athlete_declared_carbs_per_unit_for_unknown_product(self):
        """#67, revue de code : plus d'addition à la main côté agent — un
        produit inconnu dont l'athlète a donné la valeur en grammes se
        multiplie ici, jamais dans le prompt de l'agent."""
        items = [{"product": "barre maison", "qty": "2", "carbs_g_per_unit": 25}]
        result = L.compute_nutrition(items, self.catalogue)
        self.assertEqual(result["carbs_g"], 50.0)
        self.assertEqual(result["matched"][0]["source"], "athlete_declared")
        self.assertEqual(result["unknown"], [])

    def test_athlete_declared_carbs_per_unit_rejects_negative(self):
        items = [{"product": "barre maison", "qty": "1", "carbs_g_per_unit": -5}]
        result = L.compute_nutrition(items, self.catalogue)
        self.assertIsNone(result["carbs_g"])
        self.assertEqual(len(result["unknown"]), 1)

    def test_athlete_declared_carbs_per_unit_takes_precedence_over_catalogue(self):
        """Une valeur explicitement déclarée par l'athlète prime même pour un
        produit qui existerait par ailleurs dans le catalogue (l'athlète
        corrige une portion différente de celle du catalogue)."""
        items = [{"product": "gel", "qty": "1", "carbs_g_per_unit": 45}]
        result = L.compute_nutrition(items, self.catalogue)
        self.assertEqual(result["carbs_g"], 45.0)
        self.assertEqual(result["matched"][0]["matched_product"], "gel")


class TestComputeFluids(unittest.TestCase):
    def test_sums_mixed_units(self):
        result = L.compute_fluids(["500 ml", "0,5 l"])
        self.assertEqual(result["fluid_intake_ml"], 1000.0)
        self.assertEqual(result["unknown"], [])

    def test_empty_returns_none(self):
        result = L.compute_fluids([])
        self.assertIsNone(result["fluid_intake_ml"])

    def test_unrecognized_entry_goes_to_unknown_not_invented(self):
        result = L.compute_fluids(["1 bidon", "500 ml"])
        self.assertEqual(result["fluid_intake_ml"], 500.0)
        self.assertEqual(len(result["unknown"]), 1)
        self.assertEqual(result["unknown"][0]["input"], "1 bidon")

    def test_bare_number_goes_to_unknown(self):
        result = L.compute_fluids(["500"])
        self.assertIsNone(result["fluid_intake_ml"])
        self.assertEqual(len(result["unknown"]), 1)


class TestComputePain(unittest.TestCase):
    def test_flags_consult_at_or_above_threshold(self):
        result = L.compute_pain(
            [{"location": "genou gauche", "score": "7"}, {"location": "mollet", "score": "3"}],
            threshold=7.0,
        )
        self.assertTrue(result["entries"][0]["consult"])
        self.assertFalse(result["entries"][1]["consult"])
        self.assertEqual(result["unknown"], [])

    def test_out_of_range_score_goes_to_unknown_not_fatal(self):
        result = L.compute_pain([{"location": "genou", "score": "12"}], threshold=7.0)
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(result["unknown"]), 1)

    def test_unparseable_score_goes_to_unknown_not_fatal(self):
        result = L.compute_pain([{"location": "genou", "score": "forte"}], threshold=7.0)
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(result["unknown"]), 1)

    def test_negative_score_goes_to_unknown(self):
        result = L.compute_pain([{"location": "genou", "score": "-1"}], threshold=7.0)
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(result["unknown"]), 1)

    def test_out_of_ten_form_accepted_not_unknown(self):
        """"genou gauche 3/10" — revue de code : ne doit JAMAIS ressortir
        `pain.unknown`."""
        result = L.compute_pain([{"location": "genou gauche", "score": "3/10"}], threshold=7.0)
        self.assertEqual(result["unknown"], [])
        self.assertEqual(result["entries"][0]["score"], 3.0)


class TestPainConsultThresholdResolution(unittest.TestCase):
    def test_resolves_from_live_config_not_a_hardcoded_constant(self):
        """#67, revue de code : `arc_log` ne doit plus dupliquer une constante
        de seuil — il doit résoudre `[injury_risk].pain_consult_threshold`
        depuis la configuration vivante (même chemin que `arc_guardrails`)."""
        default = arc_guardrails.injury_risk_settings(arc_index.load_config(REPO))["pain_consult_threshold"]
        self.assertEqual(L.resolve_pain_consult_threshold(REPO), default)

    def test_falls_back_when_modules_unavailable(self):
        saved_index, saved_guardrails = L._arc_index, L._arc_guardrails
        try:
            L._arc_index = None
            L._arc_guardrails = None
            self.assertEqual(
                L.resolve_pain_consult_threshold(REPO), L.FALLBACK_PAIN_CONSULT_THRESHOLD
            )
        finally:
            L._arc_index, L._arc_guardrails = saved_index, saved_guardrails


class TestMergeActivity(unittest.TestCase):
    def test_sums_carbs_and_fluid_replaces_rpe(self):
        existing = {"garmin_activity_id": 1, "carbs_g": 32, "fluid_intake_ml": 250, "rpe": 6}
        merged = L.merge_activity(existing, carbs_g=64, fluid_intake_ml=500, rpe=7)
        self.assertEqual(merged["carbs_g"], 96)
        self.assertEqual(merged["fluid_intake_ml"], 750)
        self.assertEqual(merged["rpe"], 7)
        # Ne touche jamais aux clés hors de son ressort.
        self.assertNotIn("garmin_activity_id", merged)

    def test_no_existing_file_starts_from_zero(self):
        merged = L.merge_activity(None, carbs_g=64, fluid_intake_ml=500, rpe=None)
        self.assertEqual(merged["carbs_g"], 64)
        self.assertEqual(merged["fluid_intake_ml"], 500)
        self.assertNotIn("rpe", merged)


class TestMergePain(unittest.TestCase):
    def test_accumulates_never_replaces(self):
        existing = [{"location": "cheville", "score": 2}]
        new = [{"location": "genou gauche", "score": 3, "consult": False}]
        merged = L.merge_pain(existing, new)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["location"], "cheville")
        self.assertEqual(merged[1]["location"], "genou gauche")

    def test_added_entries_drop_consult_key(self):
        """#249 : `consult` n'est pas une clé du contrat `health.pain` — il reste
        dans `pain.entries`, jamais dans ce qui est recopié dans le fichier santé."""
        new = [{"location": "genou gauche", "score": 8, "consult": True}]
        merged = L.merge_pain([{"location": "cheville", "score": 2}], new)
        self.assertEqual(merged[1], {"location": "genou gauche", "score": 8})
        self.assertTrue(new[0]["consult"])  # l'entrée d'origine n'est pas mutée


class TestIdempotency(unittest.TestCase):
    def test_duplicate_raw_text_detected_case_and_space_insensitive(self):
        self.assertTrue(L.check_duplicate("2 Gels  + 500 ml", ["2 gels + 500 ml"]))

    def test_distinct_raw_text_not_duplicate(self):
        self.assertFalse(L.check_duplicate("2 gels", ["3 gels"]))

    def test_no_raw_text_never_duplicate(self):
        self.assertFalse(L.check_duplicate(None, ["2 gels"]))

    def test_provenance_line_contains_raw_text_and_timestamp(self):
        line = L.provenance_line("2 gels", timestamp="2026-09-24T18:00:00+02:00")
        self.assertIn("2 gels", line)
        self.assertIn("2026-09-24T18:00:00+02:00", line)

    def test_duplicate_detected_against_a_real_provenance_line(self):
        """BLOCKER (revue de code) : `existing_log_entries` vient de relire des
        lignes déjà écrites par `provenance_line()` sous le bloc — donc PRÉFIXÉES
        `[/log <horodatage>] `. Sans retirer ce préfixe, la comparaison à
        `raw_text` (jamais préfixé) ne matche jamais, et la même déclaration se
        recompte deux fois (64 g devient 128 g)."""
        raw_text = "2 gels + 500 ml au km 15, genou gauche 3/10, RPE 7"
        written_line = L.provenance_line(raw_text, timestamp="2026-09-24T18:00:00+02:00")
        self.assertTrue(L.check_duplicate(raw_text, [written_line]))


class TestProcessEndToEnd(unittest.TestCase):
    def test_full_payload(self):
        payload = {
            "catalogue_paths": [],
            "nutrition_items": [{"product": "gel", "qty": "2"}],
            "fluid_entries": ["500 ml"],
            "pain": [{"location": "genou gauche", "score": "3"}],
            "rpe": "7",
            "position": "km 15",
        }
        # Catalogue vide explicite (liste []) → produit inconnu, jamais deviné.
        result = L.process(payload)
        self.assertEqual(result["nutrition"]["unknown"][0]["reason"], "no_catalogue")
        self.assertEqual(result["fluids"]["fluid_intake_ml"], 500.0)
        self.assertEqual(result["pain"]["entries"][0]["consult"], False)
        self.assertEqual(result["rpe"], 7.0)
        self.assertEqual(result["position"], "km 15")

    def test_rpe_out_of_range_is_never_written_only_flagged(self):
        result = L.process({"rpe": "12"})
        self.assertNotIn("rpe", result)
        self.assertIn("rpe_unknown", result)
        self.assertTrue(any("rpe" in w for w in result["warnings"]))

    def test_rpe_out_of_ten_form_accepted(self):
        """"RPE 7/10" — revue de code : ne doit JAMAIS ressortir `rpe_unknown`."""
        result = L.process({"rpe": "7/10"})
        self.assertEqual(result["rpe"], 7.0)
        self.assertNotIn("rpe_unknown", result)

    def test_many_pain_entries_warns_like_contract(self):
        pain = [{"location": f"zone {i}", "score": "2"} for i in range(11)]
        result = L.process({"pain": pain})
        self.assertTrue(any("pain" in w for w in result["warnings"]))

    def test_no_activity_merge_when_nothing_was_computed(self):
        """Produit inconnu (catalogue vide explicite) → pas de `carbs_g`
        calculé → pas de clé `activity_merge` à fusionner, même si l'état
        existant est fourni."""
        payload = {
            "catalogue_paths": [],
            "nutrition_items": [{"product": "gel", "qty": "2"}],
            "existing_activity_arc": {"carbs_g": 10},
        }
        result = L.process(payload)
        self.assertNotIn("activity_merge", result)

    def test_activity_merge_present_when_existing_arc_given(self):
        payload = {
            "fluid_entries": ["500 ml"],
            "existing_activity_arc": {"fluid_intake_ml": 250},
        }
        result = L.process(payload)
        self.assertEqual(result["activity_merge"]["fluid_intake_ml"], 750.0)

    def test_pain_merge_present_when_existing_pain_given(self):
        payload = {
            "pain": [{"location": "genou gauche", "score": "3"}],
            "existing_pain": [{"location": "cheville", "score": 2}],
        }
        result = L.process(payload)
        self.assertEqual(len(result["pain_merge"]), 2)
        self.assertIn("consult", result["pain"]["entries"][0])
        self.assertNotIn("consult", result["pain_merge"][1])

    def test_pain_merge_validates_against_health_contract(self):
        """#249 : `pain_merge` recopié tel quel dans le bloc santé ne doit lever
        aucun avertissement de clé inconnue."""
        import arc_contract
        result = L.process({"pain": [{"location": "hanche", "score": "0/10"}], "existing_pain": []})
        arc = {"arc": 1, "kind": "health", "date": "2026-10-12", "morning_check": "full",
               "pain": result["pain_merge"]}
        errors, warnings = arc_contract.validate(arc)
        self.assertEqual((errors, warnings), ([], []))

    def test_duplicate_raw_text_skips_merge(self):
        payload = {
            "fluid_entries": ["500 ml"],
            "existing_activity_arc": {"fluid_intake_ml": 250},
            "raw_text": "500 ml au km 10",
            "existing_log_entries": ["500 ml au km 10"],
        }
        result = L.process(payload)
        self.assertTrue(result["duplicate"])
        self.assertNotIn("activity_merge", result)


if __name__ == "__main__":
    unittest.main()
