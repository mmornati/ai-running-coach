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
#   ./install.sh --cycle-tracking MODE # off (défaut) | garmin | intervals | manual — contexte du cycle menstruel, opt-in (#166)
#   ./install.sh --nutrition-sync MODE # off (défaut) | ask — pousser les apports vers Garmin Connect, opt-in (#167)
#   ./install.sh --health-source S     # primary (défaut) | openwearables — santé du bilan matinal lue chez Open Wearables, opt-in (#220)
#     --ow-url URL --ow-provider P     #   instance Open Wearables et UN fabricant (oura, whoop, polar…) ; --ow-key-file F importe la clé
#   ./install.sh --workspace DIR    # données + config IDE dans DIR (dépôt privé), moteur lié
#   ./install.sh --agents LISTE     # staff à installer, ex. coach,nutritionist
#   ./install.sh --no-medical       # tous les agents sauf le médecin
#   ./install.sh --no-auth          # saute l'authentification Garmin
#   ./install.sh --use-leanproxy    # mode passerelle leanproxy (power user)
#   ./install.sh --daily-sync       # cron/launchd : sync Garmin aux heures de [sync].times
#   ./install.sh --remote-control   # service Remote Control (le coach dans la poche)
#   ./install.sh --llm openrouter   # chat + sync sur une API (openrouter|anthropic|openai), un abonnement (chatgpt|copilot) ou l'essai gratuit (openrouter-free)
#   ./install.sh --chat             # service du chat avec le coach (dashboard)
#   ./install.sh --telegram         # bot Telegram : retours en un geste, sans LLM (docs/telegram.md)
#   ./install.sh --dashboard-docker local|traefik # tableau de bord en conteneur, reconstruit par /update-coach
#   ./install.sh --dry-run          # affiche les actions sans rien exécuter
#   ./install.sh --help
#
# Prérequis : macOS ou Linux, bash 3.2+ (celui de macOS convient), curl, git.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
# Numéro de la dernière release : fichier VERSION, réécrit par le workflow « Tag a release ».
VERSION="$(tr -d '[:space:]' 2>/dev/null < "$(dirname "${BASH_SOURCE[0]}")/VERSION" || true)"
VERSION="${VERSION:-inconnue}"
# Épinglé à un commit précis, comme INTERVALS_MCP_REF ci-dessous : ce serveur reçoit le
# mot de passe et le code MFA Garmin à l'authentification, puis tourne à chaque
# synchronisation — un changement en amont ne doit jamais être exécuté sans relecture.
# Mettre à jour après vérification du diff amont.
GARMIN_MCP_REF="git+https://github.com/Taxuspt/garmin_mcp@cfc5d799ab0f165e837f1188a1d093c65838aaf7"
# Source alternative (#68) : serveur MCP communautaire retenu par --source
# intervals. project.scripts expose `intervals-icu-mcp` + `intervals-icu-mcp-auth`,
# comme garmin_mcp/garmin-mcp-auth ci-dessus — même mécanique `uv tool install`.
# #165 : fork maintenu hhopke/intervals-icu-mcp (v5.6.0), qui remplace
# eddmann/intervals-icu-mcp@cb91d4a (plus de commit depuis nov. 2025). Mêmes
# binaires et même `.env` (INTERVALS_ICU_API_KEY / INTERVALS_ICU_ATHLETE_ID),
# MAIS tous les outils sont préfixés `icu_` — voir AGENTS.md et
# docs/intervals-setup.md.
# Épinglé à un commit précis (vérifié dans le code : project.scripts, tools/*.py,
# réponses JSON) plutôt qu'à `main` — un changement en amont (renommage d'outil,
# retrait de champ) ne doit jamais casser silencieusement ce projet. Mettre à jour
# ensemble : cette ligne, AGENTS.md, docs/intervals-setup.md et
# scripts/coach_doctor.py (INTERVALS_MCP_PINNED_*) ; le lint
# tests/lint/test_data_source_parity.py vérifie qu'ils concordent.
INTERVALS_MCP_REF="git+https://github.com/hhopke/intervals-icu-mcp@92a630bfc4ffe7906c9bf8d2280c1ea41a561d66"
# Le serveur charge ses identifiants depuis un `.env` relatif à SON répertoire
# de travail (pydantic-settings) — jamais depuis le dépôt : `intervals-icu-mcp-auth`
# est donc lancé depuis ce dossier dédié, hors du projet, comme `$GARMIN_TOKENS_DIR`
# ci-dessous pour Garmin.
INTERVALS_ENV_DIR="$HOME/.config/ai-running-coach/intervals-icu-mcp"
# Source Strava (#164) : serveur MCP communautaire r-huijts/strava-mcp, publié sur npm
# (`@r-huijts/strava-mcp-server`, bin `strava-mcp-server`, stdio). Épinglé à la version 1.2.1,
# publiée depuis le commit a68112aa12a88909593db0f4b1ac0f6aebed6e3a (`gitHead` du registre npm) :
# noms d'outils et fichier de jetons vérifiés dans le dist/ du tarball et dans ce commit (la tête de
# `main` a des outils non publiés — à relire avant de relever la version). Documenté dans docs/strava-setup.md ;
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
GARMIN_TOOL_WHITELIST="get_activities,get_activities_by_date,get_activity,get_activity_fit_data,get_activity_splits,get_activity_typed_splits,get_activity_split_summaries,get_sleep_data,get_hrv_data,get_rhr_day,get_training_readiness,get_calendar_events,get_courses,get_workouts,get_workout_by_id,get_scheduled_workouts,schedule_workouts,schedule_week,upload_workout,upload_course,create_strength_workout,delete_workout,unschedule_workout,unschedule_workouts,download_activity_file,get_stats,get_lactate_threshold,get_training_status,get_gear,get_activity_gear,add_gear_to_activity,get_daily_weigh_ins,get_weigh_ins"
# Outils de cycle menstruel (#166) : JAMAIS dans la liste blanche par défaut — ajoutés par
# resolve_cycle_tracking() uniquement quand [health].cycle_tracking = "garmin" (opt-in) et que la
# source est Garmin. Noms vérifiés dans src/garmin_mcp/womens_health.py du commit épinglé ci-dessus.
# `get_pregnancy_summary` (même module) n'est volontairement PAS ajouté : hors périmètre.
GARMIN_CYCLE_TOOLS="get_menstrual_data_for_date,get_menstrual_calendar_data"
# Outils de nutrition/hydratation (#167) : JAMAIS dans la liste blanche par défaut — ajoutés par
# resolve_nutrition_sync() uniquement quand [nutrition].garmin_sync = "ask" (opt-in) et que la source
# est Garmin. Noms vérifiés dans src/garmin_mcp/nutrition.py, data_management.py (add_hydration_data)
# et health_wellness.py (get_hydration_data) du commit épinglé ci-dessus. Volontairement ABSENTS :
# delete_food_log, update_custom_food, upsert_and_log (écriture irréversible / qui écrase une entrée
# de l'athlète — à corriger dans Garmin Connect). Les écritures restent derrière un « oui » explicite
# et sont interdites en headless (scripts/daily-sync.sh).
GARMIN_NUTRITION_TOOLS="get_custom_foods,get_custom_food_serving_units,get_nutrition_daily_food_log,get_nutrition_daily_meals,get_hydration_data,create_custom_food,log_custom_food,log_food,add_hydration_data"

# Chat avec le coach et sync sur une API (--llm) : modèles par défaut, UNE constante
# chacun. Identifiant OpenRouter « deepseek/deepseek-v4.1-flash » vérifié dans le catalogue
# https://openrouter.ai/api/v1/models et comparé à 7 autres modèles en conditions réelles
# (docs/dashboard/chat.md, « Quel modèle sur OpenRouter ? ») : le plus fiable et le moins cher.
# L'ancien « deepseek/deepseek-chat » (V3) annonçait des écritures jamais faites. Forme OpenCode « fournisseur/modèle »
# (https://opencode.ai/docs/providers). Haiku 4.5 pour le cron (répétitif, contrat
# vérifié par arc_index.py --validate), Sonnet 5.5 pour le chat.
# Catalogue complet (source de vérité) : python3 scripts/arc_llm.py providers --json ; un test vérifie
# que ces constantes y concordent (install.sh doit fonctionner sans python3).
LLM_OPENROUTER_MODEL="openrouter/deepseek/deepseek-v4.1-flash"
# Essai gratuit (--llm openrouter-free, #267) : identifiants vérifiés dans https://openrouter.ai/api/v1/models le
# 2026-10-15 (alternatives : openrouter/nvidia/nemotron-3.5-lightning:free, openrouter/cohere/north-mini-code:free).
# Choisi par un essai réel du même jour (/log, bilan, /week sur un workspace synthétique, un passage par modèle) :
# 19/19 contre 17/19 pour les alternatives — méthode et limites dans docs/choisir-son-ia.md#essai-gratuit.
LLM_OPENROUTER_FREE_MODEL="openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
LLM_ANTHROPIC_CHAT_MODEL="claude-sonnet-5-5"
LLM_ANTHROPIC_SYNC_MODEL="claude-haiku-4-5"
# Abonnements (--llm chatgpt|copilot, #266) : identifiants vérifiés dans models.dev (2026-10-15) et dans la
# liste d'autorisation du plugin OAuth d'OpenCode v1.18.35 — PAS évalués sur un vrai forfait (approximation
# du projet). Un test les compare au catalogue (scripts/arc_llm.py).
LLM_CHATGPT_CHAT_MODEL="openai/gpt-5.4-mini"
LLM_CHATGPT_SYNC_MODEL="openai/gpt-5.4"
LLM_COPILOT_CHAT_MODEL="github-copilot/gpt-5.4-mini"
LLM_COPILOT_SYNC_MODEL="github-copilot/claude-sonnet-5.5"
# Magasin d'authentification OpenCode dédié au coach (mode 700), hors dépôt et hors workspace : chat ET sync
# l'utilisent comme XDG_DATA_HOME pour ces deux fournisseurs ([chat|sync].opencode_data_dir).
LLM_OPENCODE_DATA_DIR="${ARC_OPENCODE_DATA_DIR:-$HOME/.local/share/ai-running-coach/opencode}"
# Clés API : dans ce fichier (mode 600), jamais dans le TOML ni dans le shell.
LLM_ENV_FILE="${ARC_LLM_ENV:-$HOME/.config/ai-running-coach/llm.env}"
# Jeton du bot Telegram (#174) : même discipline (mode 600, hors dépôt, jamais dans le TOML).
TELEGRAM_ENV_FILE="$HOME/.config/ai-running-coach/telegram.env"

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
NEW_AGENTS=""      # agents apparus depuis la dernière installation, activés d'office
PRESET=""          # --preset laptop|coach-server|docker (défaut : aucun)
SOURCE="garmin"    # --source garmin|intervals|strava (#68, #164) — source de données primaire
CYCLE_TRACKING="off" # --cycle-tracking off|garmin|intervals|manual (#166) — contexte du cycle, opt-in
NUTRITION_SYNC="off" # --nutrition-sync off|ask (#167) — poussée des apports vers Garmin, opt-in
HEALTH_SOURCE=""   # --health-source primary|openwearables (#220) — santé du bilan matinal, opt-in
OW_URL=""          # --ow-url URL (avec --health-source openwearables)
OW_PROVIDER=""     # --ow-provider P (avec --health-source openwearables)
OW_KEY_FILE_ARG="" # --ow-key-file FICHIER : clé d'API à importer (jamais passée en argument)
OW_KEY_FILE_DEFAULT="$HOME/.config/ai-running-coach/openwearables.key" # = défaut de [health.openwearables].api_key_file
HEALTH_EFFECTIVE="primary" # résolu par resolve_health_source()
LLM_PROVIDER=""    # --llm openrouter|openrouter-free|anthropic|openai|chatgpt|copilot — chat + sync sur une API, un abonnement ou l'essai gratuit
LLM_MODEL_ARG=""   # --model ID (avec --llm)
LLM_BASE_URL_ARG="" # --base-url URL (avec --llm openai : API compatible OpenAI)
SYNC_SUBSCRIPTION=0 # --sync-subscription (1) : avec --llm chatgpt|copilot, met AUSSI la synchronisation sur l'abonnement ; --no-sync-subscription (-1) : jamais
LLM_CONNECT=0      # --connect : connexion en un clic (openrouter) ou avec son compte (chatgpt|copilot), interactif seulement
DO_CHAT=0          # --chat : service du chat avec le coach
CHAT_BUDGET=""     # --chat-budget EUR
DO_TELEGRAM=0      # --telegram : bot Telegram (retours en un geste, #174)
TELEGRAM_CHAT_ID="" # --telegram-chat-id ID : ajoute un chat à [telegram].allowed_chat_ids
SYNC_BUDGET=""     # --sync-budget EUR
SYNC_RUNNER_ARG="" # --sync-runner : exécuteur headless explicite
DASH_DOCKER=""     # --dashboard-docker off|local|traefik : tableau de bord en conteneur, opt-in
DASH_HOST=""       # --dashboard-host NOM (avec traefik ; défaut coach.localhost)
DASH_AUTH=""       # --dashboard-auth MIDDLEWARE (avec traefik ; obligatoire si Traefik est joignable du réseau)
DASH_NETWORK=""    # réseau Docker de Traefik ([dashboard].docker_network, sinon détecté)
DASH_ENTRYPOINT="" # point d'entrée Traefik ([dashboard].docker_entrypoint, sinon détecté)
DASH_TRAEFIK=""    # conteneur Traefik détecté
DASH_PERSIST=0     # 1 : réponse ou option à écrire dans [dashboard]
DASH_PROJECT="arc-dashboard"
DASH_DIR="$HOME/.config/ai-running-coach/dashboard"

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
EXPLICIT_CYCLE=0   # --cycle-tracking passé (#166) : seul cas où [health].cycle_tracking est écrit
EXPLICIT_NUTRITION=0 # --nutrition-sync passé (#167) : seul cas où [nutrition].garmin_sync est écrit
EXPLICIT_DASH=0    # --dashboard-docker passé : écrit [dashboard].docker
EXPLICIT_HEALTH=0  # --health-source passé (#220) : seul cas où [health].source et [health.openwearables] sont écrits
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
  ./install.sh --cycle-tracking MODE # off (défaut) | garmin | intervals | manual — contexte du cycle menstruel, opt-in (#166)
  ./install.sh --nutrition-sync MODE # off (défaut) | ask — pousser les apports vers Garmin Connect, opt-in (#167)
  ./install.sh --health-source S  # primary (défaut) | openwearables — santé du bilan matinal chez Open Wearables, opt-in (#220)
  ./install.sh --ow-url URL       # avec --health-source openwearables : adresse de votre instance (http://hôte[:port])
  ./install.sh --ow-provider P    # avec --health-source openwearables : UN fabricant (oura, whoop, polar…)
  ./install.sh --ow-key-file F    # avec --health-source openwearables : importe la clé d'API (copiée hors dépôt, mode 600)
  ./install.sh --workspace DIR    # données + config IDE dans DIR (dépôt privé), moteur lié
  ./install.sh --agents LISTE     # staff à installer, ex. coach,nutritionist
  ./install.sh --no-medical       # tous les agents sauf le médecin
  ./install.sh --no-auth          # saute l'authentification Garmin
  ./install.sh --auth             # force l'authentification Garmin (annule --no-auth d'un préréglage)
  ./install.sh --use-leanproxy    # mode passerelle leanproxy (power user)
  ./install.sh --skip-leanproxy   # mode direct (annule --use-leanproxy d'un préréglage)
  ./install.sh --daily-sync       # cron/launchd : sync Garmin aux heures de [sync].times
  ./install.sh --sync-runner CLI  # claude | codex | copilot | opencode | gemini | cursor
  ./install.sh --no-daily-sync    # désactive la sync (annule --daily-sync d'un préréglage)
  ./install.sh --remote-control   # service Remote Control (le coach dans la poche)
  ./install.sh --no-remote-control # désactive Remote Control (annule --remote-control d'un préréglage)
  ./install.sh --llm FOURNISSEUR  # openrouter | openrouter-free | anthropic | openai | chatgpt | copilot — chat ET sync (voir ci-dessous)
  ./install.sh --model ID         # avec --llm : modèle (openrouter : ID OpenRouter ; openrouter-free : ID finissant par :free ; anthropic, chatgpt, copilot : modèle du chat)
  ./install.sh --sync-subscription # avec --llm chatgpt|copilot : la synchronisation automatique passe aussi sur l'abonnement
  ./install.sh --no-sync-subscription # avec --llm chatgpt|copilot : ne touche pas à la synchronisation, même sur une installation neuve
  ./install.sh --connect          # avec --llm openrouter|openrouter-free|chatgpt|copilot : se connecte dans le navigateur (aucune clé à copier)
  ./install.sh --base-url URL     # avec --llm openai : API compatible OpenAI autre que api.openai.com
  ./install.sh --chat             # active [chat] et installe le service (scripts/coach-chat.sh)
  ./install.sh --chat-budget EUR  # plafond quotidien du chat ([chat].daily_budget_eur)
  ./install.sh --sync-budget EUR  # plafond quotidien de la sync ([sync].daily_budget_eur)
  ./install.sh --telegram         # active [telegram] et installe le service (scripts/coach-telegram.sh)
  ./install.sh --telegram-chat-id ID # avec --telegram : autorise ce chat (liste blanche, jamais le jeton)
  ./install.sh --dashboard-docker MODE # off | local | traefik — tableau de bord en conteneur, reconstruit par /update-coach
  ./install.sh --dashboard-host NOM   # avec traefik : adresse servie (défaut coach.localhost)
  ./install.sh --dashboard-auth MW    # avec traefik : middleware d'authentification (obligatoire si Traefik est joignable du réseau)
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
Pour changer la SYNCHRONISATION SEULE (chat intact, sans relancer install.sh) :
python3 scripts/arc_llm.py sync anthropic|openrouter|openai|claude-subscription.

