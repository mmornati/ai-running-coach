"""Palier D — index dérivé : chaîne de lecture, incrémentalité, et les défauts
trouvés sur un vrai workspace (doublons, fichiers d'analyse, fichiers sans date).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_metrics as M  # noqa: E402

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


class TestFitSampleIngestion(Workspace):
    """Palier D — ingestion des échantillons FIT (#42) : `activities/fit/*.json` →
    `activity_sample`. Incrémentalité, idempotence, liens par `garmin_activity_id`
    (jamais le rowid interne `activity.id` — voir revue PR #87), suppression."""

    GARMIN_ID = 90000000001

    def _write_activity(self, garmin_id=None, date="2026-09-20", duration_s=3600, distance_m=10000):
        garmin_id = self.GARMIN_ID if garmin_id is None else garmin_id
        self.write(f"activities/{date}_trail.md", arc(
            f'{{"arc": 1, "kind": "activity", "date": "{date}", "sport": "trail", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, "garmin_activity_id": {garmin_id}}}'
        ))

    def _write_fit(self, garmin_id=None, n=20, resolution=1):
        garmin_id = self.GARMIN_ID if garmin_id is None else garmin_id
        records = [
            {"t_s": t, "distance_m": float(t) * 2.5, "altitude_m": 0.0, "hr_bpm": 140.0 + (t % 5),
             "speed_ms": 2.5, "cadence_spm": 170.0}
            for t in range(0, n, resolution)
        ]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def _row_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM activity_sample").fetchone()[0]

    def _internal_id(self, garmin_id=None):
        garmin_id = self.GARMIN_ID if garmin_id is None else garmin_id
        row = self.conn.execute("SELECT id FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()
        return row["id"] if row else None

    def test_matching_activity_gets_samples(self):
        self._write_activity()
        self._write_fit()
        counts = self.index()
        self.assertEqual(counts["fit_ingestion"], {"ingested": 1, "unchanged": 0, "removed": 0, "invalid": 0})
        self.assertGreater(self._row_count(), 0)
        rows = self.conn.execute(
            "SELECT garmin_activity_id FROM activity_sample WHERE garmin_activity_id != ?", (self.GARMIN_ID,)
        ).fetchall()
        self.assertEqual(rows, [])

    def test_samples_are_downsampled_to_5s_by_default(self):
        self._write_activity()
        self._write_fit(n=20, resolution=1)   # 20 échantillons/s -> 4 buckets de 5 s attendus
        self.index()
        self.assertEqual(self._row_count(), 4)

    def test_two_ingestions_produce_identical_rows(self):
        """Idempotence : deux passes sans changement de fichier -> mêmes lignes."""
        self._write_activity()
        self._write_fit()
        self.index()
        before = sorted(tuple(r) for r in self.conn.execute(
            "SELECT garmin_activity_id, t_s, distance_m, hr_bpm FROM activity_sample ORDER BY t_s").fetchall())
        counts2 = self.index()
        after = sorted(tuple(r) for r in self.conn.execute(
            "SELECT garmin_activity_id, t_s, distance_m, hr_bpm FROM activity_sample ORDER BY t_s").fetchall())
        self.assertEqual(before, after)
        self.assertEqual(counts2["fit_ingestion"]["unchanged"], 1)
        self.assertEqual(counts2["fit_ingestion"]["ingested"], 0)

    def test_changed_file_is_replaced_not_duplicated(self):
        self._write_activity()
        self._write_fit(n=20)
        self.index()
        rows_before = self._row_count()
        self._write_fit(n=40)   # même fichier, deux fois plus d'échantillons
        counts = self.index()
        self.assertEqual(counts["fit_ingestion"]["ingested"], 1)
        self.assertGreater(self._row_count(), rows_before)

    def test_deleted_fit_file_removes_its_samples(self):
        self._write_activity()
        self._write_fit()
        self.index()
        self.assertGreater(self._row_count(), 0)
        (self.ws / f"activities/fit/{self.GARMIN_ID}.json").unlink()
        counts = self.index()
        self.assertEqual(counts["fit_ingestion"]["removed"], 1)
        self.assertEqual(self._row_count(), 0)

    def test_invalid_json_is_counted_invalid_not_ingested(self):
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / "123.json").write_text("{ceci n'est pas du JSON", encoding="utf-8")
        counts = self.index()
        self.assertEqual(counts["fit_ingestion"]["invalid"], 1)
        self.assertEqual(counts["fit_ingestion"]["ingested"], 0)
        self.assertEqual(self._row_count(), 0)

    def test_activity_without_samples_is_unaffected(self):
        """Une séance sans FIT associé reste une séance normale : rien ne casse."""
        self._write_activity()
        counts = self.index()
        self.assertEqual(counts["fit_ingestion"], {"ingested": 0, "unchanged": 0, "removed": 0, "invalid": 0})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0], 1)
        self.assertEqual(self._row_count(), 0)

    def test_samples_accessor_returns_ordered_rows(self):
        self._write_activity()
        self._write_fit(n=30)
        self.index()
        rows = I.samples(self.conn, self._internal_id())
        self.assertEqual([r["t_s"] for r in rows], sorted(r["t_s"] for r in rows))
        for key in ("t_s", "distance_m", "altitude_m", "hr_bpm", "speed_ms", "cadence_spm"):
            self.assertIn(key, rows[0])

    def test_samples_accessor_empty_for_activity_without_fit(self):
        self._write_activity()
        self.index()
        self.assertEqual(I.samples(self.conn, self._internal_id()), [])

    def test_samples_by_garmin_id_reports_reason_when_nothing_ingested(self):
        result = I.samples_by_garmin_id(self.conn, 12345)
        self.assertEqual(result["samples"], [])
        self.assertIn("reason", result)

    def test_repeated_indexing_without_fit_dir_is_a_noop(self):
        """Un workspace sans `activities/fit/` du tout ne doit ni planter ni rien compter."""
        self._write_activity()
        counts = self.index()
        self.assertEqual(counts["fit_ingestion"], {"ingested": 0, "unchanged": 0, "removed": 0, "invalid": 0})

    def test_status_reports_sample_coverage(self):
        self._write_activity()
        self._write_fit(n=10)
        self.index()
        coverage = I.sample_coverage(self.conn)
        self.assertEqual(coverage["activities_with_samples"], 1)
        self.assertEqual(coverage["unlinked_garmin_ids"], 0)
        self.assertGreater(coverage["rows"], 0)

    def test_orphan_fit_sample_counted_as_unlinked_not_lost(self):
        self._write_fit(garmin_id=999999999999)
        self.index()
        coverage = I.sample_coverage(self.conn)
        self.assertEqual(coverage["unlinked_garmin_ids"], 1)
        self.assertGreater(coverage["rows"], 0, "les échantillons doivent être stockés même sans activité")

    def test_backfill_items_never_lists_fit_sample_files(self):
        """Régression (#42, revue PR #87, blocker 2) : `backfill_items` lit `source_file`,
        qui ne doit JAMAIS contenir de ligne `fit_sample` (table dédiée `sample_file`) —
        sinon un FIT orphelin ou invalide serait listé comme une dette de contrat
        Markdown, ce qu'il n'est pas."""
        self._write_fit(garmin_id=999999999999)   # orphelin
        fit_dir = self.ws / "activities/fit"
        (fit_dir / "invalide.json").write_text("{pas du JSON", encoding="utf-8")   # invalide
        self.index()
        paths = [item["path"] for item in I.backfill_items(self.conn)]
        self.assertEqual([p for p in paths if p.startswith("activities/fit/")], [])


