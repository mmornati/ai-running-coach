# 🏃 ai-running-coach

> Votre coach IA de trail running, connecté à **Garmin Connect** — préparez votre objectif avec l'aide d'agents spécialisés.

`ai-running-coach` est un projet open-source qui fournit des **agents IA** et des **skills** pour aider les coureurs à préparer un objectif (course, trail, ultra) avec l'aide d'un assistant IA dans leur IDE préféré.

Le projet est **100 % en français** et ne supporte que **Garmin** dans cette version.

## ✨ Ce que le projet apporte

| Composant | Description |
|---|---|
| 🧠 **4 agents spécialisés** | `coach`, `course-strategist`, `medical`, `nutritionist` |
| 🛠️ **8 skills** | analyse GPX, comparaison de parcours, planification Garmin, météo, analyse de séances, etc. |
| 📡 **Accès Garmin Connect** | via `garmin-mcp` + `leanproxy-mcp` (données, calendrier, planification d'entraînements) |
| 🚀 **Installation automatisée** | un script pour installer et configurer tout (uv, Garmin, IDE) |
| 📚 **Documentation** | guide de démarrage rapide, configuration, dépannage |

## 🧑‍💻 IDE supportés

- **Claude Code** (`.claude/agents` + `.claude/skills`)
- **OpenCode** (`.opencode/agents` + `.opencode/skills`)
- **Gemini CLI** (`.gemini/commands`)
- **Cursor** (`.cursor/mcp.json`)
- **Windsurf** (`.windsurf/mcp_config.json`)

## 📋 Prérequis

- **macOS** ou **Linux**
- **bash 4+**
- **curl** et **git**
- Un compte **Garmin Connect** (avec un appareil Garmin)

> 💡 **Homebrew** est recommandé sur macOS pour installer `leanproxy-mcp`.

## 🚀 Installation rapide

```bash
git clone https://github.com/mmornati/ai-running-coach.git
cd ai-running-coach
./install.sh
```

Le script installe et configure automatiquement :

1. **uv** (gestionnaire Python)
2. **garmin-mcp** + **garmin-mcp-auth** (accès Garmin Connect)
3. **leanproxy-mcp** (passerelle MCP)
4. La configuration de votre **IDE** (Claude Code, OpenCode, Gemini CLI, Cursor, Windsurf)
5. Les dossiers de travail (`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `resources/`)

### Options du script

```bash
./install.sh --ide claude    # installe pour un IDE précis (claude|opencode|gemini|cursor|windsurf)
./install.sh --no-auth       # saute l'authentification Garmin
./install.sh --skip-leanproxy # saute l'installation de leanproxy-mcp
./install.sh --dry-run       # affiche les actions sans rien exécuter
./install.sh --help
```

### 🔐 Authentification Garmin

Lors de la première installation, le script lance l'authentification Garmin Connect :

1. Saisissez votre **email** et **mot de passe** Garmin Connect
2. Validez le **code MFA** si votre compte en est équipé
3. Les tokens sont stockés dans `~/.garminconnect/` (valides ~6 mois)

> ⚠️ **Sécurité** : vos identifiants ne sont jamais stockés dans le projet. Les tokens sont conservés dans votre répertoire personnel (`~/.garminconnect/`), hors du dépôt.

## 🏁 Premiers pas

1. **Lancez votre IDE** dans le dossier du projet
2. **Demandez à l'agent `coach`** de définir votre objectif, par exemple :
   - *« Je veux préparer un trail de 50 km avec 2500 m de D+ dans 6 mois »*
   - *« Aide-moi à planifier ma semaine d'entraînement »*
3. L'agent `coach` coordonne les autres agents (`course-strategist`, `medical`, `nutritionist`) et pousse vos séances directement dans le **calendrier Garmin Connect**

## 📁 Structure du projet

```
ai-running-coach/
├── agents/                  # Agents IA (coach, course-strategist, medical, nutritionist)
├── skills/                  # Skills (analyse GPX, planification, météo, etc.)
├── config/
│   └── gemini/commands/     # Templates de commandes Gemini CLI
├── install.sh               # Script d'installation
├── AGENTS.md                # Conventions de travail pour les agents
└── docs/                    # Documentation (GitHub Pages)
```

## 📚 Documentation

La documentation complète est disponible sur [GitHub Pages](https://mmornati.github.io/ai-running-coach/) :

- [Guide de démarrage rapide](docs/quickstart.md)
- [Configuration Garmin](docs/garmin-setup.md)
- [Les agents](docs/agents.md)
- [Les skills](docs/skills.md)
- [Base de connaissances (resources)](docs/resources.md)
- [Dépannage](docs/troubleshooting.md)
- [FAQ](docs/faq.md)

## 🤝 Contribution

Les contributions sont les bienvenues ! Consultez le fichier [CONTRIBUTING.md](CONTRIBUTING.md) pour les conventions.

## 📄 Licence

Ce projet est sous licence [MIT](LICENSE).

## ⚠️ Avertissement

Ce projet fournit des outils d'aide à la préparation sportive. Il ne remplace pas un avis médical professionnel. Consultez un médecin avant de commencer un programme d'entraînement.
