"""Palier D — moteur de garde-fous déterministe (#52), incluant les correctifs
de la revue de code #98 (PR #98) : historique minimal avant projection ACWR/
monotonie, appariement séance par séance (pas par jour agrégé), estimation de
durée depuis la distance, gating `today`, comparaison au scénario « repos
complet » pour R1, etc.

Deux niveaux de test, comme le module lui-même :
- `TestR*`/`TestGuardrailSettings` appellent directement les fonctions de règle
  (`_eval_r1`…`_eval_r7`), en unitaire, avec un `context` fabriqué à la main —
  la façon la plus simple et la plus robuste d'écrire « juste sous / juste
  au-dessus du seuil » sans dépendre des non-linéarités du modèle
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
from datetime import date, timedelta
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
        "week_activities": [], "recent_run_pace_s_km": None,
        "previous_week": {"duration_s": 0.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                           "has_any_activity": False},
        "mean4_weeks": {"duration_s": 0.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                        "has_any_activity": False},
        "health_by_date": {},
    }
    ctx.update(overrides)
    return ctx


def gconf(**overrides):
    return G.guardrail_settings({"guardrails": overrides} if overrides else {})


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

    def test_just_above_threshold_violates_as_warn_by_default(self):
        # Revue de code #98, should-fix 7 : R1 est passée de "block" à "warn"
        # par défaut (réserves scientifiques sur l'ACWR, voir ASSUMPTIONS).
        ctx = base_context(acwr_projected=DEFAULT_GCONF["r1_acwr_max"] + 0.01)
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r1_acwr_projected")
        self.assertEqual(violation["severity"], "warn")

    def test_can_be_configured_back_to_block(self):
        conf = gconf(severity_r1_acwr_projected="block")
        ctx = base_context(acwr_projected=conf["r1_acwr_max"] + 0.5)
        violation, _ = G._eval_r1(ctx, conf)
        self.assertEqual(violation["severity"], "block")

    def test_none_is_insufficient_history(self):
        ctx = base_context(acwr_projected=None)
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")

    def test_does_not_fire_when_it_does_not_worsen_the_baseline(self):
        """Revue de code #98, should-fix 6 : une semaine de récupération après une
        course ne doit pas être BLOQUÉE si elle n'AGGRAVE pas le ratio par rapport
        à un repos complet (ACWR déjà élevé par la charge résiduelle réelle) —
        mais une violation `info` doit quand même être rendue (revue de code #98,
        2e passe, nit : le coach doit voir le chiffre)."""
        ctx = base_context(acwr_projected=1.42, acwr_baseline=1.42)
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNone(skip)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["severity"], "info")

    def test_fires_when_it_worsens_the_baseline(self):
        ctx = base_context(acwr_projected=1.42, acwr_baseline=1.20)
        violation, skip = G._eval_r1(ctx, DEFAULT_GCONF)
        self.assertIsNotNone(violation)


class TestMaxWeekAcwr(unittest.TestCase):
    def test_picks_the_maximum_of_the_last_seven_points(self):
        series = [{"acwr": 0.5}] * 3 + [{"acwr": v} for v in (0.9, 1.6, 1.1, 1.0, 0.95, 1.3, 1.2)]
        self.assertEqual(G._max_week_acwr(series), 1.6)

    def test_ignores_none_values(self):
        series = [{"acwr": None}] * 5 + [{"acwr": 1.1}, {"acwr": None}]
        self.assertEqual(G._max_week_acwr(series), 1.1)

    def test_all_none_is_none(self):
        series = [{"acwr": None}] * 7
        self.assertIsNone(G._max_week_acwr(series))


class TestR2Volume(unittest.TestCase):
    """Référence forcée sur "previous_week" pour ces tests de seuil (le défaut
    est "mean4" depuis la revue de code #98, should-fix 8 — voir
    `TestR2Reference` pour la couverture du défaut et de `no_reference`)."""

    def test_at_threshold_is_ok(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=11000)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=11500)]  # +15 %
        violation, _ = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r2_weekly_volume_jump")

    def test_no_reference_history_is_no_reference(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context()  # previous_week.has_any_activity = False
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=99999)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "no_reference")

    def test_decrease_never_violates(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=1000)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_road_checks_distance_too(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 10000.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True},
                            recent_run_pace_s_km=300.0)  # séance distance seule -> durée estimable
        sessions = [session("2026-09-22", sport="running", planned_distance_m=11500)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "road")
        self.assertIsNone(skip)
        self.assertIsNotNone(violation)

    def test_trail_ignores_distance(self):
        """En trail, seule la durée compte pour R2 — la distance ne doit jamais déclencher."""
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 1000.0, "distance_m": 1000.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=1000,
                             planned_distance_m=999999)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)

    def test_only_run_family_counts(self):
        """Une séance vélo massive ne doit jamais faire déclencher R2 (multi-sport)."""
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 1000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        sessions = [
            session("2026-09-22", sport="trail", planned_duration_s=1050),   # +5 %, sous le seuil
            session("2026-09-23", sport="cycling", planned_duration_s=999999),
        ]
        violation, _ = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)

    def test_distance_only_session_without_pace_history_skips(self):
        """Revue de code #98, blocker 3 : une séance prescrite en distance seule,
        sans allure récente pour l'estimer, rend R2 non fiable — sautée."""
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 10000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True},
                            recent_run_pace_s_km=None)
        sessions = [session("2026-09-27", sport="trail", planned_distance_m=25000,
                             planned_elevation_m=900)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "missing_planned_duration")

    def test_distance_only_session_with_pace_history_is_estimated(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 100.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True},
                            recent_run_pace_s_km=300.0)  # 5:00/km
        # 25 km + 900 m D+ (equiv. 1.575 km plat) à 5:00/km ~ 7 972 s, très
        # largement > 100 s x 1.10 : doit violer, pas sauter.
        sessions = [session("2026-09-27", sport="trail", planned_distance_m=25000,
                             planned_elevation_m=900)]
        violation, skip = G._eval_r2(ctx, conf, sessions, "trail")
        self.assertIsNone(skip)
        self.assertIsNotNone(violation)


class TestR2Reference(unittest.TestCase):
    def test_default_reference_is_mean4(self):
        self.assertEqual(G.DEFAULT_VOLUME_REFERENCE, "mean4")
        self.assertEqual(DEFAULT_GCONF["r2_volume_reference"], "mean4")

    def test_mean4_used_by_default(self):
        ctx = base_context(
            previous_week={"duration_s": 1000.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                            "has_any_activity": True},
            mean4_weeks={"duration_s": 5000.0, "distance_m": 0.0, "elevation_gain_m": 0.0,
                        "has_any_activity": True},
        )
        # +10 % vs previous_week (1000) violerait ; +10 % vs mean4 (5000) ne
        # devrait pas déclencher avec une proposition de 1050 s.
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=1050)]
        violation, _ = G._eval_r2(ctx, DEFAULT_GCONF, sessions, "trail")
        self.assertIsNone(violation)


class TestR3Elevation(unittest.TestCase):
    def test_at_threshold_is_ok(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 0.0,
                                          "elevation_gain_m": 1000.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_elevation_m=1100)]
        violation, skip = G._eval_r3(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 0.0,
                                          "elevation_gain_m": 1000.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="trail", planned_elevation_m=1101)]
        violation, _ = G._eval_r3(ctx, conf, sessions, "trail")
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r3_weekly_elevation_jump")

    def test_not_applicable_on_road(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 0.0, "distance_m": 0.0,
                                          "elevation_gain_m": 100.0, "has_any_activity": True})
        sessions = [session("2026-09-22", sport="running", planned_elevation_m=999999)]
        violation, skip = G._eval_r3(ctx, conf, sessions, "road")
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "not_applicable_sport")

    def test_no_reference_is_no_reference(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context()
        sessions = [session("2026-09-22", sport="trail", planned_elevation_m=99999)]
        violation, skip = G._eval_r3(ctx, conf, sessions, "trail")
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "no_reference")


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

    def test_missed_quality_session_is_ignored(self):
        ctx = base_context(health_by_date={"2026-09-24": "red"})
        sessions = [session("2026-09-24", intensity="vo2max", status="missed")]
        violation, skip = G._eval_r5(ctx, sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)


class TestR6LongRunShare(unittest.TestCase):
    """`R6_MIN_SESSIONS` (4) séances de la famille course minimum — voir
    `TestR6TooFewSessions` pour la garde elle-même."""

    def test_at_threshold_is_ok(self):
        threshold = DEFAULT_GCONF["r6_long_run_share_max_pct"]
        long_s = threshold * 10  # 350 sur un total de 1000 -> exactement `threshold` %
        rest = (1000 - long_s) / 3
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=long_s)] + [
            session(f"2026-09-2{3 + i}", sport="trail", planned_duration_s=rest) for i in range(3)
        ]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF, None)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_just_above_threshold_violates(self):
        threshold = DEFAULT_GCONF["r6_long_run_share_max_pct"]
        long_s = threshold * 10 + 1   # 351 sur 1000 -> juste au-dessus du seuil
        rest = (1000 - long_s) / 3
        sessions = [session("2026-09-22", sport="trail", planned_duration_s=long_s)] + [
            session(f"2026-09-2{3 + i}", sport="trail", planned_duration_s=rest) for i in range(3)
        ]
        violation, _ = G._eval_r6(sessions, DEFAULT_GCONF, None)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["rule_id"], "r6_long_run_share")
        self.assertEqual(violation["session_dates"], ["2026-09-22"])

    def test_no_run_family_session_is_insufficient(self):
        sessions = [session("2026-09-22", sport="cycling", planned_duration_s=5000)]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF, None)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")

    def test_missing_planned_duration_is_skipped(self):
        sessions = [session("2026-09-22", sport="trail", planned_distance_m=25000)] + [
            session(f"2026-09-2{3 + i}", sport="trail", planned_duration_s=1800) for i in range(3)
        ]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF, None)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "missing_planned_duration")

    def test_distance_only_is_estimated_with_pace_history(self):
        sessions = [session("2026-09-22", sport="trail", planned_distance_m=5000)] + [
            session(f"2026-09-2{3 + i}", sport="trail", planned_duration_s=1800) for i in range(3)
        ]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF, 300.0)
        self.assertIsNone(skip)  # ne saute plus, une estimation a pu être faite


