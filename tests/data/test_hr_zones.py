"""Palier D — zones FC, temps en zone et polarisation 80/20 (#43).

Trois familles de tests :
- `arc_metrics.hr_zone_bounds`/`time_in_zone_seconds`/`polarisation_shares`, purs,
  contre des valeurs de référence à la main et contre la vérité connue du générateur
  synthétique (`tests/lib/synthetic.sample_session`, story #25).
- `arc_index` : la table dérivée `hr_zone_time` se recalcule à chaque passage
  (changement de profil compris), la CLI `zones`, la polarisation hebdomadaire.
"""

from __future__ import annotations

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
        self.assertEqual(round(bounds[1]), round(172 * 0.85))

    def test_percent_max_is_the_last_resort(self):
        bounds, method = M.hr_zone_bounds({"hr_max_bpm": 190})
        self.assertEqual(method, "percent_max")
        self.assertEqual(round(bounds[1]), round(190 * 0.60))

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

    def test_hr_zone_of_saturates(self):
        bounds = (118, 132, 146, 160, 174, 188)
        self.assertEqual(M.hr_zone_of(50, bounds), 1)     # bien en dessous : zone 1
        self.assertEqual(M.hr_zone_of(200, bounds), 5)    # bien au-dessus : zone 5 (jamais hors zone)
        self.assertEqual(M.hr_zone_of(131.9, bounds), 1)
        self.assertEqual(M.hr_zone_of(132.0, bounds), 2)


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


class TestPolarisation(unittest.TestCase):
    def test_seiler_mapping_low_moderate_high(self):
        zone_seconds = {1: 100.0, 2: 50.0, 3: 30.0, 4: 10.0, 5: 10.0}
        shares = M.polarisation_shares(zone_seconds)
        self.assertAlmostEqual(shares["low_s"], 150.0)
        self.assertAlmostEqual(shares["moderate_s"], 30.0)
        self.assertAlmostEqual(shares["high_s"], 20.0)
        self.assertAlmostEqual(shares["low_pct"], 75.0)
        self.assertAlmostEqual(shares["moderate_pct"], 15.0)
        self.assertAlmostEqual(shares["high_pct"], 10.0)

    def test_string_zone_keys_are_accepted(self):
        """`hr_zone_time`/JSON rendent parfois des clés de zone en chaîne."""
        shares = M.polarisation_shares({"1": 100.0, "5": 100.0})
        self.assertAlmostEqual(shares["low_pct"], 50.0)
        self.assertAlmostEqual(shares["high_pct"], 50.0)

    def test_none_when_empty_or_zero(self):
        self.assertIsNone(M.polarisation_shares({}))
        self.assertIsNone(M.polarisation_shares({1: 0.0, 2: 0.0}))


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
        (self.ws / rel).write_text(text, encoding="utf-8")

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

    def write_activity(self, garmin_id, day="2026-09-20", duration_s=3600, distance_m=10000):
        self.write(f"activities/{day}_trail.md", arc(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "trail", '
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


class TestActivityZoneReportAndCli(Workspace):
    GARMIN_ID = 90000000003

    def test_activity_zone_report_reasons_without_profile(self):
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID)
        conf = I.settings(I.load_config(self.ws))
        self.index()
        report = I.activity_zone_report(self.conn, conf, self.GARMIN_ID)
        self.assertIsNone(report["zone_seconds"])
        self.assertIn("reason", report)

    def test_activity_zone_report_reasons_without_samples(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.index()
        conf = I.settings(I.load_config(self.ws))
        report = I.activity_zone_report(self.conn, conf, self.GARMIN_ID)
        self.assertIsNone(report["zone_seconds"])
        self.assertEqual(report["method"], "karvonen")

    def test_activity_zone_report_returns_seconds_and_polarisation(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        self.index()
        conf = I.settings(I.load_config(self.ws))
        report = I.activity_zone_report(self.conn, conf, self.GARMIN_ID)
        self.assertIsNotNone(report["zone_seconds"])
        self.assertIsNotNone(report["polarisation"])

    def test_cli_zones_command_prints_bounds(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.index()
        out = self.tmp / "db.sqlite"
        code = I.main(["zones", "--workspace", str(self.ws), "--db", str(out), "--today", "2026-09-25"])
        self.assertEqual(code, 0)

    def test_cli_zones_command_with_activity_selector(self):
        self.write_profile(hr_max=188, hr_rest=48)
        self.write_activity(self.GARMIN_ID)
        self.write_fit(self.GARMIN_ID, hr_bpm=140.0)
        out = self.tmp / "db.sqlite"
        code = I.main(["zones", "--activity", str(self.GARMIN_ID),
                       "--workspace", str(self.ws), "--db", str(out), "--today", "2026-09-25"])
        self.assertEqual(code, 0)


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


if __name__ == "__main__":
    unittest.main()
