"""Palier D — retours de chaussant et bilan de retraite d'une paire (#299, épopée #297) : contrat
`activity.shoe_feedback` (bornes, énumérations fermées, `gear_id` obligatoire), `shoe_spec.verdict`,
phrases françaises types de `scripts/arc_log.py` -> JSON attendu, indexation SQLite et commande
`arc_index.py shoe-feedback`.

Fixtures SYNTHÉTIQUES, workspaces temporaires passés en `--workspace`, base en mémoire : jamais le
workspace réel.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_index as I  # noqa: E402
import arc_log as L  # noqa: E402
import arc_shoes as SH  # noqa: E402

GEARS = [{"gear_id": "kipride-max-1", "name": "Kiprun Kipride Max"},
         {"gear_id": "ultra-glide-3", "name": "Salomon Ultra Glide 3"},
         {"gear_id": "ultra-glide-4", "name": "Salomon Ultra Glide 4"}]
RT = "https://www.rtings.com/running-shoes/reviews/kiprun/kipride-max"


def kind_of(term):
    """Premier problème retenu pour un terme (None = aucun)."""
    kinds = L._classify_shoe_term(term)["kinds"]
    return kinds[0]["kind"] if kinds else None


def activity(**extra) -> dict:
    base = {"arc": 1, "kind": "activity", "date": "2026-10-20", "sport": "running", "duration_s": 3600,
            "distance_m": 10000, "gear_id": "kipride-max-1"}
    base.update(extra)
    return base


def spec(**extra) -> dict:
    base = {"arc": 1, "kind": "shoe_spec", "date": "2026-10-12", "gear_id": "kipride-max-1",
            "brand": "Kiprun", "model": "Kipride Max",
            "drop_mm": {"value": 8.7, "source_type": "measured", "url": RT, "retrieved": "2026-10-12"}}
    base.update(extra)
    return base


def block_file(data: dict) -> str:
    return f"# Fichier\n\n```arc\n{json.dumps(data, ensure_ascii=False)}\n```\n\nTexte.\n"


class TestFeedbackContract(unittest.TestCase):
    def test_valid_feedback(self):
        fb = {"comfort": 6, "issues": [{"kind": "blister", "zone": "forefoot_central", "side": "left"},
                                       {"kind": "toe_box_tight"}], "notes": "avant-pied serré après 1 h"}
        self.assertEqual(C.validate(activity(shoe_feedback=fb)), ([], []))

    def test_comfort_bounds(self):
        for bad in (-1, 10.5, "6", True):
            errors, _ = C.validate(activity(shoe_feedback={"comfort": bad}))
            self.assertTrue(any("shoe_feedback.comfort" in e for e in errors), (bad, errors))
        for good in (0, 10, 7.5):
            self.assertEqual(C.validate(activity(shoe_feedback={"comfort": good})), ([], []))

    def test_closed_issue_kinds(self):
        for kind in C.SHOE_ISSUE_KIND:
            self.assertEqual(C.validate(activity(shoe_feedback={"issues": [{"kind": kind}]})), ([], []), kind)
        errors, _ = C.validate(activity(shoe_feedback={"issues": [{"kind": "smelly"}]}))
        self.assertTrue(any("issues[0].kind" in e for e in errors), errors)

    def test_zone_and_side_reuse_the_gear_inspection_enums(self):
        self.assertEqual(C.SHOE_ISSUE_KIND[0], "blister")
        errors, _ = C.validate(activity(shoe_feedback={"issues": [{"kind": "blister", "zone": "ankle"}]}))
        self.assertTrue(any("zone" in e for e in errors), errors)
        errors, _ = C.validate(activity(shoe_feedback={"issues": [{"kind": "blister", "side": "both"}]}))
        self.assertTrue(any("side" in e for e in errors), errors)
        for zone in C.GEAR_WEAR_ZONE:
            self.assertEqual(C.validate(activity(shoe_feedback={"issues": [{"kind": "hot_spot", "zone": zone}]})),
                             ([], []), zone)

    def test_requires_gear_id(self):
        data = activity(shoe_feedback={"comfort": 6})
        del data["gear_id"]
        errors, _ = C.validate(data)
        self.assertTrue(any("exige un gear_id" in e for e in errors), errors)

    def test_garmin_unmapped_run_cannot_carry_feedback(self):
        data = activity(shoe_feedback={"comfort": 6}, gear_source="garmin_unmapped")
        errors, _ = C.validate(data)
        self.assertTrue(errors)

    def test_empty_feedback_is_rejected(self):
        errors, _ = C.validate(activity(shoe_feedback={}))
        self.assertTrue(any("au moins" in e for e in errors), errors)
        errors, _ = C.validate(activity(shoe_feedback={"issues": []}))
        self.assertTrue(any("au moins" in e for e in errors), errors)

    def test_duplicate_issue_warns(self):
        _, warnings = C.validate(activity(shoe_feedback={"issues": [{"kind": "blister"}, {"kind": "blister"}]}))
        self.assertTrue(any("double" in w for w in warnings), warnings)

    def test_old_activity_without_feedback_is_unchanged(self):
        self.assertEqual(C.validate(activity()), ([], []))

    def test_pain_stays_separate(self):
        """Une clé `pain` n'appartient pas à `shoe_feedback` : clé hors contrat signalée (jamais un second
        canal de douleur silencieux)."""
        _, warnings = C.validate(activity(shoe_feedback={"issues": [{"kind": "blister", "pain": 7}]}))
        self.assertTrue(any("pain" in w for w in warnings), warnings)


class TestVerdictContract(unittest.TestCase):
    def verdict(self, **extra) -> dict:
        v = {"date": "2026-10-20", "comfort_overall": 8, "would_rebuy": "yes"}
        v.update(extra)
        return v

    def test_valid_verdicts(self):
        self.assertEqual(C.validate(spec(verdict=self.verdict())), ([], []))
        v = self.verdict(would_rebuy="yes_with_change", change_wanted=["wider_toe_box", "more_grip"],
                         notes="plus large devant", distance_m=812000)
        self.assertEqual(C.validate(spec(verdict=v)), ([], []))
        self.assertEqual(C.validate(spec(verdict=self.verdict(would_rebuy="no", comfort_overall=3))), ([], []))

    def test_enums_and_bounds(self):
        for bad in (self.verdict(would_rebuy="maybe"), self.verdict(comfort_overall=11),
                    self.verdict(comfort_overall=-0.5), self.verdict(change_wanted=["bigger"])):
            errors, _ = C.validate(spec(verdict=bad))
            self.assertTrue(errors, bad)
        for value in C.SHOE_CHANGE_WANTED:
            data = spec(verdict=self.verdict(would_rebuy="yes_with_change", change_wanted=[value]))
            self.assertEqual(C.validate(data), ([], []), value)

    def test_required_keys(self):
        for key in ("date", "comfort_overall", "would_rebuy"):
            v = self.verdict()
            del v[key]
            errors, _ = C.validate(spec(verdict=v))
            self.assertTrue(any(key in e for e in errors), (key, errors))

    def test_yes_with_change_needs_a_change(self):
        errors, _ = C.validate(spec(verdict=self.verdict(would_rebuy="yes_with_change")))
        self.assertTrue(any("change_wanted" in e for e in errors), errors)

    def test_yes_with_change_wanted_warns(self):
        _, warnings = C.validate(spec(verdict=self.verdict(change_wanted=["firmer"])))
        self.assertTrue(any("yes_with_change" in w for w in warnings), warnings)


class TestLogFrenchSentences(unittest.TestCase):
    """Phrases types -> JSON attendu. Le modèle fournit les termes ; le script fait le reste."""

    def run_log(self, shoe, **extra):
        payload = {"declared_gear": GEARS, "existing_activity_arc": {"duration_s": 3600}, **extra}
        payload["shoe_feedback"] = shoe
        return L.process(payload, workspace=None)

    def test_issue_term_mapping(self):
        cases = {"ampoule": "blister", "avant-pied serré": "toe_box_tight", "talon qui bouge": "heel_slip",
                 "point chaud": "hot_spot", "pied qui s'endort": "numbness", "laçage trop serré": "lacing_pressure",
                 "instable": "instability", "trop mou": "too_soft", "trop dur": "too_firm",
                 "manque d'adhérence": "poor_grip", "tige déchirée": "upper_tear", "blister": "blister"}
        for term, kind in cases.items():
            out = self.run_log({"pair": "Kipride", "issues": [{"term": term}]})
            self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": kind}], term)

    def test_every_closed_kind_is_reachable_from_french(self):
        reachable = {kind_of(p) for phrases in L._SHOE_ISSUE_TERMS.values() for p in phrases}
        self.assertEqual(reachable, set(C.SHOE_ISSUE_KIND))

    def test_every_table_phrase_maps_to_its_own_kind(self):
        for kind, phrases in L._SHOE_ISSUE_TERMS.items():
            for phrase in phrases:
                self.assertEqual(kind_of(phrase), kind, phrase)

    def test_plurals_agreement_articles_and_intensifiers(self):
        cases = {"ampoules": "blister", "des cloques": "blister", "frottements": "hot_spot",
                 "trop dures": "too_firm", "mousse trop dure": "too_firm", "orteils très serrés": "toe_box_tight",
                 "avant-pied trop serré": "toe_box_tight", "un peu instable": "instability",
                 "les lacets trop serrés": "lacing_pressure", "orteils à l'étroit": "toe_box_tight",
                 "tige abîmée": "upper_tear", "trop molle": "too_soft"}
        for term, kind in cases.items():
            self.assertEqual(kind_of(term), kind, term)

    def test_negations_are_never_logged(self):
        for term in ("pas d'ampoule", "aucune ampoule", "sans ampoule", "plus d'ampoule", "pas instable",
                     "pas trop dur", "pas de frottement", "jamais de point chaud", "pas de souci",
                     "pas de problème", "rien", "ni ampoule ni frottement"):
            out = self.run_log({"pair": "Kipride", "issues": [{"term": term}], "notes": ""})
            shoe = out["shoe_feedback"]
            self.assertEqual(shoe["entry"].get("issues"), None, term)
            self.assertEqual(shoe["unknown"], [], term)
            self.assertEqual(shoe["negated"], [term], term)
            self.assertNotIn("shoe_feedback", out.get("activity_merge", {}), term)

    def test_negation_in_one_clause_does_not_hide_a_real_issue(self):
        self.assertEqual(kind_of("pas de souci au talon, mais une ampoule"), "blister")

    def test_pas_mal_de_means_a_lot_not_a_negation(self):
        self.assertEqual(kind_of("pas mal d'ampoules"), "blister")
        self.assertEqual(kind_of("pas mal de frottements"), "hot_spot")
        self.assertFalse(L._classify_shoe_term("pas mal d'ampoules")["negated"])

    def test_exception_words_split_clauses(self):
        for term in ("pas de souci sauf une ampoule", "rien à signaler hormis une ampoule",
                     "pas de problème à part une ampoule", "RAS excepté une ampoule"):
            self.assertEqual(kind_of(term), "blister", term)

    def test_short_negated_phrases_without_a_problem_are_questions_not_no_problem(self):
        for term in ("pas top", "pas terrible", "pas confortable", "non", "jamais eu d'ampoule avant, là oui",
                     "plus d'ampoules qu'avant", "plus de frottements que d'habitude"):
            cls = L._classify_shoe_term(term)
            self.assertEqual(cls["kinds"], [], term)
            out = self.run_log({"pair": "Kipride", "comfort": "5", "issues": [{"term": term}]})
            shoe = out["shoe_feedback"]
            self.assertFalse(shoe["ready"], term)
            self.assertTrue(shoe["unknown"], term)
            self.assertNotIn("negated", shoe, term)

    def test_explicit_no_issue_words(self):
        for term in ("RAS", "rien à signaler", "pas de gêne", "aucun souci", "pas de problème"):
            cls = L._classify_shoe_term(term)
            self.assertTrue(cls["negated"] and not cls["kinds"] and not cls["unclear"], term)

    def test_lack_of_grip_is_poor_grip(self):
        for term in ("pas assez de grip", "manque de grip", "grip insuffisant"):
            self.assertEqual(kind_of(term), "poor_grip", term)

    def test_every_problem_of_a_multi_problem_term_is_kept(self):
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule et frottement"}]})
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": "blister"}, {"kind": "hot_spot"}])
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule, orteils serrés"}]})
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": "blister"}, {"kind": "toe_box_tight"}])
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule, pas de frottement, orteils serrés"}]})
        self.assertEqual([i["kind"] for i in out["shoe_feedback"]["entry"]["issues"]], ["blister", "toe_box_tight"])

    def test_side_and_zone_in_another_clause(self):
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "talon qui glisse, côté gauche"}]})
        self.assertTrue(out["shoe_feedback"]["ready"])
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": "heel_slip", "side": "left"}])
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule, côté droit, au talon"}]})
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"],
                         [{"kind": "blister", "zone": "heel_central", "side": "right"}])

    def issues_of(self, term):
        out = self.run_log({"pair": "Kipride", "issues": [{"term": term}]})
        return out["shoe_feedback"]["entry"].get("issues")

    def test_zone_and_side_stay_with_their_own_problem(self):
        self.assertEqual(self.issues_of("orteils serrés, ampoule au talon"),
                         [{"kind": "toe_box_tight"}, {"kind": "blister", "zone": "heel_central"}])
        self.assertEqual(self.issues_of("ampoule talon gauche, orteils serrés"),
                         [{"kind": "blister", "zone": "heel_central", "side": "left"}, {"kind": "toe_box_tight"}])
        self.assertEqual(self.issues_of("ampoule au talon, frottement"),
                         [{"kind": "blister", "zone": "heel_central"}, {"kind": "hot_spot"}])

    def test_pure_locator_clause_goes_to_the_preceding_problem_only(self):
        self.assertEqual(self.issues_of("talon qui glisse, côté gauche"), [{"kind": "heel_slip", "side": "left"}])
        self.assertEqual(self.issues_of("ampoule, côté droit, frottement"),
                         [{"kind": "blister", "side": "right"}, {"kind": "hot_spot"}])
        self.assertEqual(self.issues_of("côté gauche, ampoule"), [{"kind": "blister", "side": "left"}])

    def test_negation_after_the_problem_is_a_question(self):
        for term in ("ampoule non", "ampoules ? aucune", "ampoule ? pas cette fois", "ampoule : rien"):
            cls = L._classify_shoe_term(term)
            self.assertEqual(cls["kinds"], [], term)
            self.assertTrue(cls["unclear"], term)
            out = self.run_log({"pair": "Kipride", "comfort": "5", "issues": [{"term": term}]})
            self.assertFalse(out["shoe_feedback"]["ready"], term)
            self.assertNotIn("shoe_feedback", out.get("activity_merge", {}), term)

    def test_named_unknown_or_ambiguous_pair_on_a_run_that_has_one_is_a_question(self):
        gears = GEARS + [{"gear_id": "pegasus", "name": "Nike Pegasus"},
                         {"gear_id": "pegasus-41", "name": "Nike Pegasus 41"}]
        base = {"declared_gear": gears, "existing_activity_arc": {"gear_id": "kipride-max-1"}}
        out = L.process({**base, "shoe_feedback": {"pair": "Pegasus", "comfort": "6"}})
        self.assertEqual(out["shoe_feedback"]["needs_gear"]["reason"], "ambiguous_pair")
        self.assertFalse(out["shoe_feedback"]["ready"])
        out = L.process({**base, "shoe_feedback": {"pair": "Speedgoat", "comfort": "6"}})
        self.assertEqual(out["shoe_feedback"]["needs_gear"]["reason"], "unknown_pair")
        out = L.process({**base, "shoe_feedback": {"pair": "Kipride", "comfort": "6"}})
        self.assertTrue(out["shoe_feedback"]["ready"])

    def test_comfort_with_a_negated_issue_is_still_written(self):
        out = self.run_log({"pair": "Kipride", "comfort": "8", "issues": [{"term": "pas d'ampoule"}]})
        self.assertTrue(out["shoe_feedback"]["ready"])
        self.assertEqual(out["activity_merge"]["shoe_feedback"], {"comfort": 8.0})

    def test_zone_and_side_inside_the_term(self):
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "Ampoule au talon gauche"}]})
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"],
                         [{"kind": "blister", "zone": "heel_central", "side": "left"}])
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "talon qui bouge"}]})
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": "heel_slip"}])
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule au talon", "zone": "avant-pied"}]})
        self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": "blister", "zone": "forefoot_central"}])

    def test_pair_with_article_and_plural(self):
        for said in ("mes Kipride", "les kipride max", "Kipride"):
            self.assertEqual(L.resolve_pair(said, GEARS), {"gear_id": "kipride-max-1"}, said)

    def test_exact_name_does_not_hide_an_ambiguity(self):
        gears = [{"gear_id": "pegasus", "name": "Nike Pegasus"}, {"gear_id": "pegasus-41", "name": "Nike Pegasus 41"},
                 {"gear_id": "speedgoat", "name": "Hoka Speedgoat 5"},
                 {"gear_id": "speedgoat6", "name": "Hoka Speedgoat 6"}]
        for said in ("Pegasus", "Speedgoat", "nike pegasus"):
            res = L.resolve_pair(said, gears)
            self.assertEqual(res["reason"], "ambiguous_pair", said)
        self.assertEqual(L.resolve_pair("pegasus 41", gears), {"gear_id": "pegasus-41"})
        self.assertEqual(L.resolve_pair("speedgoat 6", gears), {"gear_id": "speedgoat6"})

    def test_notes_survive_repeated_logs(self):
        arc = {"gear_id": "kipride-max-1"}
        for note, expected in (("A", "A"), ("B", "A ; B"), ("A", "A ; B"), ("C", "A ; B ; C"),
                               ("A ; B ; C", "A ; B ; C")):
            out = L.process({"declared_gear": GEARS, "existing_activity_arc": dict(arc),
                             "shoe_feedback": {"notes": note}})
            merged = out["activity_merge"]["shoe_feedback"]
            self.assertEqual(merged["notes"], expected, note)
            arc["shoe_feedback"] = merged

    def test_confirmed_pair_overrides_the_run_gear(self):
        payload = {"declared_gear": GEARS, "existing_activity_arc": {"gear_id": "ultra-glide-3", "gear_source": "garmin"},
                   "shoe_feedback": {"pair": "Kipride", "comfort": "7"}}
        self.assertEqual(L.process(payload)["shoe_feedback"]["needs_gear"]["reason"], "conflict")
        payload["shoe_feedback"]["pair_confirmed"] = True
        out = L.process(payload)
        self.assertTrue(out["shoe_feedback"]["ready"])
        merge = out["activity_merge"]
        self.assertEqual((merge["gear_id"], merge["gear_source"]), ("kipride-max-1", "chat"))
        data = activity(**merge)
        self.assertEqual(C.validate(data), ([], []))

    def test_confirmed_flag_without_a_named_pair_changes_nothing(self):
        out = L.process({"declared_gear": GEARS, "existing_activity_arc": {"gear_id": "ultra-glide-3"},
                         "shoe_feedback": {"comfort": "7", "pair_confirmed": True}})
        self.assertEqual(out["shoe_feedback"]["gear_id"], "ultra-glide-3")
        self.assertNotIn("gear_id", out["activity_merge"])

    def test_new_activity_file_still_gets_an_activity_merge(self):
        out = L.process({"declared_gear": GEARS, "shoe_feedback": {"pair": "Kipride", "comfort": "6"}})
        self.assertEqual(out["activity_merge"]["gear_id"], "kipride-max-1")
        self.assertEqual(out["activity_merge"]["shoe_feedback"], {"comfort": 6.0})

    def test_kipride_sentence(self):
        """« Kipride : ampoule sous le talon gauche, avant-pied serré, confort 6 »."""
        out = self.run_log({"pair": "Kipride", "comfort": "6", "issues": [
            {"term": "ampoule", "zone": "talon", "side": "gauche"}, {"term": "avant-pied serré"}]},
            raw_text="Kipride : ampoule sous le talon gauche, avant-pied serré, confort 6")
        shoe = out["shoe_feedback"]
        self.assertTrue(shoe["ready"])
        self.assertEqual(shoe["gear_id"], "kipride-max-1")
        self.assertEqual(shoe["entry"], {"comfort": 6.0, "issues": [
            {"kind": "blister", "zone": "heel_central", "side": "left"}, {"kind": "toe_box_tight"}]})
        merge = out["activity_merge"]
        self.assertEqual((merge["gear_id"], merge["gear_source"]), ("kipride-max-1", "chat"))
        data = activity(**{k: v for k, v in merge.items()})
        self.assertEqual(C.validate(data), ([], []))

    def test_confort_on_ten_notation(self):
        out = self.run_log({"pair": "ultra glide 3", "comfort": "7/10"})
        self.assertEqual(out["shoe_feedback"]["entry"], {"comfort": 7.0})
        self.assertEqual(out["shoe_feedback"]["gear_id"], "ultra-glide-3")

    def test_zone_variants(self):
        cases = {"talon externe": "heel_lateral", "talon": "heel_central", "médio-pied": "midfoot_central",
                 "avant-pied interne": "forefoot_medial", "avant pied": "forefoot_central",
                 "gros orteil": "toe", "midfoot_lateral": "midfoot_lateral"}
        for text, zone in cases.items():
            out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule", "zone": text}]})
            self.assertEqual(out["shoe_feedback"]["entry"]["issues"], [{"kind": "blister", "zone": zone}], text)

    def test_vague_zone_is_a_question(self):
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule", "zone": "sous le pied"}]})
        shoe = out["shoe_feedback"]
        self.assertFalse(shoe["ready"])
        self.assertEqual(shoe["unknown"][0]["field"], "zone")
        self.assertNotIn("shoe_feedback", out.get("activity_merge", {}))

    def test_unknown_term_is_a_question_and_blocks_only_the_shoe_part(self):
        out = self.run_log({"pair": "Kipride", "comfort": "5", "issues": [{"term": "ça pue"}]},
                           rpe="6", pain=[{"location": "genou", "score": "2"}])
        shoe = out["shoe_feedback"]
        self.assertFalse(shoe["ready"])
        self.assertEqual(shoe["unknown"][0]["input"], "ça pue")
        self.assertEqual(out["activity_merge"], {"rpe": 6.0})     # le reste du /log passe
        self.assertEqual(out["pain"]["entries"][0]["location"], "genou")

    def test_run_without_pair_asks_which_pair(self):
        out = self.run_log({"comfort": "6", "issues": [{"term": "ampoule"}]})
        shoe = out["shoe_feedback"]
        self.assertFalse(shoe["ready"])
        self.assertEqual(shoe["needs_gear"]["reason"], "no_gear")
        self.assertEqual(set(shoe["needs_gear"]["candidates"]), {g["gear_id"] for g in GEARS})
        self.assertNotIn("activity_merge", out)

    def test_unknown_and_ambiguous_pair(self):
        out = self.run_log({"pair": "Speedgoat", "comfort": "6"})
        self.assertEqual(out["shoe_feedback"]["needs_gear"]["reason"], "unknown_pair")
        out = self.run_log({"pair": "Ultra Glide", "comfort": "6"})
        needs = out["shoe_feedback"]["needs_gear"]
        self.assertEqual(needs["reason"], "ambiguous_pair")
        self.assertEqual(set(needs["candidates"]), {"ultra-glide-3", "ultra-glide-4"})

    def test_run_gear_id_wins_and_a_different_pair_is_a_conflict(self):
        payload = {"declared_gear": GEARS, "existing_activity_arc": {"gear_id": "ultra-glide-3"},
                   "shoe_feedback": {"comfort": "8"}}
        out = L.process(payload)
        self.assertTrue(out["shoe_feedback"]["ready"])
        self.assertEqual(out["shoe_feedback"]["gear_origin"], "run")
        self.assertNotIn("gear_id", out["activity_merge"])            # déjà sur la séance : pas réécrit
        payload["shoe_feedback"]["pair"] = "Kipride"
        out = L.process(payload)
        self.assertEqual(out["shoe_feedback"]["needs_gear"]["reason"], "conflict")
        self.assertFalse(out["shoe_feedback"]["ready"])

    def test_out_of_range_comfort_is_a_question(self):
        out = self.run_log({"pair": "Kipride", "comfort": "12"})
        self.assertEqual(out["shoe_feedback"]["unknown"][0]["field"], "comfort")
        self.assertFalse(out["shoe_feedback"]["ready"])

    def test_pain_and_shoe_issue_write_both_and_keep_the_consult(self):
        """« douleur 7/10 pied gauche + ampoule » : `pain` ET `shoe_feedback`, consultation recommandée."""
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule", "side": "gauche"}]},
                           pain=[{"location": "pied gauche", "score": "7"}], existing_pain=[])
        self.assertTrue(out["shoe_feedback"]["ready"])
        self.assertTrue(out["pain"]["entries"][0]["consult"])
        self.assertEqual(out["pain_merge"], [{"location": "pied gauche", "score": 7.0}])
        self.assertIn("shoe_feedback", out["activity_merge"])
        self.assertNotIn("pain", out["activity_merge"])
        self.assertNotIn("pain", json.dumps(out["activity_merge"]))

    def test_consult_threshold_is_still_the_configured_one(self):
        out = self.run_log({"pair": "Kipride", "issues": [{"term": "ampoule"}]},
                           pain=[{"location": "pied", "score": "5"}], pain_consult_threshold=5)
        self.assertTrue(out["pain"]["entries"][0]["consult"])

    def test_merge_with_existing_feedback(self):
        existing = {"gear_id": "kipride-max-1",
                    "shoe_feedback": {"comfort": 5, "issues": [{"kind": "blister"}], "notes": "début"}}
        out = L.process({"declared_gear": GEARS, "existing_activity_arc": existing,
                         "shoe_feedback": {"comfort": "7", "issues": [{"term": "ampoule"}, {"term": "trop dur"}],
                                           "notes": "fin"}})
        merged = out["activity_merge"]["shoe_feedback"]
        self.assertEqual(merged["comfort"], 7.0)
        self.assertEqual(merged["issues"], [{"kind": "blister"}, {"kind": "too_firm"}])
        self.assertEqual(merged["notes"], "début ; fin")

    def test_duplicate_sentence_does_not_merge_twice(self):
        out = L.process({"declared_gear": GEARS, "existing_activity_arc": {"gear_id": "kipride-max-1"},
                         "shoe_feedback": {"comfort": "6"}, "raw_text": "Kipride confort 6",
                         "existing_log_entries": ["[/log 2026-10-20T10:00:00+02:00] Kipride confort 6"]})
        self.assertTrue(out["duplicate"])
        self.assertNotIn("activity_merge", out)

    def test_empty_feedback_warns(self):
        out = self.run_log({"pair": "Kipride"})
        self.assertTrue(any("rien à écrire" in w for w in out["warnings"]))
        self.assertFalse(out["shoe_feedback"]["ready"])

    def test_gear_resolved_from_workspace_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "planning").mkdir()
            (ws / "planning" / "Runner_Profile.md").write_text(
                "# Profil\n\n### Chaussures\n\n- Kiprun Kipride Max — usage: route — id: kipride-max-1\n",
                encoding="utf-8")
            out = L.process({"existing_activity_arc": {"duration_s": 60},
                             "shoe_feedback": {"pair": "kipride", "comfort": "6"}}, workspace=ws)
        self.assertEqual(out["shoe_feedback"]["gear_id"], "kipride-max-1")

    def test_input_without_shoe_feedback_is_unchanged(self):
        out = L.process({"rpe": "7", "existing_activity_arc": {}})
        self.assertNotIn("shoe_feedback", out)
        self.assertEqual(out["activity_merge"], {"rpe": 7.0})


class TestIndexAndCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.write("planning/Runner_Profile.md",
                   "# Profil\n\n### Chaussures\n\n- Kiprun Kipride Max — usage: route — id: kipride-max-1\n"
                   "- Salomon Ultra Glide 3 — usage: trail — id: ultra-glide-3\n")
        self.write("activities/2026-10-18_running.md", block_file(activity(
            date="2026-10-18", shoe_feedback={"comfort": 8})))
        self.write("activities/2026-10-20_running.md", block_file(activity(
            shoe_feedback={"comfort": 5, "issues": [{"kind": "blister", "zone": "heel_lateral", "side": "left"},
                                                     {"kind": "toe_box_tight"}], "notes": "serré"})))
        self.write("activities/2026-10-22_running.md", block_file(activity(
            date="2026-10-22", gear_id="ultra-glide-3", shoe_feedback={"issues": [{"kind": "poor_grip"}]})))
        self.write("activities/2026-10-23_running.md", block_file(activity(date="2026-10-23")))
        self.write("gear/specs/kipride-max-1.md", block_file(spec(verdict={
            "date": "2026-10-21", "comfort_overall": 6, "would_rebuy": "yes_with_change",
            "change_wanted": ["wider_toe_box"], "notes": "trop serré devant"})))

    def write(self, rel: str, text: str) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cli(self, *extra) -> tuple:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", "2026-10-23",
                           "shoe-feedback", *extra])
        return code, buf.getvalue()

    def test_schema_version_and_table(self):
        self.assertGreaterEqual(I.SCHEMA_VERSION, 40, "nouvelle table shoe_feedback : SCHEMA_VERSION à relever")
        conn = I.open_db(self.ws, memory=True)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(shoe_feedback)")}
        self.assertEqual(columns, {"source_path", "date", "gear_id", "comfort", "issues", "notes"})

    def test_json_report_aggregates_per_pair(self):
        code, out = self.cli()
        self.assertEqual(code, 0)
        report = json.loads(out)
        pairs = {p["gear_id"]: p for p in report["pairs"]}
        kip = pairs["kipride-max-1"]
        self.assertEqual(kip["runs_with_feedback"], 2)
        self.assertEqual(kip["runs_with_issues"], 1)
        self.assertEqual(kip["comfort"], {"mean": 6.5, "min": 5, "max": 8, "last": 5, "n": 2})
        self.assertEqual(kip["issue_counts"], {"blister": 1, "toe_box_tight": 1})   # en séances
        self.assertEqual(kip["zone_counts"], {"heel_lateral": 1})
        self.assertEqual(kip["verdict"]["would_rebuy"], "yes_with_change")
        self.assertEqual(kip["name"], "Kiprun Kipride Max")
        ug = pairs["ultra-glide-3"]
        self.assertIsNone(ug["comfort"])
        self.assertEqual(ug["issue_counts"], {"poor_grip": 1})
        self.assertIn("pas causalité", report["note"])

    def test_issue_counts_are_runs_not_occurrences(self):
        rep = SH.feedback_report([
            {"gear_id": "a", "date": "2026-10-01", "source_path": "x", "comfort": 5,
             "issues": [{"kind": "blister", "side": "left"}, {"kind": "blister", "side": "right"}]},
            {"gear_id": "a", "date": "2026-10-02", "source_path": "y", "comfort": 6,
             "issues": [{"kind": "blister"}]}], [])
        self.assertEqual(rep["pairs"][0]["issue_counts"], {"blister": 2})

    def test_run_without_feedback_is_not_counted(self):
        _, out = self.cli("--gear", "kipride-max-1")
        report = json.loads(out)
        dates = [r["date"] for r in report["pairs"][0]["recent"]]
        self.assertEqual(dates, ["2026-10-18", "2026-10-20"])

    def test_gear_filter_and_unknown_pair(self):
        code, out = self.cli("--gear", "ultra-glide-3")
        self.assertEqual([p["gear_id"] for p in json.loads(out)["pairs"]], ["ultra-glide-3"])
        code, out = self.cli("--gear", "inconnue")
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))

    def test_declared_pair_without_feedback_is_info_not_error(self):
        rep = SH.feedback_report([], [], [{"gear_id": "x", "name": "X"}], "x")
        self.assertEqual(rep["count"], 0)
        self.assertNotIn("error", rep)
        self.assertIn("info", rep)

    def test_text_output(self):
        code, out = self.cli("--text")
        self.assertEqual(code, 0)
        self.assertIn("kipride-max-1", out)
        self.assertIn("blister ×1", out)
        self.assertIn("rachat : yes_with_change", out)

    def test_verdict_only_pair_is_listed(self):
        rep = SH.feedback_report([], [{"source_path": "gear/specs/a.md",
                                       "data": spec(gear_id="a", verdict={"date": "2026-10-21", "comfort_overall": 9,
                                                                         "would_rebuy": "yes"})}])
        self.assertEqual(rep["pairs"][0]["runs_with_feedback"], 0)
        self.assertEqual(rep["pairs"][0]["verdict"]["comfort_overall"], 9)

    def test_read_only(self):
        before = sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*") if p.is_file())
        self.cli()
        after = sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*") if p.is_file())
        self.assertEqual(before, after)

    def test_invalid_feedback_is_not_indexed(self):
        data = activity(date="2026-10-24")
        del data["gear_id"]
        data["shoe_feedback"] = {"comfort": 4}
        self.write("activities/2026-10-24_running.md", block_file(data))
        _, out = self.cli()
        self.assertNotIn("2026-10-24", out)

    def test_validate_file_on_a_good_activity(self):
        ok, errors, warnings = I.validate_file(self.ws / "activities/2026-10-20_running.md")
        self.assertEqual((ok, errors), (True, []))


if __name__ == "__main__":
    unittest.main()
