"""Palier D — squelette de bloc (#190, #204, `scripts/arc_plan_skeleton.py`).

Volume tenu + objectif synthétiques → squelette qui respecte les proportions du gabarit (#189), passe
`arc_guardrails.evaluate` semaine par semaine, gère `too_short` / mise en route / disponibilité, n'écrase
jamais, et dont les fichiers écrits passent `arc_index.py --validate`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_guardrails as G  # noqa: E402
import arc_index as I  # noqa: E402
import arc_plan_skeleton as PS  # noqa: E402
import arc_plan_templates as PT  # noqa: E402

TODAY = date(2026, 10, 5)                     # lundi
GCONF = G.guardrail_settings({})
TEMPLATES = PT.load_templates()
ULTRA = PT.get_template("ultra_80_100", TEMPLATES)
MARATHON = PT.get_template("marathon_trail", TEMPLATES)
ROUTE = PT.get_template("route_marathon", TEMPLATES)
AVAIL = PS.parse_availability(None)           # profil muet : valeurs par défaut du moteur


def held(hours=6.0, elev=1500.0, distance_km=0.0, weeks=None):
    if weeks:
        return PS.held_from_weeks(weeks, "index")
    return PS.declared_held(hours, elev, distance_km)


def factory(sport="trail", **overrides):
    def make(week_start, prior):
        ctx = PS.synthetic_context(week_start, TODAY, sport)
        ctx.update(overrides)
        return ctx
    return make


def race_after(weeks: int) -> date:
    """Dimanche de la semaine de course, `weeks` semaines (course comprise) à partir de TODAY."""
    return TODAY + timedelta(days=7 * (weeks - 1) + 6)


def build(template=MARATHON, weeks=None, availability=AVAIL, held_=None, sport="trail", gconf=GCONF, today=TODAY,
          context_factory=None, race=None, **kw):
    weeks = weeks or template["weeks"]["default"]
    return PS.build_skeleton(template=template, today=today, race_date=race or race_after(weeks),
                             held=held_ or held(), availability=availability, gconf=gconf,
                             context_factory=context_factory or factory(sport), templates=TEMPLATES, **kw)


class TestProportions(unittest.TestCase):
    def setUp(self):
        self.sk = build()
        self.weeks = self.sk["weeks"]

    def test_status_and_length(self):
        n = MARATHON["weeks"]["default"]
        self.assertEqual(self.sk["status"], "ok")
        self.assertEqual(self.sk["n_weeks"], n)
        self.assertEqual(self.sk["lead_in_weeks"], 0)
        pre = [w for w in self.weeks if w["type"] != "post_race"]
        self.assertEqual(len(pre), n)
        self.assertEqual(self.weeks[0]["week_start"], TODAY.isoformat())
        self.assertEqual(pre[-1]["type"], "race")
        self.assertEqual(pre[-1]["week_start"], (race_after(n) - timedelta(days=6)).isoformat())
        post = [w for w in self.weeks if w["type"] == "post_race"]
        self.assertEqual(len(post), MARATHON["phases"][-1]["weeks"]["min"])

    def test_peak_is_held_volume_times_template_factor(self):
        resolved = PT.resolve_weeks(MARATHON, MARATHON["weeks"]["default"])
        factors = PT.peak_from_current(resolved, "trail")
        self.assertEqual(self.sk["peak"]["volume_factor"], factors["volume_factor"])
        self.assertAlmostEqual(self.sk["peak"]["duration_s"], 6 * 3600 * factors["volume_factor"], delta=1)
        self.assertAlmostEqual(self.sk["peak"]["elevation_m"], 1500 * factors["elevation_factor"], delta=1)
        # Semaine 1 = volume tenu (jamais plus) : 100 / pct1 × pct1 / 100.
        self.assertAlmostEqual(self.weeks[0]["target_duration_s"], 6 * 3600, delta=120)

    def test_weeks_follow_template_percentages(self):
        resolved = PT.resolve_weeks(MARATHON, MARATHON["weeks"]["default"])
        peak = self.sk["peak"]["duration_s"]
        for rec, w in zip(resolved, self.weeks):
            self.assertEqual(w["phase"], rec["phase"])
            self.assertEqual(w["quality_sessions"] <= rec["quality_sessions_max"], True)
            self.assertEqual(w["intensity_split"], rec["intensity"])
            self.assertEqual(w["strength_emphasis"], rec["strength"])
            if not w["adjustments"]:
                # Première semaine post-course (course un dimanche) : 3 jours sans course → 4/7 du gabarit.
                first_post = next(x for x in self.weeks if x["type"] == "post_race")
                prorata = 4 / 7 if w is first_post else 1
                self.assertAlmostEqual(w["target_duration_s"], peak * rec["volume_pct"] / 100.0 * prorata, delta=125)
            expected_type = {"build": "build", "recovery_week": "recovery", "taper": "taper",
                             "post_race": "post_race"}[rec["kind"]]
            if w["type"] != "race":
                self.assertEqual(w["type"], expected_type)

    def test_sessions_sum_to_target_and_carry_week_fields(self):
        for w in self.weeks:
            e = w["entry"]
            runs = [s for s in e["sessions"] if s["sport"] == "trail" and s.get("placeholder")]
            self.assertEqual(sum(s["planned_duration_s"] for s in runs), e["target_duration_s"])
            self.assertTrue(all(s["status"] == "planned" for s in e["sessions"]))
            self.assertEqual(e["week_type"], w["type"])
            self.assertEqual(e["strength_emphasis"], w["strength_emphasis"])

    def test_long_run_share_and_cap(self):
        for w in self.weeks:
            if w["type"] in ("build", "lead_in") and w["long_run_target_s"]:
                self.assertLessEqual(w["long_run_target_s"], w["long_run_cap_min"] * 60)
                self.assertLessEqual(w["long_run_target_s"] / w["target_duration_s"], 0.36)

    def test_deterministic(self):
        self.assertEqual(json.dumps(build(), sort_keys=True), json.dumps(self.sk, sort_keys=True))


class TestGuardrails(unittest.TestCase):
    def test_every_week_passes_the_engine_check_and_none_blocks(self):
        for template in TEMPLATES:
            sport = template["sport"]
            sk = build(template, sport=sport)
            self.assertEqual(sk["status"], "ok", template["id"])
            self.assertTrue(sk["summary"]["block_free"], template["id"])
            for w in sk["weeks"]:
                self.assertTrue(w["guardrails"]["ok"], (template["id"], w["week_start"]))
                self.assertNotEqual(w["guardrails"]["level"], "block")
                self.assertNotIn("r2_weekly_volume_jump", [v["rule_id"] for v in w["guardrails"]["violations"]])
                self.assertNotIn("r3_weekly_elevation_jump", [v["rule_id"] for v in w["guardrails"]["violations"]])

    def test_uses_the_guardrails_own_evaluate(self):
        calls = []
        real = G.evaluate

        def spy(week, ctx, gconf):
            calls.append(week["week_start"])
            return real(week, ctx, gconf)
        with mock.patch.object(G, "evaluate", spy):
            sk = build()
        self.assertGreaterEqual(len(calls), len(sk["weeks"]))
        self.assertEqual(set(calls) >= {w["week_start"] for w in sk["weeks"]}, True)

    def test_reference_is_the_chain_of_generated_weeks(self):
        """Une semaine se compare aux 4 précédentes DU SQUELETTE : l'évaluation indépendante de chaque semaine
        (référence mean4 reconstruite à la main) ne trouve ni R2 ni R3."""
        sk = build()
        chain = [{"duration_s": 6 * 3600.0, "elevation_gain_m": 1500.0, "distance_m": 0.0} for _ in range(4)]
        for w in sk["weeks"]:
            ref = PS._reference(chain, "mean4")
            ctx = PS.synthetic_context(date.fromisoformat(w["week_start"]), TODAY)
            ctx.update(previous_week=PS._reference(chain, "previous_week"), mean4_weeks=ref,
                       race_date=sk["race_date"],
                       is_race_week=w["type"] == "race")
            verdict = G.evaluate({k: v for k, v in w["entry"].items()}, ctx, GCONF)
            self.assertFalse([v for v in verdict["violations"] if v["rule_id"] in
                              ("r2_weekly_volume_jump", "r3_weekly_elevation_jump")], w["week_start"])
            chain.append(PS._run_totals(w["entry"]))

    def test_r2_violation_reduces_the_week_from_the_verdict(self):
        """Référence `previous_week` et dernière semaine tenue très basse : la semaine 1 dépasserait R2 ; le
        générateur la réduit (facteur tiré du verdict) au lieu de l'émettre en `warn`."""
        gconf = dict(GCONF, r2_volume_reference="previous_week")
        weeks = [{"duration_s": 6 * 3600.0, "elevation_gain_m": 1500.0, "distance_m": 0.0}] * 3 + [
            {"duration_s": 3 * 3600.0, "elevation_gain_m": 800.0, "distance_m": 0.0}]
        sk = build(held_=held(weeks=weeks), gconf=gconf)
        first = sk["weeks"][0]
        self.assertTrue(first["adjustments"])
        self.assertLessEqual(first["target_duration_s"], 3 * 3600 * 1.1)
        self.assertNotIn("r2_weekly_volume_jump", [v["rule_id"] for v in first["guardrails"]["violations"]])

    def test_block_verdict_removes_quality_then_reports(self):
        red = {d.isoformat(): "red" for d in (TODAY + timedelta(days=i) for i in range(0, 8))}
        sk = build(context_factory=factory(health_by_date=red))
        first = sk["weeks"][0]
        self.assertEqual(first["quality_sessions"], 0)
        self.assertTrue(any("qualité" in a for a in first["adjustments"]))
        self.assertTrue(first["guardrails"]["ok"])

    def test_persistent_block_week_is_not_emitted(self):
        def always_block(week, ctx, gconf):
            return {"ok": False, "checked_rules": ["r5_quality_after_red"], "skipped_rules": [],
                    "violations": [{"rule_id": "r5_quality_after_red", "severity": "block", "message": "x",
                                    "values": {"observed": 1, "threshold": 0}}]}
        with mock.patch.object(G, "evaluate", always_block):
            sk = build()
        self.assertEqual(sk["status"], "needs_review")
        self.assertEqual(sk["weeks"], [])
        self.assertTrue(sk["unresolved"])
        self.assertTrue(sk["summary"]["block_free"])
        with tempfile.TemporaryDirectory() as tmp:
            out = PS.write_weeks(Path(tmp), sk, lambda p: (True, [], []))
            self.assertEqual(out["written"], [])
            self.assertTrue(out["refused"])


