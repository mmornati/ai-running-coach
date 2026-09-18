#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — Script d'installation
#
# Installe et configure tout ce qu'il faut pour utiliser les agents/skills de
# coaching trail-running avec accès Garmin :
#   1. uv (gestionnaire Python)
#   2. garmin-mcp + garmin-mcp-auth (accès Garmin Connect)
#   3. leanproxy-mcp (passerelle MCP)
#   4. Configuration des IDE (Claude Code, OpenCode, Gemini CLI, Cursor, Windsurf)
#   5. Vérification finale
#
# Usage :
#   ./install.sh                 # installation interactive
#   ./install.sh --ide claude    # installe pour un IDE précis
#   ./install.sh --no-auth       # saute l'authentification Garmin
#   ./install.sh --dry-run       # affiche les actions sans rien exécuter
#   ./install.sh --help
#
# Prérequis : macOS ou Linux, bash 4+, curl, git.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
VERSION="0.1.0"
GARMIN_MCP_REF="git+https://github.com/Taxuspt/garmin_mcp"
LEANPROXY_BREW_TAP="mmornati/leanproxy-mcp"
LEANPROXY_FORMULA="leanproxy-mcp"
GARMIN_TOKENS_DIR="$HOME/.garminconnect"
LEANPROXY_CONFIG_DIR="$HOME/.config/leanproxy"
LEANPROXY_SERVERS="$HOME/.config/leanproxy_servers.yaml"

# Détection du répertoire du projet (racine du dépôt)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR" && pwd)"

# ---------------------------------------------------------------------------
# Couleurs (si terminal interactif)
# ---------------------------------------------------------------------------
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
IDE="all"          # all | claude | opencode | gemini | cursor | windsurf
SKIP_LEANPROXY=0

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ide) IDE="$2"; shift 2 ;;
        --no-auth) DO_AUTH=0; shift ;;
        --skip-leanproxy) SKIP_LEANPROXY=1; shift ;;
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
        return 0
    fi
    cat > "$file"
}

have() { command -v "$1" >/dev/null 2>&1; }

