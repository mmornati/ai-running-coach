"""Palier D — auto-test du générateur d'échantillons synthétiques (story #25).

`tests.lib.synthetic.sample_session` fabrique des séries seconde par seconde à
vérité connue : chaque propriété demandée (montée, dérive FC, zones, fade,
trous de signal) doit se retrouver, mesurée, dans le dict `truth` qu'il
renvoie. Ces tests sont le seul garde-fou de ce générateur — toute l'épopée
FIT (#42 à #48, #58) va s'appuyer dessus sans revérifier ses fondations.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.lib.synthetic import build, sample_session  # noqa: E402


class TestClimb(unittest.TestCase):
    def test_8_percent_climb_over_1km_gives_about_80m(self):
        """Une montée à 8 % sur 1 km ≈ 80 m de D+ (critère d'acceptation de #25)."""
        _, truth = sample_session(
            seed=1, duration_s=3000, base_speed_ms=2.0,
            climb_start_m=0, climb_length_m=1000, climb_grade_pct=8, noise=False,
        )
        self.assertAlmostEqual(truth["elevation_gain_m"], 80.0, delta=2.0)
        self.assertEqual(truth["climb_requested_gain_m"], 80.0)

    def test_flat_course_has_no_gain(self):
        _, truth = sample_session(seed=1, duration_s=600, climb_start_m=None, noise=False)
        self.assertEqual(truth["elevation_gain_m"], 0.0)
        self.assertIsNone(truth["climb_requested_gain_m"])

    def test_climb_must_be_fully_traversed_to_reach_requested_gain(self):
        """Une séance trop courte pour parcourir toute la montée ne produit pas le D+ complet."""
        _, truth = sample_session(
            seed=1, duration_s=60, base_speed_ms=1.0,
            climb_start_m=0, climb_length_m=1000, climb_grade_pct=8, noise=False,
        )
        self.assertLess(truth["elevation_gain_m"], truth["climb_requested_gain_m"])


class TestDecoupling(unittest.TestCase):
    def test_requested_drift_appears_in_raw_data(self):
        """La dérive FC demandée (découplage, story #45) se retrouve mesurée à ±0,5 point."""
        _, truth = sample_session(seed=2, duration_s=3600, decoupling_pct=4.0, noise=True)
        self.assertAlmostEqual(truth["decoupling_pct_measured"], 4.0, delta=0.5)

    def test_zero_drift_is_flat(self):
        _, truth = sample_session(seed=2, duration_s=3600, decoupling_pct=0.0, noise=True)
        self.assertAlmostEqual(truth["decoupling_pct_measured"], 0.0, delta=0.5)


class TestZoneDistribution(unittest.TestCase):
    def test_imposed_zone_shares_are_respected(self):
        shares = {1: 0.6, 2: 0.2, 3: 0.1, 4: 0.05, 5: 0.05}
        _, truth = sample_session(seed=3, duration_s=2000, zone_shares=shares, noise=False)
        self.assertEqual(sum(truth["zone_seconds_requested"].values()), 2000)
        for zone, share in shares.items():
            self.assertEqual(truth["zone_seconds_requested"][zone], round(2000 * share))
        # Sans bruit, la FC générée retombe exactement dans la zone visée.
        self.assertEqual(truth["zone_seconds_from_hr"], truth["zone_seconds_requested"])

    def test_zone_shares_take_precedence_over_decoupling(self):
        _, truth = sample_session(
            seed=3, duration_s=1000, zone_shares={1: 1.0}, decoupling_pct=10.0, noise=False,
        )
        self.assertIsNone(truth["decoupling_pct_requested"])


class TestFade(unittest.TestCase):
    def test_last_third_fade_is_measured(self):
        """Fade de fin de séance (durabilité, story #48) mesuré sur le dernier tiers."""
        _, truth = sample_session(seed=4, duration_s=3600, fade_pct=8.0, noise=False)
        self.assertAlmostEqual(truth["fade_pct_measured"], 8.0, delta=0.1)

    def test_no_fade_by_default(self):
        _, truth = sample_session(seed=4, duration_s=3600, noise=False)
        self.assertEqual(truth["fade_pct_measured"], 0.0)


class TestDropouts(unittest.TestCase):
    def test_dropout_windows_remove_samples(self):
        recs, truth = sample_session(seed=5, duration_s=200, dropout_windows=((50, 60), (100, 120)))
        self.assertEqual(truth["dropout_seconds"], 30)
        self.assertEqual(len(recs), 200 - 30)
        missing = {t for t in range(50, 60)} | {t for t in range(100, 120)}
        present = {r["t_s"] for r in recs}
        self.assertFalse(missing & present, "les secondes en trou de signal ne doivent pas apparaître")

    def test_no_dropout_by_default(self):
        recs, truth = sample_session(seed=5, duration_s=120)
        self.assertEqual(truth["dropout_seconds"], 0)
        self.assertEqual(len(recs), 120)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_is_byte_for_byte_identical(self):
        params = dict(seed=42, duration_s=900, climb_start_m=200, climb_length_m=400,
                      climb_grade_pct=6, decoupling_pct=3, fade_pct=5,
                      dropout_windows=((10, 15),))
        r1, t1 = sample_session(**params)
        r2, t2 = sample_session(**params)
        self.assertEqual(r1, r2)
        self.assertEqual(t1, t2)

    def test_different_seed_changes_noise(self):
        r1, _ = sample_session(seed=1, duration_s=200)
        r2, _ = sample_session(seed=2, duration_s=200)
        self.assertNotEqual(r1, r2)


class TestSampleFormat(unittest.TestCase):
    """Le format doit correspondre au schéma `activity_sample` de `scripts/arc_index.py`."""

    def test_record_keys_match_activity_sample_schema(self):
        recs, _ = sample_session(seed=1, duration_s=5)
        expected_keys = {"t_s", "distance_m", "altitude_m", "hr_bpm", "speed_ms", "cadence_spm"}
        for record in recs:
            self.assertEqual(set(record.keys()), expected_keys)

    def test_no_gps_coordinates(self):
        """Aucune coordonnée GPS générée — inutile aux KPI, ça évite tout risque de lieu réel."""
        recs, _ = sample_session(seed=1, duration_s=5)
        for record in recs:
            self.assertNotIn("lat", record)
            self.assertNotIn("lon", record)


class TestWithSamplesCLI(unittest.TestCase):
    """`--with-samples` (ici via `build(..., with_samples=True)`, sans sous-processus)."""

    def test_build_with_samples_writes_fit_json_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = build(Path(tmp), days=10, today=None, sport="trail", seed=1, with_samples=True)
            fit_dir = root / "activities/fit"
            self.assertTrue(fit_dir.is_dir())
            files = list(fit_dir.glob("*.json"))
            self.assertGreater(len(files), 0)
            import json
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertIn("activity_id", payload)
            self.assertIn("records", payload)
            self.assertIn("truth", payload)
            self.assertGreaterEqual(payload["activity_id"], 20_000_000_000)


if __name__ == "__main__":
    unittest.main()
