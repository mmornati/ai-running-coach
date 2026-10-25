"""Palier D — foulée (#151) : extraction de la dynamique de course depuis le FIT (mapping, unités,
balance absente), cadence (piège documenté), synthèse `gait-summary` (maths, confiance,
contradictions), contrat, schéma d'index et re-extraction `--refresh-dynamics`.

Aucune dépendance à `fitparse` (CI stdlib) : le FIT est simulé par des dicts façon `fitparse` et, pour
`refresh_dynamics`, par un FAUX `_read_fit`. Les workspaces de test sont des répertoires temporaires
(`--workspace` / `ARC_WORKSPACE` explicites) — jamais le workspace réel.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/fit-download/scripts"))
import arc_contract as C  # noqa: E402
import arc_gait as GT  # noqa: E402
import arc_index as I  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_samples as S  # noqa: E402
import download_fit as D  # noqa: E402

TODAY = date(2026, 9, 23)


def raw(ts_s: int, **fields) -> dict:
    """Un `record` façon `fitparse` (échelles du profil FIT déjà appliquées : ms, mm, %)."""
    return {"timestamp": f"2026-09-01 08:00:{ts_s:02d}", "distance": ts_s * 3.0, "heart_rate": 140,
            "enhanced_speed": 3.0, "cadence": 88, **fields}


class TestFitMapping(unittest.TestCase):
    def test_units_and_keys(self):
        rec = S.normalise_records([raw(0, stance_time=266.5, stance_time_balance=50.65,
                                        vertical_oscillation=106.7, vertical_ratio=9.72,
                                        step_length=1075.5)], sport="running")[0]
        self.assertAlmostEqual(rec["ground_contact_s"], 0.2665, places=4)      # ms -> s
        self.assertAlmostEqual(rec["stance_balance_pct"], 50.65, places=2)     # % inchangé
        self.assertAlmostEqual(rec["vertical_oscillation_m"], 0.1067, places=4)  # mm -> m
        self.assertAlmostEqual(rec["vertical_ratio_pct"], 9.72, places=2)
        self.assertAlmostEqual(rec["step_length_m"], 1.0755, places=4)         # mm -> m

    def test_missing_balance_is_none_never_fifty(self):
        rec = S.normalise_records([raw(0, stance_time=250.0, vertical_oscillation=95.0)], sport="running")[0]
        self.assertIsNone(rec["stance_balance_pct"])
        self.assertIsNotNone(rec["ground_contact_s"])

    def test_no_dynamics_at_all_gives_none_everywhere(self):
        rec = S.normalise_records([raw(0)], sport="cycling")[0]
        for key in S.DYNAMICS_KEYS:
            self.assertIn(key, rec)
            self.assertIsNone(rec[key])

    def test_zero_and_absurd_values_are_missing_not_zero(self):
        rec = S.normalise_records([raw(0, stance_time=0, stance_time_balance=0, vertical_oscillation=0,
                                        vertical_ratio=400, step_length=90000)], sport="running")[0]
        for key in S.DYNAMICS_KEYS:
            self.assertIsNone(rec[key], key)

    def test_downsample_averages_present_values_only(self):
        records = S.normalise_records([raw(0, stance_time_balance=50.0), raw(1), raw(2, stance_time_balance=52.0),
                                        raw(7, stance_time_balance=49.0)], sport="running")
        out = S.downsample(records, 5)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0]["stance_balance_pct"], 51.0)      # moyenne de 50 et 52, la valeur absente ignorée
        self.assertAlmostEqual(out[1]["stance_balance_pct"], 49.0)

    def test_bucket_without_any_balance_stays_none(self):
        out = S.downsample(S.normalise_records([raw(0), raw(1)], sport="running"), 5)
        self.assertIsNone(out[0]["stance_balance_pct"])

    def test_already_normalised_format_passes_dynamics_through(self):
        rec = S.normalise_records([{"t_s": 0, "ground_contact_s": 0.24, "stance_balance_pct": 50.2}])[0]
        self.assertEqual(rec["ground_contact_s"], 0.24)
        self.assertIsNone(rec["step_length_m"])


class TestCadenceTrap(unittest.TestCase):
    """Le champ FIT `cadence` d'une course est PAR PIED : doublé à l'extraction (spm = deux pieds) ; la synthèse
    n'invente jamais une correction sur une valeur du bloc `arc`."""

    def test_running_cadence_is_doubled_cycling_is_not(self):
        self.assertEqual(S.normalise_records([raw(0)], sport="running")[0]["cadence_spm"], 176.0)
        self.assertEqual(S.normalise_records([raw(0)], sport="cycling")[0]["cadence_spm"], 88.0)

    def test_arc_fallback_below_120_is_discarded_and_counted(self):
        values, notes = GT.resolve_session({}, {"avg_cadence_spm": 85})
        self.assertNotIn("cadence_spm", values)
        self.assertTrue(notes["cadence_suspect"])

    def test_arc_fallback_plausible_steps_per_minute_is_kept(self):
        values, notes = GT.resolve_session({}, {"avg_cadence_spm": 170})
        self.assertEqual(values["cadence_spm"], {"value": 170.0, "source": "arc"})
        self.assertEqual(notes, {})

    def test_samples_win_over_the_arc_block(self):
        values, _ = GT.resolve_session({"ground_contact_s": 0.25}, {"avg_ground_contact_s": 0.30})
        self.assertEqual(values["ground_contact_s"], {"value": 0.25, "source": "samples"})

    def test_absent_balance_is_absent_not_fifty(self):
        values, _ = GT.resolve_session({"ground_contact_s": 0.25, "stance_balance_pct": None}, {})
        self.assertNotIn("stance_balance_pct", values)


