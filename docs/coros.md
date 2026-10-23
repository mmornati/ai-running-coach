# Montres COROS

Une montre COROS se branche **directement** au coach par le **MCP officiel de COROS** :
pas de compte tiers, une seule connexion pour toutes les IA. Tout ce qui est marqué
« constaté » ci-dessous a été vérifié par nous sur un compte réel (montre COROS PACE 4
Pro), entre le 22 et le 23 octobre 2026.

## En bref

| | État |
|---|---|
| Connexion (une fois, pour toutes les IA) | ✅ `./install.sh --source coros` (source de données) ou `--coros` (montre seule) |
| Envoyer les séances de course, trail et vélo à la montre | ✅ cibles FC et allure personnelles |
| Modifier une séance envoyée | ✅ |
| Supprimer ou déplacer une séance | ❌ dans l'app COROS (aucun outil dans le MCP) |
| Renforcement structuré | ✅ vos séances types, créées une fois dans l'app, planifiées par le coach |
| Allure seuil COROS (contrôle de la vitesse critique) | ✅ |
| Lire activités, tours, santé, récupération | ✅ |
| FIT et analyses fines (zones, GAP, découplage, montées, foulée) | ✅ `download_fit.py --source coros`, identifiant `coros_activity_id` |
| Source de données `coros` : activités et santé enregistrées, bilan matinal, synchronisation quotidienne | ✅ `./install.sh --source coros` |
| Surveillance (`[sync].mode = "watch"`) : synchronisation dès qu'une séance ou la nuit arrive | ✅ sans IA, par le relais |
| Splits par km | ⬜ à venir, calculés depuis le FIT |
| FC de récupération, matériel par séance, pesées | ❌ absents du MCP COROS |

## Deux façons de brancher la montre

| | `./install.sh --source coros` | `./install.sh --coros` |
|---|---|---|
| Pour qui | votre montre est une COROS | votre source de données reste une autre |
| Activités et santé enregistrées (`activities/`, `medical/`), bilan matinal, synchronisation quotidienne, surveillance | ✅ comme avec Garmin | ❌ lectures pendant la conversation seulement |
| Séances envoyées à la montre | ✅ destination principale | ✅ |

`--source coros` implique `--coros` (le relais est la source de données) ; `--no-coros` lui
est refusé. Il installe aussi un petit environnement Python dédié à la lecture des FIT
(`~/.local/share/ai-running-coach/fit-reader`, `fitparse`), puisque `garmin-mcp` n'est plus là.

## Installation : une seule connexion pour toutes les IA

```bash
./install.sh --source coros     # ou --coros pour la montre seule
```

- **Une seule connexion.** L'installeur lance `python3 scripts/arc_coros_auth.py login`
  (en interactif seulement) : le navigateur s'ouvre, vous autorisez l'accès à votre
  compte COROS, c'est tout. Sans navigateur sur la machine (serveur, SSH) :
  `arc_coros_auth.py login --device` affiche une adresse et un code à valider depuis
  votre téléphone. Les jetons vont dans `~/.config/ai-running-coach/coros/`
  (dossier 700, fichiers 600) et ne sont jamais affichés.
- **Toutes les IA.** Le serveur `coros` est déclaré dans la config de chaque client
  (Claude Code, Copilot, Cursor, OpenCode, Gemini, Windsurf) : c'est un relais local,
  `scripts/arc_coros_mcp.py`, qui transmet au MCP officiel de COROS avec ces jetons.
  Aucun client ne fait de connexion OAuth ; les outils et les réponses sont ceux de
  COROS, sans réécriture.
- **Renouvellement automatique.** Le jeton d'accès vit 30 jours ; le relais le
  renouvelle quand il reste moins de 7 jours (ou après un refus), sous verrou, car COROS
  remplace aussi le jeton de rafraîchissement à chaque fois. Constaté : rafraîchissement
  forcé (nouveaux jetons, 30 jours), et relais avec un jeton d'accès refusé → rafraîchi
  puis 34 outils listés. Pas encore mesurés : la durée de vie du jeton de rafraîchissement
  et le sort de l'ancien après rotation.
- **Jamais d'écriture sans vous.** Pendant la synchronisation sans tête, le relais passe
  en lecture seule et les 7 outils d'écriture sont refusés par leur nom, quelle que soit
  l'IA qui la lance.
- **Vérifier :** `python3 scripts/arc_coros_auth.py status` (sans réseau), `verify`
  (appel réel du MCP), ou `/coach-doctor` (contrôle `coros_connection`). **Retirer :**
  `./install.sh --no-coros` (ne touche jamais une entrée `coros` ajoutée à la main), puis
  `arc_coros_auth.py logout`.

