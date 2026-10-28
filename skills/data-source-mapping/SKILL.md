---
name: data-source-mapping
description: Tool mapping when the data source is not Garmin — Garmin ↔ intervals.icu (hhopke/intervals-icu-mcp, icu_* tools), Garmin ↔ Strava (r-huijts/strava-mcp 1.2.1) and Garmin ↔ COROS (official COROS MCP relay). Covers which tool replaces which, response shapes, identifiers, durations, Strava streams, intervals.icu FIT download, and every Garmin feature with no port (explained, never guessed or simulated). MANDATORY — read in full before the first data-tool call when `[data].source` is `intervals`, `strava` or `coros`, or before calling an `icu_*`, Strava or `coros` tool with another primary source. Not needed with `[data].source = "garmin"` and no COROS relay.
---

# Correspondance des outils par source de données (#68, #164, #168)

Sorti d'AGENTS.md pour ne pas charger ces tables dans chaque requête : seules les installations qui
utilisent intervals.icu, Strava ou COROS en ont besoin. Texte inchangé, sauf le paragraphe « v5.6.0 » (outil d'écriture intervals.icu jamais
appelé), resté dans AGENTS.md pour être toujours chargé. Les renvois (« voir plus
haut », « Bilan matinal », « Splits par km depuis le FIT », « Matériel », « Backends MCP ») désignent
les sections d'`AGENTS.md`, qui restent valables pour toutes les sources.

### Correspondance des outils — Garmin ↔ intervals.icu (#68)

