"""Palier D — le profil par km d'`analyze_gpx.compute_metrics` somme les MÊMES
contributions que le D+/D- total (seuil anti-bruit `min_step_m` compris).

Avant correction, le total appliquait le seuil de 1 m par pas mais le profil par km
sommait les écarts bruts : sans `--dem`, sur une trace bruitée, la somme des D+ par km
dépassait largement le D+ annoncé du rapport.

Ce que verrouille ce fichier :
- somme du profil par km == totaux (à l'arrondi au dixième près par km), sur des
  traces synthétiques bruitées, à altitudes décimales ET entières ;
- sémantique du seuil : comparaison STRICTE, un pas d'exactement 1,0 m est ignoré,
  au total comme dans le profil (`arc_elevation.step_gain_loss`) ;
- parité avec `arc_elevation.gain_loss` (donc avec le « D+ fichier » de `arc_dem`) ;
- série MNT (`min_step_m=0`) inchangée ; altitudes manquantes tolérées ;
- même égalité dans le dump JSON du CLI.

Coordonnées FICTIVES (Pacifique Sud, voir
`tests/lint/test_synthetic_no_real_data.py::SAFE_LAT_RANGE`/`SAFE_LON_RANGE`).
"""

from __future__ import annotations

import io
import json
import math
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/gpx-analysis/scripts"))

import analyze_gpx as G  # noqa: E402
import arc_elevation as EL  # noqa: E402

BASE_LAT = -40.0
BASE_LON = -130.0
M_PER_DEG_LAT = 111_195.0  # rayon de `haversine` (6 371 km) — distance nord-sud exacte


def noisy_track(n=2000, step_m=10.0, noise_m=1.0, integer=False, seed=7):
    """Trace nord-sud de `n` points : relief sinusoïdal + bruit gaussien (GPS)."""
    rnd = random.Random(seed)
    pts = []
    for i in range(n):
        ele = 300.0 + 80.0 * math.sin(i / 120.0) + 25.0 * math.sin(i / 17.0) + rnd.gauss(0.0, noise_m)
        pts.append({"lat": BASE_LAT + i * step_m / M_PER_DEG_LAT, "lon": BASE_LON,
                    "ele": float(round(ele)) if integer else round(ele, 1)})
    return pts


def raw_positive_sum(pts, smooth=3):
    """Somme des écarts positifs SANS seuil — ce que l'ancien profil par km additionnait."""
    ele = EL.smooth_moving_average([p["ele"] for p in pts], smooth)
    return sum(b - a for a, b in zip(ele, ele[1:]) if a is not None and b is not None and b > a)