class TestFitSampleLinkingBugs(Workspace):
    """Régressions ciblées (revue PR #87, blocker 1) : `activity_sample` était keyé sur
    le rowid interne `activity.id`, qui change à chaque purge/réinsertion d'un Markdown
    (`_purge`/`store`) et peut être RÉATTRIBUÉ à une autre séance après suppression.
    Ces trois scénarios sont les repros exacts de la revue."""

    GARMIN_ID = 90000000001

    def _write_fit(self, garmin_id, n=10):
        records = [{"t_s": t, "distance_m": float(t) * 2.5, "altitude_m": 0.0, "hr_bpm": 140.0,
                    "speed_ms": 2.5, "cadence_spm": 170.0} for t in range(n)]
        fit_dir = self.ws / "activities/fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{garmin_id}.json").write_text(
            json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")

    def _write_activity(self, garmin_id, date, duration_s=3600, distance_m=10000):
        self.write(f"activities/{date}_trail.md", arc(
            f'{{"arc": 1, "kind": "activity", "date": "{date}", "sport": "trail", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, "garmin_activity_id": {garmin_id}}}'
        ))

    def test_fit_indexed_before_its_md_is_not_lost(self):
        """Repro 1 : le FIT arrive avant le Markdown de la séance (téléchargement puis
        synchronisation, ou l'inverse en `daily-sync`). Une version antérieure comptait
        ce fichier « orphan » et ne le réingérait jamais (sha256 inchangé → sauté pour
        toujours), même une fois le Markdown apparu."""
        self._write_fit(self.GARMIN_ID)
        self.index()   # FIT seul : aucune activité encore
        self.assertEqual(len(I.samples_by_garmin_id(self.conn, self.GARMIN_ID)["samples"]), 2)

        self._write_activity(self.GARMIN_ID, "2026-09-20")
        self.index()   # le Markdown apparaît ; le FIT n'a pas changé (même sha256)
        activity_id = self.conn.execute(
            "SELECT id FROM activity WHERE garmin_activity_id = ?", (self.GARMIN_ID,)).fetchone()["id"]
        rows = I.samples(self.conn, activity_id)
        self.assertEqual(len(rows), 2, "les échantillons ingérés avant le Markdown doivent rester accessibles")

    def test_md_edited_after_ingestion_keeps_its_samples(self):
        """Repro 2 : le Markdown est réécrit (purge + réinsertion, `store()`) après que
        le FIT a été ingéré. Le rowid interne change ; les échantillons ne doivent PAS
        rester accrochés à l'ancien id."""
        self._write_activity(self.GARMIN_ID, "2026-09-20")
        self._write_fit(self.GARMIN_ID)
        self.index()
        old_internal_id = self.conn.execute(
            "SELECT id FROM activity WHERE garmin_activity_id = ?", (self.GARMIN_ID,)).fetchone()["id"]

        self._write_activity(self.GARMIN_ID, "2026-09-20", duration_s=3700, distance_m=10500)   # édition
        self.index()
        new_internal_id = self.conn.execute(
            "SELECT id FROM activity WHERE garmin_activity_id = ?", (self.GARMIN_ID,)).fetchone()["id"]

        rows = I.samples(self.conn, new_internal_id)
        self.assertEqual(len(rows), 2, "les échantillons ne doivent pas rester sur l'ancien rowid")
        if new_internal_id != old_internal_id:
            self.assertEqual(I.samples(self.conn, old_internal_id), [])

    def test_deleted_md_then_reused_rowid_does_not_steal_samples(self):
        """Repro 3 : le Markdown de la séance A est supprimé, puis une séance B, SANS
        FIT, est indexée — SQLite peut réattribuer le rowid libéré par A à B. B ne doit
        JAMAIS hériter des échantillons de A."""
        self._write_activity(self.GARMIN_ID, "2026-09-20")
        self._write_fit(self.GARMIN_ID)
        self.index()
        a_internal_id = self.conn.execute(
            "SELECT id FROM activity WHERE garmin_activity_id = ?", (self.GARMIN_ID,)).fetchone()["id"]
        self.assertGreater(len(I.samples(self.conn, a_internal_id)), 0)

        (self.ws / "activities/2026-09-20_trail.md").unlink()
        self.index()   # A retirée de `activity` — ses échantillons FIT restent en base, non rattachés

        other_id = self.GARMIN_ID + 1
        self._write_activity(other_id, "2026-09-21")   # B : aucun FIT pour elle
        self.index()
        b_internal_id = self.conn.execute(
            "SELECT id FROM activity WHERE garmin_activity_id = ?", (other_id,)).fetchone()["id"]

        self.assertEqual(I.samples(self.conn, b_internal_id), [],
                         "B ne doit jamais hériter des échantillons de A via un rowid réutilisé")


class TestHrvBaselineCli(Workspace):
    """#34 — `arc_index.py hrv-baseline` : la seule voie sans tableau de bord (headless,
    `/garmin-daily-sync` compris) vers la ligne de base HRV personnelle."""

    def health(self, day: str, hrv_ms: float, mode: str = "full") -> None:
        self.write(f"medical/{day}_health.md",
                  arc(f'{{"arc": 1, "kind": "health", "date": "{day}", "morning_check": "{mode}", '
                      f'"hrv_overnight_ms": {hrv_ms}}}'))

    def test_full_mode_returns_the_computed_point(self):
        for i in range(40):
            day = f"2026-08-{i + 1:02d}" if i < 31 else f"2026-09-{i - 30:02d}"
            self.health(day, 60.0)
        self.index()
        conf = {"morning_check": "full"}
        point = I.hrv_baseline_today(self.conn, conf, date(2026, 9, 9))
        self.assertEqual(point["morning_check"], "full")
        self.assertIsNotNone(point["hrv_ln_mean7"])
        self.assertEqual(point["hrv_personal_status"], "dans_la_norme")

    def test_minimal_mode_returns_no_status_and_says_why(self):
        """`[health].morning_check = "minimal"` : rien de calculé, jamais un statut deviné
        depuis un historique qui n'aurait de toute façon pas dû être récupéré ce jour-là."""
        conf = {"morning_check": "minimal"}
        point = I.hrv_baseline_today(self.conn, conf, date(2026, 9, 9))
        self.assertIsNone(point["status"])
        self.assertEqual(point["morning_check"], "minimal")
        self.assertIn("full", point["reason"])

    def test_off_mode_returns_no_status(self):
        conf = {"morning_check": "off"}
        point = I.hrv_baseline_today(self.conn, conf, date(2026, 9, 9))
        self.assertIsNone(point["status"])
        self.assertEqual(point["morning_check"], "off")


class TestSleepDebtCli(Workspace):
    """#37 — `arc_index.py sleep-debt` : voie headless vers la dette de sommeil 7 j,
    même porte `[health].morning_check` que `hrv-baseline` (#34)."""

    def health(self, day: str, sleep_h: float, mode: str = "full") -> None:
        self.write(f"medical/{day}_health.md",
                  arc(f'{{"arc": 1, "kind": "health", "date": "{day}", "morning_check": "{mode}", '
                      f'"sleep_total_s": {sleep_h * 3600}}}'))

    def test_full_mode_returns_the_computed_debt(self):
        for day in ("2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06"):
            self.health(day, 5.0)
        self.index()
        conf = {"morning_check": "full"}
        point = I.sleep_debt_today(self.conn, conf, date(2026, 9, 9))
        self.assertEqual(point["morning_check"], "full")
        self.assertEqual(point["nights_counted"], 4)
        self.assertAlmostEqual(point["sleep_debt_7d_s"], 4 * 2.5 * 3600)
        self.assertEqual(point["sleep_need_s"], 7 * 3600 + 30 * 60, "défaut 7 h 30 sans profil")

    def test_uses_profile_sleep_need_when_present(self):
        self.write("planning/Runner_Profile.md", "# Profil\n\n## Physiologie\n\n- **Besoin de sommeil** : 8h00\n")
        for day in ("2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06"):
            self.health(day, 6.0)
        self.index()
        conf = {"morning_check": "full"}
        point = I.sleep_debt_today(self.conn, conf, date(2026, 9, 9))
        self.assertEqual(point["sleep_need_s"], 8 * 3600)
        self.assertAlmostEqual(point["sleep_debt_7d_s"], 4 * 2 * 3600)

    def test_below_min_nights_gives_none_but_counts(self):
        for day in ("2026-09-05", "2026-09-06"):
            self.health(day, 5.0)
        self.index()
        conf = {"morning_check": "full"}
        point = I.sleep_debt_today(self.conn, conf, date(2026, 9, 9))
        self.assertIsNone(point["sleep_debt_7d_s"])
        self.assertEqual(point["nights_counted"], 2)

    def test_minimal_mode_returns_no_debt_and_says_why(self):
        """`minimal` : rien de calculé (même porte que la ligne de base HRV, #34) — la
        readiness seule sort du bilan matinal, pas la dette de sommeil."""
        conf = {"morning_check": "minimal"}
        point = I.sleep_debt_today(self.conn, conf, date(2026, 9, 9))
        self.assertIsNone(point["sleep_debt_7d_s"])
        self.assertEqual(point["morning_check"], "minimal")
        self.assertIn("full", point["reason"])

    def test_off_mode_returns_no_debt(self):
        conf = {"morning_check": "off"}
        point = I.sleep_debt_today(self.conn, conf, date(2026, 9, 9))
        self.assertIsNone(point["sleep_debt_7d_s"])
        self.assertEqual(point["morning_check"], "off")


class TestTrailShapeCli(Workspace):
    """#63 — `arc_index.py trail-shape` : la formule elle-même (constantes, cas
    limites, renormalisation des poids) est verrouillée par
    `tests/data/test_arc_trail_shape.py` sur des dicts nus — ici, seulement le
    câblage SQL (lecture de `planning/active_objective.md` et des activités
    indexées, jamais un second calcul, voir `I.trail_shape_report`)."""

    def objective(self, race_date="2026-12-06", distance_km="21,1 km", dplus="1 200 m"):
        self.write("planning/active_objective.md", (
            "# Objectif actif\n\n## Course visée\n\n"
            f"- **Nom** : Trail des Crêtes\n- **Date** : {race_date}\n"
            f"- **Distance** : {distance_km}\n- **Dénivelé positif** : {dplus}\n"))

    def activity(self, day: str, distance_m: float, elevation_gain_m: float = 0, duration_s: float = 3600) -> None:
        self.write(f"activities/{day}_trail.md", arc(
            f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "trail", '
            f'"duration_s": {duration_s}, "distance_m": {distance_m}, "elevation_gain_m": {elevation_gain_m}}}'))

    def test_no_objective_reads_as_no_objective_status(self):
        self.index()
        report = I.trail_shape_report(self.conn, date(2026, 9, 23))
        self.assertEqual(report["status"], "no_objective")

    def test_objective_and_activities_flow_through_to_a_score(self):
        self.objective()
        today = date(2026, 9, 23)
        for i in range(6):
            day = (today - timedelta(days=i * 7)).isoformat()
            self.activity(day, 12000, 300)
        self.index()
        report = I.trail_shape_report(self.conn, today)
        self.assertEqual(report["status"], "ok")
        self.assertIsInstance(report["score"], float)
        self.assertEqual(report["objective"]["distance_m"], 21100.0)

    def test_no_d_plus_omits_the_max_dplus_component(self):
        self.objective(dplus="")
        self.activity("2026-09-20", 12000)
        self.index()
        report = I.trail_shape_report(self.conn, date(2026, 9, 23))
        by_id = {c["id"]: c for c in report["components"]}
        self.assertFalse(by_id["max_dplus"]["eligible"])


class TestHeatAcclimationCli(Workspace):
    """#38 — `arc_index.py heat-acclimation` : jointure activité outdoor / météo réelle
    (fichiers indexés, pas des dicts à la main comme `test_arc_metrics.py`), et
    l'indépendance de `[health].morning_check` (contrairement à `hrv-baseline`/`sleep-debt`)."""

    TODAY = "2026-09-23"

    def activity(self, day: str, sport: str, duration_s: float = 3600, location: str = None) -> None:
        loc = f', "location": "{location}"' if location else ""
        self.write(f"activities/{day}_{sport}.md",
                  arc(f'{{"arc": 1, "kind": "activity", "date": "{day}", "sport": "{sport}", '
                      f'"duration_s": {duration_s}{loc}}}'))

    def weather(self, day: str, temp_max_c: float, location: str = "Tournai") -> None:
        self.write(f"medical/{day}_meteo.md",
                  arc(f'{{"arc": 1, "kind": "weather", "date": "{day}", "location": "{location}", '
                      f'"category": "orange", "temp_max_c": {temp_max_c}}}'))

    def test_full_workspace_hand_computed(self):
        """2 séances outdoor chaudes (28°C, 30°C), 1 sous le seuil (20°C), sur des fichiers
        réels indexés — pas des dicts construits à la main."""
        self.activity("2026-09-20", "running", duration_s=3000)
        self.weather("2026-09-20", 28)
        self.activity("2026-09-21", "trail", duration_s=4000)
        self.weather("2026-09-21", 30)
        self.activity("2026-09-22", "running", duration_s=5000)
        self.weather("2026-09-22", 20)
        self.index()
        conf = {"heat_threshold_c": 25.0}
        result = I.heat_acclimation_today(self.conn, conf, date.fromisoformat(self.TODAY))
        self.assertEqual(result["hot_sessions"], 2)
        self.assertEqual(result["hot_duration_s"], 3000 + 4000)
        self.assertEqual(result["sessions_considered"], 3)
        self.assertEqual(result["sessions_without_weather"], 0)

    def test_indoor_sport_excluded(self):
        self.activity("2026-09-20", "strength", duration_s=2400)
        self.weather("2026-09-20", 32)
        self.index()
        conf = {"heat_threshold_c": 25.0}
        result = I.heat_acclimation_today(self.conn, conf, date.fromisoformat(self.TODAY))
        self.assertEqual(result["hot_sessions"], 0)
        self.assertEqual(result["sessions_considered"], 0)

    def test_missing_weather_counted_separately_not_cold(self):
        self.activity("2026-09-20", "running")
        # Pas de fichier météo ce jour-là.
        self.index()
        conf = {"heat_threshold_c": 25.0}
        result = I.heat_acclimation_today(self.conn, conf, date.fromisoformat(self.TODAY))
        self.assertEqual(result["sessions_considered"], 0)
        self.assertEqual(result["sessions_without_weather"], 1)

    def test_custom_threshold_from_workspace_config(self):
        """`[health].heat_threshold_c` en config : une séance à 27°C compte au seuil
        défaut (25°C) mais pas au seuil surchargé (30°C)."""
        self.activity("2026-09-20", "running")
        self.weather("2026-09-20", 27)
        self.index()
        (self.ws / "config").mkdir(parents=True, exist_ok=True)
        self.write("config/workspace.toml", "[health]\nheat_threshold_c = 30.0\n")
        conf = I.settings(I.load_config(self.ws))
        self.assertEqual(conf["heat_threshold_c"], 30.0)
        result = I.heat_acclimation_today(self.conn, conf, date.fromisoformat(self.TODAY))
        self.assertEqual(result["hot_sessions"], 0)

    def test_not_gated_by_morning_check_off(self):
        """Contrairement à `hrv-baseline`/`sleep-debt`, le calcul tourne même en
        `[health].morning_check = "off"` — la jointure activité/météo n'a rien à voir
        avec le bilan matinal."""
        self.activity("2026-09-20", "running")
        self.weather("2026-09-20", 30)
        self.index()
        conf = {"heat_threshold_c": 25.0, "morning_check": "off"}
        result = I.heat_acclimation_today(self.conn, conf, date.fromisoformat(self.TODAY))
        self.assertEqual(result["hot_sessions"], 1)


class TestChatEnabledSetting(unittest.TestCase):
    """`settings().chat_enabled` pilote l'entrée de nav « Coach » : faux par défaut."""

    def test_default_is_false(self):
        self.assertIs(I.settings({})["chat_enabled"], False)
        self.assertIs(I.settings({"chat": {}})["chat_enabled"], False)

    def test_enabled_key(self):
        self.assertIs(I.settings({"chat": {"enabled": True}})["chat_enabled"], True)
        self.assertIs(I.settings({"chat": {"enabled": False}})["chat_enabled"], False)


class TestHeatThresholdConfig(unittest.TestCase):
    """#38 — `[health].heat_threshold_c` : jamais d'exception (`settings()` est appelé
    par CHAQUE commande, y compris un simple `index`), booléen explicitement rejeté,
    chaîne numérique acceptée (repli TOML < 3.11 qui rend les flottants en chaîne)."""

    def conf(self, raw) -> dict:
        return I.settings({"health": {"heat_threshold_c": raw}})

    def test_missing_key_uses_default_silently(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = I.settings({})
        self.assertEqual(result["heat_threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertEqual(err.getvalue(), "", "l'absence d'override n'est pas une erreur : pas d'avertissement")

    def test_float_value_is_used_as_is(self):
        self.assertEqual(self.conf(30.0)["heat_threshold_c"], 30.0)

    def test_int_value_is_converted_to_float(self):
        self.assertEqual(self.conf(30)["heat_threshold_c"], 30.0)

    def test_numeric_string_is_parsed(self):
        """Repli TOML < 3.11 (`coach_config._read_toml_fallback`) : un flottant sans
        guillemets ressort comme une CHAÎNE (« 27.5 »), jamais rejetée pour autant."""
        self.assertEqual(self.conf("27.5")["heat_threshold_c"], 27.5)

    def test_numeric_string_with_french_comma_is_parsed(self):
        self.assertEqual(self.conf("27,5")["heat_threshold_c"], 27.5)

    def test_invalid_string_falls_back_to_default_with_a_warning_not_a_crash(self):
        """Le bug rapporté : un typo (« chaud ») ne doit JAMAIS faire planter `settings()`
        (donc `index_workspace`, donc CHAQUE commande de la CLI et le rafraîchissement
        du tableau de bord) — repli sur le défaut, avertissement sur stderr."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = self.conf("chaud")
        self.assertEqual(result["heat_threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertIn("heat_threshold_c", err.getvalue())

    def test_boolean_is_rejected_not_treated_as_one_degree(self):
        """`True` est aussi un `int` en Python : sans un test explicite, il vaudrait
        1.0 °C — un seuil de chaleur absurde, jamais celui voulu par un booléen mal
        placé dans le TOML."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = self.conf(True)
        self.assertEqual(result["heat_threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertIn("heat_threshold_c", err.getvalue())

    def test_empty_string_falls_back_silently(self):
        """Une clé présente mais vide (convention du projet, AGENTS.md : « une clé
        présente mais vide gagne ») n'est pas une erreur de saisie — pas d'avertissement."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = self.conf("")
        self.assertEqual(result["heat_threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertEqual(err.getvalue(), "")

    def test_none_falls_back_silently(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = self.conf(None)
        self.assertEqual(result["heat_threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)
        self.assertEqual(err.getvalue(), "")


class TestHeatThresholdConfigPrecedence(Workspace):
    """`workspace.user.toml` prime sur `workspace.toml`, clé par clé — même règle que
    tout le reste de la configuration (AGENTS.md)."""

    def test_user_override_wins_over_shared_default(self):
        (self.ws / "config").mkdir(parents=True, exist_ok=True)
        self.write("config/workspace.toml", "[health]\nheat_threshold_c = 25.0\n")
        self.write("config/workspace.user.toml", "[health]\nheat_threshold_c = 32.0\n")
        conf = I.settings(I.load_config(self.ws))
        self.assertEqual(conf["heat_threshold_c"], 32.0)

    def test_empty_user_override_falls_back_to_engine_default_not_shared_value(self):
        """Une clé présente mais VIDE dans `workspace.user.toml` gagne (annule
        l'héritage, AGENTS.md) — elle ne doit pas retomber sur la valeur de
        `workspace.toml`, mais sur le défaut moteur."""
        (self.ws / "config").mkdir(parents=True, exist_ok=True)
        self.write("config/workspace.toml", "[health]\nheat_threshold_c = 28.0\n")
        self.write("config/workspace.user.toml", '[health]\nheat_threshold_c = ""\n')
        conf = I.settings(I.load_config(self.ws))
        self.assertEqual(conf["heat_threshold_c"], M.HEAT_THRESHOLD_C_DEFAULT)


class TestProfileSleepNeed(unittest.TestCase):
    """#37 — `Besoin de sommeil` du profil, analysé comme les autres champs physio."""

    def test_parses_hour_and_minutes_notation(self):
        text = "# Profil\n\n## Physiologie\n\n- **Besoin de sommeil** : 7h30\n"
        self.assertEqual(L.parse_profile(text)["sleep_need_s"], 7 * 3600 + 30 * 60)

    def test_absent_when_not_filled(self):
        text = "# Profil\n\n## Physiologie\n\n- **FC max** : 188\n"
        self.assertNotIn("sleep_need_s", L.parse_profile(text))


class TestParseGear(unittest.TestCase):
    """#40 — `arc_legacy.parse_gear` : sous-section « Chaussures » du profil, en
    langage libre (pas des puces « Libellé : valeur »)."""

    def _gear(self, bullet: str):
        text = f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n- {bullet}\n"
        gear = L.parse_gear(text)
        self.assertEqual(len(gear), 1, gear)
        return gear[0]

    def test_name_only_derives_id(self):
        g = self._gear("Hoka Speedgoat 5")
        self.assertEqual(g, {"gear_id": "hoka-speedgoat-5", "name": "Hoka Speedgoat 5"})

    def test_full_line_all_segments(self):
        g = self._gear("Hoka Speedgoat 5 (bleues) — depuis 2026-03-01 — alerte 700 km "
                        "— id: speedgoat-bleues (par défaut)")
        self.assertEqual(g["gear_id"], "speedgoat-bleues")
        self.assertEqual(g["name"], "Hoka Speedgoat 5 (bleues)")
        self.assertEqual(g["start_date"], "2026-03-01")
        self.assertEqual(g["threshold_m"], 700000.0)
        self.assertIs(g["default"], True)
        self.assertNotIn("retired", g)

    def test_retired_flag(self):
        g = self._gear("Nike Pegasus (retirée)")
        self.assertIs(g["retired"], True)
        self.assertNotIn("default", g)
        self.assertEqual(g["name"], "Nike Pegasus")   # le marqueur est retiré du nom

    def test_retired_accent_variants(self):
        for text in ("(retirée)", "(retiree)", "(RETIRÉE)", "( retirée )"):
            with self.subTest(text=text):
                self.assertIs(self._gear(f"Nike Pegasus {text}")["retired"], True)

    def test_explicit_id_is_slugified(self):
        """Un id explicite mal formé (majuscules, espaces) reste passé par `gear_slug` :
        même garantie de format que le `gear_id` dérivé automatiquement."""
        g = self._gear("Salomon S/Lab Ultra — id: Mon Id Perso")
        self.assertEqual(g["gear_id"], "mon-id-perso")

    def test_accented_name_without_explicit_id(self):
        g = self._gear("Adidas Adizero Évo Été")
        self.assertEqual(g["gear_id"], "adidas-adizero-evo-ete")

    def test_hyphenated_model_name_not_split_on_plain_hyphen(self):
        """Un simple tiret dans le nom (pas un cadratin/demi-cadratin entouré
        d'espaces) ne doit jamais être pris pour un séparateur de segment."""
        g = self._gear("Salomon S/Lab Ultra-Trail")
        self.assertEqual(g["name"], "Salomon S/Lab Ultra-Trail")

    def test_no_chaussures_section_returns_empty(self):
        text = "# Profil\n\n## Matériel & lieux\n\n- **Lieu par défaut** : Tournai\n"
        self.assertEqual(L.parse_gear(text), [])

    def test_commented_out_example_is_ignored(self):
        """L'exemple commenté du modèle (`templates/Runner_Profile.template.md`) ne
        doit jamais être lu comme une chaussure réellement déclarée."""
        text = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                "<!--\n- Hoka Speedgoat 5 — depuis 2026-03-01 — alerte 700 km\n-->\n")
        self.assertEqual(L.parse_gear(text), [])

    def test_multiple_shoes(self):
        text = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                "- Hoka Speedgoat 5 (par défaut)\n- Adidas Adizero SL\n- Nike Pegasus (retirée)\n")
        gear = L.parse_gear(text)
        self.assertEqual([g["gear_id"] for g in gear],
                         ["hoka-speedgoat-5", "adidas-adizero-sl", "nike-pegasus"])

    # -- revue PR #85 -------------------------------------------------------

    def test_duplicate_slug_is_suffixed_not_overwritten(self):
        """blocker 2 : rachat du même modèle sans `id:` explicite pour les
        distinguer — la seconde puce ne doit jamais écraser la première."""
        text = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                "- Hoka Speedgoat 5 (par défaut)\n- Hoka Speedgoat 5\n- Hoka Speedgoat 5\n")
        gear = L.parse_gear(text)
        self.assertEqual([g["gear_id"] for g in gear],
                         ["hoka-speedgoat-5", "hoka-speedgoat-5-2", "hoka-speedgoat-5-3"])
        self.assertNotIn("collision_base", gear[0])
        self.assertEqual(gear[1]["collision_base"], "hoka-speedgoat-5")
        self.assertEqual(gear[2]["collision_base"], "hoka-speedgoat-5")
        self.assertIs(gear[0]["default"], True)   # la première garde ses attributs propres

    def test_duplicate_slug_via_explicit_id_also_suffixed(self):
        """La collision se détecte sur le slug FINAL (après résolution de l'id
        explicite), pas seulement sur des noms identiques."""
        text = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                "- Hoka Speedgoat 5 — id: sg\n- Adidas Adizero — id: sg\n")
        gear = L.parse_gear(text)
        self.assertEqual([g["gear_id"] for g in gear], ["sg", "sg-2"])
        self.assertEqual(gear[1]["collision_base"], "sg")

    def test_id_keyword_does_not_match_note_starting_with_id(self):
        """blocker 3 : « idéale » / « idem » ne sont pas le mot-clé `id`."""
        g = self._gear("Hoka Speedgoat 5 — idéale pour la route")
        self.assertEqual(g["gear_id"], "hoka-speedgoat-5")   # pas "eale-pour-la-route"

    def test_depuis_and_alerte_keywords_use_word_boundaries(self):
        g = self._gear("Hoka Speedgoat 5 — idem que la bleue")
        self.assertEqual(g["gear_id"], "hoka-speedgoat-5")
        self.assertNotIn("start_date", g)
        self.assertNotIn("threshold_m", g)

    def test_nested_sub_bullet_folds_into_parent_not_a_new_shoe(self):
        """blocker 4 : une puce indentée sous une chaussure est un complément de
        cette chaussure (ex. seuil noté à part), jamais sa propre chaussure."""
        text = ("# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                "- Hoka Speedgoat 5\n  - alerte 800 km\n- Adidas Adizero SL\n")
        gear = L.parse_gear(text)
        self.assertEqual([g["gear_id"] for g in gear], ["hoka-speedgoat-5", "adidas-adizero-sl"])
        self.assertEqual(gear[0]["threshold_m"], 800000)

    def test_plain_hyphen_separator_with_spaces(self):
        """blocker 5 : « - » entouré d'espaces sépare quand un mot-clé suit."""
        g = self._gear("Hoka Speedgoat 5 - depuis 2026-03-01 - alerte 700 km")
        self.assertEqual(g["name"], "Hoka Speedgoat 5")
        self.assertEqual(g["start_date"], "2026-03-01")
        self.assertEqual(g["threshold_m"], 700000)

    def test_plain_hyphen_not_followed_by_keyword_stays_in_name(self):
        """Revue #85, round 2 : un « - » entouré d'espaces mais SANS mot-clé
        reconnu derrière n'est pas un séparateur — un suffixe de variante
        (« - GTX ») ne doit jamais tronquer le nom réel du modèle (ce qui
        dériverait un `gear_id` faux, risquant même une fausse collision avec
        un modèle homonyme sans ce suffixe)."""
        g = self._gear("Brooks Cascadia 17 - GTX")
        self.assertEqual(g["name"], "Brooks Cascadia 17 - GTX")
        self.assertEqual(g["gear_id"], "brooks-cascadia-17-gtx")

    def test_plain_hyphen_number_suffix_stays_in_name_until_a_keyword(self):
        g = self._gear("Salomon S/Lab Ultra - 3 - alerte 600 km")
        self.assertEqual(g["name"], "Salomon S/Lab Ultra - 3")
        self.assertEqual(g["threshold_m"], 600000)

    def test_unspaced_em_dash_separator(self):
        """blocker 5 : un cadratin collé au texte (« 5—alerte ») sépare quand même."""
        g = self._gear("Hoka Speedgoat 5—alerte 700 km")
        self.assertEqual(g["name"], "Hoka Speedgoat 5")
        self.assertEqual(g["threshold_m"], 700000)

    def test_colon_separator_before_recognized_keyword(self):
        """blocker 5 : un deux-points sépare quand le segment suivant commence
        par un mot-clé reconnu — mais celui de « id: » n'est jamais un séparateur."""
        g = self._gear("Hoka Speedgoat 5: depuis 2026-03-01: alerte 700 km: id: speedgoat-bleues")
        self.assertEqual(g["name"], "Hoka Speedgoat 5")
        self.assertEqual(g["start_date"], "2026-03-01")
        self.assertEqual(g["threshold_m"], 700000)
        self.assertEqual(g["gear_id"], "speedgoat-bleues")

    def test_colon_not_split_on_unrelated_note(self):
        """Un deux-points suivi de texte quelconque (pas un mot-clé) reste dans
        le nom : seuls depuis/alerte/id: déclenchent un découpage sur « : »."""
        g = self._gear("Hoka Speedgoat 5: super confortable")
        self.assertEqual(g["name"], "Hoka Speedgoat 5: super confortable")

    def test_alerte_in_miles_is_converted_to_meters(self):
        """blocker 6 : unité miles reconnue et convertie (jamais stockée telle
        quelle comme si elle était en km)."""
        g = self._gear("Hoka Speedgoat 5 — alerte 500 miles")
        self.assertEqual(g["threshold_m"], round(500 * 1609.344))

    def test_alerte_in_mi_abbreviation_is_converted(self):
        g = self._gear("Hoka Speedgoat 5 — alerte 500 mi")
        self.assertEqual(g["threshold_m"], round(500 * 1609.344))

    def test_bold_markers_stripped_from_name(self):
        g = self._gear("**Hoka Speedgoat 5**")
        self.assertEqual(g["name"], "Hoka Speedgoat 5")

    def test_month_year_start_date_defaults_to_first_of_month(self):
        g = self._gear("Hoka Speedgoat 5 — depuis mars 2026")
        self.assertEqual(g["start_date"], "2026-03-01")

    def test_numeric_month_year_start_date(self):
        g = self._gear("Hoka Speedgoat 5 — depuis 03/2026")
        self.assertEqual(g["start_date"], "2026-03-01")


class TestParsePerformanceIndex(unittest.TestCase):
    """#62 — `arc_legacy.parse_performance_index` : section « Indices de
    performance », une puce datée par relevé. Rend `(entrées, avertissements)` —
    jamais d'impression directe (revue de code #62) : les avertissements sont
    portés par l'appelant, pour que le tableau de bord/la CLI puissent les
    afficher sans dépendre de la sortie standard."""

    def _history(self, *lines: str, sub_heading: bool = True):
        body = "\n".join(f"- {line}" for line in lines)
        heading = "### Historique des indices\n\n" if sub_heading else ""
        text = f"# Profil\n\n## Indices de performance (ITRA / UTMB)\n\n{heading}{body}\n"
        return L.parse_performance_index(text)

    def _entries(self, *lines: str, sub_heading: bool = True):
        entries, _ = self._history(*lines, sub_heading=sub_heading)
        return entries

    def test_present_general_itra_and_utmb(self):
        entries = self._entries("2025-11-01 — itra : 610", "2026-02-15 — utmb : 580")
        self.assertEqual([{k: v for k, v in e.items() if k != "ordinal"} for e in entries], [
            {"date": "2025-11-01", "kind": "itra", "value": 610.0},
            {"date": "2026-02-15", "kind": "utmb", "value": 580.0},
        ])

    def test_absent_when_no_section(self):
        text = "# Profil\n\n## Physiologie\n\n- **FC max** : 188\n"
        self.assertEqual(L.parse_performance_index(text), ([], []))
        self.assertNotIn("performance_index", L.parse_profile(text))

    def test_partial_only_one_kind_declared(self):
        entries = self._entries("2025-11-01 — itra : 610")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "itra")

    def test_category_is_kept_for_itra_free_form(self):
        entries = self._entries("2025-11-01 — itra L : 600")
        self.assertEqual(entries[0]["category"], "l")

    def test_utmb_category_must_be_known(self):
        """Catégorie UTMB hors nomenclature (`20k`/`50k`/`100k`/`100m`) : la ligne
        est ignorée avec un avertissement, jamais acceptée telle quelle — la
        nomenclature ITRA par catégorie, elle, reste libre (non vérifiée)."""
        entries, warnings = self._history("2025-11-01 — utmb 200k : 500")
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    def test_malformed_value_ignored_with_warning(self):
        entries, warnings = self._history("2025-11-01 — itra : beaucoup")
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    def test_missing_date_ignored_with_warning(self):
        entries, warnings = self._history("itra : 610")
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    def test_history_is_ordered_by_date_ascending_regardless_of_file_order(self):
        entries = self._entries("2026-02-15 — itra : 620", "2025-11-01 — itra : 610", "2026-01-01 — itra : 615")
        self.assertEqual([e["date"] for e in entries], ["2025-11-01", "2026-01-01", "2026-02-15"])

    def test_commented_out_example_is_ignored(self):
        text = ("# Profil\n\n## Indices de performance (ITRA / UTMB)\n\n### Historique des indices\n\n"
                "<!--\n- 2025-11-01 — itra : 610\n-->\n")
        self.assertEqual(L.parse_performance_index(text), ([], []))

    # -- revue de code #62 : migration (bullets directement sous le titre principal) --

    def test_bullets_directly_under_main_heading_without_sub_heading(self):
        """Un profil installé avant le sous-titre « Historique des indices », ou un
        athlète qui a simplement collé ses relevés sous le titre principal, doit
        être lu tout pareil (revue de code #62, blocker 1)."""
        entries = self._entries("2025-11-01 — itra : 610", sub_heading=False)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["value"], 610.0)

    def test_bullets_both_direct_and_under_sub_heading_are_both_read(self):
        text = ("# Profil\n\n## Indices de performance (ITRA / UTMB)\n\n"
                "- 2025-10-01 — itra : 600\n\n"
                "### Historique des indices\n\n"
                "- 2025-11-01 — itra : 610\n")
        entries, _ = L.parse_performance_index(text)
        self.assertEqual([e["date"] for e in entries], ["2025-10-01", "2025-11-01"])

    def test_next_top_level_section_still_ends_the_section(self):
        text = ("# Profil\n\n## Indices de performance (ITRA / UTMB)\n\n"
                "- 2025-11-01 — itra : 610\n\n"
                "## Matériel & lieux\n\n"
                "- 2099-01-01 — itra : 999\n")
        entries, _ = L.parse_performance_index(text)
        self.assertEqual(len(entries), 1)

    def test_unrelated_heading_mentioning_performance_is_not_matched(self):
        """Revue de code #109, 2e tour, nit : « #### Indice de performance VO2 »
        (VO2max, vue Performance du tableau de bord) ne doit jamais être pris
        pour le titre de la section ITRA/UTMB — seul un titre qui mentionne
        explicitement ITRA ou UTMB l'est, ou un titre NU qui s'arrête juste
        après « performance » (voir les tests de repli ci-dessous)."""
        text = ("# Profil\n\n#### Indice de performance VO2\n\n"
                "- 2025-11-01 — itra : 610\n")
        self.assertEqual(L.parse_performance_index(text), ([], []))

    # -- revue de code #109, 3e tour : titre NU (sans ITRA/UTMB), repli --------

    def test_bare_heading_without_itra_or_utmb_is_read_with_a_warning(self):
        text = "# Profil\n\n## Indices de performance\n\n- 2025-11-01 — itra : 610\n"
        entries, warnings = L.parse_performance_index(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["value"], 610.0)
        self.assertTrue(any("sans mention ITRA/UTMB" in w for w in warnings))

    def test_bare_heading_with_trailing_parenthetical_is_read_with_a_warning(self):
        text = "# Profil\n\n## Indices de performance (facultatif)\n\n- 2025-11-01 — itra : 610\n"
        entries, warnings = L.parse_performance_index(text)
        self.assertEqual(len(entries), 1)
        self.assertTrue(any("sans mention ITRA/UTMB" in w for w in warnings))

    def test_heading_with_itra_or_utmb_never_gets_the_bare_heading_warning(self):
        text = "# Profil\n\n## Indices de performance (ITRA / UTMB)\n\n- 2025-11-01 — itra : 610\n"
        _, warnings = L.parse_performance_index(text)
        self.assertFalse(any("sans mention ITRA/UTMB" in w for w in warnings))

    def test_bare_heading_with_unrelated_trailing_text_is_still_rejected(self):
        """Le repli reste STRICT (revue de code #109, 3e tour) : un texte libre
        après « performance » et SANS parenthèses (comme « VO2 » ci-dessus)
        n'est jamais un titre nu accepté — seule une ligne qui s'arrête net,
        éventuellement suivie d'une seule parenthèse, l'est."""
        text = "# Profil\n\n#### Indice de performance VO2\n\n- 2025-11-01 — itra : 610\n"
        self.assertEqual(L.parse_performance_index(text), ([], []))

    # -- revue de code #62 : normalisation « général »/synonymes -------------

    def test_general_synonyms_normalize_to_no_category(self):
        for line in ("2025-11-01 — itra Général : 612", "2025-11-02 — utmb général : 555",
                     "2025-11-03 — utmb Index : 540", "2025-11-04 — itra GLOBAL : 611"):
            with self.subTest(line=line):
                entries = self._entries(line)
                self.assertNotIn("category", entries[0])

    def test_multi_word_category_is_preserved(self):
        entries = self._entries("2025-11-01 — itra senior hommes : 600")
        self.assertEqual(entries[0]["category"], "senior hommes")

    def test_utmb_category_with_spaced_unit_is_collapsed(self):
        entries = self._entries("2025-11-01 — utmb 100 k : 560")
        self.assertEqual(entries[0]["category"], "100k")

    def test_utmb_category_case_insensitive_unit(self):
        entries = self._entries("2025-11-01 — utmb 100 K : 560")
        self.assertEqual(entries[0]["category"], "100k")

    # -- revue de code #62 : séparateur de date élargi -----------------------

    def test_double_hyphen_separator(self):
        entries = self._entries("2025-11-01 -- itra : 610")
        self.assertEqual(entries[0]["value"], 610.0)

    def test_unspaced_em_dash_separator_still_works(self):
        entries = self._entries("2025-11-01—itra : 610")
        self.assertEqual(entries[0]["value"], 610.0)

    # -- revue de code #62 : bornes de valeur ---------------------------------

    def test_value_above_max_is_dropped_with_warning(self):
        entries, warnings = self._history("2025-11-01 — itra : 1500")
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    def test_value_zero_is_dropped_with_warning(self):
        entries, warnings = self._history("2025-11-01 — itra : 0")
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    def test_value_at_max_bound_is_accepted(self):
        entries = self._entries("2025-11-01 — itra : 1000")
        self.assertEqual(entries[0]["value"], 1000.0)

    # -- revue de code #109 (2e tour) : date future jamais vérifiée ICI --------
    #
    # `parse_performance_index` ne connaît pas « aujourd'hui » et ne le vérifie
    # plus (déplacé vers `arc_index.performance_index`, voir
    # `TestPerformanceIndexQuery` plus bas) : « futur » ne se juge qu'à la
    # LECTURE, jamais à l'écriture — un avertissement calculé ici resterait figé
    # en base tant que le fichier ne change pas, même après que la date soit
    # passée.

    def test_future_date_entry_is_kept_without_warning_at_parse_time(self):
        entries, warnings = self._history("2099-01-01 — itra : 610")
        self.assertEqual(len(entries), 1)
        self.assertEqual(warnings, [])

    # -- revue de code #62 : doublons exacts -----------------------------------

    def test_exact_duplicate_keeps_last_line_with_warning(self):
        entries, warnings = self._history("2025-11-01 — itra : 600", "2025-11-01 — itra : 620")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["value"], 620.0)
        self.assertTrue(any("doublon" in w for w in warnings))

    def test_different_category_same_date_is_not_a_duplicate(self):
        entries, warnings = self._history("2025-11-01 — itra : 610", "2025-11-01 — itra L : 600")
        self.assertEqual(len(entries), 2)
        self.assertFalse(any("doublon" in w for w in warnings))

    def test_ordinal_breaks_ties_in_document_order(self):
        entries, _ = self._history("2025-11-01 — itra : 610", "2025-11-01 — utmb : 580")
        self.assertEqual([e["kind"] for e in entries], ["itra", "utmb"])


class TestPerformanceIndexQuery(Workspace):
    """#62 — `arc_index.performance_index` : historique complet + valeur courante
    (la plus récente) par (kind, category), lue depuis le workspace indexé —
    avec les avertissements de lecture persistés (revue de code #62)."""

    def test_current_is_latest_per_kind_and_category(self):
        self.write("planning/Runner_Profile.md", """# Profil

## Indices de performance (ITRA / UTMB)

### Historique des indices

- 2025-11-01 — itra : 600
- 2026-02-15 — itra : 620
- 2026-01-15 — utmb 100k : 560
""")
        self.index()
        result = I.performance_index(self.conn, date(2026, 9, 27))
        self.assertEqual(len(result["history"]), 3)
        self.assertEqual([h["date"] for h in result["history"]], ["2025-11-01", "2026-01-15", "2026-02-15"])
        current_by_key = {(c["kind"], c.get("category")): c["value"] for c in result["current"]}
        self.assertEqual(current_by_key[("itra", None)], 620.0)
        self.assertEqual(current_by_key[("utmb", "100k")], 560.0)
        self.assertEqual(result["warnings"], [])

    def test_empty_when_no_history_declared(self):
        self.write("planning/Runner_Profile.md", "# Profil\n\n- **FC max** : 188\n")
        self.index()
        self.assertEqual(I.performance_index(self.conn, date(2026, 9, 27)),
                         {"history": [], "current": [], "warnings": []})

    def test_future_date_warning_is_computed_fresh_at_read_time(self):
        """Revue de code #109, 2e tour : la date future n'est JAMAIS stockée —
        recalculée à chaque appel contre `today`. Un relevé qui était « futur »
        hier ne doit plus l'être une fois que `today` l'a dépassé, SANS que le
        fichier n'ait changé ni ne soit réindexé."""
        self.write("planning/Runner_Profile.md", """# Profil

## Indices de performance (ITRA / UTMB)

- 2026-09-30 — itra : 630
""")
        self.index()
        still_future = I.performance_index(self.conn, date(2026, 9, 27))
        self.assertTrue(any("futur" in w for w in still_future["warnings"]))
        no_longer_future = I.performance_index(self.conn, date(2026, 10, 5))
        self.assertEqual(no_longer_future["warnings"], [])
        # Le relevé lui-même reste inchangé dans les deux cas (jamais retiré).
        self.assertEqual(len(no_longer_future["history"]), 1)

    def test_warnings_are_persisted_and_survive_a_second_index_pass(self):
        """Revue de code #62, blocker 2 : les avertissements restent lisibles via
        `performance_index()` sans jamais réapparaître sur la sortie standard —
        et une seconde indexation du même fichier (inchangé) ne les recalcule ni
        ne les duplique."""
        self.write("planning/Runner_Profile.md", """# Profil

## Indices de performance (ITRA / UTMB)

- 2025-11-01 — itra : 1500
""")
        self.index()
        first = I.performance_index(self.conn)
        self.assertEqual(len(first["warnings"]), 1)
        self.index()  # fichier inchangé : pas de double avertissement
        second = I.performance_index(self.conn)
        self.assertEqual(second["warnings"], first["warnings"])

    def test_migration_bullets_directly_under_main_heading_are_indexed(self):
        self.write("planning/Runner_Profile.md", """# Profil

## Indices de performance (ITRA / UTMB)

- 2025-11-01 — itra : 610
""")
        self.index()
        result = I.performance_index(self.conn)
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["value"], 610.0)


