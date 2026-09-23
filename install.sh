#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — Script d'installation
#
# Installe et configure tout ce qu'il faut pour utiliser les agents/skills de
# coaching trail-running avec accès Garmin :
#   1. uv (gestionnaire Python)
#   2. garmin-mcp + garmin-mcp-auth (accès Garmin Connect) — mode DIRECT par défaut
#   3. (Optionnel) leanproxy-mcp — passerelle MCP "power user" (--use-leanproxy)
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
#   ./install.sh --workspace DIR    # données + config IDE dans DIR (dépôt privé), moteur lié
#   ./install.sh --agents LISTE     # staff à installer, ex. coach,nutritionist
#   ./install.sh --no-medical       # tous les agents sauf le médecin
#   ./install.sh --no-auth          # saute l'authentification Garmin
#   ./install.sh --use-leanproxy    # mode passerelle leanproxy (power user)
#   ./install.sh --daily-sync       # cron/launchd : sync Garmin aux heures de [sync].times
#   ./install.sh --remote-control   # service Remote Control (le coach dans la poche)
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
GARMIN_MCP_REF="git+https://github.com/Taxuspt/garmin_mcp"
LEANPROXY_BREW_TAP="mmornati/leanproxy-mcp"
LEANPROXY_FORMULA="leanproxy-mcp"
GARMIN_TOKENS_DIR="$HOME/.garminconnect"
LEANPROXY_CONFIG_DIR="$HOME/.config/leanproxy"
LEANPROXY_SERVERS="$HOME/.config/leanproxy_servers.yaml"

# Liste blanche des outils Garmin utilisés par les agents/skills du projet.
# Réduit la taxe de contexte (~151 outils → ~30) en mode direct.
# Noms réels des outils garmin-mcp (sans préfixe garmin_).
GARMIN_TOOL_WHITELIST="get_activities,get_activities_by_date,get_activity,get_activity_fit_data,get_activity_splits,get_activity_typed_splits,get_activity_split_summaries,get_sleep_data,get_hrv_data,get_rhr_day,get_training_readiness,get_calendar_events,get_courses,get_workouts,get_workout_by_id,get_scheduled_workouts,schedule_workouts,schedule_week,upload_workout,upload_course,create_strength_workout,delete_workout,unschedule_workout,unschedule_workouts,download_activity_file"

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

