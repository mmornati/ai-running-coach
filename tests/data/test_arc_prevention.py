"""Palier D — prévention ciblée (#192) : normalisation des zones (accents, synonymes, vocabulaire de /log
et de Telegram), règles de sécurité déterministes (seuil de consultation, douleur aiguë, aggravation,
persistance, drapeau de risque de blessure), repli matériel, décision `medical` vs coach, et surtout :
aucun mot de diagnostic dans aucune sortie.

Aucun réseau ; les dates sont relatives à un `today` fixe passé aux fonctions pures ; les workspaces de la
CLI sont des répertoires temporaires — jamais le workspace réel.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_prevention as PV  # noqa: E402
import arc_strength as SG  # noqa: E402
import arc_telegram as TG  # noqa: E402
from coach_config import ConfigError  # noqa: E402

TODAY = date(2026, 10, 4)
DOC, EXERCISES, SDOC = PV._library()
THRESHOLD = 7.0

# Mots de diagnostic interdits dans toute sortie (« diagnostic » lui-même reste permis : « sans diagnostic »).
# Liste partagée avec le palier B (prompts, documentation) : `arc_prevention.DIAGNOSIS_TERMS`.
DIAGNOSIS_WORDS = PV.DIAGNOSIS_TERMS
CARE_WORDS = PV.CARE_TERMS


def entry(days_ago: int, location: str, score: float) -> dict:
    return {"date": (TODAY - timedelta(days=days_ago)).isoformat(), "location": location, "score": score}


def evaluate(entries, **kw):
    kw.setdefault("available", ["none", "elastic"])
    return PV.evaluate(entries, TODAY, kw.pop("threshold", THRESHOLD), DOC, EXERCISES, SDOC, **kw)


def confirmed(location: str, score: float = 2) -> list:
    """Deux déclarations à 3 jours d'écart, sans hausse : la gêne « connue et stable » qui ouvre la routine."""
    return [entry(5, location, score), entry(2, location, score)]


def only_zone(report, zone):
    found = [z for z in report["zones"] if z["zone"] == zone]
    assert len(found) == 1, report
    return found[0]


class TestShippedData(unittest.TestCase):
    def test_shipped_prevention_file_is_valid(self):
        self.assertEqual(PV.validate_prevention(DOC, EXERCISES), [])

    def test_ten_zones_are_covered(self):
        self.assertEqual({z["id"] for z in DOC["zones"]},
                         {"tendon_achille", "cheville", "mollet", "tibia", "genou", "hanche", "fessier",
                          "ischio", "pied", "bas_du_dos"})

    def test_routines_are_gentle_and_impact_free(self):
        for z in DOC["zones"]:
            for b in z["exercises"]:
                ex = EXERCISES[b["exercise"]]
                self.assertNotEqual(ex["group"], "pliometrie", z["id"])
                self.assertLessEqual(b["sets"], 3, z["id"])
                self.assertNotIn("quadriceps_excentrique", ex["targets"], z["id"])

    def test_validation_catches_broken_data(self):
        import copy
        bad = copy.deepcopy(DOC)
        bad["zones"][0]["exercises"][0]["exercise"] = "inconnu"
        self.assertTrue(PV.validate_prevention(bad, EXERCISES))
        bad = copy.deepcopy(DOC)
        bad["zones"][0]["exercises"].append({"exercise": "saut_squat", "sets": 2, "reps": 5})
        self.assertTrue(any("pliométrie" in e for e in PV.validate_prevention(bad, EXERCISES)))
        bad = copy.deepcopy(DOC)
        bad["thresholds"]["gentle_max_score"] = 0
        self.assertTrue(PV.validate_prevention(bad, EXERCISES))