class TestMetricTrend(unittest.TestCase):
    def pts(self, values, start_day=1):
        return [(f"2026-09-{start_day + i:02d}", v) for i, v in enumerate(values)]

    def test_none_without_points(self):
        self.assertIsNone(GT.metric_trend("ground_contact_s", [], TODAY))

    def test_mean_sd_min_max(self):
        t = GT.metric_trend("ground_contact_s", self.pts([0.24, 0.25, 0.26]), TODAY)
        self.assertEqual((t["n"], t["mean"], t["min"], t["max"]), (3, 0.25, 0.24, 0.26))
        self.assertAlmostEqual(t["sd"], 0.01, places=4)
        self.assertEqual(t["latest"], {"date": "2026-09-03", "value": 0.26})

    def test_change_needs_two_sessions_each_side(self):
        old = [("2026-07-01", 0.26), ("2026-07-10", 0.26)]
        recent = [("2026-09-20", 0.24), ("2026-09-22", 0.24)]
        t = GT.metric_trend("ground_contact_s", old + recent, TODAY)
        self.assertAlmostEqual(t["change"], -0.02, places=4)
        self.assertEqual((t["recent_n"], t["prior_n"]), (2, 2))
        self.assertIsNone(GT.metric_trend("ground_contact_s", old + recent[:1], TODAY)["change"])

    def test_balance_band_share_and_no_side(self):
        t = GT.metric_trend("stance_balance_pct", self.pts([50.0, 50.5, 51.5, 48.0]), TODAY)
        self.assertEqual(t["beyond_band_n"], 2)          # 51,5 et 48,0 : écart > 1 point
        self.assertEqual(t["beyond_band_share"], 0.5)
        self.assertEqual(t["mean_gap_pts"], 1.0)          # (0 + 0,5 + 1,5 + 2) / 4
        self.assertEqual(t["band_label"], "approximation du projet")
        self.assertFalse(t["side_named"])

    def test_band_is_inclusive_of_one_point(self):
        t = GT.metric_trend("stance_balance_pct", self.pts([51.0, 49.0]), TODAY)
        self.assertEqual(t["beyond_band_n"], 0)


def insp(gear, day, hints=(), level=None, side=None, path=None):
    d = {"gear_id": gear, "date": day, "condition": "yellow", "gait_hints": list(hints),
         "path": path or f"gear/{day}_{gear}_inspection.md"}
    if level:
        d["asymmetry"] = {"level": level, **({"side": side} if side else {})}
    return d


