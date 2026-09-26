"""Palier D — identité de montée entre séances (#49, épopée #21).

Toutes les coordonnées de ce fichier sont FICTIVES, choisies en pleine mer (Pacifique Sud,
loin de toute côte) — voir `tests/lint/test_synthetic_no_real_data.py::SAFE_LAT_RANGE`/
`SAFE_LON_RANGE`, qui vérifie qu'aucun test du dépôt n'utilise une coordonnée en dehors de
cette zone : aucune trace GPS de test ne doit pouvoir ressembler à un lieu réel.

Familles de tests :
- `arc_climb_match.ClimbSegmentIndex`/`haversine_m`/`progression_pct` : appariement
  GPS robuste aux petites variations de trace (bruit ~ glissement de bord documenté par
  #46, y compris une mesure seedée à σ ≈ 2/4 m après mise à l'échelle de la tolérance),
  sens inverse jamais apparié, deux montées de profil proche mais à des lieux différents
  jamais appariées, repli sans GPS conservateur (ambiguïté -> pas de match), adoption d'un
  segment sans GPS par un candidat GPS, bucketing spatial (pas de balayage complet).
- `arc_climb_match.hr_drift_bpm_per_100m` : dérive FC par 100 m de D+.
- `arc_index` : `compute_metrics` relie deux séances synthétiques sur la même montée à
  un seul `climb_segment` (id DÉTERMINISTE, stable même si une activité plus ancienne est
  indexée ensuite), avec une progression de 5 % correctement rapportée sur l'occurrence la
  plus rapide, guard de nettoyage transactionnel (par activité, y compris quand une
  activité PRÉCÉDENTE a déjà réussi) sur les nouvelles colonnes/table.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_climb as VC  # noqa: E402
import arc_climb_match as VM  # noqa: E402
import arc_index as I  # noqa: E402

from tests.data.test_arc_climb import Workspace  # noqa: E402

# Coordonnées fictives : Pacifique Sud, loin de toute côte (voir docstring du module).
BASE_LAT, BASE_LON = -40.0, -135.0

# ---------------------------------------------------------------------------
# arc_climb_match : appariement pur, sans SQLite
# ---------------------------------------------------------------------------


BASE_CLIMB = {
    "start_lat": BASE_LAT, "start_lon": BASE_LON,
    "end_lat": BASE_LAT + 0.01, "end_lon": BASE_LON + 0.01,
    "gain_m": 300.0, "distance_m": 3000.0, "avg_grade": 0.10, "grade_class": "5-10%",
    "location": "Cirque Fictif",
}


class TestHaversine(unittest.TestCase):
    def test_zero_distance_for_identical_points(self):
        self.assertEqual(VM.haversine_m(BASE_LAT, BASE_LON, BASE_LAT, BASE_LON), 0.0)

    def test_one_degree_of_longitude_at_equator_is_about_111km(self):
        # Fait géométrique pur (pas une trace de séance) : la circonférence terrestre à
        # l'équateur, sans rapport avec un lieu réellement enregistré.
        d = VM.haversine_m(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(d, 111_320, delta=500)


class TestGpsMatchingRobustToSmallTraceVariation(unittest.TestCase):
    """Critère d'acceptation #49 : « correspondance de montée robuste aux petites
    variations de trace » — voir #46, ASSUMPTIONS['merge'] pour le glissement de bord
    documenté à fort bruit altimétrique (jusqu'à quelques dizaines de mètres)."""

    def setUp(self):
        self.index = VM.ClimbSegmentIndex()
        self.seg = self.index.add(dict(BASE_CLIMB, garmin_activity_id=1, climb_idx=1))

    def test_boundary_slide_within_tolerance_still_matches(self):
        # ~80 m de glissement sur le départ (voisinage du seuil de bruit documenté par
        # #46) : bien sous la tolérance effective (150 m plancher, voir
        # `arc_climb_match._position_tolerance_m`).
        shifted = dict(BASE_CLIMB, start_lat=BASE_LAT + 0.00072, start_lon=BASE_LON)
        match = self.index.match(shifted)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], self.seg["id"])

    def test_shift_beyond_tolerance_does_not_match(self):
        far = dict(BASE_CLIMB, start_lat=BASE_LAT + 0.01, start_lon=BASE_LON + 0.01,
                   end_lat=BASE_LAT + 0.02, end_lon=BASE_LON + 0.02)
        self.assertIsNone(self.index.match(far))

    def test_second_occurrence_is_registered_under_the_same_id(self):
        shifted = dict(BASE_CLIMB, start_lat=BASE_LAT + 0.0005, start_lon=BASE_LON + 0.0005)
        match = self.index.match(shifted)
        self.assertEqual(match["id"], self.seg["id"])
        self.assertEqual(len(self.index.segments), 1)  # aucun nouveau segment créé


