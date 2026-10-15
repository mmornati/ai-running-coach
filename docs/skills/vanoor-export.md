# Skill : Export Vanoor

> **Description** : écrit les séances de course de la semaine et le plan de course au format de l'app [Vanoor](https://vanoor.app) (Apple Watch), pour les importer dans l'app iPhone qui les envoie à la montre.

## Pourquoi ce skill existe

Avec une montre Garmin, le coach pousse les séances au calendrier. Avec une Apple Watch, il n'y a pas de calendrier à alimenter, et l'app Exercice d'Apple ne fait ni pacing par section ni suivi de GPX. Vanoor le fait — séances structurées avec cibles d'allure ou de FC, plan d'allure de course, parcours GPX hors ligne — et importe des séances depuis un **fichier JSON au format publié** (`vanoor.workout/1`). Pas de serveur ni d'API : le coach écrit le fichier, vous l'importez.

## Activation

Opt-in strict, désactivé par défaut :

```toml
# config/workspace.user.toml
[vanoor]
export = "on"
output_dir = "~/iCloudDrive/Vanoor"   # vide = exports/vanoor/ dans le workspace
```

Avec un `output_dir` dans iCloud Drive, le fichier apparaît directement dans l'app Fichiers de l'iPhone. Détails : [Configuration](../configuration.md#lexport-vers-vanoor-apple-watch-vanoor).

## Ce qui est exporté

**Les séances de la semaine** (`semaine-<lundi>.vanoor`), à chaque validation de semaine par le coach :

- seulement les séances `running` / `trail` encore planifiées ;
- une étape par partie de la séance (échauffement, blocs, récupérations), à la durée ou à la distance ;
- **vos** cibles : plage FC en bpm de votre profil, allure seulement quand la séance en donne une (mêmes cibles que pour Garmin, `arc_workout_targets.py`) ; jamais de zone générique ni de cible inventée ;
- les efforts au ressenti (lignes droites, marche active en côte) sans cible, consigne dans le libellé.

**Le plan de course** (`course-<date>-<nom>.vanoor`), écrit par le stratège de course :

- une séance par scénario (prudent, réaliste, ambitieux) ;
- une étape par segment du plan, à sa distance, avec l'allure du scénario (marge ±30 s/km en montée, ±20 s/km ailleurs — approximation du projet) ;
- un rappel « Ravito » au kilomètre de chaque ravitaillement du plan.

Attachez ensuite le GPX de la course à la séance dans Vanoor (onglet *Parcours*) pour avoir le tracé hors ligne.

## Importer dans Vanoor

1. Le fichier est dans `output_dir` (ou `exports/vanoor/` du workspace).
2. Sur l'iPhone : Vanoor → *Mes séances* → **+** → *Importer des séances* → choisir le fichier.
3. Les séances apparaissent dans un dossier (« Semaine du 12/10 ») et passent sur la montre.

## Limites à connaître

- **Pas de date** : Vanoor range les séances par dossier, sans calendrier.
- **Réimport** : une semaine modifiée est réécrite en entier ; supprimez l'ancienne version dans l'app (le format n'a pas d'identifiant de séance).
- **Retour des séances** : Vanoor enregistre dans Apple Santé. Faites-le remonter vers intervals.icu par Intervals.icu Companion ou HealthFit pour que le coach ait le FIT complet (une activité arrivée par Strava n'en a pas). La structure (étapes) ne revient pas : un seul tour, les étapes se retrouvent à la vitesse.
- **Distance GPS** : en trail, les étapes à la distance peuvent se décaler de quelques pourcents par rapport au parcours.
- **Pas d'allure ajustée à la pente** dans Vanoor : en montée raide, cible FC ou ressenti.
- Les distances et durées estimées que l'app affiche pour une étape sans cible d'allure sont calculées par Vanoor, pas par le projet.

## Script

```bash
python3 scripts/arc_vanoor.py week --week planning/Semaine_2026-10-12.md < structure.json   # séances
python3 scripts/arc_vanoor.py race --plan planning/2026-10-20_plan_course_feodieres.md      # plan de course
python3 scripts/arc_vanoor.py validate exports/vanoor/semaine-2026-10-12.vanoor             # vérification
```

`--dry-run` affiche le fichier sans l'écrire. Tant que `[vanoor].export` n'est pas `on`, le script n'écrit rien (code de sortie 2). Bibliothèque standard uniquement.
