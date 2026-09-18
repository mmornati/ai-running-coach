# 📅 Skill : Planification Garmin

> **Description** : Push de séances planifiées directement dans le calendrier Garmin Connect via leanproxy (serveur `garmin`, outils `schedule_workouts` / `schedule_week` / `upload_workout`).

## Quand l'utiliser

- Pousser des **séances planifiées** dans le calendrier Garmin Connect
- Planifier une **semaine d'entraînement** complète
- Téléverser une **séance individuelle** (workout)

## Contenu du skill

- **Schéma JSON exact** des DTO Garmin
- Tables de correspondance : `step`, `endCondition`, `targetType`, `sportType`
- **Idempotence** : éviter les doublons lors des re-push
- **Détail des séances de renforcement** : exercices, répétitions, poids, repos, boucles `RepeatGroupDTO`
- **Pattern verify-after-push** : vérifier que la séance est bien dans le calendrier après le push

## Principes clés

- Le **calendrier Garmin est la destination PRIMAIRE** de planification
- **Intervals.icu est secondaire** (uniquement si l'utilisateur le demande)
- Les séances de renforcement doivent inclure le **détail complet** (boucles, exercices, séries, poids, repos)

## Fichier source

`skills/garmin-workout-scheduling/SKILL.md`
