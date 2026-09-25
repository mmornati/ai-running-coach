"""Palier D — découplage aérobie (Pa:HR) et facteur d'efficacité (#45).

Familles de tests :
- `arc_decoupling.decoupling_report` sur des séances à vérité connue :
  - une dérive LINÉAIRE construite à la main, dont le découplage attendu se
    calcule analytiquement (moyenne d'une fonction linéaire sur un intervalle
    = valeur au milieu de l'intervalle) — INDÉPENDANT du point exact où
    `arc_decoupling` place la frontière des deux moitiés (revue de code #45) :
    contrairement à une marche d'escalier (dérive en palier), une dérive
    linéaire donne le même résultat quel que soit l'ordre exclusion/découpage
    ou l'endroit précis de la frontière, ce qui en fait une vérité de
    référence robuste pour ce test d'acceptation.
  - des séances `tests.lib.synthetic.sample_session` (dérive en PALIER à
    `duration_s/2`, jamais post-échauffement) comparées à une recomputation
    INDÉPENDANTE de ce module, calculée ICI sur les moitiés RÉELLEMENT
    utilisées par `arc_decoupling` (échauffement exclu D'ABORD, moitiés
    égales du reste) — la vérité `truth["decoupling_pct_measured"]` du
    générateur n'est PAS comparée directement à `decoupling_report` : son
    palier est fixé à `duration_s/2`, pas à `warmup + (duration_s -
    warmup)/2`, donc les deux ne mesurent pas exactement la même chose (revue
    de code #45 ; voir `tests/README.md` sur la comparaison « comme avec
    comme »).
- Éligibilité : familles hors course à pied, durée insuffisante, aucun
  échantillon, aucune FC exploitable, couverture FC/GAP insuffisante sur une
  moitié (ex. décrochage capteur), profil de pente trop asymétrique entre les
  deux moitiés, effort jugé non stable (fenêtres glissantes de 30 s, pas des
  seaux disjoints d'une minute — un fractionné 30 s/30 s serait sinon
  invisible, revue de code #45).
- Découpage en deux moitiés sur le temps de MOUVEMENT (pas le temps écoulé) :
  un arrêt au milieu de la séance ne doit pas fausser la mesure.
- `arc_index` : colonnes `activity.decoupling_pct`/`ef_whole`/
  `decoupling_reason` recalculées à l'indexation, CLI `decoupling`, tendance
  sur les sorties longues.
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

import arc_decoupling as D  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_index as I  # noqa: E402
from tests.lib.synthetic import sample_session  # noqa: E402


# ---------------------------------------------------------------------------
# Vérités de référence
# ---------------------------------------------------------------------------


def _linear_drift_records(duration_s=3900, speed=2.7, hr0=140.0, slope=0.0037):
    """Séance plate, FC en dérive LINÉAIRE (`hr0 + slope * t`), un échantillon
    par seconde — voir le docstring du module pour pourquoi cette vérité est
    indépendante du point exact de la frontière des deux moitiés."""
    return [{"t_s": t, "distance_m": t * speed, "altitude_m": 0.0, "hr_bpm": hr0 + slope * t,
             "speed_ms": speed, "cadence_spm": 170.0} for t in range(duration_s)]


def _analytic_linear_decoupling(duration_s, warmup_s, hr0, slope):
    """Découplage EXACT (à la discrétisation 1 s près) d'une dérive linéaire de
    FC sur une séance plate (GAP = vitesse constante) : la moyenne d'une
    fonction linéaire sur un intervalle vaut sa valeur au milieu de cet
    intervalle — vrai quel que soit l'intervalle, donc pas besoin de connaître
    l'algorithme de découpage en détail pour vérifier son résultat."""
    mid = warmup_s + (duration_s - warmup_s) / 2.0
    mean_hr1 = hr0 + slope * (warmup_s + mid) / 2.0
    mean_hr2 = hr0 + slope * (mid + duration_s) / 2.0
    return (mean_hr2 - mean_hr1) / mean_hr2 * 100.0


