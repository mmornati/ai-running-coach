# 🗂️ Votre workspace privé

`ai-running-coach` est un **moteur** : agents, skills, scripts, installation. Vos données —
séances, santé, plans, rapports, ressources — sont votre **workspace**. Par défaut les deux
vivent dans le même dossier (les dossiers de données sont exclus du dépôt). Dès que vous
voulez **versionner vos données dans votre propre dépôt privé** et **suivre les mises à
jour du moteur sans rien copier**, séparez-les avec `--workspace`.

## Le principe

```
~/ai-running-coach/          moteur (ce dépôt, public)        → git pull pour les nouveautés
~/mon-workspace/             workspace (VOTRE dépôt privé)
├── activities/ medical/ nutrition/ planning/ rapports/ resources/   ← versionnés
├── local/agents/  local/skills/    ← vos agents/skills privés, versionnés
├── config/workspace.user.toml      ← vos réglages (langue, notifications, sync), versionné
│
│   généré par install.sh, ignoré par git (bloc ajouté à .gitignore) :
├── agents/  skills/                ← catalogues de liens : moteur + local/
├── AGENTS.md  config/workspace.toml → liens vers le moteur
├── .mcp.json  .claude/  .opencode/  .gemini/  .cursor/  .windsurf/  .github/agents|skills
└── logs/
```

- **Rien n'est copié** : `agents/` et `skills/` du workspace ne contiennent que des liens.
  Un `git pull` dans le moteur met à jour tous les skills instantanément ; relancez
  `./install.sh --workspace …` seulement si un skill a été **ajouté ou supprimé** (le
  catalogue est recréé, idempotent).
- **Vos skills privés** vont dans `local/skills/<nom>/SKILL.md` (idem `local/agents/`) :
  ils apparaissent dans le catalogue à côté de ceux du moteur, avec priorité en cas
  d'homonyme. Candidats à une contribution upstream quand ils sont génériques.
- **La diff de votre dépôt privé = vos données**, rien d'autre.
- L'IDE, le cron et Remote Control travaillent **dans le workspace** (`cwd`), jamais dans
  le moteur.

!!! note "Pourquoi pas un fork ou un sous-module ?"
    Un fork du moteur contenant vos données oblige à modifier son `.gitignore` et à
    résoudre ce conflit à chaque synchronisation. Un sous-module fonctionne (il fige la
    version du moteur) mais ajoute de la cérémonie ; `--workspace` accepte aussi un moteur
    cloné en sous-module de votre workspace si vous tenez à ce figeage.

## Mise en place

```bash
# 1. le moteur
git clone https://github.com/mmornati/ai-running-coach.git ~/ai-running-coach

# 2. votre dépôt privé (nouveau ou existant)
git clone git@github.com:vous/mon-workspace.git ~/mon-workspace   # ou : mkdir + git init

# 3. installation : configs IDE, dossiers et liens dans le workspace
cd ~/ai-running-coach
./install.sh --ide claude --workspace ~/mon-workspace
```

Le chemin du workspace est mémorisé dans `~/.config/ai-running-coach/workspace` : les
scripts (`daily-sync.sh`, `coach-remote.sh`, `setup-ntfy.sh`) l'utilisent automatiquement
(variable `ARC_WORKSPACE` pour forcer). Les options `--daily-sync` et `--remote-control`
(voir [Le coach dans la poche](mobile.md)) s'appliquent au workspace.

Ouvrez ensuite votre IDE **dans `~/mon-workspace`**.

## Migrer un workspace existant

Si votre dépôt privé contient déjà des **copies** d'agents/skills (`.opencode/skills/…`,
`AGENTS.md` maison…), supprimez-les de l'index avant l'installation — sinon `install.sh`
refuse d'écraser un vrai dossier par un lien :

```bash
cd ~/mon-workspace
git rm -r --cached .opencode/agents .opencode/skills .gemini/commands AGENTS.md
rm -rf .opencode/agents .opencode/skills .gemini/commands AGENTS.md
# skills privés (absents du moteur) → local/
mkdir -p local/skills && git mv .opencode/skills/mon-skill local/skills/mon-skill   # avant le rm ci-dessus
```

Puis `./install.sh --ide claude --workspace ~/mon-workspace`, vérifiez `git status` (seuls
vos données, `local/`, `config/workspace.user.toml` et `.gitignore` doivent apparaître) et
committez.

## Versionner automatiquement depuis la machine coach

Avec `git_autocommit = true` dans `config/workspace.user.toml` (section `[sync]`), chaque
run de `scripts/daily-sync.sh` termine par `git add -A && git commit && git push` dans le
workspace : les fichiers de la synchronisation **et** ceux créés entre-temps par vos sessions
mobiles (plans, rapports) arrivent dans votre dépôt privé sans intervention. Un échec de
commit/push est signalé dans la notification, sans bloquer la synchronisation. Le push
suppose une clé SSH sur la machine coach autorisée sur votre dépôt.

Sur le portable : `git pull` avant de travailler.

## Suivre les mises à jour du moteur

```bash
cd ~/ai-running-coach && git pull
./install.sh --ide claude --workspace ~/mon-workspace --no-auth   # si un skill a été ajouté/supprimé
```

Sur la machine coach, le service Remote Control et le cron n'ont pas besoin d'être
redémarrés : ils lisent les skills à chaque session.

## Ce qui reste hors des deux dépôts

- `~/.garminconnect/` — tokens Garmin
- `~/.config/ai-running-coach/ntfy.token` — token de notification
- `~/.config/ai-running-coach/workspace` — chemin du workspace
- `~/.claude.json` — approbation du serveur MCP pour le workspace
