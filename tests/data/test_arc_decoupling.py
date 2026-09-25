"""Palier D — découplage aérobie (Pa:HR) et facteur d'efficacité (#45).

Familles de tests :
- `arc_decoupling.decoupling_report` sur des séances SYNTHÉTIQUES construites
  par `tests.lib.synthetic.sample_session`, à vérité connue
  (`truth["decoupling_pct_measured"]`) : identité sur le plat, dérive imposée
  de 4 % (critère d'acceptation de l'issue #45), interaction avec un fade
  (#48), bruit, arrêt au milieu de la séance, effet de l'exclusion de
  l'échauffement.

  **Comparaison « comme avec comme »** (voir tests/README.md et le corps de
  la tâche #45) : `sample_session` mesure sa propre vérité avec le SLOPE
  FACTOR du générateur (`default_slope_factor`), volontairement différent du
  modèle de Minetti utilisé par `arc_gap`/`arc_decoupling`. Sur une séance
  SANS SEGMENT DE PENTE (parcours plat, le cas par défaut), la pente vaut 0
  partout : les deux modèles valent alors 1 (`default_slope_factor(0) == 1`,
  `arc_gap.minetti_cost(0)/MINETTI_FLAT_COST == 1`), donc le GAP produit par
  les deux méthodes est identique à la vitesse mesurée — la comparaison est
  alors bien « comme avec comme », sans avoir besoin de reconstruire les
  échantillons depuis le modèle de Minetti (contrairement à #44, qui doit
  comparer un GAP en pente).
- Éligibilité : familles hors course à pied, durée insuffisante, aucune FC
  exploitable, séance jugée non stable (règle du coefficient de variation du
  GAP par fenêtre d'une minute).
- Découpage en deux moitiés sur le temps de MOUVEMENT (pas le temps écoulé) :
  un arrêt au milieu de la séance ne doit pas fausser la mesure.
- `arc_index` : colonnes `activity.decoupling_pct`/`ef_whole`/
  `decoupling_reason` recalculées à l'indexation, CLI `decoupling`, tendance
  sur les sorties longues.
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

import arc_decoupling as D  # noqa: E402
import arc_index as I  # noqa: E402
from tests.lib.synthetic import sample_session  # noqa: E402


# ---------------------------------------------------------------------------
# arc_decoupling : découplage sur séances synthétiques à vérité connue
# ---------------------------------------------------------------------------


class TestDecouplingMatchesSyntheticTruth(unittest.TestCase):
    """Séances à effort stable, PLATES (pas de segment de pente) — voir le
    docstring du module pour pourquoi c'est la comparaison « comme avec
    comme » correcte face à `sample_session`."""

    def test_flat_identity_zero_decoupling(self):
        records, truth = sample_session(duration_s=3900, decoupling_pct=0.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertEqual(truth["decoupling_pct_measured"], 0.0)
        self.assertAlmostEqual(report["decoupling_pct"], 0.0, delta=0.5)

    def test_imposed_4_percent_drift_measured_within_half_point(self):
        """Critère d'acceptation de l'issue #45 : 4 % imposé -> 4 % mesuré ± 0,5."""
        records, truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(truth["decoupling_pct_measured"], 3.98, delta=0.05)
        self.assertAlmostEqual(report["decoupling_pct"], 4.0, delta=0.5)

    def test_imposed_4_percent_drift_with_noise_still_within_tolerance(self):
        records, truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=True, seed=11)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], truth["decoupling_pct_measured"], delta=0.5)

    def test_drift_plus_fade_increases_measured_decoupling_beyond_drift_alone(self):
        """Un fade (#48) actif AUGMENTE légitimement le découplage mesuré au-delà
        du seul `decoupling_pct` demandé — voir le docstring de `sample_session`."""
        records, truth = sample_session(duration_s=3900, decoupling_pct=4.0, fade_pct=8.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertGreater(report["decoupling_pct"], 4.0)
        self.assertAlmostEqual(report["decoupling_pct"], truth["decoupling_pct_measured"], delta=0.5)

    def test_longer_session_dilutes_warmup_effect_further(self):
        records, truth = sample_session(duration_s=7200, decoupling_pct=4.0, noise=False)
        report = D.decoupling_report(records, "trail")
        self.assertAlmostEqual(report["decoupling_pct"], truth["decoupling_pct_measured"], delta=0.5)


def _flat_session_with_depressed_warmup_hr(duration_s=3900, speed_ms=2.8, warmup_s=600,
                                            warmup_hr=100.0, hr1=140.0, decoupling_pct=4.0):
    """Séance plate, artisanale (pas `sample_session`, dont le modèle de dérive ne
    simule pas de « retard cardiovasculaire » à l'échauffement) : FC anormalement
    basse pendant `warmup_s`, puis FC stable `hr1` jusqu'à la moitié (temps de
    mouvement, séance plate donc identique au temps écoulé), puis FC en dérive de
    `decoupling_pct` — voir `ASSUMPTIONS["warmup"]` pour l'effet que ceci illustre."""
    half_t = duration_s / 2.0
    hr2 = hr1 / (1 - decoupling_pct / 100.0)
    records = []
    for t in range(duration_s):
        if t < warmup_s:
            hr = warmup_hr
        elif t < half_t:
            hr = hr1
        else:
            hr = hr2
        records.append({"t_s": float(t), "distance_m": t * speed_ms, "altitude_m": 0.0,
                         "hr_bpm": hr, "speed_ms": speed_ms, "cadence_spm": 170.0})
    return records


class TestWarmupExclusion(unittest.TestCase):
    def test_excluding_warmup_changes_the_measured_value(self):
        """La règle d'exclusion de l'échauffement (10 min, ASSUMPTIONS["warmup"])
        a un effet mesurable : sans elle, une FC anormalement basse pendant les
        10 premières minutes (retard cardiovasculaire) est comptée dans la
        moyenne de la première moitié, ce qui gonfle artificiellement le
        découplage mesuré au-delà de la vraie dérive imposée."""
        records = _flat_session_with_depressed_warmup_hr()
        with_warmup_excluded = D.decoupling_report(records, "trail")["decoupling_pct"]

        original_warmup = D.WARMUP_S
        try:
            D.WARMUP_S = 0.0
            without_exclusion = D.decoupling_report(records, "trail")["decoupling_pct"]
        finally:
            D.WARMUP_S = original_warmup

        self.assertNotAlmostEqual(with_warmup_excluded, without_exclusion, delta=0.001)
        # L'échauffement exclu rapproche la mesure de la vraie dérive imposée (4 %).
        self.assertLess(abs(with_warmup_excluded - 4.0), abs(without_exclusion - 4.0))
        self.assertAlmostEqual(with_warmup_excluded, 4.0, delta=0.1)
        self.assertGreater(without_exclusion, 10.0)


class TestStoppedSamplesExcluded(unittest.TestCase):
    def test_pause_in_the_middle_does_not_distort_the_measurement(self):
        records, truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        records = [dict(r) for r in records]
        mid = len(records) // 2
        for r in records[mid:mid + 120]:
            r["speed_ms"] = 0.0
        report = D.decoupling_report(records, "trail")
        self.assertIsNone(report["reason"])
        self.assertAlmostEqual(report["decoupling_pct"], truth["decoupling_pct_measured"], delta=0.5)


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
        self.assertIn("fréquence cardiaque", report["reason"])

    def test_intervals_like_session_is_flagged_unstable(self):
        """Alternance rapide effort/récupération (fractionné), CV du GAP par
        fenêtre d'une minute au-delà du seuil documenté."""
        records = []
        for t in range(3900):
            on = (t // 120) % 2 == 0
            records.append({
                "t_s": t, "distance_m": t * (3.0 if on else 1.2), "altitude_m": 0.0,
                "hr_bpm": 178.0 if on else 128.0, "speed_ms": 3.0 if on else 1.2,
                "cadence_spm": 170.0,
            })
        report = D.decoupling_report(records, "trail")
        self.assertFalse(report["eligible"])
        self.assertIn("non stable", report["reason"])


class TestCoefficientOfVariation(unittest.TestCase):
    def test_constant_gap_has_zero_cv(self):
        series = [{"t_s": float(t), "gap_speed_ms": 2.8} for t in range(0, 900, 5)]
        cv = D.coefficient_of_variation_pct(series)
        self.assertAlmostEqual(cv, 0.0, delta=0.01)

    def test_too_few_windows_is_none(self):
        series = [{"t_s": 0.0, "gap_speed_ms": 2.8}, {"t_s": 30.0, "gap_speed_ms": 3.0}]
        self.assertIsNone(D.coefficient_of_variation_pct(series))


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
        records, truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=3900)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        row = self.activity_row(self.GARMIN_ID)
        self.assertIsNotNone(row["decoupling_pct"])
        self.assertAlmostEqual(row["decoupling_pct"], truth["decoupling_pct_measured"], delta=0.5)
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
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=3900)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        report = I.activity_decoupling_report(self.conn, self.GARMIN_ID)
        self.assertIsNone(report["reason"])
        self.assertIsNotNone(report["decoupling_pct"])

    def test_cli_decoupling_command_activity(self):
        records, _truth = sample_session(duration_s=3900, decoupling_pct=4.0, noise=False)
        self.write_activity(self.GARMIN_ID, duration_s=3900)
        self.write_fit_records(self.GARMIN_ID, records)
        self.index()
        code = I.main(["decoupling", "--activity", str(self.GARMIN_ID),
                        "--workspace", str(self.ws), "--memory"])
        self.assertEqual(code, 0)

    def test_cli_decoupling_command_trend(self):
        code = I.main(["decoupling", "--workspace", str(self.ws), "--memory", "--weeks", "12"])
        self.assertEqual(code, 0)


