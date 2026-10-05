"""Palier D — recalibrage des coefficients de pacing au débrief (#188, épopée #170).

Courses SYNTHÉTIQUES (aucune donnée d'athlète) dont les « vraies » pénalités de nuit /
technicité diffèrent des défauts : les propositions doivent bouger dans le bon sens, être
attirées vers le défaut (attrition), refuser quand les groupes sont trop petits ou confondus,
se CUMULER d'un débrief à l'autre, être relues par `arc_race_pacing` (le drapeau CLI primant) et
laisser le pacing inchangé octet pour octet sans `[pacing.personal]`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_heat as H  # noqa: E402
import arc_pacing_calibration as CAL  # noqa: E402
import arc_pacing_personal as PP  # noqa: E402
import arc_race_debrief as D  # noqa: E402
import arc_race_pacing as RP  # noqa: E402
from tests.data.test_arc_race_pacing import _ClimbFlatDescentProfile, _straight_course  # noqa: E402

N_SEG = 40
BASE_S = 300.0
NIGHT_PCT = 5.0  # pénalité de nuit du plan (défaut)


def _plan(*, night=range(18, 34), tech=(), tech_eff=1.1, heat_notes=None, race_name="Course Fictive",
          race_date="2026-09-27", with_tech=True, personal=None):
    """40 segments d'1 km, 300 s/km prévus x facteurs du plan (nuit 1,05, technicité `tech_eff`)."""
    segs = []
    for i in range(N_SEG):
        nf = 1.0 + NIGHT_PCT / 100.0 if i in night else 1.0
        eff = tech_eff if i in tech else 1.0
        t = round(BASE_S * nf * eff, 1)
        seg = {"id": f"s{i + 1:02d}", "km_start": float(i), "km_end": float(i + 1), "distance_m": 1000.0,
               "predicted_time_s": {"safe": t * 1.1, "realistic": t, "ambitious": t * 0.9},
               "pace_s_km": {"safe": t * 1.1, "realistic": t, "ambitious": t * 0.9},
               "night_fraction": {"safe": 1.0 if i in night else 0.0, "realistic": 1.0 if i in night else 0.0,
                                  "ambitious": 1.0 if i in night else 0.0},
               "night_factor": {"safe": nf, "realistic": nf, "ambitious": nf}}
        if with_tech:
            seg["technicity"] = {"coef": eff, "effective_factor": eff, "source": "declared" if eff != 1.0 else "none"}
        segs.append(seg)
    plan = {"arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": race_name, "race_date": race_date,
            "segments": segs}
    if heat_notes is not None:
        plan["heat_notes"] = heat_notes
    if personal:
        plan["pacing_personal"] = personal
    return plan


def _activity(plan, *, night_true=NIGHT_PCT, tech_true=None, bias=1.0, date="2026-09-27", noise=0.0):
    """Splits d'1 km : temps réel = base x biais x technicité VRAIE x nuit VRAIE (+ bruit déterministe)."""
    splits = []
    cum = 0.0
    for i, seg in enumerate(plan["segments"]):
        nf = seg["night_factor"]["realistic"]
        is_night = seg["night_fraction"]["realistic"] > 0.5
        eff_plan = seg["technicity"]["effective_factor"] if "technicity" in seg else 1.0
        eff = eff_plan if (tech_true is None or eff_plan == 1.0) else tech_true
        night = 1.0 + night_true / 100.0 if is_night else 1.0
        wobble = 1.0 + noise * (1 if i % 2 else -1) * ((i % 5) / 5.0)
        t = BASE_S * bias * eff * night * wobble
        cum += t
        splits.append([i + 1, round(t, 2), 1000.0])
    return {"arc": 1, "kind": "activity", "date": date, "sport": "trail", "duration_s": cum,
            "distance_m": 1000.0 * N_SEG, "splits_cols": ["km", "duration_s", "distance_m"], "splits": splits}