class TestZoneNormalisation(unittest.TestCase):
    def test_accents_case_and_synonyms(self):
        cases = {
            "Tendon d'Achille gauche": ("tendon_achille", "left"),
            "tendon d’Achille": ("tendon_achille", None),
            "TENDON D'ACHILLE": ("tendon_achille", None),
            "talon d'Achille": ("tendon_achille", None),
            "voûte plantaire": ("pied", None),
            "Voute plantaire droite": ("pied", "right"),
            "talon": ("pied", None),
            "mollet droit": ("mollet", "right"),
            "Mollets": ("mollet", None),
            "cheville gauche": ("cheville", "left"),
            "périoste": ("tibia", None),
            "face interne du tibia": ("tibia", None),
            "genou gauche": ("genou", "left"),
            "face externe du genou": ("genou", None),
            "bandelette": ("genou", None),
            "hanche": ("hanche", None),
            "aine droite": ("hanche", "right"),
            "fessier": ("fessier", None),
            "ischio-jambiers": ("ischio", None),
            "arrière de la cuisse": ("ischio", None),
            "Ischios": ("ischio", None),
            "bas du dos": ("bas_du_dos", None),
            "lombaires": ("bas_du_dos", None),
            "dos": ("bas_du_dos", None),
        }
        for text, (zone, side) in cases.items():
            with self.subTest(text=text):
                got = PV.normalize_zone(DOC, text)
                self.assertEqual((got["zone"], got["side"]), (zone, side))

    def test_unknown_or_empty_zone_is_never_guessed(self):
        for text in ("", "   ", "autre", "quadriceps", "épaule", "bras gauche", None):
            with self.subTest(text=text):
                self.assertIsNone(PV.normalize_zone(DOC, text)["zone"])

    def test_substring_is_not_a_match(self):
        # « dossier » contient « dos » mais n'est pas la zone ; « pieds » = pied (pluriel déclaré).
        self.assertIsNone(PV.normalize_zone(DOC, "dossier")["zone"])
        self.assertEqual(PV.normalize_zone(DOC, "pieds")["zone"], "pied")

    def test_every_telegram_pain_zone_is_understood(self):
        for z in TG.PAIN_ZONES:
            if z == "autre":
                continue
            with self.subTest(zone=z):
                self.assertIsNotNone(PV.normalize_zone(DOC, z)["zone"])

    def test_telegram_free_text_zone_with_side(self):
        got = PV.normalize_zone(DOC, "mollet droit")
        self.assertEqual((got["zone"], got["side"]), ("mollet", "right"))

    def test_acute_keywords(self):
        for text in ("mollet gonflé", "douleur vive au mollet", "genou soudaine", "cheville : craquement",
                     "Mollet enflé"):
            with self.subTest(text=text):
                self.assertTrue(PV.is_acute(DOC, text))
        for text in ("mollet droit", "genou gauche", "vivement", ""):
            with self.subTest(text=text):
                self.assertFalse(PV.is_acute(DOC, text))


