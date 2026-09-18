# 📊 Skill : Comparaison de parcours

> **Description** : Analyse comparative générique de séances sur un même parcours/lieu (ex. toutes les « Tournai Trail ») — découverte des activités via Garmin, alignement des boucles/segments comparables, montées, et rapport Markdown comparatif.

## Quand l'utiliser

- L'utilisateur demande une **comparaison entre séances d'un même lieu**
- Évaluer la **progression** sur un parcours connu
- Comparer des séances sur le même parcours (ex. « toutes mes sorties sur le Tournai Trail »)

## Fonctionnalités

- **Découverte des activités** via Garmin (recherche par lieu/parcours)
- **Alignement des boucles/segments** comparables
- Analyse des **montées** et du profil
- **Rapport Markdown comparatif** avec les métriques clés

## Script

`skills/course-comparison/scripts/compare_course.py` — **stdlib uniquement**, aucune dépendance externe.

## Utilisation

```bash
python3 skills/course-comparison/scripts/compare_course.py --help
```

## Exemple

Un exemple de rapport comparatif est fourni dans `skills/course-comparison/examples/2026-05-10_comparaison_exemple.md`.

## Fichier source

`skills/course-comparison/SKILL.md`
