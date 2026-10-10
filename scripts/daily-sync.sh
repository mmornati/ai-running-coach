#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — synchronisation Garmin automatique (headless)
#
# Lance le skill /garmin-daily-sync avec l'exécuteur configuré (Claude Code,
# Codex CLI, GitHub Copilot, OpenCode, Gemini CLI ou Cursor Agent), journalise,
# extrait le bloc ```resume``` et l'envoie
# en notification push via scripts/notify.sh. Par défaut : abonnement (pas de
# clé API). Avec [sync].api_key_env : mode API (OpenRouter, Anthropic…), clé lue
# dans ~/.config/ai-running-coach/llm.env et injectée dans le seul process du
# runner (jamais dans votre shell : ANTHROPIC_API_KEY casse Remote Control).
#
# Usage :
#   scripts/daily-sync.sh              # exécution (appelée par cron/launchd)
#   scripts/daily-sync.sh --dry-run    # affiche la commande sans l'exécuter
#   scripts/daily-sync.sh --runner copilot   # ou claude|codex|opencode|gemini|cursor
#   scripts/daily-sync.sh --trigger activity:123,morning   # passé par garmin_watch.py
#
# Configuration : section [sync] de config/workspace.toml (runner, model, base_url,
# api_key_env, daily_budget_eur, lookback_days) et [notifications] (voir
# scripts/setup-ntfy.sh). S'exécute dans le workspace (ARC_WORKSPACE / ~/.config/ai-running-coach/workspace, sinon ce dépôt).
# Journaux : <workspace>/logs/sync-YYYY-MM-DD.log (gitignoré). Verrou : logs/.sync.lock.
# =============================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/config.sh"
# shellcheck source=lib/sync_tools.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/sync_tools.sh"

DRY_RUN=0
RUNNER=""
TRIGGER=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --runner) RUNNER="$2"; shift 2 ;;
        --trigger) TRIGGER="$2"; shift 2 ;;
        --help|-h) sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Option inconnue : $1 (voir --help)" ;;
    esac
done

# cron/launchd démarrent avec un PATH minimal : ajoute les emplacements usuels
# de claude, codex, uv et garmin-mcp.
MAC_APP_SUPPORT="$HOME/Library/Application Support/AI Running Coach"
export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$HOME/.claude/bin:$MAC_APP_SUPPORT/node-runtime/bin:$MAC_APP_SUPPORT/npm-tools/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

RUNNER="${RUNNER:-$(toml_get sync runner claude)}"
LOOKBACK="$(toml_get sync lookback_days 2)"
GIT_AUTOCOMMIT="$(toml_get sync git_autocommit false)"
SKILL_FILE="$ARC_ENGINE_ROOT/skills/garmin-daily-sync/SKILL.md"
LOG_DIR="$ARC_WORKSPACE/logs"
LOG_FILE="$LOG_DIR/sync-$(date +%F).log"
LOCK_FILE="$LOG_DIR/.sync.lock"
NOTIFY="$ARC_ENGINE_ROOT/scripts/notify.sh"

# Mode API / modèle (#chat) : [sync].api_key_env non vide = clé lue dans llm.env
# (jamais dans le TOML). model : requis pour opencode, optionnel pour claude API.
SYNC_MODEL="$(toml_get sync model "")"
SYNC_BASE_URL="$(toml_get sync base_url "")"
API_KEY_ENV="$(toml_get sync api_key_env "")"
DAILY_BUDGET_EUR="$(toml_get sync daily_budget_eur 0.5)"
USD_EUR_RATE="$(toml_get chat usd_eur_rate 0.92)"
LLM_ENV_FILE="${ARC_LLM_ENV:-$HOME/.config/ai-running-coach/llm.env}"
SPEND_FILE="$LOG_DIR/.sync-spend-$(date +%F)"
# Variables « NOM=valeur » réservées au process du runner (voir load_llm_env).
RUNNER_ENV=()
# Format de sortie du runner : text | claude-json | opencode-json (voir build_command).
OUTPUT_KIND="text"
OC_CONFIG_FILE="$ARC_WORKSPACE/.arc/sync/opencode.json"
GEMINI_CONFIG_FILE="$ARC_WORKSPACE/.arc/sync/gemini-system.json"

# Déclencheurs détectés par scripts/garmin_watch.py (#watch) : un indice pour
# l'agent (quoi récupérer en priorité), jamais une restriction — les dates
# manquantes de la fenêtre restent récupérées. Format fermé : il finit dans un prompt.
if [[ -n "$TRIGGER" && ! "$TRIGGER" =~ ^(morning|activity:[0-9]+)(,(morning|activity:[0-9]+))*$ ]]; then
    die "Déclencheur invalide : « $TRIGGER » (attendu : morning, activity:<id>, séparés par des virgules)."
fi
SYNC_ARGS="lookback_days=$LOOKBACK"
[[ -z "$TRIGGER" ]] || SYNC_ARGS+=", trigger=$TRIGGER"

[[ -f "$SKILL_FILE" ]] || die "Skill introuvable : $SKILL_FILE"
mkdir -p "$LOG_DIR"

# Source de données (#68) — [data].source, défaut garmin (voir AGENTS.md,
# « Backends MCP », et install.sh --source). Décide le serveur MCP autorisé,
# le libellé des notifications et la commande de renouvellement suggérée.
SOURCE="$(toml_get data source garmin)"
# Durcissement du run non surveillé : une consigne injectée dans une donnée synchronisée
# (nom d'activité, description d'événement, fichier tiré par `git pull`) ne doit pas pouvoir
# exécuter du Python arbitraire ni réécrire ce que cron exécutera ensuite.
#   - Python : seulement les scripts du moteur (`scripts/`, `skills/*/scripts/`), jamais
#     `python3 -c …` ni un fichier écrit ailleurs pendant le run.
#   - Écriture refusée sur ces mêmes scripts, sur les skills et sur la configuration MCP/IDE
#     (une règle `Edit(…)` couvre tous les outils d'écriture de fichiers, Write compris).
PYTHON_TOOLS="Bash(python3 scripts/*),Bash(python3 skills/*)"
PROTECTED_PATHS="Edit(scripts/**),Edit(skills/**),Edit(local/skills/**),Edit(local/agents/**),Edit(.claude/**),Edit(.mcp.json)"
if [[ "$SOURCE" == "strava" ]]; then
    # Source Strava (#164) : serveur MCP communautaire r-huijts/strava-mcp (nom « strava »,
    # install.sh --source strava). Lecture seule : on autorise tout le serveur, puis on retire
    # explicitement les trois outils qui agissent — `connect-strava` (ouvre un navigateur et un
    # port local : personne pour répondre en headless), `disconnect-strava` (efface les jetons) et
    # `star-segment` (ÉCRITURE côté Strava). Pas de leanproxy (garmin uniquement).
    CLAUDE_TOOLS="mcp__strava,Agent,Task,Skill,Read,Write,Edit,Glob,Grep,$PYTHON_TOOLS"
    CLAUDE_DISALLOWED="mcp__strava__connect-strava,mcp__strava__disconnect-strava,mcp__strava__star-segment"
    CLAUDE_DISALLOWED+=",$PROTECTED_PATHS"
    SOURCE_LABEL="Strava"
    MCP_SERVER_NAME="strava"
    AUTH_CMD_HINT="demandez à l'agent (session interactive) d'exécuter l'outil connect-strava avec force=true"
