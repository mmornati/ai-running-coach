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
#   scripts/coach-remote.sh start|stop|restart|status|logs|url
#   scripts/coach-remote.sh rotate-log # rotation du journal (lancée chaque heure par le service)
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
        --help|-h) sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        run|install|uninstall|start|stop|restart|status|logs|url|rotate-log) ACTION="$1"; shift ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done
[[ -n "$ACTION" ]] || { sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

export PATH="$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SERVICE_NAME="ai-running-coach-remote"
SYSTEMD_UNIT="$HOME/.config/systemd/user/$SERVICE_NAME.service"
LAUNCHD_LABEL="com.ai-running-coach.remote"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
LOG_DIR="$ARC_WORKSPACE/logs"
SCREEN_NAME="coach-remote"
REMOTE_LOG="$LOG_DIR/remote-control.log"
# Rotation du journal : `claude remote-control` y écrit ses redessins d'écran et
# ses reconnexions (245 Mo en 12 jours observés). Le processus garde le
# descripteur ouvert en ajout : on copie puis on tronque (« copytruncate »),
# sans redémarrage. Gardés : .1 (en clair, pour retrouver l'URL), .2.gz, .3.gz.
LOG_MAX_BYTES="${ARC_REMOTE_LOG_MAX_BYTES:-10485760}"
LOG_KEEP=3
ROTATE_MARKER="# ai-running-coach logrotate"
ROTATE_LAUNCHD_LABEL="com.ai-running-coach.remote-logrotate"
ROTATE_LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$ROTATE_LAUNCHD_LABEL.plist"
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

# ---------------------------------------------------------------------------
# Rotation du journal
# ---------------------------------------------------------------------------
# Copie puis troncature : le processus écrit en mode ajout (O_APPEND), il
# reprend donc au début du fichier tronqué, sans trou ni redémarrage. Les
# quelques lignes écrites entre la copie et la troncature sont perdues — même
# limite que « copytruncate » de logrotate.
do_rotate_log() {
    local f="$REMOTE_LOG" size i
    [[ -f "$f" ]] || return 0
    size="$(wc -c < "$f" | tr -d ' ')"
    (( size >= LOG_MAX_BYTES )) || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} rotation de $f ($size octets)"
        return 0
    fi
    rm -f "$f.$LOG_KEEP.gz"
    for (( i = LOG_KEEP - 1; i >= 2; i-- )); do
        [[ -f "$f.$i.gz" ]] && mv -f "$f.$i.gz" "$f.$((i + 1)).gz"
    done
    # .1 reste en clair (« delaycompress ») : `url` y cherche encore.
    if [[ -f "$f.1" ]]; then
        gzip -c "$f.1" > "$f.2.gz" && rm -f "$f.1"
    fi
    cp -p "$f" "$f.1"
    : > "$f"
}

# Dernière URL de session : journal courant, sinon le journal tourné .1.
last_session_url() {
    local f url=""
    for f in "$REMOTE_LOG" "$REMOTE_LOG.1"; do
        [[ -f "$f" ]] || continue
        url="$(grep -o 'https://claude.ai/code/[A-Za-z0-9_-]*' "$f" | tail -1 || true)"
        [[ -n "$url" ]] && { printf '%s\n' "$url"; return 0; }
    done
    return 1
}

# Lecture de la crontab : « pas de crontab » = table vide ; toute autre erreur
# est fatale (on n'écrase jamais une table qu'on n'a pas pu lire).
read_crontab() {
    local out
    out="$(crontab -l 2>&1)" && { printf '%s\n' "$out"; return 0; }
    printf '%s' "$out" | grep -qi 'no crontab' && return 0
    err "Lecture de la crontab impossible : $out"
    return 1
}

# Une seule ligne marquée « # ai-running-coach logrotate » : une ligne posée à
# la main (logrotate + fichier de conf) est remplacée, jamais doublée.
install_rotation_cron() {
    local line current
    line="23 * * * * ARC_WORKSPACE=\"$ARC_WORKSPACE\" \"$ARC_ENGINE_ROOT/scripts/coach-remote.sh\" rotate-log >/dev/null 2>&1 $ROTATE_MARKER"
    if ! have crontab; then
        warn "crontab absent : le journal ne tournera qu'au (re)démarrage du service."
        return 0
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} crontab : $line"
        return 0
    fi
    current="$(read_crontab)" || die "crontab illisible — rotation du journal non installée."
    if printf '%s\n' "$current" | grep -qxF "$line"; then
        ok "Rotation du journal déjà planifiée (crontab)."
        return 0
    fi
    printf '%s\n%s\n' "$(printf '%s\n' "$current" | grep -vF "$ROTATE_MARKER" || true)" "$line" \
        | grep -v '^[[:space:]]*$' | crontab -
    ok "Rotation du journal planifiée (crontab, chaque heure, au-delà de $((LOG_MAX_BYTES / 1048576)) Mo)."
}

remove_rotation_cron() {
    local current
    have crontab || return 0
    current="$(read_crontab)" || { warn "crontab illisible — ligne de rotation laissée en place."; return 0; }
    printf '%s\n' "$current" | grep -qF "$ROTATE_MARKER" || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} retrait de la ligne « $ROTATE_MARKER » de la crontab"
        return 0
    fi
    printf '%s\n' "$current" | grep -vF "$ROTATE_MARKER" | grep -v '^[[:space:]]*$' | crontab - || true
    ok "Rotation du journal retirée de la crontab."
}

