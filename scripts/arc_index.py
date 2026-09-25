#!/usr/bin/env python3
"""Index SQLite dérivé du workspace : la source de vérité reste le Markdown.

La base est jetable et reconstruisible à tout moment depuis les fichiers. Elle
sert au tableau de bord (`scripts/arc_serve.py`) et aux calculs de charge
(`scripts/arc_metrics.py`).

    arc_index.py                         # (ré)indexe le workspace, incrémental
    arc_index.py --rebuild               # repart de zéro
    arc_index.py --validate FICHIER…     # vérifie le bloc ```arc (code 1 si non conforme)
    arc_index.py backfill-plan           # écrit .arc/backfill.md : fichiers à réécrire au contrat
    arc_index.py status                  # état de l'index, en JSON
    arc_index.py hrv-baseline            # ligne de base HRV personnelle du jour, en JSON (#34)
    arc_index.py sleep-debt               # dette de sommeil 7 j du jour, en JSON (#37)
    arc_index.py heat-acclimation         # acclimatation à la chaleur, 14 j, en JSON (#38)
    arc_index.py fueling                  # glucides/h et sudation, sorties longues, en JSON (#41)
    arc_index.py samples GARMIN_ID         # échantillons ingérés d'une séance, en JSON (#42)

`hrv-baseline` n'a besoin d'aucun tableau de bord lancé (headless, `/garmin-daily-sync`
compris) : elle réindexe puis rend le point du jour de `arc_metrics.hrv_baseline_series`
sur `medical/*_health.md::hrv_overnight_ms`, ou `{"status": null, "morning_check": ...}`
si `[health].morning_check` n'est pas `"full"` (rien n'est calculé aux autres niveaux,
voir `arc_metrics.ASSUMPTIONS["hrv_baseline"]`). Les agents `medical`/`coach` l'appellent
quand `get_hrv_data` (Garmin) ne renvoie pas de `baseline`, au lieu d'inventer un statut
Garmin ou de rester silencieux sur la HRV.

`sleep-debt` a la même discipline headless : dette de sommeil 7 j (besoin du profil,
défaut 7 h 30, − sommeil réalisé, nuits manquantes jamais comptées 0 h) sur
`medical/*_health.md::sleep_total_s`, ou `{"sleep_debt_7d_s": null, "morning_check": ...}`
hors `"full"` (voir `arc_metrics.ASSUMPTIONS["sleep_debt"]`). Utilisée par `coach`/`medical`.

`heat-acclimation` joint les activités outdoor et les fichiers météo du même jour sur
les 14 derniers jours (`[health].heat_threshold_c`, défaut 25 °C) : nombre de séances
« chaudes » et durée cumulée, séances sans météo comptées à part
(`sessions_without_weather`, jamais froides par défaut). N'est PAS soumis à
`[health].morning_check` (voir `arc_metrics.ASSUMPTIONS["heat_acclimation"]`). Utilisée
par `coach` et `course-strategist` (course dont la météo prévue est chaude).

`fueling` agrège glucides/h et taux de sudation sur les sorties longues (> 90 min) des
12 dernières semaines glissantes : meilleur débit observé (+ plafond avec marge de
progression), médiane du taux de sudation, effectifs. N'est PAS soumis à
`[health].morning_check` (voir `arc_metrics.ASSUMPTIONS["fueling"]`). Utilisée par
`course-strategist` pour plafonner l'objectif glucides/h d'un plan de course.

`samples` rend, pour une séance donnée (identifiée par son `garmin_activity_id`,
pas l'id interne de la table `activity`), les échantillons FIT déjà ingérés
(sous-échantillonnés, triés par `t_s`) ou `{"samples": [], "reason": ...}` si la
séance n'a pas de FIT associé — jamais une erreur (voir `arc_samples.py` et
`ingest_samples` ci-dessous pour le format et l'ingestion elle-même).

Options communes : `--workspace DIR` (sinon $ARC_WORKSPACE, le pointeur
~/.config/ai-running-coach/workspace, puis le moteur), `--db FICHIER` (défaut
<workspace>/.arc/coach.db), `--memory` (base en mémoire, rien sur disque),
`--today AAAA-MM-JJ` (date de fin des séries, pour des sorties reproductibles).

Chaîne de lecture par fichier : bloc ```arc valide → format canonique hérité
(YAML + splits) → puces → rien. Seul le premier étage donne `parsed_ok = ok`.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_contract as C  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_samples as S  # noqa: E402
from coach_config import ConfigError, read_toml  # noqa: E402
from coach_setup import ENGINE, workspace_root  # noqa: E402

SCHEMA_VERSION = 8   # #42 : `activity_sample.source_path` (purge par fichier) + index par activity_id
DEFAULT_DB = ".arc/coach.db"
DATA_DIRS = ("activities", "medical", "nutrition", "planning", "rapports")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(workspace: Path) -> Dict[str, dict]:
    """workspace.toml puis workspace.user.toml, clé par clé (même règle que config.sh).

    Sans `config/workspace.toml` dans le workspace (installation incomplète),
    les défauts du moteur s'appliquent.
    """
    shared = workspace / "config/workspace.toml"
    if not shared.exists():
        shared = ENGINE / "config/workspace.toml"
    merged: Dict[str, dict] = {}
    for path in (shared, workspace / "config/workspace.user.toml"):
        for section, values in read_toml(path).items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
    return merged


def _heat_threshold_c(config: Dict[str, dict]) -> float:
    """Résout `[health].heat_threshold_c`, jamais en levant : un typo dans
    `workspace.user.toml` (ex. `heat_threshold_c = "chaud"`) ne doit PAS casser
    `index_workspace` — appelé par CHAQUE commande (`index`, `hrv-baseline`,
    `sleep-debt`, `heat-acclimation`, et le rafraîchissement du tableau de bord).

    Accepte un nombre, ou une chaîne numérique (le repli TOML < 3.11,
    `coach_config._read_toml_fallback`, ne reconnaît que les entiers et rend les
    flottants sous forme de chaîne — `"25.0"` doit donc rester valide). Rejette
    explicitement les booléens (`True`/`False` sont aussi des `int` en Python :
    sans ce test, `heat_threshold_c = true` serait accepté comme 1.0 °C). Toute
    valeur absente, vide ou invalide retombe sur `M.HEAT_THRESHOLD_C_DEFAULT`,
    avec un avertissement sur stderr dans le cas invalide (pas pour une simple
    absence, qui est le cas normal sans override) — voir
    `arc_metrics.ASSUMPTIONS["heat_acclimation"]`.
    """
    raw = config.get("health", {}).get("heat_threshold_c")
    if raw in (None, ""):
        return M.HEAT_THRESHOLD_C_DEFAULT
    value = None
    if not isinstance(raw, bool):
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip().replace(",", "."))
            except ValueError:
                value = None
    if value is None:
        print(f"avertissement : [health].heat_threshold_c = {raw!r} n'est pas un nombre valide — "
              f"défaut {M.HEAT_THRESHOLD_C_DEFAULT:g} °C appliqué.", file=sys.stderr)
        return M.HEAT_THRESHOLD_C_DEFAULT
    return value


def settings(config: Dict[str, dict]) -> dict:
    """Les réglages qui changent ce que l'index attend et ce que le tableau affiche."""
    agents = config.get("agents", {}).get("enabled", ["coach", "medical", "nutritionist", "course-strategist"])
    return {
        "sport": config.get("sport", {}).get("primary", "trail") or "trail",
        "morning_check": config.get("health", {}).get("morning_check", "full") or "full",
        "heat_threshold_c": _heat_threshold_c(config),
        "agents": list(agents),
        "units": config.get("athlete", {}).get("units", "metric") or "metric",
        "profile": config.get("athlete", {}).get("profile", "planning/Runner_Profile.md"),
        "language": config.get("language", {}).get("documents", "fr") or "fr",
    }


