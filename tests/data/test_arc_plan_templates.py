"""Palier D — gabarits de périodisation (#189) : chaque gabarit livré est conforme,
le validateur attrape les gabarits cassés, la résolution est déterministe aux bornes,
et les seuils de garde-fous copiés dans `arc_plan_templates` suivent ceux du moteur."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_guardrails as GR  # noqa: E402
import arc_plan_templates as PT  # noqa: E402

SHIPPED = {t["id"]: t for t in PT.load_templates()}


def broken(template_id: str = "marathon_trail"):
    return copy.deepcopy(SHIPPED[template_id])


def phase(t: dict, pid: str) -> dict:
    return next(p for p in t["phases"] if p["id"] == pid)


class TestShippedTemplates(unittest.TestCase):
    def test_expected_formats_are_shipped(self):
        self.assertTrue({"trail_court", "marathon_trail", "ultra_80_100", "cent_miles",
                         "route_semi", "route_marathon"} <= set(SHIPPED))

    def test_every_shipped_template_validates(self):
        for tid, t in SHIPPED.items():
            with self.subTest(template=tid):
                self.assertEqual(PT.validate_template(t), [])

    def test_collection_validates(self):
        self.assertEqual(PT.validate_templates(list(SHIPPED.values())), [])

    def test_every_length_resolves_with_taper_last_and_recovery_weeks(self):
        for tid, t in SHIPPED.items():
            for n in range(t["weeks"]["min"], t["weeks"]["max"] + 1):
                with self.subTest(template=tid, weeks=n):
                    weeks = PT.resolve_weeks(t, n, with_recovery=False)
                    self.assertEqual(len(weeks), n)
                    self.assertEqual([w["week"] for w in weeks], list(range(1, n + 1)))
                    kinds = [w["kind"] for w in weeks]
                    first = kinds.index("taper")
                    self.assertTrue(all(k == "taper" for k in kinds[first:]))
                    self.assertEqual(weeks[-1]["phase"], "taper")
                    self.assertEqual(max(w["volume_pct"] for w in weeks), 100.0)
                    if n >= 2 * t["recovery_week"]["every_n_weeks"]:
                        self.assertIn("recovery_week", kinds)

    def test_all_templates_carry_the_project_caveat_and_only_verified_sources(self):
        for tid, t in SHIPPED.items():
            with self.subTest(template=tid):
                self.assertIn("approximation du projet", t["caveat"])
                for src in t["sources"]:
                    self.assertTrue("10.1249/01.MSS.0000074448.73931.11" in src or "10.1123/ijspp.5.3.276" in src, src)

    def test_road_templates_have_no_elevation_and_trail_ones_do(self):
        for tid, t in SHIPPED.items():
            has = all("elevation_pct" in p for p in t["phases"])
            self.assertEqual(has, t["sport"] == "trail", tid)


class TestGuardrailConsistency(unittest.TestCase):
    def test_copied_thresholds_equal_the_engine_defaults(self):
        self.assertEqual(PT.GUARDRAIL_DEFAULTS["r2_volume_increase_max_pct"], GR.DEFAULT_VOLUME_INCREASE_MAX_PCT)
        self.assertEqual(PT.GUARDRAIL_DEFAULTS["r3_elevation_increase_max_pct"], GR.DEFAULT_ELEVATION_INCREASE_MAX_PCT)
        self.assertEqual(PT.GUARDRAIL_DEFAULTS["r6_long_run_share_max_pct"], GR.DEFAULT_LONG_RUN_SHARE_MAX_PCT)
        self.assertEqual(GR.DEFAULT_VOLUME_REFERENCE, "mean4")   # la validation suppose la référence par défaut

    def test_shipped_progressions_never_exceed_r2_against_the_previous_week_either(self):
        # Recontrôle indépendant du validateur : +% semaine à semaine hors retour de semaine allégée.
        limit = GR.DEFAULT_VOLUME_INCREASE_MAX_PCT
        for tid, t in SHIPPED.items():
            for n in (t["weeks"]["min"], t["weeks"]["max"]):
                weeks = PT.resolve_weeks(t, n, with_recovery=False)
                for prev, cur in zip(weeks, weeks[1:]):
                    if cur["kind"] == "build" and prev["kind"] == "build":
                        self.assertLessEqual((cur["volume_pct"] - prev["volume_pct"]) / prev["volume_pct"] * 100,
                                             limit + 1e-6, f"{tid}@{n} semaine {cur['week']}")

    def test_steep_ramp_is_caught_as_r2(self):
        t = broken()
        phase(t, "base")["volume_pct"] = {"start": 50, "end": 60}
        errors = PT.validate_template(t)
        self.assertTrue(any("R2" in e for e in errors), errors)

    def test_steep_elevation_ramp_is_caught_as_r3(self):
        t = broken()
        phase(t, "base")["elevation_pct"] = {"start": 40, "end": 50}
        errors = PT.validate_template(t)
        self.assertTrue(any("R3" in e for e in errors), errors)

    def test_long_run_share_above_r6_is_caught(self):
        t = broken()
        phase(t, "specific")["long_run"]["share_pct"] = 40
        self.assertTrue(any("R6" in e for e in PT.validate_template(t)))

    def test_stricter_workspace_limits_are_honoured(self):
        errors = PT.validate_template(broken(), limits={"r6_long_run_share_max_pct": 25.0})
        self.assertTrue(any("R6" in e for e in errors))

    def test_too_many_quality_sessions_is_caught(self):
        t = broken()
        phase(t, "specific")["quality_sessions"] = 4
        self.assertTrue(PT.validate_template(t))

    def test_lower_workspace_r2_threshold_is_caught(self):
        errors = PT.validate_template(SHIPPED["ultra_80_100"], limits={"r2_volume_increase_max_pct": 3.0})
        self.assertTrue(any("R2" in e for e in errors), errors)

    def test_mean4_reference_matches_arc_guardrails_semantics(self):
        # `_reference_totals("mean4")` divise TOUJOURS par 4 ; avant le bloc = semaine 1.
        vals = [80.0, 84.0, 88.0, 92.0, 96.0]
        self.assertEqual(PT._reference_value(vals, 0, "mean4"), 80.0)
        self.assertEqual(PT._reference_value(vals, 2, "mean4"), (80 + 80 + 80 + 84) / 4)
        self.assertEqual(PT._reference_value(vals, 4, "mean4"), (80 + 84 + 88 + 92) / 4)
        self.assertEqual(PT._reference_value(vals, 3, "previous_week"), 88.0)

    def test_mean4_ramp_is_caught_even_when_each_step_is_small(self):
        # Chaque pas reste ≤ +10 % vs la dernière semaine non allégée, mais la reprise
        # après la semaine allégée dépasse la moyenne de 4 semaines (référence d'arc_guardrails).
        t = broken("trail_court")
        t["recovery_week"]["volume_factor"] = 0.4
        errors = PT.validate_template(t)
        self.assertTrue(any("R2" in e and "mean4" in e for e in errors), errors)

    def test_rounding_matches_arc_guardrails(self):
        # arc_guardrails arrondit le % à 0,1 avant de comparer : +10,04 % n'est pas > 10 %.
        self.assertEqual(GR._pct_increase(110.04, 100.0), 10.0)

    def test_previous_week_reference_rebounds_are_notes_not_problems(self):
        limits = {"r2_volume_reference": "previous_week"}
        for tid, t in SHIPPED.items():
            with self.subTest(template=tid):
                self.assertEqual(PT.validate_template(t, limits), [])
        self.assertTrue(PT.reference_notes(limits))
        self.assertEqual(PT.reference_notes(), [])

    def test_previous_week_reference_still_catches_a_real_jump(self):
        t = broken()
        phase(t, "base")["volume_pct"] = {"start": 70, "end": 92}
        errors = PT.validate_template(t, {"r2_volume_reference": "previous_week"})
        self.assertTrue(any("R2" in e and "previous_week" in e for e in errors), errors)

    def test_peak_from_current_is_the_inverse_of_week_one(self):
        t = SHIPPED["ultra_80_100"]
        weeks = PT.resolve_weeks(t, 20)
        f = PT.peak_from_current(weeks, "trail")
        self.assertAlmostEqual(f["volume_factor"], round(100 / weeks[0]["volume_pct"], 3))
        self.assertIn("elevation_factor", f)
        self.assertNotIn("elevation_factor", PT.peak_from_current(PT.resolve_weeks(SHIPPED["route_semi"], 12), "road"))

    def test_missing_recovery_weeks_is_caught(self):
        t = broken()
        t["recovery_week"]["phases"] = ["base"]
        errors = PT.validate_template(t)
        self.assertTrue(any("semaine allégée" in e for e in errors), errors)


class TestSchemaFailures(unittest.TestCase):
    def check(self, mutate, needle):
        t = broken()
        mutate(t)
        errors = PT.validate_template(t)
        self.assertTrue(any(needle in e for e in errors), (needle, errors))

    def test_unknown_key(self):
        self.check(lambda t: t.update(surprise=1), "clés inconnues")

    def test_unknown_phase_key(self):
        self.check(lambda t: phase(t, "base").update(oops=1), "clés inconnues")

    def test_intensity_must_sum_to_100(self):
        self.check(lambda t: phase(t, "base")["intensity"].update(easy_pct=80), "somme")

    def test_intensity_must_be_polarised(self):
        def mutate(t):
            phase(t, "base")["intensity"] = {"easy_pct": 60, "moderate_pct": 20, "hard_pct": 20}
        self.check(mutate, "polarisée")

    def test_percentage_out_of_bounds(self):
        self.check(lambda t: phase(t, "base").update(volume_pct={"start": 90, "end": 120}), "]0, 100]")

    def test_phase_minima_must_fit_total_minimum(self):
        self.check(lambda t: t["weeks"].update(min=5, default=16), "minima")

    def test_phase_maxima_must_cover_total_maximum(self):
        self.check(lambda t: t["weeks"].update(max=40), "maxima")

    def test_phase_order(self):
        def mutate(t):
            t["phases"].reverse()
        self.check(mutate, "ordre")

    def test_taper_must_decrease(self):
        self.check(lambda t: phase(t, "taper").update(volume_pct={"start": 60, "end": 95}), "taper")

    def test_peak_must_be_100(self):
        def mutate(t):
            phase(t, "specific")["volume_pct"] = {"start": 90, "end": 95}
        self.check(mutate, "pic")

    def test_unknown_strength_emphasis(self):
        self.check(lambda t: phase(t, "base").update(strength="yoga"), "strength")

    def test_road_template_rejects_elevation(self):
        t = broken("route_semi")
        phase(t, "base")["elevation_pct"] = {"start": 90, "end": 92}
        self.assertTrue(any("route" in e for e in PT.validate_template(t)))

    def test_caveat_required(self):
        self.check(lambda t: t.update(caveat="valeurs exactes"), "approximation du projet")

    def test_non_dict(self):
        self.assertTrue(PT.validate_template([]))

    def test_duplicate_ids_and_overlapping_bands(self):
        a, b = broken("trail_court"), broken("trail_court")
        self.assertTrue(any("double" in e for e in PT.validate_templates([a, b])))
        c = broken("marathon_trail")
        c["applies_to"]["distance_km"] = {"min": 20, "max": 60}
        errors = PT.validate_templates([broken("trail_court"), c])
        self.assertTrue(any("chevauchent" in e for e in errors), errors)


class TestResolution(unittest.TestCase):
    def test_resolution_is_deterministic(self):
        t = SHIPPED["ultra_80_100"]
        self.assertEqual(PT.resolve_weeks(t, 19), PT.resolve_weeks(t, 19))

    def test_minimum_length_uses_phase_minima(self):
        t = SHIPPED["marathon_trail"]
        alloc = PT.allocate_phase_weeks(t, t["weeks"]["min"])
        self.assertEqual(alloc, {p["id"]: p["weeks"]["min"] for p in t["phases"] if p["id"] != "recovery"})

    def test_maximum_length_uses_phase_maxima(self):
        t = SHIPPED["marathon_trail"]
        alloc = PT.allocate_phase_weeks(t, t["weeks"]["max"])
        self.assertEqual(sum(alloc.values()), t["weeks"]["max"])
        for p in t["phases"]:
            if p["id"] != "recovery":
                self.assertLessEqual(alloc[p["id"]], p["weeks"]["max"])

    def test_stretch_follows_stretch_order(self):
        t = SHIPPED["marathon_trail"]      # min 12 : 3/4/3/2 ; ordre développement, spécifique, base, affûtage
        self.assertEqual(PT.allocate_phase_weeks(t, 13), {"base": 3, "development": 5, "specific": 3, "taper": 2})
        self.assertEqual(PT.allocate_phase_weeks(t, 14), {"base": 3, "development": 5, "specific": 4, "taper": 2})
        self.assertEqual(PT.allocate_phase_weeks(t, 15), {"base": 4, "development": 5, "specific": 4, "taper": 2})

    def test_out_of_range_refused(self):
        t = SHIPPED["trail_court"]
        for n in (t["weeks"]["min"] - 1, t["weeks"]["max"] + 1, 0, -3):
            with self.assertRaises(PT.PlanTemplateError):
                PT.resolve_weeks(t, n)
        with self.assertRaises(PT.PlanTemplateError):
            PT.resolve_weeks(t, 12.5)

    def test_recovery_week_rule(self):
        t = SHIPPED["trail_court"]
        weeks = PT.resolve_weeks(t, 12, with_recovery=False)
        seen = 0
        for w in weeks:
            if w["kind"] == "recovery_week":
                seen += 1
                self.assertEqual(w["week"] % t["recovery_week"]["every_n_weeks"], 0)
                self.assertLessEqual(w["quality_sessions_max"], 1)
                prev = weeks[w["week"] - 2]
                self.assertAlmostEqual(w["volume_pct"], prev["volume_pct"] * t["recovery_week"]["volume_factor"], delta=0.1)
        self.assertGreater(seen, 0)
        # jamais allégée juste avant l'affûtage
        self.assertNotEqual(weeks[[w["kind"] for w in weeks].index("taper") - 1]["kind"], "recovery_week")

    def test_post_race_recovery_appended_after_the_block(self):
        t = SHIPPED["ultra_80_100"]
        weeks = PT.resolve_weeks(t, 20)
        post = [w for w in weeks if w["post_race"]]
        self.assertEqual([w["week"] for w in post], [21, 22])
        self.assertEqual(len(PT.resolve_weeks(t, 20, with_recovery=False)), 20)

    def test_single_week_phase_uses_end_value(self):
        t = SHIPPED["trail_court"]
        weeks = PT.resolve_weeks(t, 8, with_recovery=False)      # affûtage à 1 semaine
        self.assertEqual(weeks[-1]["volume_pct"], phase(t, "taper")["volume_pct"]["end"])

    def test_match_template_by_distance(self):
        ts = list(SHIPPED.values())
        self.assertEqual(PT.match_template(ts, 21.1, "trail")["id"], "trail_court")
        self.assertEqual(PT.match_template(ts, 30, "trail")["id"], "marathon_trail")   # borne basse incluse
        self.assertEqual(PT.match_template(ts, 29.99, "trail")["id"], "trail_court")   # borne haute exclue
        self.assertEqual(PT.match_template(ts, 100, "trail")["id"], "ultra_80_100")
        self.assertEqual(PT.match_template(ts, 59.9, "trail")["id"], "marathon_trail")
        self.assertEqual(PT.match_template(ts, 60, "trail")["id"], "ultra_80_100")
        self.assertEqual(PT.match_template(ts, 130, "trail")["id"], "cent_miles")
        self.assertEqual(PT.match_template(ts, 21.1, "road")["id"], "route_semi")
        self.assertEqual(PT.match_template(ts, 160, "trail")["id"], "cent_miles")
        self.assertEqual(PT.match_template(ts, 42.2, "road")["id"], "route_marathon")
        self.assertIsNone(PT.match_template(ts, 5, "road"))
        self.assertIsNone(PT.match_template(ts, 500, "trail"))

    def test_get_template_unknown(self):
        with self.assertRaises(PT.PlanTemplateError):
            PT.get_template("nope")

    def test_load_templates_reports_bad_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.json").write_text("{oops", encoding="utf-8")
            with self.assertRaises(PT.PlanTemplateError):
                PT.load_templates(Path(d))


class TestCli(unittest.TestCase):
    def run_cli(self, *args, ok=True, config=None):
        with tempfile.TemporaryDirectory() as ws:
            before = []
            if config is not None:
                (Path(ws) / "config").mkdir()
                (Path(ws) / "config/workspace.toml").write_text(config, encoding="utf-8")
                before = sorted(Path(ws).rglob("*"))
            r = subprocess.run([sys.executable, str(REPO / "scripts/arc_index.py"), "plan-templates",
                                "--workspace", ws, *args], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode == 0, ok, r.stderr)
            self.assertEqual(sorted(Path(ws).rglob("*")), before, "la commande ne doit rien écrire dans le workspace")
            return r

    def test_list(self):
        r = self.run_cli("--text")
        self.assertIn("marathon_trail", r.stdout)
        self.assertIn("conforme", r.stdout)

    def test_json_is_the_default_like_the_other_subcommands(self):
        data = json.loads(self.run_cli().stdout)
        self.assertEqual(data["problems"], [])
        self.assertIn("marathon_trail", {t["id"] for t in data["templates"]})
        # --json l'emporte sur --text
        json.loads(self.run_cli("--format", "trail_court", "--text", "--json").stdout)

    def test_text_detail_shows_the_peak_rule(self):
        self.assertIn("Pic = volume tenu", self.run_cli("--format", "trail_court", "--text").stdout)

    def test_sport_defaults_to_the_workspace_primary_sport(self):
        data = json.loads(self.run_cli("--distance-km", "21.1", config='[sport]\nprimary = "road"\n').stdout)
        self.assertEqual(data["template"]["id"], "route_semi")
        data = json.loads(self.run_cli("--distance-km", "21.1").stdout)
        self.assertEqual(data["template"]["id"], "trail_court")
        data = json.loads(self.run_cli("--distance-km", "21.1", "--sport", "trail",
                                       config='[sport]\nprimary = "road"\n').stdout)
        self.assertEqual(data["template"]["id"], "trail_court")

    def test_workspace_previous_week_reference_is_reported_as_a_note(self):
        data = json.loads(self.run_cli("--format", "marathon_trail",
                                       config='[guardrails]\nr2_volume_reference = "previous_week"\n').stdout)
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["guardrail_limits"]["r2_volume_reference"], "previous_week")
        self.assertTrue(data["notes"])

    def test_json_detail(self):
        data = json.loads(self.run_cli("--format", "cent_miles", "--weeks", "20", "--json").stdout)
        self.assertEqual(data["n_weeks"], 20)
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["weeks"][0]["week"], 1)

    def test_distance_selection_and_no_match(self):
        data = json.loads(self.run_cli("--distance-km", "90", "--json").stdout)
        self.assertEqual(data["template"]["id"], "ultra_80_100")
        self.assertIn("aucun gabarit", self.run_cli("--distance-km", "5", "--sport", "road").stdout)

    def test_out_of_range_weeks_and_unknown_format_fail_cleanly(self):
        self.assertIn("hors de", self.run_cli("--format", "cent_miles", "--weeks", "99", ok=False).stderr)
        self.assertIn("inconnu", self.run_cli("--format", "nope", ok=False).stderr)


if __name__ == "__main__":
    unittest.main()
