"""Palier D — dépense énergétique brute d'une séance course/marche.

Familles de tests :
- `arc_energy.re3_power_w_kg` : valeurs de référence de l'équation RE3
  (Looney, Hoogkamer & Kram, 2025), calculées à la main dans les docstrings
  ci-dessous (plat, montée/descente 10 %, descente -30 %), décroissance puis
  remontée du coût en descente, bornage COURSE (±0,30, `RUN_GRADE_CLAMP`).
- `arc_energy.walk_power_w_kg` : polynôme MARCHE de Minetti et al. 2002,
  bornage MARCHE (±0,45, `WALK_GRADE_CLAMP`), coût debout (1,44 W/kg, Looney
  et al. 2019a, cité par la RE3 elle-même).
- Seuils marche/course/arrêt, bande de plat (`FLAT_GRADE_BAND`), lissage de
  classification (discontinuité au seuil résolue).
- `energy_from_samples` : intégration temporelle RÉELLE à l'intérieur d'un
  segment (correctif : jamais plafonnée à `resolution_s`), trous de signal
  jamais traversés (`gap_s`), vitesse manquante inférée depuis la distance
  avant exclusion (`excluded_s`), échantillons vides, poids absent.
- `energy_from_profile` : compatibilité RÉELLE avec le format rendu par
  `arc_race_pacing.predict_segments` (`predicted_time_s`/scénario), profil
  point par point, segment malformé, vitesse d'arrêt.
- Enchaînement RÉEL `parse_gpx` -> `segment_course` -> `predict_segments` ->
  `energy_from_profile` sur la fixture GPX du plan de course personnel.
- Non-régression sur des séances synthétiques de `tests.lib.synthetic.sample_session`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_energy as NRG  # noqa: E402
import arc_race_pacing as RP  # noqa: E402
import arc_samples as S  # noqa: E402
import arc_slope_model as SL  # noqa: E402
from tests.lib.synthetic import sample_session  # noqa: E402

GPX_FIXTURE = REPO / "tests" / "evals" / "fixtures" / "race-plan-personal-model" / "course.gpx"


# ---------------------------------------------------------------------------
# arc_energy : équation RE3 (course)
# ---------------------------------------------------------------------------

class TestRe3PowerWKg(unittest.TestCase):
    def test_flat_v3_matches_hand_computation(self):
        """v=3 m/s, g=0 : le terme en g s'annule quel que soit le facteur —
        P = 4.43 + 1.51*3 + 0.37*3² = 4.43 + 4.53 + 3.33 = 12.29 W/kg."""
        self.assertAlmostEqual(NRG.re3_power_w_kg(3.0, 0.0), 12.29, places=6)

    def test_uphill_10_percent_v3_matches_hand_computation(self):
        """v=3 m/s, g=0.10 : terme additionnel 30.43×3×0.10×(1 −
        1.133^(1 − 1.056^(100×0.10+43))) — 1.056^53 ≈ 17.953,
        1.133^(1−17.953) = 1.133^(−16.953) ≈ 0.1204, terme ≈ 9.129×0.8796
        ≈ 8.0301 -> P ≈ 12.29 + 8.0301 ≈ 20.3201 W/kg."""
        self.assertAlmostEqual(NRG.re3_power_w_kg(3.0, 0.10), 20.320120606306666, places=6)

    def test_downhill_10_percent_v3_matches_hand_computation(self):
        """v=3 m/s, g=-0.10 : même formule, terme négatif -> coût réduit sous
        le plat, mais pas divisé par deux (non-linéarité RE3)."""
        self.assertAlmostEqual(NRG.re3_power_w_kg(3.0, -0.10), 8.027320549708184, places=6)
        self.assertLess(NRG.re3_power_w_kg(3.0, -0.10), NRG.re3_power_w_kg(3.0, 0.0))

    def test_downhill_30_percent_v3_matches_hand_computation(self):
        """v=3 m/s, g=-0.30 (borne `RUN_GRADE_CLAMP`) : le coût REMONTE déjà
        par rapport à -10 %/-15 %/-20 % — voir
        `test_downhill_cost_decreases_then_increases` pour la forme complète."""
        self.assertAlmostEqual(NRG.re3_power_w_kg(3.0, -0.30), 8.982832114066177, places=6)

    def test_downhill_cost_decreases_then_increases(self):
        """Le coût en descente n'est PAS monotone : il baisse jusqu'à un
        minimum (autour de -15/-20 %) puis REMONTE aux pentes plus raides —
        même comportement que le modèle de Minetti sous-jacent au GAP
        (`docs/marques.md`, avertissement sur l'efficacité en descente)."""
        p_minus_10 = NRG.re3_power_w_kg(3.0, -0.10)
        p_minus_15 = NRG.re3_power_w_kg(3.0, -0.15)
        p_minus_20 = NRG.re3_power_w_kg(3.0, -0.20)
        p_minus_30 = NRG.re3_power_w_kg(3.0, -0.30)
        self.assertLess(p_minus_15, p_minus_10)     # baisse encore de -10 % à -15 %
        self.assertGreater(p_minus_20, p_minus_15)  # remonte déjà à -20 %
        self.assertGreater(p_minus_30, p_minus_20)  # continue de remonter à -30 %

    def test_grade_clamped_beyond_run_grade_clamp(self):
        """Au-delà de ±`RUN_GRADE_CLAMP` (0,30), la pente est plafonnée avant
        d'entrer dans le polynôme — jamais une extrapolation, même si la RE3
        a réellement été étudiée plus loin (-0,45 à +0,82, voir docstring du
        module) : notre borne est un choix de projet plus conservateur."""
        self.assertEqual(NRG.RUN_GRADE_CLAMP, 0.30)
        self.assertEqual(NRG.re3_power_w_kg(3.0, 0.9), NRG.re3_power_w_kg(3.0, 0.30))
        self.assertEqual(NRG.re3_power_w_kg(3.0, -0.9), NRG.re3_power_w_kg(3.0, -0.30))

    def test_none_grade_is_flat(self):
        self.assertAlmostEqual(NRG.re3_power_w_kg(3.0, None), NRG.re3_power_w_kg(3.0, 0.0), places=9)

    def test_negative_speed_treated_as_zero(self):
        self.assertAlmostEqual(NRG.re3_power_w_kg(-1.0, 0.0), NRG.re3_power_w_kg(0.0, 0.0), places=9)


# ---------------------------------------------------------------------------
# arc_energy : polynôme MARCHE de Minetti et al. 2002 + coût debout
# ---------------------------------------------------------------------------

class TestWalkPowerWKg(unittest.TestCase):
    def test_standing_power_is_looney_2019a_value(self):
        """1,44 W/kg — Looney DP et al. (2019a), cité tel quel par la RE3
        (Looney et al. 2025, vérifié dans le texte de l'article : « we added
        the generalized standing Ṁ determined by Looney et al. (2019a)
        (1.44 W·kg⁻¹) »)."""
        self.assertEqual(NRG.STANDING_POWER_W_KG, 1.44)

    def test_flat_cost_matches_constant_term(self):
        """Cw(0) = 2.5 J/kg/m (terme constant du polynôme, littéralement) ;
        puissance = 2.5 × 1.2 + 1.44 (debout) = 3.0 + 1.44 = 4.44 W/kg."""
        self.assertAlmostEqual(NRG.walk_power_w_kg(1.2, 0.0), 4.44, places=6)

    def test_uphill_10_percent_matches_hand_computation(self):
        """Cw(0.10), calculé à la main (i=0.1, i²=0.01, i³=0.001, i⁴=0.0001,
        i⁵=0.00001) : 280.5×0.00001 − 58.7×0.0001 − 76.8×0.001 + 51.9×0.01
        + 19.6×0.1 + 2.5 = 0.002805 − 0.00587 − 0.0768 + 0.519 + 1.96 + 2.5
        = 4.899135 J/kg/m ; puissance à 1.2 m/s = 4.899135×1.2 + 1.44
        ≈ 7.319 W/kg."""
        self.assertAlmostEqual(NRG.walk_power_w_kg(1.2, 0.10), 4.899135 * 1.2 + 1.44, places=6)

    def test_standing_power_is_floor(self):
        """Une vitesse de marche nulle rend la puissance debout seule (aucun
        coût de déplacement)."""
        self.assertAlmostEqual(NRG.walk_power_w_kg(0.0, 0.10), NRG.STANDING_POWER_W_KG, places=9)

    def test_grade_clamped_at_walk_grade_clamp_045(self):
        """Bornage MARCHE (±0,45, plage ÉTUDIÉE par Minetti et al. 2002,
        même source que `arc_gap.CLAMP_GRADE`) — DIFFÉRENT du bornage course
        (±0,30, `RUN_GRADE_CLAMP`, approximation de projet)."""
        self.assertEqual(NRG.WALK_GRADE_CLAMP, 0.45)
        self.assertEqual(NRG.walk_power_w_kg(1.2, 0.9), NRG.walk_power_w_kg(1.2, 0.45))
        self.assertEqual(NRG.walk_power_w_kg(1.2, -0.9), NRG.walk_power_w_kg(1.2, -0.45))


# ---------------------------------------------------------------------------
# Seuils marche / course / arrêt / bande de plat
# ---------------------------------------------------------------------------

class TestThresholds(unittest.TestCase):
    def test_walk_speed_threshold_value(self):
        self.assertEqual(NRG.WALK_SPEED_MS, 1.8)

    def test_stopped_speed_threshold_value(self):
        self.assertEqual(NRG.STOPPED_SPEED_MS, 0.3)

    def test_classify_walk_below_threshold(self):
        category = NRG._category_for(1.5, 0.0)
        self.assertEqual(category, "walk")

    def test_classify_run_at_threshold(self):
        # >= WALK_SPEED_MS (1.8 pile) -> régime course, jamais marche.
        self.assertEqual(NRG._category_for(1.8, 0.0), "flat")

    def test_classify_stopped_below_threshold(self):
        self.assertEqual(NRG._category_for(0.1, 0.05), "stopped")

    def test_classify_uphill_vs_downhill_vs_flat(self):
        self.assertEqual(NRG._category_for(3.0, 0.05), "uphill")
        self.assertEqual(NRG._category_for(3.0, -0.05), "downhill")
        self.assertEqual(NRG._category_for(3.0, 0.0), "flat")

    def test_flat_band_absorbs_small_grade_noise(self):
        """±0,5 % (0.005), bien sous FLAT_GRADE_BAND (0.02) -> « flat »,
        jamais « uphill »/« downhill » pour un bruit de mesure."""
        self.assertEqual(NRG.FLAT_GRADE_BAND, 0.02)
        self.assertEqual(NRG._category_for(3.0, 0.005), "flat")
        self.assertEqual(NRG._category_for(3.0, -0.005), "flat")
        # Juste au-delà de la bande : classé normalement.
        self.assertEqual(NRG._category_for(3.0, 0.03), "uphill")
        self.assertEqual(NRG._category_for(3.0, -0.03), "downhill")

    def test_missing_speed_has_no_category(self):
        self.assertIsNone(NRG._category_for(None, 0.0))


# ---------------------------------------------------------------------------
# `energy_from_samples` : intégration temporelle, trous, données manquantes
# ---------------------------------------------------------------------------

def _flat_samples(n=40, dt=5.0, speed=3.0, grade=0.0):
    out = []
    dist = alt = 0.0
    for i in range(n):
        out.append({"t_s": i * dt, "distance_m": dist, "altitude_m": alt,
                    "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
        dist += speed * dt
        alt += speed * dt * grade
    return out


class TestEnergyFromSamples(unittest.TestCase):
    def test_missing_weight_returns_none(self):
        self.assertIsNone(NRG.energy_from_samples(_flat_samples(), None))
        self.assertIsNone(NRG.energy_from_samples(_flat_samples(), 0.0))
        self.assertIsNone(NRG.energy_from_samples(_flat_samples(), -5.0))

    def test_empty_samples_never_raises(self):
        result = NRG.energy_from_samples([], 70.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["kcal"], 0.0)
        self.assertEqual(result["reason_code"], "no_samples")

    def test_flat_run_kcal_matches_re3_hand_computation(self):
        """40 échantillons de 5 s à 3 m/s plat, poids 70 kg : puissance
        constante (12.29 W/kg, voir `TestRe3PowerWKg`), énergie totale =
        12.29 × 70 × 200 s / 4184 J/kcal ≈ 41.16 kcal. Les échantillons de
        bord (fenêtre de pente trop courte) restent malgré tout à un plat
        connu ici (altitude nulle partout), donc AUCUNE tolérance de bord
        n'est nécessaire : le résultat colle exactement."""
        result = NRG.energy_from_samples(_flat_samples(), 70.0)
        expected_kcal = 12.29 * 70.0 * 200.0 / NRG.J_PER_KCAL
        self.assertAlmostEqual(result["kcal"], expected_kcal, places=3)
        self.assertAlmostEqual(result["breakdown"]["flat"]["seconds"], 200.0, places=3)
        self.assertEqual(result["breakdown"]["uphill"]["seconds"], 0.0)
        self.assertEqual(result["breakdown"]["walk"]["seconds"], 0.0)
        self.assertAlmostEqual(result["counted_s"], 200.0, places=3)
        self.assertEqual(result["gap_s"], 0.0)
        self.assertEqual(result["excluded_s"], 0.0)
        self.assertFalse(result["elevation_missing"])
        self.assertEqual(result["model_id"], NRG.MODEL_ID)

    def test_irregular_sampling_integrates_real_dt_not_capped_at_resolution(self):
        """CORRECTIF (revue de code, 1ʳᵉ passe) : 10 échantillons tous les 7 s
        (> resolution_s par défaut de 5 s, comme un enregistrement Garmin en
        pas variable) doivent être intégrés sur leur `dt` RÉEL (7 s), jamais
        plafonnés à 5 s — sinon 30 % de l'énergie serait perdue. `counted_s`
        doit refléter le temps RÉELLEMENT écoulé (9 intervalles × 7 s) plus la
        fenêtre nominale du DERNIER échantillon (resolution_s, 5 s par
        défaut, faute de savoir combien de temps il a duré après la dernière
        mesure) : 9×7 + 5 = 68 s — jamais 10×5 = 50 s (l'ancien comportement,
        plafonné)."""
        n, dt = 10, 7.0
        samples = _flat_samples(n=n, dt=dt, speed=3.0)
        result = NRG.energy_from_samples(samples, 70.0)
        expected_counted_s = (n - 1) * dt + NRG.DEFAULT_RESOLUTION_S
        self.assertAlmostEqual(result["counted_s"], expected_counted_s, places=3)
        expected_kcal = 12.29 * 70.0 * expected_counted_s / NRG.J_PER_KCAL
        self.assertAlmostEqual(result["kcal"], expected_kcal, places=3)
        # L'ancien comportement (buggé) aurait donné 50 s comptées, largement
        # sous le temps réellement écoulé : on vérifie explicitement l'écart.
        buggy_counted_s = n * NRG.DEFAULT_RESOLUTION_S
        self.assertGreater(result["counted_s"], buggy_counted_s)

    def test_walk_vs_run_at_equal_distance(self):
        """À DISTANCE ÉGALE (180 m), une séance marchée à 1,5 m/s (120 s) doit
        coûter MOINS cher qu'une séance courue à 3 m/s (60 s) : la marche est
        physiologiquement plus économe par mètre à ces deux allures
        (Cw(0)×1,5/1,5 ≈ 3,46 J/kg/m marché contre RE3(3,0)/3,0 ≈ 4,10 J/kg/m
        couru) — comparaison quantitative, pas seulement qualitative."""
        distance_m = 180.0
        walk_speed, run_speed = 1.5, 3.0
        walk_samples = _flat_samples(n=int(distance_m / walk_speed / 5.0), dt=5.0, speed=walk_speed)
        run_samples = _flat_samples(n=int(distance_m / run_speed / 5.0), dt=5.0, speed=run_speed)
        walk = NRG.energy_from_samples(walk_samples, 70.0)
        run = NRG.energy_from_samples(run_samples, 70.0)
        self.assertGreater(walk["breakdown"]["walk"]["seconds"], 0.0)
        self.assertGreater(run["breakdown"]["flat"]["seconds"], 0.0)
        self.assertLess(walk["kcal"], run["kcal"])

    def test_stops_counted_at_standing_power_only(self):
        samples = _flat_samples(n=20, speed=0.0)
        result = NRG.energy_from_samples(samples, 70.0)
        self.assertAlmostEqual(result["breakdown"]["stopped"]["seconds"], 100.0, places=3)
        expected_kcal = NRG.STANDING_POWER_W_KG * 70.0 * 100.0 / NRG.J_PER_KCAL
        self.assertAlmostEqual(result["kcal"], expected_kcal, places=3)

    def test_signal_gap_never_bridged_and_reported(self):
        """Une pause de 300 s (>> max_gap_s=30 s) entre deux plats : le dernier
        échantillon avant le trou pèse `resolution_s` (5 s), JAMAIS les 300 s
        du silence — `gap_s` rend compte du trou séparément."""
        before = _flat_samples(n=10, speed=3.0)
        gap_t0 = before[-1]["t_s"] + 305.0
        after = [{"t_s": gap_t0 + i * 5.0, "distance_m": before[-1]["distance_m"] + i * 5.0 * 3.0,
                  "altitude_m": 0.0, "hr_bpm": 150.0, "speed_ms": 3.0, "cadence_spm": 170.0}
                 for i in range(10)]
        result = NRG.energy_from_samples(before + after, 70.0)
        # 20 échantillons utiles, chacun pèse au plus resolution_s (5 s) pour
        # le dernier de chaque segment -> 100 s de mouvement, jamais 405 s.
        self.assertAlmostEqual(result["moving_duration_s"], 100.0, places=3)
        self.assertAlmostEqual(result["counted_s"], 100.0, places=3)
        # `gap_s` déduit `resolution_s` (5 s) du trou brut (305 s) : cette
        # fenêtre nominale du dernier échantillon avant le trou est déjà
        # comptée dans `counted_s`, jamais deux fois (voir
        # `ASSUMPTIONS["time_weighting"]`).
        self.assertAlmostEqual(result["gap_s"], 300.0, places=3)

    def test_missing_altitude_everywhere_flags_elevation_missing(self):
        samples = [{"t_s": i * 5.0, "distance_m": i * 5.0 * 3.0, "altitude_m": None,
                    "hr_bpm": 150.0, "speed_ms": 3.0, "cadence_spm": 170.0} for i in range(20)]
        result = NRG.energy_from_samples(samples, 70.0)
        self.assertTrue(result["elevation_missing"])
        self.assertGreater(result["elevation_missing_s"], 0.0)
        # Traité comme un plat explicite : toute la séance classée "flat".
        self.assertGreater(result["breakdown"]["flat"]["seconds"], 0.0)
        self.assertEqual(result["breakdown"]["uphill"]["seconds"], 0.0)
        self.assertEqual(result["breakdown"]["downhill"]["seconds"], 0.0)

    def test_missing_speed_inferred_from_distance_before_exclusion(self):
        """Un échantillon sans `speed_ms` MAIS avec une distance cohérente
        avec ses voisins est inféré (Δdistance/Δt), jamais exclu à tort —
        voir `ASSUMPTIONS['missing_speed']`."""
        samples = _flat_samples(n=10, speed=3.0)
        samples[5]["speed_ms"] = None  # distance_m reste cohérente (3 m/s)
        result = NRG.energy_from_samples(samples, 70.0)
        # Les 10 échantillons restent tous exploitables (inférence réussie) :
        # 9 intervalles de 5 s + la fenêtre nominale du dernier échantillon
        # (5 s) = 50 s, rien d'exclu (comme sans le trou de vitesse).
        reference = NRG.energy_from_samples(_flat_samples(n=10, speed=3.0), 70.0)
        self.assertAlmostEqual(result["moving_duration_s"], reference["moving_duration_s"], places=3)
        self.assertEqual(result["excluded_s"], 0.0)

    def test_missing_speed_and_distance_excluded_and_counted_separately(self):
        """Un échantillon sans vitesse NI distance exploitable (donc sans
        inférence possible) est exclu — `excluded_s` en rend compte,
        distinct de `gap_s` (trou de signal RÉEL, jamais confondu)."""
        samples = _flat_samples(n=10, speed=3.0)
        samples[5]["speed_ms"] = None
        samples[5]["distance_m"] = None
        result = NRG.energy_from_samples(samples, 70.0)
        self.assertGreater(result["excluded_s"], 0.0)
        self.assertEqual(result["gap_s"], 0.0)

    def test_noisy_speed_oscillating_around_walk_threshold_does_not_flicker(self):
        """Une vitesse RAW qui oscille FORTEMENT autour de WALK_SPEED_MS
        (1,8 m/s, ex. 1,75/2,05 alternés — chaque échantillon INDIVIDUEL
        franchit le seuil dans un sens ou l'autre) mais dont la MOYENNE est
        nettement au-dessus (1,90 m/s) ne doit PAS produire une classification
        en mélange échantillon par échantillon (lissage de classification,
        voir `ASSUMPTIONS['classification_smoothing']`) : la séance entière
        retombe d'un seul côté du seuil une fois lissée — `walk` doit rester à
        zéro seconde, jamais un mélange qui refléterait la vitesse INSTANTANÉE
        brute plutôt que la tendance lissée."""
        n, dt = 30, 5.0
        samples = []
        dist = 0.0
        for i in range(n):
            speed = 1.75 if i % 2 == 0 else 2.05  # individuellement, franchit 1.8 dans les deux sens
            samples.append({"t_s": i * dt, "distance_m": dist, "altitude_m": 0.0,
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
            dist += speed * dt
        result = NRG.energy_from_samples(samples, 70.0)
        walk_s = result["breakdown"]["walk"]["seconds"]
        flat_s = result["breakdown"]["flat"]["seconds"]
        self.assertEqual(walk_s, 0.0, f"classification en flip-flop : walk={walk_s}s, flat={flat_s}s")
        self.assertGreater(flat_s, 0.0)


# ---------------------------------------------------------------------------
# `energy_from_profile` : prévision par segment
# ---------------------------------------------------------------------------

class TestEnergyFromProfile(unittest.TestCase):
    def test_missing_weight_returns_none(self):
        self.assertIsNone(NRG.energy_from_profile([{"distance_m": 100.0, "grade": 0.0, "speed_ms": 3.0}], None))

    def test_empty_segments_never_raises(self):
        result = NRG.energy_from_profile([], 70.0)
        self.assertEqual(result["kcal"], 0.0)
        self.assertEqual(result["reason_code"], "no_segments")

    def test_simple_segment_matches_hand_computation(self):
        """1 segment de 900 m à 3 m/s plat -> 300 s -> énergie =
        12.29 × 70 × 300 / 4184 ≈ 61.74 kcal ; kcal/h = kcal / (300/3600)."""
        result = NRG.energy_from_profile([{"id": "s01", "distance_m": 900.0, "grade": 0.0, "speed_ms": 3.0}], 70.0)
        expected_kcal = 12.29 * 70.0 * 300.0 / NRG.J_PER_KCAL
        self.assertAlmostEqual(result["kcal"], expected_kcal, places=3)
        self.assertAlmostEqual(result["time_s"], 300.0, places=3)
        self.assertAlmostEqual(result["kcal_per_h"], expected_kcal / (300.0 / 3600.0), places=3)
        self.assertEqual(result["segments"][0]["id"], "s01")
        self.assertIsNone(result["segments"][0]["reason_code"])

    def test_missing_segment_speed_counts_distance_not_energy(self):
        result = NRG.energy_from_profile([{"distance_m": 500.0, "grade": 0.0}], 70.0)
        self.assertEqual(result["kcal"], 0.0)
        self.assertEqual(result["time_s"], 0.0)
        self.assertEqual(result["segments"][0]["distance_m"], 500.0)
        self.assertIsNone(result["segments"][0]["kcal_per_h"])
        self.assertEqual(result["segments"][0]["reason_code"], "no_speed")

    def test_time_s_resolves_speed(self):
        """`time_s` explicite (sans `speed_ms`) résout une vitesse dérivée
        `distance_m / time_s`, sans passer par `predicted_time_s`."""
        result = NRG.energy_from_profile([{"distance_m": 900.0, "grade": 0.0, "time_s": 300.0}], 70.0)
        expected_kcal = 12.29 * 70.0 * 300.0 / NRG.J_PER_KCAL
        self.assertAlmostEqual(result["kcal"], expected_kcal, places=3)
        self.assertIsNone(result["segments"][0]["reason_code"])

    def test_predicted_time_s_from_arc_race_pacing_scenario(self):
        """Format EXACT rendu par `arc_race_pacing.predict_segments`
        (`predicted_time_s` par scénario) : le scénario par défaut
        ('realistic') est utilisé sans que l'appelant ait à convertir quoi
        que ce soit."""
        segment = {"distance_m": 900.0, "grade": 0.0,
                   "predicted_time_s": {"safe": 340, "realistic": 300, "ambitious": 270}}
        result = NRG.energy_from_profile([segment], 70.0)
        expected_kcal = 12.29 * 70.0 * 300.0 / NRG.J_PER_KCAL
        self.assertAlmostEqual(result["kcal"], expected_kcal, places=2)

        result_safe = NRG.energy_from_profile([segment], 70.0, scenario="safe")
        self.assertNotAlmostEqual(result_safe["kcal"], result["kcal"], places=2)

    def test_no_speed_reason_code_when_nothing_resolves(self):
        result = NRG.energy_from_profile([{"distance_m": 500.0, "grade": 0.0,
                                            "predicted_time_s": {"realistic": None}}], 70.0)
        self.assertEqual(result["segments"][0]["reason_code"], "no_speed")

    def test_non_numeric_speed_time_and_predicted_time_never_raise(self):
        """`speed_ms`/`time_s`/`predicted_time_s[scenario]` non numériques
        (ex. une chaîne `"3"`, un type inattendu) sont IGNORÉS — jamais une
        `TypeError` (comparaison str/int) qui ferait échouer tout l'appel."""
        cases = [
            {"distance_m": 500.0, "grade": 0.0, "speed_ms": "3"},
            {"distance_m": 500.0, "grade": 0.0, "time_s": "300"},
            {"distance_m": 500.0, "grade": 0.0, "predicted_time_s": {"realistic": "300"}},
            {"distance_m": 500.0, "grade": 0.0, "speed_ms": object()},
            {"distance_m": 500.0, "grade": 0.0, "predicted_time_s": "not-a-dict"},
        ]
        for segment in cases:
            with self.subTest(segment=segment):
                result = NRG.energy_from_profile([segment], 70.0)  # ne doit jamais lever
                self.assertEqual(result["segments"][0]["reason_code"], "no_speed")
                self.assertEqual(result["segments"][0]["kcal"], 0.0)

    def test_profile_key_integrates_point_by_point(self):
        """Un profil `_profile` (format `arc_race_pacing.segment_course`) avec
        un aller +12 %/-12 % coûte STRICTEMENT plus cher qu'un plat de la même
        distance totale à la même vitesse — la pente moyenne quasi nulle ne
        doit jamais être utilisée telle quelle (voir
        `arc_race_pacing.ASSUMPTIONS["rolling_terrain"]`)."""
        rolling = [{"_profile": [(200.0, 0.12), (200.0, -0.12)], "speed_ms": 3.0}]
        flat = [{"distance_m": 400.0, "grade": 0.0, "speed_ms": 3.0}]
        result_rolling = NRG.energy_from_profile(rolling, 70.0)
        result_flat = NRG.energy_from_profile(flat, 70.0)
        self.assertGreater(result_rolling["kcal"], result_flat["kcal"])

    def test_malformed_profile_element_never_raises(self):
        """Un élément de `_profile` qui n'est pas une paire `(dx, grade)`
        valide est ignoré, jamais une exception."""
        segment = {"_profile": [(100.0, 0.05), "invalide", (None, 0.05), (100.0, -0.05)], "speed_ms": 3.0}
        result = NRG.energy_from_profile([segment], 70.0)
        self.assertGreater(result["kcal"], 0.0)
        self.assertAlmostEqual(result["segments"][0]["distance_m"], 200.0, places=3)

    def test_stopped_speed_segment(self):
        """Un segment prévu à une vitesse d'ARRÊT (0 < speed < STOPPED_SPEED_MS,
        ex. un ravitaillement modélisé comme un segment à très faible vitesse)
        utilise le métabolisme debout seul, jamais une extrapolation RE3/marche
        à une vitesse quasi nulle."""
        result = NRG.energy_from_profile([{"distance_m": 5.0, "grade": 0.0, "speed_ms": 0.1}], 70.0)
        seg = result["segments"][0]
        expected_kcal = NRG.STANDING_POWER_W_KG * 70.0 * seg["time_s"] / NRG.J_PER_KCAL
        self.assertAlmostEqual(seg["kcal"], expected_kcal, places=6)


# ---------------------------------------------------------------------------
# Cohérence prévision (`energy_from_profile`) vs mesure (`energy_from_samples`)
# ---------------------------------------------------------------------------

class TestProfileVsSamplesConsistency(unittest.TestCase):
    def test_constant_grade_and_speed_agree_within_one_percent(self):
        """Un parcours SYNTHÉTIQUE à vitesse et pente constantes (8 %, 3 m/s,
        60 échantillons de 5 s -> 900 m) doit donner un kcal quasi identique
        calculé par les deux voies : `energy_from_samples` (pente recalculée
        par fenêtre glissante) et `energy_from_profile` (pente EXACTE
        fournie). L'écart résiduel vient du LISSAGE DE BORD
        (`arc_elevation.grade_series` : les tout premiers/derniers
        échantillons n'ont pas assez de distance de part et d'autre pour une
        fenêtre complète et retombent à pente `None` -> traités comme un plat,
        voir `ASSUMPTIONS['missing_elevation']`) — PAS d'un défaut d'intégration
        temporelle (déjà exacte, voir `TestEnergyFromSamples`). Tolérance 1 %."""
        speed, grade, n, dt = 3.0, 0.08, 60, 5.0
        samples = _flat_samples(n=n, dt=dt, speed=speed, grade=grade)
        total_distance_m = speed * dt * n
        from_samples = NRG.energy_from_samples(samples, 70.0)
        from_profile = NRG.energy_from_profile(
            [{"distance_m": total_distance_m, "grade": grade, "speed_ms": speed}], 70.0)
        self.assertGreater(from_samples["kcal"], 0.0)
        self.assertAlmostEqual(from_samples["kcal"], from_profile["kcal"],
                                delta=0.01 * from_profile["kcal"])


# ---------------------------------------------------------------------------
# Enchaînement RÉEL arc_race_pacing : parse_gpx -> segment_course ->
# predict_segments -> energy_from_profile
# ---------------------------------------------------------------------------

def _generic_bins() -> list:
    """Paniers `bins` minimaux (format `arc_slope_model.fit_slope_model`),
    UNIQUEMENT génériques (aucune donnée personnelle) — suffisant pour faire
    tourner `predict_segments` de bout en bout sans dépendre d'un historique
    d'activités personnel (hors de portée d'un test palier D isolé)."""
    bins = []
    for lo, hi, label in SL.GRADE_BINS:
        mid = (lo + hi) / 2.0 if lo > float("-inf") and hi < float("inf") else (lo if hi == float("inf") else hi)
        flat_speed = 2.8
        factor = SL.G.gap_factor(mid)
        speed = flat_speed if not factor else flat_speed / factor
        bins.append({"grade_lo": lo, "grade_hi": hi, "grade_mid": mid, "label": label,
                     "speed_ms": speed, "ci_low_speed_ms": speed * 0.9, "ci_high_speed_ms": speed * 1.1,
                     "hr_bpm": None, "source": "generic", "n_samples": 0, "n_activities": 0,
                     "effective_time_s": 0.0, "run_share": None})
    return bins


class TestRealRacePacingPipeline(unittest.TestCase):
    def setUp(self):
        if not GPX_FIXTURE.exists():
            self.skipTest(f"fixture GPX absente : {GPX_FIXTURE}")

    def test_parse_segment_predict_energy_end_to_end(self):
        """Enchaînement RÉEL, sans mock : `arc_race_pacing.parse_gpx` ->
        `segment_course` (garde `_profile`) -> `predict_segments` (rend
        `predicted_time_s`, RETIRE `_profile`) -> l'appelant recombine les
        deux (comme le fait `course-strategist`, `scripts/arc_race_pacing.py`) ->
        `energy_from_profile`. Prouve que le format de sortie RÉEL de
        `predict_segments` est bien consommable, pas seulement un format
        `{distance_m, grade, speed_ms}` idéalisé."""
        pts = RP.parse_gpx(GPX_FIXTURE)
        segments = RP.segment_course(pts)
        self.assertGreater(len(segments), 0)
        bins = _generic_bins()
        predicted = RP.predict_segments(segments, bins)
        self.assertEqual(len(predicted), len(segments))

        # Recombinaison : le `_profile` de `segment_course` (retiré par
        # `predict_segments`) est réattaché par index à la sortie publique de
        # `predict_segments` — c'est la responsabilité de l'APPELANT (voir
        # `ASSUMPTIONS["race_pacing_integration"]`), jamais d'`energy_from_profile`
        # lui-même (qui reste indépendant d'`arc_race_pacing`).
        combined = [{**pred, "_profile": seg["_profile"]} for seg, pred in zip(segments, predicted)]

        result = NRG.energy_from_profile(combined, weight_kg=70.0, scenario="realistic")
        self.assertGreater(result["kcal"], 0.0)
        self.assertGreater(result["time_s"], 0.0)
        # Chaque segment doté d'un temps prédit réaliste doit avoir résolu une
        # vitesse (pas de "no_speed" quand `predicted_time_s['realistic']`
        # existe) — un segment "no_model"/sans vitesse générique reste toléré
        # (reason_code renseigné), mais pas la majorité sur ce jeu de paniers
        # entièrement génériques.
        no_speed_segments = [s for s in result["segments"] if s["reason_code"] == "no_speed"]
        self.assertLess(len(no_speed_segments), len(result["segments"]))

    def test_without_profile_reattached_still_resolves_average_speed(self):
        """Sans réattacher `_profile` (appelant qui ignore la limite connue),
        `energy_from_profile` retombe sur `distance_m`/`grade_mean_pct` du
        segment public de `predict_segments` — dégradé mais jamais un échec."""
        pts = RP.parse_gpx(GPX_FIXTURE)
        segments = RP.segment_course(pts)
        bins = _generic_bins()
        predicted = RP.predict_segments(segments, bins)
        result = NRG.energy_from_profile(predicted, weight_kg=70.0, scenario="realistic")
        self.assertGreaterEqual(result["kcal"], 0.0)


# ---------------------------------------------------------------------------
# Écart modèle vs Garmin
# ---------------------------------------------------------------------------

class TestDeltaPct(unittest.TestCase):
    def test_delta_pct_basic(self):
        self.assertAlmostEqual(NRG.delta_pct(115.0, 100.0), 15.0, places=6)
        self.assertAlmostEqual(NRG.delta_pct(85.0, 100.0), -15.0, places=6)

    def test_delta_pct_none_when_missing(self):
        self.assertIsNone(NRG.delta_pct(None, 100.0))
        self.assertIsNone(NRG.delta_pct(100.0, None))
        self.assertIsNone(NRG.delta_pct(100.0, 0.0))

    def test_delta_flag_threshold(self):
        self.assertEqual(NRG.DELTA_ALERT_PCT, 15.0)
        self.assertFalse(NRG.delta_flag(14.9))
        self.assertTrue(NRG.delta_flag(15.1))
        self.assertTrue(NRG.delta_flag(-20.0))
        self.assertIsNone(NRG.delta_flag(None))


# ---------------------------------------------------------------------------
# Calibration personnelle (prévisions uniquement) — `calibration_band_report`.
# ---------------------------------------------------------------------------

class TestCalibrationBandReport(unittest.TestCase):
    def test_below_min_n_is_insufficient_even_with_a_clear_bias(self):
        """14 ratios (juste sous `CALIBRATION_MIN_N`, 15), tous à 1.30 : un
        biais net et sans dispersion, mais l'échantillon reste trop petit —
        `status="insufficient"`, facteur 1.0 (jamais appliqué), MAIS
        `ratio_median`/`ratio_iqr` restent rendus (diagnostic utile même sous
        le seuil). Aucune valeur aberrante ici (toutes identiques) : `n`
        reste le nombre de ratios reçus."""
        ratios = [1.30] * (NRG.CALIBRATION_MIN_N - 1)
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["n"], 14)
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["factor"], 1.0)
        self.assertAlmostEqual(result["ratio_median"], 1.30, places=3)
        self.assertEqual(result["ratio_iqr"], 0.0)

    def test_median_within_band_is_not_needed(self):
        """15 ratios, médiane à 1.03 (3 %, sous `CALIBRATION_NOT_NEEDED_BAND_PCT`,
        5 %) : le modèle est déjà fidèle sur ce panier, `status="not_needed"`,
        facteur 1.0 — jamais 1.03 (calibrer sur du bruit serait une fausse
        précision)."""
        ratios = [1.03] * NRG.CALIBRATION_MIN_N
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["status"], "not_needed")
        self.assertEqual(result["factor"], 1.0)
        self.assertAlmostEqual(result["ratio_median"], 1.03, places=3)

    def test_median_outside_band_is_applied_at_the_median_value(self):
        """15 ratios à 1.10 (10 %, hors bande) : `status="applied"`, facteur =
        la médiane elle-même (dans la plage prudente, aucun bornage requis
        ici)."""
        ratios = [1.10] * NRG.CALIBRATION_MIN_N
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["status"], "applied")
        self.assertAlmostEqual(result["factor"], 1.10, places=3)

    def test_factor_is_clamped_to_the_prudent_range(self):
        """Un ratio médian extrême (1.5, largement hors [0.8, 1.2]) donne un
        facteur BORNÉ à `CALIBRATION_FACTOR_MAX` (1.2), jamais extrapolé —
        même chose côté bas avec 0.5 -> `CALIBRATION_FACTOR_MIN` (0.8)."""
        high = NRG.calibration_band_report([1.5] * NRG.CALIBRATION_MIN_N)
        self.assertEqual(high["status"], "applied")
        self.assertEqual(high["factor"], NRG.CALIBRATION_FACTOR_MAX)
        low = NRG.calibration_band_report([0.5] * NRG.CALIBRATION_MIN_N)
        self.assertEqual(low["status"], "applied")
        self.assertEqual(low["factor"], NRG.CALIBRATION_FACTOR_MIN)

    def test_empty_ratios_is_insufficient_with_none_stats(self):
        """Aucun ratio du tout (panier sans séance éligible dans la fenêtre) :
        `status="insufficient"`, `n=0`, `ratio_median`/`ratio_iqr` à `None`
        (jamais 0.0, qui laisserait croire à un accord parfait mesuré)."""
        result = NRG.calibration_band_report([])
        self.assertEqual(result, {"n": 0, "ratio_median": None, "ratio_iqr": None,
                                   "status": "insufficient", "factor": 1.0})

    def test_single_ratio_has_no_iqr(self):
        """Un seul ratio (n=1, de toute façon insuffisant) : `ratio_iqr` reste
        `None` (aucun quartile calculable sur un point), jamais 0.0."""
        result = NRG.calibration_band_report([1.10])
        self.assertEqual(result["n"], 1)
        self.assertIsNone(result["ratio_iqr"])
        self.assertAlmostEqual(result["ratio_median"], 1.10, places=3)

    def test_iqr_reflects_real_dispersion(self):
        """Un panier dispersé mais SANS aberrante au sens de la bande relative
        (ratios de 0.95 à 1.25, médiane 1.10 — écart relatif max 13,6 %, sous
        `CALIBRATION_OUTLIER_RELATIVE_BAND_PCT`, 15 %) doit rendre un IQR
        strictement positif SANS qu'aucun ratio ne soit exclu — pas seulement
        une médiane, une vraie mesure de dispersion, cohérente avec
        `statistics.quantiles`."""
        ratios = [0.95, 0.95, 1.0, 1.0, 1.05, 1.05, 1.1, 1.1, 1.1, 1.15, 1.15,
                  1.2, 1.2, 1.25, 1.25]
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["n"], 15)  # aucune exclusion : toutes sous la bande relative
        self.assertGreater(result["ratio_iqr"], 0.0)

    # -------------------------------------------------------------------
    # Correctif de revue de code (BLOQUANT) : exclusion RELATIVE à la médiane
    # du panier, jamais au `flag` par séance (|écart| > DELTA_ALERT_PCT).
    # -------------------------------------------------------------------

    def test_a_real_consistent_bias_is_applied_despite_every_session_being_individually_flagged(self):
        """Reproduit le bug corrigé : ~20 séances à ratio 1,20 ± bruit — CHAQUE
        séance individuelle dépasserait le seuil d'alerte PAR SÉANCE
        (`arc_energy.delta_flag`, |écart| > 15 %, delta_pct ≈ -16,7 % à ratio
        1,20), mais le PANIER ENTIER est cohérent (aucune aberrante) : doit
        rester `status="applied"`, `n` proche de 20 (aucune exclusion), facteur
        ≈ 1,2 — jamais `insufficient` à cause d'un filtre sur `flag`."""
        import random
        rng = random.Random(20260928)
        ratios = [1.20 + rng.uniform(-0.02, 0.02) for _ in range(20)]
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["n"], 20)
        self.assertAlmostEqual(result["factor"], 1.20, delta=0.02)

    def test_a_minority_of_outliers_is_excluded_from_a_consistent_majority(self):
        """20 séances cohérentes à ratio ≈ 1,20, PLUS 2 séances clairement
        aberrantes (ratio 2,0, ex. capteur FC manifestement défaillant) : les 2
        aberrantes sont EXCLUES (n=20, pas 22), le facteur final reste proche
        de 1,2 — jamais tiré vers le haut par les 2 aberrantes."""
        import random
        rng = random.Random(20260929)
        ratios = [1.20 + rng.uniform(-0.02, 0.02) for _ in range(20)] + [2.0, 2.0]
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["n"], 20)
        self.assertAlmostEqual(result["factor"], 1.20, delta=0.02)

    def test_ratio_1_35_is_bounded_to_the_factor_max(self):
        """Panier cohérent à ratio 1,35 (hors [0,8 ; 1,2], mais AUCUNE
        aberrante entre elles — toutes proches de la même valeur) : le facteur
        est BORNÉ à `CALIBRATION_FACTOR_MAX` (1,2), jamais 1,35."""
        ratios = [1.35] * NRG.CALIBRATION_MIN_N
        result = NRG.calibration_band_report(ratios)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["n"], NRG.CALIBRATION_MIN_N)
        self.assertEqual(result["factor"], NRG.CALIBRATION_FACTOR_MAX)

    def test_flagging_by_absolute_delta_would_have_wrongly_produced_insufficient(self):
        """Preuve DIRECTE que l'ancien mécanisme (exclusion par `flag`, |écart|
        > 15 %) aurait fait tomber ce panier en `insufficient` : à ratio 1,20,
        `arc_energy.delta_pct` vaut environ -16,7 % (|·| > `DELTA_ALERT_PCT`) —
        chaque séance serait donc `flag=True` et TOUTES auraient été exclues
        par l'ancien filtre (n=0). Le nouveau mécanisme (relatif à la médiane
        du panier) ne les exclut PAS : c'est justement le comportement attendu
        documenté par le correctif."""
        ratio = 1.20
        # model_kcal=100 (arbitraire), garmin_kcal=100*ratio -> delta_pct = (model-garmin)/garmin*100
        delta_pct = (100.0 - 100.0 * ratio) / (100.0 * ratio) * 100.0
        self.assertTrue(NRG.delta_flag(delta_pct))  # chaque séance serait individuellement "flag"
        result = NRG.calibration_band_report([ratio] * NRG.CALIBRATION_MIN_N)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["n"], NRG.CALIBRATION_MIN_N)  # jamais exclu malgré le flag individuel


