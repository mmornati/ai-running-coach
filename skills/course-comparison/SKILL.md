---
name: course-comparison
description: "Analyse comparative générique de séances sur un même parcours/lieu (ex. toutes les 'Tournai Trail') — découverte des activités via Garmin, alignement des boucles/segments comparables, montées, et rapport Markdown comparatif (script compare_course.py). Utiliser quand l'utilisateur demande une comparaison entre séances d'un même lieu ou l'évaluation de progression sur un parcours connu."
---

# Skill: course-comparison

Analyse comparative de séances enregistrées sur le **même parcours / même lieu** à des dates différentes. Produit un tableau comparatif (distance, durée, allure, D+, FC, HRR, TE), un alignement des tours/boucles, une comparaison des montées, et un verdict de progression.

## Quand l'utiliser

- L'utilisateur demande de comparer 2+ séances d'un même lieu (« compare avec le Tournai Trail de juillet », « comment ai-je progressé sur ce parcours ? »).
- Évaluation de la faisabilité d'un objectif à partir de la progression sur un parcours de référence.
- Toute demande « même parcours, dates différentes » → remplacer l'analyse manuelle par ce workflow reproductible.

**Ne PAS utiliser** pour l'analyse globale d'une seule séance (utiliser le workflow coach standard sur `get_activity`) ni pour les drills (strides/intervalles → `session-parts-analyzer`).

## Deux niveaux d'analyse

Le skill offre **2 niveaux** :

| Niveau | Données | Outil | Vitesse | Précision |
|:---|:---|:---|:---|:---|
| **Simplifié** (défaut) | Splits Garmin ~1 km (MD) | `scripts/compare_course.py` | Instantané | Segment km |
| **Détaillé** (sur demande) | FIT brut → points GPS | `scripts/compare_course.py --fit-dir` + skill `fit-download` | Lourd (FIT ~400 Ko/séance) | Segment géométrique, sub-km |

### Analyse simplifiée (défaut)
Utilise les fichiers `activities/*.md` (bloc `## Données brutes Garmin (référence)` + `## Analyse par splits (km)`). Rapide, suffisant pour les tours/boucles/montées par km.

### Analyse détaillée (FIT/GPX) — workflow
1. **Téléchargement FIT direct** : charge le skill **`fit-download`** et utilise `skills/fit-download/scripts/download_fit.py` (bypass MCP, évite le timeout de `get_activity_fit_data` autour des records GPS) :
   ```bash
   python3 skills/fit-download/scripts/download_fit.py 24070286912 --json
   # → activities/24070286912.fit (+ <id>.records.json si --json)
   python3 .../download_fit.py --from-dir activities/        # tous les activity_id des MD
   ```
   - Utilise `garminconnect` + tokens locaux `~/.garminconnect` (aucun mot de passe)
   - Auto-relaunch avec le python de garmin-mcp si le module manque (ou `--python <PATH>`)
   - Extraits : `--json` → records GPS/HR/power/cadence (fichier dédié, ne jamais dumper dans le chat)
2. **Analyse segment à segment** : une fois les FIT dispo, l'agent découpe chaque séance par zones GPS (lat/long) et aligne les segments des séances entre elles (mêmes coordonnées). Voir `docs/fit-analysis.md` pour le format.
   - Découpage par géométrie (haversine) → segments comparables sub-km
   - Comparaison FC/allure/puissance par segment identique
   - Note : les records GPS bruts sont lourds (2-3 Mo JSON) — extraction systématique en fichiers, jamais de raw JSON dans le contexte.

## Workflow

### Étape 1 — Persistance Garmin (prérequis, via l'agent)

1. Charge `garmin-sync-efficiency` et récupère les activités du lieu via `get_activities_by_date`.
2. Pour chaque activité à comparer, récupère le détail (`get_activity`) et les splits (`get_activity_splits`).
3. **Persiste immédiatement** chaque activité dans la langue des documents (`config/workspace.toml` → `[language].documents`, défaut FRANÇAIS) dans `activities/YYYY-MM-DD_type.md` **avec** :
   - le bloc `## Données brutes Garmin (référence)` (YAML : `activity_id`, `name`, `distance_m`, `duration_s`, `avg_hr_bpm`, `max_hr_bpm`, `elevation_gain_m`, `elevation_loss_m`, `recovery_hr_bpm`, `training_effect`…)
   - le tableau `## Analyse par splits (km)` (colonnes : `num | durée | allure | vmax | D+/D- | FC moy | cadence | lecture`).
   - Ces deux blocs sont **requis** par le script (un fichier sans eux est ignoré avec un warning).
4. Note : si une date demandée par l'utilisateur n'existe pas dans Garmin, cherche dans les jours voisins et signale explicitement la date réelle utilisée (ex. « Tournai Trail du 18/11/2025 introuvable → la vraie séance de référence est le 18/10/2025 (34,6 km), plus proche du format de course »). Toujours vérifier les deux mois précédents avant d'arrêter une date par défaut.