def _independent_recompute(records, warmup_s=600.0):
    """Recalcule le découplage sur les MÊMES moitiés que `arc_decoupling`
    (échauffement exclu D'ABORD, temps de mouvement restant partagé en deux
    PAR NOMBRE D'ÉCHANTILLONS — une approximation valide ici : les séances
    `sample_session` sans arrêt ni trou de signal sont régulièrement
    échantillonnées, donc partager par nombre d'échantillons ou par temps de
    mouvement cumulé donne le même résultat à l'arrondi près), par une moyenne
    ARITHMÉTIQUE simple (pas pondérée par le temps — même remarque) de la
    vitesse (= GAP sur un parcours plat) et de la FC. Sert à vérifier
    `decoupling_report` de façon indépendante, sans réutiliser son code."""
    ordered = sorted(records, key=lambda r: r["t_s"])
    moving = [r for r in ordered if (r.get("speed_ms") or 0.0) >= 0.2]
    t0 = moving[0]["t_s"]
    post = [r for r in moving if r["t_s"] - t0 >= warmup_s]
    n = len(post)
    half1, half2 = post[: n // 2], post[n // 2:]

    def _mean(key, xs):
        vs = [x[key] for x in xs]
        return sum(vs) / len(vs)

    ef1 = _mean("speed_ms", half1) * 60.0 / _mean("hr_bpm", half1)
    ef2 = _mean("speed_ms", half2) * 60.0 / _mean("hr_bpm", half2)
    return (ef1 - ef2) / ef1 * 100.0


def _two_grade_halves_records(duration_s=3900, grade1=0.02, grade2=-0.02, target_gap=2.7, hr=150.0):
    """Séance à allure adaptée à la pente (effort constant, comme les profils
    vallonnés de `TestSteadyEffort`) : pente moyenne `grade1` dans la première
    moitié, `grade2` dans la seconde — pour tester la frontière de
    `arc_decoupling.GRADE_ASYMMETRY_MAX` sans déclencher la détection d'effort
    non stable (grades faibles, effort constant, pas de fractionné)."""
    mid = 600 + (duration_s - 600) / 2.0
    records = []
    distance = altitude = 0.0
    for t in range(duration_s):
        grade = grade1 if t < mid else grade2
        cost = G.minetti_cost(grade)
        speed = target_gap * G.MINETTI_FLAT_COST / cost
        distance += speed
        altitude += speed * grade
        records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                         "hr_bpm": hr, "speed_ms": speed, "cadence_spm": 170.0})
    return records


class TestDecouplingMatchesAnalyticLinearDrift(unittest.TestCase):
    def test_imposed_linear_drift_matches_closed_form(self):
        """Critère d'acceptation de l'issue #45 (dérive imposée -> mesure
        proche), sur une vérité de référence dont le calcul ne dépend pas du
        détail d'implémentation de la frontière (voir le docstring du module)."""
        records = _linear_drift_records(duration_s=3900, hr0=140.0, slope=0.0037)
        report = D.decoupling_report(records, "trail")
        expected = _analytic_linear_decoupling(3900, 600.0, 140.0, 0.0037)
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(expected, 4.03, delta=0.05)  # sanity : ~4 %, comme demandé par l'issue
        self.assertAlmostEqual(report["decoupling_pct"], expected, delta=0.05)

    def test_no_drift_is_near_zero(self):
        records = _linear_drift_records(duration_s=3900, hr0=140.0, slope=0.0)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], 0.0, delta=0.05)


class TestDecouplingMatchesIndependentRecomputation(unittest.TestCase):
    """`sample_session` (dérive en PALIER à `duration_s/2`) comparé à une
    recomputation indépendante sur les moitiés RÉELLEMENT utilisées par
    `arc_decoupling` (échauffement exclu d'abord) — voir le docstring du
    module : ce n'est PAS `truth["decoupling_pct_measured"]` du générateur,
    dont le palier est ailleurs."""

    def test_drift_only(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], _independent_recompute(records), delta=0.1)

    def test_drift_plus_fade(self):
        """Un fade (#48) actif AUGMENTE légitimement le découplage mesuré au-delà
        du seul `decoupling_pct` demandé — voir le docstring de `sample_session`."""
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, fade_pct=8.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertGreater(report["decoupling_pct"], 4.0)
        self.assertAlmostEqual(report["decoupling_pct"], _independent_recompute(records), delta=0.15)

    def test_with_noise_still_close_to_independent_recomputation(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=True, seed=11)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], _independent_recompute(records), delta=0.3)