class TestParseSleepNeed(unittest.TestCase):
    """#37, revue de code PR #82 — `_parse_sleep_need_s` est un parseur DÉDIÉ, distinct
    de `parse_fr_duration` : ce dernier lit silencieusement « 7.5 h » comme 5 h (le « h »
    de « 7h30 » matche avant que « .5 » ne soit consommé) et « 7:30 » comme m:ss
    (450 s), deux contresens qui rendraient la dette de sommeil silencieusement fausse
    (souvent 0, ou une dette énorme) plutôt que d'échouer bruyamment."""

    def test_decimal_hours_with_dot(self):
        self.assertEqual(L._parse_sleep_need_s("7.5 h"), 7.5 * 3600)

    def test_decimal_hours_with_comma(self):
        """Décimale française (virgule) : ne doit PAS être lue comme « 7 h » plus un
        reliquat « ,5 h » ignoré — 7,5 h vaut 7 h 30, pas 7 h."""
        self.assertEqual(L._parse_sleep_need_s("7,5 h"), 7.5 * 3600)

    def test_colon_notation_is_hours_minutes_not_minutes_seconds(self):
        """« 7:30 » est un besoin de sommeil en HEURES:MINUTES (7 h 30 = 27 000 s),
        jamais m:ss (ce que `parse_fr_duration` rendrait : 450 s, une dette qui ne
        pourrait alors jamais retomber à 0)."""
        self.assertEqual(L._parse_sleep_need_s("7:30"), 7 * 3600 + 30 * 60)

    def test_minutes_notation(self):
        self.assertEqual(L._parse_sleep_need_s("450 min"), 450 * 60)

    def test_bare_number_is_hours(self):
        self.assertEqual(L._parse_sleep_need_s("8"), 8 * 3600)

    def test_hour_minute_notation_still_works(self):
        self.assertEqual(L._parse_sleep_need_s("7h30"), 7 * 3600 + 30 * 60)
        self.assertEqual(L._parse_sleep_need_s("7 h 30"), 7 * 3600 + 30 * 60)

    def test_implausible_value_is_rejected(self):
        """« 25 h » : hors de `SLEEP_NEED_PLAUSIBLE_H` (4-12 h) — une faute de saisie,
        jamais un besoin de sommeil réel. `None`, pour que l'appelant retombe sur son
        propre défaut (7 h 30) plutôt que de programmer sur une valeur absurde."""
        self.assertIsNone(L._parse_sleep_need_s("25 h"))

    def test_unparseable_text_is_none(self):
        self.assertIsNone(L._parse_sleep_need_s("beaucoup"))


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


