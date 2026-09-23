#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — tableau de bord local (lecture seule)
#
# Indexe le workspace dans une base SQLite dérivée (<workspace>/.arc/coach.db,
# jetable, reconstruite depuis les fichiers Markdown) puis sert le tableau de
# bord sur http://127.0.0.1:<port>/. Rien n'écoute hors de la machine, rien
# n'est écrit hors de .arc/.
#
# Usage :
#   scripts/dashboard.sh              # port de [dashboard].port (défaut 8765), ouvre le navigateur
#   scripts/dashboard.sh --port 9000  # autre port
#   scripts/dashboard.sh --no-open    # sans ouvrir le navigateur
#   scripts/dashboard.sh --memory     # base en mémoire : aucun fichier .arc/ écrit
#   scripts/dashboard.sh --rebuild    # repart d'un index vide
#
# Configuration : section [dashboard] de config/workspace.toml. Workspace :
# ARC_WORKSPACE, sinon ~/.config/ai-running-coach/workspace, sinon ce dépôt.
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

PORT=""
OPEN=1
EXTRA=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) [[ $# -ge 2 ]] || die "--port attend un numéro"; PORT="$2"; shift 2 ;;
        --no-open) OPEN=0; shift ;;
        --memory) EXTRA+=(--memory); shift ;;
        --rebuild) REBUILD=1; shift ;;
        --help|-h) sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

have python3 || die "python3 introuvable — requis pour le tableau de bord."
PORT="${PORT:-$(toml_get dashboard port 8765)}"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "[dashboard].port : entier attendu, « $PORT » trouvé."

if [[ "${REBUILD:-0}" -eq 1 ]]; then
    python3 "$ARC_ENGINE_ROOT/scripts/arc_index.py" --workspace "$ARC_WORKSPACE" --rebuild >/dev/null \
        || die "Réindexation impossible — voir le message ci-dessus."
fi

log "Tableau de bord — workspace : $ARC_WORKSPACE"

open_browser() {
    local url="$1"
    [[ "$OPEN" -eq 1 ]] || return 0
    if have open; then open "$url" >/dev/null 2>&1 || true
    elif have xdg-open; then xdg-open "$url" >/dev/null 2>&1 || true
    fi
}

# Le serveur imprime « URL: http://127.0.0.1:<port>/ » dès qu'il écoute (port
# éventuellement décalé si le premier est pris) : on relaie la ligne, on ouvre.
python3 "$ARC_ENGINE_ROOT/scripts/arc_serve.py" --workspace "$ARC_WORKSPACE" --port "$PORT" ${EXTRA[@]+"${EXTRA[@]}"} \
    | while IFS= read -r line; do
        printf '%s\n' "$line"
        case "$line" in
            URL:*) ok "Ouvert sur ${line#URL: } — Ctrl+C pour arrêter"; open_browser "${line#URL: }" ;;
        esac
    done
