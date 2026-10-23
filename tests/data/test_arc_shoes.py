"""Palier D — fiche de caractéristiques des chaussures (#298) : contrat `shoe_spec` (provenance
obligatoire, unités, bornes plausibles, mesure > marque, aberrations), sélection de la valeur retenue,
index minimaliste d'Esculier et al. 2015 (grille du fichier additionnel 1), indexation SQLite et
commande `arc_index.py shoe-specs`.

Fixtures SYNTHÉTIQUES : les deux tableaux publics de la story (Kiprun Kipride Max v1, Salomon Ultra
Glide 3) — aucune donnée personnelle. Les valeurs reprennent le tableau de l'issue #298 ; les URL et les
dates de consultation illustrent le FORMAT (elles ne sont pas relues ici). Les workspaces sont des
répertoires temporaires passés en `--workspace`, base en mémoire : jamais le workspace réel.
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
import arc_shoes as SH  # noqa: E402

RT = "https://www.rtings.com/running-shoes/reviews/kiprun/kipride-max"
RL = "https://runnerslab.com/kiprun-kipride-max-review/"
RW = "https://www.runningwarehouse.com/KIPRUN_Kipride_Max/descpage-KRMAXM3.html"
SS = "https://www.sportsshoes.com/product/sal6723/ultra-glide-3-men's-trail-running-shoes---aw25"
BF = "https://www.bergfreunde.eu/salomon-ultra-glide-3-trail-running-shoes/"
DAY = "2026-10-12"


def src(value, source_type, url, **extra):
    return {"value": value, "source_type": source_type, "url": url, "retrieved": DAY, **extra}


def kipride() -> dict:
    """Kipride Max v1 : drop marque 6 mm / mesuré 8,7 mm (RTINGS), piles 42/36 vs 44/38, poids mesuré 277 g (US 9)."""
    return {
        "arc": 1, "kind": "shoe_spec", "date": DAY, "gear_id": "kipride-max-1", "brand": "Kiprun",
        "model": "Kipride Max", "version": "v1", "release_year": 2026,
        "size": {"value": 42, "system": "EU"}, "purchase_date": "2026-02-20",
        "category": src("road", "manufacturer", RL),
        "drop_mm": {**src(8.7, "measured", RT), "alternatives": [src(6, "manufacturer", RL)]},
        "stack_heel_mm": {**src(42, "manufacturer", RL), "alternatives": [src(44, "manufacturer", RW)]},
        "stack_forefoot_mm": {**src(36, "manufacturer", RL), "alternatives": [src(38, "manufacturer", RW)]},
        "weight_g": {**src(277, "measured", RT), "reference_size": "US 9"},
        "plate": src("none", "manufacturer", RL),
        "flexibility_longitudinal": {"value": 1.5, "source_type": "athlete"},
        "flexibility_torsional": {"value": 1.0, "source_type": "athlete"},
        "stability_devices": {"value": 0, "source_type": "athlete"},
    }


def ultra_glide(outlier: bool = True) -> dict:
    """Ultra Glide 3 (2025) : drop 6 mm marque sans labo, piles 41/35, poids 240-285 g + une aberration à 580 g."""
    return {
        "arc": 1, "kind": "shoe_spec", "date": DAY, "gear_id": "ultra-glide-3", "brand": "Salomon",
        "model": "Ultra Glide", "version": "3", "release_year": 2025,
        "category": src("trail", "manufacturer", SS),
        "drop_mm": src(6, "manufacturer", SS),
        "stack_heel_mm": src(41, "manufacturer", SS),
        "stack_forefoot_mm": src(35, "manufacturer", SS),
        "weight_g": {**src(240, "manufacturer", SS), "alternatives": [
            src(285, "manufacturer", BF), src(580, "manufacturer", BF, **({"outlier": True} if outlier else {}))]},
        "midsole_foam": src("EnergyFOAM (EVA)", "manufacturer", SS),
        "plate": src("none", "manufacturer", SS),
        "lug_depth_mm": src(4, "manufacturer", SS),
        "flexibility_longitudinal": {"value": 2.0, "source_type": "athlete"},
        "flexibility_torsional": {"value": 1.5, "source_type": "athlete"},
        "stability_devices": {"value": 2, "source_type": "athlete"},
    }


def block_file(data: dict, body: str = "Notes.") -> str:
    return f"# Fiche\n\n```arc\n{json.dumps(data, ensure_ascii=False)}\n```\n\n{body}\n"


class TestContract(unittest.TestCase):
    def test_public_fixtures_validate_clean(self):
        for data in (kipride(), ultra_glide()):
            self.assertEqual(C.validate(data), ([], []), data["gear_id"])

    def test_brand_vs_lab_gap_is_not_an_outlier(self):
        """6 mm annoncé face à 8,7 mm mesuré : un désaccord légitime, ni erreur ni avertissement."""
        self.assertEqual(C.validate(kipride()), ([], []))

    def test_580g_outlier_is_flagged_unless_acknowledged(self):
        """Le 580 g est dans la plage plausible (100-600 g) : seul l'écart à la valeur retenue le trahit."""
        errors, warnings = C.validate(ultra_glide(outlier=False))
        self.assertEqual(errors, [])
        self.assertTrue(any("alternatives[1]" in w and "aberration" in w for w in warnings), warnings)
        self.assertFalse(any("alternatives[0]" in w for w in warnings), "285 g reste une source normale")
        self.assertEqual(C.validate(ultra_glide(outlier=True)), ([], []))

    def test_provenance_is_required_on_every_value(self):
        data = kipride()
        del data["drop_mm"]["source_type"]
        errors, _ = C.validate(data)
        self.assertTrue(any("drop_mm.source_type" in e for e in errors), errors)
        data = kipride()
        data["drop_mm"] = 8.7                      # un nombre nu, sans provenance
        errors, _ = C.validate(data)
        self.assertTrue(any("drop_mm" in e and "objet" in e for e in errors), errors)

    def test_url_and_retrieved_are_required_for_measured_and_manufacturer(self):
        data = kipride()
        del data["drop_mm"]["url"]
        del data["drop_mm"]["alternatives"][0]["retrieved"]
        errors, _ = C.validate(data)
        self.assertTrue(any("drop_mm.url" in e for e in errors), errors)
        self.assertTrue(any("alternatives[0].retrieved" in e for e in errors), errors)
        data = kipride()
        data["drop_mm"] = {"value": 7, "source_type": "athlete"}      # l'athlète n'a pas d'URL à fournir
        self.assertEqual(C.validate(data), ([], []))

    def test_implausible_values_are_errors(self):
        for field, bad in (("drop_mm", 25), ("drop_mm", -6), ("stack_heel_mm", 70), ("stack_forefoot_mm", -1),
                           ("weight_g", 90), ("weight_g", 650), ("lug_depth_mm", 20)):
            data = ultra_glide()
            data[field] = src(bad, "manufacturer", SS)
            errors, _ = C.validate(data)
            self.assertTrue(any(f"{field}.value" in e and "plage plausible" in e for e in errors),
                            (field, bad, errors))

    def test_bounds_are_inclusive_and_negative_drop_is_allowed(self):
        for field, ok in (("drop_mm", -5), ("drop_mm", 20), ("stack_heel_mm", 60), ("weight_g", 100), ("weight_g", 600)):
            data = ultra_glide()
            data[field] = src(ok, "manufacturer", SS)
            self.assertEqual([e for e in C.validate(data)[0] if "plage" in e], [], (field, ok))

    def test_units_are_si_numbers(self):
        data = ultra_glide()
        data["weight_g"] = src("8.5 oz", "manufacturer", SS)
        self.assertTrue(C.validate(data)[0])

    def test_measured_alternative_beats_a_manufacturer_value(self):
        data = kipride()
        data["drop_mm"] = {**src(6, "manufacturer", RL), "alternatives": [src(8.7, "measured", RT)]}
        errors, _ = C.validate(data)
        self.assertTrue(any("measured" in e and "prime" in e for e in errors), errors)
        data["drop_mm"] = {"value": 6, "source_type": "athlete", "alternatives": [src(8.7, "measured", RT)]}
        self.assertEqual(C.validate(data), ([], []), "l'athlète a le dernier mot")

    def test_minimalist_subscales_domain_and_step(self):
        for field, bad in (("flexibility_longitudinal", 3), ("flexibility_torsional", 1.3),
                           ("stability_devices", 7), ("stability_devices", 1.5)):
            data = kipride()
            data[field] = {"value": bad, "source_type": "athlete"}
            self.assertTrue(C.validate(data)[0], (field, bad))

    def test_softness_needs_its_scale_and_enums_are_closed(self):
        data = ultra_glide()
        data["midsole_softness"] = src(52, "measured", SS)
        self.assertTrue(any("scale" in e for e in C.validate(data)[0]))
        data["midsole_softness"] = src(52, "measured", SS, scale="Asker C")
        self.assertEqual(C.validate(data)[0], [])
        data["plate"] = src("titanium", "manufacturer", SS)
        self.assertTrue(C.validate(data)[0])

    def test_same_source_drop_must_match_the_stacks(self):
        data = ultra_glide()
        data["drop_mm"] = src(9, "manufacturer", SS)          # 41 - 35 = 6
        _, warnings = C.validate(data)
        self.assertTrue(any("incohérent" in w for w in warnings), warnings)

    def test_alternatives_are_type_checked_like_the_retained_value(self):
        data = kipride()
        data["drop_mm"]["alternatives"] = [src("huit", "manufacturer", RL)]
        errors, _ = C.validate(data)
        self.assertTrue(any("drop_mm.alternatives[0].value" in e for e in errors), errors)
        data = kipride()
        data["plate"]["alternatives"] = [src("graphene", "manufacturer", RL)]
        errors, _ = C.validate(data)
        self.assertTrue(any("plate.alternatives[0].value" in e for e in errors), errors)
        data = kipride()
        data["weight_g"]["alternatives"] = [src(-3, "manufacturer", RL)]
        self.assertTrue(C.validate(data)[0])
        data = kipride()
        data["plate"]["alternatives"] = [src("carbon", "manufacturer", RL)]
        self.assertEqual(C.validate(data), ([], []))

    def test_basis_is_for_athlete_values_only_and_is_an_enum(self):
        data = kipride()
        data["drop_mm"] = {"value": 6, "source_type": "athlete", "basis": "manufacturer", "url": RL,
                           "retrieved": DAY, "alternatives": [src(8.7, "measured", RT), src(6, "manufacturer", RL)]}
        self.assertEqual(C.validate(data), ([], []), "l'athlète garde la valeur de la marque")
        data["drop_mm"]["basis"] = "guess"
        self.assertTrue(C.validate(data)[0])
        data = kipride()
        data["drop_mm"]["basis"] = "measured"          # sur une valeur measured : refusé
        self.assertTrue(any("basis" in e for e in C.validate(data)[0]))

    def test_future_retrieved_date_is_a_warning(self):
        data = kipride()
        data["drop_mm"]["retrieved"] = "2999-01-01"
        errors, warnings = C.validate(data)
        self.assertEqual(errors, [])
        self.assertTrue(any("retrieved" in w and "futur" in w for w in warnings), warnings)

    def test_unknown_key_is_reported_and_kind_is_registered(self):
        data = kipride()
        data["dorp_mm"] = src(8, "measured", RT)
        self.assertTrue(any("dorp_mm" in w for w in C.validate(data)[1]))
        self.assertIn("shoe_spec", C.KINDS)
        self.assertEqual(C.KIND_FOLDERS["shoe_spec"], "gear")


