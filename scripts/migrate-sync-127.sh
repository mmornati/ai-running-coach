#!/usr/bin/env bash
# Migration d'une installation EXISTANTE (un seul athlète, workspace séparé, mode « watch ») vers le moteur
# qui contient #127 (PR #292 : jetons et planification par workspace) et le renommage
# garmin_watch.py → watch.py — sans jamais laisser la synchronisation cassée ni doublée.
#
# À lancer SUR LA MACHINE de la sync, depuis une copie HORS du moteur (le moteur est mis à jour pendant
# l'exécution : bash lit un script au fil de l'eau, il ne doit pas changer sous lui) :
#
#   cp ~/ai-running-coach/scripts/migrate-sync-127.sh ~/ && cd ~
#   ./migrate-sync-127.sh check [--no-fetch]            # ne modifie rien, sauf git fetch (voir plus bas)
#   ./migrate-sync-127.sh migrate [--fix-install-args] [--allow-pre-127] [--yes]
#   ./migrate-sync-127.sh verify                        # après le prochain passage du watch (≤ 15 min)
#   ./migrate-sync-127.sh rollback <dossier-de-sauvegarde>
#
# Principe de sécurité : la ligne cron d'origine (garmin_watch.py) reste valable avant ET après la mise à
# jour, car garmin_watch.py est gardé comme cale vers watch.py. Toute erreur pendant `migrate` remet donc
# la crontab d'origine telle quelle : au pire, on revient à l'état de départ, jamais à une sync arrêtée.
#
# `check` ne modifie ni la crontab, ni le moteur, ni le workspace. Il lance seulement `git fetch origin`
# dans le moteur (appel réseau, met à jour les références distantes `origin/*`, jamais `main`) pour savoir
# si #127 est déjà fusionné ; `--no-fetch` l'évite et compare aux références déjà présentes.
#
# Ce que `migrate` NE fait PAS : relancer ./install.sh en entier (agents, .mcp.json, chat Docker,
# Remote Control). La ligne cron est réécrite à l'identique, seul le nom du script change.
set -euo pipefail

CONF="$HOME/.config/ai-running-coach"
MARKER="# ai-running-coach daily-sync"
PAUSE_PREFIX="#ARC-127-PAUSED# "
DEFAULT_TOKENS="$HOME/.garminconnect"

