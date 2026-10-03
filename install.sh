#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — Script d'installation
#
# Installe et configure tout ce qu'il faut pour utiliser les agents/skills de
# coaching trail-running avec accès Garmin (ou Intervals.icu, --source intervals, ou Strava, --source strava,
# pour les athlètes sans montre Garmin — #68) :
#   1. uv (gestionnaire Python)
#   2. garmin-mcp + garmin-mcp-auth (accès Garmin Connect) — mode DIRECT par défaut,
#      OU intervals-icu-mcp + intervals-icu-mcp-auth avec --source intervals (jamais les deux)
#   3. (Optionnel) leanproxy-mcp — passerelle MCP "power user", source garmin uniquement (--use-leanproxy)
#   4. Configuration des IDE (Claude Code, GitHub Copilot, OpenCode, Gemini CLI,
#      Cursor, Windsurf)
#   5. (Optionnel) Workspace séparé (--workspace DIR) : vos données personnelles
#      dans votre propre dépôt privé, le moteur (agents/skills) lié dedans —
#      voir docs/workspace.md
#   6. (Optionnel) Machine « coach » toujours allumée : synchronisation Garmin
#      automatique (--daily-sync) et coach accessible depuis le téléphone via
#      Claude Code Remote Control (--remote-control) — voir docs/mobile.md
#   7. Vérification finale
#
# Usage :
#   ./install.sh                    # installation interactive (mode direct Garmin)
#   ./install.sh --ide claude       # installe pour un IDE précis
#   ./install.sh --ide copilot      # GitHub Copilot (CLI, VS Code, agent cloud)
#   ./install.sh --source intervals # Intervals.icu au lieu de Garmin (#68)
#   ./install.sh --source strava    # Strava au lieu de Garmin (#164)
#   ./install.sh --workspace DIR    # données + config IDE dans DIR (dépôt privé), moteur lié
#   ./install.sh --agents LISTE     # staff à installer, ex. coach,nutritionist
#   ./install.sh --no-medical       # tous les agents sauf le médecin
#   ./install.sh --no-auth          # saute l'authentification Garmin
#   ./install.sh --use-leanproxy    # mode passerelle leanproxy (power user)
#   ./install.sh --daily-sync       # cron/launchd : sync Garmin aux heures de [sync].times
#   ./install.sh --remote-control   # service Remote Control (le coach dans la poche)
#   ./install.sh --llm openrouter   # chat + sync sur une API (openrouter|anthropic|openai)
#   ./install.sh --chat             # service du chat avec le coach (dashboard)
#   ./install.sh --dry-run          # affiche les actions sans rien exécuter
#   ./install.sh --help
#
# Prérequis : macOS ou Linux, bash 3.2+ (celui de macOS convient), curl, git.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
VERSION="0.2.0"
# Épinglé à un commit précis, comme INTERVALS_MCP_REF ci-dessous : ce serveur reçoit le
# mot de passe et le code MFA Garmin à l'authentification, puis tourne à chaque
# synchronisation — un changement en amont ne doit jamais être exécuté sans relecture.
# Mettre à jour après vérification du diff amont.
GARMIN_MCP_REF="git+https://github.com/Taxuspt/garmin_mcp@cfc5d799ab0f165e837f1188a1d093c65838aaf7"
# Source alternative (#68) : serveur MCP communautaire déjà référencé par
# docs/faq.md avant cette story (hypothèse de travail des tests, désormais
# celui réellement installé par --source intervals). project.scripts expose
# `intervals-icu-mcp` + `intervals-icu-mcp-auth`, comme garmin_mcp/garmin-mcp-auth
# ci-dessus — même mécanique `uv tool install git+…`.
# Épinglé à un commit précis (vérifié : project.scripts, tools/*.py, réponses
# JSON) plutôt qu'à `main` — un changement en amont (renommage d'outil, retrait
# de champ) ne doit jamais casser silencieusement ce projet. Documenté dans
# docs/intervals-setup.md ; mettre à jour les deux ensemble après vérification.
INTERVALS_MCP_REF="git+https://github.com/eddmann/intervals-icu-mcp@cb91d4a0f3b4dc21f57421e029c07a8e9af11649"
# Le serveur charge ses identifiants depuis un `.env` relatif à SON répertoire
# de travail (pydantic-settings) — jamais depuis le dépôt : `intervals-icu-mcp-auth`
# est donc lancé depuis ce dossier dédié, hors du projet, comme `$GARMIN_TOKENS_DIR`
# ci-dessous pour Garmin.
INTERVALS_ENV_DIR="$HOME/.config/ai-running-coach/intervals-icu-mcp"
# Source Strava (#164) : serveur MCP communautaire r-huijts/strava-mcp, publié sur npm
# (`@r-huijts/strava-mcp-server`, bin `strava-mcp-server`, stdio). Épinglé à la version 1.2.1,
# vérifiée contre le commit ac43cc7b0aad2f218b9c42bd639aee696dbee531 du dépôt (package.json,
# src/server.ts, src/config.ts) — l'identité entre ce commit et le tarball npm n'est PAS vérifiée
# octet pour octet (à relire avant de relever la version). Documenté dans docs/strava-setup.md ;
# mettre à jour les deux ensemble. Ce serveur reçoit le client secret de l'application Strava de
# l'athlète et tourne à chaque synchronisation : ne jamais le laisser flotter sur `latest`.
STRAVA_MCP_PKG="@r-huijts/strava-mcp-server@1.2.1"
# Wrapper du projet (même rôle que celui d'intervals : une commande stable et reconnaissable
# par le nettoyage au changement de source) ; les jetons, eux, vivent dans le fichier du SERVEUR
# (~/.config/strava-mcp/config.json), jamais ici ni dans une config d'IDE.
STRAVA_MCP_DIR="$HOME/.config/ai-running-coach/strava-mcp"
STRAVA_TOKEN_FILE="$HOME/.config/strava-mcp/config.json"
LEANPROXY_BREW_TAP="mmornati/leanproxy-mcp"
LEANPROXY_FORMULA="leanproxy-mcp"
GARMIN_TOKENS_DIR="$HOME/.garminconnect"
LEANPROXY_CONFIG_DIR="$HOME/.config/leanproxy"
LEANPROXY_SERVERS="$HOME/.config/leanproxy_servers.yaml"

# Liste blanche des outils Garmin utilisés par les agents/skills du projet.
# Réduit la taxe de contexte (~151 outils → ~30) en mode direct.
# Noms réels des outils garmin-mcp (sans préfixe garmin_).
GARMIN_TOOL_WHITELIST="get_activities,get_activities_by_date,get_activity,get_activity_fit_data,get_activity_splits,get_activity_typed_splits,get_activity_split_summaries,get_sleep_data,get_hrv_data,get_rhr_day,get_training_readiness,get_calendar_events,get_courses,get_workouts,get_workout_by_id,get_scheduled_workouts,schedule_workouts,schedule_week,upload_workout,upload_course,create_strength_workout,delete_workout,unschedule_workout,unschedule_workouts,download_activity_file,get_stats,get_lactate_threshold,get_training_status,get_gear,get_activity_gear,add_gear_to_activity"

# Chat avec le coach et sync sur une API (--llm) : modèles par défaut, UNE constante
# chacun. Identifiant OpenRouter « deepseek/deepseek-v4.1-flash » vérifié dans le catalogue
# https://openrouter.ai/api/v1/models et comparé à 7 autres modèles en conditions réelles
# (docs/dashboard/chat.md, « Quel modèle sur OpenRouter ? ») : le plus fiable et le moins cher.
# L'ancien « deepseek/deepseek-chat » (V3) annonçait des écritures jamais faites. Forme OpenCode « fournisseur/modèle »
# (https://opencode.ai/docs/providers). Haiku 4.5 pour le cron (répétitif, contrat
# vérifié par arc_index.py --validate), Sonnet 5.5 pour le chat.
LLM_OPENROUTER_MODEL="openrouter/deepseek/deepseek-v4.1-flash"
LLM_ANTHROPIC_CHAT_MODEL="claude-sonnet-5-5"
LLM_ANTHROPIC_SYNC_MODEL="claude-haiku-4-5"
# Clés API : dans ce fichier (mode 600), jamais dans le TOML ni dans le shell.
LLM_ENV_FILE="${ARC_LLM_ENV:-$HOME/.config/ai-running-coach/llm.env}"

# Détection du répertoire du projet (racine du dépôt) = le « moteur »
# (agents, skills, scripts). Le workspace (données personnelles + config IDE)
# est le même dossier par défaut, ou celui passé à --workspace.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR" && pwd)"
WORKSPACE_ROOT="$PROJECT_ROOT"
WORKSPACE_STATE_FILE="$HOME/.config/ai-running-coach/workspace"

# ---------------------------------------------------------------------------
# Couleurs (si terminal interactif)
# ---------------------------------------------------------------------------
# shellcheck disable=SC2034  # C_BOLD fait partie de la palette, utilisé au besoin
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

# ---------------------------------------------------------------------------
# Options par défaut
# ---------------------------------------------------------------------------
DRY_RUN=0
DO_AUTH=1
IDE="all"          # all | claude | copilot | opencode | gemini | cursor | windsurf
USE_LEANPROXY=0    # mode passerelle (power user) — défaut : direct
DAILY_SYNC=0       # cron/launchd de synchronisation Garmin automatique
WORKSPACE_ARG=""   # --workspace DIR (défaut : le dossier du projet)
REMOTE_CONTROL=0   # service Claude Code Remote Control (accès mobile)
AGENTS_ARG=""      # --agents coach,medical,… (défaut : la config, sinon tous)
ENABLED_AGENTS=""  # résolu par resolve_agents()
PRESET=""          # --preset laptop|coach-server|docker (défaut : aucun)
SOURCE="garmin"    # --source garmin|intervals|strava (#68, #164) — source de données primaire
LLM_PROVIDER=""    # --llm openrouter|anthropic|openai — chat + sync sur une API
LLM_MODEL_ARG=""   # --model ID (avec --llm)
LLM_BASE_URL_ARG="" # --base-url URL (avec --llm openai : API compatible OpenAI)
DO_CHAT=0          # --chat : service du chat avec le coach
CHAT_BUDGET=""     # --chat-budget EUR
SYNC_BUDGET=""     # --sync-budget EUR

# Options qu'un préréglage peut fixer ; « explicite » gagne toujours, quel que
# soit l'ordre des arguments (voir apply_preset() et la note plus bas).
#
# --source n'est PAS composée par un préréglage (laptop/coach-server/docker
# décrivent OÙ vous installez, pas QUELLE source de données vous avez — les
# deux axes sont orthogonaux) : dans le récapitulatif, son origine n'est donc
# jamais « préréglage X », seulement « explicite » ou « défaut ».
EXPLICIT_IDE=0
EXPLICIT_DO_AUTH=0
EXPLICIT_LEANPROXY=0
EXPLICIT_DAILY_SYNC=0
EXPLICIT_REMOTE_CONTROL=0
EXPLICIT_AGENTS=0
EXPLICIT_SOURCE=0
# Vrai (1) uniquement quand --source a été passé explicitement ET que la
# valeur résolue diffère de celle DÉJÀ en config (resolve_source()) — jamais
# sur un simple rerun sans --source. C'est ce qui protège un serveur MCP
# `intervals` ajouté À LA MAIN par un utilisateur Garmin (docs/faq.md,
# « configurer Intervals.icu en secondaire ») : sans cette distinction,
# `cleanup_stale_mcp_server()` le supprimerait à CHAQUE `./install.sh`, y
# compris ceux qui ne touchent jamais à --source (revue PR #116).
SOURCE_CHANGED=0

