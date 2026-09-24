# 🏃 ai-running-coach

> Votre coach IA de trail running, connecté à **Garmin Connect** — préparez votre objectif avec l'aide d'agents spécialisés.

`ai-running-coach` est un projet open-source qui fournit des **agents IA** et des **skills** pour aider les coureurs à préparer un objectif (course, trail, ultra) avec l'aide d'un assistant IA dans leur IDE préféré.

Le projet est **en français par défaut** (la langue des documents générés est configurable via `config/workspace.toml`). Il est connecté principalement à **Garmin Connect**, installé et configuré automatiquement par `./install.sh` ; **Intervals.icu** est supporté en destination secondaire, uniquement sur demande explicite — son serveur MCP n'est pas installé par `install.sh` (configuration manuelle, voir [la FAQ](docs/faq.md#comment-configurer-intervalsicu-optionnel)).

## ✨ Ce que le projet apporte

| Composant | Description |
|---|---|
| 🧠 **4 agents spécialisés** | `coach`, `course-strategist`, `medical`, `nutritionist` — installez seulement ceux que vous voulez |
| 🛠️ **12 skills** | analyse GPX, comparaison de parcours, planification Garmin, météo, analyse de séances, Intervals.icu, etc. |
| 📡 **Accès Garmin Connect** | via `garmin-mcp` (mode direct, liste blanche d'outils) — passerelle `leanproxy-mcp` optionnelle |
| 🚀 **Installation automatisée** | un script pour installer et configurer tout (uv, Garmin, IDE) |
| 📊 **Tableau de bord local** | courbe de forme (condition / fatigue / forme), bilan santé du matin, semaine, séances et splits, prédictions — à côté du texte du coach (`scripts/dashboard.sh`, lecture seule, 127.0.0.1) |
| 📱 **Le coach dans la poche** | synchronisation Garmin automatique + notification push, et dialogue avec le coach depuis le téléphone (Claude Code Remote Control) — sans renoncer à votre abonnement |
| 🎛️ **Coach configurable** | style de coaching, discipline (trail ou route), bilan santé matinal, profil d'athlète |
| 📚 **Documentation** | guide de démarrage rapide, configuration, dépannage |

## 📊 Tableau de bord

Tout ce que le coach stocke — verdict du jour, bilan du matin, courbe de forme,
semaine planifiée, séances et splits, rapports — dans un tableau de bord local,
en lecture seule :

```bash
scripts/dashboard.sh
```

![Tableau de bord — vue Aujourd'hui](docs/assets/dashboard/aujourdhui.webp)

Sur un serveur qui a déjà Traefik et une authentification unique, il se range aussi
en conteneur Docker, workspace en lecture seule :
[Derrière un reverse proxy](docs/dashboard/docker.md).

Voir [la documentation du tableau de bord](docs/dashboard/index.md).

## 🧑‍💻 IDE supportés

- **Claude Code** (`.claude/agents` + `.claude/skills`)
- **GitHub Copilot** (`.github/agents` + `.github/skills` + `.mcp.json`) — CLI, VS Code et agent cloud
- **OpenCode** (`.opencode/agents` + `.opencode/skills`)
- **Gemini CLI** (`.gemini/commands`)
- **Cursor** (`.cursor/mcp.json`)
- **Windsurf** (`.windsurf/mcp_config.json`)

## 📋 Prérequis

- **macOS** ou **Linux**
- **bash 3.2+** (celui livré avec macOS convient)
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
./install.sh --agents LISTE    # staff à installer, ex. coach,nutritionist
./install.sh --no-medical      # tous les agents sauf le médecin
./install.sh --no-auth         # saute l'authentification Garmin
./install.sh --use-leanproxy   # mode passerelle leanproxy-mcp (power user, optionnel)
./install.sh --workspace DIR   # vos données dans votre dépôt privé, moteur lié (voir docs/workspace.md)
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
2. **Lancez `/coach-setup`** — un entretien court qui règle votre staff d'agents, votre discipline, la façon dont le coach vous parle, et installe votre profil d'athlète. Relancer la commande est sans effet : elle ne pose que les questions sans réponse.
3. **Demandez à l'agent `coach`** de définir votre objectif, par exemple :
   - *« Je veux préparer un trail de 50 km avec 2500 m de D+ dans 6 mois »*
   - *« Aide-moi à planifier ma semaine d'entraînement »*
4. L'agent `coach` coordonne les agents que vous avez retenus et pousse vos séances directement dans le **calendrier Garmin Connect**

### 🎛️ Ce qui est configurable

| Réglage | Exemple |
|---|---|
| **Staff** | Retirez le médecin ou le nutritionniste : `./install.sh --no-medical` |
| **Façon de coacher** | `bienveillant`, `exigeant`, `factuel`, `pedagogue` — plus une fermeté et une longueur |
| **Discipline** | `trail` ou `road` — change l'unité de charge, le vocabulaire et le matériel |
| **Bilan santé matinal** | `full`, `minimal` ou `off` si vous ne voulez pas que l'entraînement dépende de la HRV |

Tout est décrit dans [la documentation de configuration](docs/configuration.md).

## 📁 Structure du projet

```
ai-running-coach/
├── agents/                  # Agents IA (coach, course-strategist, medical, nutritionist)
├── skills/                  # Skills (analyse GPX, planification, météo, etc.)
├── scripts/                 # Machine « coach » : sync automatique, notifications, Remote Control
├── config/
│   ├── workspace.toml       # Configuration (staff, sport, style, santé, langue)
│   ├── coaching-styles.md   # Catalogue des styles de coaching
│   ├── setup-questions.toml # Questions du premier démarrage
│   ├── sports/              # Profils de sport (trail, route)
│   └── gemini/commands/     # Commandes Gemini CLI (générées depuis agents/)
├── templates/               # Modèles installés dans votre workspace
├── tests/                   # Suite de tests (voir tests/README.md)
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
- [Configuration (staff, style, sport, santé)](docs/configuration.md)
- [Configuration Garmin](docs/garmin-setup.md)
- [Votre workspace privé (données versionnées, moteur lié)](docs/workspace.md)
- [Le coach dans la poche (mobile + sync automatique)](docs/mobile.md)
- [Tableau de bord](docs/dashboard/index.md) · [Les vues](docs/dashboard/views.md) · [Migrer vos fichiers](docs/dashboard/migration.md) · [Mode headless](docs/dashboard/headless.md) · [Docker](docs/dashboard/docker.md)
- [Les agents](docs/agents.md)
- [Les skills](docs/skills.md)
- [Base de connaissances (resources)](docs/resources.md)
- [Dépannage](docs/troubleshooting.md)
- [FAQ](docs/faq.md)

## 🤝 Contribution

Les contributions sont les bienvenues ! Consultez le fichier [CONTRIBUTING.md](CONTRIBUTING.md) pour les conventions.

## 📄 Licence

Ce projet est sous licence [MIT](LICENSE).

## ™️ Marques

Garmin®, Garmin Connect™, Body Battery™ et Firstbeat Analytics™ sont des marques de Garmin Ltd. ou de ses filiales. TrainingPeaks® ainsi que TSS®, NP® et IF® sont des marques de Peaksware LLC ; les sigles CTL, ATL et TSB sont revendiqués par la même société. Intervals.icu et Strava sont des marques de leurs éditeurs respectifs. Ces noms sont cités uniquement pour désigner les services avec lesquels le projet interagit ou pour expliquer une équivalence.

Ce projet est **indépendant** : il n'est ni affilié à ces sociétés, ni approuvé, parrainé ou soutenu par elles. Ses métriques de charge (TRIMP de Banister, condition / fatigue / forme, ACWR) reposent sur des modèles scientifiques publiés et portent volontairement des noms génériques — voir [Marques et métriques](docs/marques.md).

## ⚠️ Avertissement

Ce projet fournit des outils d'aide à la préparation sportive. Il ne remplace pas un avis médical professionnel. Consultez un médecin avant de commencer un programme d'entraînement.