def _calibrate(plan, activity, existing=None, **kw):
    debrief = D.build_race_debrief(plan, activity)
    return CAL.calibrate(plan, debrief, scenario="realistic", existing=existing, **kw)


class TestNightAttribution(unittest.TestCase):
    def test_underestimated_night_moves_up_with_shrinkage(self):
        plan = _plan()
        rep = _calibrate(plan, _activity(plan, night_true=12.0))
        f = rep["factors"]["night"]
        self.assertEqual(f["status"], "estimated")
        self.assertAlmostEqual(f["observed"], 12.0, delta=0.2)
        self.assertEqual(f["n_used_exposed"], 16)
        self.assertEqual(f["confidence"], "high")
        p = rep["proposals"]["night_penalty_pct"]
        self.assertEqual(p["status"], "proposal")
        # w = 16 / (16 + 20) : défaut + w x (observé - défaut)
        self.assertAlmostEqual(p["weight"], 16 / 36, places=3)
        self.assertAlmostEqual(p["proposed"], 5.0 + 16 / 36 * (12.0 - 5.0), delta=0.15)
        self.assertGreater(p["proposed"], 5.0)
        self.assertLess(p["proposed"], 12.0)
        self.assertFalse(rep["applied"])
        self.assertEqual(rep["config_patch"]["section"], "pacing.personal")

    def test_overestimated_night_moves_down(self):
        plan = _plan()
        rep = _calibrate(plan, _activity(plan, night_true=1.0))
        self.assertLess(rep["proposals"]["night_penalty_pct"]["proposed"], 5.0)

    def test_global_bias_does_not_leak_into_night(self):
        """Un biais de base (allure d'endurance trop optimiste) touche jour ET nuit : écarté."""
        plan = _plan()
        rep = _calibrate(plan, _activity(plan, night_true=NIGHT_PCT, bias=1.08))
        self.assertEqual(rep["factors"]["night"]["status"], "inconclusive")
        self.assertNotIn("night_penalty_pct", rep["proposals"])

    def test_correct_default_is_no_proposal(self):
        plan = _plan()
        rep = _calibrate(plan, _activity(plan))
        self.assertEqual(rep["config_patch"]["values"], {})

    def test_too_few_night_segments_refused(self):
        plan = _plan(night=range(18, 21))
        rep = _calibrate(plan, _activity(plan, night_true=15.0))
        f = rep["factors"]["night"]
        self.assertEqual(f["status"], "refused")
        self.assertIn("trop peu", f["reason"])
        self.assertEqual(rep["config_patch"]["values"], {})

    def test_no_night_in_plan_is_not_applicable(self):
        plan = _plan(night=())
        rep = _calibrate(plan, _activity(plan))
        self.assertEqual(rep["factors"]["night"]["status"], "not_applicable")

    def test_night_confounded_with_technicity_refused(self):
        """Toutes les sections techniques sont de nuit et toutes celles de nuit sont techniques :
        aucune cellule ne contient à la fois exposés et référence."""
        night = range(18, 34)
        plan = _plan(night=night, tech=set(night))
        rep = _calibrate(plan, _activity(plan, night_true=15.0))
        f = rep["factors"]["night"]
        self.assertEqual(f["status"], "refused")
        self.assertEqual(f["refusal_code"], "confounded")
        self.assertIn("confondu", f["reason"])
        t = rep["factors"]["technicity"]
        self.assertEqual(t["status"], "refused")
        self.assertEqual(t["refusal_code"], "confounded")
        self.assertEqual(rep["config_patch"]["values"], {})

    def test_night_estimated_within_smooth_stratum_despite_technical_day(self):
        """Des sections techniques de jour (autre cellule) ne polluent pas le contraste de nuit."""
        plan = _plan(tech=set(range(2, 14)), tech_eff=1.1)
        rep = _calibrate(plan, _activity(plan, night_true=12.0, tech_true=1.1))
        self.assertAlmostEqual(rep["factors"]["night"]["observed"], 12.0, delta=0.3)
        self.assertEqual({c["cell"] for c in rep["factors"]["night"]["cells"]}, {"smooth/low"})


