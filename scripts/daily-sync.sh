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
GIT_AUTOCOMMIT="$(toml_get sync git_autocommit false)"
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

# Identité des commits et des rebase faits par la machine coach : cron n'a souvent
# aucune configuration git globale, et un rebase sans identité échoue.
GIT_ID=(-c user.name="${GIT_AUTHOR_NAME:-ai-running-coach}" -c user.email="${GIT_AUTHOR_EMAIL:-coach@localhost}")

# Avant le run : récupère ce qu'une autre machine a poussé (fichiers mis au contrat
# depuis le portable, plan écrit en session mobile…), pour que l'agent parte de
# l'état le plus récent. Un échec (conflit, réseau) n'empêche pas la
# synchronisation : elle se fait sur l'état local et le push final le signalera.
git_pull_before_run() {
    [[ "$GIT_AUTOCOMMIT" == "true" ]] || return 0
    git -C "$ARC_WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
    git -C "$ARC_WORKSPACE" remote get-url origin >/dev/null 2>&1 || return 0
    if git -C "$ARC_WORKSPACE" "${GIT_ID[@]}" pull -q --rebase --autostash 2>>"$LOG_FILE"; then
        ok "git : workspace à jour"
    else
        git -C "$ARC_WORKSPACE" rebase --abort >/dev/null 2>&1 || true
        warn "git pull échoué (voir $LOG_FILE) — synchronisation sur l'état local."
    fi
}

