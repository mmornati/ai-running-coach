# Open Wearables (audit, #216 / #217)

Cette page trace l'audit de [Open Wearables](https://github.com/the-momentum/open-wearables)
(OW) et la décision prise pour le projet. Audit réalisé le 5 octobre 2026 **dans
le code source** (pas dans la plaquette), puis revérifié le 10 octobre 2026 pour
cette page. Légende utilisée partout : **vérifié** = lu dans le code ou la
documentation d'OW au commit épinglé, ou dans une page publique que nous avons
effectivement récupérée (URL et date données) ; **rapporté** = affirmé par un
tiers, étiqueté comme tel avec sa date et son URL.

Commit épinglé de tout ce qui suit : tag `0.9.0` =
`ff8527a52ad8a96cd1ebe8c19344295c934ae9dc` (17 septembre 2026). La branche
`main` a aussi été relue au commit `12941a4cb10fd77755d5b0007d8f267c5fea451b`
(2 octobre 2026), uniquement là où c'est dit.

## Décision

!!! success "Décision : OW n'est jamais une source d'entraînement ; Garmin reste en direct ; la santé du bilan matinal est une option prévue"
    1. **OW comme source d'entraînement (`[data].source`) : non.** Les trois
       marques clés du trail lui sont inaccessibles (ou inexistantes) pour un
       particulier, et ce qui reste est trop pauvre pour l'analyse trail.
    2. **Garmin reste séparé et en direct** (`garmin-mcp`). OW ne peut pas
       obtenir les données Garmin d'un particulier, et même avec un accès
       entreprise il n'exposerait ni Training Readiness, ni FC de récupération,
       ni D−.
    3. **« Beaucoup d'appareils » pour l'entraînement : la réponse existe déjà,
       c'est [Intervals.icu](intervals-setup.md)** — voir le guide
       [Quelle source pour mon appareil ?](configuration.md#quelle-source-pour-mon-appareil).
    4. **La valeur d'OW est étroite : la santé quotidienne** (HRV, FC de repos,
       sommeil, scores de récupération natifs) venant d'appareils que le projet
       ne lit pas aujourd'hui. Cette lecture est **prévue** (#218 à #221) comme
       option stricte `[health].source`, **pas encore livrée** : à ce jour, rien
       dans le projet n'appelle OW, et aucun agent n'en parle.

## Ce qu'est Open Wearables

- Plateforme libre sous licence MIT (`LICENSE`), **auto-hébergée** : API
  FastAPI, Postgres, Redis, workers Celery (`README.md`, `docker-compose.yml`).
- Une API unifiée qui normalise les données de plusieurs fournisseurs, et un
  **serveur MCP intégré** (`README.md`, dossier `mcp/`).
- **Pré-1.0** : le tag audité est `0.9.0` ; la version 1.0 est annoncée pour
  fin octobre 2026 (`docs/roadmap.mdx`). Les endpoints et formes de réponse
  peuvent encore bouger : toute intégration devra être revérifiée au dernier
  tag publié avant d'être écrite (c'est la « porte d'entrée » de #219 à #221).

## Accès par fournisseur pour un particulier

Preuves : fichiers d'OW **au commit épinglé** (chemins relatifs à la racine du
dépôt). « Utile ici » = ce que le projet pourrait en tirer pour le bilan
matinal ; les cases de couverture viennent de `docs/providers/coverage.mdx`.