class TestLengthCases(unittest.TestCase):
    def test_too_short(self):
        short = MARATHON["weeks"]["min"] - 1
        sk = build(MARATHON, weeks=short)
        self.assertEqual(sk["status"], "too_short")
        self.assertEqual(sk["weeks"], [])
        ids = {o["id"] for o in sk["options"]}
        self.assertTrue({"later_race", "freehand"} <= ids)
        later = next(o for o in sk["options"] if o["id"] == "later_race")
        self.assertEqual(later["earliest_race_week"],
                         (TODAY + timedelta(days=7 * (MARATHON["weeks"]["min"] - 1))).isoformat())
        shorter = next(o for o in sk["options"] if o["id"] == "shorter_format")
        self.assertTrue(all(PT.get_template(t, TEMPLATES)["weeks"]["min"] <= short for t in shorter["templates"]))

    def test_exactly_min_and_max_weeks_are_accepted(self):
        for n in (MARATHON["weeks"]["min"], MARATHON["weeks"]["max"]):
            sk = build(MARATHON, weeks=n)
            self.assertEqual(sk["status"], "ok", n)
            self.assertEqual(sk["lead_in_weeks"], 0)

    def test_flat_lead_in_weeks_at_held_volume(self):
        """`--lead-in flat` : le comportement de #190 (mise en route au volume tenu), conservé en option (#204)."""
        n = MARATHON["weeks"]["max"] + 6
        sk = build(MARATHON, weeks=n, lead_in="flat")
        self.assertEqual(sk["lead_in"]["mode"], "flat")
        self.assertEqual(sk["peak"]["base"]["source"], "held")
        self.assertEqual(sk["peak"]["lead_in_gain_pct"], 0.0)
        self.assertEqual(sk["status"], "ok")
        self.assertEqual(sk["lead_in_weeks"], 6)
        lead = [w for w in sk["weeks"] if w["type"] in ("lead_in", "recovery") and w["week"] <= 6]
        self.assertEqual(len(lead), 6)
        self.assertEqual(sk["weeks"][0]["type"], "lead_in")
        self.assertAlmostEqual(sk["weeks"][0]["target_duration_s"], 6 * 3600, delta=120)   # volume tenu
        self.assertNotEqual(sk["weeks"][5]["type"], "recovery")        # jamais la dernière avant le gabarit
        self.assertEqual(sk["weeks"][6]["phase"], "base")
        self.assertTrue(sk["summary"]["block_free"])
        self.assertEqual(sk["phase_weeks"], PT.allocate_phase_weeks(MARATHON, MARATHON["weeks"]["max"]))

    def test_race_in_the_past_or_this_week(self):
        self.assertEqual(build(race=TODAY - timedelta(days=1))["status"], "target_past")
        self.assertEqual(build(race=TODAY + timedelta(days=5))["status"], "too_short")

    def test_start_next_monday_when_today_is_not_monday(self):
        wed = TODAY + timedelta(days=2)
        sk = build(MARATHON, today=wed, race=race_after(MARATHON["weeks"]["default"] + 1))
        self.assertEqual(sk["start_week"], (TODAY + timedelta(days=7)).isoformat())
        self.assertEqual(sk["status"], "ok")

    def test_started_week_is_assumed_at_held_volume_in_the_reference(self):
        """Semaine en cours entamée : elle entre dans la référence R2/R3 au volume tenu (ASSUMPTIONS
        `start_week`), donc mean4 de la 1re semaine = (3 dernières réelles + tenu) / 4."""
        wed = TODAY + timedelta(days=2)
        weeks = [{"duration_s": h * 3600.0, "elevation_gain_m": 0.0, "distance_m": 0.0} for h in (2, 4, 6, 8)]
        seen = []
        real = G.evaluate

        def spy(proposed, ctx, gconf):
            seen.append(ctx["mean4_weeks"]["duration_s"])
            return real(proposed, ctx, gconf)
        with mock.patch.object(G, "evaluate", spy):
            build(MARATHON, today=wed, race=race_after(MARATHON["weeks"]["default"] + 1), held_=held(weeks=weeks))
        self.assertAlmostEqual(seen[0], (4 + 6 + 8 + 5) / 4 * 3600.0)

    def test_no_history_is_stated_never_invented(self):
        empty = PS.held_from_weeks([{"duration_s": 0.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                                     "has_any_activity": False}] * 4)
        sk = build(held_=empty)
        self.assertEqual(sk["status"], "no_history")
        self.assertEqual(sk["weeks"], [])
        self.assertIn("--held-hours", sk["reason"])

    def test_missing_elevation_history_warns(self):
        sk = build(held_=held(6, 0))
        self.assertTrue(any("D+ tenu nul" in w for w in sk["warnings"]))
        self.assertIsNone(sk["weeks"][0]["target_elevation_m"])

    def test_low_peak_warning_never_stretches(self):
        sk = build(ULTRA, held_=held(3, 600))
        self.assertTrue(any("sous le pic indicatif" in w for w in sk["warnings"]))
        self.assertAlmostEqual(sk["peak"]["duration_s"], 3 * 3600 * sk["peak"]["volume_factor"], delta=1)