def _flat_climb_flat_samples_gauss(*, lead_m, climb_gain_m, climb_dist_m, trail_m,
                                    speed_ms=2.0, resolution_s=5, hr_bpm=150.0,
                                    rng=None, sigma_m=0.0):
    """Même construction que `tests.data.test_arc_climb._flat_climb_flat_samples`, mais
    bruit GAUSSIEN (`rng.gauss(0, sigma_m)`, un `sigma_m` est alors un VRAI écart-type —
    voir #46, ASSUMPTIONS["trim"], « σ ≈ 2 m » pour le niveau de bruit résiduel réaliste
    après lissage) plutôt qu'uniforme, pour une mesure directement comparable à ce
    vocabulaire. Position GPS ajoutée : déplacement linéaire le long de `bearing` depuis
    `(BASE_LAT, BASE_LON)`, proportionnel à la distance parcourue."""
    out = []
    t = 0.0
    dist = 0.0
    alt = 0.0

    def emit():
        a = alt + (rng.gauss(0, sigma_m) if rng and sigma_m else 0.0)
        out.append({"t_s": t, "distance_m": dist, "altitude_m": a,
                     "speed_ms": speed_ms, "hr_bpm": hr_bpm, "cadence_spm": 160.0})

    n_lead = int(lead_m / speed_ms / resolution_s)
    n_climb = int(climb_dist_m / speed_ms / resolution_s)
    n_trail = int(trail_m / speed_ms / resolution_s)
    step_dist = speed_ms * resolution_s
    step_alt = climb_gain_m / n_climb if n_climb else 0.0
    emit()
    for _ in range(n_lead):
        t += resolution_s
        dist += step_dist
        emit()
    for _ in range(n_climb):
        t += resolution_s
        dist += step_dist
        alt += step_alt
        emit()
    for _ in range(n_trail):
        t += resolution_s
        dist += step_dist
        emit()
    total = out[-1]["distance_m"] or 1.0
    bearing = (0.02, 0.0)
    for rec in out:
        frac = rec["distance_m"] / total
        rec["lat_deg"] = BASE_LAT + bearing[0] * frac
        rec["lon_deg"] = BASE_LON + bearing[1] * frac
    return out


def _noisy_climb_and_endpoints(seed: int, sigma_m: float):
    rng = random.Random(seed)
    samples = _flat_climb_flat_samples_gauss(lead_m=500, climb_gain_m=300.0, climb_dist_m=3600.0,
                                              trail_m=500, speed_ms=2.0, rng=rng, sigma_m=sigma_m)
    climbs = VC.detect_climbs(samples)
    if not climbs:
        return None, None
    c = climbs[0]
    return c, VM.climb_endpoints(samples, c)


