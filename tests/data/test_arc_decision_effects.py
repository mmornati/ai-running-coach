"""Palier D — effet des décisions (#175) : fonctions pures, CLI `decision-effects`, `/api/decision-effects`.

Historiques synthétiques écrits à la main (fichiers ```arc), dates fixes relatives à TODAY — aucune
donnée réelle. Les décisions sont évaluées au jour TODAY, jamais à la date du run.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_decision_effects as DE  # noqa: E402
import arc_index as I  # noqa: E402
import arc_serve as S  # noqa: E402

TODAY = date(2026, 9, 30)


def iso(offset_from_today: int) -> str:
    return (TODAY + timedelta(days=offset_from_today)).isoformat()


def dec(day: str, trigger="morning_check", outcome="applied") -> dict:
    return {"id": f"{day}_decision_x", "source_path": f"planning/{day}_decision_x.md", "date": day,
            "trigger": trigger, "outcome": outcome}


def health_series(day: str, pre: dict, post: dict) -> dict:
    """Santé J-2..J = `pre`, J+1..J+7 = `post` (dict de clés hrv_ms/rhr_bpm/readiness/pain_max)."""
    d0 = date.fromisoformat(day)
    out = {}
    for off in range(-2, 8):
        out[(d0 + timedelta(days=off)).isoformat()] = dict(pre if off <= 0 else post)
    return out


class TestEvaluateDecision(unittest.TestCase):
    DAY = iso(-20)

    def test_morning_check_improved_on_hrv_rise(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 45, "rhr_bpm": 50, "readiness": 60},
                                        {"hrv_ms": 55, "rhr_bpm": 50, "readiness": 60})}
        ev = DE.evaluate_decision(dec(self.DAY), data, TODAY)
        self.assertEqual(ev["effect"], "improved")
        hrv = next(s for s in ev["signals"] if s["signal"] == "hrv")
        self.assertEqual((hrv["pre_value"], hrv["post_value"], hrv["verdict"]), (45.0, 55.0, "improved"))
        self.assertEqual(hrv["post"]["to"], iso(-17))   # N = 3 pour le bilan matinal
        self.assertEqual(ev["horizon_days"], 3)

    def test_morning_check_worsened_on_rhr_rise_and_hrv_drop(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 60, "rhr_bpm": 48}, {"hrv_ms": 50, "rhr_bpm": 55})}
        ev = DE.evaluate_decision(dec(self.DAY), data, TODAY)
        self.assertEqual(ev["effect"], "worsened")
        self.assertEqual(len(ev["signals"]), 2)      # readiness absente : sautée, jamais imputée
        self.assertEqual([s["signal"] for s in ev["skipped"]], ["readiness"])

    def test_within_tolerance_is_neutral(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 60, "rhr_bpm": 50}, {"hrv_ms": 61, "rhr_bpm": 51})}
        self.assertEqual(DE.evaluate_decision(dec(self.DAY), data, TODAY)["effect"], "neutral")

    def test_mixed_signals_are_neutral(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 50, "rhr_bpm": 50}, {"hrv_ms": 60, "rhr_bpm": 56})}
        self.assertEqual(DE.evaluate_decision(dec(self.DAY), data, TODAY)["effect"], "neutral")

    def test_medical_pain_decrease_is_improved(self):
        data = {"health": health_series(self.DAY, {"pain_max": 6.0}, {"pain_max": 2.0})}
        ev = DE.evaluate_decision(dec(self.DAY, "medical"), data, TODAY)
        self.assertEqual(ev["effect"], "improved")
        self.assertEqual(ev["horizon_days"], 7)

    def test_medical_pain_increase_is_worsened(self):
        data = {"health": health_series(self.DAY, {"pain_max": 3.0}, {"pain_max": 6.0})}
        self.assertEqual(DE.evaluate_decision(dec(self.DAY, "medical"), data, TODAY)["effect"], "worsened")

    def test_guardrail_acwr_back_into_band_is_improved(self):
        acwr = {iso(-20 - 2): 1.6, iso(-21): 1.6, iso(-20): 1.6}
        for off in range(1, 8):
            acwr[iso(-20 + off)] = 1.2
        ev = DE.evaluate_decision(dec(self.DAY, "guardrail"), {"acwr": acwr}, TODAY)
        self.assertEqual(ev["effect"], "improved")
        gap = ev["signals"][0]
        self.assertEqual(gap["signal"], "acwr_gap")
        self.assertAlmostEqual(gap["pre_value"], 0.3, places=3)
        self.assertEqual(gap["post_value"], 0.0)

    def test_session_signals_rpe_decoupling_and_compliance(self):
        sessions = [{"date": iso(-30), "rpe": 8, "decoupling_pct": 7.0},
                    {"date": iso(-25), "rpe": 8, "decoupling_pct": 6.0},
                    {"date": iso(-18), "rpe": 5, "decoupling_pct": 2.0}]
        planned = ([{"date": iso(-24 + i), "status": "missed"} for i in range(3)]
                   + [{"date": iso(-19 + i), "status": "done"} for i in range(3)])
        ev = DE.evaluate_decision(dec(self.DAY, "athlete_request"),
                                  {"sessions": sessions, "planned": planned}, TODAY)
        self.assertEqual(ev["effect"], "improved")
        self.assertEqual({s["signal"] for s in ev["signals"]}, {"rpe", "decoupling", "compliance"})

    def test_rejected_by_athlete_is_evaluated_too(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 60, "rhr_bpm": 48}, {"hrv_ms": 48, "rhr_bpm": 56})}
        ev = DE.evaluate_decision(dec(self.DAY, outcome="rejected_by_athlete"), data, TODAY)
        self.assertEqual(ev["effect"], "worsened")
        self.assertEqual(ev["outcome"], "rejected_by_athlete")

    def test_insufficient_data_without_measures(self):
        ev = DE.evaluate_decision(dec(self.DAY), {"health": {}}, TODAY)
        self.assertEqual((ev["effect"], ev["reason_code"]), ("insufficient_data", "no_signal"))
        self.assertEqual(len(ev["skipped"]), 3)

    def test_post_window_with_one_point_is_skipped(self):
        data = {"health": {iso(-20): {"hrv_ms": 50}, iso(-19): {"hrv_ms": 70}}}   # 1 seul point après (min 2)
        ev = DE.evaluate_decision(dec(self.DAY), data, TODAY)
        self.assertEqual(ev["effect"], "insufficient_data")

    def test_window_not_elapsed_is_insufficient_not_guessed(self):
        recent = iso(-1)
        data = {"health": health_series(recent, {"hrv_ms": 45}, {"hrv_ms": 70})}
        ev = DE.evaluate_decision(dec(recent), data, TODAY)
        self.assertEqual((ev["effect"], ev["reason_code"]), ("insufficient_data", "window_open"))
        self.assertEqual(ev["mature_on"], iso(2))

    def test_proposed_and_superseded_are_not_evaluated(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 45}, {"hrv_ms": 70})}
        for outcome in ("proposed", "superseded"):
            ev = DE.evaluate_decision(dec(self.DAY, outcome=outcome), data, TODAY)
            self.assertEqual((ev["effect"], ev["reason_code"]), ("insufficient_data", outcome))

    def test_bad_date(self):
        self.assertEqual(DE.evaluate_decision(dec("pas-une-date"), {}, TODAY)["reason_code"], "bad_date")

    def test_no_imputation_of_missing_pain(self):
        """Une clé `pain_max` absente (fichier santé sans `pain`) n'est JAMAIS lue comme 0."""
        data = {"health": health_series(self.DAY, {"hrv_ms": 50}, {"hrv_ms": 50})}
        ev = DE.evaluate_decision(dec(self.DAY, "medical"), data, TODAY)
        self.assertIn("pain", [s["signal"] for s in ev["skipped"]])