FAILS=0
FETCH=1    # check : git fetch origin dans le moteur (--no-fetch : 0)
WARNS=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
info() { printf '  · %s\n' "$*"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$*"; WARNS=$((WARNS + 1)); }
fail() { printf '  \033[31m✖\033[0m %s\n' "$*"; FAILS=$((FAILS + 1)); }
die()  { printf '\033[31m✖\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[34m==>\033[0m %s\n' "$*"; }

read_cron() { crontab -l 2>/dev/null || true; }

# Lignes marquées ACTIVES (ni commentées, ni mises en pause par ce script).
# Messages d'install.sh signalant une planification conservée / périmée retirée / remplacée. Motif ASCII
# (« onserv », « p.{1,2}rim » = « périm » en UTF-8 ou en octets) : insensible à la casse des libellés
# (CONSERVÉE/conservée) et à la locale. Verrouillé par tests/lint/test_migrate_sync_guard.py.
SCHEDULE_NOTICE_RE='lanification.*(CONSERV|onserv)|igne cron p.{1,2}rim|LaunchAgent p.{1,2}rim'

active_marker_lines() { grep -F "$MARKER" <<<"$1" | grep -vE '^[[:space:]]*#' || true; }
paused_marker_lines() { grep -F "$PAUSE_PREFIX" <<<"$1" || true; }

line_workspace() { sed -n 's/.*ARC_WORKSPACE="\([^"]*\)".*/\1/p' <<<"$1"; }
line_script()    { sed -n 's/.*python3 "\([^"]*\.py\)".*/\1/p' <<<"$1"; }

physical() { (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; }

# Reprend la logique d'install.sh (engine_root_has_athlete_data, #292).
engine_root_has_athlete_data() {
    local f d
    for f in "$ENGINE/planning/Runner_Profile.md" "$ENGINE/planning/active_objective.md"; do
        [[ -f "$f" ]] && return 0
    done
    for d in activities medical; do
        compgen -G "$ENGINE/$d/*.md" >/dev/null && return 0
    done
    return 1
}

resolve_tokens() {
    if [[ -f "$ENGINE/scripts/arc_credentials.py" ]]; then
        env -u ARC_LOCK_WORKSPACE -u GARMINTOKENS ARC_WORKSPACE="$WS" \
            python3 "$ENGINE/scripts/arc_credentials.py" garmin-tokens --workspace "$WS" 2>/dev/null | head -n1
    else
        printf '%s' "$DEFAULT_TOKENS"
    fi
}

mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }

# ---------------------------------------------------------------------------------------------------------
# Découverte : tout part de la ligne cron existante (c'est elle qui fait tourner la sync aujourd'hui).
# ---------------------------------------------------------------------------------------------------------
discover() {
    CRON="$(read_cron)"
    local active paused n
    active="$(active_marker_lines "$CRON")"
    paused="$(paused_marker_lines "$CRON")"
    if [[ -n "$paused" && -z "$active" ]]; then
        LINE="${paused#"$PAUSE_PREFIX"}"
        PAUSED=1
    else
        LINE="$active"
        PAUSED=0
    fi
    n="$(grep -c . <<<"$LINE" || true)"
    [[ "$n" -eq 1 ]] || die "Il faut exactement UNE ligne cron « $MARKER » active, trouvé $n. Rien n'est fait.
$LINE"
    WS="$(line_workspace "$LINE")"
    SCRIPT="$(line_script "$LINE")"
    [[ -n "$WS" ]] || die "La ligne cron n'a pas d'ARC_WORKSPACE : $LINE"
    [[ -n "$SCRIPT" ]] || die "La ligne cron ne lance pas un script python3 \"…\" (mode watch attendu) : $LINE"
    ENGINE="$(cd "$(dirname "$SCRIPT")/.." && pwd -P)"
}

# ---------------------------------------------------------------------------------------------------------
check() {
    discover
    step "Planification"
    info "ligne : $LINE"
    [[ "$PAUSED" -eq 0 ]] || fail "la ligne est EN PAUSE (migration interrompue) : ./migrate-sync-127.sh rollback <sauvegarde>"
    if [[ -d "$WS" ]]; then ok "workspace $WS"; else fail "workspace $WS introuvable"; fi
    [[ "$(physical "$WS")" == "$WS" ]] || warn "ARC_WORKSPACE n'est pas un chemin physique ($(physical "$WS")) : install.sh compare les chemins physiques"
    local memorised
    memorised="$(head -n1 "$CONF/workspace" 2>/dev/null || true)"
    if [[ "$memorised" == "$WS" ]]; then ok "workspace mémorisé identique ($CONF/workspace)"
    else warn "workspace mémorisé « $memorised » ≠ cron « $WS »"; fi
    case "$(basename "$SCRIPT")" in
        garmin_watch.py) info "ancien nom garmin_watch.py (fonctionne par la cale vers watch.py ; migrate le renomme)" ;;
        watch.py)        ok "déjà sur watch.py" ;;
        *)               fail "script inattendu : $SCRIPT" ;;
    esac
    [[ -f "$SCRIPT" ]] && ok "script présent" || fail "script absent : $SCRIPT"

    step "Moteur ($ENGINE)"
    local branch upstream behind
    branch="$(git -C "$ENGINE" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    [[ "$branch" == "main" ]] && ok "branche main" || fail "branche « ${branch:-détachée} » (main attendue)"
    [[ -z "$(git -C "$ENGINE" status --porcelain --untracked-files=no)" ]] && ok "aucune modification locale" \
        || fail "modifications locales dans le moteur (git -C $ENGINE status)"
    if [[ "$FETCH" -eq 1 ]]; then
        git -C "$ENGINE" fetch --quiet origin 2>/dev/null || warn "git fetch impossible (réseau ?)"
    else
        info "--no-fetch : comparaison aux références origin/* déjà présentes (peut-être anciennes)"
    fi
    upstream="$(git -C "$ENGINE" rev-parse --abbrev-ref '@{u}' 2>/dev/null || true)"
    if [[ -n "$upstream" ]]; then
        if git -C "$ENGINE" merge-base --is-ancestor HEAD "$upstream"; then
            behind="$(git -C "$ENGINE" rev-list --count "HEAD..$upstream")"
            ok "avance rapide possible ($behind commit(s) de retard sur $upstream)"
        else
            fail "HEAD n'est pas un ancêtre de $upstream : pas d'avance rapide possible"
        fi
        if git -C "$ENGINE" cat-file -e "$upstream:scripts/arc_credentials.py" 2>/dev/null; then
            ok "$upstream contient #127 (scripts/arc_credentials.py)"
        else
            info "$upstream ne contient PAS encore #127 : migrate refusera sans --allow-pre-127"
        fi
        git -C "$ENGINE" cat-file -e "$upstream:scripts/garmin_watch.py" 2>/dev/null \
            && ok "la cale garmin_watch.py existe toujours dans $upstream (retour arrière sûr)" \
            || fail "garmin_watch.py a disparu de $upstream : la ligne cron d'origine ne serait plus un repli sûr"
    else
        fail "main ne suit aucune branche distante"
    fi

    step "Jetons Garmin"
    local tokens
    tokens="$(resolve_tokens)"
    if [[ "$tokens" == "$DEFAULT_TOKENS" ]]; then ok "dossier résolu : $tokens (inchangé)"
    else warn "dossier résolu : $tokens (≠ $DEFAULT_TOKENS) — vérifier que le chat Docker le monte aussi"; fi
    if [[ -d "$tokens" ]]; then
        [[ "$(mode_of "$tokens")" == "700" ]] && ok "dossier en 700" || warn "dossier en $(mode_of "$tokens") (700 attendu)"
        local f bad=0
        for f in "$tokens"/*.json; do
            [[ -e "$f" ]] || continue
            [[ "$(mode_of "$f")" == "600" ]] || { warn "$(basename "$f") en $(mode_of "$f") (600 attendu)"; bad=1; }
        done
        [[ "$bad" -eq 1 ]] || ok "fichiers en 600"
        [[ -f "$tokens/garmin_tokens.json" || -f "$tokens/oauth2_token.json" ]] && ok "jetons présents" \
            || fail "aucun jeton dans $tokens"
    else
        fail "dossier de jetons absent : $tokens"
    fi
    local gt
    gt="$(python3 - "$WS/.mcp.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
print(((d.get("mcpServers") or {}).get("garmin") or {}).get("env", {}).get("GARMINTOKENS", ""))
PY
)"
    [[ -z "$gt" ]] && ok "pas de GARMINTOKENS dans $WS/.mcp.json (défaut conservé)" \
        || info "GARMINTOKENS=$gt dans $WS/.mcp.json"

    step "Pièges de #292 pour CETTE installation"
    if engine_root_has_athlete_data; then
        warn "la racine du moteur contient des données d'athlète : install.sh la traiterait comme un AUTRE membre"
    else
        ok "racine du moteur sans données d'athlète"
    fi
    local args=""
    [[ -f "$CONF/install-args" ]] && args="$(tr '\n' ' ' <"$CONF/install-args")"
    if grep -qx -- "--workspace" "$CONF/install-args" 2>/dev/null; then
        ok "install-args contient --workspace ($args)"
    else
        warn "install-args sans --workspace (« ${args:-vide} ») : /update-coach réinstalle la RACINE DU MOTEUR."
        info "  Après #292, un « ./install.sh --daily-sync » lancé ainsi AJOUTERAIT une 2e ligne cron (sync doublée)."
        info "  Correction : migrate --fix-install-args"
    fi
    [[ -f "$ENGINE/.mcp.json" ]] && info "reste d'une installation sur la racine du moteur : $ENGINE/.mcp.json (sans effet sur la sync)"

    step "Activité de la sync"
    local state="$WS/logs/.watch-state.json" last
    if [[ -f "$state" ]]; then
        last="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("last_check",""))' "$state" 2>/dev/null || true)"
        info "dernier passage du watch : ${last:-inconnu} ; dernier run : $(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("last_run",""), "rc", d.get("last_run_rc",""))' "$state" 2>/dev/null || true)"
    else
        warn "pas d'état de watch ($state)"
    fi
    if pgrep -f "scripts/daily-sync.sh" >/dev/null 2>&1; then info "une daily-sync tourne EN CE MOMENT"; else ok "aucune daily-sync en cours"; fi

    printf '\nBilan : %d échec(s), %d avertissement(s).\n' "$FAILS" "$WARNS"
}

# ---------------------------------------------------------------------------------------------------------
BACKUP=""
ORIG_CRON=""
# Toute sortie (erreur, die, Ctrl-C) avant la reprise remet la crontab d'origine.
restore_cron_on_error() {
    local rc=$?
    if [[ -n "$ORIG_CRON" ]]; then
        (( rc != 0 )) || rc=1
        printf '%s\n' "$ORIG_CRON" | crontab -
        printf '\n\033[31m✖\033[0m Erreur (code %s) : crontab initiale remise (la cale garmin_watch.py la rend valable).\n' "$rc" >&2
        [[ -z "$BACKUP" ]] || printf '  Moteur : retour complet avec ./migrate-sync-127.sh rollback %s\n' "$BACKUP" >&2
    fi
    exit "$rc"
}

wait_for_running_sync() {
    local waited=0
    while pgrep -f "scripts/daily-sync.sh" >/dev/null 2>&1 || pgrep -f "scripts/(garmin_)?watch.py" >/dev/null 2>&1; do
        (( waited == 0 )) && info "une sync/un passage du watch tourne : attente de la fin (30 min max)…"
        sleep 20
        waited=$((waited + 20))
        (( waited < 1800 )) || die "la sync tourne encore après 30 min : réessayez plus tard"
    done
}

migrate() {
    local yes=0 fix_args=0 allow_pre=0
    for a in "$@"; do
        case "$a" in
            --yes) yes=1 ;;
            --fix-install-args) fix_args=1 ;;
            --allow-pre-127) allow_pre=1 ;;
            *) die "option inconnue : $a" ;;
        esac
    done

    check
    [[ "$FAILS" -eq 0 ]] || die "check en échec : rien n'est fait."
    case "$(physical "$(dirname "${BASH_SOURCE[0]}")")" in
        "$ENGINE"*) die "Lancez une COPIE hors du moteur : cp $ENGINE/scripts/migrate-sync-127.sh ~/ && ~/migrate-sync-127.sh migrate" ;;
    esac
    local upstream
    upstream="$(git -C "$ENGINE" rev-parse --abbrev-ref '@{u}')"
    if ! git -C "$ENGINE" cat-file -e "$upstream:scripts/arc_credentials.py" 2>/dev/null && [[ "$allow_pre" -eq 0 ]]; then
        die "$upstream ne contient pas encore #127 (PR #292 non fusionnée). Relancez après la fusion, ou --allow-pre-127."
    fi

    local new_line="${LINE/scripts\/garmin_watch.py/scripts/watch.py}"
    step "Plan"
    info "1. sauvegarde : crontab, install-args, workspace mémorisé, HEAD du moteur, .mcp.json, état du watch"
    info "2. pause de la ligne cron, attente de toute sync en cours"
    info "3. moteur : git merge --ff-only $upstream"
    info "4. contrôles : jetons résolus identiques, watch.py --dry-run (un appel Garmin, rien n'est lancé)"
    info "5. ligne cron réécrite : $new_line"
    [[ "$fix_args" -eq 0 ]] || info "6. install-args : + --workspace $WS --daily-sync, puis aperçu install.sh --dry-run"
    if [[ "$yes" -eq 0 ]]; then
        read -r -p "Continuer ? [o/N] " r
        [[ "$r" =~ ^[oOyY]$ ]] || die "abandon, rien n'a été modifié."
    fi

    step "1. Sauvegarde"
    BACKUP="$CONF/backup-migration-127-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP" && chmod 700 "$BACKUP"
    printf '%s\n' "$CRON" > "$BACKUP/crontab.txt"
    git -C "$ENGINE" rev-parse HEAD > "$BACKUP/engine-head.txt"
    printf '%s\n' "$ENGINE" > "$BACKUP/engine-path.txt"
    [[ -f "$CONF/install-args" ]] && cp -p "$CONF/install-args" "$BACKUP/install-args"
    [[ -f "$CONF/workspace" ]] && cp -p "$CONF/workspace" "$BACKUP/workspace"
    [[ -f "$WS/.mcp.json" ]] && cp -p "$WS/.mcp.json" "$BACKUP/workspace.mcp.json"
    [[ -f "$WS/logs/.watch-state.json" ]] && cp -p "$WS/logs/.watch-state.json" "$BACKUP/watch-state.json"
    resolve_tokens > "$BACKUP/tokens-before.txt"
    date +%s > "$BACKUP/started-at.txt"
    ok "$BACKUP"

    step "2. Pause"
    ORIG_CRON="$CRON"
    trap 'exit 1' ERR
    trap 'exit 130' INT TERM
    trap restore_cron_on_error EXIT
    printf '%s\n' "$CRON" | awk -v m="$MARKER" -v p="$PAUSE_PREFIX" \
        'index($0, m) && $0 !~ /^[[:space:]]*#/ { print p $0; next } { print }' | crontab -
    ok "ligne en pause"
    wait_for_running_sync
    ok "aucune sync en cours"

    step "3. Mise à jour du moteur"
    git -C "$ENGINE" merge --ff-only --quiet "$upstream"
    ok "moteur à $(git -C "$ENGINE" log --oneline -1)"
    [[ -f "$ENGINE/scripts/watch.py" ]] || { false; }
    [[ -f "$ENGINE/scripts/garmin_watch.py" ]] || { false; }

    step "4. Contrôles avant reprise"
    local before after out
    before="$(cat "$BACKUP/tokens-before.txt")"
    after="$(resolve_tokens)"
    if [[ "$after" != "$before" ]]; then
        printf '  ✖ jetons résolus : %s (avant : %s)\n' "$after" "$before" >&2
        false
    fi
    ok "jetons résolus inchangés : $after"
    if ! out="$(cd "$WS" && env -u ARC_LOCK_WORKSPACE ARC_WORKSPACE="$WS" timeout 180 python3 "$ENGINE/scripts/watch.py" --dry-run 2>&1)"; then
        printf '  ✖ watch.py --dry-run a échoué :\n%s\n' "$out" >&2
        false
    fi
    info "watch.py --dry-run : $(tail -n1 <<<"$out")"
    if grep -qE 'Authentication|HTTP 401|garmin-mcp-auth' <<<"$out"; then
        printf '  ✖ authentification Garmin refusée\n' >&2
        false
    fi
    ok "watch.py fonctionne avec ce workspace"

    step "5. Ligne cron définitive"
    printf '%s\n' "$CRON" | awk -v old="$LINE" -v new="$new_line" '$0 == old { print new; next } { print }' | crontab -
    ORIG_CRON=""    # reprise faite : plus de remise automatique
    trap - ERR INT TERM EXIT
    local check_cron
    check_cron="$(active_marker_lines "$(read_cron)")"
    [[ "$(grep -c . <<<"$check_cron")" -eq 1 && "$check_cron" == "$new_line" ]] \
        || die "crontab inattendue après écriture — rollback : ./migrate-sync-127.sh rollback $BACKUP"
    ok "$new_line"

    if [[ "$fix_args" -eq 1 ]]; then
        step "6. Options mémorisées pour /update-coach"
        local args=() line prev=""
        if [[ -f "$CONF/install-args" ]]; then
            while IFS= read -r line || [[ -n "$line" ]]; do
                [[ -n "$line" ]] || continue
                if [[ "$line" == "--workspace" ]]; then prev="$line"; continue; fi
                if [[ "$prev" == "--workspace" ]]; then prev=""; continue; fi
                args+=("$line")
            done <"$CONF/install-args"
        fi
        args+=(--workspace "$WS")
        printf '%s\n' "${args[@]}" | grep -qx -- '--daily-sync' || args+=(--daily-sync)
        info "aperçu : ./install.sh ${args[*]} --no-auth --dry-run"
        local preview cron_block
        preview="$(cd "$ENGINE" && ./install.sh "${args[@]}" --no-auth --dry-run </dev/null 2>&1 || true)"
        printf '%s\n' "$preview" > "$BACKUP/install-dry-run.txt"
        info "aperçu complet (à relire : services chat / Remote Control) : $BACKUP/install-dry-run.txt"
        cron_block="$(grep -F "$MARKER" <<<"$preview" | grep -F 'ARC_WORKSPACE=' || true)"
        if [[ "$(grep -c . <<<"$cron_block")" -eq 1 && "$cron_block" == *"ARC_WORKSPACE=\"$WS\""* \
              && "$cron_block" == *"scripts/watch.py"* ]] \
           && ! grep -qE "$SCHEDULE_NOTICE_RE" <<<"$preview"; then
            printf '%s\n' "${args[@]}" > "$CONF/install-args"
            chmod 600 "$CONF/install-args"
            ok "install-args : ${args[*]}"
            info "La prochaine /update-coach réinstallera $WS (et réécrira la même ligne cron)."
        else
            warn "aperçu inattendu : install-args NON modifié. Lignes cron de l'aperçu :"
            printf '%s\n' "${cron_block:-    (aucune)}"
        fi
    fi

    printf '\nMigration faite. Sauvegarde : %s\nDans ~15 min : ./migrate-sync-127.sh verify\n' "$BACKUP"
}

# ---------------------------------------------------------------------------------------------------------
verify() {
    discover
    step "Vérification"
    [[ "$PAUSED" -eq 0 ]] && ok "ligne active" || fail "ligne encore en pause"
    [[ "$(basename "$SCRIPT")" == "watch.py" ]] && ok "watch.py" || warn "toujours $(basename "$SCRIPT")"
    local backup started state last_check
    backup="$(ls -1d "$CONF"/backup-migration-127-* 2>/dev/null | tail -n1 || true)"
    started="$(cat "$backup/started-at.txt" 2>/dev/null || echo 0)"
    state="$WS/logs/.watch-state.json"
    last_check="$(python3 - "$state" <<'PY' 2>/dev/null || echo 0
import json, sys
from datetime import datetime
print(int(datetime.fromisoformat(json.load(open(sys.argv[1]))["last_check"]).timestamp()))
PY
)"
    if (( last_check > started )); then ok "le watch est passé depuis la migration ($(date -d "@$last_check" 2>/dev/null || echo "$last_check"))"
    else warn "pas encore de passage du watch depuis la migration (attendre 15 min)"; fi
    tail -n 3 "$WS/logs/watch.log" 2>/dev/null | sed 's/^/    /'
    local c
    for c in daily_sync_scheduled garmin_token garmin_token_perms; do
        if out="$(cd "$WS" && python3 "$ENGINE/scripts/coach_doctor.py" --workspace "$WS" --check "$c" 2>&1)"; then
            ok "coach_doctor $c"
        else
            warn "coach_doctor $c :"; sed 's/^/    /' <<<"$out" | tail -n 6
        fi
    done
    printf '\nBilan : %d échec(s), %d avertissement(s).\n' "$FAILS" "$WARNS"
}

rollback() {
    local dir="${1:-}"
    [[ -n "$dir" && -f "$dir/crontab.txt" ]] || die "usage : rollback <dossier backup-migration-127-…>"
    local engine head
    engine="$(cat "$dir/engine-path.txt")"
    head="$(cat "$dir/engine-head.txt")"
    step "Retour arrière depuis $dir"
    crontab "$dir/crontab.txt"
    ok "crontab d'origine remise"
    git -C "$engine" reset --keep "$head"
    ok "moteur remis à $(git -C "$engine" log --oneline -1)"
    if [[ -f "$dir/install-args" ]]; then cp -p "$dir/install-args" "$CONF/install-args"; ok "install-args remis"; fi
    if [[ -f "$dir/workspace" ]]; then cp -p "$dir/workspace" "$CONF/workspace"; ok "workspace mémorisé remis"; fi
}

case "${1:-}" in
    check)
        shift
        for a in "$@"; do
            case "$a" in
                --no-fetch) FETCH=0 ;;
                *) die "option inconnue : $a" ;;
            esac
        done
        check; [[ "$FAILS" -eq 0 ]] ;;
    migrate)  shift; migrate "$@" ;;
    verify)   verify; [[ "$FAILS" -eq 0 ]] ;;
    rollback) shift; rollback "$@" ;;
    *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