class TestReviewFindings(unittest.TestCase):
    """Revue de code #188 : supplément de descente, preuves « dans le bruit », écart de position,
    course anormale."""

    def test_night_descent_extra_not_attributed_to_base(self):
        """Le plan ajoute un supplément de nuit en DESCENTE ; la vraie pénalité de base est 12 %.
        L'observé doit être 12, pas 12 + supplément (double compte au plan suivant)."""
        night = range(18, 34)
        plan = _plan(night=night)
        for i, seg in enumerate(plan["segments"]):
            seg["grade_mean_pct"] = -10.0 if i % 2 else 3.0
            if i in night:
                pen = RP.night_penalty_fraction(seg["grade_mean_pct"])
                seg["night_factor"] = {k: 1.0 + pen for k in ("safe", "realistic", "ambitious")}
                for k in ("predicted_time_s", "pace_s_km"):
                    seg[k] = {sc: round(BASE_S * (1.0 + pen) * f, 1)
                              for sc, f in (("safe", 1.1), ("realistic", 1.0), ("ambitious", 0.9))}
        act = _activity(plan)
        for i in night:
            pen_true = RP.night_penalty_fraction(plan["segments"][i]["grade_mean_pct"], base_pct=12.0)
            act["splits"][i][1] = round(BASE_S * (1.0 + pen_true), 2)
        f = _calibrate(plan, act)["factors"]["night"]
        self.assertEqual(f["status"], "estimated")
        self.assertAlmostEqual(f["observed"], 12.0, delta=0.3)

    def test_inconclusive_debrief_still_records_evidence(self):
        """Sans quoi seules les courses à gros écart seraient cumulées (biais loin du défaut)."""
        plan = _plan()
        rep = _calibrate(plan, _activity(plan, bias=1.08))
        self.assertEqual(rep["factors"]["night"]["status"], "inconclusive")
        self.assertNotIn("night_penalty_pct", rep["proposals"])
        self.assertTrue(any("|night|" in e for e in rep["evidence"]))
        self.assertNotIn("evidence", rep["factors"]["night"])

    def test_late_exposure_caps_confidence(self):
        """Nuit en FIN de course : toute la référence est plus tôt -> confiance faible + note."""
        plan = _plan(night=range(24, 40))
        f = _calibrate(plan, _activity(plan, night_true=12.0))["factors"]["night"]
        self.assertEqual(f["status"], "estimated")
        self.assertGreater(f["position_gap"], CAL.POSITION_GAP_MAX)
        self.assertEqual(f["confidence"], "low")
        self.assertIn("fatigue", f["position_note"])
        mid = _calibrate(_plan(), _activity(_plan(), night_true=12.0))["factors"]["night"]
        self.assertLessEqual(abs(mid["position_gap"]), CAL.POSITION_GAP_MAX)
        self.assertNotIn("position_note", mid)

    def test_abnormal_fade_refuses_and_exclusion_recovers(self):
        plan = _plan()
        act = _activity(plan, night_true=12.0)
        for i in range(32, N_SEG):  # fin de course marchée
            act["splits"][i][1] = round(act["splits"][i][1] * 2.0, 2)
        rep = _calibrate(plan, act)
        for f in ("night", "technicity", "altitude", "heat"):
            self.assertEqual(rep["factors"][f]["status"], "refused", f)
            self.assertEqual(rep["factors"][f]["refusal_code"], "abnormal_fade")
        self.assertEqual(rep["config_patch"], {"section": "pacing.personal", "values": {}, "evidence": []})
        self.assertIn("abnormal_fade", rep["segments"])
        ok = _calibrate(plan, act, exclude_from_km=32.0)
        self.assertEqual(ok["segments"]["skipped"]["excluded"], 8)
        self.assertEqual(ok["factors"]["night"]["status"], "estimated")
        self.assertAlmostEqual(ok["factors"]["night"]["observed"], 12.0, delta=0.3)