class TestReviewFindings(unittest.TestCase):
    """Revue #175 : nature de l'action, chevauchements, douleur sans biais de fenêtre, volumétrie."""
    DAY = iso(-20)

    def test_action_kind_from_before_after(self):
        cases = [
            ({}, "unspecified"),
            ({"after": {"status": "cancelled"}}, "cancel"),
            ({"before": {"date": iso(-3)}, "after": {"date": iso(-1)}}, "move"),
            ({"before": {"intensity": "vo2max"}, "after": {"intensity": "recovery"}}, "lighten"),
            ({"before": {"planned_duration_s": 5400}, "after": {"planned_duration_s": 3600}}, "lighten"),
            ({"before": {"intensity": "endurance"}, "after": {"intensity": "threshold"}}, "intensify"),
            ({"before": {"intensity": "vo2max", "planned_duration_s": 3000},
              "after": {"intensity": "endurance", "planned_duration_s": 6000}}, "other"),
            ({"before": {"sport": "trail"}, "after": {"sport": "indoor_cycling"}}, "replace"),
            ({"before": {"intensity": "strength"}, "after": {"intensity": "recovery"}}, "replace"),
        ]
        for extra, expected in cases:
            self.assertEqual(DE.action_kind(extra), expected, extra)
        self.assertEqual(set(DE.ACTION_LABEL), set(DE.ACTION_KINDS))

    def test_synthesis_groups_by_action_with_french_labels(self):
        evals = ([{"trigger": "morning_check", "action": "lighten", "outcome": "applied", "effect": "improved"}] * 7
                 + [{"trigger": "morning_check", "action": "cancel", "outcome": "applied", "effect": "neutral"}])
        groups = DE.synthesize(evals)
        self.assertEqual(len(groups), 2)
        self.assertTrue(groups[0]["statement"].startswith("Allègement après bilan matinal"))
        self.assertEqual((groups[0]["n"], groups[0]["improved"]), (7, 7))

    def test_overlapping_decisions_are_flagged(self):
        data = {"health": health_series(self.DAY, {"hrv_ms": 45, "rhr_bpm": 50}, {"hrv_ms": 56, "rhr_bpm": 50})}
        a = dec(self.DAY)
        b = {**dec(iso(-19), "weather"), "id": "b"}
        far = {**dec(iso(-60)), "id": "far"}
        evs = DE.evaluate_all([a], data, TODAY, context=[a, b, far])
        self.assertEqual(evs[0]["overlaps"], ["b"])
        g = DE.synthesize(evs)[0]
        self.assertEqual(g["overlapping"], 1)
        self.assertIn("effets confondus", g["statement"])

    def test_supersedes_chain_is_not_an_overlap(self):
        old = {**dec(iso(-21), outcome="superseded"), "id": "old"}
        new = {**dec(self.DAY), "supersedes": old["source_path"]}
        evs = DE.evaluate_all([new], {"health": {}}, TODAY, context=[old, new])
        self.assertEqual(evs[0]["overlaps"], [])

    def test_proposed_neighbour_does_not_count_as_overlap(self):
        a = dec(self.DAY)
        b = {**dec(self.DAY, outcome="proposed"), "id": "b"}
        evs = DE.evaluate_all([a], {"health": {}}, TODAY, context=[a, b])
        self.assertEqual(evs[0].get("overlaps"), [])

    def test_pain_uses_mean_not_max_over_unequal_windows(self):
        """Un pic isolé dans une fenêtre APRÈS plus longue ne fait plus pencher vers « aggravée »."""
        d0 = date.fromisoformat(self.DAY)
        health = {(d0 + timedelta(days=o)).isoformat(): {"pain_max": 4.0} for o in range(-2, 1)}
        for o, v in zip(range(1, 8), (3, 3, 5, 3, 3, 3, 3)):
            health[(d0 + timedelta(days=o)).isoformat()] = {"pain_max": float(v)}
        ev = DE.evaluate_decision(dec(self.DAY, "medical"), {"health": health}, TODAY)
        pain = next(s for s in ev["signals"] if s["signal"] == "pain")
        self.assertLess(pain["post_value"], 4.0)
        self.assertNotEqual(pain["verdict"], "worsened")

    def test_five_hundred_decisions_stay_fast(self):
        import time
        decisions, health, sessions = [], {}, []
        for i in range(500):
            day = (TODAY - timedelta(days=5 + i)).isoformat()
            decisions.append({**dec(day, ("morning_check", "medical", "athlete_request")[i % 3]),
                              "id": f"d{i}"})
            health[day] = {"hrv_ms": 50 + i % 7, "rhr_bpm": 48 + i % 3, "readiness": 60, "pain_max": i % 4}
            sessions.append({"date": day, "rpe": 5 + i % 3, "decoupling_pct": 3.0})
        t0 = time.perf_counter()
        evs = DE.evaluate_all(decisions, {"health": health, "sessions": sessions, "planned": []}, TODAY)
        DE.synthesize(evs)
        self.assertEqual(len(evs), 500)
        self.assertLess(time.perf_counter() - t0, 5.0)