class TestPositionToleranceScalesWithClimbLength(unittest.TestCase):
    """Revue de code #49, BLOQUANT : un plancher de tolérance FIXE (150 m) s'est révélé
    insuffisant sur une montée longue (3 560 m/300 m) à bruit altimétrique réaliste — mesuré
    sur 200 tirages indépendants (script de mesure, voir `arc_climb_match.py`, commentaire de
    `CLIMB_MATCH_POSITION_TOLERANCE_M`) : 184/200 appariés à σ ≈ 2 m (glissement de sommet
    jusqu'à 256 m), 100/200 à σ ≈ 4 m (jusqu'à 290 m) — la mise à l'échelle
    (`CLIMB_MATCH_POSITION_TOLERANCE_FRAC`, 10 % de la longueur) appariait 200/200 aux deux
    niveaux sur le même jeu de tirages. Reproduit ici avec des graines FIXES (déterministe,
    jamais aléatoire en CI) sur un sous-ensemble de ces mêmes tirages."""

    def test_seeded_pairs_at_sigma_2m_all_match_with_scaled_tolerance(self):
        index = VM.ClimbSegmentIndex()
        first_c, first_ep = _noisy_climb_and_endpoints(2, 2.0)
        self.assertIsNotNone(first_ep, "aucune montée détectée pour la graine de référence")
        seg = index.add({
            "start_lat": first_ep["start_lat"], "start_lon": first_ep["start_lon"],
            "end_lat": first_ep["end_lat"], "end_lon": first_ep["end_lon"],
            "gain_m": first_c["gain_m"], "distance_m": first_c["distance_m"],
            "avg_grade": first_c["avg_grade"], "grade_class": first_c["grade_class"],
            "location": None, "garmin_activity_id": 1, "climb_idx": 1,
        })
        unmatched = []
        for seed in range(3, 100):  # tirages indépendants supplémentaires (inclut la graine 77,
            # qui dépasse 150 m au sommet sans mise à l'échelle — voir le test négatif ci-dessous)
            c, ep = _noisy_climb_and_endpoints(seed, 2.0)
            if c is None or ep is None:
                unmatched.append((seed, "aucune montée détectée"))
                continue
            candidate = {
                "start_lat": ep["start_lat"], "start_lon": ep["start_lon"],
                "end_lat": ep["end_lat"], "end_lon": ep["end_lon"],
                "gain_m": c["gain_m"], "distance_m": c["distance_m"],
                "avg_grade": c["avg_grade"], "grade_class": c["grade_class"], "location": None,
            }
            match = index.match(candidate)
            if match is None or match["id"] != seg["id"]:
                unmatched.append((seed, "non apparié"))
        self.assertEqual(unmatched, [], f"tirages non appariés malgré la mise à l'échelle : {unmatched}")

    def test_fixed_150m_tolerance_alone_would_have_missed_at_least_one_of_these_pairs(self):
        """Preuve NÉGATIVE (revue de code #49) : sans mise à l'échelle, au moins un des
        tirages ci-dessus dépasse 150 m sur le départ OU le sommet — la mise à l'échelle
        n'est pas cosmétique, elle change réellement l'issue de l'appariement."""
        _, base_ep = _noisy_climb_and_endpoints(2, 2.0)
        self.assertIsNotNone(base_ep)
        exceeds_fixed = False
        for seed in range(3, 100):
            c, ep = _noisy_climb_and_endpoints(seed, 2.0)
            if c is None or ep is None:
                continue
            d_start = VM.haversine_m(base_ep["start_lat"], base_ep["start_lon"], ep["start_lat"], ep["start_lon"])
            d_summit = VM.haversine_m(base_ep["end_lat"], base_ep["end_lon"], ep["end_lat"], ep["end_lon"])
            if d_start > VM.CLIMB_MATCH_POSITION_TOLERANCE_M or d_summit > VM.CLIMB_MATCH_POSITION_TOLERANCE_M:
                exceeds_fixed = True
                break
        self.assertTrue(exceeds_fixed, "aucun tirage ne dépasse 150 m : le jeu de graines ne prouve plus rien, "
                                        "en choisir un autre")


class TestReverseDirectionNeverMatches(unittest.TestCase):
    """Critère d'acceptation #49 : « la descendre n'est pas la même montée — ascension
    uniquement » — voir ASSUMPTIONS['direction']."""

    def test_swapped_start_and_summit_creates_a_new_segment(self):
        index = VM.ClimbSegmentIndex()
        seg = index.add(dict(BASE_CLIMB, garmin_activity_id=1, climb_idx=1))
        reversed_climb = dict(
            BASE_CLIMB,
            start_lat=BASE_CLIMB["end_lat"], start_lon=BASE_CLIMB["end_lon"],
            end_lat=BASE_CLIMB["start_lat"], end_lon=BASE_CLIMB["start_lon"],
            garmin_activity_id=2, climb_idx=1,
        )
        match = index.match(reversed_climb)
        self.assertIsNone(match)
        new_seg = index.add(reversed_climb)
        self.assertNotEqual(new_seg["id"], seg["id"])


