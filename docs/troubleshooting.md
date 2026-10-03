# Dépannage

Cette page regroupe les problèmes courants et leurs solutions.

## Par où commencer

Avant de chercher plus loin, lancez le diagnostic d'installation en une
commande — il vérifie les tokens Garmin, le MCP, la configuration, le profil
athlète, l'index et le daily-sync sans rien modifier :

```bash
python3 scripts/coach_doctor.py
```

Voir le skill [`coach-doctor`](skills/coach-doctor.md) pour le détail de
chaque vérification et la sortie `--json`.

## Installation

### `uv` introuvable après installation

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
```

Rechargez votre shell (`source ~/.zshrc` ou `source ~/.bashrc`) puis relancez le script.

### `garmin-mcp` introuvable

```bash
uv tool install --python 3.12 git+https://github.com/Taxuspt/garmin_mcp@cfc5d799ab0f165e837f1188a1d093c65838aaf7
```

### `leanproxy-mcp` introuvable (mode passerelle uniquement)

```bash
brew tap mmornati/leanproxy-mcp
brew install leanproxy-mcp
```

!!! note
    `leanproxy-mcp` n'est requis qu'en mode passerelle (`--use-leanproxy`). En mode direct (défaut), il n'est pas installé.

## Authentification Garmin

### Tokens expirés

Les tokens Garmin sont valides environ **6 mois**. Pour les renouveler :

```bash
uv run garmin-mcp-auth
```

`coach doctor` (`garmin_token`) estime cette échéance à partir de la date de
dernière modification de `garmin_tokens.json`, faute d'échéance explicite dans
ce fichier (voir le skill [`coach-doctor`](skills/coach-doctor.md)) — cette
estimation peut dériver, car le fichier est réécrit à chaque rafraîchissement
automatique du token, ce qui repousse sa date de modification sans que la
session ait réellement été renouvelée pour 6 mois de plus.

### Vérifier les tokens

```bash
uv run garmin-mcp-auth --verify
```

### Erreur de connexion à Garmin Connect

1. Vérifiez que `garmin-mcp` fonctionne : `garmin-mcp stdio`
2. Vérifiez que les tokens existent : `ls ~/.garminconnect/`
3. Relancez l'authentification : `uv run garmin-mcp-auth`

### Alerte push avant expiration des tokens (#32)

Avant chaque exécution, `scripts/daily-sync.sh` interroge `coach_doctor.py
--check garmin_token --json` (lecture seule, borné dans le temps via
`timeout`/`gtimeout` quand l'un des deux est disponible — sur une machine sans
coreutils, l'appel n'est pas borné, mais ce check ne fait aucun accès réseau ;
dans tous les cas, une panne du diagnostic se journalise et n'empêche jamais la
synchronisation) et envoie, au plus une fois par jour, une notification ntfy
avec la commande de renouvellement quand l'échéance estimée approche.

- **Seuils** : `[notifications].token_alert_days` dans `config/workspace.toml`
  (défaut `[14, 3]`, en jours restants, entiers positifs uniquement — toute
  valeur non entière dans la config est ignorée avec un avertissement, jamais
  évaluée). Le seuil le plus proche de l'échéance (le plus petit, ainsi que
  « expiré ») alerte chaque jour jusqu'au renouvellement ; un seuil plus
  lointain (J-14 par défaut) n'alerte qu'une seule fois tant que l'échéance n'a
  pas atteint le seuil suivant — pas de rappel quotidien dès J-14. Une liste
  vide (`[]`, ou qui ne contient plus aucun entier valide) désactive l'alerte
  d'expiration, sans effet sur la notification 401 explicite ci-dessous.
  « Expiré depuis N jour(s) » arrondit vers le bas comme `coach doctor`
  (un token expiré depuis 30h30 affiche 1 jour, pas 2).
- **Désactivation** : `[notifications].token_alerts = false` dans
  `config/workspace.user.toml`. Sans effet si `provider = "none"`.
- **État** : `<workspace>/logs/.token-alert-state` (gitignoré comme tout
  `logs/`) — supprimez-le pour forcer une réévaluation, par exemple après un
  renouvellement manuel des tokens en dehors du daily-sync.
- **401 réel** : si la synchronisation rencontre effectivement un refus
  d'authentification **Garmin** — jamais un 401 sans rapport, par exemple un
  échec d'authentification du runner Codex lui-même, ni une ligne `ERREUR`
  qui mentionne « tokens Garmin » en passant pour une tout autre raison (panne
  réseau, DNS…) —, la notification remplace le message d'échec générique par
  un message explicite avec la commande de renouvellement. Deux formes
  reconnues selon l'exécuteur : le texte réel de `garminconnect`/`garmin_mcp`
  (`GarminConnectAuthenticationError`, visible seulement si l'exécuteur
  restitue la sortie brute d'un outil MCP, ex. `codex exec` en mode verbeux —
  un « 401 » est alors une certitude, revendiqué tel quel) et la formulation
  `ERREUR : …` que `skills/garmin-daily-sync/SKILL.md` impose à l'agent
  d'écrire lui-même, reconnue SEULEMENT quand elle nomme explicitement une
  expiration/un refus de token ou renvoie vers `garmin-mcp-auth` — seule forme
  qui traverse le runner par défaut, `claude -p --output-format text` (ne
  restitue que le message final de l'agent) ; dans ce cas, la cause réelle
  n'étant pas confirmée comme un 401, la notification relaie la ligne de
  l'agent telle quelle plutôt que d'affirmer « 401 ». Si une alerte
  d'expiration est déjà partie plus tôt dans le même run, cette notification
  n'est pas doublée.

### Synchronisation sur une API (OpenRouter, Anthropic)

Quand `[sync].api_key_env` est défini, ces échecs ont **leur propre notification** — ils
ne sont jamais présentés comme un problème Garmin :

| Notification | Cause | Correctif |
|---|---|---|
| `🔑 Sync Garmin — clé openrouter refusée` (ou `Anthropic`) | Le fournisseur renvoie 401 : clé invalide, révoquée ou mal copiée. | Éditez `~/.config/ai-running-coach/llm.env` (ligne `OPENROUTER_API_KEY=…`, mode 600), puis `python3 scripts/coach_doctor.py --check llm_config`. |
| `💳 Sync Garmin — crédits … épuisés` | Le fournisseur renvoie 402 : plus de crédit. | Rechargez le compte du fournisseur. |
| `🔑 Sync Garmin — clé API absente` | `[sync].api_key_env` est défini mais la variable est introuvable dans `llm.env` et l'environnement. | Ajoutez la ligne dans `llm.env` (`./install.sh --llm …` crée le fichier). |
| `💸 Sync Garmin suspendue — budget atteint` | Le cumul du jour (`logs/.sync-spend-AAAA-MM-JJ`) atteint `[sync].daily_budget_eur`. Le run est sauté, sans erreur. | Relancez demain, ou relevez `./install.sh --sync-budget EUR`. |
| `⚠ hors contrat arc : …` (dans le résumé) | Un fichier écrit par le modèle pendant le run ne respecte pas le bloc `arc`. | Voir `logs/sync-AAAA-MM-JJ.log` ; changez de modèle (`[sync].model`) si cela se répète. |

`opencode introuvable` : `curl -fsSL https://opencode.ai/v2/install | bash`. Un refus
d'authentification **Garmin** garde sa notification habituelle
(`🔑 Authentification Garmin refusée`, voir plus haut).