Vous aviez ajouté le serveur à la main (`claude mcp add … coros https://mcpeu.coros.com/mcp`) ?
Retirez-le (`claude mcp remove coros`), sinon il masque le relais : Claude Code donne la
priorité à une entrée locale sur celle du projet, et vous auriez deux connexions.

## Envoyer les séances à la montre

Le coach envoie les séances validées au calendrier COROS (skill
[`coros-workout-scheduling`](skills/coros-workout-scheduling.md)) ; l'app COROS les
synchronise sur la montre. **En interactif seulement**, après votre « oui » explicite.

- **Cibles personnelles** : plages FC en bpm et allure sur le plat calculées depuis votre
  profil (`arc_workout_targets.py`), mises au format COROS par
  `scripts/arc_coros_workout.py section`, contrôlées par `validate` avant l'envoi. Jamais
  les zones de COROS, qu'une montre neuve n'a pas encore calibrées.
- **Pas de doublon** : le calendrier est lu avant chaque envoi ; une séance déjà présente
  est mise à jour, jamais recréée. **Un seul chemin vers la montre** : si un autre service
  envoie déjà vos séances au calendrier COROS, coupez cet envoi, sinon chaque séance
  apparaît deux fois.
- **Relue après envoi** : la séance relue doit être identique à celle envoyée.

**Constaté :**

- **Création** (`createScheduledWorkout`) : 40 min à 137-149 bpm puis 4 × 100 m + 1 min
  de récupération, relue à l'identique (COROS y ajoute son estimation de durée, de
  distance et de charge), affichée sur la montre après synchronisation.
- **Modification** (`updateScheduledWorkout`) : la séance entière est remplacée (durée,
  FC, nom, description), relue à l'identique, sans doublon.
- **Trail** : pas de cible de durée en trail. Une séance prescrite en minutes passe en
  étapes libres (« Manuel » dans l'app, bouton Tour, cible FC gardée, durée écrite dans
  la consigne) ou en séance de course ; le coach vous demande une fois ce que vous
  préférez. COROS ne donne alors ni durée, ni distance, ni charge estimées.
- **Montée** : une répétition « 30 m de D+ » s'affiche « 30 m » avec l'icône de montée.
- **Suppression, déplacement** : aucun outil. Le coach vous dit quelle séance retirer
  dans l'app COROS.

**Règles du schéma** (lues dans la description de l'outil, appliquées par
`arc_coros_workout.py validate`) : course, trail et vélo seulement ; pas de cible de
durée en trail (distance, D+ ou libre) ; un seul format d'intensité par étape (zone,
pourcentage ou valeurs absolues) ; allure en s/km entières ; groupes de 1 à 20
répétitions, sans imbrication ; dates d'aujourd'hui à aujourd'hui + 90 jours.
`idInPlan`, l'identifiant rendu, est un petit compteur (« 1 », « 2 »), qui ne commence
pas toujours à 1 et n'est pas unique : une séance se désigne par sa date **et** son
`idInPlan`.

## Renforcement : vos séances types

Le MCP ne sait ni créer, ni lire, ni modifier une séance de renforcement (« COROS sport
type 4 (Strength) cannot be expressed by MCP »). Il sait en revanche **planifier** une
séance de votre bibliothèque COROS, renforcement compris (`scheduleWorkout`). D'où le
partage :

1. **Vous**, une fois : vous créez dans l'app COROS une séance type par renforcement que
   le coach vous donne (en général 1 à 3, à refaire au changement de phase). Le coach peut
   vous en recopier la fiche (exercices, tours, répétitions ou maintiens, par côté) ; les
   repos qu'il ne précise pas sont à votre choix.
2. **Le coach** retrouve la séance (`queryWorkoutLibrary`), vous la propose pour la date
   prévue et la planifie après votre « oui ».

Constaté sur deux séances créées dans l'app (« Renfo lombaires », « Renfo descentes ») :

- `queryWorkoutLibrary` les liste avec leur durée estimée et leur nombre de séries ;
  `queryWorkoutDetails` ne rend que le nom et le sport : **le coach ne voit pas les
  exercices**, seule l'app (ou la montre) fait foi ;
- `scheduleWorkout` a posé « Renfo descentes » sur une date ; `queryTrainingSchedule` l'a
  relue comme « Standalone workout (scheduled from the workout library) », et la séance
  est **arrivée sur la montre avec ses exercices** ;