class TestAvailability(unittest.TestCase):
    def test_parse_profile(self):
        text = ("- **Disponibilité hebdomadaire** : 4 séances, 6 h au total\n"
                "- **Jours impossibles** : mardi, dimanche matin\n- **Sortie longue** : samedi\n")
        av = PS.parse_availability(text)
        self.assertEqual(av["sessions_per_week"], 4)
        self.assertEqual(av["max_weekly_s"], 6 * 3600)
        self.assertEqual(av["blocked_days"], [1, 6])
        self.assertEqual(av["long_run_day"], 5)
        self.assertEqual(PS.parse_availability(text, "vendredi")["long_run_day"], 4)
        self.assertEqual(PS.parse_availability("- **Disponibilité hebdomadaire** : 7 h à 8 h au total")["max_weekly_s"],
                         8 * 3600)
        silent = PS.parse_availability("# rien")
        self.assertEqual((silent["sessions_per_week"], silent["blocked_days"], silent["source"]), (None, [], "default"))
        self.assertTrue(PS.parse_availability("- **Sortie longue** : someday")["notes"])

    def test_blocked_days_and_session_count_respected(self):
        av = PS.parse_availability("- **Disponibilité hebdomadaire** : 4 séances\n- **Jours impossibles** : mardi, jeudi\n"
                                   "- **Sortie longue** : samedi")
        sk = build(availability=av)
        self.assertEqual(sk["status"], "ok")
        for w in sk["weeks"]:
            e = w["entry"]
            days = [date.fromisoformat(s["date"]).weekday() for s in e["sessions"]]
            self.assertFalse({1, 3} & set(days), w["week_start"])
            if w["type"] in ("build", "recovery"):
                runs = [s for s in e["sessions"] if s["sport"] == "trail"]
                self.assertEqual(len(runs), 3)                       # 4 séances : 3 course + 1 renforcement
                self.assertEqual(len(e["sessions"]), 4)
                self.assertEqual(date.fromisoformat(max(runs, key=lambda s: s["planned_duration_s"])["date"]).weekday(), 5)

    def test_quality_sessions_never_consecutive_days(self):
        for w in build()["weeks"]:
            q = sorted(date.fromisoformat(s["date"]).toordinal() for s in w["entry"]["sessions"]
                       if s["intensity"] in ("tempo", "threshold", "vo2max"))
            self.assertTrue(all(b - a > 1 for a, b in zip(q, q[1:])), w["week_start"])

    def test_few_sessions_means_no_strength_slot(self):
        sk = build(availability=PS.parse_availability("- **Disponibilité hebdomadaire** : 3 séances"))
        self.assertFalse(sk["slots"]["strength_slot"])
        self.assertFalse(any(s["sport"] == "strength" for w in sk["weeks"] for s in w["entry"]["sessions"]))

    def test_max_hours_caps_the_peak(self):
        av = PS.parse_availability("- **Disponibilité hebdomadaire** : 5 séances, 6 h au total")
        sk = build(ULTRA, availability=av, held_=held(6, 1500))
        self.assertTrue(sk["peak"]["capped_by_availability"])
        self.assertEqual(sk["peak"]["duration_s"], 6 * 3600)
        self.assertTrue(any("plafond de disponibilité" in w for w in sk["warnings"]))
        self.assertLessEqual(max(w["target_duration_s"] for w in sk["weeks"]), 6 * 3600 + 60)

    def test_all_days_blocked_is_flagged_not_crashing(self):
        av = PS.parse_availability("- **Jours impossibles** : lundi mardi mercredi jeudi vendredi samedi dimanche")
        sk = build(availability=av)
        self.assertEqual(sk["status"], "ok")
        self.assertTrue(all(not w["entry"]["sessions"] for w in sk["weeks"][:-2]))

    def test_race_week_has_the_race_and_few_short_runs(self):
        obj = {"name": "Trail X", "distance_m": 42000, "elevation_gain_m": 2000, "target_time_s": 18000}
        sk = PS.build_skeleton(template=MARATHON, today=TODAY, race_date=race_after(MARATHON["weeks"]["default"]),
                               held=held(), availability=AVAIL, gconf=GCONF, context_factory=factory(),
                               objective=obj)
        race_week = next(w for w in sk["weeks"] if w["type"] == "race")
        sessions = race_week["entry"]["sessions"]
        race = sessions[-1]
        self.assertEqual(race["intensity"], "race")
        self.assertEqual(race["date"], sk["race_date"])
        self.assertEqual((race["planned_distance_m"], race["planned_elevation_m"]), (42000, 2000))
        self.assertLessEqual(len([s for s in sessions if s["intensity"] != "race"]), PS.MAX_RACE_WEEK_RUNS)
        self.assertTrue(all(s["date"] < sk["race_date"] for s in sessions[:-1]))
        # Veille de course laissée libre.
        eve = (date.fromisoformat(sk["race_date"]) - timedelta(days=1)).isoformat()
        self.assertNotIn(eve, [s["date"] for s in sessions])

    def _race_on(self, weekday: int) -> dict:
        race = race_after(MARATHON["weeks"]["default"]) - timedelta(days=6 - weekday)
        return PS.build_skeleton(template=MARATHON, today=TODAY, race_date=race, held=held(), availability=AVAIL,
                                 gconf=GCONF, context_factory=factory())

    def test_race_not_on_sunday_prorates_and_never_piles_up_before_the_race(self):
        full = next(w for w in self._race_on(6)["weeks"] if w["type"] == "race")
        for weekday in (1, 2, 5):            # mardi, mercredi, samedi
            sk = self._race_on(weekday)
            race_week = next(w for w in sk["weeks"] if w["type"] == "race")
            runs = [s for s in race_week["entry"]["sessions"] if s["intensity"] != "race"]
            race_d = date.fromisoformat(sk["race_date"])
            self.assertTrue(all(date.fromisoformat(s["date"]) < race_d - timedelta(days=1) for s in runs), weekday)
            # Volume au prorata des jours avant la course (≤ jour/6 du volume d'une course le dimanche).
            self.assertLessEqual(race_week["target_duration_s"], full["target_duration_s"] * weekday / 6 + 120, weekday)
            self.assertTrue(any("ramené à" in f for f in race_week["flags"]), weekday)
        # Course un mardi : la seule journée avant est la veille → aucun footing, jamais 3 h la veille.
        tuesday = next(w for w in self._race_on(1)["weeks"] if w["type"] == "race")
        self.assertEqual([s for s in tuesday["entry"]["sessions"] if s["intensity"] != "race"], [])

    def test_no_run_slot_in_the_days_after_the_race(self):
        for weekday in (6, 5, 2):
            sk = self._race_on(weekday)
            race_d = date.fromisoformat(sk["race_date"])
            rest_end = race_d + timedelta(days=PS.POST_RACE_REST_DAYS)
            for w in sk["weeks"]:
                if w["type"] != "post_race":
                    continue
                days = [date.fromisoformat(s["date"]) for s in w["entry"]["sessions"] if s["sport"] == "trail"]
                self.assertTrue(all(d > rest_end for d in days), (weekday, w["week_start"]))
        first_post = next(w for w in self._race_on(6)["weeks"] if w["type"] == "post_race")
        self.assertTrue(any("ramené à 4/7" in f for f in first_post["flags"]))