usage() {
    cat <<'USAGE'
ai-running-coach — script d'installation

Usage :
  ./install.sh                    # installation (mode direct Garmin)
  ./install.sh --preset PRESET    # laptop | coach-server | docker — voir --help ci-dessous
  ./install.sh --ide IDE          # claude | copilot | opencode | gemini | cursor | windsurf
  ./install.sh --source SOURCE    # garmin (défaut) | intervals | strava — source de données primaire (#68, #164)
  ./install.sh --workspace DIR    # données + config IDE dans DIR (dépôt privé), moteur lié
  ./install.sh --agents LISTE     # staff à installer, ex. coach,nutritionist
  ./install.sh --no-medical       # tous les agents sauf le médecin
  ./install.sh --no-auth          # saute l'authentification Garmin
  ./install.sh --auth             # force l'authentification Garmin (annule --no-auth d'un préréglage)
  ./install.sh --use-leanproxy    # mode passerelle leanproxy (power user)
  ./install.sh --skip-leanproxy   # mode direct (annule --use-leanproxy d'un préréglage)
  ./install.sh --daily-sync       # cron/launchd : sync Garmin aux heures de [sync].times
  ./install.sh --no-daily-sync    # désactive la sync (annule --daily-sync d'un préréglage)
  ./install.sh --remote-control   # service Remote Control (le coach dans la poche)
  ./install.sh --no-remote-control # désactive Remote Control (annule --remote-control d'un préréglage)
  ./install.sh --llm FOURNISSEUR  # openrouter | anthropic | openai — chat ET sync sur une API (voir ci-dessous)
  ./install.sh --model ID         # avec --llm : modèle (openrouter : ID OpenRouter ; anthropic : modèle du chat)
  ./install.sh --base-url URL     # avec --llm openai : API compatible OpenAI autre que api.openai.com
  ./install.sh --chat             # active [chat] et installe le service (scripts/coach-chat.sh)
  ./install.sh --chat-budget EUR  # plafond quotidien du chat ([chat].daily_budget_eur)
  ./install.sh --sync-budget EUR  # plafond quotidien de la sync ([sync].daily_budget_eur)
  ./install.sh --dry-run          # affiche les actions sans rien exécuter
  ./install.sh --help

--llm écrit à la fois [chat] et [sync] de config/workspace.user.toml. Une valeur
DÉJÀ posée qui diffère est REMPLACÉE, avec un avertissement « ancien → nouveau »
et la façon de revenir ; un rerun sans --llm ne touche jamais à ces clés. La clé
API n'est jamais écrite dans la config : ~/.config/ai-running-coach/llm.env
(mode 600, créé avec une ligne d'exemple commentée) — à remplir vous-même.
ATTENTION : n'exportez PAS ANTHROPIC_API_KEY dans votre shell ou votre profil :
cela empêche Remote Control de fonctionner (docs/mobile.md). Le chat et la sync
la lisent dans llm.env et ne la passent qu'à leur propre process.

Préréglages (--preset), chacun ne fait que composer les options ci-dessus —
toute option passée explicitement l'emporte toujours, quel que soit l'ordre
(« --preset laptop --daily-sync » et « --daily-sync --preset laptop » sont
équivalents ; utilisez --auth/--no-daily-sync/--no-remote-control pour
désactiver ce qu'un préréglage aurait activé) :

  laptop        --ide all                          (docs/quickstart.md : usage interactif
                                                      sur votre machine, tous les IDE — c'est
                                                      exactement la configuration par défaut)
  coach-server  --ide claude --daily-sync
                --remote-control                    (docs/mobile.md : machine « coach »
                                                      toujours allumée, sync + téléphone)
  docker        --ide claude --daily-sync           (docs/dashboard/docker.md : machine
                                                      « coach » qui sert AUSSI le tableau de
                                                      bord en conteneur — la sync a besoin de
                                                      l'authentification Garmin comme sur
                                                      n'importe quelle machine coach, donc
                                                      elle reste active ; pas de Remote
                                                      Control, l'interface de cette machine
                                                      est le tableau de bord web. Le
                                                      préréglage ne prépare que l'hôte : le
                                                      conteneur lui-même se lance séparément
                                                      avec « docker compose up -d --build »,
                                                      voir docs/dashboard/docker.md)

Prérequis : macOS ou Linux, bash 3.2+, curl, git.
Documentation : https://mmornati.github.io/ai-running-coach/
USAGE
    exit 0
}

# Vérifie qu'une option attendant une valeur en a bien reçu une. Sans cela,
# « ./install.sh --ide » meurt sur « $2: unbound variable » (set -u).
need_value() {
    [[ $# -ge 2 && -n "${2:-}" ]] || die "L'option $1 attend une valeur (voir --help)."
}

# Préréglages : ne fixent QUE des valeurs pour des options qui existent déjà —
# jamais de comportement qui ne serait pas atteignable avec le script actuel.
# Un préréglage inconnu est une erreur claire, non silencieuse.
VALID_PRESETS="laptop coach-server docker"

apply_preset() {
    case "$1" in
        laptop)
            # docs/quickstart.md : installation interactive sur sa propre machine,
            # tous les IDE (le parcours documenté est « ./install.sh » sans --ide),
            # pas de synchronisation automatique ni de Remote Control (réservés à
            # la machine « coach », voir docs/mobile.md).
            PRESET_IDE="all"
            PRESET_DO_AUTH=1
            PRESET_USE_LEANPROXY=0
            PRESET_DAILY_SYNC=0
            PRESET_REMOTE_CONTROL=0
            ;;
        coach-server)
            # docs/mobile.md, section « Installation pas à pas » : la machine
            # « coach » toujours allumée enchaîne exactement ces options
            # (étapes 2, 4 et 5) — Claude Code est l'IDE utilisé par le runner
            # de synchronisation et par Remote Control, l'authentification
            # Garmin reste interactive (fonctionne en SSH, tokens ~6 mois).
            PRESET_IDE="claude"
            PRESET_DO_AUTH=1
            PRESET_USE_LEANPROXY=0
            PRESET_DAILY_SYNC=1
            PRESET_REMOTE_CONTROL=1
            ;;
        docker)
            # docs/dashboard/docker.md : « Sur la machine coach, dans le dépôt
            # du moteur » — le conteneur du tableau de bord se déploie SUR la
            # machine coach, pas sur une machine à part. Sa synchronisation
            # Garmin (scripts/daily-sync.sh) a donc besoin d'une authentification
            # comme n'importe quelle machine coach : --no-auth romprait le cron,
            # qui échouerait deux fois par jour faute de tokens. --daily-sync
            # garde le workspace monté (lecture seule par le conteneur) à jour ;
            # --remote-control est sauté car l'interface de cette machine est le
            # tableau de bord web, pas le chat depuis le téléphone. Ce préréglage
            # ne prépare que l'HÔTE : le conteneur lui-même se lance séparément
            # avec « docker compose up -d --build » (docs/dashboard/docker.md).
            PRESET_IDE="claude"
            PRESET_DO_AUTH=1
            PRESET_USE_LEANPROXY=0
            PRESET_DAILY_SYNC=1
            PRESET_REMOTE_CONTROL=0
            ;;
        *)
            die "Préréglage inconnu : « $1 ». Valides : $VALID_PRESETS (voir --help)."
            ;;
    esac
}

# Repère --preset AVANT la boucle d'analyse normale, sans consommer les
# arguments : c'est ce qui permet à une option explicite de l'emporter sur le
# préréglage quel que soit l'ordre — « --preset x --foo » et « --foo --preset x »
# doivent produire le même résultat. Les valeurs du préréglage ne sont donc
# appliquées qu'AUX DÉFAUTS, avant que la boucle ci-dessous ne lise les
# options explicites (qui, elles, écrivent directement sur ces variables).
_scan_args=("$@")
_scan_n=${#_scan_args[@]}
_scan_i=0
while [[ "$_scan_i" -lt "$_scan_n" ]]; do
    if [[ "${_scan_args[$_scan_i]}" == "--preset" ]]; then
        _scan_i=$((_scan_i + 1))
        # Une valeur absente OU qui ressemble à une autre option (« --dry-run »)
        # est traitée comme une valeur manquante, jamais comme un préréglage
        # nommé « --dry-run » (qui échouerait avec un message trompeur).
        if [[ "$_scan_i" -ge "$_scan_n" || "${_scan_args[$_scan_i]}" == --* ]]; then
            die "L'option --preset attend une valeur (voir --help)."
        fi
        _scan_value="${_scan_args[$_scan_i]}"
        if [[ -n "$PRESET" && "$PRESET" != "$_scan_value" ]]; then
            die "Option --preset répétée avec des valeurs différentes : « $PRESET » puis « $_scan_value » (voir --help)."
        fi
        PRESET="$_scan_value"
    fi
    _scan_i=$((_scan_i + 1))
done
unset _scan_args _scan_n _scan_i _scan_value

if [[ -n "$PRESET" ]]; then
    apply_preset "$PRESET"
    IDE="$PRESET_IDE"
    DO_AUTH="$PRESET_DO_AUTH"
    USE_LEANPROXY="$PRESET_USE_LEANPROXY"
    DAILY_SYNC="$PRESET_DAILY_SYNC"
    REMOTE_CONTROL="$PRESET_REMOTE_CONTROL"
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --preset) need_value "$@"; shift 2 ;;  # déjà résolu ci-dessus
        --ide) need_value "$@"; IDE="$2"; EXPLICIT_IDE=1; shift 2 ;;
        --source) need_value "$@"; SOURCE="$2"; EXPLICIT_SOURCE=1; shift 2 ;;
        --no-auth) DO_AUTH=0; EXPLICIT_DO_AUTH=1; shift ;;
        --auth) DO_AUTH=1; EXPLICIT_DO_AUTH=1; shift ;;  # annule --no-auth composé par un préréglage
        --use-leanproxy) USE_LEANPROXY=1; EXPLICIT_LEANPROXY=1; shift ;;
        --skip-leanproxy) USE_LEANPROXY=0; EXPLICIT_LEANPROXY=1; shift ;;  # rétro-compatibilité
        --workspace) need_value "$@"; WORKSPACE_ARG="$2"; shift 2 ;;
        --agents) need_value "$@"; AGENTS_ARG="$2"; EXPLICIT_AGENTS=1; shift 2 ;;
        --no-medical) AGENTS_ARG="${AGENTS_ARG:-__all_but__}:medical"; EXPLICIT_AGENTS=1; shift ;;
        --daily-sync) DAILY_SYNC=1; EXPLICIT_DAILY_SYNC=1; shift ;;
        --no-daily-sync) DAILY_SYNC=0; EXPLICIT_DAILY_SYNC=1; shift ;;  # annule --daily-sync composé par un préréglage
        --remote-control) REMOTE_CONTROL=1; EXPLICIT_REMOTE_CONTROL=1; shift ;;
        --no-remote-control) REMOTE_CONTROL=0; EXPLICIT_REMOTE_CONTROL=1; shift ;;  # annule --remote-control composé par un préréglage
        --llm) need_value "$@"; LLM_PROVIDER="$2"; shift 2 ;;
        --model) need_value "$@"; LLM_MODEL_ARG="$2"; shift 2 ;;
        --base-url) need_value "$@"; LLM_BASE_URL_ARG="$2"; shift 2 ;;
        --chat) DO_CHAT=1; shift ;;
        --chat-budget) need_value "$@"; CHAT_BUDGET="$2"; shift 2 ;;
        --sync-budget) need_value "$@"; SYNC_BUDGET="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) usage ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

# Validation des options chat/llm : échec immédiat, avant tout travail.
validate_budget() {
    local flag="$1" value="$2"
    [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v v="$value" 'BEGIN { exit !(v + 0 > 0) }' \
        || die "$flag : nombre strictement positif attendu en EUR (reçu « $value »)."
}
[[ -z "$CHAT_BUDGET" ]] || validate_budget --chat-budget "$CHAT_BUDGET"
[[ -z "$SYNC_BUDGET" ]] || validate_budget --sync-budget "$SYNC_BUDGET"
if [[ -n "$LLM_PROVIDER" ]]; then
    case "$LLM_PROVIDER" in
        openrouter|anthropic) ;;
        openai) [[ -n "$LLM_MODEL_ARG" ]] || die "--llm openai exige --model (ex. --model gpt-4.1-mini ; ajoutez --base-url pour une autre API compatible OpenAI)." ;;
        *) die "Fournisseur LLM inconnu : « $LLM_PROVIDER ». Valides : openrouter, anthropic, openai (voir --help)." ;;
    esac
    if [[ -n "$LLM_BASE_URL_ARG" && "$LLM_PROVIDER" == "anthropic" ]]; then
        die "--base-url n'a pas de sens avec --llm anthropic (utilisez --llm openai pour une API compatible OpenAI)."
    fi
elif [[ -n "$LLM_MODEL_ARG" || -n "$LLM_BASE_URL_ARG" ]]; then
    die "--model et --base-url s'utilisent avec --llm (voir --help)."
fi

# Valide $SOURCE (défini ici pour être appelable dès l'analyse des arguments
# ET depuis resolve_source() dans main(), qui peut réécrire $SOURCE depuis la
# config existante).
validate_source() {
    case "$SOURCE" in
        garmin|intervals|strava) ;;
        *) die "Source de données inconnue : « $SOURCE ». Valides : garmin, intervals, strava (voir --help)." ;;
    esac
    if [[ "$SOURCE" != "garmin" && "$USE_LEANPROXY" -eq 1 ]]; then
        die "--use-leanproxy ne route que le serveur garmin — incompatible avec --source $SOURCE (voir --help)."
    fi
}

# Validation immédiate UNIQUEMENT si --source a été passé explicitement : une
# valeur invalide venue de la ligne de commande doit échouer tout de suite,
# avant tout travail. La valeur par défaut ("garmin") ou celle résolue depuis
# la config existante (resolve_source(), dans main() — après resolve_workspace,
# comme resolve_agents()) est revalidée là-bas.
if [[ "$EXPLICIT_SOURCE" -eq 1 ]]; then
    validate_source
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
run() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} $*"
        return 0
    fi
    "$@"
}

# Écrit un fichier depuis stdin (heredoc) — respecte le mode dry-run.
write_file() {
    local file="$1"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} écriture de $file"
        cat > /dev/null      # consomme le heredoc sans rien écrire
        return 0
    fi
    mkdir -p "$(dirname "$file")"
    cat > "$file"
}

