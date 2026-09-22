# Contribuer à ai-running-coach

Merci de votre intérêt pour `ai-running-coach` ! Voici les conventions à respecter.

## Conventions

### Langue

- **Tout le contenu** (agents, skills, documentation, fichiers MD générés) est en **français**
- Les noms de fichiers et de dossiers sont en anglais (convention technique)

### Structure

```
agents/                  # Agents IA (un fichier .md par agent)
skills/                  # Skills (un dossier par skill avec SKILL.md)
config/gemini/commands/  # Templates de commandes Gemini CLI
.github/                 # Instructions Copilot + workflows (agent cloud, Pages)
docs/                    # Documentation (MkDocs / GitHub Pages)
```

> Les dossiers `.github/agents/` et `.github/skills/` sont des **liens symboliques**
> vers `agents/` et `skills/`, créés par `./install.sh --ide copilot` et gitignorés.
> Ne les modifiez jamais directement.

### Agents

- Un agent = un fichier Markdown dans `agents/`
- Format : frontmatter YAML (`name`, `description`, `mode: subagent`) + instructions
  — `name` et `description` sont **obligatoires** pour la découverte par GitHub Copilot
- Les agents délèguent via l'outil `task` de leur IDE
- Toutes les données Garmin passent par les outils du serveur MCP `garmin` (mode direct) ou via `leanproxy_invoke_tool(server="garmin", ...)` (mode passerelle)

### Skills

- Un skill = un dossier dans `skills/` avec un fichier `SKILL.md`
- Le `SKILL.md` commence par un frontmatter YAML avec `name` (lettres, chiffres, tirets)
  et `description` (quoi + quand l'utiliser, ≤ 1024 caractères) — **obligatoires** pour
  la découverte par GitHub Copilot
- Les scripts Python doivent utiliser **uniquement la stdlib** (sauf exception documentée)
- Chaque skill doit documenter son usage dans `docs/skills/`

### Scripts Python

- **stdlib uniquement** par défaut
- Si des dépendances externes sont nécessaires, documentez-les dans le `SKILL.md`
- Vérifiez la syntaxe : `python3 -m py_compile <script>.py`

## Processus

1. **Fork** le dépôt
2. Créez une **branche** : `git checkout -b feature/ma-fonctionnalite`
3. Faites vos modifications
4. **Testez** :
   - `bash -n install.sh` (syntaxe du script d'installation)
   - `python3 -m py_compile skills/*/scripts/*.py` (syntaxe des scripts)
   - `./install.sh --dry-run` (test du script d'installation)
5. **Commit** avec un message clair
6. Ouvrez une **pull request**

## Tests

```bash
# Syntaxe du script d'installation
bash -n install.sh

# Syntaxe des scripts Python
python3 -m py_compile skills/*/scripts/*.py

# Test du script d'installation (sans rien modifier)
./install.sh --dry-run

# Build de la documentation
pip install mkdocs-material
mkdocs build
```

## Licence

En contribuant, vous acceptez que vos contributions soient publiées sous la [licence MIT](LICENSE).

## Tests

Trois paliers, aucun paquet à installer (bibliothèque standard uniquement) :

```bash
python3 tests/run_tests.py --tier a     # intégration de l'installation (bac à sable)
python3 tests/run_tests.py --tier b     # lint des prompts et de la configuration
ARC_LLM_TESTS=1 python3 tests/run_tests.py --tier c   # évals d'exécution (modèle léger)
```

Les paliers A et B tournent en CI sur `ubuntu-latest` **et** `macos-latest` — bash
3.2, le sed de BSD et `launchctl` sont des cibles de premier plan. Le palier C
coûte des jetons : il ne tourne que la nuit et sur déclenchement manuel.

Le détail (bac à sable, stubs, ajout d'un cas) est dans
[`tests/README.md`](tests/README.md).

### Fichiers générés

`config/gemini/commands/*.toml` est **généré** depuis `agents/*.md`. Ne les
éditez pas à la main :

```bash
python3 scripts/build-gemini-commands.py
```

La CI vérifie leur fraîcheur.

### Avant d'ouvrir une PR

```bash
shellcheck -S warning install.sh scripts/*.sh scripts/lib/*.sh
python3 tests/run_tests.py --tier ab
python3 scripts/build-gemini-commands.py --check
mkdocs build --strict
```
