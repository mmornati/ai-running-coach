# Mettre à jour

**Installation avec l'application Mac :** les versions publiées sont proposées dans
l'app, puis le moteur est actualisé au relancement. Voir [Mises à jour macOS](macos.md#mises-a-jour).
Les commandes ci-dessous concernent les installations par clonage Git.

`ai-running-coach` s'installe par un simple `git clone` : mettre à jour, c'est **tirer
le moteur** puis **relancer `install.sh` avec les mêmes options** que lors de
l'installation. Vos données (workspace) ne sont jamais touchées ; `install.sh` est
idempotent et ne remplace jamais une réponse de `/coach-setup` ni votre
`config/workspace.user.toml`.

## En bref

```bash
scripts/update-coach.sh      # ou /update-coach dans votre assistant
```

Il fait exactement les trois étapes ci-dessous, avec les options de votre dernière
installation (mémorisées par `install.sh` dans `~/.config/ai-running-coach/install-args`),
et refuse plutôt que de forcer : moteur hors de `main`, modifications locales, options
inconnues (installation antérieure à leur mémorisation). Une nouvelle release est
signalée par le tableau de bord, au démarrage de Claude Code et par la notification du
daily-sync — voir [Mettre à jour (/update-coach)](skills/update-coach.md).

À la main :

```bash
cd ~/ai-running-coach
git pull --ff-only
./install.sh <les mêmes options qu'à l'installation>
python3 scripts/coach_doctor.py
```

## Passer de la 1.3 à la 1.4

La 1.4 ajoute COROS, le choix de l'IA, l'épopée chaussures, l'export Vanoor, plusieurs workspaces sur
une machine et un tableau de bord installable (liste complète : [Nouveautés](nouveautes.md)). Aucune
donnée à migrer, aucune option nouvelle obligatoire ; seule une machine coach dont les données vivent
dans un workspace séparé demande une étape de plus (point 2).

1. **Mise à jour ordinaire** : `/update-coach`, ou à la main `git pull --ff-only` puis
   `./install.sh` avec vos options d'origine (voir [En bref](#en-bref)). Les nouveaux skills
   (`/shoes`, `shoe-specs`, `shoe-selection`, `vanoor-export`…) apparaissent grâce au rejeu d'`install.sh`.
