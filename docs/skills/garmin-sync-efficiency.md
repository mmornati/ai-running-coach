# ⚡ Skill : Synchronisation Garmin

> **Description** : Récupération efficace des données Garmin (activités, sommeil, HRV, training readiness, métriques de santé) via le serveur MCP garmin à travers leanproxy.

## Quand l'utiliser

- Récupérer des **données Garmin** (activités, sommeil, HRV, training readiness, métriques de santé)
- Avant toute interaction avec le serveur MCP garmin

## Pourquoi ce skill existe

Le skill prévient la **saturation du contexte** :

- **Récupération ciblée** : ne récupérer que les dates spécifiques nécessaires
- **Persistance immédiate** : sauvegarder en Markdown dès la récupération
- **Jamais de JSON brut** : ne jamais déverser le JSON brut dans la conversation

## Principes clés

1. **Récupérer uniquement ce qui est nécessaire** — dates spécifiques, pas des plages entières
2. **Persister immédiatement** — chaque récupération est sauvegardée dans `activities/` ou `medical/`
3. **Synthétiser** — présenter des résumés, pas des données brutes

## Fichier source

`skills/garmin-sync-efficiency/SKILL.md`