# Échappe une chaîne pour l'insérer dans du XML (plist launchd) : un « & » dans
# un chemin suffit à produire un plist que launchctl refuse.
xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# Échappe une chaîne pour l'insérer dans une valeur JSON construite par
# `printf` (revue PR #116) : un `\` ou un `"` dans $HOME (donc dans
# $INTERVALS_ENV_DIR) produirait sinon un JSON invalide silencieusement écrit
# tel quel dans .mcp.json/opencode.json/etc.
json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# Fusionne une clé dans un fichier JSON sans toucher au reste (scripts/coach_config.py).
merge_json_key() {
    local file="$1" section="$2" name="$3" value="$4" template="${5:-}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} fusion de « $name » dans $file"
        return 0
    fi
    have python3 || { warn "python3 absent : $file non modifié (ajoutez « $name » à la main)."; return 0; }
    python3 "$PROJECT_ROOT/scripts/coach_config.py" merge-json \
        --file "$file" --section "$section" --name "$name" --value "$value" \
        ${template:+--template "$template"} >/dev/null \
        || die "Échec de la mise à jour de $file (voir le message ci-dessus)."
}

# Retire une clé d'un fichier JSON si elle y est ET que sa valeur « command »
# correspond exactement à $expected_command (chaîne, ou premier élément si
# c'est une liste — format OpenCode) — sans effet sinon. `expected_command`
# vide désactive ce garde-fou (comportement de `merge_json_key`/l'ancien
# `remove_json_key`, conservé pour d'éventuels autres appelants).
#
# Ce garde-fou protège un serveur MCP AJOUTÉ À LA MAIN par l'utilisateur (ex.
# un athlète Garmin qui a suivi docs/faq.md pour ajouter Intervals.icu en
# secondaire, `"command": "uv", "args": ["run", "--directory", …]`) : sans
# lui, basculer --source supprimerait aussi bien une entrée installée par
# install.sh qu'une entrée que l'utilisateur a écrite lui-même (revue PR #116).
remove_json_key() {
    local file="$1" section="$2" name="$3" expected_command="${4:-}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} retrait de « $name » de $file (si présent et « command » = « $expected_command »)"
        return 0
    fi
    [[ -f "$file" ]] || return 0
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" remove-json-key \
        --file "$file" --section "$section" --name "$name" \
        ${expected_command:+--expect-command "$expected_command"} >/dev/null \
        || warn "Impossible de nettoyer « $name » dans $file."
}

# Noms de serveur MCP à retirer d'une config quand la source a RÉELLEMENT
# changé (#68, revue PR #116) : sans ce nettoyage, basculer --source
# laisserait l'ancien serveur déclaré à côté du nouveau (l'IDE en propose un
# qui ne répond plus). Ne couvre QUE l'axe garmin<->intervals introduit par
# cette story — le pré-existant garmin<->leanproxy (--use-leanproxy) n'est
# pas traité ici, hors du périmètre de #68.
stale_mcp_server_names() {
    case "$SOURCE" in
        intervals) echo "garmin strava" ;;
        strava) echo "garmin intervals" ;;
        *) echo "intervals strava" ;;
    esac
}

# Commande EXACTE que install.sh écrit pour un serveur donné — jamais celle
# d'une entrée ajoutée à la main (voir remove_json_key()).
stale_mcp_expected_command() {
    case "$1" in
        garmin) echo "garmin-mcp" ;;
        intervals) echo "$INTERVALS_ENV_DIR/run.sh" ;;
        strava) echo "$STRAVA_MCP_DIR/run.sh" ;;
        *) echo "" ;;
    esac
}

# N'agit QUE si `--source` a réellement fait basculer la source (voir la note
# de SOURCE_CHANGED) — un rerun qui ne touche pas --source ne doit JAMAIS
# passer ici, même en présence d'une clé « intervals »/« garmin » ajoutée à
# la main par l'utilisateur.
cleanup_stale_mcp_server() {
    [[ "$SOURCE_CHANGED" -eq 1 ]] || return 0
    local file="$1" section="$2" stale
    for stale in $(stale_mcp_server_names); do
        remove_json_key "$file" "$section" "$stale" "$(stale_mcp_expected_command "$stale")"
    done
}

# Vrai si `name` est encore présent dans `section` de `file` — utilisé pour ne
# désapprouver dans ~/.claude.json (voir unapprove_claude_project_mcp()) QUE
# les entrées effectivement retirées de .mcp.json par cleanup_stale_mcp_server()
# ci-dessus, jamais une entrée ajoutée à la main qui a survécu au garde-fou
# --expect-command (revue PR #116).
mcp_server_key_exists() {
    local file="$1" section="$2" name="$3"
    [[ -f "$file" ]] || return 1
    have python3 || return 1
    python3 -c '
import json, sys
file, section, name = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    data = json.load(open(file, encoding="utf-8"))
except Exception:
    sys.exit(1)
sys.exit(0 if name in (data.get(section) or {}) else 1)
' "$file" "$section" "$name"
}

have() { command -v "$1" >/dev/null 2>&1; }

require_cmd() {
    local cmd="$1" hint="${2:-}"
    if ! have "$cmd"; then
        die "Commande '$cmd' introuvable. $hint"
    fi
}

