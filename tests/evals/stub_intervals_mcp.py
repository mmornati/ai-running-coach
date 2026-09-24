#!/usr/bin/env python3
"""Serveur MCP « intervals » factice, pour le palier C (story source
intervals.icu, #68).

Même protocole, même journal d'appels, même mécanique de scripting par cas
d'éval que `stub_garmin_mcp.py` (partagés via `mcp_stub_common.py`) — seuls la
liste d'outils et les données canned changent, pour coller à une source de
données alternative.

**Liste d'outils : hypothèse documentée.** Le serveur MCP intervals.icu n'est
pas encore choisi par le projet (#68 est encore ouvert). Cette liste reprend
les noms et la casse (kebab-case, contrairement au snake_case de garmin_mcp)
de `eddmann/intervals-icu-mcp` (README à la racine du dépôt, catégories
« Activities », « Wellness », « Events/Calendar », « Athlete » — 48 outils au
total dans l'original ; on n'en reprend ici qu'un sous-ensemble plausible pour
ce que les agents `coach`/`medical` consomment aujourd'hui côté Garmin :
activités récentes, wellness/HRV du jour, calendrier). Si le projet retient un
autre serveur pour #68, seule cette liste (et le nom des champs canned) doit
changer — le protocole et le scripting restent les mêmes.

**Scriptable par cas d'éval (#26)**, identique à `stub_garmin_mcp.py` :
`[stub.intervals.<outil>] file = "…json"` ou `error = "401" | "timeout" | "empty"`.

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


# Données synthétiques : un athlète reposé, sans signal d'alerte — même
# posture que le stub garmin, pour que basculer `[data].source` entre les
# deux ne change rien au comportement par défaut d'un scénario.
CANNED = {
    "get-wellness-for-date": {
        "id": _day(0), "restingHR": 49, "hrv": 62, "hrvSDNN": 62,
        "sleepSecs": 25800, "sleepScore": 78, "readiness": 71,
    },
    "get-wellness-data": [{
        "id": _day(0), "restingHR": 49, "hrv": 62, "sleepSecs": 25800, "readiness": 71,
    }],
    "get-recent-activities": [{
        "id": "i99000001", "name": "Sortie longue",
        "start_date_local": f"{_day(2)}T12:05:00",
        "type": "Run",
        "distance": 24800.0, "moving_time": 9660.0, "total_elevation_gain": 890.0,
        "average_heartrate": 141, "max_heartrate": 168,
    }],
    "get-activity-details": {"status": "ok", "stub": True},
    "get-calendar-events": [],
    "get-upcoming-workouts": [],
    "get-athlete-profile": {"id": "0", "name": "Athlete", "sportSettings": []},
    "get-fitness-summary": {"ctl": 42.0, "atl": 38.0, "form": 4.0},
}

TOOLS = [
    ("get-wellness-for-date", "Wellness (HRV, FC repos, sommeil, readiness) pour une date."),
    ("get-wellness-data", "Wellness entre deux dates."),
    ("get-recent-activities", "Dernières activités enregistrées."),
    ("get-activity-details", "Détail d'une activité."),
    ("get-calendar-events", "Événements planifiés entre deux dates."),
    ("get-upcoming-workouts", "Séances planifiées à venir."),
    ("get-athlete-profile", "Profil de l'athlète."),
    ("get-fitness-summary", "CTL/ATL/forme courants."),
    ("create-event", "Planifie une séance dans le calendrier intervals.icu."),
    ("update-event", "Modifie un événement planifié."),
    ("delete-event", "Supprime un événement planifié."),
    ("bulk-create-events", "Planifie plusieurs séances en un appel."),
]


def result_for(name: str, arguments: dict):
    if name in CANNED:
        return CANNED[name]
    if name.startswith(("create-", "update-", "delete-", "bulk-")):
        return {"status": "ok", "stub": True, "tool": name, "received": arguments}
    return {"status": "ok", "stub": True, "tool": name, "data": []}


def main() -> int:
    handle = common.make_handler(
        server_name="intervals", tools=TOOLS, result_for=result_for, fixtures_dir=FIXTURES_DIR,
    )
    return common.serve(handle)


if __name__ == "__main__":
    raise SystemExit(main())
