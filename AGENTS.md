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
| `[language].documents` | Langue des MD persistés (`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`). Défaut `fr`. |
| `[language].responses` | Langue des réponses. Défaut `auto` = celle de la requête. |
| `[coaching].style` | Voix de l'agent → `config/coaching-styles.md`. |
| `[coaching].intensity` | Fermeté d'application du style. |
| `[coaching].verbosity` | Longueur des retours et rapports. |
| `[sport].primary` | Profil chargé depuis `config/sports/<valeur>.md` (`trail` \| `road`). |
| `[sport].disciplines` | Sports croisés réellement pratiqués — les seuls à programmer. |
| `[agents].enabled` | **Seuls agents joignables.** Ne jamais déléguer à un agent absent. |
| `[health].morning_check` | `full` \| `minimal` \| `off` — voir ci-dessous. |
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
**proposer**, jamais l'imposer, et jamais deux fois dans une session. Exception :
`/garmin-daily-sync` tourne sous cron et ne doit rien proposer du tout.

## Bilan matinal — `[health].morning_check`

| Valeur | Comportement attendu |
|---|---|
| `full` | Triptyque indivisible : HRV + FC de repos (`get_rhr_day`) + readiness, avant toute décision de séance. Défaut. |
| `minimal` | `get_training_readiness` seule, rapportée en une ligne. Pas de HRV, pas de FC de repos, pas d'annulation sur les seules données de santé. |
| `off` | Aucune donnée de santé récupérée, aucun filtrage. Planification sur la charge, l'historique `activities/` et le ressenti déclaré. |

Ne jamais réactiver silencieusement un niveau plus strict que celui configuré.

## Carte des dossiers

| Dossier | Contenu | Convention |
|---|---|---|
| `activities/` | Journaux d'entraînement | `YYYY-MM-DD_type.md` (running, trail, strength, indoor_cycling, home_trainer, hiking, elliptical, rest) |
| `medical/` | Sommeil, HRV, récupération, blessures, météo | `YYYY-MM-DD_health.md`, `YYYY-MM-DD_meteo.md` |
| `nutrition/` | Journaux nutrition & plans de ravitaillement | `YYYY-MM-DD_nutrition.md` |
| `planning/` | Plans d'entraînement, objectifs, stratégies de course, **décisions tracées** | `active_objective.md` est la **source de vérité** de l'objectif courant ; `Runner_Profile.md` est le profil de l'athlète. Les deux sont installés depuis `templates/` par `/coach-setup`. Une décision (garde-fou, bilan matinal, blessure…) = un fichier `YYYY-MM-DD_decision_<slug>.md`. |
| `rapports/` | Rapports de synthèse périodiques (propriété du **coach**) | `YYYY-MM-DD_rapport.md` |
| `resources/` | Base de connaissances (langue des documents) : running, nutrition, santé, récupération | Matériel de référence, citer lors des conseils. **Catalogues produits** (optionnels) : `resources/nutrition/catalogue-produits-*.md` = valeurs nutritionnelles par produit de l'athlète |

> **Note** : ces dossiers sont créés par l'utilisateur dans son espace de travail
> (voir `install.sh`). Ils sont exclus du dépôt public (`.gitignore`).

### Contrat de données