class TestWarmupExclusion(unittest.TestCase):
    def _flat_session_with_depressed_warmup_hr(self, duration_s=3900, speed_ms=2.8, warmup_s=600,
                                                warmup_hr=100.0, hr1=140.0, decoupling_pct=4.0):
        """Séance plate, artisanale : FC anormalement basse pendant `warmup_s`
        (retard cardiovasculaire), puis FC stable `hr1`, puis en dérive à la
        frontière RÉELLE des deux moitiés (`warmup_s + (duration_s -
        warmup_s) / 2`, PAS `duration_s / 2`) — voir
        `arc_decoupling.ASSUMPTIONS["warmup"]` pour l'effet que ceci illustre."""
        mid = warmup_s + (duration_s - warmup_s) / 2.0
        hr2 = hr1 / (1 - decoupling_pct / 100.0)
        records = []
        for t in range(duration_s):
            if t < warmup_s:
                hr = warmup_hr
            elif t < mid:
                hr = hr1
            else:
                hr = hr2
            records.append({"t_s": float(t), "distance_m": t * speed_ms, "altitude_m": 0.0,
                             "hr_bpm": hr, "speed_ms": speed_ms, "cadence_spm": 170.0})
        return records

    def test_excluding_warmup_changes_the_measured_value(self):
        """Sans exclusion de l'échauffement, une FC anormalement basse pendant
        les 10 premières minutes (retard cardiovasculaire) est comptée dans la
        moyenne de la première moitié, ce qui gonfle artificiellement le
        découplage mesuré au-delà de la vraie dérive imposée."""
        records = self._flat_session_with_depressed_warmup_hr()
        with_warmup_excluded = D.decoupling_report(records, "trail")["decoupling_pct"]

        original_warmup = D.WARMUP_S
        try:
            D.WARMUP_S = 0.0
            without_exclusion = D.decoupling_report(records, "trail")["decoupling_pct"]
        finally:
            D.WARMUP_S = original_warmup

        self.assertNotAlmostEqual(with_warmup_excluded, without_exclusion, delta=0.001)
        self.assertLess(abs(with_warmup_excluded - 4.0), abs(without_exclusion - 4.0))
        self.assertAlmostEqual(with_warmup_excluded, 4.0, delta=0.1)
        self.assertGreater(without_exclusion, 10.0)


class TestStoppedSamplesExcluded(unittest.TestCase):
    def test_pause_in_the_middle_does_not_distort_the_measurement(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        records = [dict(r) for r in records]
        mid = len(records) // 2
        for r in records[mid:mid + 120]:
            r["speed_ms"] = 0.0
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], _independent_recompute(records), delta=0.2)


class TestHrGapCoverage(unittest.TestCase):
    def test_hr_dropout_in_one_half_is_ineligible_not_silently_biased(self):
        """Revue de code #45 : un décrochage capteur FC de 13 minutes dans une
        moitié, sur une séance sans aucune vraie dérive (0 % attendu), ne doit
        JAMAIS produire un découplage mesuré non nul faute de FC — il doit
        rendre l'activité inéligible avec une raison explicite."""
        records = _linear_drift_records(duration_s=3900, hr0=150.0, slope=0.0)
        records = [dict(r) for r in records]
        for r in records:
            if 2500 <= r["t_s"] < 2500 + 780:  # 13 min, dans la seconde moitié (frontière à 2250 s)
                r["hr_bpm"] = None
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIsNone(report["decoupling_pct"])
        self.assertIn("FC incomplète", report["reason"])

    def test_full_hr_coverage_is_eligible(self):
        records = _linear_drift_records(duration_s=3900, hr0=150.0, slope=0.0)
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"])

    def test_rolling_hill_trail_with_complete_hr_is_eligible(self):
        """Revue de code #45 (SHOULD-FIX) : un profil vallonné réaliste
        (±12 %, allure adaptée à la pente pour tenir l'effort) avec une FC
        COMPLÈTE à 100 % du temps doit rester éligible — l'ancienne règle de
        couverture (qui comptait les pentes fortes/la marche comme « non
        couvertes ») rejetait à tort ce genre de sortie de montagne pourtant
        parfaitement mesurée côté FC (mesuré avant correction : 64-86 % de
        « couverture » pour un profil ±12 %, sous le seuil de 80 % alors même
        que la FC ne manquait jamais)."""
        duration_s = 3900
        target_gap = 2.7
        cycle_len = 300.0
        records = []
        distance = altitude = 0.0
        sign = 1
        for t in range(duration_s):
            grade = 0.12 * sign
            cost = G.minetti_cost(grade)
            speed = target_gap * G.MINETTI_FLAT_COST / cost
            distance += speed
            altitude += speed * grade
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
            if distance % (2 * cycle_len) < speed:
                sign *= -1
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])