class TestTrendDirection(unittest.TestCase):
    """Le SENS d'une variation est décidé côté serveur (palier D), jamais par un regex sur un nombre arrondi
    dans le JS — régression : -0,26 pt ne doit JAMAIS perdre son signe."""

    def test_small_but_displayable_changes_keep_their_sign(self):
        self.assertEqual(GT.change_direction("stance_balance_pct", -0.26), "down")
        self.assertEqual(GT.change_direction("stance_balance_pct", 0.26), "up")
        self.assertEqual(GT.change_direction("ground_contact_s", -0.006), "down")      # -6 ms
        self.assertEqual(GT.change_direction("vertical_oscillation_m", 0.0007), "up")   # +0,1 cm (0,07 cm arrondi)

    def test_flat_only_when_it_displays_as_zero(self):
        self.assertEqual(GT.change_direction("stance_balance_pct", 0.004), "flat")     # < 0,005 pt : « 0,00 »
        self.assertEqual(GT.change_direction("ground_contact_s", -0.0004), "flat")     # -0,4 ms : « 0 ms »
        self.assertEqual(GT.change_direction("cadence_spm", -0.3), "flat")
        self.assertEqual(GT.change_direction("cadence_spm", -0.6), "down")
        self.assertIsNone(GT.change_direction("cadence_spm", None))

    def test_trend_exposes_direction_and_never_negative_zero(self):
        old = [("2026-07-01", 50.0), ("2026-07-10", 50.0)]
        recent = [("2026-09-20", 49.74), ("2026-09-22", 49.74)]
        t = GT.metric_trend("stance_balance_pct", old + recent, TODAY)
        self.assertEqual((t["change"], t["direction"]), (-0.26, "down"))
        flat = GT.metric_trend("stance_balance_pct", [(d, 50.0) for d, _ in old + recent], TODAY)
        self.assertEqual(flat["direction"], "flat")
        self.assertNotIn("-0.0", json.dumps(flat))
        self.assertIsNone(GT.metric_trend("stance_balance_pct", recent[:1], TODAY)["direction"])

    def test_js_does_not_decide_the_sign_from_a_rounded_string(self):
        js = (REPO / "web/js/app.js").read_text(encoding="utf-8")
        self.assertNotIn("const signed", js)
        self.assertIn("gaitTrend(d.direction", js)


class TestInspectionGait(unittest.TestCase):
    def test_pronation_is_not_a_strike_hint(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", ["heel_strike"]),
                                   insp("a", "2026-09-01", ["heel_strike", "pronation_hint"])])
        self.assertEqual(out["pairs"][0]["strike_sets"], [["heel_strike"], ["heel_strike"]])
        codes = {c["code"] for c in GT.find_contradictions({}, out)}
        self.assertEqual(codes, set())

    def test_change_of_strike_between_inspections(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", ["heel_strike"]),
                                   insp("a", "2026-09-01", ["midfoot_forefoot_strike", "supination_hint"])])
        codes = {c["code"]: c for c in GT.find_contradictions({}, out)}
        self.assertIn("strike_hint_changes_within_pair", codes)
        self.assertNotIn("strike_hints_conflict_in_inspection", codes)

    def test_two_strike_hints_in_one_inspection_is_worded_differently(self):
        out = GT.inspection_gait([insp("a", "2026-09-01", ["heel_strike", "midfoot_forefoot_strike"])])
        codes = {c["code"]: c for c in GT.find_contradictions({}, out)}
        self.assertEqual(set(codes), {"strike_hints_conflict_in_inspection"})
        self.assertIn("même inspection", codes["strike_hints_conflict_in_inspection"]["message"])

    def test_same_strike_hints_repeated_is_stable(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", ["heel_strike"]), insp("a", "2026-09-01", ["heel_strike"])])
        self.assertEqual(GT.find_contradictions({}, out), [])

    def test_strike_tally_and_dominant(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", ["heel_strike"]), insp("a", "2026-09-01", ["heel_strike"]),
                                   insp("a", "2026-09-10", ["midfoot_forefoot_strike"])], {"a": "Paire A"})
        p = out["pairs"][0]
        self.assertEqual(p["strike_hints"], {"heel_strike": 2, "midfoot_forefoot_strike": 1})
        self.assertEqual(p["dominant_strike"], "heel_strike")
        self.assertEqual(p["latest_strike"], ["midfoot_forefoot_strike"])
        self.assertEqual(out["strike_hint_tally"], {"heel_strike": 2, "midfoot_forefoot_strike": 1})
        self.assertEqual(p["name"], "Paire A")

    def test_tie_has_no_dominant(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", ["heel_strike"]),
                                   insp("a", "2026-09-01", ["midfoot_forefoot_strike"])])
        self.assertIsNone(out["pairs"][0]["dominant_strike"])

    def test_asymmetry_repeating_on_the_same_side(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", level="mild", side="left"),
                                   insp("a", "2026-09-01", level="marked", side="left"),
                                   insp("a", "2026-09-15", level="none")])
        p = out["pairs"][0]
        self.assertEqual(p["asymmetry_repeats"], {"side": "left", "count": 2, "of": 2})
        self.assertFalse(p["asymmetry_side_changes"])
        self.assertEqual(len(p["asymmetry"]), 3)

    def test_side_flip_is_flagged_and_not_a_repeat(self):
        out = GT.inspection_gait([insp("a", "2026-08-01", level="mild", side="left"),
                                   insp("a", "2026-09-01", level="mild", side="right")])
        p = out["pairs"][0]
        self.assertIsNone(p["asymmetry_repeats"])
        self.assertTrue(p["asymmetry_side_changes"])


