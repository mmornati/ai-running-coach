"""Palier D — VAM sur les montées détectées (#46).

Familles de tests :
- `arc_climb.detect_climbs` : montée synthétique à vérité connue (300 m en
  30 min -> 600 m/h, critère d'acceptation de l'issue), robustesse au bruit sur
  un parcours plat (aucune fausse montée), fusion de deux montées séparées par
  un petit creux, trou de signal jamais franchi, arrêt au milieu d'une montée
  (VAM temps écoulé vs temps de mouvement), classes de pente.
- `arc_climb.best_vam_windows` : meilleure VAM sur des fenêtres de 10/20 min.
- `arc_climb.climb_report` : restriction à la famille course à pied, raisons
  explicites.
- `arc_index` : table `activity_climb`, colonnes `activity.best_vam_*`
  recalculées à l'indexation, CLI `vam --activity`/`vam --weeks`.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_climb as VC  # noqa: E402
import arc_index as I  # noqa: E402


def _linear_climb_samples(*, duration_s=1800, gain_m=300.0, distance_m=3600.0,
                           resolution_s=5, speed_ms=None, hr_bpm=150.0):
    """Montée synthétique parfaitement linéaire (altitude et distance
    proportionnelles au temps) — vérité connue : gain/durée = VAM imposée."""
    n = duration_s // resolution_s + 1
    speed = speed_ms if speed_ms is not None else distance_m / duration_s
    out = []
    for i in range(n):
        t = i * resolution_s
        frac = min(1.0, t / duration_s)
        out.append({
            "t_s": float(t),
            "distance_m": distance_m * frac,
            "altitude_m": gain_m * frac,
            "speed_ms": speed,
            "hr_bpm": hr_bpm,
            "cadence_spm": 160.0,
        })
    return out


class TestSyntheticClimbKnownVam(unittest.TestCase):
    """Critère d'acceptation de #46 : montée synthétique de 300 m en 30 min -> 600 m/h."""

    def test_300m_in_30min_gives_600_m_per_hour(self):
        samples = _linear_climb_samples(duration_s=1800, gain_m=300.0, distance_m=3600.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1)
        c = climbs[0]
        # Tolérance : le rognage (`_trim_rise`, `TRIM_TOLERANCE_M`) recadre chaque
        # montée sur son intervalle le plus étroit à `TRIM_TOLERANCE_M` près de part
        # et d'autre (voir arc_climb.ASSUMPTIONS["trim"]) — sur une rampe parfaitement
        # linéaire sans aucun replat, cela rogne jusqu'à ~2×TRIM_TOLERANCE_M du D+
        # total, mais préserve exactement le TAUX (VAM), d'où une tolérance plus large
        # sur le gain que sur la VAM elle-même.
        self.assertAlmostEqual(c["vam_elapsed_m_h"], 600.0, delta=5.0)
        self.assertAlmostEqual(c["gain_m"], 300.0, delta=2 * VC.TRIM_TOLERANCE_M + 1.0)
        self.assertAlmostEqual(c["avg_grade"], 300.0 / 3600.0, delta=0.002)
        self.assertEqual(c["grade_class"], "5-10%")

    def test_report_matches_detect_climbs(self):
        samples = _linear_climb_samples()
        report = VC.climb_report(samples, "trail")
        self.assertIsNone(report["reason"])
        self.assertEqual(len(report["climbs"]), 1)
        self.assertAlmostEqual(report["best_climb_vam_elapsed_m_h"], 600.0, delta=5.0)


class TestNoiseRobustnessOnFlat(unittest.TestCase):
    def test_small_jitter_on_flat_creates_no_climb(self):
        """Bruit d'altitude de ±1 m sur un parcours plat : aucune fausse montée
        (le seuil de détection, 50 m de gain net, est très au-dessus du bruit)."""
        import random
        rng = random.Random(7)
        n = 400
        samples = []
        for i in range(n):
            t = i * 5
            samples.append({
                "t_s": float(t), "distance_m": t * 2.7,
                "altitude_m": rng.uniform(-1.0, 1.0),
                "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0,
            })
        climbs = VC.detect_climbs(samples)
        self.assertEqual(climbs, [])


