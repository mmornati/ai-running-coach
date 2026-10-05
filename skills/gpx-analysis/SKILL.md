---
name: gpx-analysis
description: Use when the user provides a GPX file (race course, Strava/Garmin track) and wants it analyzed or evaluated against a planned session. Runs scripts/analyze_gpx.py (stdlib) to compute real distance, elevation gain/loss with noise smoothing, per-km profile, significant climbs, loop vs point-to-point detection, and a compatibility verdict against a distance/elevation target. Do not use for an already-run session (use session-parts-analyzer) or multi-session comparison (use course-comparison).
---

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
3. **Persister** la fiche d'évaluation dans la langue des documents (`config/workspace.toml` → `[language].documents`, défaut FRANÇAIS) dans `planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md` (format : chiffres GPX, verdict compat, recommandation, détails pratiques). La fiche s'ouvre, sous son titre, par un bloc ```arc `kind: course_eval` construit depuis la sortie `--json` du script (`distance_m`, `elevation_gain_m`, `is_loop`, cible, `verdict`) — voir le skill `workspace-data-contract`.
4. Le cas échéant, proposer l'**upload Garmin** via `upload_course` — ne jamais uploader sans validation utilisateur.

## Sorties du script

- **Métadonnées** : distance réelle, D+/D-, alt min/max, type (boucle fermée / point-to-point), nb points GPS
- **Verdict compatibilité** (si `--target-*`) : tableau Distance / D+ avec ✅/🟡/🔴
- **Profil par km** : D+ et D- par km + lecture automatique (⛰️ Montée ≥40 m / 〽️ Mixte ≥15 m / 🟢 Plat)
- **Montées significatives** : km début/fin, distance, gain net, grade moyen (≥ `--min-gain` m, ≥ `--min-grade` %, sur ≥ `--min-climb-dist` m) — détectées par le moteur (`scripts/arc_climb.py`), voir « Détection des montées »

## Configuration (CLI flags)

| Flag | Défaut | Description |
|:-----|:-------|:------------|
| `--gpx` | requis | Chemin du fichier GPX |
| `--name` | "" | Nom du parcours |
| `--target-distance` | — | Cible "MIN-MAX" km (ex. 30-32) |
| `--target-dp` | — | Cible D+ en m |
| `--smooth` | 3 | Fenêtre de lissage altitude (points) — réduit le bruit GPS |
| `--min-gain` | 15 m | Gain net min pour détecter une montée |
| `--min-grade` | 5 % | Pente moyenne min d'une montée (gain net / distance) |
| `--min-climb-dist` | 100 m | Distance min pour détecter une montée |
| `--output` | stdout | Fichier Markdown de sortie |
| `--json` | — | Dump JSON structuré |
| `--quiet` | false | Silencieux |
| `--dem` | false | Altitude corrigée par MNT public (#176) : IGN RGE ALTI en France, Copernicus GLO-90 via Open-Meteo ailleurs. Opt-in |
| `--no-dem` | false | Désactive la correction même avec `[elevation].dem = "auto"` |
| `--dem-step` | config / 50 m | Pas d'amincissement des coordonnées envoyées |
| `--workspace` | auto | Workspace (config `[elevation]`, cache local) |

## Notes techniques

- **Stdlib uniquement** (xml.etree + math) — aucune dépendance.
- **Namespace-agnostic** : fonctionne avec ou sans préfixe XML (`<trkpt>` vs `<g:trkpt>`).
- **Altitude** : champ `<ele>` ; lissage glissant pour neutraliser le bruit GPS.
- **D+** : somme des pas d'altitude strictement supérieurs à 1 m après lissage (un pas d'exactement 1,0 m est ignoré) → valeur conservative proche du baromètre. Le **profil par km** applique la même règle, pas par pas : la somme des D+/D- par km égale le total (à l'arrondi au dixième près par km). Limite : sur un GPX très finement échantillonné, une pente douce donne des pas de moins de 1 m et n'est pas comptée — `--dem` (sans seuil) est alors la référence.
- **Boucle fermée** : si retour-à-départ < 300 m.

## Correction altimétrique par MNT (#176)

L'altitude d'un GPX (GPS seul) est bruitée, celle d'un baromètre dérive : `--dem` rééchantillonne la trace sur un **modèle numérique de terrain** — IGN RGE ALTI (Géoplateforme) pour les points de France métropolitaine, Copernicus GLO-90 via Open-Meteo ailleurs et là où l'IGN n'a pas de donnée. Le D+ MNT devient la **référence** (verdict, profil par km, montées) et le rapport affiche `D+ fichier / D+ MNT` avec l'écart.

- **Désactivé par défaut** : sans `--dem` et avec `[elevation].dem = "off"`, aucun appel réseau. `[elevation].dem = "auto"` l'active pour les GPX de course (itinéraires publics) ; `--no-dem` l'annule.
- **Vie privée** : seules des coordonnées arrondies, amincies (un point tous les 50 m), sont envoyées à data.geopf.fr (IGN) ou api.open-meteo.com. Un GPX qui est l'enregistrement d'une SÉANCE personnelle (domicile en début/fin de trace) ne doit pas être envoyé sans l'accord explicite de l'athlète ; les séances FIT passent par `arc_index.py dem-check` (opt-in `[privacy].dem_for_activities`).
- **Hors ligne** : le script garde l'altitude du fichier et avertit (`status = "unavailable"` dans `--json`) — relayer l'avertissement, ne jamais inventer un D+ MNT.
- Cache local du workspace (fichier `dem-cache.json`, jamais dans le dépôt). Hypothèses et limites : `scripts/arc_dem.py::ASSUMPTIONS`.
- **Attribution** à reprendre dans la fiche d'évaluation : la ligne `_Altitudes : …_` du rapport (IGN — Licence Ouverte Etalab 2.0 ; Copernicus DEM GLO-90 via Open-Meteo.com).
- Le bloc ```arc `course_eval` reste en altitude de référence (MNT si `--dem` a réussi) ; reporter `elevation_gain_m` depuis `metrics` du `--json`, et `dem.comparison` en texte libre.