class TestSelectValue(unittest.TestCase):
    def test_priority_athlete_then_measured_then_manufacturer(self):
        brand, lab, mine = src(6, "manufacturer", RL), src(8.7, "measured", RT), {"value": 7, "source_type": "athlete"}
        self.assertEqual(SH.select_value([brand, lab])["value"], 8.7)
        self.assertEqual(SH.select_value([lab, brand])["value"], 8.7)
        self.assertEqual(SH.select_value([brand, lab, mine])["value"], 7)

    def test_outlier_and_empty_candidates_are_never_selected(self):
        aberrant = src(580, "measured", BF, outlier=True)
        self.assertEqual(SH.select_value([aberrant, src(240, "manufacturer", SS)])["value"], 240)
        self.assertIsNone(SH.select_value([aberrant]))
        self.assertIsNone(SH.select_value([]), "une valeur introuvable reste absente")

    def test_field_summary_exposes_the_brand_lab_gap(self):
        summary = SH.field_summary(kipride()["drop_mm"])
        self.assertEqual(summary["value"], 8.7)
        self.assertEqual(summary["source_type"], "measured")
        self.assertEqual(summary["spread"]["measured_minus_manufacturer"], 2.7)
        self.assertEqual((summary["spread"]["min"], summary["spread"]["max"]), (6, 8.7))

    def test_athlete_keeping_the_brand_value_keeps_the_gap_and_exposes_the_basis(self):
        entry = {"value": 6, "source_type": "athlete", "basis": "manufacturer", "url": RL, "retrieved": DAY,
                 "alternatives": [src(8.7, "measured", RT), src(6, "manufacturer", RL)]}
        summary = SH.field_summary(entry)
        self.assertEqual((summary["value"], summary["source_type"], summary["basis"]), (6, "athlete", "manufacturer"))
        self.assertEqual(summary["spread"]["measured_minus_manufacturer"], 2.7)

    def test_field_summary_ignores_the_acknowledged_outlier(self):
        summary = SH.field_summary(ultra_glide()["weight_g"])
        self.assertEqual((summary["spread"]["min"], summary["spread"]["max"], summary["spread"]["n"]), (240, 285, 2))
        self.assertEqual(summary["outliers"], 1)
        self.assertEqual(len(summary["alternatives"]), 2, "l'aberration est conservée pour mémoire")