### Étape 2 — Découverte des sorties du même lieu

```bash
python3 skills/course-comparison/scripts/compare_course.py \
  --lieu "Tournai" \
  --aliases "Tournai Trail" "Tournai - Sortie" \
  --ref 2026-08-22 \
  --loop-length 10 \
  --output /tmp/comparaison_tournai.md \
  --json   /tmp/comparaison_tournai.json
```

- `--lieu` : regex/texte matché contre le champ `**Lieu :**` ET le nom de l'activité (insensible à la casse). C'est le paramètre principal de découverte.
- `--aliases` : noms alternatifs du même endroit (ex. « Tournai Trail », « Tournai - Sortie longue ») pour élargir la découverte.
- `--ref` : date de la séance de référence (ex. celle du jour). Les autres séances trouvées sont comparées à celle-ci.
- `--dates` : plage optionnelle `YYYY-MM-DD:YYYY-MM-DD` pour restreindre.
- `--exclude-dates` : dates à exclure `YYYY-MM-DD` (répétable) — utile pour écarter une séance de même lieu mais de format différent (ex. boucle unique courte parmi des formats course).
- `--loop-length` : longueur de boucle en km. Si absent → auto-détection (corrélation du profil D+ par km + boucle commune divisible par plusieurs séances).
- `--tolerance` : tolérance d'alignement en mètres (défaut 50).
- `--min-climb` : seuil de détection d'une « montée » (défaut 40 m D+ sur 1 km).

### Étape 3 — Lecture du rapport

Le script émet un rapport Markdown dans la langue des documents (`config/workspace.toml` → `[language].documents`, défaut FRENCH) avec 4 sections :

1. **Comparaison globale** — un tableau par séance : distance, durée, allure, D+/D-, FC moy/max, HRR, TE. Lecture rapide de la progression brute.
2. **Alignement des tours** — découpage de chaque séance en boucles de `--loop-length` km (ou auto-détectée). Lignes empilées par tour = **segments comparables** (ex. premier tour 1-10 km de chaque séance).
3. **Montées comparables** — tous les km avec D+ ≥ seuil, par séance : allocation à FC identique sur la même bosse.
4. **Verdict automatique** — delta % d'allure + delta FC bpm entre la référence et chaque autre séance (indicatif : à confirmer par l'analyse coach avec contexte fatigue/météo/blessure).

### Étape 4 — Interprétation coach (à enrichir)

- Compare d'abord le **premier tour** si le nombre de tours diffère (fatigue vs vitesse).
- Compare les **montées homologues** (même km, même D+) : duration et FC sur la même bosse = le vrai signal de progression.
- **HR manquante** : si `recovery_hr_bpm` absent sur une séance, le script l'affiche « — » : n'est PAS un signal physiologique, rappeler la mesure.
- Croise toujours avec `medical/` (sommeil, HRV, charge) et la météo (`medical/YYYY-MM-DD_meteo.md`) avant de conclure.

## Sorties

| Fichier | Contenu |
|:--------|:--------|
| stdout / `--output` | Rapport Markdown FR |
| `--json` | Structuré : liste des séances (distance, durée, D+, FC, HR, TE, montées) + `loop_length_km` |

## Exemples

```bash
# Progression sur le parcours Tournai (boucles de 10 km)
python3 skills/course-comparison/scripts/compare_course.py \
  --lieu "Tournai" --ref 2026-08-22 --loop-length 10 \
  --output rapports/2026-08-22_comparaison_tournai.md

# Analyse large sur plusieurs mois
python3 skills/course-comparison/scripts/compare_course.py \
  --lieu "Lille" --aliases "Citadelle" "Bois de Boulogne" \
  --ref 2026-08-20 --dates 2026-01-01:2026-08-20 \
  --loop-length 6
```

## Limites connues

- **Granularité km** : le script travaille sur les splits Garmin (~1 km). Pas de précision métrique sub-km (pour stridеs ou drill → `session-parts-analyzer`).
- Un fichier MD sans bloc YAML « Données brutes » ni tableau de splits est **ignoré** → toujours vérifier la persistance avant de lancer.
- Auto-détection de boucle : heuristique, peut échouer sur des parcours non périodiques → privilégier `--loop-length` explicite quand la boucle est connue.
- Verdict automatique = indication, pas une vérité : contexte toujours nécessaire.

## Fichiers

| Path | Rôle |
|:-----|:-----|
| `skills/course-comparison/SKILL.md` | Ce fichier (load via la tool `skill`) |
| `skills/course-comparison/scripts/compare_course.py` | Analyse simplifiée + rapport (CLI) |
| `skills/fit-download/scripts/download_fit.py` | Téléchargement FIT Garmin (bypass MCP, garminconnect + tokens locaux) — voir skill `fit-download` |
| `skills/course-comparison/docs/fit-analysis.md` | Workflow analyse détaillée FIT (segments GPS sub-km) |
| `examples/` | Exemples de rapport (à compléter) |
```