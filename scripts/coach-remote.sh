#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — le coach dans la poche (Claude Code Remote Control)
#
# Fait tourner `claude remote-control` (mode serveur) en permanence sur la
# machine « coach » : depuis l'appli Claude (iOS/Android) ou claude.ai/code vous
# ouvrez des sessions qui s'exécutent ICI, avec le serveur MCP garmin, les
# fichiers du workspace et les agents/skills du projet. Abonnement Claude
# (Pro/Max/Team/Enterprise) requis — pas de clé API.
#
# Usage :
#   scripts/coach-remote.sh run        # premier plan (utilisé par le service ; 1re fois : accepter la confirmation)
#   scripts/coach-remote.sh install    # service systemd --user (Linux) / launchd (macOS), démarre au boot
#   scripts/coach-remote.sh start|stop|restart|status|logs
#   scripts/coach-remote.sh uninstall
#
# Options : --name "Titre de session" (défaut : AI Running Coach)
#           --permission-mode <mode>  (défaut : acceptEdits ; les outils Garmin
#                                      d'écriture restent confirmés depuis le téléphone)
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

SESSION_NAME="AI Running Coach"
PERMISSION_MODE="acceptEdits"
DRY_RUN="${ARC_DRY_RUN:-0}"
ACTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) SESSION_NAME="$2"; shift 2 ;;
        --permission-mode) PERMISSION_MODE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        run|install|uninstall|start|stop|restart|status|logs) ACTION="$1"; shift ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done
[[ -n "$ACTION" ]] || { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

export PATH="$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SERVICE_NAME="ai-running-coach-remote"
SYSTEMD_UNIT="$HOME/.config/systemd/user/$SERVICE_NAME.service"
LAUNCHD_LABEL="com.ai-running-coach.remote"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
LOG_DIR="$ARC_PROJECT_ROOT/logs"
SCREEN_NAME="coach-remote"
OS="$(uname -s)"

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

claude_bin() {
    command -v claude && return 0
    [[ "$DRY_RUN" -eq 1 ]] && { warn >&2 "claude introuvable (ignoré en dry-run) — installez Claude Code : curl -fsSL https://claude.ai/install.sh | bash"; return 0; }
    die "claude introuvable — installez Claude Code : curl -fsSL https://claude.ai/install.sh | bash"
}

# Remote Control exige une connexion claude.ai (abonnement) — pas de clé API.
check_login() {
    local status
    status="$(claude auth status 2>/dev/null || true)"
    if printf '%s' "$status" | grep -q '"loggedIn": *true'; then
        ok "Claude Code connecté ($(printf '%s' "$status" | grep -o '"authMethod": *"[^"]*"' | cut -d'"' -f4))"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
        warn "Claude Code n'est pas connecté (ignoré en dry-run)."
    else
        die "Claude Code n'est pas connecté. Lancez 'claude' puis '/login' (compte claude.ai, pas de clé API)."
    fi
    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        die "ANTHROPIC_API_KEY est défini : Remote Control refuse l'authentification par clé API. Retirez-le de l'environnement."
    fi
}

# Comment le service est géré sur cette machine.
backend() {
    if [[ "$OS" == "Darwin" ]]; then echo launchd
    elif have systemctl && systemctl --user show-environment >/dev/null 2>&1; then echo systemd
    elif have screen || have tmux; then echo screen
    else die "Ni systemd --user, ni screen/tmux disponibles."
    fi
}

# ---------------------------------------------------------------------------
# run — premier plan
# ---------------------------------------------------------------------------
do_run() {
    claude_bin >/dev/null
    cd "$ARC_PROJECT_ROOT"
    log "Démarrage de claude remote-control — session « $SESSION_NAME » ($PERMISSION_MODE)"
    log "Projet : $ARC_PROJECT_ROOT"
    exec claude remote-control --name "$SESSION_NAME" --permission-mode "$PERMISSION_MODE"
}

# ---------------------------------------------------------------------------
# install — service permanent
# ---------------------------------------------------------------------------
install_systemd() {
    write_file "$SYSTEMD_UNIT" <<EOT
[Unit]
Description=ai-running-coach — Claude Code Remote Control (le coach dans la poche)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ARC_PROJECT_ROOT
Environment=PATH=$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
ExecStart=$ARC_PROJECT_ROOT/scripts/coach-remote.sh run --name "$SESSION_NAME" --permission-mode $PERMISSION_MODE
# Le serveur s'arrête de lui-même après ~10 min sans joindre claude.ai :
# on le relance, il reprend ses sessions (fenêtre ~4 h).
Restart=always
RestartSec=30
StandardOutput=append:$LOG_DIR/remote-control.log
StandardError=append:$LOG_DIR/remote-control.log

[Install]
WantedBy=default.target
EOT
    ok "Unité écrite : $SYSTEMD_UNIT"
    # Sans « linger », les services utilisateur meurent à la déconnexion SSH.
    run loginctl enable-linger "$USER"
    run systemctl --user daemon-reload
    run systemctl --user enable --now "$SERVICE_NAME"
    ok "Service $SERVICE_NAME activé (démarre au boot). Journal : $LOG_DIR/remote-control.log"
}

install_launchd() {
    write_file "$LAUNCHD_PLIST" <<EOT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ARC_PROJECT_ROOT/scripts/coach-remote.sh</string>
    <string>run</string>
    <string>--name</string><string>$SESSION_NAME</string>
    <string>--permission-mode</string><string>$PERMISSION_MODE</string>
  </array>
  <key>WorkingDirectory</key><string>$ARC_PROJECT_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:$HOME/.claude/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/remote-control.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/remote-control.log</string>
</dict>
</plist>
EOT
    ok "LaunchAgent écrit : $LAUNCHD_PLIST"
    run launchctl bootout "gui/$(id -u)" "$LAUNCHD_PLIST" 2>/dev/null || true
    run launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_PLIST"
    ok "Service $LAUNCHD_LABEL chargé (démarre à l'ouverture de session). Journal : $LOG_DIR/remote-control.log"
    warn "macOS : empêchez la mise en veille (Réglages > Batterie, ou 'caffeinate -s') pour garder le coach joignable."
}

install_screen() {
    warn "Pas de systemd --user : lancement dans une session screen/tmux (ne survit pas au reboot)."
    do_start
}

do_install() {
    claude_bin >/dev/null
    check_login
    [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$LOG_DIR"
    if [[ -t 0 && "$DRY_RUN" -eq 0 ]]; then
        echo
        warn "Première utilisation : Remote Control demande une confirmation unique (Enable Remote Control? y/n)"
        warn "qui ne peut pas être acceptée par un service en arrière-plan."
        read -r -p "Avez-vous déjà accepté cette confirmation sur cette machine ? [o/N] : " yn
        if [[ ! "${yn:-n}" =~ ^[oOyY]$ ]]; then
            log "Lancement interactif : répondez 'y', attendez « Remote Control session started », puis Ctrl+C."
            (cd "$ARC_PROJECT_ROOT" && claude remote-control --name "$SESSION_NAME" --permission-mode "$PERMISSION_MODE") || true
        fi
    fi
    case "$(backend)" in
        systemd) install_systemd ;;
        launchd) install_launchd ;;
        screen)  install_screen ;;
    esac
    echo
    log "Sur le téléphone : appli Claude → onglet Code → la session « $SESSION_NAME » apparaît."
    log "Pour un QR code : 'scripts/coach-remote.sh logs' (URL imprimée au démarrage) ou lancez 'claude remote-control' à la main."
}

