# Skill : Planification COROS

> **Description** : met les séances planifiées sur la montre COROS. Avec Intervals.icu (préconisé), c'est Intervals.icu qui les envoie et le skill vérifie leur arrivée ; sinon, il les pousse lui-même (course, trail, vélo) par le MCP officiel de COROS, en session interactive et après votre « oui ».

## Intervals.icu d'abord (configuration préconisée)

Si votre source est Intervals.icu (`[data].source = "intervals"`), **activez l'envoi des séances planifiées vers COROS dans Intervals.icu** (*Settings → COROS*) : le coach pousse vers Intervals.icu comme d'habitude, et Intervals.icu envoie les 7 prochains jours à la montre. Ce skill ne pousse alors rien lui-même ; il vérifie seulement, en lecture, que la séance est arrivée sur le calendrier COROS. Pourquoi ce choix et ses limites : [Montres COROS](../coros.md#configuration-preconisee-intervalsicu-coros).

## Quand l'utiliser (poussée directe)

- Vous avez une montre COROS et vous avez ajouté le serveur MCP `coros` à Claude Code (voir [Montres COROS](../coros.md#session-authentifiee-22-octobre-2026) : URL régionale `https://mcpeu.coros.com/mcp`, puis autorisation OAuth par `/mcp`).
- Votre source n'est pas Intervals.icu (par exemple Strava), ou vous demandez explicitement une poussée directe, et le coach a validé une séance.

COROS n'est **pas** une source de données du projet (`[data].source`) : vos activités et votre santé passent par votre source configurée. La poussée directe ne sert qu'à envoyer des séances.

## Ce que fait le skill

- **Cibles personnelles** : les plages FC (et l'allure sur le plat) viennent de votre profil par `arc_workout_targets.py`, comme pour Garmin ; `scripts/arc_coros_workout.py section` les met au format COROS (allure en s/km). Jamais les zones calculées par COROS, qu'une montre neuve n'a pas encore calibrées.
- **Vérification avant envoi** : `python3 scripts/arc_coros_workout.py validate` contrôle la séance contre les règles de l'outil COROS ; une séance invalide n'est jamais poussée.
- **Pas de doublon** : le calendrier COROS est lu avant chaque envoi ; une séance déjà présente est mise à jour, jamais recréée.
- **Vérification après envoi** : la séance est relue et doit être identique à celle envoyée.

## Limites

- **Aucun outil de suppression ni de déplacement** : une séance à retirer ou à déplacer se gère dans l'app COROS (le coach vous dit laquelle).
- **Course, trail et vélo seulement** pour les séances que le coach écrit. Le
  **renforcement** passe par vos séances types : créées une fois dans l'app COROS, le
  coach les planifie à la bonne date (voir [Montres COROS](../coros.md#renforcement-vos-seances-types-23-octobre-2026)).
- **Pas de cible de durée en trail** : une séance de trail prescrite en minutes se pousse en sections libres (bouton Tour, durée écrite dans la consigne) ou en séance de course ; le coach vous demande une fois ce que vous préférez. Jamais une distance devinée.
- **Jamais en mode headless** (sync quotidienne, Telegram) : chaque envoi demande votre « oui » dans la conversation.
- L'estimation de durée, de distance et de charge affichée par COROS est celle de COROS, pas un chiffre du projet.

## Fichier source

`skills/coros-workout-scheduling/SKILL.md`
