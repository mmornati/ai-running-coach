# ❓ FAQ

## Général

### Qu'est-ce que `ai-running-coach` ?

Un projet open-source qui fournit des **agents IA** et des **skills** pour aider les coureurs à préparer un objectif (course, trail, ultra) avec l'aide d'un assistant IA dans leur IDE préféré.

### Quels IDE sont supportés ?

Claude Code, GitHub Copilot, OpenCode, Gemini CLI, Cursor et Windsurf.

### Le projet est-il en français ?

Oui, le projet est **en français par défaut** : les agents, les skills et la documentation sont en français, et les fichiers Markdown générés utilisent la langue configurée dans `config/workspace.toml` (`[language].documents`, défaut : français). Vous pouvez changer cette langue via `config/workspace.user.toml` (gitignoré).

### Quels appareils sont supportés ?

Seul **Garmin** est supporté dans cette version (Garmin Connect, montres et capteurs Garmin).

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

## Agents

### Quel agent dois-je utiliser ?

Commencez toujours par l'agent **`coach`**. Il coordonne les autres agents (stratège de course, médecin, nutritionniste) selon vos besoins.

### Comment définir mon objectif ?

Demandez à l'agent `coach`, par exemple : *« Je veux préparer un trail de 50 km avec 2500 m de D+ dans 6 mois »*.

### Les agents poussent-ils les séances dans Garmin ?

Oui. L'agent `coach` pousse les séances planifiées directement dans le **calendrier Garmin Connect**.

## Données

### Où sont stockées mes données ?

Dans les dossiers de travail du projet : `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `resources/`. Ces dossiers sont **exclus du dépôt** (voir `.gitignore`).

### Mes données personnelles sont-elles publiées ?

Non. Les dossiers de données personnelles sont exclus du dépôt via `.gitignore`. Le projet ne contient que des agents, des skills et de la documentation.

### Puis-je utiliser mes propres documents de référence ?

Oui. Placez vos documents dans `resources/` (par exemple `resources/nutrition/catalogue-produits-*.md` pour les catalogues produits).

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
