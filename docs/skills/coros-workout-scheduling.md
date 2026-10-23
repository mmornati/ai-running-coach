# Skill : Planification COROS

> **Description** : met les séances planifiées sur la montre COROS par le MCP officiel de COROS (course, trail, vélo, et renforcement par vos séances types), en session interactive et après votre « oui ». Aucun compte tiers nécessaire.

## Quand l'utiliser

- Vous avez une montre COROS et installé la connexion COROS (`./install.sh --coros`, une seule connexion pour toutes les IA : voir [Montres COROS](../coros.md#installation-une-seule-connexion-pour-toutes-les-ia)).
- Le coach a validé une ou plusieurs séances et vous voulez les retrouver sur la montre.

## Ce que fait le skill

- **Cibles personnelles** : les plages FC (et l'allure sur le plat) viennent de votre profil par `arc_workout_targets.py`, comme pour Garmin ; `scripts/arc_coros_workout.py section` les met au format COROS (allure en s/km). Jamais les zones calculées par COROS, qu'une montre neuve n'a pas encore calibrées.
- **Vérification avant envoi** : `python3 scripts/arc_coros_workout.py validate` contrôle la séance contre les règles de l'outil COROS ; une séance invalide n'est jamais envoyée.
- **Pas de doublon** : le calendrier COROS est lu avant chaque envoi ; une séance déjà présente est mise à jour, jamais recréée.
- **Vérification après envoi** : la séance est relue et doit être identique à celle envoyée.
- **Renforcement** : vos séances types, créées une fois dans l'app COROS, sont planifiées à la bonne date (voir [Montres COROS](../coros.md#renforcement-vos-seances-types)).
- **Allure seuil COROS** : lue pour contrôler votre vitesse critique, jamais utilisée comme cible.

## Limites

- **Aucun outil de suppression ni de déplacement** : une séance à retirer ou à déplacer se gère dans l'app COROS (le coach vous dit laquelle).
- **Le renforcement ne se crée pas par le MCP** : vous créez la séance type dans l'app, le coach la planifie ; il ne voit pas ses exercices.
- **Pas de cible de durée en trail** : une séance de trail prescrite en minutes se pousse en sections libres (bouton Tour, durée écrite dans la consigne) ou en séance de course ; le coach vous demande une fois ce que vous préférez. Jamais une distance devinée.
- **Un seul chemin vers la montre** : si un autre service envoie déjà vos séances au calendrier COROS, coupez cet envoi, sinon chaque séance apparaît deux fois.
- **Jamais en mode headless** (sync quotidienne, Telegram) : chaque envoi demande votre « oui » dans la conversation.
- L'estimation de durée, de distance et de charge affichée par COROS est celle de COROS, pas un chiffre du projet.

## Fichier source

`skills/coros-workout-scheduling/SKILL.md`
