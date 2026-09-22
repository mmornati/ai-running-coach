#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — configuration des notifications push (ntfy) en une fois
#
# ntfy (https://ntfy.sh) : appli gratuite iOS/Android, sans compte. Ce script :
#   1. choisit le serveur (public ntfy.sh ou auto-hébergé) et le sujet (topic)
#   2. enregistre un token d'accès si le serveur l'exige (hors du dépôt, chmod 600)
#   3. écrit la section [notifications] dans config/workspace.user.toml (gitignoré)
#   4. envoie une notification de test
#
# Usage :
#   scripts/setup-ntfy.sh                         # interactif
#   scripts/setup-ntfy.sh --url https://ntfy.example.com --topic mon-sujet [--token-file ~/.config/ai-running-coach/ntfy.token]
#   scripts/setup-ntfy.sh --disable               # provider = "none"
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

URL=""; TOPIC=""; TOKEN_FILE=""; DISABLE=0; NO_TEST=0
DEFAULT_TOKEN_FILE="$HOME/.config/ai-running-coach/ntfy.token"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url) URL="$2"; shift 2 ;;
        --topic) TOPIC="$2"; shift 2 ;;
        --token-file) TOKEN_FILE="$2"; shift 2 ;;
        --disable) DISABLE=1; shift ;;
        --no-test) NO_TEST=1; shift ;;
        --help|-h) sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

random_topic() {
    printf 'running-coach-%s' "$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 8)"
}

# Remplace (ou ajoute) la section [notifications] dans workspace.user.toml en
# conservant le reste du fichier.
write_user_config() {
    local provider="$1" url="$2" topic="$3" token_file="$4"
    local tmp
    tmp="$(mktemp)"
    if [[ -f "$ARC_CONFIG_USER" ]]; then
        awk '
            /^[[:space:]]*\[notifications\]/ { skip = 1; next }
            /^[[:space:]]*\[/ { skip = 0 }
            !skip' "$ARC_CONFIG_USER" > "$tmp"
    else
        cat > "$tmp" <<'HDR'
# Overrides personnels — ce fichier est GITIGNORÉ.
# Les valeurs ci-dessous priment sur config/workspace.toml (versionné).
HDR
    fi
    # supprime les lignes vides finales avant d'ajouter la section
    sed -i.bak -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$tmp" 2>/dev/null || true
    rm -f "$tmp.bak"
    cat >> "$tmp" <<EOT

[notifications]
# Généré par scripts/setup-ntfy.sh le $(date +%F)
provider = "$provider"
ntfy_url = "$url"
ntfy_topic = "$topic"
ntfy_token_file = "$token_file"
EOT
    mkdir -p "$(dirname "$ARC_CONFIG_USER")"
    mv "$tmp" "$ARC_CONFIG_USER"
    ok "Section [notifications] écrite dans $ARC_CONFIG_USER"
}

if [[ "$DISABLE" -eq 1 ]]; then
    write_user_config none "$(toml_get notifications ntfy_url https://ntfy.sh)" "$(toml_get notifications ntfy_topic)" "$(toml_get notifications ntfy_token_file)"
    ok "Notifications désactivées."
    exit 0
fi

log "Configuration des notifications ntfy"
echo

# --- 1. Serveur -------------------------------------------------------------
if [[ -z "$URL" && ! -t 0 ]]; then
    URL="$(toml_get notifications ntfy_url https://ntfy.sh)"
fi
if [[ -z "$URL" ]]; then
    current="$(toml_get notifications ntfy_url https://ntfy.sh)"
    echo "Serveur ntfy :"
    echo "  1) public  — https://ntfy.sh (gratuit, aucun compte ; le sujet fait office de secret)"
    echo "  2) auto-hébergé — votre propre serveur (ex. https://ntfy.mondomaine.fr)"
    read -r -p "Choix [1/2] (défaut : 1) : " choice
    case "${choice:-1}" in
        2) read -r -p "URL du serveur [$current] : " URL; URL="${URL:-$current}" ;;
        *) URL="https://ntfy.sh" ;;
    esac
fi
URL="${URL%/}"

# --- 2. Sujet ---------------------------------------------------------------
if [[ -z "$TOPIC" && ! -t 0 ]]; then
    TOPIC="$(toml_get notifications ntfy_topic)"
    [[ -n "$TOPIC" ]] || die "--topic requis en mode non interactif."
fi
if [[ -z "$TOPIC" ]]; then
    suggested="$(toml_get notifications ntfy_topic)"
    [[ -n "$suggested" ]] || suggested="$(random_topic)"
    read -r -p "Sujet (topic) [$suggested] : " TOPIC
    TOPIC="${TOPIC:-$suggested}"
fi

# --- 3. Token (serveur avec authentification) --------------------------------
if [[ -z "$TOKEN_FILE" && "$URL" != "https://ntfy.sh" && -t 0 ]]; then
    echo
    echo "Si votre serveur exige une authentification (auth-default-access: deny-all),"
    echo "créez un utilisateur + token côté serveur, par exemple :"
    echo "  ntfy user add --role=user coach            # ou : docker exec -it ntfy ntfy user add ..."
    echo "  ntfy access coach $TOPIC write-only"
    echo "  ntfy token add coach                       # → tk_xxxxxxxx"
    read -r -p "Token d'accès (laisser vide si le serveur n'en exige pas) : " token
    if [[ -n "$token" ]]; then
        TOKEN_FILE="$DEFAULT_TOKEN_FILE"
        mkdir -p "$(dirname "$TOKEN_FILE")"
        (umask 077; printf '%s\n' "$token" > "$TOKEN_FILE")
        ok "Token enregistré dans $TOKEN_FILE (chmod 600, hors du dépôt)"
    fi
fi
if [[ -n "$TOKEN_FILE" ]]; then
    TOKEN_FILE_EXPANDED="$(expand_path "$TOKEN_FILE")"
    [[ -f "$TOKEN_FILE_EXPANDED" ]] || die "Fichier token introuvable : $TOKEN_FILE_EXPANDED"
    chmod 600 "$TOKEN_FILE_EXPANDED" 2>/dev/null || true
    # stocke la forme ~ pour rester portable entre machines
    TOKEN_FILE="${TOKEN_FILE_EXPANDED/#$HOME/\~}"
fi

# --- 4. Écriture + test --------------------------------------------------------
write_user_config ntfy "$URL" "$TOPIC" "$TOKEN_FILE"

echo
log "Sur votre téléphone : installez l'appli ntfy, puis « + » → abonnez-vous à :"
echo "    serveur : $URL"
echo "    sujet   : $TOPIC"
echo

if [[ "$NO_TEST" -eq 0 && -t 0 ]]; then
    read -r -p "Envoyer une notification de test maintenant ? [O/n] : " yn
    if [[ "${yn:-o}" =~ ^([oO]([uU][iI])?|[yY]([eE][sS])?)$ ]]; then
        "$ARC_ENGINE_ROOT/scripts/notify.sh" --title "AI Running Coach" --tags "white_check_mark" \
            "Notifications configurées ✅ — vous recevrez ici le résumé de chaque synchronisation Garmin."
    fi
fi
ok "Terminé. Les synchronisations automatiques (scripts/daily-sync.sh) enverront leur résumé ici."
