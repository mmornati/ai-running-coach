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

1. `git fetch`, puis **avance rapide** de `main` (`git merge --ff-only` : jamais de
   fusion, jamais de force) ;
2. `./install.sh` relancé avec **les options de votre dernière installation**,
   mémorisées par `install.sh` dans `~/.config/ai-running-coach/install-args` ;
3. `python3 scripts/coach_doctor.py` pour vérifier le résultat.

Ouvrez ensuite une nouvelle session de votre assistant et relancez le tableau de bord.

## Quand la mise à jour refuse

| Situation | Que faire |
|---|---|
| Application macOS (moteur sans git) | La mise à jour passe par l'application |
| Image Docker du tableau de bord | `git pull` dans le dépôt source, puis `docker compose up -d --build` |
| Options d'installation inconnues | Installation antérieure à leur mémorisation : relancez une fois `./install.sh` avec vos options ([Retrouver ses options](../update.md#retrouver-ses-options-dinstallation)) |
| Moteur hors de `main`, modifications ou commits locaux | Rien n'est forcé : mettez à jour à la main ([Mettre à jour](../update.md)) |

Jamais en headless : la synchronisation automatique ne fait que signaler la release.
