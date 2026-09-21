# 🧑‍💻 IDE supportés

`ai-running-coach` supporte **6 IDE** avec une configuration automatique via le script d'installation.

## Claude Code

- **Agents** : `.claude/agents/*.md`
- **Skills** : `.claude/skills/*/SKILL.md`
- **MCP** : `.mcp.json` (à la racine du projet)

Le script crée des **liens symboliques** depuis `.claude/` vers `agents/` et `skills/`, afin que le projet reste la source de vérité.

```bash
./install.sh --ide claude
```

## GitHub Copilot

- **Agents** : `.github/agents/*.md`
- **Skills** : `.github/skills/*/SKILL.md`
- **MCP** : `.mcp.json` (à la racine du projet, partagé avec Claude Code)
- **Instructions** : `.github/copilot-instructions.md` (+ `AGENTS.md`, lu nativement)

Le script crée des **liens symboliques** depuis `.github/` vers `agents/` et `skills/`, afin que le projet reste la source de vérité.

```bash
./install.sh --ide copilot
```

Fonctionne avec **Copilot CLI**, **Copilot dans VS Code** et l'**agent cloud** (Copilot coding agent).

### Copilot CLI

```bash
copilot            # depuis le dossier du projet
/agent coach       # sélectionne l'agent coach
/skills            # liste les skills disponibles
/mcp               # vérifie le serveur MCP garmin
```

!!! warning "Confiance du dossier"
    Au premier lancement, Copilot CLI demande de **faire confiance au dossier**.
    Sans cette confirmation, les serveurs MCP du projet (donc `garmin`) ne sont pas chargés.

### Agent cloud

L'environnement de l'agent cloud est préparé par `.github/workflows/copilot-setup-steps.yml`.
Il n'a **pas** accès à Garmin Connect (aucun token) : utilisez-le pour contribuer au dépôt
(documentation, agents, skills, installation), pas pour le coaching.

## OpenCode

- **Agents** : `.opencode/agents/*.md`
- **Skills** : `.opencode/skills/*/SKILL.md`
- **MCP** : `~/.config/opencode/opencode.json`

Le script crée des **liens symboliques** depuis `.opencode/` vers `agents/` et `skills/`.

```bash
./install.sh --ide opencode
```

## Gemini CLI

- **Commandes** : `.gemini/commands/*.toml`

Le script copie les templates depuis `config/gemini/commands/` vers `.gemini/commands/`.

```bash
./install.sh --ide gemini
```

## Cursor

- **MCP** : `.cursor/mcp.json`

```bash
./install.sh --ide cursor
```

## Windsurf

- **MCP** : `.windsurf/mcp_config.json`

```bash
./install.sh --ide windsurf
```

## Tous les IDE

Par défaut, le script configure **tous** les IDE :

```bash
./install.sh
```

## Vérification

Après installation, vérifiez que la configuration MCP est présente :

```bash
# Claude Code
cat .mcp.json

# GitHub Copilot (même fichier + agents/skills)
cat .mcp.json
ls .github/agents/ .github/skills/

# OpenCode
cat ~/.config/opencode/opencode.json

# Cursor
cat .cursor/mcp.json

# Windsurf
cat .windsurf/mcp_config.json

# Gemini CLI
ls .gemini/commands/
```

Chaque configuration doit contenir une référence au serveur MCP `garmin` (mode direct) ou `leanproxy` (mode passerelle).