- la date reçoit une **copie figée** : modifier ensuite la séance type ne la change pas, et
  le MCP ne peut pas modifier la copie. Finissez les retouches avant que le coach planifie ;
  supprimer ou déplacer se fait dans l'app ;
- dans l'app, un côté = un exercice à part (ou une seule entrée « par côté »), les tours
  sont un bloc « Répéter N fois », un exercice peut rester hors du bloc. Noms du catalogue
  en français : « Crunch », « Chien d'oiseau » (bird-dog), « Couché sur le dos Pont des
  fessiers », « Extension mollets debout », « Gainage latéral », « Étirement du chat et de
  la vache ». Le curl-up de McGill n'a pas d'équivalent exact : « Crunch » avec une note
  (tenir 10 s, une jambe pliée, mains sous les lombaires).

## Ce que le MCP lit

**Activités** (relevées le 22 octobre 2026, première séance) :

- `querySportRecords` : une ligne par séance, avec `labelId` et `sportType` (codes
  d'activité : 100 course, 102 trail…), horodatages de début et de fin, durée,
  distance, allure, FC moyenne, calories, coordonnées de départ. `LabelId` est un
  entier de 18 chiffres (`481221836600803431`). Le champ « Location » contient le **nom
  de l'activité** (celui de la séance planifiée quand elle en vient, sinon le titre,
  par exemple « Cusy Course ») : jamais un lieu fiable ;
- `getActivityDetail` : texte, résumé seulement (allure, allure ajustée à la pente,
  FC moyenne, cadence, longueur de pas, puissance, D+/D−, calories, charge,
  effets aérobie/anaérobie, effort perçu). **Pas de FC de récupération, pas de
  matériel** ;
- `queryActivityLapData` : JSON avec des libellés de colonnes en chinois, plusieurs
  découpages (`type` 10 = par km, 2 = étapes de la séance, 11 = tous les 5 km,
  -1 = total). Unités relevées : distance en **cm**, temps en s, allure en s/km,
  vitesse en km/h × 100, temps de contact en ms, oscillation en mm, longueur de pas
  en cm. **Le découpage « par km » repart de zéro à chaque étape de la séance
  planifiée** : sur la séance du 22/10, un tour de 194,85 m à la fin des 40 min, puis
  un tour par ligne droite et par récupération. Ce ne sont donc pas des splits au
  km réguliers ; les vrais splits seront calculés depuis le FIT ;
- `queryActivityFitFileDownloadUrls(labelId, sportType)` : une URL de fichier FIT standard
  (produit « COROS PACE 4 Pro », 3 786 points : FC, allure, altitude, GPS, puissance, temps
  de contact, oscillation, longueur de pas), lisible par `fitparse` et par la normalisation
  du projet sans changement. COROS annonce 50 fichiers par jour au plus. Constaté le 23/10 :
  `sportType` est exigé mais pas vérifié (100 et 102 rendent le même fichier) ; l'URL pointe
  vers le stockage de COROS et se télécharge **sans authentification** (le projet ne l'affiche
  jamais) ; une demande par plage de dates a été refusée par le serveur (« Tool call
  anomalies detected »), d'où une demande par `labelId`.

**Le FIT dans le projet** : `download_fit.py <c+LabelId> --json --source coros` (skill
`fit-download`) passe par le relais, avec nos jetons, puis écrit la copie normalisée
`activities/fit/c<LabelId>.json`. Une séance au contrat porte `coros_activity_id`
(`"c481221836600803431"`) et `start_time`. Constaté sur la séance du 22/10 : zones, allure
ajustée à la pente, découplage, montées (1 montée de 123 m à 558 m/h) calculés comme pour
une séance Garmin. Les montées d'une séance COROS sont numérotées par son heure de départ :
le `LabelId` de 18 chiffres dépasse les entiers que le tableau de bord sait manipuler.

**Santé et récupération** (relevées le 23 octobre 2026, avant la fin de la première
nuit) :

- `queryRestingHeartRate(days)` : une ligne par jour, `2026-10-22: 66 bpm`, ou
  `No data` ; ne prend qu'un nombre de jours, pas de date ;
- `queryDailyHealthData(days)` : en-tête `Resting HR: 68 bpm | HRV Baseline: 42 ms`,
  puis par jour pas, calories, temps d'exercice, stress moyen ;
- `queryRecoveryStatus` : `Recovery: 96%`, un niveau (`Heavy training allowed`) et le
  temps estimé avant récupération complète (`9h`). Sans donnée : `Recovery: -1% / Level:
  Unknown` — une valeur absente, pas un score ;