# ---------------------------------------------------------------------------
# Schéma SQLite
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE source_file (
    path TEXT PRIMARY KEY, kind TEXT, sha256 TEXT, mtime REAL,
    arc_version INTEGER, parsed_ok TEXT, issues TEXT
);
CREATE TABLE athlete (
    source_path TEXT, name TEXT, hr_max_bpm INTEGER, hr_rest_bpm INTEGER,
    hr_threshold_bpm INTEGER, sex TEXT, weight_kg REAL, birth_year INTEGER,
    default_location TEXT, usual_slot TEXT, sleep_need_s REAL, body_md TEXT
);
CREATE TABLE gear (
    source_path TEXT, gear_id TEXT, name TEXT, start_date TEXT, threshold_m REAL,
    is_default INTEGER, retired INTEGER, collision_base TEXT
);
CREATE TABLE objective (
    source_path TEXT, name TEXT, race_date TEXT, distance_m REAL, elevation_gain_m REAL,
    location TEXT, goal TEXT, target_time_s REAL, weekly_start_s REAL, weekly_start_m REAL,
    weekly_target_s REAL, weekly_target_m REAL, quality_per_week INTEGER,
    training_location TEXT, body_md TEXT
);
CREATE TABLE activity (
    id INTEGER PRIMARY KEY, source_path TEXT, arc_version INTEGER, date TEXT, sport TEXT,
    name TEXT, location TEXT, garmin_activity_id INTEGER, start_time TEXT,
    distance_m REAL, duration_s REAL, moving_duration_s REAL, elevation_gain_m REAL,
    elevation_loss_m REAL, avg_hr_bpm REAL, max_hr_bpm REAL, recovery_hr_bpm REAL,
    avg_cadence_spm REAL, calories_kcal REAL, te_aerobic REAL, te_anaerobic REAL, rpe REAL,
    load REAL, load_source TEXT, vo2max_est REAL, missing_reason TEXT,
    gear_id TEXT, carbs_g REAL, fluid_intake_ml REAL, weight_pre_kg REAL, weight_post_kg REAL,
    sweat_rate_l_h REAL, body_md TEXT, data_json TEXT
);
CREATE INDEX activity_date ON activity(date);
CREATE TABLE activity_split (
    activity_id INTEGER, km INTEGER, distance_m REAL, duration_s REAL, elev_gain_m REAL,
    elev_loss_m REAL, avg_hr_bpm REAL, max_hr_bpm REAL, max_speed_kmh REAL,
    cadence_spm REAL, label TEXT
);
CREATE TABLE health_day (
    source_path TEXT, arc_version INTEGER, date TEXT, morning_check TEXT,
    sleep_total_s REAL, sleep_deep_s REAL, sleep_light_s REAL, sleep_rem_s REAL,
    sleep_awake_s REAL, sleep_score REAL, sleep_start TEXT, sleep_end TEXT,
    hrv_overnight_ms REAL, hrv_baseline_low_ms REAL, hrv_baseline_high_ms REAL, hrv_status TEXT,
    hrv_personal_low_ms REAL, hrv_personal_high_ms REAL, hrv_personal_status TEXT,
    resting_hr_bpm REAL, readiness_score REAL, body_battery_high REAL, body_battery_low REAL,
    stress_avg REAL, weight_kg REAL, verdict TEXT, verdict_reason TEXT, body_md TEXT, data_json TEXT
);
CREATE INDEX health_date ON health_day(date);
CREATE TABLE weather_day (
    source_path TEXT, date TEXT, location TEXT, category TEXT, best_slot TEXT, slot_reason TEXT,
    temp_min_c REAL, temp_max_c REAL, feels_like_c REAL, wind_kmh REAL, gust_kmh REAL,
    precip_mm REAL, chance_of_rain_pct REAL, uv_index REAL, data_json TEXT
);
CREATE TABLE week (
    source_path TEXT, arc_version INTEGER, week_start TEXT, location TEXT, phase TEXT,
    target_duration_s REAL, target_distance_m REAL, target_elevation_m REAL, body_md TEXT
);
CREATE TABLE planned_session (
    source_path TEXT, week_start TEXT, date TEXT, sport TEXT, title TEXT,
    planned_duration_s REAL, planned_distance_m REAL, planned_elevation_m REAL,
    intensity TEXT, outdoor INTEGER, garmin_workout_id INTEGER, status TEXT,
    weather_category TEXT, best_slot TEXT
);
CREATE TABLE nutrition_day (
    source_path TEXT, date TEXT, intake_kcal REAL, carbs_g REAL, protein_g REAL, fat_g REAL,
    hydration_ml REAL, burned_kcal REAL, weight_kg REAL, target_weight_kg REAL, body_md TEXT
);
CREATE TABLE report (
    source_path TEXT, date TEXT, report_type TEXT, title TEXT, period_start TEXT,
    period_end TEXT, location TEXT, body_md TEXT
);
CREATE TABLE course_eval (
    source_path TEXT, date TEXT, name TEXT, distance_m REAL, elevation_gain_m REAL,
    verdict TEXT, body_md TEXT, data_json TEXT
);
CREATE TABLE race_plan (
    source_path TEXT, date TEXT, race_name TEXT, race_date TEXT, distance_m REAL,
    elevation_gain_m REAL, target_time_s REAL, body_md TEXT, data_json TEXT
);
CREATE TABLE aid_station (source_path TEXT, km REAL, name TEXT, cutoff TEXT, services TEXT);
CREATE TABLE metric_day (
    date TEXT PRIMARY KEY, load REAL, fitness REAL, fatigue REAL, form REAL, acwr REAL,
    monotony REAL, strain REAL, vo2max REAL
);
-- Échantillons FIT sous-échantillonnés (#42) : source_path permet de purger les lignes
-- d'un fichier `activities/fit/<id>.json` modifié ou supprimé, comme les autres tables
-- par fichier. lat/lon restent NULL : aucune source actuelle n'en fournit (voir
-- arc_samples.py) — présentes pour un usage futur, pas remplies par cette histoire.
CREATE TABLE activity_sample (
    activity_id INTEGER, source_path TEXT, t_s REAL, distance_m REAL, altitude_m REAL,
    hr_bpm REAL, speed_ms REAL, cadence_spm REAL, lat REAL, lon REAL
);
CREATE INDEX activity_sample_activity ON activity_sample(activity_id);
CREATE INDEX activity_sample_source ON activity_sample(source_path);
-- Lot 3 (zones FC, #43) : table prévue, vide tant que cette histoire n'existe pas.
CREATE TABLE hr_zone_time (activity_id INTEGER, zone INTEGER, seconds REAL);
CREATE INDEX hr_zone_time_activity ON hr_zone_time(activity_id);
"""

# Tables alimentées par fichier (colonne `source_path`) : purgées à la réindexation d'un fichier.
PER_FILE_TABLES = (
    "athlete", "objective", "health_day", "weather_day", "week", "planned_session",
    "nutrition_day", "report", "course_eval", "race_plan", "aid_station", "gear",
)


def open_db(workspace: Path, db: Optional[str] = None, memory: bool = False,
            rebuild: bool = False) -> sqlite3.Connection:
    if memory:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        path = Path(db) if db else workspace / DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        if not db:
            # Le dossier s'ignore lui-même : même dans un workspace dont le .gitignore
            # n'a jamais été complété, `git add -A` (git_autocommit) n'embarque pas la base.
            marker = path.parent / ".gitignore"
            if not marker.exists():
                marker.write_text("# Index dérivé du tableau de bord : jetable, jamais versionné.\n*\n", encoding="utf-8")
        # Le tableau de bord et la synchronisation peuvent indexer en même temps :
        # on attend le verrou plutôt que d'échouer.
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    current = None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = int(row[0]) if row else None
    except sqlite3.DatabaseError:
        current = None
    # --rebuild vide les tables sur place au lieu de supprimer le fichier : un serveur
    # déjà ouvert sur la base garderait sinon une connexion vers un fichier disparu.
    if rebuild or current != SCHEMA_VERSION:
        # Base d'une autre version (ou vide) : elle est dérivée, on la recrée.
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.executescript(DDL)
        conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Découverte et lecture des fichiers
# ---------------------------------------------------------------------------


def classify(rel: str) -> Optional[str]:
    """Type attendu d'après le chemin (None : fichier hors contrat, sauf bloc ```arc)."""
    parts = rel.split("/")
    folder, name = parts[0], parts[-1]
    if folder == "activities" and L.filename_date(name) and L.sport_from_filename(name):
        # `2026-08-21_strides_analysis.md` est une analyse, pas une séance : seul un
        # type de sport connu après la date fait un fichier d'activité.
        return "activity"
    if folder == "medical" and name.endswith("_health.md"):
        return "health"
    if folder == "medical" and name.endswith("_meteo.md"):
        return "weather"
    if folder == "nutrition" and name.endswith("_nutrition.md"):
        return "nutrition"
    if folder == "rapports" and name.endswith(".md"):
        return "report"
    if folder == "planning":
        if name == "Runner_Profile.md":
            return "athlete"
        if name == "active_objective.md":
            return "objective"
        if name.startswith("Semaine_"):
            return "week"
        if "_evaluation_parcours_" in name:
            return "course_eval"
    return None


def discover(workspace: Path) -> List[Path]:
    files = []
    for folder in DATA_DIRS:
        root = workspace / folder
        if root.is_dir():
            files.extend(p for p in sorted(root.rglob("*.md")) if p.is_file())
    return files


def expected_keys(kind: str, data: dict, conf: dict) -> List[str]:
    """Clés dont l'absence est une dette (au-delà des clés obligatoires du contrat)."""
    if kind == "activity":
        sport = data.get("sport")
        keys = ["garmin_activity_id"]
        if sport not in ("strength", "rest", "home_trainer", "indoor_cycling", "elliptical"):
            keys.append("distance_m")
        if sport != "rest":
            keys.append("avg_hr_bpm")
        if sport in M.RUNNING_SPORTS:
            keys.append("splits")
        return keys
    if kind == "health":
        mode = data.get("morning_check") or conf["morning_check"]
        return {
            "full": ["sleep_total_s", "hrv_overnight_ms", "resting_hr_bpm", "readiness_score", "verdict"],
            "minimal": ["readiness_score", "verdict"],
        }.get(mode, [])
    if kind == "weather":
        return ["best_slot"]
    return []


def read_file(path: Path, rel: str, conf: dict) -> Tuple[Optional[str], dict, int, str, List[str]]:
    """Rend (kind, données, arc_version, parsed_ok, problèmes)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    kind = classify(rel)
    issues: List[str] = []

    if kind in ("athlete", "objective"):          # fichiers humains : puces du modèle
        data = L.parse_profile(text) if kind == "athlete" else L.parse_objective(text)
        data["body_md"] = text
        return kind, data, 0, "ok" if data else "partial", issues

    block_error = None
    try:
        block = C.extract_block(text)
    except C.ContractError as exc:
        block, block_error = None, str(exc)

    if block is not None:
        errors, warnings = C.validate(block)
        block_kind = block.get("kind")
        if block_kind in C.KINDS:
            if kind and block_kind != kind:
                issues.append(f"kind « {block_kind} » dans un fichier attendu « {kind} »")
            kind = block_kind
        issues.extend(warnings)
        if not errors:
            data = dict(block)
            data["body_md"] = C.body_after_block(text)
            missing = [k for k in expected_keys(kind, data, conf) if data.get(k) is None]
            issues.extend(f"{k} : absent" for k in missing)
            return kind, data, 1, "ok", issues
        issues = errors + issues
        status = "invalid"
    else:
        if kind is None:
            return None, {}, 0, "no", []
        issues.append(block_error or "bloc ```arc absent")
        status = "partial"

    # Repli : lecture héritée.
    name = path.name
    if kind == "activity":
        data = L.legacy_activity(text, name, conf["sport"])
    elif kind == "health":
        data = L.legacy_health(text, name, conf["morning_check"])
    elif kind == "weather":
        data = L.legacy_weather(text, name)
    elif kind == "week":
        data = L.legacy_week(text, name, conf["sport"])
    elif kind == "nutrition":
        data = L.legacy_nutrition(text, name)
    elif kind == "report":
        data = L.legacy_report(text, name)
    elif kind == "course_eval":
        data = {"kind": "course_eval", "date": L.filename_date(name), "name": L.title_of(text) or name}
    else:
        data = {}
    data["body_md"] = text
    required = C.SCHEMA.get(kind, {}).get("required", {})
    missing = [k for k in list(required) + expected_keys(kind, data, conf) if data.get(k) in (None, [], "")]
    issues.extend(f"{k} : absent" for k in dict.fromkeys(missing))
    if kind == "activity":
        # « Aucune activité enregistrée ce jour » ne doit pas devenir une séance vide.
        usable = data.get("duration_s") is not None or data.get("distance_m") is not None
    else:
        usable = any(data.get(k) is not None for k in required if k != "date") or kind in ("report", "course_eval")
    if "date" in required and not data.get("date"):
        usable = False                      # `2026-04-11b_health.md` : sans date sûre, rien à tracer
        issues.append("date introuvable (nom de fichier non conforme)")
    if status == "partial" and not usable:
        status = "no"
    return kind, data, 0, status, issues


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------


def _j(value) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _insert(conn, table: str, row: dict) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values())).lastrowid


def _purge(conn, rel: str) -> None:
    for (activity_id,) in conn.execute("SELECT id FROM activity WHERE source_path = ?", (rel,)).fetchall():
        conn.execute("DELETE FROM activity_split WHERE activity_id = ?", (activity_id,))
    conn.execute("DELETE FROM activity WHERE source_path = ?", (rel,))
    for table in PER_FILE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE source_path = ?", (rel,))


def _data_json(data: dict) -> str:
    return _j({k: v for k, v in data.items() if k != "body_md"})


def store(conn, rel: str, kind: str, data: dict, arc_version: int) -> None:
    body = data.get("body_md")
    g = data.get
    if kind == "athlete":
        _insert(conn, "athlete", {
            "source_path": rel, "name": g("name"), "hr_max_bpm": g("hr_max_bpm"),
            "hr_rest_bpm": g("hr_rest_bpm"), "hr_threshold_bpm": g("hr_threshold_bpm"),
            "sex": g("sex"), "weight_kg": g("weight_kg"), "birth_year": g("birth_year"),
            "default_location": g("default_location"), "usual_slot": g("usual_slot"),
            "sleep_need_s": g("sleep_need_s"), "body_md": body,
        })
        for shoe in g("gear") or []:
            if not isinstance(shoe, dict) or not shoe.get("gear_id"):
                continue
            _insert(conn, "gear", {
                "source_path": rel, "gear_id": shoe["gear_id"], "name": shoe.get("name"),
                "start_date": shoe.get("start_date"), "threshold_m": shoe.get("threshold_m"),
                "is_default": int(bool(shoe.get("default"))), "retired": int(bool(shoe.get("retired"))),
                "collision_base": shoe.get("collision_base"),
            })
    elif kind == "objective":
        row = {k: g(k) for k in (
            "name", "race_date", "distance_m", "elevation_gain_m", "location", "goal", "target_time_s",
            "weekly_start_s", "weekly_start_m", "weekly_target_s", "weekly_target_m",
            "quality_per_week", "training_location")}
        _insert(conn, "objective", {"source_path": rel, **row, "body_md": body})
    elif kind == "activity":
        activity_id = _insert(conn, "activity", {
            "source_path": rel, "arc_version": arc_version, "date": g("date"), "sport": g("sport"),
            "name": g("name"), "location": g("location"), "garmin_activity_id": g("garmin_activity_id"),
            "start_time": g("start_time"), "distance_m": g("distance_m"), "duration_s": g("duration_s"),
            "moving_duration_s": g("moving_duration_s"), "elevation_gain_m": g("elevation_gain_m"),
            "elevation_loss_m": g("elevation_loss_m"), "avg_hr_bpm": g("avg_hr_bpm"),
            "max_hr_bpm": g("max_hr_bpm"), "recovery_hr_bpm": g("recovery_hr_bpm"),
            "avg_cadence_spm": g("avg_cadence_spm"), "calories_kcal": g("calories_kcal"),
            "te_aerobic": g("training_effect_aerobic"), "te_anaerobic": g("training_effect_anaerobic"),
            "rpe": g("rpe"), "missing_reason": _j(g("missing_reason")),
            "gear_id": g("gear_id"), "carbs_g": g("carbs_g"), "fluid_intake_ml": g("fluid_intake_ml"),
            "weight_pre_kg": g("weight_pre_kg"), "weight_post_kg": g("weight_post_kg"),
            "body_md": body,
            "data_json": _data_json(data),
        })
        for split in C.split_rows(data):
            _insert(conn, "activity_split", {
                "activity_id": activity_id,
                **{col: split.get(col) for col in C.SPLIT_COLUMNS},
            })
    elif kind == "health":
        cols = [k for k in C.SCHEMA["health"]["optional"] if k not in ("readiness_factors", "missing_reason")]
        _insert(conn, "health_day", {
            "source_path": rel, "arc_version": arc_version, "date": g("date"),
            "morning_check": g("morning_check"), **{k: g(k) for k in cols},
            "body_md": body, "data_json": _data_json(data),
        })
    elif kind == "weather":
        _insert(conn, "weather_day", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "location", "category", "best_slot", "slot_reason", "temp_min_c", "temp_max_c",
                "feels_like_c", "wind_kmh", "gust_kmh", "precip_mm", "chance_of_rain_pct", "uv_index")},
            "data_json": _data_json(data),
        })
    elif kind == "week":
        _insert(conn, "week", {
            "source_path": rel, "arc_version": arc_version, "week_start": g("week_start"),
            "location": g("location"), "phase": g("phase"), "target_duration_s": g("target_duration_s"),
            "target_distance_m": g("target_distance_m"), "target_elevation_m": g("target_elevation_m"),
            "body_md": body,
        })
        for s in g("sessions") or []:
            if not isinstance(s, dict):
                continue
            _insert(conn, "planned_session", {
                "source_path": rel, "week_start": g("week_start"),
                **{k: s.get(k) for k in (
                    "date", "sport", "title", "planned_duration_s", "planned_distance_m",
                    "planned_elevation_m", "intensity", "garmin_workout_id", "status",
                    "weather_category", "best_slot")},
                "outdoor": None if s.get("outdoor") is None else int(bool(s["outdoor"])),
            })
    elif kind == "nutrition":
        _insert(conn, "nutrition_day", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "intake_kcal", "carbs_g", "protein_g", "fat_g", "hydration_ml",
                "burned_kcal", "weight_kg", "target_weight_kg")},
            "body_md": body,
        })
    elif kind == "report":
        _insert(conn, "report", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "report_type", "title", "period_start", "period_end", "location")},
            "body_md": body,
        })
    elif kind == "course_eval":
        _insert(conn, "course_eval", {
            "source_path": rel, "date": g("date"), "name": g("name"), "distance_m": g("distance_m"),
            "elevation_gain_m": g("elevation_gain_m"), "verdict": g("verdict"), "body_md": body,
            "data_json": _data_json(data),
        })
    elif kind == "race_plan":
        _insert(conn, "race_plan", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "race_name", "race_date", "distance_m", "elevation_gain_m", "target_time_s")},
            "body_md": body, "data_json": _data_json(data),
        })
        for station in g("aid_stations") or []:
            if isinstance(station, dict):
                _insert(conn, "aid_station", {
                    "source_path": rel, "km": station.get("km"), "name": station.get("name"),
                    "cutoff": station.get("cutoff"), "services": _j(station.get("services")),
                })


def compute_metrics(conn, conf: dict, today: Optional[str] = None) -> None:
    """Charge par séance, VO2max par séance, puis la série quotidienne matérialisée."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete) if athlete else {}
    loads: Dict[str, float] = {}
    estimates = []
    rows = conn.execute("SELECT * FROM activity ORDER BY date").fetchall()
    for row in rows:
        act = dict(row)
        load, source = M.session_load(act, athlete)
        vo2 = M.vo2max_effective(act, athlete)
        sweat_rate = M.sweat_rate_l_h(act)
        conn.execute("UPDATE activity SET load = ?, load_source = ?, vo2max_est = ?, sweat_rate_l_h = ? WHERE id = ?",
                     (round(load, 2), source, vo2, sweat_rate, act["id"]))
        if act.get("date"):
            loads[act["date"]] = loads.get(act["date"], 0.0) + load
            if vo2 is not None:
                estimates.append((act["date"], vo2, act.get("duration_s") or 0))
    conn.execute("DELETE FROM metric_day")
    dated = sorted(loads)
    if dated:
        start = date.fromisoformat(dated[0])
        end = max(date.fromisoformat(dated[-1]), date.fromisoformat(today) if today else date.today())
        for point in M.daily_series(loads, start, end):
            point["vo2max"] = M.vo2max_trend(estimates, point["date"])
            _insert(conn, "metric_day", point)


# ---------------------------------------------------------------------------
# Échantillons FIT (#42) — ingestion incrémentale, idempotente
# ---------------------------------------------------------------------------


def discover_sample_files(workspace: Path) -> List[Path]:
    root = workspace / "activities" / "fit"
    return sorted(p for p in root.glob("*.json") if p.is_file()) if root.is_dir() else []


def _sample_file_activity_id(path: Path, raw) -> Optional[int]:
    """`garmin_activity_id` d'un fichier `activities/fit/*.json` : le nom du fichier
    (chemin canonique) prime, avec repli sur la clé `activity_id` du JSON pour un
    fichier renommé ou déposé à la main."""
    from_name = S.sample_file_activity_id(path)
    if from_name is not None:
        return from_name
    if isinstance(raw, dict) and raw.get("activity_id") is not None:
        try:
            return int(raw["activity_id"])
        except (TypeError, ValueError):
            return None
    return None


def ingest_samples(conn, workspace: Path, resolution_s: int = S.DEFAULT_RESOLUTION_S) -> dict:
    """Ingestion incrémentale et idempotente des échantillons FIT (`activities/fit/*.json`)
    dans `activity_sample`. Même discipline que `index_workspace` pour les fichiers
    Markdown : chaque fichier est suivi dans `source_file` (kind `fit_sample`) par son
    sha256 — inchangé → sauté, modifié → repurgé puis réingéré, disparu → ses lignes
    `activity_sample` retirées. Deux ingestions successives sans changement de fichier
    produisent donc des lignes identiques (idempotence).

    Un fichier dont le `garmin_activity_id` ne correspond à aucune activité déjà indexée
    est compté à part (`orphan`) : rien n'est écrit dans `activity_sample`, et **rien ne
    casse** côté séance — c'est le cas normal d'un FIT téléchargé avant que le Markdown
    de la séance n'existe encore, ou d'un `garmin_activity_id` qui a changé.

    **Budget de taille** (documenté ici, pas ailleurs, pour rester à côté du code qui le
    détermine) : à la résolution par défaut (5 s), une sortie d'1 h ≈ 720 lignes. Pour
    ~300 séances/an d'1 h en moyenne (un volume plausible de coureur régulier, cf.
    `tests/lib/synthetic.py`), ≈ 216 000 lignes — quelques dizaines de Mo dans SQLite
    (l'ordre de grandeur usuel est de 50 à 100 octets/ligne avec l'overhead SQLite pour 6
    colonnes REAL + 2 INTEGER/TEXT), largement absorbable par le fichier `.arc/coach.db`
    déjà jetable et reconstruit à la demande. L'index sur `activity_id` (DDL ci-dessus)
    garde `arc_serve.samples`-like les requêtes par séance en O(log n) plutôt qu'un scan
    complet de la table à mesure qu'elle grossit.
    """
    counts = {"ingested": 0, "unchanged": 0, "removed": 0, "orphan": 0}
    seen = set()
    for path in discover_sample_files(workspace):
        rel = path.relative_to(workspace).as_posix()
        seen.add(rel)
        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        known = conn.execute("SELECT sha256 FROM source_file WHERE path = ?", (rel,)).fetchone()
        if known and known[0] == digest:
            counts["unchanged"] += 1
            continue
        conn.execute("DELETE FROM activity_sample WHERE source_path = ?", (rel,))
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            conn.execute(
                "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rel, "fit_sample", digest, path.stat().st_mtime, 0, "invalid", _j(["JSON illisible"])),
            )
            counts["ingested"] += 1
            continue
        garmin_id = _sample_file_activity_id(path, raw)
        activity_row = (
            conn.execute("SELECT id FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()
            if garmin_id is not None else None
        )
        if activity_row is None:
            parsed_ok = "orphan"
            counts["orphan"] += 1
        else:
            parsed_ok = "ok"
            records = S.downsample(S.normalise_records(raw), resolution_s)
            for rec in records:
                conn.execute(
                    "INSERT INTO activity_sample "
                    "(activity_id, source_path, t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (activity_row["id"], rel, rec["t_s"], rec["distance_m"], rec["altitude_m"],
                     rec["hr_bpm"], rec["speed_ms"], rec["cadence_spm"]),
                )
        conn.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel, "fit_sample", digest, path.stat().st_mtime, 0, parsed_ok,
             _j([] if parsed_ok == "ok" else [f"garmin_activity_id {garmin_id} : aucune activité indexée"])),
        )
        counts["ingested"] += 1
    for (rel,) in conn.execute("SELECT path FROM source_file WHERE kind = 'fit_sample'").fetchall():
        if rel not in seen:
            conn.execute("DELETE FROM activity_sample WHERE source_path = ?", (rel,))
            conn.execute("DELETE FROM source_file WHERE path = ?", (rel,))
            counts["removed"] += 1
    conn.commit()
    return counts


