#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — synchronisation Garmin automatique (headless)
#
# Lance le skill /garmin-daily-sync avec l'exécuteur configuré (Claude Code ou
# Codex CLI, abonnement — pas de clé API), journalise, extrait le bloc ```resume```
# et l'envoie en notification push via scripts/notify.sh.
#
# Usage :
#   scripts/daily-sync.sh              # exécution (appelée par cron/launchd)
#   scripts/daily-sync.sh --dry-run    # affiche la commande sans l'exécuter
#   scripts/daily-sync.sh --runner codex
#
# Configuration : section [sync] de config/workspace.toml (runner, lookback_days)
# et [notifications] (voir scripts/setup-ntfy.sh). S'exécute dans le workspace
# (ARC_WORKSPACE / ~/.config/ai-running-coach/workspace, sinon ce dépôt).
# Journaux : <workspace>/logs/sync-YYYY-MM-DD.log (gitignoré). Verrou : logs/.sync.lock.
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

DRY_RUN=0
RUNNER=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --runner) RUNNER="$2"; shift 2 ;;
        --help|-h) sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

# cron/launchd démarrent avec un PATH minimal : ajoute les emplacements usuels
# de claude, codex, uv et garmin-mcp.
export PATH="$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

RUNNER="${RUNNER:-$(toml_get sync runner claude)}"
LOOKBACK="$(toml_get sync lookback_days 2)"
SKILL_FILE="$ARC_ENGINE_ROOT/skills/garmin-daily-sync/SKILL.md"
LOG_DIR="$ARC_WORKSPACE/logs"
LOG_FILE="$LOG_DIR/sync-$(date +%F).log"
LOCK_FILE="$LOG_DIR/.sync.lock"
NOTIFY="$ARC_ENGINE_ROOT/scripts/notify.sh"

[[ -f "$SKILL_FILE" ]] || die "Skill introuvable : $SKILL_FILE"
mkdir -p "$LOG_DIR"

# Outils autorisés en mode non interactif : serveur MCP garmin (tous ses outils),
# délégation au coach (Agent/Task), skills, lecture/écriture des MD, scripts
# Python du projet. Rien d'autre.
CLAUDE_TOOLS="mcp__garmin,mcp__leanproxy,Agent,Task,Skill,Read,Write,Edit,Glob,Grep,Bash(python3:*)"
# En mode -p, un serveur MCP déclaré dans .mcp.json (portée projet) n'est chargé
# que s'il a été approuvé interactivement ; on le passe explicitement.
MCP_CONFIG="$ARC_WORKSPACE/.mcp.json"

build_command() {
    case "$RUNNER" in
        claude)
            have claude || [[ "$DRY_RUN" -eq 1 ]] || die "claude introuvable — installez Claude Code : curl -fsSL https://claude.ai/install.sh | bash"
            CMD=(claude -p "/garmin-daily-sync (lookback_days=$LOOKBACK)"
                 --permission-mode acceptEdits
                 --allowedTools "$CLAUDE_TOOLS"
                 --output-format text)
            if [[ -f "$MCP_CONFIG" ]]; then
                CMD+=(--mcp-config "$MCP_CONFIG" --strict-mcp-config)
            else
                warn "$MCP_CONFIG absent — lancez './install.sh --ide claude' (serveur MCP garmin)."
            fi ;;
        codex)
            have codex || [[ "$DRY_RUN" -eq 1 ]] || die "codex introuvable — installez Codex CLI : npm i -g @openai/codex"
            # Codex n'a pas de slash-command projet : on passe le corps du skill en prompt.
            local prompt
            prompt="$(awk 'NR==1 && /^---$/ {fm=1; next} fm && /^---$/ {fm=0; next} !fm' "$SKILL_FILE")"
            prompt="lookback_days=$LOOKBACK. Follow these instructions exactly:
$prompt"
            CMD=(codex exec --full-auto --cd "$ARC_WORKSPACE" "$prompt") ;;
        *) die "Exécuteur inconnu : $RUNNER (claude|codex)" ;;
    esac
}

# Extrait le contenu du dernier bloc ```resume … ``` de la sortie.
extract_resume() {
    awk '
        /^```resume[[:space:]]*$/ { capture = 1; buf = ""; next }
        capture && /^```[[:space:]]*$/ { capture = 0; last = buf; next }
        capture { buf = buf $0 "\n" }
        END { printf "%s", last }'
}

notify() {
    local title="$1" priority="$2" tags="$3"
    shift 3
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} notify.sh --title \"$title\" — $*"
        return 0
    fi
    "$NOTIFY" --title "$title" --priority "$priority" --tags "$tags" "$*" || warn "Notification non envoyée."
}

main() {
    build_command
    log "Synchronisation Garmin — exécuteur : $RUNNER, fenêtre : $LOOKBACK jour(s)"
    log "Workspace : $ARC_WORKSPACE (moteur : $ARC_ENGINE_ROOT)"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} cd $ARC_WORKSPACE && ${CMD[*]}" | head -c 600; echo
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} journal : $LOG_FILE"
        return 0
    fi

    # Verrou : pas de synchronisations concurrentes (cron du matin trop long, relance manuelle…).
    if [[ -e "$LOCK_FILE" ]] && kill -0 "$(cat "$LOCK_FILE" 2>/dev/null)" 2>/dev/null; then
        warn "Une synchronisation est déjà en cours (pid $(cat "$LOCK_FILE")) — abandon."
        exit 0
    fi
    echo $$ > "$LOCK_FILE"
    trap 'rm -f "$LOCK_FILE"' EXIT

    local output rc=0
    {
        echo "===== $(date '+%F %T') — runner=$RUNNER lookback=$LOOKBACK ====="
    } >> "$LOG_FILE"
    cd "$ARC_WORKSPACE"
    output="$("${CMD[@]}" 2>>"$LOG_FILE")" || rc=$?
    printf '%s\n' "$output" >> "$LOG_FILE"

    if [[ "$rc" -ne 0 ]]; then
        err "La synchronisation a échoué (code $rc) — voir $LOG_FILE"
        notify "❌ Sync Garmin échouée" 4 "warning" "Exécuteur $RUNNER, code $rc. Voir logs/sync-$(date +%F).log sur la machine coach."
        exit "$rc"
    fi

    local resume
    resume="$(printf '%s\n' "$output" | extract_resume)"
    if [[ -z "$resume" ]]; then
        warn "Aucun bloc \`\`\`resume trouvé — envoi des 5 dernières lignes de la sortie."
        resume="$(printf '%s\n' "$output" | tail -n 5)"
    fi
    ok "Résumé :"
    printf '%s\n' "$resume"

    local title="🏃 Sync Garmin" priority=3 tags="running"
    if printf '%s' "$resume" | grep -qi '^ERREUR'; then
        title="⚠️ Sync Garmin"; priority=4; tags="warning"
    elif printf '%s' "$resume" | grep -qi '^À jour'; then
        title="Sync Garmin — à jour"; priority=2; tags="running"
    fi
    notify "$title" "$priority" "$tags" "$resume"
}

main "$@"
