#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — discuter avec le coach sur Telegram, sur abonnement
#                    (Claude Code Channels — EXPÉRIMENTAL, research preview)
#
# Fait tourner en permanence, sur la machine « coach », une session
#   claude --channels plugin:telegram@claude-plugins-official
# dans le workspace : vos messages au bot arrivent dans cette session (agents,
# skills, serveur MCP garmin, fichiers MD) et le coach répond dans Telegram,
# sur l'abonnement claude.ai (aucune clé d'API). Distinct du bot « un geste »
# (scripts/coach-telegram.sh, [telegram]) : il faut un SECOND bot, sinon deux
# processus lisent le même bot (erreur 409) — le script refuse de démarrer.
#
# Usage :
#   scripts/coach-telegram-chat.sh run --pairing  # 1re fois, au premier plan : appairage du compte
#   scripts/coach-telegram-chat.sh install        # permissions + service (systemd --user / launchd / tmux)
#   scripts/coach-telegram-chat.sh start|stop|restart|status|logs
#   scripts/coach-telegram-chat.sh uninstall
#   scripts/coach-telegram-chat.sh --dry-run install   # affiche sans rien écrire ni lancer
#
# Prérequis : Claude Code >= 2.1.295 connecté avec un abonnement claude.ai (pas de clé API),
# Bun, tmux, plugin installé et configuré avec le jeton d'un second bot :
#   /plugin install telegram@claude-plugins-official
#   /telegram:configure <token BotFather du second bot>
# Configuration : section [telegram_chat] de config/workspace.toml (docs/telegram.md).
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

DRY_RUN="${ARC_DRY_RUN:-0}"
PAIRING=0
ACTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pairing) PAIRING=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        run|supervise|install|uninstall|start|stop|restart|status|logs) ACTION="$1"; shift ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done
[[ -n "$ACTION" ]] || { sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

# Production : les dossiers d'outils passent AVANT le PATH. ARC_PATH_APPEND=1 (tests : les stubs doivent
# l'emporter sur les vrais tmux / claude de la machine) les place APRÈS.
if [[ "${ARC_PATH_APPEND:-0}" == "1" ]]; then
    export PATH="$PATH:$HOME/.local/bin:$HOME/.claude/bin:$HOME/.bun/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin"
else
    export PATH="$HOME/.local/bin:$HOME/.claude/bin:$HOME/.bun/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
fi

CHANNEL="plugin:telegram@claude-plugins-official"
# « default » (pas acceptEdits) : acceptEdits validerait d'office toute écriture du workspace et
# viderait de son sens le périmètre d'écriture de templates/settings.telegram.json.
PERMISSION_MODE="$(toml_get telegram_chat permission_mode default)"
DAILY_RESTART="$(toml_get telegram_chat daily_restart 03:30)"
# Dossier d'état du plugin : ${TELEGRAM_STATE_DIR}, sinon ${CLAUDE_CONFIG_DIR:-~/.claude}/channels/telegram.
TG_DIR="${TELEGRAM_STATE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/channels/telegram}"
# Racine PHYSIQUE du moteur : ce script est presque toujours lancé via workspace/scripts -> moteur/scripts,
# et ARC_ENGINE_ROOT (chemin logique) désignerait alors le workspace, qui n'a pas templates/.
ENGINE_PHYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SELF="$ENGINE_PHYS/scripts/coach-telegram-chat.sh"
# Aussi le nom de la socket tmux (-L) : serveur dédié, sinon le restart systemd
# (KillMode=control-group) tuerait toutes les sessions tmux de l'utilisateur.
TMUX_SESSION="coach-telegram-chat"
SERVICE_NAME="ai-running-coach-telegram-chat"
SYSTEMD_DIR="$HOME/.config/systemd/user"
LAUNCHD_LABEL="com.ai-running-coach.telegram-chat"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ARC_WORKSPACE/logs"
LOG_FILE="$LOG_DIR/telegram-chat.log"   # distinct de telegram.log (bot un geste)
# Réglages DÉDIÉS à cette session, passés par « claude --settings » (jamais dans settings.local.json, qui
# s'applique à toutes les sessions du workspace : synchronisation headless, /coach-setup, appairage…).
# Ce script n'écrit JAMAIS settings.local.json.
CHAT_SETTINGS="$ARC_WORKSPACE/.claude/telegram-chat.settings.json"
SETTINGS_TEMPLATE="$ENGINE_PHYS/templates/settings.telegram.json"
HOOK_SCRIPT="$ENGINE_PHYS/scripts/arc_telegram_hook.py"
MIN_CLAUDE="2.1.295"   # onFailure du hook (échec fermé)
OS="$(uname -s)"

# Rappel injecté dans la session : chaque message Telegram passe par le skill
# telegram-chat (réponse via l'outil reply, confirmation dans le chat avant toute écriture distante).
SYSTEM_HINT="Messages arriving through the Telegram channel come from the athlete on their phone. Before handling one, load the telegram-chat skill and follow it: reply only with the channel's reply tool, keep it short, and never write to Garmin, COROS or intervals.icu without an explicit OK sent in a later Telegram message, and never delete anything from Telegram."

# Échappe une chaîne pour l'insérer dans du XML (plist launchd).
xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

run() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} $*"
        return 0
    fi
    "$@"
}

