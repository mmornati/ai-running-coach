"""Palier D — puissance home trainer : `power_w` dans les échantillons FIT
(`arc_samples`), clés de contrat (`avg_power_w`…, `session.virtual_route`), section
« ### Vélo & home trainer » du profil (`arc_legacy.parse_profile`), calibration
puissance ↔ FC (`arc_power`) et commande `arc_index.py power-hr` sur un workspace
synthétique. Données synthétiques uniquement."""

from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_index as I  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_power as PW  # noqa: E402
import arc_samples as S  # noqa: E402

TEMPLATE = (REPO / "templates" / "Runner_Profile.template.md").read_text(encoding="utf-8")


def _profile(**fill) -> str:
    text = TEMPLATE
    for label, value in fill.items():
        text = text.replace(f"- **{label}** :", f"- **{label}** : {value}", 1)
    return text


def _ride_samples(minutes: int = 60, step: int = 5, seed: int = 1) -> list:
    """Séance synthétique : FC qui monte de 100 à 145 bpm, puissance = 2·FC − 90 W
    (60 s plus tôt), bruit léger. Échantillons normalisés au pas de `step` s."""
    rng = random.Random(seed)
    n = minutes * 60 // step
    hr = [100 + 45 * i / n for i in range(n)]
    out = []
    for i in range(n):
        later = hr[min(i + PW.HR_LAG_S // step, n - 1)]
        out.append({"t_s": float(i * step), "hr_bpm": hr[i], "power_w": 2.0 * later - 90 + rng.uniform(-3, 3)})
    return out


class TestSamplesPower(unittest.TestCase):
    def test_fitparse_power_kept_zero_kept_spike_dropped(self):
        raw = [{"timestamp": f"2026-10-01 10:00:0{i}", "heart_rate": 120, "power": p, "cadence": 85}
               for i, p in enumerate([150, 0, 9999])]
        recs = S.normalise_records(raw, sport="cycling")
        self.assertEqual([r["power_w"] for r in recs], [150.0, 0.0, None])
        self.assertEqual(recs[0]["cadence_spm"], 85.0)   # vélo : pas de doublement

    def test_no_sensor_is_none_and_downsample_averages(self):
        recs = S.normalise_records([{"timestamp": "2026-10-01 10:00:00", "heart_rate": 120}], sport="running")
        self.assertIsNone(recs[0]["power_w"])
        buckets = S.downsample([{"t_s": 0.0, "power_w": 100.0}, {"t_s": 1.0, "power_w": 200.0},
                                {"t_s": 2.0, "power_w": None}], 5)
        self.assertEqual(buckets[0]["power_w"], 150.0)

    def test_normalised_path_round_trips_power(self):
        recs = S.normalise_records({"records": [{"t_s": 0, "power_w": 180}]})
        self.assertEqual(recs[0]["power_w"], 180.0)


class TestContract(unittest.TestCase):
    def test_activity_power_keys(self):
        ok = {"arc": 1, "kind": "activity", "date": "2026-10-10", "sport": "home_trainer", "duration_s": 600,
              "avg_power_w": 150, "max_power_w": 300, "normalized_power_w": 160}
        self.assertEqual(C.validate(ok)[0], [])
        self.assertTrue(C.validate({**ok, "avg_power_w": -1})[0])

    def test_session_virtual_route(self):
        week = {"arc": 1, "kind": "week", "week_start": "2026-10-05", "location": "Lille", "sessions": [
            {"date": "2026-10-10", "sport": "home_trainer", "title": "HT Z2",
             "virtual_route": {"platform": "mywhoosh", "route_id": 120, "name": "Limmat Loop", "laps": 2,
                               "predicted_s": 4100, "target_power_w": 155}}]}
        self.assertEqual(C.validate(week)[0], [])
        week["sessions"][0]["virtual_route"]["platform"] = "zwift"
        self.assertTrue(C.validate(week)[0])
        del week["sessions"][0]["virtual_route"]["route_id"]
        self.assertTrue(C.validate(week)[0])


class TestProfile(unittest.TestCase):
    def test_empty_template_declares_nothing(self):
        out = L.parse_profile(TEMPLATE)
        for key in ("ht_trainer", "ht_bike", "bike_mass_kg", "ftp_declared_w"):
            self.assertNotIn(key, out)

    def test_bike_section_parsed_without_touching_athlete_weight(self):
        out = L.parse_profile(_profile(**{"Home trainer": "Wahoo KICKR", "Vélo sur home trainer": "Route alu",
                                          "Masse du vélo": "8,5 kg", "FTP déclarée": "230 W (test 2026-10-01)"}))
        self.assertEqual(out["ht_trainer"], "Wahoo KICKR")
        self.assertEqual(out["ht_bike"], "Route alu")
        self.assertEqual(out["bike_mass_kg"], 8.5)
        self.assertEqual(out["ftp_declared_w"], 230.0)
        self.assertNotIn("weight_kg", out)   # « Masse du vélo » n'est jamais lu comme poids de l'athlète

    def test_implausible_values_dropped(self):
        out = L.parse_profile(_profile(**{"Masse du vélo": "80 kg", "FTP déclarée": "2000 W"}))
        self.assertNotIn("bike_mass_kg", out)
        self.assertNotIn("ftp_declared_w", out)


class TestCalibration(unittest.TestCase):
    def test_recovers_relation_and_zone_power(self):
        sessions = [{"ref": str(i), "date": "2026-10-0%d" % i, "sport": "home_trainer",
                     "samples": _ride_samples(seed=i)} for i in (1, 2)]
        rep = PW.calibrate(sessions, bounds_bpm=[100, 115, 130, 145, 160, 175])
        self.assertEqual(rep["status"], "ok")
        self.assertAlmostEqual(rep["fit"]["slope_w_per_bpm"], 2.0, delta=0.15)
        z2 = next(z for z in rep["zones"] if z["zone"] == 2)
        self.assertEqual(z2["bounds_bpm"], [115, 130])
        self.assertAlmostEqual(z2["power_w"][0], 140, delta=10)
        self.assertFalse(z2["extrapolated"])
        self.assertTrue(next(z for z in rep["zones"] if z["zone"] == 5)["extrapolated"])

    def test_refusals_are_explicit(self):
        no_power = PW.calibrate([{"ref": "1", "samples": [{"t_s": 0.0, "hr_bpm": 120}]}])
        self.assertEqual(no_power["status"], "no_power_samples")
        self.assertIsNone(no_power["fit"])
        short = PW.calibrate([{"ref": "1", "samples": _ride_samples(minutes=15)}])
        self.assertEqual(short["status"], "insufficient_data")
        self.assertIn("fenêtre", short["reason"])

    def test_unsteady_power_windows_rejected(self):
        samples = _ride_samples()
        for i, s in enumerate(samples):
            s["power_w"] = 400.0 if (i // 6) % 2 else 50.0   # intervalles de 30 s
        self.assertEqual(PW.windows(samples), [])


class TestPowerHrCommand(unittest.TestCase):
    def test_power_hr_on_indexed_workspace(self):
        today = date(2026, 10, 10)
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "activities" / "fit").mkdir(parents=True)
            (ws / "planning").mkdir()
            (ws / "config").mkdir()
            (ws / "config" / "workspace.user.toml").write_text('[home_trainer]\nplatform = "mywhoosh"\n')
            (ws / "planning" / "Runner_Profile.md").write_text(_profile(**{
                "FC max": "180", "FC de repos de référence": "45", "Poids de forme": "70 kg",
                "Home trainer": "Home trainer connecté", "Masse du vélo": "9 kg"}), encoding="utf-8")
            for i in range(3):
                day = (today - timedelta(days=2 + i)).isoformat()
                aid = 9_000_000_000 + i
                arc = {"arc": 1, "kind": "activity", "date": day, "sport": "home_trainer",
                       "garmin_activity_id": aid, "duration_s": 3600, "avg_hr_bpm": 122, "avg_power_w": 150}
                (ws / "activities" / f"{day}_home_trainer.md").write_text(
                    f"# HT\n\n```arc\n{json.dumps(arc)}\n```\n", encoding="utf-8")
                (ws / "activities" / "fit" / f"{aid}.json").write_text(
                    json.dumps({"activity_id": aid, "records": _ride_samples(seed=i, step=1)}), encoding="utf-8")
            conn = I.open_db(ws, memory=True)
            I.index_workspace(conn, ws)
            rep = I.power_hr(conn, I.settings(I.load_config(ws)), today)
            self.assertEqual(rep["status"], "ok", rep.get("reason"))
            self.assertEqual(rep["platform"], "mywhoosh")
            self.assertEqual(rep["equipment"], {"ht_trainer": "Home trainer connecté", "bike_mass_kg": 9.0})
            self.assertEqual(rep["weight_kg"], 70.0)
            self.assertEqual(len(rep["recent"]), 3)
            self.assertEqual([z["zone"] for z in rep["zones"]], [1, 2, 3, 4, 5])
            self.assertIn("P ≈", I.power_hr_text(rep))

    def test_platform_normalisation(self):
        self.assertEqual(I.home_trainer_platform({}), "off")
        self.assertEqual(I.home_trainer_platform({"home_trainer": {"platform": "MyWhoosh"}}), "mywhoosh")
        self.assertEqual(I.home_trainer_platform({"home_trainer": {"platform": "zwift"}}), "off")


if __name__ == "__main__":
    unittest.main()
