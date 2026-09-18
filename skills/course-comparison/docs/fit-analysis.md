# Analyse détaillée FIT (segments GPS) — workflow agent

Ce document décrit l'utilisation des fichiers FIT bruts pour une analyse de
précision **segment à segment** (alliage de zones géographiques), en complément
de l'analyse simplifiée par splits km (`compare_course.py`).

## 1. Obtenir les FIT

```bash
# Un fichier (via le skill fit-download — bypass MCP)
python3 skills/fit-download/scripts/download_fit.py 12345678901

# Plusieurs + JSON records
python3 skills/fit-download/scripts/download_fit.py \
  12345678901 12345678902 --json

# Tous les activity_id référencés dans les MD de activities/
python3 skills/fit-download/scripts/download_fit.py --from-dir activities/
```

Sorties :
- `activities/<activity_id>.fit` — FIT brut (dézippé automatiquement)
- `activities/<activity_id>.records.json` (avec `--json`) — records 1 s :
  timestamp, position_lat/long (demi-cercles), enhanced_altitude, heart_rate,
  cadence, power.

**Taille** : ~400 Ko FIT / 2-3 Mo JSON. La lecture du JSON dans le contexte du
chat est proscrite — tout calcul se fait via script et on persiste le résultat.

## 2. Découpage par zones GPS

Le point clé : convertir les coordonnées GPS des records en séries continues, puis
aligner les séances sur un même parcours par **proximité géométrique**.

Outils disponibles (stdlib Python 3) :
- Conversion GPS : `lat = position_lat * 180 / 2**31` (valeurs signées Garmin).
- Distance : formule haversine (r ~6371 km).
- Alignement d'un point d'une séance sur l'autre : plus proche voisin
  (distance minimale) — tolérance ~15-30 m.
- Segmentation : découper par seuil de distance au point de départ pour
  retrouver le même endroit entre séances.

## 3. Comparaison segment à segment

Pour chaque segment répété (même géométrie, dates différentes) :
- durée / allure
- FC moyenne max
- cadence, puissance moyenne
- D+ (somme des gains d'altitude sur les records du segment)

Sortie : tableau Markdown FRENCH identique au format de `compare_course.py`,
mais alignée sur les segments GPS exacts plutôt que sur les bornes km fixes.

## 4. Limites & bonnes pratiques

- La position Garmin est bruitée : ne pas comparer des segments < 200 m.
- Si une séance n'a pas de coordonnées (position_lat/long tous None),
  l'alignement GPS est impossible → retomber sur l'analyse simplifiée par km.
- Toujours vérifier que les séances comparées sont bien sur le **même chemin**
  (corrélation de la série alt / distance avant d'aligner).
- Les .fit locaux ne sont **pas** re-téléchargés si le fichier existe (check
  `--overwrite` pour forcer).