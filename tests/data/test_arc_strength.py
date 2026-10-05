"""Palier D — bibliothèque de renforcement (#191) : validation (références, couples Garmin, cohérence
mode/séries), sélection par phase/usage, repli matériel, charge d'affûtage, placement, charge utile Garmin
(forme identique au DTO du skill `garmin-workout-scheduling`) et version texte intervals.icu.

Aucun réseau : la liste blanche `GARMIN_VERIFIED` a été vérifiée une fois contre le catalogue Garmin
(voir la docstring de `arc_strength`) ; ici on verrouille qu'aucune donnée ne s'en écarte. Les workspaces
sont des répertoires temporaires — jamais le workspace réel.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_strength as SG  # noqa: E402
from coach_config import ConfigError  # noqa: E402

EX_DOC = json.loads((REPO / "config/strength/exercises.json").read_text(encoding="utf-8"))
PROG_DOC = json.loads((REPO / "config/strength/programmes.json").read_text(encoding="utf-8"))
EXERCISES, DOC = SG.load_library()
EQUIPMENT_SETS = [["none"], ["none", "elastic"], ["none", "dumbbell"], ["none", "step"], ["none", "box"],
                  ["none", "elastic", "dumbbell", "step", "box"]]


def libs():
    return copy.deepcopy(EX_DOC), copy.deepcopy(PROG_DOC)


def cli(*argv: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = I.main(list(argv))
    assert rc == 0
    return buf.getvalue()


class TestShippedLibrary(unittest.TestCase):
    def test_shipped_library_is_valid(self):
        self.assertEqual(SG.validate_library(EX_DOC, PROG_DOC), [])

    def test_size_and_coverage(self):
        self.assertGreaterEqual(len(EXERCISES), 30)
        self.assertLessEqual(len(EXERCISES), 60)
        for target in ("mollet_gastrocnemien", "soleaire", "tibial_anterieur", "quadriceps_excentrique", "ischio_jambiers",
                       "fessiers", "abducteurs_hanche", "gainage", "intrinseques_pied", "pliometrie"):
            self.assertTrue(any(target in e["targets"] for e in EXERCISES.values()), target)
        for q in SG.EQUIPMENT:
            self.assertTrue(any(q in e["equipment"] for e in EXERCISES.values()), q)

    def test_every_exercise_is_in_french_with_cues_and_caution(self):
        for e in EXERCISES.values():
            self.assertGreaterEqual(len(e["cues"]), 2, e["id"])
            self.assertTrue(e["caution"].strip(), e["id"])

    def test_garmin_whitelist_is_exactly_what_the_data_uses(self):
        used = {(e["garmin"]["category"], e["garmin"]["exercise"]) for e in EXERCISES.values() if e["garmin"]}
        listed = {(c, x) for c, xs in SG.GARMIN_VERIFIED.items() for x in xs}
        self.assertEqual(used, listed)   # pas de couple mort, pas de couple non vérifié

    def test_garmin_whitelist_is_frozen(self):
        # Empreinte de la liste vérifiée le 2026-10-04 contre le catalogue Garmin (42 couples). Ajouter un
        # couple = le vérifier d'abord dans Exercises.json, puis mettre à jour cette empreinte, sciemment.
        import hashlib
        pairs = sorted(f"{c}/{x}" for c, xs in SG.GARMIN_VERIFIED.items() for x in xs)
        self.assertEqual(len(pairs), 42)
        self.assertEqual(hashlib.sha256("\n".join(pairs).encode()).hexdigest(),
                         "179480b71de95267a48f8f7b11a3d490cc68c3c7b8488bcdb1c222d38322abc2")

    def test_some_exercises_have_no_garmin_mapping(self):
        self.assertTrue(any(e["garmin"] is None for e in EXERCISES.values()))

    def test_every_programme_resolves_for_every_equipment_set(self):
        for p in DOC["programmes"]:
            for eq in EQUIPMENT_SETS:
                kw = {"phase": p["phase"]} if p["kind"] == "phase" else {"use": p["use"]}
                sel = SG.select_programme(EXERCISES, DOC, available=eq, **kw)
                blocks = sel["programme"]["blocks"]
                self.assertTrue(blocks, (p["id"], eq))
                for b in blocks:
                    self.assertTrue(set(b["equipment"]) <= set(eq) | {"none"}, (p["id"], eq, b["exercise_id"]))
                ids = [b["exercise_id"] for b in blocks]
                self.assertEqual(len(ids), len(set(ids)), (p["id"], eq))

    def test_emphases_match_the_periodisation_templates(self):
        import arc_plan_templates as PT
        self.assertEqual(SG.STRENGTH_EMPHASES, PT.STRENGTH_EMPHASES)
        self.assertEqual(SG.PHASES, PT.PHASES_PRE_RACE + (PT.PHASE_RECOVERY,))
        # Chaque emphase citée par un gabarit livré a son programme de phase, et `--phase <emphase>` le résout.
        cited = set()
        for path in sorted((REPO / "config/plans").glob("*.json")):
            tpl = json.loads(path.read_text(encoding="utf-8"))
            for ph in tpl["phases"]:
                self.assertIn(ph["strength"], SG.STRENGTH_EMPHASES, (path.name, ph))
                cited.add(ph["strength"])
        self.assertTrue(cited)
        for emph in cited:
            sel = SG.select_programme(EXERCISES, DOC, phase=emph, available=None)
            self.assertEqual(sel["emphasis"], emph)


class TestValidationCatchesBreakage(unittest.TestCase):
    def errs(self, ex_doc, doc):
        return SG.validate_library(ex_doc, doc)

    def test_unknown_garmin_pair(self):
        ex, doc = libs()
        ex["exercises"][0]["garmin"] = {"category": "SQUAT", "exercise": "NOT_A_GARMIN_KEY"}
        self.assertTrue(any("GARMIN_VERIFIED" in e for e in self.errs(ex, doc)))

    def test_unknown_garmin_category(self):
        ex, doc = libs()
        ex["exercises"][0]["garmin"] = {"category": "UNASSIGNED", "exercise": "AIR_SQUAT"}
        self.assertTrue(any("GARMIN_VERIFIED" in e for e in self.errs(ex, doc)))

    def test_broken_progression_and_regression_refs(self):
        ex, doc = libs()
        ex["exercises"][0]["progressions"] = ["ghost"]
        ex["exercises"][1]["regressions"] = [ex["exercises"][1]["id"]]
        out = " | ".join(self.errs(ex, doc))
        self.assertIn("« ghost » inconnu", out)
        self.assertIn("se référence lui-même", out)

    def test_duplicate_id(self):
        ex, doc = libs()
        ex["exercises"][1]["id"] = ex["exercises"][0]["id"]
        self.assertTrue(any("id en double" in e for e in self.errs(ex, doc)))

    def test_vocabulary_violations(self):
        ex, doc = libs()
        ex["exercises"][0]["equipment"] = ["barbell"]
        ex["exercises"][0]["targets"] = ["biceps"]
        ex["exercises"][0]["mode"] = "distance"
        out = " | ".join(self.errs(ex, doc))
        self.assertIn("equipment", out)
        self.assertIn("targets", out)
        self.assertIn("mode", out)

    def test_programme_block_with_unknown_exercise(self):
        ex, doc = libs()
        doc["programmes"][0]["blocks"][0]["exercise"] = "ghost"
        self.assertTrue(any("« ghost » inconnu" in e for e in self.errs(ex, doc)))

    def test_programme_warmup_with_unknown_exercise(self):
        ex, doc = libs()
        doc["programmes"][0]["warmup"] = ["ghost"]
        self.assertTrue(any("warmup" in e for e in self.errs(ex, doc)))

    def test_mode_must_match_reps_or_seconds(self):
        ex, doc = libs()
        timed = next(i for i, b in enumerate(doc["programmes"][0]["blocks"]) if "seconds" in b)
        b = doc["programmes"][0]["blocks"][timed]
        b["reps"] = b.pop("seconds")
        self.assertTrue(any("chronométré" in e for e in self.errs(ex, doc)))

    def test_bad_tempo_and_each_side(self):
        ex, doc = libs()
        doc["programmes"][0]["blocks"][0]["tempo"] = "lent"
        bilateral = next(b for b in doc["programmes"][0]["blocks"] if not EXERCISES[b["exercise"]]["unilateral"])
        bilateral["each_side"] = True
        out = " | ".join(self.errs(ex, doc))
        self.assertIn("tempo", out)
        self.assertIn("each_side", out)

    def test_missing_emphasis_and_use(self):
        ex, doc = libs()
        doc["programmes"] = [p for p in doc["programmes"] if p.get("emphasis") != "entretien" and p.get("use") != "pied"]
        out = " | ".join(self.errs(ex, doc))
        self.assertIn("entretien", out)
        self.assertIn("pied", out)

    def test_unknown_emphasis(self):
        ex, doc = libs()
        doc["programmes"][0]["emphasis"] = "hypertrophie"
        self.assertTrue(any("hypertrophie" in e for e in self.errs(ex, doc)))

    def test_status_must_stay_an_approximation(self):
        ex, doc = libs()
        doc["status"] = "valide"
        self.assertTrue(any("approximation_projet" in e for e in self.errs(ex, doc)))

    def test_load_library_raises_on_invalid_directory(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "exercises.json").write_text("{}", encoding="utf-8")
            (Path(d) / "programmes.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(SG.StrengthError):
                SG.load_library(Path(d))


class TestSelection(unittest.TestCase):
    def sel(self, **kw):
        kw.setdefault("available", None)
        return SG.select_programme(EXERCISES, DOC, **kw)

    def test_phase_maps_to_template_emphasis(self):
        for phase, emph in SG.PHASE_TO_EMPHASIS.items():
            s = self.sel(phase=phase)
            self.assertEqual(s["emphasis"], emph)
            self.assertEqual(s["programme"]["kind"], "phase")

    def test_phase_aliases_french_and_emphasis(self):
        self.assertEqual(SG.normalize_phase("Développement"), "development")
        self.assertEqual(SG.normalize_phase("affûtage"), "taper")
        self.assertEqual(SG.normalize_phase("spécifique"), "specific")
        self.assertEqual(SG.normalize_phase("pliometrie_excentrique"), "specific")
        self.assertEqual(SG.normalize_use("Hanches"), "hanches")

    def test_unknown_phase_use_and_no_args(self):
        for kw in ({"phase": "hiver"}, {"use": "genou"}, {}):
            with self.assertRaises(SG.StrengthError):
                self.sel(**kw)

    def test_use_programme_and_window_warning(self):
        s = self.sel(use="descente", phase="base")
        self.assertEqual(s["programme"]["id"], "usage_descente")
        self.assertTrue(any("fenêtre" in w for w in s["warnings"]))
        self.assertFalse(any("fenêtre" in w for w in self.sel(use="descente", phase="specific")["warnings"]))

    def test_taper_applies_volume_factor_and_drops_plyometrics(self):
        full = self.sel(use="descente", phase="specific")["programme"]["blocks"]
        taper = self.sel(use="descente", phase="taper")["programme"]["blocks"]
        for f, t in zip(full, taper):
            self.assertEqual(t["sets"], max(1, int(f["sets"] * 0.67 + 0.5)), f["exercise_id"])
        self.assertTrue(all(b["group"] != "pliometrie" for b in taper))
        # un programme de phase « affûtage » n'est pas réduit une seconde fois
        base_sets = [b["sets"] for b in DOC["programmes"][3]["blocks"]]
        self.assertEqual([b["sets"] for b in self.sel(phase="taper")["programme"]["blocks"]], base_sets)

    def test_taper_drops_plyometrics_of_a_use_programme_that_has_some(self):
        ex, doc = copy.deepcopy(EXERCISES), copy.deepcopy(DOC)
        usage = next(p for p in doc["programmes"] if p.get("use") == "pied")
        usage["blocks"].append({"exercise": "saut_squat", "sets": 2, "reps": 5, "rest_s": 60, "each_side": False})
        s = SG.select_programme(ex, doc, use="pied", phase="taper", available=None)
        self.assertTrue(any(d["reason"].startswith("pliométrie") for d in s["dropped"]))

    def test_recovery_with_a_use_falls_back_to_mobility(self):
        s = self.sel(use="descente", phase="recovery")
        self.assertEqual(s["programme"]["id"], "recuperation_mobilite")
        self.assertTrue(s["warnings"])

    def test_unknown_equipment_asks_and_applies_no_fallback(self):
        s = self.sel(phase="specific", available=None)
        self.assertFalse(s["equipment"]["known"])
        self.assertTrue(s["questions"])
        self.assertEqual(s["substitutions"], [])
        self.assertTrue(any("step" in b["equipment"] for b in s["programme"]["blocks"]))

    def test_known_equipment_falls_back_to_regressions(self):
        s = self.sel(phase="specific", available=["none"])
        self.assertTrue(s["equipment"]["known"])
        self.assertEqual(s["questions"], [])
        self.assertIn({"from": "descente_de_marche_excentrique", "to": "squat_excentrique_lent"},
                      [{k: x[k] for k in ("from", "to")} for x in s["substitutions"]])
        for sub in s["substitutions"]:
            self.assertIn("matériel manquant", sub["reason"])

    def test_substitution_that_changes_mode_is_coerced(self):
        ex, doc = copy.deepcopy(EXERCISES), copy.deepcopy(DOC)
        usage = next(p for p in doc["programmes"] if p.get("use") == "pied")
        s = SG.select_programme(ex, doc, use="pied", available=["none"])
        farmer = [b for b in s["programme"]["blocks"] if b["exercise_id"] == "mollet_debout"]
        self.assertEqual(len(farmer), 1)           # doublon retiré après repli de marche_pointes_halteres
        self.assertTrue(any(d["reason"].startswith("doublon") for d in s["dropped"]))
        self.assertTrue(usage)

    def test_exercise_without_fallback_is_dropped(self):
        ex, doc = copy.deepcopy(EXERCISES), copy.deepcopy(DOC)
        ex["fente_bulgare"]["regressions"] = []
        s = SG.select_programme(ex, doc, phase="development", available=["none"])
        self.assertTrue(any(d["exercise"] == "fente_bulgare" for d in s["dropped"]))

    def test_parse_equipment(self):
        self.assertEqual(SG.parse_equipment("elastic, dumbbell"), ["dumbbell", "elastic", "none"])
        self.assertEqual(SG.parse_equipment("none"), ["none"])
        with self.assertRaises(SG.StrengthError):
            SG.parse_equipment("barre")

    def test_equipment_from_profile_line(self):
        template = (REPO / "templates/Runner_Profile.template.md").read_text(encoding="utf-8")
        self.assertFalse(SG.equipment_from_profile(template)["known"])      # gabarit non rempli
        self.assertFalse(SG.equipment_from_profile("")["known"])
        got = SG.equipment_from_profile("- **Équipement** : haltères, élastiques et une marche\n")
        self.assertEqual(got["available"], ["dumbbell", "elastic", "none", "step"])
        gym = SG.equipment_from_profile("- **Équipement** : salle de sport\n")
        self.assertEqual(gym["available"], ["box", "dumbbell", "none", "step"])
        self.assertFalse(SG.equipment_from_profile("- **Équipement** : tapis\n")["known"])   # rien de reconnu

    def test_equipment_from_profile_is_robust(self):
        def avail(text):
            return SG.equipment_from_profile(f"- **Équipement** : {text}\n")["available"]
        for none_only in ("aucun", "Aucun matériel", "rien", "poids du corps uniquement",
                          "sans élastique ni haltères, poids du corps"):
            self.assertEqual(avail(none_only), ["none"], none_only)
        self.assertEqual(avail("pas d'haltères, juste un élastique"), ["elastic", "none"])     # négation
        self.assertEqual(avail("pas d’haltères, juste un élastique"), ["elastic", "none"])
        self.assertEqual(avail("élastiques (mini-bands), box, marches"), ["box", "elastic", "none", "step"])
        for not_equipment in ("boxe", "bandeau", "marche à pied", "ballon suisse"):         # mots entiers
            self.assertIsNone(avail(not_equipment), not_equipment)

    def test_placement_rules_and_check(self):
        high = SG.placement_rules(DOC, "high")
        self.assertFalse(SG.check_placement(high, hours_to_quality=24)["ok"])      # veille d'une VMA
        self.assertTrue(SG.check_placement(high, hours_to_quality=72, hours_to_long_run=60, days_to_race=10)["ok"])
        self.assertFalse(SG.check_placement(high, days_to_race=3)["ok"])
        self.assertTrue(SG.check_placement(SG.placement_rules(DOC, "low"), hours_to_quality=12)["ok"])
        for p in DOC["programmes"]:
            self.assertEqual(SG.select_programme(EXERCISES, DOC, **({"phase": p["phase"]} if p["kind"] == "phase" else {"use": p["use"]}),
                                                 available=None)["placement"]["fatigue"], p["fatigue"])


class TestGarminPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (REPO / "skills/garmin-workout-scheduling/SKILL.md").read_text(encoding="utf-8")
        section = text.split("### Strength circuit WITH FULL DETAIL", 1)[1]
        cls.skill_dto = json.loads(re.search(r"```json\n(.*?)\n```", section, re.S).group(1))

    def payload(self, **kw):
        return SG.garmin_payload(SG.select_programme(EXERCISES, DOC, available=kw.pop("available", ["none", "dumbbell", "step", "box", "elastic"]), **kw))

    def test_dto_shape_equals_the_skill_example(self):
        dto = self.payload(phase="base")["workout_data"]
        self.assertEqual(set(dto), set(self.skill_dto))
        self.assertEqual(dto["sportType"], self.skill_dto["sportType"])
        seg, skill_seg = dto["workoutSegments"][0], self.skill_dto["workoutSegments"][0]
        self.assertEqual(set(seg), set(skill_seg))
        self.assertEqual(seg["sportType"], skill_seg["sportType"])
        group, skill_group = seg["workoutSteps"][0], skill_seg["workoutSteps"][0]
        self.assertEqual(set(group), set(skill_group))
        self.assertEqual(group["endCondition"], skill_group["endCondition"])
        work, skill_work = group["workoutSteps"][0], skill_group["workoutSteps"][0]
        self.assertEqual(set(work), set(skill_work) - {"weightValue", "weightUnit"})
        for k in ("type", "stepType", "endCondition", "targetType"):
            self.assertEqual(work[k], skill_work[k], k)
        rest, skill_rest = group["workoutSteps"][1], skill_group["workoutSteps"][1]
        self.assertEqual(set(rest), set(skill_rest))
        for k in ("type", "stepType", "endCondition", "targetType"):
            self.assertEqual(rest[k], skill_rest[k], k)

    def test_only_verified_pairs_carry_category_and_exercise_name(self):
        pairs = {(c, x) for c, xs in SG.GARMIN_VERIFIED.items() for x in xs}
        for kw in ({"phase": p} for p in SG.PHASES):
            dto = self.payload(**kw)["workout_data"]
            for g in dto["workoutSegments"][0]["workoutSteps"]:
                for s in g.get("workoutSteps", [g]):
                    if "category" in s or "exerciseName" in s:
                        self.assertIn((s.get("category"), s.get("exerciseName")), pairs)

    def test_unmapped_exercise_goes_without_garmin_keys(self):
        p = self.payload(phase="specific")
        self.assertIn("rebonds_cheville", p["unmapped"])
        self.assertTrue(any("sans correspondance" in w for w in p["warnings"]))
        steps = [s for g in p["workout_data"]["workoutSegments"][0]["workoutSteps"] for s in g["workoutSteps"]
                 if s["description"].startswith("Rebonds")]
        self.assertEqual(len(steps), 1)
        self.assertNotIn("category", steps[0])
        self.assertNotIn("exerciseName", steps[0])

    def test_reps_vs_time_steps_and_iterations(self):
        p = self.payload(phase="base")
        groups = p["workout_data"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual([g["stepOrder"] for g in groups], list(range(1, len(groups) + 1)))
        blocks = SG.select_programme(EXERCISES, DOC, phase="base", available=None)["programme"]["blocks"]
        for g, b in zip(groups, blocks):
            work = g["workoutSteps"][0]
            self.assertEqual(g["numberOfIterations"], b["sets"])
            if "seconds" in b:
                self.assertEqual(work["endCondition"]["conditionTypeKey"], "time")
                self.assertEqual(work["endConditionValue"], b["seconds"])
            else:
                self.assertEqual(work["endCondition"]["conditionTypeKey"], "reps")
                self.assertEqual(work["endConditionValue"], b["reps"])

    def test_timed_each_side_exercise_gets_one_step_per_side(self):
        p = self.payload(use="hanches")
        groups = p["workout_data"]["workoutSegments"][0]["workoutSteps"]
        side = [g for g in groups if g["workoutSteps"][0]["description"].startswith("Planche latérale (chaque côté)")]
        self.assertEqual(len(side), 1)
        inner = side[0]["workoutSteps"]
        self.assertEqual([s["stepOrder"] for s in inner], [1, 2, 3])
        self.assertEqual([s["endCondition"]["conditionTypeKey"] for s in inner], ["time", "time", "time"])
        self.assertEqual([s["stepType"]["stepTypeKey"] for s in inner], ["interval", "interval", "rest"])
        self.assertTrue(inner[0]["description"].endswith("côté 1/2") and inner[1]["description"].endswith("côté 2/2"))
        self.assertEqual(inner[0]["category"], "PLANK")

    def test_single_set_is_a_plain_step_not_a_group(self):
        p = self.payload(phase="taper", use="pied")        # 3 séances -> 2 séries ; force 1 série ci-dessous
        ex, doc = copy.deepcopy(EXERCISES), copy.deepcopy(DOC)
        doc["programmes"][3]["blocks"][0]["sets"] = 1
        sel = SG.select_programme(ex, doc, phase="taper", available=None)
        steps = SG.garmin_payload(sel)["workout_data"]["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(steps[0]["type"], "ExecutableStepDTO")
        self.assertEqual(steps[1]["stepType"]["stepTypeKey"], "rest")
        self.assertTrue(p)

    def test_create_strength_workout_arguments(self):
        p = self.payload(phase="development")["create_strength_workout"]
        self.assertEqual(set(p), {"name", "exercises"})
        for e in p["exercises"]:
            self.assertTrue({"name", "sets", "reps", "rest_seconds"} <= set(e))
            self.assertLessEqual(set(e), {"name", "sets", "reps", "rest_seconds", "category"})
            if "category" in e:
                self.assertIn(e["category"], SG.GARMIN_VERIFIED)
        timed = [e for e in self.payload(phase="base")["create_strength_workout"]["exercises"] if re.search(r"— \d+ s$", e["name"])]
        self.assertTrue(timed and all(e["reps"] == 1 for e in timed))

    def test_payload_never_writes_anything(self):
        self.assertIn("confirmation explicite", self.payload(phase="base")["note"])


class TestTextFallback(unittest.TestCase):
    def test_text_has_one_line_per_exercise_and_the_caveat(self):
        sel = SG.select_programme(EXERCISES, DOC, phase="base", available=["none", "dumbbell", "step"])
        text = SG.render_text(sel)
        for b in sel["programme"]["blocks"]:
            self.assertIn(b["name"], text)
            self.assertRegex(text, rf"{b['sets']} x {b['seconds'] if 'seconds' in b else b['reps']}")
        self.assertIn("approximation du projet", text)
        self.assertIn("ni prescription médicale ni diagnostic", text)
        self.assertIn("Placement", text)

    def test_text_says_when_equipment_is_unknown(self):
        text = SG.render_text(SG.select_programme(EXERCISES, DOC, phase="base", available=None))
        self.assertIn("inconnu", text)
        self.assertIn("Question", text)


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_catalogue_without_arguments(self):
        out = json.loads(cli("strength", "--workspace", self.ws))
        self.assertEqual(out["exercises"], len(EXERCISES))
        self.assertEqual(len(out["programmes"]), len(DOC["programmes"]))

    def test_json_text_and_garmin_outputs(self):
        sel = json.loads(cli("strength", "--workspace", self.ws, "--phase", "specific", "--equipment", "none"))
        self.assertEqual(sel["programme"]["id"], "specifique_excentrique_pliometrie")
        self.assertEqual(sel["equipment"]["source"], "cli")
        self.assertIn("approximation du projet", cli("strength", "--workspace", self.ws, "--use", "hanches", "--text"))
        g = json.loads(cli("strength", "--workspace", self.ws, "--use", "hanches", "--equipment", "elastic", "--garmin-json"))
        self.assertIn("workout_data", g)
        self.assertIn("create_strength_workout", g)

    def test_equipment_is_read_from_the_athlete_profile(self):
        planning = Path(self.ws) / "planning"
        planning.mkdir()
        (planning / "Runner_Profile.md").write_text("- **Équipement** : haltères, une marche\n", encoding="utf-8")
        sel = json.loads(cli("strength", "--workspace", self.ws, "--phase", "base"))
        self.assertEqual(sel["equipment"]["source"], "profile")
        self.assertEqual(sel["equipment"]["available"], ["dumbbell", "none", "step"])

    def test_equipment_follows_the_configured_profile_path(self):
        (Path(self.ws) / "config").mkdir()
        (Path(self.ws) / "config/workspace.user.toml").write_text('[athlete]\nprofile = "moi/profil.md"\n',
                                                                  encoding="utf-8")
        (Path(self.ws) / "moi").mkdir()
        (Path(self.ws) / "moi/profil.md").write_text("- **Équipement** : élastique\n", encoding="utf-8")
        sel = json.loads(cli("strength", "--workspace", self.ws, "--phase", "base"))
        self.assertEqual(sel["equipment"]["available"], ["elastic", "none"])

    def test_missing_profile_means_unknown_equipment(self):
        sel = json.loads(cli("strength", "--workspace", self.ws, "--phase", "base"))
        self.assertFalse(sel["equipment"]["known"])
        self.assertTrue(sel["questions"])

    def test_errors_are_config_errors(self):
        for argv in (["--phase", "hiver"], ["--use", "genou"], ["--phase", "base", "--equipment", "barre"]):
            with self.assertRaises(ConfigError):
                cli("strength", "--workspace", self.ws, *argv)

    def test_never_touches_the_index(self):
        cli("strength", "--workspace", self.ws, "--phase", "base")
        self.assertFalse((Path(self.ws) / ".arc").exists())


if __name__ == "__main__":
    unittest.main()