--connect (avec --llm openrouter) lance « scripts/arc_llm.py connect openrouter » : le navigateur
s'ouvre, vous autorisez le coach, la clé est écrite dans llm.env (mode 600) sans que vous la
voyiez. Interactif seulement : sans terminal, la commande à lancer vous est indiquée ; avec
--dry-run, rien n'est ouvert. Sans --connect, rien ne change.

--llm openrouter-free (essai gratuit, #267) : même clé et même connexion qu'openrouter (--connect), modèle
gratuit « :free » pour le chat ET la sync, rien à payer (aucun budget en euros). Limites dites franchement :
50 requêtes par jour sans achat de crédits (1 000 après 10 $ achetés au total), 20 par minute — environ un /log
et quelques questions par jour. CONFIDENTIALITÉ : ces modèles peuvent conserver vos prompts (à vérifier sur les pages
d'OpenRouter) et NVIDIA déclare s'entraîner dessus : pas de données de santé sensibles (https://openrouter.ai/settings/privacy) ; payant :
DeepSeek ≈ 0,80 €/mois ou « 10 $ une fois ». Si [sync].mode n'est pas déjà posé dans workspace.user.toml, la
sync passe en mode « watch » (LLM seulement s'il y a du neuf, pour ménager le quota) ; une valeur déjà posée
n'est jamais écrasée. Détails : docs/choisir-son-ia.md#essai-gratuit.

--llm chatgpt (ChatGPT Plus ou Pro) et --llm copilot (GitHub Copilot Pro, Pro+, Business, Enterprise)
utilisent votre abonnement existant, sans clé API : le CHAT passe par OpenCode, qui garde la
connexion dans un magasin dédié au coach (mode 700, [chat|sync].opencode_data_dir, par défaut
~/.local/share/ai-running-coach/opencode). Rien n'est facturé au jeton : les limites de votre forfait
s'appliquent, et le plafond en euros ne compte rien. La SYNCHRONISATION automatique ne passe sur
l'abonnement que sur une installation NEUVE (aucune installation antérieure : options mémorisées,
planificateur de la sync, [sync].runner) ou avec
--sync-subscription : aucune déclaration officielle n'autorise l'usage planifié sans surveillance
d'un forfait grand public, ce choix doit donc être explicite. Sinon elle garde son exécuteur actuel.
ARC_OPENCODE_DATA_DIR change le dossier du magasin le temps d'une installation (il est alors écrit dans la
configuration ; à répéter si vous relancez l'installation). Avec --connect, « scripts/arc_llm.py login
chatgpt|copilot » est lancé (interactif seulement) ; sinon lancez-le vous-même une fois. --model change
le modèle du chat (identifiant OpenCode « fournisseur/modèle »). Les modèles par défaut n'ont pas été
évalués sur un vrai forfait.

--telegram active [telegram].enabled et installe le service du bot. Le jeton du
bot (BotFather) n'est JAMAIS une option de ligne de commande : ~/.config/ai-running-coach/telegram.env
(mode 600, créé avec une ligne d'exemple commentée) — à remplir vous-même.
Un rerun n'écrase jamais [telegram] : --telegram-chat-id AJOUTE un chat à la liste.

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
# Arguments tels que reçus, mémorisés en fin d'installation réussie (persist_install_args) :
# scripts/update-coach.sh relance install.sh avec exactement les mêmes options.
INSTALL_ARGS=("$@")
INSTALL_CWD="$PWD"   # update-coach.sh relance depuis la racine du moteur : chemins relatifs rendus absolus
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
        --cycle-tracking) need_value "$@"; CYCLE_TRACKING="$2"; EXPLICIT_CYCLE=1; shift 2 ;;
        --nutrition-sync) need_value "$@"; NUTRITION_SYNC="$2"; EXPLICIT_NUTRITION=1; shift 2 ;;
        --health-source) need_value "$@"; HEALTH_SOURCE="$2"; EXPLICIT_HEALTH=1; shift 2 ;;
        --ow-url) need_value "$@"; OW_URL="$2"; shift 2 ;;
        --ow-provider) need_value "$@"; OW_PROVIDER="$2"; shift 2 ;;
        --ow-key-file) need_value "$@"; OW_KEY_FILE_ARG="$2"; shift 2 ;;
        --no-auth) DO_AUTH=0; EXPLICIT_DO_AUTH=1; shift ;;
        --auth) DO_AUTH=1; EXPLICIT_DO_AUTH=1; shift ;;  # annule --no-auth composé par un préréglage
        --use-leanproxy) USE_LEANPROXY=1; EXPLICIT_LEANPROXY=1; shift ;;
        --skip-leanproxy) USE_LEANPROXY=0; EXPLICIT_LEANPROXY=1; shift ;;  # rétro-compatibilité
        --workspace) need_value "$@"; WORKSPACE_ARG="$2"; shift 2 ;;
        --agents) need_value "$@"; AGENTS_ARG="$2"; EXPLICIT_AGENTS=1; shift 2 ;;
        --no-medical) AGENTS_ARG="${AGENTS_ARG:-__all_but__}:medical"; EXPLICIT_AGENTS=1; shift ;;
        --daily-sync) DAILY_SYNC=1; EXPLICIT_DAILY_SYNC=1; shift ;;
        --sync-runner) need_value "$@"; SYNC_RUNNER_ARG="$2"; shift 2 ;;
        --no-daily-sync) DAILY_SYNC=0; EXPLICIT_DAILY_SYNC=1; shift ;;  # annule --daily-sync composé par un préréglage
        --remote-control) REMOTE_CONTROL=1; EXPLICIT_REMOTE_CONTROL=1; shift ;;
        --no-remote-control) REMOTE_CONTROL=0; EXPLICIT_REMOTE_CONTROL=1; shift ;;  # annule --remote-control composé par un préréglage
        --llm) need_value "$@"; LLM_PROVIDER="$2"; shift 2 ;;
        --model) need_value "$@"; LLM_MODEL_ARG="$2"; shift 2 ;;
        --base-url) need_value "$@"; LLM_BASE_URL_ARG="$2"; shift 2 ;;
        --connect) LLM_CONNECT=1; shift ;;
        --sync-subscription) SYNC_SUBSCRIPTION=1; shift ;;
        --no-sync-subscription) SYNC_SUBSCRIPTION=-1; shift ;;
        --chat) DO_CHAT=1; shift ;;
        --chat-budget) need_value "$@"; CHAT_BUDGET="$2"; shift 2 ;;
        --telegram) DO_TELEGRAM=1; shift ;;
        --telegram-chat-id) need_value "$@"; TELEGRAM_CHAT_ID="$2"; shift 2 ;;
        --sync-budget) need_value "$@"; SYNC_BUDGET="$2"; shift 2 ;;
        --dashboard-docker) need_value "$@"; DASH_DOCKER="$2"; EXPLICIT_DASH=1; shift 2 ;;
        --dashboard-host) need_value "$@"; DASH_HOST="$2"; shift 2 ;;
        --dashboard-auth) need_value "$@"; DASH_AUTH="$2"; shift 2 ;;
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
[[ -z "$TELEGRAM_CHAT_ID" || "$TELEGRAM_CHAT_ID" =~ ^-?[0-9]+$ ]] \
    || die "--telegram-chat-id : identifiant numérique attendu (python3 scripts/arc_telegram.py whoami)."
[[ -z "$TELEGRAM_CHAT_ID" || "$DO_TELEGRAM" -eq 1 ]] || die "--telegram-chat-id s'utilise avec --telegram."
[[ -z "$CHAT_BUDGET" ]] || validate_budget --chat-budget "$CHAT_BUDGET"
[[ -z "$SYNC_BUDGET" ]] || validate_budget --sync-budget "$SYNC_BUDGET"
if [[ -n "$SYNC_RUNNER_ARG" ]]; then
    case "$SYNC_RUNNER_ARG" in
        claude|codex|copilot|opencode|gemini|cursor) ;;
        *) die "Exécuteur de synchronisation inconnu : « $SYNC_RUNNER_ARG ». Valides : claude, codex, copilot, opencode, gemini, cursor." ;;
    esac
