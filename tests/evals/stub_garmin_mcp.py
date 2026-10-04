#!/usr/bin/env python3
"""Serveur MCP « garmin » factice, pour le palier C.

Rend les évals hermétiques et vérifiables :

- **hermétiques** — aucun compte Garmin, aucun réseau, des données synthétiques
  et stables, donc un scénario tourne chez n'importe qui ;
- **vérifiables** — chaque appel d'outil est journalisé dans `$ARC_TOOL_LOG`.
  « Le coach a-t-il cherché la HRV ? » devient une assertion sur un fichier au
  lieu d'une devinette sur du texte. C'est ce qui permet de tester
  `[health].morning_check = "off"` pour de bon : le point n'est pas que l'agent
  évite le mot « HRV », c'est qu'il n'aille pas la chercher.

**Scriptable par cas d'éval (#26)** — un cas peut déclarer, dans son
`[stub.garmin.<outil>]` :

- `file = "…json"` : sert ce fichier tel quel comme `content` de l'appel, au
  lieu de la donnée canned. Résolu dans `tests/evals/fixtures/stub-responses/`
  (choix documenté dans `fixtures/README.md`).
- `error = "401"` : imite un token Garmin expiré (voir
  `mcp_stub_common.auth_expired_text`).
- `error = "timeout"` (+ `delay = <secondes>`, défaut 2s, borne dure 10s via
  `ARC_STUB_TIMEOUT_CAP`) : l'appel ne reçoit aucune réponse.
- `error = "empty"` : rend une liste/dict vide de la même forme que la donnée
  canned (utile pour « aucune activité récente », etc.).

Un cas sans section `[stub]` se comporte exactement comme avant #26 : c'est
`mcp_stub_common.load_stub_config` qui rend un dict vide dans ce cas.

JSON-RPC 2.0 sur stdin/stdout, une requête par ligne. Bibliothèque standard.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_stub_common as common

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

TODAY = date.today()


def _day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


# Données synthétiques : un athlète reposé, sans signal d'alerte. Les scénarios
# qui ont besoin d'autre chose le posent dans leurs fixtures Markdown, ou
# scriptent `[stub.garmin.<outil>]` pour ce cas précis (#26).
CANNED = {
    "get_hrv_data": {
        "date": _day(0), "lastNightAvg": 62, "lastNight5MinHigh": 78,
        "status": "BALANCED", "baseline": {"lowUpper": 48, "balancedLow": 52, "balancedUpper": 74},
    },
    "get_rhr_day": {"date": _day(0), "restingHeartRate": 49},
    # Story #65 (`/coach-setup` pré-rempli), revue de code : noms de champs
    # vérifiés contre le paquet `garmin_mcp` réellement installé (0.1.0).
    # `get_stats().max_heart_rate_bpm`/`resting_heart_rate_bpm` sont des
    # valeurs DU JOUR (187/47, volontairement différentes de tout ce qu'un
    # pré-remplissage doit écrire) — jamais utilisées pour « FC max »/« FC de
    # repos » : seul `last_7_days_avg_resting_hr` (moyenne 7 j) sert de FC de
    # repos, et la FC max vient du maximum observé sur `get_activities_by_date`
    # (ci-dessous), jamais de `get_stats`.
    "get_stats": {
        "date": _day(0), "max_heart_rate_bpm": 187, "resting_heart_rate_bpm": 47,
        "last_7_days_avg_resting_hr": 48,
    },
    # 7 séances dont le `type` CONTIENT « run » (running, trail_running, ET
    # treadmill_running — le skill filtre sur la SOUS-CHAÎNE « run », pas sur
    # un ensemble figé de deux valeurs, pour couvrir aussi track_running,
    # ultra_run, etc., revue de code #112, 2ᵉ tour) sur les 180 derniers jours
    # (N ≥ 5, seuil du skill) + 1 séance vélo à FC volontairement la PLUS
    # HAUTE de toutes (192) pour prouver que le filtre exclut bien ce qui ne
    # contient pas « run » — si le maximum retenu était 192, le filtre serait
    # cassé (ou absent). `treadmill_running` (183) porte le vrai maximum
    # attendu, volontairement PLUS HAUT que `trail_running` (178) : un filtre
    # qui ne reconnaîtrait que l'ensemble figé `{running, trail_running}`
    # (comportement d'avant la revue de code) manquerait cette séance et
    # rendrait 178 au lieu de 183 — le cas d'éval `setup-prefill-garmin`
    # attend explicitement 183.
    "get_activities_by_date": {
        "count": 8, "page": 0, "page_size": 100, "has_more": False,
        "date_range": {"start": _day(180), "end": _day(0)},
        "activities": [
            {"id": 99000010, "name": "Footing", "type": "running", "start_time": f"{_day(9)} 07:05:00",
             "distance_meters": 8200.0, "duration_seconds": 2700.0, "avg_hr_bpm": 138, "max_hr_bpm": 165},
            {"id": 99000011, "name": "Sortie trail", "type": "trail_running", "start_time": f"{_day(16)} 08:10:00",
             "distance_meters": 18000.0, "duration_seconds": 7200.0, "avg_hr_bpm": 145, "max_hr_bpm": 178},
            {"id": 99000012, "name": "Fractionné", "type": "running", "start_time": f"{_day(23)} 18:30:00",
             "distance_meters": 9500.0, "duration_seconds": 2400.0, "avg_hr_bpm": 152, "max_hr_bpm": 172},
            {"id": 99000013, "name": "Footing", "type": "running", "start_time": f"{_day(30)} 07:00:00",
             "distance_meters": 7800.0, "duration_seconds": 2550.0, "avg_hr_bpm": 136, "max_hr_bpm": 160},
            {"id": 99000014, "name": "Sortie trail", "type": "trail_running", "start_time": f"{_day(37)} 08:00:00",
             "distance_meters": 15500.0, "duration_seconds": 6300.0, "avg_hr_bpm": 143, "max_hr_bpm": 168},
            {"id": 99000015, "name": "Footing", "type": "running", "start_time": f"{_day(44)} 07:15:00",
             "distance_meters": 8000.0, "duration_seconds": 2650.0, "avg_hr_bpm": 135, "max_hr_bpm": 158},
            {"id": 99000017, "name": "Séance tapis", "type": "treadmill_running", "start_time": f"{_day(5)} 12:20:00",
             "distance_meters": 9000.0, "duration_seconds": 2400.0, "avg_hr_bpm": 160, "max_hr_bpm": 183},
            {"id": 99000016, "name": "Home trainer", "type": "cycling", "start_time": f"{_day(12)} 19:00:00",
             "distance_meters": 25000.0, "duration_seconds": 3000.0, "avg_hr_bpm": 150, "max_hr_bpm": 192},
        ],
    },
    # `is_stale` volontairement absent : dans le vrai outil, il vient de la
    # section puissance/FTP (`power.get("isStale")`), jamais de la FC/vitesse
    # au seuil — l'inclure ici referait croire qu'il qualifie la LTHR (revue
    # de code #112, 2ᵉ tour).
    "get_lactate_threshold": {
        "lactate_threshold_speed_mps": 3.42, "lactate_threshold_heart_rate_bpm": 168,
        "speed_hr_date": _day(5),
    },
    "get_training_status": {
        "date": _day(0), "training_status": "PRODUCTIVE", "vo2_max": 52.0, "vo2_max_precise": 52.3,
    },
    "get_training_readiness": [{
        "date": _day(0), "score": 71, "level": "READY",
        "sleepScore": 78, "sleepScoreFactorFeedback": "GOOD",
        "hrvFactorPercent": 64, "recoveryTime": 6, "acuteLoad": 312,
    }],
    "get_sleep_data": {
        "date": _day(0), "sleepTimeSeconds": 25800,
        "sleepStartTimestampLocal": f"{_day(1)}T23:10:00.0",
        "sleepEndTimestampLocal": f"{_day(0)}T06:20:00.0", "sleepScore": 78,
    },
    "get_activities": [{
        "activityId": 99000001, "activityName": "Sortie longue",
        "startTimeLocal": f"{_day(2)} 12:05:00",
        "activityType": {"typeKey": "trail_running"},
        "distance": 24800.0, "duration": 9660.0, "elevationGain": 890.0,
        "averageHR": 141, "maxHR": 168, "recovery_hr_bpm": 28,
    }],
    # #133 — matériel. Formes vérifiées dans `garmin_mcp/gear_management.py` (Taxuspt/garmin_mcp,
    # ref épinglée `GARMIN_MCP_REF`) : `get_gear` rend `{gear_count, active_count, retired_count,
    # defaults, gear: [{uuid, name, full_name, type, status, date_begin, date_end, max_distance_km?,
    # is_default_for?, stats?}]}` ; `get_activity_gear` rend la liste brute de `garminconnect`
    # (`uuid`, `displayName`, `customMakeModel`, `gearTypeName`, `gearStatusName`…) ou, sans matériel
    # attaché, le TEXTE BRUT (non JSON) « No gear data found for activity with ID N ». `defaults` /
    # `is_default_for` : noms de `ACTIVITY_TYPE_MAPPING` (« Running », « Hiking »…, `activity_<pk>`
    # pour un pk inconnu), jamais les `typeKey` de `get_activities` (`trail_running`). Par défaut : aucun matériel
    # attaché (les cas qui en ont besoin scriptent `[stub.garmin.get_activity_gear]`).
    "get_gear": {
        "gear_count": 2, "active_count": 2, "retired_count": 0,
        "defaults": {"Running": "Nike Pegasus", "Hiking": "Salomon S/Lab"},
        "gear": [
            {"uuid": "a1b2c3d4e5f60718293a4b5c6d7e8f90", "name": "Nike Pegasus", "full_name": "Nike Pegasus 41",
             "type": "Shoes", "status": "active", "date_begin": "2026-01-10", "date_end": None,
             "max_distance_km": 700.0, "is_default_for": ["Running"]},
            {"uuid": "0f9e8d7c6b5a49382716f5e4d3c2b1a0", "name": "Salomon S/Lab", "full_name": "Salomon S/Lab Ultra 3",
             "type": "Shoes", "status": "active", "date_begin": "2026-03-01", "date_end": None,
             "max_distance_km": 600.0, "is_default_for": ["Hiking"]},
        ],
    },
    "get_activity_gear": "No gear data found for activity with ID 99000001",
    "get_scheduled_workouts": [],
    "get_calendar_events": [],
    "get_workouts": [],
    "get_courses": [],
}

TOOLS = [
    ("get_hrv_data", "Variabilité de fréquence cardiaque nocturne pour une date."),
    ("get_rhr_day", "Fréquence cardiaque de repos pour une date."),
    ("get_stats", "Statistiques quotidiennes (dont FC max/repos du jour) pour une date."),
    ("get_lactate_threshold", "Dernier seuil lactique (FC, vitesse, puissance)."),
    ("get_training_status", "Statut d'entraînement (dont VO2max) pour une date."),
    ("get_training_readiness", "Score de readiness et ses facteurs pour une date."),
    ("get_sleep_data", "Données de sommeil détaillées pour une date."),
    ("get_activities", "Dernières activités enregistrées."),
    ("get_activities_by_date", "Activités entre deux dates."),
    ("get_activity", "Détail d'une activité."),
    ("get_activity_splits", "Splits d'une activité."),
    ("get_scheduled_workouts", "Séances planifiées entre deux dates."),
    ("get_calendar_events", "Événements du calendrier Garmin."),
    ("get_workouts", "Séances enregistrées."),
    ("get_workout_by_id", "Détail d'une séance."),
    ("get_courses", "Parcours enregistrés."),
    ("get_gear", "Inventaire du matériel Garmin Connect (include_stats optionnel)."),
    ("get_activity_gear", "Matériel attaché à une activité (activity_id)."),
    ("add_gear_to_activity", "Attache un matériel à une activité — ÉCRITURE côté Garmin."),
    # #167 — journal alimentaire / hydratation (opt-in `[nutrition].garmin_sync`). Noms et formes
    # vérifiés dans `garmin_mcp/nutrition.py`, `data_management.py`, `health_wellness.py` (ref épinglée).
    ("get_custom_foods", "Aliments personnalisés (search, start, limit)."),
    ("get_nutrition_daily_food_log", "Journal alimentaire d'une date."),
    ("get_hydration_data", "Hydratation d'une date."),
    ("create_custom_food", "Crée un aliment personnalisé — ÉCRITURE côté Garmin."),
    ("log_custom_food", "Journalise un aliment personnalisé — ÉCRITURE côté Garmin."),
    ("log_food", "Quick Add au journal alimentaire — ÉCRITURE côté Garmin."),
    ("add_hydration_data", "Ajoute de l'hydratation — ÉCRITURE côté Garmin."),
    ("schedule_workouts", "Planifie des séances dans le calendrier Garmin."),
    ("schedule_week", "Planifie une semaine de séances."),
    ("upload_workout", "Téléverse une séance."),
    ("upload_course", "Téléverse un parcours."),
    ("delete_workout", "Supprime une séance."),
    ("unschedule_workout", "Retire une séance du calendrier."),
]


def result_for(name: str, arguments: dict):
    if name in CANNED:
        return CANNED[name]
    # #167 : textes bruts réels de garmin-mcp pour « rien » ; écritures = accusés plausibles.
    if name == "get_custom_foods":
        return "No custom foods found."
    if name == "get_nutrition_daily_food_log":
        return f"No food log data found for {arguments.get('date')}."
    if name == "get_hydration_data":
        return f"No hydration data found for {arguments.get('date')}"
    if name == "create_custom_food":
        return {"foodMetaData": {"foodId": "f0e1d2c3b4a5968778695a4b3c2d1e0f", "foodName": arguments.get("food_name")},
                "nutritionContents": [{"servingId": "1a2b3c4d5e6f70819293a4b5c6d7e8f9"}], "stub": True}
    if name in ("log_custom_food", "log_food"):
        return "Food logged successfully."
    if name == "add_hydration_data":
        return {"stub": True, "value_in_ml": arguments.get("value_in_ml"), "cdate": arguments.get("cdate")}
    if name == "add_gear_to_activity":
        return {"success": True, "stub": True, "activity_id": arguments.get("activity_id"),
                "gear_uuid": arguments.get("gear_uuid")}
    if name.startswith(("schedule_", "upload_", "delete_", "unschedule_")):
        return {"status": "ok", "stub": True, "tool": name, "received": arguments}
    return {"status": "ok", "stub": True, "tool": name, "data": []}


def main() -> int:
    handle = common.make_handler(
        server_name="garmin", tools=TOOLS, result_for=result_for, fixtures_dir=FIXTURES_DIR,
    )
    return common.serve(handle)


if __name__ == "__main__":
    raise SystemExit(main())