class TestPreviousWeekReference(unittest.TestCase):
    """`r2_volume_reference = "previous_week"` : la reprise après une semaine allégée n'est pas réduite
    (comme `arc_plan_templates`, #189), sauf si R2/R3 sont configurés en `block`."""

    def test_rebound_after_recovery_week_is_kept_and_flagged(self):
        g = G.guardrail_settings({"guardrails": {"r2_volume_reference": "previous_week"}})
        sk = build(ULTRA, gconf=g)
        ref = build(ULTRA)                      # référence mean4 : aucune réduction
        self.assertEqual(sk["summary"]["adjusted_weeks"], 0)
        for a, b in zip(sk["weeks"], ref["weeks"]):
            if b["type"] != "post_race":
                self.assertEqual(a["target_duration_s"], b["target_duration_s"], a["week_start"])
        rebounds = [w for w in sk["weeks"] if any("reprise" in f for f in w["flags"])]
        self.assertTrue(rebounds)
        for w in rebounds:
            self.assertEqual(w["guardrails"]["level"], "warn")
            self.assertIn(sk["weeks"][w["week"] - 2]["type"], ("recovery", "post_race"))

    def test_rebound_is_still_reduced_when_r2_blocks(self):
        g = G.guardrail_settings({"guardrails": {"r2_volume_reference": "previous_week",
                                                 "severity_r2_weekly_volume_jump": "block",
                                                 "severity_r3_weekly_elevation_jump": "block"}})
        sk = build(ULTRA, gconf=g)
        self.assertTrue(sk["summary"]["block_free"])
        self.assertGreater(sk["summary"]["adjusted_weeks"], 0)
        self.assertFalse(any("reprise" in f for w in sk["weeks"] for f in w["flags"]))


