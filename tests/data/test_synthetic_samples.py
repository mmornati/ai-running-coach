"""Palier D — auto-test du générateur d'échantillons synthétiques (story #25).

`tests.lib.synthetic.sample_session` fabrique des séries seconde par seconde à
vérité connue : chaque propriété demandée (montée/descente, dérive FC, zones,
fade, trous de signal) doit se retrouver, mesurée depuis `records` seul, dans
le dict `truth` qu'il renvoie. Ces tests sont le seul garde-fou de ce
générateur — toute l'épopée FIT (#42 à #48, #58) va s'appuyer dessus sans
revérifier ses fondations.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.lib.synthetic import (  # noqa: E402
    ZONE_BOUNDS_BPM, build, default_slope_factor, sample_session,
)


class TestClimb(unittest.TestCase):
    def test_8_percent_climb_over_1km_gives_about_80m(self):
        """Une montée à 8 % sur 1 km ≈ 80 m de D+ (critère d'acceptation de #25)."""
        _, truth = sample_session(
            seed=1, duration_s=3000, base_speed_ms=2.0,
            segments=((0, 1000, 8),), noise=False,
        )
        self.assertAlmostEqual(truth["elevation_gain_m"], 80.0, delta=0.2)
        self.assertEqual(truth["segments_gain_requested_m"], 80.0)

    def test_flat_course_has_no_gain(self):
        _, truth = sample_session(seed=1, duration_s=600, segments=(), noise=False)
        self.assertEqual(truth["elevation_gain_m"], 0.0)
        self.assertEqual(truth["segments_gain_requested_m"], 0.0)

    def test_climb_must_be_fully_traversed_to_reach_requested_gain(self):
        """Une séance trop courte pour parcourir toute la montée ne produit pas le D+ complet."""
        _, truth = sample_session(
            seed=1, duration_s=60, base_speed_ms=1.0,
            segments=((0, 1000, 8),), noise=False,
        )
        self.assertLess(truth["elevation_gain_m"], truth["segments_gain_requested_m"])

    def test_descent_segment_gives_measured_loss(self):
        """Une descente (pente négative, story #47) produit une perte, pas un gain."""
        _, truth = sample_session(
            seed=1, duration_s=1000, base_speed_ms=2.0,
            segments=((0, 500, -10),), noise=False,
        )
        self.assertEqual(truth["elevation_gain_m"], 0.0)
        self.assertAlmostEqual(truth["elevation_loss_m"], 50.0, delta=0.5)
        self.assertEqual(truth["segments_loss_requested_m"], 50.0)

    def test_climb_then_descent_are_independent_segments(self):
        """Deux segments (montée puis descente, story #46/#47) ne s'annulent pas dans les totaux."""
        _, truth = sample_session(
            seed=1, duration_s=3000, base_speed_ms=2.0,
            segments=((0, 500, 10), (700, 500, -10)), noise=False,
        )
        self.assertAlmostEqual(truth["elevation_gain_m"], 50.0, delta=0.5)
        self.assertAlmostEqual(truth["elevation_loss_m"], 50.0, delta=0.5)


class TestDecoupling(unittest.TestCase):
    def test_requested_drift_appears_in_raw_data(self):
        """La dérive FC demandée (découplage Pa:HR, story #45) se retrouve à ±0,5 point sur parcours plat."""
        _, truth = sample_session(seed=2, duration_s=3600, decoupling_pct=4.0, noise=True)
        self.assertAlmostEqual(truth["decoupling_pct_measured"], 4.0, delta=0.5)

    def test_zero_drift_is_flat(self):
        _, truth = sample_session(seed=2, duration_s=3600, decoupling_pct=0.0, noise=True)
        self.assertAlmostEqual(truth["decoupling_pct_measured"], 0.0, delta=0.5)

    def test_ef_based_decoupling_matches_independent_recomputation_with_climb_and_fade(self):
        """#45 définit le découplage comme un rapport GAP/FC (EF), pas un simple ratio de FC.

        Avec une montée ET un fade actifs (deux effets qui, mal isolés, avaient
        auparavant faussé la mesure — cf. revue de la story #25), `truth`
        doit rester égal à une mesure indépendante de la même formule
        (EF = moyenne(GAP)/moyenne(FC) par moitié, GAP = vitesse / facteur de
        pente) appliquée depuis l'extérieur sur `records` seul.
        """
        segments = ((200, 500, 10),)
        records, truth = sample_session(
            seed=2, duration_s=3600, decoupling_pct=4.0, fade_pct=5.0,
            segments=segments, noise=True,
        )
        half_t = 1800
        gaps = []
        for i, r in enumerate(records):
            if i == 0:
                grade = 0.0
            else:
                dd = r["distance_m"] - records[i - 1]["distance_m"]
                da = r["altitude_m"] - records[i - 1]["altitude_m"]
                grade = (da / dd * 100) if dd else 0.0
            gaps.append(r["speed_ms"] / default_slope_factor(grade))
        idx1 = [i for i, r in enumerate(records) if r["t_s"] < half_t]
        idx2 = [i for i, r in enumerate(records) if r["t_s"] >= half_t]
        ef1 = (sum(gaps[i] for i in idx1) / len(idx1)) / (sum(records[i]["hr_bpm"] for i in idx1) / len(idx1))
        ef2 = (sum(gaps[i] for i in idx2) / len(idx2)) / (sum(records[i]["hr_bpm"] for i in idx2) / len(idx2))
        expected = round((ef1 - ef2) / ef1 * 100, 2)
        self.assertAlmostEqual(truth["decoupling_pct_measured"], expected, delta=0.01)
        self.assertAlmostEqual(truth["ef_first_half"], ef1, delta=1e-4)
        self.assertAlmostEqual(truth["ef_second_half"], ef2, delta=1e-4)

    def test_zone_shares_take_precedence_over_decoupling(self):
        _, truth = sample_session(
            seed=3, duration_s=1000, zone_shares={1: 1.0}, decoupling_pct=10.0, noise=False,
        )
        self.assertIsNone(truth["decoupling_pct_requested"])
        self.assertIsNone(truth["decoupling_pct_measured"])


class TestZoneDistribution(unittest.TestCase):
    def test_imposed_zone_shares_are_respected(self):
        shares = {1: 0.6, 2: 0.2, 3: 0.1, 4: 0.05, 5: 0.05}
        _, truth = sample_session(seed=3, duration_s=2000, zone_shares=shares, noise=False)
        self.assertEqual(sum(truth["zone_seconds_measured"].values()), 2000)
        for zone, share in shares.items():
            self.assertEqual(truth["zone_seconds_measured"][str(zone)], round(2000 * share))

    def test_zone_shares_and_dropout_are_counted_only_on_emitted_records(self):
        """Un trou de signal ne doit jamais gonfler un total de zone au-delà des échantillons émis.

        Avant correction, `zone_seconds` comptait les secondes du calendrier de
        zones même quand l'échantillon correspondant était supprimé par un
        trou de signal : {1: .5, 5: .5} + un trou de 300 s sur la zone 1
        donnait Z1 = 500 alors que seuls 200 échantillons de zone 1 sont
        réellement émis.
        """
        _, truth = sample_session(
            seed=1, duration_s=1000, zone_shares={1: 0.5, 5: 0.5},
            dropout_windows=((0, 300),), noise=False,
        )
        self.assertEqual(truth["n_samples"], 700)
        self.assertEqual(truth["zone_seconds_measured"]["1"], 200)
        self.assertEqual(truth["zone_seconds_measured"]["5"], 500)
        self.assertEqual(sum(truth["zone_seconds_measured"].values()), truth["n_samples"])

    def test_default_zone_bounds_are_karvonen_on_profile_hr(self):
        """Bornes par défaut dérivées de FC repos/max du profil type (Karvonen), pas des constantes arbitraires."""
        _, truth = sample_session(seed=1, duration_s=10)
        self.assertEqual(truth["zone_bounds_bpm"], list(ZONE_BOUNDS_BPM))
        self.assertEqual(truth["zone_bounds_method"], "karvonen_hrr")

    def test_invalid_zone_shares_raise(self):
        with self.assertRaises(ValueError):
            sample_session(seed=1, duration_s=10, zone_shares={1: 0.5, 2: 0.6})
        with self.assertRaises(ValueError):
            sample_session(seed=1, duration_s=10, zone_shares={0: 1.0})
        with self.assertRaises(ValueError):
            sample_session(seed=1, duration_s=10, zone_shares={99: 1.0})


class TestFade(unittest.TestCase):
    def test_last_third_fade_is_measured_on_flat_course(self):
        """Fade de fin de séance (durabilité, story #48) mesuré sur le dernier tiers vs le premier."""
        _, truth = sample_session(seed=4, duration_s=3600, fade_pct=8.0, noise=False)
        self.assertAlmostEqual(truth["fade_pct_measured"], 8.0, delta=0.1)

    def test_fade_uses_grade_adjusted_pace_so_a_climb_does_not_distort_it(self):
        """Un fade demandé de 8 % reste ≈ 8 % même avec une montée en cours de route.

        Avant correction, la comparaison se faisait sur la vitesse brute des
        deux premiers tiers vs le dernier ; une montée placée tôt (ex. à
        500 m) faussait la moyenne du premier groupe et donnait une mesure
        aberrante (ex. -6,78 au lieu de ≈ 8). Sur GAP (vitesse ajustée à la
        pente) et premier tiers vs dernier tiers, la montée est neutralisée.
        """
        _, truth = sample_session(
            seed=4, duration_s=3600, fade_pct=8.0, segments=((500, 300, 8),), noise=False,
        )
        self.assertAlmostEqual(truth["fade_pct_measured"], 8.0, delta=0.5)

    def test_no_fade_by_default(self):
        _, truth = sample_session(seed=4, duration_s=3600, noise=False)
        self.assertEqual(truth["fade_pct_measured"], 0.0)
        self.assertEqual(len(truth["hr_by_third_bpm"]), 3)


class TestDropouts(unittest.TestCase):
    def test_dropout_windows_remove_samples(self):
        recs, truth = sample_session(seed=5, duration_s=200, dropout_windows=((50, 60), (100, 120)))
        self.assertEqual(truth["dropout_seconds"], 30)
        self.assertEqual(len(recs), 200 - 30)
        missing = set(range(50, 60)) | set(range(100, 120))
        present = {r["t_s"] for r in recs}
        self.assertFalse(missing & present, "les secondes en trou de signal ne doivent pas apparaître")

    def test_no_dropout_by_default(self):
        recs, truth = sample_session(seed=5, duration_s=120)
        self.assertEqual(truth["dropout_seconds"], 0)
        self.assertEqual(len(recs), 120)


class TestSpeedByGradeCurve(unittest.TestCase):
    def test_curve_reflects_segments_and_slope_model(self):
        """La courbe pente→allure imposée (story #58) est exposée pour être retrouvée par régression."""
        _, truth = sample_session(seed=1, duration_s=100, segments=((0, 50, 10), (60, 20, -5)), noise=False)
        curve = dict(truth["speed_by_grade_curve"])
        self.assertIn(10, curve)
        self.assertIn(-5, curve)
        self.assertIn(0.0, curve)
        self.assertAlmostEqual(curve[10], default_slope_factor(10), places=4)
        self.assertAlmostEqual(curve[-5], default_slope_factor(-5), places=4)

    def test_custom_slope_factor_fn_is_exposed_verbatim(self):
        curve_fn = lambda g: 1.0 - 0.1 * g  # noqa: E731
        _, truth = sample_session(
            seed=1, duration_s=100, segments=((0, 50, 4),),
            slope_factor_fn=curve_fn, noise=False,
        )
        curve = dict(truth["speed_by_grade_curve"])
        self.assertAlmostEqual(curve[4], curve_fn(4), places=4)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_is_byte_for_byte_identical(self):
        params = dict(seed=42, duration_s=900, segments=((200, 400, 6),),
                      decoupling_pct=3, fade_pct=5, dropout_windows=((10, 15),))
        r1, t1 = sample_session(**params)
        r2, t2 = sample_session(**params)
        self.assertEqual(
            json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True),
        )
        self.assertEqual(
            json.dumps(t1, sort_keys=True), json.dumps(t2, sort_keys=True),
        )

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

    def test_truth_survives_a_json_round_trip_unchanged(self):
        """`truth` ne doit contenir que des types qui survivent un aller-retour JSON
        (donc pas de clé entière ou de tuple) : sinon un fichier relu diffère de
        l'objet Python d'origine sans qu'aucun test ne le voie.
        """
        records, truth = sample_session(
            seed=9, duration_s=600, segments=((100, 200, 8),),
            zone_shares={1: 0.7, 2: 0.3}, dropout_windows=((50, 55),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.json"
            path.write_text(json.dumps({"records": records, "truth": truth}, ensure_ascii=False), encoding="utf-8")
            reloaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(reloaded["truth"], truth)
        self.assertEqual(reloaded["records"], records)


class TestWithSamplesCLI(unittest.TestCase):
    """`--with-samples` (ici via `build(..., with_samples=True)`, sans sous-processus)."""

    def test_build_with_samples_writes_fit_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(Path(tmp), days=10, today=None, sport="trail", seed=1, with_samples=True)
            fit_dir = root / "activities/fit"
            self.assertTrue(fit_dir.is_dir())
            files = list(fit_dir.glob("*.json"))
            self.assertGreater(len(files), 0)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertIn("activity_id", payload)
            self.assertIn("records", payload)
            self.assertIn("truth", payload)


class TestMarkdownAgreement(unittest.TestCase):
    """`--with-samples` doit rester cohérent avec le Markdown de la même séance (finding de revue #5)."""

    def test_samples_agree_with_the_activity_markdown(self):
        import re

        with tempfile.TemporaryDirectory() as tmp:
            root = build(Path(tmp), days=15, today=None, sport="trail", seed=3, with_samples=True)
            checked = 0
            for md_path in (root / "activities").glob("*.md"):
                text = md_path.read_text(encoding="utf-8")
                m = re.search(r"```arc\n(.*?)\n```", text, re.S)
                if not m:
                    continue
                data = json.loads(m.group(1))
                if data.get("sport") == "strength" or "garmin_activity_id" not in data:
                    continue
                sample_path = root / "activities/fit" / f"{data['garmin_activity_id']}.json"
                self.assertTrue(sample_path.exists(), sample_path)
                payload = json.loads(sample_path.read_text(encoding="utf-8"))
                truth = payload["truth"]
                records = payload["records"]

                self.assertAlmostEqual(truth["distance_m"], data["distance_m"], delta=0.05 * data["distance_m"])
                self.assertAlmostEqual(
                    truth["elevation_gain_m"], data["elevation_gain_m"],
                    delta=max(20.0, 0.25 * max(data["elevation_gain_m"], 1)),
                )
                avg_hr_samples = sum(r["hr_bpm"] for r in records) / len(records)
                self.assertAlmostEqual(avg_hr_samples, data["avg_hr_bpm"], delta=3.0)
                checked += 1
            self.assertGreater(checked, 0, "aucune séance running/trail à comparer")


if __name__ == "__main__":
    unittest.main()