class TestTechnicityAttribution(unittest.TestCase):
    def test_underestimated_technicity_scale_goes_up(self):
        # coef planifié 1,10 (surcoût 10 %) ; surcoût réel 20 % -> échelle observée 2,0
        plan = _plan(tech=set(range(2, 14)) | set(range(36, 40)), tech_eff=1.1)
        rep = _calibrate(plan, _activity(plan, tech_true=1.2))
        f = rep["factors"]["technicity"]
        self.assertEqual(f["status"], "estimated")
        self.assertAlmostEqual(f["observed"], 2.0, delta=0.05)
        p = rep["proposals"]["technicity_scale"]
        self.assertGreater(p["proposed"], 1.0)
        self.assertLess(p["proposed"], 2.0)
        self.assertEqual(p["status"], "proposal")

    def test_plan_without_technicity_not_applicable(self):
        plan = _plan(with_tech=False)
        rep = _calibrate(plan, _activity(plan))
        self.assertEqual(rep["factors"]["technicity"]["status"], "not_applicable")

    def test_observed_scale_composes_with_scale_already_used(self):
        """Plan construit AVEC échelle 1,5 : le surcoût planifié (coef 1,15) inclut déjà ce 1,5 ;
        un surcoût réel de 20 % vaut une échelle ABSOLUE de 2,0 (0,2 / 0,10 base)."""
        plan = _plan(tech=set(range(2, 14)), tech_eff=1.15, personal={"technicity_scale": 1.5})
        rep = _calibrate(plan, _activity(plan, tech_true=1.2))
        self.assertAlmostEqual(rep["factors"]["technicity"]["observed"], 1.5 * (1.15 * (1.2 / 1.15) - 1) / 0.15,
                               delta=0.05)

    def test_few_technical_sections_refused(self):
        plan = _plan(tech={5, 6})
        rep = _calibrate(plan, _activity(plan, tech_true=1.3))
        self.assertEqual(rep["factors"]["technicity"]["status"], "refused")


class TestAltitudeGeneric(unittest.TestCase):
    def test_altitude_factor_included_when_present(self):
        plan = _plan(night=())
        for i, seg in enumerate(plan["segments"]):
            a = 1.04 if 20 <= i < 32 else 1.0
            seg["altitude_factor"] = {"realistic": a}
            if a > 1.0:
                for k in ("predicted_time_s", "pace_s_km"):
                    seg[k]["realistic"] = round(seg[k]["realistic"] * a, 1)
        act = _activity(plan)
        for i in range(20, 32):  # la vraie perte est le double
            act["splits"][i][1] = round(act["splits"][i][1] * 1.08, 2)
        rep = _calibrate(plan, act)
        f = rep["factors"]["altitude"]
        self.assertEqual(f["status"], "estimated")
        self.assertAlmostEqual(f["observed"], 2.0, delta=0.1)
        self.assertIn("altitude_scale", rep["proposals"])

    def test_no_altitude_in_plan_skipped(self):
        plan = _plan()
        self.assertEqual(_calibrate(plan, _activity(plan))["factors"]["altitude"]["status"], "not_applicable")