def samples(conn, activity_id: int) -> List[dict]:
    """Échantillons sous-échantillonnés d'une séance (id INTERNE de `activity`, pas le
    `garmin_activity_id`), triés par `t_s`. Pure lecture, jamais d'exception : une
    séance sans FIT ingéré rend `[]` — les KPI dérivés (zones #43, GAP #44, découplage
    #45, VAM #46, descente #47, durabilité #48, modèle pente→allure #58) peuvent tous
    tester `if not samples: ...` sans se soucier de l'existence du FIT.
    """
    rows = conn.execute(
        "SELECT t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm "
        "FROM activity_sample WHERE activity_id = ? ORDER BY t_s", (activity_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def samples_by_garmin_id(conn, garmin_activity_id: int) -> dict:
    """Enveloppe JSON-amie de `samples()`, par `garmin_activity_id` (identifiant externe,
    celui du nom de fichier `activities/fit/<id>.json` et du CLI `arc_index.py samples`).
    """
    row = conn.execute("SELECT id FROM activity WHERE garmin_activity_id = ?", (garmin_activity_id,)).fetchone()
    if row is None:
        return {"garmin_activity_id": garmin_activity_id, "samples": [],
                "reason": "aucune activité indexée avec cet identifiant Garmin"}
    return {"garmin_activity_id": garmin_activity_id, "samples": samples(conn, row["id"])}


def index_workspace(conn, workspace: Path, today: Optional[str] = None) -> dict:
    """Indexe (incrémental) puis recalcule les métriques. Rend un résumé."""
    conf = settings(load_config(workspace))
    seen = set()
    counts = {"indexed": 0, "unchanged": 0, "removed": 0}
    for path in discover(workspace):
        rel = path.relative_to(workspace).as_posix()
        seen.add(rel)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        known = conn.execute("SELECT sha256 FROM source_file WHERE path = ?", (rel,)).fetchone()
        if known and known[0] == digest:
            counts["unchanged"] += 1
            continue
        _purge(conn, rel)
        kind, data, arc_version, parsed_ok, issues = read_file(path, rel, conf)
        twin = None
        if kind == "activity" and data.get("garmin_activity_id"):
            twin = conn.execute("SELECT source_path FROM activity WHERE garmin_activity_id = ? AND source_path != ?",
                                (data["garmin_activity_id"], rel)).fetchone()
        if twin:
            # Même séance Garmin décrite dans deux fichiers : une seule charge. Le fichier
            # écarté est relu à chaque passe (sha vide) pour reprendre la main si l'autre disparaît.
            issues.append(f"doublon de {twin[0]} (même garmin_activity_id) : non compté")
            digest = ""
        elif kind is not None and parsed_ok != "no":
            store(conn, rel, kind, data, arc_version)
        conn.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel, kind, digest, path.stat().st_mtime, arc_version, parsed_ok, _j(issues)),
        )
        counts["indexed"] += 1
    # kind != 'fit_sample' : ce nettoyage porte sur les fichiers Markdown découverts par
    # `discover()` ci-dessus — les échantillons FIT (`activities/fit/*.json`) ont leur
    # propre découverte et leur propre nettoyage dans `ingest_samples`, plus bas. Sans ce
    # filtre, chaque passe purgerait puis réingérerait les échantillons en boucle (leur
    # chemin n'est jamais dans `seen`, rempli uniquement par `discover()`).
    for (rel,) in conn.execute("SELECT path FROM source_file WHERE kind IS NULL OR kind != 'fit_sample'").fetchall():
        if rel not in seen:
            _purge(conn, rel)
            conn.execute("DELETE FROM source_file WHERE path = ?", (rel,))
            counts["removed"] += 1
    # Échantillons FIT (#42) : APRÈS le passage Markdown ci-dessus, pour que les activités
    # tout juste indexées soient déjà en base au moment de résoudre garmin_activity_id.
    # Clé distincte de `samples` (coverage globale, calculée par la commande `status`) :
    # celle-ci ne compte que les fichiers TOUCHÉS par CETTE passe d'indexation.
    counts["fit_ingestion"] = ingest_samples(conn, workspace)
    compute_metrics(conn, conf, today)
    for key, value in (("settings", _j(conf)), ("assumptions", _j(M.ASSUMPTIONS)),
                       ("today", today or date.today().isoformat())):
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    conn.commit()
    return counts


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill_items(conn) -> List[dict]:
    """Fichiers qui ne sont pas au contrat, ou incomplets, et ce qui leur manque.

    L'attendu tient compte de la configuration : en `morning_check = "off"`, un
    fichier santé sans HRV n'est pas une dette (expected_keys ne demande rien) ;
    un workspace sans nutritionniste n'a pas de `nutrition/` à remplir.
    """
    items = []
    for row in conn.execute(
        "SELECT path, kind, parsed_ok, issues FROM source_file "
        "WHERE kind IS NOT NULL AND kind NOT IN ('athlete', 'objective') "
        "AND parsed_ok != 'ok' ORDER BY path"
    ).fetchall():
        # Seul un fichier hors contrat (sans bloc, bloc invalide, illisible) est une dette.
        # Une clé facultative absente d'un bloc valide (pas de verdict ce jour-là, pas de
        # splits sur une séance de renfo) reste visible dans `issues`, sans être à reprendre.
        issues = json.loads(row["issues"] or "[]")
        items.append({"path": row["path"], "kind": row["kind"], "status": row["parsed_ok"], "issues": issues})
    return items