# Versionne le workspace après chaque run (données de la sync ET fichiers créés
# entre-temps par les sessions Remote Control). Push seulement si un remote existe.
# Retourne 0 si rien à faire ou si le commit/push a réussi ; sinon 1 (signalé
# dans la notification, sans faire échouer la synchronisation).
git_autocommit() {
    [[ "$GIT_AUTOCOMMIT" == "true" ]] || return 0
    git -C "$ARC_WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { warn "git_autocommit : $ARC_WORKSPACE n'est pas un dépôt git."; return 1; }
    cd "$ARC_WORKSPACE"
    if [[ -z "$(git status --porcelain)" ]]; then
        ok "git : rien à versionner"
        return 0
    fi
    git add -A
    git "${GIT_ID[@]}" commit -q -m "sync: $(date '+%F %H:%M') ($RUNNER)" || { warn "git commit échoué"; return 1; }
    ok "git : commit $(git rev-parse --short HEAD)"
    if git remote get-url origin >/dev/null 2>&1; then
        # Sans ce rebase, un seul push venu d'ailleurs pendant le run rendait tous les
        # push suivants de la machine coach impossibles (historiques divergents).
        if ! git "${GIT_ID[@]}" pull -q --rebase 2>>"$LOG_FILE"; then
            git rebase --abort >/dev/null 2>&1 || true
            warn "git pull --rebase échoué avant le push (voir $LOG_FILE)"
            return 1
        fi
        git push -q 2>>"$LOG_FILE" && ok "git : push origin" || { warn "git push échoué (voir $LOG_FILE)"; return 1; }
    fi
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

# =============================================================================
# Alerte d'expiration des tokens Garmin (#32)
#
# Appelle `coach_doctor.py --check garmin_token --json` AVANT la synchronisation
# (une échéance proche doit être signalée même si le run qui suit échoue), en
# lecture seule et borné dans le temps quand `timeout`/`gtimeout` (coreutils)
# est disponible. macOS sans coreutils n'a NI L'UN NI L'AUTRE : l'appel n'est
# alors pas borné — le check `garmin_token` ne fait toutefois aucun accès
# réseau (lecture de fichiers locaux uniquement, voir sa docstring), le risque
# de blocage reste donc faible même sans borne. Toute panne du diagnostic
# (binaire absent, JSON illisible, code de sortie inattendu) se journalise et
# retourne 0 : le doctor ne doit JAMAIS faire échouer la synchronisation.
#
# Seuils : [notifications].token_alert_days (défaut 14 et 3 jours ; `[]` ou
# une liste où plus aucune valeur n'est un entier positif désactive toute
# alerte d'expiration, sans toucher à l'alerte 401 explicite ci-dessous). Le
# seuil le plus proche de l'échéance (le plus petit, ainsi que « expiré »)
# alerte au maximum une fois par jour ; un seuil plus lointain (ex. J-14)
# n'alerte qu'une seule fois tant que l'échéance ne s'est pas encore
# rapprochée du seuil suivant — pas de rappel quotidien dès J-14, seulement à
# l'approche réelle. « Expiré depuis N jour(s) » utilise le même arrondi vers
# le bas que `coach_doctor.py` (`timedelta.days` : un token expiré depuis 30h30
# affiche N=2, pas 1). État persisté hors du dépôt :
# logs/.token-alert-state (gitignoré comme tout logs/), remis à zéro dès que
# l'échéance repasse au-dessus de tous les seuils (renouvellement effectué).
# =============================================================================
# Mis à 1 dès qu'une alerte d'expiration part — évite de doubler avec la
# notification 401 explicite plus bas quand les deux détectent le même
# problème sous-jacent au même run (voir revue PR #77).
TOKEN_ALERT_SENT_THIS_RUN=0

check_token_alert() {
    local token_alerts provider
    token_alerts="$(toml_get notifications token_alerts true)"
    [[ "$token_alerts" == "true" ]] || return 0
    provider="$(toml_get notifications provider none)"
    [[ "$provider" != "none" ]] || return 0

    local doctor_cmd=(python3 "$ARC_ENGINE_ROOT/scripts/coach_doctor.py"
                       --check garmin_token --json --workspace "$ARC_WORKSPACE")
    local timeout_bin="" doctor_json rc=0
    if have timeout; then
        timeout_bin="timeout"
    elif have gtimeout; then
        timeout_bin="gtimeout"
    fi
    if [[ -n "$timeout_bin" ]]; then
        doctor_json="$("$timeout_bin" 10 "${doctor_cmd[@]}" 2>>"$LOG_FILE")" || rc=$?
    else
        doctor_json="$("${doctor_cmd[@]}" 2>>"$LOG_FILE")" || rc=$?
    fi
    if [[ "$rc" -ne 0 && "$rc" -ne 1 ]]; then
        warn "coach doctor indisponible (code $rc) — alerte d'expiration des tokens ignorée."
        return 0
    fi

    local parsed
    parsed="$(printf '%s' "$doctor_json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    check = data["checks"][0]
except Exception:
    sys.exit(1)
days_left = check.get("days_left")
print(days_left if days_left is not None else "")
print(check.get("source") or "")
print(check.get("expires_at") or "")
' 2>>"$LOG_FILE")" || { warn "coach doctor : sortie JSON illisible — alerte d'expiration des tokens ignorée."; return 0; }

    local days_left source_field expires_at
    days_left="$(printf '%s\n' "$parsed" | sed -n '1p')"
    source_field="$(printf '%s\n' "$parsed" | sed -n '2p')"
    expires_at="$(printf '%s\n' "$parsed" | sed -n '3p')"

    # Tokens absents (première authentification jamais faite) : hors sujet ici,
    # déjà couvert par le message d'échec générique de la synchronisation.
    [[ -n "$days_left" && "$source_field" != "missing" ]] || return 0

    local state_file="$LOG_DIR/.token-alert-state" today
    if [[ -n "${ARC_DOCTOR_NOW:-}" ]]; then
        today="${ARC_DOCTOR_NOW:0:10}"
    else
        today="$(date +%F)"
    fi

    # `token_alert_days` vient de la config utilisateur : chaque valeur DOIT être
    # un entier avant d'entrer dans une comparaison arithmétique `[[ -le ]]`. Un
    # jeton non numérique (`"three"`, `"J-14"`) y serait interprété comme un nom
    # de variable — « unbound variable » sous `set -u` (le doctor meurt AVANT la
    # synchronisation, silencieusement, code 0 — voir revue PR #77) — et une
    # substitution de commande dans le jeton (`"HOME[$(touch x)]"` façon indice de
    # tableau) pourrait carrément s'exécuter. On ne laisse donc jamais une valeur
    # qui n'est pas purement `[0-9]+` atteindre `-le` : elle est écartée, avec un
    # avertissement, plutôt que « nettoyée » ou évaluée.
    local thresholds_raw thresholds_asc invalid smallest_threshold
    thresholds_raw="$(toml_get_list notifications token_alert_days "14 3")"
    thresholds_asc="$(printf '%s\n' "$thresholds_raw" | grep -E '^[0-9]+$' | sort -n || true)"
    invalid="$(printf '%s\n' "$thresholds_raw" | grep -vE '^[0-9]+$' | grep -v '^$' || true)"
    if [[ -n "$invalid" ]]; then
        warn "[notifications].token_alert_days : valeur(s) ignorée(s) (entier positif attendu) : $(printf '%s' "$invalid" | tr '\n' ' ')"
    fi
    # Liste vide (après filtrage, ou `token_alert_days = []` explicite) : aucun
    # seuil configuré -> aucune alerte d'expiration, quelle que soit l'échéance.
    [[ -n "$thresholds_asc" ]] || return 0
    smallest_threshold="$(printf '%s\n' "$thresholds_asc" | head -n1)"

    local tier="" t
    for t in $thresholds_asc; do
        if [[ "$days_left" -le "$t" ]]; then
            tier="$t"
            break
        fi
    done
    [[ "$days_left" -ge 0 ]] || tier="expired"

    local last_tier="" last_date=""
    if [[ -f "$state_file" ]]; then
        last_tier="$(sed -n '1p' "$state_file" 2>/dev/null)"
        last_date="$(sed -n '2p' "$state_file" 2>/dev/null)"
    fi

    if [[ -z "$tier" ]]; then
        # Au-dessus de tous les seuils configurés (renouvellement effectué,
        # ou seuils resserrés) : on efface l'état pour qu'un futur passage
        # sous un seuil réalerte normalement.
        [[ -z "$last_tier" ]] || rm -f "$state_file"
        return 0
    fi

    local urgent=0
    [[ "$tier" == "expired" || "$tier" == "$smallest_threshold" ]] && urgent=1

    if [[ "$urgent" -eq 1 ]]; then
        [[ "$last_date" == "$today" ]] && return 0
    else
        [[ "$last_tier" == "$tier" ]] && return 0
    fi

    local message
    if [[ "$tier" == "expired" ]]; then
        message="Tokens Garmin expirés depuis $(( -1 * days_left )) jour(s) — renouvelez avec : uv run garmin-mcp-auth"
    else
        message="Encore $days_left jour(s) avant l'expiration estimée des tokens Garmin (échéance ~${expires_at%%T*}) — renouvelez avec : uv run garmin-mcp-auth"
    fi
    notify "🔑 Tokens Garmin — renouvellement" 4 "key,warning" "$message"
    TOKEN_ALERT_SENT_THIS_RUN=1
    printf '%s\n%s\n' "$tier" "$today" > "$state_file"
}

# Un vrai 401 Garmin — jamais deviné depuis un `ERREUR` générique écrit par
# l'agent, et jamais confondu avec un 401 sans rapport avec Garmin (ex. un
# 401 du runner Codex lui-même) : on exige un contexte Garmin explicite.
# Deux sources possibles selon l'exécuteur, documentées ici parce qu'aucun test
# ne peut les couvrir toutes les deux avec le même stub :
#   - le texte RÉEL émis par `garminconnect`/`garmin_mcp`
#     (`GarminConnectAuthenticationError`, ou son message
#     « Authentication failed: 401 Client Error: Unauthorized for url:
#     https://connect(api).garmin.com/... », voir
#     tests/evals/mcp_stub_common.py::auth_expired_text) — visible dans le
#     journal seulement si l'exécuteur restitue la sortie brute des outils
#     (ex. `codex exec` en mode verbeux). `AUTH_FAILURE_KIND=raw` : on peut
#     revendiquer un 401 avec certitude, c'est le texte HTTP réel ;
#   - avec le runner par défaut, `claude -p --output-format text` ne restitue
#     QUE le message final de l'agent, jamais la sortie brute d'un outil MCP :
#     le texte ci-dessus n'atteint donc jamais ce journal. C'est pour cette
#     raison que `skills/garmin-daily-sync/SKILL.md` impose à l'agent d'écrire
#     lui-même, en première ligne du bloc ```resume```, `ERREUR : <cause>`. On
#     reconnaît cette formulation, mais SEULEMENT quand elle nomme
#     explicitement une expiration/un refus de token ou renvoie vers
#     `garmin-mcp-auth` — jamais un `ERREUR` générique quelconque (ex. « MCP
#     garmin injoignable (timeout réseau) », « échec du rafraîchissement des
#     tokens Garmin (DNS) » : ni l'un ni l'autre ne doit déclencher cette
#     alerte, un problème réseau n'est pas un problème d'authentification —
#     voir revue PR #77). `AUTH_FAILURE_KIND=erreur` : la cause réelle peut ne
#     PAS être un 401 (l'agent a pu mal diagnostiquer) — ne jamais l'affirmer
#     dans la notification, relayer sa ligne telle quelle.
# `AUTH_FAILURE_LINE` porte la ligne `ERREUR : …` détectée (kind=erreur), pour
# que l'appelant puisse la relayer mot pour mot plutôt que d'inventer un « 401 ».
AUTH_FAILURE_KIND=""
AUTH_FAILURE_LINE=""
detect_auth_failure() {
    local run_log erreur_line
    AUTH_FAILURE_KIND=""
    AUTH_FAILURE_LINE=""
    run_log="$(awk '/^===== /{buf=""} {buf = buf $0 ORS} END{printf "%s", buf}' "$LOG_FILE" 2>/dev/null)"
    if printf '%s' "$run_log" | grep -qiE \
        'garminconnectauthenticationerror|401 client error: unauthorized for url: https://connect(api)?\.garmin\.com|error retrieving [a-z ]+ data: authentication failed'
    then
        AUTH_FAILURE_KIND="raw"
        return 0
    fi
    erreur_line="$(printf '%s' "$run_log" \
        | grep -iE '^ERREUR.*(garmin-mcp-auth|tokens? garmin (expir|invalid|refus)|401)' | tail -n1)"
    if [[ -n "$erreur_line" ]]; then
        AUTH_FAILURE_KIND="erreur"
        AUTH_FAILURE_LINE="$erreur_line"
        return 0
    fi
    return 1
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
    check_token_alert || warn "Alerte d'expiration des tokens Garmin interrompue (voir $LOG_FILE)."
    git_pull_before_run

    local output rc=0
    {
        echo "===== $(date '+%F %T') — runner=$RUNNER lookback=$LOOKBACK ====="
    } >> "$LOG_FILE"
    cd "$ARC_WORKSPACE"
    output="$("${CMD[@]}" 2>>"$LOG_FILE")" || rc=$?
    printf '%s\n' "$output" >> "$LOG_FILE"

    if [[ "$rc" -ne 0 ]]; then
        err "La synchronisation a échoué (code $rc) — voir $LOG_FILE"
        if detect_auth_failure; then
            if [[ "$TOKEN_ALERT_SENT_THIS_RUN" -eq 1 ]]; then
                # L'alerte d'expiration envoyée juste avant la synchronisation couvre
                # déjà ce même problème (tokens expirés) — pas de doublon.
                warn "Garmin — alerte d'expiration déjà envoyée ce run, pas de notification supplémentaire."
            elif [[ "$AUTH_FAILURE_KIND" == "raw" ]]; then
                # Texte HTTP réel de garminconnect/garmin_mcp : le 401 est un fait constaté.
                notify "🔑 Authentification Garmin refusée" 5 "key,warning" \
                    "Synchronisation interrompue (401) — renouvelez avec : uv run garmin-mcp-auth. Voir logs/sync-$(date +%F).log."
            else
                # Détecté via la formulation ERREUR de l'agent : la cause réelle peut ne
                # PAS être un 401 (ex. un problème réseau/DNS mal diagnostiqué par
                # l'agent) — on relaie sa ligne telle quelle plutôt que d'affirmer « 401 ».
                notify "🔑 Authentification Garmin — action requise" 5 "key,warning" \
                    "Synchronisation interrompue — ${AUTH_FAILURE_LINE#ERREUR : } Voir logs/sync-$(date +%F).log."
            fi
        else
            notify "❌ Sync Garmin échouée" 4 "warning" "Exécuteur $RUNNER, code $rc. Voir logs/sync-$(date +%F).log sur la machine coach."
        fi
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
    if detect_auth_failure; then
        title="🔑 Authentification Garmin refusée"; priority=5; tags="key,warning"
        # N'ajoute la commande que si l'agent (ERREUR du skill) ne l'a pas déjà écrite.
        if ! printf '%s' "$resume" | grep -qi 'garmin-mcp-auth'; then
            resume="$resume — renouvelez avec : uv run garmin-mcp-auth"
        fi
    elif printf '%s' "$resume" | grep -qi '^ERREUR'; then
        title="⚠️ Sync Garmin"; priority=4; tags="warning"
    elif printf '%s' "$resume" | grep -qi '^À jour'; then
        title="Sync Garmin — à jour"; priority=2; tags="running"
    fi
    # Index du tableau de bord : dérivé, jetable, et ignoré par git (.arc/ s'ignore
    # lui-même). Un tableau de bord ouvert voit ainsi la synchronisation sans attendre.
    python3 "$ARC_ENGINE_ROOT/scripts/arc_index.py" --workspace "$ARC_WORKSPACE" >>"$LOG_FILE" 2>&1 \
        || warn "Index du tableau de bord non mis à jour (voir $LOG_FILE)"
    if ! git_autocommit; then
        resume="$resume
⚠ git : commit/push du workspace échoué — voir logs/"
        priority=4
    fi
    notify "$title" "$priority" "$tags" "$resume"
}

main "$@"
