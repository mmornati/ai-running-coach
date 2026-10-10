# Skills

<div class="arc-page-banner" markdown>
![](assets/ridge.jpg)
</div>

`ai-running-coach` fournit **20 skills** que les agents chargent à la demande pour des tâches spécifiques.

## Vue d'ensemble

<div class="arc-skills">

<div class="arc-skill"><span class="arc-skill__name"><a href="skills/today.md">Aujourd'hui (/today)</a></span><span class="arc-skill__desc">Statut du jour : séance, bilan matinal au niveau configuré, créneau météo</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/why.md">Pourquoi (/why)</a></span><span class="arc-skill__desc">Explique la dernière décision (ou une décision nommée) du journal des décisions</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/week.md">Semaine (/week)</a></span><span class="arc-skill__desc">Statut compact de la semaine en cours : réalisé/prévu, garde-fous</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/race.md">Course (/race)</a></span><span class="arc-skill__desc">Compte à rebours de l'objectif, score Trail Shape, forme prévue le jour J, plan de course</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/gpx-analysis.md">Analyse GPX</a></span><span class="arc-skill__desc">Analyse générique d'un fichier GPX et production d'un rapport Markdown structuré</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/course-comparison.md">Comparaison de parcours</a></span><span class="arc-skill__desc">Analyse comparative de séances sur un même parcours/lieu</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/garmin-workout-scheduling.md">Planification Garmin</a></span><span class="arc-skill__desc">Push de séances planifiées dans le calendrier Garmin Connect</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/garmin-sync-efficiency.md">Synchronisation Garmin</a></span><span class="arc-skill__desc">Récupération efficace des données Garmin sans saturer le contexte</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/weather-forecast.md">Météo</a></span><span class="arc-skill__desc">Prévisions météo pour le lieu d'entraînement</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/session-parts-analyzer.md">Analyse de séances</a></span><span class="arc-skill__desc">Analyse de portions spécifiques d'une séance Garmin</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/intervals-icu-best-practices.md">Intervals.icu</a></span><span class="arc-skill__desc">Création et mise à jour d'événements Intervals.icu</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/fit-download.md">Téléchargement FIT</a></span><span class="arc-skill__desc">Téléchargement de fichiers FIT Garmin en bypassant le canal MCP</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/garmin-daily-sync.md">Sync quotidienne</a></span><span class="arc-skill__desc">Synchronisation Garmin sans surveillance (cron, téléphone) avec résumé pour notification</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/coach-setup.md">Premier démarrage</a></span><span class="arc-skill__desc">Entretien de configuration : staff d'agents, discipline, style de coaching, bilan santé, profil d'athlète</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/workspace-data-contract.md">Contrat de données</a></span><span class="arc-skill__desc">Schéma JSON du bloc <code>arc</code> pour la persistance structurée des données</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/arc-backfill.md">Backfill du contrat</a></span><span class="arc-skill__desc">Migration des fichiers Markdown existants pour les conformer au contrat de données</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/coach-doctor.md">Diagnostic d'installation</a></span><span class="arc-skill__desc">Vérification en une commande des tokens Garmin, du MCP, de la configuration et du daily-sync</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/gear-inspection.md">Inspection des chaussures</a></span><span class="arc-skill__desc">Photos des semelles : état 🟢🟡🟠🔴, comparaison avec l'inspection précédente, indices de foulée (jamais un diagnostic)</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/inspection.md">Inspection d'une paire (/inspection)</a></span><span class="arc-skill__desc">Désigner la paire, protocole photo, dépôt des photos dans gear/photos/, puis lecture par gear-inspection</span></div>
<div class="arc-skill"><span class="arc-skill__name"><a href="skills/log.md">Saisie libre (/log)</a></span><span class="arc-skill__desc">Ravitaillement, douleur et RPE en une phrase, convertis en blocs arc sans jamais inventer une valeur nutritionnelle</span></div>

</div>

## Comment les skills sont utilisés

Les agents chargent les skills **à la demande** via l'outil `skill` de leur IDE. Par exemple :