elif [[ "$SOURCE" == "intervals" ]]; then
    # Outils autorisés en mode non interactif : serveur MCP intervals (tous ses
    # outils), délégation au coach (Agent/Task), skills, lecture/écriture des
    # MD, scripts Python du projet. Rien d'autre. Pas de leanproxy : passerelle
    # garmin uniquement (install.sh refuse déjà --use-leanproxy + --source intervals).
    CLAUDE_TOOLS="mcp__intervals,Agent,Task,Skill,Read,Write,Edit,Glob,Grep,$PYTHON_TOOLS"
    # #165 : même règle que pour Garmin — le run headless n'écrit JAMAIS côté intervals.icu
    # (personne ne peut confirmer). `mcp__intervals` autorise tout le serveur : on retire
    # ses outils d'écriture (annotation `readOnlyHint: False` dans server.py du fork
    # hhopke au commit épinglé) et ses téléchargements (`output_path` = écriture d'un
    # fichier local arbitraire, hors des règles `Edit(…)` ; `fit-download` reste le
    # chemin du projet). Les anciens noms sans préfixe (eddmann, avant #165) sont
    # aussi retirés : une installation pas encore mise à jour reste protégée.
    # Liste partagée avec les autres exécuteurs : scripts/lib/sync_tools.sh.
    CLAUDE_DISALLOWED=""
    # Ancien serveur eddmann : mêmes noms sans préfixe (+ `duplicate_event` au singulier).
    for _tool in $(sync_write_tools intervals); do
        CLAUDE_DISALLOWED+="mcp__intervals__${_tool},"
    done
    CLAUDE_DISALLOWED+="$PROTECTED_PATHS"
    SOURCE_LABEL="Intervals.icu"
    MCP_SERVER_NAME="intervals"
    AUTH_CMD_HINT="(cd \"$HOME/.config/ai-running-coach/intervals-icu-mcp\" && intervals-icu-mcp-auth)"
else
    # Outils autorisés en mode non interactif : serveur MCP garmin (tous ses outils),
    # délégation au coach (Agent/Task), skills, lecture/écriture des MD, scripts
    # Python du projet. Rien d'autre.
    CLAUDE_TOOLS="mcp__garmin,mcp__leanproxy,Agent,Task,Skill,Read,Write,Edit,Glob,Grep,$PYTHON_TOOLS"
    # #133 : la synchronisation headless ne doit JAMAIS écrire côté Garmin (personne ne peut
    # confirmer) — ni matériel, ni séance planifiée, ni parcours (le skill l'interdit déjà :
    # « jamais d'écriture de plan ni de push ici »). `mcp__garmin` autorise tous les outils du
    # serveur : on retire explicitement ses outils d'écriture. LIMITE : en mode passerelle, l'appel
    # passe par `mcp__leanproxy__invoke_tool(server="garmin", tool=...)`, dont l'outil est unique
    # et ne peut pas être filtré par nom de sous-outil — seule la consigne du skill
    # (`garmin-daily-sync`) protège alors ; préférer le mode direct pour un run non surveillé.
    CLAUDE_DISALLOWED="mcp__garmin__add_gear_to_activity,mcp__garmin__remove_gear_from_activity"
    CLAUDE_DISALLOWED+=",mcp__garmin__schedule_workouts,mcp__garmin__schedule_week,mcp__garmin__upload_workout"
    CLAUDE_DISALLOWED+=",mcp__garmin__create_strength_workout,mcp__garmin__delete_workout"
    CLAUDE_DISALLOWED+=",mcp__garmin__unschedule_workout,mcp__garmin__unschedule_workouts,mcp__garmin__upload_course"
    # #167 : idem pour le journal alimentaire et l'hydratation (poussée des apports, opt-in
    # `[nutrition].garmin_sync`) — jamais d'écriture nutrition sans le « oui » de l'athlète.
    CLAUDE_DISALLOWED+=",mcp__garmin__log_food,mcp__garmin__log_custom_food,mcp__garmin__create_custom_food"
    CLAUDE_DISALLOWED+=",mcp__garmin__update_custom_food,mcp__garmin__upsert_and_log,mcp__garmin__delete_food_log"
    CLAUDE_DISALLOWED+=",mcp__garmin__add_hydration_data"
    # #222 : le poids se LIT dans Garmin (get_daily_weigh_ins/get_weigh_ins), jamais il ne s'y écrit.
    CLAUDE_DISALLOWED+=",mcp__garmin__add_weigh_in,mcp__garmin__add_weigh_in_with_timestamps"
    CLAUDE_DISALLOWED+=",mcp__garmin__delete_weigh_ins,mcp__garmin__add_body_composition"
    CLAUDE_DISALLOWED+=",$PROTECTED_PATHS"
    SOURCE_LABEL="Garmin"
    MCP_SERVER_NAME="garmin"
    AUTH_CMD_HINT="uv run garmin-mcp-auth"
fi
# En mode -p, un serveur MCP déclaré dans .mcp.json (portée projet) n'est chargé
# que s'il a été approuvé interactivement ; on le passe explicitement.
MCP_CONFIG="$ARC_WORKSPACE/.mcp.json"

