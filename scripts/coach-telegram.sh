#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — service du bot Telegram (scripts/arc_telegram.py, #174)
#
# Fait tourner en permanence, sur la machine « coach », le bot Telegram :
# `python3 scripts/arc_telegram.py run --workspace <workspace>`. Interrogation périodique
# (long polling) de l'API Telegram : aucune adresse publique à exposer. Retours en un geste
# (boutons du résumé quotidien, /rpe, /douleur, /statut) SANS modèle ni clé d'API ; conversation
# libre seulement si [telegram].chat_bridge = true (docs/telegram.md).
#
# Le jeton du bot vit dans ~/.config/ai-running-coach/telegram.env (mode 600), jamais dans
# le TOML : le service le lit lui-même ([telegram].token_file) et ne l'écrit jamais dans
# ses journaux. Aucune clé n'est passée par l'unité de service.
#
# Usage :
#   scripts/coach-telegram.sh run        # premier plan (utilisé par le service)
#   scripts/coach-telegram.sh install    # service systemd --user (Linux) / launchd (macOS), démarre au boot
#   scripts/coach-telegram.sh start|stop|restart|status|logs
#   scripts/coach-telegram.sh uninstall
#   scripts/coach-telegram.sh --dry-run install   # affiche sans rien écrire ni lancer
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

DRY_RUN="${ARC_DRY_RUN:-0}"
ACTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        run|install|uninstall|start|stop|restart|status|logs) ACTION="$1"; shift ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done
[[ -n "$ACTION" ]] || { sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

export PATH="$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SERVICE_NAME="ai-running-coach-telegram"
SYSTEMD_UNIT="$HOME/.config/systemd/user/$SERVICE_NAME.service"
LAUNCHD_LABEL="com.ai-running-coach.telegram"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
LOG_DIR="$ARC_WORKSPACE/logs"
LOG_FILE="$LOG_DIR/telegram.log"
SCREEN_NAME="coach-telegram"
TOKEN_FILE_DEFAULT="$HOME/.config/ai-running-coach/telegram.env"
BOT_SCRIPT="$ARC_ENGINE_ROOT/scripts/arc_telegram.py"
# uname : ARC_FAKE_UNAME est le levier des tests (tests/README.md), comme le stub uname.
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

# Échappe une chaîne pour l'insérer dans du XML (plist launchd).
xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

python_bin() {
    command -v python3 && return 0
    [[ "$DRY_RUN" -eq 1 ]] && { warn >&2 "python3 introuvable (ignoré en dry-run)."; return 0; }
    die "python3 introuvable."
}

# Comment le service est géré sur cette machine (voir coach-remote.sh : jamais de
# « die » ici, backend est appelé en substitution de commande).
backend() {
    if [[ "$OS" == "Darwin" ]]; then echo launchd; return 0
    elif have systemctl && systemctl --user show-environment >/dev/null 2>&1; then echo systemd; return 0
    elif have screen || have tmux; then echo screen; return 0
    fi
    echo none
    return 1
}

NO_BACKEND_MSG="Ni systemd --user, ni screen/tmux disponibles sur cette machine — service impossible."

# ---------------------------------------------------------------------------
# run — premier plan
# ---------------------------------------------------------------------------
do_run() {
    local py
    py="$(python_bin)"
    [[ -f "$BOT_SCRIPT" ]] || die "Service introuvable : $BOT_SCRIPT"
    cd "$ARC_WORKSPACE"
    log "Démarrage du bot Telegram (workspace : $ARC_WORKSPACE, moteur : $ARC_ENGINE_ROOT)"
    exec "$py" "$BOT_SCRIPT" run --workspace "$ARC_WORKSPACE"
}

# ---------------------------------------------------------------------------
# install — service permanent
# ---------------------------------------------------------------------------
install_systemd() {
    # Aucun EnvironmentFile : le service lit lui-même le fichier du jeton ([telegram].token_file).
    write_file "$SYSTEMD_UNIT" <<EOT
[Unit]
Description=ai-running-coach — bot Telegram (arc_telegram.py)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ARC_WORKSPACE
Environment=PATH=$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
Environment=ARC_WORKSPACE=$ARC_WORKSPACE
ExecStart=$ARC_ENGINE_ROOT/scripts/coach-telegram.sh run
Restart=always
RestartSec=10
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=default.target
EOT
    ok "Unité écrite : $SYSTEMD_UNIT"
    # Sans « linger », les services utilisateur meurent à la déconnexion SSH.
    run loginctl enable-linger "$USER"
    run systemctl --user daemon-reload
    run systemctl --user enable --now "$SERVICE_NAME"
    ok "Service $SERVICE_NAME activé (démarre au boot). Journal : $LOG_FILE"
    warn "Linux : « loginctl enable-linger $USER » garde le service actif après la déconnexion SSH (déjà demandé ci-dessus ; vérifiez avec « loginctl show-user $USER | grep Linger »)."
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
    <string>$(xml_escape "$ARC_ENGINE_ROOT")/scripts/coach-telegram.sh</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml_escape "$ARC_WORKSPACE")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ARC_WORKSPACE</key><string>$(xml_escape "$ARC_WORKSPACE")</string>
    <key>PATH</key><string>$(xml_escape "$HOME")/.local/bin:$(xml_escape "$HOME")/.claude/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$(xml_escape "$HOME")</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$(xml_escape "$LOG_FILE")</string>
  <key>StandardErrorPath</key><string>$(xml_escape "$LOG_FILE")</string>
</dict>
</plist>
EOT
    ok "LaunchAgent écrit : $LAUNCHD_PLIST"
    run launchctl bootout "gui/$(id -u)" "$LAUNCHD_PLIST" 2>/dev/null || true
    run launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_PLIST"
    ok "Service $LAUNCHD_LABEL chargé (démarre à l'ouverture de session). Journal : $LOG_FILE"
    warn "macOS : empêchez la mise en veille (Réglages > Batterie, ou 'caffeinate -s') pour garder le bot joignable."
}

