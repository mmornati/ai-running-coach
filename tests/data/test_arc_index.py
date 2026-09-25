"""Palier D — index dérivé : chaîne de lecture, incrémentalité, et les défauts
trouvés sur un vrai workspace (doublons, fichiers d'analyse, fichiers sans date).
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
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
        self.assertEqual(I.SCHEMA_VERSION, 13)

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


if __name__ == "__main__":
    unittest.main()