- `querySleepOverview` et `querySleepHrv` : datés par le **jour du réveil** (la nuit qui
  finit le matin de D est rangée sous D). Nuit pas encore terminée : `Sleep Score: 0` avec
  « Sleep detail for this day is not available yet » (0 = absent, pas un score) et « No
  data found ». La forme d'une nuit complète reste à relever.

- `queryMenstruationCycles` : sur un compte sans saisie, plage interrogée (30 jours
  avant, 365 après), « No cycle includes today », durées habituelles (7 jours de règles,
  cycle de 28 jours, valeurs par défaut) et « No menstrual cycle data found ». Jamais
  une phase à déduire de ces durées par défaut.

**Forme** : `queryFitnessAssessmentOverview` rend VO2max, niveau de course, allure seuil
(`Threshold Pace 4:12 /km` le 22/10) et prédictions, en texte. L'allure seuil sert au
contrôle de la vitesse critique (`arc_coros_workout.py threshold`, nommée « allure seuil
COROS »), jamais comme cible.

## Le bilan matinal avec COROS

Avec `--source coros`, le bilan matinal est le même triptyque qu'avec Garmin, au niveau de
`[health].morning_check` :

| Garmin | COROS | Enregistré dans `medical/AAAA-MM-JJ_health.md` |
|---|---|---|
| HRV nocturne | `querySleepHrv` (évaluation officielle du jour) | `hrv_overnight_ms` |
| FC de repos | `queryRestingHeartRate` | `resting_hr_bpm` |
| Training Readiness | **récupération COROS** (`queryRecoveryStatus`) | `provider_scores` (`recovery`, 0-100) |
| Score de sommeil | score de sommeil COROS (`querySleepOverview`) | `provider_scores` (`sleep`, 0-100) |

- **Nommer, jamais convertir.** Le coach dit « récupération COROS 96 % », jamais « Training
  Readiness », et ne la compare jamais aux seuils Garmin. C'est un état **actuel**, mis à jour en
  continu : il ne prouve jamais que la nuit a été lue.
- **Jour du réveil.** La nuit du 22 au 23 est datée du 23.
- **Nuit pas encore calculée.** `Sleep Score: 0`, HRV « No data found », FC de repos `No data` :
  la nuit n'est pas encore arrivée chez COROS (constaté le 23/10/2026 : nuit visible dans l'app
  COROS à 11 h 27, toujours absente du MCP à 11 h 34 ; délai à mesurer). La synchronisation sans
  tête n'écrit alors **aucun** fichier santé et réessaie au passage suivant ; en conversation, le
  coach le dit et décide sur la charge et votre ressenti.
- **Ligne de base HRV** : environ 5 nuits avec la montre selon COROS ; avant, « ligne de base COROS
  en construction ».

## Correspondance Garmin ↔ COROS

Ce que la source `coros` lit, outil par outil. La table de référence des agents (avec les
règles de persistance) est dans `AGENTS.md`, « Correspondance des outils — Garmin ↔ COROS ».

