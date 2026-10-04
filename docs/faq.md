# FAQ

## Général

### Qu'est-ce que `ai-running-coach` ?

Un projet open-source qui fournit des **agents IA** et des **skills** pour aider les coureurs à préparer un objectif (course, trail, ultra) avec l'aide d'un assistant IA dans leur IDE préféré.

### Quels IDE sont supportés ?

Claude Code, GitHub Copilot, OpenCode, Gemini CLI, Cursor et Windsurf.

### Le projet est-il en français ?

Oui, le projet est **en français par défaut** : les agents, les skills et la documentation sont en français, et les fichiers Markdown générés utilisent la langue configurée dans `config/workspace.toml` (`[language].documents`, défaut : français). Vous pouvez changer cette langue via `config/workspace.user.toml` (gitignoré).

### Quels appareils sont supportés ?

**Garmin Connect** (montres et capteurs Garmin) est la destination primaire par défaut, installée automatiquement par `./install.sh`. **Intervals.icu** (#68) peut aussi devenir la source primaire avec `./install.sh --source intervals` — voir [Configuration Intervals.icu](intervals-setup.md) — ou rester en secondaire, uniquement sur demande explicite à l'agent `coach`, voir [configurer Intervals.icu sans passer par `install.sh`](#comment-configurer-intervalsicu-sans-passer-par-installsh) ci-dessous.

**Strava** (#164) — la source « universelle » de toutes les marques de montres — peut aussi être la source primaire avec `./install.sh --source strava` (Node.js 18+ requis) : voir [Configuration Strava](strava-setup.md). Sans HRV/sommeil/readiness ni push de séances, mais avec les flux par seconde pour les KPI.

## Installation

### Quels sont les prérequis ?

macOS ou Linux, bash 4+, curl, git, et un compte Garmin Connect.

### Combien de temps dure l'installation ?

Quelques minutes. Le script installe uv, garmin-mcp et configure votre IDE (mode direct). Le mode passerelle leanproxy-mcp est optionnel (`--use-leanproxy`).

### L'installation est-elle sûre ?

Oui. Le script n'installe que des outils open-source connus (uv, garmin-mcp, et optionnellement leanproxy-mcp). Vos identifiants Garmin ne sont jamais stockés dans le projet — les tokens sont conservés dans `~/.garminconnect/`.

### Puis-je installer pour un seul IDE ?

Oui : `./install.sh --ide claude` (ou `opencode`, `gemini`, `cursor`, `windsurf`).

## Garmin

### Comment fonctionne l'accès à Garmin Connect ?

Le projet utilise `garmin-mcp` (serveur MCP) pour accéder aux données Garmin Connect : activités, santé, sommeil, calendrier, planification d'entraînements. Une passerelle optionnelle `leanproxy-mcp` (mode power user) peut réduire la consommation de tokens.

### Mes identifiants Garmin sont-ils en sécurité ?

Oui. L'authentification utilise OAuth et les tokens sont stockés dans `~/.garminconnect/`, hors du dépôt. Vos identifiants ne sont jamais écrits dans le projet.

### Combien de temps les tokens sont-ils valides ?

Environ **6 mois**. Après expiration, relancez `uv run garmin-mcp-auth`.

### Puis-je utiliser le projet sans compte Garmin ?

Non, l'accès à Garmin Connect est requis pour la synchronisation des données.

## Intervals.icu

### Intervals.icu est-il installé automatiquement ?

Depuis #68 : **oui, si vous le demandez** — `./install.sh --source intervals`
installe et configure `intervals-icu-mcp` (serveur communautaire
[`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp), fork
maintenu de `eddmann/intervals-icu-mcp` depuis #165),
**à la place** de `garmin-mcp`, et écrit `[data].source = "intervals"`. Voir
[Configuration Intervals.icu](intervals-setup.md) pour le détail. Sans cette
option, `install.sh` continue de n'installer que `garmin-mcp` (et, en option,
la passerelle `leanproxy-mcp`), comme avant #68.

### Comment configurer Intervals.icu sans passer par `install.sh` ?

Utile si vous voulez Intervals.icu en **secondaire** (Garmin reste la source
primaire, vous demandez explicitement un événement Intervals.icu de temps en
temps) plutôt qu'en remplacement complet de Garmin :

1. Suivez le README du serveur retenu par le projet
   ([`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp))
   pour l'installation exacte (clone + `uv sync`, ou `uv tool install`
   directement — voir [Configuration Intervals.icu](intervals-setup.md)).
   Les outils portent le préfixe `icu_` : c'est le seul serveur dont les noms
   d'outils sont ceux attendus par le coach (l'ancien `eddmann/…` expose les mêmes
   outils sans préfixe).