class TestR6TooFewSessions(unittest.TestCase):
    def test_three_sessions_is_too_few(self):
        """Revue de code #98, should-fix 9 : 60/60/120 min -> 50 % ne doit pas
        déclencher R6, faute de séances assez nombreuses pour que la part soit
        un repère fiable."""
        sessions = [
            session("2026-09-22", sport="trail", planned_duration_s=3600),
            session("2026-09-24", sport="trail", planned_duration_s=3600),
            session("2026-09-27", sport="trail", planned_duration_s=7200),
        ]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF, None)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "too_few_sessions")

    def test_four_sessions_is_enough(self):
        sessions = [
            session("2026-09-21", sport="trail", planned_duration_s=1800),
            session("2026-09-22", sport="trail", planned_duration_s=1800),
            session("2026-09-24", sport="trail", planned_duration_s=1800),
            session("2026-09-27", sport="trail", planned_duration_s=7200),
        ]
        violation, skip = G._eval_r6(sessions, DEFAULT_GCONF, None)
        # 7200 / 12600 = 57 % > 35 % : devrait violer, pas être sauté pour nombre
        # de séances insuffisant.
        self.assertIsNotNone(violation)
        self.assertNotEqual((skip or {}).get("reason_code"), "too_few_sessions")


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

    def test_missed_session_does_not_count(self):
        """Revue de code #98, should-fix 4 : `missed` doit avoir le même effet
        que `cancelled`/`moved` sur R7."""
        sessions = [session("2026-09-22", intensity="vo2max"),
                    session("2026-09-23", intensity="threshold", status="missed")]
        violation, skip = G._eval_r7(sessions, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertIsNone(skip)

    def test_two_quality_sessions_same_day_violate(self):
        """Nit de la revue de code #98 : deux séances de qualité le même jour."""
        sessions = [session("2026-09-22", intensity="vo2max"),
                    session("2026-09-22", intensity="threshold", sport="cycling")]
        violation, _ = G._eval_r7(sessions, DEFAULT_GCONF)
        self.assertIsNotNone(violation)
        self.assertEqual(violation["session_dates"], ["2026-09-22"])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestGuardrailSettings(unittest.TestCase):
    def test_defaults_when_section_absent(self):
        conf = G.guardrail_settings({})
        self.assertTrue(conf["enabled"])
        self.assertEqual(conf["r1_acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertEqual(conf["severity"]["r1_acwr_projected"], "warn")
        self.assertEqual(conf["severity"]["r2_weekly_volume_jump"], "warn")
        self.assertEqual(conf["severity"]["r5_quality_after_red"], "block")

    def test_user_override_applies(self):
        conf = G.guardrail_settings({"guardrails": {"r1_acwr_max": 1.5, "enabled": False}})
        self.assertEqual(conf["r1_acwr_max"], 1.5)
        self.assertFalse(conf["enabled"])

    def test_invalid_threshold_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.guardrail_settings({"guardrails": {"r1_acwr_max": "beaucoup"}})
        self.assertEqual(conf["r1_acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertIn("avertissement", buf.getvalue())

    def test_nan_threshold_falls_back_with_warning(self):
        """Revue de code #98, should-fix 12 : NaN/inf passaient `value <= 0`
        (False pour les deux) et désactivaient silencieusement la règle."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.guardrail_settings({"guardrails": {"r1_acwr_max": float("nan")}})
        self.assertEqual(conf["r1_acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertIn("avertissement", buf.getvalue())

    def test_infinite_threshold_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.guardrail_settings({"guardrails": {"r4_monotony_max": float("inf")}})
        self.assertEqual(conf["r4_monotony_max"], G.DEFAULT_MONOTONY_MAX)
        self.assertIn("avertissement", buf.getvalue())

    def test_invalid_severity_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.guardrail_settings({"guardrails": {"severity_r1_acwr_projected": "catastrophe"}})
        self.assertEqual(conf["severity"]["r1_acwr_projected"], "warn")
        self.assertIn("avertissement", buf.getvalue())

    def test_invalid_reference_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.guardrail_settings({"guardrails": {"r2_volume_reference": "n'importe quoi"}})
        self.assertEqual(conf["r2_volume_reference"], G.DEFAULT_VOLUME_REFERENCE)
        self.assertIn("avertissement", buf.getvalue())

    def test_enabled_false_skips_everything(self):
        conf = G.guardrail_settings({"guardrails": {"enabled": False}})
        result = G.evaluate(week([session("2026-09-22", planned_duration_s=999999)]),
                             base_context(), conf)
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
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 1000.0, "distance_m": 0.0,
                                          "elevation_gain_m": 0.0, "has_any_activity": True})
        w = week([session("2026-09-22", planned_duration_s=5000)])  # gros +% -> R2 warn
        result = G.evaluate(w, ctx, conf)
        self.assertTrue(any(v["rule_id"] == "r2_weekly_volume_jump" for v in result["violations"]))
        self.assertTrue(result["ok"])  # aucune violation `block`

    def test_deterministic_ordering(self):
        conf = gconf(r2_volume_reference="previous_week")
        ctx = base_context(previous_week={"duration_s": 100.0, "distance_m": 0.0,
                                          "elevation_gain_m": 100.0, "has_any_activity": True})
        w = week([
            session("2026-09-22", intensity="vo2max", planned_duration_s=9000, planned_elevation_m=900),
            session("2026-09-23", intensity="threshold", planned_duration_s=9000),
        ])
        r1 = G.evaluate(w, ctx, conf)
        r2 = G.evaluate(w, ctx, conf)
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

    def test_same_day_sessions_are_summed_regardless_of_order(self):
        """Revue de code #98, blocker 2 : deux séances le même jour, sans
        activité réelle, doivent SOMMER leurs charges — et le résultat doit être
        identique quel que soit l'ordre des séances dans la liste."""
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 20.0
            d = date.fromordinal(d.toordinal() + 1)
        ctx = base_context(loads_by_date=loads)
        s1 = session("2026-09-22", intensity="endurance", planned_duration_s=3600)
        s2 = session("2026-09-22", intensity="tempo", planned_duration_s=1800, sport="running")
        result_ab = G.evaluate(week([s1, s2]), ctx, DEFAULT_GCONF)
        result_ba = G.evaluate(week([s2, s1]), ctx, DEFAULT_GCONF)
        self.assertEqual(result_ab["context"]["acwr_projected"], result_ba["context"]["acwr_projected"])
        only_one = G.evaluate(week([s1]), ctx, DEFAULT_GCONF)
        # Les deux séances sommées doivent peser plus qu'une seule.
        self.assertGreater(result_ab["context"]["fatigue_projected"], only_one["context"]["fatigue_projected"])

    def test_second_session_not_dropped_when_day_already_has_real_activity(self):
        """Revue de code #98, blocker 2 : un jour avec déjà une activité réelle
        indexée ne doit pas faire disparaître une seconde séance ENCORE PRÉVUE
        ce jour-là."""
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 20.0
            d = date.fromordinal(d.toordinal() + 1)
        ctx_no_activity = base_context(loads_by_date=loads, week_activities=[])
        ctx_with_activity = base_context(
            loads_by_date=loads,
            week_activities=[{"date": "2026-09-22", "sport": "strength", "load": 5.0}],
        )
        # Séance de course encore prévue le même jour qu'une séance de
        # renforcement déjà réalisée (sport différent, jamais appariée).
        s = session("2026-09-22", intensity="vo2max", planned_duration_s=3600, sport="trail")
        without = G.evaluate(week([s]), ctx_no_activity, DEFAULT_GCONF)
        with_real = G.evaluate(week([s]), ctx_with_activity, DEFAULT_GCONF)
        # La charge projetée de la séance de course doit être comptée dans LES
        # DEUX cas (elle n'est jamais appariée à l'activité de renforcement) ;
        # le cas "avec activité réelle" doit même être LÉGÈREMENT plus chargé
        # (charge réelle de force en plus).
        self.assertGreaterEqual(with_real["context"]["fatigue_projected"],
                                without["context"]["fatigue_projected"])

    def test_unmatched_real_activity_is_not_dropped(self):
        """Revue de code #98, 2e passe, BLOCKER : une activité réelle de la
        semaine sans AUCUNE séance proposée correspondante ne doit jamais
        disparaître de la série (ex. une séance de renforcement retirée de la
        proposition mais bien réalisée)."""
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 20.0
            d = date.fromordinal(d.toordinal() + 1)
        ctx_without_real = base_context(loads_by_date=loads, week_activities=[])
        ctx_with_real = base_context(
            loads_by_date=loads,
            week_activities=[{"date": "2026-09-24", "sport": "trail", "load": 72.0}],
        )
        # Semaine proposée qui ne mentionne PLUS du tout cette sortie (par
        # exemple parce qu'elle a été retirée du plan après coup, ou que la
        # proposition ne couvre qu'un autre jour) — l'activité réelle du 24
        # doit compter quand même.
        w = week([session("2026-09-22", intensity="recovery", planned_duration_s=1800)])
        without_real = G.evaluate(w, ctx_without_real, DEFAULT_GCONF)
        with_real = G.evaluate(w, ctx_with_real, DEFAULT_GCONF)
        self.assertGreater(with_real["context"]["fatigue_projected"],
                           without_real["context"]["fatigue_projected"])

    def test_partial_proposal_keeps_the_rest_of_the_weeks_real_loads(self):
        """Revue de code #98, 2e passe, BLOCKER : une proposition qui ne couvre
        QU'UN SEUL jour de la semaine (ex. seulement le dimanche) ne doit jamais
        faire disparaître les activités réelles des autres jours déjà réalisés."""
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 20.0
            d = date.fromordinal(d.toordinal() + 1)
        week_activities = [
            {"date": "2026-09-22", "sport": "trail", "load": 40.0},
            {"date": "2026-09-24", "sport": "trail", "load": 210.0},   # ex. sortie longue 3h30
            {"date": "2026-09-26", "sport": "trail", "load": 40.0},
        ]
        ctx = base_context(loads_by_date=loads, week_activities=week_activities, today="2026-09-27")
        # Proposition PARTIELLE : seule la séance du dimanche est encore là.
        partial_week = week([session("2026-09-27", intensity="recovery", planned_duration_s=1800)])
        result = G.evaluate(partial_week, ctx, DEFAULT_GCONF)
        # Référence : même historique, mais sans aucune activité réelle cette
        # semaine (pour vérifier que le calcul CHANGE bien selon leur présence).
        ctx_no_real = base_context(loads_by_date=loads, week_activities=[], today="2026-09-27")
        result_no_real = G.evaluate(partial_week, ctx_no_real, DEFAULT_GCONF)
        self.assertGreater(result["context"]["fatigue_projected"],
                           result_no_real["context"]["fatigue_projected"])


class TestInsufficientHistoryGate(unittest.TestCase):
    """Revue de code #98, blocker 1 : sans au moins `MIN_HISTORY_DAYS_FOR_PROJECTION`
    (84 j) d'historique réel, R1/R4 doivent être sautées, jamais évaluées sur un
    démarrage à froid de l'EWMA de condition."""

    def _steady_context(self, days_of_history: int) -> dict:
        loads = {}
        start = date(2026, 9, 20) - timedelta(days=days_of_history)
        d = start
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 40.0
            d += timedelta(days=1)
        return base_context(loads_by_date=loads)

    def test_three_weeks_of_history_skips_r1_but_not_r4(self):
        """R1 (84 j requis) reste sautée à 21 j d'historique ; R4 (14 j requis
        seulement, revue de code #98, 2e passe, nit) ne l'est plus."""
        ctx = self._steady_context(21)
        w = week([session(f"2026-09-{22 + i}", intensity="endurance",
                          planned_duration_s=3000) for i in range(6)])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        skipped_ids = {s["rule_id"]: s["reason_code"] for s in result["skipped_rules"]}
        self.assertEqual(skipped_ids.get("r1_acwr_projected"), "insufficient_history")
        self.assertNotIn("r4_monotony_projected", skipped_ids)
        self.assertIsNone(result["context"]["acwr_projected"])
        self.assertIsNotNone(result["context"]["monotony_projected"])

    def test_less_than_monotony_minimum_skips_r4(self):
        ctx = self._steady_context(10)  # < MIN_HISTORY_DAYS_FOR_MONOTONY (14 j)
        w = week([session(f"2026-09-{22 + i}", intensity="endurance",
                          planned_duration_s=3000) for i in range(6)])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        skipped_ids = {s["rule_id"]: s["reason_code"] for s in result["skipped_rules"]}
        self.assertEqual(skipped_ids.get("r4_monotony_projected"), "insufficient_history")

    def test_eight_weeks_of_history_is_still_skipped(self):
        """Repro exact de la revue de code #98 (blocker 1) : même à 8 semaines
        (56 j < 84 j requis), l'ACWR projeté d'une semaine STABLE ne doit pas
        être évalué — 56 j reste sous MIN_HISTORY_DAYS_FOR_PROJECTION."""
        ctx = self._steady_context(56)
        w = week([session(f"2026-09-{22 + i}", intensity="endurance",
                          planned_duration_s=3000) for i in range(6)])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        self.assertIsNone(result["context"]["acwr_projected"])

    def test_enough_history_is_evaluated(self):
        ctx = self._steady_context(100)
        w = week([session(f"2026-09-{22 + i}", intensity="endurance",
                          planned_duration_s=3000) for i in range(6)])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        self.assertIsNotNone(result["context"]["acwr_projected"])
        self.assertNotIn("r1_acwr_projected", {s["rule_id"] for s in result["skipped_rules"]
                                                if s["reason_code"] == "insufficient_history"})


class TestTodayGating(unittest.TestCase):
    """Revue de code #98, blocker/should-fix 5 : un jour de la semaine proposée
    STRICTEMENT avant `today`, sans activité réelle appariée, compte 0 — jamais
    la charge projetée (qui suppose que la séance a réellement eu lieu)."""

    def test_past_unmatched_day_counts_zero_not_projected(self):
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 20.0
            d = date.fromordinal(d.toordinal() + 1)
        # `today` un mercredi : lundi/mardi de la semaine proposée sont déjà
        # passés, sans activité réelle indexée.
        ctx_mid_week = base_context(loads_by_date=loads, today="2026-09-23")
        ctx_before_week = base_context(loads_by_date=loads, today="2026-09-20")
        s_monday = session("2026-09-21", intensity="vo2max", planned_duration_s=7200)
        result_mid_week = G.evaluate(week([s_monday]), ctx_mid_week, DEFAULT_GCONF)
        result_before = G.evaluate(week([s_monday]), ctx_before_week, DEFAULT_GCONF)
        # Avant le début de semaine, la séance du lundi est future -> projetée.
        # En milieu de semaine, le lundi est déjà passé sans activité -> 0.
        self.assertGreater(result_before["context"]["fatigue_projected"],
                           result_mid_week["context"]["fatigue_projected"])

    def test_future_day_still_projected_mid_week(self):
        loads = {}
        d = date(2026, 6, 1)
        while d < date(2026, 9, 21):
            loads[d.isoformat()] = 20.0
            d = date.fromordinal(d.toordinal() + 1)
        ctx = base_context(loads_by_date=loads, today="2026-09-23")
        s_future = session("2026-09-26", intensity="vo2max", planned_duration_s=7200)
        s_none = session("2026-09-26", intensity="rest", planned_duration_s=0)
        with_load = G.evaluate(week([s_future]), ctx, DEFAULT_GCONF)
        without_load = G.evaluate(week([s_none]), ctx, DEFAULT_GCONF)
        self.assertGreater(with_load["context"]["fatigue_projected"],
                           without_load["context"]["fatigue_projected"])


class TestDistanceOnlyEstimate(unittest.TestCase):
    def test_estimated_dates_exposed_in_context(self):
        ctx = base_context(recent_run_pace_s_km=300.0)
        w = week([session("2026-09-22", sport="trail", planned_distance_m=10000)])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        self.assertEqual(result["context"]["distance_only_sessions_estimated"], ["2026-09-22"])

    def test_no_estimate_when_duration_given(self):
        ctx = base_context(recent_run_pace_s_km=300.0)
        w = week([session("2026-09-22", sport="trail", planned_duration_s=3000,
                           planned_distance_m=10000)])
        result = G.evaluate(w, ctx, DEFAULT_GCONF)
        self.assertEqual(result["context"]["distance_only_sessions_estimated"], [])


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
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        self.assertTrue(ctx["is_race_week"])
        self.assertEqual(ctx["race_date"], "2026-09-24")

    def test_no_objective_is_not_a_race_week(self):
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
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
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        self.assertTrue(ctx["previous_week"]["has_any_activity"])
        self.assertEqual(ctx["previous_week"]["duration_s"], 3600)   # strength (hors famille course) exclue
        self.assertEqual(ctx["previous_week"]["elevation_gain_m"], 300)

    def test_bike_only_week_has_no_run_reference(self):
        """Revue de code #98, should-fix 10 : une semaine 100 % vélo n'est pas
        une référence course à pied, même si `activity` porte bien des lignes."""
        self.write("activities/2026-09-15_cycling.md",
                    {"kind": "activity", "date": "2026-09-15", "sport": "cycling", "duration_s": 7200})
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        self.assertFalse(ctx["previous_week"]["has_any_activity"])

    def test_health_verdict_is_read(self):
        self.write("medical/2026-09-20_health.md",
                    {"kind": "health", "date": "2026-09-20", "morning_check": "full",
                     "verdict": "red", "verdict_reason": "HRV basse trois jours de suite."})
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        self.assertEqual(ctx["health_by_date"].get("2026-09-20"), "red")

    def test_recent_run_pace_computed_from_real_activities(self):
        self.write("activities/2026-09-10_running.md",
                    {"kind": "activity", "date": "2026-09-10", "sport": "running",
                     "duration_s": 1800, "distance_m": 5000})  # 6:00/km = 360 s/km
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        self.assertAlmostEqual(ctx["recent_run_pace_s_km"], 360.0, places=3)

    def test_recent_run_pace_excludes_hiking_and_walking(self):
        """Revue de code #98, 2e passe, should-fix : la randonnée/la marche sont
        nettement plus lentes et ne doivent jamais entrer dans la médiane
        d'allure COURSE — sans quoi elles la gonfleraient (surestimation de la
        durée d'une séance de course estimée depuis cette allure)."""
        self.write("activities/2026-09-10_running.md",
                    {"kind": "activity", "date": "2026-09-10", "sport": "running",
                     "duration_s": 1800, "distance_m": 5000})   # 360 s/km
        self.write("activities/2026-09-12_hiking.md",
                    {"kind": "activity", "date": "2026-09-12", "sport": "hiking",
                     "duration_s": 7200, "distance_m": 5000})   # 1440 s/km (marche)
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        # Médiane sur running SEUL (360 s/km) : la randonnée ne doit pas la faire
        # dériver vers une allure plus lente.
        self.assertAlmostEqual(ctx["recent_run_pace_s_km"], 360.0, places=3)

    def test_recent_run_pace_uses_flat_equivalent_distance(self):
        """Revue de code #98, 2e passe, should-fix : l'allure de référence doit
        être calculée sur la distance ÉQUIVALENT PLAT (distance + D+ ×
        TRAIL_FLAT_M_PER_M_DPLUS), pas la distance brute — sinon le D+ compterait
        deux fois quand cette même allure sert ensuite à estimer une séance
        elle-même prescrite en distance + D+."""
        import arc_metrics as M
        # 10 km + 500 m D+ en 1h. Équivalent plat = 10000 + 500*1.75 = 10875 m.
        self.write("activities/2026-09-10_trail.md",
                    {"kind": "activity", "date": "2026-09-10", "sport": "trail",
                     "duration_s": 3600, "distance_m": 10000, "elevation_gain_m": 500})
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        expected = 3600 / ((10000 + 500 * M.TRAIL_FLAT_M_PER_M_DPLUS) / 1000.0)
        self.assertAlmostEqual(ctx["recent_run_pace_s_km"], expected, places=3)
        # Allure sur distance BRUTE (fausse, sans la correction D+) serait de
        # 360 s/km — nettement différente : la correction doit être active.
        self.assertNotAlmostEqual(ctx["recent_run_pace_s_km"], 360.0, places=1)

    def test_recent_run_pace_none_without_history(self):
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        self.assertIsNone(ctx["recent_run_pace_s_km"])

    def test_week_activities_scoped_to_the_proposed_week(self):
        self.write("activities/2026-09-15_trail.md",
                    {"kind": "activity", "date": "2026-09-15", "sport": "trail", "duration_s": 3600})
        self.write("activities/2026-09-22_trail.md",
                    {"kind": "activity", "date": "2026-09-22", "sport": "trail", "duration_s": 1800})
        self.index()
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))
        dates = {a["date"] for a in ctx["week_activities"]}
        self.assertEqual(dates, {"2026-09-22"})


class TestEndToEndOnWorkspace(WorkspaceCase):
    """`build_context` + `evaluate` bout en bout sur un vrai workspace
    synthétique (index SQLite réel), cas limites combinés — revue de code #98 :
    historique court, séance manquée, prescription en distance seule, deux
    séances le même jour."""

    def test_short_history_missed_same_day_and_distance_only_combined(self):
        # Historique réel COURT (3 semaines, < 84 j requis) : R1/R4 doivent être
        # sautées, quel que soit le contenu de la semaine proposée.
        d = date(2026, 8, 31)
        while d < date(2026, 9, 21):
            self.write(f"activities/{d.isoformat()}_running.md",
                       {"kind": "activity", "date": d.isoformat(), "sport": "running",
                        "duration_s": 1800, "distance_m": 5000})
            d += timedelta(days=1)
        self.index(today="2026-09-20")
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        ctx = G.build_context(self.conn, config, gc, date(2026, 9, 21), date(2026, 9, 20))

        # Allure récente calculable (5000 m / 1800 s = 360 s/km) -> une séance
        # en distance seule peut être estimée, pas sautée.
        self.assertAlmostEqual(ctx["recent_run_pace_s_km"], 360.0, places=3)

        w = week([
            # Deux séances le même jour (course + renforcement) : sommées.
            session("2026-09-22", sport="running", intensity="endurance", planned_duration_s=1800),
            session("2026-09-22", sport="strength", intensity="strength", planned_duration_s=1800),
            # Séance manquée : exclue de tout calcul.
            session("2026-09-23", sport="running", intensity="tempo", planned_duration_s=3600,
                    status="missed"),
            # Prescrite en distance seule : estimée depuis l'allure récente.
            session("2026-09-27", sport="trail", intensity="endurance", planned_distance_m=10000),
        ])
        result = G.evaluate(w, ctx, gc)
        skipped = {s["rule_id"]: s["reason_code"] for s in result["skipped_rules"]}
        self.assertEqual(skipped.get("r1_acwr_projected"), "insufficient_history")
        # R4 (14 j requis, revue de code #98, 2e passe, nit) EST évaluable ici
        # (21 j d'historique réel), contrairement à R1 (84 j requis).
        self.assertNotIn("r4_monotony_projected", skipped)
        self.assertEqual(result["context"]["distance_only_sessions_estimated"], ["2026-09-27"])
        # Historique réel présent mais toujours court : `history_span_days` doit
        # rester sous le seuil minimal.
        self.assertLess(result["context"]["history_span_days"], G.MIN_HISTORY_DAYS_FOR_PROJECTION)


class TestMultiWeekAcwrProjection(WorkspaceCase):
    """#69, revue de code (2e tour), BLOCKER : `check --week-start` pour une
    semaine au-delà de la prochaine, dans un plan multi-semaines, ignorait la
    charge PLANIFIÉE des semaines intercalaires (`today` -> veille de
    `week_start`) — ces jours comptaient comme un repos complet dans l'ACWR
    projeté, sous-estimant le risque. `_intervening_weeks_loads` répare ça en
    réutilisant le même estimateur que pour la semaine proposée elle-même."""

    TODAY = date(2026, 9, 27)
    HISTORY_DAYS = 119   # > MIN_HISTORY_DAYS_FOR_PROJECTION (84 j)

    def _write_history(self):
        """119 jours de charge constante (~60/jour : 40 min à RPE 5, la même
        formule que `projected_session_load` — voir `arc_metrics.session_load`,
        repli sRPE sans FC) jusqu'à la veille de `today`."""
        d = self.TODAY - timedelta(days=self.HISTORY_DAYS)
        while d < self.TODAY:
            self.write(f"activities/{d.isoformat()}_running.md",
                       {"kind": "activity", "date": d.isoformat(), "sport": "running",
                        "duration_s": 2400, "rpe": 5})
            d += timedelta(days=1)

    def _week_sessions(self, start: date) -> list:
        """7 séances quotidiennes d'endurance, 50 min chacune : charge PROJETÉE
        de 60 par jour (`INTENSITY_RPE["endurance"] == 4`,
        `(3000 / 60) * 4 * arc_metrics.RPE_TO_TRIMP == 60`) — la même échelle
        que la charge réelle ci-dessus, pour un plan qui prolonge simplement le
        régime déjà en place (ACWR qui devrait rester stable autour de 1)."""
        out = []
        d = start
        for _ in range(7):
            out.append(session(d.isoformat(), sport="running", intensity="endurance",
                               planned_duration_s=3000))
            d += timedelta(days=1)
        return out

    def test_week_plus_two_acwr_is_understated_without_intervening_week(self):
        """Repro du bug : sans `other_weeks`, la semaine +2 ignore les séances
        planifiées de la semaine +1 (intercalaire) — ACWR sous-estimé."""
        self._write_history()
        self.index(today=self.TODAY.isoformat())
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        week1_start, week2_start = date(2026, 9, 28), date(2026, 10, 5)

        ctx1 = G.build_context(self.conn, config, gc, week1_start, self.TODAY)
        w1 = week(self._week_sessions(week1_start), week_start=week1_start.isoformat())
        acwr_week1 = G.evaluate(w1, ctx1, gc)["context"]["acwr_projected"]

        ctx2_broken = G.build_context(self.conn, config, gc, week2_start, self.TODAY)
        w2 = week(self._week_sessions(week2_start), week_start=week2_start.isoformat())
        acwr_week2_broken = G.evaluate(w2, ctx2_broken, gc)["context"]["acwr_projected"]

        # Charge constante avant ET après `today` : l'ACWR de la semaine +1 doit
        # déjà être proche de 1 (pas de rupture de rythme). Sans `other_weeks`,
        # la semaine +2 (qui saute la charge intercalaire de la +1) doit tomber
        # NETTEMENT en dessous — c'est le bug.
        self.assertAlmostEqual(acwr_week1, 1.021, places=3)
        self.assertAlmostEqual(acwr_week2_broken, 0.923, places=3)
        self.assertLess(acwr_week2_broken, acwr_week1 - 0.05)

    def test_week_plus_two_acwr_is_corrected_with_intervening_week(self):
        """Même scénario, `other_weeks=[semaine_1]` (comme `main()` le fait
        désormais à partir de `raw_block["weeks"]`) : l'ACWR de la semaine +2
        remonte près de celui de la semaine +1 — le plan reste cohérent."""
        self._write_history()
        self.index(today=self.TODAY.isoformat())
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        week1_start, week2_start = date(2026, 9, 28), date(2026, 10, 5)
        w1 = week(self._week_sessions(week1_start), week_start=week1_start.isoformat())
        w2 = week(self._week_sessions(week2_start), week_start=week2_start.isoformat())

        ctx2_fixed = G.build_context(self.conn, config, gc, week2_start, self.TODAY, [w1])
        acwr_week2_fixed = G.evaluate(w2, ctx2_fixed, gc)["context"]["acwr_projected"]

        self.assertAlmostEqual(acwr_week2_fixed, 1.042, places=3)

    def test_intervening_week_respects_excluded_and_real_activity(self):
        """`_intervening_weeks_loads` doit respecter les mêmes règles que la
        semaine proposée elle-même : une séance intercalaire ANNULÉE n'ajoute
        rien, et un jour déjà couvert par une activité RÉELLE indexée (séance
        de la semaine +1 déjà faite) ne compte pas sa charge deux fois."""
        self._write_history()
        # La semaine +1 a en réalité déjà commencé : son premier jour est fait
        # (activité réelle indexée), avec une charge DIFFÉRENTE de la charge
        # planifiée (90 au lieu de 60) — la charge réelle doit prévaloir.
        week1_start = date(2026, 9, 28)
        self.write(f"activities/{week1_start.isoformat()}_running.md",
                   {"kind": "activity", "date": week1_start.isoformat(), "sport": "running",
                    "duration_s": 3600, "rpe": 5})   # (3600/60)*5*0.3 = 90
        self.index(today=self.TODAY.isoformat())
        config = I.load_config(self.ws)
        gc = G.guardrail_settings(config)
        week2_start = date(2026, 10, 5)

        sessions1 = self._week_sessions(week1_start)
        sessions1[1]["status"] = "cancelled"   # 2e jour : annulée, ne doit rien ajouter
        # (le premier jour, déjà réel ci-dessus, reste "planned" dans le plan —
        # `resolve_sessions` doit l'apparier à l'activité réelle plutôt que
        # d'ajouter sa charge projetée par-dessus.)
        w1 = week(sessions1, week_start=week1_start.isoformat())

        loads = G._intervening_weeks_loads(
            self.conn, recent_pace_s_km=None, other_weeks=[w1],
            today=self.TODAY, week_start=week2_start)
        first_day = week1_start.isoformat()
        self.assertAlmostEqual(loads[first_day], 90.0, places=3)   # réel, pas 60 projeté
        second_day = (week1_start + timedelta(days=1)).isoformat()
        # Annulée : ni la charge projetée (60) ni aucune autre valeur ajoutée —
        # absente de `loads`, exactement comme un jour de repos non planifié.
        self.assertNotIn(second_day, loads)


class TestSelectWeekEntry(unittest.TestCase):
    """`arc_guardrails._select_week_entry` (#69, revue de code du 27/09,
    blocker) — unitaire, sans passer par le CLI/subprocess."""

    def multi(self, *week_starts):
        return {"arc": 1, "kind": "week", "weeks": [
            {"week_start": ws, "location": "Tournai", "sessions": []} for ws in week_starts
        ]}

    def test_legacy_single_week_is_returned_unchanged(self):
        block = {"arc": 1, "kind": "week", "week_start": "2026-09-21", "location": "Tournai", "sessions": []}
        self.assertIs(G._select_week_entry(block, date(2026, 9, 20)), block)

    def test_legacy_single_week_matching_week_start_arg_is_accepted(self):
        block = {"arc": 1, "kind": "week", "week_start": "2026-09-21", "location": "Tournai", "sessions": []}
        self.assertIs(G._select_week_entry(block, date(2026, 9, 20), "2026-09-21"), block)

    def test_legacy_single_week_mismatched_week_start_arg_raises(self):
        block = {"arc": 1, "kind": "week", "week_start": "2026-09-21", "location": "Tournai", "sessions": []}
        with self.assertRaises(G.ConfigError):
            G._select_week_entry(block, date(2026, 9, 20), "2026-09-28")

    def test_default_picks_the_week_containing_today(self):
        block = self.multi("2026-09-21", "2026-09-28")
        chosen = G._select_week_entry(block, date(2026, 9, 24))   # jeudi de la semaine 1
        self.assertEqual(chosen["week_start"], "2026-09-21")

    def test_default_on_sunday_before_an_upcoming_week_picks_it(self):
        """BLOQUANT : aucune semaine du fichier ne couvre `today` lui-même (la
        semaine courante vit ailleurs) — la prochaine à venir est choisie plutôt
        que de lever une erreur."""
        block = self.multi("2026-09-28", "2026-10-05")
        chosen = G._select_week_entry(block, date(2026, 9, 27))   # dimanche
        self.assertEqual(chosen["week_start"], "2026-09-28")

    def test_explicit_week_start_overrides_the_default(self):
        block = self.multi("2026-09-21", "2026-09-28", "2026-10-05")
        chosen = G._select_week_entry(block, date(2026, 9, 20), "2026-10-05")
        self.assertEqual(chosen["week_start"], "2026-10-05")

    def test_explicit_week_start_outside_all_weeks_raises(self):
        block = self.multi("2026-09-21", "2026-09-28")
        with self.assertRaises(G.ConfigError):
            G._select_week_entry(block, date(2026, 9, 20), "2026-11-02")

    def test_no_week_on_or_after_today_raises_with_hint(self):
        block = self.multi("2026-09-21", "2026-09-28")
        with self.assertRaises(G.ConfigError) as cm:
            G._select_week_entry(block, date(2026, 12, 14))
        self.assertIn("--week-start", str(cm.exception))


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
        self.assertEqual(result.returncode, 2)
        self.assertIn("week_start", result.stderr)

    def test_missing_file_is_exit_code_two_not_one(self):
        """Revue de code #98, should-fix 11 : un fichier introuvable ne doit
        JAMAIS ressortir en code 1 (confondu avec « violation bloquante »)."""
        result = self._run("check", "--week", str(self.ws / "planning/absent.md"),
                            "--workspace", str(self.ws))
        self.assertEqual(result.returncode, 2)

    def test_non_monday_week_start_is_rejected(self):
        payload = {"week_start": "2026-09-22", "location": "Tournai", "sessions": []}
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 2)
        self.assertIn("lundi", result.stderr)

    def test_non_numeric_duration_is_rejected_by_contract_validation(self):
        payload = {"week_start": "2026-09-21", "location": "Tournai",
                   "sessions": [{"date": "2026-09-22", "sport": "trail", "title": "EF",
                                 "planned_duration_s": "beaucoup", "intensity": "endurance"}]}
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 2)

    def test_missing_location_is_rejected_by_contract_validation(self):
        payload = {"week_start": "2026-09-21", "sessions": [
            {"date": "2026-09-22", "sport": "trail", "title": "EF", "intensity": "endurance"}]}
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 2)

    def test_missed_session_status_is_valid_input(self):
        payload = {"week_start": "2026-09-21", "location": "Tournai",
                   "sessions": [{"date": "2026-09-22", "sport": "trail", "title": "EF",
                                 "planned_duration_s": 3000, "intensity": "endurance",
                                 "status": "missed"}]}
        result = self._run("check", "--week", "-", "--workspace", str(self.ws),
                            "--today", "2026-09-20", input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _multi_week_file(self):
        self.write("planning/Semaine_2026-09-21.md", {
            "kind": "week",
            "weeks": [
                {"week_start": "2026-09-21", "location": "Tournai",
                 "sessions": [{"date": "2026-09-22", "sport": "trail", "title": "EF S1",
                               "planned_duration_s": 3000, "intensity": "endurance"}]},
                {"week_start": "2026-09-28", "location": "Tournai",
                 "sessions": [{"date": "2026-09-29", "sport": "trail", "title": "EF S2",
                               "planned_duration_s": 3000, "intensity": "endurance"}]},
                {"week_start": "2026-10-05", "location": "Tournai",
                 "sessions": [{"date": "2026-10-06", "sport": "trail", "title": "EF S3",
                               "planned_duration_s": 3000, "intensity": "endurance"}]},
            ],
        })

    def test_check_on_multi_week_file_selects_the_week_of_today(self):
        """#69 : `--week` sur un fichier `weeks[]` doit vérifier la semaine du
        lundi de `--today`, pas « la première du fichier »."""
        self._multi_week_file()
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_2026-09-21.md"),
                            "--workspace", str(self.ws), "--today", "2026-09-27")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("ok", payload)

    def test_check_on_multi_week_file_the_sunday_before_selects_the_upcoming_week(self):
        """BLOQUANT (revue de code #69, review du 27/09) — repro exacte : deux
        semaines à venir (2026-09-28, 2026-10-05), aucune semaine « courante »
        dans ce fichier (elle vit dans un autre fichier dédié). Un dimanche
        (2026-09-27, `week.weekday() == 6`) juste avant que la première ne
        commence, `check --week` doit pouvoir la vérifier À L'AVANCE (garde-fou
        mandatory avant tout push Garmin, voir `garmin-workout-scheduling`/
        `garmin-daily-sync` étape 4) SANS `--week-start` — et sans que
        faux-dater `--today` (qui fausserait la projection ACWR) ne soit
        nécessaire pour l'atteindre. Avant #69 (revue de code), ceci sortait en
        code 2 (« aucune semaine du 2026-09-22 » — le lundi de --today lui-même,
        absent du fichier)."""
        self.write("planning/Semaine_next.md", {
            "kind": "week",
            "weeks": [
                {"week_start": "2026-09-28", "location": "Tournai",
                 "sessions": [{"date": "2026-09-29", "sport": "trail", "title": "EF S2",
                               "planned_duration_s": 3000, "intensity": "endurance"}]},
                {"week_start": "2026-10-05", "location": "Tournai",
                 "sessions": [{"date": "2026-10-06", "sport": "trail", "title": "EF S3",
                               "planned_duration_s": 3000, "intensity": "endurance"}]},
            ],
        })
        self.assertEqual(date.fromisoformat("2026-09-27").weekday(), 6)   # dimanche, hypothèse du test
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_next.md"),
                            "--workspace", str(self.ws), "--today", "2026-09-27")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self._run(
            "check", "--week", str(self.ws / "planning/Semaine_next.md"),
            "--workspace", str(self.ws), "--today", "2026-09-27",
            "--week-start", "2026-09-28").stdout), json.loads(result.stdout))   # même semaine que le défaut

    def test_check_on_multi_week_file_explicit_week_start_selects_week_two(self):
        self._multi_week_file()
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_2026-09-21.md"),
                            "--workspace", str(self.ws), "--today", "2026-09-20",
                            "--week-start", "2026-10-05")
        self.assertEqual(result.returncode, 0, result.stderr)
        # La règle de sélection par défaut (première semaine >= lundi de --today)
        # aurait pris 2026-09-21 : la preuve que --week-start l'a bien emporté est
        # que la charge projetée (r1) ne référence que les séances DE cette
        # semaine (aucune levée d'erreur/plantage sur la semaine 3, la plus
        # tardive) — on vérifie surtout l'absence d'erreur de sélection ici, le
        # détail du contexte est verrouillé par les tests unitaires de
        # `_select_week_entry`.
        payload = json.loads(result.stdout)
        self.assertIn("ok", payload)

    def test_check_on_multi_week_file_without_any_upcoming_week_is_a_clean_error(self):
        """Toutes les semaines du fichier sont déjà passées : erreur claire,
        jamais « la première du fichier » choisie par défaut."""
        self._multi_week_file()
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_2026-09-21.md"),
                            "--workspace", str(self.ws), "--today", "2026-12-14")
        self.assertEqual(result.returncode, 2)
        self.assertIn("2026-12-14", result.stderr)
        self.assertIn("--week-start", result.stderr)

    def test_check_on_multi_week_file_week_start_outside_all_weeks_is_a_clean_error(self):
        self._multi_week_file()
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_2026-09-21.md"),
                            "--workspace", str(self.ws), "--today", "2026-09-20",
                            "--week-start", "2026-11-02")
        self.assertEqual(result.returncode, 2)
        self.assertIn("2026-11-02", result.stderr)

    def test_check_warns_when_selected_week_is_shadowed(self):
        """#69, revue de code should-fix 5 : le fichier multi-semaines vérifié
        n'est pas le fichier DÉDIÉ de la semaine choisie — priorité au fichier
        dédié (#69) — un avertissement doit accompagner un résultat par ailleurs
        normal (le contrôle porte sur le contenu propre du fichier)."""
        self._multi_week_file()
        self.write("planning/Semaine_2026-09-28.md", {
            "kind": "week", "week_start": "2026-09-28", "location": "Tournai",
            "sessions": [{"date": "2026-09-29", "sport": "trail", "title": "EF dédiée",
                          "planned_duration_s": 3000, "intensity": "endurance"}],
        })
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_2026-09-21.md"),
                            "--workspace", str(self.ws), "--today", "2026-09-20",
                            "--week-start", "2026-09-28")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("éclipsée", result.stderr)
        self.assertIn("Semaine_2026-09-28.md", result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("shadowed_warning", payload)

    def test_check_week_start_wires_intervening_weeks_into_acwr(self):
        """#69, revue de code (2e tour), BLOCKER, bout en bout : `main()` doit
        calculer `other_weeks` depuis `raw_block["weeks"]` tout seul et le
        transmettre à `build_context` — verrouille le câblage CLI, la logique
        de calcul elle-même est testée dans `TestMultiWeekAcwrProjection`."""
        today = date(2026, 9, 27)
        d = today - timedelta(days=119)
        while d < today:
            self.write(f"activities/{d.isoformat()}_running.md",
                       {"kind": "activity", "date": d.isoformat(), "sport": "running",
                        "duration_s": 2400, "rpe": 5})
            d += timedelta(days=1)

        def week_sessions(start):
            out, dd = [], start
            for _ in range(7):
                out.append({"date": dd.isoformat(), "sport": "running", "title": "EF",
                            "intensity": "endurance", "planned_duration_s": 3000})
                dd += timedelta(days=1)
            return out

        week1_start, week2_start = date(2026, 9, 28), date(2026, 10, 5)
        self.write("planning/Semaine_2026-09-28.md", {
            "kind": "week",
            "weeks": [
                {"week_start": week1_start.isoformat(), "location": "Tournai",
                 "sessions": week_sessions(week1_start)},
                {"week_start": week2_start.isoformat(), "location": "Tournai",
                 "sessions": week_sessions(week2_start)},
            ],
        })
        result = self._run("check", "--week", str(self.ws / "planning/Semaine_2026-09-28.md"),
                            "--workspace", str(self.ws), "--today", today.isoformat(),
                            "--week-start", week2_start.isoformat())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        # Même valeur que `TestMultiWeekAcwrProjection.
        # test_week_plus_two_acwr_is_corrected_with_intervening_week` (même
        # scénario) : la charge de la semaine intercalaire (+1) est bien entrée
        # dans la projection, pas le chiffre sous-estimé (0.923) qu'on aurait
        # sans le câblage `other_weeks`.
        self.assertAlmostEqual(payload["context"]["acwr_projected"], 1.042, places=3)


# ---------------------------------------------------------------------------
# R8 — pic de charge d'une séance (#338, Frandsen et al., BJSM 2025)
# ---------------------------------------------------------------------------


def hist(day, km, source="activity"):
    return {"date": day, "distance_m": km * 1000.0, "source": source}


class TestSpikeBoundaries(unittest.TestCase):
    """Bornes exactes de l'article : <= 1,10 référence, <= 1,30 faible, <= 2,00 modéré."""
    DAY = date(2026, 9, 30)

    def _cat(self, km, ref_km=10.0):
        return G.evaluate_spike(self.DAY, km * 1000.0, [hist("2026-09-20", ref_km)])

    def test_exact_upper_bounds_are_inclusive(self):
        self.assertEqual(self._cat(11.0)["category"], "reference")      # 1,10
        self.assertEqual(self._cat(13.0)["category"], "low")            # 1,30
        self.assertEqual(self._cat(20.0)["category"], "moderate")       # 2,00

    def test_just_above_each_bound_changes_category(self):
        self.assertEqual(self._cat(11.01)["category"], "low")
        self.assertEqual(self._cat(13.01)["category"], "moderate")
        self.assertEqual(self._cat(20.01)["category"], "large")

    def test_float_noise_does_not_tip_a_bound(self):
        # 8,8 / 8,0 et 10,4 / 8,0 : bornes exactes en décimal, pas toujours en binaire.
        self.assertEqual(G.evaluate_spike(self.DAY, 8800.0, [hist("2026-09-20", 8.0)])["category"], "reference")
        self.assertEqual(G.evaluate_spike(self.DAY, 10400.0, [hist("2026-09-20", 8.0)])["category"], "low")

    def test_hazard_ratios_and_confidence_intervals(self):
        self.assertEqual((self._cat(10)["hazard_ratio"], self._cat(10)["hazard_ratio_ci95"]), (1.0, None))
        self.assertEqual((self._cat(12)["hazard_ratio"], self._cat(12)["hazard_ratio_ci95"]), (1.64, [1.31, 2.05]))
        self.assertEqual((self._cat(15)["hazard_ratio"], self._cat(15)["hazard_ratio_ci95"]), (1.52, [1.16, 2.0]))
        self.assertEqual((self._cat(25)["hazard_ratio"], self._cat(25)["hazard_ratio_ci95"]), (2.28, [1.5, 3.48]))

    def test_category_does_not_depend_on_the_rounded_display_ratio(self):
        ev = G.evaluate_spike(self.DAY, 13004.0, [hist("2026-09-20", 10.0)])
        self.assertEqual(ev["ratio"], 1.3)
        self.assertEqual(ev["category"], "moderate")   # 1,3004 > 1,30


class TestSpikeWindow(unittest.TestCase):
    DAY = date(2026, 9, 30)

    def test_current_day_is_excluded(self):
        ev = G.evaluate_spike(self.DAY, 10000.0, [hist("2026-09-30", 40.0), hist("2026-09-25", 10.0)])
        self.assertEqual(ev["reference_distance_m"], 10000.0)
        self.assertEqual(ev["window_sessions"], 1)

    def test_day_minus_30_is_included_day_minus_31_is_not(self):
        ev30 = G.evaluate_spike(self.DAY, 10000.0, [hist("2026-08-31", 10.0)])   # J-30
        self.assertEqual(ev30["status"], "ok")
        self.assertEqual(ev30["reference_date"], "2026-08-31")
        ev31 = G.evaluate_spike(self.DAY, 10000.0, [hist("2026-08-30", 10.0)])   # J-31
        self.assertEqual(ev31["status"], "insufficient_history")
        self.assertIsNone(ev31["ratio"])

    def test_future_entries_are_ignored(self):
        ev = G.evaluate_spike(self.DAY, 10000.0, [hist("2026-10-02", 40.0)])
        self.assertEqual(ev["status"], "insufficient_history")

    def test_reference_is_the_longest_not_the_most_recent(self):
        ev = G.evaluate_spike(self.DAY, 12000.0, [hist("2026-09-01", 20.0), hist("2026-09-28", 6.0)])
        self.assertEqual(ev["reference_distance_m"], 20000.0)
        self.assertEqual(ev["category"], "reference")

    def test_no_history_gives_no_ratio(self):
        ev = G.evaluate_spike(self.DAY, 10000.0, [])
        self.assertEqual(ev["status"], "insufficient_history")
        self.assertIsNone(ev["ratio"])
        self.assertIn("historique insuffisant", G.spike_text(ev))

    def test_session_without_distance_concludes_nothing(self):
        ev = G.evaluate_spike(self.DAY, None, [hist("2026-09-20", 10.0)])
        self.assertEqual(ev["status"], "no_distance")
        self.assertIsNone(ev["ratio"])
        self.assertIn("sans distance", G.spike_text(ev))


class TestR8Rule(unittest.TestCase):
    TODAY = date(2026, 9, 20)

    def _spikes(self, sessions, history, today=TODAY):
        ctx = base_context(spike_history=history)
        return G._planned_session_spikes(sessions, ctx, today)

    def test_moderate_planned_session_is_a_warn_not_a_block(self):
        spikes = self._spikes([session("2026-09-24", planned_distance_m=16000)], [hist("2026-09-10", 10.0)])
        violation, skip = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertIsNone(skip)
        self.assertEqual(violation["rule_id"], "r8_session_spike")
        self.assertEqual(violation["severity"], "warn")
        self.assertEqual(violation["session_dates"], ["2026-09-24"])
        self.assertEqual(violation["values"]["observed"], 1.6)
        self.assertIn("> 10 %", violation["message"])
        self.assertIn("(ratio 1,60)", violation["message"])
        self.assertIn("sans gradient régulier", violation["message"])
        self.assertEqual(violation["values"]["threshold"], 1.10)

    def test_low_category_is_a_violation_too(self):
        spikes = self._spikes([session("2026-09-24", planned_distance_m=12000)], [hist("2026-09-10", 10.0)])
        self.assertEqual(spikes[0]["category"], "low")
        self.assertEqual(spikes[0]["hazard_ratio"], 1.64)
        violation, _ = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertEqual(violation["severity"], "warn")
        self.assertIn("HR 1,64 (IC95 1,31–2,05)", violation["message"])

    def test_reference_category_is_not_a_violation(self):
        spikes = self._spikes([session("2026-09-24", planned_distance_m=11000)], [hist("2026-09-10", 10.0)])
        self.assertEqual(spikes[0]["category"], "reference")
        self.assertEqual(G._eval_r8(spikes, DEFAULT_GCONF), (None, None))

    def test_observed_is_the_raw_ratio(self):
        spikes = self._spikes([session("2026-09-24", planned_distance_m=11004)], [hist("2026-09-10", 10.0)])
        violation, _ = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertEqual(violation["values"]["observed"], 1.1004)
        self.assertEqual(spikes[0]["ratio"], 1.1)

    def test_hiking_and_walking_are_not_evaluated(self):
        for sport in ("hiking", "walking"):
            self.assertEqual(self._spikes([session("2026-09-24", sport=sport, planned_distance_m=25000)],
                                          [hist("2026-09-10", 10.0)]), [])
        self.assertEqual(G.SPIKE_SPORTS, ("running", "trail"))

    def test_past_and_already_done_days_are_not_evaluated(self):
        sessions = [session("2026-09-18", planned_distance_m=30000),    # passée
                    session("2026-09-22", planned_distance_m=30000),    # déjà courue ce jour-là
                    session("2026-09-24", planned_distance_m=30000)]
        spikes = self._spikes(sessions, [hist("2026-09-10", 10.0), hist("2026-09-22", 5.0)])
        self.assertEqual([e["date"] for e in spikes], ["2026-09-24"])

    def test_same_day_sessions_are_each_compared_on_their_own(self):
        sessions = [session("2026-09-24", planned_distance_m=8000), session("2026-09-24", planned_distance_m=16000)]
        spikes = self._spikes(sessions, [hist("2026-09-10", 10.0)])
        self.assertEqual([e["category"] for e in spikes], ["reference", "moderate"])
        # le matin (8 km) n'entre pas dans l'historique du soir : même jour exclu
        self.assertEqual(spikes[1]["reference_distance_m"], 10000.0)

    def test_nothing_to_evaluate_has_its_own_reason_code(self):
        _, skip = G._eval_r8([], DEFAULT_GCONF)
        self.assertEqual(skip["reason_code"], "nothing_to_evaluate")

    def test_french_formatting_and_short_notification(self):
        ev = G.evaluate_spike(date(2026, 10, 30), 16000.0, [hist("2026-10-25", 11.0)])
        self.assertEqual(G.spike_notification(ev),
                         "Pic de charge : 16 km = 1,45 × la plus longue sortie des 30 j (11 km le 25/10)")
        self.assertIn("(ratio 1,45)", G.spike_text(ev))
        self.assertIn("catégorie modéré, HR 1,52 (IC95 1,16–2,00)", G.spike_text(ev))

    def test_large_planned_session(self):
        spikes = self._spikes([session("2026-09-24", planned_distance_m=25000)], [hist("2026-09-10", 10.0)])
        violation, _ = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertEqual(violation["values"]["observed"], 2.5)
        self.assertIn("important", violation["message"])

    def test_severity_is_configurable_but_not_block_by_default(self):
        self.assertEqual(G.DEFAULT_SEVERITY["r8_session_spike"], "warn")
        spikes = self._spikes([session("2026-09-24", planned_distance_m=25000)], [hist("2026-09-10", 10.0)])
        violation, _ = G._eval_r8(spikes, gconf(severity_r8_session_spike="info"))
        self.assertEqual(violation["severity"], "info")

    def test_no_history_is_skipped_as_insufficient_history(self):
        spikes = self._spikes([session("2026-09-24", planned_distance_m=25000)], [])
        violation, skip = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "insufficient_history")
        self.assertIn("historique insuffisant", skip["reason"])

    def test_session_without_distance_is_skipped_never_estimated(self):
        spikes = self._spikes([session("2026-09-24", planned_duration_s=7200)], [hist("2026-09-10", 10.0)])
        self.assertEqual(spikes[0]["status"], "no_distance")
        violation, skip = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertIsNone(violation)
        self.assertEqual(skip["reason_code"], "missing_planned_distance")

    def test_unresolved_session_does_not_hide_a_resolved_one(self):
        spikes = self._spikes([session("2026-09-22", planned_duration_s=3600),
                               session("2026-09-24", planned_distance_m=25000)], [hist("2026-09-10", 10.0)])
        violation, _ = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertEqual(violation["session_dates"], ["2026-09-24"])

    def test_bike_is_ignored(self):
        spikes = self._spikes([session("2026-09-22", sport="cycling", planned_distance_m=90000)], [])
        self.assertEqual(spikes, [])
        _, skip = G._eval_r8(spikes, DEFAULT_GCONF)
        self.assertEqual(skip["reason_code"], "nothing_to_evaluate")

    def test_earlier_planned_session_of_the_week_is_history(self):
        sessions = [session("2026-09-22", planned_distance_m=10000),
                    session("2026-09-26", planned_distance_m=25000)]
        spikes = self._spikes(sessions, [], today=date(2026, 9, 21))
        self.assertEqual(spikes[0]["status"], "insufficient_history")
        self.assertEqual(spikes[1]["ratio"], 2.5)
        self.assertEqual(spikes[1]["reference_source"], "plan")

    def test_realised_activity_replaces_the_plan_of_that_day(self):
        sessions = [session("2026-09-22", planned_distance_m=30000),
                    session("2026-09-26", planned_distance_m=12000)]
        spikes = self._spikes(sessions, [hist("2026-09-22", 8.0)], today=date(2026, 9, 25))
        self.assertEqual(len(spikes), 1)   # la séance du 22 est passée : plus évaluée
        self.assertEqual(spikes[0]["reference_distance_m"], 8000.0)   # le réalisé, pas les 30 km prévus
        self.assertEqual(spikes[0]["category"], "moderate")

    def test_past_planned_session_without_activity_is_not_history(self):
        sessions = [session("2026-09-22", planned_distance_m=30000),
                    session("2026-09-26", planned_distance_m=12000)]
        spikes = self._spikes(sessions, [], today=date(2026, 9, 25))
        self.assertEqual(spikes[0]["status"], "insufficient_history")

    def test_excluded_planned_session_is_not_history(self):
        sessions = [session("2026-09-22", planned_distance_m=30000, status="cancelled"),
                    session("2026-09-26", planned_distance_m=12000)]
        spikes = self._spikes(sessions, [], today=date(2026, 9, 20))
        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0]["status"], "insufficient_history")

    def test_race_week_skips_r8(self):
        ctx = base_context(is_race_week=True, spike_history=[hist("2026-09-10", 10.0)])
        result = G.evaluate(week([session("2026-09-24", planned_distance_m=40000)]), ctx, DEFAULT_GCONF)
        skipped = {s["rule_id"]: s for s in result["skipped_rules"]}
        self.assertEqual(skipped["r8_session_spike"]["reason_code"], "race_week")

    def test_evaluate_exposes_the_evaluation_and_hides_the_internal_history(self):
        ctx = base_context(spike_history=[hist("2026-09-10", 10.0)])
        result = G.evaluate(week([session("2026-09-24", planned_distance_m=16000)]), ctx, DEFAULT_GCONF)
        self.assertIn("r8_session_spike", [v["rule_id"] for v in result["violations"]])
        self.assertTrue(result["ok"])
        self.assertEqual(result["context"]["session_spike"][0]["category"], "moderate")
        self.assertNotIn("spike_history", result["context"])

    def test_r8_label_and_default_severity_are_registered(self):
        self.assertIn("r8_session_spike", G.RULE_IDS)
        self.assertIn("r8_session_spike", G.RULE_LABELS)


