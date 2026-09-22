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

JSON-RPC 2.0 sur stdin/stdout, une requête par ligne. Bibliothèque standard.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

PROTOCOL_VERSION = "2024-11-05"

TODAY = date.today()


def _day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


# Données synthétiques : un athlète reposé, sans signal d'alerte. Les scénarios
# qui ont besoin d'autre chose le posent dans leurs fixtures Markdown.
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


def log_call(name: str, arguments: dict) -> None:
    path = os.environ.get("ARC_TOOL_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=False) + "\n")
    except OSError:
        pass                       # journaliser ne doit jamais casser le serveur


def result_for(name: str, arguments: dict):
    if name in CANNED:
        return CANNED[name]
    if name.startswith(("schedule_", "upload_", "delete_", "unschedule_")):
        return {"status": "ok", "stub": True, "tool": name, "received": arguments}
    return {"status": "ok", "stub": True, "tool": name, "data": []}


def handle(request: dict):
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "garmin-stub", "version": "0.1.0"},
        }
    if method == "tools/list":
        return {"tools": [
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            }
            for name, description in TOOLS
        ]}
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        log_call(name, arguments)
        payload = result_for(name, arguments)
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
    if method in ("ping", "notifications/initialized"):
        return {} if request_id is not None else None
    if request_id is None:
        return None                # notification inconnue : rien à répondre
    raise LookupError(method)


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = request.get("id")
        try:
            result = handle(request)
        except LookupError as exc:
            if request_id is None:
                continue
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32601, "message": f"méthode inconnue : {exc}"}}
        else:
            if request_id is None or result is None:
                continue           # notification : pas de réponse
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
