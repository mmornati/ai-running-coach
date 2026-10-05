"""Palier D — modèle du roadbook imprimable (#187, épopée #170) : `scripts/arc_roadbook.py`.

Le plan de départ sort du VRAI `arc_race_pacing.build_race_plan` (voir `tests/lib/roadbook_plan.py`) ;
chaque test vise un défaut précis : cohérence des sections avec les passages du plan, marges de
barrière, drapeaux de nuit, honnêteté quand une donnée manque (rien d'inventé, tout listé dans
`missing`), et validité du bloc `arc` avec les nouvelles clés optionnelles.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_contract as C  # noqa: E402
import arc_race_pacing as RP  # noqa: E402
import arc_roadbook as RB  # noqa: E402
from tests.lib import roadbook_plan as R  # noqa: E402

SCEN = RP.SCENARIOS


def _model(**over):
    return RB.build_roadbook(R.persisted_plan(**over), plan_path="planning/plan.md")


class TestRoadbookSections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = R.persisted_plan()
        cls.model = RB.build_roadbook(cls.plan, plan_path="planning/plan.md")

    def test_three_scenarios_with_contiguous_sections(self):
        for s in SCEN:
            sc = self.model["scenarios"][s]
            self.assertTrue(sc["available"])
            secs = sc["sections"]
            self.assertEqual([r["from_name"] for r in secs], ["Départ", "Ravito du Col", "Base de vie"])
            self.assertEqual(secs[-1]["to_name"], "Arrivée")
            for a, b in zip(secs, secs[1:]):
                self.assertEqual(a["to_km"], b["from_km"])

    def test_totals_and_elevation_add_up(self):
        h = self.model["header"]
        secs = self.model["scenarios"]["realistic"]["sections"]
        self.assertAlmostEqual(sum(r["distance_m"] for r in secs), h["distance_m"], delta=5.0)
        self.assertAlmostEqual(sum(r["gain_m"] for r in secs), h["elevation_gain_m"], delta=1.0)
        self.assertAlmostEqual(sum(r["loss_m"] for r in secs), h["elevation_loss_m"], delta=1.0)

    def test_passage_times_are_the_plans_own(self):
        passages = RP.compute_passages(self.plan["segments"], self.plan["aid_stations"])
        for s in SCEN:
            secs = self.model["scenarios"][s]["sections"]
            self.assertEqual(secs[0]["arrival_s"], passages["aid_station_passages"][0][s])
            self.assertEqual(secs[1]["arrival_s"], passages["aid_station_passages"][1][s])
            self.assertEqual(secs[-1]["arrival_s"], passages["totals_s"][s])
            self.assertEqual(self.model["scenarios"][s]["total_s"], passages["totals_s"][s])

    def test_clock_times_follow_the_start_and_roll_over_midnight(self):
        secs = self.model["scenarios"]["realistic"]["sections"]
        self.assertEqual(secs[0]["arrival_clock"], "17:54")
        self.assertEqual(secs[0]["departure_clock"], "17:55")
        self.assertTrue(secs[-1]["arrival_clock"].endswith("(J+1)"))
        self.assertEqual(self.model["header"]["start_clock"], "16:00")

    def test_scenarios_are_ordered(self):
        t = {s: self.model["scenarios"][s]["total_s"] for s in SCEN}
        self.assertGreaterEqual(t["safe"], t["realistic"])
        self.assertGreaterEqual(t["realistic"], t["ambitious"])

    def test_cutoff_margin_and_status(self):
        first = self.model["scenarios"]["realistic"]["sections"][0]
        # barrière « +02:10 » = 7800 s, passage à 6840 s : 960 s de marge, sous les 30 min de confort
        self.assertEqual(first["cutoff"]["margin_s"], 7800 - first["arrival_s"])
        self.assertEqual(first["cutoff"]["status"], "tendu")
        second = self.model["scenarios"]["realistic"]["sections"][1]
        self.assertEqual(second["cutoff"]["status"], "ok")
        self.assertNotIn("cutoff", self.model["scenarios"]["realistic"]["sections"][2])

    def test_aid_station_take_and_services_are_carried(self):
        st = self.model["scenarios"]["realistic"]["sections"][0]["station"]
        self.assertEqual(st["take"], ["2 gels", "500 ml de boisson d'effort"])
        self.assertEqual(st["services"], ["eau", "coca", "soupe"])
        self.assertEqual(self.model["scenarios"]["realistic"]["sections"][1]["stop_s"], 300)

    def test_night_flags_and_spans(self):
        sc = self.model["scenarios"]["realistic"]
        self.assertEqual([r.get("night") for r in sc["sections"]], ["partial", "full", "full"])
        self.assertEqual(sc["lamp_sections"], 3)
        self.assertTrue(sc["night_spans_km"])
        # plus on part tard dans la nuit, plus le scénario lent passe de km de nuit : la nuit débute plus tôt (km)
        self.assertLess(self.model["scenarios"]["safe"]["night_spans_km"][0][0],
                        self.model["scenarios"]["ambitious"]["night_spans_km"][0][0])

    def test_profile_is_relative_and_marks_the_aid_stations(self):
        prof = self.model["profile"]
        self.assertTrue(prof["relative"])
        self.assertEqual(prof["points"][0], [0.0, 0.0])
        self.assertAlmostEqual(prof["points"][-1][1], self.model["header"]["elevation_gain_m"]
                               - self.model["header"]["elevation_loss_m"], delta=1.0)
        self.assertEqual([m["name"] for m in prof["aid_stations"]], ["Ravito du Col", "Base de vie"])

    def test_nothing_missing_for_a_complete_plan(self):
        self.assertEqual(self.model["missing"], [])
        self.assertEqual(self.model["warnings"], [])
        self.assertEqual(self.model["emergency"], self.plan["emergency"])
        self.assertEqual(self.model["notes"], self.plan["notes"])

    def test_header_target_from_the_plan(self):
        self.assertEqual(self.model["header"]["target_time_s"], self.plan["target_time_s"])
        self.assertEqual(self.model["scenarios"]["realistic"]["target_s"], self.plan["scenarios"]["realistic"])


class TestRoadbookHonesty(unittest.TestCase):
    def test_no_start_time_means_no_clock_times_and_says_so(self):
        plan = R.persisted_plan()
        del plan["start_time"]
        model = RB.build_roadbook(plan)
        secs = model["scenarios"]["realistic"]["sections"]
        self.assertTrue(all("arrival_clock" not in r for r in secs))
        self.assertTrue(all("margin_s" not in r.get("cutoff", {}) for r in secs))
        self.assertTrue(any("heure de départ" in m for m in model["missing"]))
        self.assertTrue(any("marges non calculées" in m for m in model["missing"]))
        self.assertNotIn("finish_clock", model["scenarios"]["realistic"])

    def test_hhmm_start_is_combined_with_the_race_date(self):
        model = _model(start_time="16:00")
        self.assertEqual(model["scenarios"]["realistic"]["sections"][0]["arrival_clock"], "17:54")

    def test_plan_without_segments_has_no_timed_sections(self):
        model = _model(segments=[])
        self.assertTrue(all(not model["scenarios"][s]["available"] for s in SCEN))
        self.assertIsNone(model["profile"])
        self.assertTrue(any("segment" in m for m in model["missing"]))
        # les temps visés du plan restent affichés tels quels, jamais recalculés
        self.assertEqual(model["scenarios"]["realistic"]["target_s"], R.persisted_plan()["scenarios"]["realistic"])

    def test_scenario_missing_from_segments_is_dropped_not_guessed(self):
        plan = R.persisted_plan()
        for seg in plan["segments"]:
            seg["predicted_time_s"].pop("safe")
        model = RB.build_roadbook(plan)
        self.assertFalse(model["scenarios"]["safe"]["available"])
        self.assertTrue(model["scenarios"]["realistic"]["available"])
        self.assertTrue(any("safe" in m for m in model["missing"]))

    def test_missing_take_gear_emergency_are_listed(self):
        plan = R.persisted_plan()
        for st in plan["aid_stations"]:
            st.pop("take")
        plan.pop("gear")
        plan.pop("emergency")
        model = RB.build_roadbook(plan)
        text = " ".join(model["missing"])
        self.assertIn("ravito", text)
        self.assertIn("matériel obligatoire", text)
        self.assertIn("urgence", text)
        self.assertIsNone(model["gear"])
        self.assertNotIn("take", model["scenarios"]["realistic"]["sections"][0]["station"])
        # nuit prévue sans matériel déclaré : rappel de la frontale
        self.assertTrue(any("frontale" in w for w in model["warnings"]))

    def test_night_without_headlamp_in_gear_warns(self):
        model = _model(gear=["Couverture de survie"])
        self.assertTrue(any("aucune frontale" in w for w in model["warnings"]))

    def test_gear_check_statuses_pass_through(self):
        check = {"entries": [{"entry": "Frontale", "status": "never_used", "matches": [{"name": "Petzl"}]},
                             {"entry": "Gobelet", "status": "missing", "matches": []}],
                 "inventory_empty": False}
        model = RB.build_roadbook(R.persisted_plan(), gear_check=check)
        self.assertEqual([(e["entry"], e["status"]) for e in model["gear"]["entries"]],
                         [("Frontale", "never_used"), ("Gobelet", "missing")])
        self.assertEqual(model["gear"]["entries"][0]["items"], ["Petzl"])
        self.assertTrue(model["gear"]["inventory_checked"])

    def test_gear_without_inventory_check_is_marked_unchecked(self):
        model = RB.build_roadbook(R.persisted_plan(), gear_check={"error": "aucun plan"})
        self.assertFalse(model["gear"]["inventory_checked"])
        self.assertTrue(all(e["status"] == "unchecked" for e in model["gear"]["entries"]))

    def test_timezone_aware_cutoff_does_not_crash(self):
        plan = R.persisted_plan()
        plan["aid_stations"][0]["cutoff"] = "2026-06-20T20:00:00+00:00"
        model = RB.build_roadbook(plan)
        self.assertTrue(model["scenarios"]["realistic"]["available"])
        # #205 : la marge est calculée (instant exact dans le fuseau du plan), plus de « fuseau mixte ».
        first = model["scenarios"]["realistic"]["sections"][0]
        self.assertIn("margin_s", first["cutoff"])
        self.assertFalse(any("fuseau mixte" in m for m in model["missing"]))
        # Etc/GMT+9 : départ 16:00 local = 2026-06-21T01:00Z ; barrière 20:00Z la veille -> hors délai.
        self.assertEqual(first["cutoff"]["margin_s"], -5 * 3600 - first["arrival_s"])
        self.assertEqual(first["cutoff"]["status"], "hors_delai")

    def test_aid_station_beyond_the_course_is_flagged(self):
        plan = R.persisted_plan()
        plan["aid_stations"].append({"km": 150.0, "name": "Fantôme"})
        model = RB.build_roadbook(plan)
        self.assertTrue(any("au-delà de la fin" in w for w in model["warnings"]))

    def test_no_aid_station_falls_back_to_segment_rows(self):
        plan = R.persisted_plan(aid_stations=[])
        model = RB.build_roadbook(plan)
        secs = model["scenarios"]["realistic"]["sections"]
        self.assertEqual(len(secs), len(plan["segments"]))
        self.assertEqual(secs[-1]["arrival_s"], model["scenarios"]["realistic"]["total_s"])
        self.assertTrue(any("aucun ravito" in m for m in model["missing"]))

    def test_inputs_are_not_mutated(self):
        plan = R.persisted_plan()
        before = copy.deepcopy(plan)
        RB.build_roadbook(plan)
        self.assertEqual(plan, before)


class TestRoadbookClockTimezone(unittest.TestCase):
    """Heures de passage d'un ultra qui traverse le changement d'heure (revue #187) : le temps écoulé
    est absolu, l'horloge affichée est l'heure locale RÉELLE du fuseau du plan — comme la nuit (#184)."""

    @staticmethod
    def _expected(start_iso, elapsed_s):
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("Europe/Paris")
        start = datetime.fromisoformat(start_iso).astimezone(zone)
        local = (start.astimezone(timezone.utc) + timedelta(seconds=elapsed_s)).astimezone(zone)
        days = (local.date() - start.date()).days
        return local.strftime("%H:%M") + (f" (J+{days})" if days > 0 else "")

    def test_fall_back_during_the_race_uses_real_local_time(self):
        start = "2026-10-25T01:30:00+02:00"          # 03:00 CEST -> 02:00 CET pendant la course
        model = _model(start_time=start, timezone="Europe/Paris", race_date="2026-10-25")
        secs = model["scenarios"]["realistic"]["sections"]
        for r in secs:
            self.assertEqual(r["arrival_clock"], self._expected(start, r["arrival_s"]))
        # 1 h 30 CEST + 1 h 54 de course = 02:24 CET (et non 03:24 en simple addition murale)
        self.assertEqual(secs[0]["arrival_clock"], self._expected(start, secs[0]["arrival_s"]))
        self.assertNotEqual(secs[0]["arrival_clock"], "03:24")
        self.assertTrue(any("changement d'heure" in w for w in model["warnings"]))

    def test_utc_start_is_shown_in_the_plan_timezone(self):
        model = _model(start_time="2026-10-24T16:00:00Z", timezone="Europe/Paris", race_date="2026-10-24")
        self.assertEqual(model["header"]["start_clock"], "18:00")

    def test_without_timezone_the_clock_is_a_plain_wall_clock_addition(self):
        plan = R.persisted_plan(start_time="2026-10-25T01:30:00+02:00", race_date="2026-10-25")
        del plan["timezone"]
        model = RB.build_roadbook(plan)
        first = model["scenarios"]["realistic"]["sections"][0]
        h, m = divmod((90 * 60 + first["arrival_s"]) // 60, 60)
        self.assertEqual(first["arrival_clock"], f"{h % 24:02d}:{m:02d}")
        self.assertFalse(any("changement d'heure" in w for w in model["warnings"]))


class TestRoadbookContract(unittest.TestCase):
    def test_new_optional_keys_validate(self):
        plan = R.persisted_plan(nutrition_plan="nutrition/2026-06-10_nutrition.md")
        errors, _warnings = C.validate(plan)
        self.assertEqual(errors, [], errors)

    def test_take_must_be_a_list(self):
        plan = R.persisted_plan()
        plan["aid_stations"][0]["take"] = "2 gels"
        errors, _ = C.validate(plan)
        self.assertTrue(any("take" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