fi
if [[ -n "$LLM_PROVIDER" ]]; then
    case "$LLM_PROVIDER" in
        openrouter|anthropic) ;;
        openrouter-free)
            [[ -z "$LLM_MODEL_ARG" || "$LLM_MODEL_ARG" == *:free ]] \
                || die "--llm openrouter-free n'accepte qu'un modèle gratuit (identifiant finissant par :free, ex. nvidia/nemotron-3.5-lightning:free) ; pour un modèle payant, utilisez --llm openrouter." ;;
        openai) [[ -n "$LLM_MODEL_ARG" ]] || die "--llm openai exige --model (ex. --model gpt-4.1-mini ; ajoutez --base-url pour une autre API compatible OpenAI)." ;;
        chatgpt|copilot) ;;
        *) die "Fournisseur LLM inconnu : « $LLM_PROVIDER ». Valides : openrouter, openrouter-free, anthropic, openai, chatgpt, copilot (voir --help)." ;;
    esac
    if [[ -n "$LLM_BASE_URL_ARG" && "$LLM_PROVIDER" == "anthropic" ]]; then
        die "--base-url n'a pas de sens avec --llm anthropic (utilisez --llm openai pour une API compatible OpenAI)."
    fi
    if [[ -n "$LLM_BASE_URL_ARG" && ( "$LLM_PROVIDER" == "chatgpt" || "$LLM_PROVIDER" == "copilot" ) ]]; then
        die "--base-url n'a pas de sens avec --llm $LLM_PROVIDER (abonnement : aucune URL ni clé)."
    fi
    # Un modèle d'un autre fournisseur donnerait « openai/github-copilot/x » : refusé net.
    if [[ "$LLM_PROVIDER" == "chatgpt" && "$LLM_MODEL_ARG" == */* && "$LLM_MODEL_ARG" != openai/* ]]; then
        die "--model $LLM_MODEL_ARG : un modèle ChatGPT s'écrit « gpt-5.4 » ou « openai/gpt-5.4 » (pas d'autre fournisseur)."
    fi
    if [[ "$LLM_PROVIDER" == "copilot" && "$LLM_MODEL_ARG" == */* && "$LLM_MODEL_ARG" != github-copilot/* ]]; then
        die "--model $LLM_MODEL_ARG : un modèle Copilot s'écrit « gpt-5.4-mini » ou « github-copilot/gpt-5.4-mini » (pas d'autre fournisseur)."
    fi
elif [[ -n "$LLM_MODEL_ARG" || -n "$LLM_BASE_URL_ARG" ]]; then
    die "--model et --base-url s'utilisent avec --llm (voir --help)."
fi
if [[ "$SYNC_SUBSCRIPTION" -ne 0 && "$LLM_PROVIDER" != "chatgpt" && "$LLM_PROVIDER" != "copilot" ]]; then
    die "--sync-subscription et --no-sync-subscription s'utilisent avec --llm chatgpt ou --llm copilot."
fi
if [[ "$LLM_CONNECT" -eq 1 && "$LLM_PROVIDER" != "openrouter" && "$LLM_PROVIDER" != "openrouter-free" && "$LLM_PROVIDER" != "chatgpt" && "$LLM_PROVIDER" != "copilot" ]]; then
    die "--connect s'utilise avec --llm openrouter, openrouter-free, chatgpt ou copilot (connexion sans clé à copier ; pour les autres fournisseurs, collez la clé dans llm.env — docs/choisir-son-ia.md)."
fi

# Valide $CYCLE_TRACKING (même principe que validate_source).
validate_cycle_tracking() {
    case "$CYCLE_TRACKING" in
        off|garmin|intervals|manual) ;;
        *) die "Mode de suivi du cycle inconnu : « $CYCLE_TRACKING ». Valides : off, garmin, intervals, manual (voir --help)." ;;
    esac
}
if [[ "$EXPLICIT_CYCLE" -eq 1 ]]; then
    validate_cycle_tracking
fi

# Valide $NUTRITION_SYNC (#167, même principe).
validate_nutrition_sync() {
    case "$NUTRITION_SYNC" in
        off|ask) ;;
        *) die "Mode de synchronisation nutrition inconnu : « $NUTRITION_SYNC ». Valides : off, ask (voir --help)." ;;
    esac
}
if [[ "$EXPLICIT_NUTRITION" -eq 1 ]]; then
    validate_nutrition_sync
fi

# Valide les options Open Wearables (#220) : échec immédiat, avant tout travail. Les fournisseurs
# reprennent scripts/arc_health_source.py (PROVIDERS / REFUSED_PROVIDERS ; un test de lint compare).
OW_PROVIDERS="oura whoop polar ultrahuman withings google_health apple health_connect samsung suunto"
# Contrôles du fournisseur et de l'URL Open Wearables — appelés aussi sur les valeurs relues de la
# configuration (resolve_health_source) : une valeur écrite à la main n'échappe pas à la validation.
check_ow_provider() {
    [[ -n "$OW_PROVIDER" ]] || return 0
    OW_PROVIDER="$(printf '%s' "$OW_PROVIDER" | tr '[:upper:]' '[:lower:]')"
    case "$OW_PROVIDER" in
        garmin) die "--ow-provider garmin refusé : Garmin se lit en direct (garmin-mcp), jamais via Open Wearables (docs/open-wearables.md)." ;;
        strava) die "--ow-provider strava refusé : Strava n'expose aucune donnée de santé (HRV, FC de repos, sommeil)." ;;
    esac
    case " $OW_PROVIDERS " in
        *" $OW_PROVIDER "*) ;;
        *) die "Fournisseur Open Wearables inconnu : « $OW_PROVIDER ». Valides : $OW_PROVIDERS." ;;
    esac
}
check_ow_url() {
    [[ -n "$OW_URL" ]] || return 0
    local url_re='^https?://[][A-Za-z0-9._:-]+(/[A-Za-z0-9._~/%-]*)?$'
    [[ "$OW_URL" =~ $url_re ]] \
        || die "Adresse Open Wearables invalide : http(s)://hôte[:port] attendu, sans identifiants ni paramètres."
    OW_URL="${OW_URL%/}"
}
validate_health_source() {
    case "$HEALTH_SOURCE" in
        primary|openwearables) ;;
        *) die "Source de santé inconnue : « $HEALTH_SOURCE ». Valides : primary, openwearables (voir --help)." ;;
    esac
    if [[ "$HEALTH_SOURCE" != "openwearables" ]]; then
        [[ -z "$OW_URL$OW_PROVIDER$OW_KEY_FILE_ARG" ]] \
            || die "--ow-url, --ow-provider et --ow-key-file s'utilisent avec --health-source openwearables."
        return 0
    fi
    check_ow_provider
    check_ow_url
    if [[ -n "$OW_KEY_FILE_ARG" && ! -f "$OW_KEY_FILE_ARG" ]]; then
        die "--ow-key-file : fichier introuvable."
    fi
}
if [[ "$EXPLICIT_HEALTH" -eq 1 ]]; then
    validate_health_source
elif [[ -n "$OW_URL$OW_PROVIDER$OW_KEY_FILE_ARG" ]]; then
    die "--ow-url, --ow-provider et --ow-key-file s'utilisent avec --health-source openwearables."
fi

# Tableau de bord Docker : options vérifiées par resolve_dashboard_docker() (section dédiée, plus
# bas), au début de main(), avant tout travail.

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
    local file="$1" section="$2" name="$3" value="$4" template="${5:-}" union="${6:-}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} fusion de « $name » dans $file"
        return 0
    fi
    have python3 || { warn "python3 absent : $file non modifié (ajoutez « $name » à la main)."; return 0; }
    python3 "$PROJECT_ROOT/scripts/coach_config.py" merge-json \
        --file "$file" --section "$section" --name "$name" --value "$value" \
        ${template:+--template "$template"} ${union:+--union-lists} >/dev/null \
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

# Idem pour un dossier (scripts/, config/sports/) — un vrai dossier existant est
# conservé, avec $3 pour expliquer la conséquence.
link_dir() {
    local target="$1" link="$2" consequence="$3"
    [[ -d "$target" ]] || { warn "Cible introuvable, lien ignoré : $target"; return 0; }
    if [[ -e "$link" && ! -L "$link" ]]; then
        warn "$link existe et n'est pas un lien — conservé ; $consequence"
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
# Agents connus d'une installation antérieure à `[agents].known` : les quatre
# agents d'origine. Sans cette référence, un agent ajouté au moteur depuis
# (ex. sports-director) serait impossible à distinguer d'un agent retiré par
# l'athlète, et n'arriverait jamais chez les utilisateurs existants.
LEGACY_KNOWN_AGENTS="coach medical nutritionist course-strategist"

resolve_agents() {
    local available requested="" excluded="" name keep skip known
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
        # Mise à jour : un agent du moteur absent de `[agents].known` est
        # nouveau, il rejoint le staff (le défaut active tous les agents). Un
        # agent connu mais absent de `enabled` a été retiré : il le reste.
        if [[ -n "$requested" ]]; then
            known="$(python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
                --workspace "$WORKSPACE_ROOT" --section agents --key known 2>/dev/null | tr '\n' ' ')" \
                || known=""
            [[ -n "${known// /}" ]] || known="$LEGACY_KNOWN_AGENTS"
            for name in $available; do
                printf '%s\n' $known $requested | grep -qx "$name" && continue
                NEW_AGENTS="$NEW_AGENTS $name"
            done
            NEW_AGENTS="${NEW_AGENTS# }"
            [[ -z "$NEW_AGENTS" ]] || requested="$requested $NEW_AGENTS"
        fi
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
    if [[ -n "$NEW_AGENTS" ]]; then
        local without=""
        for name in $ENABLED_AGENTS; do
            printf '%s\n' $NEW_AGENTS | grep -qx "$name" || without="$without,$name"
        done
        ok "Nouvel agent activé : $NEW_AGENTS — pour le retirer : ./install.sh --agents ${without#,}"
    fi
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

# Détermine le mode de suivi du cycle (#166) : --cycle-tracking (explicite), sinon
# [health].cycle_tracking de la configuration EXISTANTE, sinon "off". Une valeur invalide
# EN CONFIG est traitée comme "off" avec un avertissement (jamais un échec : l'installation
# d'un athlète qui n'a rien demandé ne doit pas casser). Seul le mode "garmin" (avec la
# source Garmin) ajoute les outils get_menstrual_* à la liste blanche ; tout autre cas
# laisse GARMIN_TOOL_WHITELIST strictement inchangée — un rerun avec "off" en config la
# ramène donc à la liste par défaut (l'opt-in se retire comme il s'active).
resolve_cycle_tracking() {
    if [[ "$EXPLICIT_CYCLE" -eq 0 ]]; then
        CYCLE_TRACKING="off"
        if have python3; then
            local previous
            previous="$(python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
                --workspace "$WORKSPACE_ROOT" --section health --key cycle_tracking --default off 2>/dev/null)" \
                || previous="off"
            # Même tolérance que scripts/arc_cycle.py (casse et espaces ignorés) : sans elle, « Garmin »
            # serait « garmin » pour les agents mais « off » ici — outils appelés mais jamais exposés.
            previous="$(printf '%s' "$previous" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
            case "$previous" in
                off|garmin|intervals|manual) CYCLE_TRACKING="$previous" ;;
                "") ;;
                *) warn "[health].cycle_tracking = « $previous » invalide (off, garmin, intervals, manual) — traité comme « off »." ;;
            esac
        fi
    fi
    if [[ "$CYCLE_TRACKING" == "garmin" ]]; then
        if [[ "$SOURCE" == "garmin" ]]; then
            GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,$GARMIN_CYCLE_TOOLS"
            log "Suivi du cycle (opt-in) : outils get_menstrual_* ajoutés à la liste blanche garmin"
        else
            if [[ "$SOURCE" == "strava" ]]; then
                warn "cycle_tracking = garmin avec la source Strava : Strava n'expose aucune donnée de cycle — les agents retomberont sur « manual » (voir docs/cycle-menstruel.md)."
            else
                warn "cycle_tracking = garmin sans source Garmin : aucun outil à exposer — utilisez « intervals » (champ menstrualPhase) ou « manual » (voir docs/configuration.md)."
            fi
        fi
    elif [[ "$CYCLE_TRACKING" == "intervals" && "$SOURCE" != "intervals" ]]; then
        warn "cycle_tracking = intervals sans source intervals.icu : les agents retomberont sur la déclaration manuelle (voir docs/configuration.md)."
    fi
}

# Enregistre le mode de suivi du cycle — UNIQUEMENT si --cycle-tracking a été passé
# explicitement (un rerun, ou une installation par défaut, n'écrit jamais cette clé).
persist_cycle_tracking() {
    [[ "$EXPLICIT_CYCLE" -eq 1 ]] || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [health].cycle_tracking = $CYCLE_TRACKING"
        return 0
    fi
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section health --key cycle_tracking --value "$CYCLE_TRACKING" >/dev/null \
        || warn "Impossible d'écrire [health].cycle_tracking — vérifiez config/workspace.user.toml."
}

# Détermine la synchronisation nutrition (#167) : --nutrition-sync (explicite), sinon
# [nutrition].garmin_sync de la configuration EXISTANTE, sinon "off". Valeur invalide EN CONFIG =
# "off" + avertissement (jamais un échec). Seul "ask" (avec la source Garmin) ajoute les outils de
# nutrition/hydratation à la liste blanche ; tout autre cas la laisse strictement inchangée — un
# rerun avec "off" en config la ramène donc à la liste par défaut. Ne s'exécute qu'APRÈS
# resolve_cycle_tracking : les deux extensions s'ajoutent, sans se connaître.
resolve_nutrition_sync() {
    if [[ "$EXPLICIT_NUTRITION" -eq 0 ]]; then
        NUTRITION_SYNC="off"
        if have python3; then
            local previous
            previous="$(python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
                --workspace "$WORKSPACE_ROOT" --section nutrition --key garmin_sync --default off 2>/dev/null)" \
                || previous="off"
            # Même tolérance que scripts/arc_nutrition_sync.py (casse et espaces ignorés).
            previous="$(printf '%s' "$previous" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
            case "$previous" in
                off|ask) NUTRITION_SYNC="$previous" ;;
                "") ;;
                *) warn "[nutrition].garmin_sync = « $previous » invalide (off, ask) — traité comme « off »." ;;
            esac
        fi
    fi
    if [[ "$NUTRITION_SYNC" == "ask" ]]; then
        # Mode passerelle : `invoke_tool` est un outil unique, `scripts/daily-sync.sh` ne peut pas en
        # retirer les écritures nutrition par nom — seule une consigne protégerait alors le run
        # headless. On refuse donc d'exposer ces écritures derrière leanproxy (mode direct requis).
        if [[ "$USE_LEANPROXY" -eq 1 ]]; then
            if [[ "$EXPLICIT_NUTRITION" -eq 1 ]]; then
                die "--nutrition-sync ask est incompatible avec --use-leanproxy : les écritures Garmin ne peuvent pas y être interdites en headless. Utilisez le mode direct (voir docs/nutrition-garmin.md)."
            fi
            warn "[nutrition].garmin_sync = « ask » ignoré en mode passerelle leanproxy (écritures non filtrables en headless) — aucun outil nutrition exposé ; mode direct requis."
            return 0
        fi
        if [[ "$SOURCE" == "garmin" ]]; then
            GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,$GARMIN_NUTRITION_TOOLS"
            log "Synchronisation nutrition (opt-in) : outils de journal alimentaire et d'hydratation ajoutés à la liste blanche garmin"
        else
            # intervals.icu et Strava (#164) n'ont ni journal alimentaire ni hydratation : rien à pousser.
            warn "[nutrition].garmin_sync = « ask » indisponible avec [data].source = « $SOURCE » (journal alimentaire et hydratation propres à Garmin Connect) — aucun outil exposé (voir docs/nutrition-garmin.md)."
        fi
    fi
}

# Enregistre la synchronisation nutrition — UNIQUEMENT si --nutrition-sync a été passé
# explicitement (un rerun, ou une installation par défaut, n'écrit jamais cette clé).
persist_nutrition_sync() {
    [[ "$EXPLICIT_NUTRITION" -eq 1 ]] || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [nutrition].garmin_sync = $NUTRITION_SYNC"
        return 0
    fi
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section nutrition --key garmin_sync --value "$NUTRITION_SYNC" >/dev/null \
        || warn "Impossible d'écrire [nutrition].garmin_sync — vérifiez config/workspace.user.toml."
}

# ---------------------------------------------------------------------------
# Santé du bilan matinal : Open Wearables (#220, épopée #216) — opt-in strict
# ---------------------------------------------------------------------------
# On n'installe PAS Open Wearables (l'athlète le déploie lui-même) et on ne déclare AUCUN serveur MCP :
# le projet lit son API REST par scripts/arc_openwearables.py. install.sh pose seulement la configuration
# ([health].source, [health.openwearables]) et stocke la clé d'API hors dépôt, en mode 600, sans jamais
# l'afficher ni la passer en argument.

# Valeur d'une clé de [health.openwearables] dans la configuration effective (user > shared),
# imbriquée ou en section plate. Jamais utilisée pour la clé d'API elle-même.
ow_config_value() {
    have python3 || return 0
    python3 - "$PROJECT_ROOT/scripts" "$WORKSPACE_ROOT" "$1" <<'PYEOF' 2>/dev/null || true
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import coach_config
ws, key = Path(sys.argv[2]), sys.argv[3]
for path in coach_config.config_paths(ws):
    try:
        data = coach_config.read_toml(path)
    except Exception:
        continue
    nested = (data.get("health") or {}).get("openwearables")
    for sect in (nested, data.get("health.openwearables")):
        if isinstance(sect, dict) and key in sect:
            print(sect[key])
            raise SystemExit(0)
PYEOF
}

# Détermine la source santé effective (#220) : --health-source (explicite), sinon [health].source de la
# configuration EXISTANTE. Une valeur inconnue en config vaut « primary » (jamais un échec). Seul le
# cas explicite écrit quoi que ce soit ; un rerun sans option ne touche à rien.
resolve_health_source() {
    if [[ "$EXPLICIT_HEALTH" -eq 1 ]]; then
        HEALTH_EFFECTIVE="$HEALTH_SOURCE"
    else
        HEALTH_EFFECTIVE="primary"
        local previous
        previous="$(effective_value health source | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
        [[ "$previous" == "openwearables" ]] && HEALTH_EFFECTIVE="openwearables"
    fi
    if [[ "$HEALTH_EFFECTIVE" == "openwearables" ]]; then
        # Le récapitulatif et verify() citent l'URL et le fournisseur effectifs.
        [[ -n "$OW_URL" ]] || OW_URL="$(ow_config_value base_url)"
        [[ -n "$OW_PROVIDER" ]] || OW_PROVIDER="$(ow_config_value provider)"
        if [[ "$EXPLICIT_HEALTH" -eq 1 ]]; then
            [[ -n "$OW_URL" ]] || die "--health-source openwearables exige --ow-url (adresse de votre instance Open Wearables, ex. http://127.0.0.1:8000)."
            [[ -n "$OW_PROVIDER" ]] || die "--health-source openwearables exige --ow-provider (UN fabricant : $OW_PROVIDERS)."
            # Valeurs relues de la configuration : mêmes contrôles que sur la ligne de commande.
            check_ow_provider
            check_ow_url
        fi
    fi
}

# Enregistre la source santé — UNIQUEMENT si --health-source a été passé explicitement. « primary »
# remet seulement [health].source : ni l'URL, ni le fournisseur, ni la clé d'API ne sont supprimés.
persist_health_source() {
    [[ "$EXPLICIT_HEALTH" -eq 1 ]] || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [health].source = $HEALTH_SOURCE"
        if [[ "$HEALTH_SOURCE" == "openwearables" ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [health.openwearables].base_url = $OW_URL"
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [health.openwearables].provider = $OW_PROVIDER"
        fi
        return 0
    fi
    have python3 || return 0
    local set_cfg=(python3 "$PROJECT_ROOT/scripts/coach_config.py" set --workspace "$WORKSPACE_ROOT")
    "${set_cfg[@]}" --section health --key source --value "$HEALTH_SOURCE" >/dev/null \
        || warn "Impossible d'écrire [health].source — vérifiez config/workspace.user.toml."
    [[ "$HEALTH_SOURCE" == "openwearables" ]] || return 0
    "${set_cfg[@]}" --section health.openwearables --key base_url --value "$OW_URL" >/dev/null \
        || warn "Impossible d'écrire [health.openwearables].base_url — vérifiez config/workspace.user.toml."
    "${set_cfg[@]}" --section health.openwearables --key provider --value "$OW_PROVIDER" >/dev/null \
        || warn "Impossible d'écrire [health.openwearables].provider — vérifiez config/workspace.user.toml."
}

# Fichier de la clé d'API (mode 600, HORS dépôt) — jamais affichée, jamais en argument, jamais dans le
# workspace ni dans .mcp.json. Ordre : --ow-key-file (import explicite, remplace) > fichier déjà présent
# (conservé, jamais redemandé : un rerun ne touche pas à la clé) > saisie sans écho sur un terminal
# (sauf --no-auth) > avertissement avec la marche à suivre.
ensure_ow_key() {
    [[ "$HEALTH_EFFECTIVE" == "openwearables" ]] || return 0
    local key_file
    key_file="$(ow_config_value api_key_file)"
    [[ -n "$key_file" ]] || key_file="$OW_KEY_FILE_DEFAULT"
    key_file="${key_file/#\~/$HOME}"
    # Jamais dans le dépôt ni dans le workspace (donnée versionnable/synchronisée) : refus, même en dry-run.
    local key_abs root
    key_abs="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$key_file" 2>/dev/null)" || key_abs="$key_file"
    for root in "$PROJECT_ROOT" "$WORKSPACE_ROOT"; do
        if [[ "$key_abs" == "$root" || "$key_abs" == "$root"/* ]]; then
            die "[health.openwearables].api_key_file ($key_abs) est dans le dépôt ou le workspace : la clé d'API doit rester hors de l'un comme de l'autre (défaut : $OW_KEY_FILE_DEFAULT)."
        fi
    done
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} clé d'API Open Wearables : $key_file (mode 600, saisie sans écho ou --ow-key-file)"
        return 0
    fi
    local key=""
    if [[ -n "$OW_KEY_FILE_ARG" ]]; then
        key="$(tr -d '[:space:]' < "$OW_KEY_FILE_ARG" 2>/dev/null)" || key=""
        [[ -n "$key" ]] || die "--ow-key-file : fichier vide ou illisible."
    elif [[ -s "$key_file" ]]; then
        chmod 600 "$key_file" 2>/dev/null || true
        ok "Clé d'API Open Wearables : présente ($key_file, mode 600, valeur non affichée)"
        return 0
    elif [[ "$DO_AUTH" -eq 1 && -t 0 ]]; then
        printf '%s' "Clé d'API Open Wearables (saisie masquée, créée dans le portail OW) : " >&2
        IFS= read -r -s key || key=""
        printf '\n' >&2
        key="$(printf '%s' "$key" | tr -d '[:space:]')"
    fi
    if [[ -z "$key" ]]; then
        warn "Clé d'API Open Wearables absente : créez-la dans le portail OW puis relancez avec --ow-key-file FICHIER, ou écrivez-la dans $key_file (mode 600, une ligne, jamais dans le dépôt) — voir docs/open-wearables.md#installation."
        return 0
    fi
    ( umask 077; mkdir -p "$(dirname "$key_file")" )
    ( umask 077; printf '%s\n' "$key" > "$key_file.tmp.$$" ) \
        && chmod 600 "$key_file.tmp.$$" && mv -f "$key_file.tmp.$$" "$key_file" \
        || { rm -f "$key_file.tmp.$$"; die "Impossible d'écrire le fichier de clé Open Wearables ($key_file)."; }
    key=""
    ok "Clé d'API Open Wearables enregistrée : $key_file (mode 600, valeur non affichée)"
}

# Contrôle de joignabilité en fin d'installation : un seul appel `check` au client (valeurs jamais
# affichées). Un échec avertit, il n'interrompt jamais l'installation.
verify_openwearables() {
    [[ "$HEALTH_EFFECTIVE" == "openwearables" ]] || return 0
    [[ "$DRY_RUN" -eq 0 ]] || return 0
    have python3 || return 0
    local out rc=0
    out="$(python3 "$PROJECT_ROOT/scripts/arc_openwearables.py" --workspace "$WORKSPACE_ROOT" check --json --timeout 5 2>/dev/null)" || rc=$?
    if [[ "$rc" -eq 0 ]]; then
        local summary
        summary="$(printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("fournisseur %s connecté : %s ; forme conforme à Open Wearables %s : %s ; synchro périmée : %s" % (
    d.get("provider"), "oui" if d.get("provider_connected") else "non", d.get("tested_version"),
    "oui" if d.get("shape_ok") else "non", d.get("stale")))
' 2>/dev/null)" || summary=""
        ok "Open Wearables : joignable${summary:+ — $summary}"
    elif [[ "$rc" -eq 2 ]]; then
        warn "Open Wearables : configuration incomplète (clé d'API, fournisseur ou adresse) — lancez /coach-doctor ou voir docs/open-wearables.md#installation."
    else
        warn "Open Wearables : instance injoignable ou clé refusée — lancez /coach-doctor (docs/troubleshooting.md)."
    fi
}

# Enregistre le staff retenu dans la config personnelle, et les agents que le
# moteur fournit à cet instant (`[agents].known`) : à la prochaine mise à jour,
# seul un agent absent de cette liste sera considéré comme nouveau.
persist_agents() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [agents].enabled = $ENABLED_AGENTS"
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [agents].known = $(all_agents | tr '\n' ' ')"
        return 0
    fi
    have python3 || return 0
    local args=() known=() name
    for name in $ENABLED_AGENTS; do args+=(--list "$name"); done
    for name in $(all_agents); do known+=(--list "$name"); done
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section agents --key enabled "${args[@]}" >/dev/null \
        || warn "Impossible d'écrire [agents].enabled — vérifiez config/workspace.user.toml."
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section agents --key known "${known[@]}" >/dev/null \
        || warn "Impossible d'écrire [agents].known — vérifiez config/workspace.user.toml."
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
# /scripts et /config/sports sans « / » final : ce sont des liens, et un motif « dossier/ » ne couvre pas
# un lien symbolique — `git add -A` (git_autocommit) l'aurait versionné.
# *.bak : sauvegardes que install.sh et coach_config.py laissent à côté des fichiers.
WORKSPACE_IGNORES=(
    /agents/ /skills/ /scripts /AGENTS.md /config/workspace.toml /config/coaching-styles.md /config/sports
    config/workspace.user.toml
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
/config/coaching-styles.md
/config/sports
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
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} liens AGENTS.md, config/workspace.toml, config/coaching-styles.md, config/sports, scripts → moteur"
    else
        link_file "$PROJECT_ROOT/AGENTS.md" "$WORKSPACE_ROOT/AGENTS.md"
        link_file "$PROJECT_ROOT/config/workspace.toml" "$WORKSPACE_ROOT/config/workspace.toml"
        # Les agents lisent ces deux-là par chemin relatif ([coaching].style,
        # [sport].primary). config/plans/ et config/strength/ n'ont pas besoin de
        # lien : les scripts les résolvent depuis le moteur (Path(__file__).resolve()).
        link_file "$PROJECT_ROOT/config/coaching-styles.md" "$WORKSPACE_ROOT/config/coaching-styles.md"
        link_dir "$PROJECT_ROOT/config/sports" "$WORKSPACE_ROOT/config/sports" \
            "les agents n'y trouveront pas les profils de sport du moteur."
        # Les agents appellent `python3 scripts/arc_index.py …` depuis le workspace.
        link_dir "$PROJECT_ROOT/scripts" "$WORKSPACE_ROOT/scripts" \
            "les agents n'y trouveront pas les scripts du moteur."
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
# GHSA-wjhr-76vg-2hvc (garminconnect 0.3.2, version figée par garmin_mcp en amont ; correctif amont
# en 0.3.5, non validé par garmin_mcp) : le magasin de jetons OAuth (`garmin_tokens.json`, qui
# contient le jeton de rafraîchissement) peut être lisible par les autres comptes de la machine.
# `Client.dump()` écrit avec `write_text`, qui CONSERVE le mode d'un fichier existant : le umask ne
# joue qu'à la création. Les versions récentes de garmin-mcp-auth resserrent déjà le dossier (700)
# et les fichiers (600), mais des jetons créés par une version antérieure de garmin-mcp, par un
# autre outil ou par une connexion garminconnect directe restent parfois en 0644 (constaté sur une
# installation réelle). Ce resserrage est donc un FILET DE SÉCURITÉ de notre côté : dossier en 0700,
# fichiers réguliers en 0600 (on ne RETIRE que les droits groupe/autres ; `find -type f` ne suit
# aucun lien symbolique), ainsi que `~/.garminconnect_base64` (fichier régulier seulement) et
# l'éventuel dossier personnalisé `GARMINTOKENS` de l'entrée `garmin` de .mcp.json (ou de
# l'environnement). Idempotent, ne fait jamais échouer l'installation, sans effet si rien n'existe.
# Relancé par scripts/daily-sync.sh après chaque run (fichier recréé au umask par une
# reconnexion). Contrôlé par /coach-doctor (check `garmin_token_perms`).
garmin_token_dirs() {
    printf '%s\n' "$GARMIN_TOKENS_DIR"
    local custom
    custom="$(python3 -c '
import json, os, sys
try:
    value = json.load(open(sys.argv[1]))["mcpServers"]["garmin"]["env"]["GARMINTOKENS"]
except Exception:
    value = os.environ.get("GARMINTOKENS", "")
if isinstance(value, str) and value:
    print(os.path.expanduser(value))
' "$WORKSPACE_ROOT/.mcp.json" 2>/dev/null || true)"
    [[ -z "$custom" || "$custom" == "$GARMIN_TOKENS_DIR" ]] || printf '%s\n' "$custom"
}

restrict_garmin_tokens() {
    local d b64="$HOME/.garminconnect_base64"
    while IFS= read -r d; do
        [[ -n "$d" && -d "$d" && ! -L "$d" ]] || continue
        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} resserrage des droits de $d (dossier 700, jetons 600)"
            continue
        fi
        if chmod go-rwx "$d" 2>/dev/null; then
            find "$d" -type f -exec chmod go-rwx {} + 2>/dev/null || true
            ok "Jetons Garmin ($d) : accès réservé au propriétaire (GHSA-wjhr-76vg-2hvc)"
        else
            warn "Droits de $d non resserrés (voir /coach-doctor, check garmin_token_perms)."
        fi
    done < <(garmin_token_dirs)
    if [[ -f "$b64" && ! -L "$b64" && "$DRY_RUN" -eq 0 ]]; then
        chmod go-rwx "$b64" 2>/dev/null || true
    fi
    return 0
}

# Origine VCS de l'installation `uv tool` de garmin-mcp : « <url> <commit> » (vide si
# illisible). Même lecture que `intervals_installed_origin` (PEP 610, aucun réseau) ; le
# dist-info s'appelle `garmin_mcp-*.dist-info`.
garmin_installed_origin() {
    local exe env_dir
    exe="$(command -v garmin-mcp)" || return 0
    env_dir="$(dirname "$(dirname "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$exe")")")"
    python3 - "$env_dir" <<'PYEOF'
import glob, json, sys
for path in glob.glob(sys.argv[1] + "/lib/python*/site-packages/garmin_mcp-*.dist-info/direct_url.json"):
    try:
        info = json.load(open(path))
        print(info.get("url", ""), (info.get("vcs_info") or {}).get("commit_id", ""))
    except Exception:  # noqa: BLE001 — JSON illisible ou non-objet : ne rien afficher
        pass
    break
PYEOF
}

# Le pin GARMIN_MCP_REF n'était appliqué qu'à la première installation (« déjà installé »
# sautait tout) : une installation antérieure, non épinglée, garde donc des dépendances
# transitives périmées (`uv tool install` re-résout pyproject.toml, pas l'uv.lock amont) avec
# des avis de sécurité connus. Même mécanique que `upgrade_intervals_pin_if_needed` : réinstalle
# au commit épinglé, uniquement pour l'origine amont CONNUE ; une origine personnalisée n'est
# jamais écrasée. Les jetons de $GARMIN_TOKENS_DIR ne sont pas touchés.
upgrade_garmin_pin_if_needed() {
    local origin url commit want_url want_commit ref="${GARMIN_MCP_REF#git+}"
    want_url="${ref%@*}"
    want_commit="${ref##*@}"
    origin="$(garmin_installed_origin)"
    url="${origin%% *}"
    commit="${origin#* }"
    url="${url%/}"
    url="${url%.git}"
    if [[ -z "$origin" || -z "$url" ]]; then
        warn "Origine de l'installation garmin-mcp illisible — non mise à jour (voir /coach-doctor, check garmin_mcp_pin)."
        return 0
    fi
    if [[ "$url" != "$want_url" ]]; then
        warn "garmin-mcp installé depuis une origine personnalisée ($url) — laissé tel quel."
        return 0
    fi
    if [[ "$commit" == "$want_commit" ]]; then
        ok "garmin-mcp au commit épinglé (${want_commit:0:7})"
        return 0
    fi
    log "Réinstallation de garmin-mcp au commit épinglé du projet : ${commit:0:7} -> ${want_commit:0:7} (dépendances re-résolues ; jetons Garmin conservés)"
    run uv tool install --python 3.12 --force "$GARMIN_MCP_REF" \
        || warn "Mise à jour de garmin-mcp échouée — l'ancienne version reste en place (voir /coach-doctor)."
}

install_garmin_mcp() {
    log "Installation de garmin-mcp (accès Garmin Connect)"
    if have garmin-mcp; then
        # NB : pas de « garmin-mcp --version » — cela démarre le serveur stdio et bloque.
        ok "garmin-mcp déjà installé : $(command -v garmin-mcp)"
        upgrade_garmin_pin_if_needed
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
# `intervals-icu-mcp-auth` écrit le .env avec les droits par défaut (0644 : lisible par les
# autres comptes de la machine) — constaté au test d'intégration de #165. La clé API ne doit
# être lisible que par son propriétaire : on resserre à 0600 après l'authentification et à
# chaque relance (idempotent ; jamais en dry-run).
restrict_intervals_env() {
    local env_file="$INTERVALS_ENV_DIR/.env"
    [[ -f "$env_file" && "$DRY_RUN" -eq 0 ]] || return 0
    chmod 600 "$env_file" && ok "Droits du fichier d'identifiants Intervals.icu : 600"
}

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

# Origine VCS de l'installation `uv tool` en place : « <url> <commit> » (vide si
# illisible — installation locale, outil sans direct_url.json…). Source : le
# `direct_url.json` du dist-info (PEP 610), écrit par uv pour toute installation
# depuis un dépôt ; aucun réseau. Même lecture que scripts/coach_doctor.py
# (check `intervals_mcp_pin`).
intervals_installed_origin() {
    local exe env_dir
    exe="$(command -v intervals-icu-mcp)" || return 0
    env_dir="$(dirname "$(dirname "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$exe")")")"
    python3 - "$env_dir" <<'PYEOF'
import glob, json, sys
for path in glob.glob(sys.argv[1] + "/lib/python*/site-packages/intervals_icu_mcp-*.dist-info/direct_url.json"):
    try:
        info = json.load(open(path))
        print(info.get("url", ""), (info.get("vcs_info") or {}).get("commit_id", ""))
    except Exception:  # noqa: BLE001 — JSON illisible ou non-objet : ne rien afficher
        pass
    break
PYEOF
}

# #165 : une installation antérieure épinglée sur eddmann/intervals-icu-mcp (ou sur
# un ancien commit du fork) est remplacée par le pin courant — sans cela, `install.sh`
# la laisserait en place pour toujours (« déjà installé ») alors que les docs, les
# agents et les skills parlent les noms d'outils `icu_*` du fork. Uniquement pour
# les origines amont CONNUES : une installation locale/personnalisée (chemin, autre
# fork) n'est jamais écrasée.
upgrade_intervals_pin_if_needed() {
    local origin url commit want_url want_commit ref="${INTERVALS_MCP_REF#git+}"
    want_url="${ref%@*}"
    want_commit="${ref##*@}"
    origin="$(intervals_installed_origin)"
    url="${origin%% *}"
    commit="${origin#* }"
    # Même dépôt écrit autrement (`…/intervals-icu-mcp.git`, barre finale) : même origine.
    url="${url%/}"
    url="${url%.git}"
    if [[ -z "$origin" || -z "$url" ]]; then
        warn "Origine de l'installation intervals-icu-mcp illisible — non mise à jour (voir /coach-doctor, check intervals_mcp_pin)."
        return 0
    fi
    case "$url" in
        https://github.com/eddmann/intervals-icu-mcp|https://github.com/hhopke/intervals-icu-mcp) ;;
        *)
            warn "intervals-icu-mcp installé depuis une origine personnalisée ($url) — laissé tel quel."
            return 0 ;;
    esac
    if [[ "$url" == "$want_url" && "$commit" == "$want_commit" ]]; then
        ok "intervals-icu-mcp au commit épinglé (${want_commit:0:7})"
        return 0
    fi
    if [[ "$url" == "https://github.com/eddmann/intervals-icu-mcp" ]]; then
        log "Mise à jour de intervals-icu-mcp : ${url#https://github.com/}@${commit:0:7} -> ${want_url#https://github.com/}@${want_commit:0:7} (#165)"
        warn "Les outils du serveur sont désormais préfixés « icu_ » — ouvrez une NOUVELLE session de coaching après l'installation (docs/update.md)."
    else
        log "Réinstallation de intervals-icu-mcp au commit épinglé du projet : ${commit:0:7} -> ${want_commit:0:7}"
    fi
    run uv tool install --python 3.12 --force --with fitparse "$INTERVALS_MCP_REF" \
        || warn "Mise à jour de intervals-icu-mcp échouée — l'ancienne version reste en place (voir /coach-doctor)."
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
        upgrade_intervals_pin_if_needed
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
            restrict_intervals_env
        elif [[ "$DRY_RUN" -eq 1 ]]; then
            warn "Authentification Intervals.icu sautée (dry-run) — serait lancée dans $INTERVALS_ENV_DIR."
        else
            warn "Aucun identifiant trouvé dans $INTERVALS_ENV_DIR"
            warn "L'authentification interactive va démarrer : clé API (https://intervals.icu/settings,"
            warn "section « Developer ») + identifiant athlète (ex. i123456)."
            mkdir -p "$INTERVALS_ENV_DIR"
            (cd "$INTERVALS_ENV_DIR" && intervals-icu-mcp-auth) \
                || die "Échec de l'authentification Intervals.icu (voir le message ci-dessus)."
            restrict_intervals_env
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
    # cron/launchd (garmin-daily-sync) démarrent avec un PATH minimal, sans les Node.js
    # installés par nvm/fnm/asdf : le dossier de `npx` trouvé ICI est figé dans le wrapper
    # (devant le PATH hérité), sinon le serveur ne démarrerait qu'en session interactive.
    local node_dir="" node_path_line=""
    if have npx; then
        node_dir="$(cd "$(dirname "$(command -v npx)")" && pwd)"
        node_path_line="export PATH=$(printf '%q' "$node_dir"):\"\$PATH\""
    fi
    cat > "$wrapper" <<WRAPPER
#!/usr/bin/env bash
# Généré par install.sh (--source strava, #164). Les jetons Strava ne sont JAMAIS ici :
# le serveur les lit/écrit dans ~/.config/strava-mcp/config.json.
# npx -y télécharge la version épinglée depuis le registre npm au premier lancement (puis
# cache npm) : pas de vérification d'intégrité au-delà de celle de npm — voir docs/strava-setup.md.
set -euo pipefail
$node_path_line
cd "\$(dirname "\${BASH_SOURCE[0]}")"
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
    # Le runner headless partage ce fichier projet avec les autres CLI ; la
    # configuration globale OpenCode reste utile pour le fournisseur choisi.
    write_project_mcp_json
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
    install_claude_update_hook
}