class TestSynthesis(unittest.TestCase):
    def _evals(self, trigger, outcome, effects):
        return [{"trigger": trigger, "outcome": outcome, "effect": e} for e in effects]

    def test_small_sample_has_counts_and_no_trend(self):
        g = DE.synthesize(self._evals("morning_check", "applied", ["improved", "improved"]))[0]
        self.assertEqual((g["n"], g["trend_allowed"], g["trend"]), (2, False, None))
        self.assertIn("aucune tendance", g["warning"])
        self.assertNotIn("tendance", g["statement"])
        self.assertIn("2 améliorée(s)", g["statement"])

    def test_trend_allowed_from_five(self):
        g = DE.synthesize(self._evals("morning_check", "applied",
                                      ["improved"] * 5 + ["neutral", "worsened", "insufficient_data"]))[0]
        self.assertEqual((g["n"], g["total"], g["trend_allowed"]), (7, 8, True))
        self.assertEqual(g["trend"], "plutôt favorable")
        self.assertIsNone(g["warning"])
        self.assertIn("7 évaluée(s)", g["statement"])
        self.assertIn("5 améliorée(s)", g["statement"])

    def test_groups_split_by_trigger_and_outcome_and_skip_unevaluable_outcomes(self):
        evals = (self._evals("morning_check", "applied", ["improved"])
                 + self._evals("morning_check", "rejected_by_athlete", ["worsened"])
                 + self._evals("guardrail", "proposed", ["insufficient_data"]))
        groups = DE.synthesize(evals)
        self.assertEqual({(g["trigger"], g["outcome"]) for g in groups},
                         {("morning_check", "applied"), ("morning_check", "rejected_by_athlete")})

    def test_all_insufficient_group_is_honest(self):
        g = DE.synthesize(self._evals("medical", "applied", ["insufficient_data"] * 3))[0]
        self.assertEqual(g["n"], 0)
        self.assertIn("aucune décision évaluable", g["warning"])


