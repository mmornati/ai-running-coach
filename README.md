# 🏃 ai-running-coach

> Votre coach IA de trail running, connecté à **Garmin Connect** — préparez votre objectif avec l'aide d'agents spécialisés.

`ai-running-coach` est un projet open-source qui fournit des **agents IA** et des **skills** pour aider les coureurs à préparer un objectif (course, trail, ultra) avec l'aide d'un assistant IA dans leur IDE préféré.

Le projet est **en français par défaut** (la langue des documents générés est configurable via `config/workspace.toml`). Il est connecté par défaut à **Garmin Connect**, installé et configuré automatiquement par `./install.sh`. **Intervals.icu** peut aussi être la source primaire — pour les athlètes sans montre Garmin (COROS, Suunto, Polar, Apple) — avec `./install.sh --source intervals` (voir [Configuration Intervals.icu](docs/intervals-setup.md)) ; **Strava** (toutes marques de montres, flux par seconde pour les KPI, sans données de santé ni push de séances) avec `./install.sh --source strava` (voir [Configuration Strava](docs/strava-setup.md)) ; sans cette option, Intervals.icu reste disponible en destination secondaire, uniquement sur demande explicite (configuration manuelle, voir [la FAQ](docs/faq.md#comment-configurer-intervalsicu-sans-passer-par-installsh)). Pour COROS, voir [Montres COROS](docs/coros.md) (Intervals.icu recommandé ; le MCP officiel est audité mais non intégré).

🎬 **[La bande-annonce](https://mmornati.github.io/ai-running-coach/video/)** et **[Le Sentier](https://mmornati.github.io/ai-running-coach/videos/)**, une série de courtes vidéos narrées en français et en anglais, une par fonctionnalité — chaque image est dessinée en JavaScript ([source](docs/video/), rendu MP4 : `uv run --with playwright scripts/render_video.py --episode all`).

## ✨ Ce que le projet apporte

| Composant | Description |
|---|---|
| 🧠 **5 agents spécialisés** | `coach`, `course-strategist`, `medical`, `nutritionist`, `sports-director` — installez seulement ceux que vous voulez |
| 🌙 **Pénalité de nuit en ultra** | le plan de course calcule, sans réseau, le crépuscule du lieu et pénalise la vitesse des sections courues de nuit (selon la pente), avec les heures de frontale par scénario |
| 🗺️ **Roadbook imprimable** | une feuille A4 par scénario depuis le tableau de bord (vue Roadbook, lien depuis Trail Shape) : profil, sections, heures de passage, barrières et marges, ravitos avec ce qu'on y prend, matériel obligatoire — impression ou PDF du navigateur, sans dépendance |
| ⛰️ **Technicité du terrain en ultra** | coefficient par section, déclaré ou dérivé d'OpenStreetMap (`sac_scale`, surface, visibilité ; option `--technicity osm`, réseau opt-in), pondéré par la pente, appliqué en plus du modèle pente → allure |
| 🎯 **Recalibrage au débrief de course** | `arc_race_debrief.py --calibrate` attribue l'écart plan/réalisé à chaque facteur (nuit, technicité, chaleur, altitude) par contraste stratifié, refuse quand les groupes sont trop petits ou confondus, et propose des coefficients personnels cumulés d'une course à l'autre — écrits seulement après votre accord |
| ⛰️ **Altitude en ultra** | pénalité de temps au-dessus de 1 500 m (approximation du projet, tirée d'une étude publiée), réduite par l'acclimatation déclarée et par l'exposition mesurée à l'entraînement (carte « Exposition à l'altitude » de la vue Santé) |
| 🌡️ **Cibles ajustées à la chaleur** | par grosse chaleur, l'allure cible des séances (endurance, sortie longue, qualité) est ralentie de façon déterministe — FC inchangée, créneau frais proposé, jamais d'intensité maintenue en 🔴 (mêmes coefficients que le plan de course) |
| 🛠️ **20 skills** | commandes courtes `/today` `/why` `/week` `/race` `/log` `/inspection`, analyse GPX (altitude corrigée par MNT en option), comparaison de parcours, planification Garmin, météo, analyse de séances, Intervals.icu, diagnostic d'installation, inspection photo des chaussures, etc. |
| 📡 **Accès Garmin Connect** | via `garmin-mcp` (mode direct, liste blanche d'outils) — passerelle `leanproxy-mcp` optionnelle |
| 🚀 **Installation automatisée** | un script pour installer et configurer tout (uv, Garmin, IDE) |
| 👟 **Suivi du matériel** | kilométrage par paire depuis Garmin, prévision de retraite, équipement et kits, inspection photo (`/inspection`), contrôle du matériel de course |
| 📊 **Tableau de bord local** | courbe de forme (condition / fatigue / forme), bilan santé du matin, semaine, séances et splits, prédictions — à côté du texte du coach (`scripts/dashboard.sh`, lecture seule, 127.0.0.1) |
| 🗓️ **Gabarits de périodisation** | base / développement / spécifique / affûtage / récupération par format (trail court, marathon trail, ultra 80–100 km, 100 miles, semi et marathon route), en données vérifiées par un script contre les garde-fous — point de départ du bloc, jamais un plan imposé ; `plan-skeleton` en tire un squelette semaine par semaine vérifié par les garde-fous (proposition, écriture sur accord) — voir [Gabarits de périodisation](docs/plans.md) |
| 🏋️ **Renforcement et mobilité** | bibliothèque d'exercices (consignes, progressions, matériel) et programmes par phase du bloc ou par usage (descente, cheville, hanches, pied), correspondance Garmin vérifiée dans le catalogue officiel, placement par rapport aux séances de qualité — approximations du projet, jamais un diagnostic ; **prévention ciblée** d'une douleur déclarée (gêne légère → routine douce, sinon consultation, jamais un diagnostic ; `medical` décide s'il est activé) — voir [Renforcement](docs/strength.md) |
| 🎯 **Vitesse critique** | courbe allure-durée en GAP, vitesse critique et réserve anaérobie D′ estimées sur vos meilleurs efforts (refus explicite si les données manquent), cibles d'intervalles en % de la vitesse critique — voir [Vitesse critique](docs/vitesse-critique.md) |
| 🔁 **Effet des décisions** | ce qui s'est passé après chaque décision du coach (HRV, douleur, charge, RPE… avant / après), même quand l'athlète ne l'a pas suivie — synthèse par déclencheur dans la vue « Décisions » ; corrélation, pas causalité, jamais utilisé pour assouplir un garde-fou |
| 📱 **Le coach dans la poche** | synchronisation Garmin automatique + notification push, et dialogue avec le coach depuis le téléphone (Claude Code Remote Control) — sans renoncer à votre abonnement |
| ✈️ **Bot Telegram** | retours en un geste sous le résumé du daily-sync (séance faite, RPE, douleur), écrits sans modèle ni clé d'API dans votre workspace ; conversation libre en option |
| 🌙 **Cycle menstruel (opt-in)** | contexte facultatif du bilan matinal (phase du cycle), désactivé par défaut : jamais une règle ni un diagnostic, veille RED-S — voir [Cycle menstruel](docs/cycle-menstruel.md) |
| 🍽️ **Apports vers Garmin (opt-in)** | le coach propose de pousser ce que vous déclarez (`/log`, rapports) vers le journal alimentaire et l'hydratation de Garmin Connect, désactivé par défaut, jamais sans votre « oui » — voir [Apports vers Garmin](docs/nutrition-garmin.md) |
| 🎛️ **Coach configurable** | style de coaching, discipline (trail ou route), bilan santé matinal, profil d'athlète |
| 📚 **Documentation** | guide de démarrage rapide, configuration, dépannage |

## 📊 Tableau de bord

Tout ce que le coach stocke — verdict du jour, bilan du matin, courbe de forme,
semaine planifiée, séances et splits, matériel (kilométrage des paires, inspections), rapports — dans un tableau de bord local,
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

### Sur Mac — application graphique

Téléchargez le fichier `.dmg` depuis la page des versions, glissez **AI Running Coach** dans Applications, puis laissez l'assistant vous guider jusqu'au profil, aux chaussures, à l'objectif et au choix du chat. Le chat intégré fonctionne avec OpenRouter ; le mode « assistant habituel » installe automatiquement Claude Code, Copilot, OpenCode, Gemini CLI ou Cursor Agent et le lance ensuite au bon endroit. Dans les deux cas, le même assistant synchronise ensuite Garmin ou Intervals.icu automatiquement en arrière-plan, sans devoir rester ouvert. La même application sert ensuite à parler au coach, lancer le tableau de bord, compléter vos informations, retrouver vos données, vérifier l'installation et reconnecter le compte sportif.

Voir le guide [Application macOS](docs/macos.md).

### Installation en ligne de commande

```bash
git clone https://github.com/mmornati/ai-running-coach.git
cd ai-running-coach
./install.sh
```

Le script installe et configure automatiquement :

1. **uv** (gestionnaire Python)
2. **garmin-mcp** + **garmin-mcp-auth** (accès Garmin Connect)
3. La configuration de votre **IDE** (Claude Code, GitHub Copilot, OpenCode, Gemini CLI, Cursor, Windsurf) — serveur MCP `garmin` en mode direct avec liste blanche d'outils
4. Les dossiers de travail (`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/`, `resources/`)

### Options du script

```bash
./install.sh --preset laptop        # préréglage : composent les options ci-dessous (voir docs/quickstart.md#prereglages)
./install.sh --preset coach-server  #   coach-server = --ide claude --daily-sync --remote-control
./install.sh --preset docker        #   docker       = --ide claude --daily-sync (prépare l'hôte, pas le conteneur)
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

### ⚡ Commandes courtes du quotidien

Pour un usage rapide depuis le téléphone, six commandes courtes (cinq réponses rapides, et `/inspection` pour une
inspection guidée), format prévisible — natives sur **Claude Code** et **Gemini CLI** (commande dédiée),
chargées comme n'importe quel skill sur **OpenCode** et **GitHub Copilot**,
non disponibles sur **Cursor**/**Windsurf** (pas de skills/commandes sur ces
deux IDE, voir [IDE supportés](docs/ides.md)) :

| Commande | Répond |
|---|---|
| `/today` | La séance du jour, le bilan matinal (au niveau configuré), le créneau météo si la séance est en extérieur |
| `/why` | Pourquoi la dernière décision du coach (ou une décision nommée) a été prise — jamais une raison inventée ; peut citer le bilan personnel « ce qui s'est passé ensuite » (corrélation, pas causalité) |
| `/week` | Le statut compact de la semaine en cours : réalisé/prévu, garde-fous |
| `/race` | Le compte à rebours de votre objectif, le score Trail Shape, la forme prévue le jour J (estimation), votre plan de course s'il existe |
| `/log` | Saisie libre en une phrase — ravitaillement, douleur, RPE — convertis en données du contrat sans jamais inventer une valeur |
| `/inspection` | Lancer l'inspection photo d'une paire de chaussures : désigner la paire, protocole photo, où déposer les photos (`gear/photos/`) |

`/today`, `/why`, `/week` et `/race` n'écrivent ni ne modifient jamais un
plan, une semaine, une décision ou un plan de course, et ne poussent jamais
rien vers Garmin. `/log`, lui, écrit dans `activities/`/`medical/` (jamais
dans `planning/`) ; `/inspection` n'écrit, une fois la paire et les photos fournies,
que dans `gear/`.

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
├── agents/                  # Agents IA (coach, course-strategist, medical, nutritionist, sports-director)
├── skills/                  # Skills (analyse GPX, planification, météo, etc.)
├── scripts/                 # Machine « coach » : sync automatique, notifications, Remote Control
├── config/
│   ├── workspace.toml       # Configuration (staff, sport, style, santé, langue)
│   ├── coaching-styles.md   # Catalogue des styles de coaching
│   ├── setup-questions.toml # Questions du premier démarrage
│   ├── sports/              # Profils de sport (trail, route)
│   ├── plans/               # Gabarits de périodisation (JSON, vérifiés par arc_plan_templates.py)
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
- [Le bot Telegram (retours en un geste, sans clé d'API)](docs/telegram.md)
- [Mettre à jour (moteur, workspace, machine coach)](docs/update.md)
- [Tableau de bord](docs/dashboard/index.md) · [Les vues](docs/dashboard/views.md) · [Migrer vos fichiers](docs/dashboard/migration.md) · [Mode headless](docs/dashboard/headless.md) · [Docker](docs/dashboard/docker.md)
- [Les agents](docs/agents.md)
- [Les skills](docs/skills.md)
- [Gabarits de périodisation](docs/plans.md)
- [Vitesse critique et courbe allure-durée](docs/vitesse-critique.md)
- [Renforcement et mobilité (bibliothèque et programmes)](docs/strength.md)
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