class TestMinimalistIndex(unittest.TestCase):
    """Grille du fichier additionnel 1 d'Esculier et al. 2015 (J Foot Ankle Res 8:42)."""

    def test_weight_bands(self):
        for grams, score in ((100, 5), (124.9, 5), (125, 4), (174.9, 4), (175, 3), (224.9, 3), (225, 2),
                             (274.9, 2), (275, 1), (324.9, 1), (325, 0), (500, 0)):
            self.assertEqual(SH.weight_subscore(grams), score, grams)

    def test_stack_bands(self):
        for mm, score in ((0, 5), (7.9, 5), (8, 4), (13.9, 4), (14, 3), (19.9, 3), (20, 2), (25.9, 2),
                          (26, 1), (31.9, 1), (32, 0), (45, 0)):
            self.assertEqual(SH.stack_subscore(mm), score, mm)

    def test_drop_bands(self):
        for mm, score in ((-3, 5), (0.9, 5), (1, 4), (3.9, 4), (4, 3), (6.9, 3), (7, 2), (9.9, 2),
                          (10, 1), (12.9, 1), (13, 0), (18, 0)):
            self.assertEqual(SH.drop_subscore(mm), score, mm)

    def test_stability_devices(self):
        self.assertEqual([SH.stability_subscore(n) for n in range(7)], [5, 4, 3, 2, 1, 0, 0])

    def test_flexibility_is_the_sum_of_two_halves(self):
        self.assertEqual(SH.flexibility_subscore(2.5, 2.5), 5.0)
        self.assertEqual(SH.flexibility_subscore(0, 0), 0.0)
        self.assertEqual(SH.flexibility_subscore(1.5, 1.0), 2.5)

    def minimal(self, **over) -> dict:
        base = {"weight_g": 100, "stack_heel_mm": 5, "drop_mm": 0, "flexibility_longitudinal": 2.5,
                "flexibility_torsional": 2.5, "stability_devices": 0}
        base.update(over)
        return {k: {"value": v, "source_type": "athlete"} for k, v in base.items()}

    def test_most_minimalist_is_100_and_most_structured_is_0(self):
        top = SH.minimalist_index(self.minimal())
        self.assertEqual((top["available"], top["sum"], top["index_pct"]), (True, 25, 100.0))
        bottom = SH.minimalist_index(self.minimal(weight_g=330, stack_heel_mm=35, drop_mm=13,
                                                  flexibility_longitudinal=0, flexibility_torsional=0,
                                                  stability_devices=6))
        self.assertEqual((bottom["sum"], bottom["index_pct"]), (0, 0.0))

    def test_formula_is_sum_times_four(self):
        out = SH.minimalist_index(ultra_glide())
        # poids 240 -> 2 ; pile 41 -> 0 ; drop 6 -> 3 ; flexibilité 2,0 + 1,5 -> 3,5 ; 2 dispositifs -> 3
        self.assertEqual(out["subscores"], {"weight": 2, "stack_height": 0, "heel_toe_drop": 3,
                                            "flexibility": 3.5, "stability": 3})
        self.assertEqual(out["sum"], 11.5)
        self.assertEqual(out["index_pct"], 46.0)
        self.assertAlmostEqual(out["index_pct"], out["sum"] / SH.MI_MAX_SUM * 100)

    def test_the_retained_value_is_used_so_the_lab_drop_counts(self):
        out = SH.minimalist_index(kipride())
        # poids mesuré 277 -> 1 ; pile 42 -> 0 ; drop MESURÉ 8,7 -> 2 (6 mm de la marque aurait donné 3) ; 1,5 + 1,0 ; 0 dispositif -> 5
        self.assertEqual(out["subscores"]["heel_toe_drop"], 2)
        self.assertEqual(out["index_pct"], 42.0)

    def test_drop_falls_back_to_the_two_stacks(self):
        spec = ultra_glide()
        del spec["drop_mm"]
        out = SH.minimalist_index(spec)
        self.assertTrue(out["available"])
        self.assertEqual(out["inputs"]["drop_mm"]["source_type"], "derived")
        self.assertEqual(out["subscores"]["heel_toe_drop"], 3)

    def test_missing_input_makes_it_unavailable_with_the_reason(self):
        for field, label in (("weight_g", "weight_g"), ("stack_heel_mm", "stack_heel_mm"),
                             ("flexibility_longitudinal", "flexibility_longitudinal"),
                             ("flexibility_torsional", "flexibility_torsional"),
                             ("stability_devices", "stability_devices")):
            spec = ultra_glide()
            del spec[field]
            out = SH.minimalist_index(spec)
            self.assertFalse(out["available"], field)
            self.assertNotIn("index_pct", out)
            self.assertIn(label, out["reason"])
        spec = ultra_glide()
        del spec["drop_mm"], spec["stack_forefoot_mm"]
        self.assertIn("drop_mm", SH.minimalist_index(spec)["reason"])

    def test_no_athlete_scores_means_no_index_for_a_scraped_sheet(self):
        """Les fiches issues du web n'ont ni flexibilité ni stabilité : l'index est dit indisponible, pas deviné."""
        spec = {k: v for k, v in kipride().items()
                if k not in ("flexibility_longitudinal", "flexibility_torsional", "stability_devices")}
        out = SH.minimalist_index(spec)
        self.assertFalse(out["available"])
        self.assertIn("index non calculé", out["reason"])

    def test_out_of_domain_athlete_score_is_not_computed(self):
        spec = ultra_glide()
        spec["flexibility_longitudinal"] = {"value": 4, "source_type": "athlete"}
        out = SH.minimalist_index(spec)
        self.assertFalse(out["available"])

    def test_output_carries_the_assumptions(self):
        for spec in (kipride(), {}):
            out = SH.minimalist_index(spec)
            self.assertEqual(out["assumptions"], list(SH.MI_ASSUMPTIONS))
            self.assertTrue(any("approximation du projet" in a for a in out["assumptions"]))

    def test_weight_reference_size_is_checked_against_us_m9(self):
        for ref in ("US 9", "US M9", "US men's 9", "M9", "us m 9", "9"):
            self.assertTrue(SH.is_us_m9(ref), ref)
        for ref in ("EU 42", "US W8", "US 10", "US M10", "", None, 9):
            self.assertFalse(SH.is_us_m9(ref), ref)
        self.assertNotIn("warnings", SH.minimalist_index(kipride()))          # « US 9 »
        missing = SH.minimalist_index(ultra_glide())                         # aucune pointure de référence
        self.assertTrue(any("absente" in w for w in missing["warnings"]), missing)
        other = kipride()
        other["weight_g"]["reference_size"] = "EU 42"
        self.assertTrue(any("EU 42" in w for w in SH.minimalist_index(other)["warnings"]))
        self.assertNotIn("warnings", SH.minimalist_index({}), "pas de poids, pas d'avertissement de pointure")

    def test_reference_is_cited(self):
        self.assertIn("s13047-015-0094-5", SH.minimalist_index({})["url"])
        self.assertIn("Esculier", SH.minimalist_index({})["reference"])


