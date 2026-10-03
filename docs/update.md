# Mettre à jour

`ai-running-coach` s'installe par un simple `git clone` : mettre à jour, c'est **tirer
le moteur** puis **relancer `install.sh` avec les mêmes options** que lors de
l'installation. Vos données (workspace) ne sont jamais touchées ; `install.sh` est
idempotent et ne remplace jamais une réponse de `/coach-setup` ni votre
`config/workspace.user.toml`.

## En bref

```bash
cd ~/ai-running-coach
git pull --ff-only
./install.sh <les mêmes options qu'à l'installation>
python3 scripts/coach_doctor.py
```

## Ce qu'un `git pull` seul ne met pas à jour

Les agents et skills existants sont des **liens** vers le moteur : un `git pull` suffit
pour eux. Relancer `install.sh` reste nécessaire pour tout ce qui est **généré** :

| Élément | Pourquoi relancer `install.sh` |
|---|---|
| Catalogue `agents/` et `skills/` du workspace | Un nouveau skill (ex. `/today`, `/log`, `coach-doctor`) n'apparaît qu'une fois son lien créé. |
| `.mcp.json` | La liste blanche d'outils Garmin (`GARMIN_ENABLED_TOOLS`) évolue avec les skills ; l'ancienne reste figée dans le fichier. |
| Bloc `.gitignore` du workspace | De nouveaux fichiers générés peuvent y être ajoutés. |
| Crontab / launchd du daily-sync | Relus depuis `[sync].mode` (`schedule` : heures de `[sync].times` ; `watch` : sondage `scripts/garmin_watch.py`, voir [Le coach dans la poche](mobile.md#mode-watch-ne-payer-le-llm-que-quand-garmin-a-du-neuf)) ; les lignes marquées sont remplacées, le reste de la crontab est conservé (sauvegarde dans `~/.config/ai-running-coach/`). |
| Unité Remote Control | Réécrite si son modèle a changé. |
| Lecteur FIT (`fitparse`) de l'environnement `intervals-icu-mcp` | Source intervals.icu : `fitparse` y est ajouté (sans réinstaller le serveur) pour que `fit-download` lise les FIT — sans lui, zones, GAP, VAM… restent vides. `coach_doctor.py` le signale (`fit_reader`). |

Les tokens Garmin sont **vérifiés**, pas redemandés : l'authentification interactive ne
se relance que s'ils sont absents ou expirés.

## Retrouver ses options d'installation

`install.sh` ne mémorise que le chemin du workspace (`~/.config/ai-running-coach/workspace`).
Pour le reste, les traces de l'installation suffisent :

| Trace | Option correspondante |
|---|---|
| `~/.config/ai-running-coach/workspace` existe | `--workspace <ce chemin>` |
| `crontab -l` contient `# ai-running-coach daily-sync` | `--daily-sync` |
| Service `ai-running-coach-remote` (`scripts/coach-remote.sh status`) | `--remote-control` |
| `[agents].enabled` dans `config/workspace.user.toml` | `--agents …` (ou `--no-medical`) |
| `[data].source = "intervals"` | `--source intervals` |
| `[data].source = "strava"` | `--source strava` |
| Dossiers `.claude/`, `.opencode/`, `.gemini/`… présents | `--ide …` |

Une machine coach (daily-sync + Remote Control, Claude Code) correspond au préréglage
`--preset coach-server` ; un portable à `--preset laptop`. Voir
[Préréglages](quickstart.md#prereglages).

## Machine coach (cron + Remote Control)

La machine coach tourne sans surveillance : on met à jour **entre deux synchronisations**
(par défaut 07:15 et 14:15) pour ne pas tirer le moteur pendant qu'un run l'utilise.

```bash
ssh machine-coach
cd ~/ai-running-coach

# 1. état des lieux : rien de modifié localement, combien de commits de retard
git status --short
git fetch origin && git log --oneline HEAD..origin/main | wc -l

# 2. point de retour, au cas où
git tag -f avant-maj HEAD

# 3. mise à jour du moteur
git pull --ff-only

# 4. aperçu, puis application (mêmes options qu'à l'installation)
./install.sh --preset coach-server --workspace ~/mon-workspace --dry-run
./install.sh --preset coach-server --workspace ~/mon-workspace

# 5. Remote Control : relancer pour que les nouvelles sessions voient le nouveau .mcp.json
scripts/coach-remote.sh restart

# 6. vérification
python3 scripts/coach_doctor.py --workspace ~/mon-workspace
scripts/daily-sync.sh     # optionnel : un run à blanc, notification comprise
```

Puis, dans le workspace, `git status` : seuls `.gitignore` (bloc généré) et
éventuellement `config/` doivent apparaître. Avec `git_autocommit = true`, le prochain
daily-sync les committe de lui-même.

!!! note "Sessions Remote Control en cours"
    Le redémarrage coupe la session ouverte sur le téléphone ; elle reste reprenable
    ~4 h, mais une session **reprise** garde les outils MCP qu'elle avait au démarrage.
    Ouvrez une nouvelle session pour profiter des nouveaux outils.

## Serveurs MCP (`garmin-mcp`, `intervals-icu-mcp`)

`install.sh` n'installe un serveur MCP que s'il est **absent** : il ne le met jamais à jour
de lui-même. Pour suivre les correctifs de `garmin-mcp` (API Garmin qui change, nouveaux
outils de la liste blanche) :

```bash
uv tool upgrade garmin-mcp
```

`intervals-icu-mcp` est épinglé à un commit précis (`INTERVALS_MCP_REF` dans
`install.sh`) : quand ce commit change dans le moteur, réinstallez-le explicitement
(voir [Configuration Intervals.icu](intervals-setup.md)).

## Revenir en arrière

```bash
cd ~/ai-running-coach
git reset --hard avant-maj
./install.sh <mêmes options>
scripts/coach-remote.sh restart     # machine coach uniquement
```

Vos données ne sont pas concernées : elles vivent dans le workspace, jamais dans le moteur.

## Voir aussi

- [Votre workspace privé](workspace.md) — séparation moteur / données.
- [Le coach dans la poche](mobile.md) — cron, ntfy, Remote Control.
- [Dépannage](troubleshooting.md) — à commencer par `coach_doctor.py`.
