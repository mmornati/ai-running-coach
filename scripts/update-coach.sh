#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — mise à jour du moteur (skill /update-coach)
#
#   scripts/update-coach.sh           # vérifie, résume, demande confirmation, met à jour
#   scripts/update-coach.sh --check   # vérifie et résume seulement : rien n'est modifié
#   scripts/update-coach.sh --yes     # sans question (confirmation déjà donnée dans le chat)
#
# Étapes : git fetch → avance rapide de main (git merge --ff-only, jamais de fusion ni
# de force) → ./install.sh avec les options MÉMORISÉES de la dernière installation
# (~/.config/ai-running-coach/install-args, écrit par install.sh) → coach_doctor.py.
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

log "Recherche de mises à jour ($upstream)…"
git -C "$ENGINE" fetch --quiet --tags "${upstream%%/*}" || die "git fetch impossible (réseau ?)."
behind="$(git -C "$ENGINE" rev-list --count "HEAD..$upstream")"
current="$(python3 "$ENGINE/scripts/arc_version.py" 2>/dev/null || echo inconnue)"
if [[ "$behind" -eq 0 ]]; then
    ok "Déjà à jour ($current)."
    exit 0
fi
if ! git -C "$ENGINE" merge-base --is-ancestor HEAD "$upstream"; then
    err "main a divergé de $upstream (commits locaux) : avance rapide impossible, mise à jour manuelle."
    exit 5
fi
target="$(git -C "$ENGINE" describe --tags --match 'v[0-9]*' "$upstream" 2>/dev/null || git -C "$ENGINE" rev-parse --short "$upstream")"

printf '%s\n' "Version installée : $current"
printf '%s\n' "Nouvelle version  : $target ($behind commit(s))"
printf '%s' "Réinstallation    : ./install.sh"
printf ' %q' ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"}
printf '\n'

[[ "$MODE" != "check" ]] || exit 0
if [[ "$MODE" == "ask" ]]; then
    [[ -t 0 ]] || die "Pas de terminal pour confirmer : relancez avec --yes."
    read -r -p "Mettre à jour maintenant ? [o/N] " answer
    [[ "$answer" =~ ^[oOyY] ]] || die "Mise à jour annulée."
fi

log "Avance rapide de main…"
git -C "$ENGINE" merge --ff-only --quiet "$upstream" || die "git merge --ff-only a échoué."
log "Réinstallation avec les mêmes options…"
(cd "$ENGINE" && ./install.sh ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"}) \
    || die "install.sh a échoué : le code est à jour, relancez ./install.sh $(printf '%q ' ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"})"
log "Diagnostic…"
python3 "$ENGINE/scripts/coach_doctor.py" --workspace "$ARC_WORKSPACE" || warn "coach_doctor signale des points à voir (ci-dessus)."
ok "Mise à jour terminée : $(python3 "$ENGINE/scripts/arc_version.py" 2>/dev/null || echo "$target")."
printf '%s\n' "Ouvrez une nouvelle session de votre assistant et relancez le tableau de bord (scripts/dashboard.sh)" \
    "— ou « docker compose up -d --build » pour l'image Docker — pour profiter de la nouvelle version."
