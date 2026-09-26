"""Palier D — moteur de garde-fous déterministe (#52).

Deux niveaux de test, comme le module lui-même :
- `TestRuleThresholds`/`TestRuleEdgeCases` appellent directement les fonctions de
  règle (`_eval_r1`…`_eval_r7`), en unitaire, avec un `context` fabriqué à la
  main — c'est la façon la plus simple et la plus robuste d'écrire « juste sous
  / juste au-dessus du seuil » sans dépendre des non-linéarités du modèle
  impulsion-réponse de Banister (EMA).
- `TestEvaluateIntegration`/`TestBuildContext`/`TestCLI` couvrent `evaluate()`
  bout en bout (projection de charge incluse) et `build_context()` sur un vrai
  workspace synthétique (même patron que `tests/data/test_arc_index.py`).
"""

from __future__ import annotations

import contextlib
import io
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
import arc_guardrails as G  # noqa: E402
import arc_index as I  # noqa: E402


def week(sessions, week_start="2026-09-21", **extra):
    return {"week_start": week_start, "location": "Tournai", "sessions": sessions, **extra}


def session(d, sport="trail", intensity="endurance", **extra):
    return {"date": d, "sport": sport, "title": "séance", "intensity": intensity, **extra}


def base_context(**overrides):
    ctx = {
        "week_start": "2026-09-21", "week_end": "2026-09-27", "today": "2026-09-20",
        "sport_primary": "trail", "morning_check": "full", "race_date": None,
        "is_race_week": False, "has_load_history": False, "loads_by_date": {},
        "previous_week": {"duration_s": 0.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                           "has_any_activity": False},
        "mean4_weeks": {"duration_s": 0.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                        "has_any_activity": False},
        "health_by_date": {},
    }
    ctx.update(overrides)
    return ctx


DEFAULT_GCONF = G.guardrail_settings({})


# ---------------------------------------------------------------------------
# Seuils, une règle à la fois
# ---------------------------------------------------------------------------


class TestR1Acwr(unittest.TestCase):
    def test_at_threshold_is_ok(self):
        ctx = base_context(acwr_projected=DEFAULT_GCONF["r1_acwr_max"])
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        ctx = base_context(acwr_projected=DEFAULT_GCONF["r1_acwr_max"] + 0.01)
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r1_acwr_projected")
        self.assertEqual(violation["severity"], "block")

    def test_severity_from_config(self):
        gconf = G.guardrail_settings({"guardrails": {"severity_r1_acwr_projected": "info"}})
        ctx = base_context(acwr_projected=gconf["r1_acwr_max"] + 0.5)
        violation, _ = G._eval_r1(ctx, gconf)
        self.assertEqual(violation["severity"], "info")

    def test_none_is_insufficient_history(self):
        ctx = base_context(acwr_projected=None)
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")


class TestR2Volume(unittest.TestCase):
    def test_at_threshold_is_ok(self):
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=11000)]
        violation, skip = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=11500)]  # +15 %
        violation, _ = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r2_weekly_volume_jump")

    def test_no_reference_history_is_insufficient(self):
        ctx = base_context()  # previous_week.has_any_activity = False
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=99999)]
        violation, skip = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")

    def test_decrease_never_violates(self):
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=1000)]
        violation, skip = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_road_checks_distance_too(self):
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 10000.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="running", planned_distance_m=11500)]
        violation, _ = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "road")
        self.assertIsNotNone(violation)

    def test_trail_ignores_distance(self):
        """En trail, seule la durée compte pour R2 — la distance ne doit jamais déclencher."""
        ctx = base_context(previous_week={"duration_s": 1000.0, "distance_m": 1000.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=1000,
                             planned_distance_m=999999)]
        violation, skip = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)

    def test_only_run_family_counts(self):
        """Une séance vélo massive ne doit jamais faire déclencher R2 (multi-sport)."""
        ctx = base_context(previous_week={"duration_s": 1000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [
            session("2026-09-22", sport="trail", planned_duration_s=1050),   # +5 %, sous le seuil
            session("2026-09-23", sport="cycling", planned_duration_s=999999),
        ]
        violation, _ = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)


class TestR3Elevation(unittest.TestCase):
    def test_at_threshold_is_ok(self):
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 0.0,
                                          "elevation_gain_m": 1000.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_elevation_m=1100)]
        violation, skip = G._eval_r3(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 0.0,
                                          "elevation_gain_m": 1000.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_elevation_m=1101)]
        violation, _ = G._eval_r3(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r3_weekly_elevation_jump")

    def test_not_applicable_on_road(self):
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 0.0,
                                          "elevation_gain_m": 100.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="running", planned_elevation_m=999999)]
        violation, skip = G._eval_r3(ctx, DEFAULT_GCONF, sessions, "road")
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "not_applicable_sport")