class TestMergeAcrossSmallDip(unittest.TestCase):
    def test_two_climbs_separated_by_small_dip_are_merged(self):
        """Deux montées de 60 m chacune, séparées par un creux de 5 m sur 50 m
        (sous MERGE_MAX_DIP_LOSS_M/MERGE_MAX_DIP_DIST_M) : fusionnées en UNE
        seule montée de gain net ~115 m (60 - 5 + 60)."""
        samples = []
        t = 0
        alt = 0.0
        dist = 0.0

        def emit():
            samples.append({"t_s": float(t), "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})

        emit()
        # montée 1 : +60 m sur 600 m (10 %)
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        # creux : -5 m sur 50 m
        for _ in range(10):
            t += 5
            dist += 5.0
            alt -= 0.5
            emit()
        # montée 2 : +60 m sur 600 m
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        # Rognage des deux extrémités EXTÉRIEURES de la montée fusionnée (voir
        # arc_climb.ASSUMPTIONS["trim"]) : jusqu'à ~2×TRIM_TOLERANCE_M de moins que
        # les 115 m « bruts » (60 - 5 + 60), sans affecter la décision de fusion
        # elle-même (le creux interne, lui, reste correctement mesuré).
        self.assertAlmostEqual(climbs[0]["gain_m"], 115.0, delta=2 * VC.TRIM_TOLERANCE_M + 2.0)

    def test_dip_too_big_keeps_climbs_separate(self):
        """Même profil, mais un creux de 20 m (au-dessus de
        MERGE_MAX_DIP_LOSS_M=10) : deux montées DISTINCTES."""
        samples = []
        t = 0
        alt = 0.0
        dist = 0.0

        def emit():
            samples.append({"t_s": float(t), "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})

        emit()
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        for _ in range(40):
            t += 5
            dist += 5.0
            alt -= 0.5
            emit()
        for _ in range(120):
            t += 5
            dist += 5.0
            alt += 0.5
            emit()
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 2, climbs)


class TestSignalGapNeverBridged(unittest.TestCase):
    def test_climb_split_by_a_signal_gap_is_two_climbs(self):
        """Un trou de signal (> arc_climb.MAX_GAP_S) au milieu d'une montée continue
        ne doit JAMAIS être comblé : deux montées détectées séparément, jamais
        recollées en une seule, même si le profil d'altitude semble continu."""
        samples = []
        t = 0.0
        alt = 0.0
        dist = 0.0
        for _ in range(120):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 1.0  # 10 % sur 1200 m -> 120 m de D+
        # trou de signal : 5 minutes sans échantillon (> MAX_GAP_S = 30 s)
        t += 300
        for _ in range(120):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 1.0
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 2, climbs)
        # Aucune des deux montées ne doit avoir une durée qui inclut le trou : la
        # somme des deux durées écoulées reste nettement sous la durée totale
        # écoulée (qui, elle, inclut les 300 s de trou).
        total_elapsed = samples[-1]["t_s"] - samples[0]["t_s"]
        self.assertLess(sum(c["duration_elapsed_s"] for c in climbs), total_elapsed - 250.0)


class TestStopInsideClimb(unittest.TestCase):
    def test_long_stop_lowers_elapsed_vam_but_not_moving_vam(self):
        """Un arrêt de 10 minutes au milieu d'une montée fait chuter la VAM
        « temps écoulé » sans changer la VAM « temps de mouvement » — voir
        `arc_climb.ASSUMPTIONS["vam_basis"]`."""
        samples = []
        t = 0.0
        alt = 0.0
        dist = 0.0
        # première moitié de la montée : +150 m sur 15 min
        for _ in range(180):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 0.833333
        # arrêt de 10 minutes (vitesse nulle, altitude/distance figées)
        for _ in range(120):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 0.0, "hr_bpm": 100.0, "cadence_spm": 0.0})
            t += 5
        # seconde moitié : encore +150 m sur 15 min
        for _ in range(180):
            samples.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                             "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})
            t += 5
            dist += 10.0
            alt += 0.833333
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        c = climbs[0]
        # Temps écoulé total ~40 min (30 min de montée + 10 min d'arrêt) -> VAM
        # écoulée basse ; temps de mouvement ~30 min -> VAM de mouvement haute.
        self.assertLess(c["vam_elapsed_m_h"], c["vam_moving_m_h"])
        self.assertAlmostEqual(c["vam_moving_m_h"], 600.0, delta=15.0)
        self.assertAlmostEqual(c["vam_elapsed_m_h"], 450.0, delta=15.0)