def arc(block: str) -> str:
    return f"# Titre\n\n```arc\n{block}\n```\n\nTexte.\n"


class IndexedWorkspace(unittest.TestCase):
    """Historique complet dans un vrai workspace : l'index lit santé, séances, décisions."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-effects-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "planning", "rapports", "nutrition"):
            (self.ws / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        (self.ws / rel).write_text(text, encoding="utf-8")

    def decision(self, day, trigger="morning_check", outcome="applied", slug="x"):
        self.write(f"planning/{day}_decision_{slug}.md", arc(json.dumps({
            "arc": 1, "kind": "decision", "date": day, "created_at": f"{day}T06:45:00+02:00",
            "trigger": trigger, "summary": f"Décision {trigger}", "outcome": outcome})))

    def health(self, day, hrv=None, rhr=None, pain=None):
        block = {"arc": 1, "kind": "health", "date": day, "morning_check": "full"}
        if hrv is not None:
            block["hrv_overnight_ms"] = hrv
        if rhr is not None:
            block["resting_hr_bpm"] = rhr
        if pain is not None:
            block["pain"] = [{"location": "genou", "score": pain}] if pain else []
        self.write(f"medical/{day}_health.md", arc(json.dumps(block)))

    def build(self):
        store = S.Store(self.ws, memory=True, today=TODAY.isoformat())
        self.addCleanup(store.conn.close)
        return store

    def report(self, **kw):
        store = self.build()
        return I.decision_effects(store.conn, TODAY, **kw)


class TestEndToEnd(IndexedWorkspace):
    def seed_improved(self, count):
        for i in range(count):
            off = -10 - 12 * i
            self.decision(iso(off), slug=f"d{i}")
            for o in range(-2, 4):
                self.health(iso(off + o), hrv=45 if o <= 0 else 56, rhr=50)

    def test_five_improved_allows_a_trend(self):
        self.seed_improved(5)
        rep = self.report()
        self.assertEqual(len(rep["effects"]), 5)
        self.assertTrue(all(e["effect"] == "improved" for e in rep["effects"]))
        g = rep["synthesis"][0]
        self.assertEqual((g["trigger"], g["n"], g["improved"], g["trend_allowed"]), ("morning_check", 5, 5, True))
        self.assertIn("corrélation", rep["caveat"].lower())

    def test_two_cases_never_a_trend(self):
        self.seed_improved(2)
        g = self.report()["synthesis"][0]
        self.assertFalse(g["trend_allowed"])
        self.assertIsNone(g["trend"])

    def test_empty_workspace_is_honest(self):
        rep = self.report()
        self.assertEqual((rep["effects"], rep["synthesis"]), ([], []))

    def test_rejected_decision_evaluated_and_pain_read_from_health(self):
        day = iso(-15)
        self.decision(day, "medical", "rejected_by_athlete", "genou")
        for o in range(-2, 8):
            self.health(iso(-15 + o), pain=5 if o <= 0 else 8)
        ev = self.report()["effects"][0]
        self.assertEqual((ev["outcome"], ev["effect"]), ("rejected_by_athlete", "worsened"))
        self.assertEqual(ev["signals"][0]["signal"], "pain")

    def test_empty_pain_list_means_zero_not_missing(self):
        day = iso(-15)
        self.decision(day, "medical", slug="genou")
        for o in range(-2, 8):
            self.health(iso(-15 + o), pain=4 if o <= 0 else 0)
        ev = self.report()["effects"][0]
        self.assertEqual(ev["effect"], "improved")
        self.assertEqual(ev["signals"][0]["post_value"], 0.0)

    def test_trigger_filter(self):
        self.decision(iso(-30), "morning_check", slug="a")
        self.decision(iso(-30), "weather", slug="b")
        rep = self.report(trigger="weather")
        self.assertEqual([e["trigger"] for e in rep["effects"]], ["weather"])

    def test_cli_json_and_text(self):
        self.seed_improved(1)
        argv = ["decision-effects", "--workspace", str(self.ws), "--memory", "--today", TODAY.isoformat()]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(I.main([*argv, "--json"]), 0)
        self.assertEqual(len(json.loads(buf.getvalue())["effects"]), 1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(I.main(argv), 0)
        self.assertEqual(len(json.loads(buf.getvalue())["effects"]), 1)   # JSON par défaut (convention)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(I.main([*argv, "--text"]), 0)
        self.assertTrue(buf.getvalue().startswith("Effet des décisions"))
        self.assertIn("Corrélation, pas causalité", buf.getvalue())

    def test_api_route(self):
        self.seed_improved(1)
        store = self.build()
        body = S.api_decision_effects(store, {"days": ["365"], "trigger": ["morning_check"]})
        self.assertEqual(body["days"], 365)
        self.assertEqual(body["effects"][0]["id"], Path(body["effects"][0]["source_path"]).stem)
        self.assertIn("/api/decision-effects", S.ROUTES)
        self.assertEqual(S.api_decision_effects(store, {"trigger": ["bogus"]})["trigger"], None)

    def test_does_not_modify_decision_files(self):
        self.seed_improved(1)
        before = {p.name: p.read_text(encoding="utf-8") for p in (self.ws / "planning").iterdir()}
        self.report()
        after = {p.name: p.read_text(encoding="utf-8") for p in (self.ws / "planning").iterdir()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