Ne s'applique que si `[data].source = "intervals"`. Même déclencheur, même
cadence, même persistance MD, même contrat `arc` **pour les lectures**.
**Le push de séances n'est PAS un simple changement de nom d'outil** — voir
l'avertissement sous la table. Noms et formes de réponse vérifiés dans le code
source du serveur retenu (`src/intervals_icu_mcp/tools/*.py`, `client.py`,
`response_builder.py`, fork `hhopke/intervals-icu-mcp` au commit `92a630b` (v5.6.0)
— épinglé par `INTERVALS_MCP_REF` dans `install.sh`, documenté dans
`docs/intervals-setup.md`, #165), jamais devinés. **Tous les outils de ce serveur
portent le préfixe `icu_`** (`icu_get_wellness_for_date`…) ; l'ancien serveur
(eddmann, épinglé avant #165) exposait les mêmes outils SANS préfixe : si les outils
appelables n'ont pas ce préfixe, l'installation est périmée — le dire à l'athlète
(`./install.sh --source intervals`, nouvelle session, `docs/update.md` ; `/coach-doctor`
check `intervals_mcp_pin`) et ne pousser aucune séance en attendant.

| Besoin | Outil `garmin` | Outil `intervals` | Note |
|---|---|---|---|
| HRV nocturne | `get_hrv_data` | `icu_get_wellness_for_date` (`heart.hrv_rmssd`/`heart.hrv_sdnn`) | Un seul appel intervals.icu couvre HRV + FC de repos + sommeil. |
| FC de repos | `get_rhr_day` | `icu_get_wellness_for_date` (`heart.resting_hr`) | Idem — ne PAS appeler `icu_get_wellness_data` (plage de dates) pour un seul jour. |
| Sommeil | `get_sleep_data` | `icu_get_wellness_for_date` (`sleep.*`) | |
| Readiness algorithmique | `get_training_readiness` | **aucun équivalent** | intervals.icu n'expose que `subjective.readiness` — une valeur manuelle dans le champ wellness du jour, qui peut venir de l'athlète OU d'un appareil tiers synchronisé (Oura, Whoop...), jamais un score calculé par intervals.icu lui-même — jamais présenté comme équivalent au Training Readiness Garmin. Dire explicitement l'indisponibilité (voir `[health].morning_check` ci-dessus). |
| Activités récentes | `get_activities` / `get_activities_by_date` | `icu_get_recent_activities` | |
| Détail d'une activité | `get_activity` | `icu_get_activity_details` | Pas de fréquence cardiaque de récupération (HRR/`recovery_hr_bpm`) ni de `splits` par km sur ce serveur — HRR omise, jamais inventée ; les `splits` : `arc_index.py splits <id>` les calcule depuis le FIT (voir « Splits par km depuis le FIT »). Pas de champ équivalent à `bmr_calories` identifié non plus : `calories_bmr_kcal` reste omis pour une activité synchronisée depuis cette source, jamais deviné. Renseigner `intervals_activity_id` (chaîne, ex. `"i12345678"`) sur `activities/*.md` au lieu de `garmin_activity_id` (entier) — `workspace-data-contract`. |
| Durées d'une activité | `get_activity` | `icu_get_activity_details` : `duration_s` ← `elapsed_time_seconds` (durée totale, pauses comprises), `moving_duration_s` ← `moving_time_seconds` | **Jamais `duration_s` depuis `icu_get_recent_activities`** : cette liste ne renvoie que `moving_time_seconds` (temps en mouvement). Un `duration_s` égal au temps en mouvement fait refuser par la validation un temps en zone pourtant juste (`time_in_zone_s` > `duration_s`). |
| Événements planifiés | `get_calendar_events` / `get_scheduled_workouts` | `icu_get_calendar_events` / `icu_get_upcoming_workouts` | |
| Détail d'une séance planifiée | `get_workout_by_id` | `icu_get_event` | Ne renvoie que id/date/name/category/description/type/tags/metrics — jamais de structure de séance (le résultat du parsing n'est écho que sur la réponse de `icu_create_event`/`icu_update_event`/`icu_bulk_create_events`). |
| Push d'une séance | `schedule_workouts` / `schedule_week` | `icu_create_event` / `icu_bulk_create_events` | **Pas un remplacement direct** — charger le skill `intervals-icu-best-practices` (pas `garmin-workout-scheduling`) : `icu_create_event`/`icu_update_event` n'ont PAS de paramètre structuré (pas de `workout_doc`), mais la `description` d'un événement WORKOUT écrite dans la **syntaxe native intervals.icu** est analysée côté serveur en étapes structurées (cibles FC/zone de `scripts/arc_workout_targets.py` (#60) ; l'écho `workout_parsed`/`workout_steps` de la réponse d'écriture dit si l'analyse a réussi) — **repli : texte libre** quand `workout_parsed` vaut `false` ; une plage d'allure absolue n'est pas dans la syntaxe documentée (elle va dans le nom de l'événement) ; aucun upsert n'existe (vérifier `icu_get_calendar_events` avant chaque push, pas de réutilisation de `workout_id`) ; la vérification post-push porte sur l'écho d'analyse puis sur les champs que `icu_get_event` renvoie réellement ; en bulk, mêmes noms de champs que `icu_create_event` (`event_type`, `duration_seconds`…), les noms bruts de l'API sont refusés. |
| Matériel (inventaire) | `get_gear` (appeler avec `include_stats=False` : le défaut du serveur est `True`, un appel API par matériel) | `icu_get_gear_list` | **Référence seulement** côté intervals.icu (id, nom, type, `usage.total_distance_km`) — jamais une attribution. Voir « Matériel » sous la table (#133). |
| Matériel attaché à une activité | `get_activity_gear` | **aucun équivalent** | Le serveur intervals.icu n'a aucun champ matériel sur les activités : `gear_id` reste déclaré en chat ou `(par défaut)`, jamais deviné. |
| Attacher un matériel à une activité | `add_gear_to_activity` (ÉCRITURE Garmin, confirmation explicite, jamais en headless) | **aucun équivalent** | Voir « Matériel » sous la table. |
| Modifier/supprimer une séance planifiée | `delete_workout` / `unschedule_workout` | `icu_update_event` / `icu_delete_event` | `icu_update_event` exige un `event_id` déjà existant — jamais un upsert. `icu_delete_event` : en mode `safe` du serveur (défaut), seuls les événements datés de demain ou plus tard sont supprimés. |
| Profil athlète (référence, jamais substitué au profil déclaré) | — | `icu_get_athlete_profile` | |
| Charge/forme (vocabulaire générique du projet, jamais les noms TrainingPeaks) | — (calculée par `scripts/arc_index.py`) | `icu_get_fitness_summary` | Ne jamais citer `ctl`/`atl`/`form` sous ces noms dans une réponse — reformuler en charge/condition/fatigue/forme comme partout ailleurs (`docs/marques.md`). |

### Correspondance des outils — Garmin ↔ Strava (#164)

Ne s'applique que si `[data].source = "strava"` **avec le serveur communautaire
`r-huijts/strava-mcp`** (version 1.2.1 = commit `a68112aa12a88909593db0f4b1ac0f6aebed6e3a`, le `gitHead` publié sur npm — **pas** la tête de `main`, qui a
des outils non publiés). Noms et paramètres vérifiés dans le `dist/` du tarball npm 1.2.1 et dans le code
source de ce commit (`src/server.ts`, `src/tools/*.ts`) ; les
réponses sont du **texte formaté** (pas du JSON structuré, sauf les blocs « Complete Lap Data » /
« Raw Athlete Zone Data » et le flux), jamais un schéma stable : lire les valeurs
telles qu'imprimées, sans en déduire un champ absent.

| Besoin | Outil `garmin` | Outil `strava` | Note |
|---|---|---|---|
| Activités récentes | `get_activities` / `get_activities_by_date` | `get-recent-activities` (`perPage`) ; `get-all-activities` (`startDate`, `endDate`, `activityTypes`, `sportTypes`, `maxActivities`, `maxApiCalls`) | Une ligne de texte par activité : nom, **`(ID: <entier>)`**, distance en mètres, date (jour seulement, au format local du serveur) — pas de type — pas d'heure précise ni de durée dans `get-recent-activities`. Limites d'API Strava : voir `docs/strava-setup.md`. |
| Détail d'une activité | `get_activity` | `get-activity-details` (`activityId`, entier) | Texte : type/`sport_type`, date locale, temps en mouvement ET écoulé, distance, D+, vitesse moy./max, cadence moy., puissance moy., FC moy./max, calories, description, **nom** du matériel (`Gear: <nom>`, pas d'identifiant), effort perçu. **Pas de D−, pas de FC de récupération (HRR), pas de `bmr_calories`, pas de splits par km, pas d'effort relatif (`suffer_score`, ajouté après 1.2.1)** : champs omis du bloc `arc`, jamais inventés (les splits par km : `arc_index.py splits <id>` les calcule depuis le FIT (voir « Splits par km depuis le FIT »)). `Avg Cadence` d'une course à pied = valeur brute de l'API (convention Strava : une jambe — hypothèse du projet, voir `docs/strava-setup.md`), ne pas la recopier en pas/min sans le dire. Renseigner `strava_activity_id` = `"s<ID>"` (préfixe `s` du projet). |
| Tours (laps) | `get_activity_splits` | `get-activity-laps` (`id`) | Laps tels que Strava les expose (blocs JSON bruts) — ce ne sont pas des splits par km réguliers. |
| Zones FC de l'athlète | — (profil) | `get-athlete-zones` | Référence ; le profil déclaré de l'athlète prime. |
| Matériel (inventaire) | `get_gear` | **aucun équivalent dans 1.2.1** | `get-athlete-shoes` n'existe que dans des commits non publiés sur npm : ne jamais l'appeler. L'inventaire reste celui du profil déclaré. |
| Matériel attaché à une activité | `get_activity_gear` | **aucun équivalent fiable** | `get-activity-details` ne donne que le NOM : `gear_id` reste déclaré en chat ou `(par défaut)`, jamais deviné depuis ce nom. |
| Profil athlète | — | `get-athlete-profile`, `get-athlete-stats` | Référence, jamais substitués au profil déclaré. |
| Flux par seconde (analyse fine) | `get_activity_fit_data` (timeoute) | **pas via le MCP** : skill `fit-download` (`download_fit.py --source strava`, API REST) | `get-activity-streams` existe (`types`, `resolution`, `series_type`, pagination, `max_points`) mais sert à l'exploration ; les KPI passent par les fichiers `activities/fit/s<id>.json` normalisés. |
| Santé (HRV, FC de repos, sommeil, readiness) | `get_hrv_data`, `get_rhr_day`, `get_sleep_data`, `get_training_readiness` | **aucun équivalent** | Voir `[health].morning_check` : indisponibilité dite explicitement. |
| Calendrier / push de séances | `get_scheduled_workouts`, `schedule_workouts`… | **aucun équivalent** | Strava n'a pas de calendrier d'entraînement. Le plan reste dans `planning/` ; dire que rien n'est poussé vers la montre. |
| Outils qui AGISSENT (jamais en headless) | — | `connect-strava`, `disconnect-strava`, `star-segment` (écriture) | Réservés à une session interactive, avec confirmation explicite. |

**Fonctionnalités/champs Garmin sans portage Strava — indisponibles et
EXPLIQUÉS comme tels quand `[data].source = "strava"`, jamais devinés ou simulés :**

- **HRV, FC de repos, sommeil, score de readiness** : aucun outil ; `[health].morning_check`
  se dégrade explicitement (voir plus haut), y compris à `full`.
- **Push de séances au calendrier, upload de parcours** (`upload_course`,
  `course-strategist` reste limité à l'analyse GPX locale), **suppression de séance planifiée**.
- **Fréquence cardiaque de récupération (HRR, `recovery_hr_bpm`)** : absente, omise du bloc `arc`.
  Les **splits par km** n'existent pas côté Strava, mais se calculent depuis les flux par seconde
  (`arc_index.py splits s<id>`, voir « Splits par km depuis le FIT »).
- **Dynamique de course** (temps de contact, balance, oscillation) : aucun flux Strava
  équivalent — `arc_index.py gait-summary` n'a rien à dire pour ces séances.
- **Identifiant de matériel par séance** : voir ci-dessus.
- **Surveillance Garmin (`[sync].mode = "watch"`)** : heures fixes seulement.

**Flux Strava → KPI (`download_fit.py --source strava`).** Strava ne sert pas de
FIT : le script appelle l'API REST (`GET /activities/<id>/streams`, avec les jetons du
serveur MCP communautaire, rafraîchis au besoin — jamais affichés) et normalise les flux
par seconde en `activities/fit/s<chiffres>.json`, le même format que le FIT : zones, GAP,
découplage, VAM, descente, durabilité, énergie modèle fonctionnent donc comme avec Garmin
(hypothèse documentée : cadence doublée pour les sports à pied, à vérifier sur une vraie
séance). Les données restent dans l'espace de travail **privé** de l'athlète
(`activities/fit/` est gitignoré) : l'accord API Strava (mis à jour le 1er juin 2026)
limite l'affichage des données à l'utilisateur concerné et impose leur suppression à
la fin de l'accord — rien de Strava ne va dans un dépôt public, fixtures synthétiques
uniquement. Cela lève aussi la limite « activité importée depuis Strava » d'intervals.icu
pour qui connecte Strava directement.

**Téléchargement FIT — disponible avec Garmin et intervals.icu ; flux par seconde avec Strava (voir au-dessus).** Le skill
`fit-download` télécharge le FIT d'une séance intervals.icu par l'API REST
(`download_fit.py <intervals_activity_id> --json`, source lue dans
`[data].source`, clé API du serveur MCP) : `activities/fit/i<chiffres>.json` se
rattache à la séance par son `intervals_activity_id` et débloque les mêmes KPI
qu'avec Garmin (zones, GAP, découplage, VAM, descente, durabilité, dépense
énergétique modèle), ainsi que `session-parts-analyzer`. **Exception : une
activité importée dans intervals.icu depuis Strava** — l'API Strava interdit sa
redistribution, aucun FIT n'existe : le script le dit (`INDISPONIBLE`), la
séance reste valide sans ces KPI, jamais de valeur inventée (avec `--source strava`,
les flux sont lus directement chez Strava : voir plus haut).