# Hook SessionStart (nouvelles sessions seulement, pas les reprises) : si une release plus
# récente existe, arc_update_check.py --hook ajoute une ligne au contexte et Claude la
# mentionne une fois. Muet si à jour, hors ligne, en headless (ARC_HEADLESS) ou avec
# [update].check = false. Les hooks SessionStart de l'utilisateur restent ; une version
# antérieure du nôtre (moteur déplacé, options changées) est remplacée, jamais empilée.
# Chemins protégés par shlex.quote : la commande est interprétée par un shell.
install_claude_update_hook() {
    local settings="$WORKSPACE_ROOT/.claude/settings.json" value
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} hook SessionStart « nouvelle version » dans $settings"
        return 0
    fi
    have python3 || { warn "python3 absent : hook « nouvelle version » non installé."; return 0; }
    value="$(python3 -c 'import json, shlex, sys
cmd = "python3 " + shlex.quote(sys.argv[1] + "/scripts/arc_update_check.py") + " --hook --workspace " + shlex.quote(sys.argv[2])
print(json.dumps({"matcher": "startup", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}))' \
        "$PROJECT_ROOT" "$WORKSPACE_ROOT")"
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set-claude-hook --file "$settings" \
        --event SessionStart --marker "scripts/arc_update_check.py" --value "$value" >/dev/null \
        || die "Échec de la mise à jour de $settings (voir le message ci-dessus)."
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
    local dir="$WORKSPACE_ROOT/.gemini/commands" cfg="$WORKSPACE_ROOT/.gemini/settings.json"
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
    cleanup_stale_mcp_server "$cfg" mcpServers
    merge_json_key "$cfg" mcpServers "$(mcp_server_name)" "$(mcp_server_value)"
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
}

