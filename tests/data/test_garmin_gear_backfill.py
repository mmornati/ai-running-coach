"""Palier D — `scripts/garmin_gear_backfill.py` (#145) : planification pure (appariement, conflits,
ambiguïtés, arithmétique de « départ », filtres, repli de nom, collisions d'id), insertion de puces
dans le profil, réécriture textuelle du bloc `arc`, idempotence. Stdlib seule : client Garmin simulé
(`FakeClient`), workspace temporaire, aucun appel réseau, `garminconnect` non requis.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_index as I  # noqa: E402
import arc_legacy as L  # noqa: E402
import garmin_gear_backfill as B  # noqa: E402

U1 = "a1" * 16
U2 = "b2" * 16
U3 = "c3" * 16


def shoe(uuid=U1, name="Hoka Speedgoat 5", status="active", begin="2026-01-10T00:00:00.0", max_m=800000, typ="Shoes",
         custom=None):
    return {"uuid": uuid, "displayName": name, "customMakeModel": custom, "gearTypeName": typ,
            "gearStatusName": status, "dateBegin": begin, "maximumMeters": max_m}


def gact(aid, day, km=10.0):
    return {"activityId": aid, "startTimeLocal": f"{day} 07:00:00", "distance": km * 1000}


def ws(aid, day, km=10.0, gear_id=None, source=None, name=None):
    return {"path": f"activities/{day}_{name or aid}.md", "date": day, "garmin_activity_id": aid,
            "distance_m": km * 1000, "gear_id": gear_id, "gear_source": source, "has_block": True}


def acts(*items):
    return {"activities": B.normalize_gear_activities(list(items)), "error": None, "truncated": False}


def make_plan(raw_shoes, per_shoe, files, profile="", **kw):
    shoes = B.normalize_shoes(raw_shoes)
    gear_acts = {u: (v if isinstance(v, dict) else acts(*v)) for u, v in per_shoe.items()}
    return B.plan(shoes, gear_acts, files, L.parse_gear(profile), **kw)


class TestNormalize(unittest.TestCase):
    def test_only_shoes_and_name_fallbacks(self):
        raw = [shoe(U1, name=None, custom="Nike Pegasus"), shoe(U2, name=None, custom=None),
               shoe(U3, typ="Bike"), shoe("d4" * 16, name="  ")]
        out = B.normalize_shoes(raw)
        self.assertEqual([s["name"] for s in out],
                         ["Nike Pegasus", f"Chaussure Garmin {U2[:8]}", f"Chaussure Garmin {'d4' * 4}"])
        self.assertEqual(len(out), 3)

    def test_fields(self):
        s = B.normalize_shoes([shoe(status="retired", max_m=0)])[0]
        self.assertTrue(s["retired"])
        self.assertEqual(s["date_begin"], "2026-01-10")
        self.assertEqual(s["max_m"], 0.0)

    def test_gear_activities_dedup_and_date(self):
        out = B.normalize_gear_activities([gact(1, "2026-02-01"), gact(1, "2026-02-01"), {"activityId": "x"}])
        self.assertEqual(out, [{"id": 1, "date": "2026-02-01", "distance_m": 10000.0}])


class TestBullet(unittest.TestCase):
    def test_full_bullet_roundtrips_through_parser(self):
        s = B.normalize_shoes([shoe(status="retired")])[0]
        b = B.build_bullet(s, "hoka-speedgoat-5", 250)
        self.assertEqual(b, f"- Hoka Speedgoat 5 — depuis 2026-01-10 — alerte 800 km — départ 250 km — "
                            f"id: hoka-speedgoat-5 — garmin: {U1} (retirée)")
        g = L.parse_gear("### Chaussures\n\n" + b + "\n")[0]
        self.assertEqual((g["gear_id"], g["garmin_uuid"], g["start_m"], g["threshold_m"], g["retired"]),
                         ("hoka-speedgoat-5", U1, 250000, 800000, True))
        self.assertNotIn("default", g)

    def test_no_alert_when_max_is_zero_and_no_default_marker(self):
        s = B.normalize_shoes([shoe(max_m=0)])[0]
        b = B.build_bullet(s, "x", None)
        self.assertNotIn("alerte", b)
        self.assertNotIn("défaut", b)
        self.assertNotIn("départ", b)

    def test_hostile_names_are_sanitised(self):
        for name in ("Brooks — Ghost (retirée) 15", "Nike: depuis 2020", "Saucony - id: x", "A — départ 3 km"):
            s = B.normalize_shoes([shoe(name=name)])[0]
            bullet = B.build_bullet(s, "ok", None)
            g = L.parse_gear("### Chaussures\n" + bullet + "\n")[0]
            self.assertEqual(g["garmin_uuid"], U1, name)
            self.assertFalse(g.get("retired"), name)
            self.assertNotIn("start_m", g, name)

    def test_unique_ids_with_collisions(self):
        used = {"hoka-speedgoat-5", "hoka-speedgoat-5-2"}
        self.assertEqual(B.unique_gear_id("Hoka Speedgoat 5", U1, used), "hoka-speedgoat-5-3")
        self.assertEqual(B.unique_gear_id("Hoka Speedgoat 5", U1, used), "hoka-speedgoat-5-4")
        self.assertEqual(B.unique_gear_id("???", U2, set()), C.gear_slug(f"chaussure garmin {U2[:8]}"))


class TestPlanMatching(unittest.TestCase):
    def test_basic_matching_and_km(self):
        files = [ws(1, "2026-03-01"), ws(2, "2026-03-05", km=12), ws(3, "2026-03-09")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-05", 12), gact(9, "2025-12-01", 20)]}, files)
        s = p["shoes"][0]
        self.assertEqual((s["status"], s["matched"], s["to_write"], s["workspace_km"], s["garmin_km"]),
                         ("new", 2, 2, 22.0, 42.0))
        self.assertEqual(len(p["assignments"]), 2)
        self.assertEqual(p["assignments"][0]["gear_id"], "hoka-speedgoat-5")
        self.assertEqual(p["workspace_without_id"], [])

    def test_workspace_files_without_id_counted(self):
        files = [ws(1, "2026-03-01"), ws(None, "2026-03-02")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01")]}, files)
        self.assertEqual(len(p["workspace_without_id"]), 1)
        self.assertEqual(p["workspace_with_id"], 1)

    def test_existing_athlete_declaration_is_kept_and_listed(self):
        files = [ws(1, "2026-03-01", gear_id="pegasus", source="chat"), ws(2, "2026-03-02")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-02")]}, files)
        self.assertEqual(len(p["assignments"]), 1)
        self.assertEqual(p["assignments"][0]["path"], files[1]["path"])
        self.assertEqual(p["conflicts"][0]["kept"], "pegasus")
        self.assertEqual(p["conflicts"][0]["kept_source"], "chat")

    def test_same_gear_already_attributed_is_not_a_conflict(self):
        files = [ws(1, "2026-03-01", gear_id="hoka-speedgoat-5", source="garmin")]
        profile = f"### Chaussures\n- Hoka Speedgoat 5 — id: hoka-speedgoat-5 — garmin: {U1}\n"
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01")]}, files, profile)
        self.assertEqual((p["shoes"][0]["already"], p["conflicts"], p["assignments"]), (1, [], []))

    def test_unmapped_is_replaced(self):
        files = [ws(1, "2026-03-01", source="garmin_unmapped")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01")]}, files)
        self.assertTrue(p["assignments"][0]["replaces_unmapped"])

    def test_ambiguous_activity_never_attributed(self):
        files = [ws(1, "2026-03-01"), ws(2, "2026-03-02")]
        p = make_plan([shoe(U1), shoe(U2, "Nike Pegasus")],
                      {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-02")], U2: [gact(1, "2026-03-01")]}, files)
        self.assertEqual([a["path"] for a in p["assignments"]], [files[1]["path"]])
        self.assertEqual(p["ambiguous"][0]["id"], 1)
        self.assertEqual(sorted(p["ambiguous"][0]["shoes"]), sorted([U1, U2]))

    def test_ignored_bullet_skipped_and_existing_id_reused(self):
        profile = (f"### Chaussures\n\n- Vieille — id: vieille — garmin: {U2} (ignorée)\n"
                   f"- Ma Hoka — id: mes-hoka — garmin: {U1}\n")
        files = [ws(1, "2026-03-01"), ws(2, "2026-03-02")]
        p = make_plan([shoe(U1), shoe(U2, "Old")], {U1: [gact(1, "2026-03-01")], U2: [gact(2, "2026-03-02")]},
                      files, profile)
        by = {s["uuid"]: s for s in p["shoes"]}
        self.assertEqual(by[U1]["status"], "existing")
        self.assertEqual(p["assignments"][0]["gear_id"], "mes-hoka")
        self.assertEqual(by[U2]["status"], "ignored")
        self.assertEqual(len(p["assignments"]), 1)
        self.assertEqual(p["new_bullets"], [])

    def test_duplicate_uuid_in_profile_attributes_nothing(self):
        profile = f"### Chaussures\n- A — id: a — garmin: {U1}\n- B — id: b — garmin: {U1}\n"
        p = make_plan([shoe(U1)], {U1: [gact(1, "2026-03-01")]}, [ws(1, "2026-03-01")], profile)
        self.assertEqual(p["assignments"], [])
        self.assertEqual(p["shoes"][0]["status"], "duplicate_in_profile")

    def test_new_id_avoids_profile_and_equipment_collisions(self):
        profile = f"### Chaussures\n- Hoka Speedgoat 5 — id: hoka-speedgoat-5 — garmin: {U3}\n"
        p = make_plan([shoe(U1)], {U1: [gact(1, "2026-03-01")]}, [ws(1, "2026-03-01")], profile,
                      extra_used_ids={"hoka-speedgoat-5-2"})
        self.assertEqual(p["shoes"][0]["gear_id"], "hoka-speedgoat-5-3")

    def test_two_new_shoes_same_name_get_distinct_ids(self):
        p = make_plan([shoe(U1), shoe(U2, begin="2026-02-01T00:00:00.0")],
                      {U1: [gact(1, "2026-03-01")], U2: [gact(2, "2026-03-02")]},
                      [ws(1, "2026-03-01"), ws(2, "2026-03-02")])
        self.assertEqual(sorted(s["gear_id"] for s in p["shoes"]), ["hoka-speedgoat-5", "hoka-speedgoat-5-2"])

    def test_gear_filter_and_since_filter(self):
        files = [ws(1, "2026-03-01"), ws(2, "2026-04-01")]
        per = {U1: [gact(1, "2026-03-01"), gact(2, "2026-04-01")], U2: [gact(3, "2026-04-02")]}
        p = make_plan([shoe(U1), shoe(U2, "Nike")], per, files, only_gear=U2.upper())
        self.assertEqual([s["uuid"] for s in p["shoes"]], [U2])
        p = make_plan([shoe(U1)], per, files, since="2026-03-15")
        self.assertEqual(len(p["assignments"]), 1)
        self.assertEqual(p["shoes"][0]["before_since"], 1)


class TestPeriodAndDepart(unittest.TestCase):
    def test_out_of_period_skipped_unless_all_shoes(self):
        old = shoe(U2, "Vieille", status="retired", begin="2022-01-01T00:00:00.0", max_m=0)
        per = {U1: [gact(1, "2026-03-01")], U2: [gact(50, "2023-01-01", 30), gact(51, "2023-02-01", 20)]}
        files = [ws(1, "2026-03-01")]
        p = make_plan([shoe(U1), old], per, files)
        self.assertEqual([b["uuid"] for b in p["new_bullets"]], [U1])
        p = make_plan([shoe(U1), old], per, files, all_shoes=True)
        bullet = next(b for b in p["new_bullets"] if b["uuid"] == U2)["bullet"]
        self.assertIn("(retirée)", bullet)
        self.assertIn("départ 50 km", bullet)
        self.assertEqual(p["assignments"][0]["gear_id"], "hoka-speedgoat-5")

    def test_depart_counts_only_garmin_sessions_absent_from_workspace(self):
        files = [ws(1, "2026-03-01", km=10), ws(2, "2026-03-05", km=12)]
        per = {U1: [gact(1, "2026-03-01", 10), gact(2, "2026-03-05", 12), gact(7, "2025-11-01", 40), gact(8, "2025-12-01", 60)]}
        s = make_plan([shoe()], per, files)["shoes"][0]
        self.assertEqual(s["depart_km"], 100)
        self.assertEqual(s["workspace_km"], 22.0)
        self.assertIn("100 km", s["depart_note"])
        self.assertIn("2 séance(s) Garmin", s["depart_note"])

    def test_workspace_km_plus_depart_equals_garmin_total(self):
        files = [ws(1, "2026-03-01", km=10)]
        per = {U1: [gact(1, "2026-03-01", 10), gact(7, "2025-11-01", 40)]}
        s = make_plan([shoe()], per, files)["shoes"][0]
        self.assertEqual(s["workspace_km"] + s["depart_km"], s["garmin_km"])

    def test_depart_skipped_with_since(self):
        s = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(7, "2025-11-01", 40)]},
                      [ws(1, "2026-03-01")], since="2026-01-01")["shoes"][0]
        self.assertIsNone(s["depart_km"])
        self.assertIn("--since", s["depart_note"])
        self.assertNotIn("départ", s["bullet"])

    def test_depart_skipped_when_truncated(self):
        per = {U1: {**acts(gact(1, "2026-03-01"), gact(7, "2025-11-01", 40)), "truncated": True}}
        s = make_plan([shoe()], per, [ws(1, "2026-03-01")])["shoes"][0]
        self.assertIsNone(s["depart_km"])
        self.assertIn("tronquée", s["depart_note"])

    def test_existing_bullet_never_gets_depart(self):
        profile = f"### Chaussures\n- Ma Hoka — id: mes-hoka — garmin: {U1}\n"
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(7, "2025-11-01", 40)]}, [ws(1, "2026-03-01")], profile)
        self.assertIsNone(p["shoes"][0]["depart_km"])
        self.assertEqual(p["new_bullets"], [])

    def test_ambiguous_absent_session_excluded_from_depart(self):
        per = {U1: [gact(1, "2026-03-01"), gact(7, "2025-11-01", 40)], U2: [gact(7, "2025-11-01", 40)]}
        p = make_plan([shoe(U1), shoe(U2, "Nike")], per, [ws(1, "2026-03-01")])
        self.assertTrue(all(s["depart_km"] is None for s in p["shoes"]))

    def test_error_shoe_reported_not_proposed(self):
        per = {U1: {"activities": [], "error": "RuntimeError: 500", "truncated": False}}
        p = make_plan([shoe()], per, [ws(1, "2026-03-01")])
        self.assertEqual(p["shoes"][0]["status"], "error")
        self.assertEqual(p["new_bullets"], [])

    def test_idempotence_second_plan_is_empty(self):
        files = [ws(1, "2026-03-01"), ws(2, "2026-03-05")]
        per = {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-05"), gact(7, "2025-11-01", 40)]}
        p1 = make_plan([shoe()], per, files)
        profile = B.insert_gear_bullets("# Profil\n", [b["bullet"] for b in p1["new_bullets"]])
        files2 = [ws(1, "2026-03-01", gear_id="hoka-speedgoat-5", source="garmin"),
                  ws(2, "2026-03-05", gear_id="hoka-speedgoat-5", source="garmin")]
        p2 = make_plan([shoe()], per, files2, profile)
        self.assertEqual((p2["assignments"], p2["new_bullets"], p2["conflicts"]), ([], [], []))
        self.assertEqual(p2["shoes"][0]["already"], 2)


class TestProfileInsertion(unittest.TestCase):
    B1 = f"- Hoka — id: hoka — garmin: {U1}"
    B2 = f"- Nike — id: nike — garmin: {U2}"

    def ids(self, text):
        return [g["gear_id"] for g in L.parse_gear(text)]

    def test_appends_after_last_bullet_without_touching_existing(self):
        text = ("## Matériel & lieux\n\n### Chaussures\n\n- Vieille — id: vieille (retirée)\n  - alerte 500 km\n\n"
                "Note.\n\n### Matériel\n- x\n")
        out = B.insert_gear_bullets(text, [self.B1, self.B2])
        self.assertIn("- Vieille — id: vieille (retirée)\n  - alerte 500 km\n" + self.B1 + "\n" + self.B2 + "\n\nNote.", out)
        self.assertEqual(self.ids(out), ["vieille", "hoka", "nike"])

    def test_empty_subsection_with_commented_template(self):
        text = "## Matériel & lieux\n\n### Chaussures\n\n<!-- exemple :\n- Fake — id: fake\n-->\n\n### Matériel\n"
        out = B.insert_gear_bullets(text, [self.B1])
        self.assertEqual(self.ids(out), ["hoka"])
        self.assertIn(self.B1 + "\n", out)
        self.assertIn("\n\n### Matériel", out)
        self.assertLess(out.index("-->"), out.index(self.B1))

    def test_commented_heading_is_not_the_section(self):
        text = "## Matériel & lieux\n\n<!--\n### Chaussures\n- Fake — id: fake\n-->\n\n### Matériel\n- Poche\n\n## Autre\n"
        out = B.insert_gear_bullets(text, [self.B1])
        self.assertEqual(self.ids(out), ["hoka"])
        self.assertLess(out.index("\n### Chaussures\n\n- Hoka"), out.index("### Matériel\n- Poche"))
        self.assertTrue(out.rstrip().endswith("## Autre"))

    def test_creates_subsection_at_end_of_section(self):
        text = "# Profil\n\n## Matériel & lieux\n\n- **Lieu par défaut** : Tournai\n\n## Objectifs\n\n- x\n"
        out = B.insert_gear_bullets(text, [self.B1])
        self.assertEqual(self.ids(out), ["hoka"])
        self.assertLess(out.index("### Chaussures"), out.index("## Objectifs"))
        self.assertGreater(out.index("### Chaussures"), out.index("Tournai"))
        self.assertIn("\n## Objectifs\n\n- x\n", out)

    def test_creates_section_when_absent(self):
        out = B.insert_gear_bullets("# Profil\n\n- **Nom** : Marco", [self.B1])
        self.assertEqual(self.ids(out), ["hoka"])
        self.assertIn("## Matériel & lieux\n\n### Chaussures", out)
        self.assertIn("- **Nom** : Marco\n", out)

    def test_existing_lines_preserved_verbatim(self):
        text = "## Matériel & lieux\n### Chaussures\n- A — id: a\n- B — id: b\n"
        out = B.insert_gear_bullets(text, [self.B1])
        self.assertTrue(out.startswith(text))


class TestSetBlockKeys(unittest.TestCase):
    def test_single_line_insertion_preserves_order_and_text(self):
        text = ('# T\n\n```arc\n{"arc": 1, "kind": "activity", "date": "2026-03-01", "sport": "trail", '
                '"duration_s": 60}\n```\n\nTexte.\n')
        out = B.set_block_keys(text, {"gear_id": "x", "gear_source": "garmin"})
        self.assertIn('"duration_s": 60, "gear_id": "x", "gear_source": "garmin"}\n```\n\nTexte.', out)
        self.assertEqual(C.extract_block(out)["gear_id"], "x")

    def test_multiline_insertion_keeps_indent(self):
        text = ('```arc\n{\n  "arc": 1, "kind": "activity", "date": "2026-03-01",\n'
                '  "sport": "trail", "duration_s": 60\n}\n```\n')
        out = B.set_block_keys(text, {"gear_id": "x", "gear_source": "garmin"})
        self.assertIn('"duration_s": 60,\n  "gear_id": "x",\n  "gear_source": "garmin"\n}', out)

    def test_replaces_unmapped_source(self):
        text = ('```arc\n{"arc": 1, "kind": "activity", "date": "2026-03-01", "sport": "trail", "duration_s": 60, '
                '"gear_source": "garmin_unmapped"}\n```\n')
        block = C.extract_block(B.set_block_keys(text, {"gear_id": "x", "gear_source": "garmin"}))
        self.assertEqual((block["gear_id"], block["gear_source"]), ("x", "garmin"))
        self.assertEqual(block["duration_s"], 60)


def write_activity(ws_dir: Path, name: str, **extra):
    block = {"arc": 1, "kind": "activity", "date": name[:10], "sport": "trail", "duration_s": 3600, **extra}
    (ws_dir / "activities").mkdir(exist_ok=True)
    (ws_dir / "activities" / name).write_text(
        f"# Séance\n\n```arc\n{json.dumps(block, ensure_ascii=False)}\n```\n\nTexte.\n", encoding="utf-8")


class TestApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / "planning").mkdir()
        self.profile = self.ws / "planning" / "Runner_Profile.md"
        self.profile.write_text("# Profil\n\n## Matériel & lieux\n\n- **Lieu par défaut** : Tournai\n", encoding="utf-8")
        write_activity(self.ws, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=10000)
        write_activity(self.ws, "2026-03-05_trail.md", garmin_activity_id=2, distance_m=12000,
                       gear_id="pegasus", gear_source="chat")
        write_activity(self.ws, "2026-03-09_trail.md", distance_m=5000)
        self.addCleanup(self.tmp.cleanup)

    def run_plan(self):
        files = B.scan_workspace(self.ws)
        per = {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-05", 12), gact(7, "2025-10-01", 40)]}
        return B.plan(B.normalize_shoes([shoe()]), {u: acts(*v) for u, v in per.items()}, files,
                      L.parse_gear(self.profile.read_text()))

    def snapshot(self):
        return {p: p.read_text() for p in [self.profile, *(self.ws / "activities").glob("*.md")]}

    def test_scan(self):
        files = B.scan_workspace(self.ws)
        self.assertEqual([f["garmin_activity_id"] for f in files], [1, 2, None])
        self.assertEqual(files[1]["gear_source"], "chat")

    def test_apply_writes_validates_and_is_idempotent(self):
        p = self.run_plan()
        self.assertEqual(len(p["assignments"]), 1)
        out = B.apply_plan(self.ws, self.profile, p)
        self.assertEqual((out["profile_written"], out["written"], out["failed"]),
                         (True, ["activities/2026-03-01_trail.md"], []))
        block = C.extract_block((self.ws / "activities/2026-03-01_trail.md").read_text())
        self.assertEqual((block["gear_id"], block["gear_source"]), ("hoka-speedgoat-5", "garmin"))
        chat = C.extract_block((self.ws / "activities/2026-03-05_trail.md").read_text())
        self.assertEqual(chat["gear_id"], "pegasus")   # jamais écrasée
        self.assertIn("départ 40 km", self.profile.read_text())
        self.assertIn("### Chaussures", self.profile.read_text())
        self.assertTrue(I.validate_file(self.ws / "activities/2026-03-01_trail.md")[0])
        before = self.snapshot()
        p2 = self.run_plan()
        self.assertEqual((p2["assignments"], p2["new_bullets"]), ([], []))
        out2 = B.apply_plan(self.ws, self.profile, p2)
        self.assertEqual(out2["written"], [])
        self.assertEqual(before, self.snapshot())

    def test_invalid_file_is_restored(self):
        p = self.run_plan()
        target = self.ws / "activities/2026-03-01_trail.md"
        original = target.read_text()
        calls = []

        def validate(_p):     # valide AVANT l'écriture, refuse APRÈS
            calls.append(1)
            return (len(calls) == 1, ["refus simulé"], [])
        out = B.apply_plan(self.ws, self.profile, p, validate=validate)
        self.assertEqual(target.read_text(), original)
        self.assertEqual(out["failed"][0]["error"], "refus simulé")

    def test_planning_writes_nothing(self):
        before = self.snapshot()
        self.run_plan()
        self.assertEqual(before, self.snapshot())

    def test_gear_total_after_reindex_equals_garmin_total(self):
        p = self.run_plan()
        B.apply_plan(self.ws, self.profile, p)
        r = B.reindex(self.ws)
        row = next(g for g in r["gear"]["shoes"] if g["gear_id"] == "hoka-speedgoat-5")
        self.assertEqual(round(row["distance_m"]), 10000 + 40000)


class TestReport(unittest.TestCase):
    def test_report_is_french_and_mentions_sections(self):
        files = [ws(1, "2026-03-01", gear_id="autre", source="chat"), ws(None, "2026-03-02")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(7, "2025-11-01", 40)]}, files)
        text = B.render_report(p)
        for needle in ("simulation", "puce proposée", "CONFLITS", "FICHIERS SANS garmin_activity_id", "--apply",
                       "SÉANCES GARMIN ABSENTES"):
            self.assertIn(needle, text)
        json.dumps(p)


# ---------------------------------------------------------------------------
# Revue Opus (#145) : tests par constat
# ---------------------------------------------------------------------------

class TestReviewMajor(unittest.TestCase):
    def test_1_gear_filter_still_detects_ambiguity_across_all_shoes(self):
        files = [ws(1, "2026-03-01"), ws(2, "2026-03-02")]
        per = {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-02")], U2: [gact(1, "2026-03-01")]}
        p = make_plan([shoe(U1), shoe(U2, "Nike")], per, files, only_gear=U1)
        self.assertEqual([a["path"] for a in p["assignments"]], [files[1]["path"]])
        self.assertEqual([a["id"] for a in p["ambiguous"]], [1])
        self.assertEqual([s["uuid"] for s in p["shoes"]], [U1])

    def test_1_errored_or_truncated_pair_is_incomplete(self):
        per = {U1: [gact(1, "2026-03-01")], U2: {"activities": [], "error": "boom", "truncated": False}}
        p = make_plan([shoe(U1), shoe(U2, "Nike")], per, [ws(1, "2026-03-01")], only_gear=U1)
        self.assertEqual([i["uuid"] for i in p["incomplete"]], [U2])
        per = {U1: [gact(1, "2026-03-01")], U2: {**acts(gact(5, "2026-03-02")), "truncated": True}}
        p = make_plan([shoe(U1), shoe(U2, "Nike")], per, [ws(1, "2026-03-01")])
        self.assertEqual(p["incomplete"][0]["reason"], "liste tronquée")

    def test_1_run_refuses_apply_when_incomplete_and_writes_nothing(self):
        import argparse
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "planning").mkdir()
            prof = root / "planning" / "Runner_Profile.md"
            prof.write_text("# P\n", encoding="utf-8")
            write_activity(root, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=1000)
            spec = {"gear": [shoe(U1), shoe(U2, "Nike")],
                    "gear_activities": {U1: [gact(1, "2026-03-01")], U2: "HTTP 500"}}
            args = argparse.Namespace(workspace=str(root), apply=True, since=None, gear=U1, all_shoes=False,
                                      json=False, tokens_dir=None, fake_client=None)
            before = (prof.read_text(), (root / "activities/2026-03-01_trail.md").read_text())
            code, payload, text = B.run(args, B.GarminSource(B.FakeClient(spec)))
            self.assertEqual(code, B.EXIT_PARTIAL)
            self.assertTrue(payload["apply_refused"])
            self.assertIn("--apply REFUSÉ", text)
            self.assertEqual(before, (prof.read_text(), (root / "activities/2026-03-01_trail.md").read_text()))
            self.assertFalse((root / ".arc").exists())

    def _run_apply(self, root):
        import argparse
        (root / "planning").mkdir()
        (root / "planning" / "Runner_Profile.md").write_text("# P\n", encoding="utf-8")
        write_activity(root, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=1000)
        spec = {"gear": [shoe(U1, status="retired")], "gear_activities": {U1: [gact(1, "2026-03-01")]}}
        args = argparse.Namespace(workspace=str(root), apply=True, since=None, gear=None, all_shoes=False,
                                  json=False, tokens_dir=None, fake_client=None)
        return B.run(args, B.GarminSource(B.FakeClient(spec)))

    def test_apply_writes_garmin_snapshot(self):
        import arc_garmin_gear as GG
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, payload, text = self._run_apply(root)
            self.assertEqual(code, B.EXIT_OK)
            self.assertIsNone(payload["applied"]["snapshot_error"])
            self.assertEqual(GG.load_cache(root)["shoes"][0]["status"], "retired")

    def test_apply_reports_snapshot_failure_as_partial(self):
        import arc_garmin_gear as GG
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(GG, "write_cache", side_effect=PermissionError("lecture seule")):
            root = Path(tmp)
            code, payload, text = self._run_apply(root)
            self.assertEqual(code, B.EXIT_PARTIAL)
            self.assertIn("lecture seule", payload["applied"]["snapshot_error"])
            self.assertIn("garmin_gear.json non écrit", text)
            self.assertTrue(payload["applied"]["profile_written"])     # le reste est écrit quand même

    def test_2_depart_ignores_sessions_after_and_inside_the_workspace_period(self):
        files = [ws(1, "2026-03-01"), ws(2, "2026-03-20")]
        per = {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-20"), gact(7, "2025-11-01", 40),
                    gact(8, "2026-03-10", 15),       # trou dans la période
                    gact(9, "2026-04-05", 25)]}      # postérieure : la synchronisation l'importera
        s = make_plan([shoe()], per, files)["shoes"][0]
        self.assertEqual(s["depart_km"], 40)
        self.assertEqual((s["missing_before"], s["missing_in_period"], s["missing_after"]), (1, 1, 1))
        self.assertIn("postérieure", s["depart_note"])
        self.assertIn("trous", s["depart_note"])

    def test_2_after_period_only_gives_no_depart(self):
        s = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(9, "2026-04-05", 25)]},
                      [ws(1, "2026-03-01")])["shoes"][0]
        self.assertIsNone(s["depart_km"])
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(9, "2026-04-05", 25)]}, [ws(1, "2026-03-01")])
        self.assertEqual(p["missing_from_workspace"][0]["bucket"], "after")
        self.assertIn("postérieures", B.render_report(p))

    def test_3_duplicate_files_for_same_activity_are_reported_not_written(self):
        files = [ws(1, "2026-03-01", name="running"), ws(1, "2026-03-01", name="running_2"), ws(2, "2026-03-02")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01"), gact(2, "2026-03-02")]}, files)
        self.assertEqual([a["path"] for a in p["assignments"]], [files[2]["path"]])
        self.assertEqual(p["duplicate_ids"][0]["id"], 1)
        self.assertEqual(len(p["duplicate_ids"][0]["paths"]), 2)
        s = p["shoes"][0]
        self.assertEqual((s["matched"], s["duplicates"]), (1, 1))
        self.assertEqual(p["workspace_with_id"], 3)
        self.assertIn("DOUBLONS", B.render_report(p))

    def test_4_new_slug_never_reuses_gear_id_declared_in_activities(self):
        files = [ws(1, "2026-03-01"), ws(5, "2026-03-02", gear_id="hoka", source="chat")]
        p = make_plan([shoe(name="Hoka")], {U1: [gact(1, "2026-03-01")]}, files)
        s = p["shoes"][0]
        self.assertEqual(s["gear_id"], "hoka-2")
        self.assertEqual(s["name_matches"], ["hoka"])
        self.assertEqual(p["assignments"][0]["gear_id"], "hoka-2")
        self.assertIn("déclarent déjà", B.render_report(p))

    def test_4_prefix_name_match_is_reported(self):
        files = [ws(1, "2026-03-01"), ws(5, "2026-03-02", gear_id="hoka", source="chat")]
        s = make_plan([shoe()], {U1: [gact(1, "2026-03-01")]}, files)["shoes"][0]
        self.assertEqual(s["name_matches"], ["hoka"])


class TestReviewMinor(unittest.TestCase):
    def test_5_uuidless_bullet_of_same_shoe_is_linked_not_duplicated(self):
        profile = "### Chaussures\n- Nike Pegasus 41 — id: pegasus\n- Autre — id: autre\n"
        p = make_plan([shoe(U1, "Nike Pegasus 41")], {U1: [gact(1, "2026-03-01")]}, [ws(1, "2026-03-01")], profile)
        s = p["shoes"][0]
        self.assertEqual((s["status"], s["gear_id"], p["new_bullets"]), ("link_existing", "pegasus", []))
        self.assertEqual(p["links"], [{"uuid": U1, "gear_id": "pegasus", "name": "Nike Pegasus 41"}])
        self.assertEqual(p["assignments"][0]["gear_id"], "pegasus")
        self.assertIsNone(s["depart_km"])
        self.assertIn("garmin:", B.render_report(p))

    def test_5_slug_match_via_gear_id_and_ambiguity(self):
        profile = "### Chaussures\n- Pegasus — id: nike-pegasus-41\n"
        p = make_plan([shoe(U1, "Nike Pegasus 41")], {U1: [gact(1, "2026-03-01")]}, [ws(1, "2026-03-01")], profile)
        self.assertEqual(p["shoes"][0]["status"], "link_existing")
        profile = "### Chaussures\n- Nike Pegasus 41 — id: a\n- Nike Pegasus 41 — id: b\n"
        p = make_plan([shoe(U1, "Nike Pegasus 41")], {U1: [gact(1, "2026-03-01")]}, [ws(1, "2026-03-01")], profile)
        self.assertEqual(p["shoes"][0]["status"], "name_ambiguous")
        self.assertEqual((p["assignments"], p["new_bullets"], p["links"]), ([], [], []))

    def test_5_append_segment_only_touches_that_bullet(self):
        text = ("## Matériel & lieux\n\n### Chaussures\n\n- Nike Pegasus 41 — id: pegasus (par défaut)\n"
                "  - alerte 500 km\n- Autre — id: autre\n\n### Matériel\n")
        out = B.append_garmin_segment(text, "pegasus", U1)
        self.assertEqual(out, text.replace("id: pegasus (par défaut)", f"id: pegasus (par défaut) — garmin: {U1}", 1))
        parsed = {g["gear_id"]: g for g in L.parse_gear(out)}
        self.assertEqual(parsed["pegasus"]["garmin_uuid"], U1)
        self.assertTrue(parsed["pegasus"]["default"])
        self.assertIsNone(B.append_garmin_segment(text, "absent", U1))
        self.assertIsNone(B.append_garmin_segment(text.replace("id: autre", "id: pegasus"), "pegasus", U1))

    def test_5_apply_links_existing_bullet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "planning").mkdir()
            prof = root / "planning" / "Runner_Profile.md"
            prof.write_text("# P\n\n## Matériel & lieux\n\n### Chaussures\n\n- Nike Pegasus 41 — id: pegasus\n",
                            encoding="utf-8")
            write_activity(root, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=1000)
            p = B.plan(B.normalize_shoes([shoe(U1, "Nike Pegasus 41")]), {U1: acts(gact(1, "2026-03-01"))},
                       B.scan_workspace(root), L.parse_gear(prof.read_text()))
            out = B.apply_plan(root, prof, p)
            self.assertEqual((out["profile_written"], out["linked"], out["failed"]), (True, ["pegasus"], []))
            self.assertIn(f"id: pegasus — garmin: {U1}\n", prof.read_text())
            self.assertEqual(prof.read_text().count("Nike Pegasus 41"), 1)
            self.assertEqual(C.extract_block((root / "activities/2026-03-01_trail.md").read_text())["gear_id"], "pegasus")

    def test_9_pagination_stops_when_start_is_ignored(self):
        class Stub:
            garmin_connect_activities_baseurl = "u/"
            calls = 0

            def get_gear_activities(self, uuid, limit=1000):
                return [{"activityId": i} for i in range(1000)]

            def connectapi(self, url):
                Stub.calls += 1
                return [{"activityId": i} for i in range(1000)]   # ignore `start`

        out = B.GarminSource(Stub()).gear_activities(U1)
        self.assertTrue(out["truncated"])
        self.assertEqual((len(out["activities"]), Stub.calls), (1000, 1))

    def test_9_pagination_follows_real_pages_and_caps(self):
        class Paged:
            garmin_connect_activities_baseurl = "u/"

            def get_gear_activities(self, uuid, limit=1000):
                return [{"activityId": i} for i in range(1000)]

            def connectapi(self, url):
                start = int(url.split("start=")[1].split("&")[0])
                return [{"activityId": i} for i in range(start, min(start + 1000, 2300))]

        out = B.GarminSource(Paged()).gear_activities(U1)
        self.assertEqual((len(out["activities"]), out["truncated"]), (2300, False))

        class Endless(Paged):
            def connectapi(self, url):
                start = int(url.split("start=")[1].split("&")[0])
                return [{"activityId": i} for i in range(start, start + 1000)]

        out = B.GarminSource(Endless()).gear_activities(U1)
        self.assertTrue(out["truncated"])
        self.assertLessEqual(len(out["activities"]), 1000 * (B.GEAR_ACTIVITIES_MAX_PAGES + 1))

    def test_nit_profile_id_called_once_and_error_payload_is_error(self):
        calls = []

        class C1:
            def get_device_last_used(self):
                calls.append(1)
                return {"userProfileNumber": 7}

            def get_gear(self, pid):
                return {"error": "unauthorized"}

            def get_gear_defaults(self, pid):
                return []
        src = B.GarminSource(C1())
        with self.assertRaises(RuntimeError):
            src.gear()
        src.defaults()
        self.assertEqual(len(calls), 1)

    def test_nit_inconsistent_source_without_gear_id_left_untouched(self):
        files = [ws(1, "2026-03-01", source="chat")]
        p = make_plan([shoe()], {U1: [gact(1, "2026-03-01")]}, files)
        self.assertEqual(p["assignments"], [])
        self.assertEqual(p["inconsistent"][0]["gear_source"], "chat")
        self.assertIn("INCOHÉRENTS", B.render_report(p))


class TestReviewIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / "planning").mkdir()
        self.profile = self.ws / "planning" / "Runner_Profile.md"
        self.profile.write_text("# P\n\n## Matériel & lieux\n", encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def plan_for(self, per=None):
        per = per or {U1: [gact(1, "2026-03-01")]}
        return B.plan(B.normalize_shoes([shoe()]), {u: acts(*v) for u, v in per.items()},
                      B.scan_workspace(self.ws), L.parse_gear(self.profile.read_text()))

    def test_6_crlf_profile_and_mode_preserved(self):
        import os
        raw = ("# P\r\n\r\n## Matériel & lieux\r\n\r\n### Chaussures\r\n\r\n- Vieille — id: vieille\r\n\r\n"
               "### Matériel\r\n- x\r\n").encode("utf-8")
        self.profile.write_bytes(raw)
        os.chmod(self.profile, 0o600)
        write_activity(self.ws, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=1000)
        act = self.ws / "activities/2026-03-01_trail.md"
        os.chmod(act, 0o640)
        out = B.apply_plan(self.ws, self.profile, self.plan_for())
        self.assertEqual(out["failed"], [])
        new = self.profile.read_bytes()
        self.assertTrue(new.startswith(raw[:raw.index(b"\r\n\r\n### Mat")]))
        self.assertNotIn(b"\n", new.replace(b"\r\n", b""))            # aucun LF nu introduit
        self.assertIn(b"- Vieille \xe2\x80\x94 id: vieille\r\n- Hoka", new)
        self.assertEqual([g["gear_id"] for g in L.parse_gear(new.decode())], ["vieille", "hoka-speedgoat-5"])
        self.assertEqual(oct(os.stat(self.profile).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(act).st_mode & 0o777), "0o640")
        self.assertFalse(list(self.ws.rglob("*.tmp-gearbackfill")))

    def test_6_crlf_profile_creating_subsection_stays_crlf(self):
        self.profile.write_bytes(b"# P\r\n\r\n## Mat\xc3\xa9riel & lieux\r\n\r\n- Lieu : T\r\n")
        out = B.insert_gear_bullets(self.profile.read_bytes().decode(), [f"- Hoka — id: hoka — garmin: {U1}"])
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertEqual([g["gear_id"] for g in L.parse_gear(out)], ["hoka"])

    def test_12_headings_match_arc_legacy_on_crlf(self):
        text = "## Matériel & lieux\r\n### Chaussures\r\n- A — id: a\r\n"
        self.assertEqual(len(L.parse_gear(text)), 1)
        out = B.insert_gear_bullets(text, [f"- B — id: b — garmin: {U1}"])
        self.assertEqual([g["gear_id"] for g in L.parse_gear(out)], ["a", "b"])
        self.assertEqual(out.count("### Chaussures"), 1)

    def test_6_rollback_is_byte_identical_only_when_written(self):
        write_activity(self.ws, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=1000)
        act = self.ws / "activities/2026-03-01_trail.md"
        import os
        os.chmod(act, 0o600)
        original = act.read_bytes()
        calls = []

        def validate(_p):
            calls.append(1)
            return (len(calls) == 1, ["non"], [])
        out = B.apply_plan(self.ws, self.profile, self.plan_for(), validate=validate)
        self.assertEqual(act.read_bytes(), original)
        self.assertEqual(oct(os.stat(act).st_mode & 0o777), "0o600")
        self.assertEqual(len(out["failed"]), 1)

    def test_8_already_invalid_file_is_reported_apart_and_untouched(self):
        write_activity(self.ws, "2026-03-01_trail.md", garmin_activity_id=1, distance_m=1000)
        act = self.ws / "activities/2026-03-01_trail.md"
        original = act.read_bytes()
        out = B.apply_plan(self.ws, self.profile, self.plan_for(), validate=lambda _p: (False, ["hors contrat"], []))
        self.assertEqual((out["failed"], out["written"]), ([], []))
        self.assertEqual(out["out_of_contract"][0]["path"], "activities/2026-03-01_trail.md")
        self.assertIn("/arc-backfill", out["out_of_contract"][0]["reason"])
        self.assertEqual(act.read_bytes(), original)

    def test_7_unmapped_replacement_is_byte_minimal(self):
        text = ('# T\n\n```arc\n{\n  "arc": 1, "kind": "activity", "date": "2026-03-01",\n'
                '  "gear_source": "garmin_unmapped", "sport": "trail",   "duration_s": 60, "name": "é"\n}\n```\n\nTexte\n')
        out = B.set_block_keys(text, {"gear_id": "x", "gear_source": "garmin"})
        self.assertEqual(out, text.replace('"garmin_unmapped"', '"garmin"').replace(
            '"name": "é"\n}', '"name": "é",\n  "gear_id": "x"\n}'))
        single = ('```arc\n{"arc": 1, "kind": "activity", "date": "2026-03-01", "sport": "trail", "duration_s": 60, '
                  '"gear_source": "garmin_unmapped"}\n```\n')
        out = B.set_block_keys(single, {"gear_id": "x", "gear_source": "garmin"})
        self.assertEqual(out, single.replace("garmin_unmapped", "garmin").replace(
            '"garmin"}', '"garmin", "gear_id": "x"}'))

    def test_nit_insertion_cosmetics(self):
        text = "## Matériel & lieux\n- Lieu : T\n### Matériel\n- x\n"
        out = B.insert_gear_bullets(text, [f"- Hoka — id: hoka — garmin: {U1}"])
        self.assertIn("- Lieu : T\n\n### Chaussures\n", out)
        self.assertNotIn("\n\n\n", out)
        self.assertEqual(text.replace("- Lieu : T\n", "- Lieu : T\n", 1).count("###"), 1)

    def test_nit_relaunch_guard_prevents_ping_pong(self):
        import os
        import subprocess
        code = ("import sys,os; sys.path.insert(0,%r); sys.modules['garminconnect']=None; import garmin_gear_backfill as B; "
                "B._auto_relaunch([])" % str(REPO / "scripts"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env=dict(os.environ, ARC_GEAR_BACKFILL_RELAUNCHED="1"))
        self.assertEqual(r.returncode, B.EXIT_USAGE)
        self.assertIn("même après relance", r.stderr)


class TestRelaunchCandidates(unittest.TestCase):
    """Linux : `bin/python` d'un venv uv est un LIEN vers le python système ; le venv se reconnaît à `pyvenv.cfg`."""

    def setUp(self):
        import os
        sys.path.insert(0, str(REPO / "skills/fit-download/scripts"))
        import download_fit as D
        self.mods = (B, D)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.venv = Path(self.tmp.name) / "garmin-mcp"
        (self.venv / "bin").mkdir(parents=True)
        (self.venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        os.symlink(sys.executable, self.venv / "bin" / "python")          # python -> python système
        os.symlink("python", self.venv / "bin" / "python3")               # python3 -> python

    def test_symlinked_venv_python_is_not_the_current_interpreter(self):
        for m in self.mods:
            self.assertFalse(m.is_current_interpreter(str(self.venv / "bin/python3"), "/usr", sys.executable))
            self.assertFalse(m.is_current_interpreter(str(self.venv / "bin/python"), sys.prefix, sys.executable) and
                             str(self.venv) != sys.prefix)

    def test_venv_is_recognised_as_current_when_prefix_is_that_venv(self):
        for m in self.mods:
            self.assertTrue(m.is_current_interpreter(str(self.venv / "bin/python3"), str(self.venv), sys.executable))

    def test_without_pyvenv_cfg_falls_back_to_realpath(self):
        import os
        plain = Path(self.tmp.name) / "plain/bin"
        plain.mkdir(parents=True)
        os.symlink(sys.executable, plain / "python3")
        for m in self.mods:
            self.assertTrue(m.is_current_interpreter(str(plain / "python3"), "/nowhere", sys.executable))

    def test_symlinked_venv_is_chosen_as_candidate(self):
        for m in self.mods:
            chosen = m.pick_relaunch_candidate(
                [str(self.venv / "bin/python3"), str(self.venv / "bin/python")], prefix="/usr", executable=sys.executable)
            self.assertEqual(chosen, str(self.venv / "bin/python3"))
            self.assertIsNone(m.pick_relaunch_candidate([str(self.venv / "bin/python3")], prefix=str(self.venv),
                                                        executable=sys.executable))

    def test_candidate_order_includes_python_and_python3(self):
        for m in self.mods:
            cands = m.relaunch_candidates("~/mon-python", "/x/venv/bin/garmin-mcp", home="/h")
            self.assertEqual(cands[0], str(Path("~/mon-python").expanduser()))
            self.assertEqual([Path(c).name for c in cands[1:3]], ["python3", "python"])
            self.assertEqual(cands[3:], ["/h/.local/share/uv/tools/garmin-mcp/bin/python3",
                                         "/h/.local/share/uv/tools/garmin-mcp/bin/python"])


if __name__ == "__main__":
    unittest.main()