Tout fichier écrit par un agent dans `activities/`, `medical/`, `nutrition/`,
`planning/` (semaines, évaluations, plans de course, décisions) ou `rapports/` s'ouvre, sous
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
| `coach` | Plans d'entraînement, analyse des activités Garmin (**incl. HRR `recovery_hr_bpm` dans chaque retour de séance**), ajustements de séances, **push des séances au calendrier Garmin** (`schedule_workouts`, Garmin d'abord), rapports hebdomadaires. **Bilan matinal avant toute décision de séance, au niveau fixé par `[health].morning_check` : à `full` (défaut), HRV + FC de repos (`get_rhr_day`) + readiness — les trois, jamais deux.** **Inclut toujours la météo + le créneau optimal (matin tôt / midi / soir) dans chaque validation hebdomadaire/journalière (charger le skill `weather-forecast`, résoudre le lieu via la règle de précédence stricte).** |
| `medical` | Analyse sommeil/HRV/récupération (**incl. HRR lors de l'évaluation de l'impact d'une séance**, et **FC de repos dans le bilan matinal**), protocoles blessures, gatekeeper de disponibilité, contraintes de coordination pour coach/nutritionniste |
| `nutritionist` | Macros, poids de course, plans de ravitaillement. **Pas de serveur MyFitnessPal** — les apports viennent des rapports manuels de l'utilisateur ; croiser avec les calories brûlées Garmin |
| `course-strategist` | Analyse GPX/URL de course → plan de course (allures ×3 scénarios, nutrition, météo, équipement), enrichissement points d'eau OSM, upload de parcours Garmin via l'outil `upload_course` |

Lors d'une délégation, écrire le prompt de tâche en anglais mais ajouter
explicitement **« Respond in <langue des documents> »** (résolue via
`config/workspace.toml` → `[language].documents`, défaut FRENCH) si la sortie
est destinée à l'utilisateur.

## Backends MCP

- **`garmin`** — activités, sommeil, HRV, readiness, **calendrier des séances planifiées (destination PRIMAIRE)**, upload parcours/séances. **Mode direct par défaut** : le serveur MCP `garmin` expose `garmin-mcp` avec une liste blanche d'outils (`GARMIN_ENABLED_TOOLS`). **Mode passerelle (optionnel, power user)** : `leanproxy_invoke_tool(server="garmin", tool="...")` via leanproxy-mcp (économie de tokens ~98 %, chargement paresseux des schémas).
- **`Intervals.icu`** — événements, wellness, séances planifiées (**SECONDAIRE** : uniquement si l'utilisateur le demande explicitement)
- **Absents localement** : `myfitnesspal` (utiliser les rapports manuels), `nexus-mcp` (RAG — déploiement Docker VPS uniquement ; localement utiliser `resources/` + historique MD)

## Règles de fraîcheur des données

- Avant d'invoquer les outils Garmin, vérifier si le fichier MD du jour existe déjà — ne récupérer que si la date a changé ou si le fichier manque.
- Après CHAQUE récupération de données, persister immédiatement le fichier MD correspondant (ne jamais sauter, ne jamais dumper le JSON brut dans le chat).

## Skills

- `coach-setup` — **premier démarrage** (`/coach-setup`) : entretien mené par le modèle,
  écriture pilotée par `scripts/coach_setup.py` (qui ne remplace jamais une réponse
  existante), installation de `planning/Runner_Profile.md` et `planning/active_objective.md`
  depuis `templates/`. Relancer la commande est sans effet.
- `garmin-workout-scheduling` — push des séances planifiées au calendrier Garmin (schéma DTO exact, détail force, idempotence, vérification après push)
- `intervals-icu-best-practices` — pièges de création/mise à jour d'événements (`workout_doc`, vérification `start_date`) ; secondaire, Garmin d'abord
- `garmin-sync-efficiency` — discipline de récupération pour éviter l'explosion du contexte
- `workspace-data-contract` — **schéma du bloc ```` ```arc ````** par type de fichier (activité, santé, météo, semaine, nutrition, rapport, évaluation de parcours, plan de course), unités SI, validation par `scripts/arc_index.py --validate`. Charger avant d'écrire un fichier du workspace.
- `arc-backfill` — met au contrat les fichiers écrits avant lui, par lots, à partir de la liste produite par `python3 scripts/arc_index.py backfill-plan`.
- `coach-doctor` — **diagnostic d'installation en une commande** (`/coach-doctor`, `python3 scripts/coach_doctor.py`) : âge/échéance des tokens Garmin, joignabilité du MCP `garmin`, validité TOML de la config, complétude du profil athlète, fraîcheur de l'index `.arc/coach.db`, fichiers hors contrat, planification du daily-sync, configuration ntfy. Ne lit ni n'écrit rien de sensible ; à charger dès qu'un symptôme d'installation apparaît, avant de deviner la cause.
- `garmin-daily-sync` — **prompt d'orchestration headless** (`/garmin-daily-sync`) lancé par le cron de la machine coach (`scripts/daily-sync.sh`), depuis le téléphone (Remote Control) ou l'IDE : délègue au `coach` + `garmin-sync-efficiency`, ne pose aucune question, ne récupère que les dates manquantes, termine par un bloc ```` ```resume ```` (≤ 5 lignes) envoyé en notification push (ntfy). Voir `docs/mobile.md`.
- `weather-forecast` — récupération + persistance des prévisions météo (wttr.in via webfetch), résolution du lieu (override fichier semaine → `active_objective.md` défaut → profil défaut → demander), seuils de catégorie (🟢/🟡/🟠/🔴), créneau optimal par séance outdoor. Utilisé par l'agent `coach` à chaque validation hebdo/journalière.
- `session-parts-analyzer` — analyse au niveau segment des drills (strides, montées, intervalles, sprints) depuis FIT/MCP. L'analyse détaillée délègue le téléchargement FIT à `fit-download`.
- `fit-download` — **téléchargement des fichiers FIT Garmin + records GPS en bypassant le MCP** (qui timeoute sur les FIT) : `scripts/download_fit.py` utilisant `garminconnect` + tokens locaux `~/.garminconnect`. Charger dès qu'une séance doit être analysée à précision sub-km (profil de parcours, montées, dérive FC×élévation, analyse stride/sprint/intervalle, comparaison de parcours). Toujours persister l'analyse dans le MD de l'activité dans la langue des documents (`config/workspace.toml`), ne jamais dumper le JSON brut.
- `gpx-analysis` — **analyse générique de parcours GPX** (fichiers Strava/Garmin/course) via `scripts/analyze_gpx.py` (stdlib) : distance réelle, D+/D- (lissage anti-bruit), profil par km, montées significatives, boucle vs point-to-point, verdict de compatibilité vs une cible (distance/D+). Charger dès que l'utilisateur fournit un GPX et veut l'analyser ou l'évaluer contre une séance planifiée. Persister la fiche d'évaluation dans `planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md` (langue des documents). Utilisé par `course-strategist` pour l'entrée GPX.
- `course-comparison` — **analyse comparative de séances sur le même parcours/lieu** via `scripts/compare_course.py` : découverte de toutes les activités d'un lieu (fichiers MD Garmin), alignement des boucles/segments, comparaison des montées, tableau global (date, distance, D+, durée, allure, FC moy/max, premier tour, montées) et dump JSON. Charger quand l'utilisateur demande de comparer des séances d'un même lieu ou d'évaluer la progression sur un parcours connu. Prérequis : chaque MD d'activité porte son bloc ```` ```arc ```` avec `location` et `splits` (fichiers anciens : bloc YAML `## Données brutes Garmin (référence)` + `## Analyse par splits (km)`). Persister les rapports dans `rapports/YYYY-MM-DD_comparaison_<lieu>.md`.