class TestSafetyRules(unittest.TestCase):
    def test_light_stable_known_discomfort_gets_a_gentle_routine(self):
        r = evaluate([entry(5, "mollet droit", 2), entry(2, "Mollet droit", 2)])
        z = only_zone(r, "mollet")
        self.assertEqual((r["status"], z["status"]), ("prevention_ok", "prevention_ok"))
        self.assertIsNone(z["consult_level"])
        self.assertEqual(z["sides"], ["right"])
        self.assertTrue(z["routine"]["blocks"])
        self.assertEqual(z["routine"]["level"], "doux")
        self.assertEqual(z["routine"]["fatigue"], "low")
        for b in z["routine"]["blocks"]:
            self.assertLessEqual(b["sets"], 3)
            self.assertNotEqual(b["group"], "pliometrie")

    def test_single_light_declaration_is_observed_without_any_exercise(self):
        r = evaluate([entry(1, "cheville", 1)])
        z = only_zone(r, "cheville")
        self.assertEqual((r["status"], z["status"], z["consult_level"]), ("observe", "observe", None))
        self.assertIsNone(z["routine"])
        self.assertEqual(len(z["questions"]), 3)
        joined = " ".join(z["questions"]).lower()
        for word in ("nouveau", "vif", "gonflement"):
            self.assertIn(word, joined)
        self.assertIn("--known", " ".join(z["reasons"]))

    def test_two_declarations_too_close_are_still_observed(self):
        for gap in (0, 1):
            with self.subTest(gap=gap):
                z = only_zone(evaluate([entry(1 + gap, "mollet", 2), entry(1, "mollet", 2)]), "mollet")
                self.assertEqual(z["status"], "observe")
                self.assertIsNone(z["routine"])
        z = only_zone(evaluate([entry(3, "mollet", 2), entry(1, "mollet", 2)]), "mollet")   # 2 jours : confirmé
        self.assertEqual(z["status"], "prevention_ok")

    def test_athlete_confirmation_opens_the_routine_on_a_first_declaration(self):
        for name in ("cheville", "Cheville gauche"):
            with self.subTest(name=name):
                z = only_zone(evaluate([entry(1, "cheville", 1)], known_zones=[name]), "cheville")
                self.assertEqual(z["status"], "prevention_ok")
                self.assertTrue(z["routine"]["blocks"])
                self.assertTrue(any("confirmée par l'athlète" in x for x in z["reasons"]))
        other = only_zone(evaluate([entry(1, "cheville", 1)], known_zones=["genou"]), "cheville")
        self.assertEqual(other["status"], "observe")

    def test_athlete_confirmation_never_lifts_another_rule(self):
        cases = (([entry(1, "mollet", 7)], "urgent"), ([entry(1, "mollet", 5)], "advised"),
                 ([entry(1, "mollet gonflé", 2)], "urgent"), ([entry(5, "mollet", 2), entry(1, "mollet", 3)], "advised"),
                 ([entry(10, "mollet", 2), entry(1, "mollet", 2)], "advised"))
        for entries, level in cases:
            with self.subTest(entries=entries):
                z = only_zone(evaluate(entries, known_zones=["mollet"]), "mollet")
                self.assertEqual((z["status"], z["consult_level"]), ("consult", level))
                self.assertIsNone(z["routine"])
        z = only_zone(evaluate([entry(1, "mollet", 2)], known_zones=["mollet"], acute_zones=["mollet"]), "mollet")
        self.assertEqual(z["status"], "consult")
        z = only_zone(evaluate([entry(1, "mollet", 2)], known_zones=["mollet"],
                               injury_risk={"level": "high", "consult": True}), "mollet")
        self.assertEqual(z["status"], "consult")

    def test_unevaluated_injury_risk_flag_never_counts_as_low(self):
        r = evaluate(confirmed("mollet"), injury_risk={"unavailable": True})
        z = only_zone(r, "mollet")
        self.assertEqual(z["status"], "observe")
        self.assertIsNone(z["routine"])
        self.assertTrue(r["injury_risk"]["unavailable"])
        self.assertTrue(r["injury_risk"]["blocks_routines"])
        self.assertIn("non évalué", PV.render_text(r))

    def test_improving_pain_is_still_gentle(self):
        z = only_zone(evaluate([entry(6, "mollet", 3), entry(2, "mollet", 2)]), "mollet")
        self.assertEqual(z["status"], "prevention_ok")

    def test_score_at_consult_threshold_means_no_exercise(self):
        r = evaluate([entry(1, "genou droit", 7)])
        z = only_zone(r, "genou")
        self.assertEqual((r["status"], z["status"], z["consult_level"]), ("consult", "consult", "urgent"))
        self.assertIsNone(z["routine"])
        self.assertIn("recommande de consulter un professionnel de santé", " ".join(z["reasons"]))
        self.assertIn("seuil de consultation (7/10)", " ".join(z["reasons"]))

    def test_custom_consult_threshold_is_honoured(self):
        z = only_zone(evaluate([entry(1, "genou", 5)], threshold=5.0), "genou")
        self.assertEqual(z["consult_level"], "urgent")
        self.assertIn("seuil de consultation (5/10)", " ".join(z["reasons"]))

    def test_moderate_score_is_advised_not_urgent_and_has_no_routine(self):
        for score in (4, 5, 6):
            with self.subTest(score=score):
                z = only_zone(evaluate([entry(1, "mollet", score)]), "mollet")
                self.assertEqual((z["status"], z["consult_level"]), ("consult", "advised"))
                self.assertIsNone(z["routine"])

    def test_a_past_peak_in_the_window_blocks_the_routine(self):
        z = only_zone(evaluate([entry(6, "mollet", 5), entry(1, "mollet", 2)]), "mollet")
        self.assertEqual(z["status"], "consult")

    def test_acute_keyword_means_urgent_consult(self):
        z = only_zone(evaluate([entry(1, "mollet gonflé", 2)]), "mollet")
        self.assertEqual((z["status"], z["consult_level"]), ("consult", "urgent"))
        self.assertIsNone(z["routine"])

    def test_acute_zone_declared_by_the_agent(self):
        for name in ("mollet", "Mollet droit"):
            with self.subTest(name=name):
                z = only_zone(evaluate(confirmed("mollet"), acute_zones=[name]), "mollet")
                self.assertEqual((z["status"], z["consult_level"]), ("consult", "urgent"))
        # une autre zone déclarée aiguë ne bloque pas celle-ci
        z = only_zone(evaluate(confirmed("mollet"), acute_zones=["genou"]), "mollet")
        self.assertEqual(z["status"], "prevention_ok")

    def test_acute_unrecognised_zone_declared_by_the_agent_consults(self):
        r = evaluate([entry(1, "épaule", 2)], acute_zones=["Épaule"])
        self.assertEqual((r["status"], r["unrecognized"][0]["consult_level"]), ("consult", "urgent"))

    def test_worsening_pain_is_advised(self):
        z = only_zone(evaluate([entry(5, "mollet", 2), entry(1, "mollet", 3)]), "mollet")
        self.assertEqual((z["status"], z["consult_level"]), ("consult", "advised"))
        self.assertTrue(any("s'aggrave" in x for x in z["reasons"]))

    def test_persistence_beyond_seven_days_is_advised(self):
        z = only_zone(evaluate([entry(9, "mollet", 2), entry(1, "mollet", 2)]), "mollet")   # 8 jours d'écart
        self.assertEqual((z["status"], z["consult_level"]), ("consult", "advised"))
        self.assertTrue(any("persiste" in x for x in z["reasons"]))
        ok = only_zone(evaluate([entry(8, "mollet", 2), entry(1, "mollet", 2)]), "mollet")  # 7 jours : toléré
        self.assertEqual(ok["status"], "prevention_ok")

    def test_injury_risk_flag_blocks_every_routine_and_is_never_relaxed(self):
        for risk in ({"level": "high", "consult": False}, {"level": "moderate", "consult": True},
                     {"level": "high", "consult": True}):
            with self.subTest(risk=risk):
                r = evaluate([entry(5, "mollet", 2), entry(2, "mollet", 2)], injury_risk=risk)
                z = only_zone(r, "mollet")
                self.assertEqual((z["status"], z["consult_level"]), ("consult", "urgent"))
                self.assertIsNone(z["routine"])
                self.assertTrue(r["injury_risk"]["blocks_routines"])
        calm = evaluate([entry(5, "mollet", 2), entry(2, "mollet", 2)], injury_risk={"level": "moderate", "consult": False})
        self.assertEqual(calm["status"], "prevention_ok")
        self.assertFalse(calm["injury_risk"]["blocks_routines"])

    def test_no_declaration_means_no_data(self):
        r = evaluate([])
        self.assertEqual((r["status"], r["zones"], r["unrecognized"]), ("no_data", [], []))
        self.assertIn("jamais d'exercice", r["no_data_reason"])

    def test_declarations_outside_the_window_are_ignored(self):
        r = evaluate([entry(20, "mollet", 2)])
        self.assertEqual(r["status"], "no_data")
        self.assertEqual(evaluate([entry(20, "mollet", 2)], window_days=30)["status"], "observe")

    def test_future_or_invalid_entries_are_ignored(self):
        bad = [entry(-3, "mollet", 2), {"date": "n'importe quoi", "location": "mollet", "score": 2},
               {"date": TODAY.isoformat(), "location": "mollet", "score": 14},
               {"date": TODAY.isoformat(), "location": "mollet"}]
        self.assertEqual(evaluate(bad)["status"], "no_data")

    def test_zero_score_means_resolved(self):
        r = evaluate([entry(5, "mollet", 3), entry(1, "mollet", 0)])
        self.assertEqual((r["status"], r["zones"], r["resolved"]), ("no_data", [], ["mollet"]))
        r = evaluate([entry(5, "mollet", 5), entry(1, "mollet", 0)])            # sous le seuil : résolue
        self.assertEqual(r["resolved"], ["mollet"])

    def test_zero_score_never_erases_a_red_flag_of_the_window(self):
        for entries in ([entry(3, "genou", 8), entry(1, "genou", 0)],
                        [entry(3, "genou gonflé", 2), entry(1, "genou", 0)]):
            with self.subTest(entries=entries):
                r = evaluate(entries)
                z = only_zone(r, "genou")
                self.assertEqual((r["status"], z["status"], z["consult_level"]), ("consult", "consult", "urgent"))
                self.assertEqual(z["latest_score"], 0)
                self.assertIsNone(z["routine"])
                self.assertEqual(r["resolved"], [])
                self.assertTrue(any("0/10" in x for x in z["reasons"]))

    def test_worst_score_of_the_day_wins(self):
        z = only_zone(evaluate([entry(1, "mollet", 2), entry(1, "mollet gauche", 7)]), "mollet")
        self.assertEqual(z["consult_level"], "urgent")

    def test_unrecognised_zone_gets_no_routine(self):
        r = evaluate([entry(1, "épaule", 2)])
        self.assertEqual((r["status"], r["zones"]), ("no_data", []))
        self.assertEqual(r["unrecognized"][0]["status"], "no_data")
        self.assertIsNone(r["unrecognized"][0].get("routine"))

    def test_unrecognised_zone_still_consults_above_threshold(self):
        r = evaluate([entry(1, "épaule", 8)])
        self.assertEqual((r["status"], r["unrecognized"][0]["consult_level"]), ("consult", "urgent"))

    def test_overall_status_is_the_most_severe(self):
        r = evaluate([entry(1, "mollet", 2), entry(1, "genou", 8)])
        self.assertEqual(r["status"], "consult")
        self.assertEqual([z["zone"] for z in r["zones"]], ["genou", "mollet"])   # le plus grave d'abord
        r = evaluate(confirmed("mollet") + [entry(1, "cheville", 1)])
        self.assertEqual(r["status"], "observe")                                  # observer avant de proposer
        self.assertEqual([z["status"] for z in r["zones"]], ["observe", "prevention_ok"])

    def test_rule_order_and_threshold_boundaries(self):
        # Mutations de seuils : chaque frontière est figée (une inversion d'ordre ou un < / <= change ces sorties).
        grid = {
            (2, 2, 3): ("prevention_ok", None),     # écart 3 j, stable
            (3, 3, 3): ("prevention_ok", None),     # 3/10 = gêne légère, incluse
            (3.5, 3.5, 3): ("consult", "advised"),  # au-dessus de 3/10
            (6.9, 6.9, 3): ("consult", "advised"),
            (7, 7, 3): ("consult", "urgent"),       # seuil de consultation inclus
            (3, 2, 3): ("prevention_ok", None),     # en baisse
            (2, 2.5, 3): ("prevention_ok", None),   # hausse < 1 point
            (2, 3, 3): ("consult", "advised"),      # hausse d'1 point
            (2, 2, 7): ("prevention_ok", None),     # 7 jours : toléré
            (2, 2, 8): ("consult", "advised"),      # 8 jours : persiste
            (2, 2, 1): ("observe", None),           # trop rapproché
        }
        for (first, last, gap), expected in grid.items():
            with self.subTest(first=first, last=last, gap=gap):
                z = only_zone(evaluate([entry(1 + gap, "mollet", first), entry(1, "mollet", last)]), "mollet")
                self.assertEqual((z["status"], z["consult_level"]), expected)
                self.assertEqual(z["routine"] is not None, expected[0] == "prevention_ok")

    def test_custom_thresholds_from_the_data_file_are_honoured(self):
        import copy
        doc = copy.deepcopy(DOC)
        doc["thresholds"].update(gentle_max_score=2, persistence_days=5, confirm_min_span_days=4)
        run = lambda e: only_zone(PV.evaluate(e, TODAY, THRESHOLD, doc, EXERCISES, SDOC, available=["none"]), "mollet")
        self.assertEqual(run([entry(5, "mollet", 3), entry(1, "mollet", 3)])["consult_level"], "advised")
        self.assertEqual(run([entry(7, "mollet", 2), entry(1, "mollet", 2)])["consult_level"], "advised")
        self.assertEqual(run([entry(5, "mollet", 2), entry(1, "mollet", 2)])["status"], "prevention_ok")
        self.assertEqual(run([entry(4, "mollet", 2), entry(1, "mollet", 2)])["status"], "observe")


