"""Palier D — drapeau composite de risque de blessure (#57, épopée #22).

Deux niveaux de test, même patron que `tests/data/test_arc_guardrails.py` :
- `TestFactor*`/`TestLevel*`/`TestInjuryRiskSettings` appellent directement les
  évaluateurs de facteur (`_eval_*_factor`) et `evaluate_injury_risk`, en
  unitaire, avec un `context` fabriqué à la main.
- `TestBuildInjuryRiskContext`/`TestCLI` couvrent `build_injury_risk_context`
  sur un vrai workspace synthétique et la sous-commande CLI `injury-risk`.
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

DEFAULT_GCONF = G.injury_risk_settings({})


def base_context(**overrides):
    ctx = {
        "today": "2026-09-24", "morning_check": "full",
        "acwr_history_sufficient": True, "acwr_today": 1.0,
        "monotony_history_sufficient": True, "monotony_today": 1.0,
        "pain_found_any_health_file": True, "pain_max_score": 0.0, "pain_window_days": 3,
        "pain_location": None,
        "recent_rpe_hr_ratios": [1.0, 1.0, 1.0],
        "baseline_rpe_hr_ratios": [1.0, 1.0, 1.0],
        "sleep_debt_7d_s": 0.0,
        "health_by_date": {},
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# Un facteur à la fois : seuils, juste sous / juste au-dessus
# ---------------------------------------------------------------------------


class TestAcwrFactor(unittest.TestCase):
    def test_insufficient_history_is_skipped(self):
        ctx = base_context(acwr_history_sufficient=False)
        factor = G._eval_acwr_factor(ctx, DEFAULT_GCONF)
        self.assertFalse(factor["contributes"])
        self.assertEqual(factor["reason_code"], "insufficient_history")

    def test_low_fitness_none_is_skipped(self):
        ctx = base_context(acwr_today=None)
        factor = G._eval_acwr_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "insufficient_history")

    def test_at_threshold_does_not_contribute(self):
        ctx = base_context(acwr_today=DEFAULT_GCONF["acwr_max"])
        factor = G._eval_acwr_factor(ctx, DEFAULT_GCONF)
        self.assertFalse(factor["contributes"])

    def test_just_above_threshold_contributes(self):
        ctx = base_context(acwr_today=DEFAULT_GCONF["acwr_max"] + 0.01)
        factor = G._eval_acwr_factor(ctx, DEFAULT_GCONF)
        self.assertTrue(factor["contributes"])
        self.assertEqual(factor["weight"], G.INJURY_RISK_WEIGHTS["acwr"])


class TestMonotonyFactor(unittest.TestCase):
    def test_insufficient_history_is_skipped(self):
        ctx = base_context(monotony_history_sufficient=False)
        factor = G._eval_monotony_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "insufficient_history")

    def test_none_value_is_skipped(self):
        ctx = base_context(monotony_today=None)
        factor = G._eval_monotony_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "insufficient_history")

    def test_at_threshold_does_not_contribute(self):
        ctx = base_context(monotony_today=DEFAULT_GCONF["monotony_max"])
        factor = G._eval_monotony_factor(ctx, DEFAULT_GCONF)
        self.assertFalse(factor["contributes"])

    def test_just_above_threshold_contributes(self):
        ctx = base_context(monotony_today=DEFAULT_GCONF["monotony_max"] + 0.01)
        factor = G._eval_monotony_factor(ctx, DEFAULT_GCONF)
        self.assertTrue(factor["contributes"])


class TestPainFactor(unittest.TestCase):
    def test_no_health_file_is_skipped_as_no_health_file(self):
        ctx = base_context(pain_found_any_health_file=False, pain_max_score=0.0)
        factor = G._eval_pain_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "no_health_file")
        self.assertFalse(factor["contributes"])

    def test_location_is_reported_alongside_score(self):
        """Revue de code #104, should-fix 2 : la zone déclarée (`location`)
        accompagne le score maximal, pour que le facteur reste lisible sans
        rouvrir le fichier santé."""
        ctx = base_context(pain_max_score=6.0, pain_location="genou droit")
        factor = G._eval_pain_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["location"], "genou droit")

    def test_location_is_none_without_pain(self):
        ctx = base_context(pain_max_score=0.0, pain_location=None)
        factor = G._eval_pain_factor(ctx, DEFAULT_GCONF)
        self.assertIsNone(factor["location"])

    def test_health_file_without_pain_is_checked_not_skipped(self):
        """Un fichier santé existe mais ne rapporte aucune douleur : c'est une
        vraie observation (0/10), jamais une donnée manquante."""
        ctx = base_context(pain_found_any_health_file=True, pain_max_score=0.0)
        factor = G._eval_pain_factor(ctx, DEFAULT_GCONF)
        self.assertNotIn("reason_code", factor)
        self.assertFalse(factor["contributes"])
        self.assertEqual(factor["observed"], 0.0)

    def test_below_threshold_does_not_contribute(self):
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_score_threshold"] - 1)
        factor = G._eval_pain_factor(ctx, DEFAULT_GCONF)
        self.assertFalse(factor["contributes"])

    def test_at_threshold_contributes(self):
        """Seuil de sévérité en `>=` (contrairement à ACWR/monotonie en `>`) :
        une douleur exactement au seuil déclaré compte, voir
        ASSUMPTIONS_INJURY_RISK['pain']."""
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_score_threshold"])
        factor = G._eval_pain_factor(ctx, DEFAULT_GCONF)
        self.assertTrue(factor["contributes"])
        self.assertEqual(factor["weight"], G.INJURY_RISK_WEIGHTS["pain"])


class TestRpeHrMismatchFactor(unittest.TestCase):
    def test_too_few_recent_sessions_is_skipped(self):
        ctx = base_context(recent_rpe_hr_ratios=[1.0])
        factor = G._eval_rpe_hr_mismatch_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "no_rpe_hr_pairs")

    def test_too_few_baseline_sessions_is_skipped(self):
        ctx = base_context(baseline_rpe_hr_ratios=[1.0, 1.0])
        factor = G._eval_rpe_hr_mismatch_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "no_rpe_hr_pairs")

    def test_zero_baseline_median_is_skipped(self):
        ctx = base_context(baseline_rpe_hr_ratios=[0.0, 0.0, 0.0])
        factor = G._eval_rpe_hr_mismatch_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "no_rpe_hr_pairs")

    def test_ratio_at_threshold_does_not_contribute(self):
        threshold = DEFAULT_GCONF["mismatch_ratio_max"]
        ctx = base_context(baseline_rpe_hr_ratios=[1.0, 1.0, 1.0],
                            recent_rpe_hr_ratios=[threshold, threshold, threshold])
        factor = G._eval_rpe_hr_mismatch_factor(ctx, DEFAULT_GCONF)
        self.assertFalse(factor["contributes"])

    def test_ratio_just_above_threshold_contributes(self):
        threshold = DEFAULT_GCONF["mismatch_ratio_max"]
        ctx = base_context(baseline_rpe_hr_ratios=[1.0, 1.0, 1.0],
                            recent_rpe_hr_ratios=[threshold + 0.05] * 3)
        factor = G._eval_rpe_hr_mismatch_factor(ctx, DEFAULT_GCONF)
        self.assertTrue(factor["contributes"])


class TestSleepDebtFactor(unittest.TestCase):
    def test_minimal_mode_is_skipped(self):
        ctx = base_context(morning_check="minimal")
        factor = G._eval_sleep_debt_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "health_check_disabled")

    def test_off_mode_is_skipped(self):
        ctx = base_context(morning_check="off")
        factor = G._eval_sleep_debt_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "health_check_disabled")

    def test_none_value_is_skipped(self):
        ctx = base_context(sleep_debt_7d_s=None)
        factor = G._eval_sleep_debt_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["reason_code"], "insufficient_history")

    def test_below_threshold_does_not_contribute(self):
        ctx = base_context(sleep_debt_7d_s=DEFAULT_GCONF["sleep_debt_alert_s"] - 1)
        factor = G._eval_sleep_debt_factor(ctx, DEFAULT_GCONF)
        self.assertFalse(factor["contributes"])

    def test_at_threshold_contributes(self):
        ctx = base_context(sleep_debt_7d_s=DEFAULT_GCONF["sleep_debt_alert_s"])
        factor = G._eval_sleep_debt_factor(ctx, DEFAULT_GCONF)
        self.assertTrue(factor["contributes"])

    def test_observed_and_threshold_are_exposed_in_hours(self):
        """Revue de code #104, should-fix 2 : le calcul interne reste en
        secondes, mais la sortie du facteur doit être lisible directement
        (heures), jamais « 37800 vs seuil 36000 »."""
        ctx = base_context(sleep_debt_7d_s=37800.0)
        factor = G._eval_sleep_debt_factor(ctx, DEFAULT_GCONF)
        self.assertEqual(factor["observed"], 10.5)
        self.assertEqual(factor["threshold"], round(DEFAULT_GCONF["sleep_debt_alert_s"] / 3600.0, 1))


class TestRedVerdictFactor(unittest.TestCase):
    def test_observed_and_threshold_are_none(self):
        """Revue de code #104, should-fix 2 : un fait booléen (rouge ou non)
        n'a pas de « valeur observée contre un seuil » — jamais « red vs seuil
        red »."""
        ctx = base_context(health_by_date={"2026-09-24": "red"})
        factor = G._eval_red_verdict_factor(ctx)
        self.assertIsNone(factor["observed"])
        self.assertIsNone(factor["threshold"])

    def test_off_mode_is_skipped(self):
        ctx = base_context(morning_check="off")
        factor = G._eval_red_verdict_factor(ctx)
        self.assertEqual(factor["reason_code"], "health_check_disabled")

    def test_minimal_mode_still_checked(self):
        ctx = base_context(morning_check="minimal", health_by_date={"2026-09-24": "red"})
        factor = G._eval_red_verdict_factor(ctx)
        self.assertNotIn("reason_code", factor)
        self.assertTrue(factor["contributes"])

    def test_red_today_contributes(self):
        ctx = base_context(health_by_date={"2026-09-24": "red"})
        factor = G._eval_red_verdict_factor(ctx)
        self.assertTrue(factor["contributes"])

    def test_red_yesterday_contributes(self):
        ctx = base_context(health_by_date={"2026-09-23": "red"})
        factor = G._eval_red_verdict_factor(ctx)
        self.assertTrue(factor["contributes"])

    def test_green_does_not_contribute(self):
        ctx = base_context(health_by_date={"2026-09-24": "green"})
        factor = G._eval_red_verdict_factor(ctx)
        self.assertFalse(factor["contributes"])

    def test_no_verdict_known_does_not_contribute(self):
        ctx = base_context(health_by_date={})
        factor = G._eval_red_verdict_factor(ctx)
        self.assertFalse(factor["contributes"])


# ---------------------------------------------------------------------------
# evaluate_injury_risk() — combinaisons de facteurs → niveau attendu
# ---------------------------------------------------------------------------


class TestLevel(unittest.TestCase):
    def test_no_factor_contributes_is_low(self):
        ctx = base_context()
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["score"], 0)
        self.assertFalse(result["consult"])
        self.assertIn("disclaimer", result)

    def test_single_weight_one_factor_stays_low(self):
        ctx = base_context(acwr_today=DEFAULT_GCONF["acwr_max"] + 0.1)
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["level"], "low")

    def test_two_weight_one_factors_is_moderate(self):
        ctx = base_context(acwr_today=DEFAULT_GCONF["acwr_max"] + 0.1,
                            monotony_today=DEFAULT_GCONF["monotony_max"] + 0.1)
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["level"], "moderate")

    def test_pain_alone_is_moderate(self):
        """La douleur pèse double (`INJURY_RISK_WEIGHTS['pain']` == 2) : un seul
        facteur suffit à basculer en modéré."""
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_score_threshold"])
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["level"], "moderate")

    def test_pain_plus_acwr_is_high(self):
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_score_threshold"],
                            acwr_today=DEFAULT_GCONF["acwr_max"] + 0.1,
                            monotony_today=DEFAULT_GCONF["monotony_max"] + 0.1)
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["score"], 4)
        self.assertEqual(result["level"], "high")

    def test_skipped_factor_never_contributes(self):
        """Un facteur SAUTÉ (historique insuffisant...) ne doit jamais faire
        basculer le niveau — voir ASSUMPTIONS_INJURY_RISK['level']."""
        ctx = base_context(acwr_history_sufficient=False, monotony_history_sufficient=False,
                            pain_found_any_health_file=False,
                            recent_rpe_hr_ratios=[], baseline_rpe_hr_ratios=[],
                            morning_check="off")
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "low")
        self.assertTrue(all("reason_code" in f for f in result["factors"]))

    def test_factors_are_sorted_by_id(self):
        ctx = base_context()
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        ids = [f["id"] for f in result["factors"]]
        self.assertEqual(ids, sorted(ids))

    def test_disclaimer_is_non_diagnostic(self):
        """Critère d'acceptation #57 : aucune formulation médicale diagnostique."""
        ctx = base_context()
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        disclaimer = result["disclaimer"].lower()
        for word in ("blessure avérée", "tendinite", "fracture", "diagnostic médical"):
            self.assertNotIn(word, disclaimer)
        self.assertIn("signal de vigilance", disclaimer)
        self.assertIn("non-diagnostique", disclaimer)

    def test_disabled_engine_returns_low_and_all_skipped(self):
        conf = G.injury_risk_settings({"injury_risk": {"enabled": False}})
        ctx = base_context()
        result = G.evaluate_injury_risk(ctx, conf)
        self.assertEqual(result["level"], "low")
        self.assertFalse(result["consult"])
        self.assertTrue(all(f["reason_code"] == "injury_risk_disabled" for f in result["factors"]))

    # -- douleur sévère (#57/#104, decision du coordinateur, S1) ------------

    def test_severe_pain_alone_forces_high_and_consult(self):
        """Une douleur >= `pain_consult_threshold` (défaut 7/10) force `level:
        "high"` À ELLE SEULE, même si le score pondéré (2, poids de `pain`
        seul) resterait « modéré » sans cette règle."""
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_consult_threshold"])
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["level"], "high")
        self.assertTrue(result["consult"])

    def test_pain_below_consult_threshold_does_not_force_high(self):
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_consult_threshold"] - 0.1)
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["level"], "moderate")
        self.assertFalse(result["consult"])

    def test_high_from_other_factors_with_contributing_pain_also_consults(self):
        """`consult` vaut aussi `true` quand `level` atteint `"high"` par la
        combinaison d'AUTRES facteurs, tant que `pain` contribue aussi — même
        sous le seuil de douleur sévère (voir ASSUMPTIONS_INJURY_RISK['consult'])."""
        ctx = base_context(pain_max_score=DEFAULT_GCONF["pain_score_threshold"],
                            acwr_today=DEFAULT_GCONF["acwr_max"] + 0.1,
                            monotony_today=DEFAULT_GCONF["monotony_max"] + 0.1)
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["level"], "high")
        self.assertTrue(result["consult"])

    def test_high_without_contributing_pain_does_not_consult(self):
        """`level: "high"` sans que `pain` y contribue (ex. RPE/FC + sommeil +
        verdict rouge) ne doit jamais recommander une consultation — `consult`
        est spécifique à la douleur."""
        ctx = base_context(
            acwr_today=DEFAULT_GCONF["acwr_max"] + 0.1,
            recent_rpe_hr_ratios=[DEFAULT_GCONF["mismatch_ratio_max"] + 1] * 3,
            baseline_rpe_hr_ratios=[1.0, 1.0, 1.0],
            sleep_debt_7d_s=DEFAULT_GCONF["sleep_debt_alert_s"],
            health_by_date={"2026-09-24": "red"},
        )
        result = G.evaluate_injury_risk(ctx, DEFAULT_GCONF)
        self.assertEqual(result["level"], "high")
        self.assertFalse(result["consult"])