class TestRoad(unittest.TestCase):
    def test_road_has_distance_and_no_elevation(self):
        sk = build(ROUTE, sport="road", held_=held(5, 0, distance_km=50))
        self.assertEqual(sk["status"], "ok")
        for w in sk["weeks"]:
            self.assertIsNone(w["target_elevation_m"])
            runs = [s for s in w["entry"]["sessions"] if s.get("placeholder") and s["sport"] == "running"]
            for s in runs:
                self.assertAlmostEqual(s["planned_distance_m"] / s["planned_duration_s"], 50000 / (5 * 3600), delta=0.05)
        self.assertTrue(sk["summary"]["block_free"])


class TestWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-skeleton-"))
        (self.tmp / "planning").mkdir()
        self.sk = build()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_written_files_validate(self):
        out = PS.write_weeks(self.tmp, self.sk, I.validate_file)
        self.assertEqual(out["refused"], None)
        self.assertEqual(len(out["written"]), len(self.sk["weeks"]))
        for rel in out["written"]:
            ok, errors, warnings = I.validate_file(self.tmp / rel)
            self.assertTrue(ok, (rel, errors))
            self.assertEqual(warnings, [], rel)
        self.assertEqual(PS.find_conflicts(self.tmp, self.sk).__len__(), len(self.sk["weeks"]))

    def test_ramped_lead_in_weeks_are_written_and_validate(self):
        """#204 : une semaine de mise en route en rampe n'a pas de % du pic ; son fichier s'écrit et se valide."""
        sk = build(MARATHON, weeks=MARATHON["weeks"]["max"] + 2, held_=held(6, 1500, 50))
        self.assertIsNone(sk["weeks"][0]["volume_pct_of_peak"])
        self.assertIn("mise en route en rampe", PS.week_markdown(sk, sk["weeks"][0]))
        out = PS.write_weeks(self.tmp, sk, I.validate_file)
        self.assertEqual(len(out["written"]), len(sk["weeks"]))

    def test_never_overwrites_a_week_file(self):
        target = self.tmp / "planning" / f"Semaine_{self.sk['weeks'][3]['week_start']}.md"
        target.write_text("# à moi\n", encoding="utf-8")
        out = PS.write_weeks(self.tmp, self.sk, I.validate_file)
        self.assertEqual(out["written"], [])
        self.assertEqual([c["week_start"] for c in out["conflicts"]], [self.sk["weeks"][3]["week_start"]])
        self.assertEqual(target.read_text(encoding="utf-8"), "# à moi\n")
        self.assertEqual(sorted(p.name for p in (self.tmp / "planning").iterdir()), [target.name])

    def test_conflict_with_a_multi_week_file_entry(self):
        start = self.sk["weeks"][2]["week_start"]
        block = {"arc": 1, "kind": "week", "weeks": [{"week_start": start, "location": "X", "sessions": []}]}
        (self.tmp / "planning" / "Semaine_autre.md").write_text(
            f"# Plan\n\n```arc\n{json.dumps(block)}\n```\n", encoding="utf-8")
        out = PS.write_weeks(self.tmp, self.sk, I.validate_file)
        self.assertEqual(out["written"], [])
        self.assertEqual(out["conflicts"], [{"week_start": start, "file": "Semaine_autre.md"}])
        self.assertEqual(len(list((self.tmp / "planning").iterdir())), 1)

    def test_failed_validation_removes_what_was_written(self):
        out = PS.write_weeks(self.tmp, self.sk, lambda p: (False, ["boom"], []))
        self.assertEqual(out["written"], [])
        self.assertTrue(out["refused"])
        self.assertEqual(list((self.tmp / "planning").iterdir()), [])

    def test_only_ok_skeletons_are_written(self):
        out = PS.write_weeks(self.tmp, build(MARATHON, weeks=2), I.validate_file)
        self.assertEqual(out["written"], [])
        self.assertIn("too_short", out["refused"])


def _write_arc(path: Path, data: dict):
    path.write_text(f"# T\n\n```arc\n{json.dumps({'arc': 1, **data}, ensure_ascii=False)}\n```\n\ntexte\n", encoding="utf-8")