class TestRoutineAndEquipment(unittest.TestCase):
    def test_elastic_exercise_falls_back_to_a_bodyweight_regression(self):
        r = evaluate([entry(5, "hanche", 2), entry(2, "hanche", 2)], available=["none"])
        z = only_zone(r, "hanche")
        names = [b["exercise_id"] for b in z["routine"]["blocks"]]
        self.assertNotIn("coquille_elastique", names)
        self.assertIn("abduction_allongee_cote", names)
        self.assertEqual(z["routine"]["substitutions"][0]["from"], "coquille_elastique")
        self.assertEqual(z["routine"]["questions"], [])

    def test_every_zone_has_a_bodyweight_routine(self):
        for zone in DOC["zones"]:
            with self.subTest(zone=zone["id"]):
                r = evaluate(confirmed(zone["synonyms"][0]), available=["none"])
                z = only_zone(r, zone["id"])
                self.assertGreaterEqual(len(z["routine"]["blocks"]), 2)
                for b in z["routine"]["blocks"]:
                    self.assertEqual(b["equipment"], ["none"])

    def test_unknown_equipment_asks_instead_of_guessing(self):
        z = only_zone(evaluate(confirmed("hanche"), available=None), "hanche")
        self.assertFalse(z["routine"]["equipment"]["known"])
        self.assertTrue(z["routine"]["questions"])
        self.assertEqual(z["routine"]["substitutions"], [])

    def test_routine_carries_progression_and_placement(self):
        z = only_zone(evaluate(confirmed("mollet")), "mollet")
        self.assertIn("14 jours sans aucune gêne", z["routine"]["progression_rule"])
        self.assertEqual(z["routine"]["placement"]["fatigue"], "low")
        self.assertTrue(any(b["next_level"] for b in z["routine"]["blocks"]))

    def test_next_level_never_shows_eccentric_or_plyometric_work(self):
        banned = set(DOC["never_in_prevention"])
        banned_names = {EXERCISES[i]["name"] for i in banned} | {
            e["name"] for e in EXERCISES.values() if e["group"] == "pliometrie"}
        self.assertTrue({"nordique_assiste", "squat_excentrique_lent", "mollet_excentrique_marche",
                         "descente_de_marche_excentrique"} <= banned)
        for zone in DOC["zones"]:
            for avail in (["none"], ["none", "elastic", "dumbbell", "step", "box"]):
                with self.subTest(zone=zone["id"], avail=avail):
                    z = only_zone(evaluate(confirmed(zone["synonyms"][0]), available=avail), zone["id"])
                    for b in z["routine"]["blocks"]:
                        self.assertNotIn(b["exercise_id"], banned)
                        self.assertFalse(set(b["next_level"]) & banned_names, b)

    def test_zone_specific_exclusions(self):
        # Exercice par exercice : ce qu'une zone douloureuse ne doit JAMAIS recevoir dans la routine douce.
        forbidden = {
            "tendon_achille": {"mobilite_cheville_genou_mur", "etirement_mollet", "mollet_unipodal_lestee"},
            "mollet": {"etirement_mollet", "mollet_unipodal_lestee"},
            "genou": {"chaise_murale", "squat_poids_du_corps", "squat_gobelet", "fente_arriere", "fente_bulgare",
                      "fente_laterale", "montee_de_marche", "montee_de_marche_lestee"},
            "ischio": {"flexion_jambe_glissante", "flexion_jambe_glissante_unilaterale", "balancier_jambes",
                       "etirement_ischio", "souleve_de_terre_roumain_unilateral", "bonjour_elastique"},
            "tibia": {"marche_pointes_halteres"},
        }
        for zone in DOC["zones"]:
            ids = {b["exercise"] for b in zone["exercises"]}
            with self.subTest(zone=zone["id"]):
                self.assertFalse(ids & forbidden.get(zone["id"], set()))
                self.assertFalse(ids & set(DOC["never_in_prevention"]))

    def test_tendon_and_knee_routines_hold_back_impact_and_deep_loading(self):
        for zid in ("tendon_achille", "genou"):
            z = next(x for x in DOC["zones"] if x["id"] == zid)
            ids = {b["exercise"] for b in z["exercises"]}
            self.assertFalse(ids & {"mollet_excentrique_marche", "saut_squat", "rebonds_cheville", "fente_bulgare",
                                    "squat_excentrique_lent", "descente_de_marche_excentrique"}, zid)