write_cursor_config() {
    log "Configuration Cursor"
    local cfg="$WORKSPACE_ROOT/.cursor/mcp.json" permissions="$WORKSPACE_ROOT/.cursor/cli.json"
    cleanup_stale_mcp_server "$cfg" mcpServers
    merge_json_key "$cfg" mcpServers "$(mcp_server_name)" "$(mcp_server_value)"
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
    # Refus des outils d'écriture de la source (`Mcp(serveur:outil)`, prioritaires sur
    # tout « allow ») : la synchronisation headless lance `cursor-agent --force`, qui
    # approuverait sinon une écriture Garmin/intervals.icu/Strava sans personne pour
    # confirmer. scripts/daily-sync.sh vérifie leur présence avant chaque run.
    # shellcheck source=scripts/lib/sync_tools.sh
    source "$PROJECT_ROOT/scripts/lib/sync_tools.sh"
    local server tool mcp_deny=""
    case "$SOURCE" in intervals|strava) server="$SOURCE" ;; *) server="garmin" ;; esac
    for tool in $(sync_write_tools "$server"); do
        mcp_deny+=",\"Mcp($server:$tool)\""
    done
    # Santé lue chez Open Wearables avec des activités Garmin (#220) : les outils santé Garmin sont refusés
    # aussi (une seule source santé par jour). Quand on revient à « primary », on retire ces seules entrées.
    local health_denied="" want_health_deny=0
    if [[ "$HEALTH_EFFECTIVE" == "openwearables" && "$server" == "garmin" ]]; then
        want_health_deny=1
    fi
    SYNC_DENY_GARMIN_HEALTH=1
    health_denied="$(sync_health_denied_tools garmin | tr '\n' ' ')"
    SYNC_DENY_GARMIN_HEALTH=0
    if [[ "$want_health_deny" -eq 1 ]]; then
        for tool in $health_denied; do
            mcp_deny+=",\"Mcp(garmin:$tool)\""
        done
    fi
    # Fusion par listes : les règles allow/deny ajoutées par l'utilisateur sont conservées.
    merge_json_key "$permissions" "" permissions \
        '{"allow":["Read(**)","Write(activities/**)","Write(medical/**)","Write(nutrition/**)","Write(planning/**)","Write(rapports/**)","Write(gear/**)","Shell(python3)"],"deny":["Write(scripts/**)","Write(skills/**)","Write(local/**)","Write(config/**)","Write(.mcp.json)","Write(.cursor/**)","Write(.github/**)","Write(.gemini/**)","Write(.claude/**)","Write(.opencode/**)","Write(install.sh)","Read(**/.env*)","Shell(rm)","Shell(git)","Shell(gh)"'"$mcp_deny"']}' \
        "" union
    if [[ "$want_health_deny" -eq 0 && "$DRY_RUN" -eq 0 && -f "$permissions" ]] && have python3; then
        python3 - "$permissions" "$health_denied" <<'PYEOF' || warn "Impossible de retirer les refus santé Garmin de $permissions."
import json, sys
path, tools = sys.argv[1], sys.argv[2].split()
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
deny = (data.get("permissions") or {}).get("deny")
if isinstance(deny, list):
    drop = {"Mcp(garmin:%s)" % t for t in tools}
    kept = [d for d in deny if d not in drop]
    if len(kept) != len(deny):
        data["permissions"]["deny"] = kept
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
PYEOF
    fi
    ok "Permissions Cursor limitées aux données du coach ($permissions)"
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
# 6c. Exécuteurs headless — machine « coach »
# ---------------------------------------------------------------------------
# Les fonctionnalités mobiles reposent sur les CLI officiels (abonnement, pas de
# clé API). On ne les installe pas à la place de l'utilisateur : on vérifie et
# on affiche la commande officielle.
check_runners() {
    local runner
    runner="${SYNC_RUNNER_ARG:-$(ARC_WORKSPACE="$WORKSPACE_ROOT" bash -c 'source "$0/scripts/lib/config.sh"; toml_get sync runner claude' "$PROJECT_ROOT")}"
    case "$runner" in
        claude) have claude && ok "claude : présent ($(claude --version 2>/dev/null | head -1))" \
            || warn "claude absent — lancez l'installation guidée puis connectez le compte une fois." ;;
        codex) have codex && ok "codex : présent ($(codex --version 2>/dev/null | head -1))" \
            || warn "codex absent — installez Codex CLI puis connectez le compte une fois." ;;
        copilot) have copilot && ok "copilot : présent ($(copilot --version 2>/dev/null | head -1))" \
            || warn "copilot absent — lancez l'installation guidée puis connectez GitHub une fois." ;;
        opencode) have opencode && ok "opencode : présent ($(opencode --version 2>/dev/null | head -1))" \
            || warn "opencode absent — lancez l'installation guidée puis configurez le fournisseur une fois." ;;
        gemini) have gemini && ok "gemini : présent ($(gemini --version 2>/dev/null | head -1))" \
            || warn "gemini absent — lancez l'installation guidée puis connectez Google une fois." ;;
        cursor) have cursor-agent && ok "cursor-agent : présent ($(cursor-agent --version 2>/dev/null | head -1))" \
            || warn "cursor-agent absent — lancez l'installation guidée puis connectez Cursor une fois." ;;
    esac
    # Remote Control repose sur Claude Code quel que soit l'exécuteur de synchronisation.
    if [[ "$REMOTE_CONTROL" -eq 1 && "$runner" != "claude" ]] && ! have claude; then
        warn "claude absent — requis pour --remote-control : curl -fsSL https://claude.ai/install.sh | bash   (puis 'claude' → /login)"
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
    log "Synchronisation automatique $(data_source) (scripts/daily-sync.sh)"
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

