#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — reconstruit et relance les conteneurs Docker construits depuis ce moteur
#
#   scripts/update-docker.sh            # reconstruit (build --pull), relance, attend la santé
#   scripts/update-docker.sh --check    # dit seulement si chaque conteneur tourne la révision du dépôt
#   scripts/update-docker.sh --list     # liste les conteneurs concernés (aperçu de /update-coach)
#
# Conteneurs concernés : services compose EN COURS dont build.context est le moteur ou un de ses
# dossiers — le tableau de bord (deploy/dashboard, ou celui d'install.sh --dashboard-docker) ET le
# chat (deploy/chat). Le tableau de bord embarque le code dans son image ; le chat monte le moteur
# mais garde en mémoire le code chargé à son démarrage : les deux doivent être reconstruits et
# recréés après chaque mise à jour. Chaque image porte la révision git du dépôt
# (org.opencontainers.image.revision, via ARC_REVISION) : --check la compare à HEAD, et une
# nouvelle révision suffit à faire recréer le conteneur par « up -d ».
# Lancé par scripts/update-coach.sh après une mise à jour, et quand le dépôt est à jour mais pas
# les conteneurs. Vos données (workspace) ne sont jamais touchées. Jamais en headless.
#
# Codes de sortie :
#   0   conteneurs à jour (ou reconstruction terminée)
#   1   erreur (construction ou démarrage en échec, conteneur en mauvaise santé…)
#   3   aucun conteneur concerné (Docker absent, démon injoignable, rien en cours)
#   10  --check : au moins un conteneur tourne une autre révision que le dépôt
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

MODE="update"
HEALTH_TIMEOUT_S="${ARC_DOCKER_HEALTH_TIMEOUT_S:-120}"
SOURCE_LABEL="org.opencontainers.image.source=https://github.com/mmornati/ai-running-coach"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) MODE="check"; shift ;;
        --list) MODE="list"; shift ;;
        --help|-h) sed -n '3,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

ENGINE="$ARC_ENGINE_ROOT"
[[ "$MODE" != "update" || -z "${ARC_HEADLESS:-}" ]] \
    || die "Reconstruction des conteneurs refusée en headless : lancez-la depuis un terminal."

# Révision attendue : HEAD du dépôt (ou la version publiée, pour un moteur sans git).
if [[ -e "$ENGINE/.git" ]] && have git; then
    ARC_REVISION="$(git -C "$ENGINE" rev-parse HEAD)"
else
    ARC_REVISION="$(cat "$ENGINE/VERSION" 2>/dev/null || echo inconnue)"
fi
export ARC_REVISION

# « projet<TAB>dossier<TAB>fichiers compose (virgules)<TAB>service<TAB>conteneur » des conteneurs
# compose en cours construits depuis le moteur. Docker absent, démon injoignable : liste vide.
DASHBOARDS=()
find_docker_dashboards() {
    have docker || return 0
    docker info >/dev/null 2>&1 || return 0
    local project dir files service cid
    while IFS=$'\t' read -r project dir files service cid; do
        [[ -n "$project" && -n "$dir" && -n "$files" && -n "$service" ]] || continue
        compose_args "$project" "$dir" "$files"
        docker compose "${CARGS[@]}" config --format json </dev/null 2>/dev/null | python3 -c '
import json, os, sys
try:
    build = json.load(sys.stdin)["services"][sys.argv[1]].get("build") or {}
except (ValueError, KeyError, TypeError):
    sys.exit(1)
ctx = build.get("context", "") if isinstance(build, dict) else build
engine = os.path.realpath(sys.argv[2])
ctx = os.path.realpath(ctx) if ctx else ""
# Le moteur lui-même (tableau de bord) ou un de ses dossiers (deploy/chat).
sys.exit(0 if ctx and (ctx == engine or ctx.startswith(engine + os.sep)) else 1)
' "$service" "$ENGINE" || continue
        DASHBOARDS+=("$project"$'\t'"$dir"$'\t'"$files"$'\t'"$service"$'\t'"${cid:-}")
    done < <(docker ps --filter label=com.docker.compose.project --format \
        '{{.Label "com.docker.compose.project"}}{{"\t"}}{{.Label "com.docker.compose.project.working_dir"}}{{"\t"}}{{.Label "com.docker.compose.project.config_files"}}{{"\t"}}{{.Label "com.docker.compose.service"}}{{"\t"}}{{.ID}}' \
        2>/dev/null | sort -u)
}