class TestGearSweatFuelIndex(Workspace):
    """#39 : colonnes `activity` (gear_id, carbs_g, fluid_intake_ml, weight_pre_kg,
    weight_post_kg) et dérivation de `sweat_rate_l_h` à l'indexation."""

    def test_columns_are_stored(self):
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 9000, '
            '"moving_duration_s": 8820, "gear_id": "hoka-speedgoat-5-bleue", "carbs_g": 72, '
            '"fluid_intake_ml": 900, "weight_pre_kg": 70.2, "weight_post_kg": 69.1}'))
        self.index()
        row = self.conn.execute(
            "SELECT gear_id, carbs_g, fluid_intake_ml, weight_pre_kg, weight_post_kg, sweat_rate_l_h "
            "FROM activity").fetchone()
        gear_id, carbs_g, fluid_ml, pre, post, sweat_rate = tuple(row)
        self.assertEqual((gear_id, carbs_g, fluid_ml, pre, post), ("hoka-speedgoat-5-bleue", 72, 900, 70.2, 69.1))
        # (70.2 - 69.1) + 900/1000 = 2.0 l sur 9000 s (duration_s TOTALE : la pesée
        # encadre la sortie entière, `moving_duration_s` n'entre pas dans le calcul).
        self.assertAlmostEqual(sweat_rate, 2.0 / (9000 / 3600), places=2)

    def test_sweat_rate_ignores_moving_duration(self):
        """La pesée encadre toute la sortie (arrêts compris) : `moving_duration_s`,
        bien plus court ici, ne doit pas réduire artificiellement la durée retenue."""
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, '
            '"moving_duration_s": 1800, "weight_pre_kg": 71.0, "weight_post_kg": 70.0}'))
        self.index()
        rate = self.conn.execute("SELECT sweat_rate_l_h FROM activity").fetchone()[0]
        self.assertAlmostEqual(rate, 1.0, places=2)   # 1 kg / 1 h (duration_s), pas / 0,5 h (moving_duration_s)

    def test_sweat_rate_missing_fluid_defaults_to_zero(self):
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, '
            '"weight_pre_kg": 71.5, "weight_post_kg": 71.0}'))
        self.index()
        rate = self.conn.execute("SELECT sweat_rate_l_h FROM activity").fetchone()[0]
        self.assertAlmostEqual(rate, 0.5, places=2)

    def test_sweat_rate_none_without_both_weights(self):
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, '
            '"weight_pre_kg": 71.0}'))
        self.index()
        rate = self.conn.execute("SELECT sweat_rate_l_h FROM activity").fetchone()[0]
        self.assertIsNone(rate)

    def test_sweat_rate_negative_result_is_none(self):
        """Poids après > avant et aucun liquide déclaré : le résultat serait négatif,
        donc `None`, jamais affiché tel quel — même sans franchir l'avertissement du
        contrat (`arc_contract.WEIGHT_POST_TOLERANCE_KG`, ici 0,5 kg < 1 kg)."""
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, '
            '"weight_pre_kg": 70.0, "weight_post_kg": 70.5}'))
        self.index()
        rate = self.conn.execute("SELECT sweat_rate_l_h FROM activity").fetchone()[0]
        self.assertIsNone(rate)

    def test_sweat_rate_too_short_session_is_none(self):
        """Sous `SWEAT_RATE_MIN_DURATION_S` (45 min), l'imprécision de la pesée
        domine le signal : `None` plutôt qu'un chiffre bruité."""
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 1800, '
            '"weight_pre_kg": 71.0, "weight_post_kg": 70.0}'))
        self.index()
        rate = self.conn.execute("SELECT sweat_rate_l_h FROM activity").fetchone()[0]
        self.assertIsNone(rate)

    def test_sweat_rate_above_plausible_max_is_none(self):
        """Gros transpirateur en ambiance chaude : 3,5 kg perdus en 1 h reste sous la
        borne haute (4 l/h) ; au-delà, `None` (faute de saisie plus probable qu'une
        vraie mesure)."""
        self.write("activities/2026-09-20_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 3600, '
            '"weight_pre_kg": 75.0, "weight_post_kg": 70.5}'))
        self.index()
        rate = self.conn.execute("SELECT sweat_rate_l_h FROM activity").fetchone()[0]
        self.assertIsNone(rate)   # 4.5 l/h > SWEAT_RATE_PLAUSIBLE_L_H[1] (4.0)

    def test_schema_version_bumped_forces_rebuild(self):
        self.assertEqual(I.SCHEMA_VERSION, 35)   # #193 : week.week_type (34 = #164 strava_activity_id, 33 = #166 cycle, 32 = #151, 31 = #68)

    def test_schema_version_28_adds_equipment_table_and_gear_ids_column(self):
        """#134 : table `equipment` + colonne `activity.gear_ids` — une base d'avant est reconstruite."""
        self.index()
        eq_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(equipment)")}
        self.assertTrue({"gear_id", "category", "threshold_s", "threshold_days", "maintenance_date"} <= eq_cols)
        act_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(activity)")}
        self.assertIn("gear_ids", act_cols)

    def test_schema_version_26_adds_gear_start_and_usage_columns(self):
        """#132 : `gear` gagne `start_m` et `usage` — une base d'avant ce schéma est reconstruite."""
        self.index()
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(gear)")}
        self.assertTrue({"start_m", "usage"} <= cols, cols)

    def test_schema_version_30_adds_covered_s_to_samples(self):
        """Temps en zone surestimé : `activity_sample` gagne `covered_s` — une base de
        version 29 (#135, sans la colonne) doit être reconstruite avec, sinon l'ingestion
        échouerait avec « no such column »."""
        db_path = self.tmp / "legacy29.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '29');"
            "CREATE TABLE activity_sample (garmin_activity_id INTEGER, source_path TEXT, t_s REAL);"
        )
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(activity_sample)").fetchall()}
        self.assertIn("covered_s", columns)
        conn.close()

    def test_schema_version_31_adds_intervals_id_to_sample_tables(self):
        """FIT Intervals.icu (#68) : `activity_sample` et `sample_file` gagnent
        `intervals_activity_id` — une base de version 30 (#139, `covered_s` mais sans cette
        colonne) doit être reconstruite avec, sinon l'ingestion d'un
        `activities/fit/i<chiffres>.json` échouerait avec « no such column »."""
        db_path = self.tmp / "legacy30.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '30');"
            "CREATE TABLE activity_sample (garmin_activity_id INTEGER, source_path TEXT, t_s REAL, covered_s REAL);"
        )
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        for table in ("activity_sample", "sample_file"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            self.assertIn("intervals_activity_id", columns, table)
        conn.close()

    def test_schema_version_25_adds_energy_table_and_bmr_column(self):
        """Dépense énergétique modèle : `activity` gagne `calories_bmr_kcal` (REAL)
        et une nouvelle table `activity_energy` — une base construite par une
        version d'AVANT ce schéma doit être reconstruite avec les deux, sinon
        `store()`/`compute_metrics` échoueraient avec « no such column »/
        « no such table »."""
        db_path = self.tmp / "legacy.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '24');"
            "CREATE TABLE activity (id INTEGER PRIMARY KEY, source_path TEXT, date TEXT, "
            "garmin_activity_id INTEGER);"
        )
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0],
            str(I.SCHEMA_VERSION))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(activity)").fetchall()}
        self.assertIn("calories_bmr_kcal", columns)
        energy_columns = {row[1] for row in conn.execute("PRAGMA table_info(activity_energy)").fetchall()}
        self.assertIn("model_kcal", energy_columns)
        self.assertIn("weight_source", energy_columns)
        conn.close()

    def test_schema_version_24_adds_intervals_activity_id_column(self):
        """#68 : `activity` gagne `intervals_activity_id` (TEXT) — une base
        construite par une version d'AVANT #68 doit être reconstruite avec la
        nouvelle colonne, sinon `store()` échouerait sur la première activité
        synchronisée depuis Intervals.icu avec « no such column »."""
        db_path = self.tmp / "legacy.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '23');"
            "CREATE TABLE activity (id INTEGER PRIMARY KEY, source_path TEXT, date TEXT, "
            "garmin_activity_id INTEGER);"
        )
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0],
            str(I.SCHEMA_VERSION))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(activity)").fetchall()}
        self.assertIn("intervals_activity_id", columns)
        conn.close()

    def test_real_v4_database_is_rebuilt_at_current_version(self):
        """Pas seulement « la constante vaut N » : une vraie base laissée par une
        version antérieure (#37, schema_version = 4, sans les colonnes #39 ni la
        table `gear` #40) doit être détectée et reconstruite, colonnes et table
        comprises — sinon `store()` échouerait sur la première activité avec
        `gear_id` ou sur le premier profil avec des chaussures déclarées."""
        db_path = self.tmp / "legacy.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '4');"
            "CREATE TABLE activity (id INTEGER PRIMARY KEY, source_path TEXT, date TEXT);"
        )
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0],
            str(I.SCHEMA_VERSION))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(activity)").fetchall()}
        self.assertIn("gear_id", columns)
        self.assertIn("sweat_rate_l_h", columns)
        gear_columns = {row[1] for row in conn.execute("PRAGMA table_info(gear)").fetchall()}
        self.assertIn("collision_base", gear_columns)
        sample_columns = {row[1] for row in conn.execute("PRAGMA table_info(activity_sample)").fetchall()}
        self.assertIn("source_path", sample_columns)   # #42
        self.assertIn("garmin_activity_id", sample_columns)   # #42 (revue PR #87), pas activity_id/rowid
        sample_file_columns = {row[1] for row in conn.execute("PRAGMA table_info(sample_file)").fetchall()}
        self.assertIn("garmin_activity_id", sample_file_columns)
        conn.close()

    def test_v21_database_with_unchanged_profile_gets_performance_index_after_bump(self):
        """#62, revue de code #109 (2e tour), blocker : une base `.arc/coach.db`
        construite par une version d'AVANT #62 (`schema_version = 21`, sans les
        tables `performance_index`/`performance_index_warning`) doit être
        reconstruite à la version courante — colonnes ET tables comprises — sans
        qu'un `Runner_Profile.md` déjà connu de cette base (même sha256, ce qui le
        ferait sinon sauter comme « inchangé » à la réindexation) n'échappe à la
        relecture. Sans le bump de `SCHEMA_VERSION`, `performance_index()` (donc
        `/api/summary`) échouerait avec « no such table » pour tout utilisateur
        dont la base existait déjà avant #62 — panne du tableau de bord entier."""
        self.write("planning/Runner_Profile.md", """# Profil

## Indices de performance (ITRA / UTMB)

### Historique des indices

- 2025-11-01 — itra : 610
""")
        db_path = self.tmp / "legacy.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '21');"
            "CREATE TABLE source_file (path TEXT PRIMARY KEY, kind TEXT, sha256 TEXT, mtime REAL, "
            "arc_version INTEGER, parsed_ok TEXT, issues TEXT);"
        )
        # Le profil est déjà connu de la base, MÊME sha256 que sur disque : une base
        # dont le SCHEMA_VERSION n'aurait pas changé le sauterait comme « inchangé »
        # (`known and known[0] == digest` dans `index_workspace`), sans jamais
        # peupler `performance_index` — c'est précisément ce que le bump évite en
        # forçant la reconstruction complète (donc un `source_file` reparti à zéro).
        digest = hashlib.sha256((self.ws / "planning/Runner_Profile.md").read_bytes()).hexdigest()
        legacy.execute(
            "INSERT INTO source_file VALUES (?, 'athlete', ?, 0, 0, 'ok', '[]')",
            ("planning/Runner_Profile.md", digest))
        legacy.commit()
        legacy.close()

        conn = I.open_db(self.ws, str(db_path))
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0],
            str(I.SCHEMA_VERSION))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("performance_index", tables)
        self.assertIn("performance_index_warning", tables)

        I.index_workspace(conn, self.ws, "2026-09-27")
        # Ce qu'`/api/summary`/`arc_index.py performance-index` appellent : ne doit
        # jamais lever `sqlite3.OperationalError: no such table`.
        result = I.performance_index(conn)
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["value"], 610.0)
        conn.close()