**Fonctionnalités/champs Garmin sans portage intervals.icu —
indisponibles et EXPLIQUÉS comme tels quand `[data].source = "intervals"`,
jamais devinés ou simulés :**

- **Fréquence cardiaque de récupération (HRR, `recovery_hr_bpm`)** : absente des
  activités synchronisées côté intervals.icu (voir la table ci-dessus) — omise du bloc
  `arc`, jamais inventée. Les **`splits` par km** n'existent pas non plus côté
  intervals.icu, mais se calculent depuis le FIT (`arc_index.py splits i<id>`, voir
  « Splits par km depuis le FIT ») : `course-comparison` redevient utilisable dès que
  le FIT est téléchargé.
- **Upload de parcours** (`upload_course`, agent `course-strategist`) :
  `course-strategist` reste limité à l'analyse GPX locale (skill
  `gpx-analysis`) — pas d'envoi du parcours vers la montre/l'app tierce.
- **Score de readiness Garmin** : voir la table ci-dessus.

**Revérifié sur le fork `hhopke` au commit épinglé (#165) — rien de nouveau pour ces
quatre points** : toujours aucune FC de récupération (HRR), aucun `splits` par km
(`icu_get_activity_intervals` renvoie les intervalles/tours de l'activité, pas des
splits par km — non branché au contrat `arc`), aucun matériel attaché par activité
(`gear` n'existe que sur l'inventaire `icu_get_gear_list`), aucun score de readiness
calculé (seul `subjective.readiness`, valeur manuelle). **Champ déplacé** : la
dépense de la séance est désormais `nutrition.calories_burned` dans
`icu_get_activity_details` (c'était `other.calories` chez eddmann) — c'est elle
qui alimente `calories_kcal` (référence de dépense de cette source, comme
`calories` côté Garmin) ; `calories_bmr_kcal` reste omis. Nouveautés de lecture
**non exploitées** par le projet à ce jour : `nutrition.carbs_ingested_g`,
courbes allure/FC (`icu_get_pace_curves`, `icu_get_hr_curves`), réglages par
sport (`icu_get_sport_settings`).
**v5.6.0 :** voir « Correspondance des outils » d'`AGENTS.md` (outil d'écriture jamais appelé).

### Correspondance des outils — Garmin ↔ COROS (#168)

Ne s'applique que si `[data].source = "coros"`. **Même comportement que Garmin** : même
déclencheur, même cadence, même persistance MD, même contrat `arc`, bilan matinal au même
niveau, séances poussées à la montre. Outils du **MCP officiel de COROS** (relais
`scripts/arc_coros_mcp.py`), relevés sur un compte réel les 22 et 23 octobre 2026
(`docs/coros.md`) ; réponses en **texte formaté**, jamais un schéma stable : lire les valeurs
telles qu'imprimées, sans en déduire un champ absent. Dates COROS = fuseau du compte ; le sommeil,
l'HRV et la FC de repos sont datés par le **jour du réveil** (la nuit de D est sous D+1).

| Besoin | Outil `garmin` | Outil `coros` | Note |
|---|---|---|---|
| Activités récentes | `get_activities` / `get_activities_by_date` | `querySportRecords(startDate, endDate, sportTypeCodes…)` (`yyyyMMdd`) | Une entrée par séance : date, type, `Location` (= **nom** de la séance, jamais `location`), horodatages `startTimestamp`/`endTimestamp`, durée, distance, allure, FC moyenne, calories, `LabelId` (18 chiffres), `SportType` (100 course, 101 tapis, 102 trail, 104 randonnée, 200/201 vélo, 402 renforcement…). |
| Détail d'une activité | `get_activity` | `getActivityDetail` | Texte résumé : allure, allure ajustée à la pente, FC moy./max, cadence, puissance, D+/D−, calories, charge, effort perçu. `calories_kcal` ← calories de la séance ; **pas de `bmr_calories`** (`calories_bmr_kcal` omis). |
| Identifiant au contrat | `garmin_activity_id` (entier) | `coros_activity_id` = `"c"` + `LabelId` | Toujours avec `start_time` (ISO local, depuis `startTimestamp`) : il numérote les montées. Jamais l'entier nu. |
| Tours | `get_activity_splits` | `queryActivityLapData` | Distances en **cm**, libellés en chinois ; le découpage « par km » repart à chaque étape de la séance planifiée : **jamais** recopié dans `splits` (calculés depuis le FIT : `arc_index.py splits c<LabelId>`). |
| FIT, flux par seconde | `get_activity_fit_data` (timeoute) | `download_fit.py <c+LabelId> --json --source coros` (skill `fit-download`) | Jamais par l'IA (URL du fichier jamais affichée) ; 50 fichiers par jour selon COROS. Mêmes KPI qu'avec Garmin (zones, GAP, découplage, VAM, durabilité, dynamique de course). |
| HRV nocturne | `get_hrv_data` | `querySleepHrv(startDate)` | Évaluation officielle du jour (moyenne, plage normale, ligne de base) → `hrv_overnight_ms` ; ne jamais recalculer depuis la série brute. « No data found » = absente (`missing_reason`). |
| FC de repos | `get_rhr_day` | `queryRestingHeartRate(days)` | `AAAA-MM-JJ: N bpm` ou `No data` ; nombre de jours seulement, pas de date. Jamais la ligne « Resting HR » de `queryDailyHealthData` (ce n'est pas la FC de repos du jour). |
| Sommeil | `get_sleep_data` | `querySleepOverview(startDate, endDate)` | Lu par `python3 scripts/arc_coros_sleep.py --date D` (réponse sur l'entrée standard) : `sleep_*` = **sommeil principal** seulement (les siestes ne sont jamais additionnées), ratios de phases jamais convertis en secondes ; score → `provider_scores` (`sleep`, 0-100), jamais `sleep_score`. `split_suspected` (sieste moins de 3 h après la fin du sommeil principal) = **nuit probablement coupée par COROS** : donner les deux morceaux et demander, jamais corriger seul ; la déclaration de l'athlète prime. `Sleep Score: 0` + « not available yet » = nuit pas encore calculée, **pas** un score. |
| Readiness | `get_training_readiness` | `queryRecoveryStatus` | **Récupération COROS** : `Recovery: N%`, niveau, temps avant récupération complète ; `-1%` = absente. État actuel seulement. → `provider_scores` (`recovery`, 0-100), jamais `readiness_score`, jamais « Training Readiness », jamais comparée aux seuils Garmin. |
| Cycle menstruel (opt-in, `[health].cycle_tracking = "coros"`) | `get_menstrual_data_for_date` | `queryMenstruationCycles` | « No menstrual cycle data found » = aucune phase ; des durées par défaut ne sont jamais lues comme une phase. |
| Seuil lactique (#169) | `--lt-speed-ms` (seuil Garmin) | `queryFitnessAssessmentOverview` | `Threshold Pace` → `arc_coros_workout.py threshold`, nommée « allure seuil COROS ». |
| Calendrier (lecture) | `get_calendar_events` / `get_scheduled_workouts` | `queryTrainingSchedule`, `queryScheduledWorkoutDetails` | |
| Push d'une séance | `schedule_workouts` / `schedule_week` | `createScheduledWorkout`, `updateScheduledWorkout` ; renforcement : `queryWorkoutLibrary` + `scheduleWorkout` | **Pas un remplacement direct** — charger le skill `coros-workout-scheduling` (pas `garmin-workout-scheduling`) : cibles par `arc_coros_workout.py`, calendrier relu avant chaque push, relu après, « oui » explicite, jamais en headless. |
| Supprimer / déplacer une séance planifiée | `delete_workout` / `unschedule_workout` | **aucun équivalent** | Dire à l'athlète quelle séance retirer dans l'app COROS. |
| Matériel (inventaire, par séance, attacher) | `get_gear`, `get_activity_gear`, `add_gear_to_activity` | **aucun équivalent** | `gear_id` déclaré en chat ou `(par défaut)`, jamais deviné. |
| Pesées (#222) | `get_daily_weigh_ins` / `get_weigh_ins` | **aucun équivalent** | `queryUserInfo` ne donne que le poids du profil, jamais une pesée : le poids reste déclaré. |
| Apports (#167), upload de parcours | `log_food`…, `upload_course` | **aucun équivalent** | Indisponibles, dits comme tels. |
| Pace Strategy de course | — (parcours `upload_course`) | **aucun outil** (ni route, ni Pace Strategy) | Créé par l'athlète dans l'app COROS ; le `course-strategist` prépare la fiche à recopier : `python3 scripts/arc_coros_workout.py pace-strategy --plan <plan> --text` (temps cible, arrêts aux ravitos, allures par segment, mêmes temps de passage que le plan). Jamais présenté comme créé ou poussé. |
| Outils qui AGISSENT (jamais en headless) | — | `createScheduledWorkout`, `updateScheduledWorkout`, `scheduleWorkout`, `createSingleWorkout`, `updateWorkoutDetails`, `createTrainingPlan`, `updateTrainingPlan` | Refusés par le relais en headless (`ARC_HEADLESS`) et par leur nom pour chaque exécuteur (`scripts/lib/sync_tools.sh`). |

**Fonctionnalités/champs Garmin sans portage COROS — indisponibles et EXPLIQUÉS comme tels quand
`[data].source = "coros"`, jamais devinés ou simulés :** fréquence cardiaque de récupération (HRR,
`recovery_hr_bpm` : absente du détail, des tours et du FIT),
matériel par séance (et rattrapage `garmin_gear_backfill.py`), pesées, poussée des apports, upload de
parcours, suppression/déplacement d'une séance planifiée, Training Readiness Garmin (remplacé par la
récupération COROS, nommée). **Surveillance** (`[sync].mode = "watch"`) : disponible, par le relais
(`scripts/watch.py`, sans LLM) — le MCP COROS n'ayant pas d'heure de dernier envoi, chaque passage
lit les séances récentes et, tant que le fichier santé du jour manque, le sommeil du jour.
