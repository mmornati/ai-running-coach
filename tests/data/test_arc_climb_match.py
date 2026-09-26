"""Palier D — identité de montée entre séances (#49, épopée #21).

Familles de tests :
- `arc_climb_match.ClimbSegmentIndex`/`haversine_m`/`progression_pct` : appariement
  GPS robuste aux petites variations de trace (bruit ~ glissement de bord documenté par
  #46), sens inverse jamais apparié, deux montées de profil proche mais à des lieux
  différents jamais appariées, repli sans GPS conservateur (ambiguïté -> pas de match),
  bucketing spatial (pas de balayage complet).
- `arc_climb_match.hr_drift_bpm_per_100m` : dérive FC par 100 m de D+.
- `arc_index` : `compute_metrics` relie deux séances synthétiques sur la même montée à
  un seul `climb_segment` (id stable pour la durée d'un passage), avec une progression
  de 5 % correctement rapportée sur l'occurrence la plus rapide, guard de nettoyage des
  nouvelles colonnes/table sur une activité qui échoue.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_climb_match as VM  # noqa: E402
import arc_index as I  # noqa: E402

from tests.data.test_arc_climb import Workspace  # noqa: E402


# ---------------------------------------------------------------------------
# arc_climb_match : appariement pur, sans SQLite
# ---------------------------------------------------------------------------


BASE_CLIMB = {
    "start_lat": 46.000000, "start_lon": 7.000000,
    "end_lat": 46.010000, "end_lon": 7.010000,
    "gain_m": 300.0, "distance_m": 3000.0, "avg_grade": 0.10, "grade_class": "5-10%",
    "location": "Alpe Fictive",
}


class TestHaversine(unittest.TestCase):
    def test_zero_distance_for_identical_points(self):
        self.assertEqual(VM.haversine_m(46.0, 7.0, 46.0, 7.0), 0.0)

    def test_one_degree_of_longitude_at_equator_is_about_111km(self):
        d = VM.haversine_m(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(d, 111_320, delta=500)


class TestGpsMatchingRobustToSmallTraceVariation(unittest.TestCase):
    """Critère d'acceptation #49 : « correspondance de montée robuste aux petites
    variations de trace » — voir #46, ASSUMPTIONS['merge'] pour le glissement de bord
    documenté à fort bruit altimétrique (jusqu'à quelques dizaines de mètres)."""

    def setUp(self):
        self.index = VM.ClimbSegmentIndex()
        self.seg = self.index.add(BASE_CLIMB)

    def test_boundary_slide_within_tolerance_still_matches(self):
        # ~80 m de glissement sur le départ (voisinage du seuil de bruit documenté par
        # #46) : bien sous CLIMB_MATCH_POSITION_TOLERANCE_M (150 m par défaut).
        shifted = dict(BASE_CLIMB, start_lat=46.00072, start_lon=7.00000)
        match = self.index.match(shifted)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], self.seg["id"])

    def test_shift_beyond_tolerance_does_not_match(self):
        far = dict(BASE_CLIMB, start_lat=46.01, start_lon=7.01, end_lat=46.02, end_lon=7.02)
        self.assertIsNone(self.index.match(far))

    def test_second_occurrence_is_registered_under_the_same_id(self):
        shifted = dict(BASE_CLIMB, start_lat=46.0005, start_lon=7.0005)
        match = self.index.match(shifted)
        self.assertEqual(match["id"], self.seg["id"])
        self.assertEqual(len(self.index.segments), 1)  # aucun nouveau segment créé


class TestReverseDirectionNeverMatches(unittest.TestCase):
    """Critère d'acceptation #49 : « la descendre n'est pas la même montée — ascension
    uniquement » — voir ASSUMPTIONS['direction']."""

    def test_swapped_start_and_summit_creates_a_new_segment(self):
        index = VM.ClimbSegmentIndex()
        seg = index.add(BASE_CLIMB)
        reversed_climb = dict(
            BASE_CLIMB,
            start_lat=BASE_CLIMB["end_lat"], start_lon=BASE_CLIMB["end_lon"],
            end_lat=BASE_CLIMB["start_lat"], end_lon=BASE_CLIMB["start_lon"],
        )
        match = index.match(reversed_climb)
        self.assertIsNone(match)
        new_seg = index.add(reversed_climb)
        self.assertNotEqual(new_seg["id"], seg["id"])