# Une installation antérieure existe-t-elle ? Options mémorisées, planificateur de la sync (cron ou
# launchd) ou exécuteur de sync déjà choisi. Sert à ne JAMAIS déplacer en silence la synchronisation
# d'un utilisateur existant (même sur l'exécuteur par défaut « claude »).
prior_install_state() {
    [[ -e "$(dirname "$WORKSPACE_STATE_FILE")/install-args" ]] && return 0
    [[ -e "$HOME/Library/LaunchAgents/com.ai-running-coach.daily-sync.plist" ]] && return 0
    if have crontab && crontab -l 2>/dev/null | grep -q "daily-sync.sh"; then return 0; fi
    user_toml_value sync runner >/dev/null 2>&1 && return 0
    return 1
}

# Abonnement ChatGPT / Copilot (#266) : chat + sync via OpenCode, sans clé, magasin d'authentification dédié.
persist_llm_subscription() {
    local chat_model sync_model plan
    case "$LLM_PROVIDER" in
        chatgpt) chat_model="${LLM_MODEL_ARG:-$LLM_CHATGPT_CHAT_MODEL}"; sync_model="$LLM_CHATGPT_SYNC_MODEL"; plan="ChatGPT Plus ou Pro" ;;
        copilot) chat_model="${LLM_MODEL_ARG:-$LLM_COPILOT_CHAT_MODEL}"; sync_model="$LLM_COPILOT_SYNC_MODEL"; plan="GitHub Copilot" ;;
    esac
    local prefix="openai"
    [[ "$LLM_PROVIDER" != "copilot" ]] || prefix="github-copilot"
    [[ "$chat_model" == "$prefix"/* ]] || chat_model="$prefix/$chat_model"
    log "Chat et synchronisation sur votre abonnement $plan (aucune clé API ; magasin d'authentification : $LLM_OPENCODE_DATA_DIR)"
    llm_set chat backend "opencode"
    llm_set chat model "$chat_model"
    llm_set chat base_url ""
    llm_set chat api_key_env ""
    llm_set chat opencode_data_dir "$LLM_OPENCODE_DATA_DIR"
    # Synchronisation : sur l'abonnement SEULEMENT si l'athlète le demande (--sync-subscription) ou si
    # rien n'était configuré (installation neuve). Aucune déclaration officielle n'autorise un usage
    # planifié sans surveillance d'un forfait grand public : on ne bascule pas un exécuteur existant
    # (facturation, abonnement Claude…) en silence.
    local sync_on_plan=0
    if [[ "$SYNC_SUBSCRIPTION" -eq 1 ]] || { [[ "$SYNC_SUBSCRIPTION" -eq 0 ]] && ! prior_install_state; }; then
        sync_on_plan=1
    fi
    if [[ "$sync_on_plan" -eq 1 ]]; then
        llm_set sync runner "opencode"
        llm_set sync model "$sync_model"
        llm_set sync base_url ""
        llm_set sync api_key_env ""
        llm_set sync opencode_data_dir "$LLM_OPENCODE_DATA_DIR"
    else
        log "Synchronisation automatique inchangée (exécuteur actuel : $(effective_value sync runner)). Pour la mettre aussi sur votre abonnement : ./install.sh --llm $LLM_PROVIDER --sync-subscription (elle consommera les limites de votre forfait ; aucune déclaration officielle n'autorise l'usage planifié sans surveillance, voir docs/choisir-son-ia.md)."
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} $LLM_OPENCODE_DATA_DIR (mode 700, magasin d'authentification OpenCode)"
    else
        ( umask 077; mkdir -p "$LLM_OPENCODE_DATA_DIR" ) && chmod 700 "$LLM_OPENCODE_DATA_DIR" 2>/dev/null \
            || warn "Impossible de créer $LLM_OPENCODE_DATA_DIR (mode 700)."
    fi
    if have opencode; then
        ok "opencode : présent ($(opencode --version 2>/dev/null | head -1))"
    else
        warn "opencode absent — requis par le runner de sync et le chat sur $plan :"
        warn "  curl -fsSL https://opencode.ai/v2/install | bash   (ou : npm i -g opencode-ai ; brew install anomalyco/tap/opencode)"
    fi
    if [[ -n "${OPENCODE_DISABLE_DEFAULT_PLUGINS:-}" ]]; then
        warn "OPENCODE_DISABLE_DEFAULT_PLUGINS est défini dans cet environnement : OpenCode n'y charge pas la connexion $plan — retirez-le."
    fi
    if [[ "$LLM_PROVIDER" == "chatgpt" ]]; then
        warn "Forfaits acceptés : ChatGPT Plus ou Pro (l'offre Free est refusée par OpenAI avec « usage_not_included »). Les limites de votre forfait s'appliquent ; la sync automatique les consomme aussi."
    else
        warn "Forfaits acceptés : Copilot Pro, Pro+, Business, Enterprise (Copilot Free n'est pas pris en charge). Les crédits de votre forfait s'appliquent ; la sync automatique les consomme aussi."
    fi
    if ! have python3 || ! python3 "$PROJECT_ROOT/scripts/arc_llm.py" auth-status "$LLM_PROVIDER" --data-dir "$LLM_OPENCODE_DATA_DIR" >/dev/null 2>&1; then
        warn "Pas encore connecté : lancez « python3 $(printf '%q' "$PROJECT_ROOT/scripts/arc_llm.py") login $LLM_PROVIDER --data-dir $(printf '%q' "$LLM_OPENCODE_DATA_DIR") » une fois (ou relancez avec --connect). Ni la sync ni le chat ne lancent de connexion toute seuls."
    fi
}

persist_llm() {
    [[ -n "$LLM_PROVIDER" ]] || return 0
    note_free_trial_leftover
    case "$LLM_PROVIDER" in
        chatgpt|copilot) persist_llm_subscription; return 0 ;;
    esac
    local chat_backend chat_model sync_runner sync_model key_var base_url="$LLM_BASE_URL_ARG"
    case "$LLM_PROVIDER" in
        openrouter)
            chat_backend="opencode"; sync_runner="opencode"
            chat_model="${LLM_MODEL_ARG:-$LLM_OPENROUTER_MODEL}"
            [[ "$chat_model" == openrouter/* ]] || chat_model="openrouter/$chat_model"
            sync_model="$chat_model"; key_var="OPENROUTER_API_KEY" ;;
        openrouter-free)
            # Même clé, même connexion, même backend qu'openrouter ; seul le modèle (« :free ») change (#267).
            chat_backend="opencode"; sync_runner="opencode"
            chat_model="${LLM_MODEL_ARG:-$LLM_OPENROUTER_FREE_MODEL}"
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
    # Quitter un abonnement : le magasin dédié n'a plus lieu d'être (écrit « ancien → nouveau »).
    # Seulement s'il était posé : un --llm ordinaire n'ajoute jamais cette clé.
    [[ -z "$(effective_value chat opencode_data_dir)" ]] || llm_set chat opencode_data_dir ""
    [[ -z "$(effective_value sync opencode_data_dir)" ]] || llm_set sync opencode_data_dir ""
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
            warn "Le chat avec le backend claude a besoin du SDK Python : pip install -U 'claude-agent-sdk>=0.2.121' (Python 3.10+ ; versions antérieures : GHSA-h4mw-j7qp-8mwm)."
        fi
    elif have opencode; then
        ok "opencode : présent ($(opencode --version 2>/dev/null | head -1))"
    else
        warn "opencode absent — requis par le runner de sync et le chat sur $LLM_PROVIDER :"
        warn "  curl -fsSL https://opencode.ai/v2/install | bash   (ou : npm i -g opencode-ai ; brew install anomalyco/tap/opencode)"
    fi
    if [[ "$LLM_PROVIDER" == "openrouter" ]]; then
        warn "Santé : limitez les fournisseurs OpenRouter à ceux qui ne conservent ni n'entraînent sur vos données (docs/mobile.md)."
    fi
    if [[ "$LLM_PROVIDER" == "openrouter-free" ]]; then
        persist_llm_free_trial
    fi
}

# Essai gratuit (#267) : dit le coût, les limites et la confidentialité, et propose la sync en mode
# « watch » (sans jamais écraser un [sync].mode déjà posé par l'athlète dans workspace.user.toml).
persist_llm_free_trial() {
    log "Essai gratuit OpenRouter : modèle $(effective_value chat model) — 0 € (aucun budget en euros)."
    warn "Quota : 50 requêtes par jour sans achat de crédits (1 000 après 10 \$ achetés au total), 20 par minute. Un /log en consomme 17 à 48, un /week 6 à 12, un bilan 4 à 9 (mesuré) : environ un /log et quelques questions par jour sans achat."
    warn "CONFIDENTIALITÉ : selon les pages de modèles d'OpenRouter (à vérifier), les modèles gratuits peuvent conserver vos prompts, et NVIDIA déclare s'entraîner dessus. N'y mettez pas de données de santé sensibles ; réglages : https://openrouter.ai/settings/privacy. Alternatives payantes : DeepSeek (≈ 0,80 €/mois, --llm openrouter) ou « 10 \$ une fois » (1 000 requêtes gratuites par jour)."
    warn "Si vous refusez les fournisseurs qui s'entraînent sur vos données, le modèle par défaut (NVIDIA) devient inutilisable (erreur 404) ; certains modèles gratuits (Gemma 4 sur le compte utilisé pour nos essais) répondent aussi 404 avec ZDR : voir docs/choisir-son-ia.md#essai-gratuit."
    if user_toml_value sync mode >/dev/null 2>&1; then
        log "[sync].mode déjà posé dans workspace.user.toml : inchangé ($(effective_value sync mode))."
    elif [[ "$(data_source)" != "garmin" ]]; then
        log "Sync : le mode « watch » n'existe que pour [data].source = \"garmin\" — heures fixes conservées ([sync].times), donc quelques requêtes gratuites par passage."
    elif ! have python3 && [[ "$DRY_RUN" -eq 0 ]]; then
        warn "python3 absent : [sync].mode n'a pas pu être écrit (ajoutez mode = \"watch\" dans config/workspace.user.toml pour ménager le quota)."
    else
        log "Sync en mode « watch » proposé par défaut avec l'essai gratuit (LLM seulement s'il y a du neuf, pour ménager le quota) : [sync].mode = \"watch\". Pour revenir : mettez mode = \"schedule\" dans config/workspace.user.toml."
        llm_set sync mode "watch"
        # daily-sync.sh ne lit pas [sync].mode : c'est le planificateur (cron/launchd) qui change. S'il est déjà
        # installé, on le réinstalle (install_daily_sync est idempotent : lignes marquées remplacées, sauvegarde
        # de la crontab) ; sinon la prochaine installation du planificateur en tiendra compte.
        if [[ "$DAILY_SYNC" -eq 1 && "$DRY_RUN" -eq 1 ]]; then
            log "Aperçu : [sync].mode n'est écrit que par le vrai lancement, qui installera alors le planificateur en mode watch (le détail ci-dessous montre les heures fixes)."
        elif [[ "$DAILY_SYNC" -eq 0 && "$EXPLICIT_DAILY_SYNC" -eq 1 ]]; then
            log "--no-daily-sync : planificateur non touché ; [sync].mode = \"watch\" s'appliquera à sa prochaine installation (./install.sh --daily-sync)."
        elif [[ "$DAILY_SYNC" -eq 0 ]]; then
            if scheduler_installed; then
                if [[ "$DRY_RUN" -eq 1 ]]; then
                    log "Planificateur de la sync déjà installé : il serait réinstallé pour appliquer le mode watch."
                else
                    log "Planificateur de la sync déjà installé : réinstallation pour appliquer le mode watch."
                    DAILY_SYNC=1
                fi
            else
                log "Aucun planificateur de sync installé : le mode watch s'appliquera avec ./install.sh --daily-sync."
            fi
        fi
    fi
}

# Le planificateur de la sync (launchd sous macOS, crontab ailleurs) est-il déjà installé ? Lecture seule.
scheduler_installed() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        [[ -f "$HOME/Library/LaunchAgents/com.ai-running-coach.daily-sync.plist" ]]
    else
        crontab -l 2>/dev/null | grep -qF "# ai-running-coach daily-sync"
    fi
}

# Changement de fournisseur après l'essai gratuit : [sync].mode posé par lui reste en place (jamais réécrit).
note_free_trial_leftover() {
    [[ "$LLM_PROVIDER" != "openrouter-free" ]] || return 0
    case "$(effective_value sync model)" in *:free) ;; *) return 0 ;; esac
    if [[ "$(effective_value sync mode)" == "watch" ]] && user_toml_value sync mode >/dev/null 2>&1; then
        log "[sync].mode reste « watch » (posé par l'essai gratuit) ; mettez mode = \"schedule\" dans config/workspace.user.toml pour revenir aux heures fixes."
    fi
}

# --connect avec un abonnement (#266) : « arc_llm.py login chatgpt|copilot » dans le magasin du coach.
# Jamais en --dry-run ni sans terminal (le code d'appareil suppose l'athlète présent).
connect_llm_subscription() {
    local cmd
    cmd="python3 $(printf '%q' "$PROJECT_ROOT/scripts/arc_llm.py") login $LLM_PROVIDER --data-dir $(printf '%q' "$LLM_OPENCODE_DATA_DIR")"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} $cmd (adresse et code d'appareil à valider dans votre navigateur ; jeton gardé par OpenCode dans le magasin du coach)"
        return 0
    fi
    if [[ ! -t 0 || ! -t 1 ]]; then
        warn "--connect demande un terminal interactif : lancez ensuite « $cmd »."
        return 0
    fi
    have python3 || { warn "python3 absent : impossible de lancer la connexion."; return 0; }
    log "Connexion à votre compte ($LLM_PROVIDER)"
    python3 "$PROJECT_ROOT/scripts/arc_llm.py" login "$LLM_PROVIDER" --data-dir "$LLM_OPENCODE_DATA_DIR" \
        || warn "Connexion non terminée : relancez « $cmd »."
}

# --connect : connexion OpenRouter en un clic (arc_llm.py), en TOUT DERNIER (navigateur et saisie
# du code supposent l'athlète présent ; le reste de l'installation ne l'attend pas). Jamais en
# --dry-run, jamais sans terminal. Le service du chat lit llm.env au démarrage : redémarré après succès.
connect_llm() {
    [[ "$LLM_CONNECT" -eq 1 ]] || return 0
    if [[ "$LLM_PROVIDER" == "chatgpt" || "$LLM_PROVIDER" == "copilot" ]]; then
        connect_llm_subscription
        return 0
    fi
    local script="$PROJECT_ROOT/scripts/arc_llm.py" port
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} python3 $(printf '%q' "$script") connect openrouter (ouvre le navigateur ; clé écrite dans $LLM_ENV_FILE)"
        return 0
    fi
    if [[ ! -t 0 || ! -t 1 ]]; then
        warn "--connect demande un terminal interactif : lancez ensuite « python3 $(printf '%q' "$script") connect openrouter » (ajoutez --headless sur une machine sans navigateur)."
        return 0
    fi
    have python3 || { warn "python3 absent : impossible de lancer la connexion OpenRouter."; return 0; }
    log "Connexion à OpenRouter (navigateur)"
    if ARC_LLM_ENV="$LLM_ENV_FILE" python3 "$script" connect openrouter; then
        port="$(effective_value chat port)"
        if [[ "$DO_CHAT" -eq 1 ]] || { [[ "$(effective_value chat enabled)" == "true" ]] && have curl \
            && curl -fsS --max-time 3 "http://127.0.0.1:${port:-8766}/api/chat/healthz" >/dev/null 2>&1; }; then
            log "Redémarrage du chat pour qu'il lise la nouvelle clé"
            ARC_WORKSPACE="$WORKSPACE_ROOT" "$PROJECT_ROOT/scripts/coach-chat.sh" restart \
                || warn "Redémarrage du chat impossible : relancez scripts/coach-chat.sh restart."
        fi
    else
        warn "Connexion OpenRouter non terminée : relancez « python3 $(printf '%q' "$script") connect openrouter » ou collez la clé dans $(printf '%q' "$LLM_ENV_FILE")."
    fi
}

persist_budgets() {
    [[ -z "$CHAT_BUDGET" ]] || llm_set chat daily_budget_eur "$CHAT_BUDGET" float
    [[ -z "$SYNC_BUDGET" ]] || llm_set sync daily_budget_eur "$SYNC_BUDGET" float
}

persist_sync_runner() {
    [[ -z "$SYNC_RUNNER_ARG" ]] || llm_set sync runner "$SYNC_RUNNER_ARG"
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
        log "Modèle et clé du chat : voir [chat] (ou relancez avec --llm openrouter|openrouter-free|anthropic|openai|chatgpt|copilot)."
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        ARC_WORKSPACE="$WORKSPACE_ROOT" ARC_DRY_RUN=1 "$PROJECT_ROOT/scripts/coach-chat.sh" install --dry-run
    else
        ARC_WORKSPACE="$WORKSPACE_ROOT" "$PROJECT_ROOT/scripts/coach-chat.sh" install
    fi
}

# Fichier du jeton Telegram : créé (mode 600) avec une ligne d'exemple COMMENTÉE si absent ;
# on n'y écrit jamais de jeton, on n'en affiche jamais.
ensure_telegram_env() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} $TELEGRAM_ENV_FILE (mode 600, variable TELEGRAM_BOT_TOKEN)"
        return 0
    fi
    if [[ ! -f "$TELEGRAM_ENV_FILE" ]]; then
        mkdir -p "$(dirname "$TELEGRAM_ENV_FILE")"
        ( umask 077; cat > "$TELEGRAM_ENV_FILE" <<'EOF'
# Jeton du bot Telegram (BotFather) — mode 600, jamais versionné, jamais dans le TOML.
# Une ligne NOM=valeur sans espace autour du « = ». Décommentez et complétez :
# TELEGRAM_BOT_TOKEN=
EOF
        )
        ok "Fichier du jeton créé : $TELEGRAM_ENV_FILE (mode 600)"
    else
        chmod 600 "$TELEGRAM_ENV_FILE" 2>/dev/null || true
        if ! grep -qE "^[[:space:]]*(export[[:space:]]+)?#?[[:space:]]*TELEGRAM_BOT_TOKEN=" "$TELEGRAM_ENV_FILE"; then
            printf '# TELEGRAM_BOT_TOKEN=\n' >> "$TELEGRAM_ENV_FILE"
        fi
    fi
    if grep -qE "^[[:space:]]*(export[[:space:]]+)?TELEGRAM_BOT_TOKEN=.+" "$TELEGRAM_ENV_FILE"; then
        ok "Jeton TELEGRAM_BOT_TOKEN présent (valeur non affichée)"
    else
        warn "Jeton absent : créez un bot avec @BotFather (docs/telegram.md) puis ajoutez TELEGRAM_BOT_TOKEN=<jeton> dans $TELEGRAM_ENV_FILE (mode 600, jamais dans le TOML)."
    fi
}

# Ajoute $TELEGRAM_CHAT_ID à [telegram].allowed_chat_ids sans jamais retirer ni remplacer
# un identifiant déjà autorisé.
add_telegram_chat_id() {
    [[ -n "$TELEGRAM_CHAT_ID" ]] || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [telegram].allowed_chat_ids += $TELEGRAM_CHAT_ID"
        return 0
    fi
    have python3 || return 0
    local current args=() id
    current="$(effective_value telegram allowed_chat_ids)"
    while IFS= read -r id; do
        [[ -n "$id" ]] || continue
        args+=(--list "$id")
    done <<< "$current"
    if printf '%s\n' "$current" | grep -qxF -- "$TELEGRAM_CHAT_ID"; then
        ok "Chat $TELEGRAM_CHAT_ID déjà autorisé"
        return 0
    fi
    args+=(--list "$TELEGRAM_CHAT_ID")
    python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
        --workspace "$WORKSPACE_ROOT" --section telegram --key allowed_chat_ids "${args[@]}" >/dev/null \
        && ok "Chat $TELEGRAM_CHAT_ID ajouté à [telegram].allowed_chat_ids" \
        || warn "Impossible d'écrire [telegram].allowed_chat_ids — vérifiez config/workspace.user.toml."
}

install_telegram() {
    [[ "$DO_TELEGRAM" -eq 1 ]] || return 0
    log "Bot Telegram (scripts/coach-telegram.sh install)"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [telegram].enabled = true"
    else
        have python3 && python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
            --workspace "$WORKSPACE_ROOT" --section telegram --key enabled --value true --type bool >/dev/null \
            || warn "Impossible d'écrire [telegram].enabled — vérifiez config/workspace.user.toml."
    fi
    add_telegram_chat_id
    ensure_telegram_env
    if [[ "$(effective_value telegram chat_bridge)" == "true" ]]; then
        log "Conversation libre activée : elle exige [chat].enabled = true et une clé d'API facturée (docs/telegram.md)."
    else
        log "Retours en un geste uniquement (sans clé d'API) ; la conversation libre est opt-in : [telegram].chat_bridge."
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        ARC_WORKSPACE="$WORKSPACE_ROOT" ARC_DRY_RUN=1 "$PROJECT_ROOT/scripts/coach-telegram.sh" install --dry-run
    else
        ARC_WORKSPACE="$WORKSPACE_ROOT" "$PROJECT_ROOT/scripts/coach-telegram.sh" install
    fi
}

# ---------------------------------------------------------------------------
# Tableau de bord en conteneur Docker (--dashboard-docker) — opt-in
# ---------------------------------------------------------------------------
# install.sh génère son propre compose ($DASH_DIR/compose.yaml, projet « arc-dashboard ») et lance
# le conteneur (« up -d » : l'image n'est construite que si elle n'existe pas). Il ne la reconstruit
# JAMAIS : c'est /update-coach (scripts/update-coach.sh) qui le fait, après une mise à jour du
# moteur — l'image a alors la version du moteur. État dans [dashboard]
# (docker, docker_host, docker_auth, docker_network, docker_entrypoint) de workspace.user.toml.
# Sans configuration, la question n'est posée qu'en terminal, Docker joignable ; la réponse
# (même « non ») est mémorisée : elle n'est jamais reposée. Sans Docker : rien, aucune mention.
#
# Exposition : « local » publie 127.0.0.1:<[dashboard].port> seulement ; « traefik » ne publie
# aucun port et passe par le Traefik qui tourne sur la machine. Un middleware d'authentification
# est exigé, SAUF si Traefik ne publie ses ports que sur la boucle locale (rien n'est alors
# joignable hors de la machine) — même garantie que deploy/dashboard/compose.yaml.

docker_ready() {
    have docker && docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

# Nom du premier conteneur Traefik en cours (image « traefik », « traefik:v3 », « x/traefik »…).
traefik_container() {
    docker ps --format '{{.Names}}	{{.Image}}' 2>/dev/null \
        | awk -F'\t' '$2 ~ /(^|\/)traefik([:@]|$)/ { print $1; exit }'
}

# Arguments de lancement de Traefik, un par ligne (configuration en ligne de commande).
traefik_args() {
    docker inspect -f '{{range .Args}}{{println .}}{{end}}' "$1" 2>/dev/null || true
}

# Réseau Docker de Traefik : --providers.docker.network, sinon son premier réseau utilisateur.
traefik_network() {
    local net
    net="$(traefik_args "$1" | sed -n 's/^--providers\.docker\.network=//p' | head -n1)"
    [[ -n "$net" ]] || net="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$1" 2>/dev/null \
        | grep -v -E '^(bridge|host|none)?$' | head -n1 || true)"
    printf '%s' "$net"
}

# Points d'entrée Traefik déclarés en ligne de commande, un par ligne.
traefik_entrypoints() {
    traefik_args "$1" | sed -n 's/^--entrypoints\.\([^.=]*\)\.address=.*/\1/p'
}

# Vrai si Traefik ne publie ses ports QUE sur la boucle locale (et en publie au moins un).
traefik_loopback_only() {
    local ports
    ports="$(docker port "$1" 2>/dev/null || true)"
    [[ -n "$ports" ]] || return 1
    ! printf '%s\n' "$ports" | grep -v -E -- '-> (127\.[0-9.]+|\[::1\]):[0-9]+$' | grep -q .
}

# Fuseau horaire de l'hôte (il fixe « aujourd'hui » dans le conteneur).
host_timezone() {
    local tz="${TZ:-}"
    [[ -n "$tz" ]] || tz="$(cat /etc/timezone 2>/dev/null || true)"
    [[ -n "$tz" ]] || tz="$(readlink /etc/localtime 2>/dev/null | sed -n 's|.*/zoneinfo/||p')"
    printf '%s' "${tz:-UTC}"
}

dashboard_config_value() {
    have python3 || return 0
    python3 "$PROJECT_ROOT/scripts/coach_config.py" get \
        --workspace "$WORKSPACE_ROOT" --section dashboard --key "$1" --default "" 2>/dev/null || true
}

validate_dashboard_docker() {
    case "$DASH_DOCKER" in
        off|local|traefik) ;;
        *) die "Mode de tableau de bord Docker inconnu : « $DASH_DOCKER ». Valides : off, local, traefik (voir --help)." ;;
    esac
    if [[ "$DASH_DOCKER" != "traefik" && -n "$DASH_HOST$DASH_AUTH" ]]; then
        die "--dashboard-host et --dashboard-auth s'utilisent avec --dashboard-docker traefik."
    fi
    [[ -z "$DASH_HOST" || "$DASH_HOST" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
        || die "--dashboard-host : nom d'hôte attendu (ex. coach.localhost), sans schéma ni port."
    [[ -z "$DASH_AUTH" || "$DASH_AUTH" =~ ^[A-Za-z0-9._@-]+$ ]] \
        || die "--dashboard-auth : nom de middleware Traefik attendu (ex. authentik@file)."
}

# Pose une question (terminal uniquement) ; $2 = réponse par défaut.
ask() {
    local answer
    read -r -p "$1 " answer || answer=""
    printf '%s' "${answer:-$2}"
}

# Complète la configuration Traefik (réseau, point d'entrée, authentification). En terminal, demande
# ce qui manque ; sinon, échoue avec la commande à lancer. $1 = 1 si les questions sont permises.
resolve_dashboard_traefik() {
    local interactive="$1" traefik eps
    traefik="$(traefik_container)"
    if [[ -z "$traefik" ]]; then
        die "--dashboard-docker traefik : aucun conteneur Traefik en cours. Démarrez Traefik, ou utilisez --dashboard-docker local."
    fi
    [[ -n "$DASH_NETWORK" ]] || DASH_NETWORK="$(traefik_network "$traefik")"
    [[ -n "$DASH_NETWORK" ]] \
        || die "Réseau Docker de Traefik introuvable : renseignez [dashboard].docker_network dans config/workspace.user.toml."
    if [[ -z "$DASH_ENTRYPOINT" ]]; then
        eps="$(traefik_entrypoints "$traefik")"
        if [[ "$(printf '%s\n' "$eps" | grep -c .)" -eq 1 ]]; then
            DASH_ENTRYPOINT="$eps"
        elif [[ "$interactive" -eq 1 ]]; then
            DASH_ENTRYPOINT="$(ask "Point d'entrée Traefik${eps:+ ($(printf '%s' "$eps" | tr '\n' ' ' | sed 's/ $//'))} [web] :" web)"
        else
            die "Point d'entrée Traefik ambigu${eps:+ ($(printf '%s' "$eps" | tr '\n' ' '))} : renseignez [dashboard].docker_entrypoint dans config/workspace.user.toml."
        fi
    fi
    if [[ -z "$DASH_HOST" ]]; then
        if [[ "$interactive" -eq 1 ]]; then
            DASH_HOST="$(ask "Adresse du tableau de bord [coach.localhost] :" coach.localhost)"
        else
            DASH_HOST="coach.localhost"
        fi
        validate_dashboard_docker
    fi
    if [[ -z "$DASH_AUTH" ]] && ! traefik_loopback_only "$traefik"; then
        if [[ "$interactive" -eq 1 ]]; then
            warn "Traefik ($traefik) est joignable hors de cette machine : le tableau de bord (données de santé) exige une authentification."
            DASH_AUTH="$(ask "Middleware d'authentification Traefik (ex. authentik@file) :" "")"
            validate_dashboard_docker
        fi
        [[ -n "$DASH_AUTH" ]] || die "Traefik ($traefik) est joignable hors de cette machine : --dashboard-auth <middleware> est obligatoire (docs/dashboard/docker.md)."
    fi
    DASH_TRAEFIK="$traefik"
}

# Mode du tableau de bord Docker : option explicite, sinon [dashboard].docker, sinon la question
# (terminal + Docker joignable), sinon « off » sans rien écrire.
resolve_dashboard_docker() {
    local interactive=0
    [[ -t 0 && "$DRY_RUN" -eq 0 ]] && interactive=1
    if [[ "$EXPLICIT_DASH" -eq 1 ]]; then
        DASH_DOCKER="$(printf '%s' "$DASH_DOCKER" | tr '[:upper:]' '[:lower:]')"
        validate_dashboard_docker
    elif [[ -n "$DASH_HOST$DASH_AUTH" ]]; then
        die "--dashboard-host et --dashboard-auth s'utilisent avec --dashboard-docker traefik."
    fi
    if [[ "$EXPLICIT_DASH" -eq 0 ]]; then
        DASH_DOCKER="$(dashboard_config_value docker | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
        DASH_HOST="$(dashboard_config_value docker_host)"
        DASH_AUTH="$(dashboard_config_value docker_auth)"
        case "$DASH_DOCKER" in
            off|local|traefik) ;;
            "")
                if [[ "$interactive" -eq 1 ]] && docker_ready; then
                    if [[ "$(ask "Docker détecté : servir le tableau de bord dans un conteneur, reconstruit à chaque mise à jour ? [o/N]" n)" =~ ^[oOyY] ]]; then
                        DASH_DOCKER="local"
                        if [[ -n "$(traefik_container)" ]] \
                            && [[ "$(ask "Traefik détecté : y ranger le tableau de bord (sinon 127.0.0.1:$(dashboard_config_value port)) ? [O/n]" o)" =~ ^[oOyY] ]]; then
                            DASH_DOCKER="traefik"
                        fi
                    else
                        DASH_DOCKER="off"
                    fi
                    DASH_PERSIST=1
                else
                    DASH_DOCKER="off"
                fi ;;
            *) warn "[dashboard].docker = « $DASH_DOCKER » invalide (off, local, traefik) — traité comme « off »."; DASH_DOCKER="off" ;;
        esac
    else
        DASH_PERSIST=1
    fi
    [[ "$DASH_DOCKER" == "traefik" ]] || return 0
    DASH_NETWORK="$(dashboard_config_value docker_network)"
    DASH_ENTRYPOINT="$(dashboard_config_value docker_entrypoint)"
    if docker_ready; then
        resolve_dashboard_traefik "$interactive"
    elif [[ "$EXPLICIT_DASH" -eq 1 ]]; then
        die "--dashboard-docker traefik : Docker est injoignable (démon arrêté ?)."
    fi
}

