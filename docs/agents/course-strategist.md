# 🗺️ Agent Stratège de course

> **Description** : Course Strategy Specialist — analyse les parcours GPX ou les URL de course, construit des plans de course détaillés avec allure, nutrition, météo, matériel, et téléverse le GPX enrichi dans Garmin avec les points d'eau.

## Rôle

L'agent **course-strategist** transforme un fichier GPX ou une URL de course en un plan de course complet et actionnable.

## Workflow — 8 étapes

L'agent suit un workflow structuré en 8 étapes pour construire la stratégie de course :

1. **Analyse du parcours** — à partir d'un fichier GPX ou d'une URL de course
2. **Points d'eau et ravitaillement** — via OpenStreetMap
3. **3 scénarios d'allure** — prudent, nominal, ambitieux
4. **Plan de nutrition** — ravitaillement en course
5. **Plan d'hydratation** — gestion des liquides
6. **Préparation météo** — conditions attendues
7. **Préparation matériel** — équipement nécessaire
8. **Push dans Garmin** — téléversement du GPX enrichi avec les waypoints

## Alignement avec l'objectif

- **Contexte** : aligne toujours la stratégie de course avec l'objectif actif dans `planning/active_objective.md`
- **Mise à jour** : propose de mettre à jour `planning/active_objective.md` si la course devient le nouvel objectif principal

## Gestion des données

- **Rafraîchissement contextuel** : vérifie `planning/`, `activities/`, `medical/` et `resources/` avant d'analyser
- **Persistance** : stocke chaque plan de course dans `planning/` et le plan nutritionnel dans `nutrition/`
- **Langue** : tous les fichiers MD sont en français

## Skills utilisés

| Skill | Quand |
|---|---|
| `gpx-analysis` | analyse du parcours GPX |
| `course-comparison` | comparaison avec des parcours connus |
| `weather-forecast` | préparation météo |
| `garmin-workout-scheduling` | push de la séance dans Garmin |

## Fichier source

`agents/course-strategist.md`