| Fournisseur | Accès pour un particulier | Ce qu'OW en tire d'utile ici | Preuve |
|---|---|---|---|
| Garmin | ❌ entités légales seulement (« Personal-use applications are rejected ») ; programme **en pause** (voir plus bas) ; OW ne reçoit Garmin qu'en push (URL HTTPS publique) | — | `docs/providers/garmin-api-integration.mdx` ; `backend/app/services/providers/garmin/strategy.py` (`ProviderCapabilities(webhook_stream=True, webhook_callback=True, max_historical_days=30)`, pas de lecture par sondage) |
| Suunto | ❌ entreprises / organisations seulement, pas d'usage personnel | — | `docs/providers/suunto-api-integration.mdx` (renvoie à <https://apizone.suunto.com/faq>, relue le 10 octobre 2026 : « we do not provide this for personal use ») |
| COROS | ❌ non pris en charge | — | absent de la liste des fournisseurs (`docs/providers/`, `coverage.mdx`) ; `docs/roadmap.mdx` : « we cannot promise new integrations on a timeline » |
| Polar | ✅ libre-service (compte Polar Flow → AccessLink) | séances très pauvres ; HRV RMSSD, sommeil, scores natifs : readiness 0–10, recovery 1–6 (Nightly Recharge) ; pas de FC de repos | `docs/providers/polar-api-integration.mdx` ; `backend/app/services/providers/polar/coverage.py` (`WORKOUT_FIELDS` = `heart_rate_max`, `heart_rate_avg`, `energy_burned`, `distance`) ; `backend/app/constants/health_scores.py` |
| Oura | ✅ ; l'URL de redirection OAuth doit être en HTTPS public | HRV RMSSD, FC de repos, sommeil avec stades, readiness 1–100 ; pas de FC pendant les séances | `docs/providers/oura-api-integration.mdx`, `docs/providers/coverage.mdx` |
| WHOOP | ✅ (abonnement WHOOP actif) | recovery 0–100, HRV RMSSD, FC de repos, sommeil (totaux de stades seulement, pas d'hypnogramme) | `docs/providers/whoop-api-integration.mdx`, `coverage.mdx` |
| Ultrahuman | ✅ (compte personnel, bague Ring Air ; API « Partnership ») | HRV en **SDNN**, sommeil avec stades ; **pas de FC de repos** dans la matrice ; aucune séance | `docs/providers/ultrahuman-api-integration.mdx`, `coverage.mdx` |
| Withings | ✅ ; l'URL de redirection ne peut être ni `localhost` ni une IP nue | poids et composition, tension, FC ponctuelle, sommeil (totaux) ; **HRV non importée**, pas de FC de repos | `docs/providers/withings-api-integration.mdx`, `coverage.mdx` |
| Google Health (Pixel Watch, Fitbit) | ✅ (projet Google Cloud avec l'API Health activée) | HRV RMSSD **et** SDNN, FC de repos, sommeil avec stades | `docs/providers/google-api-integration.mdx`, `coverage.mdx` |
| Apple Health, Health Connect, Samsung | ⚠️ via l'app mobile d'OW, en **bêta** (TestFlight / APK sur demande Discord) ; Samsung Health exige le mode développeur ; Apple Health aussi par import XML | Apple : HRV en **SDNN** seulement ; Health Connect : RMSSD ; FC de repos dans les deux | `docs/app/introduction.mdx`, `coverage.mdx` |
| Strava | ✅, mais un abonnement Strava est requis pour l'API depuis juin 2026 (doc OW) | flux FC / vitesse / cadence / puissance, **sans altitude ni GPS** ; pas de santé | `docs/providers/strava-api-integration.mdx` ; `backend/app/services/providers/strava/coverage.py` (`STREAM_KEY_SERIES_TYPE`) |

!!! note "Écarts avec le texte de l'épopée, corrigés ici"
    Ultrahuman : l'HRV est en SDNN (et non RMSSD) et la FC de repos n'est pas
    importée. Withings : pas de FC de repos (FC ponctuelle seulement). Ce sont
    les cases de `coverage.mdx` au commit épinglé qui font foi.

### Faits externes (datés)

- **Pause du programme développeur Garmin** — *rapporté* : billet de Momentum
  (la société qui édite OW), publié le 15 juillet 2026, mis à jour le 27 août
  2026, relu le 10 octobre 2026 :
  <https://www.themomentum.ai/blog/garmin-developer-program-closed-roadmap>.
  Selon ce billet, les nouvelles demandes sont suspendues, sans date de reprise
  annoncée, et les connexions existantes continuent de fonctionner. Un second
  article (the5krunner, 14 septembre 2026,
  <https://the5krunner.com/2026/09/14/garmin-developer-api-access-paused/>) a
  été cité par l'audit mais **n'a pas pu être relu** le 10 octobre 2026
  (réponse HTTP 403) : non vérifié par nous. La règle d'entités légales, elle,
  est dans la doc d'OW au commit épinglé.
- **Fitbit** — Google : le support de l'ancienne API Fitbit Web prend fin le
  30 septembre 2026 et l'API sera arrêtée le 30 octobre 2026 (page relue le
  10 octobre 2026 : <https://developers.google.com/health/about>). L'API
  encore active à la date de cette page ne le sera donc plus à la fin du mois ;
  OW renvoie vers son intégration Google Health.
- **Abonnement Strava** — *rapporté* par la doc d'OW (`strava-api-integration.mdx`,
  « as of June 2026 »), non vérifié chez Strava.
- **Appareils synchronisés par Intervals.icu** — page relue le 10 octobre 2026 :
  <https://www.intervals.icu/features/wellness/> (« Auto-sync from Garmin, Polar,
  Suunto, Coros, Huawei, Amazfit, Oura, WHOOP » ; « Sync from Apple Health and
  others using 3rd party apps »).

## Comparaison avec Garmin en direct

| Besoin du projet | Garmin direct (aujourd'hui) | OW 0.9.0 | Preuve (commit épinglé) |
|---|---|---|---|
| D− d'une séance | ✅ | ❌ : seul `elevation_gain_meters` | `backend/app/schemas/responses/activity/events.py` |
| FC de récupération (HRR) | ✅ `recovery_hr_bpm` | ❌ (seule `heart_rate_recovery_one_minute` existe, côté Apple) | `docs/providers/coverage.mdx` |
| Training Readiness | ✅ | ❌ : Garmin via OW = sommeil, stress, Body Battery | `backend/app/services/providers/garmin/coverage.py` (`HEALTH_SCORES`) |
| Splits / tours | ✅ | ⚠️ champ `segments` (tours issus de fichiers FIT) | `backend/app/schemas/responses/activity/events.py`, `backend/app/services/fit_parser.py` |
| Flux par seconde | ✅ (`download_fit.py`) | ⚠️ désactivés par défaut | `backend/app/config.py` : `ingest_workout_samples: bool = False`, `store_fit_files: bool = False` |
| Calories | totales + BMR | kcal **actives** seulement pour Garmin | `backend/app/services/providers/garmin/workouts.py` (`energy_burned` = `activeKilocalories`) |
| Push de séances, parcours, matériel, nutrition | ✅ | ❌ lecture seule ; « Workout planner » classé « Exploring », sans échéance | `docs/roadmap.mdx` |
| Récupération multi-fabricants | — | ⚠️ `GET /users/{user_id}/summaries/recovery` ne renvoie aujourd'hui que WHOOP (« This is a bug », docstring) | `backend/app/api/routes/v1/summaries.py` |
| Échelles des scores | Garmin 0–100 | variables selon le fabricant (readiness Oura 1–100, Polar 0–10 ; recovery WHOOP 0–100, Polar 1–6) | `backend/app/constants/health_scores.py` (`HEALTH_SCORE_RANGES`) |

## Le serveur MCP d'Open Wearables

Six outils, tous en lecture (`mcp/app/tools/`) :
`get_users`, `get_activity_summary`, `get_sleep_summary`,
`get_workout_events`, `get_timeseries`, `get_menstrual_cycles`.

- `get_sleep_summary` renvoie date, début, fin, durée et source : **ni HRV, ni
  stades, ni FC de repos**.
- `get_workout_events` renvoie 12 champs par séance (dont
  `elevation_gain_meters`, `avg_pace_sec_per_km`), sans D−, cadence ni zones.
- `get_timeseries` pagine par 100 échantillons avec un plafond `_MAX_PAGES =
  100` : jusqu'à environ 10 000 échantillons peuvent arriver dans le contexte
  d'une seule réponse.
- **Aucun outil** pour les scores de readiness ou de récupération.

Le projet ne l'utilisera donc pas pour la santé du bilan matinal. L'option
prévue lit l'API REST d'OW par un script du dépôt (même précédent que
`download_fit.py`, qui contourne un MCP inadapté).

## Coût d'hébergement

- **Services** : `docker-compose.yml` en déclare huit (`db`, `app`,
  `celery-worker`, `celery-beat`, `flower`, `redis`, `svix-server`, `frontend`).
  Le minimum fonctionnel (base, Redis, API, worker et beat) est une estimation
  de l'audit, non testée ici.
- **Une application développeur par fournisseur** : identifiant et secret à
  créer soi-même chez Polar, Oura, WHOOP, Ultrahuman, Withings, Google, Strava.
- **HTTPS public pour l'OAuth** d'Oura et de Withings (un tunnel suffit le temps
  de la connexion, selon la doc d'OW). Ensuite, hors Garmin, la synchronisation
  se fait par sondage : la doc Ultrahuman indique un sondage toutes les heures
  par Celery Beat.
- **Télémétrie anonyme** : sur la branche `main`, `telemetry_enabled: bool =
  True` (aussi coupée par `DO_NOT_TRACK=1`) depuis le commit `db55ea3` du
  25 septembre 2026, postérieur à `0.9.0` : absente du commit épinglé, elle
  arrivera avec la prochaine version. Pour la couper : `TELEMETRY_ENABLED=false`
  ou `DO_NOT_TRACK=1` (`docs/dev-guides/telemetry.mdx` à `main`, commit
  `12941a4cb10fd77755d5b0007d8f267c5fea451b`).

## Ce qui ferait changer la décision

- Garmin rouvre son programme **aux particuliers** (aujourd'hui : entités
  légales seulement, et en pause).
- OW ajoute COROS, ou ouvre Suunto aux particuliers.
- Le modèle de séance d'OW gagne le D− et un endpoint de flux par séance, avec
  ingestion activée par défaut.
- Le MCP d'OW expose HRV, FC de repos et scores de readiness.

## Références

Toutes au commit épinglé
`ff8527a52ad8a96cd1ebe8c19344295c934ae9dc` :
<https://github.com/the-momentum/open-wearables/tree/ff8527a52ad8a96cd1ebe8c19344295c934ae9dc>

- Couverture : `docs/providers/coverage.mdx`
- Fournisseurs : `docs/providers/{garmin,suunto,polar,oura,whoop,ultrahuman,withings,google,strava}-api-integration.mdx`
- Application mobile : `docs/app/introduction.mdx`
- Feuille de route : `docs/roadmap.mdx`
- Code : `backend/app/services/providers/*/coverage.py`, `backend/app/constants/health_scores.py`, `backend/app/schemas/responses/activity/events.py`, `backend/app/config.py`, `mcp/app/tools/*.py`
- Hors dépôt : pages citées plus haut, relues le 10 octobre 2026.

Voir aussi : [Quelle source pour mon appareil ?](configuration.md#quelle-source-pour-mon-appareil),
[Montres COROS](coros.md), [Configuration Intervals.icu](intervals-setup.md),
[Configuration Strava](strava-setup.md).
