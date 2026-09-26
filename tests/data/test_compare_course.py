"""Palier D — intégration de l'identité de montée entre séances (#49) au skill
`course-comparison` (`skills/course-comparison/scripts/compare_course.py`).

Le script travaille par défaut UNIQUEMENT sur les fichiers Markdown (splits km),
inchangé par #49 (`render_report`/`main` sans `--workspace`) — `climb_segment_report`
est un COMPLÉMENT optionnel qui lit l'index dérivé du moteur (`.arc/coach.db`,
`scripts/arc_index.py`) quand il existe déjà pour le workspace, et n'ajoute une
section au rapport que si des segments correspondent au lieu demandé.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/course-comparison/scripts"))
sys.path.insert(0, str(REPO))

import arc_index as I  # noqa: E402
import compare_course as CC  # noqa: E402


def _arc_activity(day: str, *, garmin_id: int, location: str = "Tournai", duration_s=1800,
                   distance_m=3600) -> str:
    return (f"# Titre\n\n```arc\n"
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "trail", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, "location": "{location}", '
            f'"garmin_activity_id": {garmin_id}}}\n```\n\nTexte du coach.\n')


class TestClimbSegmentReportWithoutIndex(unittest.TestCase):
    """`climb_segment_report` ne doit JAMAIS lever d'exception ni exiger d'index —
    c'est ce qui garantit la compatibilité ascendante de la sortie par défaut."""

    def test_no_workspace_given_is_none(self):
        self.assertIsNone(CC.climb_segment_report(["Tournai"], None))

    def test_workspace_without_arc_db_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(CC.climb_segment_report(["Tournai"], tmp))

    def test_workspace_with_unrelated_arc_db_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".arc").mkdir()
            (Path(tmp) / ".arc" / "coach.db").write_bytes(b"not a real sqlite file")
            self.assertIsNone(CC.climb_segment_report(["Tournai"], tmp))


class TestReportBackwardCompatible(unittest.TestCase):
    """Critère d'acceptation #49 : sortie byte pour byte identique à avant #49 sur
    des entrées existantes (ici : sans `--workspace`, ou `--workspace` sans index)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="compare-course-"))
        self.activities = self.tmp / "activities"
        self.activities.mkdir()
        (self.activities / "2026-09-01_trail.md").write_text(
            _arc_activity("2026-09-01", garmin_id=90000000801), encoding="utf-8")
        (self.activities / "2026-09-10_trail.md").write_text(
            _arc_activity("2026-09-10", garmin_id=90000000802, duration_s=1700), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _report(self, workspace=None):
        acts = CC.discover_activities(str(self.activities), ["Tournai"], None, None)
        ref = next(a for a in acts if a["date"] == "2026-09-10")
        others = [a for a in acts if a["date"] != "2026-09-10"]
        segments = CC.climb_segment_report(["Tournai"], workspace)
        return CC.render_report(ref, others, None, 50, 40.0, segments)

    def test_no_section_5_without_workspace(self):
        report = self._report(workspace=None)
        self.assertNotIn("Montées identifiées comme la même ascension", report)

    def test_identical_output_whether_workspace_arg_given_or_not_when_no_index_exists(self):
        report_without = self._report(workspace=None)
        report_with_absent_index = self._report(workspace=str(self.tmp))
        self.assertEqual(report_without, report_with_absent_index)


class TestClimbSegmentSectionAppearsWhenIndexAvailable(unittest.TestCase):
    """Construit un VRAI index (`arc_index.index_workspace`, écrit sur disque à
    `<workspace>/.arc/coach.db`) avec une montée FIT injectée sur deux séances du
    même lieu, la seconde plus rapide — vérifie que la section 5 apparaît, contient
    la progression, et que les sections 1-4 restent inchangées par rapport à l'appel
    sans workspace (compatibilité ascendante)."""

    GARMIN_A = 90000000811
    GARMIN_B = 90000000812

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="compare-course-idx-"))
        self.ws = self.tmp  # le workspace ET le dossier passé à --dir partagent la racine ici
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        (self.ws / "activities/2026-09-01_trail.md").write_text(
            _arc_activity("2026-09-01", garmin_id=self.GARMIN_A), encoding="utf-8")
        (self.ws / "activities/2026-09-10_trail.md").write_text(
            _arc_activity("2026-09-10", garmin_id=self.GARMIN_B), encoding="utf-8")
        self._write_fit_gps_climb(self.GARMIN_A, duration_s=1800)
        self._write_fit_gps_climb(self.GARMIN_B, duration_s=1710)  # 5 % plus rapide
        conn = I.open_db(self.ws, memory=False)
        I.index_workspace(conn, self.ws, "2026-09-15")
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_fit_gps_climb(self, garmin_id, *, duration_s, gain_m=300.0, distance_m=3600.0,
                              resolution_s=5):
        import json
        n = duration_s // resolution_s + 1
        speed = distance_m / duration_s
        records = []
        for i in range(n):
            t = i * resolution_s
            frac = min(1.0, t / duration_s)
            records.append({"t_s": float(t), "distance_m": round(distance_m * frac, 2),
                             "altitude_m": round(gain_m * frac, 2), "hr_bpm": 150.0,
                             "speed_ms": speed, "cadence_spm": 160.0,
                             "lat_deg": 46.0 + 0.01 * frac, "lon_deg": 7.0 + 0.01 * frac})
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def test_section_5_appears_with_progression(self):
        segments = CC.climb_segment_report(["Tournai"], str(self.ws))
        self.assertIsNotNone(segments)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["occurrences"], 2)
        self.assertAlmostEqual(segments[0]["last_vs_previous_pct"], 5.1, delta=0.5)
        section = CC.render_climb_segment_section(segments)
        self.assertIn("Montées identifiées comme la même ascension", section)
        self.assertIn("+5.1 %", section)

    def test_unrelated_location_yields_no_segments(self):
        self.assertIsNone(CC.climb_segment_report(["Un Autre Lieu Jamais Enregistré"], str(self.ws)))

    def test_sections_1_to_4_unchanged_by_the_new_section(self):
        acts = CC.discover_activities(str(self.ws / "activities"), ["Tournai"], None, None)
        ref = next(a for a in acts if a["date"] == "2026-09-10")
        others = [a for a in acts if a["date"] != "2026-09-10"]
        without = CC.render_report(ref, others, None, 50, 40.0, None)
        segments = CC.climb_segment_report(["Tournai"], str(self.ws))
        withit = CC.render_report(ref, others, None, 50, 40.0, segments)
        self.assertTrue(withit.startswith(without.rstrip("\n")))


if __name__ == "__main__":
    unittest.main()
