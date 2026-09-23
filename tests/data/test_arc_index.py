"""Palier D — index dérivé : chaîne de lecture, incrémentalité, et les défauts
trouvés sur un vrai workspace (doublons, fichiers d'analyse, fichiers sans date).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_legacy as L  # noqa: E402

FIXTURES = REPO / "tests/evals/fixtures"

CANONICAL = """# Activité – Samedi 31 mai 2025 (Tournai Trail)
**Lieu :** Tournai

## Données brutes Garmin (référence)

```yaml
activity_id: 19287537093
name: Tournai Trail
distance_m: 25190
duration_s: 10802
avg_hr_bpm: 132
```

## Analyse par splits (km)

| Split | Durée | Allure | Vmax | D+/D- | FC moy | Cadence | Lecture |
|---|---|---|---|---|---|---|---|
| 1 | 5:56 | 5:56 | 11.6 | +3/-36 | 117 | 169 | Échauffement |
| 2 | 5:47 | 5:47 | 12.1 | +10/-4 | 128 | 173 | |
"""


def arc(kind_line: str) -> str:
    return f"# Titre\n\n```arc\n{kind_line}\n```\n\nTexte du coach.\n"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-index-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.conn = I.open_db(self.ws, memory=True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        (self.ws / rel).write_text(text, encoding="utf-8")

    def index(self):
        return I.index_workspace(self.conn, self.ws, "2026-09-23")

    def status(self, rel):
        row = self.conn.execute("SELECT parsed_ok, arc_version FROM source_file WHERE path = ?", (rel,)).fetchone()
        return tuple(row) if row else None


class TestReadingChain(Workspace):
    def test_arc_block_first(self):
        self.write("activities/2026-09-20_trail.md", arc('{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, "distance_m": 10000}'))
        self.index()
        self.assertEqual(self.status("activities/2026-09-20_trail.md"), ("ok", 1))

    def test_canonical_legacy_format(self):
        """Le format YAML + splits du sync reste lu, splits compris, marqué partiel."""
        self.write("activities/2025-05-31_trail.md", CANONICAL)
        self.index()
        self.assertEqual(self.status("activities/2025-05-31_trail.md"), ("partial", 0))
        row = self.conn.execute("SELECT garmin_activity_id, distance_m, location FROM activity").fetchone()
        self.assertEqual(tuple(row), (19287537093, 25190, "Tournai"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM activity_split").fetchone()[0], 2)

    def test_bullets_from_eval_fixture(self):
        """Les fixtures d'évals (puces, nombres à la française) sont lues sans bloc."""
        shutil.copytree(FIXTURES / "base-week", self.ws, dirs_exist_ok=True)
        self.index()
        row = self.conn.execute("SELECT distance_m, duration_s, elevation_gain_m, avg_hr_bpm FROM activity WHERE date = '2026-03-03'").fetchone()
        self.assertEqual(tuple(row), (12400.0, 4320.0, 480.0, 152.0))
        athlete = self.conn.execute("SELECT hr_max_bpm, hr_rest_bpm FROM athlete").fetchone()
        self.assertEqual(tuple(athlete), (188, 48))

    def test_free_text_is_flagged_not_stored(self):
        self.write("activities/2026-05-06_strength.md", "# Activité\n\nAucune activité enregistrée ce jour.\n")
        self.index()
        self.assertEqual(self.status("activities/2026-05-06_strength.md")[0], "no")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0], 0,
                         "un fichier « aucune activité » est devenu une séance")

    def test_invalid_block_falls_back_and_is_reported(self):
        self.write("medical/2026-09-20_health.md", "# Santé\n\n```arc\n{\"arc\": 1, \"kind\": \"health\", \"date\": \"2026-09-20\"}\n```\n\n- FC de repos : 44 bpm\n")
        self.index()
        self.assertEqual(self.status("medical/2026-09-20_health.md")[0], "invalid")
        self.assertIn("medical/2026-09-20_health.md", [i["path"] for i in I.backfill_items(self.conn)])


