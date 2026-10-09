#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — service du chat avec le coach (scripts/arc_chat.py)
#
# Fait tourner en permanence, sur la machine « coach », le service HTTP du chat
# du tableau de bord (docs/dashboard/chat.md) : `python3 scripts/arc_chat.py
# --workspace <workspace>`. Le service lit sa configuration dans la section
# [chat] de config/workspace.toml (port, écoute, authentification…).
#
# La clé API du fournisseur (Anthropic, OpenRouter…) vit dans
# ~/.config/ai-running-coach/llm.env (mode 600), jamais dans le TOML ni dans
# votre shell : systemd la charge par EnvironmentFile=, `run` la lit pour
# launchd/screen. Ne l'exportez surtout pas globalement : ANTHROPIC_API_KEY casse
# Remote Control (docs/mobile.md).
#
# Usage :
#   scripts/coach-chat.sh run        # premier plan (utilisé par le service)
#   scripts/coach-chat.sh install    # service systemd --user (Linux) / launchd (macOS), démarre au boot
#   scripts/coach-chat.sh start|stop|restart|status|logs
#   scripts/coach-chat.sh uninstall
#   scripts/coach-chat.sh --dry-run install   # affiche sans rien écrire ni lancer
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"

DRY_RUN="${ARC_DRY_RUN:-0}"
ACTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        run|install|uninstall|start|stop|restart|status|logs) ACTION="$1"; shift ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done
[[ -n "$ACTION" ]] || { sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SERVICE_NAME="ai-running-coach-chat"
SYSTEMD_UNIT="$HOME/.config/systemd/user/$SERVICE_NAME.service"
LAUNCHD_LABEL="com.ai-running-coach.chat"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
LOG_DIR="$ARC_WORKSPACE/logs"
LOG_FILE="$LOG_DIR/chat.log"
SCREEN_NAME="coach-chat"
LLM_ENV_FILE="${ARC_LLM_ENV:-$HOME/.config/ai-running-coach/llm.env}"
CHAT_SCRIPT="$ARC_ENGINE_ROOT/scripts/arc_chat.py"
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

# Charge la clé du fournisseur dans l'environnement de CE process (celui qui va
# être remplacé par arc_chat.py via exec) : lignes NOM=valeur de llm.env, sans
# écraser une variable déjà présente, sans jamais rien afficher.
load_llm_env() {
    [[ -f "$LLM_ENV_FILE" ]] || return 0
    if [[ -n "$(find "$LLM_ENV_FILE" -maxdepth 0 -perm -077 2>/dev/null)" ]]; then
        warn "$LLM_ENV_FILE est lisible par d'autres utilisateurs — chmod 600 \"$LLM_ENV_FILE\"" >&2
    fi
    local line name value
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        name="${BASH_REMATCH[2]}"
        value="${BASH_REMATCH[3]}"
        if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
        [[ -n "$value" && -z "${!name:-}" ]] || continue
        export "$name=$value"
    done < "$LLM_ENV_FILE"
}

# ---------------------------------------------------------------------------
# run — premier plan
# ---------------------------------------------------------------------------
do_run() {
    local py
    py="$(python_bin)"
    [[ -f "$CHAT_SCRIPT" ]] || die "Service introuvable : $CHAT_SCRIPT"
    cd "$ARC_WORKSPACE"
    load_llm_env
    log "Démarrage du chat coach (workspace : $ARC_WORKSPACE, moteur : $ARC_ENGINE_ROOT)"
    exec "$py" "$CHAT_SCRIPT" --workspace "$ARC_WORKSPACE"
}

# ---------------------------------------------------------------------------
# install — service permanent
# ---------------------------------------------------------------------------
install_systemd() {
    # EnvironmentFile=- : le tiret rend le fichier optionnel. Il porte la clé API.
    write_file "$SYSTEMD_UNIT" <<EOT
[Unit]
Description=ai-running-coach — chat avec le coach (arc_chat.py)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ARC_WORKSPACE
Environment=PATH=$HOME/.local/bin:$HOME/.opencode/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
Environment=ARC_WORKSPACE=$ARC_WORKSPACE
EnvironmentFile=-$LLM_ENV_FILE
ExecStart=$ARC_ENGINE_ROOT/scripts/coach-chat.sh run
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
    # launchd n'a pas d'équivalent d'EnvironmentFile : `run` lit llm.env lui-même.
    write_file "$LAUNCHD_PLIST" <<EOT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml_escape "$ARC_ENGINE_ROOT")/scripts/coach-chat.sh</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml_escape "$ARC_WORKSPACE")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ARC_WORKSPACE</key><string>$(xml_escape "$ARC_WORKSPACE")</string>
    <key>PATH</key><string>$(xml_escape "$HOME")/.local/bin:$(xml_escape "$HOME")/.opencode/bin:$(xml_escape "$HOME")/.claude/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
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
    warn "macOS : empêchez la mise en veille (Réglages > Batterie, ou 'caffeinate -s') pour garder le chat joignable."
}

install_screen() {
    warn "Pas de systemd --user : lancement dans une session screen/tmux (ne survit pas au reboot)."
    do_start
}

do_install() {
    python_bin >/dev/null
    [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$LOG_DIR"
    if [[ "$(toml_get chat enabled false)" != "true" ]]; then
        warn "[chat].enabled n'est pas « true » : activez-le (./install.sh --chat, ou dans config/workspace.user.toml)."
    fi
    if [[ ! -f "$LLM_ENV_FILE" ]]; then
        warn "$LLM_ENV_FILE absent : le service démarrera sans clé API (./install.sh --llm … le crée)."
    fi
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) install_systemd ;;
        launchd) install_launchd ;;
        screen)  install_screen ;;
    esac
    echo
    log "Vérifier : scripts/coach-chat.sh status   (santé : http://127.0.0.1:$(toml_get chat port 8766)/api/chat/healthz)"
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
    ok "Service du chat retiré."
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
    ok "Chat coach démarré."
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
    ok "Chat coach arrêté."
}

do_status() {
    local chosen port
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    port="$(toml_get chat port 8766)"
    case "$chosen" in
        systemd) systemctl --user status "$SERVICE_NAME" --no-pager || true ;;
        launchd) launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null | grep -E "state|pid|last exit" || warn "Service non chargé." ;;
        screen)
            if have screen; then screen -ls | grep -q "$SCREEN_NAME" && ok "screen $SCREEN_NAME actif" || warn "Non démarré."
            else tmux has-session -t "$SCREEN_NAME" 2>/dev/null && ok "tmux $SCREEN_NAME actif" || warn "Non démarré."; fi ;;
    esac
    if have curl; then
        if curl -fsS --max-time 3 "http://127.0.0.1:$port/api/chat/healthz" >/dev/null 2>&1; then
            ok "healthz joignable (http://127.0.0.1:$port/api/chat/healthz)"
        else
            warn "healthz injoignable sur 127.0.0.1:$port (service arrêté, ou [chat].listen différent)."
        fi
    fi
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
