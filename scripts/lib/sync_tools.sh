#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — outils des serveurs sportifs : lecture vs écriture
#
# Sourcé par scripts/daily-sync.sh (filtres Gemini/Copilot/Cursor du run headless)
# et par install.sh (règles de .cursor/cli.json). Une seule liste par source, pour
# que la règle « aucune écriture distante sans confirmation » (#133, #165, #167) ne
# dépende pas de l'exécuteur choisi.
#
# Noms vérifiés dans les serveurs épinglés :
#   garmin    — liste blanche GARMIN_TOOL_WHITELIST d'install.sh (+ opt-in #166/#167)
#   intervals — fork hhopke au commit épinglé par INTERVALS_MCP_REF (#165) :
#               annotations `readOnlyHint` de src/intervals_icu_mcp/server.py ;
#               les anciens noms sans préfixe (eddmann) restent refusés aussi.
#   strava    — r-huijts/strava-mcp 1.2.1 (#164), outils à tirets.
# =============================================================================

# Préfixes d'un outil Garmin qui écrit (côté Garmin, ou un fichier local arbitraire).
SYNC_GARMIN_WRITE_PREFIXES="schedule_ upload_ delete_ unschedule_ create_ add_ remove_ set_ log_ update_ upsert_ bulk_ download_ request_reload"

# Outils d'écriture Garmin refusés explicitement (refus nommés : Claude, Copilot, Cursor).
SYNC_GARMIN_WRITE_TOOLS="add_gear_to_activity remove_gear_from_activity schedule_workouts schedule_workout"
SYNC_GARMIN_WRITE_TOOLS+=" schedule_week upload_workout upload_workouts create_strength_workout"
SYNC_GARMIN_WRITE_TOOLS+=" create_walk_run_workout create_z2_walk_workout delete_workout delete_workouts"
SYNC_GARMIN_WRITE_TOOLS+=" unschedule_workout unschedule_workouts upload_course delete_course"
SYNC_GARMIN_WRITE_TOOLS+=" log_food log_custom_food create_custom_food update_custom_food upsert_and_log"
SYNC_GARMIN_WRITE_TOOLS+=" delete_food_log add_hydration_data add_weigh_in add_weigh_in_with_timestamps"
SYNC_GARMIN_WRITE_TOOLS+=" delete_weigh_ins add_body_composition set_blood_pressure set_activity_name"
SYNC_GARMIN_WRITE_TOOLS+=" request_reload download_activity_file"

# intervals.icu (#165) : outils sans `readOnlyHint` + téléchargements (`output_path`).
SYNC_INTERVALS_WRITE_TOOLS="update_activity update_activity_streams bulk_create_manual_activities"
SYNC_INTERVALS_WRITE_TOOLS+=" delete_activity update_wellness create_event update_event delete_event"
SYNC_INTERVALS_WRITE_TOOLS+=" bulk_create_events bulk_update_event_access bulk_delete_events duplicate_events"
SYNC_INTERVALS_WRITE_TOOLS+=" apply_training_plan create_workout update_workout delete_workout"
SYNC_INTERVALS_WRITE_TOOLS+=" bulk_create_workouts create_workout_folder delete_workout_folder create_gear"
SYNC_INTERVALS_WRITE_TOOLS+=" update_gear delete_gear create_gear_reminder update_gear_reminder"
SYNC_INTERVALS_WRITE_TOOLS+=" update_sport_settings apply_sport_settings create_sport_settings"
SYNC_INTERVALS_WRITE_TOOLS+=" delete_sport_settings add_activity_message create_custom_item"
SYNC_INTERVALS_WRITE_TOOLS+=" update_custom_item delete_custom_item"
SYNC_INTERVALS_WRITE_TOOLS+=" download_activity_file download_fit_file download_gpx_file"

# intervals.icu : outils de lecture utiles à la synchronisation (liste blanche Gemini).
SYNC_INTERVALS_READ_TOOLS="get_wellness_for_date get_wellness_data get_recent_activities"
SYNC_INTERVALS_READ_TOOLS+=" get_activities_by_date get_activity_details get_activity_intervals"
SYNC_INTERVALS_READ_TOOLS+=" get_calendar_events get_upcoming_workouts get_event get_gear_list"
SYNC_INTERVALS_READ_TOOLS+=" get_athlete_profile get_fitness_summary"

# Strava (#164) : outils qui AGISSENT (navigateur + port local, effacement des jetons, écriture).
SYNC_STRAVA_WRITE_TOOLS="connect-strava disconnect-strava star-segment"
SYNC_STRAVA_READ_TOOLS="get-recent-activities get-all-activities get-activity-details get-activity-laps"
SYNC_STRAVA_READ_TOOLS+=" get-activity-streams get-athlete-zones get-athlete-profile get-athlete-stats"

# Outils d'écriture d'une source, un par ligne. intervals : noms `icu_` du serveur
# épinglé, puis anciens noms sans préfixe (installation pas encore mise à jour).
sync_write_tools() {
    local tool
    case "$1" in
        garmin) for tool in $SYNC_GARMIN_WRITE_TOOLS; do printf '%s\n' "$tool"; done ;;
        intervals)
            for tool in $SYNC_INTERVALS_WRITE_TOOLS; do printf 'icu_%s\n' "$tool"; done
            for tool in $SYNC_INTERVALS_WRITE_TOOLS duplicate_event; do printf '%s\n' "$tool"; done ;;
        strava) for tool in $SYNC_STRAVA_WRITE_TOOLS; do printf '%s\n' "$tool"; done ;;
    esac
}

# Outils de lecture d'une source, un par ligne. garmin : la liste blanche passée en
# 2e argument (virgules), moins tout ce qui porte un préfixe d'écriture.
sync_read_tools() {
    local tool prefix keep
    case "$1" in
        garmin)
            for tool in ${2//,/ }; do
                keep=1
                for prefix in $SYNC_GARMIN_WRITE_PREFIXES; do
                    [[ "$tool" == "$prefix"* ]] && keep=0
                done
                [[ "$keep" -eq 0 ]] || printf '%s\n' "$tool"
            done ;;
        intervals) for tool in $SYNC_INTERVALS_READ_TOOLS; do printf 'icu_%s\n' "$tool"; done ;;
        strava) for tool in $SYNC_STRAVA_READ_TOOLS; do printf '%s\n' "$tool"; done ;;
    esac
}