class TestGradeAsymmetry(unittest.TestCase):
    def test_summit_and_back_is_ineligible(self):
        """Aller-retour à un sommet : montée à 6 % dans la première moitié,
        descente à 6 % dans la seconde, FC constante (0 % de vraie dérive) —
        le biais connu du modèle de Minetti en descente (arc_gap.ASSUMPTIONS)
        peut sinon produire un découplage mesuré non nul qui reflète le
        relief, pas une dérive cardiaque (revue de code #45)."""
        duration_s = 3900
        mid = 600 + (duration_s - 600) / 2.0
        speed = 2.7
        records = []
        distance = altitude = 0.0
        for t in range(duration_s):
            grade = 0.06 if t < mid else -0.06
            distance += speed
            altitude += speed * grade
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIsNone(report["decoupling_pct"])
        self.assertIn("trop différent", report["reason"])

    def test_symmetric_hills_per_half_are_eligible(self):
        """Une colline identique DANS CHAQUE moitié (montée puis descente,
        symétrique, allure adaptée à la pente pour tenir un effort constant —
        comme le profil vallonné de `TestSteadyEffort`, sinon la seule
        variation de GAP due au relief déclencherait la détection d'effort
        non stable plutôt que celle testée ici) n'a pas de profil de pente
        asymétrique ENTRE les deux moitiés — reste éligible."""
        duration_s = 3900
        half_len = (duration_s - 600) / 2.0
        quarter = half_len / 2.0
        target_gap = 2.7
        records = []
        distance = altitude = 0.0
        for t in range(duration_s):
            # Pente : montée puis descente à 8 %, une colline par moitié (même
            # principe que `_fixed_altitude_m` du golden, #45).
            if t >= 600:
                offset = (t - 600) % half_len
                grade = 0.08 if offset < quarter else -0.08
            else:
                grade = 0.0
            cost = G.minetti_cost(grade)
            speed = target_gap * G.MINETTI_FLAT_COST / cost
            distance += speed
            altitude += speed * grade
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])

    def test_just_under_asymmetry_threshold_is_eligible(self):
        """Écart de pente moyenne de 2,9 points entre les deux moitiés — juste
        SOUS `arc_decoupling.GRADE_ASYMMETRY_MAX` (3 points) : reste éligible."""
        records = _two_grade_halves_records(grade1=0.0145, grade2=-0.0145)  # écart = 2,9 pts
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])

    def test_just_over_asymmetry_threshold_is_ineligible(self):
        """Écart de pente moyenne de 3,1 points — juste AU-DESSUS du seuil :
        devient inéligible."""
        records = _two_grade_halves_records(grade1=0.0155, grade2=-0.0155)  # écart = 3,1 pts
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("trop différent", report["reason"])