2. Ajoutez-le manuellement à la configuration MCP de votre IDE — **jamais de
   secret dans `.mcp.json`**, et **jamais un bloc `env` avec `${VAR}`** : le
   serveur charge ses identifiants depuis un `.env` relatif à SON répertoire
   de travail (`pydantic-settings`), pas depuis une variable passée par
   l'IDE, qui démarre le processus dans le dossier du projet — voir
   [Configuration Intervals.icu](intervals-setup.md#pourquoi-un-wrapper-et-pas-une-variable-denvironnement)
   pour le détail et pourquoi `install.sh --source intervals` écrit un petit
   script wrapper à la place. Si vous clonez le dépôt vous-même, `uv run
   --directory /chemin/vers/intervals-icu-mcp intervals-icu-mcp` fixe le même
   répertoire de travail sans wrapper :

   ```json
   {
     "mcpServers": {
       "intervals": {
         "command": "uv",
         "args": ["run", "--directory", "/chemin/vers/intervals-icu-mcp", "intervals-icu-mcp"]
       }
     }
   }
   ```

3. Demandez explicitement à l'agent `coach` de créer ou mettre à jour un
   événement sur Intervals.icu — il charge alors le skill
   `intervals-icu-best-practices`. Avec `[data].source = "garmin"` (défaut),
   Garmin reste la destination **primaire** : Intervals.icu n'est utilisé que
   sur demande explicite.

### Et le MCP officiel de COROS ?

Audité dans #168 : il peut s'ajouter à la main pour un usage interactif, mais il
n'est pas une source du projet (noms d'outils non vérifiables, authentification
OAuth interactive, pas de support documenté de Claude Code). Les montres COROS
passent par Intervals.icu ; voir [Montres COROS](coros.md).

## Agents

### Quel agent dois-je utiliser ?

Commencez toujours par l'agent **`coach`**. Il coordonne les autres agents (stratège de course, médecin, nutritionniste) selon vos besoins.

### Comment définir mon objectif ?

Demandez à l'agent `coach`, par exemple : *« Je veux préparer un trail de 50 km avec 2500 m de D+ dans 6 mois »*.

### Les agents poussent-ils les séances dans Garmin ?

Oui. L'agent `coach` pousse les séances planifiées directement dans le **calendrier Garmin Connect**.

## Données

### Où sont stockées mes données ?

Dans les dossiers de travail du projet : `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/`, `resources/`. Ces dossiers sont **exclus du dépôt** (voir `.gitignore`).

### Mes données personnelles sont-elles publiées ?

Non. Les dossiers de données personnelles sont exclus du dépôt via `.gitignore`. Le projet ne contient que des agents, des skills et de la documentation.

### Puis-je utiliser mes propres documents de référence ?

Oui. Placez vos documents dans `resources/` (par exemple `resources/nutrition/catalogue-produits-*.md` pour les catalogues produits).

### Mon profil est plus ancien que la section « Indices de performance » : comment l'ajouter ?

`/coach-setup` n'écrase jamais une réponse existante, donc il ne rajoute pas non plus une section apparue dans le modèle après votre installation. Deux façons de faire, sur un profil existant (`planning/Runner_Profile.md`) :

- **Demandez à l'agent `coach`** : il propose d'ajouter la section vide, à votre confirmation, s'il constate qu'elle manque au moment où vous parlez de votre niveau ou d'un objectif.
- **Copiez-la vous-même** depuis `templates/Runner_Profile.template.md` (section « Indices de performance (ITRA / UTMB) ») dans votre propre `planning/Runner_Profile.md`, puis remplissez ce que vous voulez.

Les deux méthodes sont équivalentes : la section n'est jamais remplie automatiquement avec une valeur trouvée sur le web (voir « Mes données personnelles sont-elles publiées ? » ci-dessus et le mandat de vie privée d'`agents/coach.md`).

## Skills

### Qu'est-ce qu'un skill ?

Un skill est un ensemble d'instructions et de scripts que les agents chargent à la demande pour une tâche spécifique (analyse GPX, planification Garmin, météo, etc.).

### Puis-je créer mes propres skills ?

Oui. Les skills sont des dossiers avec un fichier `SKILL.md` et éventuellement des scripts. Consultez la [documentation des skills](skills.md).

## Sécurité

### Le projet est-il sûr pour mes données ?

Oui. Le projet ne contient aucune donnée personnelle. Les données sont stockées localement dans les dossiers de travail, exclus du dépôt.

### Puis-je contribuer au projet ?

Oui ! Les contributions sont les bienvenues. Consultez le fichier `CONTRIBUTING.md` pour les conventions.
