"""Palier D — splits par km calculés depuis les échantillons FIT (`arc_splits.py`).

Séances construites à la main, à vérité connue (vitesse constante, pause,
montée) : bornes interpolées, temps écoulé, split partiel, colonnes vides
retirées, et sortie acceptée telle quelle par le contrat (`arc_contract`).
Plus la CLI `arc_index.py splits <id>` sur un FIT ingéré sans Markdown.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_contract as C  # noqa: E402
import arc_index as I  # noqa: E402
import arc_splits as SP  # noqa: E402


def steady(distance_m: float, speed_ms: float = 2.5, step_s: float = 5.0, *, hr=True,
           altitude=None, pause=None) -> list:
    """Échantillons tous les `step_s` à vitesse constante. `altitude(d)` donne
    l'altitude à la distance d ; `pause=(start_m, seconds)` arrête l'athlète."""
    out, t, d = [], 0.0, 0.0
    paused = False
    while d < distance_m:
        rec = {"t_s": t, "distance_m": d, "speed_ms": speed_ms, "cadence_spm": 170.0}
        if hr:
            rec["hr_bpm"] = 150.0
        if altitude is not None:
            rec["altitude_m"] = altitude(d)
        out.append(rec)
        if pause and not paused and d >= pause[0]:
            for k in range(1, int(pause[1] // step_s) + 1):
                out.append({**rec, "t_s": t + k * step_s, "speed_ms": 0.0})
            t += pause[1]
            paused = True
        t += step_s
        d = min(distance_m, d + speed_ms * step_s)
    out.append({**out[-1], "t_s": t, "distance_m": distance_m})
    return out


def as_dicts(result: dict) -> list:
    return [dict(zip(result["splits_cols"], row)) for row in result["splits"]]


class KmSplitsTest(unittest.TestCase):
    def test_constant_pace_full_and_partial(self):
        result = SP.km_splits(steady(2600))
        rows = as_dicts(result)
        self.assertIsNone(result["reason"])
        self.assertEqual([r["km"] for r in rows], [1, 2, 3])
        self.assertEqual([r["duration_s"] for r in rows], [400, 400, 240])
        self.assertEqual([r["distance_m"] for r in rows], [1000, 1000, 600])
        self.assertEqual(rows[0]["avg_hr_bpm"], 150)
        self.assertEqual(rows[0]["max_speed_kmh"], 9.0)
        self.assertEqual(rows[0]["cadence_spm"], 170)

    def test_whole_km_has_no_distance_column(self):
        result = SP.km_splits(steady(3000))
        self.assertNotIn("distance_m", result["splits_cols"])
        self.assertEqual(len(result["splits"]), 3)

    def test_short_remainder_is_dropped(self):
        rows = as_dicts(SP.km_splits(steady(2050)))
        self.assertEqual([r["km"] for r in rows], [1, 2])

    def test_boundary_is_interpolated_between_samples(self):
        # 3 m/s, échantillons toutes les 5 s : 1 000 m tombe entre deux échantillons (990 et 1 005 m).
        rows = as_dicts(SP.km_splits(steady(2000, speed_ms=3.0)))
        self.assertEqual(rows[0]["duration_s"], 333)

    def test_pause_counts_in_elapsed_time(self):
        rows = as_dicts(SP.km_splits(steady(3000, pause=(1500, 120))))
        self.assertEqual([r["duration_s"] for r in rows], [400, 520, 400])
        self.assertEqual(sum(r["duration_s"] for r in rows), 1320)
        # Les échantillons à l'arrêt ne comptent pas dans la cadence.
        self.assertEqual(rows[1]["cadence_spm"], 170)

    def test_climb_is_attributed_to_its_km(self):
        def altitude(d):
            return 100.0 + min(d, 1000.0) * 0.05
        rows = as_dicts(SP.km_splits(steady(2000, altitude=altitude)))
        self.assertAlmostEqual(rows[0]["elev_gain_m"], 50, delta=2)
        self.assertLessEqual(rows[1]["elev_gain_m"], 1)

    def test_empty_columns_are_removed(self):
        result = SP.km_splits(steady(2000, hr=False))
        self.assertNotIn("avg_hr_bpm", result["splits_cols"])
        self.assertNotIn("max_hr_bpm", result["splits_cols"])
        self.assertNotIn("elev_gain_m", result["splits_cols"])

    def test_distance_glitch_never_goes_backwards(self):
        samples = steady(2000)
        samples[50]["distance_m"] -= 200
        rows = as_dicts(SP.km_splits(samples))
        self.assertEqual([r["km"] for r in rows], [1, 2])
        self.assertTrue(all(r["duration_s"] > 0 for r in rows))

    def test_no_usable_samples(self):
        self.assertIsNone(SP.km_splits([])["splits"])
        self.assertIn("aucun échantillon", SP.km_splits([{"t_s": 0}])["reason"])
        self.assertIn("trop courte", SP.km_splits(steady(60))["reason"])

    def test_output_passes_the_contract(self):
        result = SP.km_splits(steady(2600, altitude=lambda d: 100 + d / 100))
        data = {"arc": 1, "kind": "activity", "date": "2026-10-22", "sport": "running",
                "distance_m": 2600, "duration_s": 1040,
                "splits_cols": result["splits_cols"], "splits": result["splits"]}
        errors, _ = C.validate(data)
        self.assertEqual(errors, [])


class SplitsCliTest(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        (self.ws / "activities" / "fit").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_cli_on_ingested_fit_without_markdown(self):
        (self.ws / "activities" / "fit" / "i123.json").write_text(
            json.dumps({"activity_id": "i123", "records": steady(2600)}), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["splits", "i123", "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out.getvalue())["splits"]), 3)

    def test_cli_without_samples(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["splits", "i999", "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 1)
        self.assertIn("fit-download", json.loads(out.getvalue())["reason"])


if __name__ == "__main__":
    unittest.main()