class _CliWorkspace(unittest.TestCase):
    """Workspace synthétique (historique trail, objectif 42 km, profil) pour les tests de la CLI."""
    RACE = race_after(MARATHON["weeks"]["default"]).isoformat()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-skeleton-cli-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        day = TODAY - timedelta(days=130)
        while day < TODAY:
            if day.weekday() in (1, 3, 5):
                dur, el = (5400, 300) if day.weekday() != 5 else (9000, 700)
                _write_arc(self.ws / f"activities/{day.isoformat()}_trail.md",
                           {"kind": "activity", "date": day.isoformat(), "sport": "trail", "duration_s": dur,
                            "distance_m": dur * 2.5, "elevation_gain_m": el, "rpe": 5})
            day += timedelta(days=1)
        (self.ws / "planning/active_objective.md").write_text(
            f"# Objectif actif\n\n## Course visée\n\n- **Nom** : Trail X\n- **Date** : {self.RACE}\n"
            "- **Distance** : 42 km\n- **Dénivelé positif** : 2000 m\n- **Lieu d'entraînement par défaut** : Tournai\n",
            encoding="utf-8")
        (self.ws / "planning/Runner_Profile.md").write_text(
            "# Profil\n\n- **Disponibilité hebdomadaire** : 5 séances, 9 h au total\n- **Jours impossibles** : lundi\n",
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cli(self, *args):
        return subprocess.run([sys.executable, str(REPO / "scripts" / "arc_index.py"), "plan-skeleton",
                               "--workspace", str(self.ws), "--today", TODAY.isoformat(), *args],
                              capture_output=True, text=True, timeout=300)


class TestCli(_CliWorkspace):
    def test_dry_run_json_by_default_and_writes_nothing(self):
        proc = self._cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["template"]["id"], "marathon_trail")           # 42 km → gabarit choisi sur l'objectif
        self.assertEqual(data["held"]["source"], "index")
        self.assertTrue(data["summary"]["block_free"])
        self.assertEqual(data["weeks"][0]["entry"]["location"], "Tournai")
        self.assertEqual(list((self.ws / "planning").glob("Semaine_*.md")), [])
        self.assertIsNotNone(data["forecast"])
        self.assertIn("alternative", data["forecast"])
        self.assertEqual(data["forecast"]["alternative"]["status"], "ok")
        self.assertIn("form", data["forecast"]["alternative"]["race_day"])

    def test_text_and_format_override(self):
        proc = self._cli("--text", "--format", "trail_court")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dry run", proc.stdout)
        self.assertIn("Forme prévue le jour J", proc.stdout)
        self.assertIn("Garde-fous", proc.stdout)

    def test_write_then_rerun_refuses_and_lists_conflicts(self):
        proc = self._cli("--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        written = data["write"]["written"]
        self.assertEqual(len(written), len(data["weeks"]))
        file = self.ws / written[0]
        check = subprocess.run([sys.executable, str(REPO / "scripts" / "arc_index.py"), "--validate", str(file)],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        before = {p.name: p.read_text(encoding="utf-8") for p in (self.ws / "planning").glob("Semaine_*.md")}
        again = self._cli("--write")
        self.assertEqual(again.returncode, 1)
        out = json.loads(again.stdout)
        self.assertEqual(out["write"]["written"], [])
        self.assertTrue(out["write"]["conflicts"])
        self.assertEqual(before, {p.name: p.read_text(encoding="utf-8") for p in (self.ws / "planning").glob("Semaine_*.md")})

    def test_declared_volume_and_errors(self):
        proc = self._cli("--held-hours", "4", "--held-elevation-m", "800")
        data = json.loads(proc.stdout)
        self.assertEqual(data["held"]["source"], "declared")
        self.assertEqual(data["held"]["duration_h"], 4.0)
        bad = self._cli("--race-date", "pas-une-date")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--race-date", bad.stderr)
        self.assertNotIn("Traceback", bad.stderr)
        short = self._cli("--race-date", (TODAY + timedelta(days=20)).isoformat())
        self.assertEqual(json.loads(short.stdout)["status"], "too_short")
        unknown = self._cli("--format", "inconnu")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("inconnu", unknown.stderr)
        self.assertNotIn("Traceback", unknown.stderr)

    def test_declared_zero_hours_is_no_history_not_the_index(self):
        data = json.loads(self._cli("--held-hours", "0").stdout)
        self.assertEqual(data["status"], "no_history")
        self.assertEqual(data["held"]["source"], "declared")

    def test_file_appearing_after_the_conflict_check_is_never_overwritten(self):
        conn = I.open_db(self.ws, memory=True)
        try:
            I.index_workspace(conn, self.ws, TODAY.isoformat())
            report = PS.skeleton_report(conn=conn, config=I.load_config(self.ws), workspace=self.ws, today=TODAY)
        finally:
            conn.close()
        late = self.ws / "planning" / PS.week_file_name(report["weeks"][3]["week_start"])
        late.write_text("écrit entre-temps\n", encoding="utf-8")
        with mock.patch.object(PS, "find_conflicts", return_value=[]):
            out = PS.write_weeks(self.ws, report, I.validate_file)
        self.assertEqual(out["written"], [])
        self.assertIn("interrompue", out["refused"])
        self.assertEqual(late.read_text(encoding="utf-8"), "écrit entre-temps\n")
        self.assertEqual(sorted(p.name for p in (self.ws / "planning").glob("Semaine_*.md")), [late.name])

    def test_current_week_plan_feeds_the_acwr_projection(self):
        today = TODAY + timedelta(days=2)              # mercredi : le squelette démarre lundi prochain
        _write_arc(self.ws / "planning/Semaine_courante.md", {
            "kind": "week", "week_start": TODAY.isoformat(), "location": "Tournai",
            "sessions": [{"date": (TODAY + timedelta(days=4)).isoformat(), "sport": "trail", "title": "Longue",
                          "planned_duration_s": 9000, "intensity": "endurance", "status": "planned"}]})
        conn = I.open_db(self.ws, memory=True)
        seen = []
        real = G.build_context

        def spy(conn_, config, gconf, week_start, today_=None, other_weeks=None):
            seen.append([w["week_start"] for w in other_weeks or []])
            return real(conn_, config, gconf, week_start, today_, other_weeks)
        try:
            I.index_workspace(conn, self.ws, today.isoformat())
            factory_ = PS.default_context_factory(conn, {}, GCONF, today)
            with mock.patch.object(G, "build_context", spy):
                factory_(TODAY + timedelta(days=7), [])
        finally:
            conn.close()
        self.assertEqual(seen, [[TODAY.isoformat()]])


# ---------------------------------------------------------------------------
# #204 : mise en route qui fait monter le volume, contrôle face aux exigences de la course
# ---------------------------------------------------------------------------

import sqlite3  # noqa: E402

import arc_trail_shape as TS  # noqa: E402

ISSUE_HELD = dict(hours=7.0, elev=900.0, distance_km=56.0)           # scénario de l'issue #204
ISSUE_OBJECTIVE = {"name": "Ultra", "distance_m": 85000.0, "elevation_gain_m": 4500.0}


def _r2r3(week):
    return [v for v in week["guardrails"]["violations"]
            if v["rule_id"] in ("r2_weekly_volume_jump", "r3_weekly_elevation_jump")]


class TestLeadInRamp(unittest.TestCase):
    N = ULTRA["weeks"]["max"] + 6

    def test_ramp_is_the_default_and_builds_the_volume(self):
        sk = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD))
        flat = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD), lead_in="flat")
        self.assertEqual(sk["status"], "ok")
        self.assertEqual(sk["lead_in"], {"mode": "ramp", "weeks": 6, "requested_weeks": None,
                                         "ramp_pct": PS.LEAD_IN_RAMP_PCT})
        lead = sk["weeks"][:6]
        builds = [w["target_duration_s"] for w in lead if w["type"] == "lead_in"]
        self.assertEqual(builds, sorted(builds))                       # jamais une baisse entre semaines pleines
        self.assertGreater(builds[-1], 7 * 3600 * 1.08)
        previous = 7 * 3600
        for w in lead:
            if w["type"] == "lead_in":
                self.assertLessEqual(w["target_duration_s"], previous * (1 + PS.LEAD_IN_RAMP_PCT / 100) + PS.ROUND_S * 2)
                previous = w["target_duration_s"]
            else:                                                       # semaine allégée : facteur du gabarit
                self.assertEqual(w["type"], "recovery")
                self.assertAlmostEqual(w["target_duration_s"], previous * ULTRA["recovery_week"]["volume_factor"],
                                       delta=PS.ROUND_S * 3)
        self.assertNotEqual(lead[-1]["type"], "recovery")
        # Le gabarit part du volume atteint : pic = dernière semaine de mise en route × facteur (#189 inchangé).
        self.assertEqual(sk["peak"]["base"]["source"], "lead_in")
        self.assertAlmostEqual(sk["peak"]["base"]["duration_s"], builds[-1], delta=1)
        self.assertAlmostEqual(sk["peak"]["duration_s"], builds[-1] * sk["peak"]["volume_factor"], delta=2)
        self.assertGreater(sk["peak"]["lead_in_gain_pct"], 10)
        self.assertGreater(sk["peak"]["duration_s"], flat["peak"]["duration_s"] * 1.1)
        self.assertIsNone(lead[0]["volume_pct_of_peak"])               # pas un pourcentage du pic : une rampe
        self.assertTrue(sk["summary"]["block_free"])

    def test_ramp_never_trips_r2_r3_with_either_reference(self):
        for ref in ("mean4", "previous_week"):
            gconf = G.guardrail_settings({"guardrails": {"r2_volume_reference": ref}})
            sk = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD), gconf=gconf)
            self.assertEqual(sk["status"], "ok", ref)
            self.assertTrue(sk["summary"]["block_free"], ref)
            for w in sk["weeks"][:6]:
                if ref == "mean4":
                    self.assertEqual(_r2r3(w), [], (ref, w["week_start"]))
                self.assertEqual(w["adjustments"], [], (ref, w["week_start"]))   # plafonnée d'emblée, jamais réduite après coup
            flat = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD), gconf=gconf, lead_in="flat")
            self.assertGreater(sk["peak"]["duration_s"], flat["peak"]["duration_s"], ref)

    def test_ramp_respects_the_profile_hour_ceiling(self):
        avail = dict(AVAIL, max_weekly_s=int(7.2 * 3600))
        sk = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD), availability=avail)
        for w in sk["weeks"]:
            self.assertLessEqual(w["target_duration_s"], 7.2 * 3600 + PS.ROUND_S, w["week_start"])
        self.assertTrue(any("plafond" in f for w in sk["weeks"][:6] for f in w["flags"]))

    def test_ramp_is_deterministic(self):
        a = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD))
        b = build(ULTRA, weeks=self.N, held_=held(**ISSUE_HELD))
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))

    def test_no_lead_in_means_no_change(self):
        """Sans semaine de mise en route, le squelette est celui de #190, quel que soit le mode."""
        for n in (ULTRA["weeks"]["min"], 18, ULTRA["weeks"]["max"]):
            a = build(ULTRA, weeks=n, held_=held(**ISSUE_HELD))
            b = build(ULTRA, weeks=n, held_=held(**ISSUE_HELD), lead_in="flat")
            self.assertEqual(a["lead_in_weeks"], 0)
            self.assertEqual([w["target_duration_s"] for w in a["weeks"]], [w["target_duration_s"] for w in b["weeks"]])
            self.assertEqual(a["peak"]["duration_s"], b["peak"]["duration_s"])

    def test_lead_in_weeks_borrows_from_the_template_down_to_its_minimum(self):
        sk = build(ULTRA, weeks=18, held_=held(**ISSUE_HELD), lead_in_weeks=2)
        self.assertEqual(sk["lead_in_weeks"], 2)
        self.assertEqual(sk["lead_in"]["requested_weeks"], 2)
        self.assertEqual(sk["phase_weeks"], PT.allocate_phase_weeks(ULTRA, 16))
        self.assertEqual([w["type"] for w in sk["weeks"][:2]], ["lead_in", "lead_in"])
        self.assertGreater(sk["peak"]["duration_s"], build(ULTRA, weeks=18, held_=held(**ISSUE_HELD))["peak"]["duration_s"])
        self.assertTrue(sk["summary"]["block_free"])
        with self.assertRaises(PS.SkeletonError) as ctx:
            build(ULTRA, weeks=18, lead_in_weeks=3)
        self.assertIn("au plus 2", str(ctx.exception))
        # Moins que l'excédent naturel : l'excédent l'emporte.
        self.assertEqual(build(ULTRA, weeks=self.N, lead_in_weeks=1)["lead_in_weeks"], 6)
        with self.assertRaises(PS.SkeletonError):
            build(ULTRA, weeks=18, lead_in_weeks=-1)
        with self.assertRaises(PS.SkeletonError):
            build(ULTRA, weeks=18, lead_in="steep")


