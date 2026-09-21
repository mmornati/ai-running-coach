#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — envoi d'une notification push (ntfy)
#
# Usage :
#   scripts/notify.sh [--title "Titre"] [--priority 1-5] [--tags "tag1,tag2"] "message"
#   echo "message" | scripts/notify.sh --title "Titre"
#
# Configuration : section [notifications] de config/workspace.toml
# (overrides dans config/workspace.user.toml — voir scripts/setup-ntfy.sh) :
#   provider        = "ntfy" | "none"
#   ntfy_url        = "https://ntfy.sh"          # ou votre serveur auto-hébergé
#   ntfy_topic      = "running-coach-xxxx"
#   ntfy_token_file = "~/.config/ai-running-coach/ntfy.token"  # optionnel (serveur avec auth)
#
# Codes de sortie : 0 envoyé (ou provider=none), 1 erreur de configuration, 2 échec réseau.
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

TITLE="AI Running Coach"
PRIORITY="3"
TAGS="running"
MESSAGE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --title) TITLE="$2"; shift 2 ;;
        --priority) PRIORITY="$2"; shift 2 ;;
        --tags) TAGS="$2"; shift 2 ;;
        --help|-h) sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) MESSAGE="$1"; shift ;;
    esac
done
if [[ -z "$MESSAGE" && ! -t 0 ]]; then
    MESSAGE="$(cat)"
fi
[[ -n "$MESSAGE" ]] || die "Aucun message à envoyer."

PROVIDER="$(toml_get notifications provider none)"
case "$PROVIDER" in
    none)
        warn "Notifications désactivées (provider = \"none\") — message non envoyé :"
        printf '%s\n' "$MESSAGE"
        exit 0 ;;
    ntfy) ;;
    *) die "Provider de notification inconnu : $PROVIDER (ntfy|none)" ;;
esac

NTFY_URL="$(toml_get notifications ntfy_url https://ntfy.sh)"
NTFY_TOPIC="$(toml_get notifications ntfy_topic)"
NTFY_TOKEN_FILE="$(expand_path "$(toml_get notifications ntfy_token_file)")"
[[ -n "$NTFY_TOPIC" ]] || die "ntfy_topic manquant — lancez scripts/setup-ntfy.sh"

auth=()
if [[ -n "$NTFY_TOKEN_FILE" ]]; then
    [[ -f "$NTFY_TOKEN_FILE" ]] || die "Fichier token introuvable : $NTFY_TOKEN_FILE"
    auth=(-H "Authorization: Bearer $(tr -d '[:space:]' < "$NTFY_TOKEN_FILE")")
fi

# ntfy accepte le corps brut (multi-lignes) + en-têtes pour titre/priorité/tags.
if curl -fsS --max-time 15 ${auth[@]+"${auth[@]}"} \
        -H "Title: $TITLE" -H "Priority: $PRIORITY" -H "Tags: $TAGS" \
        --data-binary "$MESSAGE" "${NTFY_URL%/}/$NTFY_TOPIC" >/dev/null; then
    ok "Notification envoyée sur ${NTFY_URL%/}/$NTFY_TOPIC"
else
    err "Échec de l'envoi vers ${NTFY_URL%/}/$NTFY_TOPIC (token ? réseau ?)"
    exit 2
fi
