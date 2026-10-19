"""Palier D — matériel hors chaussures (#134) : parsing `### Matériel`, déclencheurs typés,
kits, sports par catégorie, alerte une seule fois sans état, contrat `gear_ids`, contrôle du
matériel de course. Stdlib pure, workspace écrit à la main.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_index as I  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_serve as S  # noqa: E402

TODAY = date(2026, 9, 23)


def arc(line: str) -> str:
    return f"# Titre\n\n```arc\n{line}\n```\n\nTexte.\n"


PROFILE = """# Profil

## Matériel & lieux

### Chaussures

- Hoka Speedgoat 5 — alerte 700 km — id: speedgoat (par défaut)

### Matériel

- Poche à eau 2 L — catégorie: poche — depuis 2026-08-01 — alerte 30 jours — kit: trail-long
- Frontale Petzl — catégorie: frontale — alerte 10 h — id: frontale — kit: nuit, trail-long
- Bâtons Leki — catégorie: bâtons — alerte 50 km — kit: trail-long
- Ceinture cardio — catégorie: ceinture — alerte 5 séances
- Trousse mystère — catégorie: gadget — kit: trail-long
"""


class TestParseEquipment(unittest.TestCase):
    def parse(self, bullets: str):
        return L.parse_equipment(f"## Matériel & lieux\n\n### Matériel\n\n{bullets}\n")

    def test_shoes_section_is_untouched(self):
        text = PROFILE
        shoes = L.parse_gear(text)
        self.assertEqual([s["gear_id"] for s in shoes], ["speedgoat"])
        self.assertEqual(shoes[0]["threshold_m"], 700000)
        # un profil sans « ### Matériel » : aucune clé equipment, rien à modifier
        self.assertNotIn("equipment", L.parse_profile("## Matériel & lieux\n\n### Chaussures\n\n- Nike\n"))

    def test_bare_heading_of_parent_section_is_not_equipment(self):
        self.assertEqual(L.parse_equipment("## Matériel & lieux\n\n- **Équipement** : salle\n"), [])

    def test_full_bullet(self):
        [item] = self.parse("- Poche à eau 2 L — catégorie: poche — depuis 2026-03-01 — alerte 30 jours — "
                            "kit: trail-long — entretien 2026-05-02")
        self.assertEqual(item["gear_id"], "poche-a-eau-2-l")
        self.assertEqual(item["category"], "poche")
        self.assertEqual(item["start_date"], "2026-03-01")
        self.assertEqual(item["maintenance_date"], "2026-05-02")
        self.assertEqual(item["threshold_days"], 30)
        self.assertEqual(item["kits"], ["trail-long"])

    def test_each_trigger_type_and_combination(self):
        [item] = self.parse("- X — alerte 300 km — alerte 40 h ou 12 séances ou 90 jours")
        self.assertEqual((item["threshold_m"], item["threshold_s"], item["threshold_sessions"],
                          item["threshold_days"]), (300000, 144000, 12, 90))
        [miles] = self.parse("- Y — alerte 100 miles")
        self.assertEqual(miles["threshold_m"], round(100 * 1609.344))
        [glued] = self.parse("- Z — alerte 40h")
        self.assertEqual(glued["threshold_s"], 144000)

    def test_bare_number_is_not_a_trigger(self):
        [item] = self.parse("- X — alerte 300")
        self.assertNotIn("threshold_m", item)

    def test_category_only_from_explicit_segment(self):
        [item] = self.parse("- Frontale Petzl — alerte 10 h")
        self.assertNotIn("category", item)
        [aliased] = self.parse("- Truc — catégorie: Bâtons")
        self.assertEqual(aliased["category"], "batons")
        [unknown] = self.parse("- Truc — catégorie: Gadget rare")
        self.assertEqual(unknown["category"], "gadget-rare")

    def test_typed_start_and_no_start_in_days(self):
        [item] = self.parse("- X — départ 12 h — départ 3 séances — départ 20 jours")
        self.assertEqual((item["start_s"], item["start_sessions"]), (43200, 3))
        self.assertNotIn("start_days", item)

    def test_retired_sub_bullets_and_collision(self):
        items = self.parse("- Poche — catégorie: poche (retirée)\n  - alerte 20 h\n- Poche — catégorie: poche")
        self.assertTrue(items[0]["retired"])
        self.assertEqual(items[0]["threshold_s"], 72000)
        self.assertEqual(items[1]["gear_id"], "poche-2")
        self.assertEqual(items[1]["collision_base"], "poche")

    def test_later_maintenance_wins(self):
        [item] = self.parse("- X — révisé 2026-01-01 — entretien 2026-06-01 — entretien 2026-02-01")
        self.assertEqual(item["maintenance_date"], "2026-06-01")


def defs():
    return L.parse_equipment(PROFILE)


def act(day, sport="trail", distance=10000, duration=3600, ids=(), refs=()):
    return {"date": day, "sport": sport, "distance_m": distance, "duration_s": duration,
            "gear_ids": list(ids), "refs": list(refs)}


def by_id(result):
    return {i["gear_id"]: i for i in result["items"]}


class TestEquipmentUsage(unittest.TestCase):
    def test_usage_counters_and_hours(self):
        acts = [act("2026-09-01", duration=7200, distance=12000, ids=["frontale"]),
                act("2026-09-10", sport="running", duration=1800, distance=5000, ids=["frontale"])]
        item = by_id(M.equipment_usage(acts, defs(), TODAY))["frontale"]
        self.assertEqual(item["usage"], {"distance_m": 17000, "duration_s": 9000, "sessions": 2, "days": None})
        self.assertFalse(item["alert"])
        trig = item["triggers"][0]
        self.assertEqual((trig["type"], trig["value"], trig["threshold"]), ("duration", 9000, 36000))

    def test_distance_trigger(self):
        acts = [act("2026-09-01", distance=30000, ids=["batons-leki"]),
                act("2026-09-02", distance=21000, ids=["batons-leki"])]
        item = by_id(M.equipment_usage(acts, defs(), TODAY))["batons-leki"]
        self.assertTrue(item["alert"])
        self.assertTrue(item["triggers"][0]["reached"])

    def test_sessions_trigger_and_near_threshold(self):
        four = [act(f"2026-09-0{i}", sport="cycling", ids=["ceinture-cardio"]) for i in range(1, 5)]
        item = by_id(M.equipment_usage(four, defs(), TODAY))["ceinture-cardio"]
        self.assertFalse(item["alert"])
        self.assertNotIn("near_threshold", item)      # 4/5 = 80 % < 90 %
        d = L.parse_equipment("### Matériel\n\n- Ceinture — alerte 10 séances\n")
        nine = [act(f"2026-09-0{i}", ids=["ceinture"]) for i in range(1, 10)]
        near = by_id(M.equipment_usage(nine, d, TODAY))["ceinture"]
        self.assertTrue(near["near_threshold"])       # 9/10 = 90 %
        self.assertFalse(near["alert"])
        five = four + [act("2026-09-05", sport="cycling", ids=["ceinture-cardio"])]
        self.assertTrue(by_id(M.equipment_usage(five, defs(), TODAY))["ceinture-cardio"]["alert"])

    def test_days_trigger_from_depuis(self):
        # depuis 2026-08-01, alerte 30 jours : au 2026-08-31 = 30 j
        item = by_id(M.equipment_usage([], defs(), date(2026, 8, 30)))["poche-a-eau-2-l"]
        self.assertEqual(item["usage"]["days"], 29)
        self.assertFalse(item["alert"])
        item = by_id(M.equipment_usage([], defs(), date(2026, 8, 31)))["poche-a-eau-2-l"]
        self.assertTrue(item["alert"])

    def test_maintenance_resets_days_and_counters(self):
        d = L.parse_equipment("### Matériel\n\n- Poche — catégorie: poche — depuis 2026-01-01 — "
                              "alerte 30 jours ou 5 séances — entretien 2026-09-10\n")
        acts = [act(f"2026-09-0{i}", ids=["poche"]) for i in range(1, 8)] + [act("2026-09-12", ids=["poche"])]
        item = by_id(M.equipment_usage(acts, d, TODAY))["poche"]
        self.assertEqual(item["usage"]["days"], 13)
        self.assertEqual(item["usage"]["sessions"], 1)         # seule la séance après l'entretien
        self.assertEqual(item["lifetime"]["sessions"], 8)
        self.assertFalse(item["alert"])
        self.assertEqual(item["reference_date"], "2026-09-10")

    def test_maintenance_day_session_is_excluded(self):
        d = L.parse_equipment("### Matériel\n\n- Veste — catégorie: veste — alerte 2 séances — entretien 2026-09-10\n")
        acts = [act("2026-09-10", ids=["veste"]), act("2026-09-11", ids=["veste"])]
        self.assertEqual(by_id(M.equipment_usage(acts, d, TODAY))["veste"]["usage"]["sessions"], 1)

    def test_days_trigger_without_reference_is_unavailable_not_zero(self):
        d = L.parse_equipment("### Matériel\n\n- Veste — alerte 30 jours\n")
        result = M.equipment_usage([], d, TODAY)
        item = by_id(result)["veste"]
        self.assertTrue(item["triggers"][0]["unavailable"])
        self.assertFalse(item["alert"])
        self.assertTrue(any("date de référence" in w for w in result["warnings"]))

    def test_first_reached_fires(self):
        d = L.parse_equipment("### Matériel\n\n- X — catégorie: gilet — alerte 1000 km ou 2 séances\n")
        acts = [act("2026-09-01", ids=["x"]), act("2026-09-02", ids=["x"])]
        item = by_id(M.equipment_usage(acts, d, TODAY))["x"]
        self.assertTrue(item["alert"])
        reached = {t["type"]: t["reached"] for t in item["triggers"]}
        self.assertEqual(reached, {"distance": False, "sessions": True})

    def test_start_counts_until_maintenance(self):
        d = L.parse_equipment("### Matériel\n\n- Frontale — catégorie: frontale — départ 9 h — alerte 10 h\n")
        item = by_id(M.equipment_usage([act("2026-09-01", duration=3600, ids=["frontale"])], d, TODAY))["frontale"]
        self.assertTrue(item["alert"])            # 9 h de départ + 1 h

    def test_retired_never_alerts(self):
        d = L.parse_equipment("### Matériel\n\n- Bâtons — catégorie: bâtons — alerte 1 km (retirée)\n")
        item = by_id(M.equipment_usage([act("2026-09-01", ids=["batons"])], d, TODAY))["batons"]
        self.assertTrue(item["retired"])
        self.assertFalse(item["alert"])

    def test_no_default_threshold_no_invented_alert(self):
        d = L.parse_equipment("### Matériel\n\n- Sac — catégorie: gilet\n- Truc — catégorie: gadget\n- Nu\n")
        acts = [act("2026-09-01", distance=999999999, duration=999999, ids=["sac", "truc", "nu"])]
        result = M.equipment_usage(acts, d, TODAY)
        for item in result["items"]:
            self.assertFalse(item["alert"], item["gear_id"])
            self.assertEqual(item["triggers"], [])
        items = by_id(result)
        self.assertFalse(items["truc"]["category_known"])
        self.assertEqual(items["truc"]["usage"]["sessions"], 1)     # indexé et compté
        self.assertTrue(any("gadget" in w for w in result["warnings"]))

    def test_category_sports_table(self):
        acts = [act("2026-09-01", sport="running", ids=["batons-leki", "frontale", "poche-a-eau-2-l"]),
                act("2026-09-02", sport="cycling", ids=["batons-leki", "frontale", "poche-a-eau-2-l"]),
                act("2026-09-03", sport="hiking", ids=["batons-leki"])]
        items = by_id(M.equipment_usage(acts, defs(), TODAY))
        self.assertEqual(items["batons-leki"]["usage"]["sessions"], 1)     # bâtons : pas de route, ni vélo
        self.assertEqual(items["frontale"]["usage"]["sessions"], 2)        # frontale : tout sport
        self.assertEqual(items["poche-a-eau-2-l"]["usage"]["sessions"], 1)  # poche : course, pas vélo
        self.assertEqual(items["batons-leki"]["sports"], ["trail", "hiking", "walking"])
        self.assertEqual(items["frontale"]["sports"], "all")

    def test_unattributed_activity_counts_for_nothing_and_unknown_id_is_surfaced(self):
        acts = [act("2026-09-01"), act("2026-09-02", ids=["fantome"]), act("2026-09-03", ids=["speedgoat"])]
        result = M.equipment_usage(acts, defs(), TODAY, known_ids=["speedgoat"])
        self.assertEqual([u["gear_id"] for u in result["unknown"]], ["fantome"])
        self.assertTrue(all(i["usage"]["sessions"] == 0 for i in result["items"]))

    def test_future_activity_ignored(self):
        item = by_id(M.equipment_usage([act("2026-10-01", ids=["frontale"])], defs(), TODAY))["frontale"]
        self.assertEqual(item["usage"]["sessions"], 0)

    def test_pre_session_check_for_frontale_and_poche(self):
        items = by_id(M.equipment_usage([], defs(), TODAY))
        self.assertIn("nuit", items["frontale"]["pre_session_check"])
        self.assertIn("hygiène", items["poche-a-eau-2-l"]["pre_session_check"])
        self.assertNotIn("pre_session_check", items["batons-leki"])

    def test_kits_index(self):
        result = M.equipment_usage([], defs(), TODAY)
        self.assertEqual(sorted(result["kits"]["trail-long"]),
                         ["batons-leki", "frontale", "poche-a-eau-2-l", "trousse-mystere"])
        self.assertEqual(result["kits"]["nuit"], ["frontale"])


class TestOnceOnly(unittest.TestCase):
    """Alerte « une seule fois » sans état : par séance (km/h/séances), par jour (jours)."""

    def d(self):
        return L.parse_equipment("### Matériel\n\n- Frontale — catégorie: frontale — alerte 2 h\n"
                                 "- Poche — catégorie: poche — depuis 2026-09-01 — alerte 20 jours\n")

    def test_session_trigger_crossed_by_this_run_only(self):
        acts = [act("2026-09-20", duration=3600, ids=["frontale"], refs=["1"]),
                act("2026-09-21", duration=3600, ids=["frontale"], refs=["2"])]
        first = by_id(M.equipment_usage(acts, self.d(), TODAY, run_refs=["2"]))["frontale"]
        self.assertTrue(first["crossed_in_run"])
        acts.append(act("2026-09-22", duration=1800, ids=["frontale"], refs=["3"]))
        again = by_id(M.equipment_usage(acts, self.d(), TODAY, run_refs=["3"]))["frontale"]
        self.assertFalse(again["crossed_in_run"])      # le seuil (2 h) était déjà franchi avant la séance 3
        nothing = by_id(M.equipment_usage(acts, self.d(), TODAY))["frontale"]
        self.assertNotIn("crossed_in_run", nothing)

    def test_days_trigger_never_crosses_without_last_pass(self):
        """Scénario du doublon (revue #134) : sans `--last-pass`, jamais de franchissement en jours —
        ni le jour exact, ni un second passage ; l'état courant reste en alerte."""
        # depuis 2026-09-01 + 20 jours = 2026-09-21
        for day in (20, 21, 22):
            item = by_id(M.equipment_usage([], self.d(), date(2026, 9, day), run_refs=["x"]))["poche"]
            self.assertFalse(item["crossed_in_run"], day)
        self.assertTrue(item["alert"])
        # deux passages successifs le jour exact : toujours rien à émettre
        again = by_id(M.equipment_usage([], self.d(), date(2026, 9, 21), run_refs=["x", "y"]))["poche"]
        self.assertFalse(again["crossed_in_run"])

    def test_empty_run_marks_no_crossing_key(self):
        item = by_id(M.equipment_usage([], self.d(), date(2026, 9, 21)))["poche"]
        self.assertNotIn("crossed_in_run", item)

    def test_days_trigger_with_since_catches_a_missed_day_once(self):
        # dernier passage le 2026-09-19, aujourd'hui le 2026-09-23 : franchi entre les deux
        fired = by_id(M.equipment_usage([], self.d(), date(2026, 9, 23), last_pass=date(2026, 9, 19)))["poche"]
        self.assertTrue(fired["crossed_in_run"])
        # passage suivant (since = 09-23) : plus rien
        quiet = by_id(M.equipment_usage([], self.d(), date(2026, 9, 24), last_pass=date(2026, 9, 23)))["poche"]
        self.assertFalse(quiet["crossed_in_run"])
        self.assertTrue(quiet["alert"])
        # since déjà après le franchissement
        before = by_id(M.equipment_usage([], self.d(), date(2026, 9, 18), last_pass=date(2026, 9, 15)))["poche"]
        self.assertFalse(before["crossed_in_run"])

    def test_maintenance_rearms_the_day_trigger(self):
        d = L.parse_equipment("### Matériel\n\n- Poche — catégorie: poche — depuis 2026-01-01 — "
                              "alerte 20 jours — entretien 2026-09-03\n")
        item = by_id(M.equipment_usage([], d, date(2026, 9, 23), last_pass=date(2026, 9, 22)))["poche"]
        self.assertTrue(item["crossed_in_run"])    # 09-03 + 20 j = 09-23
        self.assertFalse(by_id(M.equipment_usage([], d, date(2026, 9, 22), last_pass=date(2026, 9, 21)))["poche"]["alert"])

    def test_retired_never_crosses(self):
        d = L.parse_equipment("### Matériel\n\n- Poche — depuis 2026-09-01 — alerte 20 jours (retirée)\n")
        item = by_id(M.equipment_usage([], d, date(2026, 9, 21), last_pass=date(2026, 9, 20)))["poche"]
        self.assertFalse(item["crossed_in_run"])


class TestKitMembers(unittest.TestCase):
    def test_kit_filters_by_sport_and_retired(self):
        d = defs() + L.parse_equipment("### Matériel\n\n- Vieux gilet — catégorie: gilet — kit: trail-long (retirée)\n")
        trail = M.kit_members(d, "trail-long", "trail")
        self.assertEqual(sorted(trail["gear_ids"]),
                         ["batons-leki", "frontale", "poche-a-eau-2-l", "trousse-mystere"])
        self.assertEqual(trail["skipped"], [{"gear_id": "vieux-gilet", "reason": "retired"}])
        road = M.kit_members(d, "trail-long", "running")
        self.assertNotIn("batons-leki", road["gear_ids"])
        self.assertIn({"gear_id": "batons-leki", "reason": "sport"}, road["skipped"])
        self.assertIn("frontale", road["gear_ids"])

    def test_unknown_kit(self):
        out = M.kit_members(defs(), "inexistant", "trail")
        self.assertFalse(out["known"])
        self.assertEqual(out["gear_ids"], [])


class TestContract(unittest.TestCase):
    def base(self, **kw):
        data = {"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600}
        data.update(kw)
        return data

    def test_gear_ids_valid_and_backward_compat(self):
        self.assertEqual(C.validate(self.base())[0], [])
        self.assertEqual(C.validate(self.base(gear_id="speedgoat", gear_ids=["frontale", "batons-leki"]))[0], [])
        self.assertEqual(C.validate(self.base(gear_ids=[]))[0], [])

    def test_gear_ids_rejects_bad_values(self):
        for bad in ("frontale", [1], ["Frontale"], ["a", "a"], ["x" * 41], [f"g{i}" for i in range(31)]):
            errors, _ = C.validate(self.base(gear_ids=bad))
            self.assertTrue(any("gear_ids" in e for e in errors), (bad, errors))

    def test_gear_ids_documented_in_skill(self):
        self.assertIn("`gear_ids`", (REPO / "skills/workspace-data-contract/SKILL.md").read_text(encoding="utf-8"))


class EquipmentWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-equip-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        (self.ws / "planning/Runner_Profile.md").write_text(PROFILE, encoding="utf-8")
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        (self.ws / rel).write_text(text, encoding="utf-8")

    def activity(self, day, sport="trail", ids=(), extra=""):
        gids = f', "gear_ids": {json.dumps(list(ids))}' if ids else ""
        self.write(f"activities/{day}_{sport}.md", arc(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", "duration_s": 7200, '
            f'"distance_m": 20000{gids}{extra}}}'))

    def index(self):
        I.index_workspace(self.conn, self.ws, TODAY.isoformat())


class TestEquipmentIndex(EquipmentWorkspace):
    def test_table_and_activity_column(self):
        self.activity("2026-09-10", ids=["frontale", "batons-leki"])
        self.index()
        rows = {r["gear_id"]: dict(r) for r in self.conn.execute("SELECT * FROM equipment")}
        self.assertEqual(rows["frontale"]["threshold_s"], 36000)
        self.assertEqual(json.loads(rows["frontale"]["kits"]), ["nuit", "trail-long"])
        self.assertEqual(rows["trousse-mystere"]["category"], "gadget")
        self.assertEqual(json.loads(self.conn.execute("SELECT gear_ids FROM activity").fetchone()[0]),
                         ["frontale", "batons-leki"])

    def test_equipment_usage_from_index_and_shoes_unchanged(self):
        self.activity("2026-09-10", ids=["frontale"])
        self.activity("2026-09-11", ids=["frontale"])
        self.activity("2026-09-12", ids=["frontale"])
        self.activity("2026-09-13", ids=["frontale", "speedgoat"])
        self.activity("2026-09-14", ids=["frontale"])
        self.index()
        eq = I.equipment_usage(self.conn, TODAY)
        self.assertTrue(by_id(eq)["frontale"]["alert"])                  # 5 x 2 h = 10 h ≥ 10 h
        self.assertEqual(eq["unknown"], [])                              # speedgoat = chaussure, pas inconnu
        shoes = I.gear_mileage(self.conn, TODAY)
        self.assertEqual([s["gear_id"] for s in shoes["shoes"]], ["speedgoat"])   # `gear` inchangé

    def test_summary_carries_equipment(self):
        self.activity("2026-09-10", ids=["frontale"])
        store = S.Store(self.ws, memory=True, today=TODAY.isoformat())
        summary = S.api_summary(store, {})
        self.assertEqual(summary["equipment"]["kits"]["nuit"], ["frontale"])
        self.assertIn("gear", summary)

    def test_cli_kit_and_once_only(self):
        self.index()
        base = [sys.executable, str(REPO / "scripts/arc_index.py"), "equipment", "--workspace", str(self.ws),
                "--memory", "--today", "2026-09-23"]
        out = json.loads(subprocess.run(base + ["--kit", "trail-long", "--sport", "running"],
                                        capture_output=True, text=True, check=True).stdout)
        self.assertNotIn("batons-leki", out["gear_ids"])
        self.assertIn("frontale", out["gear_ids"])
        out = json.loads(subprocess.run(base + ["--last-pass", "2026-08-29"], capture_output=True, text=True,
                                        check=True).stdout)
        poche = by_id(out)["poche-a-eau-2-l"]        # depuis 2026-08-01 + 30 j = 2026-08-31
        self.assertTrue(poche["crossed_in_run"])


class TestRaceGearCheck(EquipmentWorkspace):
    def race_plan(self, gear):
        self.write("planning/2026-10-01_plan_course_test.md", arc(json.dumps({
            "arc": 1, "kind": "race_plan", "date": "2026-09-01", "race_name": "Trail Test",
            "race_date": "2026-10-10", "gear": gear}, ensure_ascii=False)))

    def test_missing_never_used_alert_ok(self):
        self.activity("2026-09-05", ids=["batons-leki"])
        self.activity("2026-09-06", ids=["batons-leki"])
        self.activity("2026-09-07", ids=["batons-leki"])       # 3 x 20 = 60 km ≥ 50 km → alerte
        self.race_plan(["Bâtons", "Frontale 300 lumens", "Couverture de survie", "Chaussures de trail",
                        "Ceinture cardio", "Veste imperméable"])
        self.index()
        out = I.equipment_race_check(self.conn, "", TODAY)
        status = {e["entry"]: e["status"] for e in out["entries"]}
        self.assertEqual(status["Bâtons"], "alert")
        self.assertEqual(status["Frontale 300 lumens"], "never_used")      # dans l'inventaire, jamais utilisée
        self.assertEqual(status["Couverture de survie"], "missing")        # jamais inventée
        self.assertEqual(status["Veste imperméable"], "missing")           # aucune veste déclarée
        self.assertEqual(status["Ceinture cardio"], "never_used")
        self.assertEqual(status["Chaussures de trail"], "category_match")  # « chaussures » seul : à vérifier
        self.assertEqual(out["missing"], ["Couverture de survie", "Veste imperméable"])

    def test_used_item_is_ok(self):
        self.activity("2026-09-05", ids=["frontale"], sport="running")
        self.race_plan(["Frontale"])
        self.index()
        [entry] = I.equipment_race_check(self.conn, "", TODAY)["entries"]
        self.assertEqual(entry["status"], "ok")

    def test_absolute_and_dot_slash_paths(self):
        self.race_plan(["Frontale"])
        self.index()
        for ref in (str(self.ws / "planning/2026-10-01_plan_course_test.md"),
                    "./planning/2026-10-01_plan_course_test.md", "planning/2026-10-01_plan_course_test.md"):
            with self.subTest(ref=ref):
                out = I.equipment_race_check(self.conn, ref, TODAY, self.ws)
                self.assertNotIn("error", out)
                self.assertEqual(out["race_name"], "Trail Test")

    def test_no_plan(self):
        self.index()
        self.assertIn("error", I.equipment_race_check(self.conn, "", TODAY))

    def test_no_inventory_everything_missing(self):
        (self.ws / "planning/Runner_Profile.md").write_text("# Profil\n", encoding="utf-8")
        self.race_plan(["Frontale"])
        self.index()
        out = I.equipment_race_check(self.conn, "", TODAY)
        self.assertTrue(out["inventory_empty"])
        self.assertEqual(out["missing"], ["Frontale"])

    def test_retired_item_never_matched(self):
        (self.ws / "planning/Runner_Profile.md").write_text(
            "### Matériel\n\n- Frontale — catégorie: frontale (retirée)\n", encoding="utf-8")
        self.race_plan(["Frontale"])
        self.index()
        self.assertEqual(I.equipment_race_check(self.conn, "", TODAY)["missing"], ["Frontale"])


if __name__ == "__main__":
    unittest.main()


class TestRaceGearMatchingStrictness(unittest.TestCase):
    """Revue #134 : jamais de `ok` sur un simple lien de catégorie (risque de disqualification)."""

    def check(self, lines, bullets):
        items = M.equipment_usage([act("2026-09-01", ids=[i["gear_id"] for i in L.parse_equipment(bullets)])],
                                  L.parse_equipment(bullets), TODAY)["items"]
        return {e["entry"]: e for e in M.race_gear_check(lines, items, [])["entries"]}

    def test_generic_adjective_is_not_a_category_link(self):
        out = self.check(["Pantalon imperméable"], "### Matériel\n\n- Veste Decathlon — catégorie: veste\n")
        self.assertEqual(out["Pantalon imperméable"]["status"], "missing")

    def test_windbreaker_and_waterproof_do_not_cross(self):
        one = self.check(["Coupe-vent"], "### Matériel\n\n- Veste imperméable — catégorie: veste\n")
        self.assertEqual(one["Coupe-vent"]["status"], "missing")
        two = self.check(["Veste imperméable"], "### Matériel\n\n- Veste coupe-vent — catégorie: veste\n")
        self.assertEqual(two["Veste imperméable"]["status"], "category_match")

    def test_bib_belt_is_not_the_hr_strap(self):
        out = self.check(["Ceinture porte-dossard"], "### Matériel\n\n- Polar H10 — catégorie: ceinture\n")
        self.assertEqual(out["Ceinture porte-dossard"]["status"], "category_match")
        self.assertNotEqual(out["Ceinture porte-dossard"]["status"], "ok")

    def test_punctuation_is_normalised_on_both_sides(self):
        b = "### Matériel\n\n- Sac Salomon (12 L) — catégorie: gilet\n- Veste — id: coupe-vent\n"
        out = self.check(["Sac Salomon (12 L)", "Coupe-vent obligatoire"], b)
        self.assertEqual(out["Sac Salomon (12 L)"]["status"], "ok")
        self.assertEqual(out["Coupe-vent obligatoire"]["status"], "ok")     # via l'id « coupe-vent »

    def test_name_link_is_ok_and_head_noun_only_is_category_match(self):
        b = "### Matériel\n\n- Frontale Petzl — catégorie: frontale\n"
        out = self.check(["Frontale", "Lampe frontale 300 lm"], b)
        self.assertEqual(out["Frontale"]["status"], "ok")
        self.assertEqual(out["Lampe frontale 300 lm"]["status"], "category_match")

    def test_passive_other_category_is_never_never_used(self):
        b = ("### Matériel\n\n- Couverture de survie — catégorie: autre\n"
             "- Frontale Petzl — catégorie: frontale\n")
        parsed = L.parse_equipment(b)
        items = M.equipment_usage([], parsed, TODAY)["items"]
        out = {e["entry"]: e["status"] for e in M.race_gear_check(["Couverture de survie", "Frontale"], items, [])["entries"]}
        self.assertEqual(out["Couverture de survie"], "ok")     # passif : rien à roder
        self.assertEqual(out["Frontale"], "never_used")         # porté : « rien de nouveau le jour J »

    def test_passive_item_naming_a_worn_item_does_not_validate_it(self):
        b = ("### Matériel\n\n- Gilet Salomon ADV Skin 5 — catégorie: gilet\n"
             "- Sifflet (intégré au gilet Salomon ADV Skin 5) — catégorie: autre\n")
        items = M.equipment_usage([], L.parse_equipment(b), TODAY)["items"]
        out = {e["entry"]: e["status"] for e in M.race_gear_check(["Gilet Salomon ADV Skin 5", "Sifflet"], items, [])["entries"]}
        self.assertEqual(out["Gilet Salomon ADV Skin 5"], "never_used")
        self.assertEqual(out["Sifflet"], "ok")

    def test_category_word_not_at_head_does_not_match(self):
        out = self.check(["Étui pour ceinture"], "### Matériel\n\n- Ceinture cardio — catégorie: ceinture\n")
        self.assertEqual(out["Étui pour ceinture"]["status"], "missing")


class TestTriggerWordings(unittest.TestCase):
    """Revue #134 : formulations courantes, jamais silencieusement perdues."""

    def one(self, bullet):
        [item] = L.parse_equipment(f"### Matériel\n\n{bullet}\n")
        return item

    def test_calendar_units_become_days(self):
        self.assertEqual(self.one("- X — alerte 12 mois")["threshold_days"], 360)
        self.assertEqual(self.one("- X — alerte 2 ans")["threshold_days"], 730)
        self.assertEqual(self.one("- X — alerte 1 an")["threshold_days"], 365)
        self.assertEqual(self.one("- X — alerte 4 semaines")["threshold_days"], 28)
        self.assertEqual(self.one("- X — alerte 6 mois ou 40 h")["threshold_s"], 144000)

    def test_hours_and_minutes(self):
        self.assertEqual(self.one("- X — alerte 1h30")["threshold_s"], 5400)
        self.assertEqual(self.one("- X — alerte 2 h 30")["threshold_s"], 9000)
        self.assertEqual(self.one("- X — départ 2h30")["start_s"], 9000)
        self.assertEqual(self.one("- X — alerte 40h")["threshold_s"], 144000)

    def test_mois_is_not_miles(self):
        item = self.one("- X — alerte 3 mois")
        self.assertNotIn("threshold_m", item)

    def test_unreadable_segments_warn(self):
        for bullet in ("- X — alerte 800", "- X — alerte bientôt", "- X — départ 20 jours", "- X — départ beaucoup"):
            with self.subTest(bullet=bullet):
                item = self.one(bullet)
                self.assertTrue(item.get("parse_warnings"), item)
        self.assertNotIn("parse_warnings", self.one("- X — alerte 800 km"))

    def test_warnings_reach_usage_output(self):
        d = L.parse_equipment("### Matériel\n\n- Poche — alerte 800\n")
        result = M.equipment_usage([], d, TODAY)
        self.assertTrue(any("sans déclencheur lisible" in w for w in result["warnings"]))

    def test_ignoree_is_stripped_from_id_with_warning(self):
        item = self.one("- Frontale Petzl (ignorée) — catégorie: frontale")
        self.assertEqual(item["gear_id"], "frontale-petzl")
        self.assertTrue(any("ignorée" in w for w in item["parse_warnings"]))


class TestReviewFixes(unittest.TestCase):
    def test_walking_counts_for_poles_vest_flasks_jacket(self):
        d = L.parse_equipment("### Matériel\n\n- Bâtons — catégorie: bâtons\n- Gilet — catégorie: gilet\n"
                              "- Semelles — catégorie: semelles\n")
        acts = [act("2026-09-01", sport="walking", ids=["batons", "gilet", "semelles"])]
        items = by_id(M.equipment_usage(acts, d, TODAY))
        self.assertEqual(items["batons"]["usage"]["sessions"], 1)
        self.assertEqual(items["gilet"]["usage"]["sessions"], 1)
        self.assertEqual(items["semelles"]["usage"]["sessions"], 0)

    def test_shoe_slug_in_gear_ids_is_warned_not_counted(self):
        result = M.equipment_usage([act("2026-09-01", ids=["speedgoat"])], defs(), TODAY, known_ids=["speedgoat"])
        self.assertTrue(any("speedgoat" in w and "gear_id" in w for w in result["warnings"]))
        self.assertEqual(result["unknown"], [])

    def test_maintenance_rule_strictly_after(self):
        """`entretien` = date de la dernière séance AVANT l'entretien : la séance du même jour faite
        APRÈS l'entretien (donc datée le lendemain de cette date, ou plus tard) compte."""
        d = L.parse_equipment("### Matériel\n\n- Poche — catégorie: poche — alerte 9 séances — entretien 2026-09-10\n")
        acts = [act("2026-09-10", ids=["poche"]), act("2026-09-11", ids=["poche"])]
        self.assertEqual(by_id(M.equipment_usage(acts, d, TODAY))["poche"]["usage"]["sessions"], 1)

    def test_sport_validation_in_cli(self):
        tmp = Path(tempfile.mkdtemp(prefix="arc-sport-"))
        try:
            (tmp / "planning").mkdir()
            (tmp / "planning/Runner_Profile.md").write_text(PROFILE, encoding="utf-8")
            base = [sys.executable, str(REPO / "scripts/arc_index.py"), "equipment", "--workspace", str(tmp),
                    "--memory", "--today", "2026-09-23", "--kit", "trail-long"]
            ok = subprocess.run(base + ["--sport", "TRAIL"], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("batons-leki", json.loads(ok.stdout)["gear_ids"])
            bad = subprocess.run(base + ["--sport", "trial"], capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("sport inconnu", bad.stdout + bad.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