class TestMultiWeekIndex(Workspace):
    """#69 : plan multi-semaines (`week.weeks[]`) — éclatement en plusieurs lignes
    `week`/`planned_session`, purge par fichier, collision avec un fichier dédié."""

    def week_block(self, week_start, sessions=None, **extra):
        return {"week_start": week_start, "location": "Tournai",
                "sessions": sessions if sessions is not None else [], **extra}

    def write_multi(self, rel, weeks):
        self.write(rel, arc(json.dumps({"arc": 1, "kind": "week", "weeks": weeks})))

    def write_single(self, rel, week_start, sessions=None, **extra):
        block = {"arc": 1, "kind": "week", **self.week_block(week_start, sessions, **extra)}
        self.write(rel, arc(json.dumps(block)))

    def test_schema_version_23_adds_shadowed_column(self):
        db_path = self.tmp / "legacy.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '22');"
            "CREATE TABLE week (source_path TEXT, week_start TEXT);"
            "CREATE TABLE planned_session (source_path TEXT, week_start TEXT, date TEXT);"
        )
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0],
            str(I.SCHEMA_VERSION))
        week_columns = {row[1] for row in conn.execute("PRAGMA table_info(week)").fetchall()}
        self.assertIn("shadowed", week_columns)
        session_columns = {row[1] for row in conn.execute("PRAGMA table_info(planned_session)").fetchall()}
        self.assertIn("shadowed", session_columns)
        conn.close()

    def test_multi_week_file_explodes_into_one_row_per_week(self):
        self.write_multi("planning/Semaine_2026-09-21.md", [
            self.week_block("2026-09-21", [{"date": "2026-09-22", "sport": "running", "title": "Footing"}]),
            self.week_block("2026-09-28", [{"date": "2026-09-30", "sport": "trail", "title": "Sortie longue"}]),
        ])
        self.index()
        rows = self.conn.execute(
            "SELECT week_start, source_path FROM week ORDER BY week_start").fetchall()
        self.assertEqual([r["week_start"] for r in rows], ["2026-09-21", "2026-09-28"])
        self.assertTrue(all(r["source_path"] == "planning/Semaine_2026-09-21.md" for r in rows))
        sessions = self.conn.execute(
            "SELECT date, week_start FROM planned_session ORDER BY date").fetchall()
        self.assertEqual([(s["date"], s["week_start"]) for s in sessions],
                          [("2026-09-22", "2026-09-21"), ("2026-09-30", "2026-09-28")])

    def test_single_week_file_still_indexes_one_row(self):
        """Le format historique (pas de `weeks`) doit continuer à produire
        exactement une ligne — pas de régression du chemin existant (#69)."""
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21",
                           [{"date": "2026-09-22", "sport": "running", "title": "Footing"}])
        self.index()
        rows = self.conn.execute("SELECT week_start FROM week").fetchall()
        self.assertEqual([r["week_start"] for r in rows], ["2026-09-21"])

    def test_per_file_purge_removes_all_weeks_of_a_multi_week_file(self):
        self.write_multi("planning/Semaine_2026-09-21.md", [
            self.week_block("2026-09-21"), self.week_block("2026-09-28"),
        ])
        self.index()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM week").fetchone()[0], 2)
        # Le fichier change (une seule semaine désormais) : la purge par
        # `source_path` doit avoir retiré LES DEUX anciennes lignes, pas seulement
        # celle qui correspond encore au fichier.
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21")
        self.index()
        rows = self.conn.execute("SELECT week_start FROM week").fetchall()
        self.assertEqual([r["week_start"] for r in rows], ["2026-09-21"])

    def test_file_removal_purges_all_its_weeks(self):
        self.write_multi("planning/Semaine_2026-09-21.md", [
            self.week_block("2026-09-21"), self.week_block("2026-09-28"),
        ])
        self.index()
        (self.ws / "planning/Semaine_2026-09-21.md").unlink()
        self.index()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM week").fetchone()[0], 0)

    def test_dedicated_file_wins_collision_over_multi_week_entry(self):
        """Un plan multi-semaines (#69) couvrant incidemment une semaine déjà
        décrite par son propre fichier dédié : le fichier dédié fait foi — sa
        semaine reste visible (`shadowed = 0`), l'entrée concurrente est éclipsée."""
        self.write_multi("planning/Semaine_2026-09-14.md", [
            self.week_block("2026-09-14"),
            self.week_block("2026-09-21", [{"date": "2026-09-22", "sport": "running", "title": "Multi"}]),
        ])
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21",
                           [{"date": "2026-09-22", "sport": "running", "title": "Dédié"}])
        self.index()
        rows = {r["source_path"]: r["shadowed"] for r in self.conn.execute(
            "SELECT source_path, shadowed FROM week WHERE week_start = '2026-09-21'").fetchall()}
        self.assertEqual(rows, {
            "planning/Semaine_2026-09-14.md": 1,
            "planning/Semaine_2026-09-21.md": 0,
        })
        # La semaine du 14 (pas de collision) reste, elle, visible.
        self.assertEqual(self.conn.execute(
            "SELECT shadowed FROM week WHERE week_start = '2026-09-14'").fetchone()[0], 0)
        # La séance éclipsée ne doit pas non plus apparaître dans `planned_session`.
        titled = {r["title"] for r in self.conn.execute(
            "SELECT title, shadowed FROM planned_session WHERE date = '2026-09-22' AND shadowed = 0"
        ).fetchall()}
        self.assertEqual(titled, {"Dédié"})
        # Avertissement visible côté fichier perdant (#69, backfill/`issues`).
        issues = json.loads(self.conn.execute(
            "SELECT issues FROM source_file WHERE path = 'planning/Semaine_2026-09-14.md'").fetchone()[0])
        self.assertTrue(any("en collision avec" in i and "2026-09-21" in i for i in issues), issues)

    def test_collision_without_dedicated_file_picks_alphabetically_first(self):
        self.write_multi("planning/Semaine_2026-09-07.md", [self.week_block("2026-09-21")])
        self.write_multi("planning/Semaine_2026-09-14.md", [self.week_block("2026-09-21")])
        self.index()
        rows = {r["source_path"]: r["shadowed"] for r in self.conn.execute(
            "SELECT source_path, shadowed FROM week WHERE week_start = '2026-09-21'").fetchall()}
        self.assertEqual(rows, {
            "planning/Semaine_2026-09-07.md": 0,   # premier par ordre alphabétique
            "planning/Semaine_2026-09-14.md": 1,
        })

    def test_collision_warning_disappears_once_resolved(self):
        """Un avertissement de collision (#69) ne doit jamais rester périmé une
        fois la collision résolue (ici : le fichier dédié est supprimé)."""
        self.write_multi("planning/Semaine_2026-09-14.md", [
            self.week_block("2026-09-14"), self.week_block("2026-09-21"),
        ])
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21")
        self.index()
        issues = json.loads(self.conn.execute(
            "SELECT issues FROM source_file WHERE path = 'planning/Semaine_2026-09-14.md'").fetchone()[0])
        self.assertTrue(any("en collision avec" in i for i in issues), issues)

        (self.ws / "planning/Semaine_2026-09-21.md").unlink()
        self.index()
        issues = json.loads(self.conn.execute(
            "SELECT issues FROM source_file WHERE path = 'planning/Semaine_2026-09-14.md'").fetchone()[0])
        self.assertFalse(any("en collision avec" in i for i in issues), issues)
        self.assertEqual(self.conn.execute(
            "SELECT shadowed FROM week WHERE week_start = '2026-09-21'").fetchone()[0], 0)

    def test_collision_surfaces_in_backfill_items_despite_valid_contract(self):
        """#69 : le fichier perdant reste `parsed_ok = "ok"` (son bloc ```arc est
        valide) mais sa collision doit quand même apparaître dans
        `backfill_items` — sinon l'écart resterait invisible du tableau de bord
        (`/api/files`)."""
        self.write_multi("planning/Semaine_2026-09-14.md", [
            self.week_block("2026-09-14"), self.week_block("2026-09-21"),
        ])
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21")
        self.index()
        items = {item["path"]: item for item in I.backfill_items(self.conn)}
        self.assertIn("planning/Semaine_2026-09-14.md", items)
        self.assertEqual(items["planning/Semaine_2026-09-14.md"]["status"], "ok")
        self.assertTrue(items["planning/Semaine_2026-09-14.md"]["collision"])
        self.assertTrue(any("en collision avec" in i for i in items["planning/Semaine_2026-09-14.md"]["issues"]))
        self.assertNotIn("planning/Semaine_2026-09-21.md", items)

    def test_write_backfill_lists_collisions_separately_from_contract_debt(self):
        """#69, revue de code should-fix 2 : un item de collision (fichier VALIDE
        au contrat) ne doit jamais apparaître dans la section « à réécrire », qui
        enverrait `arc-backfill` (ou l'athlète) réécrire un bloc déjà correct.
        Un vrai fichier hors contrat (santé sans bloc) reste dans sa propre
        section, inchangée."""
        self.write_multi("planning/Semaine_2026-09-14.md", [
            self.week_block("2026-09-14"), self.week_block("2026-09-21"),
        ])
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21")
        self.write("medical/2026-09-20_health.md", "# Santé\n\nPas de bloc.\n")
        self.index()
        out = I.write_backfill(self.conn, self.ws)
        text = out.read_text(encoding="utf-8")
        self.assertIn("## Fichiers hors contrat", text)
        self.assertIn("## Collisions de semaine", text)
        contract_section, collision_section = text.split("## Collisions de semaine")
        self.assertIn("medical/2026-09-20_health.md", contract_section)
        self.assertNotIn("planning/Semaine_2026-09-14.md", contract_section)
        self.assertIn("planning/Semaine_2026-09-14.md", collision_section)
        self.assertNotIn("medical/2026-09-20_health.md", collision_section)

    def test_week_collisions_helper_reports_winner_and_losers(self):
        self.write_multi("planning/Semaine_2026-09-14.md", [
            self.week_block("2026-09-14"), self.week_block("2026-09-21"),
        ])
        self.write_single("planning/Semaine_2026-09-21.md", "2026-09-21")
        self.index()
        collisions = I.week_collisions(self.conn)
        self.assertEqual(collisions, [{
            "week_start": "2026-09-21",
            "winner": "planning/Semaine_2026-09-21.md",
            "losers": ["planning/Semaine_2026-09-14.md"],
        }])