class TestHeat(unittest.TestCase):
    HOT = ["chaleur prévue (28 °C > 25 °C) : temps × 1.1 (approximation du projet)"]

    def test_single_race_records_evidence_only(self):
        plan = _plan(night=(), heat_notes=self.HOT)
        rep = _calibrate(plan, _activity(plan, bias=1.05))
        self.assertEqual(rep["factors"]["heat"]["status"], "estimated")
        self.assertNotIn("heat_hot_factor", rep["proposals"])
        self.assertIn("note", rep["factors"]["heat"])

    @staticmethod
    def _existing(report):
        return {"values": {}, "evidence": [PP.parse_evidence(e)[0][0] for e in report["evidence"]], "warnings": []}

    def test_one_hot_race_is_never_enough(self):
        """Revue #188 : une course chaude + une neutre ne proposent RIEN (biais de base du jour
        indiscernable de la chaleur) ; il en faut au moins HEAT_MIN_HOT_RACES."""
        neutral = _plan(night=(), heat_notes=[], race_name="Course Fraiche", race_date="2026-05-01")
        r1 = _calibrate(neutral, _activity(neutral, bias=1.0, date="2026-05-01"))
        hot = _plan(night=(), heat_notes=self.HOT, race_name="Course Chaude", race_date="2026-09-27")
        rep = _calibrate(hot, _activity(hot, bias=1.20 / 1.10), existing=self._existing(r1))
        self.assertNotIn("heat_hot_factor", rep["proposals"])
        self.assertIn(str(CAL.HEAT_MIN_HOT_RACES), rep["factors"]["heat"]["note"])

    def test_hot_and_neutral_races_estimate_hot_factor(self):
        neutral = _plan(night=(), heat_notes=[], race_name="Course Fraiche", race_date="2026-05-01")
        r1 = _calibrate(neutral, _activity(neutral, bias=1.0, date="2026-05-01"))
        hot1 = _plan(night=(), heat_notes=self.HOT, race_name="Course Chaude 1", race_date="2026-07-14")
        r2 = _calibrate(hot1, _activity(hot1, bias=1.20 / 1.10, date="2026-07-14"), existing=self._existing(r1))
        hot = _plan(night=(), heat_notes=self.HOT, race_name="Course Chaude", race_date="2026-09-27")
        # vraie chaleur : x1,20 au lieu de 1,10 (le plan l'a déjà appliquée dans son prévu)
        act = _activity(hot, bias=1.20 / 1.10)
        rep = _calibrate(hot, act, existing=self._existing(r2))
        p = rep["proposals"]["heat_hot_factor"]
        self.assertAlmostEqual(rep["factors"]["heat"]["base_ratio"], 1.20 / 1.10, places=3)
        self.assertAlmostEqual(p["observed_cumulated"], 1.10 * (1.20 / 1.10), delta=0.005)
        self.assertGreater(p["proposed"], 1.10)
        self.assertLess(p["proposed"], 1.20)

    def test_actual_weather_contradicting_plan_refuses(self):
        plan = _plan(night=(), heat_notes=self.HOT)
        rep = _calibrate(plan, _activity(plan), actual_weather={"temp_max_c": 15.0})
        self.assertEqual(rep["factors"]["heat"]["status"], "refused")

    def test_cold_and_unknown_not_applicable(self):
        cold = _plan(night=(), heat_notes=["froid prévu (2 °C < 5 °C) : temps × 1.05 (approximation du projet)"])
        self.assertEqual(_calibrate(cold, _activity(cold))["factors"]["heat"]["status"], "not_applicable")
        unknown = _plan(night=())
        self.assertEqual(_calibrate(unknown, _activity(unknown))["factors"]["heat"]["status"], "not_applicable")