persist_dashboard_docker() {
    [[ "$DASH_PERSIST" -eq 1 ]] || return 0
    local key value
    for key in docker docker_host docker_auth docker_network docker_entrypoint; do
        case "$key" in
            docker) value="$DASH_DOCKER" ;;
            docker_host) value="$DASH_HOST" ;;
            docker_auth) value="$DASH_AUTH" ;;
            docker_network) value="$DASH_NETWORK" ;;
            docker_entrypoint) value="$DASH_ENTRYPOINT" ;;
        esac
        # Hors Traefik, seule la clé « docker » a un sens : les autres ne sont pas écrites.
        [[ "$key" == "docker" || "$DASH_DOCKER" == "traefik" ]] || continue
        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} [dashboard].$key = $value"
            continue
        fi
        have python3 || return 0
        python3 "$PROJECT_ROOT/scripts/coach_config.py" set \
            --workspace "$WORKSPACE_ROOT" --section dashboard --key "$key" --value "$value" >/dev/null \
            || warn "Impossible d'écrire [dashboard].$key — vérifiez config/workspace.user.toml."
    done
}

# Chaîne YAML entre guillemets doubles ; « $ » doublé (interpolation compose).
yaml_quote() {
    printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\$/$$/g')"
}

write_dashboard_compose() {
    local port="$1" hosts
    if [[ "$DASH_DOCKER" == "traefik" ]]; then hosts="$DASH_HOST"; else hosts="127.0.0.1,localhost"; fi
    {
        cat <<EOF
# Généré par install.sh (--dashboard-docker $DASH_DOCKER) : ne pas éditer, relancez ./install.sh.
# Image reconstruite par /update-coach (scripts/update-docker.sh) à chaque mise à jour du moteur.
# Tableau de bord ai-running-coach, lecture seule (docs/dashboard/docker.md).
name: $DASH_PROJECT

services:
  dashboard:
    build:
      context: $(yaml_quote "$PROJECT_ROOT")
      args:
        # Révision git du moteur, fournie par scripts/update-docker.sh (/update-coach).
        ARC_REVISION: "\${ARC_REVISION:-}"
    image: ai-running-coach-dashboard:local
    container_name: $DASH_PROJECT
    restart: unless-stopped
    # Propriétaire du workspace (config/workspace.user.toml est en 600).
    user: "$(id -u):$(id -g)"
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    tmpfs: [/tmp]
    environment:
      ARC_DASHBOARD_ALLOWED_HOSTS: $(yaml_quote "$hosts")
      TZ: $(yaml_quote "$(host_timezone)")
    volumes:
      - $(yaml_quote "$WORKSPACE_ROOT:/workspace:ro")
EOF
        if [[ "$DASH_DOCKER" == "local" ]]; then
            cat <<EOF
    # Boucle locale uniquement : rien n'est joignable hors de cette machine.
    ports:
      - "127.0.0.1:$port:8765"
EOF
        else
            cat <<EOF
    networks: [proxy]
    labels:
      - "traefik.enable=true"
      - $(yaml_quote "traefik.docker.network=$DASH_NETWORK")
      - $(yaml_quote "traefik.http.routers.$DASH_PROJECT.rule=Host(\`$DASH_HOST\`)")
      - $(yaml_quote "traefik.http.routers.$DASH_PROJECT.entrypoints=$DASH_ENTRYPOINT")
EOF
            [[ -z "$DASH_AUTH" ]] || printf '      - %s\n' "$(yaml_quote "traefik.http.routers.$DASH_PROJECT.middlewares=$DASH_AUTH")"
            cat <<EOF
      - "traefik.http.routers.$DASH_PROJECT.service=$DASH_PROJECT"
      - "traefik.http.services.$DASH_PROJECT.loadbalancer.server.port=8765"

networks:
  proxy:
    external: true
    name: $(yaml_quote "$DASH_NETWORK")
EOF
        fi
    } | write_file "$DASH_DIR/compose.yaml"
}

