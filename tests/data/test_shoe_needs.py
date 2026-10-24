"""Palier D — moteur de règles du choix des chaussures (#301, épopée #297) : `arc_shoe_needs` et
`arc_index.py shoe-needs` sur des workspaces bâtis avec le VRAI indexeur (profil, fiches `shoe_spec` avec
bilan de retraite, séances, météo, santé).

Fixtures SYNTHÉTIQUES, workspaces temporaires passés en `--workspace`, base en mémoire : jamais le
workspace réel. Un test par règle ; sortie déterministe, lecture seule, aucune marque ni modèle.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_shoe_needs as SN  # noqa: E402

TODAY = "2026-10-23"
URL = "https://example.org/lab/pair"
PROFILE = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
           "- Route A — usage: route — id: road-a\n- Route B — usage: route — id: road-b\n"
           "- Trail A — usage: trail — id: trail-a\n- Trail B — usage: trail — id: trail-b\n")
BRAND_WORDS = ("salomon", "kiprun", "kipride", "hoka", "nike", "adidas", "asics", "brooks", "altra", "saucony",
               "ultra glide", "vaporfly", "marque-test", "modele-test")


def block_file(data: dict) -> str:
    return f"# Fichier\n\n```arc\n{json.dumps(data, ensure_ascii=False)}\n```\n\nTexte.\n"


def day(offset: int, base: str = "2026-09-01") -> str:
    return (date.fromisoformat(base) + timedelta(days=offset)).isoformat()


def meas(value, source="measured", **extra) -> dict:
    d = {"value": value, "source_type": source}
    if source != "athlete":
        d.update({"url": URL, "retrieved": "2026-10-12"})
    d.update(extra)
    return d


def spec(gear_id: str, drop=8.0, stack=34.0, weight=260.0, toe="standard", lug=None, verdict=None, **extra) -> dict:
    data = {"arc": 1, "kind": "shoe_spec", "date": "2026-10-12", "gear_id": gear_id, "brand": "Marque-Test",
            "model": "Modele-Test", "drop_mm": meas(drop), "stack_heel_mm": meas(stack), "weight_g": meas(weight),
            "toe_box": meas(toe, "manufacturer"),
            "flexibility_longitudinal": meas(1.0, "athlete"), "flexibility_torsional": meas(1.0, "athlete"),
            "stability_devices": meas(0, "athlete")}
    if lug is not None:
        data["lug_depth_mm"] = meas(lug)
    if verdict:
        data["verdict"] = verdict
    data.update(extra)
    return data


def verdict(rebuy="yes", comfort=8, change=None) -> dict:
    v = {"date": "2026-10-01", "comfort_overall": comfort, "would_rebuy": rebuy}
    if change:
        v["change_wanted"] = change
    return v


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.write("planning/Runner_Profile.md", PROFILE)

    def write(self, rel: str, text: str) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def put_spec(self, data: dict) -> None:
        self.write(f"gear/specs/{data['gear_id']}.md", block_file(data))

    def run_(self, d: str, gear_id=None, sport="running", km=10.0, dur=3000, gain=None, **extra):
        data = {"arc": 1, "kind": "activity", "date": d, "sport": sport, "distance_m": km * 1000, "duration_s": dur}
        if gear_id:
            data["gear_id"] = gear_id
        if gain is not None:
            data["elevation_gain_m"] = gain
        data.update(extra)
        self.write(f"activities/{d}_{sport}.md", block_file(data))

    def pain(self, d: str, location: str, score=4):
        self.write(f"medical/{d}_health.md", block_file({
            "arc": 1, "kind": "health", "date": d, "morning_check": "full", "pain": [{"location": location, "score": score}]}))

    def weight(self, d: str, kg: float):
        self.write(f"medical/{d}_health.md", block_file({
            "arc": 1, "kind": "health", "date": d, "morning_check": "full", "weight_kg": kg}))

    def rain(self, d: str, mm: float):
        self.write(f"medical/{d}_meteo.md", block_file({
            "arc": 1, "kind": "weather", "date": d, "location": "Lille", "category": "yellow", "precip_mm": mm}))

    def cli(self, *extra) -> tuple:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", TODAY, "shoe-needs", *extra])
        return code, buf.getvalue()

    def needs(self, role: str, replace=None) -> dict:
        args = ["--role", role] + (["--replace", replace] if replace else [])
        code, out = self.cli(*args)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def snapshot(self) -> dict:
        return {str(p.relative_to(self.ws)): p.read_bytes() for p in sorted(self.ws.rglob("*")) if p.is_file()}


class TestRulesLint(unittest.TestCase):
    def test_shipped_rules_are_valid(self):
        self.assertEqual(SN.validate_rules(json.loads(SN.RULES_FILE.read_text(encoding="utf-8"))), [])

    def test_missing_confidence_or_reference_is_refused(self):
        doc = json.loads(SN.RULES_FILE.read_text(encoding="utf-8"))
        bad = copy.deepcopy(doc)
        bad["rules"][1].pop("confidence")
        self.assertTrue(any("confidence" in e for e in SN.validate_rules(bad)))
        bad = copy.deepcopy(doc)
        next(r for r in bad["rules"] if r["id"] == "continuity_drop")["references"] = []
        self.assertTrue(any("au moins une référence" in e for e in SN.validate_rules(bad)))
        bad = copy.deepcopy(doc)
        next(r for r in bad["rules"] if r["id"] == "terrain_lugs_hard").pop("rationale")
        self.assertTrue(any("rationale" in e for e in SN.validate_rules(bad)))
        bad = copy.deepcopy(doc)
        next(r for r in bad["rules"] if r["id"] == "continuity_drop")["references"] = ["inconnue"]
        self.assertTrue(any("inconnue" in e for e in SN.validate_rules(bad)))


class TestNoReference(Workspace):
    def test_broad_ranges_and_insufficient_data(self):
        rep = self.needs("road_easy")
        self.assertTrue(rep["insufficient_data"])
        self.assertEqual(rep["references"], [])
        t = rep["targets"]
        self.assertEqual((t["drop_mm"]["min"], t["drop_mm"]["max"]), (0.0, 12.0))
        self.assertEqual((t["stack_heel_mm"]["min"], t["stack_heel_mm"]["max"]), (15.0, 45.0))
        self.assertEqual(t["toe_box"]["allowed"], ["narrow", "standard", "wide"])
        self.assertTrue(any("données insuffisantes" in w for w in rep["warnings"]))
        self.assertIn("insufficient_reference", [r["id"] for r in rep["rules_applied"]])
        self.assertNotIn("comfort_first", [r["id"] for r in rep["rules_applied"]])
        self.assertEqual(t["drop_mm"]["confidence"], "none")

    def test_comfort_below_threshold_or_rebuy_no_is_not_a_reference(self):
        self.put_spec(spec("road-a", verdict=verdict("yes", comfort=6)))
        self.put_spec(spec("road-b", verdict=verdict("no", comfort=9)))
        self.assertTrue(self.needs("road_easy")["insufficient_data"])


class TestContinuity(Workspace):
    def setUp(self):
        super().setUp()
        self.put_spec(spec("road-a", drop=8.0, stack=34.0, verdict=verdict("yes", 8)))
        self.put_spec(spec("road-b", drop=4.0, stack=30.0, verdict=verdict("no", 3)))

    def test_drop_stack_and_minimalist_index_within_tolerance_of_reference(self):
        rep = self.needs("road_easy")
        self.assertFalse(rep["insufficient_data"])
        self.assertEqual([r["gear_id"] for r in rep["references"]], ["road-a"])
        t = rep["targets"]
        self.assertEqual((t["drop_mm"]["min"], t["drop_mm"]["max"]), (4.0, 12.0))
        self.assertEqual((t["stack_heel_mm"]["min"], t["stack_heel_mm"]["max"]), (28.0, 40.0))
        mi = I.shoe_specs(I.open_db(self.ws, memory=True))  # noqa: F841 — l'index est calculé par arc_shoes
        self.assertIn("continuity_drop", t["drop_mm"]["rules"])
        self.assertEqual(t["drop_mm"]["confidence"], "moderate")
        self.assertTrue(t["drop_mm"]["references"])

    def test_minimalist_index_range(self):
        rep = self.needs("road_easy")
        mi = rep["targets"]["minimalist_index_pct"]
        # poids 260 g -> 2, pile 34 -> 0, drop 8 -> 2, flexibilité 2, stabilité 5 : somme 11 -> 44 %
        self.assertEqual((mi["min"], mi["max"]), (24.0, 64.0))
        self.assertIn("continuity_minimalist_index", mi["rules"])

    def test_measured_value_is_the_reference(self):
        # drop annoncé 6 mm mais mesuré 8,7 mm : la valeur retenue est la mesure
        data = spec("road-a", verdict=verdict("yes", 8))
        data["drop_mm"] = meas(8.7, alternatives=[{"value": 6, "source_type": "manufacturer", "url": URL,
                                                   "retrieved": "2026-10-12"}])
        self.put_spec(data)
        t = self.needs("road_easy")["targets"]["drop_mm"]
        self.assertEqual((t["min"], t["max"]), (4.7, 12.0))

    def test_manufacturer_drop_is_flagged(self):
        data = spec("road-a", verdict=verdict("yes", 8))
        data["drop_mm"] = meas(6.0, "manufacturer")
        self.put_spec(data)
        rep = self.needs("road_easy")
        self.assertTrue(any("annoncée par la marque" in w for w in rep["warnings"]))

    def test_softness_default_and_gait_not_a_criterion(self):
        rep = self.needs("road_easy")
        self.assertEqual(rep["targets"]["midsole_softness"]["allowed"], ["soft", "moderate"])
        self.assertTrue(any("jamais un critère de choix" in n for n in rep["notes"]))
        self.assertTrue(any("prescription" in n for n in rep["notes"]))

    def test_rotation_reminder(self):
        rep = self.needs("road_easy")
        self.assertTrue(any("au moins 2 paires" in r["text"] for r in rep["reminders"]))


class TestInjuryGuards(Workspace):
    def setUp(self):
        super().setUp()
        self.put_spec(spec("road-a", drop=8.0, stack=34.0, verdict=verdict("yes", 8)))
        self.put_spec(spec("road-b", drop=8.0, stack=34.0))

    def test_achilles_history_never_lowers_the_drop(self):
        self.pain(day(0), "tendon d'Achille gauche", 4)
        rep = self.needs("road_easy", "road-b")
        t = rep["targets"]["drop_mm"]
        self.assertGreaterEqual(t["min"], 8.0)
        self.assertIn("achilles_calf_no_drop_decrease", t["rules"])
        self.assertEqual(rep["inputs"]["injury_history"]["zones"], {"tendon_achille": 1})

    def test_calf_history_counts_too(self):
        self.pain(day(0), "mollet droit", 3)
        self.assertGreaterEqual(self.needs("road_easy", "road-b")["targets"]["drop_mm"]["min"], 8.0)

    def test_without_history_drop_can_go_down(self):
        self.assertEqual(self.needs("road_easy", "road-b")["targets"]["drop_mm"]["min"], 4.0)

    def test_achilles_prevails_over_less_drop_wish(self):
        self.pain(day(0), "tendon d'Achille", 4)
        self.put_spec(spec("road-b", drop=8.0, verdict=verdict("yes_with_change", 8, ["less_drop"])))
        t = self.needs("road_easy", "road-b")["targets"]["drop_mm"]
        self.assertGreaterEqual(t["min"], 8.0)
        self.assertIn("change_wanted_adjust", t["rules"])

    def test_repeated_ankle_pain_lowers_stack_and_requires_a_wide_base(self):
        self.pain(day(0), "cheville gauche", 4)
        self.pain(day(20), "cheville gauche", 5)
        rep = self.needs("road_easy", "road-b")
        self.assertLessEqual(rep["targets"]["stack_heel_mm"]["max"], 34.0)
        self.assertTrue(any("douleurs répétées à la cheville" in r for r in rep["targets"]["stack_heel_mm"]["reasons"]))
        self.assertFalse(any("entorse" in r for r in rep["targets"]["stack_heel_mm"]["reasons"]))
        self.assertNotIn("narrow", rep["targets"]["toe_box"]["allowed"])
        self.assertEqual(rep["targets"]["stack_heel_mm"]["confidence"], "none")   # continuité (none) + experts
        self.assertIn("ankle_sprain_low_stack_wide_base", rep["targets"]["stack_heel_mm"]["rules"])

    def test_single_ankle_episode_is_not_enough(self):
        self.pain(day(0), "cheville gauche", 4)
        rep = self.needs("road_easy", "road-b")
        self.assertNotIn("ankle_sprain_low_stack_wide_base", rep["targets"]["stack_heel_mm"]["rules"])

    def test_heavy_runner_caution_on_minimalism(self):
        self.weight(day(0), 80.0)
        rep = self.needs("road_easy")
        mi = rep["targets"]["minimalist_index_pct"]
        self.assertEqual(mi["max"], 44.0)                                # plafonné à la référence
        self.assertIn("mass_minimalism_caution", mi["rules"])
        self.assertTrue(any("ne change jamais l'amorti" in n for n in rep["notes"]))
        self.assertEqual(rep["targets"]["midsole_softness"]["allowed"], ["soft", "moderate"])

    def test_light_runner_has_no_minimalism_cap(self):
        self.weight(day(0), 62.0)
        self.assertEqual(self.needs("road_easy")["targets"]["minimalist_index_pct"]["max"], 64.0)


class TestProfileHistory(Workspace):
    """Antécédents déclarés dans les puces du profil (et non dans health.pain) : jamais ignorés."""

    def profile(self, history="", fragile=""):
        self.write("planning/Runner_Profile.md", PROFILE + "\n## Historique & blessures\n\n- **Meilleures performances** :\n"
                   f"- **Antécédents de blessure** : {history}\n- **Zones fragiles à surveiller** : {fragile}\n"
                   "- **Arrêts récents** :\n")

    def setUp(self):
        super().setUp()
        self.put_spec(spec("road-a", drop=6.0, stack=34.0, verdict=verdict("yes", 8)))
        self.put_spec(spec("road-b", drop=6.0, stack=34.0))

    def test_profile_achilles_blocks_a_lower_drop(self):
        self.profile(history="tendon d'Achille gauche")
        rep = self.needs("road_easy", "road-b")
        self.assertGreaterEqual(rep["targets"]["drop_mm"]["min"], 6.0)
        self.assertIn("achilles_calf_no_drop_decrease", rep["targets"]["drop_mm"]["rules"])
        hist = rep["inputs"]["injury_history"]
        self.assertEqual(hist["zones"], {"tendon_achille": 1})
        self.assertEqual({s["source"] for s in hist["sources"]}, {"health", "profile"})
        self.assertEqual(next(s for s in hist["sources"] if s["source"] == "profile")["entries"], 1)
        self.assertIn("period", next(s for s in hist["sources"] if s["source"] == "health"))
        self.assertTrue(any("profil" in r for r in rep["targets"]["drop_mm"]["reasons"]))

    def test_fragile_zones_bullet_and_several_items(self):
        self.profile(history="aucun", fragile="mollet droit ; cheville droite (proprioception)")
        rep = self.needs("road_easy", "road-b")
        self.assertEqual(rep["inputs"]["injury_history"]["zones"], {"cheville": 1, "mollet": 1})
        self.assertGreaterEqual(rep["targets"]["drop_mm"]["min"], 6.0)
        # une zone fragile n'est pas une entorse déclarée : pas de règle de cheville
        self.assertNotIn("ankle_sprain_low_stack_wide_base", rep["targets"]["stack_heel_mm"]["rules"])

    def test_declared_sprain_triggers_the_ankle_rule(self):
        self.profile(history="entorse de la cheville droite en 2024")
        rep = self.needs("road_easy", "road-b")
        self.assertIn("ankle_sprain_low_stack_wide_base", rep["targets"]["stack_heel_mm"]["rules"])
        self.assertTrue(any("entorse de cheville déclarée" in r for r in rep["targets"]["stack_heel_mm"]["reasons"]))
        self.assertLessEqual(rep["targets"]["stack_heel_mm"]["max"], 34.0)

    def test_no_history_is_said_with_sources_read(self):
        self.profile(history="<!-- rien -->", fragile="")
        rep = self.needs("road_easy", "road-b")
        self.assertEqual(rep["inputs"]["injury_history"]["entries"], 0)
        self.assertTrue(any("aucun antécédent de blessure trouvé" in n for n in rep["notes"]))
        _, out = self.cli("--role", "road_easy", "--replace", "road-b", "--text")
        self.assertIn("Antécédents lus", out)
        self.assertIn("aucun antécédent trouvé", out)

    def test_unrecognised_zone_is_reported_not_guessed(self):
        self.profile(history="torticolis récurrent")
        rep = self.needs("road_easy", "road-b")
        self.assertTrue(any("sans zone reconnue" in n for n in rep["notes"]))

    def test_ankle_pain_needs_severity_and_same_side(self):
        self.pain(day(0), "cheville gauche", 3)
        self.pain(day(10), "cheville gauche", 3)
        self.assertNotIn("ankle_sprain_low_stack_wide_base", self.needs("road_easy", "road-b")["targets"]["stack_heel_mm"]["rules"])
        self.pain(day(20), "cheville gauche", 5)
        self.pain(day(30), "cheville droite", 6)
        self.assertNotIn("ankle_sprain_low_stack_wide_base", self.needs("road_easy", "road-b")["targets"]["stack_heel_mm"]["rules"])
        self.pain(day(40), "cheville gauche", 4)
        self.assertIn("ankle_sprain_low_stack_wide_base", self.needs("road_easy", "road-b")["targets"]["stack_heel_mm"]["rules"])


class TestAdvisoryAndReferences(Workspace):
    def test_replaced_pair_without_verdict_gets_an_advisory_band_only(self):
        self.put_spec(spec("road-b", drop=8.7, stack=34.0))
        rep = self.needs("road_easy", "road-b")
        self.assertTrue(rep["insufficient_data"])
        t = rep["targets"]["drop_mm"]
        self.assertEqual((t["min"], t["max"]), (0.0, 12.0))                       # non contraignant
        self.assertEqual((t["advisory"]["min"], t["advisory"]["max"]), (4.7, 12.7))
        self.assertEqual(t["advisory"]["basis"], "paire remplacée, sans verdict de confort")
        self.assertTrue(any("sans verdict de confort" in w for w in rep["warnings"]))
        _, out = self.cli("--role", "road_easy", "--replace", "road-b", "--text")
        self.assertIn("bande indicative", out)

    def test_no_advisory_without_a_spec_or_with_a_reference(self):
        self.assertNotIn("advisory", self.needs("road_easy", "road-b")["targets"]["drop_mm"])
        self.put_spec(spec("road-a", verdict=verdict("yes", 8)))
        self.assertNotIn("advisory", self.needs("road_easy", "road-b")["targets"]["drop_mm"])

    def test_yes_with_change_is_a_reference_and_its_change_applies(self):
        self.put_spec(spec("road-a", toe="standard", verdict=verdict("yes_with_change", 8, ["wider_toe_box"])))
        rep = self.needs("road_easy")            # sans --replace : le changement vient de la référence
        self.assertEqual([r["gear_id"] for r in rep["references"]], ["road-a"])
        self.assertEqual(rep["targets"]["toe_box"]["allowed"], ["wide"])

    def test_road_roles_never_offer_a_rock_plate(self):
        self.assertNotIn("rock_plate", self.needs("road_easy")["targets"]["plate"]["allowed"])
        self.assertNotIn("rock_plate", self.needs("road_tempo")["targets"]["plate"]["allowed"])
        self.assertIn("rock_plate", self.needs("trail")["targets"]["plate"]["allowed"])

    def test_elision(self):
        import arc_shoe_needs as N
        self.assertEqual(N._de("ultra-glide-3"), "d'ultra-glide-3")
        self.assertEqual(N._de("road-a"), "de road-a")

    def test_race_terrain_note_says_where_it_comes_from(self):
        self.put_spec(spec("road-a", verdict=verdict("yes", 8)))
        for i in range(5):
            self.run_(day(i * 2), "road-a")
        rep = self.needs("race", "road-a")
        self.assertTrue(any("USAGE de la paire remplacée" in n for n in rep["notes"]))


class TestTerrain(Workspace):
    def setUp(self):
        super().setUp()
        self.put_spec(spec("trail-a", drop=6.0, stack=30.0, lug=4.0, verdict=verdict("yes", 8)))
        for i in range(6):                       # trail : 6 sorties, beaucoup de dénivelé
            self.run_(day(i * 3), "trail-a", sport="trail", km=15, dur=7200, gain=900)

    def test_muddy_steep_trail_asks_for_lugs(self):
        for i in range(3):
            self.rain(day(i * 3), 8.0)
        rep = self.needs("trail", "trail-a")
        lug = rep["targets"]["lug_depth_mm"]
        self.assertEqual(lug["min"], 5.0)
        self.assertIn("terrain_lugs_soft", lug["rules"])
        self.assertTrue(any(o["id"] == "rock_plate" for o in rep["options"]))
        self.assertEqual((lug["min"], lug["max"]), (5.0, 5.0))             # continuité 3-5 mm, terrain >= 5 mm
        self.assertIn("continuity_lugs", lug["rules"])

    def test_steep_trail_alone_is_a_proxy(self):
        self.assertEqual(self.needs("trail_long", "trail-a")["targets"]["lug_depth_mm"]["min"], 5.0)

    def test_flat_dry_trail_has_no_lug_constraint(self):
        for i in range(6):
            self.run_(day(i * 3), "trail-a", sport="trail", km=15, dur=7200, gain=100)
        rep = self.needs("trail", "trail-a")
        self.assertNotIn("terrain_lugs_soft", rep["targets"]["lug_depth_mm"]["rules"])
        self.assertEqual((rep["targets"]["lug_depth_mm"]["min"], rep["targets"]["lug_depth_mm"]["max"]), (3.0, 5.0))   # 4 mm +/- 1
        self.assertTrue(any("ne distingue ni la boue ni la roche" in n for n in rep["notes"]))

    def test_road_role_caps_lugs(self):
        rep = self.needs("road_easy", "trail-a")
        self.assertEqual(rep["targets"]["lug_depth_mm"]["max"], 4.0)
        self.assertIn("terrain_lugs_hard", rep["targets"]["lug_depth_mm"]["rules"])
        self.assertTrue(any("plutôt de" in w for w in rep["warnings"]))     # rôle demandé != rôle déduit


class TestChangeWanted(Workspace):
    def test_wider_toe_box(self):
        self.put_spec(spec("road-a", toe="standard", verdict=verdict("yes_with_change", 8, ["wider_toe_box"])))
        rep = self.needs("road_easy", "road-a")
        self.assertEqual(rep["targets"]["toe_box"]["allowed"], ["wide"])
        self.assertIn("change_wanted_adjust", rep["targets"]["toe_box"]["rules"])

    def test_wider_toe_box_conflict_with_reference_is_reported_not_silenced(self):
        self.put_spec(spec("road-a", toe="narrow", verdict=verdict("yes_with_change", 8, ["wider_toe_box"])))
        t = self.needs("road_easy", "road-a")["targets"]["toe_box"]
        self.assertTrue(t.get("conflicts"))

    def test_more_cushion_and_unranged_changes(self):
        self.put_spec(spec("road-a", verdict=verdict("yes_with_change", 8, ["more_cushion", "lighter", "other"])))
        rep = self.needs("road_easy", "road-a")
        self.assertEqual(rep["targets"]["midsole_softness"]["allowed"], ["soft"])
        self.assertGreaterEqual(rep["targets"]["stack_heel_mm"]["min"], 34.0)
        self.assertTrue(any("plus léger" in n for n in rep["notes"]))

    def test_firmer_is_respected_with_a_warning(self):
        self.put_spec(spec("road-a", verdict=verdict("yes_with_change", 8, ["firmer"])))
        rep = self.needs("road_easy", "road-a")
        self.assertEqual(rep["targets"]["midsole_softness"]["allowed"], ["moderate"])
        self.assertTrue(any("plus ferme" in w for w in rep["warnings"]))

    def test_more_drop_less_drop(self):
        self.put_spec(spec("road-a", drop=8.0, verdict=verdict("yes_with_change", 8, ["more_drop"])))
        t = self.needs("road_easy", "road-a")["targets"]["drop_mm"]
        self.assertEqual((t["min"], t["max"]), (8.0, 12.0))
        self.put_spec(spec("road-a", drop=8.0, verdict=verdict("yes_with_change", 8, ["less_drop"])))
        t = self.needs("road_easy", "road-a")["targets"]["drop_mm"]
        self.assertEqual((t["min"], t["max"]), (4.0, 8.0))


class TestRace(Workspace):
    def setUp(self):
        super().setUp()
        self.put_spec(spec("road-a", stack=36.0, verdict=verdict("yes", 8)))
        for i in range(5):
            self.run_(day(i * 2), "road-a")

    def test_race_offers_plate_as_performance_option_with_the_road_stack_limit(self):
        rep = self.needs("race", "road-a")
        opt = next(o for o in rep["options"] if o["id"] == "performance_plate_foam")
        self.assertEqual(opt["kind"], "performance")
        self.assertIn("aucune donnée sur les blessures", opt["text"])
        self.assertEqual(rep["targets"]["stack_heel_mm"]["max"], 40.0)
        self.assertIn("race_stack_limit", rep["targets"]["stack_heel_mm"]["rules"])

    def test_race_without_terrain_does_not_invent_a_limit(self):
        rep = self.needs("race")
        self.assertNotIn("race_stack_limit", rep["targets"]["stack_heel_mm"]["rules"])
        self.assertEqual(rep["targets"]["stack_heel_mm"]["max"], 42.0)          # continuité (36 +/- 6), pas la limite
        self.assertTrue(any("terrain de la course non précisé" in n for n in rep["notes"]))

    def test_non_race_roles_have_no_performance_option(self):
        self.assertFalse(any(o["kind"] == "performance" for o in self.needs("road_easy")["options"]))

    def test_trail_race_has_no_stack_limit(self):
        self.put_spec(spec("trail-a", stack=32.0, verdict=verdict("yes", 8)))
        for i in range(6):
            self.run_(day(i * 3 + 30), "trail-a", sport="trail", km=15, dur=7200, gain=300)
        rep = self.needs("race", "trail-a")
        self.assertTrue(any("pas de limite d'épaisseur" in n for n in rep["notes"]))
        self.assertNotIn("race_stack_limit", rep["targets"]["stack_heel_mm"]["rules"])


class TestOutput(Workspace):
    def setUp(self):
        super().setUp()
        self.put_spec(spec("road-a", verdict=verdict("yes", 8)))
        self.put_spec(spec("trail-a", lug=5.0))
        self.run_(day(0), "road-a")

    def test_deterministic(self):
        a = self.cli("--role", "trail", "--replace", "road-a")
        b = self.cli("--role", "trail", "--replace", "road-a")
        self.assertEqual(a, b)

    def test_no_brand_or_model_in_json_or_text(self):
        for extra in ((), ("--text",)):
            code, out = self.cli("--role", "road_tempo", "--replace", "road-a", *extra)
            self.assertEqual(code, 0)
            for word in BRAND_WORDS:
                self.assertNotIn(word, out.lower(), word)

    def test_every_target_carries_rules_confidence_and_reasons(self):
        for name, t in self.needs("road_easy", "road-a")["targets"].items():
            self.assertTrue(t["rules"], name)
            self.assertIn(t["confidence"], SN.CONFIDENCE_ORDER, name)
            self.assertTrue(t["reasons"], name)

    def test_text_has_references_and_not_medical_advice_mention(self):
        _, out = self.cli("--role", "road_easy", "--replace", "road-a", "--text")
        self.assertIn("pas un avis médical", out)
        self.assertIn("https://", out)
        self.assertIn("Rappel", out)

    def test_json_mentions_disclaimer(self):
        self.assertIn("avis médical", self.needs("road_easy")["disclaimer"])

    def test_read_only(self):
        before = self.snapshot()
        self.cli("--role", "road_easy", "--replace", "road-a")
        self.assertEqual(self.snapshot(), before)

    def test_errors(self):
        code, out = self.cli("--role", "road_easy", "--replace", "inconnue")
        self.assertEqual(code, 1)
        self.assertIn("paire inconnue", json.loads(out)["error"])
        code, out = self.cli("--role", "gravel")          # rôle inconnu : plages larges, jamais une erreur
        self.assertEqual(code, 0)
        rep = json.loads(out)
        self.assertEqual(rep["targets"]["lug_depth_mm"]["rules"], ["broad_defaults"])
        self.assertTrue(any("inconnu de ce moteur" in n for n in rep["notes"]))
        with self.assertRaises(I.ConfigError):
            self.cli()


if __name__ == "__main__":
    unittest.main()