def write_backfill(conn, workspace: Path) -> Path:
    items = backfill_items(conn)
    lines = [
        "# Backfill — fichiers à réécrire au contrat ```arc",
        "",
        "> Généré par `scripts/arc_index.py backfill-plan`. Ne pas éditer : relancer la commande.",
        "> Chaque fichier doit être réécrit avec un bloc ```arc conforme au skill",
        "> `workspace-data-contract`, en conservant le texte existant sous le bloc.",
        "",
        f"**{len(items)} fichier(s)** à traiter.",
        "",
    ]
    for item in items:
        lines.append(f"- [ ] `{item['path']}` — {item['kind']} ({item['status']})")
        for issue in item["issues"]:
            lines.append(f"    - {issue}")
    out = workspace / ".arc/backfill.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Validation d'un fichier (appelée par les agents après chaque écriture)
# ---------------------------------------------------------------------------


def validate_file(path: Path) -> Tuple[bool, List[str], List[str]]:
    if not path.is_file():
        return False, [f"{path} : fichier introuvable"], []
    if path.name in ("Runner_Profile.md", "active_objective.md"):
        return True, [], ["fichier édité par l'humain : pas de bloc ```arc attendu (puces du modèle)"]
    try:
        block = C.extract_block(path.read_text(encoding="utf-8"))
    except C.ContractError as exc:
        return False, [str(exc)], []
    if block is None:
        return False, ["bloc ```arc absent — voir le skill workspace-data-contract"], []
    errors, warnings = C.validate(block)
    expected = classify(f"{path.parent.name}/{path.name}")
    if expected and block.get("kind") in C.KINDS and block.get("kind") != expected:
        warnings.append(f"kind « {block.get('kind')} » inattendu pour ce fichier (« {expected} » attendu)")
    return not errors, errors, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def hrv_baseline_today(conn, conf: dict, today: date) -> dict:
    """Point du jour de la ligne de base HRV personnelle (#34) — pour la CLI et pour les
    agents en headless (`/garmin-daily-sync`, ou tout appel sans tableau de bord lancé).

    Respecte `[health].morning_check` : rien n'est calculé hors `"full"` (voir
    `arc_metrics.ASSUMPTIONS["hrv_baseline"]` — décision documentée : en `"minimal"`,
    seule la readiness est exposée ; en `"off"`, aucune donnée de santé n'est récupérée).
    """
    mode = conf["morning_check"]
    if mode != "full":
        return {"status": None, "morning_check": mode,
                "reason": "ligne de base personnelle calculée seulement en "
                          '[health].morning_check = "full"'}
    rows = conn.execute(
        "SELECT date, hrv_overnight_ms FROM health_day WHERE hrv_overnight_ms IS NOT NULL"
    ).fetchall()
    hrv_by_date = {row[0]: row[1] for row in rows}
    point = M.hrv_baseline_series(hrv_by_date, today, today)[0]
    return {**point, "morning_check": mode}


