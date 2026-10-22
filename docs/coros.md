# Montres COROS (audit du MCP officiel, #168)

Cette page trace l'audit du **MCP officiel de COROS** et la décision prise pour
le projet. Date de l'audit : 3 octobre 2026. Légende utilisée partout :
**vérifié** = constaté par nous (sonde HTTP sans authentification, ou lecture
d'une source publique citée) ; **non vérifié** = rapporté par un tiers ou
non confirmable sans compte COROS autorisé (nous n'avons jamais tenté de nous
authentifier).

## Décision

!!! success "Décision : pas de source `coros` — Intervals.icu reste le chemin supporté"
    Le MCP officiel est **ajoutable à la main pour un usage interactif**
    (voir ci-dessous), mais il est **hors des tables de correspondance**, jamais
    utilisé par la synchronisation sans tête (`/garmin-daily-sync`) et jamais
    installé par `install.sh`. Les athlètes COROS passent par
    [Intervals.icu](intervals-setup.md) (`./install.sh --source intervals`).

!!! info "Mise à jour du 22 octobre 2026 : poussée de séances en interactif"
    Une session authentifiée a permis de relever la vraie liste d'outils et de
    pousser une séance réelle jusqu'à la montre (voir
    [Session authentifiée](#session-authentifiee-22-octobre-2026)). Deux des trois
    conditions ci-dessous sont levées (liste d'outils, écriture de séances) : le
    skill [`coros-workout-scheduling`](skills/coros-workout-scheduling.md) pousse
    les séances planifiées au calendrier COROS, **en interactif seulement**, avec
    un « oui » explicite. Reste ouverte : l'exécution sans tête (jeton OAuth en
    cron), dont dépend une vraie source `coros`. Avec Intervals.icu, la
    [configuration préconisée](#configuration-preconisee-intervalsicu-coros)
    reste de laisser Intervals.icu envoyer les séances à COROS.

Pourquoi pas une source `coros` :

1. **Les noms d'outils ne sont pas vérifiables à la source.** `tools/list`
   exige un jeton OAuth ; le serveur n'est pas open source. Les seuls noms
   connus viennent d'un projet tiers (voir « Références »), qui en annonce 22
   fin juillet 2026, contre 15 au lancement selon une revue de presse de mai
   2026 ; le journal des versions de COROS montre des ajouts en juin puis en
   septembre 2026. La liste évolue et nous ne pouvons pas l'épingler à un
   commit comme pour `garmin-mcp` ou `intervals-icu-mcp`. Règle du projet :
   jamais de nom d'outil deviné.
2. **L'exécution sans tête n'est pas démontrée.** L'authentification est
   OAuth 2.0 interactive (code d'autorisation + PKCE) ; selon le tiers, le
   jeton d'accès dure environ 30 jours et le jeton de rafraîchissement est
   **à usage unique** (rotation). Le support documenté par COROS ne cite pas
   Claude Code ni opencode (voir ci-dessous). Un cron qui rafraîchit seul un
   jeton à rotation, sans client MCP qui le persiste, n'est pas un socle
   acceptable pour `garmin-daily-sync`.
3. **Le gain est partiel.** Le MCP officiel apporterait des tours (laps)
   détaillés, le FIT et des mesures de récupération ; mais l'écriture de
   séances, annoncée par COROS le 21 septembre 2026, n'est confirmée par
   aucune source indépendante (voir plus bas), et le FIT est plafonné à 50
   demandes de fichiers par jour.

Ce qui ferait changer la décision : un `tools/list` public ou épinglé, un
support documenté de Claude Code (jeton persistant en mode sans tête), et une
écriture de séances confirmée. Le cas échéant, l'implémentation suivrait
exactement la méthode de #68 (table de correspondance, `install.sh --source`,
stubs, `coach-doctor`).

## Configuration préconisée : Intervals.icu + COROS

!!! tip "La version préconisée"
    Montre COROS **connectée à Intervals.icu**, `./install.sh --source intervals`,
    et dans Intervals.icu : *Settings → COROS*, **envoi des séances planifiées
    activé**. Le coach pousse les séances vers Intervals.icu, qui les envoie
    lui-même au calendrier COROS (les 7 prochains jours). Le MCP officiel de
    COROS n'est pas nécessaire ; s'il est installé (`--coros`, voir
    [Installation](#installation-une-seule-connexion-pour-toutes-les-ia)), il sert
    à vérifier, en lecture, qu'une séance est bien arrivée sur la montre.

## Installation : une seule connexion pour toutes les IA

```bash
./install.sh --source intervals --coros
```

`--coros` fonctionne avec n'importe quelle source. Comme pour Garmin
(`garmin-mcp-auth` + `garmin-mcp stdio`) :

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
  remplace aussi le jeton de rafraîchissement à chaque fois. Vérifié le 22 octobre 2026
  sur le vrai serveur : rafraîchissement forcé (nouveaux jetons, 30 jours), et relais
  avec un jeton d'accès refusé → rafraîchi puis 34 outils listés. Pas encore mesurés : la
  durée de vie du jeton de rafraîchissement et le sort de l'ancien après rotation.
- **Vérifier :** `python3 scripts/arc_coros_auth.py status` (sans réseau) ou `verify`
  (appel réel du MCP). **Retirer :** `./install.sh --no-coros` (ne touche jamais une
  entrée `coros` ajoutée à la main), puis `arc_coros_auth.py logout`.

Vous aviez ajouté le serveur à la main (`claude mcp add … coros https://mcpeu.coros.com/mcp`) ?
Retirez-le (`claude mcp remove coros`), sinon il masque le relais : Claude Code donne la
priorité à une entrée locale sur celle du projet, et vous auriez deux connexions.

**Pourquoi ce chemin plutôt que le MCP officiel de COROS :**

- **Tout est déjà codé.** Lectures (activités, sommeil, HRV, FC de repos), FIT,
  poussée des séances avec les cibles personnelles dans la syntaxe native,
  vérification des doublons avant chaque poussée, relecture après : c'est le
  chemin `[data].source = "intervals"` du projet, sans rien de spécifique à COROS.
- **Il tourne sans surveillance.** La synchronisation quotidienne (`/garmin-daily-sync`)
  sait déjà lire et écrire sur Intervals.icu ; le jeton OAuth du MCP COROS, lui,
  n'a pas encore été démontré en cron.
- **On peut corriger une erreur.** Une séance modifiée ou supprimée dans
  Intervals.icu l'est aussi sur COROS tant qu'elle est dans la fenêtre de 7 jours
  (rapporté sur le forum Intervals.icu) ; le MCP officiel n'a aucun outil de
  suppression ni de déplacement.
- **Une seule source de vérité.** Le plan vit dans `planning/`, puis dans le
  calendrier Intervals.icu ; COROS n'en reçoit qu'une copie. Pousser la même
  séance par les deux chemins la ferait apparaître deux fois sur la montre.

**Limites de ce chemin** (rapportées sur le forum Intervals.icu, non vérifiées par nous) :

- seulement les **7 prochains jours** sont envoyés ; une séance plus lointaine
  arrive quand la fenêtre l'atteint ;
- **une seule métrique d'intensité par séance** : Intervals.icu envoie à COROS la
  FC *ou* l'allure, et les blocs écrits dans l'autre arrivent sans cible
  ([fil d'avril-août 2026](https://forum.intervals.icu/t/coros-integration-mixed-pace-hr-intervals/127171),
  non corrigé pour COROS). Le projet écrit déjà ses séances en FC uniquement ;
- des envois **silencieusement bloqués** par des zones FC non renseignées dans
  Intervals.icu, une erreur de syntaxe ou un filtre dans les réglages de la
  connexion ([fil d'août 2026](https://forum.intervals.icu/t/coros-training-plan-is-created-but-planed-workouts-are-not-syncing/131097)) ;
- il faut parfois ajouter le plan « Intervals.icu Training Plan » au calendrier
  de l'app COROS ([annonce de la connexion](https://forum.intervals.icu/t/coros-support-added/37006)).

**Constaté par nous le 22 octobre 2026** (envoi activé, première semaine, relue par
le MCP COROS) :

- les séances arrivent dans un **plan COROS « Plan d'entr. Intervals.icu »**, pas en
  séances isolées ; `queryTrainingSchedule` les liste. Ce plan n'est **pas modifiable
  par le MCP** (« Editable via MCP: no ») : on corrige dans Intervals.icu ;
- la fenêtre couvrait bien 7 jours (22 → 28 octobre) ; la séance du 29 n'était pas
  encore envoyée ;
- la **structure arrive** (blocs, durées, répétitions) et le nom est gardé tel quel ;
- **les cibles FC en bpm absolus (`137-149bpm`) ne sont PAS arrivées** : aucune
  section n'avait de cible d'intensité sur la montre. Testé ensuite sur des séances
  d'essai (supprimées depuis) : `81-88% LTHR` arrive en 137-149 bpm, `73-80% HR` en
  136-149, `Z2 HR` avec les zones d'Intervals.icu (144-152), et `137-149bpm` toujours
  sans cible. **Le projet écrit donc la FC en % du seuil FC d'Intervals.icu**, à une
  décimale pour retomber pile sur les bornes (`80.6-87.7% LTHR` → 137-149, relu sur la
  montre) : `arc_workout_targets.py --icu-lthr-bpm` ;
- une séance **supprimée dans Intervals.icu disparaît de COROS** (vérifié sur ces
  séances d'essai) ;
- la **description est tronquée** : COROS ne garde que le premier paragraphe, coupé
  vers 250 caractères. Ce qui compte pour la séance doit donc tenir dans ce premier
  paragraphe ;
- le **renforcement arrive** (séance de type force, avec son nom et sa description,
  sans exercices) ; pour un renforcement structuré, voir
  [Renforcement : vos séances types](#renforcement-vos-seances-types-23-octobre-2026) ;
- la séance faite revient dans Intervals.icu avec l'appareil « COROS PACE 4 Pro », et
  son FIT se télécharge par `download_fit.py` sans changement (3 786 points : FC,
  allure, altitude, GPS, puissance, temps de contact, oscillation, longueur de pas).

Le skill [`coros-workout-scheduling`](skills/coros-workout-scheduling.md) ne
pousse lui-même que si la source n'est pas Intervals.icu (par exemple Strava),
ou sur demande explicite de l'athlète.

### Les données qui remontent

Pour les autres appareils : [Quelle source pour mon appareil ?](configuration.md#quelle-source-pour-mon-appareil).

La montre synchronise ses activités et une partie de son bien-être vers
Intervals.icu (via l'intégration entre les deux comptes : sommeil et FC de
repos ; la HRV n'arrive pas chez tous les utilisateurs selon le
[forum Intervals.icu](https://forum.intervals.icu/t/coros-support-added/37006)),
puis `./install.sh --source intervals`
installe le serveur MCP épinglé `intervals-icu-mcp`. Limites déjà documentées :
pas de score de readiness (HRV + FC de repos uniquement), pas de FC de
récupération ni de `splits` par km ; séances poussées dans la syntaxe native
d'Intervals.icu (étapes structurées, repli en texte libre si l'analyse échoue, #165). Détail :
[Configuration Intervals.icu](intervals-setup.md#fonctionnalites-et-champs-indisponibles-avec-cette-source).
Le FIT d'une activité s'obtient par l'API REST d'Intervals.icu
([Fichiers FIT](intervals-setup.md#fichiers-fit)).

## Ce que propose le MCP officiel

### Faits vérifiés (sonde sans authentification, 3 octobre 2026)

| Fait | Preuve |
|---|---|
| Point d'accès `https://mcp.coros.com/mcp`, transport HTTP | `POST` sans jeton → `401` avec `www-authenticate: Bearer resource_metadata="https://mcpeu.coros.com/.well-known/oauth-protected-resource/mcp"` |
| Authentification **OAuth 2.0**, portées `openid mcp.tools offline_access` | document `https://mcpeu.coros.com/.well-known/oauth-protected-resource/mcp` (`bearer_methods_supported: header`) |
| Serveur d'autorisation `https://mcpeu.coros.com`, **PKCE S256**, **enregistrement dynamique de client** (`/connect/register`), flux annoncés dont `authorization_code`, `refresh_token` et `device_code` | document `https://mcpeu.coros.com/.well-known/oauth-authorization-server` |
| Instance qui a répondu (depuis l'Europe) | en-tête `mr: mcp_eu_prod` ; COROS dit avoir fusionné les URL régionales le 19 mai 2026 ; `https://mcpcn.coros.com/mcp` rapporté par un tiers, non sondé |

L'enregistrement dynamique et le flux appareil sont techniquement compatibles
avec un client MCP en ligne de commande, mais cela ne prouve pas que COROS
accepte un client arbitraire : **non vérifié**.

### Faits rapportés par COROS (page officielle, non vérifiés par nous)

Source : <https://coros.com/stories/coros-metrics/c/mcp-testing> (la page
d'aide <https://support.coros.com/hc/en-us/articles/5146420791060> renvoie 403
à un client automatisé).

- Clients cités : ChatGPT (mode développeur), Claude Desktop (connecteur
  personnalisé), Cursor, Gemini CLI. **Claude Code et opencode ne sont pas
  cités.**
- Lecture : activités et splits, métriques de forme (VO2max, puissance de
  course, allure seuil, prédictions), charge, récupération, santé quotidienne
  (pas, calories, sommeil, HRV, stress, FC de repos), profil et appareils,
  fichiers `.fit` (GPS, seconde par seconde), cycle menstruel.
- Écriture : création/édition de plans et de séances (course sur route, trail,
  vélo), plans de 4 à 16 semaines, synchronisation vers la bibliothèque ou le
  calendrier jusqu'à 14 jours à l'avance. Selon le journal des versions de
  COROS, l'écriture n'a été ajoutée que le **21 septembre 2026** : ce n'est
  donc pas une contradiction avec les sources plus anciennes (revue de presse
  de mai 2026 : lancement en lecture seule ; projet tiers fin juillet 2026 :
  erreurs `Unknown tool` sur les outils d'écriture), mais aucune source
  indépendante postérieure ne la confirme : écriture **non vérifiée**.
- Limites : 50 demandes de fichiers `.fit` par jour ; accès « uniquement après
  autorisation explicite » de l'utilisateur.
- Calendrier (journal des versions de la page) : lancement en lecture seule
  le 5 mai 2026 (page datée du 4 mai), URL régionales fusionnées en une seule
  le 19 mai, ajout des splits, du FIT, du stress et de la HRV de sommeil le
  22 juin, écriture le 21 septembre 2026. Aucune des sources consultées ne
  mentionne une version d'application (la « v4.8.8 » et le « juillet 2026 »
  de l'issue #168 n'y apparaissent pas).

### Noms d'outils rapportés par un tiers (non vérifiés)

Relevés dans `ADAPTERS.md` de `xiaolouJB/ai-running-coach` au commit
`5f2c4a2018e52f9fdcabdc7adf15cb0ee7aa33fc`. Ce dépôt les dit obtenus par un
`tools/list` en direct, mais nous ne pouvons pas le confirmer : **tous « non
vérifiés »** pour ce projet, informatifs seulement.

| Besoin | Outil rapporté (non vérifié) | Note rapportée |
|---|---|---|
| Liste d'activités | `querySportRecords` | texte formaté, non JSON ; 404 intermittents rapportés |
| Détail d'une activité | `getActivityDetail` | charge, effets d'entraînement, effort perçu |
| Tours (laps) | `queryActivityLapData`, `queryCustomActivityLapData` | allure, FC, puissance, contact au sol, cadence |
| FIT | `queryActivityFitFileDownloadUrls`, `downloadActivityFitFiles` | 50 fichiers/jour |
| HRV | `querySleepHrv` | remplace un ancien outil supprimé |
| Sommeil | `querySleepData` | |
| FC de repos | `queryRestingHeartRate` | |
| Stress | `queryStressLevel`, `queryStressTimeSeries` | |
| Forme / prédictions | `queryFitnessAssessmentOverview` | |
| Charge | `queryTrainingLoadAssessment` | rapport de charge fourni |
| Récupération | `queryRecoveryStatus` | pourcentage et heures estimées |
| Planning existant | `queryTrainingSchedule` | |
| Profil / appareils | `queryUserInfo`, `queryDevices` | |
| Cycle | `queryMenstruationCycles` | |

Le projet communautaire non officiel
[`cygnusb/coros-mcp`](https://github.com/cygnusb/coros-mcp) (26 outils, login
e-mail/mot de passe, indépendant de COROS) n'a **pas** été retenu : il passe
par une API privée avec les identifiants du compte.

## Session authentifiée (22 octobre 2026)

Le serveur a été ajouté à Claude Code et autorisé par OAuth avec un compte
COROS réel (montre COROS PACE 4 Pro associée le jour même). Tout ce qui suit a
été constaté par nous sur cette session.

**URL.** `https://mcp.coros.com/mcp` (l'URL publiée par COROS) est refusée par
Claude Code : ses métadonnées OAuth déclarent la ressource
`https://mcpeu.coros.com/mcp`, et Claude Code exige qu'elles correspondent
(« Protected resource … does not match expected »). Il faut déclarer
directement l'URL régionale :

```bash
claude mcp add --transport http coros https://mcpeu.coros.com/mcp
```

puis `/mcp` → `coros` → *Authenticate* (redémarrer la session si le serveur a été
ajouté pendant qu'elle tournait).

**Liste relevée : 34 outils**, dont 27 en lecture et 7 en écriture. Tous les noms
de la liste du projet tiers ci-dessous y figurent, sauf `querySleepData` (le
sommeil passe par `querySleepOverview`).

| Famille | Outils |
|---|---|
| Activités | `querySportRecords`, `getActivityDetail`, `analyzeActivityDetail`, `queryActivityLapData`, `queryCustomActivityLapData` |
| FIT | `downloadActivityFitFiles`, `queryActivityFitFileDownloadUrls` (50 fichiers par jour selon COROS) |
| Santé | `querySleepHrv`, `querySleepOverview`, `queryRestingHeartRate`, `queryAvgHeartRate`, `queryDailyHealthData`, `queryHealthCheckTimeSeries`, `queryStressLevel`, `queryStressTimeSeries`, `queryRecoveryStatus`, `queryMenstruationCycles` |
| Forme et charge | `queryTrainingLoadAssessment`, `queryFitnessAssessmentOverview` |
| Profil | `queryUserInfo`, `queryDevices` |
| Calendrier (lecture) | `queryTrainingSchedule`, `queryScheduledWorkoutDetails`, `queryTrainingPlanLibrary`, `queryTrainingPlanDetails`, `queryWorkoutLibrary`, `queryWorkoutDetails` |
| Calendrier (écriture) | `createScheduledWorkout`, `updateScheduledWorkout`, `scheduleWorkout`, `createSingleWorkout`, `updateWorkoutDetails`, `createTrainingPlan`, `updateTrainingPlan` |

**Aucun outil de suppression ni de déplacement** : une séance poussée par erreur
se retire dans l'app COROS.

**Écriture de séances : constatée.** `createScheduledWorkout` a créé la séance
du jour (40 min à 137-149 bpm, puis 4 × 100 m + 1 min de récupération) ;
`queryScheduledWorkoutDetails` l'a relue à l'identique (COROS y ajoute son
estimation de durée, de distance et de charge) ; elle est apparue sur la montre
après synchronisation. Réponse : texte formaté, la structure de la séance en JSON.
`idInPlan`, l'identifiant rendu, est un petit compteur par jour (« 1 », « 2 »),
pas un identifiant global ; il ne commence pas toujours à 1 (« 2 » pour la
première séance du 23 octobre).

**Modification de séances : constatée le 22 octobre 2026.** Une séance de test
créée sur le lendemain (20 min, 137-149 bpm) est relue `Editable via MCP: yes` ;
`updateScheduledWorkout` avec le cours entier (25 min, 130-145 bpm, nom et
description changés) la remplace : relecture à l'identique, même `idInPlan`, une
seule séance ce jour-là (pas de doublon). La séance de test reste à supprimer
dans l'app COROS.

**Trail : cible de D+ et étapes libres, constatées le 22 octobre 2026.** Une séance
de trail (échauffement libre à 137-149 bpm, 4 × [30 m de D+ à 155-168 bpm +
récupération libre], retour au calme libre à 130-145 bpm) est acceptée, relue à
l'identique et affichée par l'app COROS : étapes libres « Manuel » (bouton Tour),
répétition « 30 m » avec l'icône de montée, cibles FC gardées, « 10 séries ».
COROS ne donne alors ni durée, ni distance, ni charge estimées (les étapes libres
en sont exclues). La durée prévue d'une étape va donc dans la description.

**Règles du schéma de l'outil** (lues dans sa description, appliquées par
`scripts/arc_coros_workout.py validate` ; seules la cible de durée, la plage FC
absolue, la distance et le groupe de répétitions ont été poussés en vrai) :
séances de course, trail et vélo seulement (pas de création de renforcement, voir
ci-dessous) ; pas de cible
de durée en trail (distance, D+ ou libre) ; un seul format d'intensité par
section (zone, pourcentage ou valeurs absolues) ; allure en s/km entières ;
groupes de 1 à 20 répétitions, sans imbrication ; dates d'aujourd'hui à
aujourd'hui + 90 jours.

### Renforcement : vos séances types (23 octobre 2026)

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

Constaté sur deux séances créées par l'athlète (« Renfo lombaires », « Renfo descentes ») :

- `queryWorkoutLibrary` les liste avec leur durée estimée et leur nombre de séries ;
  `queryWorkoutDetails` ne rend que le nom et le sport : **le coach ne voit pas les
  exercices**, seule l'app (ou la montre) fait foi ;
- `scheduleWorkout` a posé « Renfo descentes » sur une date ; `queryTrainingSchedule` l'a
  relue comme « Standalone workout (scheduled from the workout library) », et la séance
  est **arrivée sur la montre avec ses exercices** ;
- la date reçoit une **copie figée** : modifier ensuite la séance type ne la change pas, et
  le MCP ne peut pas modifier la copie. Finir les retouches avant de planifier ; supprimer
  ou déplacer se fait dans l'app ;
- `idInPlan` n'est pas unique : cette copie et une séance envoyée par Intervals.icu à une
  autre date avaient le même. Une séance se désigne par sa date **et** son `idInPlan` ;
- dans l'app, un côté = un exercice à part (ou une seule entrée « par côté »), les tours
  sont un bloc « Répéter N fois », un exercice peut rester hors du bloc. Noms du catalogue
  en français : « Crunch », « Chien d'oiseau » (bird-dog), « Couché sur le dos Pont des
  fessiers », « Extension mollets debout », « Gainage latéral », « Étirement du chat et de
  la vache ». Le curl-up de McGill n'a pas d'équivalent exact : « Crunch » avec une note
  (tenir 10 s, une jambe pliée, mains sous les lombaires).

**Un seul canal par séance** : avec Intervals.icu comme source, un renforcement planifié
ainsi n'est pas poussé vers Intervals.icu, sinon sa version texte arrive aussi sur la
montre (deux séances le même jour).

**Lectures : formes à relever.** La montre n'avait encore rien enregistré : les
lectures santé ont répondu « No data » et `queryRecoveryStatus` « Recovery: -1% /
Level: Unknown » (valeur absente, pas un score). `queryRestingHeartRate` ne prend
qu'un nombre de jours, pas de date. La HRV et le sommeil restent à relever après
les premières nuits.

**Activités : relevées le 22 octobre 2026** (première séance) :

- `querySportRecords` : une ligne par séance, avec `labelId` et `sportType` (codes
  d'activité : 100 course, 102 trail…), horodatages de début et de fin, durée,
  distance, allure, FC moyenne. Le champ « Location » contient le **nom de la séance
  planifiée**, pas un lieu ;
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
  km réguliers, et le projet ne les recopie pas dans `splits` ;
- `queryActivityFitFileDownloadUrls` : une URL de fichier FIT standard (produit
  « COROS PACE 4 Pro »), lisible par `fitparse` et par la normalisation du projet
  sans changement. Avec Intervals.icu comme source, le même FIT s'obtient déjà par
  `download_fit.py` : le MCP n'apporte rien de plus ici.

**Jeton OAuth.** Le jeton d'accès émis est un JWT de l'émetteur
`https://mcpeu.coros.com`, portées `mcp.tools openid offline_access`, valable
**30 jours** (`exp − iat` = 2 592 000 s) ; `offline_access` donne un jeton de
rafraîchissement, donc une durée, pas un accès à d'autres API. Une synchronisation
sans tête devra renouveler et sauvegarder ce jeton avant l'échéance (rotation à
usage unique selon le projet tiers) : c'est le point encore ouvert.

**Client OAuth à nous : constaté le 22 octobre 2026.** Le serveur publie ses
métadonnées (`/.well-known/oauth-protected-resource/mcp`,
`/.well-known/oauth-authorization-server`) : enregistrement dynamique de client
(`/connect/register`, client public sans secret), code + PKCE `S256`, jeton de
rafraîchissement et connexion par code d'appareil (`device_code`). Une sonde en
bibliothèque standard a enregistré un client « ai-running-coach (sonde) » (201),
obtenu un jeton après validation de l'athlète dans son navigateur (retour sur
`127.0.0.1`, depuis WSL2), puis appelé le MCP **en HTTP direct, sans l'IA** :
`initialize`, `tools/list` (34 outils), `queryTrainingSchedule`. Le rafraîchissement
rend un nouveau jeton d'accès (30 jours) **et un nouveau jeton de rafraîchissement**
(rotation constatée), et le MCP répond avec le nouveau jeton. Une synchronisation
sans tête est donc possible avec des jetons propres au projet, sans toucher à ceux
de Claude Code ; restent à mesurer la durée de vie du jeton de rafraîchissement et
le refus de l'ancien après rotation.

**API privée de Training Hub : jeton refusé.** Une sonde en lecture seule
(calendrier du jour sur `teameuapi.coros.com`, en-tête `accessToken` puis
`Authorization: Bearer`) a répondu `1019 « Access token is invalid »` dans les deux
cas : le jeton du MCP ne donne pas accès aux fonctions que seule l'API privée offre
(suppression d'une séance, création de renforcement). Elles restent à faire dans
l'app COROS (le renforcement créé dans l'app se planifie ensuite par le MCP, voir
plus haut) ; le projet n'utilise pas la connexion par mot de passe de l'API privée
(voir plus haut).

## Utilisation manuelle, en interactif (hors périmètre du projet)

`./install.sh --coros` (voir [Installation](#installation-une-seule-connexion-pour-toutes-les-ia))
remplace cet ajout manuel. Pour interroger vos données COROS sans réinstaller, vous pouvez
encore ajouter le connecteur officiel vous-même, à vos risques, **en plus** de la source
configurée :

- Claude Desktop : Réglages → Connecteurs → connecteur personnalisé, URL
  `https://mcp.coros.com/mcp` (procédure indiquée par COROS).
- Claude Code : non documenté par COROS, mais **testé ici le 22 octobre 2026**
  avec l'URL régionale (`claude mcp add --transport http coros
  https://mcpeu.coros.com/mcp`, puis `/mcp` pour l'autorisation OAuth) ; voir
  [Session authentifiée](#session-authentifiee-22-octobre-2026).

Dans ce cas, avec Intervals.icu comme source, le coach continue de pousser vers
Intervals.icu et ne lit le calendrier COROS que pour vérifier l'arrivée des séances ;
avec une autre source, il pousse par les quatre outils de calendrier du skill
[`coros-workout-scheduling`](skills/coros-workout-scheduling.md), après un « oui » explicite ; les lectures (activités, santé) ne sont
dans aucune table de correspondance, rien n'est persisté au contrat `arc`
automatiquement, et la synchronisation sans tête ne s'en sert jamais.

## Références

- Page COROS : <https://coros.com/stories/coros-metrics/c/mcp-testing>
- Revue de presse : <https://the5krunner.com/2026/05/13/coros-mcp-ai-data/>
- Projet tiers de référence : <https://github.com/xiaolouJB/ai-running-coach> (commit `5f2c4a2018e52f9fdcabdc7adf15cb0ee7aa33fc`, `ADAPTERS.md`)
- Projet non officiel : <https://github.com/cygnusb/coros-mcp>
- Sonde : `POST https://mcp.coros.com/mcp` (401) et les deux documents `/.well-known/` ci-dessus, le 3 octobre 2026