usage() {
    cat <<'USAGE'
ai-running-coach — script d'installation

Usage :
  ./install.sh                    # installation (mode direct Garmin)
  ./install.sh --ide IDE          # claude | copilot | opencode | gemini | cursor | windsurf
  ./install.sh --workspace DIR    # données + config IDE dans DIR (dépôt privé), moteur lié
  ./install.sh --agents LISTE     # staff à installer, ex. coach,nutritionist
  ./install.sh --no-medical       # tous les agents sauf le médecin
  ./install.sh --no-auth          # saute l'authentification Garmin
  ./install.sh --use-leanproxy    # mode passerelle leanproxy (power user)
  ./install.sh --daily-sync       # cron/launchd : sync Garmin aux heures de [sync].times
  ./install.sh --remote-control   # service Remote Control (le coach dans la poche)
  ./install.sh --dry-run          # affiche les actions sans rien exécuter
  ./install.sh --help

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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ide) need_value "$@"; IDE="$2"; shift 2 ;;
        --no-auth) DO_AUTH=0; shift ;;
        --use-leanproxy) USE_LEANPROXY=1; shift ;;
        --skip-leanproxy) USE_LEANPROXY=0; shift ;;  # rétro-compatibilité
        --workspace) need_value "$@"; WORKSPACE_ARG="$2"; shift 2 ;;
        --agents) need_value "$@"; AGENTS_ARG="$2"; shift 2 ;;
        --no-medical) AGENTS_ARG="${AGENTS_ARG:-__all_but__}:medical"; shift ;;
        --daily-sync) DAILY_SYNC=1; shift ;;
        --remote-control) REMOTE_CONTROL=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) usage ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

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
WORKSPACE_IGNORES=(
    /agents/ /skills/ /scripts/ /AGENTS.md /config/workspace.toml config/workspace.user.toml
    /.mcp.json /.claude/ /.opencode/ /.gemini/ /.cursor/ /.windsurf/ /.github/agents /.github/skills
    /logs/ /.arc/ .DS_Store __pycache__/
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
/scripts/
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
# 3. leanproxy-mcp (optionnel — mode power user)
# ---------------------------------------------------------------------------
install_leanproxy() {
    if [[ "$USE_LEANPROXY" -eq 0 ]]; then
        warn "leanproxy-mcp non installé (mode direct). Utilisez --use-leanproxy pour la passerelle."
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
        write_file "$LEANPROXY_SERVERS" <<'EOF'
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
            - GARMIN_ENABLED_TOOLS: "get_activities,get_activities_by_date,get_activity,get_activity_fit_data,get_activity_splits,get_activity_typed_splits,get_activity_split_summaries,get_sleep_data,get_hrv_data,get_rhr_day,get_training_readiness,get_calendar_events,get_courses,get_workouts,get_workout_by_id,get_scheduled_workouts,schedule_workouts,schedule_week,upload_workout,upload_course,create_strength_workout,delete_workout,unschedule_workout,unschedule_workouts,download_activity_file"
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

# Bloc MCP pour le mode direct (garmin-mcp + whitelist)
mcp_garmin_direct() {
    cat <<'EOF'
    "garmin": {
      "command": "garmin-mcp",
      "args": ["stdio"],
      "env": {
        "GARMIN_ENABLED_TOOLS": "get_activities,get_activities_by_date,get_activity,get_activity_fit_data,get_activity_splits,get_activity_typed_splits,get_activity_split_summaries,get_sleep_data,get_hrv_data,get_rhr_day,get_training_readiness,get_calendar_events,get_courses,get_workouts,get_workout_by_id,get_scheduled_workouts,schedule_workouts,schedule_week,upload_workout,upload_course,create_strength_workout,delete_workout,unschedule_workout,unschedule_workouts,download_activity_file"
      }
    }
EOF
}

# Bloc MCP pour le mode leanproxy
mcp_leanproxy_block() {
    cat <<'EOF'
    "leanproxy": {
      "command": "leanproxy-mcp",
      "args": []
    }
EOF
}

# Valeur JSON du serveur, au format « mcpServers » (Claude, Copilot, Cursor,
# Windsurf) puis au format OpenCode. Produites ici pour qu'il n'y ait qu'un
# endroit à corriger quand la liste blanche change.
mcp_server_value() {
    if [[ "$USE_LEANPROXY" -eq 1 ]]; then
        printf '{"command": "leanproxy-mcp", "args": []}'
    else
        printf '{"command": "garmin-mcp", "args": ["stdio"], "env": {"GARMIN_ENABLED_TOOLS": "%s"}}' \
            "$GARMIN_TOOL_WHITELIST"
    fi
}

mcp_server_value_opencode() {
    if [[ "$USE_LEANPROXY" -eq 1 ]]; then
        printf '{"type": "local", "command": ["leanproxy-mcp"], "enabled": true}'
    else
        printf '{"type": "local", "command": ["garmin-mcp", "stdio"], "environment": {"GARMIN_ENABLED_TOOLS": "%s"}, "enabled": true}' \
            "$GARMIN_TOOL_WHITELIST"
    fi
}

# Nom du serveur MCP à utiliser selon le mode
mcp_server_name() {
    if [[ "$USE_LEANPROXY" -eq 1 ]]; then
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
    merge_json_key "$cfg" mcpServers "$(mcp_server_name)" "$(mcp_server_value)"
    ok "Serveur MCP $(mcp_server_name) présent dans $cfg"
}

write_windsurf_config() {
    log "Configuration Windsurf"
    local cfg="$WORKSPACE_ROOT/.windsurf/mcp_config.json"
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
    for d in activities medical nutrition planning rapports resources; do
        if [[ "$DRY_RUN" -eq 0 ]]; then
            mkdir -p "$WORKSPACE_ROOT/$d"
        fi
    done
    ok "Dossiers activities/ medical/ nutrition/ planning/ rapports/ resources/ prêts"
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
    local sync="$PROJECT_ROOT/scripts/daily-sync.sh" times t hour minute
    times="$(sync_times | tr '\n' ' ')"
    log "Heures : $times (config [sync].times)"

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
        local x_sync x_ws
        x_sync="$(xml_escape "$sync")"; x_ws="$(xml_escape "$WORKSPACE_ROOT")"
        write_file "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ai-running-coach.daily-sync</string>
  <key>ProgramArguments</key><array><string>$x_sync</string></array>
  <key>WorkingDirectory</key><string>$x_ws</string>
  <key>EnvironmentVariables</key><dict><key>ARC_WORKSPACE</key><string>$x_ws</string></dict>
  <key>StartCalendarInterval</key>
  <array>
$entries  </array>
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
# 7. Vérification finale
# ---------------------------------------------------------------------------
verify() {
    log "Vérification finale"
    local fail=0
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
    if [[ "$fail" -eq 0 ]]; then
        ok "Installation terminée. Lancez votre IDE et demandez à l'agent 'coach' de définir votre objectif !"
    else
        warn "Certains composants manquent — relisez les messages ci-dessus."
    fi
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
    if [[ "$USE_LEANPROXY" -eq 1 ]]; then
        log "Mode : passerelle leanproxy (power user)"
    else
        log "Mode : direct garmin-mcp (défaut, liste blanche d'outils)"
    fi
    [[ "$DRY_RUN" -eq 1 ]] && warn "Mode dry-run : aucune modification ne sera effectuée."
    echo

    require_cmd curl "Installez curl (macOS : déjà présent ; Linux : apt install curl)."
    require_cmd git "Installez git."

    install_uv
    install_garmin_mcp
    install_leanproxy
    configure_leanproxy
    prepare_workspace
    configure_ide
    create_workspace_dirs
    create_workspace_config
    persist_agents
    if [[ "$DAILY_SYNC" -eq 1 || "$REMOTE_CONTROL" -eq 1 ]]; then
        check_runners
    fi
    install_daily_sync
    install_remote_control
    verify
}

main "$@"
