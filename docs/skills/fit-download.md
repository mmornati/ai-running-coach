# 📥 Skill : Téléchargement FIT

> **Description** : Téléchargement de fichiers FIT Garmin (et leurs records GPS en JSON) en **bypassant le canal MCP**.

## Pourquoi ce skill existe

- Le MCP Garmin (`get_activity_fit_data`) **timeoute** sur les téléchargements FIT (payloads de plusieurs Mo)
- Le script `download_fit.py` utilise la lib `garminconnect` installée dans l'environnement `garmin-mcp` + les **tokens locaux** `~/.garminconnect` → **aucun mot de passe** nécessaire

## Quand l'utiliser

- Télécharger un **fichier FIT** d'une activité Garmin
- Récupérer les **records GPS** en JSON
- Analyser une activité en détail hors du canal MCP

## Fonctionnalités

- Téléchargement de fichiers FIT via la lib `garminconnect`
- Récupération des records GPS en JSON
- Utilisation des tokens locaux (pas de mot de passe)
- **Auto-relaunch** : le script se relance dans l'environnement garmin-mcp si les dépendances manquent

## Script

`skills/fit-download/scripts/download_fit.py` — nécessite `garminconnect` + `fitparse` (disponibles dans l'environnement garmin-mcp).

Avec `--json`, écrit aussi une copie **normalisée** au chemin canonique
`activities/fit/<garmin_activity_id>.json` (unités SI, mapping documenté dans
`scripts/arc_samples.py`) — c'est ce fichier que `scripts/arc_index.py` ingère dans la
table dérivée `activity_sample` (voir [Mode headless](../dashboard/headless.md)).
Donnée brute et jetable, jamais versionnée.

## Fichier source

`skills/fit-download/SKILL.md`