class TestRaceDemand(unittest.TestCase):
    def _issue(self, **kw):
        return build(ULTRA, weeks=18, held_=held(**ISSUE_HELD), objective=dict(ISSUE_OBJECTIVE), **kw)

    @staticmethod
    def _component(sk, cid):
        return next(c for c in sk["race_demand"]["components"] if c["id"] == cid)

    def test_issue_scenario_is_flagged(self):
        sk = self._issue()
        d = sk["race_demand"]
        self.assertEqual(d["status"], "short")
        self.assertEqual(d["warn_ratio"], PS.DEMAND_WARN_RATIO)
        for cid in ("long_run", "weekly_elevation", "max_session_elevation"):
            self.assertEqual(self._component(sk, cid)["status"], "short", cid)
        self.assertTrue(any(w.startswith("exigence de course — plus longue sortie") for w in sk["warnings"]))
        self.assertTrue(any("jamais forcer les garde-fous" in w for w in sk["warnings"]))
        self.assertTrue(sk["summary"]["block_free"])                  # un avertissement, jamais une correction

    def test_targets_are_trail_shape_targets(self):
        sk = self._issue()
        effort = TS._race_effort_km(85000, 4500)
        self.assertEqual(self._component(sk, "long_run")["target"], round(TS.longest_run_target_m(85000), 1))
        self.assertEqual(self._component(sk, "weekly_volume")["target"], round(TS.weekly_volume_target_km(effort), 1))
        self.assertEqual(self._component(sk, "max_session_elevation")["target"],
                         round(min(4500 * TS.MAX_DPLUS_SESSION_RATIO, TS.MAX_DPLUS_TARGET_CAP_M), 1))
        self.assertAlmostEqual(self._component(sk, "weekly_elevation")["target"],
                               TS.weekly_volume_target_km(effort) * 45 / effort * 100, delta=0.1)
        long_run = self._component(sk, "long_run")
        self.assertAlmostEqual(long_run["observed"], long_run["observed_duration_s"] * 56000 / (7 * 3600), delta=0.1)

    def test_comfortable_objective_is_ok(self):
        sk = build(PT.get_template("trail_court", TEMPLATES), weeks=12, held_=held(6, 1200, 50),
                   objective={"distance_m": 20000.0, "elevation_gain_m": 600.0})
        self.assertEqual(sk["race_demand"]["status"], "ok")
        self.assertFalse(any(w.startswith("exigence de course") for w in sk["warnings"]))

    def test_unknown_distance_is_never_guessed(self):
        sk = build(ULTRA, weeks=18, held_=held(7, 900), objective=dict(ISSUE_OBJECTIVE))   # déclaré sans distance
        for cid in ("long_run", "weekly_volume"):
            c = self._component(sk, cid)
            self.assertEqual(c["status"], "unavailable", cid)
            self.assertIsNone(c["observed"])
            self.assertIn("jamais devinée", c["reason"])
        self.assertEqual(self._component(sk, "weekly_elevation")["status"], "short")   # le D+ reste évaluable

    def test_without_objective_or_for_another_race(self):
        sk = build(ULTRA, weeks=18, held_=held(**ISSUE_HELD))
        self.assertEqual(sk["race_demand"]["status"], "unavailable")
        self.assertIn("distance", sk["race_demand"]["reason"])
        other = build(ULTRA, weeks=18, held_=held(**ISSUE_HELD),
                      objective={**ISSUE_OBJECTIVE, "race_date": "2030-01-01"})
        self.assertEqual(other["race_demand"]["status"], "unavailable")
        self.assertIn("2030-01-01", other["race_demand"]["reason"])

    def test_road_has_no_elevation_components(self):
        sk = build(ROUTE, weeks=16, sport="road", held_=held(5, 0, 55),
                   objective={"distance_m": 42195.0})
        ids = {c["id"] for c in sk["race_demand"]["components"]}
        self.assertNotIn("weekly_elevation", ids)
        self.assertNotIn("max_session_elevation", ids)
        self.assertIn("long_run", ids)

    def test_declared_weekly_target_and_race_time_information(self):
        sk = self._issue(race_time={"seconds": 14 * 3600, "source": "objective.target_time_s"})
        sk_obj = build(ULTRA, weeks=18, held_=held(**ISSUE_HELD), objective={**ISSUE_OBJECTIVE, "weekly_target_s": 9 * 3600},
                       race_time={"seconds": 14 * 3600, "source": "objective.target_time_s"})
        declared = self._component(sk_obj, "declared_weekly_duration")
        self.assertEqual(declared["target"], 9 * 3600)
        self.assertEqual(declared["status"], "ok")
        info = self._component(sk, "long_run_vs_race_time")
        self.assertEqual(info["status"], "info")
        self.assertAlmostEqual(info["observed"], info["long_run_s"] / (14 * 3600) * 100, delta=0.1)
        self.assertFalse(any("temps de course" in w for w in sk["warnings"]))     # information, jamais un avertissement

    def test_text_render_shows_the_check(self):
        text = PS.render_text(self._issue())
        self.assertIn("Exigences de la course", text)
        self.assertIn("⚠", text)
        ramp = PS.render_text(build(ULTRA, weeks=ULTRA["weeks"]["max"] + 6, held_=held(**ISSUE_HELD)))
        self.assertIn("Mise en route en rampe", ramp)