def athlete_sleep_need_s(row) -> float:
    """Résout le besoin de sommeil à partir d'une ligne `athlete` (dict-like portant
    `sleep_need_s` — `sqlite3.Row` ou `dict`, tous deux indexables par nom de colonne
    — ou `None`) : la valeur du profil si présente et non nulle, sinon le défaut
    moteur (`arc_metrics.SLEEP_NEED_DEFAULT_S`, 7 h 30).

    Point de résolution UNIQUE, partagé par la CLI `sleep-debt` ci-dessous et par
    `arc_serve.py` (`/api/summary`, `/api/health`) — revue de code PR #82 : trois
    copies de `(row["sleep_need_s"] if row else None) or DEFAULT` avaient dérivé.
    """
    value = row["sleep_need_s"] if row is not None else None
    return value or M.SLEEP_NEED_DEFAULT_S


def sleep_debt_today(conn, conf: dict, today: date) -> dict:
    """Dette de sommeil 7 j du jour (#37) — pour la CLI et pour les agents en headless.

    Respecte `[health].morning_check` : rien n'est calculé hors `"full"` (même porte
    que `hrv_baseline_today` — voir `arc_metrics.ASSUMPTIONS["sleep_debt"]`).
    """
    mode = conf["morning_check"]
    if mode != "full":
        return {"sleep_debt_7d_s": None, "nights_counted": None, "morning_check": mode,
                "reason": "dette de sommeil calculée seulement en "
                          '[health].morning_check = "full"'}
    rows = conn.execute(
        "SELECT date, sleep_total_s FROM health_day WHERE sleep_total_s IS NOT NULL"
    ).fetchall()
    sleep_by_date = {row[0]: row[1] for row in rows}
    athlete = conn.execute("SELECT sleep_need_s FROM athlete LIMIT 1").fetchone()
    need_s = athlete_sleep_need_s(athlete)
    result = M.sleep_debt_7d(sleep_by_date, today, need_s)
    return {**result, "morning_check": mode}


