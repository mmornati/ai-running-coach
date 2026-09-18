# 🌦️ Skill : Météo

> **Description** : Prévisions météo (wttr.in via webfetch) pour le lieu d'entraînement, persistance de fichiers MD par jour, résolution du lieu effectif, et recommandations d'heure optimale pour les séances en extérieur.

## Quand l'utiliser

- Récupérer les **prévisions météo** pour le lieu d'entraînement
- Avant chaque **validation hebdomadaire ou quotidienne** (utilisé par l'agent coach)

## Fonctionnalités

- **Prévisions météo** via wttr.in (webfetch)
- **Persistance** : un fichier MD par jour (`medical/YYYY-MM-DD_meteo.md`)
- **Résolution du lieu effectif** (ordre strict) :
  1. `Lieu d'entraînement :` dans `planning/Semaine_*.md` → override
  2. `planning/active_objective.md` → lieu par défaut
  3. `planning/Runner_Profile.md` → lieu par défaut
  4. Sinon → demander à l'utilisateur
- **Recommandation d'heure optimale** : 🌅 matin tôt / ☀️ midi / 🌇 soir

## Catégories météo

| Catégorie | Signification |
|---|---|
| 🟢 | Conditions idéales |
| 🟡 | Conditions acceptables |
| 🟠 | Conditions difficiles — ajustements nécessaires |
| 🔴 | Conditions dangereuses — ajustements majeurs ou report |

## Sortie par séance

Pour chaque séance en extérieur, le skill produit :

1. **Catégorie météo** (🟢/🟡/🟠/🔴)
2. **Heure optimale** avec justification en une ligne
3. **Ajustements concrets** (hydratation, intensité, matériel, durée) si 🟠 ou 🔴

## Fichier source

`skills/weather-forecast/SKILL.md`