# Catalogue d'agents : toujours un lien PAR AGENT, jamais un lien vers le dossier.
#
# C'est ce qui rend la sélection réelle — un lien vers `agents/` exposerait les
# quatre agents quoi qu'il arrive — et c'est aussi ce qui permet de RETIRER un
# agent désactivé lors d'une réinstallation. Sans cela, désactiver un agent sur
# une installation existante ne ferait rien du tout.
link_agents() {
    local target="$1" link="$2" name n=0 existing base
    if [[ ! -d "$target" ]]; then
        warn "Cible introuvable, catalogue d'agents ignoré : $target"
        return 0
    fi
    if [[ -L "$link" ]]; then
        rm -f "$link"                      # ancien format : lien vers le dossier
    elif [[ -e "$link" && ! -d "$link" ]]; then
        warn "$link existe et n'est pas un dossier — conservé tel quel."
        return 0
    fi
    mkdir -p "$link"
    for name in $ENABLED_AGENTS; do
        [[ -e "$target/$name.md" ]] || continue
        if [[ -e "$link/$name.md" && ! -L "$link/$name.md" ]]; then
            warn "$link/$name.md est un vrai fichier — conservé."
            continue
        fi
        ln -sfn "$target/$name.md" "$link/$name.md"
        n=$((n + 1))
    done
    # Retire les agents désactivés depuis la dernière installation, et les liens morts.
    for existing in "$link"/*.md; do
        [[ -L "$existing" ]] || continue
        base="$(basename "$existing" .md)"
        if ! printf '%s\n' $ENABLED_AGENTS | grep -qx "$base" || [[ ! -e "$existing" ]]; then
            rm -f "$existing"
            ok "Agent retiré : $base"
        fi
    done
    [[ "$n" -gt 0 ]] || die "Aucun agent lié dans $link — installation incomplète."
    ok "Catalogue $link : $n agent(s)"
}

# Rend le contenu de $target visible sous $link pour un IDE.
#
# Chemin rapide : $link n'existe pas → un simple lien symbolique vers $target.
# Cas réel et fréquent : Claude Code crée .claude/ (voire .claude/agents/) tout
# seul dès qu'on ouvre le projet. L'ancienne version renonçait alors en
# affichant un avertissement — aucun agent n'était installé et l'installation se
# déclarait malgré tout réussie. On remplit désormais le dossier existant avec
# un lien par élément, et on échoue bruyamment si rien n'a pu être lié.
link_catalog() {
    local target="$1" link="$2" src name n=0
    if [[ ! -d "$target" ]]; then
        warn "Cible introuvable, lien ignoré : $target"
        return 0
    fi
    if [[ -L "$link" || ! -e "$link" ]]; then
        mkdir -p "$(dirname "$link")"
        ln -sfn "$target" "$link"
        ok "Lien créé : $link -> $target"
        return 0
    fi
    if [[ ! -d "$link" ]]; then
        warn "$link existe et n'est pas un dossier — conservé tel quel."
        warn "Supprimez-le puis relancez si vous vouliez un lien vers $target."
        return 0
    fi
    for src in "$target"/*; do
        [[ -e "$src" ]] || continue
        name="$(basename "$src")"
        if [[ -e "$link/$name" && ! -L "$link/$name" ]]; then
            warn "$link/$name est un vrai fichier — conservé (le moteur est dans $src)."
            continue
        fi
        ln -sfn "$src" "$link/$name"
        n=$((n + 1))
    done
    for src in "$link"/*; do
        if [[ -L "$src" && ! -e "$src" ]]; then rm -f "$src"; fi   # lien mort
    done
    [[ "$n" -gt 0 ]] || die "Aucun élément lié dans $link (source : $target) — installation incomplète."
    ok "Catalogue $link : $n élément(s) lié(s)"
}

# Idem pour un fichier (AGENTS.md, config/workspace.toml) — un vrai fichier
# existant est conservé (l'utilisateur l'a peut-être personnalisé).
link_file() {
    local target="$1" link="$2"
    [[ -f "$target" ]] || { warn "Cible introuvable, lien ignoré : $target"; return 0; }
    if [[ -e "$link" && ! -L "$link" ]]; then
        warn "$link existe et n'est pas un lien — conservé tel quel (le moteur est dans $target)."
        return 0
    fi
    ln -sfn "$target" "$link"
    ok "Lien créé : $link -> $target"
}

# ---------------------------------------------------------------------------
# 0. Workspace séparé (--workspace DIR)
# ---------------------------------------------------------------------------
# Le workspace contient les données personnelles (activities/ … resources/),
# config/workspace.user.toml, et d'éventuels agents/skills privés dans
# local/agents et local/skills (versionnés dans votre dépôt privé). Le moteur y
# est LIÉ, jamais copié : agents/ et skills/ du workspace sont des catalogues de
# liens (moteur + local/), AGENTS.md et config/workspace.toml pointent vers le
# moteur. Tout ce qui est généré est ajouté au .gitignore du workspace.

resolve_workspace() {
    if [[ -z "$WORKSPACE_ARG" ]]; then
        return 0
    fi
    if [[ ! -d "$WORKSPACE_ARG" ]]; then
        if [[ "$DRY_RUN" -eq 1 ]]; then
            warn "Workspace $WORKSPACE_ARG inexistant — serait créé."
            WORKSPACE_ROOT="$WORKSPACE_ARG"
            return 0
        fi
        mkdir -p "$WORKSPACE_ARG"
    fi
    WORKSPACE_ROOT="$(cd "$WORKSPACE_ARG" && pwd)"
}

workspace_is_separate() { [[ "$WORKSPACE_ROOT" != "$PROJECT_ROOT" ]]; }

# Tous les agents fournis par le moteur.
all_agents() {
    local f
    for f in "$PROJECT_ROOT"/agents/*.md; do
        [[ -e "$f" ]] || continue
        basename "$f" .md
    done
}

# Détermine le staff à installer : --agents / --no-medical, sinon
# [agents].enabled de la configuration, sinon tous.
#
# L'ensemble retenu est réécrit dans workspace.user.toml pour que l'installation
# et l'exécution ne puissent pas diverger : le coach ne délègue qu'aux agents
# listés là, et il n'y a donc qu'une seule vérité.
resolve_agents() {
    local available requested="" excluded="" name keep skip
    available="$(all_agents)"

    if [[ "$AGENTS_ARG" == __all_but__:* ]]; then
        excluded="${AGENTS_ARG#__all_but__:}"
    elif [[ -n "$AGENTS_ARG" ]]; then
        requested="$(printf '%s' "${AGENTS_ARG%%:*}" | tr ',' ' ')"
        if [[ "$AGENTS_ARG" == *:* ]]; then excluded="${AGENTS_ARG#*:}"; fi
    elif have python3; then
        requested="$(python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
            --workspace "$WORKSPACE_ROOT" --section agents --key enabled 2>/dev/null | tr '\n' ' ')" \
            || requested=""
    fi
    [[ -n "$requested" ]] || requested="$available"

    ENABLED_AGENTS=""
    for name in $requested; do
        [[ -n "$name" ]] || continue
        printf '%s\n' "$available" | grep -qx "$name" \
            || die "Agent inconnu : « $name ». Disponibles : $(all_agents | tr '\n' ' ')"
        keep=1
        for skip in $(printf '%s' "$excluded" | tr ',' ' '); do
            [[ "$name" == "$skip" ]] && keep=0
        done
        [[ "$keep" -eq 1 ]] && ENABLED_AGENTS="$ENABLED_AGENTS $name"
    done
    ENABLED_AGENTS="${ENABLED_AGENTS# }"

    [[ -n "$ENABLED_AGENTS" ]] || die "Aucun agent sélectionné — il en faut au moins un."
    printf '%s\n' $ENABLED_AGENTS | grep -qx coach \
        || die "L'agent « coach » est indispensable : c'est lui qui planifie et pousse vers Garmin."
    log "Staff : $ENABLED_AGENTS"
}

# Détermine la source de données : --source (explicite, prioritaire), sinon
# [data].source de la configuration EXISTANTE (workspace.user.toml, sinon
# workspace.toml), sinon "garmin" — même principe que resolve_agents() pour
# [agents].enabled. C'est ce qui évite qu'un simple `./install.sh` (sans
# --source) ne fasse silencieusement revenir à Garmin un athlète qui a choisi
# Intervals.icu, et qui garantit qu'une installation Garmin par défaut, elle,
# ne voit STRICTEMENT rien changer (aucune section [data] écrite tant que
# --source n'a jamais été demandé explicitement — voir persist_source()).
resolve_source() {
    local previous="garmin"
    if have python3; then
        previous="$(python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
            --workspace "$WORKSPACE_ROOT" --section data --key source --default garmin 2>/dev/null)" \
            || previous="garmin"
        [[ -n "$previous" ]] || previous="garmin"
    fi
    if [[ "$EXPLICIT_SOURCE" -eq 0 ]]; then
        SOURCE="$previous"
    fi
    validate_source
    # Un rerun sans --source (EXPLICIT_SOURCE=0) ne « change » jamais rien,
    # même si $SOURCE finit par différer d'un défaut codé en dur : SOURCE_CHANGED
    # ne s'allume QUE quand --source a été demandé ET que la valeur retenue
    # diffère de celle DÉJÀ en config — voir la note près de sa déclaration.
    if [[ "$EXPLICIT_SOURCE" -eq 1 && "$SOURCE" != "$previous" ]]; then
        SOURCE_CHANGED=1
    fi
    log "Source de données : $SOURCE"
}

# Enregistre le staff retenu dans la config personnelle.
persist_agents() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [agents].enabled = $ENABLED_AGENTS"
        return 0
    fi
    have python3 || return 0
    local args=() name
    for name in $ENABLED_AGENTS; do args+=(--list "$name"); done
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section agents --key enabled "${args[@]}" >/dev/null \
        || warn "Impossible d'écrire [agents].enabled — vérifiez config/workspace.user.toml."
}

# Enregistre la source de données retenue (#68) — sans toucher aux autres clés
# de workspace.user.toml (set_toml_key ne remplace que [data].source).
#
# UNIQUEMENT si --source a été passé explicitement : une installation par
# défaut (source résolue à "garmin" par resolve_source(), jamais demandée)
# n'écrit ni ne touche à [data] du tout — c'est ce qui garde une installation
# Garmin par défaut STRICTEMENT identique à avant #68 (aucune section [data]
# ajoutée à workspace.user.toml qui n'existerait pas sans cette story).
persist_source() {
    [[ "$EXPLICIT_SOURCE" -eq 1 ]] || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [data].source = $SOURCE"
        return 0
    fi
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section data --key source --value "$SOURCE" >/dev/null \
        || warn "Impossible d'écrire [data].source — vérifiez config/workspace.user.toml."
}

# Dossier des agents/skills à présenter aux IDE : catalogue du workspace en
# mode séparé, dossiers du moteur sinon.
agents_dir() { if workspace_is_separate; then echo "$WORKSPACE_ROOT/agents"; else echo "$PROJECT_ROOT/agents"; fi; }
skills_dir() { if workspace_is_separate; then echo "$WORKSPACE_ROOT/skills"; else echo "$PROJECT_ROOT/skills"; fi; }

# Remplit $WORKSPACE_ROOT/<catalogue> avec un lien par élément du moteur puis
# par élément de local/<catalogue> (le local prime en cas d'homonyme). Les
# liens morts sont retirés ; un vrai dossier présent dans le catalogue est
# conservé (et signalé : sa place est dans local/).
populate_catalog() {
    local cat="$1" dir="$WORKSPACE_ROOT/$1" src name n=0
    if [[ -L "$dir" ]]; then
        run rm -f "$dir"     # ancien layout : lien direct vers le moteur
    elif [[ -e "$dir" && ! -d "$dir" ]]; then
        warn "$dir existe et n'est pas un dossier — catalogue $cat ignoré."
        return 0
    fi
    run mkdir -p "$dir"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} catalogue $dir ← $PROJECT_ROOT/$cat/* + $WORKSPACE_ROOT/local/$cat/*"
        return 0
    fi
    for src in "$PROJECT_ROOT/$cat"/* "$WORKSPACE_ROOT/local/$cat"/*; do
        [[ -e "$src" ]] || continue
        name="$(basename "$src")"
        if [[ -e "$dir/$name" && ! -L "$dir/$name" ]]; then
            warn "$dir/$name est un vrai dossier — conservé ; déplacez-le dans local/$cat/ pour le versionner proprement."
            continue
        fi
        ln -sfn "$src" "$dir/$name"
        n=$((n + 1))
    done
    # liens morts (skill supprimé du moteur ou de local/)
    for src in "$dir"/*; do
        [[ -L "$src" && ! -e "$src" ]] && rm -f "$src"
    done
    ok "Catalogue $cat : $n élément(s) lié(s) dans $dir"
}

# Bloc .gitignore du workspace : tout ce que install.sh génère.
# Entrées que le bloc généré doit contenir. Une installation plus ancienne a
# déjà un bloc : on n'y ajoute que ce qui manque (sinon une nouvelle entrée,
# comme l'index du tableau de bord, n'atteindrait jamais les workspaces existants).
# /scripts sans « / » final : c'est un lien, et un motif « dossier/ » ne couvre pas
# un lien symbolique — `git add -A` (git_autocommit) l'aurait versionné.
# *.bak : sauvegardes que install.sh et coach_config.py laissent à côté des fichiers.
WORKSPACE_IGNORES=(
    /agents/ /skills/ /scripts /AGENTS.md /config/workspace.toml config/workspace.user.toml
    /.mcp.json /.claude/ /.opencode/ /.gemini/ /.cursor/ /.windsurf/ /.github/agents /.github/skills
    /logs/ /.arc/ .DS_Store __pycache__/ '*.bak'
)

ensure_workspace_gitignore() {
    local gi="$WORKSPACE_ROOT/.gitignore" marker="# ai-running-coach — généré par install.sh (ne pas éditer ce bloc)"
    local end_marker="# fin du bloc ai-running-coach"
    if [[ -f "$gi" ]] && grep -qF "$marker" "$gi"; then
        local missing=() entry
        for entry in "${WORKSPACE_IGNORES[@]}"; do
            grep -qxF -- "$entry" "$gi" || missing+=("$entry")
        done
        if [[ ${#missing[@]} -eq 0 ]]; then
            ok ".gitignore du workspace déjà à jour"
            return 0
        fi
        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} ajout à $gi : ${missing[*]}"
            return 0
        fi
        local tmp
        tmp="$(mktemp "$gi.XXXXXX")"
        if grep -qxF "$end_marker" "$gi"; then
            # Insertion juste avant la fin du bloc, pour qu'il reste d'un seul tenant.
            # Boucle bash plutôt qu'awk -v : l'awk BSD de macOS refuse un saut de ligne
            # dans une variable passée par -v.
            local line
            while IFS= read -r line || [[ -n "$line" ]]; do
                [[ "$line" == "$end_marker" ]] && printf '%s\n' "${missing[@]}"
                printf '%s\n' "$line"
            done < "$gi" > "$tmp"
        else
            { cat "$gi"; printf '%s\n' "${missing[@]}"; } > "$tmp"
        fi
        mv "$tmp" "$gi"
        ok ".gitignore du workspace complété : ${missing[*]}"
        return 0
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} ajout du bloc ai-running-coach à $gi"
        return 0
    fi
    cat >> "$gi" <<GITIGNORE

$marker
# Liens vers le moteur (recréés par ./install.sh --workspace) — ancrés à la
# racine pour ne pas masquer local/agents et local/skills (versionnés)
/agents/
/skills/
/scripts
/AGENTS.md
/config/workspace.toml
# Config personnelle : contient le sujet ntfy, qui fait office de secret
config/workspace.user.toml
# Configs IDE générées
/.mcp.json
/.claude/
/.opencode/
/.gemini/
/.cursor/
/.windsurf/
/.github/agents
/.github/skills
# Journaux, index du tableau de bord (dérivé, jetable) et fichiers temporaires
/logs/
/.arc/
.DS_Store
__pycache__/
# Sauvegardes laissées par l'installation
*.bak
$end_marker
GITIGNORE
    ok "Bloc ai-running-coach ajouté à $gi"
}

prepare_workspace() {
    # Mémorise le workspace pour scripts/ (daily-sync, coach-remote, notify).
    #
    # Uniquement si --workspace a été passé, ou si rien n'est encore mémorisé :
    # ce fichier pilote le cron DÉJÀ installé. Le réécrire à chaque exécution
    # faisait qu'une installation lancée depuis un second clone repointait
    # silencieusement la synchronisation quotidienne vers ce clone.
    if [[ "$DRY_RUN" -eq 0 ]]; then
        if [[ -n "$WORKSPACE_ARG" || ! -f "$WORKSPACE_STATE_FILE" ]]; then
            mkdir -p "$(dirname "$WORKSPACE_STATE_FILE")"
            printf '%s\n' "$WORKSPACE_ROOT" > "$WORKSPACE_STATE_FILE"
        else
            local memorised
            memorised="$(head -n1 "$WORKSPACE_STATE_FILE" 2>/dev/null || true)"
            if [[ -n "$memorised" && "$memorised" != "$WORKSPACE_ROOT" ]]; then
                warn "Workspace mémorisé conservé : $memorised"
                warn "  (relancez avec --workspace \"$WORKSPACE_ROOT\" pour le remplacer)"
            fi
        fi
    fi
    workspace_is_separate || return 0
    log "Préparation du workspace : $WORKSPACE_ROOT (moteur : $PROJECT_ROOT)"
    run mkdir -p "$WORKSPACE_ROOT/config" "$WORKSPACE_ROOT/local/agents" "$WORKSPACE_ROOT/local/skills"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} liens AGENTS.md, config/workspace.toml → moteur"
    else
        link_file "$PROJECT_ROOT/AGENTS.md" "$WORKSPACE_ROOT/AGENTS.md"
        link_file "$PROJECT_ROOT/config/workspace.toml" "$WORKSPACE_ROOT/config/workspace.toml"
        # Les agents appellent `python3 scripts/arc_index.py …` depuis le workspace.
        if [[ -e "$WORKSPACE_ROOT/scripts" && ! -L "$WORKSPACE_ROOT/scripts" ]]; then
            warn "$WORKSPACE_ROOT/scripts existe et n'est pas un lien — conservé ; les agents n'y trouveront pas les scripts du moteur."
        else
            ln -sfn "$PROJECT_ROOT/scripts" "$WORKSPACE_ROOT/scripts"
            ok "Lien créé : $WORKSPACE_ROOT/scripts -> $PROJECT_ROOT/scripts"
        fi
    fi
    populate_catalog agents
    populate_catalog skills
    ensure_workspace_gitignore
}

# ---------------------------------------------------------------------------
# 1. uv
# ---------------------------------------------------------------------------
install_uv() {
    log "Installation de uv (gestionnaire Python)"
    if have uv; then
        ok "uv déjà installé : $(uv --version)"
        return 0
    fi
    # Le pipeline entier doit être confié à « run ». Sous la forme
    # « run curl … | sh », le pipe porte sur « run » lui-même : en dry-run,
    # c'est le message « [dry-run] curl … » qui alimente sh, d'où un échec 127
    # propagé par pipefail.
    run sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
    # recharge le PATH pour la session courante
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! have uv; then
        [[ "$DRY_RUN" -eq 1 ]] && { warn "uv absent (dry-run) — serait installé."; return 0; }
        die "uv installé mais introuvable dans le PATH. Rechargez votre shell puis relancez."
    fi
    ok "uv installé : $(uv --version)"
}

# ---------------------------------------------------------------------------
# 2. garmin-mcp + auth
# ---------------------------------------------------------------------------
install_garmin_mcp() {
    log "Installation de garmin-mcp (accès Garmin Connect)"
    if have garmin-mcp; then
        # NB : pas de « garmin-mcp --version » — cela démarre le serveur stdio et bloque.
        ok "garmin-mcp déjà installé : $(command -v garmin-mcp)"
    else
        run uv tool install --python 3.12 "$GARMIN_MCP_REF"
        export PATH="$HOME/.local/bin:$PATH"
        if ! have garmin-mcp; then
            [[ "$DRY_RUN" -eq 1 ]] && warn "garmin-mcp absent (dry-run) — serait installé." || die "garmin-mcp introuvable après installation."
        else
            ok "garmin-mcp installé"
        fi
    fi

    if [[ "$DO_AUTH" -eq 1 ]]; then
        log "Authentification Garmin Connect (une seule fois, tokens valides ~6 mois)"
        if [[ -f "$GARMIN_TOKENS_DIR/garmin_tokens.json" ]]; then
            if [[ "$DRY_RUN" -eq 1 ]]; then
                warn "Tokens présents — validité non vérifiée (dry-run)."
            elif uv run garmin-mcp-auth --verify; then
                ok "Tokens Garmin valides (vérifiés)"
            else
                warn "Tokens présents mais invalides/expirés — relance de l'authentification"
                run uv run garmin-mcp-auth
            fi
        else
            warn "Aucun token trouvé dans $GARMIN_TOKENS_DIR"
            warn "L'authentification interactive va démarrer (email + mot de passe + éventuel MFA)."
            run uv run garmin-mcp-auth
        fi
    else
        warn "Authentification Garmin sautée (--no-auth). Lancez 'uv run garmin-mcp-auth' plus tard."
    fi
}

# ---------------------------------------------------------------------------
# 2bis. intervals-icu-mcp + auth (--source intervals, #68)
# ---------------------------------------------------------------------------
# Installée À LA PLACE de garmin-mcp (jamais en plus) : la story ouvre le
# projet aux athlètes SANS compte Garmin (COROS, Suunto, Polar, Apple, tout ce
# qu'intervals.icu synchronise) — leur imposer garmin-mcp + une authentification
# Garmin qui échouerait par construction n'aurait aucun sens. Les fonctionnalités
# Garmin-only (upload de parcours, téléchargement FIT) restent simplement
# indisponibles avec cette source — voir AGENTS.md.
# Commande d'authentification, telle qu'affichée/exécutée partout dans ce
# script — un seul endroit à corriger. Appel DIRECT du binaire (pas
# `uv run intervals-icu-mcp-auth`) : le binaire est déjà sur le PATH une fois
# `uv tool install` fait (comme garmin-mcp-auth), et `uv run` chercherait un
# projet uv (pyproject.toml) dans le cwd — qui n'en est pas un ici.
intervals_auth_cmd() { printf '(cd "%s" && intervals-icu-mcp-auth)' "$INTERVALS_ENV_DIR"; }

# Écrit le wrapper que CHAQUE config MCP (toutes les IDE, voir mcp_server_value_intervals*)
# référence comme `command` — jamais `intervals-icu-mcp` directement.
#
# Pourquoi : intervals-icu-mcp charge ses identifiants depuis un `.env` relatif
# à SON répertoire de travail (pydantic-settings, `env_file=".env"`), pas depuis
# une variable d'environnement passée par l'IDE — et l'IDE démarre le serveur
# MCP avec pour cwd le dossier du PROJET, pas $INTERVALS_ENV_DIR. Un bloc
# `"env": {"INTERVALS_ICU_API_KEY": "${VAR}"}` dans la config JSON ne marche
# donc NULLE PART : rien n'exporte cette variable dans le processus de l'IDE,
# certains IDE (OpenCode) n'interpolent même pas `${VAR}`, et de toute façon une
# variable d'environnement écraserait le `.env` sans jamais l'atteindre. Le
# wrapper force le bon cwd avant d'exec le serveur, quel que soit l'IDE.
write_intervals_wrapper() {
    local wrapper="$INTERVALS_ENV_DIR/run.sh"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} écriture de $wrapper"
        return 0
    fi
    mkdir -p "$INTERVALS_ENV_DIR"
    cat > "$wrapper" <<'EOF'
#!/usr/bin/env bash
# Généré par install.sh (--source intervals, #68) — NE JAMAIS committer ce
# fichier ni le .env à côté de lui : intervals-icu-mcp charge ses identifiants
# depuis un .env relatif à SON répertoire de travail (pydantic-settings), pas
# depuis une variable d'environnement passée par l'IDE. Ce wrapper garantit ce
# répertoire de travail quel que soit le dossier depuis lequel l'IDE lance
# la commande MCP.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec intervals-icu-mcp "$@"
EOF
    chmod +x "$wrapper"
    ok "Wrapper écrit : $wrapper"
}

install_intervals_mcp() {
    log "Installation de intervals-icu-mcp (accès Intervals.icu, --source intervals)"
    # `--with fitparse` : `skills/fit-download/scripts/download_fit.py --source
    # intervals` se relance dans CET environnement pour lire les FIT téléchargés
    # (même mécanique que garmin-mcp, qui embarque déjà fitparse). Une installation
    # antérieure sans fitparse est complétée par `uv pip install` DANS son
    # environnement — jamais `uv tool install --reinstall`, qui écraserait les
    # fichiers du serveur (et tout correctif local que l'athlète y aurait appliqué).
    if have intervals-icu-mcp; then
        ok "intervals-icu-mcp déjà installé : $(command -v intervals-icu-mcp)"
        local tool_py
        # realpath via python3 : `readlink -f` n'existe pas sur les macOS anciens.
        tool_py="$(dirname "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' \
            "$(command -v intervals-icu-mcp)")")/python3"
        if [[ -x "$tool_py" ]] && ! "$tool_py" -c 'import fitparse' 2>/dev/null; then
            log "Ajout de fitparse à l'environnement intervals-icu-mcp (lecture des FIT)"
            # Facultatif (seul `--json` lit les FIT) : un échec (réseau, environnement en
            # lecture seule) n'interrompt jamais l'installation — `coach_doctor` (`fit_reader`)
            # le signale ensuite.
            run uv pip install --python "$tool_py" fitparse \
                || warn "fitparse non installé dans l'environnement intervals-icu-mcp — download_fit.py --json indisponible (voir /coach-doctor)"
        fi
    else
        run uv tool install --python 3.12 --with fitparse "$INTERVALS_MCP_REF"
        export PATH="$HOME/.local/bin:$PATH"
        if ! have intervals-icu-mcp; then
            [[ "$DRY_RUN" -eq 1 ]] && warn "intervals-icu-mcp absent (dry-run) — serait installé." || die "intervals-icu-mcp introuvable après installation."
        else
            ok "intervals-icu-mcp installé"
        fi
    fi

    write_intervals_wrapper

    if [[ "$DO_AUTH" -eq 1 ]]; then
        log "Authentification Intervals.icu (clé API + identifiant athlète, une seule fois)"
        if [[ -f "$INTERVALS_ENV_DIR/.env" ]]; then
            ok "Identifiants Intervals.icu présents ($INTERVALS_ENV_DIR/.env)"
        elif [[ "$DRY_RUN" -eq 1 ]]; then
            warn "Authentification Intervals.icu sautée (dry-run) — serait lancée dans $INTERVALS_ENV_DIR."
        else
            warn "Aucun identifiant trouvé dans $INTERVALS_ENV_DIR"
            warn "L'authentification interactive va démarrer : clé API (https://intervals.icu/settings,"
            warn "section « Developer ») + identifiant athlète (ex. i123456)."
            mkdir -p "$INTERVALS_ENV_DIR"
            (cd "$INTERVALS_ENV_DIR" && intervals-icu-mcp-auth) \
                || die "Échec de l'authentification Intervals.icu (voir le message ci-dessus)."
        fi
    else
        warn "Authentification Intervals.icu sautée (--no-auth)."
        warn "Lancez plus tard : $(intervals_auth_cmd)"
    fi
}

# ---------------------------------------------------------------------------
# 2ter. serveur MCP Strava (--source strava, #164)
# ---------------------------------------------------------------------------
# Installé À LA PLACE de garmin-mcp. Pas de binaire à installer : le serveur est un
# paquet npm lancé par `npx` (épinglé, voir STRAVA_MCP_PKG) — Node.js >= 18 est le seul
# prérequis. L'authentification OAuth n'est PAS faite ici : elle passe par l'outil
# `connect-strava` du serveur (navigateur, http://localhost:8111), à lancer une fois depuis
# l'agent, après avoir créé l'application API Strava de l'athlète (docs/strava-setup.md).
write_strava_wrapper() {
    local wrapper="$STRAVA_MCP_DIR/run.sh"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} écriture de $wrapper"
        return 0
    fi
    mkdir -p "$STRAVA_MCP_DIR"
    cat > "$wrapper" <<WRAPPER
#!/usr/bin/env bash
# Généré par install.sh (--source strava, #164). Les jetons Strava ne sont JAMAIS ici :
# le serveur les lit/écrit dans ~/.config/strava-mcp/config.json.
set -euo pipefail
exec npx -y $STRAVA_MCP_PKG "\$@"
WRAPPER
    chmod +x "$wrapper"
    ok "Wrapper écrit : $wrapper"
}

install_strava_mcp() {
    log "Installation du serveur MCP Strava ($STRAVA_MCP_PKG, --source strava)"
    if ! have node || ! have npx; then
        if [[ "$DRY_RUN" -eq 1 ]]; then
            warn "node/npx absents (dry-run) — requis pour --source strava (Node.js >= 18)."
        else
            die "Node.js (node + npx, version 18 ou plus) est requis pour --source strava — voir docs/strava-setup.md."
        fi
    else
        local major
        major="$(node --version 2>/dev/null | sed -e 's/^v//' -e 's/\..*$//')"
        if [[ "$major" =~ ^[0-9]+$ ]] && (( major < 18 )); then
            warn "Node.js $(node --version) détecté — ce serveur exige la version 18 ou plus."
        else
            ok "node : $(node --version 2>/dev/null)"
        fi
    fi
    write_strava_wrapper
    if [[ -f "$STRAVA_TOKEN_FILE" ]]; then
        ok "Compte Strava déjà connecté ($STRAVA_TOKEN_FILE)"
    else
        warn "Compte Strava non connecté — après l'installation : créez votre application API sur"
        warn "https://www.strava.com/settings/api (« Authorization Callback Domain » = localhost),"
        warn "puis demandez à l'agent d'exécuter l'outil connect-strava (voir docs/strava-setup.md)."
    fi
}

# ---------------------------------------------------------------------------
# 3. leanproxy-mcp (optionnel — mode power user)
# ---------------------------------------------------------------------------
install_leanproxy() {
    if [[ "$USE_LEANPROXY" -eq 0 ]]; then
        # La passerelle leanproxy ne route que le serveur garmin (voir la
        # validation de --source plus haut) : rien à dire côté intervals.
        [[ "$SOURCE" == "garmin" ]] && warn "leanproxy-mcp non installé (mode direct). Utilisez --use-leanproxy pour la passerelle."
        return 0
    fi
    log "Installation de leanproxy-mcp (passerelle MCP — power user)"
    if have leanproxy-mcp; then
        ok "leanproxy-mcp déjà installé : $(leanproxy-mcp --version 2>/dev/null || echo 'version inconnue')"
    elif have brew; then
        run brew tap "$LEANPROXY_BREW_TAP"
        run brew install "$LEANPROXY_FORMULA"
    else
        warn "Homebrew absent — installation manuelle requise :"
        warn "  https://github.com/mmornati/leanproxy-mcp#installation"
        warn "Puis relancez ce script."
        return 0
    fi
}

# ---------------------------------------------------------------------------
# 4. Configuration leanproxy (serveur garmin) — mode power user
# ---------------------------------------------------------------------------
configure_leanproxy() {
    if [[ "$USE_LEANPROXY" -eq 0 ]]; then
        return 0
    fi
    log "Configuration de leanproxy (serveur garmin)"

    [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$LEANPROXY_CONFIG_DIR"

    # config.yaml — ne pas écraser une config existante
    if [[ -f "$LEANPROXY_CONFIG_DIR/config.yaml" ]]; then
        ok "config.yaml existant — conservé"
    else
        write_file "$LEANPROXY_CONFIG_DIR/config.yaml" <<'EOF'
server:
  host: "127.0.0.1"
  port: 8080
  timeout: 300s
  max_batch_size: 100
optimization:
  lazy_loading:
    enabled: true
    stub_tokens: 54
    cache_ttl: 24h
namespaces:
  sport:
    description: "Sport tools"
    servers:
      - garmin
    allowed_clients:
      - "*"
logging:
  level: "info"
  file: ""
EOF
        ok "config.yaml écrit dans $LEANPROXY_CONFIG_DIR/config.yaml"
    fi

    # leanproxy_servers.yaml — ajoute le serveur garmin s'il manque
    if [[ -f "$LEANPROXY_SERVERS" ]] && grep -q 'name: garmin' "$LEANPROXY_SERVERS"; then
        ok "Serveur garmin déjà présent dans $LEANPROXY_SERVERS"
    else
        # Délimiteur NON quoté (contrairement au heredoc config.yaml juste
        # au-dessus) : c'est ce qui permet d'interpoler $GARMIN_TOOL_WHITELIST
        # au lieu de dupliquer la liste blanche en dur (revue de code #112 —
        # la copie figée ici avait fini par diverger de la variable).
        write_file "$LEANPROXY_SERVERS" <<EOF
version: "1.0"
servers:
    - name: garmin
      enabled: true
      transport: stdio
      stdio:
        command: garmin-mcp
        args:
            - stdio
        env:
            - GARMIN_ENABLED_TOOLS: "$GARMIN_TOOL_WHITELIST"
        cwd: .
      timeout: 300s
      connect_timeout: 10s
      idle_timeout: ""
EOF
        ok "Serveur garmin ajouté dans $LEANPROXY_SERVERS"
    fi
}

# ---------------------------------------------------------------------------
# 5. Configuration IDE
# ---------------------------------------------------------------------------
# Mode direct (défaut) : le serveur MCP "garmin" pointe vers garmin-mcp avec
# la liste blanche d'outils. Mode leanproxy : le serveur "leanproxy" est utilisé.

# Bloc MCP pour le mode leanproxy
mcp_leanproxy_block() {
    cat <<'EOF'
    "leanproxy": {
      "command": "leanproxy-mcp",
      "args": []
    }
EOF
}

# Bloc MCP pour la source intervals.icu (--source intervals, #68). Pointe sur
# le WRAPPER écrit par write_intervals_wrapper() ($INTERVALS_ENV_DIR/run.sh),
# jamais sur le binaire `intervals-icu-mcp` directement, et SANS bloc `env` :
# un `"env": {"INTERVALS_ICU_API_KEY": "${VAR}"}` ne marche nulle part (rien
# n'exporte cette variable dans le processus de l'IDE, OpenCode n'interpole
# même pas `${VAR}`, et un `env` écraserait de toute façon le `.env` lu par le
# serveur sans jamais l'atteindre) — voir write_intervals_wrapper() pour le
# détail. Les identifiants vivent uniquement dans le `.env` du wrapper, écrit
# par `intervals-icu-mcp-auth`, jamais dans cette config.
mcp_server_value_intervals() {
    printf '{"command": "%s", "args": []}' "$(json_escape "$INTERVALS_ENV_DIR/run.sh")"
}

mcp_server_value_intervals_opencode() {
    printf '{"type": "local", "command": ["%s"], "enabled": true}' "$(json_escape "$INTERVALS_ENV_DIR/run.sh")"
}

# Source Strava (#164) : même principe — le wrapper, jamais de secret dans la config.
mcp_server_value_strava() {
    printf '{"command": "%s", "args": []}' "$(json_escape "$STRAVA_MCP_DIR/run.sh")"
}

mcp_server_value_strava_opencode() {
    printf '{"type": "local", "command": ["%s"], "enabled": true}' "$(json_escape "$STRAVA_MCP_DIR/run.sh")"
}

# Valeur JSON du serveur, au format « mcpServers » (Claude, Copilot, Cursor,
# Windsurf) puis au format OpenCode. Produites ici pour qu'il n'y ait qu'un
# endroit à corriger quand la liste blanche (ou la source) change.
mcp_server_value() {
    if [[ "$SOURCE" == "intervals" ]]; then
        mcp_server_value_intervals
    elif [[ "$SOURCE" == "strava" ]]; then
        mcp_server_value_strava
    elif [[ "$USE_LEANPROXY" -eq 1 ]]; then
        printf '{"command": "leanproxy-mcp", "args": []}'
    else
        printf '{"command": "garmin-mcp", "args": ["stdio"], "env": {"GARMIN_ENABLED_TOOLS": "%s"}}' \
            "$GARMIN_TOOL_WHITELIST"
    fi
}

mcp_server_value_opencode() {
    if [[ "$SOURCE" == "intervals" ]]; then
        mcp_server_value_intervals_opencode
    elif [[ "$SOURCE" == "strava" ]]; then
        mcp_server_value_strava_opencode
    elif [[ "$USE_LEANPROXY" -eq 1 ]]; then
        printf '{"type": "local", "command": ["leanproxy-mcp"], "enabled": true}'
    else
        printf '{"type": "local", "command": ["garmin-mcp", "stdio"], "environment": {"GARMIN_ENABLED_TOOLS": "%s"}, "enabled": true}' \
            "$GARMIN_TOOL_WHITELIST"
    fi
}

# Nom du serveur MCP à utiliser selon la source/le mode
mcp_server_name() {
    if [[ "$SOURCE" == "intervals" ]]; then
        echo "intervals"
    elif [[ "$SOURCE" == "strava" ]]; then
        echo "strava"
    elif [[ "$USE_LEANPROXY" -eq 1 ]]; then
        echo "leanproxy"
    else
        echo "garmin"
    fi
}

write_opencode_config() {
    log "Configuration OpenCode"
    # ~/.config/opencode/opencode.json est GLOBAL : d'autres projets y déclarent
    # leurs propres serveurs MCP. On insère la clé, on ne réécrit pas le fichier.
    local cfg="$HOME/.config/opencode/opencode.json"
    cleanup_stale_mcp_server "$cfg" mcp
    merge_json_key "$cfg" mcp "$(mcp_server_name)" "$(mcp_server_value_opencode)" \
        '{"$schema": "https://opencode.ai/config.json"}'
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
    # Agents/skills : OpenCode lit .opencode/ à la racine du projet.
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$WORKSPACE_ROOT/.opencode"
        link_agents "$(agents_dir)" "$WORKSPACE_ROOT/.opencode/agents"
        link_catalog "$(skills_dir)" "$WORKSPACE_ROOT/.opencode/skills"
    fi
}

# .mcp.json à la racine du projet — format partagé, lu par Claude Code ET
# GitHub Copilot CLI.
write_project_mcp_json() {
    local cfg="$WORKSPACE_ROOT/.mcp.json"
    cleanup_stale_mcp_server "$cfg" mcpServers
    merge_json_key "$cfg" mcpServers "$(mcp_server_name)" "$(mcp_server_value)"
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
}

write_claude_config() {
    log "Configuration Claude Code"
    write_project_mcp_json
    # Claude Code utilise .claude/agents/*.md + .claude/skills/*/SKILL.md
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$WORKSPACE_ROOT/.claude"
        link_agents "$(agents_dir)" "$WORKSPACE_ROOT/.claude/agents"
        link_catalog "$(skills_dir)" "$WORKSPACE_ROOT/.claude/skills"
    fi
    # Pré-approuve le serveur MCP du projet (.mcp.json) dans ~/.claude.json :
    # sinon Claude Code le laisse « Pending approval » jusqu'à une session
    # interactive — bloquant sur une machine coach sans écran (Remote Control, cron).
    approve_claude_project_mcp "$(mcp_server_name)"
    # Désapprouve l'ancienne source (#68) — sinon ~/.claude.json continue de
    # lister un serveur qui n'est plus dans .mcp.json comme "approuvé". Même
    # garde-fou que cleanup_stale_mcp_server() (--source a réellement basculé),
    # PLUS un second garde-fou (revue PR #116) : ne désapprouver que l'entrée
    # RÉELLEMENT retirée de .mcp.json ci-dessus (write_project_mcp_json a déjà
    # tourné) — jamais une entrée ajoutée à la main qui a survécu au
    # garde-fou --expect-command et reste présente/fonctionnelle.
    if [[ "$SOURCE_CHANGED" -eq 1 ]]; then
        local stale cfg="$WORKSPACE_ROOT/.mcp.json"
        for stale in $(stale_mcp_server_names); do
            mcp_server_key_exists "$cfg" mcpServers "$stale" || unapprove_claude_project_mcp "$stale"
        done
    fi
}