class TestR4Monotony(unittest.TestCase):
    def test_at_threshold_is_ok(self):
        ctx = base_context(monotony_projected=DEFAULT_GCONF["r4_monotony_max"])
        violation, skip = G._eval_r4(ctx, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        ctx = base_context(monotony_projected=DEFAULT_GCONF["r4_monotony_max"] + 0.01)
        violation, _ = G._eval_r4(ctx, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r4_monotony_projected")

    def test_none_is_insufficient_history(self):
        ctx = base_context(monotony_projected=None)
        violation, skip = G._eval_r4(ctx, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")


class TestR5QualityAfterRed(unittest.TestCase):
    def test_quality_on_red_day_violates(self):
        ctx = base_context(health_by_date={"2026-09-24": "red"})
        sessions = [session("2026-09-24", intensity="vo2max")]
        violation, _ = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["severity"], "block")

    def test_quality_day_after_red_violates(self):
        ctx = base_context(health_by_date={"2026-09-23": "red"})
        sessions = [session("2026-09-24", intensity="threshold")]
        violation, _ = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNotNone(violation)

    def test_no_red_verdict_is_ok(self):
        ctx = base_context(health_by_date={"2026-09-23": "green"})
        sessions = [session("2026-09-24", intensity="threshold")]
        violation, skip = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_easy_session_on_red_day_does_not_violate(self):
        ctx = base_context(health_by_date={"2026-09-24": "red"})
        sessions = [session("2026-09-24", intensity="recovery")]
        violation, skip = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_morning_check_off_is_skipped(self):
        ctx = base_context(morning_check="off", health_by_date={"2026-09-24": "red"})
        sessions = [session("2026-09-24", intensity="vo2max")]
        violation, skip = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "health_check_disabled")

    def test_cancelled_quality_session_is_ignored(self):
        ctx = base_context(health_by_date={"2026-09-24": "red"})
        sessions = [session("2026-09-24", intensity="vo2max", status="cancelled")]
        violation, skip = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)


class TestR6LongRunShare(unittest.TestCase):
    def test_at_threshold_is_ok(self):
        # Trois séances (pas deux) pour que la plus longue puisse être MINORITAIRE
        # (35 % < 50 %) tout en restant le maximum du trio : 350 + 325 + 325 = 1000.
        threshold = DEFAULT_GCONF["r6_long_run_share_max_pct"]
        long_s = threshold * 10  # 350 sur un total de 1000 -> exactement `threshold` %
        rest = (1000 - long_s) / 2
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=long_s),
                    session("2026-09-24", sport="trail", planned_duration_s=rest),
                    session("2026-09-27", sport="trail", planned_duration_s=rest)]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        threshold = DEFAULT_GCONF["r6_long_run_share_max_pct"]
        long_s = threshold * 10 + 1   # 351 sur 1000 -> juste au-dessus du seuil
        rest = (1000 - long_s) / 2
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=long_s),
                    session("2026-09-24", sport="trail", planned_duration_s=rest),
                    session("2026-09-27", sport="trail", planned_duration_s=rest)]
        violation, _ = G._eval_r6(sessions, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r6_long_run_share")
        self.assertEqual(violation["session_dates"], ["2026-09-22"])

    def test_no_run_family_session_is_insufficient(self):
        sessions = [session("2026-09-22", sport="cycling", planned_duration_s=5000)]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")

    def test_missing_planned_duration_is_skipped(self):
        sessions = [session("2026-09-22", sport="trail", planned_distance_m=25000),
                    session("2026-09-24", sport="trail", planned_duration_s=1800)]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "missing_planned_duration")


