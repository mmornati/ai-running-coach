# 🏃 ai-running-coach

> Votre coach IA de trail running, connecté à **Garmin Connect** — préparez votre objectif avec l'aide d'agents spécialisés.

`ai-running-coach` est un projet open-source qui fournit des **agents IA** et des **skills** pour aider les coureurs à préparer un objectif (course, trail, ultra) avec l'aide d'un assistant IA dans leur IDE préféré.

Le projet est **en français par défaut** (la langue des documents générés est configurable via `config/workspace.toml`) et ne supporte que **Garmin** dans cette version.

## ✨ Ce que le projet apporte

| Composant | Description |
|---|---|
| 🧠 **4 agents spécialisés** | `coach`, `course-strategist`, `medical`, `nutritionist` |
| 🛠️ **9 skills** | analyse GPX, comparaison de parcours, planification Garmin, météo, analyse de séances, etc. |
| 📡 **Accès Garmin Connect** | via `garmin-mcp` (mode direct, liste blanche d'outils) — passerelle `leanproxy-mcp` optionnelle |
| 🚀 **Installation automatisée** | un script pour installer et configurer tout (uv, Garmin, IDE) |
| 📱 **Le coach dans la poche** | synchronisation Garmin automatique + notification push, et dialogue avec le coach depuis le téléphone (Claude Code Remote Control) — sans renoncer à votre abonnement |
| 📚 **Documentation** | guide de démarrage rapide, configuration, dépannage |

## 🧑‍💻 IDE supportés

- **Claude Code** (`.claude/agents` + `.claude/skills`)
- **GitHub Copilot** (`.github/agents` + `.github/skills` + `.mcp.json`) — CLI, VS Code et agent cloud
- **OpenCode** (`.opencode/agents` + `.opencode/skills`)
- **Gemini CLI** (`.gemini/commands`)
- **Cursor** (`.cursor/mcp.json`)
- **Windsurf** (`.windsurf/mcp_config.json`)

## 📋 Prérequis

- **macOS** ou **Linux**
- **bash 4+**
- **curl** et **git**
- Un compte **Garmin Connect** (avec un appareil Garmin)

> 💡 **Homebrew** est recommandé sur macOS. Requis uniquement pour le mode passerelle optionnel (`--use-leanproxy`).

## 🚀 Installation rapide

```bash
git clone https://github.com/mmornati/ai-running-coach.git
cd ai-running-coach
./install.sh
```

Le script installe et configure automatiquement :

1. **uv** (gestionnaire Python)
2. **garmin-mcp** + **garmin-mcp-auth** (accès Garmin Connect)
3. La configuration de votre **IDE** (Claude Code, GitHub Copilot, OpenCode, Gemini CLI, Cursor, Windsurf) — serveur MCP `garmin` en mode direct avec liste blanche d'outils
4. Les dossiers de travail (`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `resources/`)

### Options du script

```bash
./install.sh --ide claude      # installe pour un IDE précis (claude|copilot|opencode|gemini|cursor|windsurf)
./install.sh --no-auth         # saute l'authentification Garmin
./install.sh --use-leanproxy   # mode passerelle leanproxy-mcp (power user, optionnel)
./install.sh --daily-sync      # machine « coach » : sync Garmin automatique (cron/launchd) + notification
./install.sh --remote-control  # machine « coach » : le coach accessible depuis le téléphone
./install.sh --dry-run         # affiche les actions sans rien exécuter
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
├── scripts/                 # Machine « coach » : sync automatique, notifications, Remote Control
├── config/
│   └── gemini/commands/     # Templates de commandes Gemini CLI
├── .github/
│   ├── copilot-instructions.md          # Instructions GitHub Copilot
│   └── workflows/copilot-setup-steps.yml # Environnement de l'agent cloud Copilot
├── install.sh               # Script d'installation
├── AGENTS.md                # Conventions de travail pour les agents
└── docs/                    # Documentation (GitHub Pages)
```

## 📚 Documentation

La documentation complète est disponible sur [GitHub Pages](https://mmornati.github.io/ai-running-coach/) :

- [Guide de démarrage rapide](docs/quickstart.md)
- [Configuration Garmin](docs/garmin-setup.md)
- [Le coach dans la poche (mobile + sync automatique)](docs/mobile.md)
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