class TestDecisionOwnerAndDisclaimer(unittest.TestCase):
    def test_coach_decides_without_medical_and_says_it_is_not_a_medical_opinion(self):
        r = evaluate(confirmed("mollet"), medical_enabled=False)
        self.assertEqual(r["decision_owner"], "coach")
        self.assertIn("Ce n'est pas un avis médical", r["disclaimer"])
        self.assertIn("Ce n'est pas un avis médical", PV.render_text(r))

    def test_medical_owns_the_decision_when_enabled(self):
        r = evaluate(confirmed("mollet"), medical_enabled=True)
        self.assertEqual(r["decision_owner"], "medical")
        self.assertIn("agent medical", r["disclaimer"])
        self.assertIn("sans l'assouplir", r["disclaimer"])

    def test_outputs_propose_never_push(self):
        r = evaluate([entry(1, "mollet", 2)])
        self.assertIn("PROPOSE", r["proposal"])
        self.assertIn("aucun envoi automatique", r["proposal"])


class TestNoDiagnosisWords(unittest.TestCase):
    def test_shipped_data_names_no_diagnosis(self):
        def strings(node, skip=()):
            if isinstance(node, str):
                yield node
            elif isinstance(node, dict):
                for k, v in node.items():
                    if k not in skip:
                        yield from strings(v, skip)
            elif isinstance(node, list):
                for v in node:
                    yield from strings(v, skip)
        # `acute_keywords` et `synonyms` sont des mots que l'ATHLÈTE peut employer (entrée), jamais une sortie.
        for s in strings(DOC, skip=("acute_keywords", "synonyms")):
            self.assertIsNone(DIAGNOSIS_WORDS.search(s), s)
            self.assertIsNone(CARE_WORDS.search(s), s)

    def test_every_output_for_every_zone_and_status_is_free_of_diagnosis_words(self):
        scenarios = []
        for zone in DOC["zones"]:
            label = zone["synonyms"][0]
            scenarios += [
                [entry(5, label, 2), entry(2, label, 2)],       # routine douce
                [entry(1, label, 8)],                           # seuil
                [entry(1, label + " gonflé", 2)],               # aigu
                [entry(5, label, 2), entry(1, label, 3)],       # aggravation
                [entry(10, label, 2), entry(1, label, 2)],      # persistance
                [entry(1, label, 5)],                           # modéré
                [entry(1, label, 2)],                           # observation
                [entry(3, label, 8), entry(1, label, 0)],       # 0/10 après un signal d'alerte
            ]
        scenarios.append([entry(1, "épaule", 2)])
        for entries in scenarios:
            for med in (False, True):
                for risk in (None, {"level": "high", "consult": True}):
                    r = evaluate(entries, medical_enabled=med, injury_risk=risk)
                    for blob in (json.dumps(r, ensure_ascii=False), PV.render_text(r)):
                        m = DIAGNOSIS_WORDS.search(blob) or CARE_WORDS.search(blob)
                        self.assertIsNone(m, f"{entries} -> {m and m.group(0)}")

    def test_assumptions_name_no_diagnosis_either(self):
        for text in list(PV.ASSUMPTIONS.values()) + [PV.DISCLAIMER_COACH, PV.DISCLAIMER_MEDICAL]:
            self.assertIsNone(DIAGNOSIS_WORDS.search(text), text)
            self.assertIsNone(CARE_WORDS.search(text), text)

    def test_the_forbidden_lists_are_broad_enough(self):
        for word in ("tendinite", "Tendinopathie", "fasciite plantaire", "périostite", "syndrome rotulien", "entorse",
                     "déchirure", "fracture de fatigue", "bursite", "rupture", "claquage", "aponévrosite", "contracture",
                     "élongation", "sciatique", "hernie", "lésion", "inflammation", "ménisque", "pubalgie"):
            self.assertIsNotNone(DIAGNOSIS_WORDS.search(word), word)
        for word in ("soigner", "guérir", "guérison", "thérapie", "rééducation", "soulager", "traiter", "un traitement"):
            self.assertIsNotNone(CARE_WORDS.search(word), word)
        for ok in ("jamais un traitement", "aucun traitement", "kinésithérapeute", "sans diagnostic"):
            self.assertIsNone(DIAGNOSIS_WORDS.search(ok) or CARE_WORDS.search(ok), ok)

    def test_consultation_wording_is_the_same_as_log_and_telegram(self):
        import inspect
        sentence = "je te recommande de consulter un professionnel de santé avant de reprendre la course"
        z = only_zone(evaluate([entry(1, "genou", 8)]), "genou")
        self.assertIn(sentence, " ".join(z["reasons"]))
        src = inspect.getsource(TG)
        for half in ("je te recommande de consulter un", "professionnel de santé avant de reprendre la course"):
            self.assertIn(half, src)


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        (self.ws / "medical").mkdir()

    def health(self, days_ago: int, pain: list) -> None:
        d = (TODAY - timedelta(days=days_ago)).isoformat()
        block = {"arc": 1, "kind": "health", "date": d, "morning_check": "full", "pain": pain}
        (self.ws / "medical" / f"{d}_health.md").write_text(
            f"# Bilan\n\n```arc\n{json.dumps(block, ensure_ascii=False)}\n```\n", encoding="utf-8")

    def cli(self, *argv: str) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = I.main(["prevention", "--workspace", str(self.ws), "--today", TODAY.isoformat(), *argv])
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_json_default_reads_declared_pain_from_health_files(self):
        self.health(5, [{"location": "mollet droit", "score": 2}])
        self.health(2, [{"location": "mollet droit", "score": 2}])
        out = json.loads(self.cli("--equipment", "none"))
        self.assertEqual(out["status"], "prevention_ok")
        self.assertEqual(out["zones"][0]["zone"], "mollet")
        self.assertEqual(out["decision_owner"], "medical")        # défaut du moteur : agent medical activé
        self.assertEqual(out["consult_threshold"], 7.0)

    def test_text_output(self):
        self.health(5, [{"location": "mollet droit", "score": 2}])
        self.health(2, [{"location": "mollet droit", "score": 2}])
        text = self.cli("--text", "--equipment", "none")
        self.assertIn("Routine douce", text)
        self.assertIn("approximation du projet", text)
        self.assertFalse(text.lstrip().startswith("{"))

    def test_consult_threshold_comes_from_the_live_configuration(self):
        (self.ws / "config").mkdir()
        (self.ws / "config/workspace.user.toml").write_text(
            '[injury_risk]\npain_consult_threshold = 5\n\n[agents]\nenabled = ["coach"]\n', encoding="utf-8")
        self.health(1, [{"location": "genou", "score": 5}])
        out = json.loads(self.cli("--equipment", "none"))
        self.assertEqual(out["consult_threshold"], 5.0)
        self.assertEqual(out["decision_owner"], "coach")
        self.assertEqual(out["zones"][0]["consult_level"], "urgent")
        self.assertIsNone(out["zones"][0]["routine"])

    def test_injury_risk_flag_is_read_and_blocks(self):
        # Une douleur au genou >= seuil hier lève le drapeau de risque de blessure (#57, `high`/consult) : il bloque
        # AUSSI la gêne légère, confirmée et connue, d'une autre zone (le mollet) — jamais assoupli.
        self.health(5, [{"location": "mollet", "score": 2}])
        self.health(2, [{"location": "mollet", "score": 2}])
        self.health(1, [{"location": "genou", "score": 8}])
        out = json.loads(self.cli("--equipment", "none", "--known", "mollet"))
        self.assertIsNotNone(out["injury_risk"])
        self.assertTrue(out["injury_risk"]["blocks_routines"], out["injury_risk"])   # jamais vacuement vrai
        mollet = next(z for z in out["zones"] if z["zone"] == "mollet")
        self.assertEqual((mollet["status"], mollet["consult_level"]), ("consult", "urgent"))
        self.assertIsNone(mollet["routine"])
        self.assertTrue(any("drapeau de risque" in x for x in mollet["reasons"]))

    def test_acute_option(self):
        self.health(1, [{"location": "mollet", "score": 2}])
        out = json.loads(self.cli("--acute", "mollet", "--equipment", "none"))
        self.assertEqual(out["zones"][0]["consult_level"], "urgent")

    def test_first_declaration_is_observed_until_the_athlete_confirms(self):
        self.health(1, [{"location": "hanche", "score": 2}])
        out = json.loads(self.cli("--equipment", "none"))
        self.assertEqual((out["status"], out["zones"][0]["routine"]), ("observe", None))
        self.assertIn("nouveau", self.cli("--text", "--equipment", "none"))
        out = json.loads(self.cli("--equipment", "none", "--known", "hanche"))
        self.assertEqual(out["status"], "prevention_ok")
        self.assertTrue(out["zones"][0]["routine"]["blocks"])

    def test_equipment_from_profile_and_unknown(self):
        self.health(4, [{"location": "hanche", "score": 2}])
        self.health(1, [{"location": "hanche", "score": 2}])
        unknown = json.loads(self.cli())
        self.assertTrue(unknown["zones"][0]["routine"]["questions"])
        (self.ws / "planning").mkdir()
        (self.ws / "planning/Runner_Profile.md").write_text("- **Équipement** : élastique\n", encoding="utf-8")
        known = json.loads(self.cli())
        self.assertEqual(known["zones"][0]["routine"]["equipment"]["available"], ["elastic", "none"])

    def test_no_declaration(self):
        self.assertEqual(json.loads(self.cli())["status"], "no_data")

    def test_days_option(self):
        self.health(10, [{"location": "mollet", "score": 2}])
        self.assertEqual(json.loads(self.cli("--days", "5"))["status"], "no_data")
        self.assertEqual(json.loads(self.cli("--days", "14", "--equipment", "none"))["status"], "observe")
        with self.assertRaises(ConfigError):
            self.cli("--days", "0")

    def test_bad_equipment_is_a_config_error(self):
        self.health(1, [{"location": "mollet", "score": 2}])
        with self.assertRaises(ConfigError):
            self.cli("--equipment", "barre")

    def test_read_only(self):
        self.health(1, [{"location": "mollet", "score": 2}])
        before = sorted(p.name for p in (self.ws / "medical").iterdir())
        self.cli("--equipment", "none")
        self.assertEqual(before, sorted(p.name for p in (self.ws / "medical").iterdir()))


if __name__ == "__main__":
    unittest.main()