def dyn_with_balance(gap_mean, n=10):
    t = GT.metric_trend("stance_balance_pct", [(f"2026-09-{i + 1:02d}", 50.0 + gap_mean) for i in range(n)], TODAY)
    return {"stance_balance_pct": t}


class TestContradictions(unittest.TestCase):
    def codes(self, dynamics, inspections, names=None):
        return {c["code"]: c for c in GT.find_contradictions(dynamics, GT.inspection_gait(inspections, names))}

    def test_strike_hints_differ_across_pairs(self):
        out = self.codes({}, [insp("road", "2026-09-01", ["heel_strike"]),
                              insp("trail", "2026-09-02", ["midfoot_forefoot_strike"])],
                         {"road": "Route", "trail": "Trail"})
        c = out["strike_hint_differs_across_pairs"]
        self.assertEqual(c["evidence"], {"heel_strike": ["Route"], "midfoot_forefoot_strike": ["Trail"]})
        self.assertNotIn("diagnostic médical", c["message"])

    def test_same_hint_everywhere_is_no_contradiction(self):
        out = self.codes({}, [insp("a", "2026-09-01", ["heel_strike"]), insp("b", "2026-09-02", ["heel_strike"])])
        self.assertNotIn("strike_hint_differs_across_pairs", out)

    def test_wear_asymmetry_vs_symmetric_measured_balance_measure_wins(self):
        out = self.codes(dyn_with_balance(0.3), [insp("a", "2026-09-01", level="mild", side="left")])
        c = out["wear_asymmetry_vs_symmetric_balance"]
        self.assertEqual(c["resolution"], "measure_wins")
        self.assertIn("la mesure prime", c["message"])
        self.assertIn("0,3", c["message"])                       # virgule décimale française

    def test_symmetric_wear_vs_imbalanced_measure_measure_wins(self):
        out = self.codes(dyn_with_balance(1.8), [insp("a", "2026-09-01", level="none")])
        self.assertEqual(out["symmetric_wear_vs_measured_imbalance"]["resolution"], "measure_wins")
        self.assertNotIn("wear_asymmetry_vs_symmetric_balance", out)

    def test_too_few_balance_sessions_no_arbitration(self):
        out = self.codes(dyn_with_balance(0.2, n=GT.MIN_BALANCE_SESSIONS - 1),
                         [insp("a", "2026-09-01", level="mild", side="left")])
        self.assertNotIn("wear_asymmetry_vs_symmetric_balance", out)

    def test_no_balance_at_all_no_arbitration(self):
        out = self.codes({"stance_balance_pct": None}, [insp("a", "2026-09-01", level="mild", side="left")])
        self.assertEqual(out, {})

    def test_side_change_is_reported(self):
        out = self.codes({}, [insp("a", "2026-08-01", level="mild", side="left"),
                              insp("a", "2026-09-01", level="mild", side="right")])
        self.assertIn("asymmetry_side_changes", out)

    def test_the_side_of_the_balance_is_never_compared_to_the_wear_side(self):
        out = self.codes(dyn_with_balance(1.8), [insp("a", "2026-09-01", level="none")])
        for c in out.values():
            self.assertNotRegex(c["message"], r"pied (gauche|droit)")