install_dashboard_docker() {
    local compose=(docker compose -p "$DASH_PROJECT" -f "$DASH_DIR/compose.yaml")
    if [[ "$DASH_DOCKER" == "off" ]]; then
        # Retour à « off » : on arrête le conteneur qu'install.sh avait lancé, et lui seul.
        if [[ -f "$DASH_DIR/compose.yaml" ]] && docker_ready \
            && [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$DASH_PROJECT" 2>/dev/null)" ]]; then
            log "Tableau de bord Docker désactivé : arrêt du conteneur $DASH_PROJECT"
            run "${compose[@]}" down || warn "Arrêt de $DASH_PROJECT impossible : docker compose -p $DASH_PROJECT -f $DASH_DIR/compose.yaml down"
        fi
        return 0
    fi
    local port
    port="$(dashboard_config_value port)"
    [[ "$port" =~ ^[0-9]+$ ]] || port=8765
    log "Tableau de bord Docker ($DASH_DOCKER)"
    if [[ "$DRY_RUN" -eq 0 ]] && ! docker_ready; then
        warn "Docker injoignable : tableau de bord non reconstruit. Démarrez Docker puis relancez ./install.sh."
        return 0
    fi
    write_dashboard_compose "$port"
    # Pas de --build : l'image n'est reconstruite qu'à une mise à jour (/update-coach). up -d ne
    # recrée le conteneur que si le compose a changé, et construit l'image seulement si elle manque.
    if run "${compose[@]}" up -d </dev/null; then
        if [[ "$DASH_DOCKER" == "local" ]]; then
            ok "Tableau de bord Docker : http://127.0.0.1:$port/ (conteneur $DASH_PROJECT)"
        else
            ok "Tableau de bord Docker : $DASH_HOST via Traefik ($DASH_TRAEFIK, point d'entrée $DASH_ENTRYPOINT)"
            [[ -n "$DASH_AUTH" ]] || log "Sans authentification : Traefik n'écoute que sur la boucle locale."
        fi
    else
        warn "Lancement du tableau de bord Docker impossible — relancez : ${compose[*]} up -d"
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
    [[ -z "$NEW_AGENTS" ]] || recap_line "Nouveaux agents" "$NEW_AGENTS" "mise à jour"
    # Pas de « case » dans $( ) : bash 3.2 (macOS) l'analyse mal et affiche le texte brut.
    local auth_label
    case "$SOURCE" in
        intervals) auth_label="Auth Intervals.icu" ;;
        strava) auth_label="Auth Strava" ;;
        *) auth_label="Auth Garmin" ;;
    esac
    recap_line "$auth_label" \
        "$([[ "$DO_AUTH" -eq 1 ]] && echo "activée" || echo "sautée")" "$(_config_origin "$EXPLICIT_DO_AUTH")"
    recap_line "Passerelle leanproxy" \
        "$([[ "$USE_LEANPROXY" -eq 1 ]] && echo "oui" || echo "non")" "$(_config_origin "$EXPLICIT_LEANPROXY")"
    recap_line "Sync auto (cron)" \
        "$([[ "$DAILY_SYNC" -eq 1 ]] && echo "oui" || echo "non")" "$(_config_origin "$EXPLICIT_DAILY_SYNC")"
    recap_line "Remote Control" \
        "$([[ "$REMOTE_CONTROL" -eq 1 ]] && echo "oui" || echo "non")" "$(_config_origin "$EXPLICIT_REMOTE_CONTROL")"
    if [[ "$LLM_PROVIDER" == "chatgpt" || "$LLM_PROVIDER" == "copilot" ]]; then
        if [[ "$(effective_value sync opencode_data_dir)" == "$LLM_OPENCODE_DATA_DIR" ]]; then
            recap_line "Chat + sync (abonnement)" "$LLM_PROVIDER" "explicite"
        else
            recap_line "Chat (abonnement)" "$LLM_PROVIDER" "explicite ; sync inchangée"
        fi
    elif [[ -n "$LLM_PROVIDER" ]]; then
        recap_line "Chat + sync sur API" "$LLM_PROVIDER" "explicite"
    fi
    [[ "$DO_CHAT" -eq 0 ]] || recap_line "Service du chat" "oui" "explicite"
    [[ "$DO_TELEGRAM" -eq 0 ]] || recap_line "Bot Telegram" "oui" "explicite"
    # Opt-in strict : aucune ligne tant que la santé n'est pas lue chez Open Wearables (#220).
    [[ "$HEALTH_EFFECTIVE" != "openwearables" ]] \
        || recap_line "Santé" "Open Wearables (${OW_PROVIDER:-?}) — ${OW_URL:-?}" \
            "$([[ "$EXPLICIT_HEALTH" -eq 1 ]] && echo "explicite" || echo "config")"
    [[ "$DASH_DOCKER" == "off" || -z "$DASH_DOCKER" ]] \
        || recap_line "Tableau de bord Docker" "$DASH_DOCKER${DASH_HOST:+ ($DASH_HOST)}" \
            "$([[ "$EXPLICIT_DASH" -eq 1 ]] && echo "explicite" || echo "config")"
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
    resolve_cycle_tracking
    resolve_nutrition_sync
    resolve_health_source
    resolve_dashboard_docker
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
    # Sans effet si aucun dossier de jetons n'existe ; resserre aussi des jetons laissés par une
    # source Garmin abandonnée.
    restrict_garmin_tokens
    install_leanproxy
    configure_leanproxy
    prepare_workspace
    configure_ide
    create_workspace_dirs
    create_workspace_config
    persist_agents
    persist_source
    persist_cycle_tracking
    persist_nutrition_sync
    persist_health_source
    ensure_ow_key
    persist_llm
    persist_sync_runner
    persist_budgets
    if [[ "$DAILY_SYNC" -eq 1 || "$REMOTE_CONTROL" -eq 1 ]]; then
        check_runners
    fi
    install_daily_sync
    install_remote_control
    install_chat
    install_telegram
    persist_dashboard_docker
    install_dashboard_docker
    verify
    verify_openwearables
    persist_install_args
    connect_llm
}

# Mémorise les options de configuration de cette installation, une par ligne, pour que
# scripts/update-coach.sh (/update-coach) relance install.sh à l'identique après un git pull.
# --no-auth/--auth/--dry-run/--connect (action ponctuelle interactive) ne décrivent pas la configuration : jamais mémorisés. Une relance
# sans autre option (« ./install.sh --no-auth ») garde les options déjà mémorisées — sinon elle
# effacerait, par exemple, le --daily-sync que la mise à jour doit rejouer. Écrit seulement après
# une installation complète, jamais en dry-run. Aucun secret : install.sh ne reçoit que des chemins.
persist_install_args() {
    [[ "$DRY_RUN" -eq 0 ]] || return 0
    local file arg prev="" kept=()
    file="$(dirname "$WORKSPACE_STATE_FILE")/install-args"
    for arg in ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"}; do
        if [[ "$arg" == *$'\n'* ]]; then
            warn "Option sur plusieurs lignes : options d'installation non mémorisées ($file)."
            return 0
        fi
        # Valeur de chemin relative : résolue contre le dossier d'où install.sh a été lancé,
        # sinon la relance (depuis la racine du moteur) viserait un autre dossier.
        case "$prev" in
            --workspace|--ow-key-file) [[ "$arg" == /* ]] || arg="$INSTALL_CWD/${arg#./}" ;;
        esac
        case "$arg" in
            --no-auth|--auth|--dry-run|--connect) ;;
            *) kept+=("$arg") ;;
        esac
        prev="$arg"
    done
    if [[ "${#kept[@]}" -eq 0 && -f "$file" ]]; then
        return 0
    fi
    mkdir -p "$(dirname "$file")"
    if [[ "${#kept[@]}" -eq 0 ]]; then
        : > "$file"   # aucune option : fichier vide (printf écrirait une ligne vide)
    else
        printf '%s\n' "${kept[@]}" > "$file"
    fi
    ok "Options d'installation mémorisées pour les mises à jour : $file"
}

main "$@"
