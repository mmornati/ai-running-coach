#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — mise à jour du moteur (skill /update-coach)
#
#   scripts/update-coach.sh           # vérifie, résume, demande confirmation, met à jour
#   scripts/update-coach.sh --check   # vérifie et résume seulement : rien n'est modifié
#   scripts/update-coach.sh --yes     # sans question (confirmation déjà donnée dans le chat)
#
# Étapes : git fetch → avance rapide de main jusqu'à la DERNIÈRE RELEASE publiée (tag vX.Y.Z
# fusionné dans main, jamais la tête de main ni une pré-version ; git merge --ff-only, jamais
# de fusion ni de force) → ./install.sh avec les options MÉMORISÉES de la dernière installation
# (~/.config/ai-running-coach/install-args, écrit par install.sh) → coach_doctor.py
# → reconstruction des tableaux de bord Docker construits depuis ce moteur, s'il y en a
# (conteneurs compose EN COURS dont un service a build.context = moteur, dont celui d'install.sh
# --dashboard-docker ; sans Docker : rien). Seul endroit où l'image est reconstruite.
# Sans terminal (--yes depuis l'assistant), install.sh est relancé avec --no-auth et sans
# entrée standard : aucune saisie interactive ne peut bloquer la mise à jour (coach_doctor
# signale ensuite des jetons à renouveler).
# Vos données (workspace) ne sont jamais touchées. Jamais en headless.
#
# Codes de sortie (lus par le skill) :
#   0  à jour, ou mise à jour terminée (ou --check : une mise à jour est possible)
#   1  erreur (réseau, install.sh, confirmation refusée…)
#   3  moteur sans git (application macOS, image Docker) : autre chemin de mise à jour
#   4  options d'installation non mémorisées (installation antérieure à cette fonction)
#   5  moteur hors de main, ou modifications locales : mise à jour manuelle
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

MODE="ask"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) MODE="check"; shift ;;
        --yes|-y) MODE="yes"; shift ;;
        --help|-h) sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

ENGINE="$ARC_ENGINE_ROOT"
DASHBOARDS=()  # « projet<TAB>dossier<TAB>fichiers compose (virgules)<TAB>service »
ARGS_FILE="$HOME/.config/ai-running-coach/install-args"

[[ -z "${ARC_HEADLESS:-}" ]] || die "Mise à jour refusée en headless : lancez-la depuis un terminal ou une session interactive."

if [[ ! -e "$ENGINE/.git" ]]; then
    err "Ce moteur n'est pas un dépôt git ($ENGINE)."
    err "  Application macOS : mise à jour par l'application elle-même."
    err "  Image Docker du tableau de bord : git pull dans le dépôt source, puis « docker compose up -d --build »."
    exit 3
fi
have git || die "git est requis."

branch="$(git -C "$ENGINE" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "$branch" != "main" ]]; then
    err "Le moteur est sur « ${branch:-HEAD détachée} », pas sur main : mise à jour automatique désactivée."
    err "  Développeur ? git -C \"$ENGINE\" switch main && git pull --ff-only, puis ./install.sh (docs/update.md)."
    exit 5
fi
if [[ -n "$(git -C "$ENGINE" status --porcelain --untracked-files=no)" ]]; then
    err "Le moteur a des modifications locales (git -C \"$ENGINE\" status) : rien n'est fait pour ne pas les écraser."
    exit 5
fi
upstream="$(git -C "$ENGINE" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
[[ -n "$upstream" ]] || { err "main ne suit aucune branche distante (git branch -u origin/main)."; exit 5; }

if [[ ! -f "$ARGS_FILE" ]]; then
    err "Options de la dernière installation inconnues ($ARGS_FILE absent)."
    err "  Installation antérieure à leur mémorisation : relancez une fois ./install.sh avec vos options"
    err "  (docs/update.md, « Retrouver ses options d'installation »), elles seront mémorisées."
    exit 4
fi
INSTALL_ARGS=()
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" ]] && INSTALL_ARGS+=("$line")
done < "$ARGS_FILE"

# Tableaux de bord Docker à reconstruire : conteneurs compose en cours dont le service se
# construit depuis CE moteur. Docker absent, démon injoignable, aucun conteneur : liste vide,
# aucun message (la plupart des installations n'utilisent pas Docker). Lecture seule.
find_docker_dashboards() {
    have docker || return 0
    docker info >/dev/null 2>&1 || return 0
    local project dir files service cf
    local -a cargs cfs
    while IFS=$'\t' read -r project dir files service; do
        [[ -n "$project" && -n "$dir" && -n "$files" && -n "$service" ]] || continue
        cargs=(-p "$project" --project-directory "$dir")
        IFS=, read -ra cfs <<< "$files"
        for cf in "${cfs[@]}"; do cargs+=(-f "$cf"); done
        docker compose "${cargs[@]}" config --format json </dev/null 2>/dev/null | python3 -c '
import json, os, sys
try:
    build = json.load(sys.stdin)["services"][sys.argv[1]].get("build") or {}
except (ValueError, KeyError, TypeError):
    sys.exit(1)
ctx = build.get("context", "") if isinstance(build, dict) else build
sys.exit(0 if ctx and os.path.realpath(ctx) == os.path.realpath(sys.argv[2]) else 1)
' "$service" "$ENGINE" || continue
        DASHBOARDS+=("$project"$'\t'"$dir"$'\t'"$files"$'\t'"$service")
    done < <(docker ps --filter label=com.docker.compose.project --format \
        '{{.Label "com.docker.compose.project"}}{{"\t"}}{{.Label "com.docker.compose.project.working_dir"}}{{"\t"}}{{.Label "com.docker.compose.project.config_files"}}{{"\t"}}{{.Label "com.docker.compose.service"}}' \
        2>/dev/null | sort -u)
}