write_copilot_config() {
    log "Configuration GitHub Copilot"
    # Copilot CLI lit le même .mcp.json projet que Claude Code.
    write_project_mcp_json
    # Copilot découvre les agents dans .github/agents/*.md et les skills dans
    # .github/skills/*/SKILL.md — liens symboliques pour que agents/ et skills/
    # restent la source de vérité (les liens sont gitignorés).
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$WORKSPACE_ROOT/.github"
        link_agents "$(agents_dir)" "$WORKSPACE_ROOT/.github/agents"
        link_catalog "$(skills_dir)" "$WORKSPACE_ROOT/.github/skills"
    fi
    if workspace_is_separate && [[ -f "$PROJECT_ROOT/.github/copilot-instructions.md" && ! -e "$WORKSPACE_ROOT/.github/copilot-instructions.md" && "$DRY_RUN" -eq 0 ]]; then
        cp "$PROJECT_ROOT/.github/copilot-instructions.md" "$WORKSPACE_ROOT/.github/copilot-instructions.md"
    fi
    if [[ -f "$WORKSPACE_ROOT/.github/copilot-instructions.md" ]]; then
        ok "Instructions Copilot présentes (.github/copilot-instructions.md)"
    else
        warn "Aucun .github/copilot-instructions.md — Copilot lira AGENTS.md"
    fi
}