- L'agent **coach** charge `weather-forecast` avant chaque validation hebdomadaire
- L'agent **coach** charge `garmin-workout-scheduling` avant de pousser des séances dans Garmin
- L'agent **course-strategist** charge `gpx-analysis` pour analyser un parcours

Six skills sont aussi des **commandes courtes**, invocables directement par
leur nom (`/today`, `/why`, `/week`, `/race`, `/log`, `/inspection`) plutôt que chargées par
un agent : format de sortie prévisible, pensées pour un usage rapide depuis
le téléphone. Les quatre premières délèguent en lecture seule à `coach`
(jamais d'écriture) ; `/log` écrit dans `activities/`/`medical/` via `coach`,
`nutritionist` ou `medical` selon le staff installé ; `/inspection` désigne la paire
et reçoit les photos, puis laisse `gear-inspection` écrire dans `gear/`.

## Structure d'un skill

```
skills/<nom-du-skill>/
├── SKILL.md              # Instructions du skill
├── scripts/              # Scripts Python (optionnel)
└── examples/             # Exemples de sortie (optionnel)
```

## Scripts Python

Certains skills incluent des scripts Python, dans leur propre dossier :

| Script | Skill | Dépendances |
|---|---|---|
| `analyze_gpx.py` | gpx-analysis | stdlib uniquement |
| `compare_course.py` | course-comparison | stdlib uniquement |
| `analyze_session_parts.py` | session-parts-analyzer | stdlib uniquement |
| `download_fit.py` | fit-download | `garminconnect` + `fitparse` (environnement garmin-mcp) ; Intervals.icu : `fitparse` (environnement intervals-icu-mcp) |
| `coach_setup.py` | coach-setup | stdlib uniquement |
| `coach_doctor.py` | coach-doctor | stdlib uniquement |

D'autres vivent directement dans `scripts/` (le moteur), appelés par les
agents ou par les commandes courtes plutôt que par un skill dédié :

| Script | Appelé par | Rôle |
|---|---|---|
| `arc_index.py` | tous les agents, `/today` `/why` `/week` `/race`, le tableau de bord | Index SQLite dérivé + toutes les commandes de lecture (voir ci-dessous) |
| `arc_guardrails.py` | `coach`, `garmin-workout-scheduling`, `/week` | Garde-fous déterministes (`check`) et drapeau composite de risque de blessure (`injury-risk`) — voir [Les garde-fous](guardrails.md) |
| `arc_log.py` | skill `log` (`/log`) | Arithmétique, correspondance catalogue et fusion idempotente pour la saisie libre |
| `arc_race_pacing.py` | `course-strategist` | Allures de course par segment depuis le modèle personnel pente → allure (#59) |
| `arc_race_debrief.py` | `coach`, `course-strategist` | Débrief post-course plan vs réalisé, par segment (#61) |
| `arc_workout_targets.py` | `coach` | Cibles personnelles d'une séance structurée — zones FC, allure GAP, D+ de côte (#60), plage en % de la vitesse critique quand l'ajustement est valide (#169) |
| `arc_strength.py` | `coach`, `arc_index.py strength` | Bibliothèque de renforcement/mobilité et programmes par phase ou usage (#191) : validation, repli matériel, charge utile Garmin vérifiée ou texte intervals.icu — voir [Renforcement et mobilité](strength.md) |
| `arc_cs.py` | `arc_index.py pace-curve`, `arc_workout_targets.py` | Courbe allure-durée en GAP, vitesse critique et D′ (#169) — fonctions pures, voir [Vitesse critique](vitesse-critique.md) |
| `arc_plan_templates.py` | `coach` | Gabarits de périodisation (`config/plans/*.json`) : chargement, validation contre les garde-fous, résolution semaine par semaine (#189) — voir [Gabarits de périodisation](plans.md) |
| `arc_trail_shape.py` | `coach`, `/race` | Score Trail Shape, préparation à l'objectif actif (#63) |
| `arc_load_forecast.py` | `coach`, `/race` | Projection de condition/fatigue/forme jusqu'à la course, comparaison de plans (#172) |
| `garmin_gear_backfill.py` | `coach` (interactif, sur accord), à la main | Rattrape le matériel Garmin sur l'historique (#145) : simulation par défaut, `--apply` ; dépend de `garminconnect` (via l'environnement garmin-mcp), voir [Rattraper le matériel de l'historique](garmin-setup.md#rattraper-le-materiel-de-lhistorique) |

### Sous-commandes de `arc_index.py`

```bash
python3 scripts/arc_index.py <commande> [options]
```

| Commande | Rôle |
|---|---|
| `index` | (Re)construit l'index SQLite dérivé depuis le Markdown du workspace |
| `status` | État de l'index (fichiers indexés/hors contrat, couverture des échantillons FIT) |
| `backfill-plan` | Liste les fichiers hors contrat et les collisions de semaine à corriger |
| `hrv-baseline` | Baseline HRV personnelle (moyenne glissante 7 j de ln(HRV) vs référence 60 j ± 0,5 ET) |
| `sleep-debt` | Dette de sommeil sur 7 jours (#37) |
| `heat-acclimation` | Séances « chaudes » sur 14 jours vs `[health].heat_threshold_c` (#38) |
| `altitude-exposure` | Séances et temps au-dessus de 1 500 / 2 000 m sur 14 et 28 jours (`--days N`), d'après les échantillons FIT ; altitude manquante dite, jamais comptée comme nulle (#185) |
| `gear` | Kilométrage des chaussures et seuils d'alerte (#40) |
| `gear-attribution` | Priorité d'attribution du matériel d'une séance : déclaration de l'athlète > Garmin > défaut (`--garmin-gear`, `--chat-gear`, #133) |
| `equipment` | Matériel hors chaussures : usage (km, h, séances, jours), déclencheurs typés, kits (`--kit`), alerte unique (`--activities`, `--since`), contrôle du matériel d'un plan de course (`--race-plan`) (#134) |
| `performance-index` | Lecture des indices ITRA/UTMB déclarés au profil (#62) |
| `fueling` | Plafond de glucides/h réellement toléré (sorties longues running/trail, #41) |
| `samples` | Échantillons FIT bruts d'une activité (`--activity`) |
| `zones` | Temps en zone + polarisation 80/20 (#43) |
| `gap` | Allure ajustée à la pente (GAP, modèle de Minetti) |
| `decoupling` | Découplage Pa:HR / efficacité aérobie |
| `vam` | Vitesse ascensionnelle moyenne, par montée détectée et par fenêtre (#46) |
| `descent` | Efficacité en descente |
| `durability` | Fade d'endurance sur séance longue (> 90 min) |
| `energy` | Dépense énergétique modèle (RE3 + marche) vs Garmin, contrôle d'écart |
| `pace-curve` | Courbe allure-durée en GAP (42/90/365 j), vitesse critique et D′, tendance ; `--days N`, `--lt-speed-ms V` (contrôle avec le seuil lactique Garmin) (#169) |
| `climb-history` | Historique d'une montée reconnue d'une séance à l'autre (`--segment`, #49) |
| `decisions` | Journal des décisions tracées (filtrable par date, fenêtre, déclencheur, issue) |
| `slope-model` | Modèle personnel pente → allure (#58) |
| `trail-shape` | Score Trail Shape (#63) |
| `load-forecast` | Projection de charge jusqu'à la course : forme prévue le jour J, `--compare` (#172) |
| `plan-skeleton` | Squelette de bloc semaine par semaine (gabarit + date de course + volume tenu + disponibilité) : dry run JSON/`--text`, `--write` pour `planning/Semaine_<lundi>.md` sans écrasement, garde-fous par semaine, forme prévue le jour J (#190) ; mise en route qui fait monter le volume (`--lead-in ramp|flat`, `--lead-in-weeks K`) et contrôle face aux exigences de la course (`race_demand`, #204) |
| `plan-templates` | Gabarits de périodisation : liste, choix par distance (`--distance-km`), détail résolu (`--format`, `--weeks`) ; JSON par défaut, `--text` pour un tableau lisible (#189) |

`python3 scripts/arc_index.py --help` liste toutes les options associées à
chaque commande.