rebuild_docker_dashboards() {
    local entry project dir files service cf
    local -a cargs cfs
    for entry in ${DASHBOARDS[@]+"${DASHBOARDS[@]}"}; do
        IFS=$'\t' read -r project dir files service <<< "$entry"
        cargs=(-p "$project" --project-directory "$dir")
        IFS=, read -ra cfs <<< "$files"
        for cf in "${cfs[@]}"; do cargs+=(-f "$cf"); done
        log "Reconstruction du tableau de bord Docker « $project » ($service)…"
        # --pull : dernière image Python de base, avec ses correctifs de sécurité (docs/dashboard/docker.md).
        if docker compose "${cargs[@]}" build --pull "$service" </dev/null \
            && docker compose "${cargs[@]}" up -d "$service" </dev/null; then
            ok "Tableau de bord Docker « $project » reconstruit et relancé."
        else
            warn "Reconstruction de « $project » impossible : le moteur est à jour, relancez « docker compose up -d --build » dans $dir."
        fi
    done
}

log "Recherche de mises à jour ($upstream)…"
git -C "$ENGINE" fetch --quiet --tags "${upstream%%/*}" || die "git fetch impossible (réseau ?)."
current="$(python3 "$ENGINE/scripts/arc_version.py" 2>/dev/null || echo inconnue)"
# Dernière release = plus haut tag vX.Y.Z (sans suffixe de pré-version) déjà fusionné dans
# main en amont : la version annoncée par arc_update_check.py, pas les commits non publiés.
target=""
while IFS= read -r tag; do
    if [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then target="$tag"; break; fi
done < <(git -C "$ENGINE" tag --merged "$upstream" --list 'v[0-9]*' --sort=-v:refname)
if [[ -z "$target" ]]; then
    ok "Aucune release publiée sur $upstream : rien à mettre à jour ($current)."
    exit 0
fi
target_commit="$(git -C "$ENGINE" rev-parse "$target^{commit}")"
if git -C "$ENGINE" merge-base --is-ancestor "$target_commit" HEAD; then
    ok "Déjà à jour ($current, dernière release : $target)."
    exit 0
fi
if ! git -C "$ENGINE" merge-base --is-ancestor HEAD "$target_commit"; then
    err "main contient des commits absents de la release $target : avance rapide impossible, mise à jour manuelle."
    exit 5
fi
behind="$(git -C "$ENGINE" rev-list --count "HEAD..$target_commit")"

printf '%s\n' "Version installée : $current"
printf '%s\n' "Nouvelle version  : $target ($behind commit(s))"
printf '%s' "Réinstallation    : ./install.sh"
printf ' %q' ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"}
printf '\n'
find_docker_dashboards
for entry in ${DASHBOARDS[@]+"${DASHBOARDS[@]}"}; do
    IFS=$'\t' read -r project dir _ _ <<< "$entry"
    printf '%s\n' "Tableau de bord   : conteneur Docker « $project » reconstruit ($dir)"
done

[[ "$MODE" != "check" ]] || exit 0
if [[ "$MODE" == "ask" ]]; then
    [[ -t 0 ]] || die "Pas de terminal pour confirmer : relancez avec --yes."
    read -r -p "Mettre à jour maintenant ? [o/N] " answer
    [[ "$answer" =~ ^[oOyY] ]] || die "Mise à jour annulée."
fi

log "Avance rapide de main jusqu'à ${target}…"
git -C "$ENGINE" merge --ff-only --quiet "$target_commit" || die "git merge --ff-only a échoué."
log "Réinstallation avec les mêmes options…"
if [[ -t 0 ]]; then
    (cd "$ENGINE" && ./install.sh ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"}) || install_failed=1
else
    # Pas de terminal : une authentification interactive (jetons expirés) bloquerait jusqu'au
    # délai de l'outil. --no-auth n'est jamais mémorisé ; coach_doctor signale les jetons.
    warn "Sans terminal : authentification sautée (--no-auth) — coach_doctor dira si elle est à refaire."
    (cd "$ENGINE" && ./install.sh ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"} --no-auth </dev/null) || install_failed=1
fi
[[ -z "${install_failed:-}" ]] \
    || die "install.sh a échoué : le code est à jour, relancez ./install.sh $(printf '%q ' ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"})"
log "Diagnostic…"
python3 "$ENGINE/scripts/coach_doctor.py" --workspace "$ARC_WORKSPACE" || warn "coach_doctor signale des points à voir (ci-dessus)."
rebuild_docker_dashboards
ok "Mise à jour terminée : $(python3 "$ENGINE/scripts/arc_version.py" 2>/dev/null || echo "$target")."
if [[ ${#DASHBOARDS[@]} -gt 0 ]]; then
    printf '%s\n' "Ouvrez une nouvelle session de votre assistant pour profiter de la nouvelle version."
else
    printf '%s\n' "Ouvrez une nouvelle session de votre assistant et relancez le tableau de bord (scripts/dashboard.sh)" \
        "— ou « docker compose up -d --build » pour l'image Docker — pour profiter de la nouvelle version."
fi