class TestDifferentPlacesSimilarProfileNeverMatch(unittest.TestCase):
    def test_similar_gain_and_length_at_a_different_place_is_not_matched(self):
        index = VM.ClimbSegmentIndex()
        index.add(dict(BASE_CLIMB, garmin_activity_id=1, climb_idx=1))
        elsewhere = dict(BASE_CLIMB, start_lat=BASE_LAT + 1.5, start_lon=BASE_LON + 1.5,
                          end_lat=BASE_LAT + 1.51, end_lon=BASE_LON + 1.51,
                          location="Autre Cirque Fictif")
        self.assertIsNone(index.match(elsewhere))


class TestFallbackWithoutGps(unittest.TestCase):
    """Repli sans GPS (ASSUMPTIONS['fallback_matching']) : conservateur — n'apparie que
    lieu identique + profil proche, et REFUSE en cas d'ambiguïté plutôt que de deviner."""

    def _no_gps(self, **overrides):
        base = dict(BASE_CLIMB)
        for key in ("start_lat", "start_lon", "end_lat", "end_lon"):
            base[key] = None
        base.update(overrides)
        return base

    def test_same_location_and_close_profile_matches(self):
        index = VM.ClimbSegmentIndex()
        seg = index.add(self._no_gps(garmin_activity_id=1, climb_idx=1))
        candidate = self._no_gps(gain_m=310.0, distance_m=3050.0)
        match = index.match(candidate)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], seg["id"])

    def test_different_location_never_matches(self):
        index = VM.ClimbSegmentIndex()
        index.add(self._no_gps(garmin_activity_id=1, climb_idx=1))
        candidate = self._no_gps(location="Ailleurs Fictif")
        self.assertIsNone(index.match(candidate))

    def test_ambiguous_profile_refuses_to_match(self):
        """Deux montées déjà connues au même lieu, de profil proche l'une de l'autre —
        aucune n'est retenue plutôt qu'un choix arbitraire (documenté, conservateur)."""
        index = VM.ClimbSegmentIndex()
        index.add(self._no_gps(gain_m=300.0, distance_m=3000.0, garmin_activity_id=1, climb_idx=1))
        index.add(self._no_gps(gain_m=305.0, distance_m=3010.0, garmin_activity_id=2, climb_idx=1))
        candidate = self._no_gps(gain_m=302.0, distance_m=3005.0)
        self.assertIsNone(index.match(candidate))

    def test_different_grade_class_never_matches_even_at_same_location(self):
        index = VM.ClimbSegmentIndex()
        index.add(self._no_gps(grade_class="5-10%", garmin_activity_id=1, climb_idx=1))
        candidate = self._no_gps(grade_class="10-15%")
        self.assertIsNone(index.match(candidate))


class TestGpsCandidateAdoptsGpsLessSegment(unittest.TestCase):
    """Revue de code #49, BLOQUANT : sans ce mécanisme, un segment créé SANS GPS (le cas de
    la quasi-totalité du parc existant avant #49) ne pouvait plus jamais être retrouvé par
    une occurrence ULTÉRIEURE avec GPS — l'historique se scindait artificiellement en deux
    segments à la première occurrence géolocalisée."""

    def _no_gps(self, **overrides):
        base = dict(BASE_CLIMB)
        for key in ("start_lat", "start_lon", "end_lat", "end_lon"):
            base[key] = None
        base.update(overrides)
        return base

    def test_gps_candidate_matches_and_upgrades_a_gpsless_segment(self):
        index = VM.ClimbSegmentIndex()
        seg = index.add(self._no_gps(garmin_activity_id=1, climb_idx=1))
        self.assertIsNone(seg["start_lat"])
        gps_candidate = dict(BASE_CLIMB, gain_m=305.0, distance_m=3020.0)
        match = index.match(gps_candidate)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], seg["id"])
        # Le segment a ADOPTÉ la position du candidat.
        self.assertEqual(seg["start_lat"], BASE_CLIMB["start_lat"])
        self.assertEqual(seg["summit_lat"], BASE_CLIMB["end_lat"])

    def test_subsequent_gps_occurrence_then_matches_directly_via_the_grid(self):
        index = VM.ClimbSegmentIndex()
        seg = index.add(self._no_gps(garmin_activity_id=1, climb_idx=1))
        index.match(dict(BASE_CLIMB, gain_m=305.0, distance_m=3020.0))  # adoption
        third = dict(BASE_CLIMB, start_lat=BASE_LAT + 0.0003, start_lon=BASE_LON + 0.0003)
        match = index.match(third)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], seg["id"])

    def test_never_adopts_a_segment_that_already_has_a_different_position(self):
        """Un segment déjà positionné n'est JAMAIS écrasé par le repli (ASSUMPTIONS
        ['fallback_matching']) : deux positions connues et incompatibles ne doivent jamais
        être ignorées au profit du seul lieu."""
        index = VM.ClimbSegmentIndex()
        index.add(dict(BASE_CLIMB, garmin_activity_id=1, climb_idx=1))  # déjà positionné
        far_but_same_location = dict(
            BASE_CLIMB, start_lat=BASE_LAT + 2.0, start_lon=BASE_LON + 2.0,
            end_lat=BASE_LAT + 2.01, end_lon=BASE_LON + 2.01,
        )
        self.assertIsNone(index.match(far_but_same_location))


