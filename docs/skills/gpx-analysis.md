# Skill : Analyse GPX

> **Description** : Analyse générique d'un fichier GPX (parcours de course, tracé Strava, GPX Garmin) et production d'un rapport Markdown structuré pour la planification.

<!-- arc-video:jour-de-course -->
<div class="arc-video-card" markdown>

[![La course, segment par segment](../video/jour-de-course/poster.jpg)](../video/jour-de-course/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 06 · 1 min 43</span>

**[La course, segment par segment](../video/jour-de-course/index.html)** — Du GPX au plan de course : allures par segment, énergie, matériel obligatoire, montre, puis débrief plan contre réalisé.

[Regarder](../video/jour-de-course/index.html) · [English](../video/jour-de-course/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Quand l'utiliser

- L'utilisateur fournit un **fichier GPX** (tracé de course, parcours d'entraînement, GPX Strava/Garmin) et demande une analyse du parcours
- Évaluer si un parcours **correspond à une séance planifiée** (distance cible, D+ cible) → verdict de compatibilité
- Préparer un plan de course (avec `course-strategist`) : profil, montées, boucle ou point-to-point
- Comparer le profil réel d'un GPX à l'annonce officielle d'une course (distance/D+)

## Fonctionnalités

- Analyse du **profil d'élévation** (D+, D-, pentes)
- Détection des **montées** significatives par le détecteur du moteur (`scripts/arc_climb.py`, le même que le tableau de bord) : approches plates rognées, replats courts fusionnés
- Détermination du type de parcours (boucle, point-to-point)
- **Verdict de compatibilité** avec une séance planifiée
- Rapport Markdown structuré
- **Correction altimétrique par MNT** (`--dem`, opt-in, #176) : IGN RGE ALTI en France, Copernicus GLO-90 via Open-Meteo ailleurs ; le D+ MNT devient la référence et le rapport affiche « D+ fichier / D+ MNT ». Seules des coordonnées amincies sont envoyées — voir [Correction altimétrique](../elevation.md)

## Script

`skills/gpx-analysis/scripts/analyze_gpx.py` — **stdlib uniquement**, aucune dépendance externe.

## Utilisation

```bash
python3 skills/gpx-analysis/scripts/analyze_gpx.py --gpx <fichier.gpx>
# avec altitude corrigée par MNT (opt-in, hors ligne : altitude du fichier conservée)
python3 skills/gpx-analysis/scripts/analyze_gpx.py --gpx <fichier.gpx> --dem
```

`--dem` / `--no-dem` / `--dem-step` / `--workspace` : voir [la page dédiée](../elevation.md) (sources, licences et attributions, vie privée, hypothèses). Réglage permanent : `[elevation].dem = "auto"`.

## Fichier source

`skills/gpx-analysis/SKILL.md`
