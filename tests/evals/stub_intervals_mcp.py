#!/usr/bin/env python3
"""Serveur MCP « intervals » factice, pour le palier C (story source
intervals.icu, #68).

Même protocole, même journal d'appels, même mécanique de scripting par cas
d'éval que `stub_garmin_mcp.py` (partagés via `mcp_stub_common.py`) — seuls la
liste d'outils et les données canned changent, pour coller à une source de
données alternative.

**Liste d'outils et FORME de réponse : VÉRIFIÉES (#68, revue PR #116)** contre
le code source du serveur réellement installé par le projet
(`./install.sh --source intervals`, voir `AGENTS.md` → « Backends MCP ») :
[`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp),
commit `5cd7e1a` (v5.5.0, `src/intervals_icu_mcp/tools/*.py`, `response_builder.py`) — #165 ;
le serveur précédent (eddmann@cb91d4a) exposait les mêmes outils SANS le préfixe `icu_`.

Points de fidélité qui ont changé depuis une première version non
vérifiée de ce stub (et lors du passage au fork, #165) :

0. **Préfixe `icu_`** sur CHAQUE nom d'outil (`icu_get_wellness_for_date`…).

1. **Enveloppe `{"data": ..., "metadata": {...}}`** (et `"analysis"` quand le
   vrai outil en produit une) — `ResponseBuilder.build_response` l'applique à
   CHAQUE outil, contrairement à `garmin_mcp` qui rend ses résultats à plat.
   Une assertion `payload["data"][...]` doit fonctionner contre ce stub
   exactement comme contre le vrai serveur.
2. **Formes imbriquées fidèles** par outil (`heart.resting_hr`, `sleep.*`,
   `subjective.readiness`, `fitness_metrics.ctl.value`...) — jamais un
   raccourci plat qui n'existe pas côté serveur réel.
3. **`metadata` sans `fetched_at` ni `query_type`** par défaut (le fork ne les
   injecte que si `INTERVALS_ICU_DEBUG_METADATA=true`) ; les écritures
   d'événements WORKOUT font l'écho d'analyse `workout_parsed`/`workout_steps`
   (`event_management.workout_doc_parse_info`) ; `icu_delete_event` rend une
   enveloppe `deleted`/`skipped`.

**Scriptable par cas d'éval (#26)**, identique à `stub_garmin_mcp.py` :
`[stub.intervals.<outil>] file = "…json"` ou `error = "401" | "timeout" | "empty"`.
Note de fidélité sur `error = "empty"` : `mcp_stub_common.resolve_content` vide
tout le gabarit `default` (ici l'enveloppe entière), donc `{}` — pas
`{"data": {}, "metadata": {...}}` comme le rendrait le vrai serveur pour un
résultat vide. Ce mécanisme est partagé avec `stub_garmin_mcp.py` ; aucun cas
d'éval de cette story ne scripte `error = "empty"` contre `intervals`, donc
l'écart n'affecte aucune assertion existante — à corriger dans
`mcp_stub_common.py` si un futur cas en a besoin.

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


def _envelope(data, *, query_type: str, analysis=None, metadata=None):
    """Reproduit `ResponseBuilder.build_response` du fork : `data` (+ `analysis`
    optionnelle) sous une `metadata` qui ne porte QUE ce que l'outil y met —
    `query_type`/`fetched_at` n'apparaissent qu'avec `INTERVALS_ICU_DEBUG_METADATA`
    (`query_type` reste accepté en paramètre pour documenter l'outil simulé)."""
    meta = {}
    if metadata:
        meta.update(metadata)
    envelope = {"data": data, "metadata": meta}
    if analysis:
        envelope["analysis"] = analysis
    return envelope


# Données synthétiques : un athlète reposé, sans signal d'alerte — même
# posture que le stub garmin, pour que basculer `[data].source` entre les
# deux ne change rien au comportement par défaut d'un scénario.
CANNED = {
    "icu_get_wellness_for_date": _envelope(
        {
            "date": _day(0),
            "sleep": {"duration_seconds": 25800, "score": 78},
            "heart": {"hrv_rmssd": 62.0, "resting_hr": 49},
            # Valeur manuelle du jour — PAS un score de readiness calculé
            # (aucun outil de ce serveur n'en produit un, voir AGENTS.md).
            "subjective": {"readiness": 71},
        },
        query_type="wellness_for_date",
    ),
    # Forme vérifiée (`tools/wellness.py::get_wellness_data`, exposé `icu_get_wellness_data`) : `data.wellness_data`
    # (liste) + `data.count` — PAS une liste nue à la racine de `data` comme une
    # version antérieure non vérifiée de ce stub le rendait.
    "icu_get_wellness_data": _envelope(
        {
            "wellness_data": [{
                "date": _day(0),
                "sleep": {"duration_seconds": 25800, "score": 78},
                "heart": {"hrv_rmssd": 62.0, "resting_hr": 49},
                "subjective": {"readiness": 71},
            }],
            "count": 1,
        },
        query_type="wellness_data",
    ),
    "icu_get_recent_activities": _envelope(
        {
            "activities": [{
                "id": "i99000001",
                "name": "Sortie longue",
                "start_date": f"{_day(2)}T12:05:00",
                "type": "Run",
                "distance_meters": 24800.0,
                "moving_time_seconds": 9660.0,
                "elevation_gain_meters": 890.0,
                "average_heartrate": 141,
            }],
            "count": 1,
        },
        query_type="recent_activities",
    ),
    "icu_get_activity_details": _envelope(
        {
            "id": "i99000001", "name": "Sortie longue", "type": "Run",
            "start_date": f"{_day(2)}T12:05:00",
            "distance_meters": 24800.0, "moving_time_seconds": 9660.0,
            "elevation_gain_meters": 890.0,
            "heart_rate": {"average": 141, "max": 168},
        },
        query_type="activity_details",
    ),
    # Fenêtre vide (aucun événement) : forme réelle du serveur pour ce cas
    # précis — `data.events` (jamais `events_by_date`, qui n'apparaît que
    # lorsque la liste n'est pas vide).
    "icu_get_calendar_events": _envelope(
        {"events": [], "count": 0, "date_range": {"oldest": _day(0), "newest": _day(-7)}},
        query_type="calendar_events",
    ),
    "icu_get_upcoming_workouts": _envelope(
        {"workouts": [], "count": 0},
        query_type="upcoming_workouts",
    ),
    "icu_get_event": _envelope(
        {"id": 123456, "date": _day(0), "name": "Endurance 60 min", "category": "WORKOUT"},
        query_type="get_event",
    ),
    "icu_get_athlete_profile": _envelope(
        {"profile": {"id": "i0", "name": "Athlete"}, "fitness": {"ctl": 42.0, "atl": 38.0, "tsb": 4.0}},
        query_type="athlete_profile",
    ),
    "icu_get_fitness_summary": _envelope(
        {
            "athlete_name": "Athlete",
            "fitness_metrics": {
                "ctl": {"value": 42.0, "description": "Chronic Training Load (Fitness)"},
                "atl": {"value": 38.0, "description": "Acute Training Load (Fatigue)"},
                "tsb": {"value": 4.0, "description": "Training Stress Balance (Form)"},
            },
        },
        query_type="fitness_summary",
    ),
}

TOOLS = [
    ("icu_get_wellness_for_date", "Wellness (HRV, FC repos, sommeil, valeur manuelle du jour) pour une date."),
    ("icu_get_wellness_data", "Wellness entre deux dates."),
    ("icu_get_recent_activities", "Dernières activités enregistrées."),
    ("icu_get_activity_details", "Détail d'une activité."),
    ("icu_get_calendar_events", "Événements planifiés entre deux dates."),
    ("icu_get_upcoming_workouts", "Séances planifiées à venir."),
    ("icu_get_event", "Détail d'un événement planifié."),
    ("icu_get_athlete_profile", "Profil de l'athlète."),
    ("icu_get_fitness_summary", "CTL/ATL/forme courants."),
    ("icu_create_event", "Planifie une séance dans le calendrier intervals.icu."),
    ("icu_update_event", "Modifie un événement planifié existant (event_id requis)."),
    ("icu_delete_event", "Supprime un événement planifié."),
    ("icu_bulk_create_events", "Planifie plusieurs séances en un appel."),
]


def result_for(name: str, arguments: dict):
    if name in CANNED:
        return CANNED[name]
    if name in ("icu_create_event", "icu_update_event", "icu_bulk_create_events"):
        # Formes réelles vérifiées (event_management.py, fork #165) : un event unique
        # écho des champs fournis pour icu_create_event/icu_update_event, une liste
        # `events` pour icu_bulk_create_events ; chaque événement WORKOUT porte l'écho
        # d'analyse `workout_parsed`/`workout_steps` (jamais de `workout_doc` en retour).
        if name == "icu_bulk_create_events":
            return _envelope({"events": []}, query_type="bulk_create_events")
        echoed = {k: v for k, v in (arguments or {}).items() if k != "event_id"}
        result = {"id": arguments.get("event_id", 123456), **echoed}
        if str(echoed.get("category", "")).upper() == "WORKOUT" and echoed.get("description"):
            parsed = "\n- " in "\n" + str(echoed["description"])
            result["workout_parsed"] = parsed
            if parsed:
                result["workout_steps"] = str(echoed["description"]).count("\n- ") + (
                    1 if str(echoed["description"]).startswith("- ") else 0)
        return _envelope(result, query_type=name)
    if name == "icu_delete_event":
        event_id = (arguments or {}).get("event_id")
        return _envelope(
            {"deleted": [event_id], "deleted_count": 1, "skipped": [], "skipped_count": 0},
            query_type="delete_event",
        )
    return _envelope({}, query_type=name)


def main() -> int:
    handle = common.make_handler(
        server_name="intervals", tools=TOOLS, result_for=result_for, fixtures_dir=FIXTURES_DIR,
    )
    return common.serve(handle)


if __name__ == "__main__":
    raise SystemExit(main())
