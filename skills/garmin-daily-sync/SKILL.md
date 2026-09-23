---
name: garmin-daily-sync
description: Use for the unattended (headless/cron) Garmin synchronisation — invoked as /garmin-daily-sync by scripts/daily-sync.sh, from the phone (Remote Control) or from the IDE. Orchestrates the coach agent + garmin-sync-efficiency to persist the last days of activities/sleep/HRV/readiness as Markdown, then emits a short ```resume``` block for the notification. Never asks questions.
---

# Garmin Daily Sync — Skill (orchestration headless)

Ce skill **n'ajoute aucune logique de synchronisation** : c'est le prompt versionné que le
cron (`scripts/daily-sync.sh`), le téléphone (`/garmin-daily-sync` dans une session
Remote Control) et l'IDE partagent. Il délègue tout à l'agent `coach` et au skill
`garmin-sync-efficiency`.

## Contexte d'exécution

- **Mode sans surveillance** : personne ne lit la conversation en direct. Ne JAMAIS poser de
  question (`question`, `AskUserQuestion`) ni attendre une validation. En cas de doute,
  choisir l'option conservatrice (ne rien écrire) et le signaler dans le résumé.
- **Configuration** : lire `config/workspace.toml` puis `config/workspace.user.toml`
  (ses valeurs priment) — `[language].documents` (langue des MD), `[sync].lookback_days`
  (défaut : 2), `[health].morning_check` (voir ci-dessous).
- **Pas de contrôle de premier démarrage** : le coach propose `/coach-setup` quand aucune
  configuration n'existe. **Ici, ne jamais le proposer** : personne ne peut répondre, et la
  proposition finirait dans la notification push. Travailler avec les défauts et le signaler
  en une ligne du résumé si la configuration manque.
- **Bilan matinal** : respecter `[health].morning_check`. À `off`, ne récupérer ni HRV, ni FC
  de repos, ni readiness — les fichiers correspondants ne sont alors pas attendus dans
  `medical/` et leur absence n'est pas un manque.
- **Idempotence** : ne récupérer que les dates dont le fichier MD manque dans `activities/`
  ou `medical/` (règle 1 de `garmin-sync-efficiency`). Une date déjà persistée n'est jamais
  re-synchronisée.

## Déroulé

1. Déléguer à l'agent **`coach`** (outil `task`, prompt en anglais + « Respond in <langue des
   documents> ») la tâche suivante :
   > Load the `garmin-sync-efficiency` skill. For each of the last `lookback_days` days
   > (today included), check whether `activities/YYYY-MM-DD_<type>.md` and
   > `medical/YYYY-MM-DD_health.md` exist. For missing dates only, fetch from the `garmin` MCP
   > server: activities (with splits and `recovery_hr_bpm`), sleep, HRV, training readiness,
   > resting HR / body battery. Persist each file immediately using the workspace conventions
   > (`AGENTS.md`: file names; load the `workspace-data-contract` skill and open every file
   > with its ```arc JSON block — `kind: activity` with `garmin_activity_id`, `location` and
   > `splits`, `kind: health` with `morning_check` set to the configured mode; document
   > language from `config/workspace.toml` for the prose below the block). Validate each file
   > with `python3 scripts/arc_index.py --validate <file>` and fix what it reports. Never dump
   > raw JSON into the conversation. Do not ask questions. Do not push anything
   > to the Garmin calendar. Reply with: the list of files created, and a 5-line maximum
   > summary (new activities: type/distance/D+/HR avg/HRR; sleep score; HRV status vs
   > baseline; readiness score; any alert such as low HRV, poor sleep, HRR missing).
2. Réindexer le workspace pour le tableau de bord : `python3 scripts/arc_index.py`. La base
   est dérivée ; un échec ici ne bloque rien, mais se signale en une ligne `Alerte :` du
   résumé. Un fichier resté `NON CONFORME` à la validation se signale de la même façon
   (`Alerte : 1 fichier hors contrat — medical/2026-09-20_health.md`).
3. Si l'agent `coach` échoue (MCP indisponible, tokens Garmin expirés…), ne rien inventer :
   le résumé doit contenir `ERREUR : <cause>` (ex. « tokens Garmin expirés — relancer
   `uv run garmin-mcp-auth` »).

## Sortie OBLIGATOIRE (dernier élément de la réponse)

Terminer la réponse par un bloc de code clôturé avec le langage `resume`, **5 lignes maximum**,
dans la langue des documents, sans Markdown à l'intérieur. C'est ce bloc que
`scripts/daily-sync.sh` extrait mot pour mot pour la notification push.

````
```resume
Séances : 1 nouvelle — trail 12,3 km / 480 m D+ / FC moy 148 / HRR 28 bpm (2026-09-20)
Sommeil : 7 h 42, score 81
HRV : 62 ms — équilibré (baseline 58-66)
Readiness : 74
Alerte : aucune
```
````

Si aucune date ne manquait : `À jour — aucune nouvelle donnée Garmin (dernière séance : YYYY-MM-DD)`.
Si une étape a échoué : première ligne `ERREUR : <cause courte>`.