# Comment le service est géré sur cette machine.
#
# NE JAMAIS appeler « die » ici : backend est utilisé en substitution de
# commande ($(backend)), où un exit ne quitte que le sous-shell. L'appelant
# recevait une chaîne vide, aucun case ne correspondait, et l'installation se
# poursuivait jusqu'au message de succès. On renvoie donc un statut, que
# require_backend transforme en erreur fatale dans le shell principal.
backend() {
    if [[ "$OS" == "Darwin" ]]; then echo launchd; return 0
    elif have systemctl && systemctl --user show-environment >/dev/null 2>&1; then echo systemd; return 0
    elif have screen || have tmux; then echo screen; return 0
    fi
    echo none
    return 1
}

# Message unique pour l'absence de gestionnaire de services.
NO_BACKEND_MSG="Ni systemd --user, ni screen/tmux disponibles sur cette machine — service impossible."

# ---------------------------------------------------------------------------
# run — premier plan
# ---------------------------------------------------------------------------
do_run() {
    claude_bin >/dev/null
    cd "$ARC_WORKSPACE"
    log "Démarrage de claude remote-control — session « $SESSION_NAME » ($PERMISSION_MODE)"
    log "Workspace : $ARC_WORKSPACE (moteur : $ARC_ENGINE_ROOT)"
    do_rotate_log || true
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
WorkingDirectory=$ARC_WORKSPACE
Environment=PATH=$HOME/.local/bin:$HOME/.claude/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
Environment=ARC_WORKSPACE=$ARC_WORKSPACE
ExecStart=$ARC_ENGINE_ROOT/scripts/coach-remote.sh run --name "$SESSION_NAME" --permission-mode $PERMISSION_MODE
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
    install_rotation_cron
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
    <string>$ARC_ENGINE_ROOT/scripts/coach-remote.sh</string>
    <string>run</string>
    <string>--name</string><string>$SESSION_NAME</string>
    <string>--permission-mode</string><string>$PERMISSION_MODE</string>
  </array>
  <key>WorkingDirectory</key><string>$ARC_WORKSPACE</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ARC_WORKSPACE</key><string>$ARC_WORKSPACE</string>
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
    install_rotation_launchd
    warn "macOS : empêchez la mise en veille (Réglages > Batterie, ou 'caffeinate -s') pour garder le coach joignable."
}

# macOS : pas de logrotate ; un second LaunchAgent lance la rotation chaque heure.
install_rotation_launchd() {
    write_file "$ROTATE_LAUNCHD_PLIST" <<EOT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$ROTATE_LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ARC_ENGINE_ROOT/scripts/coach-remote.sh</string>
    <string>rotate-log</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ARC_WORKSPACE</key><string>$ARC_WORKSPACE</string>
    <key>PATH</key><string>/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOT
    run launchctl bootout "gui/$(id -u)" "$ROTATE_LAUNCHD_PLIST" 2>/dev/null || true
    run launchctl bootstrap "gui/$(id -u)" "$ROTATE_LAUNCHD_PLIST"
    ok "Rotation du journal planifiée ($ROTATE_LAUNCHD_LABEL, chaque heure)."
}

install_screen() {
    warn "Pas de systemd --user : lancement dans une session screen/tmux (ne survit pas au reboot)."
    install_rotation_cron
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
        if [[ ! "${yn:-n}" =~ ^([oO]([uU][iI])?|[yY]([eE][sS])?)$ ]]; then
            log "Lancement interactif : répondez 'y', attendez « Remote Control session started », puis Ctrl+C."
            (cd "$ARC_WORKSPACE" && claude remote-control --name "$SESSION_NAME" --permission-mode "$PERMISSION_MODE") || true
        fi
    fi
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) install_systemd ;;
        launchd) install_launchd ;;
        screen)  install_screen ;;
    esac
    echo
    log "Sur le téléphone : appli Claude → onglet Code → la session « $SESSION_NAME » apparaît."
    log "Pour un QR code : 'scripts/coach-remote.sh logs' (URL imprimée au démarrage) ou lancez 'claude remote-control' à la main."
}

do_uninstall() {
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd)
            run systemctl --user disable --now "$SERVICE_NAME" || true
            run rm -f "$SYSTEMD_UNIT"
            run systemctl --user daemon-reload
            remove_rotation_cron ;;
        launchd)
            run launchctl bootout "gui/$(id -u)" "$LAUNCHD_PLIST" || true
            run rm -f "$LAUNCHD_PLIST"
            run launchctl bootout "gui/$(id -u)" "$ROTATE_LAUNCHD_PLIST" 2>/dev/null || true
            run rm -f "$ROTATE_LAUNCHD_PLIST" ;;
        screen)
            do_stop
            remove_rotation_cron ;;
    esac
    ok "Service Remote Control retiré."
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
    local chosen
    chosen="$(backend)" || die "$NO_BACKEND_MSG"
    case "$chosen" in
        systemd) run systemctl --user stop "$SERVICE_NAME" ;;
        launchd) run launchctl kill SIGTERM "gui/$(id -u)/$LAUNCHD_LABEL" ;;
        screen)
            if have screen; then run screen -S "$SCREEN_NAME" -X quit || true
            else run tmux kill-session -t "$SCREEN_NAME" || true; fi ;;
    esac
    ok "Remote Control arrêté (les sessions restent reprenables ~4 h)."
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
    if [[ -f "$REMOTE_LOG" || -f "$REMOTE_LOG.1" ]]; then
        echo; log "Dernière URL de session :"
        last_session_url || warn "(aucune URL trouvée dans le journal)"
    fi
}

do_url() {
    last_session_url || die "Aucune URL de session dans $REMOTE_LOG (ni dans $REMOTE_LOG.1)."
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
    url) do_url ;;
    rotate-log) do_rotate_log ;;
esac
