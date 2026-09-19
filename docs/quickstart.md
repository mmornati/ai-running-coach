# 🚀 Démarrage rapide

Ce guide vous permet d'installer et de configurer `ai-running-coach` en quelques minutes.

## Prérequis

- **macOS** ou **Linux**
- **bash 4+**
- **curl** et **git**
- Un compte **Garmin Connect** (avec un appareil Garmin)

!!! tip "Homebrew"
    **Homebrew** est recommandé sur macOS. Il est requis uniquement pour le mode passerelle optionnel (`leanproxy-mcp`).

## Installation

```bash
git clone https://github.com/mmornati/ai-running-coach.git
cd ai-running-coach
./install.sh
```

Le script effectue les étapes suivantes :

1. **uv** — gestionnaire Python (installé si absent)
2. **garmin-mcp** — serveur MCP d'accès à Garmin Connect
3. **garmin-mcp-auth** — authentification Garmin (tokens valides ~6 mois)
4. **Configuration IDE** — serveur MCP `garmin` (mode direct, liste blanche d'outils) pour Claude Code, OpenCode, Gemini CLI, Cursor, Windsurf
5. **Dossiers de travail** — `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `resources/`

## Authentification Garmin

Lors de la première installation, le script lance l'authentification Garmin Connect :

1. Saisissez votre **email** et **mot de passe** Garmin Connect
2. Validez le **code MFA** si votre compte en est équipé
3. Les tokens sont stockés dans `~/.garminconnect/` (valides ~6 mois)

!!! warning "Sécurité"
    Vos identifiants ne sont jamais stockés dans le projet. Les tokens sont conservés dans votre répertoire personnel (`~/.garminconnect/`), hors du dépôt.

## Options du script

| Option | Description |
|---|---|
| `--ide claude` | Installe pour un IDE précis (`claude`, `opencode`, `gemini`, `cursor`, `windsurf`) |
| `--no-auth` | Saute l'authentification Garmin |
| `--use-leanproxy` | Mode passerelle leanproxy-mcp (power user, optionnel) |
| `--dry-run` | Affiche les actions sans rien exécuter |
| `--help` | Affiche l'aide |

## Premiers pas

1. **Lancez votre IDE** dans le dossier du projet
2. **Demandez à l'agent `coach`** de définir votre objectif, par exemple :
   - *« Je veux préparer un trail de 50 km avec 2500 m de D+ dans 6 mois »*
   - *« Aide-moi à planifier ma semaine d'entraînement »*
3. L'agent `coach` coordonne les autres agents (`course-strategist`, `medical`, `nutritionist`) et pousse vos séances directement dans le **calendrier Garmin Connect**

## Vérification

Pour vérifier que tout est bien installé :

```bash
uv --version
garmin-mcp --version
ls ~/.garminconnect/
```

En mode passerelle (`--use-leanproxy`), vérifiez aussi `leanproxy-mcp --version`.

## Prochaines étapes

- [Configuration Garmin](garmin-setup.md) — détails sur l'accès Garmin
- [Les agents](agents.md) — comprendre le rôle de chaque agent
- [Les skills](skills.md) — découvrir les skills disponibles
- [Dépannage](troubleshooting.md) — résoudre les problèmes courants
