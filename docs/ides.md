# 🧑‍💻 IDE supportés

`ai-running-coach` supporte **5 IDE** avec une configuration automatique via le script d'installation.

## Claude Code

- **Agents** : `.claude/agents/*.md`
- **Skills** : `.claude/skills/*/SKILL.md`
- **MCP** : `.mcp.json` (à la racine du projet)

Le script crée des **liens symboliques** depuis `.claude/` vers `agents/` et `skills/`, afin que le projet reste la source de vérité.

```bash
./install.sh --ide claude
```

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

# OpenCode
cat ~/.config/opencode/opencode.json

# Cursor
cat .cursor/mcp.json

# Windsurf
cat .windsurf/mcp_config.json

# Gemini CLI
ls .gemini/commands/
```

Chaque configuration doit contenir une référence au serveur MCP `leanproxy`.
