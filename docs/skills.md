# 🛠️ Skills

`ai-running-coach` fournit **8 skills** que les agents chargent à la demande pour des tâches spécifiques.

## Vue d'ensemble

| Skill | Description |
|---|---|
| [Analyse GPX](skills/gpx-analysis.md) | Analyse générique d'un fichier GPX et production d'un rapport Markdown structuré |
| [Comparaison de parcours](skills/course-comparison.md) | Analyse comparative de séances sur un même parcours/lieu |
| [Planification Garmin](skills/garmin-workout-scheduling.md) | Push de séances planifiées dans le calendrier Garmin Connect |
| [Synchronisation Garmin](skills/garmin-sync-efficiency.md) | Récupération efficace des données Garmin sans saturer le contexte |
| [Météo](skills/weather-forecast.md) | Prévisions météo pour le lieu d'entraînement |
| [Analyse de séances](skills/session-parts-analyzer.md) | Analyse de portions spécifiques d'une séance Garmin |
| [Intervals.icu](skills/intervals-icu-best-practices.md) | Création et mise à jour d'événements Intervals.icu |
| [Téléchargement FIT](skills/fit-download.md) | Téléchargement de fichiers FIT Garmin en bypassant le canal MCP |

## Comment les skills sont utilisés

Les agents chargent les skills **à la demande** via l'outil `skill` de leur IDE. Par exemple :

- L'agent **coach** charge `weather-forecast` avant chaque validation hebdomadaire
- L'agent **coach** charge `garmin-workout-scheduling` avant de pousser des séances dans Garmin
- L'agent **course-strategist** charge `gpx-analysis` pour analyser un parcours

## Structure d'un skill

```
skills/<nom-du-skill>/
├── SKILL.md              # Instructions du skill
├── scripts/              # Scripts Python (optionnel)
└── examples/             # Exemples de sortie (optionnel)
```

## Scripts Python

Certains skills incluent des scripts Python :

| Script | Skill | Dépendances |
|---|---|---|
| `analyze_gpx.py` | gpx-analysis | stdlib uniquement |
| `compare_course.py` | course-comparison | stdlib uniquement |
| `analyze_session_parts.py` | session-parts-analyzer | stdlib uniquement |
| `download_fit.py` | fit-download | `garminconnect` + `fitparse` (via l'environnement garmin-mcp) |