# ---------------------------------------------------------------------------
# Non-régression : séances synthétiques de `tests.lib.synthetic`
# ---------------------------------------------------------------------------

class TestSyntheticNonRegression(unittest.TestCase):
    def test_sample_session_energy_frozen(self):
        """Séance synthétique déterministe (graine fixe, une montée + une
        descente) : valeur figée après calcul initial — toute évolution
        future des coefficients/seuils DOIT régénérer cette valeur
        intentionnellement (voir `arc_energy.MODEL_ID`, à incrémenter en même
        temps)."""
        records, _truth = sample_session(
            seed=42, duration_s=1800, base_speed_ms=2.8,
            segments=((300.0, 200.0, 8.0), (700.0, 200.0, -8.0)), noise=False,
        )
        samples = S.normalise_records(records)
        result = NRG.energy_from_samples(samples, 70.0)
        self.assertGreater(result["kcal"], 0.0)
        self.assertEqual(result["model_id"], NRG.MODEL_ID)
        self.assertFalse(result["elevation_missing"])
        # Valeur figée, régénérée pour ce MODEL_ID (voir docstring de la classe).
        self.assertAlmostEqual(result["kcal"], _FROZEN_UPHILL_DOWNHILL_KCAL, delta=1.0)

    def test_sample_session_with_walked_climb_and_stop_downsampled(self):
        """Séance synthétique avec une MONTÉE MARCHÉE (vitesse imposée sous
        WALK_SPEED_MS sur le segment) et un ARRÊT franc, ré-échantillonnée à
        la résolution 5 s de l'index (`arc_samples.downsample`) — non-
        régression sur un cas combinant marche, arrêt et sous-échantillonnage
        réel (pas seulement un plat continu)."""
        n_stop = 30

        def _slope_factor(grade_pct: float) -> float:
            # Marche imposée en montée (vitesse cible bien sous 1.8 m/s),
            # course normale ailleurs.
            if grade_pct > 0:
                return 1.4 / 2.8  # ~1.4 m/s en montée -> régime marche
            return 1.0

        records, _truth = sample_session(
            seed=11, duration_s=1200, base_speed_ms=2.8,
            segments=((100.0, 300.0, 15.0),), slope_factor_fn=_slope_factor, noise=False,
        )
        # Ajoute un arrêt franc (30 échantillons à vitesse nulle) après la séance.
        last = records[-1]
        stop_records = [{"t_s": last["t_s"] + 1 + i, "distance_m": last["distance_m"],
                          "altitude_m": last["altitude_m"], "hr_bpm": 90.0, "speed_ms": 0.0,
                          "cadence_spm": 0.0} for i in range(n_stop)]
        samples = S.normalise_records(records + stop_records)
        samples = S.downsample(samples, resolution_s=5)
        result = NRG.energy_from_samples(samples, 70.0)
        # Valeurs figées (régénérées pour ce MODEL_ID) — voir
        # `test_sample_session_energy_frozen` pour la même discipline.
        self.assertAlmostEqual(result["kcal"], 228.1, delta=1.0)
        self.assertAlmostEqual(result["breakdown"]["walk"]["seconds"], 220.0, delta=5.0)
        self.assertAlmostEqual(result["breakdown"]["stopped"]["seconds"], 20.0, delta=5.0)
        self.assertEqual(result["model_id"], NRG.MODEL_ID)


# Valeur figée : régénérée une fois pour `MODEL_ID = "re3-walk/2"` (coût
# debout 1,44 W/kg, bornage par régime, bande de plat, lissage de
# classification, intégration temporelle réelle) — voir le test associé.
_FROZEN_UPHILL_DOWNHILL_KCAL = 349.5


if __name__ == "__main__":
    unittest.main()
