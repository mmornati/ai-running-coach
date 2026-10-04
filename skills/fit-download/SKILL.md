---
name: fit-download
description: Use to download FIT files and their GPS records (JSON) by bypassing the MCP channel, which times out on FIT payloads — from Garmin Connect or from Intervals.icu, following [data].source. Load whenever a session must be analyzed at sub-kilometer precision — course profile, climbs, HR×elevation drift, stride/sprint/interval analysis, course comparison, or the FIT-derived KPIs (zones, GAP, decoupling, VAM, descent, durability, energy model). Runs scripts/download_fit.py — garminconnect + local ~/.garminconnect tokens for Garmin, the Intervals.icu REST API + the MCP server's API key for Intervals.icu.
---

# Skill: fit-download

Télécharge les fichiers FIT (et leurs records GPS en JSON) en **bypassant le canal MCP**, depuis la source de `[data].source` :

| Source | Identifiant | Accès |
|---|---|---|
| `garmin` (défaut) | `garmin_activity_id` (entier) | lib `garminconnect` de l'environnement `garmin-mcp` + **tokens locaux** `~/.garminconnect` — aucun mot de passe |
| `intervals` | `intervals_activity_id` (`i<chiffres>`) | API REST Intervals.icu (stdlib) + la **clé API du serveur MCP** (`~/.config/ai-running-coach/intervals-icu-mcp/.env`) — aucune nouvelle configuration ; `fitparse` de l'environnement `intervals-icu-mcp` pour `--json` |

