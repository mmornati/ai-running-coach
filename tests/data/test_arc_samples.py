"""Palier D — `scripts/arc_samples.py` : normalisation et sous-échantillonnage des
échantillons FIT (#42). Fonctions pures, aucun SQLite ici (voir `test_arc_index.py`
pour l'ingestion en base)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_samples as S  # noqa: E402
from tests.lib.synthetic import sample_session  # noqa: E402


class TestNormaliseFitparseFormat(unittest.TestCase):
    """Fixture à la main, façon `download_fit.py::_write_records_json` (valeurs fictives)."""

    RAW = [
        {"timestamp": "2026-01-01 08:00:00", "distance": 0.0, "heart_rate": 120,
         "enhanced_altitude": 100.0, "altitude": 99.8, "enhanced_speed": 2.5, "speed": 2.4,
         "cadence": 85, "fractional_cadence": 0.5},
        {"timestamp": "2026-01-01 08:00:05", "distance": 12.6, "heart_rate": 122,
         "enhanced_altitude": 101.0, "altitude": 100.8, "enhanced_speed": 2.6, "speed": 2.5,
         "cadence": 86},
        {"timestamp": "2026-01-01 08:00:10.500000", "distance": 25.7, "heart_rate": 125,
         "altitude": 102.0, "speed": 2.7, "cadence": None},
    ]

    def test_t_s_relative_to_first_timestamp(self):
        out = S.normalise_records(self.RAW)
        self.assertEqual([r["t_s"] for r in out], [0.0, 5.0, 10.5])

    def test_enhanced_fields_preferred_over_plain(self):
        out = S.normalise_records(self.RAW)
        self.assertEqual(out[0]["altitude_m"], 100.0)   # enhanced_altitude, pas altitude (99.8)
        self.assertEqual(out[0]["speed_ms"], 2.5)        # enhanced_speed, pas speed (2.4)

    def test_plain_field_used_when_enhanced_absent(self):
        out = S.normalise_records(self.RAW)
        self.assertEqual(out[2]["altitude_m"], 102.0)    # pas d'enhanced_altitude sur ce record
        self.assertEqual(out[2]["speed_ms"], 2.7)

    def test_heart_rate_and_distance_mapped_verbatim(self):
        out = S.normalise_records(self.RAW)
        self.assertEqual([r["hr_bpm"] for r in out], [120.0, 122.0, 125.0])
        self.assertEqual([r["distance_m"] for r in out], [0.0, 12.6, 25.7])

    def test_cadence_is_doubled_running_convention(self):
        """FIT `cadence` (course à pied) compte un seul pied/min → ×2 pour spm total."""
        out = S.normalise_records(self.RAW)
        self.assertAlmostEqual(out[0]["cadence_spm"], (85 + 0.5) * 2)
        self.assertAlmostEqual(out[1]["cadence_spm"], 86 * 2)

    def test_missing_cadence_is_none_not_zero(self):
        out = S.normalise_records(self.RAW)
        self.assertIsNone(out[2]["cadence_spm"])

    def test_record_without_readable_timestamp_is_skipped(self):
        raw = self.RAW + [{"timestamp": "n'importe quoi", "distance": 30.0, "heart_rate": 130}]
        out = S.normalise_records(raw)
        self.assertEqual(len(out), 3, "un timestamp illisible ne doit pas produire de t_s inventé")

    def test_all_timestamps_unreadable_yields_empty(self):
        raw = [{"timestamp": "?", "distance": 1.0}, {"timestamp": "??", "distance": 2.0}]
        self.assertEqual(S.normalise_records(raw), [])

    def test_empty_input_yields_empty_list(self):
        self.assertEqual(S.normalise_records([]), [])
        self.assertEqual(S.normalise_records({"records": []}), [])


class TestNormaliseAlreadyNormalisedFormat(unittest.TestCase):
    """Le format `sample_session` (#25) doit passer quasiment tel quel."""

    def test_passthrough_from_records_list(self):
        recs, _ = sample_session(seed=1, duration_s=5, noise=False)
        out = S.normalise_records(recs)
        self.assertEqual(len(out), len(recs))
        for got, expected in zip(out, recs):
            self.assertEqual(got["t_s"], expected["t_s"])
            self.assertAlmostEqual(got["distance_m"], expected["distance_m"])
            self.assertAlmostEqual(got["hr_bpm"], expected["hr_bpm"])

    def test_passthrough_from_canonical_wrapper_dict(self):
        """Format `activities/fit/<id>.json` : `{"activity_id":.., "records": [...], "truth": {...}}`."""
        recs, truth = sample_session(seed=1, duration_s=5, noise=False)
        payload = {"activity_id": 90000000001, "records": recs, "truth": truth}
        out = S.normalise_records(payload)
        self.assertEqual(len(out), len(recs))

    def test_numeric_strings_are_coerced(self):
        out = S.normalise_records([{"t_s": "0", "distance_m": "1.5", "altitude_m": None,
                                     "hr_bpm": "140", "speed_ms": "2.5", "cadence_spm": "170"}])
        self.assertEqual(out, [{"t_s": 0.0, "distance_m": 1.5, "altitude_m": None,
                                 "hr_bpm": 140.0, "speed_ms": 2.5, "cadence_spm": 170.0}])


class TestDownsample(unittest.TestCase):
    def _records(self):
        return [
            {"t_s": 0, "distance_m": 0.0, "altitude_m": 10.0, "hr_bpm": 140.0, "speed_ms": 2.0, "cadence_spm": 170.0},
            {"t_s": 1, "distance_m": 2.0, "altitude_m": 10.5, "hr_bpm": 142.0, "speed_ms": 2.2, "cadence_spm": 172.0},
            {"t_s": 2, "distance_m": 4.0, "altitude_m": 11.0, "hr_bpm": 144.0, "speed_ms": 2.1, "cadence_spm": 171.0},
            {"t_s": 3, "distance_m": 6.0, "altitude_m": 11.5, "hr_bpm": 146.0, "speed_ms": 2.3, "cadence_spm": 173.0},
            {"t_s": 4, "distance_m": 8.0, "altitude_m": 12.0, "hr_bpm": 148.0, "speed_ms": 2.0, "cadence_spm": 169.0},
            {"t_s": 5, "distance_m": 10.0, "altitude_m": 12.5, "hr_bpm": 150.0, "speed_ms": 2.4, "cadence_spm": 175.0},
        ]

    def test_single_bucket_averages_hr_speed_cadence(self):
        out = S.downsample(self._records()[:5], resolution_s=5)
        self.assertEqual(len(out), 1)
        bucket = out[0]
        self.assertEqual(bucket["t_s"], 0)
        self.assertAlmostEqual(bucket["hr_bpm"], (140 + 142 + 144 + 146 + 148) / 5)
        self.assertAlmostEqual(bucket["speed_ms"], (2.0 + 2.2 + 2.1 + 2.3 + 2.0) / 5)
        self.assertAlmostEqual(bucket["cadence_spm"], (170 + 172 + 171 + 173 + 169) / 5)

    def test_distance_and_altitude_take_last_value_not_average(self):
        out = S.downsample(self._records()[:5], resolution_s=5)
        self.assertEqual(out[0]["distance_m"], 8.0)   # dernière valeur du bucket (t_s=4), pas la moyenne
        self.assertEqual(out[0]["altitude_m"], 12.0)

    def test_second_bucket_boundary(self):
        out = S.downsample(self._records(), resolution_s=5)
        self.assertEqual([b["t_s"] for b in out], [0, 5])
        self.assertEqual(out[1]["distance_m"], 10.0)
        self.assertEqual(out[1]["hr_bpm"], 150.0)

    def test_resolution_of_one_is_passthrough(self):
        records = self._records()
        out = S.downsample(records, resolution_s=1)
        self.assertEqual(out, records)

    def test_none_values_are_excluded_from_the_average_not_treated_as_zero(self):
        records = [
            {"t_s": 0, "distance_m": 0.0, "altitude_m": 0.0, "hr_bpm": 140.0, "speed_ms": None, "cadence_spm": 170.0},
            {"t_s": 1, "distance_m": 1.0, "altitude_m": 0.0, "hr_bpm": None, "speed_ms": 2.0, "cadence_spm": None},
        ]
        out = S.downsample(records, resolution_s=5)
        self.assertEqual(out[0]["hr_bpm"], 140.0)
        self.assertEqual(out[0]["speed_ms"], 2.0)
        self.assertEqual(out[0]["cadence_spm"], 170.0)

    def test_bucket_with_only_none_yields_none_not_zero(self):
        records = [{"t_s": 0, "distance_m": None, "altitude_m": None, "hr_bpm": None, "speed_ms": None, "cadence_spm": None}]
        out = S.downsample(records, resolution_s=5)
        self.assertIsNone(out[0]["hr_bpm"])
        self.assertIsNone(out[0]["distance_m"])

    def test_empty_input(self):
        self.assertEqual(S.downsample([], resolution_s=5), [])


class TestSyntheticSessionIngestionPreservesTruth(unittest.TestCase):
    """T1 (#25) : distance et D+ mesurés sur les échantillons sous-échantillonnés restent
    proches de la vérité connue du générateur, à la tolérance du sous-échantillonnage."""

    def test_downsampled_distance_close_to_truth(self):
        records, truth = sample_session(seed=7, duration_s=3600, base_speed_ms=2.8,
                                         segments=((500, 300, 8), (1200, 200, -6)))
        normalised = S.normalise_records(records)
        down = S.downsample(normalised, resolution_s=5)
        # distance_m est un cumul : la dernière valeur du dernier bucket doit rester
        # proche de la distance totale mesurée par `sample_session` (delta = au plus
        # la distance parcourue en 5 s, largement sous 1 % de la distance totale ici).
        self.assertAlmostEqual(down[-1]["distance_m"], truth["distance_m"], delta=0.01 * truth["distance_m"] + 20)

    def test_downsampled_gain_loss_close_to_segments_requested(self):
        records, truth = sample_session(seed=7, duration_s=1200, base_speed_ms=2.8,
                                         segments=((100, 300, 10), (500, 200, -8)))
        normalised = S.normalise_records(records)
        down = S.downsample(normalised, resolution_s=5)
        gain = sum(max(0.0, b["altitude_m"] - a["altitude_m"]) for a, b in zip(down, down[1:]))
        loss = sum(max(0.0, a["altitude_m"] - b["altitude_m"]) for a, b in zip(down, down[1:]))
        self.assertAlmostEqual(gain, truth["elevation_gain_m"], delta=max(5.0, 0.15 * truth["elevation_gain_m"]))
        self.assertAlmostEqual(loss, truth["elevation_loss_m"], delta=max(5.0, 0.15 * truth["elevation_loss_m"]))


if __name__ == "__main__":
    unittest.main()