class TestAccumulation(unittest.TestCase):
    def _existing(self, report):
        recs = [PP.parse_evidence(e)[0][0] for e in report["evidence"]]
        return {"values": dict(report["config_patch"]["values"]), "evidence": recs, "warnings": []}

    def test_two_debriefs_combine_evidence(self):
        p1 = _plan(race_name="Course A", race_date="2026-06-01")
        r1 = _calibrate(p1, _activity(p1, night_true=12.0, date="2026-06-01"))
        p2 = _plan(race_name="Course B", race_date="2026-09-27", night=range(10, 26))
        r2 = _calibrate(p2, _activity(p2, night_true=9.0, date="2026-09-27"), existing=self._existing(r1))
        acc = r2["proposals"]["night_penalty_pct"]
        self.assertEqual(acc["races"], 2)
        self.assertEqual(acc["n"], 32)
        self.assertAlmostEqual(acc["observed_cumulated"], (12.0 + 9.0) / 2, delta=0.3)
        self.assertAlmostEqual(acc["weight"], 32 / 52, places=3)
        # plus de preuves : plus près de l'observé que le débrief seul
        self.assertGreater(acc["proposed"], r1["proposals"]["night_penalty_pct"]["proposed"] - 1.0)
        self.assertEqual(len(r2["evidence"]), 2 * 1 + 0)  # night x2 (technicité/altitude non applicables)

    def test_rerunning_same_debrief_is_idempotent(self):
        p1 = _plan()
        act = _activity(p1, night_true=12.0)
        r1 = _calibrate(p1, act)
        existing = self._existing(r1)
        r1b = _calibrate(p1, act, existing=existing)
        self.assertEqual(r1b["evidence"], r1["evidence"])
        self.assertEqual(r1b["proposals"]["night_penalty_pct"]["n"], 16)

    def test_dead_band_after_applying(self):
        """Une fois la proposition écrite, rejouer le même débrief ne propose plus rien."""
        p1 = _plan()
        act = _activity(p1, night_true=12.0)
        r1 = _calibrate(p1, act)
        again = _calibrate(p1, act, existing=self._existing(r1))
        self.assertEqual(again["proposals"]["night_penalty_pct"]["status"], "no_change")
        self.assertEqual(again["config_patch"]["values"], {})


