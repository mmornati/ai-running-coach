# AI Running Coach — Workspace

Espace de travail de coaching trail-running. Les agents IA gèrent l'entraînement,
la santé, la nutrition et la stratégie de course, en persistant tout sous forme de
fichiers Markdown en français.

## Configuration

**Règle de résolution** (valable pour toutes les clés) : lire
`config/workspace.toml` (versionné, défauts partagés) ; si
`config/workspace.user.toml` existe (gitignoré, personnel), ses valeurs priment,
clé par clé. Une clé présente mais vide gagne : c'est ainsi qu'on annule un
héritage.

| Clé | Effet sur les agents |
|---|---|
| `[language].documents` | Langue des MD persistés (`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/`). Défaut `fr`. |
| `[language].responses` | Langue des réponses. Défaut `auto` = celle de la requête. |
| `[coaching].style` | Voix de l'agent → `config/coaching-styles.md`. |
| `[coaching].intensity` | Fermeté d'application du style. |
| `[coaching].verbosity` | Longueur des retours et rapports. |
| `[sport].primary` | Profil chargé depuis `config/sports/<valeur>.md` (`trail` \| `road`). |
| `[sport].disciplines` | Sports croisés réellement pratiqués — les seuls à programmer. |
| `[agents].enabled` | **Seuls agents joignables.** Ne jamais déléguer à un agent absent. |
| `[health].morning_check` | `full` \| `minimal` \| `off` — voir ci-dessous. |
| `[data].source` | `garmin` (défaut) \| `intervals` \| `strava` — source de données primaire des agents. Voir « Backends MCP » et les tables de correspondance des outils ci-dessous (#68, #164). |
| `[health].heat_threshold_c` | Seuil (°C, borne incluse) « séance chaude » pour le KPI d'acclimatation à la chaleur (#38, `scripts/arc_index.py heat-acclimation`). Défaut `25.0`. Indépendant de `morning_check` ; une valeur invalide n'interrompt jamais l'index (repli sur le défaut, avertissement). |
| `[athlete].profile` | Profil de l'athlète, défaut `planning/Runner_Profile.md`. |
| `[athlete].units` | `metric` \| `imperial`. |

Le **profil de l'athlète prime sur le catalogue de styles** : sa section
« Préférences de coaching » est écrite par l'athlète lui-même. Et le style ne
change **jamais** le fond : une séance annulée pour raison médicale reste
annulée quel que soit le ton.

Les instructions des agents/skills restent rédigées en anglais ou en français
selon le fichier — seule la langue de *sortie* est paramétrée.

## Premier démarrage

Tant que `config/workspace.user.toml` n'a pas de section `[coaching]` et que le
profil de l'athlète n'existe pas, proposer `/coach-setup` en une ligne — le
**proposer**, jamais l'imposer, et jamais deux fois dans une session. Exceptions :
`/garmin-daily-sync` tourne sous cron et ne doit rien proposer du tout ; les
commandes courtes `/today`, `/why`, `/week`, `/race` (#66) répondent à une
question factuelle précise, et `/inspection` (#149) à une demande précise : aucune
ne propose jamais non plus `/coach-setup`, même sur une installation neuve.

## Bilan matinal — `[health].morning_check`

| Valeur | Comportement attendu |
|---|---|
| `full` | Triptyque indivisible : HRV + FC de repos (`get_rhr_day`) + readiness, avant toute décision de séance. Défaut. |
| `minimal` | `get_training_readiness` seule, rapportée en une ligne. Pas de HRV, pas de FC de repos, pas d'annulation sur les seules données de santé. |
| `off` | Aucune donnée de santé récupérée, aucun filtrage. Planification sur la charge, l'historique `activities/` et le ressenti déclaré. |

Ne jamais réactiver silencieusement un niveau plus strict que celui configuré.

**Avec `[data].source = "intervals"` (#68) :** intervals.icu n'a pas de score de
readiness algorithmique équivalent à celui de Garmin — seul un champ
`subjective.readiness` existe côté intervals.icu, une valeur manuelle du jour
qui peut venir de l'athlète OU d'un appareil tiers synchronisé (Oura, Whoop...),
jamais un score calculé par intervals.icu. À `full`, le bilan devient donc HRV + FC de repos
(les deux dans le même appel `get_wellness_for_date`) **et l'indisponibilité du
readiness est dite explicitement** ("readiness indisponible — source
intervals.icu"), jamais remplacée par le champ subjectif présenté comme
équivalent. À `minimal`, la ligne unique devient "readiness indisponible
(source intervals.icu)" plutôt qu'un score. Voir la table de correspondance
ci-dessous.

**Avec `[data].source = "strava"` (#164) :** Strava n'expose ni HRV, ni FC de
repos, ni sommeil, ni readiness (voir « Backends MCP » et la table
Garmin ↔ Strava). Le bilan matinal ne peut donc **pas** s'appuyer sur des
données de santé : à `full` comme à `minimal`, l'agent dit explicitement
« HRV / FC de repos / readiness indisponibles — source Strava » (jamais un
score ni une valeur inventés, jamais un « tout va bien » par défaut) et
planifie sur la charge, l'historique `activities/` et le ressenti **déclaré par
l'athlète** — comme à `off`, mais en le disant. Une séance annulée pour raison
médicale (blessure, douleur déclarée) reste annulée.

## Carte des dossiers

| Dossier | Contenu | Convention |
|---|---|---|
| `activities/` | Journaux d'entraînement (`gear_id` = chaussure, `gear_ids` = matériel hors chaussures, #134) | `YYYY-MM-DD_type.md` (running, trail, strength, indoor_cycling, home_trainer, hiking, elliptical, rest) |
| `medical/` | Sommeil, HRV, récupération, blessures, météo | `YYYY-MM-DD_health.md`, `YYYY-MM-DD_meteo.md` |
| `nutrition/` | Journaux nutrition & plans de ravitaillement | `YYYY-MM-DD_nutrition.md` |
| `planning/` | Plans d'entraînement, objectifs, stratégies de course, **décisions tracées** | `active_objective.md` est la **source de vérité** de l'objectif courant ; `Runner_Profile.md` est le profil de l'athlète. Les deux sont installés depuis `templates/` par `/coach-setup`. Une décision (garde-fou, bilan matinal, blessure…) = un fichier `YYYY-MM-DD_decision_<slug>.md`. |
| `rapports/` | Rapports de synthèse périodiques (propriété du **coach**) | `YYYY-MM-DD_rapport.md` |
| `gear/` | Inspections photo du matériel (propriété du **coach**, skill `gear-inspection`, #135) ; photos dans `gear/photos/` (jamais dans le dépôt public ; **boîte de dépôt** : les images non citées par une inspection sont à rattacher à une paire, renommer `AAAA-MM-JJ_<gear_id>_<vue>.<ext>`, jamais supprimer) | `YYYY-MM-DD_<gear_id>_inspection.md` |
| `resources/` | Base de connaissances (langue des documents) : running, nutrition, santé, récupération | Matériel de référence, citer lors des conseils. **Catalogues produits** (optionnels) : `resources/nutrition/catalogue-produits-*.md` = valeurs nutritionnelles par produit de l'athlète |

> **Note** : ces dossiers sont créés par l'utilisateur dans son espace de travail
> (voir `install.sh`). Ils sont exclus du dépôt public (`.gitignore`).

### Contrat de données

Tout fichier écrit par un agent dans `activities/`, `medical/`, `nutrition/`,
`planning/` (semaines, évaluations, plans de course, décisions), `rapports/` ou `gear/` s'ouvre, sous
son titre, par **un bloc ```` ```arc ```` de JSON** conforme au skill
`workspace-data-contract` : clés en anglais, unités SI, mesure absente = clé omise.
Le texte libre reste en dessous. Valider après écriture avec
`python3 scripts/arc_index.py --validate <fichier>`.

Exceptions : `planning/Runner_Profile.md` et `planning/active_objective.md`,
édités par l'athlète, gardent les puces de leur modèle — remplir les valeurs,
ne jamais renommer un libellé.

Ce bloc alimente un index SQLite **dérivé** (`scripts/arc_index.py`, jetable,
reconstruit depuis les fichiers) et le tableau de bord local
(`scripts/dashboard.sh`). Le Markdown reste la source de vérité.

## Sous-agents

Délégation via l'outil `task`, **et uniquement vers les agents listés dans
`[agents].enabled`**. Le staff est choisi à l'installation
(`./install.sh --agents …`, `--no-medical`) ; seuls les agents choisis sont
déployés dans `.claude/agents`, `.opencode/agents` et `.github/agents`. Si un
agent est absent, ne pas l'appeler et ne pas le mentionner à l'athlète : traiter
le sujet soi-même dans la limite de sa compétence.

| Agent | Utilisation |
|---|---|
| `coach` | Plans d'entraînement, analyse des activités Garmin (**incl. HRR `recovery_hr_bpm` dans chaque retour de séance**), ajustements de séances, **push des séances au calendrier Garmin** (`schedule_workouts`, Garmin d'abord), rapports hebdomadaires. **Bilan matinal avant toute décision de séance, au niveau fixé par `[health].morning_check` : à `full` (défaut), HRV + FC de repos (`get_rhr_day`) + readiness — les trois, jamais deux.** **Inclut toujours la météo + le créneau optimal (matin tôt / midi / soir) dans chaque validation hebdomadaire/journalière (charger le skill `weather-forecast`, résoudre le lieu via la règle de précédence stricte).** **Ligne « Dépense : Garmin X kcal · modèle Y kcal (±Z %) » dans chaque retour de séance running/trail/hiking/walking (`arc_index.py energy`), alerte si écart > 15 % — Garmin reste la référence.** **Matériel hors chaussures (#134) : kits attribués via `gear_ids` (`arc_index.py equipment --kit`), entretien noté en chat, ligne « Matériel : … » (alerte/proche du seuil), rappel frontale/poche avant séance de nuit/longue.** |
| `medical` | Analyse sommeil/HRV/récupération (**incl. HRR lors de l'évaluation de l'impact d'une séance**, et **FC de repos dans le bilan matinal**), protocoles blessures, gatekeeper de disponibilité, contraintes de coordination pour coach/nutritionniste |
| `nutritionist` | Macros, poids de course, plans de ravitaillement. **Pas de serveur MyFitnessPal** — les apports viennent des rapports manuels de l'utilisateur ; croiser avec les calories brûlées Garmin (référence par défaut ; le modèle `energy` n'est qu'un contrôle, jamais additionné au `burned_kcal` journalier — pas de double comptage) |
| `course-strategist` | Analyse GPX/URL de course → plan de course (allures ×3 scénarios, nutrition, météo, équipement, **dépense énergétique prévue par section/scénario via `arc_race_pacing.py --pack-kg`, en regard du plan de ravitaillement**), enrichissement points d'eau OSM, upload de parcours Garmin via l'outil `upload_course` **Contrôle du matériel de course (#134) : `gear` du plan croisé avec l'inventaire du profil (`arc_index.py equipment --race-plan`) → manquant / jamais utilisé à l'entraînement / sous alerte, jamais inventé.** |

Lors d'une délégation, écrire le prompt de tâche en anglais mais ajouter
explicitement **« Respond in <langue des documents> »** (résolue via
`config/workspace.toml` → `[language].documents`, défaut FRENCH) si la sortie
est destinée à l'utilisateur.

## Backends MCP

**`[data].source` décide lequel des deux est la destination PRIMAIRE (#68) —
voir la table de configuration ci-dessus.** Par défaut (`source = "garmin"`),
rien ne change par rapport au comportement historique : la section ci-dessous
et la table de correspondance qui suit ne prennent effet que si l'installation
a été faite avec `./install.sh --source intervals` (ou `[data].source =
"intervals"` posé à la main).

- **`garmin`** — activités, sommeil, HRV, readiness, **calendrier des séances planifiées**, upload parcours/séances. **Mode direct par défaut** : le serveur MCP `garmin` expose `garmin-mcp` avec une liste blanche d'outils (`GARMIN_ENABLED_TOOLS`). **Mode passerelle (optionnel, power user)** : `leanproxy_invoke_tool(server="garmin", tool="...")` via leanproxy-mcp (économie de tokens ~98 %, chargement paresseux des schémas). **PRIMAIRE si `[data].source = "garmin"` (défaut)** ; sinon non installé par `install.sh` (voir ci-dessous).
- **`Intervals.icu`** — événements, wellness, activités, via le serveur MCP communautaire [`eddmann/intervals-icu-mcp`](https://github.com/eddmann/intervals-icu-mcp) (48 outils, `intervals-icu-mcp` + `intervals-icu-mcp-auth`, voir `docs/intervals-setup.md`). **PRIMAIRE si `[data].source = "intervals"`** (installé par `./install.sh --source intervals`) : `coach`/`medical`/`garmin-daily-sync` utilisent alors ses outils au lieu de ceux de `garmin`, table de correspondance ci-dessous. **SECONDAIRE sinon** (défaut) : uniquement si l'utilisateur le demande explicitement (skill `intervals-icu-best-practices`), serveur non installé par `install.sh`, configuration manuelle (`docs/faq.md`).
- **`Strava`** (#164) — activités + flux par seconde. **PRIMAIRE si `[data].source = "strava"`** (installé par `./install.sh --source strava`, voir `docs/strava-setup.md`) : serveur MCP **communautaire** [`r-huijts/strava-mcp`](https://github.com/r-huijts/strava-mcp) (paquet npm `@r-huijts/strava-mcp-server`, épinglé à la version 1.2.1 par `STRAVA_MCP_PKG` dans `install.sh`, stdio, **Node.js >= 18**, application API Strava locale de l'athlète — client id/secret ; jetons dans `~/.config/strava-mcp/config.json`). Lecture seule **pour ce projet** : `connect-strava`, `disconnect-strava` et `star-segment` (écriture Strava) ne sont jamais appelés en headless (`daily-sync.sh` les interdit) et demandent une approbation dans le chat. Le **connecteur officiel Strava** (`https://mcp.strava.com/mcp`, HTTP + OAuth, lecture seule, abonnement payant) est une alternative **manuelle** pour Claude Code interactif (`claude mcp add --transport http strava-mcp https://mcp.strava.com/mcp`, article d'aide Strava 46190267796237) : ses noms d'outils et formes de réponse n'ont **pas pu être vérifiés** (OAuth requis) — la table de correspondance ci-dessous ne s'y applique pas, l'agent lit la liste d'outils exposée par la session et n'invente rien ; il ne sert pas au `garmin-daily-sync` headless.
- **Absents localement** : `myfitnesspal` (utiliser les rapports manuels), `nexus-mcp` (RAG — déploiement Docker VPS uniquement ; localement utiliser `resources/` + historique MD)

### Correspondance des outils — Garmin ↔ intervals.icu (#68)

Ne s'applique que si `[data].source = "intervals"`. Même déclencheur, même
cadence, même persistance MD, même contrat `arc` **pour les lectures**.
**Le push de séances n'est PAS un simple changement de nom d'outil** — voir
l'avertissement sous la table. Noms et formes de réponse vérifiés dans le code
source du serveur retenu (`src/intervals_icu_mcp/tools/*.py`, `client.py`,
`response_builder.py`, commit `cb91d4a` — épinglé par `INTERVALS_MCP_REF` dans
`install.sh`, documenté dans `docs/intervals-setup.md`), jamais devinés.

| Besoin | Outil `garmin` | Outil `intervals` | Note |
|---|---|---|---|
| HRV nocturne | `get_hrv_data` | `get_wellness_for_date` (`heart.hrv_rmssd`/`heart.hrv_sdnn`) | Un seul appel intervals.icu couvre HRV + FC de repos + sommeil. |
| FC de repos | `get_rhr_day` | `get_wellness_for_date` (`heart.resting_hr`) | Idem — ne PAS appeler `get_wellness_data` (plage de dates) pour un seul jour. |
| Sommeil | `get_sleep_data` | `get_wellness_for_date` (`sleep.*`) | |
| Readiness algorithmique | `get_training_readiness` | **aucun équivalent** | intervals.icu n'expose que `subjective.readiness` — une valeur manuelle dans le champ wellness du jour, qui peut venir de l'athlète OU d'un appareil tiers synchronisé (Oura, Whoop...), jamais un score calculé par intervals.icu lui-même — jamais présenté comme équivalent au Training Readiness Garmin. Dire explicitement l'indisponibilité (voir `[health].morning_check` ci-dessus). |
| Activités récentes | `get_activities` / `get_activities_by_date` | `get_recent_activities` | |
| Détail d'une activité | `get_activity` | `get_activity_details` | Pas de fréquence cardiaque de récupération (HRR/`recovery_hr_bpm`) ni de `splits` par km sur ce serveur — champs omis, jamais inventés (impacte aussi `course-comparison`, qui exige `splits`). Pas de champ équivalent à `bmr_calories` identifié non plus : `calories_bmr_kcal` reste omis pour une activité synchronisée depuis cette source, jamais deviné. Renseigner `intervals_activity_id` (chaîne, ex. `"i12345678"`) sur `activities/*.md` au lieu de `garmin_activity_id` (entier) — `workspace-data-contract`. |
| Durées d'une activité | `get_activity` | `get_activity_details` : `duration_s` ← `elapsed_time_seconds` (durée totale, pauses comprises), `moving_duration_s` ← `moving_time_seconds` | **Jamais `duration_s` depuis `get_recent_activities`** : cette liste ne renvoie que `moving_time_seconds` (temps en mouvement). Un `duration_s` égal au temps en mouvement fait refuser par la validation un temps en zone pourtant juste (`time_in_zone_s` > `duration_s`). |
| Événements planifiés | `get_calendar_events` / `get_scheduled_workouts` | `get_calendar_events` / `get_upcoming_workouts` | |
| Détail d'une séance planifiée | `get_workout_by_id` | `get_event` | Ne renvoie que id/date/name/category/description/type/metrics — jamais de structure de séance. |
| Push d'une séance | `schedule_workouts` / `schedule_week` | `create_event` / `bulk_create_events` | **Pas un remplacement direct** — charger le skill `intervals-icu-best-practices` (pas `garmin-workout-scheduling`) : `create_event`/`update_event` n'ont PAS de paramètre structuré (pas de `workout_doc`) ; les cibles (#60) s'écrivent en texte dans `description` ; aucun upsert n'existe (vérifier `get_calendar_events` avant chaque push, pas de réutilisation de `workout_id`) ; la vérification post-push ne porte que sur les champs que `get_event` renvoie réellement. |
| Matériel (inventaire) | `get_gear` (appeler avec `include_stats=False` : le défaut du serveur est `True`, un appel API par matériel) | `get_gear_list` | **Référence seulement** côté intervals.icu (id, nom, type, `usage.total_distance_km`) — jamais une attribution. Voir « Matériel » sous la table (#133). |
| Matériel attaché à une activité | `get_activity_gear` | **aucun équivalent** | Le serveur intervals.icu n'a aucun champ matériel sur les activités : `gear_id` reste déclaré en chat ou `(par défaut)`, jamais deviné. |
| Attacher un matériel à une activité | `add_gear_to_activity` (ÉCRITURE Garmin, confirmation explicite, jamais en headless) | **aucun équivalent** | Voir « Matériel » sous la table. |
| Modifier/supprimer une séance planifiée | `delete_workout` / `unschedule_workout` | `update_event` / `delete_event` | `update_event` exige un `event_id` déjà existant — jamais un upsert. |
| Profil athlète (référence, jamais substitué au profil déclaré) | — | `get_athlete_profile` | |
| Charge/forme (vocabulaire générique du projet, jamais les noms TrainingPeaks) | — (calculée par `scripts/arc_index.py`) | `get_fitness_summary` | Ne jamais citer `ctl`/`atl`/`form` sous ces noms dans une réponse — reformuler en charge/condition/fatigue/forme comme partout ailleurs (`docs/marques.md`). |

### Correspondance des outils — Garmin ↔ Strava (#164)

Ne s'applique que si `[data].source = "strava"` **avec le serveur communautaire
`r-huijts/strava-mcp`** (version 1.2.1, commit `ac43cc7b0aad2f218b9c42bd639aee696dbee531`). Noms et
paramètres vérifiés dans son code source (`src/server.ts`, `src/tools/*.ts`) ; les
réponses sont du **texte formaté** (pas du JSON structuré, sauf les blocs « Complete Lap Data » /
« Raw Athlete Zone Data » et le flux), jamais un schéma stable : lire les valeurs
telles qu'imprimées, sans en déduire un champ absent.

| Besoin | Outil `garmin` | Outil `strava` | Note |
|---|---|---|---|
| Activités récentes | `get_activities` / `get_activities_by_date` | `get-recent-activities` (`perPage`) ; `get-all-activities` (`startDate`, `endDate`, `activityTypes`, `sportTypes`, `maxActivities`, `maxApiCalls`) | Une ligne de texte par activité : type, nom, **`(ID: <entier>)`**, distance, date (jour seulement) — pas d'heure précise ni de durée dans `get-recent-activities`. Limites d'API Strava : voir `docs/strava-setup.md`. |
| Détail d'une activité | `get_activity` | `get-activity-details` (`activityId`, entier) | Texte : type/`sport_type`, date locale, temps en mouvement ET écoulé, distance, D+, vitesse moy./max, cadence moy., puissance moy., FC moy./max, calories, description, **nom** du matériel (`Gear: <nom>`, pas d'identifiant), effort perçu, `suffer_score`. **Pas de D−, pas de FC de récupération (HRR), pas de `bmr_calories`, pas de splits par km** : champs omis du bloc `arc`, jamais inventés. Renseigner `strava_activity_id` = `"s<ID>"` (préfixe `s` du projet). |
| Tours (laps) | `get_activity_splits` | `get-activity-laps` (`id`) | Laps tels que Strava les expose (blocs JSON bruts) — ce ne sont pas des splits par km réguliers. |
| Zones FC de l'athlète | — (profil) | `get-athlete-zones` | Référence ; le profil déclaré de l'athlète prime. |
| Matériel (inventaire) | `get_gear` | `get-athlete-shoes` | Chaussures avec distance cumulée côté Strava — **référence seulement**, jamais une attribution (voir « Matériel »). |
| Matériel attaché à une activité | `get_activity_gear` | **aucun équivalent fiable** | `get-activity-details` ne donne que le NOM : `gear_id` reste déclaré en chat ou `(par défaut)`, jamais deviné depuis ce nom. |
| Profil athlète | — | `get-athlete-profile`, `get-athlete-stats` | Référence, jamais substitués au profil déclaré. |
| Flux par seconde (analyse fine) | `get_activity_fit_data` (timeoute) | **pas via le MCP** : skill `fit-download` (`download_fit.py --source strava`, API REST) | `get-activity-streams` existe (pagination, `summary_only`…) mais sert à l'exploration ; les KPI passent par les fichiers `activities/fit/s<id>.json` normalisés. |
| Santé (HRV, FC de repos, sommeil, readiness) | `get_hrv_data`, `get_rhr_day`, `get_sleep_data`, `get_training_readiness` | **aucun équivalent** | Voir `[health].morning_check` : indisponibilité dite explicitement. |
| Calendrier / push de séances | `get_scheduled_workouts`, `schedule_workouts`… | **aucun équivalent** | Strava n'a pas de calendrier d'entraînement. Le plan reste dans `planning/` ; dire que rien n'est poussé vers la montre. |
| Outils qui AGISSENT (jamais en headless) | — | `connect-strava`, `disconnect-strava`, `star-segment` (écriture) | Réservés à une session interactive, avec confirmation explicite. |

**Fonctionnalités/champs Garmin sans portage Strava — indisponibles et
EXPLIQUÉS comme tels quand `[data].source = "strava"`, jamais devinés ou simulés :**

- **HRV, FC de repos, sommeil, score de readiness** : aucun outil ; `[health].morning_check`
  se dégrade explicitement (voir plus haut), y compris à `full`.
- **Push de séances au calendrier, upload de parcours** (`upload_course`,
  `course-strategist` reste limité à l'analyse GPX locale), **suppression de séance planifiée**.
- **Fréquence cardiaque de récupération (HRR, `recovery_hr_bpm`)**, **splits par km** (donc
  `course-comparison`, qui exige `splits`) : absents, omis du bloc `arc`.
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

**Matériel (#133).** Avec `[data].source = "garmin"`, `get_gear` / `get_activity_gear`
(lecture) et `add_gear_to_activity` (écriture) sont dans la liste blanche `GARMIN_TOOL_WHITELIST`.
Le coach associe **une fois** (proposition, jamais devinée) chaque matériel Garmin à une puce
`### Chaussures` du profil par un segment `garmin: <uuid>`, puis attribue `gear_id` avec la
priorité **déclaration de l'athlète (chat) > matériel attaché par Garmin > `(par défaut)`** (règle
exécutée par `python3 scripts/arc_index.py gear-attribution` ; un désaccord Garmin/athlète est
signalé une fois ; provenance dans `gear_source` ; un matériel Garmin non associé, ambigu ou
`(ignorée)` laisse `gear_id` absent avec `gear_source: "garmin_unmapped"` : la séance n'est alors
jamais créditée à la paire par défaut). Un seul `get_activity_gear` par activité NOUVELLE. Aucune
écriture Garmin sans confirmation dans la conversation, jamais en headless. **Avec
`[data].source = "intervals"`** : le serveur épinglé expose `get_gear_list` (inventaire, à titre
de référence — jamais utilisé pour attribuer) mais **aucun matériel par activité**
(`src/intervals_icu_mcp/tools/activities.py`/`activity_analysis.py` n'ont pas de champ gear,
vérifié au commit épinglé) : `gear_id` reste chat/`(par défaut)`, dit explicitement, jamais inventé. **Avec
`[data].source = "strava"`** (#164) : `get-athlete-shoes` (inventaire, référence) et le NOM du matériel dans
`get-activity-details` n'identifient aucune paire de façon attribuable — même règle : chat/`(par défaut)`.

**Fonctionnalités/champs Garmin sans portage intervals.icu —
indisponibles et EXPLIQUÉS comme tels quand `[data].source = "intervals"`,
jamais devinés ou simulés :**

- **Fréquence cardiaque de récupération (HRR, `recovery_hr_bpm`) et `splits`
  par km** : absents des activités synchronisées côté intervals.icu (voir la
  table ci-dessus) — omis du bloc `arc`, jamais inventés ; `course-comparison`
  (qui exige `splits`) n'est donc pas utilisable sur des activités
  synchronisées depuis cette source.
- **Upload de parcours** (`upload_course`, agent `course-strategist`) :
  `course-strategist` reste limité à l'analyse GPX locale (skill
  `gpx-analysis`) — pas d'envoi du parcours vers la montre/l'app tierce.
- **Score de readiness Garmin** : voir la table ci-dessus.

## Règles de fraîcheur des données

- Avant d'invoquer les outils Garmin, vérifier si le fichier MD du jour existe déjà — ne récupérer que si la date a changé ou si le fichier manque.
- Après CHAQUE récupération de données, persister immédiatement le fichier MD correspondant (ne jamais sauter, ne jamais dumper le JSON brut dans le chat).

## Skills

- `coach-setup` — **premier démarrage** (`/coach-setup`) : entretien mené par le modèle,
  écriture pilotée par `scripts/coach_setup.py` (qui ne remplace jamais une réponse
  existante), installation de `planning/Runner_Profile.md` et `planning/active_objective.md`
  depuis `templates/`. Relancer la commande est sans effet.
- `garmin-workout-scheduling` — push des séances planifiées au calendrier Garmin (schéma DTO exact, détail force, idempotence, vérification après push)
- `intervals-icu-best-practices` — pièges de création/mise à jour d'événements (`workout_doc`, vérification `start_date`) ; **primaire si `[data].source = "intervals"`** (push de séances), secondaire (Garmin d'abord) sinon
- `garmin-sync-efficiency` — discipline de récupération pour éviter l'explosion du contexte
- `workspace-data-contract` — **schéma du bloc ```` ```arc ````** par type de fichier (activité, santé, météo, semaine, nutrition, rapport, évaluation de parcours, plan de course), unités SI, validation par `scripts/arc_index.py --validate`. Charger avant d'écrire un fichier du workspace.
- `arc-backfill` — met au contrat les fichiers écrits avant lui, par lots, à partir de la liste produite par `python3 scripts/arc_index.py backfill-plan`.
- `coach-doctor` — **diagnostic d'installation en une commande** (`/coach-doctor`, `python3 scripts/coach_doctor.py`) : âge/échéance des tokens Garmin, joignabilité du MCP `garmin`, validité TOML de la config, complétude du profil athlète, fraîcheur de l'index `.arc/coach.db`, fichiers hors contrat, planification du daily-sync, configuration ntfy, synchronisation du matériel Garmin (`gear_sync`, statique : liste blanche + segments `garmin:` du profil, aucun appel Garmin), historique sans matériel (`gear_history`, statique, ℹ️, plus de la moitié des séances à `garmin_activity_id` sans `gear_id` : propose le rattrapage `scripts/garmin_gear_backfill.py`)., lecteur FIT (`fitparse` dans l'environnement MCP de la source), connexion Strava (`strava_connection`, #164 : Node.js >= 18, wrapper, serveur déclaré, jetons présents et non lisibles par d'autres — valeurs jamais affichées, aucun appel réseau). Ne lit ni n'écrit rien de sensible ; à charger dès qu'un symptôme d'installation apparaît, avant de deviner la cause.
- `garmin-daily-sync` — **prompt d'orchestration headless** (`/garmin-daily-sync`) lancé par le cron de la machine coach (`scripts/daily-sync.sh`) — aux heures fixes, ou seulement quand Garmin a du neuf avec `[sync].mode = "watch"` (`scripts/garmin_watch.py`, sondage sans LLM, indice `trigger=` passé au skill) —, depuis le téléphone (Remote Control) ou l'IDE : délègue au `coach` + `garmin-sync-efficiency`, ne pose aucune question, ne récupère que les dates manquantes, termine par un bloc ```` ```resume ```` (≤ 5 lignes) envoyé en notification push (ntfy). Voir `docs/mobile.md`. Ajoute une ligne à `Alerte :` quand une séance synchronisée fait franchir son seuil d'usure à une paire de chaussures (#132, `arc_index.py gear --activities`, une seule fois par franchissement — identifié par la séance, pas par la date).
- `weather-forecast` — récupération + persistance des prévisions météo (wttr.in via webfetch), résolution du lieu (override fichier semaine → `active_objective.md` défaut → profil défaut → demander), seuils de catégorie (🟢/🟡/🟠/🔴), créneau optimal par séance outdoor. Utilisé par l'agent `coach` à chaque validation hebdo/journalière.
- `session-parts-analyzer` — analyse au niveau segment des drills (strides, montées, intervalles, sprints) depuis FIT/MCP. L'analyse détaillée délègue le téléchargement FIT à `fit-download`.
- `fit-download` — (#164 : avec `[data].source = "strava"`, `download_fit.py --source strava` normalise les flux par seconde Strava en `activities/fit/s<id>.json`, aucun `.fit`) **téléchargement des fichiers FIT + records GPS en bypassant le MCP** (qui timeoute sur les FIT) : `scripts/download_fit.py`, source suivant `[data].source` — Garmin via `garminconnect` + tokens locaux `~/.garminconnect`, ou intervals.icu via son API REST + la clé API du serveur MCP (activités importées depuis Strava exclues, voir « Backends MCP »). Charger dès qu'une séance doit être analysée à précision sub-km (profil de parcours, montées, dérive FC×élévation, analyse stride/sprint/intervalle, comparaison de parcours). Toujours persister l'analyse dans le MD de l'activité dans la langue des documents (`config/workspace.toml`), ne jamais dumper le JSON brut.
- **Rattrapage du matériel Garmin** (`scripts/garmin_gear_backfill.py`, #145) — attribue la paire Garmin aux séances **déjà** dans `activities/` (un appel `get_gear_activities` par paire), propose les puces `### Chaussures` manquantes. **Simulation par défaut**, `--apply` pour écrire ; ne remplace jamais un `gear_id` déjà présent (priorité athlète), respecte `(ignorée)`, ne pose jamais `(par défaut)`, refuse `--apply` si une paire Garmin est en erreur/tronquée, n'ajoute qu'un segment `garmin:` aux puces existantes. Dépend de `garminconnect` + jetons `~/.garminconnect` (exception documentée, comme `fit-download`). Le `coach` le propose UNE fois, en interactif seulement, toujours en simulation d'abord et `--apply` après un « oui » explicite ; `garmin-daily-sync` (headless) ne le lance jamais. Voir `docs/garmin-setup.md`.
- `gpx-analysis` — **analyse générique de parcours GPX** (fichiers Strava/Garmin/course) via `scripts/analyze_gpx.py` (stdlib) : distance réelle, D+/D- (lissage anti-bruit), profil par km, montées significatives, boucle vs point-to-point, verdict de compatibilité vs une cible (distance/D+). Charger dès que l'utilisateur fournit un GPX et veut l'analyser ou l'évaluer contre une séance planifiée. Persister la fiche d'évaluation dans `planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md` (langue des documents). Utilisé par `course-strategist` pour l'entrée GPX.
- `gear-inspection` — **inspection photo des chaussures** (#135) : le coach la **propose** (jamais imposée) environ tous les 200 km d'une paire, à l'alerte de seuil ou sur demande (`python3 scripts/arc_index.py inspections`, jamais en headless) ; protocole photo (semelles, profil, arrière, tige, échelle), grille de lecture 🟢🟡🟠🔴, comparaison avec l'inspection précédente de la même paire, **indices** de foulée depuis la zone d'usure (signal faible, jamais un diagnostic ; aucune mesure en mm sans échelle ; jamais de changement de foulée recommandé sur une photo), relais à `medical` seulement s'il est dans `[agents].enabled`. Persiste `gear/YYYY-MM-DD_<gear_id>_inspection.md` (type `gear_inspection`) et produit, à la retraite d'une paire, son bilan de carrière (`arc_index.py gear-career --gear ID`). Dynamique de course mesurée (temps de contact, balance, oscillation — FIT, #151) : `python3 scripts/arc_index.py gait-summary [--weeks N]` (lecture seule, `/api/gait`, carte « Foulée » de la vue Santé) — tendances, confiance, désaccords usure/mesure (la mesure prime) ; sens gauche/droite de la balance non établi ; jamais un diagnostic, aucune modification de charge ; règles d'usage par les agents : story ultérieure. Re-extraction sur un FIT déjà téléchargé : `download_fit.py --refresh-dynamics` (skill `fit-download`).
- `course-comparison` — **analyse comparative de séances sur le même parcours/lieu** via `scripts/compare_course.py` : découverte de toutes les activités d'un lieu (fichiers MD Garmin), alignement des boucles/segments, comparaison des montées, tableau global (date, distance, D+, durée, allure, FC moy/max, premier tour, montées) et dump JSON. Charger quand l'utilisateur demande de comparer des séances d'un même lieu ou d'évaluer la progression sur un parcours connu. Prérequis : chaque MD d'activité porte son bloc ```` ```arc ```` avec `location` et `splits` (fichiers anciens : bloc YAML `## Données brutes Garmin (référence)` + `## Analyse par splits (km)`). Persister les rapports dans `rapports/YYYY-MM-DD_comparaison_<lieu>.md`.
- `inspection` — **commande courte `/inspection [paire]`** (#149) : lance l'inspection photo d'UNE paire. Sans argument, liste les paires actives avec leur rappel (`arc_index.py inspections --unreferenced-photos`) et propose la plus urgente ; avec argument, résout la paire contre le profil (`id:`, nom, slug, `garmin:`) et demande si ambigu ou inconnu, jamais de devinette. Donne le protocole photo et la façon d'envoyer les photos (copie dans la boîte de dépôt `gear/photos/` = chemin fiable quel que soit le client ; image collée = vue mais non enregistrable, `photos` absent et dit ; téléphone à valider), puis charge `gear-inspection`. Interactif uniquement, ne propose jamais `/coach-setup`, n'écrit jamais d'inspection sans photo ni description.
- `log` — **saisie libre en une phrase** (`/log`, #67) : « 2 gels + 500 ml au km 15, genou gauche 3/10, RPE 7 ». Le modèle extrait les entités, `scripts/arc_log.py` (stdlib, JSON-in/JSON-out) fait l'arithmétique et la correspondance catalogue (`resources/nutrition/catalogue-produits-*.md`) — jamais l'inverse. Produit inconnu/ambigu → toujours demander, jamais inventer. Écrit `carbs_g`/`fluid_intake_ml`/`rpe` dans l'activité du jour (`activities/`, agent coach) et `pain` dans `medical/YYYY-MM-DD_health.md` (agent medical si activé, sinon coach) ; une douleur ≥ 7/10 déclenche une recommandation de consultation.