# Skill : Planification Garmin

> **Description** : Push de séances planifiées directement dans le calendrier Garmin Connect via le serveur MCP `garmin` (outils `schedule_workouts` / `schedule_week` / `upload_workout`).

## Quand l'utiliser

- Pousser des **séances planifiées** dans le calendrier Garmin Connect
- Planifier une **semaine d'entraînement** complète
- Téléverser une **séance individuelle** (workout)

## Contenu du skill

- **Schéma JSON exact** des DTO Garmin
- Tables de correspondance : `step`, `endCondition`, `targetType`, `sportType`
- **Idempotence** : éviter les doublons lors des re-push
- **Détail des séances de renforcement** : exercices, répétitions, poids, repos, boucles `RepeatGroupDTO` ; les exercices et leur correspondance Garmin viennent de la bibliothèque `arc_index.py strength --garmin-json` (#191, voir [Renforcement et mobilité](../strength.md)) — couples (`category`, `exercise`) vérifiés dans le catalogue Garmin, jamais devinés
- **Pattern verify-after-push** : vérifier que la séance est bien dans le calendrier après le push
- **Cibles personnelles (#60)** : zones FC, allure GAP plate, D+ de côte

## Principes clés

- Le **calendrier Garmin est la destination PRIMAIRE** de planification
- **Intervals.icu est secondaire** (uniquement si l'utilisateur le demande)
- Les séances de renforcement doivent inclure le **détail complet** (boucles, exercices, séries, poids, repos)

## Cibles personnelles (`scripts/arc_workout_targets.py`, #60)

Avant de construire le `workout_data` d'une séance, l'agent `coach` calcule
ses cibles PERSONNELLES — jamais une borne générique — avec :

```bash
python3 scripts/arc_workout_targets.py targets --session planning/Semaine.md#2026-09-30
```

| Cible | Champ | Source | Unité DTO |
|---|---|---|---|
| Zone FC | `hr_target.bounds_bpm` | Zones de l'athlète (#43), mappées depuis l'intensité planifiée : `recovery`→Z1, `endurance`→Z2, `tempo`→Z3, `threshold`→Z4, `vo2max`→Z5 | bpm, entier (`targetValueOne`/`targetValueTwo`) |
| Allure plate | `pace_target.speed_low_ms`/`speed_high_ms` | Référence plate GAP personnelle/générique (#44/#58), UNIQUEMENT pour `recovery`/`endurance` | **mètres/seconde** (`targetValueOne`/`targetValueTwo`, `pace.zone`) |
| Vitesse critique (#169) | `cs_target.speed_low_ms`/`speed_high_ms` | % de la **vitesse critique** (GAP, `arc_cs.py`), pour `tempo`/`threshold`/`vo2max`, UNIQUEMENT si l'ajustement CS/D′ est valide ; complète la zone FC, ne la remplace jamais | **mètres/seconde** (`pace.zone`) |
| D+ de côte | `hill_repeats.per_rep.elevation_gain_m` | Vitesse personnelle/générique prédite à la pente demandée (#58) × durée du répétitif | mètres (informatif, dans la description du pas — Garmin n'a pas de champ D+) |

**Cibles en % de la vitesse critique (#169).** Pour `tempo` (88-95 %), `threshold`
(95-100 %) et `vo2max` (102-110 %), `cs_target` donne une plage de vitesse GAP
(« équivalent plat ») ; pour `vo2max`, `d_prime_budget_s` borne la durée cumulée
tenable au-dessus de la vitesse critique (D′ / (v − CS)). Ces pourcentages sont
une **approximation du projet**. Sans ajustement valide (au moins 2 séances,
3 efforts de 3 à 20 min, R² ≥ 0,95), `speed_low_ms` vaut `null` et `reason_code`
dit pourquoi : le coach garde la seule zone FC, jamais une CS supposée. Une
divergence de plus de 5 % avec le seuil lactique Garmin (`--lt-speed-ms`) est
signalée avec les deux valeurs, jamais arbitrée. Voir
[Vitesse critique](../vitesse-critique.md).

Une date qui identifie plusieurs séances du même fichier exige un
qualifiant (`#AAAA-MM-JJ@index` ou `#AAAA-MM-JJ:titre`) — jamais « la
première » silencieusement. Un répétitif de côte planifié dans une vraie
semaine n'a pas de clé `structure` (absente du contrat `arc`) : le titre de
la séance est analysé automatiquement (`--structure-text` en repli explicite).

Chaque cible non calculable (`bounds_bpm`/`speed_low_ms`/`elevation_gain_m` à
`null`) rend `reason`/`reason_code` explicite (profil sans zones FC, pente
sans modèle, intensité sans mise à l'échelle d'allure validée) : l'agent
retire alors la cible correspondante du DTO plutôt que d'en inventer une —
un `reason_code` comme `"extrapolated"` SANS valeur `null` reste, lui,
purement informatif (la valeur est utilisable). Le D+ de côte est calculé à
l'allure d'ENDURANCE (`hill_repeats.basis: "endurance_pace_lower_bound"`) :
c'est une borne basse plausible, pas une prévision centrée — à formuler
« ≥ X m D+ ». Voir `skills/garmin-workout-scheduling/SKILL.md`, section
« Personal targets », pour le détail complet (mapping, provenance,
conversions d'unités, D+ attendu vs mesuré).

## Cibles ajustées à la chaleur (#171)

Un jour chaud (> 25 °C) ou 🔴, ajoutez `--heat` à la commande ci-dessus : le résultat gagne `heat_adjustment`, `pace_target.adjusted` (m/s, déjà divisé par le facteur de chaleur) et `trace`. La séance poussée reflète ces cibles : le pas `pace.zone` utilise `pace_target.adjusted` (allure ralentie, durée conservée ; pour une cible en % de la vitesse critique, `cs_target.adjusted`, même facteur — le budget D′ n'est pas recalculé), la cible FC reste **inchangée**, et la note de chaleur (`step_note`, ex. « chaleur 27 °C : allure × 1.1, FC inchangée ») est ajoutée à la description du pas. Si l'action est `reschedule_or_lighten` / `reschedule_or_indoor` (🔴), la séance d'origine n'est pas poussée : l'alternative est proposée puis poussée après confirmation de l'athlète. Avec `prefer_cool_slot`, si l'athlète choisit le créneau frais, la commande est relancée avec `--slot` et c'est cette sortie qui est poussée. Côté intervals.icu, la ligne « Cible allure » du texte reprend l'allure ajustée. La trace `heat_adjustment` est recopiée dans la séance du bloc `arc` de la semaine.

## Fichier source

`skills/garmin-workout-scheduling/SKILL.md`