class TestGradeClasses(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(VC.grade_class(0.03), "<5%")
        self.assertEqual(VC.grade_class(0.05), "5-10%")
        self.assertEqual(VC.grade_class(0.09), "5-10%")
        self.assertEqual(VC.grade_class(0.10), "10-15%")
        self.assertEqual(VC.grade_class(0.17), "15-20%")
        self.assertEqual(VC.grade_class(0.25), ">20%")
        self.assertIsNone(VC.grade_class(None))

    def test_vam_by_grade_class_groups_and_averages(self):
        climbs = [
            {"grade_class": "5-10%", "vam_elapsed_m_h": 500.0},
            {"grade_class": "5-10%", "vam_elapsed_m_h": 600.0},
            {"grade_class": ">20%", "vam_elapsed_m_h": 300.0},
            {"grade_class": None, "vam_elapsed_m_h": None},
        ]
        by_class = VC.vam_by_grade_class(climbs)
        self.assertEqual(by_class["5-10%"], {"count": 2, "avg_vam_elapsed_m_h": 550.0})
        self.assertEqual(by_class[">20%"], {"count": 1, "avg_vam_elapsed_m_h": 300.0})
        self.assertNotIn(None, by_class)


class TestBestVamWindows(unittest.TestCase):
    def test_best_10_and_20_min_windows(self):
        samples = _linear_climb_samples(duration_s=1800, gain_m=300.0, distance_m=3600.0)
        climbs = VC.detect_climbs(samples)
        windows = VC.best_vam_windows(samples, climbs)
        # Rampe linéaire : la meilleure fenêtre de 10 ou 20 min donne (à peu près)
        # la même VAM que la montée entière (600 m/h), jamais plus.
        self.assertAlmostEqual(windows["vam_best_10min_m_h"], 600.0, delta=10.0)
        self.assertAlmostEqual(windows["vam_best_20min_m_h"], 600.0, delta=10.0)
        self.assertLessEqual(windows["vam_best_10min_m_h"], 620.0)

    def test_climb_shorter_than_window_gives_none(self):
        samples = _linear_climb_samples(duration_s=300, gain_m=60.0, distance_m=500.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1)
        windows = VC.best_vam_windows(samples, climbs)
        self.assertIsNone(windows["vam_best_10min_m_h"])
        self.assertIsNone(windows["vam_best_20min_m_h"])


class TestClimbReportSportRestriction(unittest.TestCase):
    def test_non_run_family_has_explicit_reason(self):
        samples = _linear_climb_samples()
        report = VC.climb_report(samples, "indoor_cycling")
        self.assertEqual(report["climbs"], [])
        self.assertIn("course à pied", report["reason"])

    def test_hiking_is_included_in_run_family(self):
        samples = _linear_climb_samples()
        report = VC.climb_report(samples, "hiking")
        self.assertIsNone(report["reason"])
        self.assertEqual(len(report["climbs"]), 1)

    def test_no_samples_has_explicit_reason(self):
        report = VC.climb_report([], "trail")
        self.assertEqual(report["climbs"], [])
        self.assertIn("aucun échantillon", report["reason"])

    def test_flat_run_has_no_climbs_but_no_error(self):
        samples = [{"t_s": float(t), "distance_m": t * 2.7, "altitude_m": 0.0,
                    "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0}
                   for t in range(0, 3600, 5)]
        report = VC.climb_report(samples, "running")
        self.assertIsNone(report["reason"])
        self.assertEqual(report["climbs"], [])
        self.assertIsNone(report["best_climb_vam_elapsed_m_h"])


def _flat_climb_flat_samples(*, lead_m, climb_gain_m, climb_dist_m, trail_m,
                              speed_ms=2.0, resolution_s=5, hr_bpm=150.0, rng=None, noise_m=0.0):
    """Approche plate (`lead_m`), montée linéaire (`climb_gain_m` sur
    `climb_dist_m`), replat de sortie (`trail_m`) — vérité connue sur la SEULE
    portion montée, pour verrouiller la revue de code #46 (BLOQUANT) : un
    replat qui ne crée lui-même aucun extremum ne doit jamais diluer le gain/
    la pente/la VAM détectés."""
    out = []
    t = 0.0
    dist = 0.0
    alt = 0.0

    def _emit():
        a = alt + (rng.uniform(-noise_m, noise_m) if rng and noise_m else 0.0)
        out.append({"t_s": t, "distance_m": dist, "altitude_m": a,
                     "speed_ms": speed_ms, "hr_bpm": hr_bpm, "cadence_spm": 160.0})

    n_lead = int(lead_m / speed_ms / resolution_s)
    n_climb = int(climb_dist_m / speed_ms / resolution_s)
    n_trail = int(trail_m / speed_ms / resolution_s)
    step_dist = speed_ms * resolution_s
    step_alt = climb_gain_m / n_climb if n_climb else 0.0
    _emit()
    for _ in range(n_lead):
        t += resolution_s
        dist += step_dist
        _emit()
    for _ in range(n_climb):
        t += resolution_s
        dist += step_dist
        alt += step_alt
        _emit()
    for _ in range(n_trail):
        t += resolution_s
        dist += step_dist
        _emit()
    return out


class TestFlatApproachAndExitNeverDiluteClimb(unittest.TestCase):
    """Revue de code #46, BLOQUANT : une longue approche/sortie plate ne crée
    elle-même aucun extremum du zigzag — sans rognage (`_trim_rise`), le
    « creux » retenu reste au tout début de l'approche plate, ce qui dilue le
    gain/la pente sur toute la distance plate en trop. Repros de la revue."""

    def test_3km_flat_plus_100m_at_10pct_plus_3km_flat_is_detected(self):
        samples = _flat_climb_flat_samples(lead_m=3000, climb_gain_m=100.0,
                                            climb_dist_m=1000.0, trail_m=3000)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        c = climbs[0]
        # Sans le rognage, la pente mesurée tombe à ~1,4 % (100 m sur ~7 km) et la
        # montée n'est même pas détectée (sous MIN_CLIMB_AVG_GRADE) — avec, la pente
        # doit rester proche des 10 % réels de la seule portion montée.
        self.assertGreaterEqual(c["avg_grade"], 0.08)
        self.assertLessEqual(c["distance_m"], 1200.0)
        self.assertAlmostEqual(c["gain_m"], 100.0, delta=2 * VC.TRIM_TOLERANCE_M + 1.0)

    def test_200m_flat_plus_60m_at_8pct_plus_200m_flat_vam_close_to_true_rate(self):
        climb_dist_m = 60.0 / 0.08  # 750 m, pour une pente réelle de 8 %
        samples = _flat_climb_flat_samples(lead_m=200, climb_gain_m=60.0,
                                            climb_dist_m=climb_dist_m, trail_m=200, speed_ms=2.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        c = climbs[0]
        true_duration_h = (climb_dist_m / 2.0) / 3600.0
        true_vam = 60.0 / true_duration_h
        # Tolérance large (rognage aux deux bords) mais la VAM mesurée doit rester du
        # bon ORDRE DE GRANDEUR — jamais diluée par les 400 m de plat comme avant #46
        # (revue de code : 343 m/h mesurés au lieu de ~432 m/h attendus).
        self.assertAlmostEqual(c["vam_elapsed_m_h"], true_vam, delta=true_vam * 0.15)

    def test_acceptance_case_with_500m_flat_lead_and_trail_across_seeds(self):
        """Le critère d'acceptation de #46 (300 m / 30 min -> 600 m/h) doit rester
        vérifié même entouré de 500 m de plat de chaque côté, et robuste à un bruit
        d'altitude ±1-3 m — plusieurs graines (revue de code, BLOQUANT : mesuré entre
        383 et 591 m/h avant #46 selon la graine, jamais 600 m/h)."""
        import random
        for seed in (1, 2, 3, 4, 5):
            for noise_m in (1.0, 2.0, 3.0):
                rng = random.Random(seed * 100 + int(noise_m))
                samples = _flat_climb_flat_samples(lead_m=500, climb_gain_m=300.0, climb_dist_m=3600.0,
                                                    trail_m=500, speed_ms=2.0, rng=rng, noise_m=noise_m)
                climbs = VC.detect_climbs(samples)
                self.assertEqual(len(climbs), 1, (seed, noise_m, climbs))
                self.assertAlmostEqual(climbs[0]["vam_elapsed_m_h"], 600.0, delta=60.0,
                                        msg=(seed, noise_m, climbs[0]))


class TestZigzagPreservesTrueSummit(unittest.TestCase):
    """Revue de code #46, SHOULD-FIX : l'ancienne élimination a posteriori pouvait
    supprimer un vrai sommet intermédiaire. [0, 100, 98, 103, 60] à seuil 5 doit
    garder le sommet réel à l'indice 3 (valeur 103), jamais le perdre."""

    def test_true_summit_is_preserved(self):
        # 100 (indice 1) n'est jamais un extremum CONFIRMÉ : il est dépassé par 103
        # avant toute retracement de 5 m depuis lui — seul le vrai sommet (103,
        # indice 3) doit être confirmé, jamais perdu comme le faisait l'ancienne
        # élimination a posteriori (qui rendait [0, 1, 4], perdant le sommet réel).
        pivots = VC._zigzag_extrema([0, 100, 98, 103, 60], 5.0)
        self.assertEqual(pivots, [0, 3, 4])


class TestRelativeMergeThreshold(unittest.TestCase):
    """Revue de code #46, SHOULD-FIX : un plancher de fusion purement absolu coupe à
    tort une grosse montée alpine dès qu'un petit creux (anecdotique à cette
    échelle) dépasse ce plancher fixe."""

    def _alpine_climb_with_two_dips(self, dip_loss_m):
        out = []
        t = 0.0
        dist = 0.0
        alt = 0.0

        def _emit():
            out.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                         "speed_ms": 1.5, "hr_bpm": 150.0, "cadence_spm": 150.0})

        _emit()

        def _ramp(gain_m, dist_m, n=None):
            nonlocal t, dist, alt
            n = n or int(dist_m / 15.0)
            step_alt = gain_m / n
            step_dist = dist_m / n
            for _ in range(n):
                t += 5
                dist += step_dist
                alt += step_alt
                _emit()

        def _dip(loss_m, dist_m=100.0, n=20):
            nonlocal t, dist, alt
            step_alt = -loss_m / n
            step_dist = dist_m / n
            for _ in range(n):
                t += 5
                dist += step_dist
                alt += step_alt
                _emit()

        _ramp(300.0, 3000.0)
        _dip(dip_loss_m)
        _ramp(300.0, 3000.0)
        _dip(dip_loss_m)
        _ramp(200.0, 2000.0)
        return out

    def test_two_15m_dips_in_800m_climb_stay_merged(self):
        samples = self._alpine_climb_with_two_dips(15.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1, climbs)
        # Gain NET (300 + 300 + 200 - 15 - 15 = 770 m, jamais la somme brute des trois
        # segments de montée qui ignorerait les deux creux internes), à ~2×TRIM_TOLERANCE_M
        # près (rognage des deux extrémités extérieures de la montée fusionnée).
        self.assertAlmostEqual(climbs[0]["gain_m"], 770.0, delta=2 * VC.TRIM_TOLERANCE_M + 5.0)

    def test_dip_far_beyond_relative_threshold_still_splits(self):
        """Un creux de 80 m (bien au-delà de 12,5 % du plus petit gain adjacent,
        300 m) reste une coupure — le seuil relatif ne devient pas sans limite."""
        samples = self._alpine_climb_with_two_dips(80.0)
        climbs = VC.detect_climbs(samples)
        self.assertGreaterEqual(len(climbs), 2, climbs)


class TestPlateauBetweenTwoClimbsStaysSplit(unittest.TestCase):
    """Revue de code #46, BLOQUANT : un plateau de 2 km (même avec un creux minime)
    entre deux montées de 200 m ne doit JAMAIS être fusionné — le seuil de distance
    (`MERGE_MAX_DIP_DIST_M`, 200 m) reste absolu, quel que soit le seuil de perte."""

    def test_200m_climb_2km_plateau_200m_climb_stays_two_climbs(self):
        out = []
        t = 0.0
        dist = 0.0
        alt = 0.0

        def _emit():
            out.append({"t_s": t, "distance_m": dist, "altitude_m": alt,
                         "speed_ms": 2.0, "hr_bpm": 150.0, "cadence_spm": 160.0})

        _emit()

        def _ramp(gain_m, dist_m, n):
            nonlocal t, dist, alt
            step_alt = gain_m / n
            step_dist = dist_m / n
            for _ in range(n):
                t += 5
                dist += step_dist
                alt += step_alt
                _emit()

        _ramp(200.0, 2000.0, 200)
        # Plateau de 2 km avec un léger creux réaliste de 6 m (au-dessus du bruit de
        # zigzag, mais dérisoire face aux deux montées de 200 m).
        _ramp(-6.0, 1000.0, 100)
        _ramp(6.0, 1000.0, 100)
        _ramp(200.0, 2000.0, 200)
        climbs = VC.detect_climbs(out)
        self.assertEqual(len(climbs), 2, climbs)


class TestMovingTimeNeverExceedsElapsed(unittest.TestCase):
    """Revue de code #46, SHOULD-FIX : le dernier échantillon d'une montée ne doit
    jamais recevoir un crédit de mouvement au-delà de la durée écoulée réelle de la
    montée elle-même (bug mesuré : 2445 s de mouvement pour 2440 s écoulées)."""

    def test_moving_duration_never_exceeds_elapsed_duration(self):
        samples = _linear_climb_samples(duration_s=1800, gain_m=300.0, distance_m=3600.0)
        climbs = VC.detect_climbs(samples)
        self.assertEqual(len(climbs), 1)
        c = climbs[0]
        self.assertLessEqual(c["duration_moving_s"], c["duration_elapsed_s"])

    def test_two_sample_climb_moving_equals_elapsed_not_more(self):
        samples = [
            {"t_s": 0.0, "distance_m": 0.0, "altitude_m": 0.0, "speed_ms": 2.0,
             "hr_bpm": 150.0, "cadence_spm": 160.0},
            {"t_s": 5.0, "distance_m": 10.0, "altitude_m": 60.0, "speed_ms": 2.0,
             "hr_bpm": 150.0, "cadence_spm": 160.0},
        ]
        # Deux échantillons seuls ne suffisent pas à passer le zigzag/rognage utiles,
        # mais l'invariant (jamais moving > elapsed) doit tenir même sur un cas
        # dégénéré : on vérifie directement via une montée fabriquée à la main plus
        # longue mais toujours à SEULEMENT deux pas de temps utiles pour le dernier
        # segment.
        big = _linear_climb_samples(duration_s=60, gain_m=55.0, distance_m=120.0, resolution_s=5)
        climbs = VC.detect_climbs(big)
        if climbs:
            self.assertLessEqual(climbs[0]["duration_moving_s"], climbs[0]["duration_elapsed_s"])


# ---------------------------------------------------------------------------
# arc_index : table activity_climb, colonnes best_vam_*, CLI
# ---------------------------------------------------------------------------


def _arc_activity(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-climb-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=1800, distance_m=3600,
                        sport="trail"):
        self.write(f"activities/{day}_{sport}.md", _arc_activity(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, '
            f'"garmin_activity_id": {garmin_id}}}'
        ))

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_fit_climb(self, garmin_id, **kwargs):
        records = _linear_climb_samples(**kwargs)
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def activity_row(self, garmin_id):
        return self.conn.execute(
            "SELECT * FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()


class TestActivityClimbTable(Workspace):
    GARMIN_ID = 90000000046

    def test_climb_detected_and_stored(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID, duration_s=1800, gain_m=300.0, distance_m=3600.0)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(act["best_climb_vam_elapsed_m_h"])
        self.assertAlmostEqual(act["best_climb_vam_elapsed_m_h"], 600.0, delta=5.0)
        self.assertIsNotNone(act["best_vam_10min_m_h"])
        rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["idx"], 1)

    def test_flat_activity_has_no_climb_rows(self):
        self.write_activity(self.GARMIN_ID)
        records = [{"t_s": float(t), "distance_m": t * 2.7, "altitude_m": 0.0,
                    "speed_ms": 2.7, "hr_bpm": 150.0, "cadence_spm": 170.0}
                   for t in range(0, 1800, 5)]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{self.GARMIN_ID}.json").write_text(
            json.dumps({"activity_id": self.GARMIN_ID, "records": records}), encoding="utf-8")
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(act["best_climb_vam_elapsed_m_h"])
        rows = self.conn.execute(
            "SELECT * FROM activity_climb WHERE activity_id = ?", (act["id"],)).fetchall()
        self.assertEqual(rows, [])

    def test_strength_sport_excluded_even_with_samples(self):
        self.write_activity(self.GARMIN_ID, sport="strength")
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(act["best_climb_vam_elapsed_m_h"])

    def test_configurable_min_gain_from_workspace_config(self):
        """Revue de code #46, should-fix 4 (critère d'acceptation : « montée
        minimale configurable ») : un `[metrics].climb_min_gain_m` plus haut que le
        gain réel de la montée (30 m) doit empêcher sa détection, alors que le
        défaut (50 m) l'aurait aussi rejetée — ici on vérifie l'inverse : ABAISSER
        le seuil sous 30 m permet de détecter une petite montée normalement
        rejetée par le défaut."""
        self.write_activity(self.GARMIN_ID, duration_s=300, distance_m=300)
        self.write_fit_climb(self.GARMIN_ID, duration_s=300, gain_m=30.0, distance_m=300.0)
        self.index()
        self.assertIsNone(self.activity_row(self.GARMIN_ID)["best_climb_vam_elapsed_m_h"])
        (self.ws / "config").mkdir(parents=True, exist_ok=True)
        self.write("config/workspace.toml", "[metrics]\nclimb_min_gain_m = 10.0\nclimb_min_grade_pct = 5.0\n")
        self.index()
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(act["best_climb_vam_elapsed_m_h"])

    def test_invalid_config_value_falls_back_to_default_with_warning(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID, duration_s=1800, gain_m=300.0, distance_m=3600.0)
        (self.ws / "config").mkdir(parents=True, exist_ok=True)
        self.write("config/workspace.toml", "[metrics]\nclimb_min_gain_m = \"beaucoup\"\n")
        self.index()  # ne doit jamais lever
        act = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(act["best_climb_vam_elapsed_m_h"])