do_uninstall() {
    case "$(backend)" in
        systemd)
            run systemctl --user disable --now "$SERVICE_NAME" || true
            run rm -f "$SYSTEMD_UNIT"
            run systemctl --user daemon-reload ;;
        launchd)
            run launchctl bootout "gui/$(id -u)" "$LAUNCHD_PLIST" || true
            run rm -f "$LAUNCHD_PLIST" ;;
        screen) do_stop ;;
    esac
    ok "Service Remote Control retiré."
}

# ---------------------------------------------------------------------------
# start / stop / status / logs
# ---------------------------------------------------------------------------
do_start() {
    case "$(backend)" in
        systemd) run systemctl --user start "$SERVICE_NAME" ;;
        launchd) run launchctl kickstart "gui/$(id -u)/$LAUNCHD_LABEL" ;;
        screen)
            mkdir -p "$LOG_DIR"
            if have screen; then
                run screen -dmS "$SCREEN_NAME" -L -Logfile "$LOG_DIR/remote-control.log" "$0" run --name "$SESSION_NAME" --permission-mode "$PERMISSION_MODE"
            else
                run tmux new-session -d -s "$SCREEN_NAME" "$0 run --name '$SESSION_NAME' --permission-mode $PERMISSION_MODE 2>&1 | tee -a '$LOG_DIR/remote-control.log'"
            fi ;;
    esac
    ok "Remote Control démarré."
}

do_stop() {
    case "$(backend)" in
        systemd) run systemctl --user stop "$SERVICE_NAME" ;;
        launchd) run launchctl kill SIGTERM "gui/$(id -u)/$LAUNCHD_LABEL" ;;
        screen)
            if have screen; then run screen -S "$SCREEN_NAME" -X quit || true
            else run tmux kill-session -t "$SCREEN_NAME" || true; fi ;;
    esac
    ok "Remote Control arrêté (les sessions restent reprenables ~4 h)."
}

do_status() {
    case "$(backend)" in
        systemd) systemctl --user status "$SERVICE_NAME" --no-pager || true ;;
        launchd) launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null | grep -E "state|pid|last exit" || warn "Service non chargé." ;;
        screen)
            if have screen; then screen -ls | grep -q "$SCREEN_NAME" && ok "screen $SCREEN_NAME actif" || warn "Non démarré."
            else tmux has-session -t "$SCREEN_NAME" 2>/dev/null && ok "tmux $SCREEN_NAME actif" || warn "Non démarré."; fi ;;
    esac
    if [[ -f "$LOG_DIR/remote-control.log" ]]; then
        echo; log "Dernière URL de session :"
        grep -o 'https://claude.ai/code/[A-Za-z0-9_-]*' "$LOG_DIR/remote-control.log" | tail -1 || warn "(aucune URL trouvée dans le journal)"
    fi
}

do_logs() {
    [[ -f "$LOG_DIR/remote-control.log" ]] || die "Aucun journal : $LOG_DIR/remote-control.log"
    tail -n 50 "$LOG_DIR/remote-control.log"
}

case "$ACTION" in
    run) do_run ;;
    install) do_install ;;
    uninstall) do_uninstall ;;
    start) do_start ;;
    stop) do_stop ;;
    restart) do_stop; do_start ;;
    status) do_status ;;
    logs) do_logs ;;
esac