approve_claude_project_mcp() {
    local server="$1" store="$HOME/.claude.json"
    if ! have python3; then
        warn "python3 absent : approuvez le serveur MCP $server en lançant 'claude' une fois dans $WORKSPACE_ROOT"
        return 0
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} approbation du serveur MCP $server pour $WORKSPACE_ROOT dans $store"
        return 0
    fi
    # ~/.claude.json contient TOUT l'état global de Claude Code. Le helper
    # sauvegarde en .bak, refuse d'écrire si le fichier est illisible, et
    # signale explicitement l'acceptation du dialogue de confiance.
    python3 "$PROJECT_ROOT/scripts/coach_config.py" approve-claude-mcp \
        --store "$store" --project "$WORKSPACE_ROOT" --server "$server" --trust \
        || die "Échec de la mise à jour de $store — rien n'a été modifié."
    ok "Serveur MCP $server approuvé pour ce projet ($store)"
}

# Retire un serveur de la liste des serveurs MCP approuvés pour ce projet
# (#68) — utilisé pour nettoyer l'ancienne source après un changement de
# --source. Sans effet si le fichier, le projet ou le serveur sont absents.
unapprove_claude_project_mcp() {
    local server="$1" store="$HOME/.claude.json"
    have python3 || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} désapprobation du serveur MCP $server pour $WORKSPACE_ROOT dans $store (si présent)"
        return 0
    fi
    [[ -f "$store" ]] || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" unapprove-claude-mcp \
        --store "$store" --project "$WORKSPACE_ROOT" --server "$server" >/dev/null \
        || warn "Impossible de désapprouver « $server » dans $store."
}

