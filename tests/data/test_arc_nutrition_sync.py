"""Palier D — `scripts/arc_nutrition_sync.py` : plan de poussée des apports vers Garmin (#167).

Pur calcul : aucun appel Garmin, aucun modèle. Verrouille la correspondance catalogue →
aliment personnalisé, l'idempotence (`garmin_pushed`), la détection de doublon contre le journal
Garmin, le refus de deviner (produit inconnu, calories absentes, heure absente) et la règle de la
source unique par jour.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract  # noqa: E402
import arc_nutrition_sync as N  # noqa: E402

CATALOGUE = """
# Catalogue test

| Produit | Portion | Glucides | Énergie (kcal) |
|---|---|---|---|
| Gel Fixture Test | 1 sachet (40 g) | 32 g | 128 |
| Barre Sans Energie | 1 barre (50 g) | 28 g | |
"""
DAY = "2026-10-02"
ASK = {"mode": "ask", "source": "garmin"}


def _catalogue_file(tmp: Path, text: str = CATALOGUE) -> str:
    path = tmp / "catalogue-produits-test.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _library(name: str, food_id="ffff0000ffff0000ffff0000ffff0000", serving_id="5555aaaa5555aaaa5555aaaa5555aaaa",
             carbs=32):
    return {"customFoods": [{"foodMetaData": {"foodId": food_id, "foodName": name},
                             "nutritionContents": [{"servingId": serving_id, "carbs": str(carbs), "calories": "128"}]}]}


class PlanBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cat = _catalogue_file(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, **kw):
        payload = {"date": DAY, "catalogue_paths": [self.cat], "default_time": "09:30:00", **ASK, **kw}
        return N.build_plan(payload)


class TestAvailability(unittest.TestCase):
    def test_default_is_off_and_invalid_is_off(self):
        self.assertEqual(N.sync_mode({}, warn=False), "off")
        self.assertEqual(N.sync_mode({"nutrition": {"garmin_sync": ""}}, warn=False), "off")
        self.assertEqual(N.sync_mode({"nutrition": {"garmin_sync": "peut-etre"}}, warn=False), "off")
        self.assertEqual(N.sync_mode({"nutrition": {"garmin_sync": " ASK "}}, warn=False), "ask")

    def test_off_disables_the_plan(self):
        out = N.build_plan({"date": DAY, "mode": "off", "source": "garmin", "items": [{"product": "gel"}]})
        self.assertEqual(out["status"], "disabled")
        self.assertEqual(out["reason"], "off")
        self.assertEqual(out["steps"], [])

    def test_intervals_source_is_unavailable_and_says_so(self):
        out = N.build_plan({"date": DAY, "mode": "ask", "source": "intervals", "fluids": [{"ml": 500}]})
        self.assertEqual(out["status"], "disabled")
        self.assertEqual(out["reason"], "source_intervals")
        self.assertIn("intervals", out["message"])

    def test_strava_source_is_unavailable_and_says_so(self):
        out = N.build_plan({"date": DAY, "mode": "ask", "source": "strava", "fluids": [{"ml": 500}]})
        self.assertEqual(out["status"], "disabled")
        self.assertEqual(out["reason"], "source_strava")
        self.assertIn("Strava", out["message"])
        self.assertFalse(N.availability("ask", "strava")["available"])

    def test_config_is_read_when_not_overridden(self):
        out = N.build_plan({"date": DAY}, {"nutrition": {"garmin_sync": "ask"}, "data": {"source": "intervals"}})
        self.assertEqual(out["reason"], "source_intervals")

    def test_bad_date_is_rejected(self):
        with self.assertRaises(N.NutritionSyncError):
            N.build_plan({"date": "demain", **ASK})


class TestReadsAndCatalogueMapping(PlanBase):
    def test_reads_are_requested_before_any_write(self):
        out = self.plan(items=[{"product": "gels", "qty": 2}], fluids=[{"ml": 500}])
        self.assertEqual(out["status"], "reads_needed")
        self.assertEqual(out["steps"], [])
        tools = [r["tool"] for r in out["reads_needed"]]
        self.assertEqual(tools, ["get_custom_foods", "get_nutrition_daily_food_log", "get_hydration_data"])
        self.assertEqual(out["reads_needed"][0]["args"], {"search": "Gel Fixture Test"})

    def test_unknown_catalogue_product_is_created_once_then_logged(self):
        out = self.plan(items=[{"product": "gels", "qty": 2}],
                        garmin_custom_foods={"Gel Fixture Test": "No custom foods found."},
                        garmin_food_log=f"No food log data found for {DAY}.")
        self.assertEqual(out["status"], "ready")
        kinds = [s["kind"] for s in out["steps"]]
        self.assertEqual(kinds, ["create_custom_food", "log_custom_food"])
        create, log = out["steps"]
        self.assertEqual(create["args"], {"food_name": "Gel Fixture Test", "calories": 128.0,
                                          "serving_unit": "G", "number_of_units": 40.0, "carbs": 32.0})
        self.assertNotIn("calories_estimated", create)
        self.assertEqual(log["args"]["serving_qty"], 2.0)
        self.assertEqual(log["args"]["meal_time"], "09:30:00")
        self.assertEqual(log["food_ref"], "Gel Fixture Test")
        self.assertIsNone(log["args"]["food_id"])

    def test_existing_garmin_food_is_reused_never_recreated(self):
        out = self.plan(items=[{"product": "gel", "qty": 1}],
                        garmin_custom_foods={"Gel Fixture Test": json.dumps(_library("Gel Fixture Test"))},
                        garmin_food_log=f"No food log data found for {DAY}.")
        self.assertEqual([s["kind"] for s in out["steps"]], ["log_custom_food"])
        self.assertEqual(out["steps"][0]["args"]["food_id"], "ffff0000ffff0000ffff0000ffff0000")
        self.assertEqual(out["steps"][0]["args"]["serving_id"], "5555aaaa5555aaaa5555aaaa5555aaaa")

    def test_two_items_of_the_same_product_create_it_only_once(self):
        out = self.plan(items=[{"product": "gel", "qty": 1, "time": "09:30"}, {"product": "gel", "qty": 1, "time": "10:30"}],
                        garmin_custom_foods={"Gel Fixture Test": "No custom foods found."},
                        garmin_food_log=f"No food log data found for {DAY}.")
        kinds = [s["kind"] for s in out["steps"]]
        self.assertEqual(kinds.count("create_custom_food"), 1)
        self.assertEqual(kinds.count("log_custom_food"), 2)

    def test_library_food_with_other_carbs_asks_instead_of_reusing(self):
        out = self.plan(items=[{"product": "gel", "qty": 1}],
                        garmin_custom_foods={"Gel Fixture Test": _library("Gel Fixture Test", carbs=10)},
                        garmin_food_log=f"No food log data found for {DAY}.")
        self.assertEqual(out["steps"], [])
        self.assertEqual(out["needs_input"][0]["what"], "garmin_food_mismatch")

    def test_two_garmin_foods_with_the_same_name_are_ambiguous(self):
        lib = _library("Gel Fixture Test")
        lib["customFoods"].append(_library("Gel Fixture Test", food_id="aaaa", serving_id="bbbb")["customFoods"][0])
        out = self.plan(items=[{"product": "gel"}], garmin_custom_foods={"Gel Fixture Test": lib},
                        garmin_food_log=f"No food log data found for {DAY}.")
        self.assertEqual(out["needs_input"][0]["what"], "garmin_food")
        self.assertEqual(out["steps"], [])


class TestNeverGuess(PlanBase):
    def reads(self, name):
        return {"garmin_custom_foods": {name: "No custom foods found."}, "garmin_food_log": f"No food log data found for {DAY}."}

    def test_unknown_product_asks_and_pushes_nothing(self):
        out = self.plan(items=[{"product": "super gel inconnu", "qty": 1}], garmin_food_log=f"No food log data found for {DAY}.")
        self.assertEqual(out["status"], "needs_input")
        self.assertEqual(out["needs_input"][0]["what"], "product")
        self.assertEqual(out["steps"], [])

    def test_missing_calories_asks_unless_athlete_accepted_the_estimate(self):
        out = self.plan(items=[{"product": "Barre Sans Energie"}], **self.reads("Barre Sans Energie"))
        self.assertEqual(out["status"], "needs_input")
        self.assertEqual(out["needs_input"][0]["what"], "calories")
        out = self.plan(items=[{"product": "Barre Sans Energie"}], estimate_kcal_from_carbs=True,
                        **self.reads("Barre Sans Energie"))
        create = out["steps"][0]
        self.assertEqual(create["args"]["calories"], 112.0)
        self.assertTrue(create["calories_estimated"])

    def test_missing_time_asks(self):
        out = N.build_plan({"date": DAY, "catalogue_paths": [self.cat], **ASK, "items": [{"product": "gel"}],
                            "garmin_custom_foods": {"Gel Fixture Test": "No custom foods found."},
                            "garmin_food_log": "No food log data found for x."})
        self.assertEqual(out["needs_input"][0]["what"], "meal_time")
        self.assertEqual(out["steps"], [])

    def test_garmin_read_error_blocks_every_write(self):
        out = self.plan(items=[{"product": "gel"}], garmin_food_log="Error retrieving food log data: 401")
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["steps"], [])

    def test_hydration_bounds(self):
        out = self.plan(fluids=[{"ml": 50000}, {"ml": 0}], garmin_hydration="No hydration data found for x")
        self.assertEqual([n["what"] for n in out["needs_input"]], ["hydration", "hydration"])
        self.assertEqual(out["steps"], [])


class TestIdempotence(PlanBase):
    def first_plan(self):
        return self.plan(items=[{"product": "gels", "qty": 2}], fluids=[{"ml": 500}],
                         garmin_custom_foods={"Gel Fixture Test": _library("Gel Fixture Test")},
                         garmin_food_log=f"No food log data found for {DAY}.",
                         garmin_hydration="No hydration data found for x")

    def test_rerun_with_recorded_keys_pushes_nothing(self):
        first = self.first_plan()
        self.assertEqual([s["kind"] for s in first["steps"]], ["log_custom_food", "add_hydration_data"])
        recorded = N.record_pushed({"executed": [{"key": s["key"], "kind": s["kind"], "name": s.get("name")} for s in first["steps"]],
                                    "now": "2026-10-02T10:00:00+02:00"})["garmin_pushed"]
        second = self.plan(items=[{"product": "gels", "qty": 2}], fluids=[{"ml": 500}], already_pushed=recorded,
                           garmin_custom_foods={"Gel Fixture Test": _library("Gel Fixture Test")},
                           garmin_food_log=f"No food log data found for {DAY}.",
                           garmin_hydration="No hydration data found for x")
        self.assertEqual(second["status"], "nothing_to_push")
        self.assertEqual({s["reason"] for s in second["skipped"]}, {"already_pushed"})
        self.assertEqual(len(second["skipped"]), 2)

    def test_keys_are_stable_and_distinguish_time_and_quantity(self):
        a = self.first_plan()["steps"][0]["key"]
        self.assertEqual(a, self.first_plan()["steps"][0]["key"])
        other = self.plan(items=[{"product": "gels", "qty": 3}], garmin_custom_foods={"Gel Fixture Test": _library("Gel Fixture Test")},
                          garmin_food_log=f"No food log data found for {DAY}.")
        self.assertNotEqual(a, other["steps"][0]["key"])

    def test_entry_in_garmin_log_without_push_trace_asks_then_passes_when_confirmed(self):
        log = {"mealDetails": [{"mealName": "SNACKS", "loggedFoods": [
            {"logId": "l1", "foodMetaData": {"foodId": "ffff0000ffff0000ffff0000ffff0000", "foodName": "Gel Fixture Test"}}]}]}
        kw = dict(items=[{"product": "gel"}], garmin_custom_foods={"Gel Fixture Test": _library("Gel Fixture Test")},
                  garmin_food_log=json.dumps(log))
        out = self.plan(**kw)
        self.assertEqual(out["steps"], [])
        self.assertEqual(out["confirm_duplicates"][0]["log_ids"], ["l1"])
        key = out["confirm_duplicates"][0]["key"]
        out = self.plan(confirm_keys=[key], **kw)
        self.assertEqual([s["kind"] for s in out["steps"]], ["log_custom_food"])

    def test_quick_add_same_name_in_garmin_log_is_a_duplicate(self):
        log = {"mealDetails": [{"loggedFoods": [{"logId": "q1", "foodMetaData": {"foodName": "Diner"}}]}]}
        out = self.plan(quick_adds=[{"name": "Dîner", "calories": 800, "carbs_g": 100, "protein_g": 30, "fat_g": 25,
                                     "time": "20:00"}], garmin_food_log=json.dumps(log))
        self.assertEqual(out["steps"], [])
        self.assertEqual(out["confirm_duplicates"][0]["log_ids"], ["q1"])

    def test_quick_add_builds_a_log_food_step(self):
        out = self.plan(quick_adds=[{"name": "Dîner", "calories": 800, "carbs_g": 100, "protein_g": 30, "fat_g": 25,
                                     "time": "20:00"}], garmin_food_log="No food log data found for x.")
        self.assertEqual(out["steps"][0]["kind"], "log_food")
        self.assertEqual(out["steps"][0]["args"], {"meal_date": DAY, "meal_time": "20:00:00", "name": "Dîner",
                                                   "calories": 800.0, "carbs": 100.0, "protein": 30.0, "fat": 25.0})

    def test_hydration_step_shape_and_garmin_total(self):
        out = self.plan(fluids=[{"ml": 500, "time": "09:30:00"}], garmin_hydration={"valueInML": 1200})
        self.assertEqual(out["steps"][0]["args"], {"value_in_ml": 500, "cdate": DAY, "timestamp": f"{DAY}T09:30:00.000"})
        self.assertEqual(out["garmin_hydration_ml_today"], 1200.0)


class TestSingleSourceOfTruth(PlanBase):
    def test_day_imported_from_garmin_is_never_pushed(self):
        out = self.plan(items=[{"product": "gel"}], day_source="garmin")
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["reason"], "day_source_garmin")

    def test_import_refused_on_a_mirrored_day(self):
        out = N.import_log({"date": DAY, "garmin_food_log": {"mealDetails": []},
                            "already_pushed": [{"key": "abc", "kind": "log_food"}]})
        self.assertEqual(out["status"], "refused")
        self.assertEqual(out["reason"], "mirror_day")

    def test_import_reads_totals_only_when_present(self):
        data = {"dailyNutritionContent": {"calories": 2400, "carbs": 310, "protein": 110, "fat": 70},
                "mealDetails": [{"loggedFoods": [{"logId": "1", "foodMetaData": {"foodName": "Pâtes"}}]}]}
        out = N.import_log({"date": DAY, "garmin_food_log": json.dumps(data)})
        self.assertEqual(out["intake_source"], "garmin")
        self.assertEqual(out["intake"], {"intake_kcal": 2400.0, "carbs_g": 310.0, "protein_g": 110.0, "fat_g": 70.0})
        bare = N.import_log({"date": DAY, "garmin_food_log": {"mealDetails": []}})
        self.assertNotIn("intake", bare)
        self.assertTrue(bare["warnings"])
        self.assertEqual(N.import_log({"date": DAY, "garmin_food_log": "No food log data found for x."})["status"], "empty")


class TestRecordAndContract(unittest.TestCase):
    def test_record_attaches_log_id_only_when_unambiguous_and_merges_without_duplicates(self):
        before = {"mealDetails": [{"loggedFoods": [{"logId": "old", "foodMetaData": {"foodId": "F", "foodName": "Gel"}}]}]}
        after = {"mealDetails": [{"loggedFoods": [{"logId": "old", "foodMetaData": {"foodId": "F", "foodName": "Gel"}},
                                                   {"logId": "new", "foodMetaData": {"foodId": "F", "foodName": "Gel"}}]}]}
        ex = [{"key": "k1", "kind": "log_custom_food", "name": "Gel", "qty": 2, "food_id": "F"}]
        out = N.record_pushed({"executed": ex, "food_log_before": before, "food_log_after": after, "now": "2026-10-02T10:00:00+02:00"})
        self.assertEqual(out["garmin_pushed"][0]["log_id"], "new")
        again = N.record_pushed({"executed": ex, "existing_garmin_pushed": out["garmin_pushed"]})
        self.assertEqual(len(again["garmin_pushed"]), 1)
        self.assertEqual(again["added"], [])

    def test_record_omits_log_id_when_two_new_entries_match(self):
        after = {"mealDetails": [{"loggedFoods": [{"logId": "a", "foodMetaData": {"foodId": "F"}},
                                                   {"logId": "b", "foodMetaData": {"foodId": "F"}}]}]}
        out = N.record_pushed({"executed": [{"key": "k", "kind": "log_custom_food", "food_id": "F"}], "food_log_after": after})
        self.assertNotIn("log_id", out["garmin_pushed"][0])

    def test_garmin_pushed_validates_against_the_contract(self):
        pushed = [{"key": "ab12cd34ef56", "kind": "log_custom_food", "name": "Gel", "qty": 2, "food_id": "F",
                   "log_id": "L", "at": "2026-10-02T10:00:00+02:00"}]
        for kind, extra in (("nutrition", {"intake_source": "manual"}), ("activity", {"sport": "trail", "duration_s": 5400})):
            block = {"arc": 1, "kind": kind, "date": DAY, "garmin_pushed": pushed, **extra}
            errors, _ = arc_contract.validate(block)
            self.assertEqual(errors, [], kind)
        bad = {"arc": 1, "kind": "nutrition", "date": DAY, "garmin_pushed": [{"key": "k", "kind": "delete_food_log"}],
               "intake_source": "garmin"}
        self.assertTrue(arc_contract.validate(bad)[0])


class TestCliReadsLiveConfig(unittest.TestCase):
    """La CLI ignore `mode`/`source` de l'entrée JSON : seule la configuration vivante active la poussée."""

    def run_cli(self, workspace: Path, payload: dict) -> dict:
        import contextlib
        import io
        src = workspace / "in.json"
        src.write_text(json.dumps(payload), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(N.main(["plan", "--workspace", str(workspace), "--input", str(src)]), 0)
        return json.loads(buf.getvalue())

    def test_payload_cannot_enable_the_push_when_config_is_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_cli(Path(tmp), {"date": DAY, "mode": "ask", "source": "garmin", "fluids": [{"ml": 500}]})
            self.assertEqual(out["status"], "disabled")
            self.assertEqual(out["reason"], "off")

    def test_live_config_ask_enables_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "config").mkdir()
            (ws / "config/workspace.user.toml").write_text('[nutrition]\ngarmin_sync = "ask"\n', encoding="utf-8")
            out = self.run_cli(ws, {"date": DAY, "mode": "off", "fluids": [{"ml": 500, "time": "09:30"}],
                                    "garmin_hydration": "No hydration data found for x"})
            self.assertEqual(out["status"], "ready")


class TestHydrationIntegerVolume(PlanBase):
    def test_fractional_volume_is_rounded_to_an_integer_ml(self):
        out = self.plan(fluids=[{"ml": 250.6, "time": "09:30:00"}], garmin_hydration={"valueInML": 0})
        self.assertEqual(out["steps"][0]["args"]["value_in_ml"], 251)
        self.assertIsInstance(out["steps"][0]["args"]["value_in_ml"], int)


class TestCatalogueParsing(unittest.TestCase):
    def test_rows_carry_portion_and_optional_energy(self):
        rows = N.parse_catalogue_rows(CATALOGUE)
        gel = next(r for r in rows if r["name"] == "Gel Fixture Test")
        self.assertEqual((gel["serving_size"], gel["serving_unit"], gel["carbs_g"], gel["kcal"]), (40.0, "G", 32.0, 128.0))
        self.assertNotIn("kcal", next(r for r in rows if r["name"] == "Barre Sans Energie"))


if __name__ == "__main__":
    unittest.main()