class TestRealWorkspaceRegressions(Workspace):
    def test_duplicate_garmin_id_counted_once(self):
        """Même séance décrite dans deux fichiers (résumé + détail) : une seule charge."""
        block = '{"arc": 1, "kind": "activity", "date": "2026-05-04", "sport": "home_trainer", "duration_s": 1906, "garmin_activity_id": 22764233338}'
        self.write("activities/2026-05-04_home_trainer.md", arc(block))
        self.write("activities/2026-05-04_home_trainer_endurance.md", arc(block))
        self.index()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0], 1)

    def test_analysis_file_is_not_an_activity(self):
        """`2026-08-21_strides_analysis.md` : « Distance moyenne 92 m » n'est pas une séance."""
        self.write("activities/2026-08-21_strides_analysis.md", "# Analyse\n\n- Distance moyenne par segment : 92 m\n")
        self.index()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0], 0)

    def test_dateless_file_ignored(self):
        """`2026-04-11b_health.md` : pas de date sûre, rien à tracer."""
        self.write("medical/2026-04-11b_health.md", "# Nuit (suite)\n\n| Sommeil | 7h12 |\n| FC Repos matinale | 45 bpm |\n")
        self.index()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM health_day").fetchone()[0], 0)

    def test_objective_written_as_table(self):
        """Objectif antérieur au modèle, en tableau libellé | valeur."""
        self.write("planning/active_objective.md", "# Objectif\n\n| Champ | Valeur |\n|:--|:--|\n| **Course** | Ultra 110 km |\n"
                   "| **Date** | Dimanche 13 Septembre 2026 |\n| **Distance** | 109.79 km |\n| **Dénivelé +** | 1768 m |\n"
                   "| **Lieu d'entraînement par défaut** | Lille |\n| **Lieu course (J-13/09)** | Wimereux |\n")
        self.index()
        row = self.conn.execute("SELECT name, race_date, distance_m, elevation_gain_m, location FROM objective").fetchone()
        self.assertEqual(tuple(row), ("Ultra 110 km", "2026-09-13", 109790.0, 1768.0, "Wimereux"))

    def test_incremental_reindex(self):
        self.write("activities/2026-09-20_trail.md", arc('{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600}'))
        self.assertEqual(self.index()["indexed"], 1)
        again = self.index()
        self.assertEqual((again["indexed"], again["unchanged"]), (0, 1))
        (self.ws / "activities/2026-09-20_trail.md").unlink()
        self.assertEqual(self.index()["removed"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0], 0)

    def test_rebuild_keeps_open_connections_valid(self):
        """--rebuild pendant que le tableau de bord tourne : l'autre connexion survit."""
        db = self.tmp / "coach.db"
        reader = I.open_db(self.ws, str(db))
        I.index_workspace(reader, self.ws, "2026-09-23")
        rebuilder = I.open_db(self.ws, str(db), rebuild=True)
        I.index_workspace(rebuilder, self.ws, "2026-09-23")
        rebuilder.close()
        try:
            I.index_workspace(reader, self.ws, "2026-09-23")
        except sqlite3.DatabaseError as exc:
            self.fail(f"connexion ouverte invalidée par --rebuild : {exc}")
        finally:
            reader.close()

    def test_morning_check_off_expects_no_health_keys(self):
        conf = {"morning_check": "off", "sport": "trail"}
        self.assertEqual(I.expected_keys("health", {"morning_check": "off"}, conf), [])
        self.assertEqual(I.expected_keys("health", {"morning_check": "minimal"}, conf), ["readiness_score", "verdict"])


class TestFrenchNumbers(unittest.TestCase):
    def test_numbers(self):
        for text, expected in (("2 400 m", 2400.0), ("2 400", 2400.0), ("12,4 km", 12.4), ("188", 188.0), ("-3,5", -3.5)):
            self.assertEqual(L.parse_fr_number(text), expected, text)

    def test_durations(self):
        for text, expected in (("1 h 12", 4320), ("4h39m53s", 16793), ("1:23:26", 5006), ("5:58", 358),
                               ("48 min 58 s", 2938), ("40 min", 2400), ("7 h 00", 25200)):
            self.assertEqual(L.parse_fr_duration(text), expected, text)

    def test_distances_and_dates(self):
        self.assertEqual(L.parse_fr_distance_m("12,4 km"), 12400.0)
        self.assertEqual(L.parse_fr_distance_m("480 m"), 480.0)
        self.assertEqual(L.parse_fr_date("13 juin 2026"), "2026-06-13")
        self.assertEqual(L.parse_fr_date("1er mai 2026"), "2026-05-01")
        self.assertEqual(L.parse_fr_date("13/06/2026"), "2026-06-13")

    def test_sport_from_filename(self):
        self.assertEqual(L.sport_from_filename("2026-05-04_home_trainer_endurance.md"), "home_trainer")
        self.assertIsNone(L.sport_from_filename("2026-08-21_strides_analysis.md"))
        self.assertEqual(L.sport_from_filename("2026-08-24_walking.md"), "walking")


if __name__ == "__main__":
    unittest.main()
