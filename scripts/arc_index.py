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
    arc_index.py zones [--activity GARMIN_ID] [--weeks N]   # zones FC, temps en zone, polarisation (#43)
    arc_index.py gap --activity GARMIN_ID                   # allure ajustée à la pente, globale + par split (#44)
    arc_index.py decoupling [--activity GARMIN_ID] [--weeks N]   # découplage aérobie (Pa:HR), EF (#45)
    arc_index.py vam [--activity GARMIN_ID] [--weeks N]           # VAM sur les montées détectées (#46)
    arc_index.py descent [--activity GARMIN_ID] [--weeks N]        # efficacité en descente par classe de pente (#47)
    arc_index.py durability [--activity GARMIN_ID] [--weeks N]      # fade GAP/EF sur les sorties longues (#48)
    arc_index.py climb-history [--segment ID | --activity GARMIN_ID]  # identité de montée entre séances (#49)

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

`zones` (#43) rend les bornes de zones FC effectives (méthode par précédence, voir
`arc_metrics.hr_zone_resolution` — toujours une `reason` explicite quand aucune
zone n'est calculable, jamais un échec muet) et, selon les options :
`--activity GARMIN_ID` le temps en zone d'une séance précise ; `--weeks N` (défaut 8)
la polarisation 80/20 hebdomadaire des N dernières semaines. Restreint aux sports de
la famille course à pied (`arc_metrics.sport_family` = « run » : course, trail,
randonnée, marche — pas le renforcement ni le vélo). Tables dérivées `hr_zone_time`
(5 zones affichées) et `hr_polarisation_time` (bornes Seiler DÉDIÉES par méthode,
jamais un regroupement des 5 zones) recalculées en entier à chaque passage de
`index_workspace` (voir `compute_metrics`) : un changement de profil (FC max/repos/
seuil) ou de `[athlete].hr_zones` est répercuté sans étape à part. Voir
`arc_metrics.ASSUMPTIONS["hr_zones"]`.

`gap` (#44) rend l'allure ajustée à la pente (« GAP », coût énergétique de
Minetti et al. 2002 — voir `arc_gap.py`) d'une séance : allure globale et par
split, `--activity GARMIN_ID` obligatoire (ou en argument positionnel).
`activity.gap_pace_s_km` et `activity_split.gap_pace_s_km` sont recalculées en
entier à chaque passage de `index_workspace` (même discipline que les tables
zones/polarisation ci-dessus), restreintes à la famille course à pied avec des
échantillons FIT ingérés — voir `arc_gap.ASSUMPTIONS`.

`decoupling` (#45) rend, sans `--activity`, la tendance du découplage aérobie
(Pa:HR) et du facteur d'efficacité (EF) sur les sorties longues (course à pied,
`duration_s` > `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) des `--weeks`
dernières semaines glissantes (défaut 12) ; avec `--activity GARMIN_ID`, le
détail d'une séance (`decoupling_pct`, `ef_whole`, `reason` explicite si non
calculable). `activity.decoupling_pct`/`ef_whole`/`decoupling_reason` sont
recalculées en entier à chaque passage de `index_workspace` (même discipline
que GAP/#44 et zones/#43), restreintes à la famille course à pied avec des
échantillons FIT ingérés — voir `arc_decoupling.ASSUMPTIONS`.

`vam` (#46) rend, avec `--activity GARMIN_ID`, le détail des montées détectées
d'une séance (bornes, gain, pente, VAM temps écoulé/temps de mouvement, classe
de pente, meilleure VAM 10/20 min) ; sans `--activity`, la tendance sur les
`--weeks` dernières semaines glissantes (défaut 12, AUCUN seuil de durée
minimale contrairement à `decoupling` — une montée peut être détectée sur une
sortie courte). La table `activity_climb` et les colonnes
`activity.best_vam_10min_m_h`/`best_vam_20min_m_h`/`best_climb_vam_elapsed_m_h`
sont recalculées en entier à chaque passage de `index_workspace` (même
discipline que GAP/#44 et découplage/#45), restreintes à la famille course à
pied (course, trail, randonnée, marche) avec des échantillons FIT ingérés —
voir `arc_climb.ASSUMPTIONS`. Seuils de détection configurables :
`[metrics].climb_min_gain_m`/`climb_min_grade_pct` (défauts 50 m / 5 %, voir
`config/workspace.toml`), résolus par `settings()` — critère d'acceptation de
#46 (« montée minimale configurable »).

`descent` (#47) rend, avec `--activity GARMIN_ID`, le détail d'efficacité en descente
d'une séance par classe de pente (vitesse/allure moyenne, allure GAP de référence de
la séance, indicateur d'efficacité — voir `arc_descent.ASSUMPTIONS["indicator"]`) ;
sans `--activity`, la tendance sur les `--weeks` dernières semaines glissantes
(défaut 12, comme `vam`). La table `activity_descent_class` est recalculée en entier
à chaque passage de `index_workspace` (même discipline que GAP/#44, découplage/#45
et VAM/#46), restreinte à la famille course à pied avec des échantillons FIT ingérés
— voir `arc_descent.ASSUMPTIONS`.

`durability` (#48) rend, avec `--activity GARMIN_ID`, le détail de durabilité d'une
séance (fade GAP et fade EF entre le premier et le dernier tiers de mouvement
post-échauffement, FC par tiers, `reason`/`reason_code` explicites — voir
`arc_durability.ASSUMPTIONS`) ; sans `--activity`, la tendance sur les `--weeks`
dernières semaines glissantes (défaut 12, comme `decoupling`). Restreint aux
sorties longues (`duration_s` > `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) de
la famille course à pied avec des échantillons FIT ingérés. Les colonnes
`activity.durability_gap_fade_pct`/`durability_ef_fade_pct`/
`durability_hr_first_third_bpm`/`durability_hr_middle_third_bpm`/
`durability_hr_last_third_bpm`/`durability_reason`/`durability_reason_code` sont
recalculées en entier à chaque passage de `index_workspace` (même discipline que
GAP/#44, découplage/#45, VAM/#46 et descente/#47).

`climb-history` (#49) rend, avec `--segment ID`, l'historique complet d'un
`climb_segment` (chaque occurrence : date, activité, temps, VAM, FC, dérive FC,
progression vs occurrence précédente/meilleure — voir `arc_climb_match.py`) ; avec
`--activity GARMIN_ID`, l'historique de CHAQUE segment gravi par cette activité ;
sans argument, la liste résumée de tous les segments connus (id, lieu, profil,
nombre d'occurrences, meilleur temps). `activity_climb.segment_id`/`hr_*`/`vs_*`
sont recalculés en entier à chaque passage de `index_workspace`, comme les autres
colonnes dérivées de l'épopée FIT — mais `climb_segment.id` n'est PAS stable d'une
réindexation à l'autre (voir la table dans `DDL`) : un id noté puis réutilisé après
un `--rebuild` peut ne plus exister (`reason_code: "unknown_segment"`, jamais une
erreur bruyante).

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
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_climb as VC  # noqa: E402
import arc_climb_match as VM  # noqa: E402
import arc_contract as C  # noqa: E402
import arc_decoupling as DC  # noqa: E402
import arc_descent as DS  # noqa: E402
import arc_durability as DU  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_samples as S  # noqa: E402
from coach_config import ConfigError, read_toml  # noqa: E402
from coach_setup import ENGINE, workspace_root  # noqa: E402

SCHEMA_VERSION = 16  # #49 : colonnes GPS `activity_sample.lat`/`lon` remplies (#42 les réservait),
                      # colonnes `activity_climb.segment_id`/`hr_*`/`vs_*` et table `climb_segment`
                      # (identité de montée entre séances, `arc_climb_match.py`) — voir #48 pour la
                      # version précédente
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


def _hr_zone_method(config: Dict[str, dict]) -> str:
    """Résout `[athlete].hr_zones`, jamais en levant (même discipline que
    `_heat_threshold_c` ci-dessus) : un typo ou une casse différente
    (`hr_zones = "LTHR"`, `hr_zones = "lthar"`) ne doit PAS casser `index_workspace`.

    Insensible à la casse et aux espaces (`M.hr_zone_bounds` le refait de toute façon
    en défense en profondeur, mais normaliser ici évite qu'un avertissement soit
    émis à chaque appel pour une simple casse différente). Toute valeur absente,
    vide, non-chaîne ou hors de `("auto",) + M.HR_ZONE_METHODS` retombe sur
    `M.HR_ZONE_METHOD_DEFAULT` (« auto »), avec un avertissement sur stderr dans le
    cas invalide seulement (pas pour une simple absence). Voir revue de code #43,
    point 4 : une méthode FORCÉE mais dont le profil n'a pas les champs requis reste
    volontairement possible ici (ce n'est pas une erreur de configuration, c'est
    `arc_metrics.hr_zone_resolution` qui en rend la raison à l'appelant, pas cette
    fonction — qui ne valide que le NOM de la méthode)."""
    raw = config.get("athlete", {}).get("hr_zones")
    if raw in (None, ""):
        return M.HR_ZONE_METHOD_DEFAULT
    allowed = (M.HR_ZONE_METHOD_DEFAULT,) + M.HR_ZONE_METHODS
    if not isinstance(raw, str):
        print(f"avertissement : [athlete].hr_zones = {raw!r} n'est pas une chaîne — "
              f"défaut « {M.HR_ZONE_METHOD_DEFAULT} » appliqué.", file=sys.stderr)
        return M.HR_ZONE_METHOD_DEFAULT
    value = raw.strip().lower()
    if value not in allowed:
        print(f"avertissement : [athlete].hr_zones = {raw!r} hors de {allowed} — "
              f"défaut « {M.HR_ZONE_METHOD_DEFAULT} » appliqué.", file=sys.stderr)
        return M.HR_ZONE_METHOD_DEFAULT
    return value


def _positive_float(config: Dict[str, dict], section: str, key: str, default: float) -> float:
    """Résout `[section].key` en flottant strictement positif, jamais en levant —
    même discipline que `_heat_threshold_c` (revue de code #46, should-fix 4 :
    « montée minimale configurable », critère d'acceptation de #46). Accepte un
    nombre ou une chaîne numérique (repli TOML < 3.11, voir `_heat_threshold_c`),
    rejette les booléens. Toute valeur absente, vide, invalide, nulle ou négative
    retombe sur `default`, avec un avertissement sur stderr dans le cas invalide
    seulement (jamais pour une simple absence, le cas normal sans override)."""
    raw = config.get(section, {}).get(key)
    if raw in (None, ""):
        return default
    value = None
    if not isinstance(raw, bool):
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip().replace(",", "."))
            except ValueError:
                value = None
    if value is None or value <= 0:
        print(f"avertissement : [{section}].{key} = {raw!r} n'est pas un nombre strictement positif "
              f"valide — défaut {default:g} appliqué.", file=sys.stderr)
        return default
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
        "hr_zones": _hr_zone_method(config),
        "language": config.get("language", {}).get("documents", "fr") or "fr",
        # VAM sur les montées détectées (#46, critère d'acceptation : « montée
        # minimale configurable (D+, pente) ») — `climb_min_grade_pct` en points de
        # pourcentage au workspace (ex. 5, pas 0.05), converti ici en fraction pour
        # `arc_climb.detect_climbs(min_avg_grade=...)`.
        "climb_min_gain_m": _positive_float(config, "metrics", "climb_min_gain_m", VC.MIN_CLIMB_GAIN_M),
        "climb_min_grade": _positive_float(
            config, "metrics", "climb_min_grade_pct", VC.MIN_CLIMB_AVG_GRADE * 100.0) / 100.0,
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
    sweat_rate_l_h REAL, gap_pace_s_km REAL, decoupling_pct REAL, ef_whole REAL,
    decoupling_reason TEXT, best_vam_10min_m_h REAL, best_vam_20min_m_h REAL,
    best_climb_vam_elapsed_m_h REAL, descent_reference_gap_pace_s_km REAL,
    descent_reference_source TEXT, durability_gap_fade_pct REAL, durability_ef_fade_pct REAL,
    durability_hr_first_third_bpm REAL, durability_hr_middle_third_bpm REAL,
    durability_hr_last_third_bpm REAL, durability_reason TEXT, durability_reason_code TEXT,
    body_md TEXT, data_json TEXT
);
CREATE INDEX activity_date ON activity(date);
-- `gap_pace_s_km` (#44, allure ajustée à la pente, `arc_gap.py`) : recalculée en
-- entier à CHAQUE `compute_metrics`, comme `hr_zone_time`/`hr_polarisation_time`
-- (#43) — jamais purgée par fichier, NULL par défaut pour tout sport hors de la
-- famille course à pied ou sans échantillons FIT (voir `arc_gap.ASSUMPTIONS`).
-- `decoupling_pct`/`ef_whole`/`decoupling_reason` (#45, découplage aérobie Pa:HR
-- et facteur d'efficacité, `arc_decoupling.py`) : même discipline de recalcul
-- intégral à chaque `compute_metrics`, restreint à la famille course à pied avec
-- échantillons FIT ingérés. `decoupling_reason` porte TOUJOURS la raison d'un
-- `decoupling_pct` NULL (durée insuffisante, échauffement, FC manquante, effort
-- non stable...) — jamais un NULL muet, voir `arc_decoupling.ASSUMPTIONS`.
-- `best_vam_10min_m_h`/`best_vam_20min_m_h`/`best_climb_vam_elapsed_m_h` (#46,
-- VAM sur les montées détectées, `arc_climb.py`) : même discipline de recalcul
-- intégral à chaque `compute_metrics`, restreint à la famille course à pied avec
-- échantillons FIT ingérés — voir `arc_climb.ASSUMPTIONS`. Le détail par montée
-- vit dans `activity_climb` ci-dessous, jamais ici (une activité peut avoir
-- plusieurs montées).
-- `descent_reference_gap_pace_s_km`/`descent_reference_source` (#47, efficacité en
-- descente, `arc_descent.py`) : allure GAP de référence « plat » utilisée pour
-- CETTE séance (voir `arc_descent.reference_gap_speed_ms`/ASSUMPTIONS["reference"]) —
-- `descent_reference_source` vaut `"flat"` (sections réellement plates) ou
-- `"non_descent"` (repli sur tout ce qui n'est pas une forte descente), jamais
-- caché : une référence de repli reste moins fiable qu'une référence plate franche.
-- NULL si aucune des deux n'est exploitable (voir `arc_descent.REASON_NO_REFERENCE`).
-- `durability_gap_fade_pct`/`durability_ef_fade_pct` (#48, durabilité sur les
-- sorties longues, `arc_durability.py`) : fade du GAP et de l'EF (GAP/FC) entre le
-- premier et le dernier tiers (temps de mouvement, post-échauffement) de la séance
-- — même discipline de recalcul intégral à chaque `compute_metrics` que
-- `decoupling_pct`/`ef_whole` ci-dessus, restreint à la famille course à pied avec
-- échantillons FIT ingérés, sorties longues UNIQUEMENT (`duration_s` >
-- `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min). `durability_hr_first_third_bpm`/
-- `_hr_middle_third_bpm`/`_hr_last_third_bpm` : FC moyenne par tiers, à titre
-- descriptif (voir `arc_durability.ASSUMPTIONS["hr_by_third"]`). `durability_reason`/
-- `durability_reason_code` portent TOUJOURS la raison d'un `durability_gap_fade_pct`
-- NULL (durée insuffisante, échauffement, FC manquante, pente asymétrique...) —
-- jamais un NULL muet, voir `arc_durability.ASSUMPTIONS`.
CREATE TABLE activity_split (
    activity_id INTEGER, km INTEGER, distance_m REAL, duration_s REAL, elev_gain_m REAL,
    elev_loss_m REAL, avg_hr_bpm REAL, max_hr_bpm REAL, max_speed_kmh REAL,
    cadence_spm REAL, label TEXT, gap_pace_s_km REAL
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
-- Échantillons FIT sous-échantillonnés (#42). Clé de rattachement = garmin_activity_id
-- (JAMAIS activity.id/rowid — voir `ingest_samples` pour le bug que ça corrige : un
-- rowid change à chaque édition du Markdown et peut être réattribué après suppression).
-- Le lien avec `activity` est résolu à LA LECTURE (`samples()`), jamais mis en cache.
-- source_path permet de purger les lignes d'un fichier `activities/fit/<id>.json`
-- modifié ou supprimé, comme les autres tables par fichier. lat/lon (#49, réservées par
-- #42) : remplies quand le FIT source porte un GPS exploitable (`arc_samples.GPS_KEYS`),
-- NULL sinon (indoor, capteur coupé) — usage INTERNE uniquement (appariement de montée,
-- `arc_climb_match.py`) : jamais exposées par l'API ni le CLI (voir
-- `arc_climb_match.ASSUMPTIONS["privacy"]`).
CREATE TABLE activity_sample (
    garmin_activity_id INTEGER, source_path TEXT, t_s REAL, distance_m REAL, altitude_m REAL,
    hr_bpm REAL, speed_ms REAL, cadence_spm REAL, lat REAL, lon REAL
);
CREATE INDEX activity_sample_garmin ON activity_sample(garmin_activity_id);
CREATE INDEX activity_sample_source ON activity_sample(source_path);
-- Suivi des fichiers `activities/fit/*.json` — table DÉDIÉE, jamais `source_file` :
-- `source_file` est lu par `backfill_items` et `scripts/coach_doctor.py` en supposant
-- qu'il ne contient que des fichiers Markdown du contrat (revue PR #87) ; y mêler les
-- FIT y ferait apparaître à tort une dette de contrat ou un « fichier supprimé »
-- fantôme après --rebuild.
CREATE TABLE sample_file (
    path TEXT PRIMARY KEY, sha256 TEXT, mtime REAL, garmin_activity_id INTEGER,
    status TEXT, issues TEXT
);
-- Temps en zone FC (#43), par activité (id INTERNE, comme `activity_split` — jamais
-- `garmin_activity_id` : la ligne est recréée à chaque `compute_metrics`, sans purge
-- par fichier). Une activité sans zone calculable (pas de FC max au profil), hors de
-- la famille course à pied (`arc_metrics.sport_family` != "run" — revue de code #43,
-- point 5 : le renforcement et le vélo faussaient la polarisation) ou sans
-- échantillons FIT n'a simplement aucune ligne ici.
CREATE TABLE hr_zone_time (activity_id INTEGER, zone INTEGER, seconds REAL);
CREATE INDEX hr_zone_time_activity ON hr_zone_time(activity_id);
-- Temps par seau Seiler (#43, revue de code point 2) : bornes bpm DÉDIÉES par
-- méthode (`arc_metrics.seiler_bounds`), JAMAIS dérivées de `hr_zone_time` par un
-- simple regroupement de numéros de zone (faux pour LTHR/%FCmax, voir
-- ASSUMPTIONS["hr_zones"]). `bucket` : "low" | "moderate" | "high". Mêmes règles de
-- restriction et de recalcul que `hr_zone_time` ci-dessus.
CREATE TABLE hr_polarisation_time (activity_id INTEGER, bucket TEXT, seconds REAL);
CREATE INDEX hr_polarisation_time_activity ON hr_polarisation_time(activity_id);
-- Montées détectées par activité (#46, `arc_climb.py`), id INTERNE (`activity_id`,
-- comme `hr_zone_time`/`activity_split` — jamais `garmin_activity_id` : la ligne
-- est recréée en entier à chaque `compute_metrics`, sans purge par fichier). `idx`
-- : ordre de la montée dans l'activité (1-based, chronologique). `avg_grade` :
-- fraction signée (0,08 = 8 %). `vam_elapsed_m_h`/`vam_moving_m_h` : voir
-- `arc_climb.ASSUMPTIONS["vam_basis"]` (les deux, jamais une seule). Une activité
-- sans montée détectée (parcours plat, ou hors famille course à pied/sans FIT)
-- n'a simplement aucune ligne ici.
-- `segment_id`/`hr_first_third_bpm`/`hr_last_third_bpm`/`hr_drift_bpm_per_100m`/
-- `vs_previous_pct`/`vs_best_pct` (#49, identité de montée entre séances,
-- `arc_climb_match.py`) : `segment_id` référence `climb_segment.id` ci-dessous, `NULL`
-- si cette montée n'a pu être appariée NI enregistrée comme nouveau segment (ne devrait
-- pas arriver en pratique — voir `compute_metrics`). `hr_*`/`vs_*` : voir
-- `arc_climb_match.ASSUMPTIONS["hr_drift"]`/["progression"], `NULL` si non calculables
-- (gain trop faible, FC manquante, ou première occurrence du segment pour `vs_*`).
CREATE TABLE activity_climb (
    activity_id INTEGER, idx INTEGER, start_t_s REAL, end_t_s REAL, start_km REAL, end_km REAL,
    distance_m REAL, gain_m REAL, avg_grade REAL, grade_class TEXT,
    duration_elapsed_s REAL, duration_moving_s REAL, vam_elapsed_m_h REAL, vam_moving_m_h REAL,
    segment_id INTEGER, hr_first_third_bpm REAL, hr_last_third_bpm REAL,
    hr_drift_bpm_per_100m REAL, vs_previous_pct REAL, vs_best_pct REAL
);
CREATE INDEX activity_climb_activity ON activity_climb(activity_id);
CREATE INDEX activity_climb_segment ON activity_climb(segment_id);
-- Registre des montées reconnues comme « la même » d'une séance à l'autre (#49,
-- `arc_climb_match.py`) — recalculé INTÉGRALEMENT à chaque `compute_metrics` (comme
-- `activity_climb`/`hr_zone_time`, jamais une purge par fichier : l'id n'est donc PAS
-- stable d'une réindexation à l'autre, seul `location`+signature de profil l'est en
-- pratique — un consommateur externe doit toujours relire `segment_id` depuis
-- `activity_climb`, jamais le mémoriser). `start_lat`/`start_lon`/`summit_lat`/
-- `summit_lon` : position de la PREMIÈRE occurrence rencontrée (jamais mise à jour
-- ensuite, un repère stable suffit à l'appariement futur — voir
-- `arc_climb_match.ClimbSegmentIndex`), `NULL` si cette première occurrence n'avait pas
-- de GPS exploitable (repli par lieu, voir `arc_climb_match.ASSUMPTIONS["fallback_matching"]`).
-- USAGE INTERNE UNIQUEMENT pour les positions : jamais exposées par l'API/le CLI (voir
-- `arc_climb_match.ASSUMPTIONS["privacy"]`) — seuls `id`/`location`/le profil/les
-- agrégats (`occurrences`, `best_time_elapsed_s`) le sont.
CREATE TABLE climb_segment (
    id INTEGER PRIMARY KEY, location TEXT, gain_m REAL, distance_m REAL, avg_grade REAL,
    grade_class TEXT, start_lat REAL, start_lon REAL, summit_lat REAL, summit_lon REAL,
    first_seen_activity_id INTEGER, first_seen_date TEXT, occurrences INTEGER,
    best_time_elapsed_s REAL, best_activity_id INTEGER
);
-- Efficacité en descente par classe de pente (#47, `arc_descent.py`), id INTERNE
-- (`activity_id`, comme `activity_climb`/`hr_zone_time` — jamais `garmin_activity_id` :
-- recréée en entier à chaque `compute_metrics`, sans purge par fichier). `grade_class` :
-- voir `arc_descent.DESCENT_GRADE_CLASSES` (mirroir des classes ascendantes de #46).
-- `efficiency` : moyenne pondérée par le temps du ratio par échantillon vitesse GAP
-- / référence « plat » de LA SÉANCE — la référence est `activity.
-- descent_reference_gap_pace_s_km`/`descent_reference_source` ci-dessous, JAMAIS
-- l'allure GAP de toute la séance (`activity.gap_pace_s_km`, #44 : se contaminerait
-- avec l'effort des descentes elles-mêmes — voir `arc_descent.ASSUMPTIONS
-- ["reference"]`, BLOQUANT corrigé en revue de code). Voir
-- `arc_descent.ASSUMPTIONS["indicator"]` pour la lecture honnête de cet indicateur
-- (le modèle de Minetti sous-jacent surestime le bénéfice des fortes descentes,
-- une valeur < 1 sur les classes raides est attendue). Une activité sans classe
-- qualifiante (durée/distance insuffisante par classe, référence indisponible, ou
-- hors famille course à pied/sans FIT) n'a simplement aucune ligne ici.
-- `mean_grade` (revue de code #47) : pente RÉELLEMENT rencontrée en moyenne sur la
-- classe (fraction signée), pas seulement son libellé — utile notamment sur les
-- deux paniers larges au-delà de -20 % (`arc_descent.ASSUMPTIONS["grade_classes"]`,
-- coût de Minetti non monotone en descente).
CREATE TABLE activity_descent_class (
    activity_id INTEGER, grade_class TEXT, count INTEGER, duration_moving_s REAL, distance_m REAL,
    mean_speed_ms REAL, mean_pace_s_km REAL, mean_gap_speed_ms REAL, mean_grade REAL, efficiency REAL
);
CREATE INDEX activity_descent_class_activity ON activity_descent_class(activity_id);
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
    """Charge par séance, VO2max par séance, temps en zone FC + polarisation, puis la
    série quotidienne matérialisée."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete) if athlete else {}
    zone_bounds = M.hr_zone_bounds(athlete, conf.get("hr_zones"))
    seiler_thresholds = M.seiler_bounds(athlete, zone_bounds[1]) if zone_bounds else None
    loads: Dict[str, float] = {}
    estimates = []
    # Tri par date, avec des DÉPARTAGEURS déterministes (#49, revue de code, BLOQUANT) :
    # `date` seule ne distingue pas deux activités du même jour, ce qui rendrait l'ordre de
    # traitement chronologique (`climb_registry`/`segment_history`, voir plus bas) dépendant
    # d'un ordre SQL non garanti d'une exécution à l'autre — deux séances au même
    # `garmin_activity_id`/lieu le même jour pourraient alors se voir apparier dans un ordre
    # instable, changeant occasionnellement laquelle est « la première » (`vs_previous_pct`
    # calculé dans le mauvais sens). `start_time` (horodatage complet) départage d'abord,
    # `garmin_activity_id` ensuite (stable, jamais réattribué), `id` en tout dernier recours
    # (toujours unique) pour un ordre totalement déterministe.
    rows = conn.execute("SELECT * FROM activity ORDER BY date, start_time, garmin_activity_id, id").fetchall()
    # Tables dérivées intégralement recalculées à chaque passage (pas de purge par
    # fichier comme `PER_FILE_TABLES`, `activity_id` change à chaque édition du
    # Markdown — voir ASSUMPTIONS["hr_zones"]) : un changement de profil (FC max/
    # repos/seuil) ou de `[athlete].hr_zones` est donc répercuté sans étape à part,
    # incrémental ou `--rebuild`.
    conn.execute("DELETE FROM hr_zone_time")
    conn.execute("DELETE FROM hr_polarisation_time")
    conn.execute("DELETE FROM activity_climb")
    conn.execute("DELETE FROM activity_descent_class")
    conn.execute("DELETE FROM climb_segment")
    # Identité de montée entre séances (#49, `arc_climb_match.py`) : registre reconstruit
    # INTÉGRALEMENT à chaque passage, comme les autres tables ci-dessus — `rows` est déjà
    # trié par date croissante (`ORDER BY date`), donc traiter les activités DANS CET ORDRE
    # suffit à obtenir une histoire chronologique par segment sans tri supplémentaire.
    # `climb_registry` reste en mémoire pour toute la durée de cette fonction (jamais
    # persisté tel quel) ; `segment_history` porte, PAR id de segment interne au registre,
    # les occurrences déjà vues (temps écoulé, activité) pour calculer `vs_previous_pct`/
    # `vs_best_pct` de l'occurrence SUIVANTE avant de s'y ajouter elle-même.
    climb_registry = VM.ClimbSegmentIndex()
    segment_history: Dict[int, dict] = {}
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
        # Restreint aux sports « course à pied » (running/trail/randonnée/marche) :
        # le renforcement (effort anaérobie/technique) et le vélo (LTHR différente,
        # non renseignée séparément au profil) fausseraient temps en zone et
        # polarisation — voir ASSUMPTIONS["hr_zones"], revue de code #43 point 5.
        if act.get("garmin_activity_id") and M.sport_family(act.get("sport")) == "run":
            act_samples = samples(conn, act["id"])
            if act_samples:
                # Défense en profondeur (revue de code #46, 3e passe, BLOQUANT) : un bug
                # inattendu dans UN des calculs dérivés des échantillons (zones, GAP,
                # découplage, VAM) — même déjà couvert par ses propres tests — ne doit
                # JAMAIS faire échouer `index_workspace` pour TOUTES les activités : le
                # tableau de bord et `/garmin-daily-sync` en dépendent à chaque
                # rafraîchissement. Une exception ici est donc rattrapée, journalisée sur
                # stderr avec l'id de l'activité (jamais silencieuse), toute ligne
                # partiellement insérée pour CETTE activité dans les tables dérivées est
                # purgée, et ses champs dérivés sont explicitement remis à NULL avec une
                # raison explicite — l'indexation continue avec l'activité suivante,
                # jamais un plantage global pour une seule séance à échantillons
                # malformés ou un cas limite non anticipé par un détecteur.
                #
                # `ARC_STRICT_METRICS=1` (revue de code #46, 4e passe) désactive ce
                # rattrapage et relève l'exception telle quelle : les suites de tests
                # (`tests/run_tests.py`, donc la CI) tournent avec cette variable pour
                # qu'un VRAI bug de programmation dans un des calculs dérivés fasse
                # échouer le test qui l'a déclenché plutôt que de disparaître,
                # silencieusement rattrapé, dans un `NULL` que rien ne signale comme une
                # anomalie — le rattrapage silencieux n'est un comportement voulu qu'en
                # PRODUCTION (workspace réel de l'athlète, `/garmin-daily-sync`), jamais
                # pendant le développement. Une erreur SQLite (verrou, base corrompue)
                # n'est, elle, JAMAIS rattrapée ici, `ARC_STRICT_METRICS` ou pas : un
                # problème d'infrastructure de la base doit toujours remonter bruyamment,
                # ce n'est pas ce que cette défense en profondeur vise à absorber.
                #
                # `registry_mark`/`history_marks` (#49, revue de code, BLOQUANT) : point de
                # reprise du registre de montées AVANT tout appariement de CETTE activité —
                # si le `except Exception` ci-dessous doit rattraper un échec survenu APRÈS
                # que cette activité a déjà été appariée/enregistrée dans `climb_registry`/
                # `segment_history`, ces mutations en mémoire sont défaites pour cette seule
                # activité (voir `ClimbSegmentIndex.rollback`) — sans ce mécanisme, une
                # activité en échec laissait une occurrence FANTÔME dans `segment_history`,
                # faussant `vs_previous_pct`/`vs_best_pct` (et `climb_segment.occurrences`)
                # d'une activité SUIVANTE qui, elle, réussit (bug réel : l'activité en échec
                # n'a AUCUNE ligne `activity_climb`, jamais purgée par le nettoyage SQL
                # ci-dessous, mais son occurrence restait comptée dans l'historique en
                # mémoire du segment).
                registry_mark = climb_registry.mark()
                history_marks: Dict[int, Optional[int]] = {}
                try:
                    if zone_bounds:
                        bounds, _method = zone_bounds
                        zone_seconds = M.time_in_zone_seconds(act_samples, bounds, S.DEFAULT_RESOLUTION_S)
                        conn.executemany(
                            "INSERT INTO hr_zone_time (activity_id, zone, seconds) VALUES (?, ?, ?)",
                            [(act["id"], zone, round(seconds, 1)) for zone, seconds in zone_seconds.items()],
                        )
                    if seiler_thresholds:
                        bucket_seconds = M.time_in_polarisation_seconds(
                            act_samples, seiler_thresholds, S.DEFAULT_RESOLUTION_S)
                        conn.executemany(
                            "INSERT INTO hr_polarisation_time (activity_id, bucket, seconds) VALUES (?, ?, ?)",
                            [(act["id"], bucket, round(seconds, 1)) for bucket, seconds in bucket_seconds.items()],
                        )
                    # GAP (#44, allure ajustée à la pente) : pente + vitesse GAP calculées une
                    # seule fois par échantillon (`gap_sample_series`), réutilisées pour
                    # l'allure globale ET par split — jamais recalculées deux fois pour la
                    # même activité (voir `arc_gap.activity_gap_pace_from_series`).
                    gap_series = G.gap_sample_series(act_samples)
                    gap_pace = G.activity_gap_pace_from_series(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
                    conn.execute("UPDATE activity SET gap_pace_s_km = ? WHERE id = ?",
                                 (round(gap_pace, 2) if gap_pace is not None else None, act["id"]))
                    split_rows = conn.execute(
                        "SELECT km, distance_m FROM activity_split WHERE activity_id = ?", (act["id"],)).fetchall()
                    if split_rows:
                        gap_by_km = G.split_gap_paces_from_series(gap_series, [dict(r) for r in split_rows],
                                                                   resolution_s=S.DEFAULT_RESOLUTION_S)
                        conn.executemany(
                            "UPDATE activity_split SET gap_pace_s_km = ? WHERE activity_id = ? AND km = ?",
                            [(round(v, 2) if v is not None else None, act["id"], km) for km, v in gap_by_km.items()],
                        )
                    # Découplage aérobie (#45, Pa:HR) et facteur d'efficacité : réutilise
                    # `gap_series` déjà calculée ci-dessus via `decoupling_report_from_series`
                    # (jamais un second calcul de pente/GAP pour la même activité) — le sport
                    # est déjà restreint à la famille course à pied par le `if` englobant,
                    # comme pour le GAP lui-même juste au-dessus.
                    report = DC.decoupling_report_from_series(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
                    conn.execute(
                        "UPDATE activity SET decoupling_pct = ?, ef_whole = ?, decoupling_reason = ? WHERE id = ?",
                        (report["decoupling_pct"], report["ef_whole"], report["reason"], act["id"]),
                    )
                    # VAM sur les montées détectées (#46) : détection PURE sur les échantillons
                    # bruts (t_s/distance_m/altitude_m/speed_ms), indépendante du GAP/de la pente
                    # fenêtrée calculée ci-dessus pour le GAP (`arc_climb.detect_climbs` a son
                    # propre lissage/segmentation, voir `arc_climb.ASSUMPTIONS`) — jamais un
                    # second calcul de pente au sens GAP, seulement une réutilisation du lissage
                    # d'altitude déjà partagé (`arc_elevation.smooth_moving_average`). Seuils de
                    # détection configurables par le workspace (`[metrics].climb_min_gain_m`/
                    # `climb_min_grade_pct`, critère d'acceptation de #46 : « montée minimale
                    # configurable »), résolus une fois pour toutes dans `conf` par `settings()`.
                    climb = VC.detect_climbs(act_samples, min_gain_m=conf["climb_min_gain_m"],
                                              min_avg_grade=conf["climb_min_grade"])
                    if climb:
                        # Identité de montée entre séances (#49) : pour CHAQUE montée détectée
                        # de CETTE activité, apparier (ou enregistrer comme nouveau segment),
                        # calculer la dérive FC et la progression vs occurrence(s) antérieure(s)
                        # — voir `arc_climb_match.py` pour l'algorithme complet et ses limites
                        # assumées.
                        climb_rows = []
                        for c in climb:
                            endpoints = VM.climb_endpoints(act_samples, c) or {}
                            candidate = {
                                "start_lat": endpoints.get("start_lat"), "start_lon": endpoints.get("start_lon"),
                                "end_lat": endpoints.get("end_lat"), "end_lon": endpoints.get("end_lon"),
                                "gain_m": c["gain_m"], "distance_m": c["distance_m"],
                                "avg_grade": c["avg_grade"], "grade_class": c["grade_class"],
                                "location": act.get("location"),
                                # Identifiant déterministe (#49, ASSUMPTIONS["segment_id"]) :
                                # requis par `ClimbSegmentIndex.add` si aucun appariement.
                                "garmin_activity_id": act["garmin_activity_id"], "climb_idx": c["index"],
                            }
                            segment = climb_registry.match(candidate)
                            if segment is None:
                                segment = climb_registry.add(candidate)
                            segment_id = segment["id"]
                            # Point de reprise PAR SEGMENT (une seule fois par segment touché
                            # par CETTE activité, voir `registry_mark` ci-dessus) : `None`
                            # signifie « ce segment n'existait pas avant cette activité »
                            # (rollback = le supprimer entièrement), un entier signifie
                            # « il avait déjà N occurrences » (rollback = tronquer à N).
                            if segment_id not in history_marks:
                                history_marks[segment_id] = (
                                    len(segment_history[segment_id]["occurrences"])
                                    if segment_id in segment_history else None)
                            history = segment_history.setdefault(
                                segment_id, {"occurrences": [], "first_activity_id": act["id"],
                                             "first_date": act.get("date")})
                            prev_times = [o["time_elapsed_s"] for o in history["occurrences"]
                                          if o["time_elapsed_s"] is not None]
                            vs_previous = (VM.progression_pct(prev_times[-1], c["duration_elapsed_s"])
                                           if prev_times else None)
                            vs_best = (VM.progression_pct(min(prev_times), c["duration_elapsed_s"])
                                       if prev_times else None)
                            history["occurrences"].append(
                                {"time_elapsed_s": c["duration_elapsed_s"], "activity_id": act["id"]})
                            hr = VM.hr_drift_bpm_per_100m(act_samples, c)
                            climb_rows.append((
                                act["id"], c["index"], c["start_t_s"], c["end_t_s"], c["start_km"], c["end_km"],
                                c["distance_m"], c["gain_m"], c["avg_grade"], c["grade_class"],
                                c["duration_elapsed_s"], c["duration_moving_s"], c["vam_elapsed_m_h"],
                                c["vam_moving_m_h"], segment_id, hr["hr_first_third_bpm"],
                                hr["hr_last_third_bpm"], hr["hr_drift_bpm_per_100m"], vs_previous, vs_best,
                            ))
                        conn.executemany(
                            "INSERT INTO activity_climb (activity_id, idx, start_t_s, end_t_s, start_km, end_km, "
                            "distance_m, gain_m, avg_grade, grade_class, duration_elapsed_s, duration_moving_s, "
                            "vam_elapsed_m_h, vam_moving_m_h, segment_id, hr_first_third_bpm, hr_last_third_bpm, "
                            "hr_drift_bpm_per_100m, vs_previous_pct, vs_best_pct) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            climb_rows,
                        )
                    windows = VC.best_vam_windows(act_samples, climb)
                    best_climb_vam = max(
                        (c["vam_elapsed_m_h"] for c in climb if c["vam_elapsed_m_h"] is not None), default=None)
                    conn.execute(
                        "UPDATE activity SET best_vam_10min_m_h = ?, best_vam_20min_m_h = ?, "
                        "best_climb_vam_elapsed_m_h = ? WHERE id = ?",
                        (windows["vam_best_10min_m_h"], windows["vam_best_20min_m_h"], best_climb_vam, act["id"]),
                    )
                    # Efficacité en descente par classe de pente (#47) : réutilise `gap_series`
                    # (pente + vitesse GAP par échantillon, jamais un second calcul) — la
                    # référence « plat » de CETTE séance N'EST PLUS l'allure GAP de la séance
                    # entière (`gap_pace`, ci-dessus, restée réservée à #44) : voir
                    # `arc_descent.ASSUMPTIONS["reference"]` (BLOQUANT, revue de code) — l'allure
                    # GAP globale se contamine avec l'effort des descentes à mesurer elles-mêmes,
                    # faisant varier l'efficacité d'une même descente selon le reste du parcours.
                    reference_speed, reference_source = DS.reference_gap_speed_ms(
                        gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
                    # Sans référence, aucune classe n'est stockée (voir
                    # `arc_descent.descent_report`, même discipline) — jamais une
                    # ligne à `efficiency: NULL` qui laisserait croire à un calcul
                    # partiel plutôt qu'à une absence totale de résultat.
                    descent_classes = (DS.descent_speed_by_grade_class(
                        gap_series, reference_gap_speed_ms=reference_speed,
                        resolution_s=S.DEFAULT_RESOLUTION_S) if reference_speed is not None else {})
                    reference_pace = (1000.0 / reference_speed) if reference_speed else None
                    conn.execute(
                        "UPDATE activity SET descent_reference_gap_pace_s_km = ?, "
                        "descent_reference_source = ? WHERE id = ?",
                        (round(reference_pace, 2) if reference_pace is not None else None,
                         reference_source, act["id"]),
                    )
                    if descent_classes:
                        conn.executemany(
                            "INSERT INTO activity_descent_class (activity_id, grade_class, count, "
                            "duration_moving_s, distance_m, mean_speed_ms, mean_pace_s_km, "
                            "mean_gap_speed_ms, mean_grade, efficiency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [(act["id"], cls, v["count"], v["duration_moving_s"], v["distance_m"],
                              v["mean_speed_ms"], v["mean_pace_s_km"], v["mean_gap_speed_ms"],
                              v["mean_grade"], v["efficiency"])
                             for cls, v in descent_classes.items()],
                        )
                    # Durabilité sur les sorties longues (#48) : réutilise `gap_series`
                    # (jamais un second calcul pente/GAP pour la même activité) — le
                    # sport est déjà restreint à la famille course à pied par le `if`
                    # englobant, comme pour le GAP/le découplage/la descente ci-dessus.
                    # Aucun seuil de durée n'est appliqué ICI avant l'appel : c'est
                    # `arc_durability.durability_report_from_series` elle-même qui
                    # rend `eligible: False` avec une `reason`/`reason_code` explicites
                    # sous `arc_metrics.LONG_RUN_MIN_DURATION_S` (même discipline que
                    # le découplage, qui a son propre seuil interne à 60 min).
                    dur_report = DU.durability_report_from_series(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
                    conn.execute(
                        "UPDATE activity SET durability_gap_fade_pct = ?, durability_ef_fade_pct = ?, "
                        "durability_hr_first_third_bpm = ?, durability_hr_middle_third_bpm = ?, "
                        "durability_hr_last_third_bpm = ?, durability_reason = ?, "
                        "durability_reason_code = ? WHERE id = ?",
                        (dur_report["gap_fade_pct"], dur_report["ef_fade_pct"],
                         dur_report["hr_first_third_bpm"], dur_report["hr_middle_third_bpm"],
                         dur_report["hr_last_third_bpm"], dur_report["reason"], dur_report["reason_code"],
                         act["id"]),
                    )
                except sqlite3.Error:
                    # Jamais rattrapé, `ARC_STRICT_METRICS` ou pas (voir le commentaire
                    # ci-dessus) : un verrou ou une base corrompue est un problème
                    # d'infrastructure, pas un défaut d'UN calcul dérivé — il doit
                    # remonter bruyamment plutôt que de laisser croire à une activité
                    # simplement sans métriques dérivées.
                    raise
                except Exception as exc:  # noqa: BLE001 — défense en profondeur assumée, voir ci-dessus
                    if os.environ.get("ARC_STRICT_METRICS") == "1":
                        raise
                    print(
                        f"avertissement : calcul des métriques dérivées des échantillons a échoué pour "
                        f"l'activité id={act['id']} (garmin_activity_id={act.get('garmin_activity_id')}) : "
                        f"{exc!r} — champs dérivés remis à NULL, indexation poursuivie avec les activités "
                        "suivantes.",
                        file=sys.stderr,
                    )
                    # Annule tout ce que CETTE activité a mutable en mémoire dans le
                    # registre de montées AVANT l'échec (#49, revue de code, BLOQUANT — voir
                    # le commentaire de `registry_mark` ci-dessus) : sans ce rollback, une
                    # occurrence fantôme resterait dans `segment_history` et fausserait la
                    # progression calculée pour l'activité suivante.
                    climb_registry.rollback(registry_mark)
                    for seg_id, occ_count in history_marks.items():
                        if occ_count is None:
                            segment_history.pop(seg_id, None)
                        else:
                            segment_history[seg_id]["occurrences"] = segment_history[seg_id]["occurrences"][:occ_count]
                    conn.execute("DELETE FROM hr_zone_time WHERE activity_id = ?", (act["id"],))
                    conn.execute("DELETE FROM hr_polarisation_time WHERE activity_id = ?", (act["id"],))
                    conn.execute("DELETE FROM activity_climb WHERE activity_id = ?", (act["id"],))
                    conn.execute("DELETE FROM activity_descent_class WHERE activity_id = ?", (act["id"],))
                    conn.execute(
                        "UPDATE activity_split SET gap_pace_s_km = NULL WHERE activity_id = ?", (act["id"],))
                    conn.execute(
                        "UPDATE activity SET gap_pace_s_km = NULL, decoupling_pct = NULL, ef_whole = NULL, "
                        "decoupling_reason = ?, best_vam_10min_m_h = NULL, best_vam_20min_m_h = NULL, "
                        "best_climb_vam_elapsed_m_h = NULL, descent_reference_gap_pace_s_km = NULL, "
                        "descent_reference_source = NULL, durability_gap_fade_pct = NULL, "
                        "durability_ef_fade_pct = NULL, durability_hr_first_third_bpm = NULL, "
                        "durability_hr_middle_third_bpm = NULL, durability_hr_last_third_bpm = NULL, "
                        "durability_reason = ?, durability_reason_code = ? WHERE id = ?",
                        ("calcul impossible (erreur interne)", "calcul impossible (erreur interne)",
                         "internal_error", act["id"]),
                    )
    # Écriture du registre `climb_segment` (#49), une fois toutes les activités traitées :
    # `climb_registry.segments` porte le profil/la position représentative (première
    # occurrence), `segment_history` les occurrences vues (temps écoulé, activité) pour
    # `occurrences`/`best_time_elapsed_s`/`best_activity_id`. Le rollback par activité
    # (`registry_mark`/`history_marks` ci-dessus) garantit qu'un segment présent ici a
    # TOUJOURS au moins une occurrence dans `segment_history` — plus de ligne orpheline
    # possible depuis ce correctif (#49, revue de code, BLOQUANT).
    # `segment["id"]` est déterministe (ASSUMPTIONS["segment_id"]), PAS une position dans
    # `climb_registry.segments` : recherche par id, jamais par index.
    segments_by_id = {seg["id"]: seg for seg in climb_registry.segments}
    for segment_id, history in segment_history.items():
        seg = segments_by_id[segment_id]
        times = [(o["time_elapsed_s"], o["activity_id"]) for o in history["occurrences"]
                 if o["time_elapsed_s"] is not None]
        best_time, best_activity_id = min(times, default=(None, None), key=lambda t: t[0])
        conn.execute(
            "INSERT INTO climb_segment (id, location, gain_m, distance_m, avg_grade, grade_class, start_lat, "
            "start_lon, summit_lat, summit_lon, first_seen_activity_id, first_seen_date, occurrences, "
            "best_time_elapsed_s, best_activity_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (segment_id, seg["location"], seg["gain_m"], seg["distance_m"], seg["avg_grade"], seg["grade_class"],
             seg["start_lat"], seg["start_lon"], seg["summit_lat"], seg["summit_lon"],
             history["first_activity_id"], history["first_date"], len(history["occurrences"]),
             best_time, best_activity_id),
        )
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
    dans `activity_sample`.

    **Clé de rattachement = `garmin_activity_id`, jamais le rowid interne `activity.id`.**
    Une version antérieure de cette fonction stockait `activity.id` — un bug réel (revue
    PR #87) : ce rowid change dès qu'une activité est repurgée puis réinsérée
    (`_purge`/`store`, sur un simple edit du Markdown), et SQLite peut le RÉATTRIBUER à
    une tout autre séance après suppression d'un fichier. Trois conséquences observées :
    un FIT ingéré avant que le Markdown correspondant n'existe restait orphelin pour
    toujours (aucun re-rattachement automatique) ; un Markdown simplement modifié
    perdait ses échantillons (rattachés à un id mort) ; un Markdown supprimé puis un id
    réutilisé par une AUTRE activité lui volait les échantillons de la première. Stocker
    `garmin_activity_id` (jamais réattribué, c'est l'identifiant Garmin réel) et joindre
    `activity` à la LECTURE (`samples()`) élimine structurellement les trois cas : le lien
    n'est jamais mis en cache, il est recalculé à chaque lecture depuis l'état courant de
    `activity`.

    Suivi dans sa propre table `sample_file` (jamais `source_file`, qui n'est lu par
    aucun consommateur autrement qu'en assumant un fichier Markdown du contrat —
    `backfill_items`, `scripts/coach_doctor.py::check_index_freshness` /
    `check_out_of_contract`, `arc_serve.py` — un fichier `fit_sample` qui s'y serait
    glissé y apparaîtrait à tort comme une dette de contrat ou un fichier « supprimé »
    fantôme après un `--rebuild`, revue PR #87) : chaque fichier est suivi par son
    sha256 — inchangé → sauté, modifié → repurgé puis réingéré, disparu → ses lignes
    `activity_sample` retirées. Deux ingestions successives sans changement de fichier
    produisent donc des lignes identiques (idempotence) ; un JSON illisible est compté
    `invalid`, jamais confondu avec un fichier ingéré avec succès.

    Le `garmin_activity_id` d'un fichier ingéré, qu'il corresponde ou non à une activité
    DÉJÀ indexée au moment de l'ingestion, est toujours stocké — voir `sample_coverage()`
    pour le comptage `unlinked_garmin_ids`, calculé fraîchement à chaque appel par une
    requête, jamais mis en cache sur le fichier : purement informatif, **rien n'est
    perdu** — `samples()` retrouvera les échantillons dès que le Markdown de la séance
    sera indexé, sans réingestion du FIT.

    **Budget de taille** (documenté ici, pas ailleurs, pour rester à côté du code qui le
    détermine) : à la résolution par défaut (5 s), une sortie d'1 h ≈ 720 lignes. Pour
    ~300 séances/an d'1 h en moyenne (un volume plausible de coureur régulier, cf.
    `tests/lib/synthetic.py`), ≈ 216 000 lignes — quelques dizaines de Mo dans SQLite
    (l'ordre de grandeur usuel est de 50 à 100 octets/ligne avec l'overhead SQLite pour 6
    colonnes REAL + 2 INTEGER/TEXT), largement absorbable par le fichier `.arc/coach.db`
    déjà jetable et reconstruit à la demande. L'index sur `garmin_activity_id` (DDL
    ci-dessus) garde les requêtes par séance en O(log n) plutôt qu'un scan complet de la
    table à mesure qu'elle grossit.
    """
    counts = {"ingested": 0, "unchanged": 0, "removed": 0, "invalid": 0}
    seen = set()
    for path in discover_sample_files(workspace):
        rel = path.relative_to(workspace).as_posix()
        seen.add(rel)
        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        known = conn.execute("SELECT sha256 FROM sample_file WHERE path = ?", (rel,)).fetchone()
        if known and known[0] == digest:
            counts["unchanged"] += 1
            continue
        conn.execute("DELETE FROM activity_sample WHERE source_path = ?", (rel,))
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            conn.execute(
                "INSERT OR REPLACE INTO sample_file VALUES (?, ?, ?, ?, ?, ?)",
                (rel, digest, path.stat().st_mtime, None, "invalid", _j(["JSON illisible"])),
            )
            counts["invalid"] += 1
            continue
        garmin_id = _sample_file_activity_id(path, raw)
        if garmin_id is None:
            conn.execute(
                "INSERT OR REPLACE INTO sample_file VALUES (?, ?, ?, ?, ?, ?)",
                (rel, digest, path.stat().st_mtime, None, "invalid",
                 _j(["garmin_activity_id introuvable (nom de fichier non numérique et clé activity_id absente)"])),
            )
            counts["invalid"] += 1
            continue
        sport = conn.execute(
            "SELECT sport FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()
        records = S.downsample(
            S.normalise_records(raw, sport=sport["sport"] if sport else None), resolution_s)
        conn.executemany(
            "INSERT INTO activity_sample "
            "(garmin_activity_id, source_path, t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm, "
            "lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(garmin_id, rel, rec["t_s"], rec["distance_m"], rec["altitude_m"],
              rec["hr_bpm"], rec["speed_ms"], rec["cadence_spm"],
              rec.get("lat_deg"), rec.get("lon_deg")) for rec in records],
        )
        conn.execute(
            "INSERT OR REPLACE INTO sample_file VALUES (?, ?, ?, ?, ?, ?)",
            (rel, digest, path.stat().st_mtime, garmin_id, "ok", "[]"),
        )
        counts["ingested"] += 1
    for (rel,) in conn.execute("SELECT path FROM sample_file").fetchall():
        if rel not in seen:
            conn.execute("DELETE FROM activity_sample WHERE source_path = ?", (rel,))
            conn.execute("DELETE FROM sample_file WHERE path = ?", (rel,))
            counts["removed"] += 1
    conn.commit()
    return counts


def sample_coverage(conn) -> dict:
    """Couverture FIT actuelle, recalculée à chaque appel (jamais mise en cache sur un
    fichier) — pour `status` et `coach_doctor`-like diagnostics. `rows` : TOUTES les
    lignes stockées, liées ou non (jamais scopé au lien) ; `activities_with_samples` :
    activités dont le `garmin_activity_id` a au moins un échantillon ; `unlinked_garmin_ids` :
    `garmin_activity_id` présents dans `activity_sample` sans activité correspondante
    (FIT téléchargé avant le Markdown, ou séance depuis retirée du workspace) — jamais
    une erreur, juste une information de latence entre les deux sources."""
    rows = conn.execute("SELECT COUNT(*) FROM activity_sample").fetchone()[0]
    linked = conn.execute(
        "SELECT COUNT(DISTINCT garmin_activity_id) FROM activity_sample "
        "WHERE garmin_activity_id IN (SELECT garmin_activity_id FROM activity WHERE garmin_activity_id IS NOT NULL)"
    ).fetchone()[0]
    unlinked = conn.execute(
        "SELECT COUNT(DISTINCT garmin_activity_id) FROM activity_sample "
        "WHERE garmin_activity_id NOT IN (SELECT garmin_activity_id FROM activity WHERE garmin_activity_id IS NOT NULL)"
    ).fetchone()[0]
    return {"rows": rows, "activities_with_samples": linked, "unlinked_garmin_ids": unlinked}


def samples(conn, activity_id: int) -> List[dict]:
    """Échantillons sous-échantillonnés d'une séance (id INTERNE de `activity`, pas le
    `garmin_activity_id`), triés par `t_s`. Pure lecture, jamais d'exception : une
    séance sans FIT ingéré, ou sans `garmin_activity_id` du tout, rend `[]` — les KPI
    dérivés (zones #43, GAP #44, découplage #45, VAM #46, descente #47, durabilité #48,
    modèle pente→allure #58) peuvent tous tester `if not samples: ...` sans se soucier
    de l'existence du FIT.

    Le lien vers `activity_sample` est résolu ICI, à la lecture, par `garmin_activity_id`
    — jamais mis en cache sur un rowid : voir `ingest_samples` pour le bug que cette
    résolution tardive corrige (rowid réutilisé/instable).
    """
    row = conn.execute("SELECT garmin_activity_id FROM activity WHERE id = ?", (activity_id,)).fetchone()
    if row is None or row["garmin_activity_id"] is None:
        return []
    return samples_by_garmin_id(conn, row["garmin_activity_id"])["samples"]


def samples_by_garmin_id(conn, garmin_activity_id: int) -> dict:
    """Enveloppe JSON-amie, par `garmin_activity_id` (identifiant externe, celui du nom
    de fichier `activities/fit/<id>.json` et du CLI `arc_index.py samples`) — fonctionne
    même SANS activité indexée correspondante (FIT ingéré avant le Markdown) : c'est le
    but de stocker `activity_sample` par `garmin_activity_id` plutôt que par rowid."""
    # `lat`/`lon` INCLUS ici (#49) : cette fonction sert à la fois de lecture INTERNE
    # (`samples()`, réutilisée par `compute_metrics` pour l'appariement de montée,
    # `arc_climb_match.py` — a besoin des positions) et de sortie du CLI `samples`
    # (débogage local d'un fichier `activities/fit/<id>.json` déjà lisible tel quel sur
    # le disque de l'athlète — pas une fuite nouvelle). Ce n'est PAS l'API du tableau de
    # bord (`arc_serve.py`), qui n'appelle jamais cette fonction et ne renvoie jamais de
    # coordonnée (voir `arc_climb_match.ASSUMPTIONS["privacy"]`).
    rows = conn.execute(
        "SELECT t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm, lat AS lat_deg, lon AS lon_deg "
        "FROM activity_sample WHERE garmin_activity_id = ? ORDER BY t_s", (garmin_activity_id,),
    ).fetchall()
    result = {"garmin_activity_id": garmin_activity_id, "samples": [dict(r) for r in rows]}
    if not rows:
        result["reason"] = "aucun échantillon ingéré pour ce garmin_activity_id"
    return result


# ---------------------------------------------------------------------------
# Zones FC, temps en zone, polarisation 80/20 (#43)
# ---------------------------------------------------------------------------


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def athlete_hr_zone_resolution(conn, conf: dict) -> dict:
    """Résolution des zones FC pour ce workspace, AVEC raison explicite en cas
    d'échec (méthode inconnue, méthode forcée mais champ manquant, ou aucune donnée
    du tout) — voir `arc_metrics.hr_zone_resolution` (revue de code #43, point 4 :
    jamais un `None` muet qui masquerait la section côté API/UI)."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    return M.hr_zone_resolution(dict(athlete) if athlete else {}, conf.get("hr_zones"))


def athlete_hr_zone_bounds(conn, conf: dict) -> Optional[Tuple[Tuple[float, ...], str]]:
    """Bornes de zones + méthode effectivement utilisée pour ce workspace — voir
    `arc_metrics.hr_zone_bounds` pour la précédence. `None` si aucune méthode n'est
    calculable (profil sans FC max renseignée, au minimum). Pour un appelant qui a
    besoin de savoir POURQUOI, voir `athlete_hr_zone_resolution`."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    return M.hr_zone_bounds(dict(athlete) if athlete else {}, conf.get("hr_zones"))


def activity_zone_report(conn, conf: dict, garmin_activity_id: int) -> dict:
    """Temps en zone d'une séance (#43), par `garmin_activity_id` — pour la CLI
    (`arc_index.py zones --activity`) et pour les agents en headless. Rend
    `{"garmin_activity_id", "bounds_bpm", "method", "reason", "zone_seconds",
    "polarisation"}` — `reason` est toujours présent (`None` en cas de succès),
    `zone_seconds`/`polarisation` restent `None` si aucune zone n'est calculable, si
    la séance n'existe pas, ou si elle n'a pas d'échantillons ingérés — jamais une
    exception, jamais un échec muet."""
    resolution = athlete_hr_zone_resolution(conn, conf)
    if resolution["bounds_bpm"] is None:
        return {"garmin_activity_id": garmin_activity_id, **resolution, "zone_seconds": None, "polarisation": None}
    act = conn.execute("SELECT id FROM activity WHERE garmin_activity_id = ?", (garmin_activity_id,)).fetchone()
    if act is None:
        return {"garmin_activity_id": garmin_activity_id, **resolution, "reason": "aucune activité indexée pour ce garmin_activity_id",
                "zone_seconds": None, "polarisation": None}
    rows = conn.execute(
        "SELECT zone, seconds FROM hr_zone_time WHERE activity_id = ?", (act["id"],)).fetchall()
    pol_rows = conn.execute(
        "SELECT bucket, seconds FROM hr_polarisation_time WHERE activity_id = ?", (act["id"],)).fetchall()
    if not rows and not pol_rows:
        return {"garmin_activity_id": garmin_activity_id, **resolution,
                "reason": "aucun échantillon FIT ingéré pour cette séance (ou sport hors de la famille "
                          "course à pied, voir ASSUMPTIONS[\"hr_zones\"])",
                "zone_seconds": None, "polarisation": None}
    zone_seconds = {row["zone"]: row["seconds"] for row in rows} if rows else None
    pol_seconds = {row["bucket"]: row["seconds"] for row in pol_rows} if pol_rows else None
    return {
        "garmin_activity_id": garmin_activity_id, **resolution,
        "zone_seconds": zone_seconds, "polarisation": M.polarisation_shares(pol_seconds) if pol_seconds else None,
    }


# ---------------------------------------------------------------------------
# GAP — allure ajustée à la pente (#44)
# ---------------------------------------------------------------------------


def activity_gap_report(conn, garmin_activity_id: int) -> dict:
    """Rapport GAP (#44) d'une séance : allure GAP globale (s/km) + par split, par
    `garmin_activity_id` — pour la CLI (`arc_index.py gap --activity`) et pour
    les agents en headless. Rend TOUJOURS `{"garmin_activity_id", "gap_pace_s_km",
    "splits", "reason"}` (`reason` non nul explique un `None`), jamais une
    exception ni un échec muet (même discipline que `activity_zone_report`,
    #43) : activité introuvable, sport hors de la famille course à pied
    (`arc_metrics.sport_family`), pas d'échantillon FIT ingéré, ou échantillons
    ingérés mais sans altitude exploitable (tapis de course, capteur
    barométrique absent, séance toujours à l'arrêt) sont QUATRE raisons
    distinctes — les deux dernières se ressemblent côté athlète (aucun chiffre
    affiché) mais pointent vers des causes très différentes à corriger."""
    act = conn.execute("SELECT id, sport, gap_pace_s_km FROM activity WHERE garmin_activity_id = ?",
                        (garmin_activity_id,)).fetchone()
    if act is None:
        return {"garmin_activity_id": garmin_activity_id, "gap_pace_s_km": None, "splits": None,
                "reason": "aucune activité indexée pour ce garmin_activity_id"}
    if M.sport_family(act["sport"]) != "run":
        return {"garmin_activity_id": garmin_activity_id, "gap_pace_s_km": None, "splits": None,
                "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                          "arc_gap.ASSUMPTIONS[\"restricted_to_run_family\"]"}
    splits = conn.execute(
        "SELECT km, gap_pace_s_km FROM activity_split WHERE activity_id = ? ORDER BY km", (act["id"],)).fetchall()
    if act["gap_pace_s_km"] is None and not any(s["gap_pace_s_km"] is not None for s in splits):
        sample_count = conn.execute(
            "SELECT COUNT(*) FROM activity_sample WHERE garmin_activity_id = ?", (garmin_activity_id,)
        ).fetchone()[0]
        if sample_count == 0:
            reason = "aucun échantillon FIT ingéré pour cette séance"
        else:
            reason = ("échantillons FIT ingérés, mais aucune pente exploitable (tapis de course, "
                      "capteur barométrique absent, altitude toujours identique, ou vitesse "
                      "toujours sous le seuil de mouvement) — voir arc_gap.ASSUMPTIONS")
        return {"garmin_activity_id": garmin_activity_id, "gap_pace_s_km": None, "splits": None,
                "reason": reason}
    return {"garmin_activity_id": garmin_activity_id, "gap_pace_s_km": act["gap_pace_s_km"],
            "splits": [dict(s) for s in splits], "reason": None}


def weekly_polarisation(conn, weeks: int, today: date) -> List[dict]:
    """Polarisation 80/20 hebdomadaire (#43) des `weeks` dernières semaines (la
    courante incluse), plus ancienne en premier — pour la CLI (`arc_index.py zones
    --weeks`) et pour `/api/load`. Une semaine sans AUCUNE activité à échantillons
    (`hr_polarisation_time` vide sur toute la semaine) rend `polarisation: None` —
    jamais 0 % partout, voir `arc_metrics.ASSUMPTIONS["hr_zones"]`. Lit directement
    les seaux Seiler déjà calculés à l'indexation (bornes dédiées par méthode,
    `arc_metrics.seiler_bounds`) — jamais un regroupement de `hr_zone_time` ici."""
    first = _monday(today) - timedelta(weeks=weeks - 1)
    buckets: Dict[str, Dict[str, float]] = {
        (first + timedelta(weeks=w)).isoformat(): {} for w in range(weeks)
    }
    rows = conn.execute(
        "SELECT a.date AS date, hp.bucket AS bucket, hp.seconds AS seconds "
        "FROM hr_polarisation_time hp JOIN activity a ON a.id = hp.activity_id "
        "WHERE a.date >= ? AND a.date <= ?",
        (first.isoformat(), today.isoformat()),
    ).fetchall()
    for row in rows:
        week_start = _monday(date.fromisoformat(row["date"])).isoformat()
        bucket = buckets.get(week_start)
        if bucket is None:
            continue
        bucket[row["bucket"]] = bucket.get(row["bucket"], 0.0) + row["seconds"]
    out = []
    for week_start in sorted(buckets):
        out.append({"week_start": week_start, "polarisation": M.polarisation_shares(buckets[week_start])})
    return out


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
    for (rel,) in conn.execute("SELECT path FROM source_file").fetchall():
        if rel not in seen:
            _purge(conn, rel)
            conn.execute("DELETE FROM source_file WHERE path = ?", (rel,))
            counts["removed"] += 1
    # Échantillons FIT (#42) — table dédiée `sample_file`, jamais `source_file` (voir
    # `ingest_samples`) : sa propre découverte/nettoyage ne touche donc jamais la boucle
    # ci-dessus. Le rattachement à `activity` n'est plus résolu ICI (il l'était par
    # rowid dans une version antérieure, bug corrigé — voir `samples()`) : l'ordre
    # d'exécution par rapport au passage Markdown n'a donc plus d'importance pour la
    # correction, seulement `sport` (déjà en base pour un fichier réingéré CETTE passe
    # puisque le passage Markdown ci-dessus vient de le (ré)écrire).
    counts["fit_ingestion"] = ingest_samples(conn, workspace)
    compute_metrics(conn, conf, today)
    # `arc_gap.ASSUMPTIONS` (#44) fusionné à celles d'`arc_metrics` : la section
    # « Hypothèses » du tableau de bord (`/api/summary` -> `web/js/app.js`) doit
    # exposer la limite connue du modèle de Minetti (surestimation des fortes
    # descentes) au même titre que les autres approximations du projet — jamais
    # cachée dans un module que cette agrégation oublierait. `arc_decoupling.ASSUMPTIONS`
    # (#45) fusionné à PART, sous des clés préfixées `decoupling_*` (revue de code) :
    # `arc_decoupling` et `arc_gap` partagent des noms de clé (`model`,
    # `stopped_samples`, `restricted_to_run_family`...) qu'un simple `{**G.ASSUMPTIONS,
    # **DC.ASSUMPTIONS}` écraserait silencieusement au lieu d'exposer les deux.
    decoupling_assumptions = {f"decoupling_{key}": value for key, value in DC.ASSUMPTIONS.items()}
    # `arc_climb.ASSUMPTIONS` (#46) fusionné à PART lui aussi, sous des clés
    # préfixées `vam_*` — même raison que `decoupling_*` ci-dessus (collision de
    # noms de clé possible avec `arc_gap`/`arc_decoupling`, ex. "model",
    # "restricted_to_run_family").
    vam_assumptions = {f"vam_{key}": value for key, value in VC.ASSUMPTIONS.items()}
    # `arc_descent.ASSUMPTIONS` (#47) fusionné à PART lui aussi, sous des clés
    # préfixées `descent_*` — même raison que `decoupling_*`/`vam_*` ci-dessus
    # (collision possible, ex. "model", "restricted_to_run_family", "grade_classes").
    descent_assumptions = {f"descent_{key}": value for key, value in DS.ASSUMPTIONS.items()}
    # `arc_durability.ASSUMPTIONS` (#48) fusionné à PART lui aussi, sous des clés
    # préfixées `durability_*` — même raison que `decoupling_*`/`vam_*`/`descent_*`
    # ci-dessus (collision possible, ex. "model", "restricted_to_run_family").
    durability_assumptions = {f"durability_{key}": value for key, value in DU.ASSUMPTIONS.items()}
    for key, value in (("settings", _j(conf)),
                       ("assumptions", _j({**M.ASSUMPTIONS, **G.ASSUMPTIONS, **decoupling_assumptions,
                                           **vam_assumptions, **descent_assumptions,
                                           **durability_assumptions})),
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


# ---------------------------------------------------------------------------
# Découplage aérobie (Pa:HR) et facteur d'efficacité (#45)
# ---------------------------------------------------------------------------


def activity_decoupling_report(conn, garmin_activity_id: int) -> dict:
    """Rapport de découplage aérobie (#45) d'une séance, par `garmin_activity_id` —
    pour la CLI (`arc_index.py decoupling --activity`) et pour les agents en
    headless (`coach`, #51). Lit les colonnes déjà calculées à l'indexation
    (`compute_metrics`), jamais un recalcul à la lecture — même discipline que
    `activity_gap_report` (#44). Rend TOUJOURS `{"garmin_activity_id",
    "decoupling_pct", "ef_whole", "reason"}`, jamais une exception."""
    act = conn.execute(
        "SELECT sport, decoupling_pct, ef_whole, decoupling_reason FROM activity WHERE garmin_activity_id = ?",
        (garmin_activity_id,)).fetchone()
    if act is None:
        return {"garmin_activity_id": garmin_activity_id, "decoupling_pct": None, "ef_whole": None,
                "reason": "aucune activité indexée pour ce garmin_activity_id"}
    if M.sport_family(act["sport"]) != "run":
        return {"garmin_activity_id": garmin_activity_id, "decoupling_pct": None, "ef_whole": None,
                "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                          "arc_decoupling.ASSUMPTIONS[\"restricted_to_run_family\"]"}
    if act["decoupling_pct"] is None and act["decoupling_reason"] is None:
        return {"garmin_activity_id": garmin_activity_id, "decoupling_pct": None, "ef_whole": None,
                "reason": "aucun échantillon FIT ingéré pour cette séance"}
    return {"garmin_activity_id": garmin_activity_id, "decoupling_pct": act["decoupling_pct"],
            "ef_whole": act["ef_whole"], "reason": act["decoupling_reason"]}


def decoupling_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance du découplage aérobie sur les sorties longues (#45) — pour la CLI
    (`arc_index.py decoupling --weeks`) et pour `coach`/le tableau de bord.
    N'est pas soumis à `[health].morning_check` : ne dépend d'aucune donnée de
    santé, seulement des activités déjà indexées. Voir
    `arc_metrics.ASSUMPTIONS`/`arc_decoupling.ASSUMPTIONS`.

    ATTENTION, deux seuils de durée DIFFÉRENTS et NON liés (revue de code) :
    « sortie longue » ici (`duration_s` DÉCLARÉ au contrat ```arc, temps ÉCOULÉ,
    > `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) détermine seulement quelles
    activités ENTRENT dans cette tendance ; l'ÉLIGIBILITÉ au découplage lui-même
    (`arc_decoupling.MIN_MOVING_DURATION_S`, 60 min de MOUVEMENT mesuré sur les
    échantillons FIT) est vérifiée séparément, à l'indexation
    (`compute_metrics`). Une activité de 70 min déclarées peut donc apparaître
    ici avec `decoupling_pct: null` (sortie longue mais pas forcément éligible),
    et une activité de 65 min déclarées mais réellement longue en mouvement
    n'apparaîtra PAS ici du tout (sous le seuil de 90 min de CETTE tendance)
    même si son découplage est parfaitement calculé et visible sur sa fiche
    séance (`/api/activity/<id>`)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, name, duration_s, decoupling_pct, ef_whole FROM activity "
        "WHERE duration_s > ?", (M.LONG_RUN_MIN_DURATION_S,)).fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.DECOUPLING_TREND_WEEKS
    return M.decoupling_trend(rows, today, window_weeks)


# ---------------------------------------------------------------------------
# VAM — montées détectées (#46)
# ---------------------------------------------------------------------------


def activity_climb_report(conn, garmin_activity_id: int) -> dict:
    """Rapport VAM (#46) d'une séance, par `garmin_activity_id` — pour la CLI
    (`arc_index.py vam --activity`) et pour les agents en headless. Lit les
    lignes/colonnes déjà calculées à l'indexation (`compute_metrics`), jamais un
    recalcul à la lecture — même discipline que `activity_gap_report` (#44) et
    `activity_decoupling_report` (#45). Rend TOUJOURS `{"garmin_activity_id",
    "climbs", "vam_best_10min_m_h", "vam_best_20min_m_h", "vam_by_grade_class",
    "best_climb_vam_elapsed_m_h", "reason", "reason_code", "applicable"}`,
    jamais une exception — voir `arc_climb.climb_report` pour la sémantique de
    `reason_code`/`applicable` (#47, revue de code, nit : contrepartie stable,
    non localisée, de `reason`)."""
    empty = {"garmin_activity_id": garmin_activity_id, "climbs": [], "vam_best_10min_m_h": None,
             "vam_best_20min_m_h": None, "vam_by_grade_class": {}, "best_climb_vam_elapsed_m_h": None}
    act = conn.execute(
        "SELECT id, sport, best_vam_10min_m_h, best_vam_20min_m_h, best_climb_vam_elapsed_m_h "
        "FROM activity WHERE garmin_activity_id = ?", (garmin_activity_id,)).fetchone()
    if act is None:
        return {**empty, "reason": "aucune activité indexée pour ce garmin_activity_id",
                "reason_code": "unknown_activity", "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                                    "arc_climb.ASSUMPTIONS[\"restricted_to_run_family\"]",
                "reason_code": "not_run_family", "applicable": False}
    sample_count = conn.execute(
        "SELECT COUNT(*) FROM activity_sample WHERE garmin_activity_id = ?", (garmin_activity_id,)
    ).fetchone()[0]
    if sample_count == 0:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance",
                "reason_code": "no_samples", "applicable": True}
    climbs = [dict(r) for r in conn.execute(
        "SELECT idx AS \"index\", start_t_s, end_t_s, start_km, end_km, distance_m, gain_m, avg_grade, "
        "grade_class, duration_elapsed_s, duration_moving_s, vam_elapsed_m_h, vam_moving_m_h, segment_id, "
        "hr_first_third_bpm, hr_last_third_bpm, hr_drift_bpm_per_100m, vs_previous_pct, vs_best_pct "
        "FROM activity_climb WHERE activity_id = ? ORDER BY idx", (act["id"],)).fetchall()]
    return {
        "garmin_activity_id": garmin_activity_id,
        "climbs": climbs,
        "vam_best_10min_m_h": act["best_vam_10min_m_h"],
        "vam_best_20min_m_h": act["best_vam_20min_m_h"],
        "vam_by_grade_class": VC.vam_by_grade_class(climbs),
        "best_climb_vam_elapsed_m_h": act["best_climb_vam_elapsed_m_h"],
        "reason": None,
        "reason_code": None,
        "applicable": True,
    }


# ---------------------------------------------------------------------------
# Identité de montée entre séances — historique par segment (#49)
# ---------------------------------------------------------------------------


def climb_segment_list(conn) -> List[dict]:
    """Segments connus (#49, `arc_climb_match.py`), pour `/api/climb-segments` et le CLI
    `climb-history` sans argument — jamais de position GPS exposée ici (voir
    `arc_climb_match.ASSUMPTIONS["privacy"]`), seulement le lieu déclaré et la
    signature de profil. Triés par occurrences décroissantes (les montées les plus
    régulièrement gravies d'abord), puis par id pour un ordre stable à égalité."""
    return [dict(r) for r in conn.execute(
        "SELECT id AS segment_id, location, gain_m, distance_m, avg_grade, grade_class, occurrences, "
        "best_time_elapsed_s, best_activity_id, first_seen_activity_id, first_seen_date "
        "FROM climb_segment ORDER BY occurrences DESC, id").fetchall()]


def climb_segment_history(conn, segment_id: int) -> dict:
    """Historique complet d'un segment (#49) : chaque occurrence (date, activité,
    temps écoulé/mouvement, VAM, FC, dérive, progression vs précédent/meilleur déjà
    calculés à l'indexation) — pour `/api/climb-segment/<id>` et le CLI `climb-history
    --segment ID`. Rend TOUJOURS un dict, jamais `None` (même discipline que les autres
    rapports de l'épopée) : `reason`/`reason_code` explicites si le segment est
    inconnu — un id de segment n'est PAS stable d'une réindexation à l'autre (voir la
    table `climb_segment`), un id périmé est donc un cas attendu, pas une erreur de
    programmation."""
    seg = conn.execute(
        "SELECT id AS segment_id, location, gain_m, distance_m, avg_grade, grade_class, occurrences, "
        "best_time_elapsed_s, best_activity_id, first_seen_activity_id, first_seen_date "
        "FROM climb_segment WHERE id = ?", (segment_id,)).fetchone()
    if seg is None:
        return {"segment_id": segment_id, "segment": None, "occurrences": [],
                "reason": "segment inconnu (id périmé — les ids de climb_segment ne sont pas stables "
                          "d'une réindexation à l'autre, voir arc_index.DDL)",
                "reason_code": "unknown_segment", "applicable": True}
    rows = conn.execute(
        "SELECT ac.activity_id, a.date, a.name, ac.start_km, ac.end_km, ac.duration_elapsed_s, "
        "ac.duration_moving_s, ac.vam_elapsed_m_h, ac.vam_moving_m_h, ac.hr_first_third_bpm, "
        "ac.hr_last_third_bpm, ac.hr_drift_bpm_per_100m, ac.vs_previous_pct, ac.vs_best_pct "
        "FROM activity_climb ac JOIN activity a ON a.id = ac.activity_id "
        "WHERE ac.segment_id = ? ORDER BY a.date, ac.activity_id", (segment_id,)).fetchall()
    return {"segment_id": segment_id, "segment": dict(seg), "occurrences": [dict(r) for r in rows],
            "reason": None, "reason_code": None, "applicable": True}


def vam_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance de la VAM sur les montées détectées (#46) — pour la CLI
    (`arc_index.py vam --weeks`) et pour `coach`/le tableau de bord. Voir
    `arc_metrics.vam_trend`/`arc_climb.ASSUMPTIONS` — AUCUN seuil de durée
    minimale (contrairement à `decoupling_trend`) : une montée peut être
    détectée sur une sortie courte."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, name, best_vam_10min_m_h, best_vam_20min_m_h, best_climb_vam_elapsed_m_h "
        "FROM activity").fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.VAM_TREND_WEEKS
    return M.vam_trend(rows, today, window_weeks)


# ---------------------------------------------------------------------------
# Efficacité en descente — par classe de pente (#47)
# ---------------------------------------------------------------------------


def activity_descent_report(conn, garmin_activity_id: int) -> dict:
    """Rapport d'efficacité en descente (#47) d'une séance, par
    `garmin_activity_id` — pour la CLI (`arc_index.py descent --activity`) et
    pour les agents en headless. Lit les lignes/colonnes déjà calculées à
    l'indexation (`compute_metrics`), jamais un recalcul à la lecture — même
    discipline que `activity_climb_report` (#46). Rend TOUJOURS
    `{"garmin_activity_id", "classes", "reference_gap_pace_s_km",
    "reference_source", "reason", "reason_code", "applicable"}`, jamais une
    exception — voir `arc_descent.descent_report` pour la sémantique de
    `reason_code`/`applicable` (contrepartie stable, non localisée, de
    `reason`)."""
    empty = {"garmin_activity_id": garmin_activity_id, "classes": {}, "reference_gap_pace_s_km": None,
              "reference_source": None}
    act = conn.execute(
        "SELECT id, sport, descent_reference_gap_pace_s_km, descent_reference_source FROM activity "
        "WHERE garmin_activity_id = ?", (garmin_activity_id,)).fetchone()
    if act is None:
        return {**empty, "reason": DS.REASON_UNKNOWN_ACTIVITY, "reason_code": "unknown_activity",
                "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": DS.REASON_NOT_RUN_FAMILY, "reason_code": "not_run_family",
                "applicable": False}
    sample_count = conn.execute(
        "SELECT COUNT(*) FROM activity_sample WHERE garmin_activity_id = ?", (garmin_activity_id,)
    ).fetchone()[0]
    if sample_count == 0:
        return {**empty, "reason": DS.REASON_NO_SAMPLES, "reason_code": "no_samples", "applicable": True}
    rows = {r["grade_class"]: dict(r) for r in conn.execute(
        "SELECT grade_class, count, duration_moving_s, distance_m, mean_speed_ms, mean_pace_s_km, "
        "mean_gap_speed_ms, mean_grade, efficiency FROM activity_descent_class WHERE activity_id = ?",
        (act["id"],)).fetchall()}
    # Ordre `DESCENT_GRADE_CLASSES` (croissant), jamais un ordre SQL arbitraire sur
    # une colonne texte (qui trierait "-10 à -15 %" avant "-5 à -10 %" alphabétiquement)
    # — même discipline que `arc_climb.vam_by_grade_class`/l'UI (`GRADE_CLASS_ORDER`).
    classes = {label: {k: v for k, v in rows[label].items() if k != "grade_class"}
               for _lo, _hi, label in DS.DESCENT_GRADE_CLASSES if label in rows}
    reason = reason_code = None
    if not classes:
        if act["descent_reference_gap_pace_s_km"] is None:
            reason, reason_code = DS.REASON_NO_REFERENCE, "no_reference"
        else:
            reason, reason_code = DS.REASON_NO_QUALIFYING_CLASS, "no_qualifying_class"
    return {
        "garmin_activity_id": garmin_activity_id,
        "classes": classes,
        "reference_gap_pace_s_km": act["descent_reference_gap_pace_s_km"],
        "reference_source": act["descent_reference_source"],
        "reason": reason,
        "reason_code": reason_code,
        "applicable": True,
    }


def descent_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance de l'efficacité en descente (#47) — pour la CLI
    (`arc_index.py descent --weeks`) et pour `coach`/le tableau de bord. Voir
    `arc_metrics.descent_trend`/`arc_descent.ASSUMPTIONS` — AUCUN seuil de durée
    minimale sur la séance (comme `vam_trend`), seul le seuil PAR CLASSE
    (déjà appliqué à l'indexation) filtre les lignes. `a.id AS activity_id`
    (revue de code, should-fix 3) : la clé de regroupement PAR ACTIVITÉ de
    `arc_metrics.descent_trend` doit être l'id, jamais `(date, name, sport)` —
    deux séances distinctes le même jour au même nom générique (« Trail »,
    par exemple, deux sorties bi-quotidiennes) se seraient sinon vues fusionnées
    à tort en une seule. `a.descent_reference_source AS reference_source`
    (revue de code, should-fix) : la référence `"flat"` et son repli
    `"non_descent"` (voir `arc_descent.ASSUMPTIONS["reference"]`) ne sont PAS
    sur la même échelle (mesuré : 0,664 en `flat` vs 0,548 en `non_descent`
    pour la MÊME descente) — la tendance doit pouvoir distinguer les deux,
    jamais les mélanger sans le dire (une séance sans plat suffisant
    apparaîtrait sinon comme une chute d'efficacité)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT a.id AS activity_id, a.date AS date, a.sport AS sport, a.name AS name, "
        "a.descent_reference_source AS reference_source, dc.grade_class AS grade_class, "
        "dc.efficiency AS efficiency, dc.mean_pace_s_km AS mean_pace_s_km, "
        "dc.mean_grade AS mean_grade FROM activity_descent_class dc "
        "JOIN activity a ON a.id = dc.activity_id").fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.DESCENT_TREND_WEEKS
    return M.descent_trend(rows, today, window_weeks)


# ---------------------------------------------------------------------------
# Durabilité sur les sorties longues (#48)
# ---------------------------------------------------------------------------


def activity_durability_report(conn, garmin_activity_id: int) -> dict:
    """Rapport de durabilité (#48) d'une séance, par `garmin_activity_id` — pour
    la CLI (`arc_index.py durability --activity`) et pour les agents en
    headless. Lit les colonnes déjà calculées à l'indexation
    (`compute_metrics`), jamais un recalcul à la lecture — même discipline que
    `activity_decoupling_report` (#45)/`activity_gap_report` (#44). Rend
    TOUJOURS `{"garmin_activity_id", "gap_fade_pct", "ef_fade_pct",
    "hr_first_third_bpm", "hr_middle_third_bpm", "hr_last_third_bpm", "reason",
    "reason_code", "applicable"}`, jamais une exception — voir
    `arc_durability.durability_report` pour la sémantique de
    `reason_code`/`applicable` (contrepartie stable, non localisée, de
    `reason`)."""
    empty = {"garmin_activity_id": garmin_activity_id, "gap_fade_pct": None, "ef_fade_pct": None,
              "hr_first_third_bpm": None, "hr_middle_third_bpm": None, "hr_last_third_bpm": None}
    act = conn.execute(
        "SELECT sport, durability_gap_fade_pct, durability_ef_fade_pct, durability_hr_first_third_bpm, "
        "durability_hr_middle_third_bpm, durability_hr_last_third_bpm, durability_reason, "
        "durability_reason_code FROM activity WHERE garmin_activity_id = ?",
        (garmin_activity_id,)).fetchone()
    if act is None:
        return {**empty, "reason": DU.REASON_UNKNOWN_ACTIVITY, "reason_code": "unknown_activity",
                "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": DU.REASON_NOT_RUN_FAMILY, "reason_code": "not_run_family",
                "applicable": False}
    if act["durability_gap_fade_pct"] is None and act["durability_reason"] is None:
        return {**empty, "reason": DU.REASON_NO_SAMPLES, "reason_code": "no_samples", "applicable": True}
    return {
        "garmin_activity_id": garmin_activity_id,
        "gap_fade_pct": act["durability_gap_fade_pct"],
        "ef_fade_pct": act["durability_ef_fade_pct"],
        "hr_first_third_bpm": act["durability_hr_first_third_bpm"],
        "hr_middle_third_bpm": act["durability_hr_middle_third_bpm"],
        "hr_last_third_bpm": act["durability_hr_last_third_bpm"],
        "reason": act["durability_reason"],
        "reason_code": act["durability_reason_code"],
        "applicable": True,
    }


def durability_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance de durabilité (#48) — pour la CLI (`arc_index.py durability
    --weeks`) et pour `coach`/le tableau de bord. Voir
    `arc_metrics.durability_trend`/`arc_durability.ASSUMPTIONS` : sorties
    longues (`moving_duration_s` déclaré, à défaut `duration_s` écoulé, >
    `arc_metrics.LONG_RUN_MIN_DURATION_S`) de la famille course à pied.
    `id AS activity_id` (revue de code #48, should-fix 3, cohérence avec
    `descent_trend`) : clé de regroupement stable, jamais `(date, name,
    sport)`. Aucun `WHERE` sur la durée ICI (contrairement à `api_decoupling`) :
    le filtrage précis (moving_duration_s OU duration_s) est fait en Python par
    `arc_metrics.durability_trend`, qui a besoin des DEUX colonnes pour
    appliquer son repli — un `WHERE duration_s > ?` exclurait à tort une
    activité dont seul `moving_duration_s` dépasse le seuil."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id AS activity_id, date, sport, name, duration_s, moving_duration_s, "
        "durability_gap_fade_pct, durability_ef_fade_pct, durability_hr_first_third_bpm, "
        "durability_hr_middle_third_bpm, durability_hr_last_third_bpm, durability_reason, "
        "durability_reason_code FROM activity").fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.DURABILITY_TREND_WEEKS
    return M.durability_trend(rows, today, window_weeks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", default="index",
                        choices=("index", "backfill-plan", "status", "hrv-baseline", "sleep-debt",
                                 "heat-acclimation", "gear", "fueling", "samples", "zones", "gap",
                                 "decoupling", "vam", "descent", "durability", "climb-history"))
    parser.add_argument("selector", nargs="?", default=None,
                        help="argument de la sous-commande (ex. garmin_activity_id pour « samples »)")
    parser.add_argument("--workspace")
    parser.add_argument("--db")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--today", help="date de fin des séries (AAAA-MM-JJ)")
    parser.add_argument("--validate", nargs="+", metavar="FICHIER")
    parser.add_argument("--activity", type=int, metavar="GARMIN_ID",
                        help="commande « zones »/« gap »/« decoupling »/« vam »/« descent »/« durability » : "
                             "temps en zone, GAP, découplage, montées/VAM, efficacité en descente ou "
                             "durabilité d'une séance (garmin_activity_id)")
    parser.add_argument("--weeks", type=int, metavar="N",
                        help="commande « zones »/« decoupling »/« vam »/« descent »/« durability » : "
                             "polarisation ou tendance sur les N dernières semaines (défaut 8 pour "
                             "« zones », 12 pour « decoupling »/« vam »/« descent »/« durability »)")
    parser.add_argument("--segment", type=int, metavar="SEGMENT_ID",
                        help="commande « climb-history » : historique complet d'un segment (#49)")
    parser.add_argument("--with-gps", action="store_true",
                        help="commande « samples » : inclut lat_deg/lon_deg dans la sortie "
                             "(désactivé par défaut depuis #49 — débogage GPS local uniquement)")
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
        result = samples_by_garmin_id(conn, garmin_id)
        # `--with-gps` (#49, revue de code, nit) : lat_deg/lon_deg RETIRÉS par défaut de la
        # sortie CLI — même si la position n'est pas une fuite nouvelle en soi (déjà lisible
        # dans le fichier `activities/fit/<id>.json` source, voir `samples_by_garmin_id`),
        # un CLI copié/collé sans y penser (log, chat de support) ne doit pas se mettre à
        # exposer une coordonnée qu'il n'exposait jamais avant #49 — sécurité par défaut.
        if not args.with_gps:
            for rec in result.get("samples", []):
                rec.pop("lat_deg", None)
                rec.pop("lon_deg", None)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "zones":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        if args.activity is not None:
            print(json.dumps(activity_zone_report(conn, conf, args.activity), ensure_ascii=False))
            return 0
        weeks = args.weeks if args.weeks and args.weeks > 0 else 8
        result = {
            **athlete_hr_zone_resolution(conn, conf),
            "weekly_polarisation": weekly_polarisation(conn, weeks, today_date),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "gap":
        garmin_id = args.activity if args.activity is not None else (int(args.selector) if args.selector else None)
        if garmin_id is None:
            raise ConfigError("commande « gap » : garmin_activity_id attendu "
                               "(--activity ou argument positionnel, ex. arc_index.py gap 19287537093).")
        print(json.dumps(activity_gap_report(conn, garmin_id), ensure_ascii=False))
        return 0
    if args.command == "decoupling":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        garmin_id = args.activity if args.activity is not None else (int(args.selector) if args.selector else None)
        if garmin_id is not None:
            print(json.dumps(activity_decoupling_report(conn, garmin_id), ensure_ascii=False))
            return 0
        print(json.dumps(decoupling_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "vam":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        garmin_id = args.activity if args.activity is not None else (int(args.selector) if args.selector else None)
        if garmin_id is not None:
            print(json.dumps(activity_climb_report(conn, garmin_id), ensure_ascii=False))
            return 0
        print(json.dumps(vam_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "descent":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        garmin_id = args.activity if args.activity is not None else (int(args.selector) if args.selector else None)
        if garmin_id is not None:
            print(json.dumps(activity_descent_report(conn, garmin_id), ensure_ascii=False))
            return 0
        print(json.dumps(descent_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "durability":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        garmin_id = args.activity if args.activity is not None else (int(args.selector) if args.selector else None)
        if garmin_id is not None:
            print(json.dumps(activity_durability_report(conn, garmin_id), ensure_ascii=False))
            return 0
        print(json.dumps(durability_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "climb-history":
        # #49 : `--segment ID` prime (historique direct d'un segment) ; sinon `--activity
        # GARMIN_ID` (ou l'argument positionnel, même convention que les autres
        # sous-commandes) rend l'historique de CHAQUE segment gravi par cette activité ;
        # sans argument, la liste de tous les segments connus (résumé, jamais l'historique
        # complet de chacun — trop volumineux pour un usage courant).
        if args.segment is not None:
            print(json.dumps(climb_segment_history(conn, args.segment), ensure_ascii=False))
            return 0
        garmin_id = args.activity if args.activity is not None else (int(args.selector) if args.selector else None)
        if garmin_id is not None:
            act_row = conn.execute(
                "SELECT id FROM activity WHERE garmin_activity_id = ?", (garmin_id,)).fetchone()
            if act_row is None:
                print(json.dumps({"activity_id": None, "segments": [],
                                   "reason": "aucune activité indexée pour ce garmin_activity_id",
                                   "reason_code": "unknown_activity"}, ensure_ascii=False))
                return 0
            seg_ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT segment_id FROM activity_climb WHERE activity_id = ? "
                "AND segment_id IS NOT NULL", (act_row[0],)).fetchall()]
            print(json.dumps(
                {"activity_id": act_row[0], "segments": [climb_segment_history(conn, sid) for sid in seg_ids]},
                ensure_ascii=False))
            return 0
        print(json.dumps({"segments": climb_segment_list(conn)}, ensure_ascii=False))
        return 0
    if args.command == "status":
        by_status = {row[0]: row[1] for row in conn.execute(
            "SELECT parsed_ok, COUNT(*) FROM source_file WHERE kind IS NOT NULL GROUP BY parsed_ok")}
        print(json.dumps({
            "workspace": str(workspace), **counts, "files": by_status,
            "samples": sample_coverage(conn),
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