install_screen() {
    warn "Pas de systemd --user : lancement dans une session screen/tmux (ne survit pas au reboot)."
    do_start
}

do_install() {
    python_bin >/dev/null
    [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$LOG_DIR"
    if [[ "$(toml_get telegram enabled false)" != "true" ]]; then
        warn "[telegram].enabled n'est pas « true » : activez-le (./install.sh --telegram, ou dans config/workspace.user.toml)."
    fi
    local token_file
    token_file="$(expand_path "$(toml_get telegram token_file "$TOKEN_FILE_DEFAULT")")"
    if [[ ! -f "$token_file" ]]; then
        warn "$token_file absent : le service ne démarrera pas sans jeton (docs/telegram.md, étape BotFather)."
    fi
    if [[ -z "$(toml_get telegram allowed_chat_ids)" || "$(toml_get telegram allowed_chat_ids)" == "[]" ]]; then
        warn "[telegram].allowed_chat_ids est vide : tout sera refusé (python3 scripts/arc_telegram.py whoami)."
    fi
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) install_systemd ;;
        launchd) install_launchd ;;
        screen)  install_screen ;;
    esac
    echo
    log "Vérifier : scripts/coach-telegram.sh status   (journal : scripts/coach-telegram.sh logs)"
}

do_uninstall() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd)
            run systemctl --user disable --now "$SERVICE_NAME" || true
            run rm -f "$SYSTEMD_UNIT"
            run systemctl --user daemon-reload ;;
        launchd)
            run launchctl bootout "gui/$(id -u)" "$LAUNCHD_PLIST" || true
            run rm -f "$LAUNCHD_PLIST" ;;
        screen) do_stop ;;
    esac
    ok "Service du bot Telegram retiré."
}

# ---------------------------------------------------------------------------
# start / stop / status / logs
# ---------------------------------------------------------------------------
do_start() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) run systemctl --user start "$SERVICE_NAME" ;;
        launchd) run launchctl kickstart "gui/$(id -u)/$LAUNCHD_LABEL" ;;
        screen)
            [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$LOG_DIR"
            if have screen; then
                run screen -dmS "$SCREEN_NAME" -L -Logfile "$LOG_FILE" "$0" run
            else
                run tmux new-session -d -s "$SCREEN_NAME" "$0 run 2>&1 | tee -a '$LOG_FILE'"
            fi ;;
    esac
    ok "Bot Telegram démarré."
}

do_stop() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) run systemctl --user stop "$SERVICE_NAME" ;;
        launchd) run launchctl kill SIGTERM "gui/$(id -u)/$LAUNCHD_LABEL" ;;
        screen)
            if have screen; then run screen -S "$SCREEN_NAME" -X quit || true
            else run tmux kill-session -t "$SCREEN_NAME" || true; fi ;;
    esac
    ok "Bot Telegram arrêté."
}

do_status() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) systemctl --user status "$SERVICE_NAME" --no-pager || true ;;
        launchd) launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null | grep -E "state|pid|last exit" || warn "Service non chargé." ;;
        screen)
            if have screen; then screen -ls | grep -q "$SCREEN_NAME" && ok "screen $SCREEN_NAME actif" || warn "Non démarré."
            else tmux has-session -t "$SCREEN_NAME" 2>/dev/null && ok "tmux $SCREEN_NAME actif" || warn "Non démarré."; fi ;;
    esac
}

do_logs() {
    [[ -f "$LOG_FILE" ]] || die "Aucun journal : $LOG_FILE"
    tail -n 50 "$LOG_FILE"
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