require_cmd() {
    local cmd="$1" hint="${2:-}"
    if ! have "$cmd"; then
        die "Commande '$cmd' introuvable. $hint"
    fi
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
    run curl -LsSf https://astral.sh/uv/install.sh | sh
    # recharge le PATH pour la session courante
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! have uv; then
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
        ok "garmin-mcp déjà installé : $(garmin-mcp --version 2>/dev/null || echo 'version inconnue')"
    else
        run uv tool install --python 3.12 "$GARMIN_MCP_REF"
        export PATH="$HOME/.local/bin:$PATH"
        have garmin-mcp || die "garmin-mcp introuvable après installation."
        ok "garmin-mcp installé"
    fi

    if [[ "$DO_AUTH" -eq 1 ]]; then
        log "Authentification Garmin Connect (une seule fois, tokens valides ~6 mois)"
        if [[ -f "$GARMIN_TOKENS_DIR/garmin_tokens.json" ]]; then
            if run uv run garmin-mcp-auth --verify; then
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
# 3. leanproxy-mcp
# ---------------------------------------------------------------------------
install_leanproxy() {
    if [[ "$SKIP_LEANPROXY" -eq 1 ]]; then
        warn "Installation de leanproxy-mcp sautée (--skip-leanproxy)"
        return 0
    fi
    log "Installation de leanproxy-mcp (passerelle MCP)"
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
# 4. Configuration leanproxy (serveur garmin)
# ---------------------------------------------------------------------------
configure_leanproxy() {
    if [[ "$SKIP_LEANPROXY" -eq 1 ]]; then
        return 0
    fi
    log "Configuration de leanproxy (serveur garmin)"

    mkdir -p "$LEANPROXY_CONFIG_DIR"

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
        env: []
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
# Chaque fonction écrit la config MCP + pointe vers les agents/skills du projet.

write_opencode_config() {
    log "Configuration OpenCode"
    local cfg="$HOME/.config/opencode/opencode.json"
    mkdir -p "$(dirname "$cfg")"
    if [[ -f "$cfg" ]] && grep -q 'leanproxy' "$cfg"; then
        ok "OpenCode déjà configuré (leanproxy présent)"
    else
        write_file "$cfg" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "mcp": {
    "leanproxy": {
      "type": "local",
      "command": ["leanproxy-mcp"],
      "enabled": true
    }
  }
}
EOF
        ok "Config OpenCode écrite dans $cfg"
    fi
    # Agents/skills : OpenCode lit .opencode/ à la racine du projet.
    # On crée des liens symboliques pour que le projet reste la source de vérité.
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$PROJECT_ROOT/.opencode"
        ln -sfn "$PROJECT_ROOT/agents" "$PROJECT_ROOT/.opencode/agents"
        ln -sfn "$PROJECT_ROOT/skills" "$PROJECT_ROOT/.opencode/skills"
        ok "Liens .opencode/agents et .opencode/skills créés"
    fi
}

write_claude_config() {
    log "Configuration Claude Code"
    local cfg="$PROJECT_ROOT/.mcp.json"
    if [[ -f "$cfg" ]] && grep -q 'leanproxy' "$cfg"; then
        ok "Claude Code déjà configuré (leanproxy présent)"
    else
        write_file "$cfg" <<'EOF'
{
  "mcpServers": {
    "leanproxy": {
      "command": "leanproxy-mcp",
      "args": []
    }
  }
}
EOF
        ok "Config Claude Code écrite dans $cfg"
    fi
    # Claude Code utilise .claude/agents/*.md + .claude/skills/*/SKILL.md
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$PROJECT_ROOT/.claude"
        ln -sfn "$PROJECT_ROOT/agents" "$PROJECT_ROOT/.claude/agents"
        ln -sfn "$PROJECT_ROOT/skills" "$PROJECT_ROOT/.claude/skills"
        ok "Liens .claude/agents et .claude/skills créés"
    fi
}

write_gemini_config() {
    log "Configuration Gemini CLI"
    local dir="$PROJECT_ROOT/.gemini/commands"
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
    local dir="$PROJECT_ROOT/.cursor"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$dir"
    fi
    if [[ -f "$dir/mcp.json" ]] && grep -q 'leanproxy' "$dir/mcp.json"; then
        ok "Cursor déjà configuré (leanproxy présent)"
    else
        write_file "$dir/mcp.json" <<'EOF'
{
  "mcpServers": {
    "leanproxy": {
      "command": "leanproxy-mcp",
      "args": []
    }
  }
}
EOF
        ok "Config Cursor écrite dans $dir/mcp.json"
    fi
}

write_windsurf_config() {
    log "Configuration Windsurf"
    local dir="$PROJECT_ROOT/.windsurf"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$dir"
    fi
    if [[ -f "$dir/mcp_config.json" ]] && grep -q 'leanproxy' "$dir/mcp_config.json"; then
        ok "Windsurf déjà configuré (leanproxy présent)"
    else
        write_file "$dir/mcp_config.json" <<'EOF'
{
  "mcpServers": {
    "leanproxy": {
      "command": "leanproxy-mcp",
      "args": []
    }
  }
}
EOF
        ok "Config Windsurf écrite dans $dir/mcp_config.json"
    fi
}

configure_ide() {
    case "$IDE" in
        all)      write_opencode_config; write_claude_config; write_gemini_config; write_cursor_config; write_windsurf_config ;;
        opencode) write_opencode_config ;;
        claude)   write_claude_config ;;
        gemini)   write_gemini_config ;;
        cursor)   write_cursor_config ;;
        windsurf) write_windsurf_config ;;
        *) die "IDE inconnu : $IDE (all|claude|opencode|gemini|cursor|windsurf)" ;;
    esac
}

# ---------------------------------------------------------------------------
# 6. Dossiers de travail
# ---------------------------------------------------------------------------
create_workspace_dirs() {
    log "Création des dossiers de travail (exclus du dépôt)"
    for d in activities medical nutrition planning rapports resources; do
        if [[ "$DRY_RUN" -eq 0 ]]; then
            mkdir -p "$PROJECT_ROOT/$d"
        fi
    done
    ok "Dossiers activities/ medical/ nutrition/ planning/ rapports/ resources/ prêts"
}

# ---------------------------------------------------------------------------
# 7. Vérification finale
# ---------------------------------------------------------------------------
verify() {
    log "Vérification finale"
    local fail=0
    for cmd in uv garmin-mcp leanproxy-mcp; do
        if have "$cmd"; then
            ok "$cmd : présent"
        else
            warn "$cmd : absent"
            fail=1
        fi
    done
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
    [[ "$DRY_RUN" -eq 1 ]] && warn "Mode dry-run : aucune modification ne sera effectuée."
    echo

    require_cmd curl "Installez curl (macOS : déjà présent ; Linux : apt install curl)."
    require_cmd git "Installez git."

    install_uv
    install_garmin_mcp
    install_leanproxy
    configure_leanproxy
    configure_ide
    create_workspace_dirs
    verify
}

main "$@"