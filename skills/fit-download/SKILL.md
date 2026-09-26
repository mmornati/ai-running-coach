---
name: fit-download
description: Use to download Garmin FIT files and their GPS records (JSON) by bypassing the MCP channel, which times out on FIT payloads. Load whenever a session must be analyzed at sub-kilometer precision — course profile, climbs, HR×elevation drift, stride/sprint/interval analysis, course comparison. Runs scripts/download_fit.py with the garminconnect library and the local ~/.garminconnect tokens.
---

# Skill: fit-download

Télécharge les fichiers FIT Garmin (et leurs records GPS en JSON) en **bypassant le canal MCP**.

## Pourquoi ce skill

- Le MCP Garmin (`get_activity_fit_data`) **timeoute** sur les downloads FIT (payload de plusieurs Mo) — ne pas insister dessus pour un download.
- Le script `download_fit.py` utilise la lib `garminconnect` installée dans l'environnement `garmin-mcp` + les **tokens locaux** `~/.garminconnect` → **aucun mot de passe** nécessaire.

## Quand l'utiliser

- **Toute analyse par profil FIT** : montées, dérive FC×élévation, LD/strides/sprints, comparaison de courses (`course-comparison`), analyse de fractions (`session-parts-analyzer`).
- À chaque fois qu'une activité doit être analysée à granularité sub-km (records par seconde) et que le MCP ne fournit pas les données.

## Workflow

1. **Trouver les activity_id** : dans les fichiers MD d'activités (`activity_id: \d+`), ou via `get_activities_by_date` (MCP).
2. **Télécharger** :
   ```bash
   python3 skills/fit-download/scripts/download_fit.py 24070286912 --json --output-dir /tmp/fits/
   # --json   → écrit aussi <id>.records.json (records GPS/HR/power/cadence, brut)
   #            + <output-dir>/fit/<id>.json (copie normalisée #42, voir scripts/arc_samples.py)
   # --from-dir activities/ → scanne tous les activity_id des MD
   # --overwrite → re-télécharge même si présent
   ```
   La sortie par défaut est `activities/` (workspace) si `--output-dir` omis — utiliser `/tmp/`
   quand le FIT n'a pas vocation à rester. **Pour que `scripts/arc_index.py` ingère les
   échantillons** (table `activity_sample`), le téléchargement doit se faire SANS
   `--output-dir` (ou avec `--output-dir <workspace>/activities`) : la copie normalisée
   canonique est `activities/fit/<garmin_activity_id>.json`, jetable et jamais versionnée
   (son propre `.gitignore` est créé automatiquement à la première écriture).
3. **Analyser** le FIT avec `session-parts-analyzer` (`analyze_session_parts.py --fit ... --part climb|stride|...`) ou `course-comparison` (`compare_course.py --fit-dir`).
4. **Persister** l'analyse (dérive, profil) dans le MD de l'activité dans la langue des documents (`config/workspace.toml` → `[language].documents`, défaut FRANÇAIS) — ne jamais dump le JSON brut en chat.

## Détails techniques

- `download_activity(activity_id, dl_fmt=ORIGINAL)` → gère le zip auto (dézippe à la volée).
- `_write_records_json` extrait les messages `record` → champs `distance`, `enhanced_altitude`/`altitude`, `heart_rate`, `speed`, `cadence`, `power`, **`position_lat`/`position_long`** (position GPS, quand le FIT en porte une — entiers en semi-cercles, pas encore des degrés à ce stade).
- **Champ altitude** : préférer `enhanced_altitude` quand présent (plus précis que `altitude`).
- `_write_canonical_samples` (#42) normalise ensuite ces mêmes records (sans reparser le FIT) via `normalise_records` de `scripts/arc_samples.py` : mapping `heart_rate → hr_bpm`, `distance → distance_m`, `enhanced_altitude/altitude → altitude_m`, `enhanced_speed/speed → speed_ms` (déjà en m/s), `timestamp → t_s` relatif au départ, **`position_lat`/`position_long` → `lat_deg`/`lon_deg`** (degrés décimaux, semi-cercles convertis — #49, identité de montée entre séances, `scripts/arc_climb_match.py` ; `None` si absents ou si le FIT ne porte aucun GPS), et **doublement de la cadence** (`cadence` FIT course à pied compte un seul pied/min, `cadence_spm` en sortie compte les deux) — voir la docstring du module pour le détail et les sources.
- Auto-relance avec le python de `garmin-mcp` si `garminconnect` absent de l'interpréteur courant.

## Files

| Path | Role |
|:-----|:-----|
| `SKILL.md` | Ce fichier |
| `scripts/download_fit.py` | Téléchargeur FIT + extracteur records (CLI) + copie normalisée `activities/fit/<id>.json` (#42) |

Base directory: skills/fit-download