write_gemini_config() {
    log "Configuration Gemini CLI"
    local dir="$WORKSPACE_ROOT/.gemini/commands"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$dir"
    fi
    # Les commandes Gemini sont des .toml ; on copie les templates fournis.
    if [[ -d "$PROJECT_ROOT/config/gemini/commands" ]]; then
        run cp -n "$PROJECT_ROOT"/config/gemini/commands/*.toml "$dir"/ 2>/dev/null || true
        ok "Commandes Gemini copiées dans $dir"
    else
        warn "Aucun template Gemini trouvé dans config/gemini/commands"
    fi
}

write_cursor_config() {
    log "Configuration Cursor"
    local cfg="$WORKSPACE_ROOT/.cursor/mcp.json"
    cleanup_stale_mcp_server "$cfg" mcpServers
    merge_json_key "$cfg" mcpServers "$(mcp_server_name)" "$(mcp_server_value)"
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
}

write_windsurf_config() {
    log "Configuration Windsurf"
    local cfg="$WORKSPACE_ROOT/.windsurf/mcp_config.json"
    cleanup_stale_mcp_server "$cfg" mcpServers
    merge_json_key "$cfg" mcpServers "$(mcp_server_name)" "$(mcp_server_value)"
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
}

configure_ide() {
    case "$IDE" in
        all)      write_opencode_config; write_claude_config; write_copilot_config; write_gemini_config; write_cursor_config; write_windsurf_config ;;
        opencode) write_opencode_config ;;
        claude)   write_claude_config ;;
        copilot)  write_copilot_config ;;
        gemini)   write_gemini_config ;;
        cursor)   write_cursor_config ;;
        windsurf) write_windsurf_config ;;
        *) die "IDE inconnu : $IDE (all|claude|copilot|opencode|gemini|cursor|windsurf)" ;;
    esac
}

# ---------------------------------------------------------------------------
# 6. Dossiers de travail
# ---------------------------------------------------------------------------
create_workspace_dirs() {
    log "Création des dossiers de travail (exclus du dépôt)"
    for d in activities medical nutrition planning rapports resources gear; do
        if [[ "$DRY_RUN" -eq 0 ]]; then
            mkdir -p "$WORKSPACE_ROOT/$d"
        fi
    done
    ok "Dossiers activities/ medical/ nutrition/ planning/ rapports/ resources/ gear/ prêts"
}

# ---------------------------------------------------------------------------
# 6b. Configuration de l'espace de travail
# ---------------------------------------------------------------------------
create_workspace_config() {
    local cfg="$WORKSPACE_ROOT/config/workspace.user.toml"
    if [[ -f "$cfg" ]]; then
        ok "Config personnelle présente : $cfg"
        return 0
    fi
    log "Création de la config personnelle (overrides, gitignorée)"
    write_file "$cfg" <<'EOF'
# Overrides personnels — ce fichier est GITIGNORÉ.
# Les valeurs ci-dessous priment sur config/workspace.toml (versionné).

[language]
# Langue des fichiers Markdown persistés par les agents/skills.
# Valeurs : code ISO 639-1 (ex. "fr", "en", "nl").
documents = "fr"

# Langue des réponses à l'utilisateur ("auto" = même langue que la requête).
responses = "auto"
EOF
    ok "Config personnelle créée : $cfg"
}

# ---------------------------------------------------------------------------
# 6c. Exécuteurs headless (Claude Code / Codex CLI) — machine « coach »
# ---------------------------------------------------------------------------
# Les fonctionnalités mobiles reposent sur les CLI officiels (abonnement, pas de
# clé API). On ne les installe pas à la place de l'utilisateur : on vérifie et
# on affiche la commande officielle.
check_runners() {
    if have claude; then
        ok "claude : présent ($(claude --version 2>/dev/null | head -1))"
    else
        warn "claude absent — requis pour --remote-control et [sync].runner = \"claude\" :"
        warn "  curl -fsSL https://claude.ai/install.sh | bash   (puis 'claude' → /login, compte claude.ai)"
    fi
    if have codex; then
        ok "codex : présent ($(codex --version 2>/dev/null | head -1))"
    else
        warn "codex absent — optionnel ([sync].runner = \"codex\") : npm i -g @openai/codex  (puis 'codex login --device-auth')"
    fi
}

# ---------------------------------------------------------------------------
# 6d. Synchronisation Garmin automatique (cron / launchd)
# ---------------------------------------------------------------------------
# Heures lues dans config/workspace.toml → [sync].times (override user.toml).
sync_times() {
    ARC_WORKSPACE="$WORKSPACE_ROOT" bash -c 'source "$0/scripts/lib/config.sh"; toml_get_list sync times "07:15 14:15"' "$PROJECT_ROOT"
}

# Clé scalaire de [sync] (mode, watch_interval_min), même précédence que sync_times.
sync_setting() {
    ARC_WORKSPACE="$WORKSPACE_ROOT" bash -c 'source "$0/scripts/lib/config.sh"; toml_get sync "$1" "$2"' "$PROJECT_ROOT" "$1" "$2"
}

# Source de données ([data].source) : la surveillance n'existe que pour Garmin.
data_source() {
    ARC_WORKSPACE="$WORKSPACE_ROOT" bash -c 'source "$0/scripts/lib/config.sh"; toml_get data source garmin' "$PROJECT_ROOT"
}

# Lit la crontab existante. Distingue « pas de crontab » (cas normal) d'une
# vraie erreur (droits, cron.deny) : dans le second cas on doit renoncer, sinon
# « crontab - » remplace la table complète de l'utilisateur par nos deux lignes.
read_crontab() {
    local out status
    out="$(crontab -l 2>&1)" && { printf '%s\n' "$out"; return 0; }
    status=$?
    if printf '%s' "$out" | grep -qi 'no crontab'; then
        return 0            # table vide
    fi
    err "Lecture de la crontab impossible : $out"
    return "$status"
}

install_daily_sync() {
    if [[ "$DAILY_SYNC" -eq 0 ]]; then
        return 0
    fi
    log "Synchronisation Garmin automatique (scripts/daily-sync.sh)"
    local sync="$PROJECT_ROOT/scripts/daily-sync.sh" times t hour minute mode interval
    local watch="$PROJECT_ROOT/scripts/garmin_watch.py"
    mode="$(sync_setting mode schedule)"
    interval="$(sync_setting watch_interval_min 15)"
    case "$mode" in
        schedule) ;;
        watch)
            # intervals.icu et Strava ne sont pas surveillés (pas de sonde équivalente) : heures fixes.
            if [[ "$(data_source)" != "garmin" ]]; then
                warn "[sync].mode = \"watch\" n'existe que pour [data].source = \"garmin\" — heures fixes ([sync].times)."
                mode="schedule"
            elif [[ ! "$interval" =~ ^[0-9]+$ ]] || (( 10#$interval < 1 || 10#$interval > 59 )); then
                die "[sync].watch_interval_min invalide : « $interval » (entier de 1 à 59 minutes)."
            fi ;;
        *) die "[sync].mode invalide : « $mode » (schedule | watch)." ;;
    esac
    times="$(sync_times | tr '\n' ' ')"
    if [[ "$mode" == "watch" ]]; then
        interval="$((10#$interval))"
        log "Mode surveillance : scripts/garmin_watch.py toutes les $interval min, LLM seulement s'il y a du neuf ([sync].mode)"
        times=""
    else
        log "Heures : $times (config [sync].times)"
    fi

    for t in $times; do
        if [[ ! "$t" =~ ^[0-9]{1,2}:[0-9]{2}$ ]]; then
            die "Heure invalide dans [sync].times : « $t » (format attendu HH:MM)."
        fi
    done

    if [[ "$(uname -s)" == "Darwin" ]]; then
        local plist="$HOME/Library/LaunchAgents/com.ai-running-coach.daily-sync.plist" entries=""
        for t in $times; do
            hour="$((10#${t%%:*}))"; minute="$((10#${t##*:}))"
            entries+="    <dict><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>$minute</integer></dict>
"
        done
        # Un « & » dans un chemin suffit à produire un plist que launchctl refuse.
        local x_sync x_ws program schedule
        x_sync="$(xml_escape "$sync")"; x_ws="$(xml_escape "$WORKSPACE_ROOT")"
        if [[ "$mode" == "watch" ]]; then
            program="  <key>ProgramArguments</key><array><string>/usr/bin/env</string><string>python3</string><string>$(xml_escape "$watch")</string></array>"
            schedule="  <key>StartInterval</key><integer>$((interval * 60))</integer>"
        else
            program="  <key>ProgramArguments</key><array><string>$x_sync</string></array>"
            schedule="  <key>StartCalendarInterval</key>
  <array>
$entries  </array>"
        fi
        write_file "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ai-running-coach.daily-sync</string>
$program
  <key>WorkingDirectory</key><string>$x_ws</string>
  <key>EnvironmentVariables</key><dict><key>ARC_WORKSPACE</key><string>$x_ws</string></dict>
$schedule
  <key>StandardOutPath</key><string>$x_ws/logs/launchd-sync.log</string>
  <key>StandardErrorPath</key><string>$x_ws/logs/launchd-sync.log</string>
</dict>
</plist>
EOF
        [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$WORKSPACE_ROOT/logs"
        run launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
        # launchctl bootstrap exige une session graphique : sur un Mac « coach »
        # accessible seulement en SSH il échoue, sans que ce soit fatal.
        if run launchctl bootstrap "gui/$(id -u)" "$plist"; then
            ok "LaunchAgent com.ai-running-coach.daily-sync installé ($plist)"
        else
            warn "launchctl bootstrap a échoué (session graphique absente ?)."
            warn "Le plist est écrit ($plist) : il sera chargé à la prochaine ouverture de session,"
            warn "ou chargez-le depuis une session graphique avec :"
            warn "  launchctl bootstrap gui/$(id -u) \"$plist\""
        fi
    else
        # crontab : on remplace les lignes marquées, on conserve le reste.
        local marker="# ai-running-coach daily-sync" lines="" current backup
        for t in $times; do
            hour="$((10#${t%%:*}))"; minute="$((10#${t##*:}))"
            # Le chemin du workspace peut contenir des espaces : il doit être cité.
            lines+="$minute $hour * * * ARC_WORKSPACE=\"$WORKSPACE_ROOT\" \"$sync\" >/dev/null 2>&1 $marker
"
        done
        if [[ "$mode" == "watch" ]]; then
            lines="*/$interval * * * * ARC_WORKSPACE=\"$WORKSPACE_ROOT\" python3 \"$watch\" >/dev/null 2>&1 $marker
"
        fi
        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} crontab :"
            printf '%s' "$lines"
        else
            current="$(read_crontab)" \
                || die "Crontab non modifiée. Corrigez l'accès à cron puis relancez."
            # Sauvegarde avant toute écriture : la crontab n'est pas versionnée.
            if [[ -n "$current" ]]; then
                backup="$(dirname "$WORKSPACE_STATE_FILE")/crontab-$(date +%Y%m%d-%H%M%S).bak"
                mkdir -p "$(dirname "$backup")"
                printf '%s\n' "$current" > "$backup"
                ok "Crontab sauvegardée : $backup"
            fi
            printf '%s\n%s' "$(printf '%s\n' "$current" | grep -vF "$marker" || true)" "$lines" \
                | grep -v '^[[:space:]]*$' | crontab -
            ok "crontab mise à jour :"
            printf '%s' "$lines"
        fi
    fi
    warn "Pensez à configurer la notification push : scripts/setup-ntfy.sh"
}

# ---------------------------------------------------------------------------
# 6e. Remote Control — le coach dans la poche
# ---------------------------------------------------------------------------
install_remote_control() {
    if [[ "$REMOTE_CONTROL" -eq 0 ]]; then
        return 0
    fi
    log "Service Claude Code Remote Control (scripts/coach-remote.sh install)"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        ARC_WORKSPACE="$WORKSPACE_ROOT" ARC_DRY_RUN=1 "$PROJECT_ROOT/scripts/coach-remote.sh" install --dry-run
    else
        ARC_WORKSPACE="$WORKSPACE_ROOT" "$PROJECT_ROOT/scripts/coach-remote.sh" install
    fi
}

# ---------------------------------------------------------------------------
# 6f. Chat avec le coach et sync sur une API (--llm, --chat, budgets)
# ---------------------------------------------------------------------------
# Valeur d'une clé dans workspace.user.toml UNIQUEMENT (rien si absente), pour
# distinguer « déjà posée par l'utilisateur » d'un défaut de config/workspace.toml.
user_toml_value() {
    have python3 || return 1
    python3 - "$WORKSPACE_ROOT/config/workspace.user.toml" "$1" "$2" "$PROJECT_ROOT/scripts" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[4])
from pathlib import Path
from coach_config import read_toml
path = Path(sys.argv[1])
section = read_toml(path).get(sys.argv[2], {}) if path.exists() else {}
if sys.argv[3] not in section:
    sys.exit(1)
print(section[sys.argv[3]])
PYEOF
}

# Valeur effective (user > défaut versionné) d'une clé, vide si absente.
effective_value() {
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
        --workspace "$WORKSPACE_ROOT" --section "$1" --key "$2" --default "" 2>/dev/null || true
}

# Pose [section].key dans workspace.user.toml. Remplace sans demander, mais jamais
# en silence : une valeur posée par l'utilisateur qui diffère, ou un changement de
# runner/backend (bascule abonnement → API, facturation différente), est signalé
# « ancien → nouveau » avec la façon de revenir. Sans effet si la valeur est déjà celle-là.
# Usage : llm_set <section> <clé> <valeur> [string|float]
llm_set() {
    local section="$1" key="$2" value="$3" type="${4:-string}" old_user="" old_eff="" had_user=0
    if old_user="$(user_toml_value "$section" "$key" 2>/dev/null)"; then had_user=1; fi
    old_eff="$(effective_value "$section" "$key")"
    if [[ "$old_eff" != "$value" && -n "$old_eff" ]] \
        && { [[ "$had_user" -eq 1 && -n "$old_user" ]] || [[ "$key" == "runner" || "$key" == "backend" ]]; }; then
        warn "[$section].$key : $old_eff → $value. Pour revenir : ./install.sh --llm <fournisseur> (ou éditez config/workspace.user.toml, ancienne valeur : $old_eff)."
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [$section].$key = $value"
        return 0
    fi
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section "$section" --key "$key" --value "$value" --type "$type" >/dev/null \
        || warn "Impossible d'écrire [$section].$key — vérifiez config/workspace.user.toml."
}

# Fichier des clés API : créé (mode 600) avec une ligne d'exemple COMMENTÉE si
# absent ; on n'y écrit jamais de clé, on n'en affiche jamais. Dit comment
# l'ajouter quand la variable est absente.
ensure_llm_env() {
    local var="$1"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} $LLM_ENV_FILE (mode 600, variable $var)"
        return 0
    fi
    if [[ ! -f "$LLM_ENV_FILE" ]]; then
        mkdir -p "$(dirname "$LLM_ENV_FILE")"
        ( umask 077; cat > "$LLM_ENV_FILE" <<EOF
# Clés API du fournisseur LLM — mode 600, jamais versionné, jamais dans votre shell.
# Lignes NOM=valeur sans espace autour du « = » ; lu par le chat et la synchronisation.
# Décommentez et complétez :
# $var=
EOF
        )
        ok "Fichier de clés créé : $LLM_ENV_FILE (mode 600)"
    else
        chmod 600 "$LLM_ENV_FILE" 2>/dev/null || true
        if ! grep -qE "^[[:space:]]*(export[[:space:]]+)?#?[[:space:]]*$var=" "$LLM_ENV_FILE"; then
            printf '# %s=\n' "$var" >> "$LLM_ENV_FILE"
        fi
    fi
    if grep -qE "^[[:space:]]*(export[[:space:]]+)?$var=.+" "$LLM_ENV_FILE" || [[ -n "${!var:-}" ]]; then
        ok "Clé $var présente (valeur non affichée)"
    else
        warn "Clé $var absente : ouvrez $LLM_ENV_FILE et ajoutez la ligne $var=<votre clé> (mode 600, jamais dans le TOML)."
    fi
}

