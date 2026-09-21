# 🔁 Skill : Sync quotidienne (headless)

> **Description** : prompt d'orchestration versionné pour la synchronisation Garmin **sans surveillance** — lancé par le cron (`scripts/daily-sync.sh`), depuis le téléphone (`/garmin-daily-sync` dans une session Remote Control) ou depuis l'IDE.

## Quand l'utiliser

- Automatiquement, aux heures de `[sync].times` (voir [Le coach dans la poche](../mobile.md))
- À la main, pour forcer une synchronisation : `/garmin-daily-sync`

## Ce qu'il fait (et ne fait pas)

Il **n'ajoute aucune logique** : il délègue à l'agent `coach` et au skill
[`garmin-sync-efficiency`](garmin-sync-efficiency.md), en mode headless :

1. Ne pose jamais de question
2. Ne récupère que les dates dont le fichier MD manque (`[sync].lookback_days`, défaut 2)
3. Persiste `activities/` et `medical/` selon les conventions du workspace
4. Termine par un bloc ```` ```resume ```` de 5 lignes maximum, extrait mot pour mot par
   `scripts/daily-sync.sh` pour la notification push (ntfy)

## Fichier source

`skills/garmin-daily-sync/SKILL.md`