# ---------------------------------------------------------------------------
# Mode API : clé du fournisseur (OpenRouter, Anthropic…)
# ---------------------------------------------------------------------------
# Lit ~/.config/ai-running-coach/llm.env (lignes NOM=valeur, mode 600) et ne
# retient QUE la variable nommée par [sync].api_key_env, dans RUNNER_ENV : elle
# n'est passée qu'au process du runner (`env NOM=valeur runner…`), jamais
# exportée dans ce shell ni dans celui de l'utilisateur. Une variable déjà
# présente dans l'environnement n'est pas écrasée. La valeur n'est JAMAIS
# affichée ni journalisée (dry-run compris). Statut 1 : clé introuvable.
load_llm_env() {
    RUNNER_ENV=()
    [[ -n "$API_KEY_ENV" ]] || return 0
    [[ "$API_KEY_ENV" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
        || die "[sync].api_key_env : nom de variable invalide (« $API_KEY_ENV »)."
    if [[ -n "${!API_KEY_ENV:-}" ]]; then
        RUNNER_ENV+=("$API_KEY_ENV=${!API_KEY_ENV}")
        return 0
    fi
    [[ -f "$LLM_ENV_FILE" ]] || return 1
    if [[ -n "$(find "$LLM_ENV_FILE" -maxdepth 0 -perm -077 2>/dev/null)" ]]; then
        warn "$LLM_ENV_FILE est lisible par d'autres utilisateurs — chmod 600 \"$LLM_ENV_FILE\""
    fi
    local line name value
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        name="${BASH_REMATCH[2]}"
        value="${BASH_REMATCH[3]}"
        [[ "$name" == "$API_KEY_ENV" ]] || continue
        # Guillemets simples ou doubles autour de la valeur.
        if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
        [[ -n "$value" ]] || continue
        RUNNER_ENV+=("$name=$value")
    done < "$LLM_ENV_FILE"
    [[ "${#RUNNER_ENV[@]}" -gt 0 ]]
}

# ---------------------------------------------------------------------------
# Runner opencode : configuration locale au projet
# ---------------------------------------------------------------------------
# Générée à chaque run dans <workspace>/.arc/sync/opencode.json (jetable, .arc/
# s'ignore lui-même) et passée par OPENCODE_CONFIG — elle est fusionnée AU-DESSUS
# de ~/.config/opencode/opencode.json. La clé n'y figure jamais : « {env:NOM} ».
# Permissions : écriture limitée aux dossiers de données, bash refusé, web
# refusé, et tous les outils MCP d'ÉCRITURE refusés (la synchronisation ne pousse
# jamais de séance : c'est le coach, sur demande). Nommage OpenCode d'un outil
# MCP : <serveur>_<outil> (# À VÉRIFIER sur un run réel avec un serveur MCP).
OC_CONFIG_PY='
import json, sys

model, base_url, api_key_env, mcp_path = sys.argv[1:5]
provider_id, _, model_id = model.partition("/")
provider = {}
if base_url:
    options = {"baseURL": base_url}
    if api_key_env:
        options["apiKey"] = "{env:%s}" % api_key_env
    provider[provider_id] = {"npm": "@ai-sdk/openai-compatible", "options": options,
                             "models": {model_id: {}}}
elif api_key_env:
    provider[provider_id] = {"options": {"apiKey": "{env:%s}" % api_key_env}}

WRITE_PREFIXES = ("schedule_", "upload_", "delete_", "unschedule_", "create_", "add_",
                  "set_", "log_", "update_", "upsert_", "bulk_", "request_reload")
mcp, permission = {}, {}
try:
    servers = json.load(open(mcp_path, encoding="utf-8")).get("mcpServers") or {}
except (OSError, ValueError):
    servers = {}
for name, spec in servers.items():
    if not isinstance(spec, dict) or not spec.get("command"):
        continue
    env = {k: str(v) for k, v in (spec.get("env") or {}).items()}
    # Liste blanche Garmin : on retire les outils d ecriture de la liste passee au serveur.
    tools = env.get("GARMIN_ENABLED_TOOLS")
    if tools:
        env["GARMIN_ENABLED_TOOLS"] = ",".join(
            t for t in tools.split(",") if not t.startswith(WRITE_PREFIXES))
    entry = {"type": "local", "command": [spec["command"]] + [str(a) for a in spec.get("args") or []],
             "enabled": True}
    if env:
        entry["environment"] = env
    mcp[name] = entry
    for prefix in WRITE_PREFIXES:
        permission["%s_%s*" % (name, prefix)] = "deny"
    if name.lower().startswith("strava"):
        # Strava (#164) : outils de r-huijts/strava-mcp qui AGISSENT (noms à tirets, hors des
        # préfixes ci-dessus) : connexion OAuth (navigateur), déconnexion, écriture Strava.
        for tool in ("connect-strava", "disconnect-strava", "star-segment"):
            permission["%s_%s" % (name, tool)] = "deny"
    if name == "leanproxy":
        # Passerelle : les outils appeles a travers elle echappent aux motifs ci-dessus.
        permission["leanproxy_*"] = "deny"

permission.update({
    "edit": {"*": "deny", "activities/**": "allow", "medical/**": "allow",
             "nutrition/**": "allow", "planning/**": "allow", "rapports/**": "allow", "gear/**": "allow"},
    "bash": "deny", "webfetch": "deny", "websearch": "deny",
    "external_directory": "deny", "task": "allow", "skill": "allow",
})
config = {"$schema": "https://opencode.ai/config.json", "permission": permission}
if model:
    config["model"] = model
if provider:
    config["provider"] = provider
if mcp:
    config["mcp"] = mcp
print(json.dumps(config, ensure_ascii=False, indent=2))
'

opencode_config_json() {
    python3 -c "$OC_CONFIG_PY" "$SYNC_MODEL" "$SYNC_BASE_URL" "$API_KEY_ENV" "$MCP_CONFIG"
}

# Configuration de sécurité propre au run Gemini. Le fichier est chargé comme
# couche système pour ce seul process : scripts Python du moteur + écritures MD,
# serveur sportif limité à ses outils de lecture. La configuration interactive
# de l'utilisateur n'est pas modifiée.
GEMINI_CONFIG_PY='
import json, sys
path, source, prefixes, reads, writes = sys.argv[1:6]
try:
    project = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    project = {}
servers = project.get("mcpServers") or {}
write_prefixes = tuple(prefixes.split())
writes = writes.split()
safe = {}
for name, spec in servers.items():
    if name != source or not isinstance(spec, dict):
        continue
    item = dict(spec)
    item["trust"] = True
    env = dict(item.get("env") or {})
    tools = env.get("GARMIN_ENABLED_TOOLS", "")
    if source == "garmin" and tools:
        kept = [t for t in tools.split(",") if not t.startswith(write_prefixes)]
        env["GARMIN_ENABLED_TOOLS"] = ",".join(kept)
        item["includeTools"] = kept
    elif source != "garmin":
        item["includeTools"] = reads.split()
    # Refus nommés en plus de la liste blanche : excludeTools prime sur includeTools.
    item["excludeTools"] = writes
    if env:
        item["env"] = env
    safe[name] = item
if not safe:
    # Serveur absent (mode passerelle leanproxy, IDE non configuré) : un run sans
    # aucun outil de données « réussirait » à vide. On échoue explicitement.
    sys.stderr.write(f"serveur MCP « {source} » absent de {path}\n")
    sys.exit(3)
print(json.dumps({
    "tools": {"core": ["read_file", "read_many_files", "list_directory", "glob", "grep_search",
                         "write_file", "replace", "run_shell_command(python3 scripts/)",
                         "run_shell_command(python3 skills/)"]},
    "mcpServers": safe,
}, ensure_ascii=False, indent=2))
'

gemini_config_json() {
    python3 -c "$GEMINI_CONFIG_PY" "$ARC_WORKSPACE/.gemini/settings.json" "$MCP_SERVER_NAME" \
        "$SYNC_GARMIN_WRITE_PREFIXES" "$(sync_read_tools "$SOURCE" | tr '\n' ' ')" \
        "$(sync_write_tools "$SOURCE" | tr '\n' ' ')"
}

# Cursor : chaque outil d'écriture de la source est-il refusé (`Mcp(serveur:outil)`)
# dans .cursor/cli.json ? Sans ces refus, `--force` les approuverait en headless.
cursor_denies_writes() {
    # shellcheck disable=SC2046  # un nom d'outil par mot (aucun ne contient d'espace)
    python3 -c '
import json, sys
path, server = sys.argv[1:3]
try:
    deny = (json.load(open(path, encoding="utf-8")).get("permissions") or {}).get("deny") or []
except (OSError, ValueError, AttributeError):
    sys.exit(1)
missing = [t for t in sys.argv[3:] if f"Mcp({server}:{t})" not in deny]
sys.exit(1 if missing else 0)
' "$ARC_WORKSPACE/.cursor/cli.json" "$MCP_SERVER_NAME" $(sync_write_tools "$SOURCE")
}

# ---------------------------------------------------------------------------
# Lecture de la sortie d'un runner qui rapporte son coût (opencode / claude API)
# ---------------------------------------------------------------------------
# Usage : runner_output <mode>   (stdin = sortie brute du runner)
#   text  : texte de l'agent (celui d'où l'on extrait le bloc ```resume)
#   cost  : coût en USD (vide si non rapporté)
#   error : texte d'erreur du FOURNISSEUR (vide si aucune erreur)
# Sortie non JSON : `text` la rend telle quelle, les autres ne rendent rien.
# Formats — opencode : `opencode run --format json`, un événement JSON par ligne
# (« text », « step_finish » avec part.cost, « error » avec error.data.message),
# vérifié sur OpenCode 1.18 ; claude : `--output-format json`, objet unique
# (« result », « total_cost_usd », « is_error », « api_error_status »).
RUNNER_OUTPUT_PY='
import json, sys

mode, kind = sys.argv[1:3]
raw = sys.stdin.read()
texts, errors = [], []
cost = None

def add_cost(value):
    global cost
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cost = (cost or 0.0) + float(value)

if kind == "claude-json":
    try:
        obj = json.loads(raw)
    except ValueError:
        obj = None
    if isinstance(obj, dict):
        result = obj.get("result")
        if isinstance(result, str):
            texts.append(result)
        add_cost(obj.get("total_cost_usd"))
        if obj.get("is_error"):
            errors.append("%s (HTTP %s)" % (result or "", obj.get("api_error_status") or "?"))
    else:
        texts.append(raw)
else:
    parsed = 0
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        parsed += 1
        part = ev.get("part") or {}
        if ev.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif ev.get("type") == "step_finish":
            add_cost(part.get("cost"))
        elif ev.get("type") == "error":
            err = ev.get("error") or {}
            data = err.get("data") or {}
            errors.append(" ".join(str(x) for x in (
                err.get("name"), data.get("statusCode"), data.get("message")) if x))
    if not parsed:
        texts.append(raw)

if mode == "text":
    print("\n".join(texts))
elif mode == "cost":
    print("" if cost is None else "%.6f" % cost)
elif mode == "error":
    print("\n".join(errors))
'

runner_output() { python3 -c "$RUNNER_OUTPUT_PY" "$1" "$OUTPUT_KIND"; }

# ---------------------------------------------------------------------------
# Budget quotidien — uniquement si le runner rapporte son coût
# ---------------------------------------------------------------------------
# Cumul du jour (en EUR) dans <workspace>/logs/.sync-spend-YYYY-MM-DD. Runner
# sans coût rapporté (claude/codex par abonnement) : jamais de plafond.
budget_enforced() {
    [[ "$OUTPUT_KIND" != "text" ]] || return 1
    awk -v b="$DAILY_BUDGET_EUR" 'BEGIN { exit !(b + 0 > 0) }'
}

spent_today_eur() {
    local v=""
    [[ -f "$SPEND_FILE" ]] && v="$(head -n1 "$SPEND_FILE" 2>/dev/null)"
    [[ "$v" =~ ^[0-9]+(\.[0-9]+)?$ ]] || v=0
    printf '%s' "$v"
}

over_budget() {
    awk -v s="$(spent_today_eur)" -v b="$DAILY_BUDGET_EUR" 'BEGIN { exit !(s + 0 >= b + 0) }'
}

record_spend() {
    local cost_usd="$1"
    [[ "$cost_usd" =~ ^[0-9]+(\.[0-9]+)?$ ]] || return 0
    awk -v s="$(spent_today_eur)" -v c="$cost_usd" -v r="$USD_EUR_RATE" \
        'BEGIN { printf "%.4f\n", s + c * r }' > "$SPEND_FILE"
    log "Coût du run : ${cost_usd} USD — cumul du jour : $(spent_today_eur) EUR (plafond $DAILY_BUDGET_EUR EUR)"
}

# ---------------------------------------------------------------------------
# Échec du FOURNISSEUR LLM (clé refusée, crédits épuisés) — jamais un 401 Garmin
# ---------------------------------------------------------------------------
# On ne regarde QUE le texte d'erreur rapporté par le runner (runner_output
# error) — événements « error » d'opencode, is_error de claude — jamais tout
# le journal : un 401 Garmin y a un contexte Garmin explicite et reste traité
# par detect_auth_failure. Un texte d'erreur qui nomme Garmin/Intervals est
# écarté ici. Motifs à VÉRIFIER contre des échecs réels (# À VÉRIFIER) : 401,
# « invalid api key », « user not found » (clé) ; 402, « credits », « payment
# required », « credit balance » (solde). PROVIDER_FAILURE : auth | credits | "".
PROVIDER_FAILURE=""
detect_provider_failure() {
    local err="$1"
    PROVIDER_FAILURE=""
    [[ -n "$err" ]] || return 1
    if printf '%s' "$err" | grep -qiE 'garmin|intervals|strava'; then
        return 1
    fi
    if printf '%s' "$err" | grep -qiE '(^|[^0-9])402([^0-9]|$)|insufficient (credits|funds)|payment required|credit balance|requires more credits|out of credits'; then
        PROVIDER_FAILURE="credits"
        return 0
    fi
    if printf '%s' "$err" | grep -qiE '(^|[^0-9])401([^0-9]|$)|invalid (x-)?api[ _-]?key|incorrect api key|user not found|authentication[_ ]error|unauthorized|no auth'; then
        PROVIDER_FAILURE="auth"
        return 0
    fi
    return 1
}

provider_label() {
    if [[ "$RUNNER" == "opencode" && -n "$SYNC_MODEL" ]]; then
        local p="${SYNC_MODEL%%/*}"
        printf '%s' "${p:-fournisseur LLM}"
    else
        printf 'Anthropic'
    fi
}

# Corps du skill sans son front matter, passé directement aux exécuteurs
# headless afin que le comportement ne dépende pas de leurs commandes projet.
skill_prompt() {
    local body
    body="$(awk 'NR==1 && /^---$/ {fm=1; next} fm && /^---$/ {fm=0; next} !fm' "$SKILL_FILE")"
    printf '%s. Follow these instructions exactly:\n%s' "$SYNC_ARGS" "$body"
}

build_command() {
    OUTPUT_KIND="text"
    case "$RUNNER" in
        claude)
            have claude || [[ "$DRY_RUN" -eq 1 ]] || die "claude introuvable — installez Claude Code : curl -fsSL https://claude.ai/install.sh | bash"
            CMD=(claude -p "/garmin-daily-sync ($SYNC_ARGS)"
                 --permission-mode acceptEdits
                 --allowedTools "$CLAUDE_TOOLS")
            if [[ -n "$CLAUDE_DISALLOWED" ]]; then
                CMD+=(--disallowedTools "$CLAUDE_DISALLOWED")
            fi
            if [[ -n "$API_KEY_ENV" ]]; then
                # Mode API : sortie JSON pour lire le coût (budget) et l'erreur du
                # fournisseur ; le texte de l'agent en est extrait avant tout
                # traitement, donc bloc ```resume et détection 401 Garmin inchangés.
                OUTPUT_KIND="claude-json"
                CMD+=(--output-format json)
                [[ -z "$SYNC_MODEL" ]] || CMD+=(--model "$SYNC_MODEL")
            else
                CMD+=(--output-format text)
            fi
            if [[ -f "$MCP_CONFIG" ]]; then
                CMD+=(--mcp-config "$MCP_CONFIG" --strict-mcp-config)
            else
                warn "$MCP_CONFIG absent — lancez './install.sh --ide claude' (serveur MCP $SOURCE_LABEL)."
            fi ;;
        codex)
            have codex || [[ "$DRY_RUN" -eq 1 ]] || die "codex introuvable — installez Codex CLI : npm i -g @openai/codex"
            # Codex n'a pas de slash-command projet : on passe le corps du skill en prompt.
            CMD=(codex exec --full-auto --cd "$ARC_WORKSPACE" "$(skill_prompt)") ;;
        copilot)
            have copilot || [[ "$DRY_RUN" -eq 1 ]] || die "copilot introuvable — relancez l'installation guidée GitHub Copilot."
            # Le MCP du workspace est chargé explicitement en mode prompt ; permissions
            # minimales : lecture/écriture des MD, scripts Python du projet et source sportive.
            # `--allow-tool=<serveur>` autorise TOUT le serveur : ses outils d'écriture sont
            # refusés un par un (`--deny-tool` prime toujours sur `--allow-tool`).
            CMD=(env GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP=true
                 copilot -p "$(skill_prompt)" -s --no-ask-user
                 --allow-tool=read --allow-tool=write
                 '--allow-tool=shell(python3:*)' "--allow-tool=$MCP_SERVER_NAME")
            local _tool
            for _tool in $(sync_write_tools "$SOURCE"); do
                CMD+=("--deny-tool=$MCP_SERVER_NAME($_tool)")
            done ;;
        opencode)
            have opencode || [[ "$DRY_RUN" -eq 1 ]] || die "opencode introuvable — installez OpenCode : curl -fsSL https://opencode.ai/v2/install | bash"
            if [[ -n "$SYNC_MODEL" && "$SYNC_MODEL" != */* ]]; then
                die "[sync].model doit être au format fournisseur/modèle (ex. openrouter/deepseek/deepseek-v4.1-flash)."
            fi
            # Sans modèle explicite, OpenCode réutilise le fournisseur/modèle choisi
            # lors de sa connexion initiale. La config locale garde les permissions et MCP.
            OUTPUT_KIND="opencode-json"
            CMD=(opencode run --format json)
            [[ -z "$SYNC_MODEL" ]] || CMD+=(--model "$SYNC_MODEL")
            CMD+=(--dir "$ARC_WORKSPACE" "$(skill_prompt)") ;;
        gemini)
            have gemini || [[ "$DRY_RUN" -eq 1 ]] || die "gemini introuvable — relancez l'installation guidée Gemini CLI."
            CMD=(env "GEMINI_CLI_SYSTEM_SETTINGS_PATH=$GEMINI_CONFIG_FILE"
                 gemini -p "$(skill_prompt)" --output-format text --approval-mode yolo --skip-trust
                 --allowed-mcp-server-names "$MCP_SERVER_NAME") ;;
        cursor)
            have cursor-agent || [[ "$DRY_RUN" -eq 1 ]] || die "cursor-agent introuvable — relancez l'installation guidée Cursor Agent."
            # `--force` approuve tout ce qui n'est pas refusé explicitement : on ne le passe
            # que si .cursor/cli.json refuse bien les outils d'écriture de la source
            # (écrits par install.sh). `--approve-mcps` : sans lui, le mode -p ne charge
            # pas les serveurs MCP du projet.
            cursor_denies_writes || [[ "$DRY_RUN" -eq 1 ]] \
                || die "Cursor : .cursor/cli.json ne refuse pas les outils d'écriture $SOURCE_LABEL — relancez ./install.sh (ou l'installation guidée) avant la synchronisation."
            CMD=(cursor-agent -p --force --approve-mcps --trust --output-format text "$(skill_prompt)") ;;
        *) die "Exécuteur inconnu : $RUNNER (claude|codex|copilot|opencode|gemini|cursor)" ;;
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

# Garde-fou déterministe (#56) : skills/garmin-daily-sync/SKILL.md promet un
# bloc ```resume de 5 lignes maximum, mais rien ne garantit qu'un run
# (agent capricieux, sortie tronquée) le respecte réellement — ce script ne
# doit jamais relayer une notification à rallonge sans y toucher. Tronque au
# besoin, en PRÉSERVANT en priorité la ligne « Pourquoi : » (raison de
# l'ajustement, #56) : elle est retirée des lignes gardées dans l'ordre puis
# rajoutée en dernière position plutôt que d'être perdue si le dépassement
# l'avait fait tomber au-delà des 5 premières. Sans ligne « Pourquoi : », se
# contente de garder les 5 premières lignes tel quel. Un bloc déjà conforme
# (<= 5 lignes) ressort inchangé — ce n'est qu'un filet de sécurité, pas le
# mécanisme normal (voir le SKILL.md : la ligne « Pourquoi : » y remplace
# `Alerte :` plutôt que de s'y ajouter, précisément pour ne jamais dépasser 5
# lignes en fonctionnement normal).
enforce_resume_cap() {
    local resume="$1" max=5
    local -a lines=()
    local line
    while IFS= read -r line; do
        line="${line%$'\r'}"   # CRLF éventuel (sortie d'un runner Windows) avant le test de vide
        [[ -n "$line" ]] && lines+=("$line")
    done <<< "$resume"
    if (( ${#lines[@]} <= max )); then
        printf '%s\n' "$resume"
        return 0
    fi
    local why="" idx
    local -a rest=()
    for idx in "${!lines[@]}"; do
        # `[^:]{0,4}` plutôt que `[[:space:]]*` : sous `LC_ALL=C` (imposé par ce
        # script), la classe POSIX `[[:space:]]` ne reconnaît que les espaces
        # ASCII — une espace insécable (NBSP, U+00A0, 2 octets en UTF-8) entre
        # « Pourquoi » et « : » ne matcherait pas et ferait perdre la ligne au
        # lieu de la préserver. `[^:]{0,4}` accepte NBSP et tout espacement
        # raisonnable sans dépendre de la locale.
        if [[ -z "$why" && "${lines[$idx]}" =~ ^Pourquoi[^:]{0,4}: ]]; then
            why="${lines[$idx]}"
        else
            rest+=("${lines[$idx]}")
        fi
    done
    local budget="$max"
    [[ -n "$why" ]] && budget=$((max - 1))
    local -a kept=()
    for ((idx = 0; idx < ${#rest[@]} && idx < budget; idx++)); do
        kept+=("${rest[$idx]}")
    done
    [[ -n "$why" ]] && kept+=("$why")
    printf '%s\n' "${kept[@]}"
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

# Telegram (#174) : résumé du run + boutons de retour en un geste (séance faite, RPE, douleur).
# ADDITIF à ntfy (les deux peuvent être actifs) et jamais bloquant : un échec Telegram ne doit
# ni faire échouer la synchronisation ni masquer le push ntfy. Sans modèle ni clé d'API.
telegram_summary() {
    local title="$1" priority="$2"
    shift 2
    [[ "$(toml_get telegram enabled false)" == "true" && "$(toml_get telegram send_summary true)" == "true" ]] || return 0
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} arc_telegram.py send-summary --title \"$title\" — $*"
        return 0
    fi
    printf '%s' "$*" | python3 "$ARC_ENGINE_ROOT/scripts/arc_telegram.py" send-summary \
        --workspace "$ARC_WORKSPACE" --title "$title" --priority "$priority" >>"$LOG_FILE" 2>&1 \
        || warn "Résumé Telegram non envoyé (voir $LOG_FILE)."
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
    # Garmin uniquement (#68, #164) : intervals-icu-mcp et Strava n'ont pas d'échéance de token lisible ici
    # comparable (clé API + ID athlète, pas d'OAuth à durée limitée) —
    # `coach_doctor.py --check garmin_token` n'a d'ailleurs aucun sens à lire
    # ici pour cette source. Skip explicite, jamais une fausse alerte Garmin.
    [[ "$SOURCE" == "garmin" ]] || return 0
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
    local run_log erreur_line raw_pattern erreur_pattern
    AUTH_FAILURE_KIND=""
    AUTH_FAILURE_LINE=""
    run_log="$(awk '/^===== /{buf=""} {buf = buf $0 ORS} END{printf "%s", buf}' "$LOG_FILE" 2>/dev/null)"
    if [[ "$SOURCE" == "strava" ]]; then
        # Textes réels du serveur r-huijts/strava-mcp (src/stravaClient.ts, commit épinglé par
        # install.sh) : « Failed to refresh Strava access token » et « Missing refresh
        # credentials. Please connect your Strava account first… » ; « Request failed with status
        # code 401 » est le message standard d'axios, que ce serveur relaie.
        raw_pattern='failed to refresh strava access token|missing refresh credentials|request failed with status code 401'
        erreur_pattern='^ERREUR.*(connect-strava|jetons? strava|strava.*(expir|invalid|refus)|401)'
    elif [[ "$SOURCE" == "intervals" ]]; then
        # Texte réel de `ICUAPIError` (intervals_icu_mcp/client.py, vérifié
        # contre hhopke/intervals-icu-mcp, identique chez eddmann) pour un 401 : "Unauthorized. Check
        # your API key and athlete ID.", restitué tel quel par ResponseBuilder.
        raw_pattern='unauthorized\. check your api key and athlete id'
        erreur_pattern='^ERREUR.*(intervals-icu-mcp-auth|cl[ée] api|athlete id|401)'
    else
        raw_pattern='garminconnectauthenticationerror|401 client error: unauthorized for url: https://connect(api)?\.garmin\.com|error retrieving [a-z ]+ data: authentication failed'
        erreur_pattern='^ERREUR.*(garmin-mcp-auth|tokens? garmin (expir|invalid|refus)|401)'
    fi
    if printf '%s' "$run_log" | grep -qiE "$raw_pattern"; then
        AUTH_FAILURE_KIND="raw"
        return 0
    fi
    erreur_line="$(printf '%s' "$run_log" | grep -iE "$erreur_pattern" | tail -n1)"
    if [[ -n "$erreur_line" ]]; then
        AUTH_FAILURE_KIND="erreur"
        AUTH_FAILURE_LINE="$erreur_line"
        return 0
    fi
    return 1
}

# Passerelle leanproxy SEULE dans .mcp.json (aucun serveur direct garmin/intervals) ?
# Sous opencode, les outils appelés à travers la passerelle (leanproxy_invoke_tool)
# échappent aux permissions par outil : la config générée refuse donc leanproxy_*
# entièrement, ce qui empêcherait toute lecture Garmin. On échoue vite plutôt que de
# synchroniser « à vide ».
mcp_gateway_only() {
    local config="${1:-$MCP_CONFIG}"
    [[ -f "$config" ]] || return 1
    python3 -c '
import json, sys
try:
    servers = json.load(open(sys.argv[1], encoding="utf-8")).get("mcpServers") or {}
except (OSError, ValueError, AttributeError):
    sys.exit(1)
# Serveur direct : « garmin » ou tout nom commençant par « intervals » (Intervals_icu, intervals-icu…), sans tenir compte de la casse.
direct = [n for n in servers if n.lower() == "garmin" or n.lower().startswith(("intervals", "strava"))]
sys.exit(0 if "leanproxy" in servers and not direct else 1)
' "$config"
}

main() {
    build_command
    log "Synchronisation $SOURCE_LABEL — exécuteur : $RUNNER, fenêtre : $LOOKBACK jour(s)${TRIGGER:+, déclencheurs : $TRIGGER}"
    log "Workspace : $ARC_WORKSPACE (moteur : $ARC_ENGINE_ROOT)"

    # Même refus pour les exécuteurs qui filtrent par nom de serveur/outil (copilot,
    # gemini, cursor) : à travers la passerelle, le filtre ne voit aucun outil de
    # données et la synchronisation « réussirait » à vide.
    local runner_mcp_config="$MCP_CONFIG"
    case "$RUNNER" in
        gemini) runner_mcp_config="$ARC_WORKSPACE/.gemini/settings.json" ;;
        cursor) runner_mcp_config="$ARC_WORKSPACE/.cursor/mcp.json" ;;
    esac
    if [[ "$RUNNER" =~ ^(opencode|copilot|gemini|cursor)$ ]] && mcp_gateway_only "$runner_mcp_config"; then
        local gateway_msg="$RUNNER + leanproxy non pris en charge pour la synchronisation — utilisez le mode direct (./install.sh sans --use-leanproxy) ou le runner claude."
        if [[ "$DRY_RUN" -eq 1 ]]; then
            warn "$gateway_msg"
        else
            err "$gateway_msg"
            notify "🚫 Sync $SOURCE_LABEL — $RUNNER + leanproxy non pris en charge" 4 "no_entry,warning" "$gateway_msg"
            exit 1
        fi
    fi

    local key_missing=0
    load_llm_env || key_missing=1

    if [[ "$DRY_RUN" -eq 1 ]]; then
        # Le prompt inline du skill, multi-ligne, n'est montré que par sa
        # taille ; les listes d'outils autorisés/interdits restent affichées en entier.
        local shown=() arg
        for arg in "${CMD[@]}"; do
            if [[ "$arg" == *$'\n'* ]]; then shown+=("<prompt : ${#arg} caractères>"); else shown+=("$arg"); fi
        done
        printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} cd $ARC_WORKSPACE && ${shown[*]}" | head -c 4000; echo
        if [[ -n "$API_KEY_ENV" ]]; then
            # Le NOM de la variable seulement — jamais sa valeur.
            if [[ "$key_missing" -eq 0 ]]; then
                printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} variable réservée au process du runner : $API_KEY_ENV (lue dans $LLM_ENV_FILE ou l'environnement)"
            else
                warn "$API_KEY_ENV introuvable dans $LLM_ENV_FILE ni dans l'environnement — la synchronisation échouerait."
            fi
        fi
        if [[ "$RUNNER" == "opencode" ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} OPENCODE_CONFIG=$OC_CONFIG_FILE, contenu :"
            opencode_config_json
        fi
        if [[ "$RUNNER" == "gemini" ]]; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} GEMINI_CLI_SYSTEM_SETTINGS_PATH=$GEMINI_CONFIG_FILE, contenu :"
            gemini_config_json || warn "Gemini : aucun serveur $SOURCE_LABEL utilisable — la synchronisation réelle s'arrêterait ici."
        fi
        if budget_enforced; then
            printf '%s\n' "${C_YELLOW}[dry-run]${C_RESET} budget : $(spent_today_eur)/$DAILY_BUDGET_EUR EUR (cumul : $SPEND_FILE)"
        fi
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

    if [[ "$key_missing" -eq 1 ]]; then
        err "$API_KEY_ENV introuvable ($LLM_ENV_FILE) — synchronisation abandonnée."
        notify "🔑 Sync $SOURCE_LABEL — clé API absente" 4 "key,warning" \
            "Mode API activé ([sync].api_key_env = $API_KEY_ENV) mais la clé est introuvable dans $LLM_ENV_FILE. Ajoutez la ligne $API_KEY_ENV=... (chmod 600)."
        exit 1
    fi

    # Plafond quotidien : seulement pour un runner qui rapporte son coût. Dépassé,
    # on ne lance rien (exit 0 : ce n'est pas une panne) et on prévient UNE fois
    # par jour, pour qu'un mode watch ne spamme pas.
    if budget_enforced && over_budget; then
        warn "Budget quotidien atteint ($(spent_today_eur)/$DAILY_BUDGET_EUR EUR) — synchronisation sautée."
        local budget_marker
        budget_marker="$LOG_DIR/.sync-budget-notified-$(date +%F)"
        if [[ ! -e "$budget_marker" ]]; then
            notify "💸 Sync $SOURCE_LABEL suspendue — budget atteint" 3 "moneybag,warning" \
                "Budget quotidien de la synchronisation atteint ($(spent_today_eur) € sur $DAILY_BUDGET_EUR €) : run sauté. Ajustez [sync].daily_budget_eur ou relancez demain."
            : > "$budget_marker"
        fi
        exit 0
    fi
    git_pull_before_run

    local output rc=0
    {
        echo "===== $(date '+%F %T') — runner=$RUNNER lookback=$LOOKBACK trigger=${TRIGGER:-planifié} ====="
    } >> "$LOG_FILE"
    cd "$ARC_WORKSPACE"
    local exec_cmd=("${CMD[@]}") raw_output provider_error="" run_marker="$LOG_DIR/.sync-run-start"
    if [[ "$RUNNER" == "opencode" ]]; then
        mkdir -p "$(dirname "$OC_CONFIG_FILE")"
        opencode_config_json > "$OC_CONFIG_FILE"
        exec_cmd=(env "OPENCODE_CONFIG=$OC_CONFIG_FILE" "${exec_cmd[@]}")
    fi
    if [[ "$RUNNER" == "gemini" ]]; then
        mkdir -p "$(dirname "$GEMINI_CONFIG_FILE")"
        gemini_config_json > "$GEMINI_CONFIG_FILE" \
            || die "Gemini : serveur MCP $MCP_SERVER_NAME absent de .gemini/settings.json — relancez ./install.sh (ou l'installation guidée)."
    fi
    # La clé n'est passée qu'à CE process (env), jamais exportée ici.
    if [[ "${#RUNNER_ENV[@]}" -gt 0 ]]; then
        exec_cmd=(env "${RUNNER_ENV[@]}" "${exec_cmd[@]}")
    fi
    : > "$run_marker"
    raw_output="$("${exec_cmd[@]}" 2>>"$LOG_FILE")" || rc=$?
    if [[ "$OUTPUT_KIND" == "text" ]]; then
        output="$raw_output"
        printf '%s\n' "$output" >> "$LOG_FILE"
    else
        # Sortie JSON : le texte de l'agent d'abord (c'est lui que lisent
        # extract_resume et detect_auth_failure), puis la sortie brute.
        output="$(printf '%s\n' "$raw_output" | runner_output text)"
        provider_error="$(printf '%s\n' "$raw_output" | runner_output error)"
        printf '%s\n' "$output" >> "$LOG_FILE"
        [[ -z "$provider_error" ]] || printf 'PROVIDER-ERREUR (%s) : %s\n' "$(provider_label)" "$provider_error" >> "$LOG_FILE"
        printf '%s\n' "$raw_output" >> "$LOG_FILE"
        record_spend "$(printf '%s\n' "$raw_output" | runner_output cost)"
    fi

    if [[ "$rc" -ne 0 ]]; then
        err "La synchronisation a échoué (code $rc) — voir $LOG_FILE"
        if detect_provider_failure "$provider_error"; then
            # Clé refusée ou crédits épuisés côté fournisseur LLM : jamais présenté
            # comme un problème Garmin, et sans lecture du journal pour un 401.
            local plabel
            plabel="$(provider_label)"
            if [[ "$PROVIDER_FAILURE" == "credits" ]]; then
                notify "💳 Sync $SOURCE_LABEL — crédits $plabel épuisés" 5 "moneybag,warning" \
                    "Synchronisation interrompue : le fournisseur LLM ($plabel) refuse la requête faute de crédits (402). Rechargez le compte. Ce n'est pas un problème $SOURCE_LABEL. Voir logs/sync-$(date +%F).log."
            else
                notify "🔑 Sync $SOURCE_LABEL — clé $plabel refusée" 5 "key,warning" \
                    "Synchronisation interrompue : la clé API du fournisseur LLM ($plabel, variable $API_KEY_ENV) est refusée (401). Vérifiez ~/.config/ai-running-coach/llm.env. Ce n'est pas un problème $SOURCE_LABEL. Voir logs/sync-$(date +%F).log."
            fi
        elif detect_auth_failure; then
            if [[ "$TOKEN_ALERT_SENT_THIS_RUN" -eq 1 ]]; then
                # L'alerte d'expiration envoyée juste avant la synchronisation couvre
                # déjà ce même problème (tokens expirés) — pas de doublon. Garmin
                # uniquement : cette variable ne passe à 1 que dans check_token_alert,
                # qui retourne tôt en mode intervals (#68).
                warn "Garmin — alerte d'expiration déjà envoyée ce run, pas de notification supplémentaire."
            elif [[ "$AUTH_FAILURE_KIND" == "raw" ]]; then
                # Texte HTTP réel du serveur MCP (garminconnect/garmin_mcp, ou
                # ICUAPIError d'intervals-icu-mcp) : le 401 est un fait constaté.
                notify "🔑 Authentification $SOURCE_LABEL refusée" 5 "key,warning" \
                    "Synchronisation interrompue (401) — renouvelez avec : $AUTH_CMD_HINT. Voir logs/sync-$(date +%F).log."
            else
                # Détecté via la formulation ERREUR de l'agent : la cause réelle peut ne
                # PAS être un 401 (ex. un problème réseau/DNS mal diagnostiqué par
                # l'agent) — on relaie sa ligne telle quelle plutôt que d'affirmer « 401 ».
                notify "🔑 Authentification $SOURCE_LABEL — action requise" 5 "key,warning" \
                    "Synchronisation interrompue — ${AUTH_FAILURE_LINE#ERREUR : } Voir logs/sync-$(date +%F).log."
            fi
        else
            notify "❌ Sync $SOURCE_LABEL échouée" 4 "warning" "Exécuteur $RUNNER, code $rc. Voir logs/sync-$(date +%F).log sur la machine coach."
        fi
        exit "$rc"
    fi

    local resume
    resume="$(printf '%s\n' "$output" | extract_resume)"
    if [[ -z "$resume" ]]; then
        warn "Aucun bloc \`\`\`resume trouvé — envoi des 5 dernières lignes de la sortie."
        resume="$(printf '%s\n' "$output" | tail -n 5)"
    fi
    resume="$(enforce_resume_cap "$resume")"
    ok "Résumé :"
    printf '%s\n' "$resume"

    local title="🏃 Sync $SOURCE_LABEL" priority=3 tags="running"
    if detect_auth_failure; then
        title="🔑 Authentification $SOURCE_LABEL refusée"; priority=5; tags="key,warning"
        # N'ajoute la commande que si l'agent (ERREUR du skill) ne l'a pas déjà écrite.
        if ! printf '%s' "$resume" | grep -qiF "$AUTH_CMD_HINT"; then
            resume="$resume — renouvelez avec : $AUTH_CMD_HINT"
        fi
    elif printf '%s' "$resume" | grep -qi '^ERREUR'; then
        title="⚠️ Sync $SOURCE_LABEL"; priority=4; tags="warning"
    elif printf '%s' "$resume" | grep -qi '^À jour'; then
        title="Sync $SOURCE_LABEL — à jour"; priority=2; tags="running"
    fi
    # Une ligne « Pourquoi : » (#56) signale un ajustement (garde-fou r5…) : la
    # notification mérite plus d'attention qu'une sync ordinaire, MÊME si elle
    # part par ailleurs sur un « À jour » (priorité 2 par défaut) — mais ne
    # descend jamais une priorité déjà plus grave (401, ERREUR, à 4 ou 5).
    # Motif accordé avec `enforce_resume_cap` (NBSP-safe sous `LC_ALL=C`).
    if printf '%s' "$resume" | grep -qE '^Pourquoi[^:]{0,4}:' && [[ "$priority" -lt 4 ]]; then
        priority=4
        tags="running,warning"
    fi
    # Un modèle faible qui casse le contrat `arc` chaque nuit est pire qu'un run
    # échoué : les fichiers écrits pendant CE run sont validés et l'écart figure
    # dans la notification (runner opencode).
    if [[ "$RUNNER" == "opencode" ]]; then
        local invalid="" f
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            python3 "$ARC_ENGINE_ROOT/scripts/arc_index.py" --validate "$f" >>"$LOG_FILE" 2>&1 \
                || invalid="$invalid ${f#"$ARC_WORKSPACE"/}"
        done < <(find "$ARC_WORKSPACE/activities" "$ARC_WORKSPACE/medical" "$ARC_WORKSPACE/nutrition" \
                      "$ARC_WORKSPACE/planning" "$ARC_WORKSPACE/rapports" "$ARC_WORKSPACE/gear" -name '*.md' -newer "$run_marker" 2>/dev/null)
        if [[ -n "$invalid" ]]; then
            warn "Fichiers hors contrat après le run :$invalid"
            resume="$resume
⚠ hors contrat arc :$invalid (validate)"
            [[ "$priority" -ge 4 ]] || priority=4
            tags="$tags,warning"
        fi
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
    telegram_summary "$title" "$priority" "$resume"
}

main "$@"