persist_llm() {
    [[ -n "$LLM_PROVIDER" ]] || return 0
    local chat_backend chat_model sync_runner sync_model key_var base_url="$LLM_BASE_URL_ARG"
    case "$LLM_PROVIDER" in
        openrouter)
            chat_backend="opencode"; sync_runner="opencode"
            chat_model="${LLM_MODEL_ARG:-$LLM_OPENROUTER_MODEL}"
            [[ "$chat_model" == openrouter/* ]] || chat_model="openrouter/$chat_model"
            sync_model="$chat_model"; key_var="OPENROUTER_API_KEY" ;;
        openai)
            chat_backend="opencode"; sync_runner="opencode"
            chat_model="$LLM_MODEL_ARG"
            [[ "$chat_model" == openai/* ]] || chat_model="openai/$chat_model"
            sync_model="$chat_model"; key_var="OPENAI_API_KEY" ;;
        anthropic)
            chat_backend="claude"; sync_runner="claude"
            chat_model="${LLM_MODEL_ARG:-$LLM_ANTHROPIC_CHAT_MODEL}"
            sync_model="$LLM_ANTHROPIC_SYNC_MODEL"; key_var="ANTHROPIC_API_KEY" ;;
    esac
    log "Chat et synchronisation sur $LLM_PROVIDER (clé : $key_var dans $LLM_ENV_FILE)"
    llm_set chat backend "$chat_backend"
    llm_set chat model "$chat_model"
    llm_set chat base_url "$base_url"
    llm_set chat api_key_env "$key_var"
    llm_set sync runner "$sync_runner"
    llm_set sync model "$sync_model"
    llm_set sync base_url "$base_url"
    # Runner claude déjà en place : la seule différence est la facturation. `llm_set` ne signale
    # pas un passage de « vide » à « rempli » ; ici, si : abonnement → clé API facturée au token.
    if [[ "$sync_runner" == "claude" && -z "$(effective_value sync api_key_env)" ]]; then
        warn "[sync].api_key_env : (vide) → $key_var — la synchronisation quitte l'abonnement : abonnement → clé API facturée au token ([sync].daily_budget_eur la plafonne). Pour revenir : videz [sync].api_key_env dans config/workspace.user.toml (ancienne valeur : vide)."
    fi
    llm_set sync api_key_env "$key_var"
    ensure_llm_env "$key_var"
    if [[ "$key_var" == "ANTHROPIC_API_KEY" ]]; then
        warn "N'exportez PAS ANTHROPIC_API_KEY dans votre shell ou votre profil : cela casse Remote Control (docs/mobile.md). Le chat et la sync la lisent dans llm.env."
    else
        warn "N'exportez pas $key_var dans votre shell ou votre profil : le chat et la sync le lisent dans llm.env."
    fi
    if [[ "$key_var" == "ANTHROPIC_API_KEY" && -n "${ANTHROPIC_API_KEY:-}" ]]; then
        warn "ANTHROPIC_API_KEY est DÉJÀ exporté dans cet environnement : retirez-le de votre profil (Remote Control refuse l'authentification par clé API)."
    fi
    if [[ "$LLM_PROVIDER" == "anthropic" ]]; then
        if [[ "$DO_CHAT" -eq 1 || "$(effective_value chat enabled)" == "true" ]]; then
            warn "Le chat avec le backend claude a besoin du SDK Python : pip install claude-agent-sdk (Python 3.10+)."
        fi
    elif have opencode; then
        ok "opencode : présent ($(opencode --version 2>/dev/null | head -1))"
    else
        warn "opencode absent — requis par le runner de sync et le chat sur $LLM_PROVIDER :"
        warn "  curl -fsSL https://opencode.ai/install | bash   (ou : npm i -g opencode-ai ; brew install anomalyco/tap/opencode)"
    fi
    if [[ "$LLM_PROVIDER" == "openrouter" ]]; then
        warn "Santé : limitez les fournisseurs OpenRouter à ceux qui ne conservent ni n'entraînent sur vos données (docs/mobile.md)."
    fi
}

persist_budgets() {
    [[ -z "$CHAT_BUDGET" ]] || llm_set chat daily_budget_eur "$CHAT_BUDGET" float
    [[ -z "$SYNC_BUDGET" ]] || llm_set sync daily_budget_eur "$SYNC_BUDGET" float
}

install_chat() {
    [[ "$DO_CHAT" -eq 1 ]] || return 0
    log "Service du chat avec le coach (scripts/coach-chat.sh install)"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [chat].enabled = true"
    else
        have python3 && python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
            --workspace "$WORKSPACE_ROOT" --section chat --key enabled --value true --type bool >/dev/null \
            || warn "Impossible d'écrire [chat].enabled — vérifiez config/workspace.user.toml."
    fi
    if [[ -z "$LLM_PROVIDER" ]]; then
        log "Modèle et clé du chat : voir [chat] (ou relancez avec --llm openrouter|anthropic|openai)."
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        ARC_WORKSPACE="$WORKSPACE_ROOT" ARC_DRY_RUN=1 "$PROJECT_ROOT/scripts/coach-chat.sh" install --dry-run
    else
        ARC_WORKSPACE="$WORKSPACE_ROOT" "$PROJECT_ROOT/scripts/coach-chat.sh" install
    fi
}

# ---------------------------------------------------------------------------
# 7. Vérification finale
# ---------------------------------------------------------------------------
verify() {
    log "Vérification finale"
    local fail=0
    if [[ "$SOURCE" == "strava" ]]; then
        for cmd in node npx; do
            if have "$cmd"; then
                ok "$cmd : présent"
            else
                warn "$cmd : absent — Node.js >= 18 requis pour --source strava"
                fail=1
            fi
        done
        if [[ -f "$STRAVA_MCP_DIR/run.sh" ]]; then
            ok "Wrapper MCP : présent ($STRAVA_MCP_DIR/run.sh)"
        else
            warn "Wrapper MCP absent ($STRAVA_MCP_DIR/run.sh) — relancez ./install.sh --source strava"
            fail=1
        fi
        if [[ -f "$STRAVA_TOKEN_FILE" ]]; then
            ok "Compte Strava : jetons présents ($STRAVA_TOKEN_FILE)"
        else
            warn "Compte Strava : non connecté — demandez à l'agent d'exécuter connect-strava (docs/strava-setup.md)"
        fi
    elif [[ "$SOURCE" == "intervals" ]]; then
        for cmd in uv intervals-icu-mcp; do
            if have "$cmd"; then
                ok "$cmd : présent"
            else
                warn "$cmd : absent"
                fail=1
            fi
        done
        if [[ -f "$INTERVALS_ENV_DIR/run.sh" ]]; then
            ok "Wrapper MCP : présent ($INTERVALS_ENV_DIR/run.sh)"
        else
            warn "Wrapper MCP absent ($INTERVALS_ENV_DIR/run.sh) — relancez ./install.sh --source intervals"
            fail=1
        fi
        if [[ -f "$INTERVALS_ENV_DIR/.env" ]]; then
            ok "Identifiants Intervals.icu : présents ($INTERVALS_ENV_DIR)"
        elif [[ "$DO_AUTH" -eq 0 ]]; then
            warn "Identifiants Intervals.icu : authentification sautée (--no-auth) — lancez $(intervals_auth_cmd)"
        else
            warn "Identifiants Intervals.icu : absents — lancez $(intervals_auth_cmd)"
        fi
    else
        for cmd in uv garmin-mcp; do
            if have "$cmd"; then
                ok "$cmd : présent"
            else
                warn "$cmd : absent"
                fail=1
            fi
        done
        if [[ "$USE_LEANPROXY" -eq 1 ]]; then
            if have leanproxy-mcp; then
                ok "leanproxy-mcp : présent (mode passerelle)"
            else
                warn "leanproxy-mcp : absent — mode passerelle incomplet"
                fail=1
            fi
        fi
        if [[ -f "$GARMIN_TOKENS_DIR/garmin_tokens.json" ]]; then
            ok "Tokens Garmin : présents ($GARMIN_TOKENS_DIR)"
        else
            warn "Tokens Garmin : absents — lancez 'uv run garmin-mcp-auth'"
        fi
    fi
    if [[ "$fail" -eq 0 ]]; then
        ok "Installation terminée. Lancez votre IDE et demandez à l'agent 'coach' de définir votre objectif !"
    else
        warn "Certains composants manquent — relisez les messages ci-dessus."
    fi
}

# ---------------------------------------------------------------------------
# Récapitulatif de la configuration effective (avant toute action)
# ---------------------------------------------------------------------------
# Indique, pour une option composée par un préréglage, si la valeur retenue
# vient d'une option explicite (toujours prioritaire) ou du préréglage.
_config_origin() {
    if [[ "$1" -eq 1 ]]; then
        echo "explicite"
    elif [[ -n "$PRESET" ]]; then
        echo "préréglage $PRESET"
    else
        echo "défaut"
    fi
}


# « clé : valeur (origine) », sans tentative d'alignement en colonnes : un
# `printf %-Ns` compte des OCTETS, pas des caractères — un mot accentué (UTF-8,
# multi-octets) désaligne toutes les lignes qui le suivent.
recap_line() { printf '  %s : %s (%s)\n' "$1" "$2" "$3"; }

print_config_recap() {
    log "Récapitulatif de la configuration effective :"
    [[ -n "$PRESET" ]] && printf '  Préréglage : %s\n' "$PRESET"
    recap_line "IDE" "$IDE" "$(_config_origin "$EXPLICIT_IDE")"
    # --source n'est composée par AUCUN préréglage (voir la note près de
    # EXPLICIT_SOURCE) : jamais "préréglage X" ici — "explicite" (--source),
    # "config" (résolue depuis workspace.user.toml/workspace.toml par
    # resolve_source(), ex. un athlète intervals qui relance sans --source) ou
    # "défaut" (jamais configuré nulle part : garmin).
    recap_line "Source de données" "$SOURCE" \
        "$([[ "$EXPLICIT_SOURCE" -eq 1 ]] && echo "explicite" || { [[ "$SOURCE" != "garmin" ]] && echo "config" || echo "défaut"; })"
    # Les préréglages ne touchent jamais au staff d'agents (voir apply_preset) :
    # « défaut » veut dire ici config/workspace.user.toml ou, à défaut, tous.
    recap_line "Agents" "$ENABLED_AGENTS" "$([[ "$EXPLICIT_AGENTS" -eq 1 ]] && echo "explicite" || echo "défaut")"
    recap_line "$(case "$SOURCE" in intervals) echo "Auth Intervals.icu" ;; strava) echo "Auth Strava" ;; *) echo "Auth Garmin" ;; esac)" \
        "$([[ "$DO_AUTH" -eq 1 ]] && echo "activée" || echo "sautée")" "$(_config_origin "$EXPLICIT_DO_AUTH")"
    recap_line "Passerelle leanproxy" \
        "$([[ "$USE_LEANPROXY" -eq 1 ]] && echo "oui" || echo "non")" "$(_config_origin "$EXPLICIT_LEANPROXY")"
    recap_line "Sync auto (cron)" \
        "$([[ "$DAILY_SYNC" -eq 1 ]] && echo "oui" || echo "non")" "$(_config_origin "$EXPLICIT_DAILY_SYNC")"
    recap_line "Remote Control" \
        "$([[ "$REMOTE_CONTROL" -eq 1 ]] && echo "oui" || echo "non")" "$(_config_origin "$EXPLICIT_REMOTE_CONTROL")"
    [[ -z "$LLM_PROVIDER" ]] || recap_line "Chat + sync sur API" "$LLM_PROVIDER" "explicite"
    [[ "$DO_CHAT" -eq 0 ]] || recap_line "Service du chat" "oui" "explicite"
    recap_line "Workspace" "$WORKSPACE_ROOT" "$([[ -n "$WORKSPACE_ARG" ]] && echo "explicite" || echo "défaut")"
    recap_line "Dry-run" \
        "$([[ "$DRY_RUN" -eq 1 ]] && echo "oui" || echo "non")" "$([[ "$DRY_RUN" -eq 1 ]] && echo "explicite" || echo "défaut")"
    echo
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log "ai-running-coach — installation v$VERSION"
    log "Projet : $PROJECT_ROOT"
    resolve_workspace
    workspace_is_separate && log "Workspace : $WORKSPACE_ROOT (--workspace)"
    resolve_agents
    resolve_source
    print_config_recap
    [[ "$DRY_RUN" -eq 1 ]] && warn "Mode dry-run : aucune modification ne sera effectuée."
    echo

    require_cmd curl "Installez curl (macOS : déjà présent ; Linux : apt install curl)."
    require_cmd git "Installez git."

    # Strava : aucun outil Python à installer (serveur npm lancé par npx) — pas de uv.
    [[ "$SOURCE" == "strava" ]] || install_uv
    if [[ "$SOURCE" == "strava" ]]; then
        install_strava_mcp
    elif [[ "$SOURCE" == "intervals" ]]; then
        install_intervals_mcp
    else
        install_garmin_mcp
    fi
    install_leanproxy
    configure_leanproxy
    prepare_workspace
    configure_ide
    create_workspace_dirs
    create_workspace_config
    persist_agents
    persist_source
    persist_llm
    persist_budgets
    if [[ "$DAILY_SYNC" -eq 1 || "$REMOTE_CONTROL" -eq 1 ]]; then
        check_runners
    fi
    install_daily_sync
    install_remote_control
    install_chat
    verify
}

main "$@"
