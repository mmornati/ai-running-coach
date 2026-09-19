# Skill: gpx-analysis

# Skill: gpx-analysis

Analyse générique d'un fichier GPX (parcours de course, tracé Strava, GPX Garmin) et production d'un rapport Markdown structuré pour la planification.

## Quand l'utiliser

- L'utilisateur fournit un **fichier GPX** (tracé de course, parcours d'entraînement, GPX Strava/Garmin) et demande une analyse du parcours.
- Évaluer si un parcours **correspond à une séance planifiée** (distance cible, D+ cible) → verdict compatibilité.
- Préparer un plan de course (avec `course-strategist`) : profil, montées, boucle ou point-to-point.
- Comparer le profil réel d'un GPX à l'annonce officielle d'une course (distance/D+).

**Ne PAS utiliser** pour l'analyse d'une séance déjà courue (→ `session-parts-analyzer` sur FIT) ni pour la comparaison multi-séances d'un même lieu (→ `course-comparison`).

## Workflow

```bash
python3 skills/gpx-analysis/scripts/analyze_gpx.py \
  --gpx ~/Downloads/"Mont-de-l'Enclus 35km Trail.gpx" \
  --name "Mont-de-l'Enclus" \
  --target-distance 30-32 \
  --target-dp 1500 \
  --output planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md \
  --json /tmp/parcours.json
```

1. **Analyser** le GPX avec le script (stdout pour lecture rapide, `--output` pour persister).
2. **Croiser avec le contexte** : séance planifiée (distance/D+ cible), météo du jour (`weather-forecast`), historique de l'athlète (`activities/`), objectif (`active_objective.md`).
3. **Persister** la fiche d'évaluation en FRANÇAIS dans `planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md` (format : chiffres GPX, verdict compat, recommandation, détails pratiques).
4. Le cas échéant, proposer l'**upload Garmin** via `upload_course` — ne jamais uploader sans validation utilisateur.

## Sorties du script

- **Métadonnées** : distance réelle, D+/D-, alt min/max, type (boucle fermée / point-to-point), nb points GPS
- **Verdict compatibilité** (si `--target-*`) : tableau Distance / D+ avec ✅/🟡/🔴
- **Profil par km** : D+ et D- par km + lecture automatique (⛰️ Montée ≥40 m / 〽️ Mixte ≥15 m / 🟢 Plat)
- **Montées significatives** : km début/fin, distance, gain, grade moyen (≥ `--min-gain` m sur ≥ `--min-climb-dist` m)

## Configuration (CLI flags)

| Flag | Défaut | Description |
|:-----|:-------|:------------|
| `--gpx` | requis | Chemin du fichier GPX |
| `--name` | "" | Nom du parcours |
| `--target-distance` | — | Cible "MIN-MAX" km (ex. 30-32) |
| `--target-dp` | — | Cible D+ en m |
| `--smooth` | 3 | Fenêtre de lissage altitude (points) — réduit le bruit GPS |
| `--min-gain` | 15 m | Gain min pour détecter une montée |
| `--min-climb-dist` | 100 m | Distance min pour détecter une montée |
| `--output` | stdout | Fichier Markdown de sortie |
| `--json` | — | Dump JSON structuré |
| `--quiet` | false | Silencieux |

## Notes techniques

- **Stdlib uniquement** (xml.etree + math) — aucune dépendance.
- **Namespace-agnostic** : fonctionne avec ou sans préfixe XML (`<trkpt>` vs `<g:trkpt>`).
- **Altitude** : champ `<ele>` ; lissage glissant pour neutraliser le bruit GPS.
- **D+** : somme des élévations > 1 m après lissage → valeur conservative proche du baromètre.
- **Boucle fermée** : si retour-à-départ < 300 m.

## Files

| Path | Role |
|:-----|:-----|
| `SKILL.md` | Ce fichier |
| `scripts/analyze_gpx.py` | Analyseur GPX générique + rapport (CLI) |

Base directory: skills/gpx-analysis