class TestGaitSummaryPure(unittest.TestCase):
    def session(self, day, **vals):
        return {"date": day, "activity_id": 1, "name": "x", "sport": "running",
                "values": {k: {"value": v, "source": "samples"} for k, v in vals.items()}, "notes": {}}

    def test_confidence_counts_and_levels(self):
        sessions = [self.session(f"2026-09-{i:02d}", ground_contact_s=0.24,
                                  **({"stance_balance_pct": 50.2} if i % 2 else {})) for i in range(1, 7)]
        sessions.append(self.session("2026-09-10", cadence_spm=170.0))       # cadence seule : pas de « dynamique »
        out = GT.gait_summary(sessions, [insp("a", "2026-09-01", ["heel_strike"])], TODAY, 26)
        conf = out["confidence"]
        self.assertEqual((conf["running_sessions"], conf["sessions_with_dynamics"], conf["sessions_with_balance"]),
                         (7, 6, 3))
        self.assertEqual((conf["inspections"], conf["pairs_inspected"]), (1, 1))
        self.assertEqual((conf["dynamics_level"], conf["inspections_level"]), ("ok", "low"))

    def test_empty_inputs(self):
        out = GT.gait_summary([], [], TODAY, 26)
        self.assertTrue(all(v is None for v in out["dynamics"].values()))
        self.assertEqual(out["confidence"]["dynamics_level"], "none")
        self.assertEqual(out["confidence"]["inspections_level"], "none")
        self.assertEqual(out["contradictions"], [])
        self.assertFalse(out["balance_side_verified"])

    def test_caveat_and_no_load_change_wording(self):
        out = GT.gait_summary([], [], TODAY, 26)
        self.assertIn("Indice, jamais un diagnostic", out["caveat"])
        self.assertIn("ne modifie ni la charge ni le plan", out["caveat"])

    def test_from_arc_block_is_counted(self):
        s = {"date": "2026-09-01", "activity_id": 1, "name": "x", "sport": "trail",
             "values": {"step_length_m": {"value": 1.1, "source": "arc"}}, "notes": {"cadence_suspect": True}}
        out = GT.gait_summary([s], [], TODAY, 26)
        self.assertEqual(out["notes"], {"cadence_suspect": 1, "values_from_arc_block": {"step_length_m": 1}})


