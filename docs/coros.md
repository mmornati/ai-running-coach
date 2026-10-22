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
    cron), dont dépend une vraie source `coros`.

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

## Aujourd'hui : COROS via Intervals.icu

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
`idInPlan`, l'identifiant rendu, est un compteur par jour (« 1 »), pas un
identifiant global.

**Règles du schéma de l'outil** (lues dans sa description, appliquées par
`scripts/arc_coros_workout.py validate` ; seules la cible de durée, la plage FC
absolue, la distance et le groupe de répétitions ont été poussés en vrai) :
séances de course, trail et vélo seulement (pas de renforcement) ; pas de cible
de durée en trail (distance, D+ ou libre) ; un seul format d'intensité par
section (zone, pourcentage ou valeurs absolues) ; allure en s/km entières ;
groupes de 1 à 20 répétitions, sans imbrication ; dates d'aujourd'hui à
aujourd'hui + 90 jours.

**Lectures : formes à relever.** La montre n'avait encore rien enregistré : les
lectures santé ont répondu « No data » et `queryRecoveryStatus` « Recovery: -1% /
Level: Unknown » (valeur absente, pas un score). `queryRestingHeartRate` ne prend
qu'un nombre de jours, pas de date. Les formes des activités, des tours, du FIT,
de la HRV et du sommeil restent à relever après les premières séances et nuits.

**Jeton OAuth.** Le jeton d'accès émis est un JWT de l'émetteur
`https://mcpeu.coros.com`, portées `mcp.tools openid offline_access`, valable
**30 jours** (`exp − iat` = 2 592 000 s) ; `offline_access` donne un jeton de
rafraîchissement, donc une durée, pas un accès à d'autres API. Une synchronisation
sans tête devra renouveler et sauvegarder ce jeton avant l'échéance (rotation à
usage unique selon le projet tiers, non vérifiée) : c'est le point encore ouvert.

**API privée de Training Hub : jeton refusé.** Une sonde en lecture seule
(calendrier du jour sur `teameuapi.coros.com`, en-tête `accessToken` puis
`Authorization: Bearer`) a répondu `1019 « Access token is invalid »` dans les deux
cas : le jeton du MCP ne donne pas accès aux fonctions que seule l'API privée offre
(suppression d'une séance, création de renforcement). Elles restent à faire dans
l'app COROS ; le projet n'utilise pas la connexion par mot de passe de l'API privée
(voir plus haut).

## Utilisation manuelle, en interactif (hors périmètre du projet)

Pour interroger vos données COROS dans une conversation, vous pouvez ajouter le
connecteur officiel vous-même, à vos risques, **en plus** de la source
configurée :

- Claude Desktop : Réglages → Connecteurs → connecteur personnalisé, URL
  `https://mcp.coros.com/mcp` (procédure indiquée par COROS).
- Claude Code : non documenté par COROS, mais **testé ici le 22 octobre 2026**
  avec l'URL régionale (`claude mcp add --transport http coros
  https://mcpeu.coros.com/mcp`, puis `/mcp` pour l'autorisation OAuth) ; voir
  [Session authentifiée](#session-authentifiee-22-octobre-2026).

Dans ce cas, le coach n'utilise que les quatre outils de calendrier du skill
[`coros-workout-scheduling`](skills/coros-workout-scheduling.md), pour pousser
des séances après un « oui » explicite ; les lectures (activités, santé) ne sont
dans aucune table de correspondance, rien n'est persisté au contrat `arc`
automatiquement, et la synchronisation sans tête ne s'en sert jamais.

## Références

- Page COROS : <https://coros.com/stories/coros-metrics/c/mcp-testing>
- Revue de presse : <https://the5krunner.com/2026/05/13/coros-mcp-ai-data/>
- Projet tiers de référence : <https://github.com/xiaolouJB/ai-running-coach> (commit `5f2c4a2018e52f9fdcabdc7adf15cb0ee7aa33fc`, `ADAPTERS.md`)
- Projet non officiel : <https://github.com/cygnusb/coros-mcp>
- Sonde : `POST https://mcp.coros.com/mcp` (401) et les deux documents `/.well-known/` ci-dessus, le 3 octobre 2026