class TestR7ConsecutiveQuality(unittest.TestCase):
    def test_two_days_apart_is_ok(self):
        sessions = [session("2026-09-22", intensity="vo2max"),
                    session("2026-09-24", intensity="threshold")]
        violation, skip = G._eval_r7(sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_consecutive_days_violate(self):
        sessions = [session("2026-09-22", intensity="vo2max"),
                    session("2026-09-23", intensity="threshold")]
        violation, _ = G._eval_r7(sessions, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r7_consecutive_quality")
        self.assertEqual(violation["session_dates"], ["2026-09-22", "2026-09-23"])

    def test_cancelled_session_does_not_count(self):
        sessions = [session("2026-09-22", intensity="vo2max"),
                    session("2026-09-23", intensity="threshold", status="cancelled")]
        violation, skip = G._eval_r7(sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestGuardrailSettings(unittest.TestCase):
    def test_defaults_when_section_absent(self):
        gconf = G.guardrail_settings({})
        self.assertTrue(gconf["enabled"])
        self.assertEqual(gconf["r1_acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertEqual(gconf["severity"]["r1_acwr_projected"], "block")
        self.assertEqual(gconf["severity"]["r2_weekly_volume_jump"], "warn")

    def test_user_override_applies(self):
        gconf = G.guardrail_settings({"guardrails": {"r1_acwr_max": 1.5, "enabled": False}})
        self.assertEqual(gconf["r1_acwr_max"], 1.5)
        self.assertFalse(gconf["enabled"])

    def test_invalid_threshold_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            gconf = G.guardrail_settings({"guardrails": {"r1_acwr_max": "beaucoup"}})
        self.assertEqual(gconf["r1_acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertIn("avertissement", buf.getvalue())

    def test_invalid_severity_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            gconf = G.guardrail_settings({"guardrails": {"severity_r1_acwr_projected": "catastrophe"}})
        self.assertEqual(gconf["severity"]["r1_acwr_projected"], "block")
        self.assertIn("avertissement", buf.getvalue())

    def test_invalid_reference_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            gconf = G.guardrail_settings({"guardrails": {"r2_volume_reference": "n'importe quoi"}})
        self.assertEqual(gconf["r2_volume_reference"], G.DEFAULT_VOLUME_REFERENCE)
        self.assertIn("avertissement", buf.getvalue())

    def test_enabled_false_skips_everything(self):
        gconf = G.guardrail_settings({"guardrails": {"enabled": False}})
        result = G.evaluate(week([session("2026-09-22", planned_duration_s=999999)]),
                             base_context(), gconf)
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])
        self.assertEqual(len(result["skipped_rules"]), len(G.RULE_IDS))
        for skip in result["skipped_rules"]:
            self.assertEqual(skip["reason_code"], "guardrails_disabled")


# ---------------------------------------------------------------------------
# evaluate() bout en bout : race week, déterminisme, projection
# ---------------------------------------------------------------------------


class TestEvaluateIntegration(unittest.TestCase):
    def test_race_week_skips_load_rules_but_keeps_r5(self):
        ctx = base_context(is_race_week=True, health_by_date={"2026-09-24": "red"})
        w = week([session("2026-09-22", planned_duration_s=999999999, intensity="vo2max"),
                  session("2026-09-24", intensity="threshold")])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        skipped_ids = {s["rule_id"] for s in result["skipped_rules"]}
        for rid in ("r1_acwr_projected", "r2_weekly_volume_jump", "r3_weekly_elevation_jump",
                    "r4_monotony_projected", "r6_long_run_share", "r7_consecutive_quality"):
            self.assertIn(rid, skipped_ids)
        violated_ids = {v["rule_id"] for v in result["violations"]}
        self.assertIn("r5_quality_after_red", violated_ids)
        self.assertFalse(result["ok"])  # r5 est severity=block par défaut

    def test_ok_true_with_only_warn_violations(self):
        ctx = base_context(previous_week={"duration_s": 1000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        w = week([session("2026-09-22", planned_duration_s=5000)])  # gros +% -> R2 warn
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        self.assertTrue(any(v["rule_id"] == "r2_weekly_volume_jump" for v in result["violations"]))
        self.assertTrue(result["ok"])  # aucune violation `block`

    def test_deterministic_ordering(self):
        ctx = base_context(previous_week={"duration_s": 100.0, "distance_m": 0.0,
                                          "elevation_gain_m": 100.0, "has_any_activity": True})
        w = week([
            session("2026-09-22", intensity="vo2max", planned_duration_s=9000, planned_elevation_m=900),
            session("2026-09-23", intensity="threshold", planned_duration_s=9000),
        ])
        r1 = G.evaluate(w, ctx, DEFAULT_GCONF)
        r2 = G.evaluate(w, ctx, DEFAULT_GCONF)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))
        rule_ids = [v["rule_id"] for v in r1["violations"]]
        self.assertEqual(rule_ids, sorted(rule_ids))
        self.assertEqual(r1["checked_rules"], sorted(r1["checked_rules"]))

    def test_projected_load_moves_acwr(self):
        """Une semaine chargée après un long historique modéré doit faire monter
        l'ACWR projeté au-delà de ce qu'il serait sans la semaine proposée."""
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 30.0
            d = date.fromordinal(d.toordinal() + 1)
        ctx = base_context(loads_by_date=loads, has_load_history=True)
        light_week = week([session(f"2026-09-{22 + i}", intensity="recovery",
                                    planned_duration_s=600) for i in range(6)])
        heavy_week = week([session(f"2026-09-{22 + i}", intensity="vo2max",
                                    planned_duration_s=6000) for i in range(6)])
        light_result = G.evaluate(light_week, ctx, DEFAULT_GCONF)
        heavy_result = G.evaluate(heavy_week, ctx, DEFAULT_GCONF)
        self.assertLess(light_result["context"]["acwr_projected"],
                        heavy_result["context"]["acwr_projected"])


# ---------------------------------------------------------------------------
# build_context() sur un vrai workspace synthétique
# ---------------------------------------------------------------------------


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-guardrails-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, arc_data: dict, body: str = "Texte.") -> None:
        text = f"# Titre\n\n```arc\n{json.dumps({'arc': 1, **arc_data}, ensure_ascii=False)}\n```\n\n{body}\n"
        (self.ws / rel).write_text(text, encoding="utf-8")

    def index(self, today="2026-09-20"):
        return I.index_workspace(self.conn, self.ws, today)


class TestBuildContext(WorkspaceCase):
    def _write_objective(self, race_date: str) -> None:
        # `planning/active_objective.md` est un format LEGACY (puces Markdown,
        # `arc_legacy.parse_objective`), jamais un bloc ```arc — voir
        # `scripts/arc_index.py::classify`.
        (self.ws / "planning/active_objective.md").write_text(
            "# Objectif actif\n\n## Course visée\n\n"
            f"- **Nom** : Trail X\n- **Date** : {race_date}\n- **Distance** : 40 km\n",
            encoding="utf-8",
        )

    def test_race_week_detected_from_objective(self):
        self._write_objective("2026-09-24")
        self.index()
        config = I.load_config(self.ws)
        gconf = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gconf, date(2026, 9, 21), date(2026, 9, 20))
        self.assertTrue(ctx["is_race_week"])
        self.assertEqual(ctx["race_date"], "2026-09-24")

    def test_no_objective_is_not_a_race_week(self):
        self.index()
        config = I.load_config(self.ws)
        gconf = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gconf, date(2026, 9, 21), date(2026, 9, 20))
        self.assertFalse(ctx["is_race_week"])
        self.assertIsNone(ctx["race_date"])

    def test_previous_week_totals_from_real_activities(self):
        self.write("activities/2026-09-15_trail.md",
                    {"kind": "activity", "date": "2026-09-15", "sport": "trail",
                     "duration_s": 3600, "distance_m": 10000, "elevation_gain_m": 300})
        self.write("activities/2026-09-16_strength.md",
                    {"kind": "activity", "date": "2026-09-16", "sport": "strength", "duration_s": 1800})
        self.index()
        config = I.load_config(self.ws)
        gconf = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gconf, date(2026, 9, 21), date(2026, 9, 20))
        self.assertTrue(ctx["previous_week"]["has_any_activity"])
        self.assertEqual(ctx["previous_week"]["duration_s"], 3600)   # strength (hors famille course) exclue
        self.assertEqual(ctx["previous_week"]["elevation_gain_m"], 300)

    def test_health_verdict_is_read(self):
        self.write("medical/2026-09-20_health.md",
                    {"kind": "health", "date": "2026-09-20", "morning_check": "full",
                     "verdict": "red", "verdict_reason": "HRV basse trois jours de suite."})
        self.index()
        config = I.load_config(self.ws)
        gconf = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gconf, date(2026, 9, 21), date(2026, 9, 20))
        self.assertEqual(ctx["health_by_date"].get("2026-09-20"), "red")