class TestDecouplingTrend(Workspace):
    def test_long_runs_appear_in_trend_with_measured_average(self):
        # > arc_metrics.LONG_RUN_MIN_DURATION_S (90 min) : condition d'entrée dans
        # la tendance des « sorties longues », distincte du seuil d'éligibilité au
        # découplage lui-même (60 min, arc_decoupling.MIN_MOVING_DURATION_S).
        records, truth = sample_session(duration_s=5700, decoupling_pct=4.0, noise=False)
        self.write_activity(90000000047, day="2026-09-10", duration_s=5700)
        self.write_fit_records(90000000047, records)
        self.write_activity(90000000048, day="2026-09-17", duration_s=5700)
        self.write_fit_records(90000000048, records)
        self.index()
        trend = I.decoupling_trend(self.conn, __import__("datetime").date(2026, 9, 25))
        self.assertEqual(trend["long_runs"], 2)
        self.assertEqual(trend["measured_n"], 2)
        self.assertAlmostEqual(trend["avg_decoupling_pct"], truth["decoupling_pct_measured"], delta=0.5)

    def test_short_runs_are_excluded_from_trend(self):
        records, _truth = sample_session(duration_s=1800, decoupling_pct=4.0, noise=False)
        self.write_activity(90000000049, day="2026-09-10", duration_s=1800)
        self.write_fit_records(90000000049, records)
        self.index()
        trend = I.decoupling_trend(self.conn, __import__("datetime").date(2026, 9, 25))
        self.assertEqual(trend["long_runs"], 0)


if __name__ == "__main__":
    unittest.main()
