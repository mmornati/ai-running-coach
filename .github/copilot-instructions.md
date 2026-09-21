# Instructions GitHub Copilot — ai-running-coach

> **Source de vérité** : [`AGENTS.md`](../AGENTS.md) à la racine du dépôt.
> Lisez-le en premier — il décrit le mandat linguistique, la carte des dossiers,
> les sous-agents, les backends MCP et les skills. Ce fichier ne contient que
> les spécificités **Copilot**.

## Découverte des agents et des skills

| Ressource | Source de vérité | Chemin lu par Copilot |
|---|---|---|
| Agents | `agents/*.md` | `.github/agents/*.md` (lien symbolique créé par `./install.sh --ide copilot`) |
| Skills | `skills/*/SKILL.md` | `.github/skills/*/SKILL.md` (lien symbolique) |
| Serveurs MCP | — | `.mcp.json` à la racine du projet |

Ne modifiez jamais `.github/agents/` ou `.github/skills/` directement : ce sont
des liens vers `agents/` et `skills/`, gitignorés.

## Agents disponibles

`coach` (principal), `medical`, `nutritionist`, `course-strategist`.
Invocation : `/agent coach` dans Copilot CLI, ou délégation via l'outil `task`
depuis l'agent principal. Voir `AGENTS.md` pour le périmètre de chacun.

## Règles de délégation

Écrire le prompt de tâche en anglais et ajouter explicitement
**« Respond in \<langue des documents\> »** (résolue via `config/workspace.toml`
→ `[language].documents`, défaut `fr`) lorsque la sortie est destinée à
l'utilisateur.

## Accès Garmin (MCP)

Le serveur MCP `garmin` est déclaré dans `.mcp.json` avec une liste blanche
d'outils (`GARMIN_ENABLED_TOOLS`). Copilot CLI demande la **confiance du dossier**
au premier lancement : acceptez-la, sinon les serveurs MCP du projet ne sont pas
chargés.

Respectez les règles de fraîcheur des données d'`AGENTS.md` : vérifier le
fichier MD du jour avant tout appel Garmin, puis persister immédiatement le
Markdown correspondant (jamais de JSON brut dans le chat).

## Agent cloud Copilot

L'environnement de l'agent cloud est préparé par
[`.github/workflows/copilot-setup-steps.yml`](workflows/copilot-setup-steps.yml)
(Python 3.12 + dépendances de documentation).

L'agent cloud n'a **pas** accès à Garmin Connect (aucun token) : il est destiné
aux contributions sur le dépôt (documentation, agents, skills, script
d'installation), pas au coaching. Les dossiers de données personnelles
(`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`,
`resources/`) sont gitignorés et absents de ses checkouts.

## Contribution

Voir [`CONTRIBUTING.md`](../CONTRIBUTING.md). Les instructions des agents et des
skills restent rédigées en français ; seule la langue de sortie des documents
est paramétrable.