| Besoin | Outil `garmin` | Outil `coros` | Note |
|---|---|---|---|
| Activités récentes | `get_activities_by_date` | `querySportRecords(startDate, endDate, sportTypeCodes…)` | Texte : une entrée par séance, `LabelId` + `SportType` (100 course, 101 tapis, 102 trail, 104 randonnée…), horodatages, durée, distance, allure, FC moyenne, calories. « Location » = nom de l'activité, jamais `location`. |
| Détail d'une activité | `get_activity` | `getActivityDetail` | Texte résumé : allure, allure ajustée à la pente, FC, cadence, puissance, D+/D−, calories, charge, effort perçu. Pas de FC de récupération ni de matériel : omis, jamais inventés. |
| Tours | `get_activity_splits` | `queryActivityLapData` | Distances en **cm**, libellés en chinois. Le découpage « par km » repart à chaque étape de la séance planifiée : jamais recopié dans `splits`. |
| FIT | `get_activity_fit_data` | `queryActivityFitFileDownloadUrls` | Par `download_fit.py --source coros`, jamais par l'IA ; 50 fichiers par jour. |
| Identifiant au contrat | `garmin_activity_id` | `coros_activity_id` | `"c"` + `LabelId`, avec `start_time`. |
| HRV nocturne | `get_hrv_data` | `querySleepHrv` | Jour du réveil. Forme d'une nuit complète à relever. |
| FC de repos | `get_rhr_day` | `queryRestingHeartRate(days)` | `AAAA-MM-JJ: N bpm` ou `No data` ; nombre de jours seulement, pas de date. |
| Sommeil | `get_sleep_data` | `querySleepOverview` | Jour du réveil ; `Sleep Score: 0` = nuit pas encore disponible, pas un score. Forme d'une nuit complète à relever. |
| Readiness | `get_training_readiness` | `queryRecoveryStatus` | **Récupération COROS** : `Recovery: N%`, un niveau, un temps avant récupération complète ; `-1%` = absent. État **actuel** seulement (pas d'historique). Toujours nommée « récupération COROS N % », jamais « Training Readiness », jamais comparée aux seuils Garmin. |
| Cycle menstruel (opt-in) | `get_menstrual_data_for_date` | `queryMenstruationCycles` | Sans saisie : « No menstrual cycle data found », aucune phase. |
| Seuil lactique | — | `queryFitnessAssessmentOverview` | Allure seuil COROS, `arc_coros_workout.py threshold`. |
| Calendrier, push | `get_scheduled_workouts`, `schedule_workouts` | `queryTrainingSchedule`, `createScheduledWorkout`, `updateScheduledWorkout` | Voir « Envoyer les séances à la montre ». |
| Matériel, pesées, FC de récupération, nutrition | `get_gear`, `get_daily_weigh_ins`… | **aucun équivalent** | Indisponibles, dits comme tels. |

## Les 34 outils (relevés le 22 octobre 2026)

27 en lecture, 7 en écriture.

| Famille | Outils |
|---|---|
| Activités | `querySportRecords`, `getActivityDetail`, `analyzeActivityDetail`, `queryActivityLapData`, `queryCustomActivityLapData` |
| FIT | `downloadActivityFitFiles`, `queryActivityFitFileDownloadUrls` |
| Santé | `querySleepHrv`, `querySleepOverview`, `queryRestingHeartRate`, `queryAvgHeartRate`, `queryDailyHealthData`, `queryHealthCheckTimeSeries`, `queryStressLevel`, `queryStressTimeSeries`, `queryRecoveryStatus`, `queryMenstruationCycles` |
| Forme et charge | `queryTrainingLoadAssessment`, `queryFitnessAssessmentOverview` |
| Profil | `queryUserInfo`, `queryDevices` |
| Calendrier (lecture) | `queryTrainingSchedule`, `queryScheduledWorkoutDetails`, `queryTrainingPlanLibrary`, `queryTrainingPlanDetails`, `queryWorkoutLibrary`, `queryWorkoutDetails` |
| Calendrier (écriture) | `createScheduledWorkout`, `updateScheduledWorkout`, `scheduleWorkout`, `createSingleWorkout`, `updateWorkoutDetails`, `createTrainingPlan`, `updateTrainingPlan` |

Le projet n'utilise pas `createTrainingPlan` / `updateTrainingPlan` (le plan vit dans
`planning/`), ni `createSingleWorkout` / `updateWorkoutDetails` (une séance type n'est
pas nécessaire pour mettre une séance de course à une date).

## Détails techniques

**Adresse.** `https://mcp.coros.com/mcp` (l'URL publiée par COROS) déclare dans ses
métadonnées OAuth la ressource `https://mcpeu.coros.com/mcp` (instance européenne) ; les
clients qui exigent la correspondance, comme Claude Code, doivent utiliser directement
l'URL régionale.

**OAuth.** Métadonnées publiées (`/.well-known/oauth-protected-resource/mcp`,
`/.well-known/oauth-authorization-server`) : enregistrement dynamique de client
(`/connect/register`, client public sans secret), code + PKCE `S256`, jeton de
rafraîchissement et connexion par code d'appareil (`device_code`). Portées
`openid mcp.tools offline_access`. Le projet enregistre son propre client
(« ai-running-coach ») : ses jetons ne touchent pas à ceux d'une IA connectée à la
main. Jeton d'accès : JWT de 30 jours ; le rafraîchissement rend un nouveau jeton
d'accès **et** un nouveau jeton de rafraîchissement (rotation constatée).

**API privée de COROS : non utilisée.** Le jeton du MCP y est refusé (`1019 « Access
token is invalid »`, sonde en lecture seule). Les seules fonctions qu'elle aurait
ajoutées (suppression d'une séance, création de renforcement) restent dans l'app COROS.
Le projet n'utilise jamais la connexion par e-mail et mot de passe de cette API, ni le
projet communautaire [`cygnusb/coros-mcp`](https://github.com/cygnusb/coros-mcp) qui
s'en sert.

## Références

- Page COROS : <https://coros.com/stories/coros-metrics/c/mcp-testing>
- Revue de presse : <https://the5krunner.com/2026/05/13/coros-mcp-ai-data/>
- Premier audit du MCP (3 octobre 2026, avant tout accès authentifié) : issue #168
