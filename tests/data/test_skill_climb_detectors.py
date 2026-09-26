"""Palier D — les skills `gpx-analysis` et `session-parts-analyzer` détectent leurs
montées avec le moteur (`scripts/arc_climb.py::detect_climbs`, #46), plus avec
leurs anciens détecteurs locaux.

Ce que verrouille ce fichier :
- parité : pour les mêmes échantillons, les bornes de montée des skills sont
  EXACTEMENT celles du moteur — c'est ce dont #49 (identité de montée entre
  séances, `arc_climb_match.py`) a besoin pour que les montées citées par le coach
  et celles du tableau de bord soient les mêmes ;
- comportements hérités du moteur que les anciens détecteurs n'avaient pas :
  rognage des approches plates, fusion d'un replat court, trou de signal jamais
  franchi (FIT) ;
- adaptation des entrées : points GPX (le `<time>` éventuel est ignoré) et records
  FIT (sous-échantillonnés à la résolution de l'index) ;
- format de sortie : clés historiques conservées, clés ajoutées documentées.

Coordonnées FICTIVES (Pacifique Sud, voir
`tests/lint/test_synthetic_no_real_data.py::SAFE_LAT_RANGE`/`SAFE_LON_RANGE`).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/gpx-analysis/scripts"))
sys.path.insert(0, str(REPO / "skills/session-parts-analyzer/scripts"))
sys.path.insert(0, str(REPO))

import analyze_gpx as G  # noqa: E402
import analyze_session_parts as SP  # noqa: E402
import arc_climb as VC  # noqa: E402
import arc_samples as AS  # noqa: E402
from tests.lib.synthetic import sample_session  # noqa: E402

BASE_LAT = -40.0
BASE_LON = -130.0
M_PER_DEG_LAT = 111_195.0  # rayon de `haversine` (6 371 km) — distance nord-sud exacte


def _profile(sections):
    """Altitude en fonction de la distance, pour des sections `(longueur_m, pente_%)`
    enchaînées depuis 0 m."""
    def alt_at(d):
        start, alt = 0.0, 100.0
        for length, grade in sections:
            if d <= start + length:
                return alt + (d - start) * grade / 100.0
            start += length
            alt += length * grade / 100.0
        return alt
    total = sum(length for length, _ in sections)
    return alt_at, total


def _gpx_points(sections, step_m=10.0):
    """Points GPX (plein nord, pas régulier) suivant `sections` — sans bruit : les
    bornes attendues restent déterministes."""
    alt_at, total = _profile(sections)
    pts, d = [], 0.0
    while d <= total:
        pts.append({"lat": BASE_LAT + d / M_PER_DEG_LAT, "lon": BASE_LON, "ele": alt_at(d)})
        d += step_m
    return pts


def _write_gpx(path: Path, pts, *, times=None):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>']
    for i, p in enumerate(pts):
        ele = f"<ele>{p['ele']:.2f}</ele>" if p["ele"] is not None else ""
        time = f"<time>{times[i]}</time>" if times else ""
        lines.append(f'<trkpt lat="{p["lat"]:.7f}" lon="{p["lon"]:.7f}">{ele}{time}</trkpt>')
    lines.append("</trkseg></trk></gpx>")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# gpx-analysis
# ---------------------------------------------------------------------------


class TestGpxUsesEngineDetector(unittest.TestCase):

    def test_bounds_match_engine_exactly(self):
        """Parité avec le moteur : mêmes bornes, gain et pente pour le même profil."""
        pts = _gpx_points([(1000, 0), (1000, 10), (1500, 0), (600, 12), (500, 0)])
        climbs = G.detect_climbs(pts)
        engine = VC.detect_climbs(G.gpx_samples(pts), min_gain_m=15.0, min_avg_grade=0.05)
        self.assertEqual(len(climbs), len(engine))
        for mine, ref in zip(climbs, engine):
            self.assertEqual(mine["start_km"], round(ref["start_km"], 2))
            self.assertEqual(mine["end_km"], round(ref["end_km"], 2))
            self.assertEqual(mine["gain_m"], ref["gain_m"])
            self.assertEqual(mine["distance_m"], ref["distance_m"])
            self.assertEqual(mine["grade_class"], ref["grade_class"])

    def test_flat_approach_is_trimmed(self):
        """1 km plat puis +100 m à 10 % : la montée démarre vers le km 1, jamais au
        départ (l'ancien détecteur par suivi de pic démarrait au premier point)."""
        pts = _gpx_points([(1000, 0), (1000, 10), (1000, 0)])
        climbs = G.detect_climbs(pts)
        self.assertEqual(len(climbs), 1)
        c = climbs[0]
        self.assertAlmostEqual(c["start_km"], 1.0, delta=0.05)
        self.assertAlmostEqual(c["end_km"], 2.0, delta=0.05)
        self.assertAlmostEqual(c["grade_pct"], 10.0, delta=0.5)
        self.assertGreater(c["gain_m"], 90.0)

    def test_short_flat_between_two_climbs_is_merged(self):
        """Un replat de 150 m (< `arc_climb.MERGE_MAX_DIP_DIST_M`) au milieu d'une
        montée ne la coupe pas en deux."""
        pts = _gpx_points([(500, 0), (800, 10), (150, 0), (800, 8), (500, 0)])
        climbs = G.detect_climbs(pts)
        self.assertEqual(len(climbs), 1)
        self.assertGreater(climbs[0]["gain_m"], 130.0)

    def test_long_plateau_splits_two_climbs(self):
        pts = _gpx_points([(500, 0), (800, 10), (1500, 0), (800, 8), (500, 0)])
        self.assertEqual(len(G.detect_climbs(pts)), 2)

    def test_flat_course_has_no_climb(self):
        self.assertEqual(G.detect_climbs(_gpx_points([(5000, 0)])), [])

    def test_skill_thresholds_apply(self):
        """`--min-gain`, `--min-grade`, `--min-climb-dist` restent des filtres du skill."""
        pts = _gpx_points([(500, 0), (300, 10), (500, 0)])  # ~+30 m sur ~300 m
        self.assertEqual(len(G.detect_climbs(pts)), 1)
        self.assertEqual(G.detect_climbs(pts, min_gain=50.0), [])
        self.assertEqual(G.detect_climbs(pts, min_dist=400.0), [])
        self.assertEqual(G.detect_climbs(pts, min_grade_pct=15.0), [])

    def test_output_keys_are_stable(self):
        climbs = G.detect_climbs(_gpx_points([(500, 0), (1000, 10), (500, 0)]))
        self.assertEqual(set(climbs[0]),
                         {"start_km", "end_km", "distance_m", "gain_m", "grade_pct", "grade_class"})

    def test_missing_elevation_points_are_tolerated(self):
        pts = _gpx_points([(500, 0), (1000, 10), (500, 0)])
        for p in pts[::7]:
            p["ele"] = None
        self.assertEqual(len(G.detect_climbs(pts)), 1)


class TestGpxCli(unittest.TestCase):

    def test_time_gap_in_recorded_track_never_splits_a_climb(self):
        """Un tracé enregistré avec une pause de 10 min en pleine montée : le skill
        analyse le TERRAIN, `<time>` est ignoré, la montée reste entière."""
        pts = _gpx_points([(500, 0), (1000, 10), (500, 0)])
        times, t = [], 0
        for i in range(len(pts)):
            t += 600 if i == len(pts) // 2 else 5
            times.append(f"2026-01-01T{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}Z")
        with tempfile.TemporaryDirectory() as tmp:
            gpx, out = Path(tmp) / "trace.gpx", Path(tmp) / "out.json"
            _write_gpx(gpx, pts, times=times)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(G.main(["--gpx", str(gpx), "--json", str(out), "--quiet"]), 0)
            dump = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(dump["climbs"]), 1)
        self.assertAlmostEqual(dump["climbs"][0]["start_km"], 0.5, delta=0.05)

    def test_markdown_table_format_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            gpx = Path(tmp) / "trace.gpx"
            _write_gpx(gpx, _gpx_points([(500, 0), (1000, 10), (500, 0)]))
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(G.main(["--gpx", str(gpx)]), 0)
        md = buf.getvalue()
        self.assertIn("## Montées significatives (1)", md)
        self.assertIn("| Début (km) | Fin (km) | Distance (m) | Gain (m) | Grade moyen |", md)