class TestContractKeys(unittest.TestCase):
    base = {"arc": 1, "kind": "activity", "date": "2026-09-01", "sport": "running", "duration_s": 3600}

    def check(self, **extra):
        return C.validate({**self.base, **extra})

    def test_valid_dynamics_keys(self):
        self.assertEqual(self.check(avg_ground_contact_s=0.25, avg_stance_balance_pct=50.4,
                                     avg_vertical_oscillation_m=0.095, avg_vertical_ratio_pct=8.6,
                                     avg_step_length_m=1.1), ([], []))

    def test_balance_outside_30_70_warns(self):
        errors, warnings = self.check(avg_stance_balance_pct=80)
        self.assertEqual(errors, [])
        self.assertTrue(any("plage plausible" in w for w in warnings), warnings)
        self.assertEqual(self.check(avg_stance_balance_pct=30), ([], []))
        self.assertEqual(self.check(avg_stance_balance_pct=70), ([], []))

    def test_omitted_is_valid(self):
        self.assertEqual(self.check(), ([], []))

    def test_balance_and_ratio_are_strict_percentages(self):
        for key in ("avg_stance_balance_pct", "avg_vertical_ratio_pct"):
            self.assertTrue(self.check(**{key: 0})[0], key)
            self.assertTrue(self.check(**{key: 100})[0], key)
            self.assertTrue(self.check(**{key: "50"})[0], key)

    def test_negative_durations_and_lengths_are_rejected(self):
        for key in ("avg_ground_contact_s", "avg_vertical_oscillation_m", "avg_step_length_m"):
            self.assertTrue(self.check(**{key: -0.1})[0], key)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-gait-"))
        self.ws = self.tmp / "ws"
        for d in ("activities/fit", "medical", "nutrition", "planning", "rapports", "gear/photos"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        p = self.ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def activity(self, day, gid, sport="running", dynamics=None, **arc):
        data = {"arc": 1, "kind": "activity", "date": day, "sport": sport, "duration_s": 3600,
                "distance_m": 10000, "garmin_activity_id": gid, **arc}
        self.write(f"activities/{day}_{sport}.md", f"# S\n\n```arc\n{json.dumps(data)}\n```\n")
        if dynamics is not None:
            records = [{"t_s": t, "distance_m": t * 3.0, "speed_ms": 3.0, "cadence_spm": 170.0, **dynamics}
                       for t in range(0, 600, 5)]
            self.write(f"activities/fit/{gid}.json", json.dumps({"activity_id": gid, "records": records}))

    def inspection(self, day, gear_id, **extra):
        data = {"arc": 1, "kind": "gear_inspection", "date": day, "gear_id": gear_id, "condition": "yellow", **extra}
        self.write(f"gear/{day}_{gear_id}_inspection.md", f"# I\n\n```arc\n{json.dumps(data)}\n```\n")

    def summary(self, weeks=26):
        I.index_workspace(self.conn, self.ws, TODAY.isoformat())
        return I.gait_summary(self.conn, TODAY, weeks)


class TestIndexAndSummary(Workspace):
    def test_schema_has_dynamics_columns_and_version_bumped(self):
        self.assertGreaterEqual(I.SCHEMA_VERSION, 32)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(activity_sample)")}
        self.assertTrue(set(S.DYNAMICS_KEYS) <= cols, cols)

    def test_running_only_walking_hiking_cycling_excluded(self):
        for sport, gid in (("running", 1), ("trail", 2), ("hiking", 3), ("walking", 4), ("cycling", 5)):
            self.activity(f"2026-09-{gid:02d}", gid, sport, {"ground_contact_s": 0.25})
        out = self.summary()
        self.assertEqual(out["confidence"]["running_sessions"], 2)
        self.assertEqual(out["dynamics"]["ground_contact_s"]["n"], 2)

    def test_session_means_and_window(self):
        self.activity("2026-09-01", 1, dynamics={"ground_contact_s": 0.24, "stance_balance_pct": 50.4,
                                                  "vertical_oscillation_m": 0.09, "vertical_ratio_pct": 8.0,
                                                  "step_length_m": 1.1})
        self.activity("2026-09-10", 2, dynamics={"ground_contact_s": 0.26, "stance_balance_pct": 49.6,
                                                  "vertical_oscillation_m": 0.11, "vertical_ratio_pct": 9.0,
                                                  "step_length_m": 1.3})
        self.activity("2025-01-01", 3, dynamics={"ground_contact_s": 0.99 / 3})       # hors fenêtre (26 sem.)
        out = self.summary()
        d = out["dynamics"]
        self.assertEqual(d["ground_contact_s"]["n"], 2)
        self.assertAlmostEqual(d["ground_contact_s"]["mean"], 0.25, places=4)
        self.assertAlmostEqual(d["stance_balance_pct"]["mean"], 50.0, places=2)
        self.assertAlmostEqual(d["step_length_m"]["mean"], 1.2, places=3)
        self.assertAlmostEqual(d["cadence_spm"]["mean"], 170.0, places=1)      # déjà en pas/min dans les échantillons
        self.assertEqual(out["window"]["weeks"], 26)
        self.assertEqual(out["confidence"]["running_sessions"], 2)

    def test_missing_balance_session_is_not_counted_as_fifty(self):
        self.activity("2026-09-01", 1, dynamics={"ground_contact_s": 0.24, "stance_balance_pct": 52.0})
        self.activity("2026-09-02", 2, dynamics={"ground_contact_s": 0.25, "stance_balance_pct": None})
        out = self.summary()
        b = out["dynamics"]["stance_balance_pct"]
        self.assertEqual(b["n"], 1)
        self.assertEqual(b["mean"], 52.0)
        self.assertEqual(out["confidence"]["sessions_with_balance"], 1)

    def test_arc_block_fallback_when_no_samples(self):
        self.activity("2026-09-01", 1, avg_ground_contact_s=0.255, avg_cadence_spm=172, avg_step_length_m=1.05)
        out = self.summary()
        self.assertEqual(out["dynamics"]["ground_contact_s"]["mean"], 0.255)
        self.assertEqual(out["dynamics"]["cadence_spm"]["mean"], 172.0)
        self.assertEqual(out["notes"]["values_from_arc_block"]["ground_contact_s"], 1)

    def test_per_leg_cadence_in_arc_is_dropped(self):
        self.activity("2026-09-01", 1, avg_cadence_spm=86)
        out = self.summary()
        self.assertIsNone(out["dynamics"]["cadence_spm"])
        self.assertEqual(out["notes"]["cadence_suspect"], 1)

    def test_inspection_contradictions_end_to_end(self):
        for i in range(1, 7):
            self.activity(f"2026-09-{i:02d}", i, dynamics={"ground_contact_s": 0.25, "stance_balance_pct": 50.2})
        self.inspection("2026-09-05", "road", gait_hints=["heel_strike"], asymmetry={"level": "mild", "side": "left"})
        self.inspection("2026-09-06", "trail", gait_hints=["midfoot_forefoot_strike"], asymmetry={"level": "none"})
        out = self.summary()
        codes = {c["code"] for c in out["contradictions"]}
        self.assertEqual(codes, {"strike_hint_differs_across_pairs", "wear_asymmetry_vs_symmetric_balance"})
        self.assertEqual(out["confidence"]["inspections"], 2)

    def test_no_data_at_all(self):
        out = self.summary()
        self.assertEqual(out["confidence"]["sessions_with_dynamics"], 0)
        self.assertEqual(out["inspections"]["pairs"], [])

    def test_reingest_after_refresh_replaces_the_dynamics(self):
        self.activity("2026-09-01", 1, dynamics={})                          # FIT d'avant #151 : aucune dynamique
        self.assertIsNone(self.summary()["dynamics"]["ground_contact_s"])
        self.write("activities/fit/1.json", json.dumps({"activity_id": 1, "records": [
            {"t_s": t, "speed_ms": 3.0, "ground_contact_s": 0.25} for t in range(0, 100, 5)]}))
        self.assertEqual(self.summary()["dynamics"]["ground_contact_s"]["mean"], 0.25)

    def test_intervals_sourced_session_gets_its_dynamics(self):
        data = {"arc": 1, "kind": "activity", "date": "2026-09-05", "sport": "running", "duration_s": 3600,
                "intervals_activity_id": "i555"}
        self.write("activities/2026-09-05_running.md", f"# S\n\n```arc\n{json.dumps(data)}\n```\n")
        self.write("activities/fit/i555.json", json.dumps({"activity_id": "i555", "records": [
            {"t_s": t, "speed_ms": 3.0, "ground_contact_s": 0.27} for t in range(0, 100, 5)]}))
        out = self.summary()
        self.assertEqual(out["dynamics"]["ground_contact_s"]["mean"], 0.27)
        self.assertEqual(out["confidence"]["sessions_with_dynamics"], 1)

    def test_cli_gait_summary(self):
        self.activity("2026-09-01", 1, dynamics={"ground_contact_s": 0.25})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(["--workspace", str(self.ws), "--memory", "--today", "2026-09-23",
                           "gait-summary", "--weeks", "4"])
        out = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(out["window"]["weeks"], 4)
        self.assertEqual(out["dynamics"]["ground_contact_s"]["n"], 1)

    def test_assumption_documents_the_method_and_the_unverified_side(self):
        text = M.ASSUMPTIONS["gait"]
        for needle in ("approximation", "50 %", "Jamais un diagnostic", "MESURE prime", "gauche/droite"):
            self.assertIn(needle, text)
        self.assertIn("balance_side", GT.ASSUMPTIONS)
        self.assertIn("n'est pas établi", GT.ASSUMPTIONS["balance_side"])


class FakeFit:
    """Remplace `_read_fit` : un FIT = liste de records façon `fitparse` + sport."""

    def __init__(self, by_name):
        self.by_name = by_name

    def __call__(self, data: bytes):
        return self.by_name[data.decode()]


class TestRefreshDynamics(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-refresh-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "fit").mkdir()
        run = [raw(i, stance_time=250.0 + i, stance_time_balance=50.5, vertical_oscillation=100.0,
                   vertical_ratio=9.0, step_length=1100.0) for i in range(0, 20, 2)]
        ride = [raw(i) for i in range(0, 20, 2)]
        self.fits = {"run": (run, "running"), "ride": (ride, "cycling")}
        (self.tmp / "111.fit").write_bytes(b"run")
        (self.tmp / "222.fit").write_bytes(b"ride")
        (self.tmp / "notes.fit").write_bytes(b"run")          # nom non numérique : ignoré

    def refresh(self, **kw):
        with patch.object(D, "_read_fit", FakeFit(self.fits)):
            return D.refresh_dynamics(self.tmp, **kw)

    def test_rewrites_old_json_then_is_idempotent(self):
        old = {"activity_id": 111, "records": [{"t_s": 0, "distance_m": 0, "altitude_m": None, "hr_bpm": 140,
                                                  "speed_ms": 3.0, "cadence_spm": 176.0}]}
        (self.tmp / "fit/111.json").write_text(json.dumps(old), encoding="utf-8")
        first = self.refresh()
        self.assertEqual((first["created"], first["rewritten"], first["unchanged"], first["failed"]), (1, 1, 0, 0))
        self.assertIn((111, "rewritten"), first["files"])
        self.assertIn((222, "created"), first["files"])       # `.fit` sans JSON (téléchargé sans --json) : créé
        self.assertEqual(first["with_dynamics"], 1)              # seul le FIT de course porte de la dynamique
        payload = json.loads((self.tmp / "fit/111.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(payload["records"][0]["ground_contact_s"], 0.25, places=3)
        self.assertEqual(payload["records"][0]["cadence_spm"], 176.0)        # course : doublée
        ride = json.loads((self.tmp / "fit/222.json").read_text(encoding="utf-8"))
        self.assertEqual(ride["records"][0]["cadence_spm"], 88.0)            # vélo : jamais doublée
        self.assertIsNone(ride["records"][0]["stance_balance_pct"])
        second = self.refresh()
        self.assertEqual((second["created"], second["rewritten"], second["unchanged"]), (0, 0, 2))
        self.assertFalse((self.tmp / "fit/notes.json").exists())

    def test_dry_run_writes_nothing(self):
        (self.tmp / "fit/111.json").write_text(json.dumps({"activity_id": 111, "records": []}), encoding="utf-8")
        before = (self.tmp / "fit/111.json").read_text(encoding="utf-8")
        result = self.refresh(dry_run=True)
        self.assertEqual((result["created"], result["rewritten"]), (1, 1))
        self.assertEqual([p.name for p in (self.tmp / "fit").glob("*.json")], ["111.json"])
        self.assertEqual((self.tmp / "fit/111.json").read_text(encoding="utf-8"), before)
        self.assertIn((111, "would_rewrite"), result["files"])
        self.assertIn((222, "would_create"), result["files"])

    def test_keeps_extra_top_level_keys_and_touches_no_markdown(self):
        (self.tmp / "2026-09-01_running.md").write_text("# S\n", encoding="utf-8")
        (self.tmp / "fit/111.json").write_text(json.dumps({"activity_id": 111, "records": [], "truth": {"x": 1}}))
        self.refresh()
        self.assertEqual(json.loads((self.tmp / "fit/111.json").read_text())["truth"], {"x": 1})
        self.assertEqual((self.tmp / "2026-09-01_running.md").read_text(encoding="utf-8"), "# S\n")

    def test_intervals_icu_fit_files_are_refreshed_too(self):
        """#68 : `i<chiffres>.fit` (source Intervals.icu) — même emplacement, JSON `fit/i<chiffres>.json`."""
        self.fits["irun"] = self.fits["run"]
        (self.tmp / "i987654.fit").write_bytes(b"irun")
        (self.tmp / "iabc.fit").write_bytes(b"irun")             # forme invalide : ignoré
        result = self.refresh()
        self.assertIn(("i987654", "created"), result["files"])
        payload = json.loads((self.tmp / "fit/i987654.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["activity_id"], "i987654")
        self.assertAlmostEqual(payload["records"][0]["ground_contact_s"], 0.25, places=3)
        self.assertFalse((self.tmp / "fit/iabc.json").exists())

    def test_coros_fit_files_are_refreshed_too(self):
        """#168 : `c<chiffres>.fit` (source COROS) — rattrapable sans retélécharger, JSON `fit/c<chiffres>.json`."""
        self.fits["crun"] = self.fits["run"]
        (self.tmp / "c481284612648108342.fit").write_bytes(b"crun")
        (self.tmp / "cabc.fit").write_bytes(b"crun")             # forme invalide : ignoré
        result = self.refresh()
        self.assertIn(("c481284612648108342", "created"), result["files"])
        payload = json.loads((self.tmp / "fit/c481284612648108342.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["activity_id"], "c481284612648108342")
        self.assertFalse((self.tmp / "fit/cabc.json").exists())

    def test_unreadable_fit_is_counted_not_fatal(self):
        self.fits.pop("ride")
        result = self.refresh()
        self.assertEqual((result["created"], result["failed"]), (1, 1))

    def test_main_refresh_needs_no_ids_and_reports(self):
        buf = io.StringIO()
        with patch.object(D, "_read_fit", FakeFit(self.fits)), patch.object(D, "_relaunch_for_fitparse") as relaunch, \
                patch.object(D, "_auto_relaunch") as auto, contextlib.redirect_stdout(buf):
            code = D.main(["--refresh-dynamics", "--output-dir", str(self.tmp)])
        self.assertEqual(code, 0)
        relaunch.assert_called_once()                               # fitparse seul
        auto.assert_not_called()                                    # jamais `garminconnect` : aucune connexion Garmin
        out = buf.getvalue()
        self.assertIn("2 JSON créés, 0 réécrits", out)
        self.assertIn("111 : créé", out)                       # id par id


if __name__ == "__main__":
    unittest.main()