write_file() {
    local file="$1"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} écriture de $file"
        cat >/dev/null
        return 0
    fi
    mkdir -p "$(dirname "$file")"
    cat > "$file"
}

# Channels exige une connexion claude.ai (abonnement). Refuser ANTHROPIC_API_KEY est un CHOIX du projet
# (ne jamais facturer une clé Console par surprise ; le mode existe pour l'abonnement), pas une limite de Claude Code.
check_login() {
    local status
    status="$(claude auth status 2>/dev/null || true)"
    if ! grep -q '"loggedIn": *true' <<<"$status"; then
        [[ "$DRY_RUN" -eq 1 ]] && { warn "Claude Code n'est pas connecté (ignoré en dry-run)."; return 0; }
        die "Claude Code n'est pas connecté. Lancez 'claude' puis '/login' (compte claude.ai, pas de clé API)."
    fi
    [[ -z "${ANTHROPIC_API_KEY:-}" ]] \
        || die "ANTHROPIC_API_KEY est défini : retirez-le, la session doit utiliser l'abonnement claude.ai."
    return 0
}

# Politique d'accès du bot : « allowlist » obligatoire hors appairage — la session
# lit des données de santé et peut écrire dans le calendrier Garmin (après approbation).
dm_policy() {
    [[ -f "$TG_DIR/access.json" ]] || { echo "absent"; return 0; }
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("dmPolicy", "pairing"))' \
        "$TG_DIR/access.json" 2>/dev/null || echo "illisible"
}

# Valeur de TELEGRAM_BOT_TOKEN dans un fichier d'environnement (dernière ligne non vide), sinon
# rien. Sert UNIQUEMENT à comparer deux jetons : la valeur n'est jamais écrite dans un message.
read_env_token() {
    local file="$1" line value="" key
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line#export }"
        key="${line%%=*}"
        [[ "$key" == "TELEGRAM_BOT_TOKEN" && "$line" == *=* ]] || continue
        line="${line#*=}"
        line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
        [[ -z "$line" ]] || value="$line"
    done < "$file"
    printf '%s' "$value"
}

# Jeton du plugin Channels : variable d'environnement, sinon <état du plugin>/.env.
plugin_token() {
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        printf '%s' "$TELEGRAM_BOT_TOKEN"
    else
        read_env_token "$TG_DIR/.env"
    fi
}