class TestSteadyEffort(unittest.TestCase):
    def test_30_30_intervals_running_recovery_rejected(self):
        """30 s effort / 30 s récupération COURUE (pas marchée, donc pas
        exclue par le filtre marche) : la moyenne glissante de 30 s (pas des
        seaux disjoints d'une minute, qui annuleraient artificiellement la
        variabilité d'un cycle pile d'une minute — revue de code #45) doit
        détecter la non-stabilité."""
        duration_s = 3900
        records = []
        for t in range(duration_s):
            on = (t // 30) % 2 == 0
            hr = 175.0 if on else 140.0
            speed = 4.2 if on else 2.2  # les deux allures restent au-dessus du seuil de marche
            records.append({"t_s": t, "distance_m": t * speed, "altitude_m": 0.0, "hr_bpm": hr,
                             "speed_ms": speed, "cadence_spm": 170.0})
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("non stable", report["reason"])

    def test_rolling_hill_trail_at_steady_effort_is_accepted(self):
        """Un profil vallonné réaliste (relances/montées modérées à 8 %, brefs
        passages raides à 22 % exclus du calcul, allure adaptée à la pente
        pour tenir un effort constant — comme un coureur réel, pas une vitesse
        brute constante) doit rester éligible : le relief seul, à effort
        constant, n'est pas un fractionné (revue de code #45)."""
        duration_s = 3900
        moderate_grade, steep_grade = 0.08, 0.22
        moderate_len, steep_len = 280.0, 20.0
        target_gap = 2.7
        cycle_len = moderate_len + steep_len
        records = []
        distance = altitude = 0.0
        sign = 1
        for t in range(duration_s):
            pos = distance % cycle_len
            grade = (moderate_grade if pos < moderate_len else steep_grade) * sign
            cost = G.minetti_cost(grade)
            speed = target_gap * G.MINETTI_FLAT_COST / cost
            distance += speed
            altitude += speed * grade
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": round(altitude, 2),
                             "hr_bpm": 150.0, "speed_ms": speed, "cadence_spm": 170.0})
            if distance % (2 * cycle_len) < speed:
                sign *= -1
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], 0.0, delta=1.0)

    def _run_walk_records(self, duration_s=7200, run_speed=2.8, walk_speed=1.2, run_s=280, walk_s=40,
                           decoupling_pct=4.0):
        boundary = 600 + (duration_s - 600) / 2.0
        records = []
        distance = 0.0
        for t in range(duration_s):
            running = (t % (run_s + walk_s)) < run_s
            speed = run_speed if running else walk_speed
            distance += speed
            hr_base = 150.0 if running else 130.0
            if t >= boundary:
                hr_base = hr_base / (1 - decoupling_pct / 100.0)
            # Cadence de course (170) vs de marche (110, sous `arc_decoupling.
            # WALKING_CADENCE_SPM`) : c'est la cadence, pas la vitesse brute, que
            # `_is_walking` regarde en premier (#45, revue de code).
            cadence = 170.0 if running else 110.0
            records.append({"t_s": t, "distance_m": round(distance, 2), "altitude_m": 0.0,
                             "hr_bpm": hr_base, "speed_ms": speed, "cadence_spm": cadence})
        return records

    def test_run_walk_ultra_mostly_running_is_measured_on_running_only(self):
        """Ultra en run/walk (#45, revue de code) : la marche est exclue de
        l'EF et de la détection d'effort stable (ASSUMPTIONS
        ["steep_grade_and_walking"]) — si la course reste largement
        majoritaire (ici 87,5 % du temps), la couverture FC/GAP utile reste
        suffisante et le découplage porte sur les portions courues."""
        records = self._run_walk_records(run_s=280, walk_s=40)
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], 4.0, delta=0.5)

    def test_run_walk_ultra_mostly_walking_is_ineligible_for_lack_of_running(self):
        """Un run/walk très majoritairement marché (10 % du temps couru) laisse
        moins de `arc_decoupling.MIN_HALF_MOVING_S` (10 min) de course
        exploitable par moitié — inéligible pour une raison DISTINCTE de « FC
        incomplète » (la FC, elle, reste mesurée à 100 % du temps, marche
        comprise) : ASSUMPTIONS['usable_running'], pas ASSUMPTIONS
        ['hr_coverage'] (revue de code #45 : les deux ne doivent jamais être
        confondues, sous peine de rejeter à tort des sorties de montagne à FC
        complète mais avec beaucoup de pente forte/marche)."""
        records = self._run_walk_records(duration_s=7200, run_s=30, walk_s=270)
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("trop peu de portions courues exploitables", report["reason"])
        self.assertNotIn("FC incomplète", report["reason"])

    def test_run_walk_ultra_balanced_with_enough_running_minutes_is_eligible(self):
        """Un run/walk moitié-moitié (#45, revue de code) laisse encore
        largement plus de 10 minutes de course exploitable par moitié sur une
        séance assez longue (2 h) : reste éligible, mesuré sur les portions
        courues seulement — la marche n'invalide PAS la mesure tant qu'il
        reste assez de minutes courues, même si sa PART du temps est élevée
        (contrairement à l'ancienne règle à 80 % de part relative, revue de
        code #45, qui rejetait ce cas à tort)."""
        records = self._run_walk_records(duration_s=7200, run_s=150, walk_s=150)
        report = D.decoupling_report(records, "trail")
        self.assertTrue(report["eligible"], report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], 4.0, delta=0.5)


