"""Palier D — zones FC, temps en zone et polarisation 80/20 (#43).

Familles de tests :
- `arc_metrics.hr_zone_bounds`/`hr_zone_resolution`/`time_in_zone_seconds`, purs,
  contre des valeurs de référence à la main et contre la vérité connue du générateur
  synthétique (`tests/lib/synthetic.sample_session`, story #25).
- `arc_metrics.seiler_bounds`/`time_in_polarisation_seconds`/`polarisation_shares` :
  la polarisation 80/20 utilise des bornes bpm DÉDIÉES par méthode (revue de code
  #43, point 2), jamais un regroupement des 5 zones affichées.
- `arc_index` : les tables dérivées `hr_zone_time`/`hr_polarisation_time` se
  recalculent à chaque passage (changement de profil compris), restreintes à la
  famille course à pied (revue de code #43, point 5), la CLI `zones`, la
  polarisation hebdomadaire.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_index as I  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_samples as S  # noqa: E402
import arc_serve  # noqa: E402
from tests.lib.synthetic import HR_MAX, HR_REST, ZONE_BOUNDS_BPM, sample_session  # noqa: E402


class TestHrZoneBounds(unittest.TestCase):
    def test_karvonen_matches_hand_values(self):
        """48/188 -> 118, 132, 146, 160, 174, 188 (issue #43, énoncé des tests)."""
        bounds, method = M.hr_zone_bounds({"hr_rest_bpm": HR_REST, "hr_max_bpm": HR_MAX})
        self.assertEqual(method, "karvonen")
        self.assertEqual(tuple(round(b) for b in bounds), (118, 132, 146, 160, 174, 188))
        self.assertEqual(tuple(round(b) for b in bounds), tuple(ZONE_BOUNDS_BPM))

    def test_precedence_prefers_lthr_when_known(self):
        bounds, method = M.hr_zone_bounds(
            {"hr_rest_bpm": 48, "hr_max_bpm": 188, "hr_threshold_bpm": 172})
        self.assertEqual(method, "lthr")
        self.assertAlmostEqual(bounds[1], 172 * 0.85, places=1)

    def test_percent_max_is_the_last_resort(self):
        bounds, method = M.hr_zone_bounds({"hr_max_bpm": 190})
        self.assertEqual(method, "percent_max")
        self.assertAlmostEqual(bounds[1], 190 * 0.60, places=1)

    def test_none_when_nothing_known(self):
        self.assertIsNone(M.hr_zone_bounds({}))

    def test_karvonen_needs_both_rest_and_max(self):
        self.assertIsNone(M.hr_zone_bounds({"hr_rest_bpm": 48}))

    def test_explicit_override_forces_the_method_without_fallback(self):
        """`[athlete].hr_zones = "lthr"` sans FC au seuil renseignée : PAS de repli sur
        Karvonen même si celui-ci serait calculable — voir ASSUMPTIONS["hr_zones"]."""
        athlete = {"hr_rest_bpm": 48, "hr_max_bpm": 188}
        self.assertIsNone(M.hr_zone_bounds(athlete, "lthr"))

    def test_explicit_override_forces_karvonen_even_if_lthr_known(self):
        athlete = {"hr_rest_bpm": 48, "hr_max_bpm": 188, "hr_threshold_bpm": 172}
        bounds, method = M.hr_zone_bounds(athlete, "karvonen")
        self.assertEqual(method, "karvonen")

    def test_auto_is_equivalent_to_no_override(self):
        athlete = {"hr_max_bpm": 190}
        self.assertEqual(M.hr_zone_bounds(athlete, "auto"), M.hr_zone_bounds(athlete, None))

    def test_method_override_is_case_and_space_insensitive(self):
        """Revue de code #43, point 4 : un typo de casse ne doit pas faire échouer
        silencieusement une méthode par ailleurs valide."""
        athlete = {"hr_rest_bpm": 48, "hr_max_bpm": 188}
        self.assertEqual(M.hr_zone_bounds(athlete, "KARVONEN"), M.hr_zone_bounds(athlete, "karvonen"))
        self.assertEqual(M.hr_zone_bounds(athlete, "  Karvonen  "), M.hr_zone_bounds(athlete, "karvonen"))

    def test_unknown_method_name_returns_none(self):
        athlete = {"hr_rest_bpm": 48, "hr_max_bpm": 188}
        self.assertIsNone(M.hr_zone_bounds(athlete, "polar"))

    def test_hr_zone_of_saturates(self):
        bounds = (118, 132, 146, 160, 174, 188)
        self.assertEqual(M.hr_zone_of(50, bounds), 1)     # bien en dessous : zone 1
        self.assertEqual(M.hr_zone_of(200, bounds), 5)    # bien au-dessus : zone 5 (jamais hors zone)
        self.assertEqual(M.hr_zone_of(131.9, bounds), 1)
        self.assertEqual(M.hr_zone_of(132.0, bounds), 2)


class TestLthrZoneBoundaries(unittest.TestCase):
    """Revue de code #43, point 1 : bornes Friel corrigées (85/90/95/100 %, pas
    85/89/94/99 %) — valeurs à la main sur une LTHR de 172 bpm."""

    def setUp(self):
        self.bounds, self.method = M.hr_zone_bounds({"hr_threshold_bpm": 172})
        self.assertEqual(self.method, "lthr")

    def test_bounds_are_85_90_95_100_pct_of_lthr(self):
        self.assertEqual([round(b, 1) for b in self.bounds], [0.0, 146.2, 154.8, 163.4, 172.0, 258.0])

    def test_153_08_bpm_is_zone_2(self):
        self.assertEqual(M.hr_zone_of(153.08, self.bounds), 2)

    def test_170_5_bpm_is_zone_4(self):
        self.assertEqual(M.hr_zone_of(170.5, self.bounds), 4)


class TestHrZoneResolution(unittest.TestCase):
    """Revue de code #43, point 4 : `hr_zone_resolution` rend toujours une raison
    explicite, jamais un `None` muet."""

    def test_success_has_no_reason(self):
        resolution = M.hr_zone_resolution({"hr_max_bpm": 188, "hr_rest_bpm": 48})
        self.assertIsNotNone(resolution["bounds_bpm"])
        self.assertEqual(resolution["method"], "karvonen")
        self.assertIsNone(resolution["reason"])

    def test_unknown_method_has_a_reason_naming_it(self):
        resolution = M.hr_zone_resolution({"hr_max_bpm": 188}, "polar")
        self.assertIsNone(resolution["bounds_bpm"])
        self.assertEqual(resolution["method"], "polar")
        self.assertIn("polar", resolution["reason"])

    def test_forced_method_missing_field_names_the_missing_field(self):
        resolution = M.hr_zone_resolution({"hr_max_bpm": 188, "hr_rest_bpm": 48}, "lthr")
        self.assertIsNone(resolution["bounds_bpm"])
        self.assertEqual(resolution["method"], "lthr")
        self.assertIn("seuil", resolution["reason"])

    def test_nothing_known_at_all(self):
        resolution = M.hr_zone_resolution({})
        self.assertIsNone(resolution["bounds_bpm"])
        self.assertIsNone(resolution["method"])
        self.assertIsNotNone(resolution["reason"])

    def test_case_insensitive_like_hr_zone_bounds(self):
        resolution = M.hr_zone_resolution({"hr_max_bpm": 188, "hr_rest_bpm": 48}, "KARVONEN")
        self.assertEqual(resolution["method"], "karvonen")
        self.assertIsNone(resolution["reason"])


class TestTimeInZone(unittest.TestCase):
    def test_matches_synthetic_truth_within_5s(self):
        """Séance synthétique à répartition de zones imposée (#25) -> temps en zone
        exact à 5 s près (résolution du sous-échantillonnage), critère de l'issue #43."""
        shares = {1: 0.5, 3: 0.3, 5: 0.2}
        records, truth = sample_session(seed=3, duration_s=2000, zone_shares=shares, noise=False)
        downsampled = S.downsample(records, S.DEFAULT_RESOLUTION_S)
        zone_seconds = M.time_in_zone_seconds(downsampled, tuple(ZONE_BOUNDS_BPM), S.DEFAULT_RESOLUTION_S)
        for zone_str, truth_seconds in truth["zone_seconds_measured"].items():
            with self.subTest(zone=zone_str):
                got = zone_seconds.get(int(zone_str), 0.0)
                self.assertAlmostEqual(got, truth_seconds, delta=5)

    def test_matches_synthetic_truth_with_dropout(self):
        """Même vérification, avec un trou de signal (pause) au milieu de la séance :
        le trou ne doit pas être compté dans une zone."""
        records, truth = sample_session(
            seed=5, duration_s=1200, zone_shares={2: 0.7, 4: 0.3},
            dropout_windows=((400, 500),), noise=False)
        downsampled = S.downsample(records, S.DEFAULT_RESOLUTION_S)
        zone_seconds = M.time_in_zone_seconds(downsampled, tuple(ZONE_BOUNDS_BPM), S.DEFAULT_RESOLUTION_S)
        total_measured = sum(truth["zone_seconds_measured"].values())
        self.assertAlmostEqual(sum(zone_seconds.values()), total_measured, delta=5)
        # Le trou (100 s) ne doit jamais réapparaître dans le total : la séance ne
        # dure que 1200 s au calendrier, mais seuls duration_s - 100 sont mesurés.
        self.assertEqual(total_measured, 1200 - 100)

    def test_pause_gap_is_never_counted_as_time_in_zone(self):
        """dt entre deux échantillons peut dépasser resolution_s (pause) : la part au
        delà de resolution_s ne doit jamais être comptée (arc_samples.ASSUMPTIONS["gaps"])."""
        samples = [
            {"t_s": 0, "hr_bpm": 120}, {"t_s": 5, "hr_bpm": 120},
            {"t_s": 605, "hr_bpm": 120}, {"t_s": 610, "hr_bpm": 120},   # 600 s de pause avant ce point
        ]
        bounds = (100, 130, 150, 160, 170, 190)
        zone_seconds = M.time_in_zone_seconds(samples, bounds, 5)
        # 4 échantillons, chacun plafonné à 5 s (dernier compris) : jamais 615 s.
        self.assertEqual(sum(zone_seconds.values()), 20.0)

    def test_none_hr_is_ignored(self):
        samples = [{"t_s": 0, "hr_bpm": 120}, {"t_s": 5, "hr_bpm": None}, {"t_s": 10, "hr_bpm": 120}]
        bounds = (100, 130, 150, 160, 170, 190)
        zone_seconds = M.time_in_zone_seconds(samples, bounds, 5)
        self.assertEqual(sum(zone_seconds.values()), 10.0)

    def test_last_sample_counts_for_its_own_bucket_length(self):
        samples = [{"t_s": 0, "hr_bpm": 120}]
        bounds = (100, 130, 150, 160, 170, 190)
        zone_seconds = M.time_in_zone_seconds(samples, bounds, 5)
        self.assertEqual(zone_seconds, {1: 5.0})


class TestSeilerBounds(unittest.TestCase):
    """Revue de code #43, point 2 : les seuils Seiler sont DÉDIÉS par méthode, pas un
    regroupement fixe des 5 zones affichées."""

    def test_karvonen_thresholds_are_70_and_80_pct_of_reserve(self):
        athlete = {"hr_rest_bpm": 48, "hr_max_bpm": 188}
        low_high, moderate_high = M.seiler_bounds(athlete, "karvonen")
        reserve = 188 - 48
        self.assertAlmostEqual(low_high, 48 + 0.70 * reserve, places=1)
        self.assertAlmostEqual(moderate_high, 48 + 0.80 * reserve, places=1)

    def test_lthr_thresholds_are_90_and_100_pct_of_lthr(self):
        low_high, moderate_high = M.seiler_bounds({"hr_threshold_bpm": 172}, "lthr")
        self.assertAlmostEqual(low_high, 172 * 0.90, places=1)
        self.assertAlmostEqual(moderate_high, 172 * 1.00, places=1)

    def test_percent_max_thresholds_are_independent_82_and_87_pct(self):
        low_high, moderate_high = M.seiler_bounds({"hr_max_bpm": 190}, "percent_max")
        self.assertAlmostEqual(low_high, 190 * 0.82, places=1)
        self.assertAlmostEqual(moderate_high, 190 * 0.87, places=1)

    def test_none_when_required_field_missing(self):
        self.assertIsNone(M.seiler_bounds({}, "lthr"))
        self.assertIsNone(M.seiler_bounds({"hr_rest_bpm": 48}, "karvonen"))
        self.assertIsNone(M.seiler_bounds({}, "percent_max"))

    def test_none_for_auto_or_unknown_method(self):
        athlete = {"hr_max_bpm": 188, "hr_rest_bpm": 48, "hr_threshold_bpm": 172}
        self.assertIsNone(M.seiler_bounds(athlete, "auto"))
        self.assertIsNone(M.seiler_bounds(athlete, "polar"))


class TestTimeInPolarisationSeconds(unittest.TestCase):
    """Revue de code #43, point 2 : le regroupement par zone (Z1+Z2/Z3/Z4+Z5) n'est
    physiologiquement correct QUE pour Karvonen — LTHR et %FCmax ont besoin de leurs
    propres seuils bpm."""

    def test_lthr_zone4_is_moderate_not_high(self):
        """96 % LTHR tombe dans notre Z4 (95-99 %), mais reste SOUS le second seuil
        Seiler (100 % LTHR) : il doit compter « modérée », pas « difficile »."""
        thresholds = M.seiler_bounds({"hr_threshold_bpm": 172}, "lthr")
        samples = [{"t_s": 0, "hr_bpm": 172 * 0.96}]
        buckets = M.time_in_polarisation_seconds(samples, thresholds, 5)
        self.assertEqual(buckets, {"moderate": 5.0})

    def test_lthr_above_100_pct_is_high(self):
        thresholds = M.seiler_bounds({"hr_threshold_bpm": 172}, "lthr")
        samples = [{"t_s": 0, "hr_bpm": 172 * 1.01}]
        buckets = M.time_in_polarisation_seconds(samples, thresholds, 5)
        self.assertEqual(buckets, {"high": 5.0})

    def test_percent_max_between_82_and_87_is_moderate(self):
        thresholds = M.seiler_bounds({"hr_max_bpm": 190}, "percent_max")
        samples = [{"t_s": 0, "hr_bpm": 190 * 0.85}]
        buckets = M.time_in_polarisation_seconds(samples, thresholds, 5)
        self.assertEqual(buckets, {"moderate": 5.0})

    def test_percent_max_below_82_is_low(self):
        thresholds = M.seiler_bounds({"hr_max_bpm": 190}, "percent_max")
        samples = [{"t_s": 0, "hr_bpm": 190 * 0.70}]
        buckets = M.time_in_polarisation_seconds(samples, thresholds, 5)
        self.assertEqual(buckets, {"low": 5.0})

    def test_karvonen_between_70_and_80_pct_reserve_is_moderate(self):
        athlete = {"hr_rest_bpm": 48, "hr_max_bpm": 188}
        thresholds = M.seiler_bounds(athlete, "karvonen")
        samples = [{"t_s": 0, "hr_bpm": 48 + 0.75 * (188 - 48)}]
        buckets = M.time_in_polarisation_seconds(samples, thresholds, 5)
        self.assertEqual(buckets, {"moderate": 5.0})

    def test_pause_gap_not_counted(self):
        thresholds = (140.0, 160.0)
        samples = [{"t_s": 0, "hr_bpm": 120}, {"t_s": 605, "hr_bpm": 120}]
        buckets = M.time_in_polarisation_seconds(samples, thresholds, 5)
        self.assertEqual(sum(buckets.values()), 10.0)


class TestPolarisationShares(unittest.TestCase):
    def test_shares_from_low_moderate_high_buckets(self):
        shares = M.polarisation_shares({"low": 150.0, "moderate": 30.0, "high": 20.0})
        self.assertAlmostEqual(shares["low_s"], 150.0)
        self.assertAlmostEqual(shares["moderate_s"], 30.0)
        self.assertAlmostEqual(shares["high_s"], 20.0)
        self.assertAlmostEqual(shares["low_pct"], 75.0)
        self.assertAlmostEqual(shares["moderate_pct"], 15.0)
        self.assertAlmostEqual(shares["high_pct"], 10.0)

    def test_missing_bucket_defaults_to_zero(self):
        shares = M.polarisation_shares({"low": 50.0})
        self.assertAlmostEqual(shares["moderate_pct"], 0.0)
        self.assertAlmostEqual(shares["high_pct"], 0.0)

    def test_none_when_empty_or_zero(self):
        self.assertIsNone(M.polarisation_shares({}))
        self.assertIsNone(M.polarisation_shares({"low": 0.0, "moderate": 0.0}))


def arc(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-hrzones-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def index(self, today="2026-09-25"):
        return I.index_workspace(self.conn, self.ws, today)

    def write_profile(self, *, hr_max=None, hr_rest=None, hr_threshold=None):
        lines = ["# Profil de l'athlète", "", "## Physiologie", ""]
        if hr_max is not None:
            lines.append(f"- **FC max** : {hr_max}")
        if hr_rest is not None:
            lines.append(f"- **FC de repos de référence** : {hr_rest}")
        if hr_threshold is not None:
            lines.append(f"- **FC au seuil** : {hr_threshold}")
        self.write("planning/Runner_Profile.md", "\n".join(lines) + "\n")

    def write_hr_zones_override(self, value: str) -> None:
        self.write("config/workspace.user.toml", f'[athlete]\nhr_zones = "{value}"\n')

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=3600, distance_m=10000, sport="trail"):
        self.write(f"activities/{day}_{sport}.md", arc(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, "garmin_activity_id": {garmin_id}}}'
        ))

    def write_fit(self, garmin_id, hr_bpm=140.0, n=20):
        records = [
            {"t_s": t, "distance_m": float(t) * 2.5, "altitude_m": 0.0, "hr_bpm": hr_bpm,
             "speed_ms": 2.5, "cadence_spm": 170.0}
            for t in range(n)
        ]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def internal_id(self, garmin_id):
        row = self.conn.execute("SELECT id FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()
        return row["id"] if row else None

    def zone_rows(self, garmin_id):
        activity_id = self.internal_id(garmin_id)
        return {r["zone"]: r["seconds"] for r in self.conn.execute(
            "SELECT zone, seconds FROM hr_zone_time WHERE activity_id = ?", (activity_id,)).fetchall()}

    def polarisation_rows(self, garmin_id):
        activity_id = self.internal_id(garmin_id)
        return {r["bucket"]: r["seconds"] for r in self.conn.execute(
            "SELECT bucket, seconds FROM hr_polarisation_time WHERE activity_id = ?", (activity_id,)).fetchall()}


class TestHrZoneTimeIndexing(Workspace):
    GARMIN_ID = 90000000002

    def test_no_profile_means_no_zone_rows(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID)
        self.index()
        self.assertEqual(self.zone_rows(self.GARMIN_ID), {})

    def test_profile_with_hr_max_and_rest_fills_zone_time(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)   # 140 bpm -> zone 2 (132 <= 140 < 146)
        self.index()
        rows = self.zone_rows(self.GARMIN_ID)
        self.assertGreater(sum(rows.values()), 0)
        self.assertEqual(set(rows), {2})

    def test_profile_with_hr_max_and_rest_fills_polarisation_time(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        self.index()
        rows = self.polarisation_rows(self.GARMIN_ID)
        self.assertGreater(sum(rows.values()), 0)

    def test_activity_without_samples_gets_no_zone_row(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.index()
        self.assertEqual(self.zone_rows(self.GARMIN_ID), {})

    def test_profile_change_triggers_recompute_on_next_index(self):
        """Changement de zones dans le profil -> recalcul (critère d'acceptation #43),
        sans étape supplémentaire : le prochain `index_workspace` suffit."""
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        self.index()
        before = self.zone_rows(self.GARMIN_ID)
        self.assertEqual(set(before), {2})
        # FC max nettement plus basse -> même FC (140) tombe désormais en zone plus haute.
        self.write_profile(hr_max=150, hr_rest=48)
        self.index()
        after = self.zone_rows(self.GARMIN_ID)
        self.assertNotEqual(before, after)

    def test_rebuild_recomputes_from_scratch(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        self.index()
        self.conn = I.open_db(self.ws, memory=True, rebuild=True)
        I.index_workspace(self.conn, self.ws, "2026-09-25")
        self.assertEqual(set(self.zone_rows(self.GARMIN_ID)), {2})


class TestSportFamilyRestriction(Workspace):
    """Revue de code #43, point 5 : renforcement et vélo exclus du temps en zone et
    de la polarisation, même avec des échantillons FIT ingérés."""

    def test_strength_gets_no_zone_or_polarisation_rows(self):
        self.write_profile(hr_max=188, hr_rest=48)
        garmin_id = 90000000020
        self.write_activity(garmin_id, sport="strength")
        self.write_fit(garmin_id, hr_bpm=140.0)
        self.index()
        self.assertEqual(self.zone_rows(garmin_id), {})
        self.assertEqual(self.polarisation_rows(garmin_id), {})

    def test_indoor_cycling_gets_no_zone_or_polarisation_rows(self):
        self.write_profile(hr_max=188, hr_rest=48)
        garmin_id = 90000000021
        self.write_activity(garmin_id, sport="indoor_cycling")
        self.write_fit(garmin_id, hr_bpm=140.0)
        self.index()
        self.assertEqual(self.zone_rows(garmin_id), {})
        self.assertEqual(self.polarisation_rows(garmin_id), {})

    def test_hiking_is_still_included(self):
        """Même famille « run » que `GEAR_WEAR_SPORTS`/`effort_km` : la randonnée
        garde le même modèle aérobie que la course, seulement plus lente."""
        self.write_profile(hr_max=188, hr_rest=48)
        garmin_id = 90000000022
        self.write_activity(garmin_id, sport="hiking")
        self.write_fit(garmin_id, hr_bpm=140.0)
        self.index()
        self.assertNotEqual(self.zone_rows(garmin_id), {})

    def test_running_is_still_included(self):
        self.write_profile(hr_max=188, hr_rest=48)
        garmin_id = 90000000023
        self.write_activity(garmin_id, sport="running")
        self.write_fit(garmin_id, hr_bpm=140.0)
        self.index()
        self.assertNotEqual(self.zone_rows(garmin_id), {})


class TestActivityZoneReportAndCli(Workspace):
    GARMIN_ID = 90000000003

    def test_activity_zone_report_reasons_without_profile(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID)
        conf = I.settings(I.load_config(self.ws))
        self.index()
        report = I.activity_zone_report(self.conn, conf, self.GARMIN_ID)
        self.assertIsNone(report["zone_seconds"])
        self.assertIsNotNone(report["reason"])

    def test_unknown_activity_has_explicit_reason_and_code(self):
        """#51, revue de code : une séance jamais indexée (aucun `activities/*.md`
        du tout, pas seulement « pas de FIT ») porte `reason_code:
        "unknown_activity"` — même code que gap/decoupling/vam/climb-history,
        pour que l'agent la distingue d'un autre motif de `reason` sans code
        (ici, la même chose que « pas de profil », mais AVEC un code cette fois)."""
        self.write_profile(hr_max=188, hr_rest=48)
        self.index()
        conf = I.settings(I.load_config(self.ws))
        report = I.activity_zone_report(self.conn, conf, 123456789)
        self.assertIsNone(report["zone_seconds"])
        self.assertIsNotNone(report["reason"])
        self.assertEqual(report["reason_code"], "unknown_activity")

    def test_activity_zone_report_reasons_without_samples(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.index()
        conf = I.settings(I.load_config(self.ws))
        report = I.activity_zone_report(self.conn, conf, self.GARMIN_ID)
        self.assertIsNone(report["zone_seconds"])
        self.assertEqual(report["method"], "karvonen")
        self.assertIsNotNone(report["reason"])

    def test_activity_zone_report_returns_seconds_and_polarisation(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        self.index()
        conf = I.settings(I.load_config(self.ws))
        report = I.activity_zone_report(self.conn, conf, self.GARMIN_ID)
        self.assertIsNotNone(report["zone_seconds"])
        self.assertIsNotNone(report["polarisation"])
        self.assertIsNone(report["reason"])

    def _run_cli(self, args) -> tuple:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = I.main(args)
        return code, buf.getvalue()

    def test_cli_zones_command_prints_bounds_and_method(self):
        self.write_profile(hr_max=188, hr_rest=48)
        out = self.tmp / "db.sqlite"
        code, stdout = self._run_cli(["zones", "--workspace", str(self.ws), "--db", str(out), "--today", "2026-09-25"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["method"], "karvonen")
        self.assertEqual([round(b) for b in payload["bounds_bpm"]], [118, 132, 146, 160, 174, 188])
        self.assertIsNone(payload["reason"])
        self.assertIn("weekly_polarisation", payload)

    def test_cli_zones_command_with_activity_selector_prints_zone_seconds(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        out = self.tmp / "db.sqlite"
        code, stdout = self._run_cli(["zones", "--activity", str(self.GARMIN_ID),
                                      "--workspace", str(self.ws), "--db", str(out), "--today", "2026-09-25"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["method"], "karvonen")
        self.assertEqual(payload["zone_seconds"], {"2": 20.0})
        self.assertIsNotNone(payload["polarisation"])

    def test_cli_zones_command_with_invalid_override_falls_back_to_auto(self):
        """Revue de code #43, point 4 : une méthode invalide dans la config n'empêche
        pas la commande de rendre un résultat (repli sur « auto », avertissement à
        part sur stderr — pas testé ici, voir `_hr_zone_method`)."""
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_hr_zones_override("PAS-UNE-METHODE")
        out = self.tmp / "db.sqlite"
        code, stdout = self._run_cli(["zones", "--workspace", str(self.ws), "--db", str(out), "--today", "2026-09-25"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["method"], "karvonen")   # auto, résolu sur Karvonen
        self.assertIsNone(payload["reason"])


class TestWeeklyPolarisation(Workspace):
    def test_week_without_any_samples_is_none(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(90000000010, day="2026-09-21")   # lundi de la semaine courante, sans FIT
        self.index()
        weeks = I.weekly_polarisation(self.conn, 2, date(2026, 9, 25))
        self.assertTrue(any(w["polarisation"] is None for w in weeks))

    def test_week_with_samples_has_polarisation(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(90000000011, day="2026-09-21")
        self.write_fit(90000000011, hr_bpm=120.0)
        self.index()
        weeks = I.weekly_polarisation(self.conn, 2, date(2026, 9, 25))
        matching = [w for w in weeks if w["polarisation"] is not None]
        self.assertTrue(matching)
        self.assertAlmostEqual(matching[0]["polarisation"]["low_pct"], 100.0)

    def test_week_with_only_excluded_sport_is_none(self):
        """Une séance de renforcement avec échantillons FIT ne doit pas suffire à
        remplir une semaine de polarisation — voir `TestSportFamilyRestriction`."""
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(90000000012, day="2026-09-21", sport="strength")
        self.write_fit(90000000012, hr_bpm=120.0)
        self.index()
        weeks = I.weekly_polarisation(self.conn, 2, date(2026, 9, 25))
        current_week = next(w for w in weeks if w["week_start"] == "2026-09-21")
        self.assertIsNone(current_week["polarisation"])


class TestApiLoadHrZonesReason(Workspace):
    """Revue de code #43, round 3 : `/api/load` doit porter une raison explicite
    quand AUCUNE zone n'est calculable pour ce profil, pour que la section
    « Polarisation 80/20 » de Forme & charge ne disparaisse pas silencieusement."""

    def _api_load(self):
        store = arc_serve.Store(self.ws, memory=True, today="2026-09-25")
        return arc_serve.api_load(store, {})

    def test_reason_present_without_any_profile(self):
        payload = self._api_load()
        self.assertIsNotNone(payload["hr_zones_reason"])
        self.assertNotIn("`", payload["hr_zones_reason"])   # pas de backtick brut affiché en UI

    def test_reason_none_when_zones_are_computable(self):
        self.write_profile(hr_max=188, hr_rest=48)
        payload = self._api_load()
        self.assertIsNone(payload["hr_zones_reason"])

    def test_reason_present_and_backtick_free_when_forced_method_incomplete(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_hr_zones_override("lthr")
        payload = self._api_load()
        self.assertIsNotNone(payload["hr_zones_reason"])
        self.assertNotIn("`", payload["hr_zones_reason"])


if __name__ == "__main__":
    unittest.main()