class TestDifferentPlacesSimilarProfileNeverMatch(unittest.TestCase):
    def test_similar_gain_and_length_at_a_different_place_is_not_matched(self):
        index = VM.ClimbSegmentIndex()
        index.add(BASE_CLIMB)
        elsewhere = dict(BASE_CLIMB, start_lat=47.5, start_lon=8.5, end_lat=47.51, end_lon=8.51,
                          location="Autre Montagne")
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
        seg = index.add(self._no_gps())
        candidate = self._no_gps(gain_m=310.0, distance_m=3050.0)
        match = index.match(candidate)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], seg["id"])

    def test_different_location_never_matches(self):
        index = VM.ClimbSegmentIndex()
        index.add(self._no_gps())
        candidate = self._no_gps(location="Ailleurs")
        self.assertIsNone(index.match(candidate))

    def test_ambiguous_profile_refuses_to_match(self):
        """Deux montées déjà connues au même lieu, de profil proche l'une de l'autre —
        aucune n'est retenue plutôt qu'un choix arbitraire (documenté, conservateur)."""
        index = VM.ClimbSegmentIndex()
        index.add(self._no_gps(gain_m=300.0, distance_m=3000.0))
        index.add(self._no_gps(gain_m=305.0, distance_m=3010.0))
        candidate = self._no_gps(gain_m=302.0, distance_m=3005.0)
        self.assertIsNone(index.match(candidate))

    def test_different_grade_class_never_matches_even_at_same_location(self):
        index = VM.ClimbSegmentIndex()
        index.add(self._no_gps(grade_class="5-10%"))
        candidate = self._no_gps(grade_class="10-15%")
        self.assertIsNone(index.match(candidate))


