# Contrat de données (`workspace-data-contract`)

Vos séances, vos nuits et vos plans restent des fichiers Markdown lisibles.
Mais chaque fichier écrit par un agent commence désormais par un **petit bloc de
données** : c'est lui que lisent le [tableau de bord](../dashboard/index.md) et la
comparaison de parcours, jamais la prose.

## À quoi ça ressemble

````markdown
# Séance du 2026-09-20 — Trail de Tournai

```arc
{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail",
 "distance_m": 12300, "duration_s": 5218, "elevation_gain_m": 480, "avg_hr_bpm": 148}
```

L'analyse du coach, en français, comme avant.
````

Le bloc est du JSON. Ses clés sont en anglais et ne changent jamais, quelle que
soit la langue de vos documents ; ses valeurs sont en unités SI (mètres,
secondes, bpm), même si vous avez choisi les unités impériales — la conversion
se fait à l'affichage.

## Pourquoi

Avant ce contrat, les chiffres se lisaient dans des tableaux et des titres
français. Passer `[language].documents` à `"en"` suffisait à faire disparaître
toutes vos séances de la comparaison de parcours, sans le moindre message. Un
bloc typé ne dépend ni de la langue, ni de l'ordre des colonnes, ni de la
formulation du modèle.

## Les types de fichiers

| Type | Fichier |
|---|---|
| `activity` | `activities/AAAA-MM-JJ_<type>.md` |
| `health` | `medical/AAAA-MM-JJ_health.md` — sommeil, HRV, FC de repos, readiness, **verdict du jour** |
| `weather` | `medical/AAAA-MM-JJ_meteo.md` |
| `week` | `planning/Semaine_AAAA-MM-JJ.md` — séances datées, lieu de la semaine |
| `nutrition` | `nutrition/AAAA-MM-JJ_nutrition.md` |
| `report` | `rapports/…` |
| `course_eval` | `planning/…_evaluation_parcours_<lieu>.md` |
| `race_plan` | plan de course dans `planning/` |

Votre profil (`planning/Runner_Profile.md`) et votre objectif
(`planning/active_objective.md`) n'ont **pas** de bloc : vous les éditez à la
main, et leurs puces suffisent. Gardez simplement les libellés du modèle.

## Vérifier un fichier

```bash
python3 scripts/arc_index.py --validate medical/2026-09-20_health.md
```

Les agents le font après chaque écriture. Le schéma complet, clé par clé, est
dans `skills/workspace-data-contract/SKILL.md`.

## Et les fichiers écrits avant ?

Ils restent lus, au mieux, et le tableau de bord les signale comme
incomplets. [`/arc-backfill`](arc-backfill.md) les met au contrat, par lots.