def heat_acclimation_today(conn, conf: dict, today: date) -> dict:
    """Acclimatation à la chaleur sur les 14 j se terminant à `today` (#38) — pour la
    CLI et pour les agents en headless (`coach`, `course-strategist` pour une course
    dont la météo prévue est chaude).

    Contrairement à `hrv_baseline_today`/`sleep_debt_today`, n'est pas soumis à
    `[health].morning_check` : la jointure activité/météo ne dépend pas du bilan
    matinal (voir `arc_metrics.ASSUMPTIONS["heat_acclimation"]`).
    """
    window_days = M.HEAT_WINDOW_DAYS
    start = (today - timedelta(days=window_days - 1)).isoformat()
    end = today.isoformat()
    activities = [dict(r) for r in conn.execute(
        "SELECT date, sport, duration_s, location FROM activity WHERE date >= ? AND date <= ?",
        (start, end)).fetchall()]
    weather_rows = [dict(r) for r in conn.execute(
        "SELECT date, location, temp_max_c FROM weather_day WHERE date >= ? AND date <= ?",
        (start, end)).fetchall()]
    return M.heat_acclimation(activities, weather_rows, today, conf["heat_threshold_c"], window_days)


def gear_mileage(conn) -> dict:
    """Kilométrage par chaussure (#40) — pour la CLI et pour les agents en headless
    (`coach`, rapport hebdomadaire). N'est pas soumis à `[health].morning_check` :
    ne dépend d'aucune donnée de santé, seulement du profil et des activités."""
    gear_defs = [dict(r) for r in conn.execute(
        "SELECT gear_id, name, start_date, threshold_m, is_default AS \"default\", retired, collision_base "
        "FROM gear")]
    activities = [dict(r) for r in conn.execute(
        # `date` : indispensable à `M.gear_mileage` pour filtrer l'attribution par
        # défaut par `depuis` (revue PR #85, blocker 1) — jamais utilisée pour
        # exclure une activité à `gear_id` explicite.
        "SELECT sport, distance_m, gear_id, date FROM activity WHERE gear_id IS NOT NULL OR sport IN "
        f"({', '.join('?' for _ in M.GEAR_WEAR_SPORTS)})", M.GEAR_WEAR_SPORTS).fetchall()]
    return M.gear_mileage(activities, gear_defs)


