"""Palier D — contrat `shoe_recommendation` (#302, épopée #297) : champs obligatoires, énumérations,
accord de l'athlète, chemin de continuité, provenance des caractéristiques des candidats (même règles que
`shoe_spec` : url/retrieved, bornes, mesure > marque, aberrations), veto médical, nom de fichier, et
comportement de l'indexeur (fichier reconnu, validé, sans table, sans dette de backfill).

Fixtures SYNTHÉTIQUES (marques et modèles fictifs) ; workspaces temporaires passés en `--workspace`.
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

DAY = "2026-10-23"
LAB = "https://example.org/lab/modele-a"
BRAND = "https://example.org/marque/modele-a"


def prov(value, source_type="measured", url=LAB, **extra):
    d = {"value": value, "source_type": source_type, "url": url, "retrieved": DAY}
    d.update(extra)
    return d


def candidate(**extra) -> dict:
    c = {
        "brand": "Marque A", "model": "Modèle A", "version": "2",
        "specs": {
            "drop_mm": {**prov(6.5), "alternatives": [prov(5, "manufacturer", BRAND)]},
            "stack_heel_mm": prov(38, "manufacturer", BRAND),
            "weight_g": prov(255),
            "toe_box": prov("wide", "manufacturer", BRAND),
        },
        "fits": ["drop_mm dans la plage 4-8 (continuity_drop)"],
        "misses": [],
    }
    c.update(extra)
    return c


def reco(**extra) -> dict:
    d = {
        "arc": 1, "kind": "shoe_recommendation", "date": DAY, "role": "trail_long", "path": "search",
        "replaced_gear_id": "trail-a",
        "targets": {"ranges": {"drop_mm": {"min": 4, "max": 8, "rules": ["continuity_drop"], "confidence": "moderate"}},
                    "rule_ids": ["continuity_drop", "softness_not_firm"], "insufficient_data": False},
        "candidates": [candidate(), candidate(model="Modèle B", version="1")],
        "medical_veto": {"status": "clear", "reviewer": "coach"},
        "athlete_validated": True,
    }
    d.update(extra)
    return d


def block_file(data: dict) -> str:
    return f"# Recommandation\n\n```arc\n{json.dumps(data, ensure_ascii=False)}\n```\n\nTableau montré à l'athlète.\n"


class TestContract(unittest.TestCase):
    def test_valid_recommendation_has_no_error_nor_warning(self):
        self.assertEqual(C.validate(reco()), ([], []))

    def test_continuity_path_valid_and_requires_the_replaced_pair(self):
        ok = reco(path="continuity", candidates=[candidate()])
        self.assertEqual(C.validate(ok), ([], []))
        bad = copy.deepcopy(ok)
        del bad["replaced_gear_id"]
        errors, _ = C.validate(bad)
        self.assertTrue(any("replaced_gear_id" in e and "continuity" in e for e in errors), errors)
        # chemin « search » sans paire remplacée (premier achat) : permis
        search = copy.deepcopy(reco())
        del search["replaced_gear_id"]
        self.assertEqual(C.validate(search), ([], []))

    def test_required_keys(self):
        for key in ("date", "role", "path", "candidates", "athlete_validated"):
            bad = reco()
            del bad[key]
            errors, _ = C.validate(bad)
            self.assertTrue(any(key in e for e in errors), (key, errors))

    def test_enums(self):
        for key, value in (("role", "marathon"), ("path", "buy"), ("replaced_gear_id", "Pas Un Slug")):
            errors, _ = C.validate(reco(**{key: value}))
            self.assertTrue(any(key in e for e in errors), (key, errors))
        for role in C.SHOE_ROLE:
            self.assertEqual(C.validate(reco(role=role)), ([], []), role)

    def test_roles_match_the_needs_engine_vocabulary(self):
        import arc_shoe_needs as SN
        self.assertEqual(set(C.SHOE_ROLE), set(SN.ROLES))

    def test_athlete_validation_is_mandatory(self):
        errors, _ = C.validate(reco(athlete_validated=False))
        self.assertTrue(any("athlete_validated" in e for e in errors), errors)

    def test_no_candidate_is_an_error_and_too_many_a_warning(self):
        errors, _ = C.validate(reco(candidates=[]))
        self.assertTrue(any("au moins un candidat" in e for e in errors), errors)
        errors, warnings = C.validate(reco(candidates=[candidate(model=f"M{i}") for i in range(6)]))
        self.assertEqual(errors, [])
        self.assertTrue(any("6 candidats" in w for w in warnings), warnings)

    def test_candidate_needs_brand_and_model(self):
        for key in ("brand", "model"):
            c = candidate()
            del c[key]
            errors, _ = C.validate(reco(candidates=[c]))
            self.assertTrue(any(key in e for e in errors), (key, errors))

    def test_spec_provenance_is_mandatory(self):
        c = candidate()
        del c["specs"]["weight_g"]["url"]
        errors, _ = C.validate(reco(candidates=[c]))
        self.assertTrue(any("candidates[0].specs.weight_g.url" in e for e in errors), errors)
        c = candidate()
        del c["specs"]["drop_mm"]["retrieved"]
        errors, _ = C.validate(reco(candidates=[c]))
        self.assertTrue(any("drop_mm.retrieved" in e for e in errors), errors)

    def test_athlete_valued_spec_needs_no_url(self):
        c = candidate()
        c["specs"]["stability_devices"] = {"value": 1, "source_type": "athlete"}
        self.assertEqual(C.validate(reco(candidates=[c])), ([], []))

    def test_unknown_spec_field_and_bad_source_type_are_refused(self):
        c = candidate()
        c["specs"]["price_eur"] = {"value": 150, "source_type": "manufacturer", "url": BRAND, "retrieved": DAY}
        errors, _ = C.validate(reco(candidates=[c]))
        self.assertTrue(any("price_eur" in e and "inconnue" in e for e in errors), errors)
        c = candidate()
        c["specs"]["drop_mm"]["source_type"] = "reseller"
        errors, _ = C.validate(reco(candidates=[c]))
        self.assertTrue(any("drop_mm.source_type" in e for e in errors), errors)

    def test_implausible_value_is_an_error(self):
        c = candidate()
        c["specs"]["weight_g"] = prov(2550)
        errors, _ = C.validate(reco(candidates=[c]))
        self.assertTrue(any("weight_g.value" in e and "plage plausible" in e for e in errors), errors)

    def test_measurement_beats_manufacturer(self):
        c = candidate()
        c["specs"]["drop_mm"] = {**prov(5, "manufacturer", BRAND), "alternatives": [prov(6.5)]}
        errors, _ = C.validate(reco(candidates=[c]))
        self.assertTrue(any("measured" in e and "prime" in e for e in errors), errors)

    def test_outlier_alternative_warns_unless_marked(self):
        c = candidate()
        c["specs"]["weight_g"] = {**prov(255), "alternatives": [prov(580, "manufacturer", BRAND)]}
        errors, warnings = C.validate(reco(candidates=[c]))
        self.assertEqual(errors, [])
        self.assertTrue(any("aberration" in w for w in warnings), warnings)
        c["specs"]["weight_g"]["alternatives"][0]["outlier"] = True
        self.assertEqual(C.validate(reco(candidates=[c])), ([], []))

    def test_fits_and_misses_are_non_empty_strings(self):
        errors, _ = C.validate(reco(candidates=[candidate(fits=[""], misses=[3])]))
        self.assertTrue(any("fits[0]" in e for e in errors), errors)
        self.assertTrue(any("misses[0]" in e for e in errors), errors)

    def test_targets_rule_ids_are_strings(self):
        errors, _ = C.validate(reco(targets={"rule_ids": ["continuity_drop", 3]}))
        self.assertTrue(any("rule_ids[1]" in e for e in errors), errors)

    def test_medical_veto(self):
        veto = {"status": "veto", "reviewer": "medical", "reason": "antécédent d'Achille : drop jamais abaissé"}
        c = candidate(vetoed=True)
        self.assertEqual(C.validate(reco(medical_veto=veto, candidates=[candidate(), c])), ([], []))
        errors, _ = C.validate(reco(medical_veto={"status": "veto", "reviewer": "medical"}))
        self.assertTrue(any("reason" in e for e in errors), errors)
        errors, _ = C.validate(reco(medical_veto={"status": "block", "reviewer": "medical"}))
        self.assertTrue(any("medical_veto.status" in e for e in errors), errors)
        errors, _ = C.validate(reco(medical_veto={"status": "clear", "reviewer": "nutritionist"}))
        self.assertTrue(any("medical_veto.reviewer" in e for e in errors), errors)
        _, warnings = C.validate(reco(medical_veto=veto))
        self.assertTrue(any("vetoed" in w for w in warnings), warnings)

    def test_contract_has_no_purchase_key(self):
        keys = set(C.SCHEMA["shoe_recommendation"]["required"]) | set(C.SCHEMA["shoe_recommendation"]["optional"])
        for sub in ("shoe_candidate", "shoe_reco_targets", "shoe_medical_veto"):
            keys |= set(C.SUBSCHEMA[sub]["required"]) | set(C.SUBSCHEMA[sub]["optional"])
        for forbidden in ("price", "price_eur", "url_buy", "affiliate", "buy_url", "purchase"):
            self.assertNotIn(forbidden, keys)

    def test_kind_is_registered(self):
        self.assertIn("shoe_recommendation", C.KINDS)
        self.assertEqual(C.KIND_FOLDERS["shoe_recommendation"], "gear")


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)

    def write(self, rel: str, text: str) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestFileAndIndex(Workspace):
    def test_classify(self):
        self.assertEqual(I.classify("gear/2026-10-23_shoe_recommendation_trail_long.md"), "shoe_recommendation")
        self.assertIsNone(I.classify("gear/photos/2026-10-23_shoe_recommendation_trail_long.md"))
        self.assertIsNone(I.classify("gear/2026-10-23_shoe_recommendation_Trail Long.md"))
        self.assertEqual(I.classify("gear/2026-10-23_ug3_inspection.md"), "gear_inspection")

    def test_validate_file_clean(self):
        path = self.write("gear/2026-10-23_shoe_recommendation_trail_long.md", block_file(reco()))
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertEqual(warnings, [])

    def test_validate_file_warns_on_name_mismatch(self):
        path = self.write("gear/2026-10-22_shoe_recommendation_road_easy.md", block_file(reco()))
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertTrue(any("date du nom de fichier" in w for w in warnings), warnings)
        self.assertTrue(any("rôle du nom de fichier" in w for w in warnings), warnings)
        path = self.write("gear/recommandation.md", block_file(reco()))
        ok, _, warnings = I.validate_file(path)
        self.assertTrue(ok)
        self.assertTrue(any("hors du format attendu" in w for w in warnings), warnings)

    def test_validate_file_refuses_unvalidated_recommendation(self):
        path = self.write("gear/2026-10-23_shoe_recommendation_trail_long.md",
                          block_file(reco(athlete_validated=False)))
        ok, errors, _ = I.validate_file(path)
        self.assertFalse(ok)
        self.assertTrue(any("athlete_validated" in e for e in errors), errors)

    def test_indexer_recognises_the_file_and_leaves_no_backfill_debt(self):
        self.write("gear/2026-10-23_shoe_recommendation_trail_long.md", block_file(reco()))
        self.write("gear/2026-10-24_shoe_recommendation_trail.md", block_file(reco(date="2026-10-24", role="trail")))
        conn = I.open_db(self.ws, memory=True)
        I.index_workspace(conn, self.ws, today=DAY)
        rows = conn.execute("SELECT path, kind, parsed_ok FROM source_file ORDER BY path").fetchall()
        self.assertEqual([(r["kind"], r["parsed_ok"]) for r in rows], [("shoe_recommendation", "ok")] * 2)
        self.assertEqual(I.backfill_items(conn), [])

    def test_invalid_recommendation_is_a_debt_not_a_phantom_row(self):
        self.write("gear/2026-10-23_shoe_recommendation_trail_long.md", block_file(reco(candidates=[])))
        conn = I.open_db(self.ws, memory=True)
        I.index_workspace(conn, self.ws, today=DAY)
        row = conn.execute("SELECT kind, parsed_ok FROM source_file").fetchone()
        self.assertEqual(row["kind"], "shoe_recommendation")
        self.assertNotEqual(row["parsed_ok"], "ok")

    def test_cli_validate_command_accepts_the_file(self):
        path = self.write("gear/2026-10-23_shoe_recommendation_trail_long.md", block_file(reco()))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--validate", str(path)])
        self.assertEqual(code, 0, buf.getvalue())


class TestRealUpstreamOutputRoundTrip(Workspace):
    """Un fichier bâti à partir de la VRAIE sortie de `shoe-needs` (sur un workspace indexé) se valide."""

    def test_targets_copied_from_shoe_needs_validate(self):
        profile = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n- Trail A — usage: trail — id: trail-a\n")
        self.write("planning/Runner_Profile.md", profile)
        spec = {"arc": 1, "kind": "shoe_spec", "date": DAY, "gear_id": "trail-a", "brand": "Marque-Test",
                "model": "Modèle-Test", "drop_mm": prov(8.0), "stack_heel_mm": prov(34.0),
                "verdict": {"date": DAY, "comfort_overall": 8, "would_rebuy": "yes_with_change",
                            "change_wanted": ["wider_toe_box"]}}
        self.write("gear/specs/trail-a.md", block_file(spec))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", DAY, "shoe-needs",
                           "--role", "trail_long", "--replace", "trail-a"])
        self.assertEqual(code, 0)
        needs = json.loads(buf.getvalue())
        ranges = {f: {k: v for k, v in t.items() if k in ("min", "max", "allowed", "rules", "confidence")}
                  for f, t in needs["targets"].items()}
        rule_ids = [r["id"] for r in needs["rules_applied"]]
        data = reco(role=needs["role"], replaced_gear_id=needs["replace"],
                    targets={"ranges": ranges, "rule_ids": rule_ids, "insufficient_data": needs["insufficient_data"]})
        self.assertEqual(C.validate(data), ([], []))
        self.assertIn("continuity_drop", rule_ids)
        path = self.write(f"gear/{DAY}_shoe_recommendation_trail_long.md", block_file(data))
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