class TestEligibility(unittest.TestCase):
    def test_too_short_is_ineligible(self):
        records, _truth = sample_session(duration_s=1800, decoupling_pct=4.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIsNone(report["decoupling_pct"])
        self.assertIn("durée de mouvement insuffisante", report["reason"])

    def test_non_run_family_is_ineligible(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        report = D.decoupling_report(records, "strength")
        self.assertFalse(report["eligible"])
        self.assertIn("course à pied", report["reason"])

    def test_no_samples_is_ineligible(self):
        report = D.decoupling_report([], "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("aucun échantillon", report["reason"])

    def test_missing_heart_rate_is_ineligible_with_distinct_reason(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        records = [dict(r, hr_bpm=None) for r in records]
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("FC incomplète", report["reason"])


def _two_block_series(block1_s, block2_s, resolution_s=5.0, v1=2.7, v2=6.0):
    """Deux blocs de valeurs GAP constantes (`v1` puis `v2`), bien plus longs
    que `arc_decoupling.STEADY_WINDOW_S` — pour tester la frontière de
    `STEADY_MIN_SHARE_PCT` avec une part « dans la bande » calculable
    approximativement à l'avance (`block1_s / (block1_s + block2_s)`, à l'effet
    de bord de la fenêtre glissante près, négligeable ici vu la longueur des
    blocs)."""
    series = []
    t = 0.0
    while t < block1_s:
        series.append({"t_s": t, "gap_speed_ms": v1})
        t += resolution_s
    while t < block1_s + block2_s:
        series.append({"t_s": t, "gap_speed_ms": v2})
        t += resolution_s
    return series


class TestSteadinessSharePct(unittest.TestCase):
    def test_constant_gap_has_full_share(self):
        series = [{"t_s": float(t), "gap_speed_ms": 2.8} for t in range(0, 900, 5)]
        share = D.steadiness_share_pct(series)
        self.assertAlmostEqual(share, 100.0, delta=0.01)

    def test_too_few_samples_is_none(self):
        series = [{"t_s": 0.0, "gap_speed_ms": 2.8}, {"t_s": 30.0, "gap_speed_ms": 3.0}]
        self.assertIsNone(D.steadiness_share_pct(series))

    def test_share_just_above_the_stable_threshold(self):
        """~63,75 % dans la bande — juste AU-DESSUS de `STEADY_MIN_SHARE_PCT`
        (60 %) : jugée stable par cette fonction pure (l'appelant, lui,
        comparerait ce chiffre au seuil)."""
        share = D.steadiness_share_pct(_two_block_series(1800, 1000))
        self.assertGreater(share, D.STEADY_MIN_SHARE_PCT)
        self.assertAlmostEqual(share, 63.75, delta=1.0)

    def test_share_just_below_the_stable_threshold(self):
        """~57,6 % dans la bande — juste SOUS `STEADY_MIN_SHARE_PCT` (60 %)."""
        share = D.steadiness_share_pct(_two_block_series(1800, 1300))
        self.assertLess(share, D.STEADY_MIN_SHARE_PCT)
        self.assertAlmostEqual(share, 57.6, delta=1.0)


# ---------------------------------------------------------------------------
# arc_index : intégration (colonnes stockées, CLI, tendance)
# ---------------------------------------------------------------------------


def _arc_activity(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-decoupling-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=3900, distance_m=10000,
                        sport="trail", name="Sortie longue"):
        self.write(f"activities/{day}_{sport}_{garmin_id}.md", _arc_activity(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", "name": "{name}", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, '
            f'"garmin_activity_id": {garmin_id}}}'
        ))

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_fit_records(self, garmin_id, records):
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def activity_row(self, garmin_id):
        return self.conn.execute(
            "SELECT * FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()


class TestActivityDecouplingColumns(Workspace):
    GARMIN_ID = 90000000045

    def test_eligible_long_run_gets_decoupling_and_ef(self):
        records = _linear_drift_records(duration_s=3900, hr0=140.0, slope=0.0037)
        self.write_activity(self.GARMIN_ID, duration_s=3900)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(row["decoupling_pct"])
        expected = _analytic_linear_decoupling(3900, 600.0, 140.0, 0.0037)
        self.assertAlmostEqual(row["decoupling_pct"], expected, delta=0.1)
        self.assertIsNotNone(row["ef_whole"])
        self.assertIsNone(row["decoupling_reason"])

    def test_too_short_run_has_no_decoupling_but_an_explicit_reason(self):
        records, _truth = sample_session(duration_s=1800, decoupling_pct=4.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=1800)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(row["decoupling_pct"])
        self.assertIn("durée de mouvement insuffisante", row["decoupling_reason"])

    def test_strength_sport_excluded_even_with_samples(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=3900, sport="strength")
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNone(row["decoupling_pct"])


class TestActivityDecouplingReportAndCli(Workspace):
    GARMIN_ID = 90000000046

    def test_unknown_activity_has_explicit_reason(self):
        self.index()
        report = I.activity_decoupling_report(self.conn, 123)
        self.assertIsNone(report["decoupling_pct"])
        self.assertIsNotNone(report["reason"])

    def test_success_report_has_no_reason(self):
        records = _linear_drift_records(duration_s=3900, hr0=140.0, slope=0.0037)
        self.write_activity(self.GARMIN_ID, duration_s=3900)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        report = I.activity_decoupling_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertIsNotNone(report["decoupling_pct"])

    def test_cli_decoupling_command_activity(self):
        records = _linear_drift_records(duration_s=3900, hr0=140.0, slope=0.0037)
        self.write_activity(self.GARMIN_ID, duration_s=3900)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["decoupling", "--activity", str(self.GARMIN_ID),
                            "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["garmin_activity_id"], self.GARMIN_ID)

    def test_cli_decoupling_command_trend(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["decoupling", "--workspace", str(self.ws), "--memory", "--weeks", "12"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["window_weeks"], 12)


class TestDecouplingTrend(Workspace):
    def test_long_runs_appear_in_trend_with_measured_average(self):
        # > arc_metrics.LONG_RUN_MIN_DURATION_S (90 min) : condition d'entrée dans
        # la tendance des « sorties longues », distincte du seuil d'éligibilité au
        # découplage lui-même (60 min, arc_decoupling.MIN_MOVING_DURATION_S).
        records = _linear_drift_records(duration_s=5700, hr0=140.0, slope=0.0025)
        self.write_activity(90000000047, day="2026-09-10", duration_s=5700)
        self.write_fit_records(90000000047, records)
        self.write_activity(90000000048, day="2026-09-17", duration_s=5700)
        self.write_fit_records(90000000048, records)
        self.index()
        trend = I.decoupling_trend(self.conn, __import__("datetime").date(2026, 9, 25))
        self.assertEqual(trend["long_runs"], 2)
        self.assertEqual(trend["measured_n"], 2)
        expected = _analytic_linear_decoupling(5700, 600.0, 140.0, 0.0025)
        self.assertAlmostEqual(trend["avg_decoupling_pct"], expected, delta=0.2)

    def test_short_runs_are_excluded_from_trend(self):
        records, _truth = sample_session(duration_s=1800, decoupling_pct=4.0, noise=False)
        self.write_activity(90000000049, day="2026-09-10", duration_s=1800)
        self.write_fit_records(90000000049, records)
        self.index()
        trend = I.decoupling_trend(self.conn, __import__("datetime").date(2026, 9, 25))
        self.assertEqual(trend["long_runs"], 0)


if __name__ == "__main__":
    unittest.main()
