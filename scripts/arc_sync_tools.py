#!/usr/bin/env python3
"""Outils des serveurs sportifs : lecture vs écriture — source unique.

Utilisé par scripts/arc_daily_sync.py (filtres Claude/Copilot/Gemini/Cursor/OpenCode du
run headless) et par install.sh (règles de .cursor/cli.json). Une seule liste par source,
pour que la règle « aucune écriture distante sans confirmation » (#133, #165, #167) ne
dépende pas de l'exécuteur choisi.

Noms vérifiés dans les serveurs épinglés :
  garmin    — liste blanche GARMIN_TOOL_WHITELIST d'install.sh (+ opt-in #166/#167)
  intervals — fork hhopke au commit épinglé par INTERVALS_MCP_REF (#165) :
              annotations `readOnlyHint` de src/intervals_icu_mcp/server.py ;
              les anciens noms sans préfixe (eddmann) restent refusés aussi.
  strava    — r-huijts/strava-mcp 1.2.1 (#164), outils à tirets.

Ce module ne dépend que de la bibliothèque standard (voir CONTRIBUTING.md).

Usage (un outil par ligne) :
  arc_sync_tools.py write <source>
  arc_sync_tools.py read <source> [liste,blanche,garmin] [--deny-health]
  arc_sync_tools.py health-denied <source> [--deny-health]
  arc_sync_tools.py deny <source> [--deny-health]
  arc_sync_tools.py shell <source> [--deny-health]   # affectations bash pour daily-sync.sh
"""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import List

# Préfixes d'un outil Garmin qui écrit (côté Garmin, ou un fichier local arbitraire).
GARMIN_WRITE_PREFIXES = (
    "schedule_", "upload_", "delete_", "unschedule_", "create_", "add_", "remove_", "set_",
    "log_", "update_", "upsert_", "bulk_", "download_", "request_reload",
)

# Outils d'écriture Garmin refusés explicitement (refus nommés : Claude, Copilot, Cursor).
GARMIN_WRITE_TOOLS = (
    "add_gear_to_activity", "remove_gear_from_activity", "schedule_workouts", "schedule_workout",
    "schedule_week", "upload_workout", "upload_workouts", "create_strength_workout",
    "create_walk_run_workout", "create_z2_walk_workout", "delete_workout", "delete_workouts",
    "unschedule_workout", "unschedule_workouts", "upload_course", "delete_course",
    "log_food", "log_custom_food", "create_custom_food", "update_custom_food", "upsert_and_log",
    "delete_food_log", "add_hydration_data", "add_weigh_in", "add_weigh_in_with_timestamps",
    "delete_weigh_ins", "add_body_composition", "set_blood_pressure", "set_activity_name",
    "request_reload", "download_activity_file",
)

# Santé Garmin (#220) : refusée au run headless quand la santé du bilan matinal vient d'Open
# Wearables (`[health].source = "openwearables"` avec `[data].source = "garmin"`) — une seule
# source santé par jour. Sans cette condition (deny_health), aucune liste ne change.
GARMIN_HEALTH_TOOLS = (
    "get_hrv_data", "get_rhr_day", "get_sleep_data", "get_training_readiness",
    # Body battery et stress : le contrat refuse body_battery_*/stress_avg dans un fichier santé
    # Open Wearables. Absents de la liste blanche livrée (défense en profondeur si une config les
    # expose à la main).
    "get_body_battery", "get_body_battery_events", "get_stress_data", "get_stress_summary",
    "get_all_day_stress",
)

# intervals.icu (#165) : outils sans `readOnlyHint` + téléchargements (`output_path`).
INTERVALS_WRITE_TOOLS = (
    "update_activity", "update_activity_streams", "bulk_create_manual_activities",
    "delete_activity", "update_wellness", "create_event", "update_event", "delete_event",
    "bulk_create_events", "bulk_update_event_access", "bulk_delete_events", "duplicate_events",
    "apply_training_plan", "create_workout", "update_workout", "delete_workout",
    "bulk_create_workouts", "create_workout_folder", "delete_workout_folder", "create_gear",
    "update_gear", "delete_gear", "create_gear_reminder", "update_gear_reminder",
    "update_sport_settings", "apply_sport_settings", "create_sport_settings",
    "delete_sport_settings", "add_activity_message", "create_custom_item",
    "update_custom_item", "delete_custom_item",
    # v5.6.0 : remplace les notes libres du profil athlète — jamais appelé par le projet.
    "update_athlete_notes",
    "download_activity_file", "download_fit_file", "download_gpx_file",
)

