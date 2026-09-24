# 🔧 Dépannage

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
uv tool install --python 3.12 git+https://github.com/Taxuspt/garmin_mcp
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

Les dossiers `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `resources/` sont créés par le script d'installation. Ils sont **exclus du dépôt** (voir `.gitignore`).

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