# ---------------------------------------------------------------------------
# injury_risk_settings() — défauts, override, valeurs invalides
# ---------------------------------------------------------------------------


class TestInjuryRiskSettings(unittest.TestCase):
    def test_defaults_when_section_absent(self):
        conf = G.injury_risk_settings({})
        self.assertTrue(conf["enabled"])
        self.assertEqual(conf["acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertEqual(conf["monotony_max"], G.DEFAULT_MONOTONY_MAX)
        self.assertEqual(conf["pain_score_threshold"], G.PAIN_SCORE_THRESHOLD)
        self.assertEqual(conf["pain_window_days"], G.PAIN_RECENT_WINDOW_DAYS)
        self.assertEqual(conf["mismatch_ratio_max"], G.RPE_HR_MISMATCH_RATIO_MAX)

    def test_user_override_applies(self):
        conf = G.injury_risk_settings({"injury_risk": {"acwr_max": 1.5, "pain_score_threshold": 6}})
        self.assertEqual(conf["acwr_max"], 1.5)
        self.assertEqual(conf["pain_score_threshold"], 6)

    def test_invalid_threshold_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"acwr_max": "beaucoup"}})
        self.assertEqual(conf["acwr_max"], G.DEFAULT_ACWR_MAX)
        self.assertIn("avertissement", buf.getvalue())

    def test_negative_threshold_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"mismatch_ratio_max": -1}})
        self.assertEqual(conf["mismatch_ratio_max"], G.RPE_HR_MISMATCH_RATIO_MAX)
        self.assertIn("avertissement", buf.getvalue())

    def test_invalid_enabled_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"enabled": "peut-être"}})
        self.assertTrue(conf["enabled"])
        self.assertIn("avertissement", buf.getvalue())

    # -- revue de code #104, should-fix 3 : bornes métier + bon nom de section --

    def test_defaults_include_pain_consult_threshold(self):
        conf = G.injury_risk_settings({})
        self.assertEqual(conf["pain_consult_threshold"], G.PAIN_CONSULT_THRESHOLD)

    def test_warning_names_injury_risk_section_not_guardrails(self):
        """Les fonctions de résolution sont PARTAGÉES avec `guardrail_settings`,
        qui écrivait `[guardrails]` en dur — un avertissement pour une clé de
        `[injury_risk]` doit citer la bonne section."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            G.injury_risk_settings({"injury_risk": {"acwr_max": "beaucoup"}})
        self.assertIn("[injury_risk]", buf.getvalue())
        self.assertNotIn("[guardrails]", buf.getvalue())

    def test_pain_score_threshold_above_ten_falls_back_with_warning(self):
        """Un seuil > 10 désactiverait le facteur en silence (aucun score de
        douleur ne peut jamais l'atteindre)."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"pain_score_threshold": 15}})
        self.assertEqual(conf["pain_score_threshold"], G.PAIN_SCORE_THRESHOLD)
        self.assertIn("avertissement", buf.getvalue())

    def test_pain_score_threshold_zero_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"pain_score_threshold": 0}})
        self.assertEqual(conf["pain_score_threshold"], G.PAIN_SCORE_THRESHOLD)
        self.assertIn("avertissement", buf.getvalue())

    def test_pain_score_threshold_at_ten_is_accepted(self):
        conf = G.injury_risk_settings({"injury_risk": {"pain_score_threshold": 10}})
        self.assertEqual(conf["pain_score_threshold"], 10)

    def test_pain_consult_threshold_above_ten_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"pain_consult_threshold": 11}})
        self.assertEqual(conf["pain_consult_threshold"], G.PAIN_CONSULT_THRESHOLD)
        self.assertIn("avertissement", buf.getvalue())

    def test_pain_window_days_half_falls_back_with_warning(self):
        """Revue de code #104, should-fix 3 : `0.5` acceptée par l'ancien
        `int(_positive_float_setting(...))` tombait à `0`, inversant la
        fenêtre et désactivant le facteur douleur en silence."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"pain_window_days": 0.5}})
        self.assertEqual(conf["pain_window_days"], G.PAIN_RECENT_WINDOW_DAYS)
        self.assertIn("avertissement", buf.getvalue())
        self.assertGreaterEqual(conf["pain_window_days"], 1)

    def test_pain_window_days_zero_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"pain_window_days": 0}})
        self.assertEqual(conf["pain_window_days"], G.PAIN_RECENT_WINDOW_DAYS)
        self.assertIn("avertissement", buf.getvalue())

    def test_pain_window_days_negative_falls_back_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = G.injury_risk_settings({"injury_risk": {"pain_window_days": -2}})
        self.assertEqual(conf["pain_window_days"], G.PAIN_RECENT_WINDOW_DAYS)
        self.assertIn("avertissement", buf.getvalue())

    def test_pain_window_days_valid_integer_override_applies(self):
        conf = G.injury_risk_settings({"injury_risk": {"pain_window_days": 5}})
        self.assertEqual(conf["pain_window_days"], 5)
        self.assertIsInstance(conf["pain_window_days"], int)


# ---------------------------------------------------------------------------
# build_injury_risk_context() sur un vrai workspace synthétique
# ---------------------------------------------------------------------------


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-injury-risk-"))
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

    def index(self, today="2026-09-24"):
        return I.index_workspace(self.conn, self.ws, today)


class TestBuildInjuryRiskContext(WorkspaceCase):
    def test_no_health_file_in_window_has_no_pain_field(self):
        self.index()
        config = I.load_config(self.ws)
        gc = G.injury_risk_settings(config)
        ctx = G.build_injury_risk_context(self.conn, config, gc, date(2026, 9, 24))
        self.assertFalse(ctx["pain_found_any_health_file"])

    def test_pain_is_read_from_health_file_across_window(self):
        self.write("medical/2026-09-22_health.md",
                    {"kind": "health", "date": "2026-09-22", "morning_check": "full",
                     "pain": [{"location": "genou droit", "score": 6}]})
        self.index()
        config = I.load_config(self.ws)
        gc = G.injury_risk_settings(config)
        ctx = G.build_injury_risk_context(self.conn, config, gc, date(2026, 9, 24))
        self.assertTrue(ctx["pain_found_any_health_file"])
        self.assertEqual(ctx["pain_max_score"], 6)

    def test_pain_outside_window_is_not_counted(self):
        self.write("medical/2026-09-10_health.md",
                    {"kind": "health", "date": "2026-09-10", "morning_check": "full",
                     "pain": [{"location": "genou droit", "score": 9}]})
        self.index()
        config = I.load_config(self.ws)
        gc = G.injury_risk_settings(config)
        ctx = G.build_injury_risk_context(self.conn, config, gc, date(2026, 9, 24))
        self.assertFalse(ctx["pain_found_any_health_file"])
        self.assertEqual(ctx["pain_max_score"], 0.0)

    def test_rpe_hr_pairs_read_from_activities(self):
        # Profil requis pour que `session_load` (arc_index) calcule un TRIMP réel
        # (`load_source = 'trimp'`) plutôt qu'un repli sRPE — sans FC max/repos,
        # aucune séance ne serait comptée par `_paired_rpe_hr_ratios`.
        (self.ws / "planning/Runner_Profile.md").write_text(
            "# Profil de l'athlète\n\n## Physiologie\n\n- **FC max** : 188\n"
            "- **FC de repos** : 48\n", encoding="utf-8")
        for i, (hr, rpe) in enumerate([(150, 8), (148, 7), (152, 9)]):
            self.write(f"activities/2026-09-2{i}_running.md",
                        {"kind": "activity", "date": f"2026-09-2{i}", "sport": "running",
                         "duration_s": 3000, "avg_hr_bpm": hr, "distance_m": 8000, "rpe": rpe})
        self.index()
        config = I.load_config(self.ws)
        gc = G.injury_risk_settings(config)
        ctx = G.build_injury_risk_context(self.conn, config, gc, date(2026, 9, 24))
        self.assertEqual(len(ctx["recent_rpe_hr_ratios"]), 3)

    def test_sleep_debt_respects_morning_check_off(self):
        (self.ws / "config").mkdir(exist_ok=True)
        (self.ws / "config/workspace.user.toml").write_text(
            "[health]\nmorning_check = \"off\"\n", encoding="utf-8")
        self.index()
        config = I.load_config(self.ws)
        gc = G.injury_risk_settings(config)
        ctx = G.build_injury_risk_context(self.conn, config, gc, date(2026, 9, 24))
        self.assertEqual(ctx["morning_check"], "off")
        factor = G._eval_sleep_debt_factor(ctx, gc)
        self.assertEqual(factor["reason_code"], "health_check_disabled")


# ---------------------------------------------------------------------------
# CLI `injury-risk`
# ---------------------------------------------------------------------------


class TestCLI(WorkspaceCase):
    def _run(self, *args, input_text=None):
        cmd = [sys.executable, str(REPO / "scripts/arc_guardrails.py"), *args]
        return subprocess.run(cmd, input=input_text, capture_output=True, text=True)

    def test_injury_risk_runs_and_returns_json(self):
        result = self._run("injury-risk", "--workspace", str(self.ws), "--today", "2026-09-24")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("level", payload)
        self.assertIn("factors", payload)
        self.assertIn("disclaimer", payload)

    def test_week_flag_is_rejected_for_injury_risk(self):
        result = self._run("injury-risk", "--week", "-", "--workspace", str(self.ws))
        self.assertEqual(result.returncode, 2)

    def test_pain_reported_pushes_level_up(self):
        self.write("medical/2026-09-24_health.md",
                    {"kind": "health", "date": "2026-09-24", "morning_check": "full",
                     "pain": [{"location": "genou", "score": 8}],
                     "verdict": "amber", "verdict_reason": "Douleur au genou."})
        result = self._run("injury-risk", "--workspace", str(self.ws), "--today", "2026-09-24")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(payload["level"], ("moderate", "high"))
        pain_factor = next(f for f in payload["factors"] if f["id"] == "pain")
        self.assertTrue(pain_factor["contributes"])


if __name__ == "__main__":
    unittest.main()
