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
    "get_scheduled_workouts": [],
    "get_calendar_events": [],
    "get_workouts": [],
    "get_courses": [],
}

TOOLS = [
    ("get_hrv_data", "Variabilité de fréquence cardiaque nocturne pour une date."),
    ("get_rhr_day", "Fréquence cardiaque de repos pour une date."),
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
