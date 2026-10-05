# Skill : Météo

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

## Cibles de séance ajustées à la chaleur (#171)

Un jour chaud (> 25 °C) ou 🔴, `python3 scripts/arc_workout_targets.py targets --heat --session …` lit ce fichier météo et ajuste les cibles de la séance de façon déterministe (mêmes coefficients que le pacing de course, `scripts/arc_heat.py`) :

| Séance | Effet |
|---|---|
| endurance / sortie longue | durée conservée, allure ralentie (× 1,10, × 1,05 de plus si acclimatation faible), FC inchangée |
| qualité / allure course | créneau frais d'abord ; sinon allures abaissées ou séance déplacée ; jamais d'intensité maintenue en 🔴 |
| renforcement, indoor | aucun changement |

Température retenue : `temp_min_c` pour le créneau matin, `temp_max_c` sinon (pas de température horaire dans le bloc) ; le ressenti la remplace s'il est plus élevé (sauf au créneau matin : le ressenti du fichier est une valeur journalière) ; humidité absente → repli sur la température seule. Les coefficients sont des approximations du projet (voir `ASSUMPTIONS` de `arc_heat.py`), pas des mesures individuelles.

## Contexte du cycle (opt-in, #166)

Seulement si `[health].cycle_tracking` n'est pas `off` et qu'une phase lutéale est enregistrée pour le jour : au plus une ligne de contexte hydratation/chaleur dans la section météo ; aucune catégorie ni seuil modifié. Voir [Cycle menstruel](../cycle-menstruel.md).

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
