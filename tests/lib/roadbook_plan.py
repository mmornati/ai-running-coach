"""Plan de course fictif PERSISTÉ tel que le `course-strategist` l'écrit — socle des tests du roadbook (#187).

Les segments, les temps par scénario et les fractions de nuit sortent du VRAI
`arc_race_pacing.build_race_plan` (parcours rectiligne synthétique de 90 km, zone fictive du dépôt,
départ à 16:00 en plein hiver austral : la nuit tombe en course) ; seuls les champs que l'agent
ajoute à la main (`take`, barrières, matériel, consignes) sont écrits ici. Aucune donnée réelle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import arc_race_pacing as RP  # noqa: E402
from tests.data.test_arc_race_pacing import (  # noqa: E402
    PERSONAL_BINS, _UltraClimbFlatDescentProfile, _straight_course,
)

TZ = "Etc/GMT+9"
RACE_DATE = "2026-06-20"
RACE_NAME = "Ultra des Collines Fictives"


def aid_stations() -> list:
    return [
        {"km": 20.0, "name": "Ravito du Col", "cutoff": "+02:10", "services": ["eau", "coca", "soupe"],
         "take": ["2 gels", "500 ml de boisson d'effort"]},
        {"km": 60.0, "name": "Base de vie", "stop_s": 300, "cutoff": "+16:00", "services": ["repas chaud"],
         "take": ["repas chaud", "chaussettes de rechange", "frontale de rechange"]},
    ]


def pacing_plan(**over) -> dict:
    kw = dict(aid_stations=aid_stations(), fade_pct=4.0, intensity_factor=1.1, intensity_source="riegel",
              race_date=RACE_DATE, segment_m=750.0, start_time="16:00", tz=TZ)
    kw.update(over)
    return RP.build_race_plan(_straight_course(_UltraClimbFlatDescentProfile(), step_m=25.0), PERSONAL_BINS, **kw)


def persisted_plan(**over) -> dict:
    """Bloc `arc` d'un plan de course complet (segments + ravitos + matériel + consignes)."""
    pacing = pacing_plan()
    totals = pacing["totals"]
    plan = {
        "arc": 1, "kind": "race_plan", "date": "2026-06-10", "race_name": RACE_NAME, "race_date": RACE_DATE,
        "start_time": f"{RACE_DATE}T16:00", "timezone": TZ,
        "distance_m": totals["distance_m"], "elevation_gain_m": totals["elevation_gain_m"],
        "target_time_s": totals["time_s"]["realistic"], "scenarios": dict(totals["time_s"]),
        "aid_stations": aid_stations(), "gear": ["Frontale", "Couverture de survie", "Gobelet"],
        "notes": ["Rien de nouveau le jour J", "Caféine après H+6 uniquement"],
        "emergency": ["Organisation : numéro au dos du dossard", "Abandon possible aux deux ravitos"],
        "segments": pacing["segments"],
    }
    plan.update(over)
    return plan


def plan_markdown(plan: dict) -> str:
    """Fichier `planning/*.md` : titre, bloc `arc`, prose."""
    return (f"# Plan de course — {plan['race_name']}\n\n```arc\n{json.dumps(plan, ensure_ascii=False, indent=1)}\n```\n\n"
            "Plan fictif de test.\n")
