# 🛠️ Skills

<div class="arc-page-banner" markdown>
![](assets/ridge.jpg)
</div>

`ai-running-coach` fournit **9 skills** que les agents chargent à la demande pour des tâches spécifiques.

## Vue d'ensemble

<div class="arc-skills">

<div class="arc-skill"><span class="arc-skill__name"><a href="skills/gpx-analysis.md">Analyse GPX</a></span><span class="arc-skill__desc">Analyse générique d'un fichier GPX et production d'un rapport Markdown structuré</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/course-comparison.md">Comparaison de parcours</a></span><span class="arc-skill__desc">Analyse comparative de séances sur un même parcours/lieu</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/garmin-workout-scheduling.md">Planification Garmin</a></span><span class="arc-skill__desc">Push de séances planifiées dans le calendrier Garmin Connect</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/garmin-sync-efficiency.md">Synchronisation Garmin</a></span><span class="arc-skill__desc">Récupération efficace des données Garmin sans saturer le contexte</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/weather-forecast.md">Météo</a></span><span class="arc-skill__desc">Prévisions météo pour le lieu d'entraînement</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/session-parts-analyzer.md">Analyse de séances</a></span><span class="arc-skill__desc">Analyse de portions spécifiques d'une séance Garmin</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/intervals-icu-best-practices.md">Intervals.icu</a></span><span class="arc-skill__desc">Création et mise à jour d'événements Intervals.icu</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/fit-download.md">Téléchargement FIT</a></span><span class="arc-skill__desc">Téléchargement de fichiers FIT Garmin en bypassant le canal MCP</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/garmin-daily-sync.md">Sync quotidienne</a></span><span class="arc-skill__desc">Synchronisation Garmin sans surveillance (cron, téléphone) avec résumé pour notification</span></div>

</div>

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