## Configuration IDE

### L'agent `coach` n'apparaît pas dans mon IDE

- **Claude Code** : vérifiez que `.claude/agents/` existe et contient `coach.md`
- **GitHub Copilot** : vérifiez que `.github/agents/` existe et contient `coach.md`, puis `/agent` dans Copilot CLI
- **OpenCode** : vérifiez que `.opencode/agents/` existe et contient `coach.md`
- **Gemini CLI** : vérifiez que `.gemini/commands/` contient les fichiers `.toml`

Relancez `./install.sh --ide <votre-ide>` si nécessaire.

### Le serveur MCP `garmin` (ou `leanproxy`) n'apparaît pas

Vérifiez la configuration MCP de votre IDE :

```bash
# Claude Code / GitHub Copilot
cat .mcp.json

# OpenCode
cat ~/.config/opencode/opencode.json

# Cursor
cat .cursor/mcp.json

# Windsurf
cat .windsurf/mcp_config.json
```

Chaque configuration doit contenir une référence au serveur MCP `garmin` (mode direct) ou `leanproxy` (mode passerelle).

### Copilot CLI ne charge pas le serveur MCP `garmin`

Copilot CLI ne charge les serveurs MCP d'un projet qu'après confirmation de la
**confiance du dossier**. Relancez `copilot` depuis la racine du projet, acceptez
la demande de confiance, puis vérifiez avec `/mcp`.

## Données

### Les dossiers de travail sont vides

Les dossiers `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/`, `resources/` sont créés par le script d'installation. Ils sont **exclus du dépôt** (voir `.gitignore`).

### Les données Garmin ne se synchronisent pas

1. Vérifiez que les tokens sont valides : `uv run garmin-mcp-auth --verify`
2. En mode passerelle, vérifiez que le serveur garmin est configuré dans leanproxy : `cat ~/.config/leanproxy_servers.yaml`
3. Vérifiez que `garmin-mcp` fonctionne : `garmin-mcp stdio`

## Scripts Python

### `download_fit.py` échoue avec une erreur de dépendances

Le script nécessite `garminconnect` et `fitparse`. Ces dépendances sont disponibles dans l'environnement `garmin-mcp`. Le script tente de se **relancer automatiquement** dans cet environnement. Si cela échoue :

```bash
uv tool run --from garminconnect --from fitparse python3 skills/fit-download/scripts/download_fit.py
```

**Source Intervals.icu** (`[data].source = "intervals"`) : seul `fitparse` est
requis, et seulement avec `--json`. Le script se relance dans l'environnement
`intervals-icu-mcp`. Sur une installation antérieure à cette fonctionnalité, cet
environnement n'a pas encore `fitparse` : relancez `./install.sh --source
intervals`, qui l'ajoute sans réinstaller le serveur.

### `download_fit.py` affiche `INDISPONIBLE` (Intervals.icu)

L'activité a été importée dans Intervals.icu **depuis Strava** : l'API Strava
interdit sa redistribution, il n'existe aucun FIT à télécharger. Ce n'est pas
une panne : la séance reste valide, sans les KPI fins (zones, GAP, VAM…).
Connectez la montre, ou l'app qui l'exporte, directement à Intervals.icu pour
les séances suivantes. `HTTP 401/403` signale en revanche une clé API refusée :
régénérez-la sur https://intervals.icu/settings (section *Developer*).

### Les autres scripts échouent

Les scripts `analyze_gpx.py`, `compare_course.py` et `analyze_session_parts.py` utilisent **uniquement la stdlib Python** — aucune dépendance externe n'est nécessaire.

## Autres

### Le script d'installation ne trouve pas Homebrew

En mode passerelle, le script affiche des instructions d'installation manuelle pour `leanproxy-mcp`. Installez-le manuellement puis relancez le script.

### Problème non résolu ?

Ouvrez une [issue](https://github.com/mmornati/ai-running-coach/issues) avec :

- Le système d'exploitation et sa version
- La version de votre IDE
- La sortie complète de `./install.sh`
- Les messages d'erreur exacts