class TestCLI(WorkspaceCase):
    def _run(self, *args, input_text=None):
        cmd = [sys.executable, str(REPO / "scripts/arc_guardrails.py"), *args]
        return subprocess.run(cmd, input=input_text, capture_output=True, text=True)

    def test_check_on_written_week_file(self):
        self.write("planning/2026-09-21_semaine.md",
                    {"kind": "week", "week_start": "2026-09-21", "location": "Tournai",
                     "sessions": [{"date": "2026-09-22", "sport": "trail", "title": "EF",
                                   "planned_duration_s": 3000, "intensity": "endurance"}]})
        result = self._run("check", "--week", str(self.ws / "planning/2026-09-21_semaine.md"),
                            "--workspace", str(self.ws), "--today", "2026-09-20")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("ok", payload)
        self.assertIn("checked_rules", payload)

    def test_check_on_stdin_json_before_persisting(self):
        payload = {"week_start": "2026-09-21", "location": "Tournai",
                   "sessions": [{"date": "2026-09-22", "sport": "trail", "title": "EF",
                                 "planned_duration_s": 3000, "intensity": "endurance"}]}
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            "--today", "2026-09-20", input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertIn("ok", out)

    def test_check_exits_nonzero_on_block(self):
        self.write("medical/2026-09-20_health.md",
                    {"kind": "health", "date": "2026-09-20", "morning_check": "full",
                     "verdict": "red", "verdict_reason": "Fatigue nette."})
        payload = {"week_start": "2026-09-21", "location": "Tournai",
                   "sessions": [{"date": "2026-09-21", "sport": "trail", "title": "Côtes",
                                 "planned_duration_s": 3000, "intensity": "vo2max"}]}
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            "--today", "2026-09-20", input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 1, result.stderr)
        out = json.loads(result.stdout)
        self.assertFalse(out["ok"])

    def test_missing_week_start_is_a_clean_error(self):
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            input_text=json.dumps({"sessions": []}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("week_start", result.stderr)


if __name__ == "__main__":
    unittest.main()