class TestGearMileageIndex(Workspace):
    """#40 : sous-section « Chaussures » du profil → table `gear`, lue par
    `arc_index.gear_mileage` (headless, `scripts/arc_index.py gear`)."""

    def write_profile_with_gear(self):
        self.write("planning/Runner_Profile.md", """# Profil de l'athlète

## Matériel & lieux

### Chaussures

- Hoka Speedgoat 5 (bleues) — depuis 2026-03-01 — alerte 700 km — id: speedgoat-bleues (par défaut)
- Adidas Adizero SL — alerte 500 km
- Nike Pegasus (retirée)
""")

    def test_gear_table_indexed_from_profile(self):
        self.write_profile_with_gear()
        self.index()
        rows = {row["gear_id"]: dict(row) for row in self.conn.execute(
            "SELECT * FROM gear ORDER BY gear_id").fetchall()}
        self.assertEqual(set(rows), {"speedgoat-bleues", "adidas-adizero-sl", "nike-pegasus"})
        self.assertEqual(rows["speedgoat-bleues"]["is_default"], 1)
        self.assertEqual(rows["speedgoat-bleues"]["threshold_m"], 700000.0)
        self.assertEqual(rows["speedgoat-bleues"]["start_date"], "2026-03-01")
        self.assertEqual(rows["nike-pegasus"]["retired"], 1)

    def test_gear_mileage_attributes_default_and_flags_unknown(self):
        self.write_profile_with_gear()
        self.write("activities/2026-04-01_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-01", "sport": "trail", '
            '"duration_s": 3600, "distance_m": 15000, "gear_id": "speedgoat-bleues"}'))
        self.write("activities/2026-04-02_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-02", "sport": "running", '
            '"duration_s": 2400, "distance_m": 10000}'))  # sans gear_id -> chaussure par défaut
        self.write("activities/2026-04-03_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-03", "sport": "running", '
            '"duration_s": 1800, "distance_m": 8000, "gear_id": "chaussure-jamais-declaree"}'))
        self.index()
        result = I.gear_mileage(self.conn)
        by_id = {s["gear_id"]: s for s in result["shoes"]}
        self.assertEqual(by_id["speedgoat-bleues"]["distance_m"], 25000)  # 15 + 10 (défaut)
        self.assertEqual(by_id["adidas-adizero-sl"]["distance_m"], 0)
        self.assertFalse(by_id["nike-pegasus"]["alert"])   # retirée : jamais d'alerte
        self.assertEqual(result["unknown"], [{"gear_id": "chaussure-jamais-declaree", "distance_m": 8000}])

    def test_gear_mileage_ignores_non_wear_sports(self):
        self.write_profile_with_gear()
        self.write("activities/2026-04-01_indoor_cycling.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-01", "sport": "indoor_cycling", '
            '"duration_s": 3600, "distance_m": 30000, "gear_id": "speedgoat-bleues"}'))
        self.index()
        result = I.gear_mileage(self.conn)
        by_id = {s["gear_id"]: s for s in result["shoes"]}
        self.assertEqual(by_id["speedgoat-bleues"]["distance_m"], 0)

    def test_gear_mileage_default_shoe_start_date_excludes_prior_history_end_to_end(self):
        """Revue PR #85, blocker 1, de bout en bout : un historique d'AVANT #39
        (aucune activité n'a de `gear_id`, la clé n'existait pas encore) ne doit
        pas se retrouver crédité à une paire déclarée `(par défaut)` hier."""
        self.write("planning/Runner_Profile.md", """# Profil de l'athlète

## Matériel & lieux

### Chaussures

- Hoka Clifton — depuis 2026-09-15 — alerte 700 km — id: clifton (par défaut)
""")
        for i in range(3):
            self.write(f"activities/2025-01-0{i + 1}_running.md", arc(
                '{"arc": 1, "kind": "activity", "date": "2025-01-0%d", "sport": "running", '
                '"duration_s": 3600, "distance_m": 10000}' % (i + 1)))
        self.write("activities/2026-09-20_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "running", '
            '"duration_s": 3600, "distance_m": 10000}'))
        self.index()
        result = I.gear_mileage(self.conn)
        self.assertEqual(result["shoes"][0]["distance_m"], 10000)   # seule la séance du 20/09 compte
        self.assertFalse(result["shoes"][0]["alert"])

    def test_gear_mileage_surfaces_duplicate_slug_warning_end_to_end(self):
        self.write("planning/Runner_Profile.md", """# Profil de l'athlète

## Matériel & lieux

### Chaussures

- Hoka Speedgoat 5
- Hoka Speedgoat 5
""")
        self.index()
        result = I.gear_mileage(self.conn)
        self.assertEqual({s["gear_id"] for s in result["shoes"]}, {"hoka-speedgoat-5", "hoka-speedgoat-5-2"})
        self.assertEqual(len(result["warnings"]), 1)


class TestFuelingCli(Workspace):
    """#41 — `arc_index.fueling_trend` : voie headless (`scripts/arc_index.py fueling`)
    vers glucides/h et taux de sudation sur les sorties longues, bout en bout depuis
    des fichiers `activities/*.md` indexés. N'est pas soumis à `[health].morning_check`
    (contrairement à `hrv-baseline`/`sleep-debt`)."""

    def test_end_to_end_max_and_median(self):
        self.write("activities/2026-08-01_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-08-01", "sport": "trail", '
            '"duration_s": 7200, "distance_m": 18000, "weight_pre_kg": 70.0, '
            '"weight_post_kg": 69.0, "carbs_g": 100}'))
        self.write("activities/2026-08-15_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-08-15", "sport": "trail", '
            '"duration_s": 9000, "distance_m": 22000, "carbs_g": 150}'))
        self.index()
        result = I.fueling_trend(self.conn, date(2026, 9, 23))
        self.assertEqual(result["long_runs"], 2)
        # 100 g / 2 h = 50 g/h ; 150 g / 2,5 h = 60 g/h (max).
        self.assertEqual(result["max_carbs_per_hour_g"], 60.0)
        self.assertEqual(result["carbs_per_hour_n"], 2)
        self.assertEqual(result["carbs_ceiling_g_h"], 60.0 + M.FUELING_MAX_MARGIN_G_H)
        self.assertEqual(result["target_band_g_h"], [60, 90])
        # Une seule séance pesée -> une seule valeur de sudation, effectif à 1.
        self.assertEqual(result["sweat_rate_n"], 1)

    def test_short_sessions_excluded_end_to_end(self):
        self.write("activities/2026-09-20_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "running", '
            '"duration_s": 3600, "distance_m": 10000, "carbs_g": 40}'))
        self.index()
        result = I.fueling_trend(self.conn, date(2026, 9, 23))
        self.assertEqual(result["long_runs"], 0)
        self.assertIsNone(result["max_carbs_per_hour_g"])
        self.assertIsNone(result["carbs_ceiling_g_h"])

    def test_no_data_ceiling_is_none(self):
        self.index()
        result = I.fueling_trend(self.conn, date(2026, 9, 23))
        self.assertEqual(result["long_runs"], 0)
        self.assertIsNone(result["carbs_ceiling_g_h"])
        self.assertEqual(result["target_band_g_h"], [60, 90])

    def test_cycling_excluded_end_to_end(self):
        """Revue de code #41, blocker : un long vélo à haut débit ne doit jamais
        gonfler le plafond d'un plan de COURSE À PIED (`FUELING_SPORTS`, ni la
        SQL `arc_index.fueling_trend` ni `arc_metrics.fueling_trend`)."""
        self.write("activities/2026-08-01_cycling.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-08-01", "sport": "cycling", '
            '"duration_s": 10800, "distance_m": 90000, "carbs_g": 300}'))   # 100 g/h
        self.index()
        result = I.fueling_trend(self.conn, date(2026, 9, 23))
        self.assertEqual(result["long_runs"], 0)
        self.assertIsNone(result["max_carbs_per_hour_g"])

    def test_not_gated_by_morning_check(self):
        """Contrairement à `hrv-baseline`/`sleep-debt`, `fueling_trend` ne lit même
        pas `conf`/`[health].morning_check` : le calcul ne dépend d'aucune donnée de
        santé, seulement des activités déjà indexées."""
        import inspect
        self.assertNotIn("conf", inspect.signature(I.fueling_trend).parameters)

    def test_end_to_end_ignores_health_only_mode(self):
        self.write("activities/2026-08-01_trail.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-08-01", "sport": "trail", '
            '"duration_s": 7200, "distance_m": 18000, "carbs_g": 100}'))
        self.index()
        result = I.fueling_trend(self.conn, date(2026, 9, 23))
        self.assertEqual(result["long_runs"], 1)
        self.assertEqual(result["max_carbs_per_hour_g"], 50.0)


class TestDecisionIndex(Workspace):
    """#54 : type `decision` — classification par nom de fichier, table dédiée
    `decision`/`decision_rule`, tri, filtres et exclusion du backfill."""

    def decision_block(self, date_, created_at, **extra):
        payload = {
            "arc": 1, "kind": "decision", "date": date_, "created_at": created_at,
            "trigger": "guardrail", "summary": "Séance allégée.", "outcome": "applied",
            **extra,
        }
        return arc(json.dumps(payload, ensure_ascii=False))

    def test_classified_by_filename(self):
        self.write("planning/2026-09-22_decision_hrv-hold.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"))
        self.index()
        self.assertEqual(self.status("planning/2026-09-22_decision_hrv-hold.md"), ("ok", 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decision").fetchone()[0], 1)

    def test_stores_full_shape_and_rule_link_table(self):
        self.write("planning/2026-09-24_decision_bloc-qualite.md", self.decision_block(
            "2026-09-24", "2026-09-23T19:40:00+02:00",
            rule_ids=["r5_quality_after_red"], sources=["medical/2026-09-23_health.md"],
            before={"intensity": "threshold"}, after={"intensity": "recovery"},
            session_ref={"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-24"},
            garmin_workout_id=445566,
        ))
        self.index()
        row = dict(self.conn.execute("SELECT * FROM decision").fetchone())
        self.assertEqual(row["date"], "2026-09-24")
        self.assertEqual(row["trigger"], "guardrail")
        self.assertEqual(row["garmin_workout_id"], 445566)
        self.assertEqual(json.loads(row["rule_ids_json"]), ["r5_quality_after_red"])
        self.assertEqual(json.loads(row["before_json"]), {"intensity": "threshold"})
        self.assertEqual(json.loads(row["session_ref_json"])["week"], "planning/Semaine_2026-09-21.md")
        rule_rows = self.conn.execute("SELECT rule_id FROM decision_rule").fetchall()
        self.assertEqual([r[0] for r in rule_rows], ["r5_quality_after_red"])

    def test_never_flagged_as_backfill_debt_even_when_invalid(self):
        """Un fichier `_decision_` sans bloc valide reste hors contrat, mais n'est
        JAMAIS une dette de backfill (#54 : type neuf, aucun historique à reprendre)."""
        self.write("planning/2026-09-25_decision_incomplete.md", "# Décision\n\nTexte libre, pas de bloc.\n")
        self.index()
        paths = [item["path"] for item in I.backfill_items(self.conn)]
        self.assertNotIn("planning/2026-09-25_decision_incomplete.md", paths)

    def test_multiple_decisions_same_day_ordered_by_created_at(self):
        self.write("planning/2026-09-22_decision_morning.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00", summary="Premier."))
        self.write("planning/2026-09-22_decision_evening.md",
                   self.decision_block("2026-09-22", "2026-09-22T18:30:00+02:00", summary="Second."))
        self.index()
        result = I.decisions_query(self.conn)
        self.assertEqual([d["summary"] for d in result], ["Second.", "Premier."])

    def test_decisions_query_filters_by_date(self):
        self.write("planning/2026-09-22_decision_a.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"))
        self.write("planning/2026-09-23_decision_b.md",
                   self.decision_block("2026-09-23", "2026-09-23T07:10:00+02:00"))
        self.index()
        result = I.decisions_query(self.conn, on_date="2026-09-23")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-09-23")

    def test_decisions_query_filters_by_trigger(self):
        self.write("planning/2026-09-22_decision_a.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00", trigger="morning_check"))
        self.write("planning/2026-09-22_decision_b.md",
                   self.decision_block("2026-09-22", "2026-09-22T08:00:00+02:00", trigger="guardrail"))
        self.index()
        result = I.decisions_query(self.conn, trigger="guardrail")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["trigger"], "guardrail")

    def test_decisions_query_days_window(self):
        self.write("planning/2026-09-10_decision_old.md",
                   self.decision_block("2026-09-10", "2026-09-10T07:10:00+02:00"))
        self.write("planning/2026-09-22_decision_recent.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"))
        self.index()
        result = I.decisions_query(self.conn, today=date(2026, 9, 23), days=7)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-09-22")

    def test_decisions_query_with_no_filter_returns_all(self):
        self.write("planning/2026-09-10_decision_old.md",
                   self.decision_block("2026-09-10", "2026-09-10T07:10:00+02:00"))
        self.write("planning/2026-09-22_decision_recent.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"))
        self.index()
        self.assertEqual(len(I.decisions_query(self.conn)), 2)

    def test_removed_file_purges_decision_rows(self):
        path = "planning/2026-09-22_decision_hrv-hold.md"
        self.write(path, self.decision_block(
            "2026-09-22", "2026-09-22T07:10:00+02:00", rule_ids=["r1_acwr_projected"]))
        self.index()
        (self.ws / path).unlink()
        self.index()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decision").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decision_rule").fetchone()[0], 0)

    # -- #100, revue de code -------------------------------------------------

    def test_invalid_block_is_never_stored_as_a_ghost_decision(self):
        """Un `trigger` invalide (bloc rejeté par le contrat) ne doit JAMAIS finir
        en ligne `decision` — même partiellement/à NULL : `decision` n'a aucun
        format hérité légitime, contrairement à `activity`/`health`."""
        self.write("planning/2026-09-22_decision_bad-trigger.md", arc(
            '{"arc": 1, "kind": "decision", "date": "2026-09-22", '
            '"created_at": "2026-09-22T07:10:00+02:00", "trigger": "nope", '
            '"summary": "x", "outcome": "applied"}'))
        self.index()
        self.assertEqual(self.status("planning/2026-09-22_decision_bad-trigger.md")[0], "invalid")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decision").fetchone()[0], 0)
        self.assertEqual(I.decisions_query(self.conn), [])

    def test_ordering_correct_across_timezone_offsets(self):
        """#100, revue de code : `A` (07:00+02:00 = 05:00 UTC) est en fait
        ANTÉRIEUR à `B` (06:00Z = 06:00 UTC) — un tri texte sur `created_at`
        mettrait `A` en tête (« 07:00... » > « 06:00Z » lexicalement), un tri
        sur `created_at_utc` doit mettre `B` en tête."""
        self.write("planning/2026-09-22_decision_a.md", self.decision_block(
            "2026-09-22", "2026-09-22T07:00:00+02:00", summary="A (05:00 UTC).", outcome="superseded"))
        self.write("planning/2026-09-22_decision_b.md", self.decision_block(
            "2026-09-22", "2026-09-22T06:00:00Z", summary="B (06:00 UTC)."))
        self.index()
        result = I.decisions_query(self.conn)
        self.assertEqual([d["summary"] for d in result], ["B (06:00 UTC).", "A (05:00 UTC)."])

    def test_stores_supersedes(self):
        self.write("planning/2026-09-24_decision_new.md", self.decision_block(
            "2026-09-24", "2026-09-24T06:30:00+02:00",
            supersedes="planning/2026-09-23_decision_old.md"))
        self.index()
        row = dict(self.conn.execute("SELECT supersedes FROM decision").fetchone())
        self.assertEqual(row["supersedes"], "planning/2026-09-23_decision_old.md")

    def test_decisions_query_active_excludes_superseded_and_rejected(self):
        self.write("planning/2026-09-20_decision_old.md",
                   self.decision_block("2026-09-20", "2026-09-20T07:00:00+02:00",
                                        summary="Remplacée.", outcome="superseded"))
        self.write("planning/2026-09-21_decision_rejected.md",
                   self.decision_block("2026-09-21", "2026-09-21T07:00:00+02:00",
                                        summary="Refusée.", outcome="rejected_by_athlete"))
        self.write("planning/2026-09-22_decision_current.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:00:00+02:00",
                                        summary="Courante.", outcome="applied"))
        self.index()
        result = I.decisions_query(self.conn, active=True)
        self.assertEqual([d["summary"] for d in result], ["Courante."])
        self.assertEqual(len(I.decisions_query(self.conn)), 3)

    def test_decisions_query_filters_by_outcome(self):
        self.write("planning/2026-09-22_decision_a.md",
                   self.decision_block("2026-09-22", "2026-09-22T07:00:00+02:00", outcome="proposed"))
        self.write("planning/2026-09-22_decision_b.md",
                   self.decision_block("2026-09-22", "2026-09-22T08:00:00+02:00", outcome="applied"))
        self.index()
        result = I.decisions_query(self.conn, outcome="proposed")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["outcome"], "proposed")

    def test_classify_does_not_match_substring_only(self):
        """L'ancien motif (`"_decision_" in name`) aurait classé n'importe quel
        fichier contenant ce segment n'importe où — l'ancrage exige le format
        exact `AAAA-MM-JJ_decision_<slug>.md`."""
        self.assertIsNone(I.classify("planning/journal_decision_generale.md"))
        self.assertIsNone(I.classify("planning/decision_2026-09-22.md"))
        self.assertEqual(I.classify("planning/2026-09-22_decision_hrv-hold.md"), "decision")

    def test_validate_file_warns_on_filename_date_mismatch(self):
        path = self.ws / "planning/2026-09-22_decision_hrv-hold.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.decision_block("2026-09-23", "2026-09-23T07:10:00+02:00"), encoding="utf-8")
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertTrue(any("2026-09-22" in w and "2026-09-23" in w for w in warnings), warnings)

    def test_validate_file_no_warning_when_dates_match(self):
        path = self.ws / "planning/2026-09-22_decision_hrv-hold.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"), encoding="utf-8")
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertEqual(warnings, [])

    # -- #55, revue de code ---------------------------------------------------

    def test_classify_rejects_a_dotted_slug(self):
        """`[^/.]+` (jamais `[^/]+`) : un `<slug>` avec un point resterait
        indexable via le repli `block_kind` de `read_file` (le bloc fait foi
        quand le nom ne dit rien), mais son id `/api/decision/<id>` (jamais un
        point accepté, voir `arc_serve.DECISION_ID_RE`) ne pourrait plus jamais
        le désigner — `classify()` doit refuser ce nom d'entrée de jeu."""
        self.assertIsNone(I.classify("planning/2026-09-22_decision_dotted.v2.md"))
        self.assertEqual(I.classify("planning/2026-09-22_decision_dotted-v2.md"), "decision")

    def test_classify_accepts_a_subfolder_by_filename_alone(self):
        """`classify()` ne regarde que le premier et le dernier segment du chemin
        (comportement PRÉEXISTANT, partagé par tous les types `planning/*`, pas
        seulement `decision`) : un fichier dans un sous-dossier de `planning/`
        est donc classé « decision » comme au premier niveau — c'est
        `classify_source_path` (pour `sources`/`supersedes`) et le lien de
        détail du dashboard (`api_decision`, recherche par id calculé plutôt que
        par chemin reconstruit) qui gèrent ce cas, pas `classify()` lui-même."""
        self.assertEqual(I.classify("planning/archive/2026-09-22_decision_hrv-hold.md"), "decision")

    def test_validate_file_warns_on_dotted_slug(self):
        path = self.ws / "planning/2026-09-22_decision_dotted.v2.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"), encoding="utf-8")
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertTrue(any("hors du format attendu" in w for w in warnings), warnings)

    def test_validate_file_warns_on_subfolder_placement(self):
        path = self.ws / "planning/archive/2026-09-22_decision_hrv-hold.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.decision_block("2026-09-22", "2026-09-22T07:10:00+02:00"), encoding="utf-8")
        ok, errors, warnings = I.validate_file(path)
        self.assertTrue(ok, errors)
        self.assertTrue(any("hors du format attendu" in w for w in warnings), warnings)


