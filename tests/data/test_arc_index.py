"""Palier D — index dérivé : chaîne de lecture, incrémentalité, et les défauts
trouvés sur un vrai workspace (doublons, fichiers d'analyse, fichiers sans date).
"""

from __future__ import annotations

import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
