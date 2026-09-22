#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — helpers partagés par les scripts (config TOML, logs)
#
# Sourcé par scripts/daily-sync.sh, scripts/notify.sh, scripts/setup-ntfy.sh,
# scripts/coach-remote.sh. Lecture minimaliste de config/workspace.toml +
# config/workspace.user.toml (overrides), sans dépendance Python : suffisant
# pour des clés `cle = "valeur"`, `cle = 12`, `cle = ["a", "b"]`.
#
# Deux racines :
#   ARC_ENGINE_ROOT — le moteur (ce dépôt : agents, skills, scripts)
#   ARC_WORKSPACE   — le workspace (données personnelles, config, logs, .mcp.json) :
#                     variable ARC_WORKSPACE, sinon ~/.config/ai-running-coach/workspace
#                     (écrit par ./install.sh --workspace), sinon le moteur lui-même.
# =============================================================================

ARC_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARC_ENGINE_ROOT="$(cd "$ARC_LIB_DIR/../.." && pwd)"
ARC_WORKSPACE_STATE_FILE="$HOME/.config/ai-running-coach/workspace"
if [[ -z "${ARC_WORKSPACE:-}" && -f "$ARC_WORKSPACE_STATE_FILE" ]]; then
    ARC_WORKSPACE="$(head -n1 "$ARC_WORKSPACE_STATE_FILE")"
fi
if [[ -z "${ARC_WORKSPACE:-}" || ! -d "${ARC_WORKSPACE:-}" ]]; then
    ARC_WORKSPACE="$ARC_ENGINE_ROOT"
fi
# shellcheck disable=SC2034  # exposé aux scripts qui sourcent ce fichier
ARC_PROJECT_ROOT="$ARC_WORKSPACE"   # compatibilité
ARC_CONFIG="$ARC_WORKSPACE/config/workspace.toml"
[[ -f "$ARC_CONFIG" ]] || ARC_CONFIG="$ARC_ENGINE_ROOT/config/workspace.toml"
ARC_CONFIG_USER="$ARC_WORKSPACE/config/workspace.user.toml"

# shellcheck disable=SC2034  # palette exposée aux scripts qui sourcent ce fichier
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
#
# Ce n'est pas un analyseur TOML complet — le projet n'en a pas besoin — mais il
# doit être honnête sur le sous-ensemble qu'il lit : les valeurs rendues ici
# pilotent le cron, les notifications et la sélection des agents.
#
# Statut : 0 = clé trouvée (la valeur peut être vide), 1 = clé absente. Cette
# distinction est nécessaire pour qu'un `cle = ""` dans workspace.user.toml
# efface une valeur héritée au lieu de retomber sur le défaut codé en dur.
#
# Usage : toml_get_file <fichier> <section> <cle>
toml_get_file() {
    local file="$1" section="$2" key="$3"
    [[ -f "$file" ]] || return 1
    awk -v section="$section" -v key="$key" '
        # Retire un commentaire de fin de ligne, sans toucher aux « # » situés
        # dans une chaîne : ntfy_topic = "run #42" doit rester intact.
        function strip_comment(s,   i, c, inq, out) {
            inq = 0; out = ""
            for (i = 1; i <= length(s); i++) {
                c = substr(s, i, 1)
                if (c == "\"") { inq = !inq }
                else if (c == "#" && !inq) { break }
                out = out c
            }
            return out
        }
        function trim(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
        function unquote(s) {
            if (length(s) >= 2 && substr(s, 1, 1) == "\"" && substr(s, length(s), 1) == "\"")
                return substr(s, 2, length(s) - 2)
            return s
        }
        {
            # Un tableau peut être réparti sur plusieurs lignes : on accumule
            # jusqu au crochet fermant. Sans cela la valeur lue était « [ » et
            # l appelant retombait silencieusement sur son défaut.
            if (collecting) {
                buffer = buffer " " trim(strip_comment($0))
                if (index($0, "]") > 0) { print trim(buffer); found = 1; exit 0 }
                next
            }
            line = trim(strip_comment($0))
            if (line == "") next
            if (substr(line, 1, 1) == "[") {
                header = line
                gsub(/^\[|\]$/, "", header)
                in_section = (header == section)
                next
            }
            if (!in_section) next
            eq = index(line, "=")
            if (eq == 0) next
            if (trim(substr(line, 1, eq - 1)) != key) next
            value = trim(substr(line, eq + 1))
            if (substr(value, 1, 1) == "[" && index(value, "]") == 0) {
                collecting = 1; buffer = value; next
            }
            print unquote(value); found = 1; exit 0
        }
        END { if (!found) exit 1 }   # clé absente
    ' "$file"
}

# Lit une clé avec la règle de précédence du projet :
# workspace.user.toml > workspace.toml > valeur par défaut.
# Une clé PRÉSENTE mais vide gagne : c'est la façon d'annuler un héritage.
# Usage : toml_get <section> <cle> [defaut]
toml_get() {
    local section="$1" key="$2" default="${3:-}" v
    if v="$(toml_get_file "$ARC_CONFIG_USER" "$section" "$key")"; then
        printf '%s' "$v"; return 0
    fi
    if v="$(toml_get_file "$ARC_CONFIG" "$section" "$key")"; then
        printf '%s' "$v"; return 0
    fi
    printf '%s' "$default"
}

# Lit un tableau de chaînes `cle = ["a", "b"]` → une valeur par ligne.
# Un tableau explicitement vide (`cle = []`) ne rend rien — ce n'est pas la même
# chose qu'une clé absente, qui rend le défaut.
# Usage : toml_get_list <section> <cle> [defaut "a b"]
toml_get_list() {
    local section="$1" key="$2" default="${3:-}" raw
    if ! raw="$(toml_get_file "$ARC_CONFIG_USER" "$section" "$key")"; then
        if ! raw="$(toml_get_file "$ARC_CONFIG" "$section" "$key")"; then
            # découpage voulu sur les espaces du défaut
            # shellcheck disable=SC2086
            printf '%s\n' $default
            return 0
        fi
    fi
    raw="${raw#[}"; raw="${raw%]}"
    printf '%s\n' "$raw" | tr ',' '\n' | sed -E 's/^[[:space:]]*"?//; s/"?[[:space:]]*$//' | sed '/^$/d'
}

# Développe un chemin commençant par ~
expand_path() { printf '%s' "${1/#\~/$HOME}"; }