class KmProfileMatchesTotals(unittest.TestCase):
    def assert_profile_matches(self, m):
        prof = m["km_profile"]
        tol = 0.05 * len(prof) + 0.05  # chaque km est arrondi au dixième
        self.assertAlmostEqual(sum(k["dp"] for k in prof), m["elevation_gain_m"], delta=tol)
        self.assertAlmostEqual(sum(k["dm"] for k in prof), m["elevation_loss_m"], delta=tol)

    def test_noisy_tracks_default_threshold(self):
        for integer in (False, True):
            for noise in (0.3, 1.0, 3.0):
                for seed in (1, 7, 42):
                    with self.subTest(integer=integer, noise=noise, seed=seed):
                        m = G.compute_metrics(noisy_track(noise_m=noise, integer=integer, seed=seed))
                        self.assert_profile_matches(m)

    def test_fixture_discriminates_old_behaviour(self):
        """La trace est assez bruitée pour que l'ancien profil (écarts bruts) dépasse le
        total de plus de 50 m : le test ci-dessus échouerait sans la correction."""
        pts = noisy_track(noise_m=1.0)
        m = G.compute_metrics(pts)
        self.assertGreater(raw_positive_sum(pts), m["elevation_gain_m"] + 50.0)
        self.assert_profile_matches(m)

    def test_step_of_exactly_threshold_is_ignored_everywhere(self):
        pts = [{"lat": BASE_LAT + i * 10.0 / M_PER_DEG_LAT, "lon": BASE_LON, "ele": 100.0 + i}
               for i in range(300)]  # 3 km, +1,0 m par pas exactement
        m = G.compute_metrics(pts, smooth=1)
        self.assertEqual(m["elevation_gain_m"], 0.0)
        self.assertTrue(all(k["dp"] == 0.0 and k["dm"] == 0.0 for k in m["km_profile"]))

    def test_step_above_threshold_is_counted_everywhere(self):
        pts = [{"lat": BASE_LAT + i * 10.0 / M_PER_DEG_LAT, "lon": BASE_LON, "ele": 100.0 + 1.5 * i}
               for i in range(300)]
        m = G.compute_metrics(pts, smooth=1)
        self.assertAlmostEqual(m["elevation_gain_m"], 1.5 * 299, delta=0.05)
        self.assert_profile_matches(m)
        self.assertTrue(all(k["dm"] == 0.0 for k in m["km_profile"]))

    def test_step_gain_loss_rule(self):
        self.assertEqual(EL.step_gain_loss(1.0, 1.0), (0.0, 0.0))
        self.assertEqual(EL.step_gain_loss(-1.0, 1.0), (0.0, 0.0))
        self.assertEqual(EL.step_gain_loss(1.2, 1.0), (1.2, 0.0))
        self.assertEqual(EL.step_gain_loss(-1.2, 1.0), (0.0, 1.2))
        self.assertEqual(EL.step_gain_loss(0.0, 0.0), (0.0, 0.0))
        self.assertEqual(EL.step_gain_loss(0.3, 0.0), (0.3, 0.0))

    def test_totals_match_shared_gain_loss(self):
        """Le D+ du rapport reste celui d'`arc_elevation.gain_loss` — c'est le « D+ fichier »
        affiché par `arc_dem.compare_gain_loss` : la correction ne change pas les totaux."""
        for integer in (False, True):
            pts = noisy_track(noise_m=1.0, integer=integer)
            m = G.compute_metrics(pts)
            gain, loss = EL.gain_loss([p["ele"] for p in pts], smooth_taps=3, min_step_m=1.0)
            self.assertEqual((m["elevation_gain_m"], m["elevation_loss_m"]), (round(gain, 1), round(loss, 1)))

    def test_dem_series_without_threshold(self):
        m = G.compute_metrics(noisy_track(noise_m=1.0), smooth=1, min_step_m=0.0)
        self.assert_profile_matches(m)

    def test_missing_elevations_are_skipped(self):
        pts = noisy_track(noise_m=1.0)
        for i in range(0, len(pts), 37):
            pts[i]["ele"] = None
        for smooth in (1, 3):
            with self.subTest(smooth=smooth):
                self.assert_profile_matches(G.compute_metrics(pts, smooth=smooth))

    def test_cli_json_dump(self):
        pts = noisy_track(noise_m=1.0)
        body = "".join(f'<trkpt lat="{p["lat"]}" lon="{p["lon"]}"><ele>{p["ele"]}</ele></trkpt>' for p in pts)
        with tempfile.TemporaryDirectory() as tmp:
            gpx = Path(tmp) / "bruit.gpx"
            gpx.write_text(f'<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}'
                           "</trkseg></trk></gpx>", encoding="utf-8")
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            js = Path(tmp) / "o.json"
            with redirect_stdout(io.StringIO()):
                rc = G.main(["--gpx", str(gpx), "--workspace", str(ws), "--no-dem", "--json", str(js), "--quiet"])
            self.assertEqual(rc, 0)
            dump = json.loads(js.read_text(encoding="utf-8"))
            self.assert_profile_matches({**dump["metrics"], "km_profile": dump["km_profile"]})


if __name__ == "__main__":
    unittest.main()