class TestClassifySourcePath(unittest.TestCase):
    """#55 : `classify_source_path` — pure, aucun accès disque/base — reconnaît
    un chemin `sources`/`supersedes`/`session_ref.week` de décision PAR SON NOM
    seul, pour que le dashboard sache quelle vue lier sans jamais rouvrir le
    fichier désigné."""

    def test_health_file(self):
        self.assertEqual(I.classify_source_path("medical/2026-09-22_health.md"),
                          {"path": "medical/2026-09-22_health.md", "kind": "health", "date": "2026-09-22"})

    def test_weather_file(self):
        self.assertEqual(I.classify_source_path("medical/2026-09-22_meteo.md")["kind"], "weather")

    def test_nutrition_file(self):
        self.assertEqual(I.classify_source_path("nutrition/2026-09-22_nutrition.md")["kind"], "nutrition")

    def test_activity_file(self):
        result = I.classify_source_path("activities/2026-09-22_trail.md")
        self.assertEqual(result, {"path": "activities/2026-09-22_trail.md", "kind": "activity", "date": "2026-09-22"})

    def test_week_file(self):
        result = I.classify_source_path("planning/Semaine_2026-09-21.md")
        self.assertEqual(result, {"path": "planning/Semaine_2026-09-21.md", "kind": "week", "date": "2026-09-21"})

    def test_decision_file(self):
        result = I.classify_source_path("planning/2026-09-20_decision_hrv-hold.md")
        self.assertEqual(result, {"path": "planning/2026-09-20_decision_hrv-hold.md",
                                  "kind": "decision", "date": "2026-09-20"})

    def test_decision_in_a_subfolder_is_not_classified_as_decision(self):
        """#55, revue de code : ancré `^planning/[^/]+$` — jamais le nom de
        fichier seul (`Path(path).name`), qui aurait classé un chemin
        `planning/archive/...` comme une décision LIABLE alors que
        `arc_serve.DECISION_ID_RE` (id = nom sans extension, jamais un chemin)
        ne désigne QUE `planning/<id>.md` : un sous-dossier aurait rendu le lien
        de détail invariablement 404."""
        result = I.classify_source_path("planning/archive/2026-09-20_decision_hrv-hold.md")
        self.assertEqual(result["kind"], "other")

    def test_decision_with_a_dotted_slug_is_not_classified_as_decision(self):
        """Même motif que `classify()` (`test_classify_rejects_a_dotted_slug`) :
        un point dans le slug empêcherait `Path(path).stem` de correspondre à
        `arc_serve.DECISION_ID_RE`, qui n'en accepte aucun."""
        result = I.classify_source_path("planning/2026-09-20_decision_dotted.v2.md")
        self.assertEqual(result["kind"], "other")

    def test_report_file(self):
        result = I.classify_source_path("rapports/2026-09-21_rapport.md")
        self.assertEqual(result["kind"], "report")
        self.assertIsNone(result["date"])

    def test_resource_and_unknown_paths_are_other(self):
        self.assertEqual(I.classify_source_path("resources/running/acwr.md")["kind"], "other")
        self.assertEqual(I.classify_source_path("planning/active_objective.md")["kind"], "other")

    def test_none_is_other(self):
        self.assertEqual(I.classify_source_path(None), {"path": None, "kind": "other", "date": None})

    def test_never_matches_a_substring_only(self):
        """Même discipline que `test_classify_does_not_match_substring_only` :
        un fichier qui ne respecte pas le format exact reste `"other"`, jamais
        classé par erreur sur un simple segment du nom."""
        self.assertEqual(I.classify_source_path("planning/journal_decision_generale.md")["kind"], "other")
        self.assertEqual(I.classify_source_path("activities/fit/12345.json")["kind"], "other")


class TestDecisionCli(Workspace):
    """#100, revue de code : garde-fous CLI de `arc_index.py decisions` — refus
    explicite d'une combinaison ambiguë plutôt qu'une précédence silencieuse."""

    def run_cli(self, *args):
        cmd = [sys.executable, str(REPO / "scripts/arc_index.py"), "decisions",
               "--workspace", str(self.ws), "--memory", *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_date_and_days_together_is_rejected(self):
        result = self.run_cli("--date", "2026-09-22", "--days", "7")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incompatibles", result.stderr)

    def test_days_below_one_is_rejected(self):
        result = self.run_cli("--days", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--days", result.stderr)

    def test_days_one_is_accepted(self):
        result = self.run_cli("--days", "1", "--today", "2026-09-22")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])


class TestParseGearStartMileage(unittest.TestCase):
    """#132 — segment « départ N km » (ou « N mi ») et « usage: … » de `parse_gear`."""

    def _gear(self, bullet: str):
        text = f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n- {bullet}\n"
        gear = L.parse_gear(text)
        self.assertEqual(len(gear), 1, gear)
        return gear[0]

    def test_start_km(self):
        g = self._gear("Nike Pegasus — départ 300 km — id: pegasus")
        self.assertEqual(g["start_m"], 300000)
        self.assertEqual(g["gear_id"], "pegasus")
        self.assertEqual(g["name"], "Nike Pegasus")

    def test_start_miles_converted(self):
        for unit in ("mi", "miles", "mile"):
            with self.subTest(unit=unit):
                self.assertEqual(self._gear(f"Nike Pegasus — départ 100 {unit}")["start_m"], 160934)

    def test_start_without_accent_and_decimal_comma(self):
        self.assertEqual(self._gear("Nike Pegasus — depart 12,5 km")["start_m"], 12500)

    def test_start_absent_key_omitted(self):
        self.assertNotIn("start_m", self._gear("Nike Pegasus — alerte 600 km"))

    def test_start_zero_is_kept(self):
        self.assertEqual(self._gear("Nike Pegasus — départ 0 km")["start_m"], 0)

    def test_start_unreadable_or_negative_ignored(self):
        self.assertNotIn("start_m", self._gear("Nike Pegasus — départ beaucoup"))
        self.assertNotIn("start_m", self._gear("Nike Pegasus — départ -50 km"))

    def test_start_with_other_segments_and_flags(self):
        g = self._gear("Hoka Speedgoat 5 — depuis 2026-03-01 — départ 120 km — alerte 700 km (retirée)")
        self.assertEqual((g["start_m"], g["threshold_m"], g["start_date"]), (120000, 700000, "2026-03-01"))
        self.assertIs(g["retired"], True)

    def test_start_with_colon_separator(self):
        self.assertEqual(self._gear("Nike Pegasus: départ 40 km")["start_m"], 40000)

    def test_departure_word_in_free_note_is_not_a_segment_keyword(self):
        g = self._gear("Nike Pegasus — départementale uniquement")
        self.assertNotIn("start_m", g)

    def test_usage_segment(self):
        g = self._gear("Salomon S/Lab — usage: course — départ 20 km")
        self.assertEqual(g["usage"], "course")
        self.assertEqual(g["start_m"], 20000)
        self.assertEqual(g["name"], "Salomon S/Lab")

    def test_no_usage_key_when_absent(self):
        self.assertNotIn("usage", self._gear("Salomon S/Lab"))


class TestGearStartMileageIndex(Workspace):
    """#132 : `start_m`/`usage` persistés dans la table `gear`, départ compté dans le cumul."""

    def test_start_m_indexed_and_counted(self):
        self.write("planning/Runner_Profile.md", """# Profil

## Matériel & lieux

### Chaussures

- Nike Pegasus — départ 300 km — id: pegasus (par défaut)
- Salomon S/Lab — usage: course — id: slab
""")
        self.write("activities/2026-04-01_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-01", "sport": "running", '
            '"duration_s": 3600, "distance_m": 10000}'))
        self.index()
        rows = {r["gear_id"]: dict(r) for r in self.conn.execute("SELECT * FROM gear")}
        self.assertEqual(rows["pegasus"]["start_m"], 300000)
        self.assertIsNone(rows["slab"]["start_m"])
        self.assertEqual(rows["slab"]["usage"], "course")
        result = I.gear_mileage(self.conn, date(2026, 4, 5))
        by_id = {s["gear_id"]: s for s in result["shoes"]}
        self.assertEqual(by_id["pegasus"]["distance_m"], 310000)
        self.assertEqual(by_id["pegasus"]["start_m"], 300000)
        self.assertEqual(by_id["slab"]["usage"], "course")

    def test_cli_gear_crossed_in_run_once(self):
        self.write("planning/Runner_Profile.md", """# Profil

## Matériel & lieux

### Chaussures

- Nike Pegasus — départ 95 km — alerte 100 km — id: pegasus (par défaut)
""")
        morning = "activities/2026-04-04_running.md"
        self.write(morning, arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-04", "sport": "running", '
            '"duration_s": 3600, "distance_m": 10000, "garmin_activity_id": 5551}'))
        self.index()
        today = date(2026, 4, 5)
        shoe = I.gear_mileage(self.conn, today, ["5551"])["shoes"][0]
        self.assertTrue(shoe["alert"])
        self.assertTrue(shoe["crossed_in_run"])
        self.assertNotIn("retire_forecast_date", shoe)   # seuil dépassé : pas de prévision
        # même séance désignée par son chemin
        self.assertTrue(I.gear_mileage(self.conn, today, [morning])["shoes"][0]["crossed_in_run"])
        # second passage du même jour : séance du soir seule dans le run
        self.write("activities/2026-04-04_running_2.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-04", "sport": "running", '
            '"duration_s": 1800, "distance_m": 4000, "garmin_activity_id": 5552}'))
        self.index()
        second = I.gear_mileage(self.conn, today, ["5552"])["shoes"][0]
        self.assertNotIn("crossed_in_run", second)
        # re-fusion d'une séance déjà synchronisée : rien n'est passé, rien n'est émis
        self.assertNotIn("crossed_in_run", I.gear_mileage(self.conn, today)["shoes"][0])

    def test_cli_activities_flag_and_invalid_today(self):
        self.write("planning/Runner_Profile.md", "# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                   "- Nike Pegasus — départ 10 km — alerte 11 km — id: pegasus (par défaut)\n")
        self.write("activities/2026-04-04_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-04", "sport": "running", '
            '"duration_s": 3600, "distance_m": 5000, "garmin_activity_id": 5551}'))
        base = [sys.executable, str(REPO / "scripts/arc_index.py"), "gear", "--workspace", str(self.ws),
                "--memory", "--today", "2026-04-05"]
        ok = subprocess.run(base + ["--activities", "5551, 99"], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["shoes"][0]["crossed_in_run"])
        bad = subprocess.run(base[:-1] + ["2026-9-1"], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--today", bad.stderr + bad.stdout)


class TestParseGearStrictStart(unittest.TestCase):
    """#132 (revue) : forme stricte du segment « départ », unités collées, décimales."""

    def _gear(self, bullet):
        return L.parse_gear(f"# P\n\n## Matériel & lieux\n\n### Chaussures\n\n- {bullet}\n")[0]

    def test_free_text_after_keyword_is_ignored(self):
        for seg in ("départ usine 2025", "départ en rotation le 12/03", "départ vers 2025 environ"):
            with self.subTest(seg=seg):
                g = self._gear(f"Nike Pegasus — {seg}")
                self.assertNotIn("start_m", g)
                self.assertEqual(g["name"], "Nike Pegasus")

    def test_accepted_shapes(self):
        cases = {"départ 300 km": 300000, "départ: 300": 300000, "départ ~300 km": 300000,
                 "départ : ~ 300 km": 300000, "départ 1 200 km": 1200000, "départ 12,5": 12500,
                 "départ 186mi": 299338, "départ 100 miles": 160934, "départ 300km": 300000}
        for seg, expected in cases.items():
            with self.subTest(seg=seg):
                self.assertEqual(self._gear(f"Nike Pegasus — {seg}")["start_m"], expected)

    def test_dot_or_comma_is_always_decimal(self):
        self.assertEqual(self._gear("Nike Pegasus — départ 1.200 km")["start_m"], 1200)
        self.assertEqual(self._gear("Nike Pegasus — départ 1,200 km")["start_m"], 1200)

    def test_glued_miles_unit_on_alert_too(self):
        self.assertEqual(self._gear("Nike Pegasus — alerte 400mi")["threshold_m"], 643738)
        self.assertEqual(self._gear("Nike Pegasus — alerte 400 min")["threshold_m"], 400000)

U1 = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
U2 = "0f9e8d7c6b5a49382716f5e4d3c2b1a0"


class TestGearGarminSegment(Workspace):
    """#133 : segment « garmin: <uuid> », colonnes indexées et priorité d'attribution."""

    def _gear(self, bullet: str):
        text = f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n- {bullet}\n"
        gear = L.parse_gear(text)
        self.assertEqual(len(gear), 1, gear)
        return gear[0]

    def test_garmin_segment_all_separators(self):
        for sep in (" — ", " - ", ": ", " – "):
            with self.subTest(sep=sep):
                g = self._gear(f"Nike Pegasus{sep}garmin: {U1.upper()} — départ 20 km")
                self.assertEqual(g["garmin_uuid"], U1)   # minuscules
                self.assertEqual(g["gear_id"], "nike-pegasus")
                self.assertEqual(g["start_m"], 20000)

    def test_dashed_uuid_and_absent(self):
        dashed = "a1b2c3d4-e5f6-0718-293a-4b5c6d7e8f90"
        self.assertEqual(self._gear(f"Nike Pegasus — garmin: {dashed}")["garmin_uuid"], dashed)
        self.assertNotIn("garmin_uuid", self._gear("Nike Pegasus — alerte 600 km"))

    def test_malformed_uuid_ignored(self):
        for bad in ("abc", "pas un uuid !", ""):
            with self.subTest(bad=bad):
                self.assertNotIn("garmin_uuid", self._gear(f"Nike Pegasus — garmin: {bad}"))

    def test_garmin_word_in_free_text_not_a_segment(self):
        g = self._gear("Nike Pegasus — synchronisée garmin plus tard")
        self.assertNotIn("garmin_uuid", g)

    def test_indexed_and_gear_source_column(self):
        self.write("planning/Runner_Profile.md", f"""# Profil

## Matériel & lieux

### Chaussures

- Nike Pegasus — garmin: {U1} — id: pegasus (par défaut)
- Salomon S/Lab — id: slab
""")
        self.write("activities/2026-04-01_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-01", "sport": "running", '
            '"duration_s": 3600, "distance_m": 10000, "gear_id": "slab", "gear_source": "garmin"}'))
        self.index()
        rows = {r["gear_id"]: r["garmin_uuid"] for r in self.conn.execute("SELECT * FROM gear")}
        self.assertEqual(rows, {"pegasus": U1, "slab": None})
        self.assertEqual(self.conn.execute("SELECT gear_source FROM activity").fetchone()[0], "garmin")

    def test_schema_version_27_columns(self):
        self.index()
        self.assertIn("garmin_uuid", {r[1] for r in self.conn.execute("PRAGMA table_info(gear)")})
        self.assertIn("gear_source", {r[1] for r in self.conn.execute("PRAGMA table_info(activity)")})