def fueling_trend(conn, today: date) -> dict:
    """Glucides/h et taux de sudation sur les sorties longues (#41) — pour la CLI
    (`arc_index.py fueling`) et pour `course-strategist` en headless (plafond
    réaliste d'un plan de course). N'est pas soumis à `[health].morning_check` :
    ne dépend d'aucune donnée de santé, seulement des activités déjà indexées.
    Voir `arc_metrics.ASSUMPTIONS["fueling"]`."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, distance_m, duration_s, carbs_g, sweat_rate_l_h FROM activity "
        "WHERE duration_s > ? AND sport IN "
        f"({', '.join('?' for _ in M.FUELING_SPORTS)})",
        (M.LONG_RUN_MIN_DURATION_S, *M.FUELING_SPORTS)).fetchall()]
    result = M.fueling_trend(rows, today)
    result["carbs_ceiling_g_h"] = M.fueling_carbs_ceiling(result["max_carbs_per_hour_g"])
    result["margin_g_h"] = M.FUELING_MAX_MARGIN_G_H
    result["target_band_g_h"] = list(M.FUELING_TARGET_BAND_G_H)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", default="index",
                        choices=("index", "backfill-plan", "status", "hrv-baseline", "sleep-debt",
                                 "heat-acclimation", "gear", "fueling", "samples"))
    parser.add_argument("selector", nargs="?", default=None,
                        help="argument de la sous-commande (ex. garmin_activity_id pour « samples »)")
    parser.add_argument("--workspace")
    parser.add_argument("--db")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--today", help="date de fin des séries (AAAA-MM-JJ)")
    parser.add_argument("--validate", nargs="+", metavar="FICHIER")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.today:
        try:
            date.fromisoformat(args.today)
        except ValueError:
            raise ConfigError(f"--today : date AAAA-MM-JJ attendue, « {args.today} » reçue.")

    if args.validate:
        all_ok = True
        for name in args.validate:
            ok, errors, warnings = validate_file(Path(name))
            all_ok &= ok
            print(f"{'ok' if ok else 'NON CONFORME'}: {name}")
            for line in errors:
                print(f"  erreur : {line}")
            for line in warnings:
                print(f"  attention : {line}")
        return 0 if all_ok else 1

    workspace = workspace_root(args.workspace)
    conn = open_db(workspace, args.db, args.memory, args.rebuild)
    counts = index_workspace(conn, workspace, args.today)
    if args.command == "hrv-baseline":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(hrv_baseline_today(conn, conf, today_date), ensure_ascii=False))
        return 0
    if args.command == "sleep-debt":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(sleep_debt_today(conn, conf, today_date), ensure_ascii=False))
        return 0
    if args.command == "heat-acclimation":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(heat_acclimation_today(conn, conf, today_date), ensure_ascii=False))
        return 0
    if args.command == "gear":
        print(json.dumps(gear_mileage(conn), ensure_ascii=False))
        return 0
    if args.command == "fueling":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(fueling_trend(conn, today_date), ensure_ascii=False))
        return 0
    if args.command == "backfill-plan":
        out = write_backfill(conn, workspace)
        print(f"{len(backfill_items(conn))} fichier(s) à reprendre — {out}")
        return 0
    if args.command == "samples":
        if not args.selector:
            raise ConfigError("commande « samples » : garmin_activity_id attendu "
                               "(ex. arc_index.py samples 19287537093).")
        try:
            garmin_id = int(args.selector)
        except ValueError:
            raise ConfigError(f"commande « samples » : entier attendu, « {args.selector} » reçu.")
        print(json.dumps(samples_by_garmin_id(conn, garmin_id), ensure_ascii=False))
        return 0
    if args.command == "status":
        by_status = {row[0]: row[1] for row in conn.execute(
            "SELECT parsed_ok, COUNT(*) FROM source_file WHERE kind IS NOT NULL GROUP BY parsed_ok")}
        sample_rows, activities_with_samples = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT activity_id) FROM activity_sample").fetchone()
        print(json.dumps({
            "workspace": str(workspace), **counts, "files": by_status,
            "samples": {"rows": sample_rows, "activities_with_samples": activities_with_samples},
        }, ensure_ascii=False))
        return 0
    print(f"index : {counts['indexed']} lu(s), {counts['unchanged']} inchangé(s), "
          f"{counts['removed']} retiré(s) — {workspace / DEFAULT_DB if not args.memory and not args.db else args.db or ':memory:'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(1)
