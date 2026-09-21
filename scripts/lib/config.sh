#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — helpers partagés par les scripts (config TOML, logs)
#
# Sourcé par scripts/daily-sync.sh, scripts/notify.sh, scripts/setup-ntfy.sh,
# scripts/coach-remote.sh. Lecture minimaliste de config/workspace.toml +
# config/workspace.user.toml (overrides), sans dépendance Python : suffisant
# pour des clés `cle = "valeur"`, `cle = 12`, `cle = ["a", "b"]`.
# =============================================================================

ARC_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARC_PROJECT_ROOT="${ARC_PROJECT_ROOT:-$(cd "$ARC_LIB_DIR/../.." && pwd)}"
ARC_CONFIG="$ARC_PROJECT_ROOT/config/workspace.toml"
ARC_CONFIG_USER="$ARC_PROJECT_ROOT/config/workspace.user.toml"

if [[ -t 1 ]]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_RESET=""
fi

log()  { printf '%s\n' "${C_BLUE}==>${C_RESET} $*"; }
ok()   { printf '%s\n' "${C_GREEN}✔${C_RESET} $*"; }
warn() { printf '%s\n' "${C_YELLOW}⚠${C_RESET} $*"; }
err()  { printf '%s\n' "${C_RED}✖${C_RESET} $*" >&2; }
die()  { err "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Lit une clé scalaire dans une section d'un fichier TOML.
# Usage : toml_get_file <fichier> <section> <cle>  → valeur (sans guillemets) ou rien
toml_get_file() {
    local file="$1" section="$2" key="$3"
    [[ -f "$file" ]] || return 0
    awk -v section="$section" -v key="$key" '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*\[/ {
            gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "")
            in_section = ($0 == section); next
        }
        in_section {
            split($0, kv, "=")
            k = kv[1]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
            if (k != key) next
            v = substr($0, index($0, "=") + 1)
            sub(/[[:space:]]+#.*$/, "", v)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
            gsub(/^"|"$/, "", v)
            print v; exit
        }' "$file"
}

# Lit une clé avec la règle de précédence du projet :
# workspace.user.toml > workspace.toml > valeur par défaut.
# Usage : toml_get <section> <cle> [defaut]
toml_get() {
    local section="$1" key="$2" default="${3:-}" v
    v="$(toml_get_file "$ARC_CONFIG_USER" "$section" "$key")"
    [[ -n "$v" ]] || v="$(toml_get_file "$ARC_CONFIG" "$section" "$key")"
    [[ -n "$v" ]] || v="$default"
    printf '%s' "$v"
}

# Lit un tableau de chaînes `cle = ["a", "b"]` → une valeur par ligne.
# Usage : toml_get_list <section> <cle> [defaut "a b"]
toml_get_list() {
    local section="$1" key="$2" default="${3:-}" raw
    raw="$(toml_get "$section" "$key")"
    if [[ -z "$raw" ]]; then
        printf '%s\n' $default
        return 0
    fi
    raw="${raw#[}"; raw="${raw%]}"
    printf '%s\n' "$raw" | tr ',' '\n' | sed -E 's/^[[:space:]]*"?//; s/"?[[:space:]]*$//' | sed '/^$/d'
}

# Développe un chemin commençant par ~
expand_path() { printf '%s' "${1/#\~/$HOME}"; }