class TestExpectedRaceTime(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE race_plan (source_path TEXT, date TEXT, race_name TEXT, race_date TEXT, "
                          "distance_m REAL, elevation_gain_m REAL, target_time_s REAL, body_md TEXT, data_json TEXT)")

    def tearDown(self):
        self.conn.close()

    def test_race_plan_then_objective_then_nothing(self):
        race = date(2027, 2, 14)
        obj = {"race_date": race.isoformat(), "target_time_s": 50000}
        self.assertEqual(PS.expected_race_time(self.conn, race, obj),
                         {"seconds": 50000.0, "source": "objective.target_time_s"})
        self.assertIsNone(PS.expected_race_time(self.conn, race, {"race_date": "2030-01-01", "target_time_s": 1}))
        self.conn.execute("INSERT INTO race_plan (date, race_date, target_time_s, data_json) VALUES (?, ?, ?, ?)",
                          ("2026-10-01", race.isoformat(), 48000, json.dumps({"scenarios": {"realistic": 47000}})))
        self.assertEqual(PS.expected_race_time(self.conn, race, obj),
                         {"seconds": 47000.0, "source": "race_plan.scenarios.realistic"})


class TestCliLeadIn(_CliWorkspace):
    """#204 côté CLI : options `--lead-in` / `--lead-in-weeks`, `race_demand` dans la sortie."""

    def test_lead_in_options_and_race_demand(self):
        data = json.loads(self._cli("--lead-in", "flat").stdout)
        self.assertEqual(data["lead_in"]["mode"], "flat")
        self.assertIn(data["race_demand"]["status"], ("ok", "short"))
        self.assertTrue(data["race_demand"]["components"])
        n = data["n_weeks"]
        borrow = n - MARATHON["weeks"]["min"]
        data = json.loads(self._cli("--lead-in-weeks", str(borrow)).stdout)
        self.assertEqual(data["lead_in_weeks"], borrow)
        bad = self._cli("--lead-in-weeks", str(borrow + 1))
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--lead-in-weeks", bad.stderr)
        self.assertNotIn("Traceback", bad.stderr)
        text = self._cli("--text").stdout
        self.assertIn("Exigences de la course", text)


if __name__ == "__main__":
    unittest.main()