class TestCliAndIndex(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.write("planning/Runner_Profile.md",
                   "# Profil\n\n### Chaussures\n\n- Kiprun Kipride Max — usage: route — id: kipride-max-1\n"
                   "- Salomon Ultra Glide 3 — usage: trail — id: ultra-glide-3\n"
                   "- Hoka Speedgoat 5 — usage: trail — id: speedgoat\n"
                   "- Nike Pegasus — id: pegasus (retirée)\n")
        self.write("gear/specs/kipride-max-1.md", block_file(kipride()))
        self.write("gear/specs/ultra-glide-3.md", block_file(ultra_glide()))

    def write(self, rel: str, text: str) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cli(self, *extra) -> tuple:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", "2026-10-23", "shoe-specs", *extra])
        return code, buf.getvalue()

    def test_json_report(self):
        code, out = self.cli()
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(report["count"], 2)
        self.assertEqual([s["gear_id"] for s in report["specs"]], ["kipride-max-1", "ultra-glide-3"])
        kip = report["specs"][0]
        self.assertEqual((kip["brand"], kip["model"], kip["version"]), ("Kiprun", "Kipride Max", "v1"))
        drop = kip["fields"]["drop_mm"]
        self.assertEqual((drop["value"], drop["source_type"], drop["url"]), (8.7, "measured", RT))
        self.assertEqual(drop["spread"]["measured_minus_manufacturer"], 2.7)
        self.assertEqual(kip["minimalist_index"]["index_pct"], 42.0)
        self.assertIn("midsole_foam", kip["absent"], "une valeur introuvable reste absente")
        ug = report["specs"][1]
        self.assertEqual(ug["fields"]["weight_g"]["outliers"], 1)
        self.assertEqual(ug["minimalist_index"]["index_pct"], 46.0)
        self.assertEqual([g["gear_id"] for g in report["gear_without_spec"]], ["speedgoat"],
                         "les paires retirées n'ont pas à avoir de fiche")

    def test_duplicate_sheet_for_the_same_pair_is_not_indexed(self):
        self.write("gear/specs/autre.md", block_file(kipride()))
        _, out = self.cli()
        report = json.loads(out)
        self.assertEqual([s["gear_id"] for s in report["specs"]], ["kipride-max-1", "ultra-glide-3"],
                         "une seule fiche par paire")
        self.assertTrue(all(s["source_path"] == f"gear/specs/{s['gear_id']}.md" for s in report["specs"]))
        conn = I.open_db(self.ws, memory=True)
        I.index_workspace(conn, self.ws, "2026-10-23")
        issues = conn.execute("SELECT issues FROM source_file WHERE path = 'gear/specs/autre.md'").fetchone()[0]
        self.assertIn("une seule fiche par paire", issues)

    def test_readme_in_specs_is_not_a_shoe_sheet(self):
        self.assertIsNone(I.classify("gear/specs/README.md"))
        self.assertIsNone(I.classify("gear/specs/readme.md"))
        self.write("gear/specs/README.md", "# Fiches\n\nNotes.\n")
        _, out = self.cli()
        self.assertEqual(json.loads(out)["count"], 2)
        conn = I.open_db(self.ws, memory=True)
        I.index_workspace(conn, self.ws, "2026-10-23")
        kind = conn.execute("SELECT kind FROM source_file WHERE path = 'gear/specs/README.md'").fetchone()
        self.assertTrue(kind is None or kind[0] is None)

    def test_sheet_of_a_pair_missing_from_the_profile_is_flagged(self):
        stray = ultra_glide()
        stray["gear_id"] = "inconnue"
        self.write("gear/specs/inconnue.md", block_file(stray))
        _, out = self.cli()
        report = json.loads(out)
        self.assertEqual(report["unknown_gear"], ["inconnue"])
        by_id = {s["gear_id"]: s for s in report["specs"]}
        self.assertFalse(by_id["inconnue"]["in_profile"])
        self.assertTrue(by_id["kipride-max-1"]["in_profile"])
        _, text = self.cli("--text")
        self.assertIn("ne figure pas dans ### Chaussures", text)

    def test_athlete_basis_and_reference_warning_are_exposed(self):
        spec = kipride()
        spec["drop_mm"] = {"value": 6, "source_type": "athlete", "basis": "manufacturer", "url": RL,
                           "retrieved": DAY, "alternatives": [src(8.7, "measured", RT), src(6, "manufacturer", RL)]}
        self.write("gear/specs/kipride-max-1.md", block_file(spec))
        _, out = self.cli("--gear", "ultra-glide-3")
        ug = json.loads(out)["specs"][0]["minimalist_index"]
        self.assertTrue(ug["warnings"])
        self.assertTrue(ug["assumptions"])
        _, out = self.cli("--gear", "kipride-max-1")
        drop = json.loads(out)["specs"][0]["fields"]["drop_mm"]
        self.assertEqual((drop["basis"], drop["spread"]["measured_minus_manufacturer"]), ("manufacturer", 2.7))
        _, text = self.cli("--gear", "kipride-max-1", "--text")
        self.assertIn("[athlete (fondée sur manufacturer)]", text)

    def test_gear_filter_and_unknown_pair(self):
        code, out = self.cli("--gear", "ultra-glide-3")
        self.assertEqual((code, json.loads(out)["count"]), (0, 1))
        code, out = self.cli("--gear", "speedgoat")
        report = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn("speedgoat", report["error"])
        self.assertEqual([g["gear_id"] for g in report["gear_without_spec"]], ["speedgoat"])

    def test_text_output(self):
        code, out = self.cli("--text")
        self.assertEqual(code, 0)
        self.assertIn("kipride-max-1 — Kiprun Kipride Max v1", out)
        self.assertIn("drop_mm : 8.7 mm [measured]", out)
        self.assertIn("labo - marque = +2.7", out)
        self.assertIn("index minimaliste : 42 %", out)
        self.assertIn("Paires sans fiche : speedgoat", out)

    def test_unavailable_index_is_said_in_text(self):
        spec = kipride()
        del spec["stability_devices"]
        self.write("gear/specs/kipride-max-1.md", block_file(spec))
        _, out = self.cli("--gear", "kipride-max-1", "--text")
        self.assertIn("index minimaliste : indisponible", out)
        self.assertIn("stability_devices", out)

    def test_read_only_and_never_the_real_workspace(self):
        before = sorted(str(p.relative_to(self.ws)) for p in self.ws.rglob("*"))
        self.cli()
        self.assertEqual(sorted(str(p.relative_to(self.ws)) for p in self.ws.rglob("*")), before)

    def test_invalid_sheet_is_not_indexed(self):
        bad = kipride()
        bad["gear_id"] = "kipride-max-2"
        bad["drop_mm"] = src(30, "measured", RT)
        self.write("gear/specs/kipride-max-2.md", block_file(bad))
        _, out = self.cli()
        self.assertEqual([s["gear_id"] for s in json.loads(out)["specs"]], ["kipride-max-1", "ultra-glide-3"])

    def test_classify_and_schema_version(self):
        self.assertEqual(I.classify("gear/specs/kipride-max-1.md"), "shoe_spec")
        self.assertEqual(I.classify("gear/2026-09-24_pegasus-41_inspection.md"), "gear_inspection")
        self.assertIsNone(I.classify("gear/specs/deep/x.md"))
        self.assertGreaterEqual(I.SCHEMA_VERSION, 39, "nouvelle table shoe_spec : SCHEMA_VERSION doit avoir été relevée")
        conn = I.open_db(self.ws, memory=True)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(shoe_spec)")}
        self.assertTrue({"source_path", "gear_id", "brand", "model", "version", "data_json"} <= columns)

    def test_validate_file_checks_name_and_location(self):
        ok, errors, warnings = I.validate_file(self.ws / "gear/specs/kipride-max-1.md")
        self.assertEqual((ok, errors, warnings), (True, [], []))
        wrong = self.write("gear/specs/autre.md", block_file(kipride()))
        _, _, warnings = I.validate_file(wrong)
        self.assertTrue(any("gear_id du nom de fichier" in w for w in warnings), warnings)
        stray = self.write("planning/fiche.md", block_file(copy.deepcopy(kipride())))
        _, _, warnings = I.validate_file(stray)
        self.assertTrue(any("hors du format attendu" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
