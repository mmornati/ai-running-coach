# Skill : Correspondance des sources de données

> **Description** : tables de correspondance des outils Garmin ↔ intervals.icu, Garmin ↔ Strava et Garmin ↔ COROS, et liste de ce qui n'a pas d'équivalent avec chaque source.

## Quand l'utiliser

- Obligatoire quand `[data].source` vaut `intervals`, `strava` ou `coros`, avant le premier appel d'outil de données.
- Avant d'appeler un outil `icu_*`, Strava ou `coros` alors que la source primaire est une autre (relais COROS, intervals.icu en secondaire).
- Inutile avec `[data].source = "garmin"` (défaut) sans relais COROS.

## Pourquoi ce skill existe

Ces tables étaient dans `AGENTS.md`, qui est envoyé au modèle avec **chaque** requête, quelle que soit la source de l'athlète. Les sortir dans un skill chargé à la demande réduit d'environ 25 % la taille du préfixe fixe de chaque requête (moins de jetons d'entrée, écritures de cache moins chères), sans changer aucune règle : le texte est recopié tel quel, et `AGENTS.md` garde un renvoi obligatoire.

Les clients sans skills natifs (Codex, Gemini CLI, Cursor) lisent le fichier par son chemin, comme le demande `AGENTS.md`.

## Fichier source

`skills/data-source-mapping/SKILL.md`