# ---------------------------------------------------------------------------
# session-parts-analyzer
# ---------------------------------------------------------------------------


SEGMENTS = ((800, 1000, 10), (1950, 120, -2), (2070, 800, 8), (4500, 300, 12))


def _records_from_samples(samples):
    return [SP.Record(t=s["t_s"], distance_m=s["distance_m"],
                      speed_kmh=(s["speed_ms"] or 0.0) * 3.6,
                      hr=int(s["hr_bpm"]) if s.get("hr_bpm") is not None else None,
                      elevation_m=s["altitude_m"], grade_pct=None,
                      cadence=int(s["cadence_spm"]) if s.get("cadence_spm") is not None else None)
            for s in samples]


class TestSessionPartsUsesEngineDetector(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.samples, _ = sample_session(seed=5, duration_s=3600, segments=SEGMENTS)
        cls.records = _records_from_samples(cls.samples)
        cls.cfg = dict(SP.DEFAULTS)
        cls.climbs = SP.detect_climbs(cls.records, cls.cfg)

    def test_bounds_match_the_index_path(self):
        """Mêmes bornes que l'index (`arc_samples.downsample` 5 s puis
        `arc_climb.detect_climbs`) — condition de cohérence avec #46/#49."""
        indexed = VC.detect_climbs(AS.downsample(AS.normalise_records(self.samples)),
                                   min_gain_m=self.cfg["climb_min_ascent_m"],
                                   min_avg_grade=self.cfg["climb_grade_min_pct"] / 100.0)
        indexed = [c for c in indexed if c["distance_m"] >= self.cfg["climb_min_distance_m"]]
        self.assertEqual([(s.start_t, s.end_t, s.elevation_gain_m) for s in self.climbs],
                         [(c["start_t_s"], c["end_t_s"], c["gain_m"]) for c in indexed])

    def test_every_requested_climb_is_found(self):
        self.assertEqual(len(self.climbs), 3)
        self.assertEqual([s.grade_class for s in self.climbs], ["10-15%", "5-10%", "10-15%"])

    def test_indexed_climbs_keep_identical_bounds_with_lower_thresholds(self):
        """Les seuils du skill (15 m / 4 %) sont plus bas que ceux de l'index
        (50 m / 5 %) : toute montée retenue par l'index l'est aussi par le skill,
        avec les MÊMES bornes (le filtre du moteur ne s'applique qu'en dernier)."""
        indexed = VC.detect_climbs(AS.downsample(AS.normalise_records(self.samples)))
        mine = {(s.start_t, s.end_t) for s in self.climbs}
        self.assertTrue(indexed)
        for c in indexed:
            self.assertIn((c["start_t_s"], c["end_t_s"]), mine)

    def test_vam_and_execution_metrics(self):
        for s in self.climbs:
            self.assertEqual(s.kind, "climb")
            self.assertIsNotNone(s.vam_elapsed_m_h)
            self.assertGreater(s.vam_elapsed_m_h, 0)
            self.assertIsNotNone(s.avg_hr_bpm)
            self.assertIsNotNone(s.cadence_avg)
            self.assertGreater(s.avg_grade_pct, self.cfg["climb_grade_min_pct"])
        self.assertIsNone(self.climbs[0].recovery_before_s)
        self.assertGreater(self.climbs[1].recovery_before_s, 0)

    def test_signal_gap_is_never_bridged(self):
        """Un trou de 2 min en pleine montée (montre en veille) : aucune montée ne
        l'enjambe (l'ancien détecteur par pente instantanée l'ignorait)."""
        samples, _ = sample_session(seed=5, duration_s=3600, segments=((800, 1000, 10),),
                                    dropout_windows=((500, 620),))
        climbs = SP.detect_climbs(_records_from_samples(samples), dict(SP.DEFAULTS))
        self.assertEqual(len(climbs), 2)  # une montée de chaque côté du trou
        for s in climbs:
            self.assertFalse(s.start_t < 500 and s.end_t > 620, (s.start_t, s.end_t))

    def test_markdown_and_json_outputs(self):
        md = SP.render_markdown("climb", self.climbs, {"part": "climb"})
        self.assertIn("### Montées — pente et VAM", md)
        self.assertIn("| # | Plage (s) |", md)  # tableau principal inchangé
        payload = json.loads(SP.render_json(self.climbs, {"part": "climb"}))
        seg = payload["segments"][0]
        for key in ("vam_elapsed_m_h", "vam_moving_m_h", "grade_class", "elevation_gain_m", "avg_grade_pct"):
            self.assertIn(key, seg)

    def test_other_parts_get_null_climb_fields(self):
        strides = SP.detect_strides(self.records, dict(SP.DEFAULTS))
        md = SP.render_markdown("stride", strides, {})
        self.assertNotIn("Montées — pente et VAM", md)
        for s in strides:
            self.assertIsNone(s.vam_elapsed_m_h)
            self.assertIsNone(s.grade_class)

    def test_no_elevation_means_no_climb(self):
        """Mode `--activity-id` (splits 1 km, sans altitude) : liste vide, jamais d'exception."""
        records = [SP.Record(t=float(i), distance_m=i * 3.0, speed_kmh=10.8, hr=140,
                             elevation_m=None, grade_pct=None, cadence=None) for i in range(600)]
        self.assertEqual(SP.detect_climbs(records, dict(SP.DEFAULTS)), [])


if __name__ == "__main__":
    unittest.main()
