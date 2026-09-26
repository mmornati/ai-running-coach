# 🔬 Skill : Analyse de séances

> **Description** : Analyse de portions spécifiques d'une séance Garmin (lignes droites, montées, sprints, intervalles, dernier km, récupérations, etc.) — détection des segments par vitesse/FC/élévation et rapport des métriques d'exécution par segment.

## Quand l'utiliser

- L'utilisateur ou le coach veut un **feedback détaillé** sur un exercice particulier
- Analyser une séance qui **mélange travail + récupération**
- **Valider l'exécution** des lignes droites ou des intervalles

## Fonctionnalités

- **Détection des segments** par vitesse, FC et/ou élévation
- Types de segments détectés :
  - Lignes droites / strides
  - Montées
  - Sprints
  - Intervalles
  - Dernier kilomètre
  - Récupérations / cooldowns
- **Métriques d'exécution par segment** : allure, FC, cadence, etc.
- **Montées** détectées par le moteur (`scripts/arc_climb.py`) : mêmes bornes que le tableau de bord et l'identité de montée entre séances (#49), avec classe de pente et VAM

## Script

`skills/session-parts-analyzer/scripts/analyze_session_parts.py` — stdlib (+ `fitparse` pour lire un FIT) ; importe le moteur (`scripts/arc_climb.py`, `scripts/arc_samples.py`).

## Utilisation

```bash
python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py --help
```

## Fichier source

`skills/session-parts-analyzer/SKILL.md`
