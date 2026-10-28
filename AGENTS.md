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
| `[data].source` | `garmin` (défaut) \| `intervals` \| `strava` \| `coros` — source de données primaire des agents. Voir « Backends MCP » et les tables de correspondance des outils (`skills/data-source-mapping/SKILL.md`, #68, #164, #168). |
| `[health].cycle_tracking` | `off` (défaut) \| `garmin` \| `intervals` \| `coros` \| `manual` — contexte du cycle menstruel, **opt-in strict** (#166). À `off` (ou absent/invalide) : aucune donnée lue, aucun outil `get_menstrual_*` exposé, **aucune mention par aucun agent**. Actif : la phase (`cycle_phase`/`cycle_day`/`cycle_source` du bloc santé) n'est qu'un **contexte** à côté d'une HRV/FC de repos décalée, jamais une règle ni un diagnostic, jamais un assouplissement d'un verdict rouge ; `medical` signale une absence prolongée de règles comme signal de vigilance RED-S (consultation, sans diagnostic). `garmin` n'ajoute les deux outils à la liste blanche qu'à l'installation (`./install.sh --cycle-tracking garmin`, ou relance après le choix en config) ; `intervals` lit `other.menstrual_phase` de `icu_get_wellness_for_date` ; `coros` (source COROS seulement) lit `queryMenstruationCycles` (« No menstrual cycle data found » = aucune phase, jamais déduite des durées par défaut). Saisie `manual` via `/log`. Voir `docs/cycle-menstruel.md`. |
| `[health].source` / `[health.openwearables]` | `primary` (défaut) \| `openwearables` — d'où vient la **santé** du bilan matinal (HRV, FC de repos, sommeil, score natif du fabricant), **opt-in strict** (#216, #221). À `primary` (ou absent/invalide) : la santé vient de `[data].source`, **rien ne change, aucun appel et aucune mention par aucun agent**. `openwearables` : instance Open Wearables auto-hébergée de l'athlète, lecture seule, **un seul appel par jour** `python3 scripts/arc_openwearables.py health-day [--date D] --json` ; les outils santé Garmin ne sont alors pas appelés (une seule source santé par jour) et les séances continuent de venir de `[data].source`. `[health.openwearables]` : `base_url`, `provider` (un seul fabricant), `user_id`, `api_key_file` (hors dépôt, mode 600), `stale_after_h`. Se pose à l'installation (`./install.sh --health-source openwearables …`). Voir « Bilan matinal » ci-dessous et `docs/open-wearables.md`. |
| `[nutrition].garmin_sync` | `off` (défaut) \| `ask` — poussée des apports vers Garmin Connect, **opt-in strict** (#167). À `off` (ou absent/invalide) : aucun outil exposé, **aucune mention par aucun agent**. `ask` : après un `/log` ou un rapport nutrition, l'agent **propose** (jamais automatique, **jamais en headless**, « oui » explicite par poussée) de pousser vers le journal alimentaire et l'hydratation Garmin ; plan, doublons et idempotence décidés par `scripts/arc_nutrition_sync.py`, trace `garmin_pushed` dans le bloc `arc`. **Une seule source de vérité par jour** : fichiers du dépôt (miroir Garmin) **ou** journal Garmin importé (`intake_source: "garmin"`), jamais les deux — pas de double comptage. Indisponible avec `[data].source = "intervals"`, `"strava"` ou `"coros"` (dit explicitement). Outils ajoutés à l'installation (`./install.sh --nutrition-sync ask`). Voir `docs/nutrition-garmin.md`. |
| `[home_trainer].platform` / `mywhoosh_calendar` | `off` (défaut) \| `mywhoosh` — **opt-in strict** (skill `mywhoosh-route`). À `off` (ou absent/invalide) : **aucune mention par aucun agent**. `mywhoosh` : pour chaque séance `home_trainer`/`indoor_cycling` planifiée, le coach propose un parcours MyWhoosh qui tient dans la durée à la puissance calibrée sur la plage FC visée (`arc_index.py power-hr`), l'écrit dans `workoutName`/`description` de la séance Garmin et la trace dans `virtual_route` de la semaine. `mywhoosh_calendar = "ask"` : inscription au calendrier MyWhoosh **proposée**, « oui » explicite, jamais en headless. Équipement déclaré dans le profil (« ### Vélo & home trainer »). |
| `[vanoor].export` / `output_dir` | `off` (défaut) \| `on` — export des séances vers l'app Vanoor (Apple Watch), **opt-in strict** (skill `vanoor-export`). À `off` (ou absent/invalide) : **aucune mention par aucun agent**. `on` : à chaque validation de semaine, le coach écrit les séances `running`/`trail` structurées (étapes composées depuis les consignes, plages FC/allures de `arc_workout_targets.py`, jamais inventées) dans `<output_dir>/weeks/semaine-<lundi>.vanoor` ; le `course-strategist` écrit le plan de course dans `<output_dir>/races/` (une étape par segment, allure du scénario, rappel à chaque ravito). Un **export, pas un push** : `python3 scripts/arc_vanoor.py` (`week` \| `race` \| `validate`) n'écrit que dans `output_dir` (vide = `exports/vanoor/` du workspace, gitignoré), ne contacte aucun service, permis en headless ; l'athlète importe le fichier dans l'app iPhone. Ne décide jamais si une séance a lieu ni son intensité. |
| `[coros].mcp` | `off` (défaut) \| `relay` — montre COROS, **opt-in strict**. À `off` : aucun serveur, **aucune mention par aucun agent**. `relay` (`./install.sh --coros`) : serveur MCP `coros` déclaré pour toutes les IA, relais local `scripts/arc_coros_mcp.py` vers le MCP officiel de COROS ; l'athlète se connecte une seule fois (`python3 scripts/arc_coros_auth.py login`, interactif, jamais en headless), jetons dans `~/.config/ai-running-coach/coros/` (600), jamais affichés ni lus ailleurs. Avec une autre source primaire, les lectures COROS se font dans la session, sans persistance. **`[data].source = "coros"`** (`./install.sh --source coros`, implique `relay`) : COROS devient la source de données, comme Garmin — table « Garmin ↔ COROS » (`skills/data-source-mapping/SKILL.md`). Voir « Backends MCP » et `docs/coros.md`. |
| `[pacing.personal]` | Coefficients de pacing personnels (#188) : `night_penalty_pct`, `technicity_scale`, `heat_hot_factor`, `altitude_scale`, `evidence` (preuves cumulées). **Jamais écrite sans confirmation explicite de l'athlète** (`arc_race_debrief.py --calibrate --apply`), dans `workspace.user.toml` ; lue par `arc_race_pacing.py`, les drapeaux CLI priment. Absente = défauts du projet. |
| `[health].heat_threshold_c` | Seuil (°C, borne incluse) « séance chaude » pour le KPI d'acclimatation à la chaleur (#38, `scripts/arc_index.py heat-acclimation`). Défaut `25.0`. Indépendant de `morning_check` ; une valeur invalide n'interrompt jamais l'index (repli sur le défaut, avertissement). |
| `[telegram].*` | Bot Telegram (#174, `docs/telegram.md`) : `enabled`, `allowed_chat_ids` (liste blanche, vide = tout refusé), `token_file` (hors dépôt, mode 600), `send_summary`, `chat_bridge` (conversation libre opt-in vers le service `arc_chat`). Canal de l'**athlète** : les agents n'y écrivent rien eux-mêmes. |
| `[elevation].dem` / `[privacy].dem_for_activities` | Correction d'altitude par MNT (#176, `scripts/arc_dem.py`, `docs/elevation.md`). `dem` : `off` (défaut, aucun envoi) \| `auto` (GPX de course corrigés d'office : IGN RGE ALTI en France, Copernicus via Open-Meteo ailleurs, coordonnées amincies seules). `dem_for_activities` (défaut `false`) : opt-in pour `arc_index.py dem-check <séance>` — comparaison, jamais un remplacement de l'altitude enregistrée. |
| `[update].check` | `true` (défaut) \| `false` — vérification des nouvelles releases (`scripts/arc_update_check.py`, au plus un appel GitHub par 24 h, cache `~/.cache/ai-running-coach/`). Signalée par le tableau de bord, le hook `SessionStart` de Claude Code (`arc_update_check.py --hook`, posé par `install.sh` : **le mentionner une seule fois**, en une ligne, en proposant `/update-coach` ; jamais pendant une décision médicale) et une notification dédiée du daily-sync (une fois par release). Jamais de mise à jour en headless ni sans « oui » explicite. `false` = aucun appel, aucune mention. |
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
question factuelle précise ; `/inspection` (#149), `/shoes` (#302) et `/update-coach` à une demande précise : aucune
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
(les deux dans le même appel `icu_get_wellness_for_date`) **et l'indisponibilité du
readiness est dite explicitement** ("readiness indisponible — source
intervals.icu"), jamais remplacée par le champ subjectif présenté comme
équivalent. À `minimal`, la ligne unique devient "readiness indisponible
(source intervals.icu)" plutôt qu'un score. Voir la table de correspondance
(`skills/data-source-mapping/SKILL.md`).

**Avec `[data].source = "strava"` (#164) :** Strava n'expose ni HRV, ni FC de
repos, ni sommeil, ni readiness (voir « Backends MCP » et la table
Garmin ↔ Strava de `skills/data-source-mapping/SKILL.md`). Le bilan matinal ne peut donc **pas** s'appuyer sur des
données de santé : à `full` comme à `minimal`, l'agent dit explicitement
« HRV / FC de repos / readiness indisponibles — source Strava » (jamais un
score ni une valeur inventés, jamais un « tout va bien » par défaut) et
planifie sur la charge, l'historique `activities/` et le ressenti **déclaré par
l'athlète** — comme à `off`, mais en le disant. Une séance annulée pour raison
médicale (blessure, douleur déclarée) reste annulée.

**Avec `[data].source = "coros"` (#168) :** même triptyque que Garmin, par le MCP COROS
(table « Garmin ↔ COROS » de `skills/data-source-mapping/SKILL.md`) : à `full`, HRV nocturne (`querySleepHrv`, évaluation
officielle du jour du réveil) + FC de repos (`queryRestingHeartRate`) + **récupération COROS**
(`queryRecoveryStatus`) — les trois, jamais deux. La récupération COROS n'est **pas** le Training
Readiness : toujours nommée « récupération COROS N % », recopiée dans `provider_scores`
(`category: "recovery"`, `provider: "coros"`, 0-100), jamais dans `readiness_score`, jamais comparée
aux seuils Garmin ; c'est un état **actuel** (pas d'historique), qui se met à jour en continu : jamais la
preuve qu'une nuit a été lue. Le score de sommeil COROS va de même dans `provider_scores`
(`category: "sleep"`), jamais dans `sleep_score`. `health_source: "coros"`. À `minimal` : une ligne,
« récupération COROS N % » (`-1%` = « récupération COROS indisponible »). **Nuit pas encore calculée**
(`Sleep Score: 0`, HRV « No data found », FC de repos `No data` au jour du réveil — la synchronisation
du sommeil COROS peut arriver plusieurs heures après le réveil) : le dire, et en headless **aucun**
fichier santé n'est écrit (le run suivant ou la surveillance réessaie) ; en interactif, planifier sur la
charge, l'historique et le ressenti déclaré en le disant, jamais un « tout va bien » par défaut. Une HRV
sans ligne de base (environ 5 nuits avec la montre) : « ligne de base COROS en construction ». La première
nuit avec une nouvelle montre n'est jamais publiée (ni dans l'app ni dans le MCP). **Nuit coupée** :
COROS peut couper une nuit continue en sommeil principal + « sieste » (`split_suspected` de
`arc_coros_sleep.py`) — le dire avec les deux morceaux, demander en interactif (la déclaration de l'athlète
prime), le signaler dans le résumé en headless ; un sommeil court issu d'un découpage douteux ne fait
jamais passer un verdict à l'orange ou au rouge à lui seul.

**Avec `[health].source = "openwearables"` (#221) :** la santé du bilan matinal ne
vient plus de `[data].source` mais d'une instance Open Wearables, en lecture
seule, par **un seul appel par jour** : `python3 scripts/arc_openwearables.py
health-day --date <D> --json` (sortie 0 = lu, même si des mesures manquent ; 2 =
configuration incomplète ; 3 = instance injoignable ou clé refusée). Il rend le
bloc `arc` à persister tel quel (`health_source`, `health_provider`,
`health_device`, `hrv_overnight_ms`, `hrv_sdnn_ms`, `resting_hr_bpm`, `sleep_*`,
`provider_scores`), `unavailable` (la cause de chaque mesure absente),
`warnings` et `freshness`. L'agent ne calcule rien. Règles :

- **Une seule source santé par jour.** Les outils santé Garmin (`get_hrv_data`,
  `get_rhr_day`, `get_sleep_data`, `get_training_readiness`) ne sont **pas**
  appelés ; avec intervals.icu primaire, `icu_get_wellness_for_date` n'est pas
  utilisé pour HRV, FC de repos ni sommeil (il reste permis pour la seule phase du
  cycle quand `[health].cycle_tracking = "intervals"`). Les séances, elles, sont
  lues comme avant via `[data].source`. Avec Strava primaire, le message
  « indisponibles — source Strava » disparaît au profit des données Open Wearables.
- **`full`** : HRV (RMSSD) + FC de repos + **score natif** de readiness/récupération
  du fabricant s'il existe. Sinon : « readiness indisponible — <fabricant> via
  Open Wearables », jamais autre chose à la place. **`minimal`** : une ligne, soit le
  score natif (« Readiness Oura 82/100 », « Nightly Recharge Polar 4/6 »), soit
  « readiness indisponible (Open Wearables, <fabricant>) ». **`off`** : rien n'est
  lu, aucune mention.
- **Avec `[data].source = "coros"`** : les outils santé COROS (`querySleepHrv`, `querySleepOverview`,
  `queryRestingHeartRate`, `queryRecoveryStatus`, `queryDailyHealthData`) ne sont pas appelés non plus.
- **Nommer, jamais convertir.** Toujours « <catégorie> <Fabricant> <valeur>/<borne
  haute> », recopié de `provider_scores`. Jamais « Training Readiness », jamais
  remis sur 100, jamais comparé aux seuils Garmin. `readiness_score` et
  `sleep_score` ne sont jamais remplis depuis Open Wearables.
- **HRV en SDNN (Apple Health) :** affichée à titre indicatif (« HRV SDNN 52 ms
  (Apple Health — non comparable à une RMSSD) »), jamais utilisée comme tendance HRV
  du verdict ; le triptyque `full` est dit incomplet : « HRV RMSSD indisponible ».
- **Ligne de base** (`arc_index.py hrv-baseline`) : calculée par source. Si elle est
  `en_construction` après un changement d'appareil, le dire (« ligne de base en
  reconstruction — N nuits avec <fabricant> ») ; le verdict s'appuie alors sur la FC de
  repos, le score natif et le ressenti déclaré, jamais sur la bande de l'ancienne source.
- **Pannes et retards, toujours dits.** Sortie 3 : « santé Open Wearables indisponible :
  instance injoignable » (ou clé refusée), puis planification sur la charge,
  l'historique `activities/` et le ressenti déclaré, comme à `off` mais en le disant, et
  `/coach-doctor` proposé en interactif seulement. Pas encore de nuit pour D
  (synchronisation en retard) : dit, et même repli. Données périmées
  (`freshness.stale`) : « dernière synchronisation Open Wearables il y a 40 h ». Jamais
  un « tout va bien » par défaut : une donnée manquante ne fait jamais passer un
  verdict orange ou rouge au vert, et une douleur déclarée ou une annulation
  médicale garde son protocole.
- **Persistance** : `medical/YYYY-MM-DD_health.md` porte l'objet `arc` rendu par le
  script, plus `morning_check`, `verdict`, `verdict_reason` et `missing_reason`
  (recopié de `unavailable`), validé par `arc_index.py --validate`. En headless
  (`/garmin-daily-sync`), si la nuit de D n'est pas encore arrivée, **aucun** fichier
  santé n'est écrit (le run suivant réessaie) et le résumé le dit.

## Carte des dossiers

| Dossier | Contenu | Convention |
|---|---|---|
| `activities/` | Journaux d'entraînement (`gear_id` = chaussure, `gear_ids` = matériel hors chaussures, #134) | `YYYY-MM-DD_type.md` (running, trail, strength, indoor_cycling, home_trainer, hiking, elliptical, rest) |
| `medical/` | Sommeil, HRV, récupération, blessures, météo | `YYYY-MM-DD_health.md`, `YYYY-MM-DD_meteo.md` |
| `nutrition/` | Journaux nutrition & plans de ravitaillement | `YYYY-MM-DD_nutrition.md` |
| `planning/` | Plans d'entraînement, objectifs, stratégies de course, **décisions tracées** | `active_objective.md` est la **source de vérité** de l'objectif courant ; `Runner_Profile.md` est le profil de l'athlète. Les deux sont installés depuis `templates/` par `/coach-setup`. Une décision (garde-fou, bilan matinal, blessure…) = un fichier `YYYY-MM-DD_decision_<slug>.md`. **Effet des décisions (#175)** : ce qui s'est passé APRÈS chaque décision (HRV/FC de repos/readiness, douleur, ACWR, RPE, découplage, conformité, fenêtres avant/après par déclencheur) est **dérivé** par `python3 scripts/arc_index.py decision-effects [--trigger T] [--days N] [--text]` (JSON par défaut, synthèse par déclencheur × nature de l'action dérivée de `before`/`after` × issue ; `/api/decision-effects`, vue « Décisions »), jamais écrit dans les fichiers de décision ; `/why` et le coach peuvent le citer — **corrélation, pas causalité**, pas de « tendance » sous 5 cas, jamais pour assouplir un garde-fou `block`, une décision médicale ni un verdict rouge. |
| `rapports/` | Rapports de synthèse périodiques (propriété du **coach**) | `YYYY-MM-DD_rapport.md` |
| `gear/` | Inspections photo du matériel (propriété du **coach**, skill `gear-inspection`, #135) et fiches de caractéristiques des paires `gear/specs/<gear_id>.md` (skill `shoe-specs`, #298) ; photos dans `gear/photos/` (jamais dans le dépôt public ; **boîte de dépôt** : les images non citées par une inspection sont à rattacher à une paire, renommer `AAAA-MM-JJ_<gear_id>_<vue>.<ext>`, jamais supprimer) | `YYYY-MM-DD_<gear_id>_inspection.md` |
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
| `coach` | Plans d'entraînement, analyse des activités Garmin (**incl. HRR `recovery_hr_bpm` dans chaque retour de séance**), ajustements de séances, **push des séances au calendrier Garmin** (`schedule_workouts`, Garmin d'abord), rapports hebdomadaires. **Bilan matinal avant toute décision de séance, au niveau fixé par `[health].morning_check` : à `full` (défaut), HRV + FC de repos (`get_rhr_day`) + readiness — les trois, jamais deux.** **Nouveau bloc (#189) : part du gabarit de `config/plans/` choisi par distance d'objectif (`arc_index.py plan-templates --distance-km D`), jamais au-dessus du profil, du bilan matinal ni des garde-fous.** **Inclut toujours la météo + le créneau optimal (matin tôt / midi / soir) dans chaque validation hebdomadaire/journalière (charger le skill `weather-forecast`, résoudre le lieu via la règle de précédence stricte).** **Cibles de séance ajustées à la chaleur prévue (#171, `arc_workout_targets.py targets --heat`, coefficients partagés avec le pacing de course dans `arc_heat.py`) : allure ralentie, FC inchangée, jamais d'intensité maintenue en 🔴 — poussées telles quelles sur la montre.** **Ligne « Dépense : Garmin X kcal · modèle Y kcal (±Z %) » dans chaque retour de séance running/trail/hiking/walking (`arc_index.py energy`), alerte si écart > 15 % — Garmin reste la référence.** **Matériel hors chaussures (#134) : kits attribués via `gear_ids` (`arc_index.py equipment --kit`), entretien noté en chat, ligne « Matériel : … » (alerte/proche du seuil), rappel frontale/poche avant séance de nuit/longue.** **Vitesse critique (#169) : `arc_index.py pace-curve` (courbe allure-durée GAP, CS et réserve anaérobie D′, refus explicite si données insuffisantes) ; cibles d'intervalles `tempo`/`threshold`/`vo2max` en % de CS (`arc_workout_targets.py`, champ `cs_target`) UNIQUEMENT si l'ajustement est valide, en complément de la zone FC ; écart > 5 % avec le seuil lactique Garmin (`--lt-speed-ms`) signalé avec les deux valeurs, jamais arbitré.** **Affûtage (#172) : toute décision d'affûtage cite `python3 scripts/arc_index.py load-forecast` (forme prévue le jour J, pic de fatigue, ACWR projeté ; `--compare <fichier>` pour une variante) — une ESTIMATION à partir du planifié (même estimateur que R1, recalé réel/estimé quand c'est mesurable), jamais une mesure ; semaines non planifiées = charge nulle, dites.** **Renforcement (#191) : exercices et programmes tirés de la bibliothèque livrée (`arc_index.py strength --phase/--use/--equipment`, `config/strength/`), jamais inventés ; correspondances Garmin vérifiées dans le catalogue officiel (liste blanche `GARMIN_VERIFIED` de `arc_strength.py`) ; matériel inconnu = question, pas de devinette ; approximations du projet, jamais un diagnostic ; push inchangé (confirmation explicite, jamais headless).** **Prévention ciblée (#192) : une douleur déclarée (`/log`, Telegram, bilan) → `arc_index.py prevention` ; routine douce seulement pour une gêne légère (≤ 3/10), connue et stable, sinon aucun exercice et consultation (seuil `[injury_risk].pain_consult_threshold`, douleur vive, aggravation, > 7 jours, drapeau de risque de blessure) ; `medical` décide s'il est activé (le coach relaie, jamais d'assouplissement), sinon le coach applique les règles et dit « ce n'est pas un avis médical » ; zones seulement, jamais un diagnostic ; proposée à la prochaine interaction, jamais poussée automatiquement.** |
| `medical` | Analyse sommeil/HRV/récupération (**incl. HRR lors de l'évaluation de l'impact d'une séance**, et **FC de repos dans le bilan matinal ; avec `[health].source = "openwearables"` (#221), la santé du bilan vient d'Open Wearables, scores natifs nommés jamais convertis**), protocoles blessures, gatekeeper de disponibilité, **décision de prévention ciblée sur une douleur déclarée (#192, `arc_index.py prevention`, le coach relaie sans assouplir),** contraintes de coordination pour coach/nutritionniste |
| `nutritionist` | Macros, poids de course, plans de ravitaillement. **Poussée opt-in des apports vers Garmin (#167, `[nutrition].garmin_sync`) : propose, « oui » explicite, jamais en headless ; une seule source de vérité par jour.** **Pas de serveur MyFitnessPal** — les apports viennent des rapports manuels de l'utilisateur ; croiser avec les calories brûlées Garmin (référence par défaut ; le modèle `energy` n'est qu'un contrôle, jamais additionné au `burned_kcal` journalier — pas de double comptage) |
| `course-strategist` | Analyse GPX/URL de course → plan de course (allures ×3 scénarios, nutrition, météo, équipement, **dépense énergétique prévue par section/scénario via `arc_race_pacing.py --pack-kg`, en regard du plan de ravitaillement**), **pénalité de nuit (#184) : avec `--race-date`, `--start` explicite et `--tz`, `arc_race_pacing.py` pénalise les sections courues de nuit (lever/coucher calculés localement, `night_fraction`/`night_factor` par section, heures de frontale par scénario) ; sans ces trois entrées, aucun facteur de nuit n'est appliqué et `night.reason` le dit.** **technicité du terrain (#186) : `--technicity <fichier.json>` (déclarée) et/ou `--technicity osm` (OpenStreetMap via Overpass, réseau opt-in, GPX de course seulement) → `technicity` par section, pondérée par la pente, appliquée avant la nuit ; sans l'option, rien ne change.** **Recalibrage au débrief (#188) : `arc_race_debrief.py … --calibrate` attribue l'erreur plan/réalisé à chaque facteur (nuit, technicité, chaleur, altitude ; contraste stratifié, refus si trop peu de segments ou facteur confondu) et PROPOSE des coefficients personnels avec attrition vers le défaut ; `[pacing.personal]` (lu par `arc_race_pacing.py`, drapeaux CLI prioritaires) n'est écrit (`--apply`) qu'après confirmation explicite de l'athlète.** **Pénalité d'altitude (#185) : au-dessus de 1 500 m (altitude moyenne de section, GPX ou MNT), facteur de temps tiré de Wehrlin & Hallén 2006 (traduction en vitesse = approximation du projet), réduit par `--altitude-acclimated-days` et par l'exposition mesurée (`arc_index.py altitude-exposure`, 14/28 j, `/api/altitude-exposure`, carte de la vue Santé) ; athlète supposé non acclimaté sans déclaration ; sous le seuil, plan inchangé (clé `altitude` seule).** Enrichissement points d'eau OSM, upload de parcours Garmin via l'outil `upload_course` (montre COROS : aucun outil de parcours, fiche **Pace Strategy** à recopier dans l'app, `arc_coros_workout.py pace-strategy`) **Contrôle du matériel de course (#134) : `gear` du plan croisé avec l'inventaire du profil (`arc_index.py equipment --race-plan`) → manquant / jamais utilisé à l'entraînement / sous alerte, jamais inventé.** |
| `sports-director` | Choix de la course et du moment : recherche de courses organisées (recherche web, **chaque course sourcée, date vérifiée sur le site officiel ou « à confirmer », jamais inventée**), conseil sur le prochain objectif depuis l'historique réel (`arc_index.py history-summary` : records à pied, volume hebdo, charge — signalée périmée après un trou de synchronisation —, rapports de course), calendrier de saison (rôles Objectif principal / Préparation / Plaisir), faisabilité pour l'athlète avant toute recherche. Consulte `medical`/`coach` seulement dans des cas précis. **Ne modifie jamais `planning/active_objective.md`** (propose les valeurs), ne persiste rien, ne pousse rien vers Garmin/intervals.icu, jamais en headless. |

Lors d'une délégation, écrire le prompt de tâche en anglais mais ajouter
explicitement **« Respond in <langue des documents> »** (résolue via
`config/workspace.toml` → `[language].documents`, défaut FRENCH) si la sortie
est destinée à l'utilisateur.

## Backends MCP

**`[data].source` décide lequel des deux est la destination PRIMAIRE (#68) —
voir la table de configuration ci-dessus.** Par défaut (`source = "garmin"`),
rien ne change par rapport au comportement historique : la section ci-dessous
et les tables de correspondance (`skills/data-source-mapping/SKILL.md`) ne prennent effet que si l'installation
a été faite avec `./install.sh --source intervals` (ou `[data].source =
"intervals"` posé à la main).

- **`garmin`** — activités, sommeil, HRV, readiness, poids (pesées, lecture seule, #222), **calendrier des séances planifiées**, upload parcours/séances. **Mode direct par défaut** : le serveur MCP `garmin` expose `garmin-mcp` avec une liste blanche d'outils (`GARMIN_ENABLED_TOOLS`). **Mode passerelle (optionnel, power user)** : `leanproxy_invoke_tool(server="garmin", tool="...")` via leanproxy-mcp (économie de tokens ~98 %, chargement paresseux des schémas). **PRIMAIRE si `[data].source = "garmin"` (défaut)** ; sinon non installé par `install.sh` (voir ci-dessous).
- **`Intervals.icu`** — événements, wellness, activités, via le serveur MCP communautaire [`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp) (fork maintenu de `eddmann/intervals-icu-mcp`, 67 outils en mode de suppression `safe` par défaut, **tous préfixés `icu_`**, `intervals-icu-mcp` + `intervals-icu-mcp-auth`, voir `docs/intervals-setup.md`). **PRIMAIRE si `[data].source = "intervals"`** (installé par `./install.sh --source intervals`) : `coach`/`medical`/`garmin-daily-sync` utilisent alors ses outils au lieu de ceux de `garmin`, table de correspondance de `skills/data-source-mapping/SKILL.md`. **SECONDAIRE sinon** (défaut) : uniquement si l'utilisateur le demande explicitement (skill `intervals-icu-best-practices`), serveur non installé par `install.sh`, configuration manuelle (`docs/faq.md`).
- **Cycle menstruel (#166, opt-in)** : `get_menstrual_data_for_date(date)` et `get_menstrual_calendar_data(start_date, end_date)` (lecture seule ; réponse = JSON brut Garmin, forme non documentée par `garmin-mcp`) ne sont dans la liste blanche **que si** `[health].cycle_tracking = "garmin"` à l'installation. Côté intervals.icu : `other.menstrual_phase` de `icu_get_wellness_for_date`. Côté Strava (#164) : aucune donnée de cycle — seul `manual` a un effet.
- **Apports vers Garmin (#167, opt-in)** : `get_custom_foods`, `get_nutrition_daily_food_log`, `get_hydration_data`… (lecture) et `create_custom_food`, `log_custom_food`, `log_food`, `add_hydration_data` (ÉCRITURE Garmin, « oui » explicite, jamais en headless) ne sont dans la liste blanche **que si** `[nutrition].garmin_sync = "ask"` à l'installation. `delete_food_log`, `update_custom_food`, `upsert_and_log` ne sont jamais exposés. Mode direct uniquement (refusé derrière la passerelle leanproxy : écritures non filtrables en headless). Aucun équivalent intervals.icu ni Strava.
- **`Strava`** (#164) — activités + flux par seconde. **PRIMAIRE si `[data].source = "strava"`** (installé par `./install.sh --source strava`, voir `docs/strava-setup.md`) : serveur MCP **communautaire** [`r-huijts/strava-mcp`](https://github.com/r-huijts/strava-mcp) (paquet npm `@r-huijts/strava-mcp-server`, épinglé à la version 1.2.1 par `STRAVA_MCP_PKG` dans `install.sh`, stdio, **Node.js >= 18**, application API Strava locale de l'athlète — client id/secret ; jetons dans `~/.config/strava-mcp/config.json`). Lecture seule **pour ce projet** : `connect-strava`, `disconnect-strava` et `star-segment` (écriture Strava) ne sont jamais appelés en headless (`daily-sync.sh` les interdit) et demandent une approbation dans le chat. Le **connecteur officiel Strava** (`https://mcp.strava.com/mcp`, HTTP + OAuth, lecture seule, abonnement payant) est une alternative **manuelle** pour Claude Code interactif (`claude mcp add --transport http strava-mcp https://mcp.strava.com/mcp`, article d'aide Strava 46190267796237) : ses noms d'outils et formes de réponse n'ont **pas pu être vérifiés** (OAuth requis) — la table de correspondance (`skills/data-source-mapping/SKILL.md`) ne s'y applique pas, l'agent lit la liste d'outils exposée par la session et n'invente rien ; il ne sert pas au `garmin-daily-sync` headless.
- **`coros`** — montre COROS, par le **MCP officiel de COROS**, sans compte tiers (`docs/coros.md`). Installé par `./install.sh --coros` : relais local `scripts/arc_coros_mcp.py`, une seule connexion de l'athlète (`scripts/arc_coros_auth.py login`) pour toutes les IA, lecture seule en headless. Le coach pousse les séances planifiées (course, trail, vélo) au calendrier COROS par le skill `coros-workout-scheduling` (outils relevés le 22 octobre 2026 sur une session authentifiée) — interactif seulement, « oui » explicite, jamais en headless ; aucun outil de suppression ni de déplacement ; un seul chemin vers la montre (jamais une séance qu'un autre service envoie déjà à COROS). **Renforcement** : le MCP ne sait pas le créer, mais planifie (`scheduleWorkout`) les séances types que l'athlète a créées une fois dans l'app COROS — exercices invisibles pour l'agent, copie figée à la date. **FIT** : `download_fit.py <c+LabelId> --json --source coros` (skill `fit-download`), identifiant `coros_activity_id` (`"c"` + `LabelId` de `querySportRecords`, avec `start_time`) — mêmes KPI qu'avec Garmin. **PRIMAIRE si `[data].source = "coros"`** (`./install.sh --source coros`, #168) : le relais `coros` remplace le serveur `garmin` — `coach`/`medical`/`garmin-daily-sync` utilisent ses outils, table de correspondance de `skills/data-source-mapping/SKILL.md` ; lecteur de FIT installé à part (`~/.local/share/ai-running-coach/fit-reader`, `fitparse`). Sinon (`--coros` avec une autre source) : activités, santé et récupération se lisent dans la session, sans persistance automatique.
- **Open Wearables** (#216, opt-in) : **pas une source d'entraînement** ni un chemin pour Garmin ; **source santé du bilan matinal** quand `[health].source = "openwearables"` (installé par `./install.sh --health-source openwearables`) — lue par `scripts/arc_openwearables.py` (client REST stdlib, **lecture seule**, pas le MCP d'OW) ; une seule source santé par jour (les outils santé Garmin ou le wellness intervals.icu ne sont pas appelés pour HRV/FC de repos/sommeil), les séances restant lues via `[data].source`. Voir « Bilan matinal » et `docs/open-wearables.md`.
- **Absents localement** : `myfitnesspal` (utiliser les rapports manuels), `nexus-mcp` (RAG — déploiement Docker VPS uniquement ; localement utiliser `resources/` + historique MD)

### Correspondance des outils — intervals.icu, Strava, COROS (#68, #164, #168)

Les tables de correspondance Garmin ↔ intervals.icu, Garmin ↔ Strava et Garmin ↔ COROS, ce qui
n'a pas de portage avec chacune de ces sources, les flux Strava et le téléchargement FIT
intervals.icu sont dans **`skills/data-source-mapping/SKILL.md`**. **Obligatoire :** quand
`[data].source` vaut `intervals`, `strava` ou `coros`, ou avant d'appeler un outil `icu_*`, Strava
ou `coros` (relais COROS avec une autre source), lire ce fichier en entier AVANT le premier appel
d'outil de données, quel que soit l'exécuteur (skill natif ou lecture du fichier). Avec
`[data].source = "garmin"` (défaut) et sans relais COROS, il n'y a rien à lire. Sans l'avoir lu :
aucun push de séance avec ces sources, et un champ sans équivalent est omis et dit, jamais
deviné ni simulé.

**v5.6.0 :** `icu_update_athlete_notes` (écriture : remplace les notes libres du profil athlète intervals.icu) est un outil d'ÉCRITURE que le projet n'appelle **jamais** — refusé au run headless, quel que soit l'exécuteur (`scripts/lib/sync_tools.sh` : refus nommés Claude/Copilot/Cursor/Gemini ; permissions OpenCode `<serveur>_<outil>` générées par `daily-sync.sh`) et soumis à approbation dans le chat (`icu_update_*`, `scripts/arc_chat_policy.py`). Le seuil d'allure de course stocké en m/s (correctif amont) concerne `icu_get_sport_settings`/`icu_update_sport_settings`, que le projet n'utilise pas ; `icu_get_activity_streams` ajoute `stream_notes` (côté droit de `left_right_balance`), champ ignoré.

**Splits par km depuis le FIT — règle par défaut, toutes sources.** Les `splits` d'une séance
viennent du FIT, pour que tous soient calculés de la même façon quelle que soit la source
(Garmin compris ; intervals.icu et Strava n'en ont pas ; des tours qui repartent de zéro à
chaque étape d'une séance structurée ne sont jamais recopiés dans `splits`) :
`python3 scripts/arc_index.py splits <id>` les calcule depuis les échantillons FIT ingérés (`scripts/arc_splits.py`) : `splits_cols` +
`splits` prêts à recopier tels quels dans le bloc `arc` (km entiers en temps **écoulé**,
bornes interpolées, dernier split partiel avec sa `distance_m` à partir de 100 m, D+/D−
sur l'altitude lissée, colonnes sans mesure retirées). Sortie 1 + `reason` si aucun FIT
n'est ingéré. Seul repli sans FIT : les splits de `get_activity_splits` avec Garmin (une fois
le FIT arrivé, ils sont remplacés) ; avec les autres sources, la clé reste absente, jamais
devinée. Les splits déjà écrits ne sont pas recalculés d'office.

**Matériel (#133).** Avec `[data].source = "garmin"`, `get_gear` / `get_activity_gear`
(lecture) et `add_gear_to_activity` (écriture) sont dans la liste blanche `GARMIN_TOOL_WHITELIST`.
Le coach associe **une fois** (proposition, jamais devinée) chaque matériel Garmin à une puce
`### Chaussures` du profil par un segment `garmin: <uuid>`, puis attribue `gear_id` avec la
priorité **déclaration de l'athlète (chat) > matériel attaché par Garmin > `(par défaut)`** (règle
exécutée par `python3 scripts/arc_index.py gear-attribution` ; un désaccord Garmin/athlète est
signalé une fois ; provenance dans `gear_source` ; un matériel Garmin non associé, ambigu ou
`(ignorée)` laisse `gear_id` absent avec `gear_source: "garmin_unmapped"` : la séance n'est alors
jamais créditée à la paire par défaut). Un seul `get_activity_gear` par activité NOUVELLE. Aucune
écriture Garmin sans confirmation dans la conversation, jamais en headless. **Retraite Garmin** :
chaque réponse de `get_gear` est écrite telle quelle dans `.arc/get_gear_response.json` puis lue par
`python3 scripts/arc_index.py garmin-gear-status --garmin-gear-json .arc/get_gear_response.json`
(instantané dérivé `.arc/garmin_gear.json`, au plus une fois par jour en headless) ; une paire liée retirée
dans Garmin est retirée **immédiatement** (`retired_source: "garmin"` : ni alerte de seuil, ni rappel
d'inspection) et le coach propose une fois, en interactif seulement, d'écrire `(retirée AAAA-MM-JJ)` sur la
puce (`--mark-retired <gear_id>`, refusé sous `ARC_HEADLESS`) ; retirée au profil mais active dans Garmin :
signalé, jamais annulé. **Avec
`[data].source = "intervals"`** : le serveur épinglé expose `icu_get_gear_list` (inventaire, à titre
de référence — jamais utilisé pour attribuer) mais **aucun matériel par activité**
(`src/intervals_icu_mcp/tools/activities.py`/`activity_analysis.py` n'ont pas de champ gear,
vérifié au commit épinglé) : `gear_id` reste chat/`(par défaut)`, dit explicitement, jamais inventé. **Avec
`[data].source = "strava"`** (#164) : aucun inventaire en 1.2.1, et le NOM du matériel dans
`get-activity-details` n'identifie aucune paire de façon attribuable — même règle : chat/`(par défaut)`.
**Avec `[data].source = "coros"`** (#168) : le MCP COROS n'expose aucun matériel — même règle.

**Poids (#222).** Avec `[data].source = "garmin"`, `get_daily_weigh_ins` et `get_weigh_ins`
(lecture seule) sont dans `GARMIN_TOOL_WHITELIST` : pendant le bilan matinal et `garmin-daily-sync`,
la pesée du jour est lue et la décision prise par `python3 scripts/arc_weight_sync.py plan` (pesée
la plus ancienne du jour ; un jour sans pesée n'a PAS de `weight_kg`, jamais la valeur de la veille
— `resolve_weight_kg_as_of` reprend déjà la dernière connue ; une valeur déclarée par l'athlète le
même jour prime, `--declared-kg`). Provenance dans `weight_origin` (`garmin` | `chat`, absente =
déclarée) ; un écart > 1 kg est signalé une seule fois (pesée écartée gardée dans
`weight_garmin_kg`). Rappel de pesée hebdomadaire du profil : sauté si Garmin a déjà le poids du
jour. Rattrapage : un seul `get_weigh_ins(start, end)` + `--existing-only`. **Jamais exposés** :
`add_weigh_in`, `add_weigh_in_with_timestamps`, `delete_weigh_ins`, `add_body_composition` (retirés
aussi par `daily-sync.sh`). `get_body_composition` : hors périmètre. `weight_pre_kg`/`weight_post_kg`
restent déclaratifs. Avec `intervals`, `strava` ou `coros` : rien n'est lu, le poids reste déclaré.

## Connexion de l'IA (#265)

`scripts/arc_llm.py` (stdlib, Python 3.9) : catalogue des fournisseurs (`providers [--json]`) et
`connect openrouter [--headless] [--json]` (OAuth PKCE, clé écrite dans `llm.env` en mode 600, jamais
affichée). `./install.sh --llm openrouter --connect` le lance en interactif seulement (jamais en
`--dry-run`, jamais sans terminal, jamais mémorisé pour `/update-coach`). Les agents ne l'appellent
pas et la sync headless n'ouvre jamais de navigateur. `arc_llm.py sync anthropic|openrouter|openrouter-free|openai|claude-subscription`
(`scripts/arc_llm_sync.py`) change la **synchronisation seule** (`[sync]` : runner, model, base_url,
api_key_env), sans toucher au chat ni réinstaller ; refus si la clé manque dans `llm.env` ; commande de
l'athlète, jamais lancée par un agent. Arbre de décision : `docs/choisir-son-ia.md`.

**Abonnements ChatGPT Plus/Pro et GitHub Copilot (#266).** `./install.sh --llm chatgpt|copilot` :
backend/runner `opencode` sans clé (`api_key_env` vide), et **`[chat].opencode_data_dir` +
`[sync].opencode_data_dir`** = magasin d'authentification OpenCode dédié au coach (mode 700, défaut
`~/.local/share/ai-running-coach/opencode`) utilisé comme `XDG_DATA_HOME` par le chat et la sync, pour les
modèles `openai/…` / `github-copilot/…` sans clé API seulement (clé absente = comportement historique).
`arc_llm.py login chatgpt|copilot` (interactif, refusé sous `ARC_HEADLESS`), `auth-status`, `with-lock` ;
verrou `<magasin>/.arc-auth.lock` entre un tour de chat et une exécution de la sync (ChatGPT réécrit
`auth.json` sans verrou). Coût rapporté **ignoré** (jamais compté en euros ; « inclus dans votre forfait »).
Jeton absent/expiré = message actionnable (chat) ou notification (sync), jamais une connexion automatique.
Forfaits : ChatGPT Plus/Pro (Free refusé : `usage_not_included`), Copilot Pro/Pro+/Business/Enterprise.
La **sync** ne passe sur l'abonnement que sur une installation neuve ou avec `--sync-subscription` (`--no-sync-subscription` ne la touche jamais) ; `ARC_SYNC_USE_CHAT_PROVIDER=1` fait utiliser l'abonnement du chat à UNE exécution manuelle de `daily-sync.sh` (jamais posée par cron/launchd/watch).
## Telegram (#174, opt-in)

`scripts/arc_telegram.py` (service `scripts/coach-telegram.sh`, `./install.sh --telegram`) est un
canal de l'**athlète**, pas un outil des agents. Niveau 1, **sans modèle ni clé d'API** : le résumé
du daily-sync part avec des boutons (séance faite / pas faite / décalée, RPE, douleur) et les appuis
écrivent dans les blocs `arc` (`rpe` de l'activité, `pain` du fichier santé, `status` de la séance
planifiée) par la logique de `scripts/arc_log.py`, puis réindexent ; idempotent ; une douleur au
seuil `[injury_risk].pain_consult_threshold` recommande une consultation. Niveau 2 (`chat_bridge`) :
le texte libre est relayé au service `arc_chat` (même politique, approbations, plafond de dépense) —
aucun second moteur de chat. **Jamais d'écriture Garmin depuis ce canal** sans l'approbation
explicite du chat, et jamais en headless. Liste blanche d'identifiants de chat obligatoire ; ne
jamais afficher ni écrire le jeton du bot.

## Règles de fraîcheur des données

- Avant d'invoquer les outils Garmin, vérifier si le fichier MD du jour existe déjà — ne récupérer que si la date a changé ou si le fichier manque.
- Après CHAQUE récupération de données, persister immédiatement le fichier MD correspondant (ne jamais sauter, ne jamais dumper le JSON brut dans le chat).

## Projection de charge (#172)

`python3 scripts/arc_index.py load-forecast [--until DATE] [--compare FICHIER] [--text]`
(`/api/load-forecast`, prolongement en pointillés de la courbe « Forme & charge ») propage condition,
fatigue et forme jour par jour de l'état réel d'aujourd'hui jusqu'à la date de `active_objective.md`,
à partir de la charge **estimée** des séances planifiées (même estimateur que le garde-fou R1, aucun
second modèle, recalé sur le rapport réel/estimé des séances passées de l'athlète quand il est mesurable) :
forme prévue le jour J (état en entrant dans la journée), semaine de pic de fatigue, ACWR projeté. C'est une **estimation
à partir du planifié, jamais une mesure**. Un jour sans séance = charge nulle (les semaines non planifiées
sont comptées et dites) ; états honnêtes `no_objective` / `no_plan` / `insufficient_history` (même
plancher que R1, 84 j) / `target_past`, jamais un chiffre inventé. `--compare` oppose le plan actuel à une
variante (semaines de même lundi remplacées) pour justifier un affûtage. Lecture seule ; intégrée à `/race`
et au coach ; ne modifie pas le score Trail Shape ; ne lit aucune donnée de santé.

## Skills

Index court : le détail de chaque entrée (options, garde-fous, sorties) est dans
**`skills/skills-reference/SKILL.md`**, à lire avant d'utiliser une entrée dont on ne connaît pas le
détail ; chaque skill a aussi son `skills/<nom>/SKILL.md`. Règles communes : rien n'est écrit chez
Garmin, COROS ou intervals.icu sans « oui » explicite dans la conversation, et jamais en headless ;
une estimation du projet est dite comme telle, jamais présentée comme une mesure.

- `coach-setup` — premier démarrage (`/coach-setup`, `scripts/coach_setup.py`) ; ne remplace jamais une réponse existante.
- `garmin-workout-scheduling` — push des séances planifiées au calendrier Garmin.
- `coros-workout-scheduling` — push des séances au calendrier COROS (`arc_coros_workout.py`) ; interactif, « oui » explicite.
- `intervals-icu-best-practices` — push d'événements intervals.icu ; primaire si `[data].source = "intervals"`.
- `garmin-sync-efficiency` — discipline de récupération pour éviter l'explosion du contexte.
- `data-source-mapping` — tables de correspondance intervals.icu / Strava / COROS (voir « Backends MCP »).
- `workspace-data-contract` — schéma du bloc ```` ```arc ```` ; charger avant d'écrire un fichier du workspace.
- `arc-backfill` — met au contrat les anciens fichiers (`arc_index.py backfill-plan`).
- Bibliothèque de renforcement (`scripts/arc_strength.py`, #191) — `python3 scripts/arc_index.py strength` ; prévention ciblée (#192) : `config/strength/prevention.json` + `scripts/arc_prevention.py`, `python3 scripts/arc_index.py prevention`.
- `coach-doctor` — diagnostic d'installation (`/coach-doctor`) ; connexion IA (#268) : `python3 scripts/arc_llm.py check`.
- `update-coach` — `/update-coach`, mise à jour du moteur ; interactif, « oui » explicite.
- `garmin-daily-sync` — orchestration headless (`/garmin-daily-sync`, `scripts/daily-sync.sh`) : aucune question, résumé ```` ```resume ````.
- `weather-forecast` — météo + créneau optimal ; utilisé à chaque validation hebdo/journalière.
- `session-parts-analyzer` — analyse par segment (strides, montées, intervalles).
- `fit-download` — FIT et flux par seconde hors MCP (`download_fit.py`), toutes sources.
- Rattrapage du matériel Garmin (`scripts/garmin_gear_backfill.py`, #145) — simulation d'abord, `--apply` après « oui », jamais en headless.
- `mywhoosh-route` — parcours MyWhoosh à la durée d'une séance home trainer.
- `vanoor-export` — export vers l'app Vanoor si `[vanoor].export = "on"`.
- `gpx-analysis` — analyse de parcours GPX (`skills/gpx-analysis/scripts/analyze_gpx.py`).
- `gear-inspection` — inspection photo des chaussures ; `arc_index.py gait-summary` pour la foulée mesurée.
- `course-comparison` — comparaison de séances sur un même lieu (`skills/course-comparison/scripts/compare_course.py`).
- `inspection` — `/inspection [paire]`, lance l'inspection photo d'une paire.
- `shoe-specs` — fiche de caractéristiques d'une paire ; rien d'écrit sans validation ligne par ligne.
- `shoes` — `/shoes [rôle]`, puis `shoe-selection`.
- `shoe-selection` — choix de la prochaine paire ; aucun achat, lien d'affiliation ni prix.
- Profil d'usage par paire (`python3 scripts/arc_index.py shoe-usage`, #300) — lecture seule.
- Besoins pour la prochaine paire (`python3 scripts/arc_index.py shoe-needs --role ROLE`, #301) — plages cibles, jamais une marque ni un modèle.
- `log` — saisie libre en une phrase (`/log`, `scripts/arc_log.py`) ; produit inconnu = on demande.
- Gabarits de périodisation (`config/plans/*.json`, #189) — `python3 scripts/arc_index.py plan-templates` ; squelette daté : `python3 scripts/arc_index.py plan-skeleton` (dry run par défaut, `--write` n'écrase jamais).