## Détection des montées

Le script délègue au détecteur canonique du moteur, `scripts/arc_climb.py::detect_climbs` (#46) — le même que le tableau de bord (VAM) et l'identité de montée entre séances (#49, `scripts/arc_climb_match.py`) : lissage de l'altitude (`--smooth`), zigzag à hystérésis, **rognage** des approches plates et des replats de sortie, découpage des longs plateaux internes, **fusion** d'un creux court (< 200 m, perte ≤ max(10 m, 12,5 % du plus petit gain)). Les seuils `--min-gain`/`--min-grade`/`--min-climb-dist` restent propres au skill.

- Le `<time>` d'un tracé enregistré est **ignoré** : le skill analyse le terrain, une pause de l'enregistrement ne coupe jamais une montée.
- Aucune VAM n'est calculée depuis un GPX (pas de durée significative) — la VAM d'une séance courue vient de `scripts/arc_index.py vam`.
- Différences avec l'ancien détecteur (suivi de pic sur l'altitude brute) : moins de montées, plus longues (un replat court ne coupe plus une montée), bornes resserrées sur la partie qui monte vraiment, gain **net** sur l'altitude lissée (légèrement conservateur aux extrémités).

## Files

| Path | Role |
|:-----|:-----|
| `SKILL.md` | Ce fichier |
| `scripts/analyze_gpx.py` | Analyseur GPX générique + rapport (CLI) |
| `../../scripts/arc_dem.py` | Correction altimétrique par MNT (#176), appelé par `--dem` |
| `../../scripts/arc_climb.py` | Détecteur de montées du moteur (importé) |

Base directory: skills/gpx-analysis