class TestPersonalConfig(unittest.TestCase):
    def test_write_and_read_roundtrip_preserves_other_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "config").mkdir()
            user = ws / "config" / "workspace.user.toml"
            user.write_text('# perso\n[coaching]\nstyle = "direct"\n', encoding="utf-8")
            ev = [("2026-09-27", "course-a", "night", 16, 12.0)]
            PP.write_workspace(ws, {"night_penalty_pct": 8.1, "technicity_scale": 1.2}, ev)
            text = user.read_text(encoding="utf-8")
            self.assertIn("# perso", text)
            self.assertIn('style = "direct"', text)
            got = PP.read_workspace(ws)
            self.assertEqual(got["values"], {"night_penalty_pct": 8.1, "technicity_scale": 1.2})
            self.assertEqual(got["evidence"], ev)
            self.assertEqual(got["warnings"], [])

    def test_backup_is_the_file_before_the_debrief(self):
        """`.bak` = fichier d'AVANT l'écriture, même quand plusieurs clés changent (revue #188)."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "config").mkdir()
            user = ws / "config" / "workspace.user.toml"
            before = '# perso\n[coaching]\nstyle = "direct"\n'
            user.write_text(before, encoding="utf-8")
            PP.write_workspace(ws, {"night_penalty_pct": 8.1, "technicity_scale": 1.2},
                               [("2026-09-27", "course-a", "night", 16, 12.0)])
            self.assertEqual((ws / "config" / "workspace.user.toml.bak").read_text(encoding="utf-8"), before)

    def test_invalid_value_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "config").mkdir()
            user = ws / "config" / "workspace.user.toml"
            user.write_text("[coaching]\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                PP.write_workspace(ws, {"night_penalty_pct": 8.0, "technicity_scale": 9.0}, [])
            self.assertEqual(user.read_text(encoding="utf-8"), "[coaching]\n")

    def test_invalid_values_ignored_with_warning(self):
        got = PP.read_config({"pacing": {"personal": {"night_penalty_pct": 99, "technicity_scale": "abc",
                                                       "heat_hot_factor": True, "altitude_scale": 1.3}}})
        self.assertEqual(got["values"], {"altitude_scale": 1.3})
        self.assertEqual(len(got["warnings"]), 3)

    def test_dotted_section_fallback_shape(self):
        got = PP.read_config({"pacing.personal": {"night_penalty_pct": "7.5"}})
        self.assertEqual(got["values"], {"night_penalty_pct": 7.5})

    def test_bounds_match_pacing_engine(self):
        self.assertEqual(PP.BOUNDS["night_penalty_pct"][1], RP.NIGHT_PENALTY_PCT_MAX)
        self.assertEqual(CAL.DEFAULTS["night_penalty_pct"], RP.NIGHT_BASE_PENALTY_PCT)
        self.assertEqual(CAL.DEFAULTS["heat_hot_factor"], H.HEAT_HOT_TIME_FACTOR)


class TestPacingReadsPersonal(unittest.TestCase):
    """`arc_race_pacing.py plan` en sous-processus : config personnelle lue, drapeau CLI prioritaire,
    sortie identique sans section."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        pts = _straight_course(_ClimbFlatDescentProfile(), step_m=25.0)
        gpx = ['<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>']
        for p in pts:
            gpx.append(f'<trkpt lat="{p["lat"]}" lon="{p["lon"]}"><ele>{p["ele"]}</ele></trkpt>')
        gpx.append("</trkseg></trk></gpx>")
        cls.gpx = cls.root / "course.gpx"
        cls.gpx.write_text("".join(gpx), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _workspace(self, toml: str = "") -> Path:
        ws = Path(tempfile.mkdtemp(dir=self.root))
        (ws / "config").mkdir()
        if toml:
            (ws / "config" / "workspace.user.toml").write_text(toml, encoding="utf-8")
        return ws

    def _plan(self, ws: Path, *extra: str) -> dict:
        cmd = [sys.executable, str(REPO / "scripts" / "arc_race_pacing.py"), "plan", "--gpx", str(self.gpx),
               "--workspace", str(ws), "--memory", "--race-date", "2026-06-20", "--start", "17:00",
               "--tz", "Etc/GMT+9", "--temp-max-c", "30", *extra]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_config_read_and_cli_override_precedence(self):
        base = self._plan(self._workspace())
        self.assertNotIn("pacing_personal", base)
        ws = self._workspace("[pacing.personal]\nnight_penalty_pct = 12.0\nheat_hot_factor = 1.2\n")
        pers = self._plan(ws)
        self.assertEqual(pers["pacing_personal"], {"night_penalty_pct": 12.0, "heat_hot_factor": 1.2})
        self.assertGreater(pers["heat_factor"], base["heat_factor"])
        self.assertAlmostEqual(pers["heat_factor"] / base["heat_factor"], 1.2 / 1.1, places=2)
        self.assertEqual(pers["night"]["parameters"]["base_penalty_pct"], 12.0)
        self.assertEqual(base["night"]["parameters"]["base_penalty_pct"], RP.NIGHT_BASE_PENALTY_PCT)
        self.assertIn("coefficient personnel", " ".join(pers["heat_notes"]))
        # le drapeau CLI prime : pénalité de nuit 5 % malgré la config (chaleur toujours personnelle)
        over = self._plan(ws, "--night-penalty-pct", "5")
        self.assertEqual(over["night"]["parameters"]["base_penalty_pct"], 5.0)
        self.assertEqual(over["pacing_personal"], {"heat_hot_factor": 1.2})

    def test_byte_identical_without_personal_section(self):
        a = self._plan(self._workspace())
        b = self._plan(self._workspace("[coaching]\nstyle = \"direct\"\n"))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertNotIn("pacing_personal", a)

    def test_invalid_personal_value_ignored(self):
        base = self._plan(self._workspace())
        bad = self._plan(self._workspace("[pacing.personal]\nnight_penalty_pct = 99\n"))
        self.assertEqual(json.dumps(base, sort_keys=True), json.dumps(bad, sort_keys=True))


class TestCalibrateCli(unittest.TestCase):
    def _files(self, root: Path, plan: dict, activity: dict):
        for name, block, folder in (("plan", plan, "planning"), ("act", activity, "activities")):
            (root / folder).mkdir(exist_ok=True)
            (root / f"{name}.md").write_text(f"# t\n\n```arc\n{json.dumps(block)}\n```\n", encoding="utf-8")

    def _run(self, root, *extra):
        cmd = [sys.executable, str(REPO / "scripts" / "arc_race_debrief.py"), "debrief", "--plan", str(root / "plan.md"),
               "--activity", str(root / "act.md"), "--calibrate", "--workspace", str(root), *extra]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    def test_json_text_apply_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan()
            self._files(root, plan, _activity(plan, night_true=12.0))
            out = self._run(root)
            self.assertEqual(out.returncode, 0, out.stderr)
            rep = json.loads(out.stdout)
            self.assertEqual(rep["proposals"]["night_penalty_pct"]["status"], "proposal")
            self.assertFalse(rep["applied"])
            self.assertFalse((root / "config" / "workspace.user.toml").exists(), "jamais écrit sans --apply")
            txt = self._run(root, "--text")
            self.assertIn("Propositions", txt.stdout)
            auto = json.loads(self._run(root, "--scenario", "auto").stdout)
            self.assertIn(auto["race"]["scenario"], ("safe", "realistic", "ambitious"))
            applied = json.loads(self._run(root, "--apply").stdout)
            self.assertTrue(applied["applied"])
            got = PP.read_workspace(root)
            self.assertAlmostEqual(got["values"]["night_penalty_pct"], rep["proposals"]["night_penalty_pct"]["proposed"], places=3)
            again = json.loads(self._run(root).stdout)
            self.assertEqual(again["proposals"]["night_penalty_pct"]["status"], "no_change")

    def test_flags_require_calibrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan()
            self._files(root, plan, _activity(plan))
            cmd = [sys.executable, str(REPO / "scripts" / "arc_race_debrief.py"), "debrief", "--plan", str(root / "plan.md"),
                   "--activity", str(root / "act.md"), "--apply"]
            self.assertEqual(subprocess.run(cmd, capture_output=True, text=True).returncode, 1)
            out = subprocess.run(cmd[:-1] + ["--exclude-from-km", "30"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertIn("--calibrate", out.stderr)


class TestTechnicityScaleInEngine(unittest.TestCase):
    def test_scale_multiplies_surcharge_and_default_is_untouched(self):
        pts = _straight_course(_ClimbFlatDescentProfile(), step_m=25.0)
        declared = {"declared": [{"km_start": 0.0, "km_end": 3.0, "coef": 1.2, "note": "t"}], "ways": None,
                    "osm_requested": False}
        kw = dict(fade_pct=0.0, temp_max_c=None, intensity_factor=1.0, intensity_source="none", segment_m=750.0,
                  technicity=declared)
        bins = __import__("tests.data.test_arc_race_pacing", fromlist=["PERSONAL_BINS"]).PERSONAL_BINS
        base = RP.build_race_plan(pts, bins, **kw)
        same = RP.build_race_plan(pts, bins, technicity_scale=1.0, **kw)
        self.assertEqual(json.dumps(base["segments"], sort_keys=True), json.dumps(same["segments"], sort_keys=True))
        scaled = RP.build_race_plan(pts, bins, technicity_scale=2.0, **kw)
        flat = [s for s in scaled["segments"] if s["technicity"]["source"] == "declared"
                and abs(s["technicity"].get("coef_before_scale", 0) - 1.2) < 1e-9]
        self.assertTrue(flat)
        self.assertAlmostEqual(flat[0]["technicity"]["coef"], 1.4, places=3)
        self.assertGreater(scaled["totals"]["time_s"]["realistic"], base["totals"]["time_s"]["realistic"])


if __name__ == "__main__":
    unittest.main()