class TestGearAttributionPriority(unittest.TestCase):
    """#133 : Garmin > chat > défaut — l'athlète gagne un conflit, rien n'est deviné."""

    DEFS = [{"gear_id": "pegasus", "garmin_uuid": U1}, {"gear_id": "slab", "garmin_uuid": U2},
            {"gear_id": "speedgoat"}]

    def r(self, uuids, chat=None, defs=None):
        return M.resolve_gear_attribution(defs or self.DEFS, uuids, chat)

    def test_garmin_only(self):
        out = self.r([U1])
        self.assertEqual((out["gear_id"], out["gear_source"], out["conflict"]), ("pegasus", "garmin", None))

    def test_case_insensitive_uuid(self):
        self.assertEqual(self.r([U1.upper()])["gear_id"], "pegasus")

    def test_chat_only(self):
        out = self.r([], "speedgoat")
        self.assertEqual((out["gear_id"], out["gear_source"]), ("speedgoat", "chat"))

    def test_agreement_is_not_a_conflict(self):
        out = self.r([U1], "pegasus")
        self.assertEqual((out["gear_id"], out["conflict"]), ("pegasus", None))

    def test_conflict_athlete_wins_and_is_flagged(self):
        out = self.r([U1], "slab")
        self.assertEqual((out["gear_id"], out["gear_source"]), ("slab", "chat"))
        self.assertEqual(out["conflict"], {"garmin": "pegasus", "chat": "slab"})

    def test_nothing_falls_back_to_default(self):
        out = self.r([])
        self.assertEqual((out["gear_id"], out["gear_source"]), (None, None))

    def test_unmapped_garmin_never_attributed(self):
        out = self.r(["ffffffffffffffffffffffffffffffff"])
        self.assertIsNone(out["gear_id"])
        self.assertEqual(out["unmapped_garmin"], ["ffffffffffffffffffffffffffffffff"])

    def test_unmapped_with_chat_keeps_chat_and_reports_unmapped(self):
        out = self.r(["ffffffffffffffffffffffffffffffff"], "slab")
        self.assertEqual((out["gear_id"], out["conflict"]), ("slab", None))
        self.assertEqual(len(out["unmapped_garmin"]), 1)

    def test_two_mapped_pairs_is_ambiguous(self):
        out = self.r([U1, U2])
        self.assertIsNone(out["gear_id"])
        self.assertEqual(sorted(out["ambiguous"]), ["pegasus", "slab"])

    def test_shared_uuid_on_two_bullets_is_ambiguous(self):
        defs = [{"gear_id": "a", "garmin_uuid": U1}, {"gear_id": "b", "garmin_uuid": U1}]
        out = self.r([U1], defs=defs)
        self.assertIsNone(out["gear_id"])
        self.assertEqual(sorted(out["ambiguous"]), ["a", "b"])

    def test_unmapped_without_chat_yields_marker_without_gear_id(self):
        out = self.r(["ffffffffffffffffffffffffffffffff"])
        self.assertEqual((out["gear_id"], out["gear_source"]), (None, "garmin_unmapped"))

    def test_ambiguous_yields_marker(self):
        self.assertEqual(self.r([U1, U2])["gear_source"], "garmin_unmapped")

    def test_chat_beats_marker(self):
        self.assertEqual(self.r(["ffffffffffffffffffffffffffffffff"], "slab")["gear_source"], "chat")

    def test_no_garmin_gear_no_marker(self):
        self.assertIsNone(self.r([])["gear_source"])

    def test_ignored_uuid_is_silent_but_marked(self):
        defs = self.DEFS + [{"gear_id": "ghost", "garmin_uuid": "c0ffee00c0ffee00c0ffee00c0ffee00", "ignored": 1}]
        out = self.r(["c0ffee00c0ffee00c0ffee00c0ffee00"], defs=defs)
        self.assertEqual((out["unmapped_garmin"], out["ignored_garmin"], out["gear_source"]),
                         ([], ["c0ffee00c0ffee00c0ffee00c0ffee00"], "garmin_unmapped"))

    def test_cli(self):
        ws = Path(tempfile.mkdtemp(prefix="arc-gear-attr-"))
        self.addCleanup(shutil.rmtree, ws, True)
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (ws / d).mkdir()
        (ws / "planning/Runner_Profile.md").write_text(
            f"# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n- Nike Pegasus — garmin: {U1}\n"
            "- Salomon S/Lab\n", encoding="utf-8")
        cmd = [sys.executable, str(Path(I.__file__)), "gear-attribution", "--workspace", str(ws),
               "--garmin-gear", f"{U1},{U2}", "--chat-gear", "salomon-s-lab"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual((out["gear_id"], out["gear_source"]), ("salomon-s-lab", "chat"))
        self.assertEqual(out["conflict"], {"garmin": "nike-pegasus", "chat": "salomon-s-lab"})
        self.assertEqual(out["unmapped_garmin"], [U2])



class TestGearUnmappedNeverCreditedToDefault(Workspace):
    """#133 — revue : un matériel Garmin non associé ne doit JAMAIS être crédité en silence à la
    paire par défaut (sinon faux kilométrage, faux `crossed_in_run`)."""

    PROFILE = f"""# Profil

## Matériel & lieux

### Chaussures

- Nike Pegasus — id: pegasus — alerte 20 km (par défaut)
- Brooks Ghost — garmin: c0ffee00c0ffee00c0ffee00c0ffee00 (ignorée)
"""

    def _run(self, extra):
        self.write("planning/Runner_Profile.md", self.PROFILE)
        self.write("activities/2026-04-01_running.md", arc(
            '{"arc": 1, "kind": "activity", "date": "2026-04-01", "sport": "running", "duration_s": 3600, '
            '"distance_m": 15000, "garmin_activity_id": 777' + extra + '}'))
        self.index()
        return I.gear_mileage(self.conn, date(2026, 4, 5), ["777"])

    def test_control_without_marker_credits_the_default_pair(self):
        shoes = {s["gear_id"]: s for s in self._run("")["shoes"]}
        self.assertEqual(shoes["pegasus"]["distance_m"], 15000)

    def test_unmapped_marker_is_excluded_from_default_and_crossed_in_run(self):
        result = self._run(', "gear_source": "garmin_unmapped"')
        shoes = {s["gear_id"]: s for s in result["shoes"]}
        self.assertEqual(shoes["pegasus"]["distance_m"], 0)
        self.assertNotIn("crossed_in_run", shoes["pegasus"])

    def test_ignored_bullet_is_not_a_shoe_but_is_resolvable(self):
        self._run("")
        self.assertEqual([s["gear_id"] for s in I.gear_mileage(self.conn, date(2026, 4, 5))["shoes"]], ["pegasus"])
        out = I.gear_attribution(self.conn, "c0ffee00c0ffee00c0ffee00c0ffee00", None)
        self.assertEqual(out["ignored_garmin"], ["c0ffee00c0ffee00c0ffee00c0ffee00"])
        self.assertEqual(out["unmapped_garmin"], [])
        self.assertEqual((out["gear_id"], out["gear_source"]), (None, "garmin_unmapped"))


class TestGearAttributionCliHardening(Workspace):
    """#133 — revue : uuid validés, `--chat-gear` normalisé en gear_id valide au contrat."""

    def setUp(self):
        super().setUp()
        self.write("planning/Runner_Profile.md", f"""# Profil

## Matériel & lieux

### Chaussures

- Nike Pegasus — id: pegasus — garmin: {U1}
- Salomon S/Lab Ultra — garmin: {U2}
""")
        self.index()

    def test_non_uuid_text_is_ignored(self):
        out = I.gear_attribution(self.conn, "No gear data found for activity with ID 1", None)
        self.assertEqual((out["gear_id"], out["gear_source"], out["unmapped_garmin"]), (None, None, []))

    def test_chat_gear_by_profile_id_name_or_slug(self):
        for raw, expected in (("pegasus", "pegasus"), ("Nike Pegasus", "pegasus"),
                              ("Salomon S/Lab Ultra", "salomon-s-lab-ultra"), ("Hoka Speedgoat 5", "hoka-speedgoat-5")):
            with self.subTest(raw=raw):
                out = I.gear_attribution(self.conn, None, raw)
                self.assertEqual((out["gear_id"], out["gear_source"]), (expected, "chat"))
                self.assertTrue(C_gear_id_ok(out["gear_id"]))

    def test_chat_gear_with_no_alphanumeric_is_dropped(self):
        self.assertIsNone(I.gear_attribution(self.conn, None, "???")["gear_id"])

    def test_already_synced_activity_uses_stored_garmin_side(self):
        """Séance déjà synchronisée : le côté Garmin = l'uuid de la puce du `gear_id` stocké."""
        out = I.gear_attribution(self.conn, U1, "salomon-s-lab-ultra")   # stocké : pegasus (garmin), chat : S/Lab
        self.assertEqual(out["conflict"], {"garmin": "pegasus", "chat": "salomon-s-lab-ultra"})


def C_gear_id_ok(value):
    import arc_contract as C
    errors, _ = C.validate({"arc": 1, "kind": "activity", "date": "2026-01-01", "sport": "running",
                            "duration_s": 60, "gear_id": value})
    return not errors


class TestGearProfileSegments(unittest.TestCase):
    """#133 — `(ignorée)` et `garmin:` illisible côté parse_gear."""

    def _one(self, bullet):
        gear = L.parse_gear(f"# P\n\n### Chaussures\n\n- {bullet}\n")
        self.assertEqual(len(gear), 1)
        return gear[0]

    def test_ignored_flag(self):
        g = self._one(f"Brooks Ghost — garmin: {U1} (ignorée)")
        self.assertTrue(g["ignored"])
        self.assertEqual(g["garmin_uuid"], U1)
        self.assertEqual(g["name"], "Brooks Ghost")

    def test_invalid_segment_is_flagged(self):
        g = self._one("Nike Pegasus — garmin: abc")
        self.assertTrue(g["garmin_uuid_invalid"])
        self.assertNotIn("garmin_uuid", g)
        self.assertNotIn("garmin_uuid_invalid", self._one(f"Nike Pegasus — garmin: {U1}"))


class TestSchemaMigrationV26ToV27(Workspace):
    def test_v26_database_is_rebuilt_with_new_columns(self):
        """#133 : une base v26 (sans `gear.garmin_uuid`/`gear.ignored`/`activity.gear_source`) est reconstruite ;
        l'indexation ne lève pas « no such column » et le profil, déjà connu (même sha256), est relu."""
        self.write("planning/Runner_Profile.md", f"# P\n\n### Chaussures\n\n- Nike Pegasus — garmin: {U1}\n")
        db_path = self.tmp / "v26.db"
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '26');"
            "CREATE TABLE source_file (path TEXT PRIMARY KEY, kind TEXT, sha256 TEXT, mtime REAL, "
            "arc_version INTEGER, parsed_ok TEXT, issues TEXT);"
            "CREATE TABLE gear (source_path TEXT, gear_id TEXT, name TEXT, start_date TEXT, threshold_m REAL, "
            "is_default INTEGER, retired INTEGER, collision_base TEXT, start_m REAL, usage TEXT);")
        digest = hashlib.sha256((self.ws / "planning/Runner_Profile.md").read_bytes()).hexdigest()
        legacy.execute("INSERT INTO source_file VALUES (?, 'athlete', ?, 0, 0, 'ok', '[]')",
                       ("planning/Runner_Profile.md", digest))
        legacy.commit()
        legacy.close()
        conn = I.open_db(self.ws, str(db_path))
        try:
            self.assertEqual(conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], str(I.SCHEMA_VERSION))
            cols = {r[1] for r in conn.execute("PRAGMA table_info(gear)")}
            self.assertTrue({"garmin_uuid", "ignored"} <= cols, cols)
            self.assertIn("gear_source", {r[1] for r in conn.execute("PRAGMA table_info(activity)")})
            I.index_workspace(conn, self.ws, "2026-09-27")
            self.assertEqual(conn.execute("SELECT garmin_uuid FROM gear").fetchone()[0], U1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