# Fichier du jeton du bot « un geste » ([telegram].token_file, « ~ » développé).
bot_token_file() {
    local file
    file="$(toml_get telegram token_file "$HOME/.config/ai-running-coach/telegram.env")"
    case "$file" in
        \~) file="$HOME" ;;
        \~/*) file="$HOME/${file#\~/}" ;;
    esac
    printf '%s' "$file"
}

# Deux processus en long polling (getUpdates) sur le même bot se coupent l'un l'autre (erreur 409
# « Conflict ») : le plugin Channels exige son PROPRE bot. Refus net, sans afficher aucun jeton.
require_distinct_bot() {
    local chat_token bot_token
    chat_token="$(plugin_token)"
    [[ -n "$chat_token" ]] || return 0
    bot_token="$(read_env_token "$(bot_token_file)")"
    if [[ -n "$bot_token" && "$chat_token" == "$bot_token" ]]; then
        die "Le jeton du plugin Telegram (Channels) est identique à celui du bot [telegram] ($(bot_token_file)).
  Deux processus en long polling sur le même bot provoquent l'erreur 409 (Conflict) : aucun ne reçoit les messages.
  Créez un second bot avec @BotFather (/newbot), puis dans Claude Code : /telegram:configure <jeton du second bot>."
    fi
}

# Version de Claude Code >= MIN_CLAUDE (hook en échec fermé : « onFailure »).
claude_version_ok() {
    local version maj min pat
    version="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)"
    [[ -n "$version" ]] || return 1
    IFS=. read -r maj min pat <<< "$version"
    local want_maj want_min want_pat
    IFS=. read -r want_maj want_min want_pat <<< "$MIN_CLAUDE"
    (( maj > want_maj || (maj == want_maj && (min > want_min || (min == want_min && pat >= want_pat))) ))
}

# Groupes de access.json sans liste allowFrom (n'importe quel membre pourrait alors parler au coach) :
# affiche leur nombre, ou « illisible » si le fichier ou sa structure est invalide (échec fermé, comme dm_policy).
open_groups() {
    [[ -f "$TG_DIR/access.json" ]] || { echo 0; return 0; }
    python3 -c '
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(data, dict) or (groups is not None and not isinstance(groups, dict)):
        raise ValueError("structure")
    if any(not isinstance(g, dict) for g in (groups or {}).values()):
        raise ValueError("groupe")
    print(sum(1 for g in (groups or {}).values() if not (isinstance(g.get("allowFrom"), list) and g["allowFrom"])))
except Exception:
    print("illisible")
' "$TG_DIR/access.json" 2>/dev/null || echo "illisible"
}

require_bin() {
    have "$1" && return 0
    [[ "$DRY_RUN" -eq 1 ]] && { warn "$1 introuvable (ignoré en dry-run) — $2"; return 0; }
    die "$1 introuvable — $2"
}

preflight() {
    require_bin claude "installez Claude Code : curl -fsSL https://claude.ai/install.sh | bash"
    require_bin bun "le plugin Telegram en a besoin : curl -fsSL https://bun.sh/install | bash"
    have claude && check_login
    if have claude && ! claude_version_ok; then
        [[ "$DRY_RUN" -eq 1 ]] && warn "Claude Code < $MIN_CLAUDE (ignoré en dry-run)." \
            || die "Claude Code >= $MIN_CLAUDE requis (hook en échec fermé) : mettez-le à jour (claude update)."
    fi
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" || -f "$TG_DIR/.env" ]] \
        || die "Token du bot absent ($TG_DIR/.env). Dans Claude Code : /plugin install telegram@claude-plugins-official puis /telegram:configure <token>."
    # Mode passerelle : un seul outil (mcp__leanproxy__…) porte lecture, envoi ET suppression, sans nom
    # qui permette de les distinguer. Les réglages et le hook refusent « leanproxy » ; le laisser
    # déclaré rendrait la session inutilisable. Pas de compromis sûr : refus.
    if grep -qs '"leanproxy"[[:space:]]*:' "$ARC_WORKSPACE/.mcp.json"; then
        die "Mode passerelle leanproxy détecté ($ARC_WORKSPACE/.mcp.json) : incompatible avec le coach sur Telegram.
  Réinstallez en mode direct (./install.sh sans --use-leanproxy), ou utilisez Remote Control."
    fi
    require_distinct_bot
    case "$PERMISSION_MODE" in
        default|plan) ;;
        acceptEdits) warn "[telegram_chat].permission_mode = acceptEdits : toute écriture du workspace est validée d'office, hors du périmètre de templates/settings.telegram.json." ;;
        *) die "[telegram_chat].permission_mode invalide : « $PERMISSION_MODE » (default, plan ou acceptEdits ; bypassPermissions est refusé)." ;;
    esac
    local policy
    policy="$(dm_policy)"
    if [[ "$PAIRING" -eq 0 ]]; then
        local groups
        groups="$(open_groups)"
        [[ "$groups" != "illisible" ]] \
            || die "$TG_DIR/access.json est illisible ou de structure invalide (groupes) : refus de démarrer. Corrigez-le avec /telegram:access."
        [[ "$groups" == "0" ]] \
            || die "Un groupe de $TG_DIR/access.json n'a pas de liste allowFrom : n'importe quel membre pourrait parler au coach.
  Dans la session d'appairage : /telegram:access (retirez le groupe ou renseignez allowFrom)."
    fi
    if [[ "$policy" != "allowlist" && "$PAIRING" -eq 0 ]]; then
        die "Politique d'accès du bot : « $policy ». Appairez d'abord votre compte :
  scripts/coach-telegram-chat.sh run --pairing
  → écrivez au bot, puis dans la session : /telegram:access pair <code>
  → puis : /telegram:access policy allowlist"
    fi
}

# Une seule session longue par workspace, idéalement : deux sessions qui
# écrivent les mêmes fichiers MD se marchent dessus. Simple avertissement.
warn_if_remote_control_runs() {
    if (have systemctl && systemctl --user is-active --quiet ai-running-coach-remote 2>/dev/null) \
        || (have tmux && tmux has-session -t coach-remote 2>/dev/null) \
        || (have screen && grep -q coach-remote <<<"$(screen -ls 2>/dev/null)"); then
        warn "Remote Control tourne aussi (scripts/coach-remote.sh) : évitez de travailler sur les mêmes fichiers depuis les deux à la fois."
    fi
}

# Comment le service est géré sur cette machine.
# NE JAMAIS appeler « die » ici (utilisé en substitution de commande, voir
# coach-remote.sh) : on renvoie un statut.
backend() {
    have tmux || { echo none; return 1; }
    if [[ "$OS" == "Darwin" ]]; then echo launchd; return 0
    elif have systemctl && systemctl --user show-environment >/dev/null 2>&1; then echo systemd; return 0
    fi
    echo tmux
    return 0
}
NO_BACKEND_MSG="tmux introuvable : la session interactive de Claude Code a besoin d'un terminal (installez tmux)."

# ---------------------------------------------------------------------------
# run / supervise — premier plan
# ---------------------------------------------------------------------------
do_run() {
    preflight
    cd "$ARC_WORKSPACE"
    log "Session Telegram (Channels, expérimental) — workspace : $ARC_WORKSPACE ($PERMISSION_MODE)"
    local settings_args=()
    if [[ "$PAIRING" -eq 1 ]]; then
        log "Appairage (sans les réglages restrictifs de la conversation) : écrivez au bot, puis tapez ici /telegram:access pair <code> et /telegram:access policy allowlist. Ensuite Ctrl+C deux fois."
        log "1er démarrage : acceptez ici la confiance du dossier et le consentement MCP (ces dialogues ne sont PAS relayés à Telegram), au besoin via : tmux -L $TMUX_SESSION attach -t $TMUX_SESSION"
    else
        require_settings
        settings_args=(--settings "$CHAT_SETTINGS")
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        run claude ${settings_args[@]+"${settings_args[@]}"} --channels "$CHANNEL" --permission-mode "$PERMISSION_MODE" --append-system-prompt "…"
        return 0
    fi
    exec claude ${settings_args[@]+"${settings_args[@]}"} --channels "$CHANNEL" --permission-mode "$PERMISSION_MODE" --append-system-prompt "$SYSTEM_HINT"
}

# Boucle lancée dans tmux : relance la session si elle s'arrête (crash, /exit).
do_supervise() {
    mkdir -p "$LOG_DIR"
    while :; do
        echo "===== $(date '+%F %T') — démarrage de la session Telegram =====" >> "$LOG_FILE"
        "$SELF" run || echo "===== $(date '+%F %T') — session terminée (code $?) =====" >> "$LOG_FILE"
        sleep 30
    done
}

tmux_start() {
    if tmux -L "$TMUX_SESSION" has-session -t "$TMUX_SESSION" 2>/dev/null; then
        ok "Session tmux $TMUX_SESSION déjà active."
        return 0
    fi
    run tmux -L "$TMUX_SESSION" new-session -d -s "$TMUX_SESSION" -c "$ARC_WORKSPACE" "'$SELF' supervise"
}

tmux_stop() {
    if tmux -L "$TMUX_SESSION" has-session -t "$TMUX_SESSION" 2>/dev/null; then
        run tmux -L "$TMUX_SESSION" kill-session -t "$TMUX_SESSION"
    fi
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------
# Fichier de réglages dédié, régénéré à chaque installation (settings.local.json n'est jamais touché).
install_permissions() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} écriture de $CHAT_SETTINGS (depuis $SETTINGS_TEMPLATE)"
        return 0
    fi
    local tg_phys python_bin
    tg_phys="$(cd "$TG_DIR" 2>/dev/null && pwd -P || printf '%s' "$TG_DIR")"
    python_bin="$(command -v python3)"
    python3 "$ENGINE_PHYS/scripts/coach_config.py" render-settings \
        --template "$SETTINGS_TEMPLATE" --out "$CHAT_SETTINGS" \
        --var "PYTHON=$python_bin" --var "HOOK=$HOOK_SCRIPT" --var "ENGINE_ABS=/$ENGINE_PHYS" \
        --var "TG_ABS=/$tg_phys" --var "INBOX_ABS=/$tg_phys/inbox"
    ok "Réglages de la session Telegram : $CHAT_SETTINGS (passés à cette session seulement ; lectures libres, écritures Garmin/COROS/intervals.icu soumises à approbation, suppressions interdites)"
}

# Les réglages dédiés sont obligatoires (restrictions, hook en échec fermé) : jamais de session sans eux.
require_settings() {
    [[ -f "$CHAT_SETTINGS" ]] && return 0
    [[ "$DRY_RUN" -eq 1 ]] && { warn "$CHAT_SETTINGS absent (ignoré en dry-run)."; return 0; }
    die "Réglages de la session absents ($CHAT_SETTINGS) : lancez d'abord scripts/coach-telegram-chat.sh install."
}

# Échappements systemd (unité écrite à la main) : « % » est un spécificateur (%%) ; dans ExecStart/ExecStop,
# « $ » ouvre une expansion ($$) et « \ » / « " » sont traités par le découpage en mots entre guillemets.
sd_escape_path() { printf '%s' "$1" | sed -e 's/%/%%/g'; }
sd_escape_env() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/%/%%/g'; }
sd_escape_exec() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/%/%%/g' -e 's/\$/$$/g'; }
# Mot protégé pour le shell que tmux lance (le chemin de ce script peut contenir une apostrophe).
sh_quote() { printf "'%s'" "$(printf '%s' "$1" | sed -e "s/'/'\\\\''/g")"; }

# Variables d'environnement à propager au service (le plugin lit TELEGRAM_STATE_DIR / CLAUDE_CONFIG_DIR).
extra_env_systemd() {
    [[ -z "${TELEGRAM_STATE_DIR:-}" ]] || printf 'Environment="TELEGRAM_STATE_DIR=%s"\n' "$(sd_escape_env "$TELEGRAM_STATE_DIR")"
    [[ -z "${CLAUDE_CONFIG_DIR:-}" ]] || printf 'Environment="CLAUDE_CONFIG_DIR=%s"\n' "$(sd_escape_env "$CLAUDE_CONFIG_DIR")"
}

extra_env_plist() {
    [[ -z "${TELEGRAM_STATE_DIR:-}" ]] || printf '    <key>TELEGRAM_STATE_DIR</key><string>%s</string>\n' "$(xml_escape "$TELEGRAM_STATE_DIR")"
    [[ -z "${CLAUDE_CONFIG_DIR:-}" ]] || printf '    <key>CLAUDE_CONFIG_DIR</key><string>%s</string>\n' "$(xml_escape "$CLAUDE_CONFIG_DIR")"
}

valid_time() { [[ "$1" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; }

install_systemd() {
    local sd_ws sd_tmux sd_systemctl sd_path sd_home sd_cmd
    sd_ws="$(sd_escape_exec "$ARC_WORKSPACE")"
    sd_tmux="$(sd_escape_exec "$(command -v tmux)")"
    sd_systemctl="$(sd_escape_exec "$(command -v systemctl)")"
    sd_cmd="$(sd_escape_exec "$(sh_quote "$SELF") supervise")"
    sd_path="$(sd_escape_env "$HOME/.local/bin:$HOME/.claude/bin:$HOME/.bun/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin")"
    sd_home="$(sd_escape_env "$HOME")"
    write_file "$SYSTEMD_DIR/$SERVICE_NAME.service" <<EOT
[Unit]
Description=ai-running-coach — coach sur Telegram (Claude Code Channels, dans tmux)
After=network-online.target
Wants=network-online.target

[Service]
# La session Claude Code est interactive : elle vit dans tmux, qui relance
# elle-même la session en cas d'arrêt (coach-telegram-chat.sh supervise).
Type=forking
WorkingDirectory=$(sd_escape_path "$ARC_WORKSPACE")
Environment="PATH=$sd_path"
Environment="HOME=$sd_home"
Environment="ARC_WORKSPACE=$(sd_escape_env "$ARC_WORKSPACE")"
$(extra_env_systemd)
ExecStart="$sd_tmux" -L $TMUX_SESSION new-session -d -s $TMUX_SESSION -c "$sd_ws" "$sd_cmd"
ExecStop="$sd_tmux" -L $TMUX_SESSION kill-session -t $TMUX_SESSION
RemainAfterExit=yes

[Install]
WantedBy=default.target
EOT
    if [[ -n "$DAILY_RESTART" ]]; then
        valid_time "$DAILY_RESTART" || die "[telegram_chat].daily_restart invalide : « $DAILY_RESTART » (HH:MM attendu, ou \"\" pour désactiver)"
        write_file "$SYSTEMD_DIR/$SERVICE_NAME-restart.service" <<EOT
[Unit]
Description=ai-running-coach — redémarrage quotidien de la session Telegram (contexte neuf)

[Service]
Type=oneshot
ExecStart="$sd_systemctl" --user restart $SERVICE_NAME.service
EOT
        write_file "$SYSTEMD_DIR/$SERVICE_NAME-restart.timer" <<EOT
[Unit]
Description=ai-running-coach — redémarrage quotidien de la session Telegram

[Timer]
OnCalendar=*-*-* $DAILY_RESTART:00
Persistent=false

[Install]
WantedBy=timers.target
EOT
    fi
    # Sans « linger », les services utilisateur meurent à la déconnexion SSH.
    run loginctl enable-linger "$USER"
    run systemctl --user daemon-reload
    run systemctl --user enable --now "$SERVICE_NAME"
    if [[ -n "$DAILY_RESTART" ]]; then
        run systemctl --user enable --now "$SERVICE_NAME-restart.timer"
        ok "Redémarrage quotidien à $DAILY_RESTART (contexte neuf)."
    fi
    ok "Service $SERVICE_NAME activé (démarre au boot)."
}

install_launchd() {
    write_file "$LAUNCHD_DIR/$LAUNCHD_LABEL.plist" <<EOT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$(xml_escape "$SELF")</string><string>start</string></array>
  <!-- le serveur tmux lancé par « start » doit survivre à la fin du job -->
  <key>AbandonProcessGroup</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ARC_WORKSPACE</key><string>$(xml_escape "$ARC_WORKSPACE")</string>
    <key>PATH</key><string>$HOME/.local/bin:$HOME/.claude/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$(xml_escape "$HOME")</string>
$(extra_env_plist)
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$(xml_escape "$LOG_FILE")</string>
  <key>StandardErrorPath</key><string>$(xml_escape "$LOG_FILE")</string>
</dict>
</plist>
EOT
    run launchctl bootout "gui/$(id -u)" "$LAUNCHD_DIR/$LAUNCHD_LABEL.plist" 2>/dev/null || true
    run launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_DIR/$LAUNCHD_LABEL.plist"
    if [[ -n "$DAILY_RESTART" ]]; then
        valid_time "$DAILY_RESTART" || die "[telegram_chat].daily_restart invalide : « $DAILY_RESTART » (HH:MM attendu, ou \"\" pour désactiver)"
        write_file "$LAUNCHD_DIR/$LAUNCHD_LABEL.restart.plist" <<EOT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL.restart</string>
  <key>ProgramArguments</key>
  <array><string>$(xml_escape "$SELF")</string><string>restart</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ARC_WORKSPACE</key><string>$(xml_escape "$ARC_WORKSPACE")</string>
    <key>PATH</key><string>$HOME/.local/bin:$HOME/.claude/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$(xml_escape "$HOME")</string>
$(extra_env_plist)
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$((10#${DAILY_RESTART%%:*}))</integer><key>Minute</key><integer>$((10#${DAILY_RESTART##*:}))</integer></dict>
</dict>
</plist>
EOT
        run launchctl bootout "gui/$(id -u)" "$LAUNCHD_DIR/$LAUNCHD_LABEL.restart.plist" 2>/dev/null || true
        run launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_DIR/$LAUNCHD_LABEL.restart.plist"
        ok "Redémarrage quotidien à $DAILY_RESTART (contexte neuf)."
    fi
    ok "Service $LAUNCHD_LABEL chargé (démarre à l'ouverture de session)."
    warn "macOS : empêchez la mise en veille (Réglages > Batterie, ou 'caffeinate -s') pour garder le coach joignable."
}

do_install() {
    PAIRING=0 preflight
    [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$LOG_DIR"
    install_permissions
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) install_systemd ;;
        launchd) install_launchd ;;
        tmux)
            warn "Pas de systemd --user : session tmux simple (ne survit pas au reboot, pas de redémarrage quotidien)."
            tmux_start ;;
    esac
    warn_if_remote_control_runs
    echo
    log "Écrivez au bot depuis Telegram : « séance du jour ? »"
    log "Si la session attend une confiance de dossier ou un consentement MCP (jamais relayés à Telegram) : tmux -L $TMUX_SESSION attach -t $TMUX_SESSION"
}

do_uninstall() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd)
            run systemctl --user disable --now "$SERVICE_NAME-restart.timer" 2>/dev/null || true
            run systemctl --user disable --now "$SERVICE_NAME" || true
            run rm -f "$SYSTEMD_DIR/$SERVICE_NAME.service" "$SYSTEMD_DIR/$SERVICE_NAME-restart.service" "$SYSTEMD_DIR/$SERVICE_NAME-restart.timer"
            run systemctl --user daemon-reload ;;
        launchd)
            run launchctl bootout "gui/$(id -u)" "$LAUNCHD_DIR/$LAUNCHD_LABEL.restart.plist" 2>/dev/null || true
            run launchctl bootout "gui/$(id -u)" "$LAUNCHD_DIR/$LAUNCHD_LABEL.plist" 2>/dev/null || true
            run rm -f "$LAUNCHD_DIR/$LAUNCHD_LABEL.plist" "$LAUNCHD_DIR/$LAUNCHD_LABEL.restart.plist"
            tmux_stop ;;
        tmux) tmux_stop ;;
    esac
    run rm -f "$CHAT_SETTINGS"
    ok "Service Telegram retiré (réglages dédiés $CHAT_SETTINGS supprimés)."
}

# ---------------------------------------------------------------------------
# start / stop / status / logs
# ---------------------------------------------------------------------------
do_start() {
    require_settings
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) run systemctl --user start "$SERVICE_NAME" ;;
        launchd|tmux) tmux_start ;;
    esac
    ok "Session Telegram démarrée (tmux -L $TMUX_SESSION attach -t $TMUX_SESSION pour la voir)."
}

do_stop() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) run systemctl --user stop "$SERVICE_NAME" ;;
        launchd|tmux) tmux_stop ;;
    esac
    ok "Session Telegram arrêtée."
}

do_status() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    [[ "$chosen" == "systemd" ]] && { systemctl --user status "$SERVICE_NAME" --no-pager 2>/dev/null | head -n 5 || true; }
    if tmux -L "$TMUX_SESSION" has-session -t "$TMUX_SESSION" 2>/dev/null; then
        ok "tmux $TMUX_SESSION actif — tmux -L $TMUX_SESSION attach -t $TMUX_SESSION (détacher : Ctrl-b d)"
    else
        warn "Session tmux $TMUX_SESSION absente : le bot ne répond pas."
    fi
    log "Politique d'accès du bot : $(dm_policy)"
}

do_logs() {
    if tmux -L "$TMUX_SESSION" has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux -L "$TMUX_SESSION" capture-pane -p -t "$TMUX_SESSION" -S -50
    elif [[ -f "$LOG_FILE" ]]; then
        tail -n 50 "$LOG_FILE"
    else
        die "Aucun journal : $LOG_FILE"
    fi
}

case "$ACTION" in
    run) do_run ;;
    supervise) do_supervise ;;
    install) do_install ;;
    uninstall) do_uninstall ;;
    start) do_start ;;
    stop) do_stop ;;
    restart) do_stop; do_start ;;
    status) do_status ;;
    logs) do_logs ;;
esac
