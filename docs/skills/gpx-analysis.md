# 🗺️ Skill : Analyse GPX

> **Description** : Analyse générique d'un fichier GPX (parcours de course, tracé Strava, GPX Garmin) et production d'un rapport Markdown structuré pour la planification.

## Quand l'utiliser

- L'utilisateur fournit un **fichier GPX** (tracé de course, parcours d'entraînement, GPX Strava/Garmin) et demande une analyse du parcours
- Évaluer si un parcours **correspond à une séance planifiée** (distance cible, D+ cible) → verdict de compatibilité
- Préparer un plan de course (avec `course-strategist`) : profil, montées, boucle ou point-to-point
- Comparer le profil réel d'un GPX à l'annonce officielle d'une course (distance/D+)

## Fonctionnalités

- Analyse du **profil d'élévation** (D+, D-, pentes)
- Détection des **montées** et **descentes** significatives
- Détermination du type de parcours (boucle, point-to-point)
- **Verdict de compatibilité** avec une séance planifiée
- Rapport Markdown structuré

## Script

`skills/gpx-analysis/scripts/analyze_gpx.py` — **stdlib uniquement**, aucune dépendance externe.

## Utilisation

```bash
python3 skills/gpx-analysis/scripts/analyze_gpx.py <fichier.gpx>
```

## Fichier source

`skills/gpx-analysis/SKILL.md`
