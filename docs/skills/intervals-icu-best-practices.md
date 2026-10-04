# Skill : Intervals.icu

> **Description** : Création, mise à jour et dépannage d'événements Intervals.icu via les outils MCP réels du serveur retenu par le projet (`icu_create_event`, `icu_update_event`, `icu_delete_event`, `icu_bulk_create_events` — [`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp) depuis #165, voir [Configuration Intervals.icu](../intervals-setup.md)).

## Quand l'utiliser

- Créer, mettre à jour ou dépanner des **événements Intervals.icu**
- **Primaire** si `[data].source = "intervals"` (#68) — voir [Configuration Intervals.icu](../intervals-setup.md)
- **Secondaire sinon** (défaut) — uniquement si l'utilisateur le demande explicitement, le calendrier Garmin restant la destination primaire

## Contenu du skill

- **Préfixe `icu_`** : tous les outils du serveur ; sans préfixe = ancien serveur, à mettre à jour (`./install.sh --source intervals`, `docs/update.md`)
- **Séances structurées (#165)** : pas de paramètre `workout_doc`, mais la `description` d'un événement `WORKOUT` écrite dans la syntaxe native d'Intervals.icu est analysée en étapes (cibles FC/zone de `arc_workout_targets.py`, répétitions) ; l'écho `workout_parsed`/`workout_steps` de la réponse d'écriture dit si ça a marché, **repli texte libre** sinon. Plage d'allure absolue : hors syntaxe documentée (nom de l'événement)
- **Pas d'upsert** : `icu_update_event` exige un `event_id` déjà existant ; vérifier `icu_get_calendar_events` avant chaque création pour éviter les doublons
- **Vérification post-push** : l'écho d'analyse, puis `icu_get_event` (id/date/name/category/description/type/tags/metrics — jamais de structure de séance)
- **Bulk** : mêmes noms de champs que `icu_create_event` (`event_type`, `duration_seconds`…), les noms bruts de l'API sont refusés
- **Suppression** : mode `safe` du serveur = seulement les événements datés de demain ou plus tard
- **Préservation de `start_date`** : ne pas écraser la date de début lors des mises à jour
- **Enveloppe de réponse** : `{"data": {...}, "metadata": {...}}` pour chaque outil (`fetched_at`/`query_type` seulement en mode debug du serveur)

## Principes clés

- Intervals.icu est **primaire** si `[data].source = "intervals"`, **secondaire** sinon (le calendrier Garmin reste alors la destination PRIMAIRE)
- Toujours **vérifier après la mise à jour**, sur les seuls champs réellement renvoyés

## Fichier source

`skills/intervals-icu-best-practices/SKILL.md`
