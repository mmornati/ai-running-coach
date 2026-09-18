# 📈 Skill : Intervals.icu

> **Description** : Création, mise à jour et dépannage d'événements ou workouts Intervals.icu via les outils MCP Intervals.icu (`add_or_update_event`, `get_events`, `delete_event`).

## Quand l'utiliser

- Créer, mettre à jour ou dépanner des **événements Intervals.icu**
- **Uniquement si l'utilisateur le demande explicitement** — le calendrier Garmin est la destination primaire

## Contenu du skill

- **Piège description-vs-workout_doc** : comprendre la différence entre les deux champs
- **Préservation de `start_date`** : ne pas écraser la date de début lors des mises à jour
- **Vérification post-mise à jour** : confirmer que l'événement est correct
- **Patterns JSON testés** : payloads éprouvés pour les différents cas

## Principes clés

- Intervals.icu est **secondaire** — le calendrier Garmin est la destination PRIMAIRE
- Toujours **vérifier après la mise à jour** que l'événement est correct

## Fichier source

`skills/intervals-icu-best-practices/SKILL.md`