| `strava` (#164) | `strava_activity_id` (`s<chiffres>`) | API REST Strava `GET /activities/<id>/streams` (stdlib) + les **jetons du serveur MCP communautaire** (`~/.config/strava-mcp/config.json`, rafraîchis et réécrits atomiquement, jamais affichés). **Pas de `.fit`** : les flux par seconde sont normalisés directement en `activities/fit/s<chiffres>.json` (même format, mêmes KPI), avec ou sans `--json` ; pas de `fitparse` requis |

## Pourquoi ce skill

- Le MCP Garmin (`get_activity_fit_data`) **timeoute** sur les downloads FIT (payload de plusieurs Mo) — ne pas insister dessus pour un download. Côté Intervals.icu, le FIT passerait en base64 dans le contexte : même raison de passer par le script.
- **Intervals.icu — activités importées depuis Strava** : l'API Strava interdit leur redistribution, aucun FIT n'existe. Le script les signale `INDISPONIBLE` (avec la raison) et continue : la séance reste valide, simplement sans KPI fins — ne jamais inventer de valeur FIT pour elle.

- **Strava (#164)** : les données restent dans l'espace de travail privé de l'athlète (`activities/fit/` gitignoré) — accord API Strava : affichage réservé à l'utilisateur concerné, suppression à la fin de l'accord. Deux requêtes par séance (détail pour le sport, puis flux) ; limites d'API (par défaut, pour les lectures : 100 requêtes / 15 min, 1000 / jour — partagées avec le serveur MCP, qui utilise la même application) : un `HTTP 429` est dit, pas contourné. Une activité saisie à la main n'a pas de flux (`INDISPONIBLE`). Pas de dynamique de course ni de HRR chez Strava : colonnes vides, jamais devinées.

## Quand l'utiliser

- **Toute analyse par profil FIT** : montées, dérive FC×élévation, LD/strides/sprints, comparaison de courses (`course-comparison`), analyse de fractions (`session-parts-analyzer`).
- À chaque fois qu'une activité doit être analysée à granularité sub-km (records par seconde) et que le MCP ne fournit pas les données.

## Workflow

1. **Trouver les identifiants** : dans le bloc ```` ```arc ```` des fichiers MD d'activités (`garmin_activity_id`, `intervals_activity_id` ou `strava_activity_id`), ou via le MCP (`get_activities_by_date` / `icu_get_recent_activities` (intervals.icu)).
2. **Télécharger** :
   ```bash
   python3 skills/fit-download/scripts/download_fit.py 24070286912 --json --output-dir /tmp/fits/
   python3 skills/fit-download/scripts/download_fit.py i123456789 --json   # Intervals.icu
   # --source garmin|intervals|strava → force la source (défaut : [data].source)
   # --json   → écrit aussi <id>.records.json (records GPS/HR/power/cadence, brut)
   #            + <output-dir>/fit/<id>.json (copie normalisée #42, voir scripts/arc_samples.py)
   # --from-dir activities/ → scanne tous les activity_id des MD
   # --overwrite → re-télécharge même si présent
   ```
   La sortie par défaut est `activities/` (workspace) si `--output-dir` omis — utiliser `/tmp/`
   quand le FIT n'a pas vocation à rester. **Pour que `scripts/arc_index.py` ingère les
   échantillons** (table `activity_sample`), le téléchargement doit se faire SANS
   `--output-dir` (ou avec `--output-dir <workspace>/activities`) : la copie normalisée
   canonique est `activities/fit/<garmin_activity_id | intervals_activity_id | strava_activity_id>.json`, jetable et jamais versionnée
   (son propre `.gitignore` est créé automatiquement à la première écriture).
3. **Analyser** le FIT avec `session-parts-analyzer` (`analyze_session_parts.py --fit ... --part climb|stride|...`) ou `course-comparison` (`compare_course.py --fit-dir`).
4. **Persister** l'analyse (dérive, profil) dans le MD de l'activité dans la langue des documents (`config/workspace.toml` → `[language].documents`, défaut FRANÇAIS) — ne jamais dump le JSON brut en chat.

## Rattraper l'historique pour la dépense énergétique modèle

Le [modèle de dépense énergétique](../../docs/energie.md) (`scripts/arc_energy.py`,
table dérivée `activity_energy`) se calcule automatiquement pour toute séance
dont le FIT est déjà ingéré (`activities/fit/<id>.json`) — il
ne manque donc **que** pour les séances plus anciennes dont le FIT n'a jamais
été téléchargé. Procédure détaillée : [docs/skills/fit-download.md — Rattraper
l'historique](../../docs/skills/fit-download.md#rattraper-lhistorique-pour-la-depense-energetique-modele).

En bref, pour un agent qui exécute ce rattrapage :

```bash
python3 skills/fit-download/scripts/download_fit.py --from-dir activities/ --json
python3 scripts/arc_index.py energy  # réindexe (n'importe quelle sous-commande le fait)
```

`--json` est indispensable (sans lui, seul le `.fit` brut est écrit, jamais la
copie normalisée qu'`arc_index.py` ingère) ; une séance déjà rattrapée (sa
copie normalisée `activities/fit/<id>.json` existe déjà) est sautée
automatiquement, même avec `--json` — relancer cette commande sur un
historique déjà (partiellement) rattrapé ne re-télécharge donc que ce qui
manque encore, jamais tout l'historique à chaque fois.

## Détails techniques

- `download_activity(activity_id, dl_fmt=ORIGINAL)` → gère le zip auto (dézippe à la volée).
- `_write_records_json` extrait les messages `record` → champs `distance`, `enhanced_altitude`/`altitude`, `heart_rate`, `speed`, `cadence`, `power`, **`position_lat`/`position_long`** (position GPS, quand le FIT en porte une — entiers en semi-cercles, pas encore des degrés à ce stade).
- **Champ altitude** : préférer `enhanced_altitude` quand présent (plus précis que `altitude`).
- `_write_canonical_samples` (#42) normalise ensuite ces mêmes records (sans reparser le FIT) via `normalise_records` de `scripts/arc_samples.py` : mapping `heart_rate → hr_bpm`, `distance → distance_m`, `enhanced_altitude/altitude → altitude_m`, `enhanced_speed/speed → speed_ms` (déjà en m/s), `timestamp → t_s` relatif au départ, **`position_lat`/`position_long` → `lat_deg`/`lon_deg`** (degrés décimaux, semi-cercles convertis — #49, identité de montée entre séances, `scripts/arc_climb_match.py` ; `None` si absents ou si le FIT ne porte aucun GPS), et **doublement de la cadence** (`cadence` FIT course à pied compte un seul pied/min, `cadence_spm` en sortie compte les deux) — voir la docstring du module pour le détail et les sources.
- Auto-relance avec le python de `garmin-mcp` si `garminconnect` absent de l'interpréteur courant (Garmin), ou avec celui de `intervals-icu-mcp` si `fitparse` est absent (Intervals.icu, `--json` seulement — le téléchargement lui-même est stdlib). Une seule relance, jamais en boucle.
- Intervals.icu : `GET /api/v1/activity/<id>` (détection d'un import Strava) puis `GET /api/v1/activity/<id>/fit-file` (gzip décompressé à la volée), authentification Basic `API_KEY:<clé>` comme `intervals-icu-mcp`. `$INTERVALS_ICU_API_KEY` prime sur le `.env`. Codes de sortie : `INDISPONIBLE` (import Strava, 404 = saisie manuelle sans fichier) n'est jamais une panne ; 401/403 = clé API refusée.

## Files

| Path | Role |
|:-----|:-----|
| `SKILL.md` | Ce fichier |
| `scripts/download_fit.py` | Téléchargeur FIT + extracteur records (CLI) + copie normalisée `activities/fit/<id>.json` (#42) |

Base directory: skills/fit-download