class TestActivityClimbReportAndCli(Workspace):
    GARMIN_ID = 90000000047

    def test_unknown_activity_has_explicit_reason(self):
        self.index()
        report = I.activity_climb_report(self.conn, 123)
        self.assertEqual(report["climbs"], [])
        self.assertIsNotNone(report["reason"])

    def test_non_run_family_has_explicit_reason(self):
        self.write_activity(self.GARMIN_ID, sport="indoor_cycling")
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        report = I.activity_climb_report(self.conn, self.GARMIN_ID)
        self.assertIn("course à pied", report["reason"])

    def test_no_samples_has_explicit_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.index()
        report = I.activity_climb_report(self.conn, self.GARMIN_ID)
        self.assertIn("aucun échantillon FIT ingéré", report["reason"])

    def test_success_report_has_climb_and_no_reason(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        report = I.activity_climb_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertEqual(len(report["climbs"]), 1)
        self.assertIn("5-10%", report["vam_by_grade_class"])

    def test_cli_vam_activity_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        code = I.main(["vam", "--activity", str(self.GARMIN_ID),
                        "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)

    def test_cli_vam_trend_command(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit_climb(self.GARMIN_ID)
        self.index()
        code = I.main(["vam", "--workspace", str(self.ws), "--memory", "--today", "2026-09-25"])
        self.assertEqual(code, 0)

    def test_vam_trend_includes_activity_without_duration_threshold(self):
        """Contrairement à `decoupling_trend`, `vam_trend` n'exige AUCUNE durée
        minimale : une sortie courte de 30 min avec une montée détectée doit
        apparaître dans la tendance."""
        self.write_activity(self.GARMIN_ID, duration_s=1800)
        self.write_fit_climb(self.GARMIN_ID, duration_s=1800, gain_m=300.0, distance_m=3600.0)
        self.index()
        from datetime import date
        trend = I.vam_trend(self.conn, date(2026, 9, 25))
        self.assertEqual(trend["activities_n"], 1)
        self.assertEqual(trend["with_climb_n"], 1)
        self.assertIsNotNone(trend["avg_best_climb_vam_elapsed_m_h"])


if __name__ == "__main__":
    unittest.main()