class TestBucketingIsNotQuadratic(unittest.TestCase):
    """Critère d'acceptation #49 : « appariement efficace — bucketing spatial, pas
    O(n²) ». Un grand nombre de lieux distincts (donc, avec GPS, dans des cellules de
    quadrillage disjointes) : le coût d'un appariement ne doit pas croître de façon
    perceptible avec le nombre total de segments déjà connus."""

    def test_match_cost_does_not_scale_with_total_segment_count(self):
        index = VM.ClimbSegmentIndex()
        n = 4000
        for i in range(n):
            # Grille fine à l'intérieur de la zone fictive (voir docstring du module) :
            # 100 x 40 positions disjointes (au sens du quadrillage, 0,005°) suffisent
            # largement à disperser 4000 segments dans des cellules distinctes.
            lat = -46.0 + (i % 100) * 0.1
            lon = -146.0 + (i // 100) * 0.5
            index.add({"start_lat": lat, "start_lon": lon, "end_lat": lat + 0.01, "end_lon": lon + 0.01,
                       "gain_m": 300.0, "distance_m": 3000.0, "avg_grade": 0.1, "grade_class": "5-10%",
                       "location": f"Cirque Fictif {i}", "garmin_activity_id": i + 1, "climb_idx": 1})
        candidate = dict(BASE_CLIMB)  # jamais ajouté : cellule vide de tout autre segment
        start = time.perf_counter()
        for _ in range(200):
            index.match(candidate)
        elapsed = time.perf_counter() - start
        # Un balayage complet de 4000 segments x 200 tours ferait des centaines de
        # milliers de comparaisons ; le bucketing les évite presque toutes. Seuil large
        # (pas un micro-benchmark de performance absolue, juste une garde contre une
        # régression O(n²) flagrante) — voir ASSUMPTIONS['bucketing'].
        self.assertLess(elapsed, 1.0, f"appariement trop lent ({elapsed:.3f}s / 200) : "
                                       "possible régression O(n) -> O(n²) du bucketing")


class TestProgressionPct(unittest.TestCase):
    def test_five_percent_faster_is_reported_as_positive_five(self):
        self.assertAlmostEqual(VM.progression_pct(1000.0, 950.0), 5.0)

    def test_slower_is_negative(self):
        self.assertLess(VM.progression_pct(1000.0, 1100.0), 0.0)

    def test_no_previous_occurrence_is_none(self):
        self.assertIsNone(VM.progression_pct(None, 950.0))


class TestHrDrift(unittest.TestCase):
    def _samples(self, hr_values):
        return [{"t_s": float(i * 60), "hr_bpm": hr} for i, hr in enumerate(hr_values)]

    def test_rising_hr_gives_positive_drift(self):
        climb = {"start_t_s": 0.0, "end_t_s": 540.0, "gain_m": 300.0}
        # FC monte de 130 à 160 sur 10 points régulièrement espacés.
        samples = self._samples([130 + 3 * i for i in range(10)])
        result = VM.hr_drift_bpm_per_100m(samples, climb)
        self.assertIsNotNone(result["hr_drift_bpm_per_100m"])
        self.assertGreater(result["hr_drift_bpm_per_100m"], 0)
        self.assertGreater(result["hr_last_third_bpm"], result["hr_first_third_bpm"])

    def test_too_small_gain_gives_none(self):
        climb = {"start_t_s": 0.0, "end_t_s": 540.0, "gain_m": 10.0}
        samples = self._samples([140] * 10)
        result = VM.hr_drift_bpm_per_100m(samples, climb)
        self.assertIsNone(result["hr_drift_bpm_per_100m"])

    def test_missing_hr_gives_none(self):
        climb = {"start_t_s": 0.0, "end_t_s": 540.0, "gain_m": 300.0}
        samples = [{"t_s": float(i * 60), "hr_bpm": None} for i in range(10)]
        result = VM.hr_drift_bpm_per_100m(samples, climb)
        self.assertIsNone(result["hr_drift_bpm_per_100m"])


# ---------------------------------------------------------------------------
# arc_index : compute_metrics relie deux séances sur le même segment
# ---------------------------------------------------------------------------


def _climb_with_gps(*, duration_s, gain_m, distance_m, start_lat, start_lon, hr_start=130.0, hr_end=130.0,
                     resolution_s=5, location_bearing=(0.0002, 0.0002)):
    """Montée linéaire (vérité connue, même construction que
    `tests.data.test_arc_climb._linear_climb_samples`) mais avec une trace GPS explicite
    (déplacement linéaire depuis `start_lat`/`start_lon`) et une FC qui varie linéairement
    de `hr_start` à `hr_end` (pour les tests de dérive FC)."""
    n = duration_s // resolution_s + 1
    speed = distance_m / duration_s
    dlat, dlon = location_bearing
    out = []
    for i in range(n):
        t = i * resolution_s
        frac = min(1.0, t / duration_s)
        out.append({
            "t_s": float(t),
            "distance_m": distance_m * frac,
            "altitude_m": gain_m * frac,
            "speed_ms": speed,
            "hr_bpm": hr_start + (hr_end - hr_start) * frac,
            "cadence_spm": 160.0,
            "lat_deg": start_lat + dlat * frac,
            "lon_deg": start_lon + dlon * frac,
        })
    return out


class TestSameClimbAcrossTwoActivities(Workspace):
    GARMIN_A = 90000000491
    GARMIN_B = 90000000492
    GARMIN_C = 90000000493

    def write_fit_gps_climb(self, garmin_id, **kwargs):
        records = _climb_with_gps(**kwargs)
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def test_second_occurrence_5pct_faster_is_matched_and_reported(self):
        # Première séance : 1800 s pour 300 m de D+. Seconde : 5 % plus rapide (1710 s),
        # même trace GPS (mêmes points de départ/sommet, à la tolérance de bruit du
        # bucketing près).
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        self.write_activity(self.GARMIN_B, day="2026-09-20")
        self.write_fit_gps_climb(self.GARMIN_B, duration_s=1710, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        self.index()

        act_a = self.activity_row(self.GARMIN_A)
        act_b = self.activity_row(self.GARMIN_B)
        climb_a = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_a["id"],)).fetchone()
        climb_b = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_b["id"],)).fetchone()

        self.assertIsNotNone(climb_a["segment_id"])
        self.assertEqual(climb_a["segment_id"], climb_b["segment_id"], "même montée -> même segment")
        # Id déterministe (#49, revue de code, BLOQUANT) : dérivé du garmin_activity_id ET
        # de l'index de la montée dans la PREMIÈRE occurrence (A), jamais un compteur.
        self.assertEqual(climb_a["segment_id"], self.GARMIN_A * VM.SEGMENT_ID_CLIMB_MULTIPLIER + 1)
        self.assertIsNone(climb_a["vs_previous_pct"], "première occurrence : rien à comparer")
        self.assertAlmostEqual(climb_b["vs_previous_pct"], 5.0, delta=0.5)
        self.assertAlmostEqual(climb_b["vs_best_pct"], 5.0, delta=0.5)

        segment = self.conn.execute(
            "SELECT * FROM climb_segment WHERE id = ?", (climb_a["segment_id"],)).fetchone()
        self.assertEqual(segment["occurrences"], 2)
        self.assertEqual(segment["best_activity_id"], act_b["id"])

    def test_reverse_direction_is_a_distinct_segment(self):
        # Écart départ<->sommet volontairement bien plus grand que la tolérance
        # d'appariement (150 m plancher) : ~1,1 km de dénivelé horizontal ici, pour que le
        # test distingue sans ambiguïté « départ proche du départ » de « départ proche du
        # sommet » (avec un écart trop petit, les deux tomberaient dans la même tolérance
        # et le test ne prouverait rien).
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON, location_bearing=(0.01, 0.01))
        self.write_activity(self.GARMIN_B, day="2026-09-20")
        # Même segment de terrain gravi dans l'AUTRE sens (départ <-> sommet inversés) :
        # un vrai gain net positif (donc bien une "montée" détectée), mais PAS la même
        # ascension.
        self.write_fit_gps_climb(self.GARMIN_B, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT + 0.01, start_lon=BASE_LON + 0.01,
                                  location_bearing=(-0.01, -0.01))
        self.index()
        act_a = self.activity_row(self.GARMIN_A)
        act_b = self.activity_row(self.GARMIN_B)
        climb_a = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_a["id"],)).fetchone()
        climb_b = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_b["id"],)).fetchone()
        self.assertNotEqual(climb_a["segment_id"], climb_b["segment_id"])

    def test_hr_drift_is_computed_and_stored(self):
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON, hr_start=130.0, hr_end=165.0)
        self.index()
        act = self.activity_row(self.GARMIN_A)
        climb = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchone()
        self.assertIsNotNone(climb["hr_drift_bpm_per_100m"])
        self.assertGreater(climb["hr_drift_bpm_per_100m"], 0)
        self.assertGreater(climb["hr_last_third_bpm"], climb["hr_first_third_bpm"])

    def test_adding_an_older_unrelated_activity_never_changes_an_existing_segment_id(self):
        """Revue de code #49, BLOQUANT : avec un ID de segment séquentiel (assigné dans
        l'ordre de traitement chronologique des activités), indexer une activité plus
        ANCIENNE que celles déjà connues décalait l'id de TOUS les segments créés après
        elle — même sans aucun rapport avec la nouvelle activité. L'id DÉTERMINISTE
        (`garmin_activity_id × MULTIPLIER + climb_idx`) ne dépend d'aucun ordre de
        traitement : ce test l'exerce en indexant d'abord A+B (montée partagée), puis en
        ajoutant une activité C, datée AVANT A, sur une tout autre montée (autre lieu,
        autre profil) — l'id du segment A/B ne doit pas bouger."""
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        self.write_activity(self.GARMIN_B, day="2026-09-20")
        self.write_fit_gps_climb(self.GARMIN_B, duration_s=1710, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        self.index()
        act_a_before = self.activity_row(self.GARMIN_A)
        segment_id_before = self.conn.execute(
            "SELECT segment_id FROM activity_climb WHERE activity_id = ?", (act_a_before["id"],)).fetchone()[0]

        # Activité C : plus ANCIENNE (2026-08-01, avant A/B), une montée SANS RAPPORT
        # (lieu et profil totalement différents, à des coordonnées éloignées).
        self.write_activity(self.GARMIN_C, day="2026-08-01")
        self.write_fit_gps_climb(self.GARMIN_C, duration_s=900, gain_m=100.0, distance_m=1000.0,
                                  start_lat=BASE_LAT + 3.0, start_lon=BASE_LON + 3.0)
        self.index()

        act_a_after = self.activity_row(self.GARMIN_A)
        segment_id_after = self.conn.execute(
            "SELECT segment_id FROM activity_climb WHERE activity_id = ?", (act_a_after["id"],)).fetchone()[0]
        self.assertEqual(segment_id_before, segment_id_after,
                          "l'id du segment A/B a changé après l'ajout d'une activité plus "
                          "ancienne sans rapport : régression de l'id déterministe")

    def test_crash_inside_the_new_matching_code_is_guarded_like_other_detectors(self):
        """Défense en profondeur (#46, 3e passe) déjà exercée par
        `tests.data.test_arc_climb.TestComputeMetricsSurvivesAnUnexpectedDetectorCrash`
        pour `arc_climb.detect_climbs` — ce test prouve qu'elle couvre aussi les
        NOUVELLES colonnes/table de #49 (`segment_id`/`hr_*`/`vs_*`, `climb_segment`) :
        un bug injecté DANS `arc_climb_match.hr_drift_bpm_per_100m` (appelé APRÈS
        l'appariement, donc après un `climb_registry.add` déjà effectué en mémoire)
        ne doit ni planter `index_workspace` en entier, ni laisser une ligne
        `activity_climb`/`climb_segment` orpheline pour l'activité fautive (#49, revue de
        code, BLOQUANT : le rollback transactionnel par activité retire intégralement ce
        qu'elle a mutable en mémoire, plus de résidu possible)."""
        import os
        previous_strict = os.environ.pop("ARC_STRICT_METRICS", None)
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        original = VM.hr_drift_bpm_per_100m

        def _boom(*args, **kwargs):
            raise RuntimeError("bug injecté par le test")

        VM.hr_drift_bpm_per_100m = _boom
        try:
            import io
            import contextlib
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.index()
        finally:
            VM.hr_drift_bpm_per_100m = original
            if previous_strict is None:
                os.environ.pop("ARC_STRICT_METRICS", None)
            else:
                os.environ["ARC_STRICT_METRICS"] = previous_strict
        self.assertIn("bug injecté par le test", stderr.getvalue())
        act = self.activity_row(self.GARMIN_A)
        self.assertIsNone(act["best_climb_vam_elapsed_m_h"])
        rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])
        # Rollback complet (#49, revue de code, BLOQUANT) : plus AUCUNE ligne orpheline dans
        # `climb_segment` — l'unique activité de ce test a échoué, son segment (créé en
        # mémoire avant l'échec de `hr_drift_bpm_per_100m`) doit avoir été entièrement
        # défait.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM climb_segment").fetchone()[0], 0)
        # Une ré-indexation SANS le bug retombe sur un état propre et cohérent.
        self.index()
        act2 = self.activity_row(self.GARMIN_A)
        self.assertIsNotNone(act2["best_climb_vam_elapsed_m_h"])
        rows2 = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act2["id"],)).fetchall()
        self.assertEqual(len(rows2), 1)
        self.assertIsNotNone(rows2[0]["segment_id"])

    def test_crash_on_a_second_activity_never_corrupts_the_first_activitys_segment(self):
        """Extension (#49, revue de code, BLOQUANT) du test ci-dessus à DEUX activités : A
        réussit et enregistre son occurrence AVANT que B (même montée, traitée ensuite dans
        le même passage chronologique) n'échoue — le rollback de B (basé sur SON PROPRE
        point de reprise, pris APRÈS le succès de A) ne doit dégrader ni l'entrée de A dans
        `climb_segment`, ni son occurrence dans `activity_climb`."""
        import os
        previous_strict = os.environ.pop("ARC_STRICT_METRICS", None)
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        self.write_activity(self.GARMIN_B, day="2026-09-20")
        self.write_fit_gps_climb(self.GARMIN_B, duration_s=1710, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        original = VM.hr_drift_bpm_per_100m
        calls = {"n": 0}

        def _boom_on_second_call(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return original(*args, **kwargs)  # A (traitée en premier, 2026-09-10) : OK
            raise RuntimeError("bug injecté par le test")  # B : échoue

        VM.hr_drift_bpm_per_100m = _boom_on_second_call
        try:
            import io
            import contextlib
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.index()
        finally:
            VM.hr_drift_bpm_per_100m = original
            if previous_strict is None:
                os.environ.pop("ARC_STRICT_METRICS", None)
            else:
                os.environ["ARC_STRICT_METRICS"] = previous_strict

        act_a = self.activity_row(self.GARMIN_A)
        act_b = self.activity_row(self.GARMIN_B)
        climb_a_rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_a["id"],)).fetchall()
        climb_b_rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_b["id"],)).fetchall()
        self.assertEqual(len(climb_a_rows), 1, "l'échec de B ne doit pas purger l'occurrence de A")
        self.assertEqual(climb_b_rows, [])
        segments = self.conn.execute("SELECT * FROM climb_segment").fetchall()
        self.assertEqual(len(segments), 1, "un seul segment : celui de A, jamais un résidu de B")
        self.assertEqual(segments[0]["occurrences"], 1, "l'occurrence fantôme de B ne doit pas être comptée")
        self.assertEqual(segments[0]["first_seen_activity_id"], act_a["id"])

    def test_climb_segment_table_purged_and_rebuilt_on_reindex(self):
        """Comme `activity_climb` (#46) : `climb_segment` est recalculée en entier à
        chaque passage, jamais accumulée — réindexer deux fois de suite sans rien
        changer ne double pas les segments."""
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=BASE_LAT, start_lon=BASE_LON)
        self.index()
        self.index()
        count = self.conn.execute("SELECT COUNT(*) FROM climb_segment").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
