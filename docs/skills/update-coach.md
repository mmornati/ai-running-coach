# Mettre à jour (`/update-coach`)

`/update-coach` met le moteur à jour vers la dernière version, sans toucher à vos
données. Il vérifie la release disponible, résume ses nouveautés, vous demande un
« oui », puis lance `scripts/update-coach.sh`.

## Comment on sait qu'une version est sortie

Une seule vérification (`scripts/arc_update_check.py`) compare votre moteur à la
dernière release GitHub, **au plus une fois par jour** (résultat gardé dans
`~/.cache/ai-running-coach/update-check.json`, délai de 3 s, silence total en cas
d'échec). Elle est signalée à trois endroits :

| Où | Comment |
|---|---|
| Tableau de bord | Une pastille « v1.2.0 disponible » dans l'en-tête, qui ouvre les notes de version |
| Claude Code | Au démarrage d'une nouvelle session (hook `SessionStart` posé par `install.sh`), le coach le mentionne une fois et propose `/update-coach` |
| Notification du daily-sync | Une notification dédiée, **une seule fois par release** |

Seule une release **plus récente** que votre version compte : un moteur sur `main`
après la v1.1.0 (`v1.1.0-24-gaa77fc7`) n'est pas alerté pour la v1.1.0.

Pour couper la vérification (aucun appel réseau, aucune mention) :

```toml
# config/workspace.user.toml
[update]
check = false
```

## Ce que fait la mise à jour

```bash
scripts/update-coach.sh --check   # ce qui va se passer, sans rien modifier
scripts/update-coach.sh           # idem, puis confirmation et mise à jour
```

1. `git fetch`, puis **avance rapide** de `main` jusqu'à la **dernière release publiée**
   (tag `vX.Y.Z`, jamais les commits non publiés ; `git merge --ff-only` : jamais de
   fusion, jamais de force) ;
2. `./install.sh` relancé avec **les options de votre dernière installation**,
   mémorisées par `install.sh` dans `~/.config/ai-running-coach/install-args` (chemins
   rendus absolus). Sans terminal (depuis l'assistant), l'authentification est sautée
   (`--no-auth`) : `coach_doctor` dit si des jetons sont à renouveler ;
3. `python3 scripts/coach_doctor.py` pour vérifier le résultat ;
4. si votre tableau de bord ou votre chat tournent dans **Docker** et que leur image se
   construit depuis ce dépôt (conteneur `docker compose` en cours dont `build.context` est le
   moteur ou un de ses dossiers : celui de `./install.sh --dashboard-docker`,
   `deploy/dashboard`, `deploy/chat`, ou votre propre compose), `scripts/update-docker.sh`
   les reconstruit (`docker compose build --pull`), les relance et attend qu'ils soient
   « healthy ». Chaque image porte la révision git du dépôt : si le moteur est déjà à jour
   mais qu'un conteneur tourne une révision plus ancienne, il est reconstruit aussi. Sans
   Docker, ou sans conteneur de ce type, rien ne se passe. Un conteneur lancé à la main
   avec `docker run` n'est pas reconnu : reconstruisez-le vous-même.

Ouvrez ensuite une nouvelle session de votre assistant, et relancez le tableau de bord
s'il ne tourne pas dans Docker (`scripts/dashboard.sh`).

## Quand la mise à jour refuse

| Situation | Que faire |
|---|---|
| Application macOS (moteur sans git) | La mise à jour passe par l'application |
| Image Docker du tableau de bord | `git pull` dans le dépôt source, puis `scripts/update-docker.sh` |
| Options d'installation inconnues | Installation antérieure à leur mémorisation : relancez une fois `./install.sh` avec vos options ([Retrouver ses options](../update.md#retrouver-ses-options-dinstallation)) |
| Moteur hors de `main`, modifications ou commits locaux | Rien n'est forcé : mettez à jour à la main ([Mettre à jour](../update.md)) |

Jamais en headless : la synchronisation automatique ne fait que signaler la release.