# intervals.icu : outils de lecture utiles à la synchronisation (liste blanche Gemini), noms du
# serveur épinglé (préfixe `icu_`).
INTERVALS_READ_TOOLS = (
    "icu_get_wellness_for_date", "icu_get_wellness_data", "icu_get_recent_activities",
    "icu_get_activities_by_date", "icu_get_activity_details", "icu_get_activity_intervals",
    "icu_get_calendar_events", "icu_get_upcoming_workouts", "icu_get_event", "icu_get_gear_list",
    "icu_get_athlete_profile", "icu_get_fitness_summary",
)

# Strava (#164) : outils qui AGISSENT (navigateur + port local, effacement des jetons, écriture).
STRAVA_WRITE_TOOLS = ("connect-strava", "disconnect-strava", "star-segment")
STRAVA_READ_TOOLS = (
    "get-recent-activities", "get-all-activities", "get-activity-details", "get-activity-laps",
    "get-activity-streams", "get-athlete-zones", "get-athlete-profile", "get-athlete-stats",
)


def write_tools(source: str) -> List[str]:
    """Outils d'écriture d'une source. intervals : noms `icu_` du serveur épinglé, puis anciens
    noms sans préfixe (installation pas encore mise à jour). Source inconnue : rien."""
    if source == "garmin":
        return list(GARMIN_WRITE_TOOLS)
    if source == "intervals":
        # Ancien serveur eddmann : mêmes noms sans préfixe (+ `duplicate_event` au singulier).
        return ["icu_" + t for t in INTERVALS_WRITE_TOOLS] + list(INTERVALS_WRITE_TOOLS) + ["duplicate_event"]
    if source == "strava":
        return list(STRAVA_WRITE_TOOLS)
    return []


def read_tools(source: str, garmin_whitelist: str = "", deny_health: bool = False) -> List[str]:
    """Outils de lecture d'une source. garmin : la liste blanche (virgules), moins tout ce qui
    porte un préfixe d'écriture (et la santé quand elle vient d'Open Wearables)."""
    if source == "garmin":
        kept = []
        for tool in garmin_whitelist.replace(",", " ").split():
            if tool.startswith(GARMIN_WRITE_PREFIXES):
                continue
            if deny_health and tool in GARMIN_HEALTH_TOOLS:
                continue
            kept.append(tool)
        return kept
    if source == "intervals":
        return list(INTERVALS_READ_TOOLS)
    if source == "strava":
        return list(STRAVA_READ_TOOLS)
    return []


def health_denied_tools(source: str, deny_health: bool) -> List[str]:
    """Outils santé Garmin refusés pour cette source (vide hors du cas Open Wearables + Garmin)."""
    if source == "garmin" and deny_health:
        return list(GARMIN_HEALTH_TOOLS)
    return []


def deny_tools(source: str, deny_health: bool) -> List[str]:
    """Écritures de la source + outils santé refusés (copilot, gemini) ; cursor sépare les deux."""
    return write_tools(source) + health_denied_tools(source, deny_health)


def shell_assignments(source: str, deny_health: bool) -> List[str]:
    """Affectations bash (une par ligne, valeurs séparées par des espaces) lues par daily-sync.sh
    en un seul appel : listes de la source configurée, plus les écritures nommées de chaque
    type de serveur (la configuration OpenCode les refuse toutes)."""
    values = {
        "SYNC_GARMIN_WRITE_PREFIXES": GARMIN_WRITE_PREFIXES,
        "SYNC_WRITE_TOOLS": write_tools(source),
        "SYNC_READ_TOOLS": read_tools(source),
        "SYNC_HEALTH_DENIED_TOOLS": health_denied_tools(source, deny_health),
        "SYNC_DENY_TOOLS": deny_tools(source, deny_health),
        "SYNC_GARMIN_WRITE_TOOLS": write_tools("garmin"),
        "SYNC_INTERVALS_WRITE_TOOLS": write_tools("intervals"),
        "SYNC_STRAVA_WRITE_TOOLS": write_tools("strava"),
    }
    return [f"{name}={shlex.quote(' '.join(tools))}" for name, tools in values.items()]


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outils des serveurs sportifs : lecture vs écriture.")
    parser.add_argument("kind", choices=("write", "read", "health-denied", "deny", "shell"))
    parser.add_argument("source")
    parser.add_argument("whitelist", nargs="?", default="", help="liste blanche Garmin (read)")
    parser.add_argument("--deny-health", action="store_true",
                        help="santé lue chez Open Wearables : outils santé Garmin refusés")
    args = parser.parse_args(argv)
    if args.kind == "shell":
        print("\n".join(shell_assignments(args.source, args.deny_health)))
        return 0
    if args.kind == "write":
        tools = write_tools(args.source)
    elif args.kind == "read":
        tools = read_tools(args.source, args.whitelist, args.deny_health)
    elif args.kind == "health-denied":
        tools = health_denied_tools(args.source, args.deny_health)
    else:
        tools = deny_tools(args.source, args.deny_health)
    for tool in tools:
        print(tool)
    return 0


if __name__ == "__main__":
    sys.exit(main())