compose_args() {  # projet dossier fichiers → CARGS
    local cf
    local -a cfs
    CARGS=(-p "$1" --project-directory "$2")
    IFS=, read -ra cfs <<< "$3"
    for cf in "${cfs[@]}"; do CARGS+=(-f "$cf"); done
}

container_revision() {  # conteneur → révision de son image ("" si inconnue)
    local rev=""
    [[ -n "$1" ]] || return 0
    rev="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1" 2>/dev/null || true)"
    [[ "$rev" == "<no value>" ]] && rev=""
    printf '%s' "$rev"
}

# Une ligne par conteneur. STALE : autre révision connue ; UNKNOWN : image sans révision
# (construite avant cette fonction, ou par « docker compose up --build » à la main).
STALE=0 UNKNOWN=0
report() {
    local entry project service cid rev
    for entry in "${DASHBOARDS[@]}"; do
        IFS=$'\t' read -r project _ _ service cid <<< "$entry"
        rev="$(container_revision "$cid")"
        if [[ -z "$rev" ]]; then
            UNKNOWN=$((UNKNOWN + 1))
            printf '  %-28s %s\n' "$project/$service" "${C_YELLOW}révision inconnue${C_RESET}"
        elif [[ "$rev" == "$ARC_REVISION" ]]; then
            printf '  %-28s %s\n' "$project/$service" "${C_GREEN}à jour (${rev:0:7})${C_RESET}"
        else
            STALE=$((STALE + 1))
            printf '  %-28s %s\n' "$project/$service" "${C_YELLOW}ancienne version (${rev:0:7}, dépôt ${ARC_REVISION:0:7})${C_RESET}"
        fi
    done
}

find_docker_dashboards
[[ ${#DASHBOARDS[@]} -gt 0 ]] || exit 3

case "$MODE" in
    list)
        for entry in "${DASHBOARDS[@]}"; do
            IFS=$'\t' read -r project dir _ service _ <<< "$entry"
            printf '%s\n' "Conteneur Docker  : « $project » reconstruit ($service, $dir)"
        done
        exit 0 ;;
    check)
        report
        if [[ "$STALE" -gt 0 ]]; then
            warn "$STALE conteneur(s) en retard sur le dépôt : scripts/update-docker.sh"
            exit 10
        fi
        if [[ "$UNKNOWN" -gt 0 ]]; then
            warn "Révision inconnue : scripts/update-docker.sh reconstruit et étiquette ces conteneurs."
        else
            ok "Tous les conteneurs tournent la révision du dépôt."
        fi
        exit 0 ;;
esac

failed=0
for entry in "${DASHBOARDS[@]}"; do
    IFS=$'\t' read -r project dir files service _ <<< "$entry"
    compose_args "$project" "$dir" "$files"
    log "Reconstruction du conteneur Docker « $project » ($service)…"
    # --pull : dernière image Python de base, avec ses correctifs de sécurité (docs/dashboard/docker.md).
    if docker compose "${CARGS[@]}" build --pull "$service" </dev/null \
        && docker compose "${CARGS[@]}" up -d "$service" </dev/null; then
        ok "Conteneur Docker « $project » reconstruit et relancé ($service)."
    else
        warn "Reconstruction de « $project » ($service) impossible : relancez « docker compose up -d --build » dans $dir."
        failed=1
    fi
done

# Santé : attend la fin de « starting », signale « unhealthy ».
deadline=$((SECONDS + HEALTH_TIMEOUT_S))
while :; do
    pending=0 unhealthy=""
    for entry in "${DASHBOARDS[@]}"; do
        IFS=$'\t' read -r project dir files service _ <<< "$entry"
        compose_args "$project" "$dir" "$files"
        for cid in $(docker compose "${CARGS[@]}" ps -q "$service" </dev/null 2>/dev/null); do
            case "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid" 2>/dev/null)" in
                starting) pending=1 ;;
                unhealthy) unhealthy+=" $project/$service" ;;
            esac
        done
    done
    [[ "$pending" -eq 1 && "$SECONDS" -lt "$deadline" ]] || break
    sleep 3
done
# Images remplacées (sans étiquette) de ce projet seulement : jamais celles d'autres services.
docker image prune -f --filter "label=$SOURCE_LABEL" >/dev/null 2>&1 || true

[[ "$failed" -eq 0 ]] || exit 1
if [[ -n "$unhealthy" ]]; then
    err "Conteneur(s) en mauvaise santé :$unhealthy — journaux : docker logs <conteneur>"
    exit 1
fi
[[ "$pending" -eq 0 ]] || warn "Santé encore « starting » après ${HEALTH_TIMEOUT_S} s : vérifiez avec docker ps."
exit 0