class TestBucketingIsNotQuadratic(unittest.TestCase):
    """Critère d'acceptation #49 : « appariement efficace — bucketing spatial, pas
    O(n²) ». Un grand nombre de lieux distincts très éloignés (donc dans des cellules
    de quadrillage disjointes) : le coût d'un appariement ne doit pas croître de façon
    perceptible avec le nombre total de segments déjà connus."""

    def test_match_cost_does_not_scale_with_total_segment_count(self):
        index = VM.ClimbSegmentIndex()
        n = 4000
        for i in range(n):
            lat = -60.0 + (i % 200) * 0.6  # largement dispersés : cellules disjointes
            lon = -170.0 + (i // 200) * 0.6
            index.add({"start_lat": lat, "start_lon": lon, "end_lat": lat + 0.01, "end_lon": lon + 0.01,
                       "gain_m": 300.0, "distance_m": 3000.0, "avg_grade": 0.1, "grade_class": "5-10%",
                       "location": f"Lieu {i}"})
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
                                  start_lat=46.0, start_lon=7.0)
        self.write_activity(self.GARMIN_B, day="2026-09-20")
        self.write_fit_gps_climb(self.GARMIN_B, duration_s=1710, gain_m=300.0, distance_m=3600.0,
                                  start_lat=46.0, start_lon=7.0)
        self.index()

        act_a = self.activity_row(self.GARMIN_A)
        act_b = self.activity_row(self.GARMIN_B)
        climb_a = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_a["id"],)).fetchone()
        climb_b = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act_b["id"],)).fetchone()

        self.assertIsNotNone(climb_a["segment_id"])
        self.assertEqual(climb_a["segment_id"], climb_b["segment_id"], "même montée -> même segment")
        self.assertIsNone(climb_a["vs_previous_pct"], "première occurrence : rien à comparer")
        self.assertAlmostEqual(climb_b["vs_previous_pct"], 5.0, delta=0.5)
        self.assertAlmostEqual(climb_b["vs_best_pct"], 5.0, delta=0.5)

        segment = self.conn.execute(
            "SELECT * FROM climb_segment WHERE id = ?", (climb_a["segment_id"],)).fetchone()
        self.assertEqual(segment["occurrences"], 2)
        self.assertEqual(segment["best_activity_id"], act_b["id"])

    def test_reverse_direction_is_a_distinct_segment(self):
        # Écart départ<->sommet volontairement bien plus grand que la tolérance
        # d'appariement (150 m) : ~1,1 km de dénivelé horizontal ici, pour que le test
        # distingue sans ambiguïté « départ proche du départ » de « départ proche du
        # sommet » (avec un écart trop petit, les deux tomberaient dans la même
        # tolérance et le test ne prouverait rien).
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=46.0, start_lon=7.0, location_bearing=(0.01, 0.01))
        self.write_activity(self.GARMIN_B, day="2026-09-20")
        # Même segment de terrain gravi dans l'AUTRE sens (départ <-> sommet inversés) :
        # un vrai gain net positif (donc bien une "montée" détectée), mais PAS la même
        # ascension.
        self.write_fit_gps_climb(self.GARMIN_B, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=46.01, start_lon=7.01,
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
                                  start_lat=46.0, start_lon=7.0, hr_start=130.0, hr_end=165.0)
        self.index()
        act = self.activity_row(self.GARMIN_A)
        climb = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchone()
        self.assertIsNotNone(climb["hr_drift_bpm_per_100m"])
        self.assertGreater(climb["hr_drift_bpm_per_100m"], 0)
        self.assertGreater(climb["hr_last_third_bpm"], climb["hr_first_third_bpm"])

    def test_crash_inside_the_new_matching_code_is_guarded_like_other_detectors(self):
        """Défense en profondeur (#46, 3e passe) déjà exercée par
        `tests.data.test_arc_climb.TestComputeMetricsSurvivesAnUnexpectedDetectorCrash`
        pour `arc_climb.detect_climbs` — ce test prouve qu'elle couvre aussi les
        NOUVELLES colonnes/table de #49 (`segment_id`/`hr_*`/`vs_*`, `climb_segment`) :
        un bug injecté DANS `arc_climb_match.hr_drift_bpm_per_100m` (appelé APRÈS
        l'appariement, donc après un `climb_registry.add` déjà effectué en mémoire)
        ne doit ni planter `index_workspace` en entier, ni laisser une ligne
        `activity_climb` à moitié écrite pour l'activité fautive."""
        import os
        previous_strict = os.environ.pop("ARC_STRICT_METRICS", None)
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=46.0, start_lon=7.0)
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
        # `climb_segment` est recalculée en entier APRÈS la boucle par activité (voir
        # `compute_metrics`) : une ligne orpheline (segment enregistré en mémoire avant
        # le plantage, sans occurrence dans `activity_climb`) est un résidu inoffensif
        # documenté (voir le commentaire de `compute_metrics` juste avant l'écriture de
        # `climb_segment`), jamais une exception ni une incohérence visible par l'API
        # (qui part toujours de `activity_climb.segment_id`, jamais d'un survol de
        # `climb_segment`) — non ré-affirmé ligne par ligne ici, le point important est
        # que l'appel n'a pas levé et que la ré-indexation suivante retombe propre.
        self.index()
        act2 = self.activity_row(self.GARMIN_A)
        self.assertIsNotNone(act2["best_climb_vam_elapsed_m_h"])
        rows2 = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act2["id"],)).fetchall()
        self.assertEqual(len(rows2), 1)
        self.assertIsNotNone(rows2[0]["segment_id"])

    def test_climb_segment_table_purged_and_rebuilt_on_reindex(self):
        """Comme `activity_climb` (#46) : `climb_segment` est recalculée en entier à
        chaque passage, jamais accumulée — réindexer deux fois de suite sans rien
        changer ne double pas les segments."""
        self.write_activity(self.GARMIN_A, day="2026-09-10")
        self.write_fit_gps_climb(self.GARMIN_A, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                                  start_lat=46.0, start_lon=7.0)
        self.index()
        self.index()
        count = self.conn.execute("SELECT COUNT(*) FROM climb_segment").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