class TestR8OnWorkspace(WorkspaceCase):
    def _activity(self, day, km, sport="trail", **extra):
        self.write(f"activities/{day}_{sport}.md",
                   {"kind": "activity", "date": day, "sport": sport, "duration_s": 3600,
                    "distance_m": km * 1000.0, **extra})

    def _run(self, *args, input_text=None):
        cmd = [sys.executable, str(REPO / "scripts/arc_guardrails.py"), *args, "--workspace", str(self.ws)]
        return subprocess.run(cmd, input=input_text, capture_output=True, text=True)

    def test_build_context_reads_run_family_activities_only(self):
        self._activity("2026-09-10", 10.0, sport="running")
        self._activity("2026-09-12", 80.0, sport="cycling")
        self.index()
        config = I.load_config(self.ws)
        ctx = G.build_context(self.conn, config, G.guardrail_settings(config), date(2026, 9, 21), date(2026, 9, 20))
        self.assertEqual([h["date"] for h in ctx["spike_history"]], ["2026-09-10"])

    def test_check_end_to_end_flags_a_planned_spike(self):
        self._activity("2026-09-10", 10.0)
        payload = {"week_start": "2026-09-21", "location": "Tournai",
                   "sessions": [{"date": "2026-09-26", "sport": "trail", "title": "Sortie longue",
                                 "intensity": "endurance", "planned_distance_m": 25000}]}
        proc = self._run("check", "--week", "-", "--today", "2026-09-20", input_text=json.dumps(payload))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertIn("r8_session_spike", [v["rule_id"] for v in out["violations"]])
        self.assertTrue(out["ok"])
        self.assertIn("r8_session_spike", out["checked_rules"])

    def test_session_spike_subcommand_reports_the_realised_session(self):
        self._activity("2026-09-01", 8.0, sport="running")
        self._activity("2026-09-20", 12.3, avg_hr_bpm=148)
        proc = self._run("session-spike", "--date", "2026-09-20", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(len(out["sessions"]), 1)
        ev = out["sessions"][0]
        self.assertEqual(ev["category"], "moderate")
        self.assertEqual(ev["ratio"], 1.54)
        self.assertEqual(ev["hazard_ratio"], 1.52)
        self.assertEqual(ev["avg_hr_bpm"], 148)
        self.assertTrue(ev["alert"])
        self.assertEqual(out["alerts"], [ev["notification"]])
        self.assertEqual(ev["notification"], "Pic de charge : 12,3 km = 1,54 × la plus longue sortie des 30 j (8 km le 01/09)")
        self.assertIn("bjsm.bmj.com", out["source"])

    def test_session_spike_excludes_the_day_and_ignores_bike(self):
        self._activity("2026-09-20", 10.0)
        self._activity("2026-09-20", 30.0, sport="cycling")
        out = json.loads(self._run("session-spike", "--date", "2026-09-20").stdout)
        self.assertEqual([s["sport"] for s in out["sessions"]], ["trail"])
        self.assertEqual(out["sessions"][0]["status"], "insufficient_history")
        self.assertFalse(out["sessions"][0]["alert"])
        self.assertEqual(out["alerts"], [])

    def test_session_spike_low_category_is_an_alert(self):
        self._activity("2026-09-10", 10.0)
        self._activity("2026-09-20", 12.0)
        out = json.loads(self._run("session-spike", "--date", "2026-09-20").stdout)
        self.assertEqual(out["sessions"][0]["category"], "low")
        self.assertEqual(out["sessions"][0]["hazard_ratio"], 1.64)
        self.assertEqual(out["alerts"], ["Pic de charge : 12 km = 1,20 × la plus longue sortie des 30 j (10 km le 10/09)"])

    def test_session_spike_reference_category_is_not_an_alert(self):
        self._activity("2026-09-10", 10.0)
        self._activity("2026-09-20", 11.0)
        out = json.loads(self._run("session-spike", "--date", "2026-09-20").stdout)
        self.assertEqual(out["sessions"][0]["category"], "reference")
        self.assertEqual(out["alerts"], [])

    def test_session_spike_ignores_hiking_as_session_and_as_reference(self):
        self._activity("2026-09-10", 25.0, sport="hiking")      # une rando n'est pas une référence
        self._activity("2026-09-12", 10.0, sport="running")
        self._activity("2026-09-20", 25.0, sport="hiking")      # ni une séance évaluée
        self._activity("2026-09-20", 12.0, sport="trail")
        out = json.loads(self._run("session-spike", "--date", "2026-09-20").stdout)
        self.assertEqual([s["sport"] for s in out["sessions"]], ["trail"])
        self.assertEqual(out["sessions"][0]["reference_distance_m"], 10000.0)

    def test_hiking_is_not_history_in_build_context(self):
        self._activity("2026-09-10", 22.0, sport="hiking")
        self.index()
        config = I.load_config(self.ws)
        ctx = G.build_context(self.conn, config, G.guardrail_settings(config), date(2026, 9, 21), date(2026, 9, 20))
        self.assertEqual(ctx["spike_history"], [])

    def test_upcoming_sessions_of_a_separate_week_file_are_history(self):
        """Un fichier par semaine : la sortie prévue la semaine d'avant (pas encore courue)
        est la référence de la semaine évaluée — lue dans l'index, pas dans le fichier évalué."""
        for week_start, day, km in (("2026-09-21", "2026-09-23", 20000), ("2026-09-28", "2026-09-30", 8000)):
            self.write(f"planning/{week_start}_semaine.md",
                       {"kind": "week", "week_start": week_start, "location": "Tournai",
                        "sessions": [{"date": day, "sport": "trail", "title": "Sortie",
                                      "intensity": "endurance", "planned_distance_m": km}]})
        self.index()
        config = I.load_config(self.ws)
        ctx = G.build_context(self.conn, config, G.guardrail_settings(config), date(2026, 10, 5), date(2026, 9, 20))
        history = [(h["date"], h["source"]) for h in ctx["spike_history"]]
        self.assertIn(("2026-09-23", "plan"), history)
        self.assertIn(("2026-09-30", "plan"), history)
        week_ = {"week_start": "2026-10-05", "location": "Tournai",
                 "sessions": [{"date": "2026-10-08", "sport": "trail", "title": "Longue",
                               "intensity": "endurance", "planned_distance_m": 30000}]}
        result = G.evaluate(week_, ctx, G.guardrail_settings(config))
        ev = result["context"]["session_spike"][0]
        self.assertEqual(ev["reference_distance_m"], 20000.0)
        self.assertEqual(ev["category"], "moderate")
        self.assertEqual(ev["reference_source"], "plan")

    def test_completed_activity_replaces_a_future_plan_of_the_same_day(self):
        self.write("planning/2026-09-21_semaine.md",
                   {"kind": "week", "week_start": "2026-09-21", "location": "Tournai",
                    "sessions": [{"date": "2026-09-23", "sport": "trail", "title": "Sortie",
                                  "intensity": "endurance", "planned_distance_m": 30000}]})
        self._activity("2026-09-23", 9.0)
        self.index()
        config = I.load_config(self.ws)
        ctx = G.build_context(self.conn, config, G.guardrail_settings(config), date(2026, 9, 28), date(2026, 9, 22))
        self.assertEqual([(h["date"], h["distance_m"], h["source"]) for h in ctx["spike_history"]],
                         [("2026-09-23", 9000.0, "activity")])

    def test_session_spike_text_and_day_without_run(self):
        proc = self._run("session-spike", "--date", "2026-09-20", "--text")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("aucune séance course", proc.stdout)

    def test_session_spike_requires_a_valid_date(self):
        self.assertEqual(self._run("session-spike").returncode, 2)
        self.assertEqual(self._run("session-spike", "--date", "demain").returncode, 2)
        self.assertEqual(self._run("check", "--date", "2026-09-20").returncode, 2)


class TestRuleLabels(unittest.TestCase):
    """#55 : `RULE_LABELS` doit toujours couvrir exactement `RULE_IDS`, jamais
    plus ni moins — le dashboard (`scripts/arc_serve.py::rule_info`) affiche un
    libellé à côté de chaque `rule_id` cité par une décision, une règle
    ajoutée/retirée sans mettre à jour `RULE_LABELS` doit donc échouer ici
    plutôt que d'afficher un id nu ou une clé fantôme côté API."""

    def test_covers_exactly_the_known_rule_ids(self):
        self.assertEqual(set(G.RULE_LABELS), set(G.RULE_IDS))

    def test_every_label_is_a_non_empty_string(self):
        for rule_id, label in G.RULE_LABELS.items():
            self.assertIsInstance(label, str, rule_id)
            self.assertTrue(label.strip(), rule_id)


if __name__ == "__main__":
    unittest.main()