2. **Machine coach avec `daily-sync` et `--workspace`** : la planification est désormais **propre à chaque
   workspace** (#127). Une réinstallation sans `--workspace` (par exemple `/update-coach` avec des options
   mémorisées vides) ajouterait une seconde planification. Si votre synchronisation tourne en mode `watch`, suivez
   [le script de migration](#mode-watch-garmin_watchpy-devient-watchpy-coros-planification-par-workspace-127)
   (`scripts/migrate-sync-127.sh`) pour ne pas obtenir deux synchronisations ; en mode `schedule`, relancez
   `./install.sh --daily-sync --workspace <votre workspace>` (toujours avec `--workspace`).
3. **Application Mac** : la mise à jour est proposée par l'app (Sparkle, signature Ed25519 vérifiée) ; la
   première fois depuis une version sans ce mécanisme, une dernière installation manuelle du DMG est
   nécessaire. Voir [Mises à jour macOS](macos.md#mises-a-jour).
4. **Tableau de bord en Docker** : `scripts/update-docker.sh` reconstruit et relance
   ([Docker](dashboard/docker.md)) : le compose construit toujours l'image localement. L'image est aussi publiée sur GHCR
   (`ghcr.io/mmornati/ai-running-coach-dashboard` : `:latest` = dernière release stable, `:edge` = tête de
   `main` après tests verts, `:X.Y.Z` pour épingler) : [Images publiées](dashboard/docker.md#images-publiees-ghcr).
5. **Tableau de bord** : le design « roadbook » devient le design par défaut ; l'ancien reste accessible avec
   `?design=classic` jusqu'à la 1.5. Le code du tableau de bord est chargé à son démarrage : relancez
   `scripts/dashboard.sh` (ou le service) après la mise à jour, puis rechargez la page. Rien à vider :
   l'application installable va toujours chercher ses fichiers sur le réseau d'abord, son cache ne sert
   que hors ligne.
6. **Vérifiez** : `python3 scripts/coach_doctor.py`.

## Ce qu'un `git pull` seul ne met pas à jour

Les agents et skills existants sont des **liens** vers le moteur : un `git pull` suffit
pour eux. Relancer `install.sh` reste nécessaire pour tout ce qui est **généré** :

| Élément | Pourquoi relancer `install.sh` |
|---|---|
| Catalogue `agents/` et `skills/` du workspace | Un nouveau skill (ex. `/today`, `/log`, `coach-doctor`) n'apparaît qu'une fois son lien créé. |
| Liens `config/coaching-styles.md` et `config/sports` du workspace | Ajoutés après coup : un workspace installé avant ne les a pas, et les agents ne trouvent alors ni le style de coaching (`[coaching].style`) ni le profil de sport (`[sport].primary`). Relancer `install.sh --workspace …` une fois. |
| `.mcp.json` | La liste blanche d'outils Garmin (`GARMIN_ENABLED_TOOLS`) évolue avec les skills ; l'ancienne reste figée dans le fichier. |
| Bloc `.gitignore` du workspace | De nouveaux fichiers générés peuvent y être ajoutés. |
| Crontab / launchd du daily-sync | Relus depuis `[sync].mode` (`schedule` : heures de `[sync].times` ; `watch` : sondage `scripts/watch.py`, voir [Le coach dans la poche](mobile.md#mode-watch-ne-payer-le-llm-que-quand-garmin-a-du-neuf)) ; les lignes marquées sont remplacées, le reste de la crontab est conservé (sauvegarde dans `~/.config/ai-running-coach/`). |
| Unité Remote Control | Réécrite si son modèle a changé. |
| Version du serveur `intervals-icu-mcp` (#165) | Source intervals.icu : `install.sh` réinstalle l'outil `uv` s'il n'est pas au commit épinglé (ancien serveur eddmann ou ancien commit du fork). `coach_doctor.py` le signale (`intervals_mcp_pin`). |
| Lecteur FIT (`fitparse`) de l'environnement `intervals-icu-mcp` | Source intervals.icu : `fitparse` y est ajouté (sans réinstaller le serveur) pour que `fit-download` lise les FIT — sans lui, zones, GAP, VAM… restent vides. `coach_doctor.py` le signale (`fit_reader`). |

Les tokens Garmin sont **vérifiés**, pas redemandés : l'authentification interactive ne
se relance que s'ils sont absents ou expirés.

## Nouveaux agents

Quand le moteur gagne un agent (ex. `sports-director`), la mise à jour **l'active
d'office**, même si vous relancez `install.sh` sans `--agents` :

```text
✔ Nouvel agent activé : sports-director — pour le retirer : ./install.sh --agents coach,medical,nutritionist,course-strategist
```

`install.sh` retient dans `config/workspace.user.toml` → `[agents].known` les agents
que le moteur fournissait lors de la dernière installation. Un agent absent de cette
liste est nouveau et rejoint votre staff ; un agent que vous aviez retiré (connu, mais
absent de `[agents].enabled`) le reste. Une installation antérieure à `known` est
traitée comme connaissant les quatre agents d'origine.

## Retrouver ses options d'installation

Depuis `/update-coach`, `install.sh` mémorise ses options dans
`~/.config/ai-running-coach/install-args` à chaque installation réussie : il suffit de
les retrouver UNE fois pour une installation plus ancienne. `--no-auth`, `--auth` et
`--dry-run` ne sont jamais mémorisés, et une relance sans autre option (`./install.sh --no-auth`)
garde les options déjà mémorisées.

`install.sh` ne mémorise que le chemin du workspace (`~/.config/ai-running-coach/workspace`).
Pour le reste, les traces de l'installation suffisent :

| Trace | Option correspondante |
|---|---|
| `~/.config/ai-running-coach/workspace` existe | `--workspace <ce chemin>` |
| `crontab -l` contient `# ai-running-coach daily-sync` (éventuellement suivi de `[<nom>-<somme>]`, un par workspace) | `--daily-sync` |
| Service `ai-running-coach-remote` (`scripts/coach-remote.sh status`) | `--remote-control` |
| `[agents].enabled` dans `config/workspace.user.toml` | `--agents …` (ou `--no-medical`) |
| `[data].source = "intervals"` | `--source intervals` |
| `[data].source = "strava"` | `--source strava` |
| `[data].source = "coros"` | `--source coros` |
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

### Mode watch : `garmin_watch.py` devient `watch.py` (COROS), planification par workspace (#127)

L'arrivée de COROS a renommé `scripts/garmin_watch.py` en `scripts/watch.py` (Garmin ou COROS).
**Une machine coach en mode `watch` ne casse pas** : `garmin_watch.py` est gardé comme cale qui
lance `watch.py` avec les mêmes arguments, donc la ligne cron posée avant le renommage continue de
tourner telle quelle. Elle sera réécrite avec le nouveau nom à la prochaine installation avec
`--daily-sync`.

C'est cette réinstallation qui demande de l'attention depuis #127 (jetons et planification par
workspace). Une ligne cron appartient désormais au workspace de son `ARC_WORKSPACE`. Sans
`--workspace`, `install.sh` vise la **racine du moteur** : la ligne de votre workspace est alors
vue comme celle d'un autre membre du foyer et conservée, et une seconde planification est ajoutée
pour la racine du moteur. La synchronisation tourne alors **deux fois**. Le piège est fréquent sur
une machine coach : `~/.config/ai-running-coach/install-args` peut être **vide** (une relance de
`./install.sh` sans option l'a mémorisé ainsi), et `/update-coach` rejoue ces options.

`scripts/migrate-sync-127.sh` fait la migration sans arrêter ni doubler la sync. À lancer **sur la
machine coach**, depuis une copie **hors du moteur** (le moteur est mis à jour pendant
l'exécution) :

```bash
cp ~/ai-running-coach/scripts/migrate-sync-127.sh ~/
~/migrate-sync-127.sh check                         # ne modifie rien (sauf git fetch), avant ou après la mise à jour
~/migrate-sync-127.sh migrate --fix-install-args    # sauvegarde, mise à jour, ligne cron renommée
~/migrate-sync-127.sh verify                        # après le prochain passage du watch (≤ 15 min)
```

| Étape | Ce qu'elle fait |
|---|---|
| `check` | Ligne cron unique, workspace mémorisé, moteur sur `main` sans modification locale, présence de #127 et de la cale dans `origin/main`, dossier de jetons Garmin résolu (`700`/`600`), `install-args`, fraîcheur du watch. Ne touche ni à la crontab, ni au moteur, ni au workspace. Lance seulement `git fetch origin` dans le moteur (appel réseau qui met à jour les références `origin/*`, jamais `main`) pour savoir si #127 est fusionné ; `check --no-fetch` l'évite. |
| `migrate` | Sauvegarde dans `~/.config/ai-running-coach/backup-migration-127-<date>/`, met la ligne cron en pause, attend la fin d'une sync en cours, `git merge --ff-only` du moteur, vérifie que les jetons résolus n'ont pas changé et que `watch.py --dry-run` répond, puis réécrit la ligne cron (seul le nom du script change). Refuse tant que `origin/main` ne contient pas #127. |
| `--fix-install-args` | Ajoute `--workspace <votre workspace> --daily-sync` aux options mémorisées, seulement si l'aperçu `install.sh --dry-run` montre une seule ligne cron, sur `watch.py`, pour votre workspace. L'aperçu complet est gardé dans la sauvegarde (`install-dry-run.txt`). |
| `verify` | Vérifie que le watch est passé depuis la migration, puis lance `coach_doctor` (`daily_sync_scheduled`, `garmin_token`, `garmin_token_perms`). |
| `rollback <sauvegarde>` | Remet la crontab, le commit du moteur, `install-args` et le workspace mémorisé. |

Toute erreur ou interruption de `migrate` avant la réécriture remet la crontab d'origine : elle
reste valable avant comme après la mise à jour, grâce à la cale. `migrate` ne relance **pas**
`./install.sh` en entier (agents, `.mcp.json`, chat Docker, Remote Control).

!!! warning "Options d'installation perdues"
    `--fix-install-args` ne reconstitue que `--workspace` et `--daily-sync`. Si `install-args`
    était vide, vos autres options d'origine (chat, Remote Control, IDE…) ne sont pas
    mémorisées : relisez `install-dry-run.txt` et complétez `install-args` avec
    [Retrouver ses options d'installation](#retrouver-ses-options-dinstallation) avant la
    prochaine `/update-coach`.

Le script ne couvre que le mode `watch`. Une planification à heures fixes
(`[sync].mode = "schedule"`) est refusée par `check` : mettez-la à jour avec
`./install.sh --workspace <votre workspace> --daily-sync`, en passant toujours `--workspace`.

## Serveurs MCP (`garmin-mcp`, `intervals-icu-mcp`)

`garmin-mcp` est épinglé à un commit précis (`GARMIN_MCP_REF` dans `install.sh`) : relancer
`./install.sh` (ou `/update-coach`) compare l'origine de l'outil installé au pin et le réinstalle
(`uv tool install --force`) s'il diffère — ce qui met aussi à jour ses dépendances transitives
(correctifs de sécurité). L'installation est ainsi alignée sur le commit revu par le projet, même
si un commit amont plus récent avait été installé à la main. Vos tokens Garmin sont conservés, et
`~/.garminconnect` est resserré en `700`/`600` (filet de sécurité, GHSA-wjhr-76vg-2hvc). Une origine
personnalisée n'est jamais écrasée. Quand le commit est déjà le bon, relancer `./install.sh` ne
re-résout pas les dépendances : pour les rafraîchir en gardant le commit épinglé, lancez

```bash
uv tool upgrade garmin-mcp
```

`intervals-icu-mcp` est épinglé à un commit précis (`INTERVALS_MCP_REF` dans
`install.sh`) : quand ce commit change dans le moteur, relancez
`./install.sh --source intervals` — il compare l'origine de l'outil installé
(`direct_url.json` de l'environnement `uv`) au pin et le réinstalle
(`uv tool install --force`) s'il diffère. Une origine personnalisée (chemin
local, autre fork) n'est jamais écrasée.

### Migration vers le fork `hhopke/intervals-icu-mcp` (#165)

Le projet utilisait `eddmann/intervals-icu-mcp@cb91d4a` ; il pointe désormais sur
le fork maintenu [`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp)
(v5.6.0). **Concerne uniquement `[data].source = "intervals"`** : avec la source
Garmin (défaut), rien ne change.

1. `git pull` dans le moteur, puis `./install.sh --source intervals` (ajoutez
   vos autres options habituelles, `--no-auth` si les identifiants existent déjà).
   L'ancien serveur est remplacé automatiquement ; **vos identifiants
   (`~/.config/ai-running-coach/intervals-icu-mcp/.env`) et le wrapper `run.sh`
   sont conservés** — mêmes noms de variables, même commande d'authentification.
   Équivalent manuel : `uv tool install --python 3.12 --force --with fitparse
   "git+https://github.com/hhopke/intervals-icu-mcp@92a630bfc4ffe7906c9bf8d2280c1ea41a561d66"`
   (ou `uv tool uninstall intervals-icu-mcp` puis la même commande sans `--force`).
2. **Ouvrez une nouvelle session de coaching** : une session reprise garde les
   outils MCP qu'elle avait au démarrage. Les outils du nouveau serveur portent le
   préfixe `icu_` (`icu_get_wellness_for_date` au lieu de `get_wellness_for_date`) ;
   le coach, les skills et la politique du chat parlent désormais ces noms.
3. Vérifiez : `python3 scripts/coach_doctor.py --check intervals_mcp_pin` — ✅ au
   commit épinglé, ⚠️ tant que l'ancien serveur est installé (le correctif est
   affiché).

Ce qui change pour vous : les séances poussées vers Intervals.icu sont
désormais **structurées** quand c'est possible (étapes lisibles par la montre) au
lieu d'un texte libre — voir [Configuration Intervals.icu](intervals-setup.md).
Les séances déjà poussées ne sont pas modifiées. **Cursor + intervals.icu, mise à jour
à la main** : relancez `./install.sh --source intervals` (la liste de refus de
`.cursor/cli.json` gagne `icu_update_athlete_notes` ; sans cela, le daily-sync refuse de
démarrer) — `/update-coach` s'en charge déjà. Retour arrière : `git reset`
du moteur à la version précédente, puis `uv tool install --force` du commit
`cb91d4a` de `eddmann/intervals-icu-mcp` (voir l'ancien `install.sh`).

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
