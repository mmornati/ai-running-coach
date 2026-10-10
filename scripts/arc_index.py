#!/usr/bin/env python3
"""Index SQLite dérivé du workspace : la source de vérité reste le Markdown.

La base est jetable et reconstruisible à tout moment depuis les fichiers. Elle
sert au tableau de bord (`scripts/arc_serve.py`) et aux calculs de charge
(`scripts/arc_metrics.py`).

    arc_index.py                         # (ré)indexe le workspace, incrémental
    arc_index.py --rebuild               # repart de zéro
    arc_index.py --validate FICHIER…     # vérifie le bloc ```arc (code 1 si non conforme)
    arc_index.py backfill-plan           # écrit .arc/backfill.md : fichiers à réécrire au contrat
    arc_index.py status                  # état de l'index, en JSON
    arc_index.py hrv-baseline            # ligne de base HRV personnelle du jour, en JSON (#34)
    arc_index.py sleep-debt               # dette de sommeil 7 j du jour, en JSON (#37)
    arc_index.py heat-acclimation         # acclimatation à la chaleur, 14 j, en JSON (#38)
    arc_index.py power-hr [--days N] [--text]  # home trainer : puissance ↔ FC, W par zone FC, équipement vélo
    arc_index.py altitude-exposure [--days N]   # exposition à l'altitude (≥ 1 500 / 2 000 m), 14 et 28 j (#185)
    arc_index.py fueling                  # glucides/h et sudation, sorties longues, en JSON (#41)
    arc_index.py samples GARMIN_ID         # échantillons ingérés d'une séance, en JSON (#42)
    arc_index.py zones [--activity GARMIN_ID] [--weeks N]   # zones FC, temps en zone, polarisation (#43)
    arc_index.py gap --activity GARMIN_ID                   # allure ajustée à la pente, globale + par split (#44)
    arc_index.py decoupling [--activity GARMIN_ID] [--weeks N]   # découplage aérobie (Pa:HR), EF (#45)
    arc_index.py vam [--activity GARMIN_ID] [--weeks N]           # VAM sur les montées détectées (#46)
    arc_index.py descent [--activity GARMIN_ID] [--weeks N]        # efficacité en descente par classe de pente (#47)
    arc_index.py durability [--activity GARMIN_ID] [--weeks N]      # fade GAP/EF sur les sorties longues (#48)
    arc_index.py climb-history [--segment ID | --activity GARMIN_ID]  # identité de montée entre séances (#49)
    arc_index.py decisions [--date D | --days N] [--trigger T] [--outcome O] [--active]
                                                                        # journal des décisions, en JSON (#54)
    arc_index.py decision-effects [--trigger T] [--days N] [--text]
                                                                        # ce qui s'est passé après chaque décision, en JSON (#175)
    arc_index.py energy [--activity GARMIN_ID | --date D | --since D] [--limit N] [--assumptions]
                                                                        # dépense modèle vs Garmin, en JSON
    arc_index.py pace-curve [--days N] [--lt-speed-ms V]              # courbe allure-durée GAP, CS/D′ (#169)
    arc_index.py energy --calibration [--weeks N]                     # calibration personnelle (ratio
                                                                        # Garmin/modèle par panier route/trail)
    arc_index.py plan-templates [--format ID | --distance-km D [--sport S]] [--weeks N] [--text]
                                                                        # gabarits de périodisation (#189)
    arc_index.py strength [--phase P] [--use U] [--equipment LISTE] [--text | --garmin-json]
                                                                        # bibliothèque de renforcement (#191)
    arc_index.py prevention [--days N] [--acute ZONE,…] [--known ZONE,…] [--equipment LISTE] [--text]
                                                                        # prévention ciblée liée aux douleurs (#192)

`strength` (#191, épopée #173) choisit un programme de renforcement/mobilité de la bibliothèque livrée avec
le moteur (`config/strength/`, `arc_strength.py`) par phase du bloc et/ou par usage (descente, cheville,
hanches, pied), remplace les exercices selon le matériel disponible (`--equipment`, sinon la puce
« Équipement » du profil ; inconnu → question, jamais deviné) et rend la sélection en JSON, en `--text`
(description intervals.icu / chat) ou en `--garmin-json` (charge utile `create_strength_workout`, aucune
écriture). Sans `--phase` ni `--use` : le catalogue. Lecture seule, sans index. Approximations du projet.

`prevention` (#192, épopée #173) relie les douleurs DÉCLARÉES des `--days` derniers jours (14 par défaut,
`health.pain` des `medical/*_health.md`) à une routine douce de la bibliothèque, après des garde-fous
déterministes (score >= `[injury_risk].pain_consult_threshold`, douleur aiguë `--acute`, aggravation,
persistance > 7 jours, drapeau de risque de blessure → consultation, aucun exercice). Jamais un diagnostic ;
`[agents].enabled` décide qui tranche (`medical` s'il est activé, sinon le coach avec « ce n'est pas un avis
médical »). Lecture seule : rien n'est écrit ni poussé. Voir `arc_prevention.py`.

`hrv-baseline` n'a besoin d'aucun tableau de bord lancé (headless, `/garmin-daily-sync`
compris) : elle réindexe puis rend le point du jour de `arc_metrics.hrv_baseline_series`
sur `medical/*_health.md::hrv_overnight_ms`, ou `{"status": null, "morning_check": ...}`
si `[health].morning_check` n'est pas `"full"` (rien n'est calculé aux autres niveaux,
voir `arc_metrics.ASSUMPTIONS["hrv_baseline"]`). Les agents `medical`/`coach` l'appellent
quand `get_hrv_data` (Garmin) ne renvoie pas de `baseline`, au lieu d'inventer un statut
Garmin ou de rester silencieux sur la HRV.

`sleep-debt` a la même discipline headless : dette de sommeil 7 j (besoin du profil,
défaut 7 h 30, − sommeil réalisé, nuits manquantes jamais comptées 0 h) sur
`medical/*_health.md::sleep_total_s`, ou `{"sleep_debt_7d_s": null, "morning_check": ...}`
hors `"full"` (voir `arc_metrics.ASSUMPTIONS["sleep_debt"]`). Utilisée par `coach`/`medical`.

`heat-acclimation` joint les activités outdoor et les fichiers météo du même jour sur
les 14 derniers jours (`[health].heat_threshold_c`, défaut 25 °C) : nombre de séances
« chaudes » et durée cumulée, séances sans météo comptées à part
(`sessions_without_weather`, jamais froides par défaut). N'est PAS soumis à
`[health].morning_check` (voir `arc_metrics.ASSUMPTIONS["heat_acclimation"]`). Utilisée
par `coach` et `course-strategist` (course dont la météo prévue est chaude).

`fueling` agrège glucides/h et taux de sudation sur les sorties longues (> 90 min) des
12 dernières semaines glissantes : meilleur débit observé (+ plafond avec marge de
progression), médiane du taux de sudation, effectifs. N'est PAS soumis à
`[health].morning_check` (voir `arc_metrics.ASSUMPTIONS["fueling"]`). Utilisée par
`course-strategist` pour plafonner l'objectif glucides/h d'un plan de course.

`samples` rend, pour une séance donnée (identifiée par son `garmin_activity_id`, ou
son `intervals_activity_id` `i<chiffres>` pour une séance synchronisée depuis
Intervals.icu — #68 —, jamais l'id interne de la table `activity`), les échantillons FIT déjà ingérés
(sous-échantillonnés, triés par `t_s`) ou `{"samples": [], "reason": ...}` si la
séance n'a pas de FIT associé — jamais une erreur (voir `arc_samples.py` et
`ingest_samples` ci-dessous pour le format et l'ingestion elle-même).

`zones` (#43) rend les bornes de zones FC effectives (méthode par précédence, voir
`arc_metrics.hr_zone_resolution` — toujours une `reason` explicite quand aucune
zone n'est calculable, jamais un échec muet) et, selon les options :
`--activity ID` (entier Garmin ou `i<chiffres>` Intervals.icu, comme pour toutes les
sous-commandes par séance) le temps en zone d'une séance précise ; `--weeks N` (défaut 8)
la polarisation 80/20 hebdomadaire des N dernières semaines. Restreint aux sports de
la famille course à pied (`arc_metrics.sport_family` = « run » : course, trail,
randonnée, marche — pas le renforcement ni le vélo). Tables dérivées `hr_zone_time`
(5 zones affichées) et `hr_polarisation_time` (bornes Seiler DÉDIÉES par méthode,
jamais un regroupement des 5 zones) recalculées en entier à chaque passage de
`index_workspace` (voir `compute_metrics`) : un changement de profil (FC max/repos/
seuil) ou de `[athlete].hr_zones` est répercuté sans étape à part. Voir
`arc_metrics.ASSUMPTIONS["hr_zones"]`.

`gap` (#44) rend l'allure ajustée à la pente (« GAP », modèle de Kay 2012 tiré
de records de course — voir `arc_gap.py` et `docs/gap.md`) d'une séance : allure globale et par
split, `--activity GARMIN_ID` obligatoire (ou en argument positionnel).
`activity.gap_pace_s_km` et `activity_split.gap_pace_s_km` sont recalculées en
entier à chaque passage de `index_workspace` (même discipline que les tables
zones/polarisation ci-dessus), restreintes à la famille course à pied avec des
échantillons FIT ingérés — voir `arc_gap.ASSUMPTIONS`.

`decoupling` (#45) rend, sans `--activity`, la tendance du découplage aérobie
(Pa:HR) et du facteur d'efficacité (EF) sur les sorties longues (course à pied,
`duration_s` > `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) des `--weeks`
dernières semaines glissantes (défaut 12) ; avec `--activity GARMIN_ID`, le
détail d'une séance (`decoupling_pct`, `ef_whole`, `reason` explicite si non
calculable). `activity.decoupling_pct`/`ef_whole`/`decoupling_reason` sont
recalculées en entier à chaque passage de `index_workspace` (même discipline
que GAP/#44 et zones/#43), restreintes à la famille course à pied avec des
échantillons FIT ingérés — voir `arc_decoupling.ASSUMPTIONS`.

`vam` (#46) rend, avec `--activity GARMIN_ID`, le détail des montées détectées
d'une séance (bornes, gain, pente, VAM temps écoulé/temps de mouvement, classe
de pente, meilleure VAM 10/20 min) ; sans `--activity`, la tendance sur les
`--weeks` dernières semaines glissantes (défaut 12, AUCUN seuil de durée
minimale contrairement à `decoupling` — une montée peut être détectée sur une
sortie courte). La table `activity_climb` et les colonnes
`activity.best_vam_10min_m_h`/`best_vam_20min_m_h`/`best_climb_vam_elapsed_m_h`
sont recalculées en entier à chaque passage de `index_workspace` (même
discipline que GAP/#44 et découplage/#45), restreintes à la famille course à
pied (course, trail, randonnée, marche) avec des échantillons FIT ingérés —
voir `arc_climb.ASSUMPTIONS`. Seuils de détection configurables :
`[metrics].climb_min_gain_m`/`climb_min_grade_pct` (défauts 50 m / 5 %, voir
`config/workspace.toml`), résolus par `settings()` — critère d'acceptation de
#46 (« montée minimale configurable »).

`descent` (#47) rend, avec `--activity GARMIN_ID`, le détail d'efficacité en descente
d'une séance par classe de pente (vitesse/allure moyenne, allure GAP de référence de
la séance, indicateur d'efficacité — voir `arc_descent.ASSUMPTIONS["indicator"]`) ;
sans `--activity`, la tendance sur les `--weeks` dernières semaines glissantes
(défaut 12, comme `vam`). La table `activity_descent_class` est recalculée en entier
à chaque passage de `index_workspace` (même discipline que GAP/#44, découplage/#45
et VAM/#46), restreinte à la famille course à pied avec des échantillons FIT ingérés
— voir `arc_descent.ASSUMPTIONS`.

`durability` (#48) rend, avec `--activity GARMIN_ID`, le détail de durabilité d'une
séance (fade GAP et fade EF entre le premier et le dernier tiers de mouvement
post-échauffement, FC par tiers, `reason`/`reason_code` explicites — voir
`arc_durability.ASSUMPTIONS`) ; sans `--activity`, la tendance sur les `--weeks`
dernières semaines glissantes (défaut 12, comme `decoupling`). Restreint aux
sorties longues (`duration_s` > `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) de
la famille course à pied avec des échantillons FIT ingérés. Les colonnes
`activity.durability_gap_fade_pct`/`durability_ef_fade_pct`/
`durability_hr_first_third_bpm`/`durability_hr_middle_third_bpm`/
`durability_hr_last_third_bpm`/`durability_reason`/`durability_reason_code` sont
recalculées en entier à chaque passage de `index_workspace` (même discipline que
GAP/#44, découplage/#45, VAM/#46 et descente/#47).

`climb-history` (#49) rend, avec `--segment ID`, l'historique complet d'un
`climb_segment` (chaque occurrence : date, activité, temps, VAM, FC, dérive FC,
progression vs occurrence précédente/meilleure — voir `arc_climb_match.py`) ; avec
`--activity GARMIN_ID`, l'historique de CHAQUE segment gravi par cette activité ;
sans argument, la liste résumée de tous les segments connus (id, lieu, profil,
nombre d'occurrences, meilleur temps). `activity_climb.segment_id`/`hr_*`/`vs_*`
sont recalculés en entier à chaque passage de `index_workspace`, comme les autres
colonnes dérivées de l'épopée FIT — mais `climb_segment.id` n'est PAS stable d'une
réindexation à l'autre (voir la table dans `DDL`) : un id noté puis réutilisé après
un `--rebuild` peut ne plus exister (`reason_code: "unknown_segment"`, jamais une
erreur bruyante).

`decisions` (#54) rend le journal des décisions (`planning/AAAA-MM-JJ_decision_*.md`),
triées `date` puis `created_at_utc` décroissants (plusieurs décisions le même jour :
la plus récemment ÉCRITE en tête — comparaison en UTC, jamais un tri texte sur
`created_at`, voir #100). `--date AAAA-MM-JJ` cible une date précise, INCOMPATIBLE
avec `--days` (rejeté par la CLI, `ConfigError`, plutôt qu'une précédence
silencieuse) ; `--days N` (>= 1) une fenêtre glissante se terminant à `--today` ;
`--trigger`/`--outcome` filtrent en plus ; `--active` exclut les décisions
`superseded`/`rejected_by_athlete` (journal courant — voir SKILL.md « Remplacer une
décision »). Sans filtre de date, rend tout l'historique. Consommée par le tableau
de bord (#55, encart « Pourquoi aujourd'hui ? » + journal filtrable) et par
`/garmin-daily-sync` (#56, ligne « Pourquoi » du bloc `resume`).

`energy` rend la dépense énergétique modèle (RE3 course + marche de
Minetti, `scripts/arc_energy.py`) d'une ou plusieurs séances, EN REGARD de
`calories_kcal` Garmin (référence par défaut partout — ce calcul reste un CONTRÔLE
INDÉPENDANT, jamais un remplacement, voir `arc_energy.py`) : `garmin_kcal`,
`model_kcal`, `delta_pct`/`flag` (`arc_energy.delta_pct`/`delta_flag`,
`DELTA_ALERT_PCT` = 15 %, `delta_reason: "no_garmin_kcal"` si `calories_kcal` manque),
`bmr_kcal` (`calories_bmr_kcal`, quand connu) et le NET Garmin/modèle qui en découle
(`− bmr_kcal`, `net_reason: "no_bmr"` sans BMR connu), poids utilisé + sa source
(`weight_kg`/`weight_source`, voir `resolve_weight_kg_as_of`), décomposition
plat/montée/descente/marche/arrêt — kcal et pourcentages arrondis à 1 décimale
(`_round1`, même précision que les autres KPI dérivés stockés). `--activity GARMIN_ID`
cible une séance précise (ou l'argument positionnel) ; `--date AAAA-MM-JJ` toutes les
séances éligibles de ce jour ; `--since AAAA-MM-JJ` toutes les séances éligibles depuis
cette date (INCLUSE, ordre chronologique) ; sans filtre, les `--limit` (défaut 10)
dernières séances éligibles, rendues en ORDRE CHRONOLOGIQUE (la plus ancienne des
`--limit` en tête, la plus récente en dernier). `--limit` est INCOMPATIBLE avec
`--activity`/`--date`/`--since` (ne s'applique qu'à la liste par défaut), et l'argument
positionnel est INCOMPATIBLE avec `--activity` (un seul moyen de désigner la séance) —
rejetés avec un message explicite, jamais une précédence silencieuse. Une séance sans
ligne dans `activity_energy` (hors famille course à pied, sans aucun identifiant
externe — `reason_code: "no_activity_id"`, saisie manuelle — ou sans échantillons FIT
ingérés, `"no_samples"`) obtient une `reason`/`reason_code` explicite à la lecture
(jamais une absence silencieuse) ; une séance AVEC ligne mais `model_kcal: None` (poids
introuvable ou implausible, `reason_code: "no_weight"`, ou erreur interne,
`"internal_error"`) la porte directement depuis la table. `--activity`/`--date`/
`--since` sont INCOMPATIBLES entre eux (comme `--date`/`--days` pour `decisions`) : au
plus un filtre de sélection à la fois, jamais une précédence silencieuse. Colonnes
`activity.calories_bmr_kcal` et table `activity_energy` recalculées en entier à chaque
`compute_metrics` — même discipline que GAP/#44, découplage/#45, VAM/#46, descente/#47,
durabilité/#48, mais dans son PROPRE `try`/`except` (revue de code) : un échec du calcul
d'énergie ne remet jamais à NULL les autres KPI FIT de la séance, et réciproquement.
Réponse toujours accompagnée de `model_id` et, par défaut, `assumptions_summary` (1-2
lignes, `arc_energy.SUMMARY`) — `--assumptions` bascule sur `assumptions`
(`arc_energy.ASSUMPTIONS` en entier, plusieurs Ko) pour l'agent qui veut vérifier une
hypothèse précise, jamais les deux en même temps.

`energy --calibration` rend un rapport DIFFÉRENT : la calibration personnelle du
modèle (`energy_calibration`, voir `arc_energy.ASSUMPTIONS["calibration"]`) — ratio
médian Garmin/modèle par panier route/trail sur `--weeks` dernières semaines (défaut
`arc_energy.CALIBRATION_WINDOW_WEEKS`, 26), INCOMPATIBLE avec `--activity`/`--date`/
`--since`/`--limit`/`--assumptions` (aucun sens pour ce rapport-ci). Appliquée
UNIQUEMENT aux prévisions (`arc_race_pacing`), JAMAIS à ce listing de séances
mesurées : `energy`/`energy --calibration` restent deux calculs INDÉPENDANTS, jamais
l'un ne recalibre l'autre.

`gait-summary [--weeks N]` (#151) rend la synthèse « Foulée » : tendances de la dynamique de course
mesurée (temps de contact, balance du temps de contact, oscillation et ratio verticaux, longueur de
pas, cadence) sur les séances de course (route + trail, défaut 26 semaines), indices d'attaque et
asymétrie des inspections photo, `confidence` (effectifs) et `contradictions` (la mesure prime sur
l'usure). Jamais un diagnostic, aucune modification de charge — voir `arc_gait.ASSUMPTIONS` et
`arc_metrics.ASSUMPTIONS["gait"]`. Lecture seule ; `/api/gait` la sert au tableau de bord.

`load-forecast [--until DATE] [--compare FICHIER] [--text]` (#172) projette condition / fatigue / forme jour
par jour de l'état réel d'aujourd'hui jusqu'à la date de l'objectif actif (ou `--until`), à partir de la
charge ESTIMÉE des séances planifiées (même estimateur que le garde-fou R1, jamais un second modèle) :
forme prévue le jour J, semaine de pic de fatigue, ACWR projeté sur le bloc. Jour sans séance = charge nulle,
semaines non planifiées comptées ; états honnêtes `no_objective` / `no_plan` / `insufficient_history`
(même plancher que R1) / `target_past`. `--compare` oppose le plan actuel à un plan modifié (les semaines de
même lundi sont remplacées) et chiffre les écarts. Estimation, jamais une mesure — voir
`arc_metrics.ASSUMPTIONS["load_forecast"]`. Sortie JSON comme les autres commandes ; `--text` pour un résumé
lisible. Lecture seule ; `/api/load-forecast` la sert au tableau de bord.

`plan-templates` (#189, épopée #173) liste les gabarits de périodisation livrés avec le moteur
(`config/plans/*.json`) ; avec `--format ID` (ou `--distance-km D [--sport trail|road]` pour le
choisir selon l'objectif), rend le gabarit résolu semaine par semaine (en % de la semaine pic) pour
`--weeks N` (défaut : celui du gabarit) et le verdict de cohérence avec les garde-fous du workspace
(`[guardrails]`). Sans `--sport`, le sport vient de `[sport].primary`. Lecture seule, sans index ni
base — voir `arc_plan_templates.py`. JSON par défaut (comme les autres sous-commandes), `--text` pour
un tableau lisible. Un point de départ, jamais un plan : le squelette daté est `plan-skeleton`.

`plan-skeleton [--format ID] [--race-date AAAA-MM-JJ] [--held-hours H] [--held-elevation-m M] [--long-run-day J]
[--lead-in ramp|flat] [--lead-in-weeks K] [--text] [--write]` (#190, épopée #173) génère le squelette du bloc, semaine par semaine, de la semaine en cours à
la semaine de course (+ récupération post-course) : gabarit (`--format`, sinon choisi d'après la distance de
l'objectif actif), volume/D+ TENUS sur les 4 dernières semaines (pic = tenu × `peak_from_current`, jamais inventé ;
`--held-hours` pour un volume déclaré), disponibilité du profil, et créneaux de séance `placeholder` à habiller par
le coach. Chaque semaine passe `arc_guardrails.evaluate` (jamais une semaine `block` émise) ; la forme prévue le
jour J est projetée par `load-forecast`. Par défaut un DRY RUN (JSON, ou `--text`) ; `--write` écrit un
`planning/Semaine_<lundi>.md` par semaine, refuse d'écraser (liste les conflits) et valide les fichiers — voir
`arc_plan_skeleton.py`. États honnêtes : `too_short` (options), `no_history`, `no_objective`, `no_template`,
`target_past`, `needs_review`. #204 : la mise en route (semaines au-delà du maximum du gabarit, ou
`--lead-in-weeks K`) fait monter le volume (≤ +4 %/semaine, plafonnée par R2/R3 ; `--lead-in flat` pour
l'ancien comportement) et `race_demand` compare pic, D+ et sortie longue aux cibles du score Trail Shape
(avertissement sous 75 %).

Options communes : `--workspace DIR` (sinon $ARC_WORKSPACE, le pointeur
~/.config/ai-running-coach/workspace, puis le moteur), `--db FICHIER` (défaut
<workspace>/.arc/coach.db), `--memory` (base en mémoire, rien sur disque),
`--today AAAA-MM-JJ` (date de fin des séries, pour des sorties reproductibles).

Chaîne de lecture par fichier : bloc ```arc valide → format canonique hérité
(YAML + splits) → puces → rien. Seul le premier étage donne `parsed_ok = ok`.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_altitude as AL  # noqa: E402
import arc_power as PW  # noqa: E402
import arc_climb as VC  # noqa: E402
import arc_climb_match as VM  # noqa: E402
import arc_contract as C  # noqa: E402
import arc_cs as CS  # noqa: E402
import arc_cycle as CY  # noqa: E402
import arc_decision_effects as DE  # noqa: E402
import arc_decoupling as DC  # noqa: E402
import arc_dem as DEM  # noqa: E402
import arc_descent as DS  # noqa: E402
import arc_durability as DU  # noqa: E402
import arc_energy as EN  # noqa: E402
import arc_gait as GT  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_legacy as L  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_plan_templates as PT  # noqa: E402
import arc_prevention as PV  # noqa: E402
import arc_samples as S  # noqa: E402
import arc_slope_model as SL  # noqa: E402
import arc_strength as SG  # noqa: E402
import arc_trail_shape as TS  # noqa: E402
from coach_config import ConfigError, read_toml  # noqa: E402
from coach_setup import ENGINE, workspace_root  # noqa: E402

# #58 (2ᵉ revue de code) : `slope_model_meta.selected_by_plan`/`selected_by_hr`.
# #58 : modèle personnel pente -> allure — tables `slope_model_bin`/`slope_model_meta`.
# #54 : nouveau type de contrat `decision` — tables `decision` (une ligne par fichier) et
# `decision_rule` (une ligne par rule_id cité, pour le filtre par règle du journal des
# décisions, #55). #100 (revue de code) : colonnes `decision.created_at_utc` (tri correct
# entre fuseaux) et `decision.supersedes` — voir #49 pour la version d'avant #54.
# #62 : nouvelles tables `performance_index`/`performance_index_warning` (indices
# de performance ITRA/UTMB) — sans ce bump, une base `.arc/coach.db` déjà
# construite par une version antérieure ne les recrée jamais (le fichier
# `Runner_Profile.md` inchangé est alors sauté à la réindexation, `current ==
# SCHEMA_VERSION` restant vrai), et `performance_index()`/`/api/summary`
# échouent avec « no such table » — panne du tableau de bord entier pour un
# utilisateur existant (revue de code #109, 2e tour, blocker).
# #69 : plan multi-semaines (`week.weeks[]`) — `week`/`planned_session` gagnent
# une colonne `shadowed` (0/1), calculée à CHAQUE `index_workspace()` par
# `_mark_week_shadowing` (jamais persistée entre deux semaines contradictoires :
# recalculée en entier à chaque passage, jamais périmée même si le fichier
# « gagnant » d'une collision disparaît). Sans ce bump, une base déjà construite
# par une version antérieure n'a pas la colonne et `store()`/les requêtes du
# tableau de bord échoueraient avec « no such column ».
# #68 : `activity` gagne la colonne `intervals_activity_id` (TEXT — identifiant
# Intervals.icu, une CHAÎNE, jamais confondue avec `garmin_activity_id` qui
# reste un entier) pour les activités synchronisées depuis `[data].source =
# "intervals"`. Sans ce bump, une base déjà construite par une version
# antérieure n'a pas la colonne et l'insertion échouerait avec « no such column ».
# Dépense énergétique modèle vs Garmin : `activity` gagne `calories_bmr_kcal` (copie déclarative
# du champ `bmr_calories` Garmin, voir `arc_contract.py`) et une nouvelle table
# `activity_energy` (dépense énergétique modèle RE3 + marche, `scripts/arc_energy.py`,
# recalculée en entier à chaque `compute_metrics` comme `activity_descent_class`/
# `activity_climb`). Sans ce bump, une base déjà construite par une version
# antérieure n'a ni la colonne ni la table et l'indexation échouerait avec « no such
# column »/« no such table ».
# #132 : `gear` gagne `start_m` (kilométrage de départ, segment « départ N km » de la puce
# chaussure) et `usage` (rôle facultatif) — sans ce bump, une base déjà construite
# n'a pas les colonnes et l'insertion échouerait avec « no such column ».
# #133 : `gear` gagne `garmin_uuid` (segment « garmin: <uuid> » de la puce chaussure) et
# `activity` gagne `gear_source` (« garmin »/« chat », provenance du `gear_id`) — sans ce
# bump, une base déjà construite n'a pas les colonnes (« no such column »).
# #134 : nouvelle table `equipment` (section « ### Matériel » du profil, `arc_legacy.parse_equipment`)
# et `activity` gagne `gear_ids` (liste JSON des slugs de matériel porté) — sans ce bump, une base
# déjà construite n'a ni la table ni la colonne (« no such table »/« no such column »).
# #135 : nouvelle table `gear_inspection` (inspections photo de chaussures, `gear/*_inspection.md`, dossier
# `gear/` ajouté à `DATA_DIRS`) — sans ce bump, une base déjà construite n'a pas la table (« no such table »).
# Temps en zone surestimé (buckets partiels) : `activity_sample` gagne `covered_s` (REAL,
# secondes réellement couvertes par les mesures du bucket, `arc_samples.ASSUMPTIONS
# ["covered_s"]`) — version 30 (#139).
# FIT Intervals.icu (#68, suite) : `activity_sample` et `sample_file` gagnent la colonne
# `intervals_activity_id` (TEXT) — les échantillons d'une séance synchronisée depuis
# Intervals.icu (`activities/fit/i<chiffres>.json`, `skills/fit-download --source
# intervals`) s'y rattachent comme ceux d'une séance Garmin à `garmin_activity_id`.
# Version 31 et non 30 : #139 a déjà publié la 30 sans cette colonne — une base construite
# en 30 doit être reconstruite, sinon l'ingestion échouerait avec « no such column ».
# #151 : `activity_sample` gagne la dynamique de course Garmin (`ground_contact_s`,
# `stance_balance_pct`, `vertical_oscillation_m`, `vertical_ratio_pct`, `step_length_m`, NULL quand le
# capteur ne les fournit pas — `arc_samples.ASSUMPTIONS["running_dynamics"]`) — sans ce bump, une base déjà
# construite n'a pas les colonnes (« no such column »). Version 32 (31 = #68 FIT Intervals.icu). Les
# `activities/fit/*.json` existants n'en portent pas : les re-extraire avec `download_fit.py --refresh-dynamics`.
# #166 : `health_day` gagne `cycle_phase`/`cycle_day`/`cycle_source` (contexte du cycle, opt-in
# `[health].cycle_tracking`, NULL par défaut) — version 33, sans ce bump l'ingestion d'un fichier santé
# portant ces clés échouerait avec « no such column » sur une base déjà construite.
# Strava (#164, `[data].source = "strava"`) : `activity`, `activity_sample` et `sample_file` gagnent la
# colonne `strava_activity_id` (TEXT, `s<chiffres>`) — troisième espace d'identifiants externes, disjoint
# des deux autres (`arc_samples.parse_activity_ref`). Version 34 (33 = #166 cycle) : sans ce bump, une base déjà construite
# n'a pas la colonne et l'insertion échouerait avec « no such column ».
# #193 : `week` gagne `week_type` (type de semaine du squelette de bloc #190, NULL pour les semaines plus
# anciennes) — la frise du bloc (`/api/block`) en a besoin. Version 35 (34 = Strava) : sans ce bump,
# l'insertion d'une semaine échouerait avec « no such column » sur une base déjà construite.
# #222 : `health_day` gagne `weight_origin` (`garmin` | `chat`, provenance du poids du jour) et
# `weight_garmin_kg` (pesée Garmin écartée au profit de la valeur déclarée) — version 36 (35 = #193) :
# les colonnes de `health_day` suivent le contrat, sans ce bump l'insertion échouerait.
# Home trainer (MyWhoosh) : `activity` gagne `avg_power_w`/`max_power_w`/`normalized_power_w`,
# `activity_sample` gagne `power_w` (`arc_samples.POWER_KEY`), `athlete` gagne l'équipement vélo déclaré
# (`ht_trainer`, `ht_bike`, `bike_mass_kg`, `ftp_declared_w`, section « ### Vélo & home trainer » du profil)
# et `planned_session` gagne `virtual_route` (JSON, parcours virtuel choisi) — version 37 (36 = #222) : sans
# ce bump, l'insertion échouerait avec « no such column ». Les `activities/fit/*.json` existants n'ont pas de
# puissance : les re-extraire avec `download_fit.py --refresh-dynamics` (ré-extrait toutes les clés).
SCHEMA_VERSION = 37
# Colonnes d'identifiant externe d'une séance, dans l'ordre de priorité de `activity_ref` — une séance n'en
# porte qu'une (`workspace-data-contract`) ; Garmin prime si un fichier ancien en porte plusieurs.
REF_COLUMNS = ("garmin_activity_id", "intervals_activity_id", "strava_activity_id")
DEFAULT_DB = ".arc/coach.db"
DATA_DIRS = ("activities", "medical", "nutrition", "planning", "rapports", "gear")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(workspace: Path) -> Dict[str, dict]:
    """workspace.toml puis workspace.user.toml, clé par clé (même règle que config.sh).

    Sans `config/workspace.toml` dans le workspace (installation incomplète),
    les défauts du moteur s'appliquent.
    """
    shared = workspace / "config/workspace.toml"
    if not shared.exists():
        shared = ENGINE / "config/workspace.toml"
    merged: Dict[str, dict] = {}
    for path in (shared, workspace / "config/workspace.user.toml"):
        for section, values in read_toml(path).items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
    return merged


DEFAULT_MAP_TILES = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
DEFAULT_MAP_ATTRIBUTION = "© OpenStreetMap contributors, SRTM · style © OpenTopoMap (CC-BY-SA)"
_MAP_TILES_RE = re.compile(r"https://(\{s\}\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(:\d+)?/[^\s\"'<>]*\{z\}[^\s\"'<>]*")


def _map_tiles(config: Dict[str, dict]) -> str:
    """`[dashboard].map_tiles`, jamais en levant : modèle d'URL de tuiles en https, hôte littéral
    (seul `{s}.` est permis en tête, pour les sous-domaines), `{z}` présent. Absente = défaut ;
    vide, ou invalide (avertissement) = `""`, la carte n'affiche que la trace. L'hôte alimente
    l'en-tête Content-Security-Policy (`arc_serve.tile_origin`) : rien d'autre n'y entre."""
    value = config.get("dashboard", {}).get("map_tiles", DEFAULT_MAP_TILES)
    if not isinstance(value, str):
        value = ""
    value = value.strip()
    if value and not _MAP_TILES_RE.fullmatch(value):
        print(f"avertissement : [dashboard].map_tiles « {value} » ignoré (https://hôte/…{{z}}/{{x}}/{{y}}… attendu) : "
              "carte sans fond.", file=sys.stderr)
        return ""
    return value


def _heat_threshold_c(config: Dict[str, dict]) -> float:
    """Résout `[health].heat_threshold_c`, jamais en levant : un typo dans
    `workspace.user.toml` (ex. `heat_threshold_c = "chaud"`) ne doit PAS casser
    `index_workspace` — appelé par CHAQUE commande (`index`, `hrv-baseline`,
    `sleep-debt`, `heat-acclimation`, et le rafraîchissement du tableau de bord).

    Accepte un nombre, ou une chaîne numérique (le repli TOML < 3.11,
    `coach_config._read_toml_fallback`, ne reconnaît que les entiers et rend les
    flottants sous forme de chaîne — `"25.0"` doit donc rester valide). Rejette
    explicitement les booléens (`True`/`False` sont aussi des `int` en Python :
    sans ce test, `heat_threshold_c = true` serait accepté comme 1.0 °C). Toute
    valeur absente, vide ou invalide retombe sur `M.HEAT_THRESHOLD_C_DEFAULT`,
    avec un avertissement sur stderr dans le cas invalide (pas pour une simple
    absence, qui est le cas normal sans override) — voir
    `arc_metrics.ASSUMPTIONS["heat_acclimation"]`.
    """
    raw = config.get("health", {}).get("heat_threshold_c")
    if raw in (None, ""):
        return M.HEAT_THRESHOLD_C_DEFAULT
    value = None
    if not isinstance(raw, bool):
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip().replace(",", "."))
            except ValueError:
                value = None
    if value is None:
        print(f"avertissement : [health].heat_threshold_c = {raw!r} n'est pas un nombre valide — "
              f"défaut {M.HEAT_THRESHOLD_C_DEFAULT:g} °C appliqué.", file=sys.stderr)
        return M.HEAT_THRESHOLD_C_DEFAULT
    return value


def _hr_zone_method(config: Dict[str, dict]) -> str:
    """Résout `[athlete].hr_zones`, jamais en levant (même discipline que
    `_heat_threshold_c` ci-dessus) : un typo ou une casse différente
    (`hr_zones = "LTHR"`, `hr_zones = "lthar"`) ne doit PAS casser `index_workspace`.

    Insensible à la casse et aux espaces (`M.hr_zone_bounds` le refait de toute façon
    en défense en profondeur, mais normaliser ici évite qu'un avertissement soit
    émis à chaque appel pour une simple casse différente). Toute valeur absente,
    vide, non-chaîne ou hors de `("auto",) + M.HR_ZONE_METHODS` retombe sur
    `M.HR_ZONE_METHOD_DEFAULT` (« auto »), avec un avertissement sur stderr dans le
    cas invalide seulement (pas pour une simple absence). Voir revue de code #43,
    point 4 : une méthode FORCÉE mais dont le profil n'a pas les champs requis reste
    volontairement possible ici (ce n'est pas une erreur de configuration, c'est
    `arc_metrics.hr_zone_resolution` qui en rend la raison à l'appelant, pas cette
    fonction — qui ne valide que le NOM de la méthode)."""
    raw = config.get("athlete", {}).get("hr_zones")
    if raw in (None, ""):
        return M.HR_ZONE_METHOD_DEFAULT
    allowed = (M.HR_ZONE_METHOD_DEFAULT,) + M.HR_ZONE_METHODS
    if not isinstance(raw, str):
        print(f"avertissement : [athlete].hr_zones = {raw!r} n'est pas une chaîne — "
              f"défaut « {M.HR_ZONE_METHOD_DEFAULT} » appliqué.", file=sys.stderr)
        return M.HR_ZONE_METHOD_DEFAULT
    value = raw.strip().lower()
    if value not in allowed:
        print(f"avertissement : [athlete].hr_zones = {raw!r} hors de {allowed} — "
              f"défaut « {M.HR_ZONE_METHOD_DEFAULT} » appliqué.", file=sys.stderr)
        return M.HR_ZONE_METHOD_DEFAULT
    return value


def _positive_float(config: Dict[str, dict], section: str, key: str, default: float) -> float:
    """Résout `[section].key` en flottant strictement positif, jamais en levant —
    même discipline que `_heat_threshold_c` (revue de code #46, should-fix 4 :
    « montée minimale configurable », critère d'acceptation de #46). Accepte un
    nombre ou une chaîne numérique (repli TOML < 3.11, voir `_heat_threshold_c`),
    rejette les booléens. Toute valeur absente, vide, invalide, nulle ou négative
    retombe sur `default`, avec un avertissement sur stderr dans le cas invalide
    seulement (jamais pour une simple absence, le cas normal sans override)."""
    raw = config.get(section, {}).get(key)
    if raw in (None, ""):
        return default
    value = None
    if not isinstance(raw, bool):
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip().replace(",", "."))
            except ValueError:
                value = None
    if value is None or value <= 0:
        print(f"avertissement : [{section}].{key} = {raw!r} n'est pas un nombre strictement positif "
              f"valide — défaut {default:g} appliqué.", file=sys.stderr)
        return default
    return value


def _positive_int_at_least_1(config: Dict[str, dict], section: str, key: str, default: int) -> int:
    """Comme `_positive_float`, puis arrondi à l'entier le plus proche et
    replié sur `default` si le résultat est sous 1 (revue de code #58, nit —
    ex. `slope_model_months = 0.5` : `_positive_float` seule le laisserait
    passer tel quel, un `int(0.5)` silencieux tronquant ensuite à 0, une
    fenêtre de modèle nulle jamais signalée comme une erreur de configuration)."""
    raw_value = _positive_float(config, section, key, float(default))
    rounded = round(raw_value)
    if rounded < 1:
        print(f"avertissement : [{section}].{key} = {raw_value:g} donne un entier < 1 une fois arrondi — "
              f"défaut {default} appliqué.", file=sys.stderr)
        return default
    return rounded


def home_trainer_platform(config: Dict[str, dict]) -> str:
    """`[home_trainer].platform` normalisée : une valeur de `arc_contract.VIRTUAL_PLATFORMS`, sinon "off"
    (absente, vide ou inconnue — opt-in strict, jamais devinée)."""
    raw = str((config.get("home_trainer") or {}).get("platform") or "").strip().lower()
    return raw if raw in C.VIRTUAL_PLATFORMS else "off"


def settings(config: Dict[str, dict]) -> dict:
    """Les réglages qui changent ce que l'index attend et ce que le tableau affiche."""
    agents = config.get("agents", {}).get("enabled", ["coach", "medical", "nutritionist", "course-strategist"])
    return {
        "sport": config.get("sport", {}).get("primary", "trail") or "trail",
        "morning_check": config.get("health", {}).get("morning_check", "full") or "full",
        "heat_threshold_c": _heat_threshold_c(config),
        # Contexte du cycle menstruel (#166) : "off" (défaut) | "garmin" | "intervals" | "manual" ; toute autre
        # valeur → "off" avec avertissement (scripts/arc_cycle.py), jamais une exception.
        "cycle_tracking": CY.cycle_tracking_mode(config),
        "agents": list(agents),
        "units": config.get("athlete", {}).get("units", "metric") or "metric",
        "profile": config.get("athlete", {}).get("profile", "planning/Runner_Profile.md"),
        "hr_zones": _hr_zone_method(config),
        # Home trainer : plateforme virtuelle (`[home_trainer].platform`), "off" si absente ou inconnue.
        "home_trainer_platform": home_trainer_platform(config),
        "language": config.get("language", {}).get("documents", "fr") or "fr",
        # Page « Coach » (chat) : n'affiche l'entrée de nav que si le service est activé.
        "chat_enabled": bool(config.get("chat", {}).get("enabled", False)),
        # Fond de carte de la page séance : modèle d'URL validé (`""` = trace seule) et mention légale.
        "map_tiles": _map_tiles(config),
        "map_attribution": str(config.get("dashboard", {}).get("map_attribution", DEFAULT_MAP_ATTRIBUTION) or ""),
        # VAM sur les montées détectées (#46, critère d'acceptation : « montée
        # minimale configurable (D+, pente) ») — `climb_min_grade_pct` en points de
        # pourcentage au workspace (ex. 5, pas 0.05), converti ici en fraction pour
        # `arc_climb.detect_climbs(min_avg_grade=...)`.
        "climb_min_gain_m": _positive_float(config, "metrics", "climb_min_gain_m", VC.MIN_CLIMB_GAIN_M),
        "climb_min_grade": _positive_float(
            config, "metrics", "climb_min_grade_pct", VC.MIN_CLIMB_AVG_GRADE * 100.0) / 100.0,
        # Modèle personnel pente -> allure (#58) : fenêtre d'historique (mois) configurable
        # (`[metrics].slope_model_months`) — voir `arc_slope_model.DEFAULT_MONTHS`.
        "slope_model_months": _positive_int_at_least_1(
            config, "metrics", "slope_model_months", SL.DEFAULT_MONTHS),
    }


# ---------------------------------------------------------------------------
# Schéma SQLite
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE source_file (
    path TEXT PRIMARY KEY, kind TEXT, sha256 TEXT, mtime REAL,
    arc_version INTEGER, parsed_ok TEXT, issues TEXT
);
CREATE TABLE athlete (
    source_path TEXT, name TEXT, hr_max_bpm INTEGER, hr_rest_bpm INTEGER,
    hr_threshold_bpm INTEGER, sex TEXT, weight_kg REAL, birth_year INTEGER,
    default_location TEXT, usual_slot TEXT, sleep_need_s REAL,
    ht_trainer TEXT, ht_bike TEXT, bike_mass_kg REAL, ftp_declared_w REAL, body_md TEXT
);
CREATE TABLE gear (
    source_path TEXT, gear_id TEXT, name TEXT, start_date TEXT, threshold_m REAL,
    is_default INTEGER, retired INTEGER, collision_base TEXT, start_m REAL, usage TEXT,
    garmin_uuid TEXT, ignored INTEGER
);
-- Matériel hors chaussures (#134) : une ligne par puce de « ### Matériel » du profil.
-- `kits` : liste JSON de slugs ; seuils typés (`threshold_m`, `threshold_s`, `threshold_sessions`,
-- `threshold_days`), départs typés (`start_m`, `start_s`, `start_sessions`).
CREATE TABLE equipment (
    source_path TEXT, gear_id TEXT, name TEXT, category TEXT, start_date TEXT, maintenance_date TEXT,
    retired INTEGER, kits TEXT, threshold_m REAL, threshold_s REAL, threshold_sessions INTEGER,
    threshold_days INTEGER, start_m REAL, start_s REAL, start_sessions INTEGER, collision_base TEXT,
    parse_warnings TEXT
);
-- Indices de performance ITRA/UTMB (#62) : une ligne par relevé daté de la
-- section « Indices de performance » du profil (`arc_legacy.
-- parse_performance_index`). `category` est NULL pour un indice général
-- (ITRA global, UTMB « général »/« index ») ; sinon texte libre pour l'ITRA, une
-- des quatre valeurs `arc_legacy.UTMB_INDEX_CATEGORIES` pour l'UTMB.
-- `ordinal` : ordre d'apparition dans le fichier (après dédoublonnage), pour
-- départager deux relevés de même date sans dépendre de l'ordre d'insertion
-- SQLite (revue de code #62) — `performance_index()` trie explicitement
-- dessus. Purement déclaratif — jamais alimentée par une requête réseau (voir
-- AGENTS.md).
CREATE TABLE performance_index (
    source_path TEXT, date TEXT, kind TEXT, category TEXT, value REAL, ordinal INTEGER
);
-- Avertissements de lecture de `performance_index` (#62, revue de code) : une
-- ligne du profil ignorée (format illisible, valeur hors bornes, catégorie
-- UTMB inconnue) ou acceptée mais à signaler (date future, doublon exact).
-- Persistés ici plutôt qu'imprimés au moment du parsing pour ne réapparaître
-- QUE lorsque le fichier change (une réindexation d'un fichier inchangé ne
-- les recalcule jamais — voir `index_workspace`), et pour rester consultables
-- par la CLI/le tableau de bord (`performance_index().warnings`) au lieu de se
-- perdre dans la sortie standard d'un process qui a déjà tourné.
CREATE TABLE performance_index_warning (
    source_path TEXT, message TEXT, ordinal INTEGER
);
CREATE TABLE objective (
    source_path TEXT, name TEXT, race_date TEXT, distance_m REAL, elevation_gain_m REAL,
    location TEXT, goal TEXT, target_time_s REAL, weekly_start_s REAL, weekly_start_m REAL,
    weekly_target_s REAL, weekly_target_m REAL, quality_per_week INTEGER,
    training_location TEXT, body_md TEXT
);
CREATE TABLE activity (
    id INTEGER PRIMARY KEY, source_path TEXT, arc_version INTEGER, date TEXT, sport TEXT,
    name TEXT, location TEXT, garmin_activity_id INTEGER, intervals_activity_id TEXT, strava_activity_id TEXT,
    start_time TEXT,
    distance_m REAL, duration_s REAL, moving_duration_s REAL, elevation_gain_m REAL,
    elevation_loss_m REAL, avg_hr_bpm REAL, max_hr_bpm REAL, recovery_hr_bpm REAL,
    avg_cadence_spm REAL, calories_kcal REAL, calories_bmr_kcal REAL, te_aerobic REAL, te_anaerobic REAL, rpe REAL,
    load REAL, load_source TEXT, vo2max_est REAL, missing_reason TEXT,
    gear_id TEXT, gear_source TEXT, carbs_g REAL, fluid_intake_ml REAL, weight_pre_kg REAL, weight_post_kg REAL,
    sweat_rate_l_h REAL, gap_pace_s_km REAL, decoupling_pct REAL, ef_whole REAL,
    decoupling_reason TEXT, best_vam_10min_m_h REAL, best_vam_20min_m_h REAL,
    best_climb_vam_elapsed_m_h REAL, descent_reference_gap_pace_s_km REAL,
    descent_reference_source TEXT, durability_gap_fade_pct REAL, durability_ef_fade_pct REAL,
    durability_hr_first_third_bpm REAL, durability_hr_middle_third_bpm REAL,
    durability_hr_last_third_bpm REAL, durability_reason TEXT, durability_reason_code TEXT,
    gear_ids TEXT, avg_power_w REAL, max_power_w REAL, normalized_power_w REAL,
    body_md TEXT, data_json TEXT
);
CREATE INDEX activity_date ON activity(date);
-- `gap_pace_s_km` (#44, allure ajustée à la pente, `arc_gap.py`) : recalculée en
-- entier à CHAQUE `compute_metrics`, comme `hr_zone_time`/`hr_polarisation_time`
-- (#43) — jamais purgée par fichier, NULL par défaut pour tout sport hors de la
-- famille course à pied ou sans échantillons FIT (voir `arc_gap.ASSUMPTIONS`).
-- `decoupling_pct`/`ef_whole`/`decoupling_reason` (#45, découplage aérobie Pa:HR
-- et facteur d'efficacité, `arc_decoupling.py`) : même discipline de recalcul
-- intégral à chaque `compute_metrics`, restreint à la famille course à pied avec
-- échantillons FIT ingérés. `decoupling_reason` porte TOUJOURS la raison d'un
-- `decoupling_pct` NULL (durée insuffisante, échauffement, FC manquante, effort
-- non stable...) — jamais un NULL muet, voir `arc_decoupling.ASSUMPTIONS`.
-- `best_vam_10min_m_h`/`best_vam_20min_m_h`/`best_climb_vam_elapsed_m_h` (#46,
-- VAM sur les montées détectées, `arc_climb.py`) : même discipline de recalcul
-- intégral à chaque `compute_metrics`, restreint à la famille course à pied avec
-- échantillons FIT ingérés — voir `arc_climb.ASSUMPTIONS`. Le détail par montée
-- vit dans `activity_climb` ci-dessous, jamais ici (une activité peut avoir
-- plusieurs montées).
-- `descent_reference_gap_pace_s_km`/`descent_reference_source` (#47, efficacité en
-- descente, `arc_descent.py`) : allure GAP de référence « plat » utilisée pour
-- CETTE séance (voir `arc_descent.reference_gap_speed_ms`/ASSUMPTIONS["reference"]) —
-- `descent_reference_source` vaut `"flat"` (sections réellement plates) ou
-- `"non_descent"` (repli sur tout ce qui n'est pas une forte descente), jamais
-- caché : une référence de repli reste moins fiable qu'une référence plate franche.
-- NULL si aucune des deux n'est exploitable (voir `arc_descent.REASON_NO_REFERENCE`).
-- `durability_gap_fade_pct`/`durability_ef_fade_pct` (#48, durabilité sur les
-- sorties longues, `arc_durability.py`) : fade du GAP et de l'EF (GAP/FC) entre le
-- premier et le dernier tiers (temps de mouvement, post-échauffement) de la séance
-- — même discipline de recalcul intégral à chaque `compute_metrics` que
-- `decoupling_pct`/`ef_whole` ci-dessus, restreint à la famille course à pied avec
-- échantillons FIT ingérés, sorties longues UNIQUEMENT (`duration_s` >
-- `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min). `durability_hr_first_third_bpm`/
-- `_hr_middle_third_bpm`/`_hr_last_third_bpm` : FC moyenne par tiers, à titre
-- descriptif (voir `arc_durability.ASSUMPTIONS["hr_by_third"]`). `durability_reason`/
-- `durability_reason_code` portent TOUJOURS la raison d'un `durability_gap_fade_pct`
-- NULL (durée insuffisante, échauffement, FC manquante, pente asymétrique...) —
-- jamais un NULL muet, voir `arc_durability.ASSUMPTIONS`.
CREATE TABLE activity_split (
    activity_id INTEGER, km INTEGER, distance_m REAL, duration_s REAL, elev_gain_m REAL,
    elev_loss_m REAL, avg_hr_bpm REAL, max_hr_bpm REAL, max_speed_kmh REAL,
    cadence_spm REAL, label TEXT, gap_pace_s_km REAL
);
CREATE TABLE health_day (
    source_path TEXT, arc_version INTEGER, date TEXT, morning_check TEXT,
    sleep_total_s REAL, sleep_deep_s REAL, sleep_light_s REAL, sleep_rem_s REAL,
    sleep_awake_s REAL, sleep_score REAL, sleep_start TEXT, sleep_end TEXT,
    hrv_overnight_ms REAL, hrv_baseline_low_ms REAL, hrv_baseline_high_ms REAL, hrv_status TEXT,
    hrv_personal_low_ms REAL, hrv_personal_high_ms REAL, hrv_personal_status TEXT,
    resting_hr_bpm REAL, readiness_score REAL, body_battery_high REAL, body_battery_low REAL,
    stress_avg REAL, weight_kg REAL, weight_origin TEXT, weight_garmin_kg REAL, verdict TEXT, verdict_reason TEXT,
    cycle_phase TEXT, cycle_day INTEGER, cycle_source TEXT, body_md TEXT, data_json TEXT
);
CREATE INDEX health_date ON health_day(date);
CREATE TABLE weather_day (
    source_path TEXT, date TEXT, location TEXT, category TEXT, best_slot TEXT, slot_reason TEXT,
    temp_min_c REAL, temp_max_c REAL, feels_like_c REAL, wind_kmh REAL, gust_kmh REAL,
    precip_mm REAL, chance_of_rain_pct REAL, uv_index REAL, data_json TEXT
);
-- `shadowed` (#69, plan multi-semaines) : 0 par défaut, posé à 1 par
-- `_mark_week_shadowing` pour la ou les semaines écartées d'une collision de
-- `week_start` entre plusieurs fichiers (voir SKILL.md, section « Collision »).
-- Recalculé en ENTIER à chaque `index_workspace()`, jamais un état persisté
-- entre deux passes : une semaine ne reste jamais figée « shadowed » après la
-- disparition du fichier qui la masquait.
CREATE TABLE week (
    source_path TEXT, arc_version INTEGER, week_start TEXT, location TEXT, phase TEXT,
    target_duration_s REAL, target_distance_m REAL, target_elevation_m REAL, body_md TEXT,
    shadowed INTEGER DEFAULT 0, week_type TEXT
);
CREATE TABLE planned_session (
    source_path TEXT, week_start TEXT, date TEXT, sport TEXT, title TEXT,
    planned_duration_s REAL, planned_distance_m REAL, planned_elevation_m REAL,
    intensity TEXT, outdoor INTEGER, garmin_workout_id INTEGER, status TEXT,
    weather_category TEXT, best_slot TEXT, shadowed INTEGER DEFAULT 0, virtual_route TEXT
);
CREATE TABLE nutrition_day (
    source_path TEXT, date TEXT, intake_kcal REAL, carbs_g REAL, protein_g REAL, fat_g REAL,
    hydration_ml REAL, burned_kcal REAL, weight_kg REAL, target_weight_kg REAL, body_md TEXT
);
CREATE TABLE report (
    source_path TEXT, date TEXT, report_type TEXT, title TEXT, period_start TEXT,
    period_end TEXT, location TEXT, body_md TEXT
);
CREATE TABLE course_eval (
    source_path TEXT, date TEXT, name TEXT, distance_m REAL, elevation_gain_m REAL,
    verdict TEXT, body_md TEXT, data_json TEXT
);
CREATE TABLE race_plan (
    source_path TEXT, date TEXT, race_name TEXT, race_date TEXT, distance_m REAL,
    elevation_gain_m REAL, target_time_s REAL, body_md TEXT, data_json TEXT
);
CREATE TABLE aid_station (source_path TEXT, km REAL, name TEXT, cutoff TEXT, services TEXT);
-- `decision` (#54) : traçabilité d'un ajustement du coach — un fichier =
-- une décision (`planning/AAAA-MM-JJ_decision_<slug>.md`), jamais une section
-- dans le fichier semaine (voir SKILL.md, justification du choix). `inputs`/
-- `rule_ids`/`sources`/`before`/`after`/`session_ref` restent en JSON brut
-- (`*_json`) : ce sont des objets/listes libres, pas des colonnes qu'une
-- requête SQL courante filtre directement — `decision_rule` ci-dessous
-- couvre déjà le seul filtre utile (#55 : décisions par règle). `created_at`
-- départage plusieurs décisions du même `date` (ordre chronologique d'écriture,
-- critère d'acceptation #54 : « plusieurs décisions le même jour, triées par
-- created_at ») — `created_at_utc` (#100, revue de code) est la colonne
-- RÉELLEMENT utilisée pour ce tri : `created_at` est un TEXTE ISO 8601, et
-- trier du texte mélange des décisions écrites depuis des fuseaux différents
-- dans le mauvais ordre (`07:00+02:00` textuellement après `06:00Z`, alors que
-- 07:00+02:00 = 05:00 UTC est en fait ANTÉRIEUR) — voir
-- `arc_contract.decision_created_at_utc`, calculée à l'écriture (`store()`),
-- jamais recalculée à la lecture.
CREATE TABLE decision (
    source_path TEXT, arc_version INTEGER, date TEXT, created_at TEXT, created_at_utc TEXT,
    trigger TEXT, summary TEXT, outcome TEXT, garmin_workout_id INTEGER, supersedes TEXT,
    inputs_json TEXT, rule_ids_json TEXT, sources_json TEXT,
    before_json TEXT, after_json TEXT, session_ref_json TEXT,
    body_md TEXT, data_json TEXT
);
CREATE INDEX decision_date ON decision(date, created_at_utc);
-- Une ligne par `rule_id` cité dans `decision.rule_ids` (#54/#55) : permet de
-- filtrer le journal des décisions par règle de garde-fou sans parser
-- `rule_ids_json` à chaque requête.
CREATE TABLE decision_rule (source_path TEXT, rule_id TEXT);
CREATE INDEX decision_rule_id ON decision_rule(rule_id);
CREATE TABLE metric_day (
    date TEXT PRIMARY KEY, load REAL, fitness REAL, fatigue REAL, form REAL, acwr REAL,
    monotony REAL, strain REAL, vo2max REAL
);
-- Échantillons FIT sous-échantillonnés (#42). Clé de rattachement = garmin_activity_id
-- (JAMAIS activity.id/rowid — voir `ingest_samples` pour le bug que ça corrige : un
-- rowid change à chaque édition du Markdown et peut être réattribué après suppression).
-- Le lien avec `activity` est résolu à LA LECTURE (`samples()`), jamais mis en cache.
-- source_path permet de purger les lignes d'un fichier `activities/fit/<id>.json`
-- modifié ou supprimé, comme les autres tables par fichier. lat/lon (#49, réservées par
-- #42) : remplies quand le FIT source porte un GPS exploitable (`arc_samples.GPS_KEYS`),
-- NULL sinon (indoor, capteur coupé) — usage INTERNE uniquement (appariement de montée,
-- `arc_climb_match.py`) : jamais exposées par l'API ni le CLI (voir
-- `arc_climb_match.ASSUMPTIONS["privacy"]`).
-- `intervals_activity_id` (#68) : même rôle que `garmin_activity_id` pour une séance
-- synchronisée depuis Intervals.icu — exactement UNE des deux colonnes est renseignée
-- par ligne, selon la forme de l'identifiant du fichier (`arc_samples.parse_activity_ref`) ;
-- `strava_activity_id` (#164) : troisième espace (`s<chiffres>`), même règle.
CREATE TABLE activity_sample (
    garmin_activity_id INTEGER, source_path TEXT, t_s REAL, distance_m REAL, altitude_m REAL,
    hr_bpm REAL, speed_ms REAL, cadence_spm REAL, lat REAL, lon REAL, covered_s REAL,
    intervals_activity_id TEXT, strava_activity_id TEXT,
    ground_contact_s REAL, stance_balance_pct REAL, vertical_oscillation_m REAL, vertical_ratio_pct REAL,
    step_length_m REAL, power_w REAL
);
CREATE INDEX activity_sample_garmin ON activity_sample(garmin_activity_id);
CREATE INDEX activity_sample_intervals ON activity_sample(intervals_activity_id);
CREATE INDEX activity_sample_strava ON activity_sample(strava_activity_id);
CREATE INDEX activity_sample_source ON activity_sample(source_path);
-- Suivi des fichiers `activities/fit/*.json` — table DÉDIÉE, jamais `source_file` :
-- `source_file` est lu par `backfill_items` et `scripts/coach_doctor.py` en supposant
-- qu'il ne contient que des fichiers Markdown du contrat (revue PR #87) ; y mêler les
-- FIT y ferait apparaître à tort une dette de contrat ou un « fichier supprimé »
-- fantôme après --rebuild.
CREATE TABLE sample_file (
    path TEXT PRIMARY KEY, sha256 TEXT, mtime REAL, garmin_activity_id INTEGER,
    status TEXT, issues TEXT, intervals_activity_id TEXT, strava_activity_id TEXT
);
-- Temps en zone FC (#43), par activité (id INTERNE, comme `activity_split` — jamais
-- `garmin_activity_id` : la ligne est recréée à chaque `compute_metrics`, sans purge
-- par fichier). Une activité sans zone calculable (pas de FC max au profil), hors de
-- la famille course à pied (`arc_metrics.sport_family` != "run" — revue de code #43,
-- point 5 : le renforcement et le vélo faussaient la polarisation) ou sans
-- échantillons FIT n'a simplement aucune ligne ici.
CREATE TABLE hr_zone_time (activity_id INTEGER, zone INTEGER, seconds REAL);
CREATE INDEX hr_zone_time_activity ON hr_zone_time(activity_id);
-- Temps par seau Seiler (#43, revue de code point 2) : bornes bpm DÉDIÉES par
-- méthode (`arc_metrics.seiler_bounds`), JAMAIS dérivées de `hr_zone_time` par un
-- simple regroupement de numéros de zone (faux pour LTHR/%FCmax, voir
-- ASSUMPTIONS["hr_zones"]). `bucket` : "low" | "moderate" | "high". Mêmes règles de
-- restriction et de recalcul que `hr_zone_time` ci-dessus.
CREATE TABLE hr_polarisation_time (activity_id INTEGER, bucket TEXT, seconds REAL);
CREATE INDEX hr_polarisation_time_activity ON hr_polarisation_time(activity_id);
-- Montées détectées par activité (#46, `arc_climb.py`), id INTERNE (`activity_id`,
-- comme `hr_zone_time`/`activity_split` — jamais `garmin_activity_id` : la ligne
-- est recréée en entier à chaque `compute_metrics`, sans purge par fichier). `idx`
-- : ordre de la montée dans l'activité (1-based, chronologique). `avg_grade` :
-- fraction signée (0,08 = 8 %). `vam_elapsed_m_h`/`vam_moving_m_h` : voir
-- `arc_climb.ASSUMPTIONS["vam_basis"]` (les deux, jamais une seule). Une activité
-- sans montée détectée (parcours plat, ou hors famille course à pied/sans FIT)
-- n'a simplement aucune ligne ici.
-- `segment_id`/`hr_first_third_bpm`/`hr_last_third_bpm`/`hr_drift_bpm_per_100m`/
-- `vs_previous_pct`/`vs_best_pct` (#49, identité de montée entre séances,
-- `arc_climb_match.py`) : `segment_id` référence `climb_segment.id` ci-dessous, `NULL`
-- si cette montée n'a pu être appariée NI enregistrée comme nouveau segment (ne devrait
-- pas arriver en pratique — voir `compute_metrics`). `hr_*`/`vs_*` : voir
-- `arc_climb_match.ASSUMPTIONS["hr_drift"]`/["progression"], `NULL` si non calculables
-- (gain trop faible, FC manquante, ou première occurrence du segment pour `vs_*`).
CREATE TABLE activity_climb (
    activity_id INTEGER, idx INTEGER, start_t_s REAL, end_t_s REAL, start_km REAL, end_km REAL,
    distance_m REAL, gain_m REAL, avg_grade REAL, grade_class TEXT,
    duration_elapsed_s REAL, duration_moving_s REAL, vam_elapsed_m_h REAL, vam_moving_m_h REAL,
    segment_id INTEGER, hr_first_third_bpm REAL, hr_last_third_bpm REAL,
    hr_drift_bpm_per_100m REAL, vs_previous_pct REAL, vs_best_pct REAL
);
CREATE INDEX activity_climb_activity ON activity_climb(activity_id);
CREATE INDEX activity_climb_segment ON activity_climb(segment_id);
-- Registre des montées reconnues comme « la même » d'une séance à l'autre (#49,
-- `arc_climb_match.py`) — recalculé INTÉGRALEMENT à chaque `compute_metrics` (comme
-- `activity_climb`/`hr_zone_time`, jamais une purge par fichier). `id` DÉTERMINISTE
-- (`garmin_activity_id × multiplicateur + index de montée` de la PREMIÈRE occurrence
-- rencontrée, voir `arc_climb_match.ASSUMPTIONS["segment_id"]`) — stable d'une
-- réindexation à l'autre SAUF si une occurrence encore plus ancienne du même segment est
-- découverte plus tard (l'id change alors légitimement, sans affecter les autres
-- segments) : un consommateur externe qui garde un id en cache doit donc rester tolérant
-- à un id devenu inconnu (`reason_code: "unknown_segment"`), jamais le supposer éternel.
-- `start_lat`/`start_lon`/`summit_lat`/`summit_lon`/`mid_lat`/`mid_lon` (mi-parcours, 2e
-- revue de code #49 — voir `arc_climb_match.ASSUMPTIONS["gps_matching"]`) : position de la
-- PREMIÈRE occurrence rencontrée (jamais mise à jour ensuite pour une occurrence
-- ULTÉRIEURE, un repère stable suffit à l'appariement futur — voir
-- `arc_climb_match.ClimbSegmentIndex`), sauf ADOPTION (une occurrence avec GPS fournit sa
-- position à un segment qui n'en avait pas encore, voir
-- `arc_climb_match.ASSUMPTIONS["fallback_matching"]`). `NULL` si aucune occurrence connue
-- n'a encore de GPS exploitable. USAGE INTERNE UNIQUEMENT pour les positions : jamais
-- exposées par l'API/le CLI (voir `arc_climb_match.ASSUMPTIONS["privacy"]`) — seuls
-- `id`/`location`/le profil/les agrégats (`occurrences`, `best_time_elapsed_s`) le sont.
CREATE TABLE climb_segment (
    id INTEGER PRIMARY KEY, location TEXT, gain_m REAL, distance_m REAL, avg_grade REAL,
    grade_class TEXT, start_lat REAL, start_lon REAL, summit_lat REAL, summit_lon REAL,
    mid_lat REAL, mid_lon REAL,
    first_seen_activity_id INTEGER, first_seen_date TEXT, occurrences INTEGER,
    best_time_elapsed_s REAL, best_activity_id INTEGER
);
-- Efficacité en descente par classe de pente (#47, `arc_descent.py`), id INTERNE
-- (`activity_id`, comme `activity_climb`/`hr_zone_time` — jamais `garmin_activity_id` :
-- recréée en entier à chaque `compute_metrics`, sans purge par fichier). `grade_class` :
-- voir `arc_descent.DESCENT_GRADE_CLASSES` (mirroir des classes ascendantes de #46).
-- `efficiency` : moyenne pondérée par le temps du ratio par échantillon vitesse GAP
-- / référence « plat » de LA SÉANCE — la référence est `activity.
-- descent_reference_gap_pace_s_km`/`descent_reference_source` ci-dessous, JAMAIS
-- l'allure GAP de toute la séance (`activity.gap_pace_s_km`, #44 : se contaminerait
-- avec l'effort des descentes elles-mêmes — voir `arc_descent.ASSUMPTIONS
-- ["reference"]`, BLOQUANT corrigé en revue de code). Voir
-- `arc_descent.ASSUMPTIONS["indicator"]` pour la lecture honnête de cet indicateur
-- (le modèle de pente sous-jacent, tiré de coureurs entraînés, est généreux en
-- descente : une valeur < 1 est fréquente). Une activité sans classe
-- qualifiante (durée/distance insuffisante par classe, référence indisponible, ou
-- hors famille course à pied/sans FIT) n'a simplement aucune ligne ici.
-- `mean_grade` (revue de code #47) : pente RÉELLEMENT rencontrée en moyenne sur la
-- classe (fraction signée), pas seulement son libellé — utile notamment sur les
-- deux paniers larges au-delà de -20 % (`arc_descent.ASSUMPTIONS["grade_classes"]`,
-- modèle de pente non monotone en descente).
CREATE TABLE activity_descent_class (
    activity_id INTEGER, grade_class TEXT, count INTEGER, duration_moving_s REAL, distance_m REAL,
    mean_speed_ms REAL, mean_pace_s_km REAL, mean_gap_speed_ms REAL, mean_grade REAL, efficiency REAL
);
CREATE INDEX activity_descent_class_activity ON activity_descent_class(activity_id);
-- Dépense énergétique modèle RE3 + marche (`arc_energy.py`), UNE ligne
-- par activité éligible (id INTERNE `activity_id`, comme `activity_descent_class`/
-- `activity_climb`/`hr_zone_time` ci-dessus — JAMAIS `garmin_activity_id` : la ligne est
-- recréée en entier à chaque `compute_metrics`, sans purge par fichier, un `activity_id`
-- change à chaque édition du Markdown, voir ASSUMPTIONS["hr_zones"]). Restreinte à la
-- famille course à pied (`arc_metrics.SPORT_FAMILY` = "run" : running/trail/hiking/
-- walking, le moteur gère la marche) AVEC des échantillons FIT ingérés — même garde que
-- GAP/#44, découplage/#45, VAM/#46, descente/#47 : une activité hors de cette famille ou
-- sans FIT n'a simplement AUCUNE ligne ici (jamais une ligne à `model_kcal: NULL` sans
-- raison pour ce cas-là — la raison se déduit alors de l'absence même de ligne, voir
-- `energy_report`/`activity_energy_report`). En revanche, une activité ÉLIGIBLE (famille
-- + FIT) dont le POIDS n'a pu être résolu obtient bien une ligne, `model_kcal` NULL avec
-- `reason`/`reason_code` explicites (`weight_kg`/`weight_source` NULL aussi) — jamais un
-- NULL muet ni une exception : voir `resolve_weight_kg_as_of`/ASSUMPTIONS["weight"].
-- `model_kcal`/`weight_kg`/`weight_source`/`counted_s`/`gap_s`/`elevation_missing` :
-- voir `arc_energy.energy_from_samples`. `walk_s`/`stopped_s`/`uphill_s`/`downhill_s`/
-- `flat_s` (+ leur kcal) : décomposition PAR CATÉGORIE de
-- `arc_energy.BREAKDOWN_CATEGORIES` (elle-même issue de `energy_from_samples`
-- ["breakdown"]) — jamais recalculée séparément ici.
CREATE TABLE activity_energy (
    activity_id INTEGER, model_id TEXT, model_kcal REAL, weight_kg REAL, weight_source TEXT,
    counted_s REAL, gap_s REAL, elevation_missing INTEGER,
    flat_s REAL, flat_kcal REAL, uphill_s REAL, uphill_kcal REAL, downhill_s REAL, downhill_kcal REAL,
    walk_s REAL, walk_kcal REAL, stopped_s REAL, stopped_kcal REAL,
    reason TEXT, reason_code TEXT
);
CREATE INDEX activity_energy_activity ON activity_energy(activity_id);
-- Modèle personnel pente -> allure (#58, `arc_slope_model.py`) — GLOBAL au workspace
-- (pas par activité, comme `climb_segment` ci-dessus) : recalculé INTÉGRALEMENT à chaque
-- `compute_metrics`, jamais de purge partielle. Une ligne par (`band`, panier de pente) —
-- voir `arc_slope_model.GRADE_BINS` pour les bornes/étiquettes. `source` : "personal"
-- (données de l'athlète suffisantes sur ce panier) ou "generic" (repli Kay sur la
-- référence plate personnelle, voir `arc_slope_model.ASSUMPTIONS['fallback']`).
-- `ci_low_speed_ms`/`ci_high_speed_ms` : repère de dispersion (IQR pondéré), PAS un
-- intervalle de confiance statistique au sens strict — voir ASSUMPTIONS['robust_stats'].
-- `run_share` : part du temps couru (vs marché/power-hiking) sur ce panier, `NULL` pour un
-- panier générique (aucune donnée réelle). `NULL` si aucun modèle n'a pu être ajusté pour
-- cette bande (voir `slope_model_meta.reason_code`) : pas de ligne du tout dans ce cas.
CREATE TABLE slope_model_bin (
    band TEXT, grade_lo REAL, grade_hi REAL, grade_mid REAL, label TEXT,
    speed_ms REAL, pace_s_km REAL, hr_bpm REAL, source TEXT,
    ci_low_speed_ms REAL, ci_high_speed_ms REAL,
    n_samples INTEGER, n_activities INTEGER, effective_time_s REAL, run_share REAL
);
CREATE INDEX slope_model_bin_band ON slope_model_bin(band);
-- Métadonnées de l'ajustement (#58), une ligne par bande (`arc_slope_model.BANDS`) même en
-- cas d'échec (`reason`/`reason_code` non NULL, `slope_model_bin` alors vide pour cette
-- bande) — jamais une absence totale de ligne qui laisserait croire à un oubli plutôt qu'à
-- une impossibilité documentée (profil sans zones FC, historique trop récent, etc.).
-- `selected_by_plan`/`selected_by_hr` (2ᵉ revue de code #58, should-fix) : nombre
-- d'activités RETENUES par méthode (`arc_slope_model.EASY_PLAN_INTENSITIES` en priorité,
-- repli FC sinon — voir `arc_slope_model.ASSUMPTIONS['population']`), jamais les exclues.
CREATE TABLE slope_model_meta (
    band TEXT PRIMARY KEY, months INTEGER, half_life_days REAL, as_of TEXT,
    n_activities INTEGER, flat_reference_speed_ms REAL, selected_by_plan INTEGER, selected_by_hr INTEGER,
    reason TEXT, reason_code TEXT
);
-- Inspections photo de chaussures (#135) : une ligne par `gear/AAAA-MM-JJ_<gear_id>_inspection.md`.
-- `wear_zones`/`gait_hints`/`photos` : JSON. `asymmetry_side` = côté le plus usé. Lu par
-- `gear_inspections()` (CLI `inspections`, `/api/summary.gear_inspections`) et `gear_career()`.
CREATE TABLE gear_inspection (
    source_path TEXT, date TEXT, gear_id TEXT, distance_m REAL, condition TEXT,
    asymmetry_level TEXT, asymmetry_side TEXT, wear_zones TEXT, gait_hints TEXT, photos TEXT,
    previous TEXT, scale_reference INTEGER, lug_depth_mm REAL, body_md TEXT
);
CREATE INDEX gear_inspection_gear ON gear_inspection(gear_id, date);
"""

# Tables alimentées par fichier (colonne `source_path`) : purgées à la réindexation d'un fichier.
PER_FILE_TABLES = (
    "athlete", "objective", "health_day", "weather_day", "week", "planned_session",
    "nutrition_day", "report", "course_eval", "race_plan", "aid_station", "gear", "equipment",
    "performance_index", "performance_index_warning", "decision", "decision_rule",
    "gear_inspection",
)


def open_db(workspace: Path, db: Optional[str] = None, memory: bool = False,
            rebuild: bool = False) -> sqlite3.Connection:
    path = None
    sqlite_header = False
    if memory:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        path = Path(db) if db else workspace / DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        if not db:
            # Le dossier s'ignore lui-même : même dans un workspace dont le .gitignore
            # n'a jamais été complété, `git add -A` (git_autocommit) n'embarque pas la base.
            marker = path.parent / ".gitignore"
            if not marker.exists():
                marker.write_text("# Index dérivé du tableau de bord : jetable, jamais versionné.\n*\n", encoding="utf-8")
        try:
            with path.open("rb") as handle:
                sqlite_header = handle.read(16) == b"SQLite format 3\x00"
        except OSError:
            sqlite_header = False
        # Le tableau de bord et la synchronisation peuvent indexer en même temps :
        # on attend le verrou plutôt que d'échouer.
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    current = None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = int(row[0]) if row else None
    except sqlite3.DatabaseError:
        current = None

    def reset_schema(connection: sqlite3.Connection) -> None:
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            connection.execute(f'DROP TABLE IF EXISTS "{name}"')
        connection.executescript(DDL)
        connection.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        connection.commit()

    # --rebuild vide les tables sur place au lieu de supprimer le fichier : un serveur
    # déjà ouvert sur la base garderait sinon une connexion vers un fichier disparu.
    if rebuild or current != SCHEMA_VERSION:
        try:
            # Base d'une autre version (ou vide) : elle est dérivée, on la recrée.
            reset_schema(conn)
        except sqlite3.DatabaseError as exc:
            corrupt = "malformed" in str(exc).lower() or "not a database" in str(exc).lower()
            # Jamais sur un fichier qui n'a pas été une base SQLite : un `--db` mal
            # orienté (ex. un Markdown) doit échouer, pas être remplacé. L'index par
            # défaut (.arc/coach.db) peut l'être même si son en-tête est abîmé.
            if memory or path is None or not corrupt or (db and not sqlite_header):
                raise
            # `.arc/coach.db` est un index entièrement dérivé des Markdown. Si
            # SQLite ne peut même plus lire son catalogue, le supprimer est la
            # seule réparation fiable ; les éventuels sidecars sont jetables aussi.
            conn.close()
            for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
                candidate.unlink(missing_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
            conn.row_factory = sqlite3.Row
            reset_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Découverte et lecture des fichiers
# ---------------------------------------------------------------------------


# `[^/.]+` (#55, revue de code) — jamais `[^/]+` : un `<slug>` avec un point
# (`..._decision_dotted.v2.md`) resterait indexable via le repli `block_kind`
# de `read_file` (le bloc ```arc fait foi quand le nom ne dit rien), mais son
# identifiant `/api/decision/<id>` (nom de fichier sans extension, JAMAIS de
# point accepté — voir `arc_serve.DECISION_ID_RE`) ne pourrait alors plus
# jamais désigner ce fichier : `Path(...).stem` ne retire que le DERNIER
# suffixe (`.md`), pas `.v2`. `validate_file` avertit explicitement quand un
# fichier `decision` ne suit pas ce format (slug sans point, directement sous
# `planning/`, jamais un sous-dossier — voir aussi `classify_source_path`).
_DECISION_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_decision_[^/.]+\.md$")


_GEAR_INSPECTION_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_([a-z0-9]+(?:-[a-z0-9]+)*)_inspection\.md$")


def classify(rel: str) -> Optional[str]:
    """Type attendu d'après le chemin (None : fichier hors contrat, sauf bloc ```arc)."""
    parts = rel.split("/")
    folder, name = parts[0], parts[-1]
    if folder == "activities" and L.filename_date(name) and L.sport_from_filename(name):
        # `2026-08-21_strides_analysis.md` est une analyse, pas une séance : seul un
        # type de sport connu après la date fait un fichier d'activité.
        return "activity"
    if folder == "medical" and name.endswith("_health.md"):
        return "health"
    if folder == "medical" and name.endswith("_meteo.md"):
        return "weather"
    if folder == "nutrition" and name.endswith("_nutrition.md"):
        return "nutrition"
    if folder == "rapports" and name.endswith(".md"):
        return "report"
    if folder == "gear" and name.endswith("_inspection.md") and L.filename_date(name):
        return "gear_inspection"
    if folder == "planning":
        if name == "Runner_Profile.md":
            return "athlete"
        if name == "active_objective.md":
            return "objective"
        if name.startswith("Semaine_"):
            return "week"
        if "_evaluation_parcours_" in name:
            return "course_eval"
        if _DECISION_FILENAME_RE.match(name):
            # Ancré (#100, revue de code) : un simple `"_decision_" in name`
            # classait à tort n'importe quel fichier `planning/` contenant ce
            # segment n'importe où (`journal_decision_generale.md`) — la
            # convention est stricte, `AAAA-MM-JJ_decision_<slug>.md`.
            return "decision"
    return None


def discover(workspace: Path) -> List[Path]:
    files = []
    for folder in DATA_DIRS:
        root = workspace / folder
        if root.is_dir():
            files.extend(p for p in sorted(root.rglob("*.md")) if p.is_file())
    return files


def expected_keys(kind: str, data: dict, conf: dict) -> List[str]:
    """Clés dont l'absence est une dette (au-delà des clés obligatoires du contrat)."""
    if kind == "activity":
        sport = data.get("sport")
        # Séance Strava (#164) : ni `garmin_activity_id` ni `splits` par km n'existent à la source
        # (AGENTS.md, « Backends MCP ») — jamais une dette. Les autres sources : inchangé.
        strava = bool(data.get("strava_activity_id"))
        keys = [] if strava else ["garmin_activity_id"]
        if sport not in ("strength", "rest", "home_trainer", "indoor_cycling", "elliptical"):
            keys.append("distance_m")
        if sport != "rest":
            keys.append("avg_hr_bpm")
        if sport in M.RUNNING_SPORTS and not strava:
            keys.append("splits")
        return keys
    if kind == "health":
        mode = data.get("morning_check") or conf["morning_check"]
        return {
            "full": ["sleep_total_s", "hrv_overnight_ms", "resting_hr_bpm", "readiness_score", "verdict"],
            "minimal": ["readiness_score", "verdict"],
        }.get(mode, [])
    if kind == "weather":
        return ["best_slot"]
    return []


def read_file(path: Path, rel: str, conf: dict) -> Tuple[Optional[str], dict, int, str, List[str]]:
    """Rend (kind, données, arc_version, parsed_ok, problèmes)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    kind = classify(rel)
    issues: List[str] = []

    if kind in ("athlete", "objective"):          # fichiers humains : puces du modèle
        data = L.parse_profile(text) if kind == "athlete" else L.parse_objective(text)
        data["body_md"] = text
        return kind, data, 0, "ok" if data else "partial", issues

    block_error = None
    try:
        block = C.extract_block(text)
    except C.ContractError as exc:
        block, block_error = None, str(exc)

    if block is not None:
        errors, warnings = C.validate(block)
        block_kind = block.get("kind")
        if block_kind in C.KINDS:
            if kind and block_kind != kind:
                issues.append(f"kind « {block_kind} » dans un fichier attendu « {kind} »")
            kind = block_kind
            if kind == "gear_inspection" and classify(rel) != "gear_inspection":
                issues.append("gear_inspection hors de `gear/AAAA-MM-JJ_<gear_id>_inspection.md` : non indexé")
        issues.extend(warnings)
        if not errors:
            data = dict(block)
            data["body_md"] = C.body_after_block(text)
            missing = [k for k in expected_keys(kind, data, conf) if data.get(k) is None]
            issues.extend(f"{k} : absent" for k in missing)
            return kind, data, 1, "ok", issues
        issues = errors + issues
        status = "invalid"
    else:
        if kind is None:
            return None, {}, 0, "no", []
        issues.append(block_error or "bloc ```arc absent")
        status = "partial"

    # Repli : lecture héritée.
    name = path.name
    if kind == "activity":
        data = L.legacy_activity(text, name, conf["sport"])
    elif kind == "health":
        data = L.legacy_health(text, name, conf["morning_check"])
    elif kind == "weather":
        data = L.legacy_weather(text, name)
    elif kind == "week":
        data = L.legacy_week(text, name, conf["sport"])
    elif kind == "nutrition":
        data = L.legacy_nutrition(text, name)
    elif kind == "report":
        data = L.legacy_report(text, name)
    elif kind == "course_eval":
        data = {"kind": "course_eval", "date": L.filename_date(name), "name": L.title_of(text) or name}
    else:
        data = {}
    data["body_md"] = text
    required = C.SCHEMA.get(kind, {}).get("required", {})
    missing = [k for k in list(required) + expected_keys(kind, data, conf) if data.get(k) in (None, [], "")]
    issues.extend(f"{k} : absent" for k in dict.fromkeys(missing))
    if kind == "activity":
        # « Aucune activité enregistrée ce jour » ne doit pas devenir une séance vide.
        usable = data.get("duration_s") is not None or data.get("distance_m") is not None
    else:
        usable = any(data.get(k) is not None for k in required if k != "date") or kind in ("report", "course_eval")
    if "date" in required and not data.get("date"):
        usable = False                      # `2026-04-11b_health.md` : sans date sûre, rien à tracer
        issues.append("date introuvable (nom de fichier non conforme)")
    if status == "partial" and not usable:
        status = "no"
    return kind, data, 0, status, issues


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------


def _j(value) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _insert(conn, table: str, row: dict) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values())).lastrowid


def _purge(conn, rel: str) -> None:
    for (activity_id,) in conn.execute("SELECT id FROM activity WHERE source_path = ?", (rel,)).fetchall():
        conn.execute("DELETE FROM activity_split WHERE activity_id = ?", (activity_id,))
    conn.execute("DELETE FROM activity WHERE source_path = ?", (rel,))
    for table in PER_FILE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE source_path = ?", (rel,))


def _data_json(data: dict) -> str:
    return _j({k: v for k, v in data.items() if k != "body_md"})


def store(conn, rel: str, kind: str, data: dict, arc_version: int) -> None:
    body = data.get("body_md")
    g = data.get
    if kind == "athlete":
        _insert(conn, "athlete", {
            "source_path": rel, "name": g("name"), "hr_max_bpm": g("hr_max_bpm"),
            "hr_rest_bpm": g("hr_rest_bpm"), "hr_threshold_bpm": g("hr_threshold_bpm"),
            "sex": g("sex"), "weight_kg": g("weight_kg"), "birth_year": g("birth_year"),
            "default_location": g("default_location"), "usual_slot": g("usual_slot"),
            "sleep_need_s": g("sleep_need_s"),
            "ht_trainer": g("ht_trainer"), "ht_bike": g("ht_bike"),
            "bike_mass_kg": g("bike_mass_kg"), "ftp_declared_w": g("ftp_declared_w"),
            "body_md": body,
        })
        for shoe in g("gear") or []:
            if not isinstance(shoe, dict) or not shoe.get("gear_id"):
                continue
            _insert(conn, "gear", {
                "source_path": rel, "gear_id": shoe["gear_id"], "name": shoe.get("name"),
                "start_date": shoe.get("start_date"), "threshold_m": shoe.get("threshold_m"),
                "is_default": int(bool(shoe.get("default"))), "retired": int(bool(shoe.get("retired"))),
                "collision_base": shoe.get("collision_base"),
                "start_m": shoe.get("start_m"), "usage": shoe.get("usage"),
                "garmin_uuid": shoe.get("garmin_uuid"), "ignored": int(bool(shoe.get("ignored"))),
            })
        for item in g("equipment") or []:
            if not isinstance(item, dict) or not item.get("gear_id"):
                continue
            _insert(conn, "equipment", {
                "source_path": rel, "gear_id": item["gear_id"], "name": item.get("name"),
                "category": item.get("category"), "start_date": item.get("start_date"),
                "maintenance_date": item.get("maintenance_date"), "retired": int(bool(item.get("retired"))),
                "kits": _j(item.get("kits")), "threshold_m": item.get("threshold_m"),
                "threshold_s": item.get("threshold_s"), "threshold_sessions": item.get("threshold_sessions"),
                "threshold_days": item.get("threshold_days"), "start_m": item.get("start_m"),
                "start_s": item.get("start_s"), "start_sessions": item.get("start_sessions"),
                "collision_base": item.get("collision_base"), "parse_warnings": _j(item.get("parse_warnings")),
            })
        for entry in g("performance_index") or []:
            if not isinstance(entry, dict) or not entry.get("date") or not entry.get("kind"):
                continue
            _insert(conn, "performance_index", {
                "source_path": rel, "date": entry["date"], "kind": entry["kind"],
                "category": entry.get("category"), "value": entry.get("value"),
                "ordinal": entry.get("ordinal", 0),
            })
        for warning_ordinal, message in enumerate(g("performance_index_warnings") or []):
            _insert(conn, "performance_index_warning", {
                "source_path": rel, "message": message, "ordinal": warning_ordinal,
            })
    elif kind == "objective":
        row = {k: g(k) for k in (
            "name", "race_date", "distance_m", "elevation_gain_m", "location", "goal", "target_time_s",
            "weekly_start_s", "weekly_start_m", "weekly_target_s", "weekly_target_m",
            "quality_per_week", "training_location")}
        _insert(conn, "objective", {"source_path": rel, **row, "body_md": body})
    elif kind == "activity":
        activity_id = _insert(conn, "activity", {
            "source_path": rel, "arc_version": arc_version, "date": g("date"), "sport": g("sport"),
            "name": g("name"), "location": g("location"), "garmin_activity_id": g("garmin_activity_id"),
            "intervals_activity_id": g("intervals_activity_id"),
            "strava_activity_id": g("strava_activity_id"),
            "start_time": g("start_time"), "distance_m": g("distance_m"), "duration_s": g("duration_s"),
            "moving_duration_s": g("moving_duration_s"), "elevation_gain_m": g("elevation_gain_m"),
            "elevation_loss_m": g("elevation_loss_m"), "avg_hr_bpm": g("avg_hr_bpm"),
            "max_hr_bpm": g("max_hr_bpm"), "recovery_hr_bpm": g("recovery_hr_bpm"),
            "avg_cadence_spm": g("avg_cadence_spm"), "calories_kcal": g("calories_kcal"),
            "calories_bmr_kcal": g("calories_bmr_kcal"),
            "te_aerobic": g("training_effect_aerobic"), "te_anaerobic": g("training_effect_anaerobic"),
            "rpe": g("rpe"), "missing_reason": _j(g("missing_reason")),
            "gear_id": g("gear_id"), "gear_source": g("gear_source"), "carbs_g": g("carbs_g"), "fluid_intake_ml": g("fluid_intake_ml"),
            "weight_pre_kg": g("weight_pre_kg"), "weight_post_kg": g("weight_post_kg"),
            "gear_ids": _j(g("gear_ids")),
            "avg_power_w": g("avg_power_w"), "max_power_w": g("max_power_w"),
            "normalized_power_w": g("normalized_power_w"),
            "body_md": body,
            "data_json": _data_json(data),
        })
        for split in C.split_rows(data):
            _insert(conn, "activity_split", {
                "activity_id": activity_id,
                **{col: split.get(col) for col in C.SPLIT_COLUMNS},
            })
    elif kind == "health":
        # `pain` (#57, liste d'objets) exclue comme `readiness_factors`/`missing_reason` :
        # `health_day` n'a pas de colonne dédiée pour un champ non-scalaire, il reste
        # accessible via `data_json` (voir `arc_guardrails.build_injury_risk_context`).
        cols = [k for k in C.SCHEMA["health"]["optional"]
                if k not in ("readiness_factors", "missing_reason", "pain")]
        _insert(conn, "health_day", {
            "source_path": rel, "arc_version": arc_version, "date": g("date"),
            "morning_check": g("morning_check"), **{k: g(k) for k in cols},
            "body_md": body, "data_json": _data_json(data),
        })
    elif kind == "weather":
        _insert(conn, "weather_day", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "location", "category", "best_slot", "slot_reason", "temp_min_c", "temp_max_c",
                "feels_like_c", "wind_kmh", "gust_kmh", "precip_mm", "chance_of_rain_pct", "uv_index")},
            "data_json": _data_json(data),
        })
    elif kind == "week":
        # #69 : `weeks` (liste) éclate un fichier multi-semaines en une ligne
        # `week` par semaine, toutes partageant ce `source_path` — la purge par
        # fichier (`_purge`, filtrée sur `source_path` seul) les retire donc
        # TOUTES d'un coup à la prochaine écriture, exactement comme pour une
        # semaine unique. Le format historique (pas de `weeks`) est traité comme
        # une liste d'une seule semaine — même code, aucun cas particulier.
        weeks = g("weeks")
        entries = weeks if isinstance(weeks, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ge = entry.get
            _insert(conn, "week", {
                "source_path": rel, "arc_version": arc_version, "week_start": ge("week_start"),
                "location": ge("location"), "phase": ge("phase"), "week_type": ge("week_type"),
                "target_duration_s": ge("target_duration_s"),
                "target_distance_m": ge("target_distance_m"), "target_elevation_m": ge("target_elevation_m"),
                "body_md": body,
            })
            for s in ge("sessions") or []:
                if not isinstance(s, dict):
                    continue
                _insert(conn, "planned_session", {
                    "source_path": rel, "week_start": ge("week_start"),
                    **{k: s.get(k) for k in (
                        "date", "sport", "title", "planned_duration_s", "planned_distance_m",
                        "planned_elevation_m", "intensity", "garmin_workout_id", "status",
                        "weather_category", "best_slot")},
                    "outdoor": None if s.get("outdoor") is None else int(bool(s["outdoor"])),
                    "virtual_route": _j(s.get("virtual_route")),
                })
    elif kind == "nutrition":
        _insert(conn, "nutrition_day", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "intake_kcal", "carbs_g", "protein_g", "fat_g", "hydration_ml",
                "burned_kcal", "weight_kg", "target_weight_kg")},
            "body_md": body,
        })
    elif kind == "report":
        _insert(conn, "report", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "report_type", "title", "period_start", "period_end", "location")},
            "body_md": body,
        })
    elif kind == "course_eval":
        _insert(conn, "course_eval", {
            "source_path": rel, "date": g("date"), "name": g("name"), "distance_m": g("distance_m"),
            "elevation_gain_m": g("elevation_gain_m"), "verdict": g("verdict"), "body_md": body,
            "data_json": _data_json(data),
        })
    elif kind == "race_plan":
        _insert(conn, "race_plan", {
            "source_path": rel, **{k: g(k) for k in (
                "date", "race_name", "race_date", "distance_m", "elevation_gain_m", "target_time_s")},
            "body_md": body, "data_json": _data_json(data),
        })
        for station in g("aid_stations") or []:
            if isinstance(station, dict):
                _insert(conn, "aid_station", {
                    "source_path": rel, "km": station.get("km"), "name": station.get("name"),
                    "cutoff": station.get("cutoff"), "services": _j(station.get("services")),
                })
    elif kind == "gear_inspection" and classify(rel) == "gear_inspection":
        # Jamais un bloc `gear_inspection` égaré hors de `gear/` (ex. `planning/sneaky.md`) : ses
        # photos deviendraient « citées » pour la route d'images. `read_file` le signale.
        asym = g("asymmetry") if isinstance(g("asymmetry"), dict) else {}
        _insert(conn, "gear_inspection", {
            "source_path": rel, "date": g("date"), "gear_id": g("gear_id"), "distance_m": g("distance_m"),
            "condition": g("condition"), "asymmetry_level": asym.get("level"),
            "asymmetry_side": asym.get("side"), "wear_zones": _j(g("wear_zones")),
            "gait_hints": _j(g("gait_hints")), "photos": _j(g("photos")), "previous": g("previous"),
            "scale_reference": None if g("scale_reference") is None else int(bool(g("scale_reference"))),
            "lug_depth_mm": g("lug_depth_mm"), "body_md": body,
        })
    elif kind == "decision":
        _insert(conn, "decision", {
            "source_path": rel, "arc_version": arc_version, "date": g("date"),
            "created_at": g("created_at"), "created_at_utc": C.decision_created_at_utc(g("created_at")),
            "trigger": g("trigger"), "summary": g("summary"),
            "outcome": g("outcome"), "garmin_workout_id": g("garmin_workout_id"),
            "supersedes": g("supersedes"),
            "inputs_json": _j(g("inputs")), "rule_ids_json": _j(g("rule_ids")),
            "sources_json": _j(g("sources")), "before_json": _j(g("before")),
            "after_json": _j(g("after")), "session_ref_json": _j(g("session_ref")),
            "body_md": body, "data_json": _data_json(data),
        })
        for rule_id in g("rule_ids") or []:
            if isinstance(rule_id, str):
                _insert(conn, "decision_rule", {"source_path": rel, "rule_id": rule_id})


def planned_intensity_for(conn, date: Optional[str], sport: Optional[str]) -> Optional[str]:
    """`planned_session.intensity` (#58, 2ᵉ revue de code, should-fix) pour la
    séance PLANIFIÉE de même date et même FAMILLE de sport qu'une activité
    réelle (`M.sport_family`, jamais une comparaison de sport exacte — un plan
    « trail » et une activité loguée « running » le même jour restent
    apparentés) — `None` si `date` manque ou si aucune séance planifiée
    correspondante n'existe (l'appelant retombe alors sur le repli FC, voir
    `arc_slope_model._endurance_selection`). Plusieurs séances planifiées la
    même date/famille (rare, ex. double séance) : la PREMIÈRE trouvée (ordre
    SQL non garanti au-delà de ça) — jamais un plantage, jamais un mélange des
    deux intensités."""
    if not date:
        return None
    family = M.sport_family(sport)
    for row in conn.execute(
            "SELECT sport, intensity FROM planned_session "
            "WHERE date = ? AND intensity IS NOT NULL AND shadowed = 0",
            (date,)).fetchall():
        if M.sport_family(row["sport"]) == family:
            return row["intensity"]
    return None


def _round1(value: Optional[float]) -> Optional[float]:
    """`round(value, 1)`, `None` si `value` est `None` — même précision que les
    autres KPI dérivés stockés (`hr_zone_time.seconds`, `round(seconds, 1)`) pour
    `activity_energy` (dépense énergétique modèle) : kcal/secondes à 1 décimale, jamais la
    précision flottante brute du calcul dans la base ni dans le JSON du CLI."""
    return None if value is None else round(value, 1)


def _plausible_weight_kg(value: Optional[float]) -> Optional[float]:
    """`value` si dans `arc_contract.BODY_WEIGHT_KG_PLAUSIBLE` (30-200 kg, la même
    plage que la validation du contrat pour `weight_kg`/`weight_pre_kg`/
    `weight_post_kg`), `None` sinon — jamais un poids aberrant (0 kg, une faute de
    frappe à 3 chiffres en trop, un export en livres non converti) utilisé comme
    s'il était plausible (revue de code) : une valeur hors plage est traitée
    EXACTEMENT comme une valeur absente, l'appelant (`resolve_weight_kg_as_of`)
    retombe alors sur la source suivante, jamais sur `weight_kg=0` avec une raison
    « aucun poids connu » qui serait un mensonge (une valeur A bien été trouvée,
    elle est seulement jugée implausible)."""
    if value is None:
        return None
    lo, hi = C.BODY_WEIGHT_KG_PLAUSIBLE
    return value if lo <= value <= hi else None


def resolve_weight_kg_as_of(conn, day: Optional[str], athlete: dict) -> Tuple[Optional[float], Optional[str]]:
    """Poids (kg) à utiliser pour la dépense énergétique modèle d'une
    séance datée `day` — voir la section « `energy` » du docstring du module pour le
    contexte d'ensemble. Résolution, PAR ORDRE DE PRIORITÉ :

    1. La DERNIÈRE pesée PLAUSIBLE connue (`health_day.weight_kg` OU
       `nutrition_day.weight_kg`, filtrées par `_plausible_weight_kg` —
       `arc_contract.BODY_WEIGHT_KG_PLAUSIBLE`, 30-200 kg, revue de code) À LA DATE
       DE LA SÉANCE OU AVANT — jamais une pesée future, qui supposerait un poids que
       l'athlète n'avait pas encore le jour de l'effort. Les deux sources sont
       interrogées séparément (dernière date <= `day` avec un poids PLAUSIBLE dans
       chacune — une pesée aberrante à cette date-là est ignorée, la requête
       retombe sur la pesée plausible ANTÉRIEURE de la même source, jamais sur la
       source concurrente à tort) puis comparées : la source dont la date est la
       PLUS RÉCENTE gagne (la vraie « dernière valeur connue ») ; à date égale,
       `health_day` gagne TOUJOURS (même précédence que `arc_metrics.
       merge_weight_kg` — la pesée de santé est celle du bilan matinal,
       `nutrition_day.weight_kg` n'a aucune garantie d'horaire). Un doublon DANS
       une même source à la date gagnante (deux fichiers santé, ou deux fichiers
       nutrition, pour le même jour) : `source_path` le plus grand par ordre
       alphabétique gagne (même règle que `arc_serve.py`, `ORDER BY date DESC,
       source_path DESC`).
    2. À défaut (aucune pesée PLAUSIBLE connue à cette date ou avant, dans AUCUNE
       des deux sources) : `athlete.weight_kg` (`planning/Runner_Profile.md`), SI
       ELLE AUSSI plausible — un profil mal rempli (0, ou en livres non converties,
       voir `arc_legacy.parse_athlete`) ne doit pas fausser silencieusement TOUTES
       les séances faute de pesée santé/nutrition.
    3. À défaut de tout : `(None, None)` — jamais un poids inventé (voir
       `arc_energy.ASSUMPTIONS["no_exception"]`, qui rend alors `None` sans
       exception), et jamais `weight_kg=0` avec la raison « aucun poids connu » —
       une valeur À ÉTÉ trouvée mais jugée implausible, `reason_code="no_weight"`
       le couvre identiquement (la CLI ne distingue pas « rien trouvé » de « trouvé
       mais rejeté », les deux se résolvent en `(None, None)` ici).

    `weight_source` vaut `"health_day"`, `"nutrition_day"` ou `"profile"`, pour que la
    CLI (`arc_index.py energy`) puisse toujours dire QUELLE source a fourni le poids
    utilisé, jamais une valeur muette. `day` absent (ne devrait pas arriver, `date` est
    obligatoire au contrat `activity`) : repli direct sur le profil, une recherche « à
    cette date ou avant » n'ayant pas de sens sans date."""
    lo, hi = C.BODY_WEIGHT_KG_PLAUSIBLE
    if not day:
        profile_weight = _plausible_weight_kg(athlete.get("weight_kg"))
        return (profile_weight, "profile") if profile_weight else (None, None)
    health_row = conn.execute(
        "SELECT date, weight_kg FROM health_day WHERE date <= ? AND weight_kg IS NOT NULL "
        "AND weight_kg BETWEEN ? AND ? ORDER BY date DESC, source_path DESC LIMIT 1", (day, lo, hi)).fetchone()
    nutrition_row = conn.execute(
        "SELECT date, weight_kg FROM nutrition_day WHERE date <= ? AND weight_kg IS NOT NULL "
        "AND weight_kg BETWEEN ? AND ? ORDER BY date DESC, source_path DESC LIMIT 1", (day, lo, hi)).fetchone()
    health_date = health_row["date"] if health_row else None
    nutrition_date = nutrition_row["date"] if nutrition_row else None
    if health_date is not None and (nutrition_date is None or health_date >= nutrition_date):
        return health_row["weight_kg"], "health_day"
    if nutrition_date is not None:
        return nutrition_row["weight_kg"], "nutrition_day"
    profile_weight = _plausible_weight_kg(athlete.get("weight_kg"))
    return (profile_weight, "profile") if profile_weight else (None, None)


class MetricsCache:
    """Cache EN MÉMOIRE des calculs dérivés des échantillons FIT, par activité.

    Utilisé par le tableau de bord (`arc_serve.Store`, processus longue durée) : sans
    lui, chaque réindexation recalculait zones, GAP, découplage, montées, descente,
    durabilité, modèle pente et dépense de TOUTES les séances à échantillons (~5 s
    pour ~100 séances), même quand un seul fichier santé avait changé.

    La clé est un condensé de TOUTES les entrées du calcul (agrégat du contenu des
    échantillons, splits, bornes FC, seuils, intensité planifiée, poids…) : une entrée
    modifiée donne une autre clé, jamais une valeur périmée. Jamais persisté, jamais
    partagé entre processus ; les entrées non utilisées lors d'un passage sont
    oubliées à la fin de celui-ci (`prune`), la taille reste bornée par le nombre de
    séances. Les CLI et les tests n'en passent pas : recalcul intégral, comme avant.
    """

    def __init__(self):
        self._entries: Dict[str, dict] = {}
        self._used: set = set()
        self.hits = 0
        self.misses = 0

    def begin(self) -> None:
        self._used = set()
        self.hits = self.misses = 0

    def get(self, key: str) -> Optional[dict]:
        value = self._entries.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
            self._used.add(key)
        return value

    def put(self, key: str, value: dict) -> None:
        self._entries[key] = value
        self._used.add(key)

    def prune(self) -> None:
        self._entries = {k: v for k, v in self._entries.items() if k in self._used}

    def clear(self) -> None:
        self._entries.clear()
        self._used = set()

    def __len__(self) -> int:
        return len(self._entries)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode("utf-8")).hexdigest()


def _sample_stats(conn) -> Dict[int, list]:
    """Empreinte du CONTENU des échantillons de chaque séance, en une requête : nombre de
    lignes, de valeurs non nulles et sommes par colonne. Calculée sur `activity_sample`
    lui-même (pas sur le sha de `sample_file`) : une réingestion qui normaliserait
    autrement le même fichier (sport connu entre-temps) change donc la clé."""
    stats = {}
    # Clé = identifiant externe (entier Garmin ou chaîne Intervals.icu, #68 — jamais en
    # collision, voir `arc_samples.parse_activity_ref`), comme `activity_ref(act)`.
    for col in REF_COLUMNS:
        for row in conn.execute(
            f"SELECT {col}, COUNT(*), TOTAL(t_s), MIN(t_s), MAX(t_s), "
            "COUNT(distance_m), TOTAL(distance_m), COUNT(altitude_m), TOTAL(altitude_m), "
            "COUNT(hr_bpm), TOTAL(hr_bpm), COUNT(speed_ms), TOTAL(speed_ms), "
            "COUNT(cadence_spm), TOTAL(cadence_spm), COUNT(lat), TOTAL(lat), TOTAL(lon), TOTAL(covered_s) "
            f"FROM activity_sample WHERE {col} IS NOT NULL GROUP BY {col}"
        ).fetchall():
            stats[row[0]] = [repr(v) for v in tuple(row)[1:]]
    return stats


def _sample_derived_metrics(act_samples: List[dict], split_rows: List[dict], zone_bounds, seiler_thresholds,
                            conf: dict, slope_planned_intensity: Optional[str]) -> dict:
    """Calculs PURS dérivés des échantillons d'UNE séance (aucune écriture en base,
    aucune dépendance aux autres séances) — mis en cache par `MetricsCache` ; les
    écritures et l'appariement de montées entre séances (#49) restent dans
    `compute_metrics`."""
    out: dict = {"zone_seconds": None, "bucket_seconds": None, "gap_by_km": None}
    if zone_bounds:
        bounds, _method = zone_bounds
        out["zone_seconds"] = M.time_in_zone_seconds(act_samples, bounds, S.DEFAULT_RESOLUTION_S)
    if seiler_thresholds:
        out["bucket_seconds"] = M.time_in_polarisation_seconds(act_samples, seiler_thresholds, S.DEFAULT_RESOLUTION_S)
    slope_easy_hr_bpm, slope_moderate_hr_bpm = seiler_thresholds if seiler_thresholds else (None, None)
    # GAP (#44, allure ajustée à la pente) : pente + vitesse GAP calculées une
    # seule fois par échantillon (`gap_sample_series`), réutilisées pour
    # l'allure globale ET par split — jamais recalculées deux fois pour la
    # même activité (voir `arc_gap.activity_gap_pace_from_series`).
    gap_series = G.gap_sample_series(act_samples)
    # Modèle personnel pente -> allure (#58) : résumé PAR PANIER de CETTE
    # activité pour chaque bande (`arc_slope_model.BANDS`), à partir de
    # `gap_series` déjà calculée ci-dessus (grade + vitesse, jamais un second
    # calcul de pente). `slope_planned_intensity` (2ᵉ revue de code #58,
    # should-fix) prime sur la FC pour la bande « endurance » — résolue même
    # sans seuils FC (`slope_easy_hr_bpm` peut être `None`, un plan seul suffit
    # à classer l'activité, voir `arc_slope_model._endurance_selection`).
    # TAMPONNÉ (revue de code #58, nit) plutôt qu'ajouté directement à
    # `slope_activities` : si un calcul PLUS LOIN échoue, cette activité doit être
    # entièrement rejetée — `compute_metrics` ne le verse qu'une fois TOUS les
    # calculs et écritures de l'activité réussis.
    slope_bins: Dict[str, tuple] = {}
    for band in SL.BANDS:
        easy_hr = slope_easy_hr_bpm if band == "endurance" else None
        moderate_hr = slope_moderate_hr_bpm if band == "endurance" else None
        planned = slope_planned_intensity if band == "endurance" else None
        bin_summary, method = SL.activity_bin_summaries_and_selection(
            gap_series, band=band, easy_hr_bpm=easy_hr, moderate_hr_bpm=moderate_hr,
            planned_intensity=planned, resolution_s=S.DEFAULT_RESOLUTION_S)
        if bin_summary:
            slope_bins[band] = (bin_summary, method)
    out["slope_bins"] = slope_bins
    out["gap_pace"] = G.activity_gap_pace_from_series(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
    if split_rows:
        out["gap_by_km"] = G.split_gap_paces_from_series(gap_series, split_rows, resolution_s=S.DEFAULT_RESOLUTION_S)
    # Découplage aérobie (#45, Pa:HR) et facteur d'efficacité : réutilise
    # `gap_series` déjà calculée ci-dessus via `decoupling_report_from_series`
    # (jamais un second calcul de pente/GAP pour la même activité) — le sport
    # est déjà restreint à la famille course à pied par l'appelant.
    out["decoupling"] = DC.decoupling_report_from_series(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
    # VAM sur les montées détectées (#46) : détection PURE sur les échantillons
    # bruts (t_s/distance_m/altitude_m/speed_ms), indépendante du GAP/de la pente
    # fenêtrée calculée ci-dessus pour le GAP (`arc_climb.detect_climbs` a son
    # propre lissage/segmentation, voir `arc_climb.ASSUMPTIONS`). Seuils de
    # détection configurables par le workspace (`[metrics].climb_min_gain_m`/
    # `climb_min_grade_pct`, critère d'acceptation de #46 : « montée minimale
    # configurable »), résolus une fois pour toutes dans `conf` par `settings()`.
    climb = VC.detect_climbs(act_samples, min_gain_m=conf["climb_min_gain_m"],
                             min_avg_grade=conf["climb_min_grade"])
    # Extrémités GPS + dérive FC par montée (#49) : propres à la séance, donc ici ;
    # l'appariement entre séances reste dans `compute_metrics`.
    out["climbs"] = [(c, VM.climb_endpoints(act_samples, c) or {}, VM.hr_drift_bpm_per_100m(act_samples, c))
                     for c in climb]
    out["vam_windows"] = VC.best_vam_windows(act_samples, climb)
    out["best_climb_vam"] = max(
        (c["vam_elapsed_m_h"] for c in climb if c["vam_elapsed_m_h"] is not None), default=None)
    # Efficacité en descente par classe de pente (#47) : réutilise `gap_series`
    # (pente + vitesse GAP par échantillon, jamais un second calcul) — la
    # référence « plat » de CETTE séance N'EST PLUS l'allure GAP de la séance
    # entière (`gap_pace`, ci-dessus, restée réservée à #44) : voir
    # `arc_descent.ASSUMPTIONS["reference"]` (BLOQUANT, revue de code) — l'allure
    # GAP globale se contamine avec l'effort des descentes à mesurer elles-mêmes,
    # faisant varier l'efficacité d'une même descente selon le reste du parcours.
    reference_speed, reference_source = DS.reference_gap_speed_ms(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
    out["descent_reference_speed_ms"], out["descent_reference_source"] = reference_speed, reference_source
    # Sans référence, aucune classe n'est stockée (voir `arc_descent.descent_report`,
    # même discipline) — jamais une ligne à `efficiency: NULL` qui laisserait croire
    # à un calcul partiel plutôt qu'à une absence totale de résultat.
    out["descent_classes"] = (DS.descent_speed_by_grade_class(
        gap_series, reference_gap_speed_ms=reference_speed,
        resolution_s=S.DEFAULT_RESOLUTION_S) if reference_speed is not None else {})
    # Durabilité sur les sorties longues (#48) : réutilise `gap_series`. Aucun seuil
    # de durée n'est appliqué ICI : c'est `arc_durability.durability_report_from_series`
    # elle-même qui rend `eligible: False` avec une `reason`/`reason_code` explicites
    # sous `arc_metrics.LONG_RUN_MIN_DURATION_S`.
    out["durability"] = DU.durability_report_from_series(gap_series, resolution_s=S.DEFAULT_RESOLUTION_S)
    return out


def compute_metrics(conn, conf: dict, today: Optional[str] = None,
                    metrics_cache: Optional[MetricsCache] = None) -> None:
    """Charge par séance, VO2max par séance, temps en zone FC + polarisation, puis la
    série quotidienne matérialisée. `metrics_cache` (tableau de bord) : voir
    `MetricsCache`."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete) if athlete else {}
    zone_bounds = M.hr_zone_bounds(athlete, conf.get("hr_zones"))
    seiler_thresholds = M.seiler_bounds(athlete, zone_bounds[1]) if zone_bounds else None
    loads: Dict[str, float] = {}
    estimates = []
    # Tri par date, avec des DÉPARTAGEURS déterministes (#49, revue de code, BLOQUANT) :
    # `date` seule ne distingue pas deux activités du même jour, ce qui rendrait l'ordre de
    # traitement chronologique (`climb_registry`/`segment_history`, voir plus bas) dépendant
    # d'un ordre SQL non garanti d'une exécution à l'autre — deux séances au même
    # `garmin_activity_id`/lieu le même jour pourraient alors se voir apparier dans un ordre
    # instable, changeant occasionnellement laquelle est « la première » (`vs_previous_pct`
    # calculé dans le mauvais sens). `start_time` (horodatage complet) départage d'abord,
    # `garmin_activity_id` ensuite (stable, jamais réattribué), `id` en tout dernier recours
    # (toujours unique) pour un ordre totalement déterministe.
    rows = conn.execute("SELECT * FROM activity ORDER BY date, start_time, garmin_activity_id, id").fetchall()
    # Tables dérivées intégralement recalculées à chaque passage (pas de purge par
    # fichier comme `PER_FILE_TABLES`, `activity_id` change à chaque édition du
    # Markdown — voir ASSUMPTIONS["hr_zones"]) : un changement de profil (FC max/
    # repos/seuil) ou de `[athlete].hr_zones` est donc répercuté sans étape à part,
    # incrémental ou `--rebuild`.
    conn.execute("DELETE FROM hr_zone_time")
    conn.execute("DELETE FROM hr_polarisation_time")
    conn.execute("DELETE FROM activity_climb")
    conn.execute("DELETE FROM activity_descent_class")
    conn.execute("DELETE FROM activity_energy")
    conn.execute("DELETE FROM climb_segment")
    conn.execute("DELETE FROM slope_model_bin")
    conn.execute("DELETE FROM slope_model_meta")
    # Modèle personnel pente -> allure (#58) : `gap_series` de CHAQUE activité course à pied
    # est réduite à un résumé PAR PANIER (`arc_slope_model.activity_bin_summaries_and_selection`)
    # au fil du même passage — jamais un second parcours des activités, voir
    # `arc_slope_model.ASSUMPTIONS["aggregation_cost"]`. Seuils FC (#43) résolus une seule
    # fois, hors boucle, pour le repli FC de la bande « endurance » (2ᵉ revue de code #58,
    # should-fix : seulement un REPLI désormais, une séance planifiée « recovery »/« endurance »
    # prime — voir `slope_planned_intensity`).
    slope_easy_hr_bpm = slope_moderate_hr_bpm = None
    if seiler_thresholds:
        slope_easy_hr_bpm, slope_moderate_hr_bpm = seiler_thresholds
    slope_activities: Dict[str, list] = {band: [] for band in SL.BANDS}
    # Identité de montée entre séances (#49, `arc_climb_match.py`) : registre reconstruit
    # INTÉGRALEMENT à chaque passage, comme les autres tables ci-dessus — `rows` est déjà
    # trié par date croissante (`ORDER BY date`), donc traiter les activités DANS CET ORDRE
    # suffit à obtenir une histoire chronologique par segment sans tri supplémentaire.
    # `climb_registry` reste en mémoire pour toute la durée de cette fonction (jamais
    # persisté tel quel) ; `segment_history` porte, PAR id de segment interne au registre,
    # les occurrences déjà vues (temps écoulé, activité) pour calculer `vs_previous_pct`/
    # `vs_best_pct` de l'occurrence SUIVANTE avant de s'y ajouter elle-même.
    climb_registry = VM.ClimbSegmentIndex()
    segment_history: Dict[int, dict] = {}
    sample_stats: Dict[int, list] = {}
    if metrics_cache is not None:
        metrics_cache.begin()
        sample_stats = _sample_stats(conn)
    for row in rows:
        act = dict(row)
        load, source = M.session_load(act, athlete)
        vo2 = M.vo2max_effective(act, athlete)
        sweat_rate = M.sweat_rate_l_h(act)
        conn.execute("UPDATE activity SET load = ?, load_source = ?, vo2max_est = ?, sweat_rate_l_h = ? WHERE id = ?",
                     (round(load, 2), source, vo2, sweat_rate, act["id"]))
        if act.get("date"):
            loads[act["date"]] = loads.get(act["date"], 0.0) + load
            if vo2 is not None:
                estimates.append((act["date"], vo2, act.get("duration_s") or 0))
        # Restreint aux sports « course à pied » (running/trail/randonnée/marche) :
        # le renforcement (effort anaérobie/technique) et le vélo (LTHR différente,
        # non renseignée séparément au profil) fausseraient temps en zone et
        # polarisation — voir ASSUMPTIONS["hr_zones"], revue de code #43 point 5.
        sample_ref = activity_ref(act)
        if sample_ref is not None and M.sport_family(act.get("sport")) == "run":
            # Cache par activité (tableau de bord, `metrics_cache`) : les échantillons ne
            # sont chargés que si l'un des deux calculs ci-dessous n'est pas déjà en cache
            # pour EXACTEMENT les mêmes entrées. Sans cache (CLI, tests), chargement
            # immédiat, comme avant.
            sample_stat = sample_stats.get(sample_ref) if metrics_cache is not None else None
            act_samples = samples(conn, act["id"]) if metrics_cache is None else None
            if metrics_cache is None:
                has_samples = bool(act_samples)
            else:
                # Agrégat SQL non vide ⇔ `samples()` non vide (même table, même clé).
                has_samples = sample_stat is not None
            if has_samples:
                # Défense en profondeur (revue de code #46, 3e passe, BLOQUANT) : un bug
                # inattendu dans UN des calculs dérivés des échantillons (zones, GAP,
                # découplage, VAM) — même déjà couvert par ses propres tests — ne doit
                # JAMAIS faire échouer `index_workspace` pour TOUTES les activités : le
                # tableau de bord et `/garmin-daily-sync` en dépendent à chaque
                # rafraîchissement. Une exception ici est donc rattrapée, journalisée sur
                # stderr avec l'id de l'activité (jamais silencieuse), toute ligne
                # partiellement insérée pour CETTE activité dans les tables dérivées est
                # purgée, et ses champs dérivés sont explicitement remis à NULL avec une
                # raison explicite — l'indexation continue avec l'activité suivante,
                # jamais un plantage global pour une seule séance à échantillons
                # malformés ou un cas limite non anticipé par un détecteur.
                #
                # `ARC_STRICT_METRICS=1` (revue de code #46, 4e passe) désactive ce
                # rattrapage et relève l'exception telle quelle : les suites de tests
                # (`tests/run_tests.py`, donc la CI) tournent avec cette variable pour
                # qu'un VRAI bug de programmation dans un des calculs dérivés fasse
                # échouer le test qui l'a déclenché plutôt que de disparaître,
                # silencieusement rattrapé, dans un `NULL` que rien ne signale comme une
                # anomalie — le rattrapage silencieux n'est un comportement voulu qu'en
                # PRODUCTION (workspace réel de l'athlète, `/garmin-daily-sync`), jamais
                # pendant le développement. Une erreur SQLite (verrou, base corrompue)
                # n'est, elle, JAMAIS rattrapée ici, `ARC_STRICT_METRICS` ou pas : un
                # problème d'infrastructure de la base doit toujours remonter bruyamment,
                # ce n'est pas ce que cette défense en profondeur vise à absorber.
                #
                # `registry_mark`/`history_marks` (#49, revue de code, BLOQUANT) : point de
                # reprise du registre de montées AVANT tout appariement de CETTE activité —
                # si le `except Exception` ci-dessous doit rattraper un échec survenu APRÈS
                # que cette activité a déjà été appariée/enregistrée dans `climb_registry`/
                # `segment_history`, ces mutations en mémoire sont défaites pour cette seule
                # activité (voir `ClimbSegmentIndex.rollback`) — sans ce mécanisme, une
                # activité en échec laissait une occurrence FANTÔME dans `segment_history`,
                # faussant `vs_previous_pct`/`vs_best_pct` (et `climb_segment.occurrences`)
                # d'une activité SUIVANTE qui, elle, réussit (bug réel : l'activité en échec
                # n'a AUCUNE ligne `activity_climb`, jamais purgée par le nettoyage SQL
                # ci-dessous, mais son occurrence restait comptée dans l'historique en
                # mémoire du segment).
                registry_mark = climb_registry.mark()
                history_marks: Dict[int, Optional[int]] = {}
                try:
                    slope_planned_intensity = planned_intensity_for(conn, act.get("date"), act.get("sport"))
                    split_rows = [dict(r) for r in conn.execute(
                        "SELECT km, distance_m FROM activity_split WHERE activity_id = ?", (act["id"],)).fetchall()]
                    derived = cache_key = None
                    if metrics_cache is not None:
                        # Clé = TOUTES les entrées de `_sample_derived_metrics` : contenu des
                        # échantillons, splits, bornes FC, seuils de montée, intensité planifiée.
                        cache_key = "samples:" + _digest(
                            [sample_stat, act.get("sport"), split_rows, zone_bounds, seiler_thresholds,
                             conf["climb_min_gain_m"], conf["climb_min_grade"], slope_planned_intensity])
                        derived = metrics_cache.get(cache_key)
                    if derived is None:
                        if act_samples is None:
                            act_samples = samples(conn, act["id"])
                        derived = _sample_derived_metrics(act_samples, split_rows, zone_bounds, seiler_thresholds,
                                                          conf, slope_planned_intensity)
                        if cache_key is not None:
                            metrics_cache.put(cache_key, derived)
                    if derived["zone_seconds"] is not None:
                        conn.executemany(
                            "INSERT INTO hr_zone_time (activity_id, zone, seconds) VALUES (?, ?, ?)",
                            [(act["id"], zone, round(seconds, 1)) for zone, seconds in derived["zone_seconds"].items()],
                        )
                    if derived["bucket_seconds"] is not None:
                        conn.executemany(
                            "INSERT INTO hr_polarisation_time (activity_id, bucket, seconds) VALUES (?, ?, ?)",
                            [(act["id"], bucket, round(seconds, 1))
                             for bucket, seconds in derived["bucket_seconds"].items()],
                        )
                    gap_pace = derived["gap_pace"]
                    conn.execute("UPDATE activity SET gap_pace_s_km = ? WHERE id = ?",
                                 (round(gap_pace, 2) if gap_pace is not None else None, act["id"]))
                    if derived["gap_by_km"] is not None:
                        conn.executemany(
                            "UPDATE activity_split SET gap_pace_s_km = ? WHERE activity_id = ? AND km = ?",
                            [(round(v, 2) if v is not None else None, act["id"], km)
                             for km, v in derived["gap_by_km"].items()],
                        )
                    report = derived["decoupling"]
                    conn.execute(
                        "UPDATE activity SET decoupling_pct = ?, ef_whole = ?, decoupling_reason = ? WHERE id = ?",
                        (report["decoupling_pct"], report["ef_whole"], report["reason"], act["id"]),
                    )
                    if derived["climbs"]:
                        # Identité de montée entre séances (#49) : pour CHAQUE montée détectée
                        # de CETTE activité, apparier (ou enregistrer comme nouveau segment),
                        # calculer la dérive FC et la progression vs occurrence(s) antérieure(s)
                        # — voir `arc_climb_match.py` pour l'algorithme complet et ses limites
                        # assumées. L'appariement dépend des activités PRÉCÉDENTES : il reste
                        # donc ici, jamais dans le cache par activité.
                        climb_rows = []
                        for c, endpoints, hr in derived["climbs"]:
                            candidate = {
                                "start_lat": endpoints.get("start_lat"), "start_lon": endpoints.get("start_lon"),
                                "end_lat": endpoints.get("end_lat"), "end_lon": endpoints.get("end_lon"),
                                # Mi-parcours (2e revue de code #49) : voir
                                # `arc_climb_match.ASSUMPTIONS["gps_matching"]`.
                                "mid_lat": endpoints.get("mid_lat"), "mid_lon": endpoints.get("mid_lon"),
                                "gain_m": c["gain_m"], "distance_m": c["distance_m"],
                                "avg_grade": c["avg_grade"], "grade_class": c["grade_class"],
                                "location": act.get("location"),
                                # Identifiant déterministe (#49, ASSUMPTIONS["segment_id"]) :
                                # requis par `ClimbSegmentIndex.add` si aucun appariement.
                                "segment_seed": VM.segment_seed(sample_ref), "climb_idx": c["index"],
                            }
                            segment = climb_registry.match(candidate)
                            if segment is None:
                                segment = climb_registry.add(candidate)
                            segment_id = segment["id"]
                            # Point de reprise PAR SEGMENT (une seule fois par segment touché
                            # par CETTE activité, voir `registry_mark` ci-dessus) : `None`
                            # signifie « ce segment n'existait pas avant cette activité »
                            # (rollback = le supprimer entièrement), un entier signifie
                            # « il avait déjà N occurrences » (rollback = tronquer à N).
                            if segment_id not in history_marks:
                                history_marks[segment_id] = (
                                    len(segment_history[segment_id]["occurrences"])
                                    if segment_id in segment_history else None)
                            history = segment_history.setdefault(
                                segment_id, {"occurrences": [], "first_activity_id": act["id"],
                                             "first_date": act.get("date")})
                            prev_times = [o["time_elapsed_s"] for o in history["occurrences"]
                                          if o["time_elapsed_s"] is not None]
                            vs_previous = (VM.progression_pct(prev_times[-1], c["duration_elapsed_s"])
                                           if prev_times else None)
                            vs_best = (VM.progression_pct(min(prev_times), c["duration_elapsed_s"])
                                       if prev_times else None)
                            history["occurrences"].append(
                                {"time_elapsed_s": c["duration_elapsed_s"], "activity_id": act["id"]})
                            climb_rows.append((
                                act["id"], c["index"], c["start_t_s"], c["end_t_s"], c["start_km"], c["end_km"],
                                c["distance_m"], c["gain_m"], c["avg_grade"], c["grade_class"],
                                c["duration_elapsed_s"], c["duration_moving_s"], c["vam_elapsed_m_h"],
                                c["vam_moving_m_h"], segment_id, hr["hr_first_third_bpm"],
                                hr["hr_last_third_bpm"], hr["hr_drift_bpm_per_100m"], vs_previous, vs_best,
                            ))
                        conn.executemany(
                            "INSERT INTO activity_climb (activity_id, idx, start_t_s, end_t_s, start_km, end_km, "
                            "distance_m, gain_m, avg_grade, grade_class, duration_elapsed_s, duration_moving_s, "
                            "vam_elapsed_m_h, vam_moving_m_h, segment_id, hr_first_third_bpm, hr_last_third_bpm, "
                            "hr_drift_bpm_per_100m, vs_previous_pct, vs_best_pct) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            climb_rows,
                        )
                    windows = derived["vam_windows"]
                    conn.execute(
                        "UPDATE activity SET best_vam_10min_m_h = ?, best_vam_20min_m_h = ?, "
                        "best_climb_vam_elapsed_m_h = ? WHERE id = ?",
                        (windows["vam_best_10min_m_h"], windows["vam_best_20min_m_h"], derived["best_climb_vam"],
                         act["id"]),
                    )
                    reference_speed = derived["descent_reference_speed_ms"]
                    reference_pace = (1000.0 / reference_speed) if reference_speed else None
                    conn.execute(
                        "UPDATE activity SET descent_reference_gap_pace_s_km = ?, "
                        "descent_reference_source = ? WHERE id = ?",
                        (round(reference_pace, 2) if reference_pace is not None else None,
                         derived["descent_reference_source"], act["id"]),
                    )
                    if derived["descent_classes"]:
                        conn.executemany(
                            "INSERT INTO activity_descent_class (activity_id, grade_class, count, "
                            "duration_moving_s, distance_m, mean_speed_ms, mean_pace_s_km, "
                            "mean_gap_speed_ms, mean_grade, efficiency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [(act["id"], cls, v["count"], v["duration_moving_s"], v["distance_m"],
                              v["mean_speed_ms"], v["mean_pace_s_km"], v["mean_gap_speed_ms"],
                              v["mean_grade"], v["efficiency"])
                             for cls, v in derived["descent_classes"].items()],
                        )
                    dur_report = derived["durability"]
                    conn.execute(
                        "UPDATE activity SET durability_gap_fade_pct = ?, durability_ef_fade_pct = ?, "
                        "durability_hr_first_third_bpm = ?, durability_hr_middle_third_bpm = ?, "
                        "durability_hr_last_third_bpm = ?, durability_reason = ?, "
                        "durability_reason_code = ? WHERE id = ?",
                        (dur_report["gap_fade_pct"], dur_report["ef_fade_pct"],
                         dur_report["hr_first_third_bpm"], dur_report["hr_middle_third_bpm"],
                         dur_report["hr_last_third_bpm"], dur_report["reason"], dur_report["reason_code"],
                         act["id"]),
                    )
                    # Modèle pente -> allure (#58) : commit du tampon SEULEMENT ICI, tout au
                    # bout du `try` réussi (voir `_sample_derived_metrics`) — une activité qui
                    # a échoué plus haut ne contribue donc jamais au modèle global, même
                    # partiellement.
                    for band, (bin_summary, method) in derived["slope_bins"].items():
                        slope_activities[band].append(
                            {"activity_id": act["id"], "date": act.get("date"), "bins": bin_summary,
                             "selected_by": method})
                except sqlite3.Error:
                    # Jamais rattrapé, `ARC_STRICT_METRICS` ou pas (voir le commentaire
                    # ci-dessus) : un verrou ou une base corrompue est un problème
                    # d'infrastructure, pas un défaut d'UN calcul dérivé — il doit
                    # remonter bruyamment plutôt que de laisser croire à une activité
                    # simplement sans métriques dérivées.
                    raise
                except Exception as exc:  # noqa: BLE001 — défense en profondeur assumée, voir ci-dessus
                    if os.environ.get("ARC_STRICT_METRICS") == "1":
                        raise
                    print(
                        f"avertissement : calcul des métriques dérivées des échantillons a échoué pour "
                        f"l'activité id={act['id']} (garmin_activity_id={act.get('garmin_activity_id')}) : "
                        f"{exc!r} — champs dérivés remis à NULL, indexation poursuivie avec les activités "
                        "suivantes.",
                        file=sys.stderr,
                    )
                    # Annule tout ce que CETTE activité a mutable en mémoire dans le
                    # registre de montées AVANT l'échec (#49, revue de code, BLOQUANT — voir
                    # le commentaire de `registry_mark` ci-dessus) : sans ce rollback, une
                    # occurrence fantôme resterait dans `segment_history` et fausserait la
                    # progression calculée pour l'activité suivante.
                    climb_registry.rollback(registry_mark)
                    for seg_id, occ_count in history_marks.items():
                        if occ_count is None:
                            segment_history.pop(seg_id, None)
                        else:
                            segment_history[seg_id]["occurrences"] = segment_history[seg_id]["occurrences"][:occ_count]
                    conn.execute("DELETE FROM hr_zone_time WHERE activity_id = ?", (act["id"],))
                    conn.execute("DELETE FROM hr_polarisation_time WHERE activity_id = ?", (act["id"],))
                    conn.execute("DELETE FROM activity_climb WHERE activity_id = ?", (act["id"],))
                    conn.execute("DELETE FROM activity_descent_class WHERE activity_id = ?", (act["id"],))
                    conn.execute(
                        "UPDATE activity_split SET gap_pace_s_km = NULL WHERE activity_id = ?", (act["id"],))
                    conn.execute(
                        "UPDATE activity SET gap_pace_s_km = NULL, decoupling_pct = NULL, ef_whole = NULL, "
                        "decoupling_reason = ?, best_vam_10min_m_h = NULL, best_vam_20min_m_h = NULL, "
                        "best_climb_vam_elapsed_m_h = NULL, descent_reference_gap_pace_s_km = NULL, "
                        "descent_reference_source = NULL, durability_gap_fade_pct = NULL, "
                        "durability_ef_fade_pct = NULL, durability_hr_first_third_bpm = NULL, "
                        "durability_hr_middle_third_bpm = NULL, durability_hr_last_third_bpm = NULL, "
                        "durability_reason = ?, durability_reason_code = ? WHERE id = ?",
                        ("calcul impossible (erreur interne)", "calcul impossible (erreur interne)",
                         "internal_error", act["id"]),
                    )
                # Dépense énergétique modèle RE3 + marche : try/except SÉPARÉ
                # du bloc GAP/VAM/descente/durabilité ci-dessus (revue de code) — un bug dans
                # UN calcul ne doit jamais empêcher l'AUTRE : un détecteur de montée qui lève ne
                # doit pas priver la séance de sa ligne `activity_energy`, et une exception ici
                # ne doit JAMAIS remettre à NULL `gap_pace_s_km`/`decoupling_pct`/etc. de la
                # séance (aucune donnée partagée entre les deux blocs hors `act_samples`, en
                # lecture seule). Réutilise `act_samples` déjà chargés ci-dessus —
                # `arc_energy.energy_from_samples` fait sa PROPRE segmentation/lissage (fenêtre
                # différente de GAP, voir `arc_energy.ASSUMPTIONS["segmentation"]`), jamais un
                # second appel à `arc_elevation` en dehors du module. Poids résolu À LA DATE DE
                # LA SÉANCE (`resolve_weight_kg_as_of`, voir sa docstring) — jamais le poids du
                # jour de l'INDEXATION, qui changerait rétroactivement la dépense d'une séance
                # ancienne à chaque nouvelle pesée. Même discipline `sqlite3.Error`/
                # `ARC_STRICT_METRICS` que le bloc ci-dessus.
                try:
                    weight_kg, weight_source = resolve_weight_kg_as_of(conn, act.get("date"), athlete)
                    # Même cache que ci-dessus, clé propre : le poids change bien plus souvent
                    # (nouvelle pesée) que les échantillons. Enveloppé dans un dict car
                    # `energy_from_samples` peut légitimement rendre `None`.
                    energy_key = cached_energy = None
                    if metrics_cache is not None:
                        energy_key = "energy:" + _digest([sample_stat, act.get("sport"), weight_kg])
                        cached_energy = metrics_cache.get(energy_key)
                    if cached_energy is None:
                        if act_samples is None:
                            act_samples = samples(conn, act["id"])
                        cached_energy = {"energy": EN.energy_from_samples(act_samples, weight_kg)}
                        if energy_key is not None:
                            metrics_cache.put(energy_key, cached_energy)
                    energy = cached_energy["energy"]
                    if energy is None:
                        # `weight_kg` absent/non positif/implausible (voir ASSUMPTIONS["no_exception"]
                        # d'`arc_energy.py` et `resolve_weight_kg_as_of`) : une ligne est quand même
                        # insérée (contrairement à une activité hors famille course à pied/sans FIT,
                        # qui n'a AUCUNE ligne ici) — la raison est alors le poids, pas
                        # l'admissibilité de la séance elle-même, et doit rester explicite pour la
                        # CLI (`energy`).
                        energy = {
                            "kcal": None,
                            "breakdown": {cat: {"seconds": None, "kcal": None} for cat in EN.BREAKDOWN_CATEGORIES},
                            "counted_s": None, "gap_s": None,
                            "elevation_missing": None, "model_id": EN.MODEL_ID,
                            "reason": "aucun poids plausible connu (santé, nutrition ou profil) à la date de "
                                       "la séance ou avant", "reason_code": "no_weight",
                        }
                    breakdown = energy["breakdown"]
                    conn.execute(
                        "INSERT INTO activity_energy (activity_id, model_id, model_kcal, weight_kg, "
                        "weight_source, counted_s, gap_s, elevation_missing, flat_s, flat_kcal, uphill_s, "
                        "uphill_kcal, downhill_s, downhill_kcal, walk_s, walk_kcal, stopped_s, stopped_kcal, "
                        "reason, reason_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (act["id"], energy["model_id"], _round1(energy["kcal"]), weight_kg, weight_source,
                         _round1(energy["counted_s"]), _round1(energy["gap_s"]),
                         None if energy["elevation_missing"] is None else int(energy["elevation_missing"]),
                         _round1(breakdown["flat"]["seconds"]), _round1(breakdown["flat"]["kcal"]),
                         _round1(breakdown["uphill"]["seconds"]), _round1(breakdown["uphill"]["kcal"]),
                         _round1(breakdown["downhill"]["seconds"]), _round1(breakdown["downhill"]["kcal"]),
                         _round1(breakdown["walk"]["seconds"]), _round1(breakdown["walk"]["kcal"]),
                         _round1(breakdown["stopped"]["seconds"]), _round1(breakdown["stopped"]["kcal"]),
                         energy.get("reason"), energy.get("reason_code")),
                    )
                except sqlite3.Error:
                    raise  # infrastructure de la base : jamais rattrapé, voir le commentaire ci-dessus.
                except Exception as exc:  # noqa: BLE001 — défense en profondeur assumée, voir ci-dessus
                    if os.environ.get("ARC_STRICT_METRICS") == "1":
                        raise
                    print(
                        f"avertissement : dépense énergétique modèle a échoué pour l'activité "
                        f"id={act['id']} (garmin_activity_id={act.get('garmin_activity_id')}) : {exc!r} — "
                        "ligne activity_energy avec reason_code=internal_error, indexation poursuivie "
                        "(GAP/VAM/descente/durabilité de cette séance ne sont PAS affectés par cet échec).",
                        file=sys.stderr,
                    )
                    conn.execute("DELETE FROM activity_energy WHERE activity_id = ?", (act["id"],))
                    conn.execute(
                        "INSERT INTO activity_energy (activity_id, model_id, reason, reason_code) "
                        "VALUES (?, ?, ?, ?)",
                        (act["id"], EN.MODEL_ID, "calcul impossible (erreur interne)", "internal_error"),
                    )
    # Écriture du registre `climb_segment` (#49), une fois toutes les activités traitées :
    # `climb_registry.segments` porte le profil/la position représentative (première
    # occurrence), `segment_history` les occurrences vues (temps écoulé, activité) pour
    # `occurrences`/`best_time_elapsed_s`/`best_activity_id`. Le rollback par activité
    # (`registry_mark`/`history_marks` ci-dessus) garantit qu'un segment présent ici a
    # TOUJOURS au moins une occurrence dans `segment_history` — plus de ligne orpheline
    # possible depuis ce correctif (#49, revue de code, BLOQUANT).
    # `segment["id"]` est déterministe (ASSUMPTIONS["segment_id"]), PAS une position dans
    # `climb_registry.segments` : recherche par id, jamais par index.
    segments_by_id = {seg["id"]: seg for seg in climb_registry.segments}
    for segment_id, history in segment_history.items():
        seg = segments_by_id[segment_id]
        times = [(o["time_elapsed_s"], o["activity_id"]) for o in history["occurrences"]
                 if o["time_elapsed_s"] is not None]
        best_time, best_activity_id = min(times, default=(None, None), key=lambda t: t[0])
        conn.execute(
            "INSERT INTO climb_segment (id, location, gain_m, distance_m, avg_grade, grade_class, start_lat, "
            "start_lon, summit_lat, summit_lon, mid_lat, mid_lon, first_seen_activity_id, first_seen_date, "
            "occurrences, best_time_elapsed_s, best_activity_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (segment_id, seg["location"], seg["gain_m"], seg["distance_m"], seg["avg_grade"], seg["grade_class"],
             seg["start_lat"], seg["start_lon"], seg["summit_lat"], seg["summit_lon"],
             seg.get("mid_lat"), seg.get("mid_lon"),
             history["first_activity_id"], history["first_date"], len(history["occurrences"]),
             best_time, best_activity_id),
        )
    # Modèle personnel pente -> allure (#58) : un ajustement par bande, sur la fenêtre
    # `[metrics].slope_model_months` (défaut `arc_slope_model.DEFAULT_MONTHS`), `as_of` =
    # `today` si fourni (sorties reproductibles, comme le reste de `compute_metrics`) sinon
    # la date d'activité la plus récente (résolue par `fit_slope_model` lui-même).
    for band in SL.BANDS:
        result = SL.fit_from_activity_bins(
            slope_activities[band], band=band, months=conf["slope_model_months"],
            easy_hr_bpm=slope_easy_hr_bpm if band == "endurance" else None,
            moderate_hr_bpm=slope_moderate_hr_bpm if band == "endurance" else None, as_of=today)
        conn.execute(
            "INSERT INTO slope_model_meta (band, months, half_life_days, as_of, n_activities, "
            "flat_reference_speed_ms, selected_by_plan, selected_by_hr, reason, reason_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (band, result["months"], result["half_life_days"], result["as_of"], result["n_activities"],
             result["flat_reference_speed_ms"], result["selected_by"]["plan"], result["selected_by"]["hr"],
             result["reason"], result["reason_code"]),
        )
        if result["bins"]:
            conn.executemany(
                "INSERT INTO slope_model_bin (band, grade_lo, grade_hi, grade_mid, label, speed_ms, "
                "pace_s_km, hr_bpm, source, ci_low_speed_ms, ci_high_speed_ms, n_samples, n_activities, "
                "effective_time_s, run_share) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(band, b["grade_lo"] if b["grade_lo"] != float("-inf") else None,
                  b["grade_hi"] if b["grade_hi"] != float("inf") else None, b["grade_mid"], b["label"],
                  b["speed_ms"], b["pace_s_km"], b["hr_bpm"], b["source"], b["ci_low_speed_ms"],
                  b["ci_high_speed_ms"], b["n_samples"], b["n_activities"], b["effective_time_s"],
                  b["run_share"]) for b in result["bins"]],
            )
    if metrics_cache is not None:
        metrics_cache.prune()
    conn.execute("DELETE FROM metric_day")
    dated = sorted(loads)
    if dated:
        start = date.fromisoformat(dated[0])
        end = max(date.fromisoformat(dated[-1]), date.fromisoformat(today) if today else date.today())
        for point in M.daily_series(loads, start, end):
            point["vo2max"] = M.vo2max_trend(estimates, point["date"])
            _insert(conn, "metric_day", point)


# ---------------------------------------------------------------------------
# Échantillons FIT (#42) — ingestion incrémentale, idempotente
# ---------------------------------------------------------------------------


def discover_sample_files(workspace: Path) -> List[Path]:
    root = workspace / "activities" / "fit"
    return sorted(p for p in root.glob("*.json") if p.is_file()) if root.is_dir() else []


def _sample_file_activity_id(path: Path, raw) -> Optional[Union[int, str]]:
    """Identifiant externe d'un fichier `activities/fit/*.json` — entier Garmin ou
    chaîne Intervals.icu `i<chiffres>` (`arc_samples.parse_activity_ref`) : le nom du
    fichier (chemin canonique) prime, avec repli sur la clé `activity_id` du JSON pour
    un fichier renommé ou déposé à la main."""
    from_name = S.sample_file_activity_id(path)
    if from_name is not None:
        return from_name
    if isinstance(raw, dict):
        return S.parse_activity_ref(raw.get("activity_id"))
    return None


def ref_column(ref: Union[int, str]) -> str:
    """Colonne qui porte l'identifiant externe `ref` — dans `activity`, `activity_sample`
    ET `sample_file`, qui la nomment toutes trois pareil : `intervals_activity_id` pour
    une chaîne `i<chiffres>` (#68), `strava_activity_id` pour une chaîne `s<chiffres>` (#164),
    `garmin_activity_id` pour un entier. Nom de colonne
    tiré d'une liste FERMÉE, jamais d'une valeur utilisateur : sûr à interpoler en SQL."""
    if not isinstance(ref, str):
        return "garmin_activity_id"
    return "strava_activity_id" if S.STRAVA_ID_RE.match(ref) else "intervals_activity_id"


def activity_ref(act) -> Optional[Union[int, str]]:
    """Identifiant externe auquel les échantillons d'une activité sont rattachés :
    `garmin_activity_id` s'il existe, sinon `intervals_activity_id` (#68), sinon
    `strava_activity_id` (#164) — le contrat
    n'en renseigne qu'un par séance (`workspace-data-contract`), Garmin prime si un
    fichier ancien porte les deux. `None` : séance sans identifiant externe (saisie
    manuelle), donc sans échantillons possibles."""
    if act is None:
        return None
    keys = act.keys() if hasattr(act, "keys") else ()
    garmin = act["garmin_activity_id"] if "garmin_activity_id" in keys else None
    if garmin is not None:
        return garmin
    for col in REF_COLUMNS[1:]:
        value = act[col] if col in keys else None
        if value:
            return S.parse_activity_ref(value)
    return None


def ref_label(ref: Union[int, str]) -> dict:
    """`{"garmin_activity_id": ref}` ou `{"intervals_activity_id": ref}` — la clé
    d'identification des rapports par séance (`zones`/`gap`/`decoupling`/…) suit la
    source de l'identifiant demandé, inchangée pour un identifiant Garmin."""
    return {ref_column(ref): ref}


def unknown_activity_reason(ref: Union[int, str]) -> str:
    return f"aucune activité indexée pour ce {ref_column(ref)}"


def parse_activity_selector(value, command: str) -> Optional[Union[int, str]]:
    """`--activity`/argument positionnel des sous-commandes par séance : entier Garmin
    ou `i<chiffres>` Intervals.icu. `None` si absent ; `ConfigError` explicite pour
    toute autre forme — jamais un `int()` qui planterait sur `i123456789`."""
    if value is None or value == "":
        return None
    ref = S.parse_activity_ref(value)
    if ref is None:
        raise ConfigError(f"commande « {command} » : identifiant de séance attendu — entier "
                          f"(garmin_activity_id), i<chiffres> (intervals_activity_id) ou s<chiffres> (strava_activity_id) "
                          f"— « {value} » reçu.")
    return ref


def ingest_samples(conn, workspace: Path, resolution_s: int = S.DEFAULT_RESOLUTION_S) -> dict:
    """Ingestion incrémentale et idempotente des échantillons FIT (`activities/fit/*.json`)
    dans `activity_sample`.

    **Clé de rattachement = `garmin_activity_id`, jamais le rowid interne `activity.id`.**
    Une version antérieure de cette fonction stockait `activity.id` — un bug réel (revue
    PR #87) : ce rowid change dès qu'une activité est repurgée puis réinsérée
    (`_purge`/`store`, sur un simple edit du Markdown), et SQLite peut le RÉATTRIBUER à
    une tout autre séance après suppression d'un fichier. Trois conséquences observées :
    un FIT ingéré avant que le Markdown correspondant n'existe restait orphelin pour
    toujours (aucun re-rattachement automatique) ; un Markdown simplement modifié
    perdait ses échantillons (rattachés à un id mort) ; un Markdown supprimé puis un id
    réutilisé par une AUTRE activité lui volait les échantillons de la première. Stocker
    `garmin_activity_id` (jamais réattribué, c'est l'identifiant Garmin réel) et joindre
    `activity` à la LECTURE (`samples()`) élimine structurellement les trois cas : le lien
    n'est jamais mis en cache, il est recalculé à chaque lecture depuis l'état courant de
    `activity`.

    Suivi dans sa propre table `sample_file` (jamais `source_file`, qui n'est lu par
    aucun consommateur autrement qu'en assumant un fichier Markdown du contrat —
    `backfill_items`, `scripts/coach_doctor.py::check_index_freshness` /
    `check_out_of_contract`, `arc_serve.py` — un fichier `fit_sample` qui s'y serait
    glissé y apparaîtrait à tort comme une dette de contrat ou un fichier « supprimé »
    fantôme après un `--rebuild`, revue PR #87) : chaque fichier est suivi par son
    sha256 — inchangé → sauté, modifié → repurgé puis réingéré, disparu → ses lignes
    `activity_sample` retirées. Deux ingestions successives sans changement de fichier
    produisent donc des lignes identiques (idempotence) ; un JSON illisible est compté
    `invalid`, jamais confondu avec un fichier ingéré avec succès.

    Le `garmin_activity_id` d'un fichier ingéré, qu'il corresponde ou non à une activité
    DÉJÀ indexée au moment de l'ingestion, est toujours stocké — voir `sample_coverage()`
    pour le comptage `unlinked_garmin_ids`, calculé fraîchement à chaque appel par une
    requête, jamais mis en cache sur le fichier : purement informatif, **rien n'est
    perdu** — `samples()` retrouvera les échantillons dès que le Markdown de la séance
    sera indexé, sans réingestion du FIT.

    **Budget de taille** (documenté ici, pas ailleurs, pour rester à côté du code qui le
    détermine) : à la résolution par défaut (5 s), une sortie d'1 h ≈ 720 lignes. Pour
    ~300 séances/an d'1 h en moyenne (un volume plausible de coureur régulier, cf.
    `tests/lib/synthetic.py`), ≈ 216 000 lignes — quelques dizaines de Mo dans SQLite
    (l'ordre de grandeur usuel est de 50 à 100 octets/ligne avec l'overhead SQLite pour 6
    colonnes REAL + 2 INTEGER/TEXT), largement absorbable par le fichier `.arc/coach.db`
    déjà jetable et reconstruit à la demande. L'index sur `garmin_activity_id` (DDL
    ci-dessus) garde les requêtes par séance en O(log n) plutôt qu'un scan complet de la
    table à mesure qu'elle grossit.
    """
    counts = {"ingested": 0, "unchanged": 0, "removed": 0, "invalid": 0}
    seen = set()
    for path in discover_sample_files(workspace):
        rel = path.relative_to(workspace).as_posix()
        seen.add(rel)
        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        known = conn.execute("SELECT sha256 FROM sample_file WHERE path = ?", (rel,)).fetchone()
        if known and known[0] == digest:
            counts["unchanged"] += 1
            continue
        conn.execute("DELETE FROM activity_sample WHERE source_path = ?", (rel,))
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            conn.execute(
                "INSERT OR REPLACE INTO sample_file (path, sha256, mtime, status, issues) VALUES (?, ?, ?, ?, ?)",
                (rel, digest, path.stat().st_mtime, "invalid", _j(["JSON illisible"])),
            )
            counts["invalid"] += 1
            continue
        ref = _sample_file_activity_id(path, raw)
        if ref is None:
            conn.execute(
                "INSERT OR REPLACE INTO sample_file (path, sha256, mtime, status, issues) VALUES (?, ?, ?, ?, ?)",
                (rel, digest, path.stat().st_mtime, "invalid",
                 _j(["identifiant de séance introuvable (nom de fichier ni entier Garmin ni i<chiffres> "
                     "Intervals.icu ni s<chiffres> Strava, et clé activity_id absente ou invalide)"])),
            )
            counts["invalid"] += 1
            continue
        col = ref_column(ref)
        sport = conn.execute(f"SELECT sport FROM activity WHERE {col} = ?", (ref,)).fetchone()
        records = S.downsample(
            S.normalise_records(raw, sport=sport["sport"] if sport else None), resolution_s)
        conn.executemany(
            "INSERT INTO activity_sample "
            f"({col}, source_path, t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm, "
            "lat, lon, covered_s, ground_contact_s, stance_balance_pct, vertical_oscillation_m, "
            "vertical_ratio_pct, step_length_m, power_w) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(ref, rel, rec["t_s"], rec["distance_m"], rec["altitude_m"],
              rec["hr_bpm"], rec["speed_ms"], rec["cadence_spm"],
              rec.get("lat_deg"), rec.get("lon_deg"), rec.get("covered_s"),
              *(rec.get(key) for key in S.DYNAMICS_KEYS), rec.get(S.POWER_KEY)) for rec in records],
        )
        conn.execute(
            f"INSERT OR REPLACE INTO sample_file (path, sha256, mtime, {col}, status, issues) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rel, digest, path.stat().st_mtime, ref, "ok", "[]"),
        )
        counts["ingested"] += 1
    for (rel,) in conn.execute("SELECT path FROM sample_file").fetchall():
        if rel not in seen:
            conn.execute("DELETE FROM activity_sample WHERE source_path = ?", (rel,))
            conn.execute("DELETE FROM sample_file WHERE path = ?", (rel,))
            counts["removed"] += 1
    conn.commit()
    return counts


def sample_coverage(conn) -> dict:
    """Couverture FIT actuelle, recalculée à chaque appel (jamais mise en cache sur un
    fichier) — pour `status` et `coach_doctor`-like diagnostics. `rows` : TOUTES les
    lignes stockées, liées ou non (jamais scopé au lien) ; `activities_with_samples` :
    activités dont le `garmin_activity_id` a au moins un échantillon ; `unlinked_garmin_ids` :
    `garmin_activity_id` présents dans `activity_sample` sans activité correspondante
    (FIT téléchargé avant le Markdown, ou séance depuis retirée du workspace) — jamais
    une erreur, juste une information de latence entre les deux sources."""
    rows = conn.execute("SELECT COUNT(*) FROM activity_sample").fetchone()[0]
    linked = unlinked = 0
    # Les deux espaces d'identifiants (#68) comptés séparément puis additionnés : une
    # ligne n'en porte jamais qu'un, voir la DDL de `activity_sample`. `unlinked_garmin_ids`
    # garde son nom historique (consommé par `status`) mais couvre les deux sources.
    for col in REF_COLUMNS:
        linked += conn.execute(
            f"SELECT COUNT(DISTINCT {col}) FROM activity_sample "
            f"WHERE {col} IN (SELECT {col} FROM activity WHERE {col} IS NOT NULL)"
        ).fetchone()[0]
        unlinked += conn.execute(
            f"SELECT COUNT(DISTINCT {col}) FROM activity_sample "
            f"WHERE {col} IS NOT NULL AND {col} NOT IN (SELECT {col} FROM activity WHERE {col} IS NOT NULL)"
        ).fetchone()[0]
    return {"rows": rows, "activities_with_samples": linked, "unlinked_garmin_ids": unlinked}


def samples(conn, activity_id: int) -> List[dict]:
    """Échantillons sous-échantillonnés d'une séance (id INTERNE de `activity`, pas le
    `garmin_activity_id`), triés par `t_s`. Pure lecture, jamais d'exception : une
    séance sans FIT ingéré, ou sans `garmin_activity_id` du tout, rend `[]` — les KPI
    dérivés (zones #43, GAP #44, découplage #45, VAM #46, descente #47, durabilité #48,
    modèle pente→allure #58) peuvent tous tester `if not samples: ...` sans se soucier
    de l'existence du FIT.

    Le lien vers `activity_sample` est résolu ICI, à la lecture, par `garmin_activity_id`
    — jamais mis en cache sur un rowid : voir `ingest_samples` pour le bug que cette
    résolution tardive corrige (rowid réutilisé/instable).
    """
    row = conn.execute("SELECT garmin_activity_id, intervals_activity_id, strava_activity_id FROM activity WHERE id = ?",
                       (activity_id,)).fetchone()
    ref = activity_ref(row)
    if ref is None:
        return []
    return samples_by_ref(conn, ref)["samples"]


def samples_by_garmin_id(conn, garmin_activity_id: int) -> dict:
    """Alias historique de `samples_by_ref` pour un identifiant Garmin."""
    return samples_by_ref(conn, garmin_activity_id)


def samples_by_ref(conn, ref: Union[int, str]) -> dict:
    """Enveloppe JSON-amie, par identifiant externe — `garmin_activity_id` (entier) ou
    `intervals_activity_id` (`i<chiffres>`, #68), celui du nom de fichier
    `activities/fit/<id>.json` et du CLI `arc_index.py samples` — fonctionne même SANS
    activité indexée correspondante (FIT ingéré avant le Markdown) : c'est le but de
    stocker `activity_sample` par identifiant externe plutôt que par rowid."""
    # `lat`/`lon` INCLUS ici (#49) : cette fonction sert à la fois de lecture INTERNE
    # (`samples()`, réutilisée par `compute_metrics` pour l'appariement de montée,
    # `arc_climb_match.py` — a besoin des positions) et de sortie du CLI `samples`
    # (débogage local d'un fichier `activities/fit/<id>.json` déjà lisible tel quel sur
    # le disque de l'athlète — pas une fuite nouvelle). Ce n'est PAS l'API du tableau de
    # bord (`arc_serve.py`), qui n'appelle jamais cette fonction : sa seule route à
    # coordonnées passe par `track` (voir `arc_climb_match.ASSUMPTIONS["privacy"]`).
    col = ref_column(ref)
    rows = conn.execute(
        "SELECT t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm, lat AS lat_deg, lon AS lon_deg, "
        "covered_s "
        f"FROM activity_sample WHERE {col} = ? ORDER BY t_s", (ref,),
    ).fetchall()
    result = {col: ref, "samples": [dict(r) for r in rows]}
    if not rows:
        result["reason"] = f"aucun échantillon ingéré pour ce {col}"
    return result


def count_samples(conn, ref: Optional[Union[int, str]]) -> int:
    """Nombre d'échantillons ingérés pour un identifiant externe (0 si `None`)."""
    if ref is None:
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM activity_sample WHERE {ref_column(ref)} = ?", (ref,)).fetchone()[0]


# Plafond de points renvoyés par `track` : la carte et les graphiques liés de la page séance
# n'en tirent rien de plus, et la réponse reste sous ~100 ko pour une sortie de plusieurs heures.
TRACK_MAX_POINTS = 1500
_TRACK_COLUMNS = (("d", "distance_m", 1), ("t", "t_s", 0), ("lat", "lat", 6), ("lon", "lon", 6),
                  ("alt", "altitude_m", 1), ("hr", "hr_bpm", 0), ("spd", "speed_ms", 2),
                  ("cad", "cadence_spm", 0))


def _track_gap_factors(rows) -> List[Optional[float]]:
    """Facteur de pente GAP (`arc_gap.gap_factor`) de chaque échantillon de `rows`, dans le même
    ordre — pente de `arc_gap.gap_sample_series`, la même que l'allure GAP de la séance."""
    samples = [{"_i": i, "t_s": r["t_s"], "distance_m": r["distance_m"], "altitude_m": r["altitude_m"],
                "speed_ms": r["speed_ms"]} for i, r in enumerate(rows)]
    factors: List[Optional[float]] = [None] * len(rows)
    for s in G.gap_sample_series(samples):
        factors[s["_i"]] = G.gap_factor(s["grade"])
    return factors


def track(conn, activity_id: int, max_points: int = TRACK_MAX_POINTS) -> Optional[dict]:
    """Trace d'une séance pour la carte et les graphiques liés de la page séance —
    `/api/activity/<id>/track`. `None` si l'activité n'existe pas.

    Colonnes parallèles (`d`, `t`, `lat`, `lon`, `alt`, `hr`, `spd`, `cad`, une valeur ou
    `None` par point) plutôt qu'un objet par point : deux à trois fois plus léger. Au-delà de
    `max_points`, un point sur n est gardé (le dernier toujours, pour que la trace finisse à
    l'arrivée). `reason_code` : `no_samples` (aucun FIT ingéré), `no_gps` (échantillons sans
    position — tapis, home trainer : les graphiques restent possibles, pas la carte).

    Famille course à pied seulement : `gf`, facteur de pente C(pente)/C(0) de chaque point
    (`arc_gap.gap_factor`, pente calculée sur TOUS les échantillons avant l'échantillonnage,
    exactement comme l'allure GAP de la séance) — le navigateur en tire l'allure ajustée à la
    pente de la carte (allure ÷ facteur moyen de la fenêtre) sans seconde copie du modèle.

    Seule route qui expose des coordonnées GPS, voir `arc_climb_match.ASSUMPTIONS["privacy"]`."""
    row = conn.execute("SELECT sport, garmin_activity_id, intervals_activity_id, strava_activity_id FROM activity "
                       "WHERE id = ?", (activity_id,)).fetchone()
    if row is None:
        return None
    ref = activity_ref(row)
    rows = [] if ref is None else conn.execute(
        f"SELECT {', '.join(col for _, col, _ in _TRACK_COLUMNS)} FROM activity_sample "
        f"WHERE {ref_column(ref)} = ? ORDER BY t_s", (ref,)).fetchall()
    if not rows:
        return {"reason_code": "no_samples", "points": 0}
    step = max(1, -(-len(rows) // max(2, max_points)))   # plafond de la division
    picked = list(range(0, len(rows), step))
    if picked[-1] != len(rows) - 1:
        picked.append(len(rows) - 1)
    kept = [rows[i] for i in picked]
    out: Dict[str, Any] = {key: [None if r[col] is None else round(r[col], digits) for r in kept]
                           for key, col, digits in _TRACK_COLUMNS}
    if M.sport_family(row["sport"]) == "run":
        factors = _track_gap_factors(rows)
        out["gf"] = [None if factors[i] is None else round(factors[i], 3) for i in picked]
    out["points"] = len(kept)
    fixes = [(la, lo) for la, lo in zip(out["lat"], out["lon"]) if la is not None and lo is not None]
    out["has_gps"] = bool(fixes)
    if fixes:
        lats, lons = [p[0] for p in fixes], [p[1] for p in fixes]
        out["bounds"] = [[min(lats), min(lons)], [max(lats), max(lons)]]
    else:
        out["reason_code"] = "no_gps"
        out.pop("lat")
        out.pop("lon")
    return out


def session_gait(conn, activity_id: int) -> Optional[dict]:
    """Dynamique de course d'UNE séance (#151, même règle que `gait_summary` : moyenne pondérée par
    `covered_s`, repli sur le bloc `arc`, `arc_gait.resolve_session`) pour la page séance. `None`
    hors course à pied, ou quand seule la cadence est connue (elle ne dit rien de la dynamique)."""
    row = conn.execute("SELECT sport, data_json, garmin_activity_id, intervals_activity_id, strava_activity_id FROM activity "
                       "WHERE id = ?", (activity_id,)).fetchone()
    if row is None or row["sport"] not in M.RUNNING_SPORTS:
        return None
    ref = activity_ref(row)
    sampled: Dict[str, Any] = {}
    if ref is not None:
        weight = "CASE WHEN covered_s IS NULL OR covered_s <= 0 THEN 1.0 ELSE covered_s END"
        cols = [f"SUM(CASE WHEN {m} IS NOT NULL THEN {m} * {weight} END) / "
                f"NULLIF(SUM(CASE WHEN {m} IS NOT NULL THEN {weight} END), 0) AS {m}" for m in GT.METRICS]
        found = conn.execute(f"SELECT {', '.join(cols)} FROM activity_sample WHERE {ref_column(ref)} = ?",
                             (ref,)).fetchone()
        sampled = dict(found) if found else {}
    try:
        arc = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        arc = {}
    values, notes = GT.resolve_session(sampled, arc if isinstance(arc, dict) else {})
    if not any(m != "cadence_spm" for m in values):
        return None
    return {"values": values, "notes": notes}


# ---------------------------------------------------------------------------
# Zones FC, temps en zone, polarisation 80/20 (#43)
# ---------------------------------------------------------------------------


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def athlete_hr_zone_resolution(conn, conf: dict) -> dict:
    """Résolution des zones FC pour ce workspace, AVEC raison explicite en cas
    d'échec (méthode inconnue, méthode forcée mais champ manquant, ou aucune donnée
    du tout) — voir `arc_metrics.hr_zone_resolution` (revue de code #43, point 4 :
    jamais un `None` muet qui masquerait la section côté API/UI)."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    return M.hr_zone_resolution(dict(athlete) if athlete else {}, conf.get("hr_zones"))


def athlete_hr_zone_bounds(conn, conf: dict) -> Optional[Tuple[Tuple[float, ...], str]]:
    """Bornes de zones + méthode effectivement utilisée pour ce workspace — voir
    `arc_metrics.hr_zone_bounds` pour la précédence. `None` si aucune méthode n'est
    calculable (profil sans FC max renseignée, au minimum). Pour un appelant qui a
    besoin de savoir POURQUOI, voir `athlete_hr_zone_resolution`."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    return M.hr_zone_bounds(dict(athlete) if athlete else {}, conf.get("hr_zones"))


def activity_zone_report(conn, conf: dict, ref: Union[int, str]) -> dict:
    """Temps en zone d'une séance (#43), par `garmin_activity_id` — pour la CLI
    (`arc_index.py zones --activity`) et pour les agents en headless. Rend
    `{"garmin_activity_id", "bounds_bpm", "method", "reason", "zone_seconds",
    "polarisation"}` — `reason` est toujours présent (`None` en cas de succès),
    `zone_seconds`/`polarisation` restent `None` si aucune zone n'est calculable, si
    la séance n'existe pas, ou si elle n'a pas d'échantillons ingérés — jamais une
    exception, jamais un échec muet. `reason_code: "unknown_activity"` (#51, revue
    de code) accompagne spécifiquement le cas « séance pas encore indexée » — un
    MD pas encore écrit/indexé, PAS une absence de FIT — même code que
    `activity_gap_report`/`activity_decoupling_report`/`activity_climb_report` ci-
    dessous, pour que l'agent distingue les deux causes sans parser le texte."""
    resolution = athlete_hr_zone_resolution(conn, conf)
    if resolution["bounds_bpm"] is None:
        return {**ref_label(ref), **resolution, "zone_seconds": None, "polarisation": None}
    act = conn.execute(f"SELECT id FROM activity WHERE {ref_column(ref)} = ?", (ref,)).fetchone()
    if act is None:
        return {**ref_label(ref), **resolution, "reason": unknown_activity_reason(ref),
                "reason_code": "unknown_activity", "zone_seconds": None, "polarisation": None}
    rows = conn.execute(
        "SELECT zone, seconds FROM hr_zone_time WHERE activity_id = ?", (act["id"],)).fetchall()
    pol_rows = conn.execute(
        "SELECT bucket, seconds FROM hr_polarisation_time WHERE activity_id = ?", (act["id"],)).fetchall()
    if not rows and not pol_rows:
        return {**ref_label(ref), **resolution,
                "reason": "aucun échantillon FIT ingéré pour cette séance (ou sport hors de la famille "
                          "course à pied, voir ASSUMPTIONS[\"hr_zones\"])",
                "zone_seconds": None, "polarisation": None}
    zone_seconds = {row["zone"]: row["seconds"] for row in rows} if rows else None
    pol_seconds = {row["bucket"]: row["seconds"] for row in pol_rows} if pol_rows else None
    return {
        **ref_label(ref), **resolution,
        "zone_seconds": zone_seconds, "polarisation": M.polarisation_shares(pol_seconds) if pol_seconds else None,
    }


# ---------------------------------------------------------------------------
# GAP — allure ajustée à la pente (#44)
# ---------------------------------------------------------------------------


def activity_gap_report(conn, ref: Union[int, str]) -> dict:
    """Rapport GAP (#44) d'une séance : allure GAP globale (s/km) + par split, par
    `garmin_activity_id` — pour la CLI (`arc_index.py gap --activity`) et pour
    les agents en headless. Rend TOUJOURS `{"garmin_activity_id", "gap_pace_s_km",
    "splits", "reason"}` (`reason` non nul explique un `None`), plus
    `reason_code: "unknown_activity"` (#51) spécifiquement quand la séance n'est
    pas (encore) indexée — jamais une exception ni un échec muet (même
    discipline que `activity_zone_report`, #43) : activité introuvable, sport
    hors de la famille course à pied
    (`arc_metrics.sport_family`), pas d'échantillon FIT ingéré, ou échantillons
    ingérés mais sans altitude exploitable (tapis de course, capteur
    barométrique absent, séance toujours à l'arrêt) sont QUATRE raisons
    distinctes — les deux dernières se ressemblent côté athlète (aucun chiffre
    affiché) mais pointent vers des causes très différentes à corriger."""
    act = conn.execute(f"SELECT id, sport, gap_pace_s_km FROM activity WHERE {ref_column(ref)} = ?",
                        (ref,)).fetchone()
    if act is None:
        return {**ref_label(ref), "gap_pace_s_km": None, "splits": None,
                "reason": unknown_activity_reason(ref), "reason_code": "unknown_activity"}
    if M.sport_family(act["sport"]) != "run":
        return {**ref_label(ref), "gap_pace_s_km": None, "splits": None,
                "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                          "arc_gap.ASSUMPTIONS[\"restricted_to_run_family\"]"}
    splits = conn.execute(
        "SELECT km, gap_pace_s_km FROM activity_split WHERE activity_id = ? ORDER BY km", (act["id"],)).fetchall()
    if act["gap_pace_s_km"] is None and not any(s["gap_pace_s_km"] is not None for s in splits):
        sample_count = count_samples(conn, ref)
        if sample_count == 0:
            reason = "aucun échantillon FIT ingéré pour cette séance"
        else:
            reason = ("échantillons FIT ingérés, mais aucune pente exploitable (tapis de course, "
                      "capteur barométrique absent, altitude toujours identique, ou vitesse "
                      "toujours sous le seuil de mouvement) — voir arc_gap.ASSUMPTIONS")
        return {**ref_label(ref), "gap_pace_s_km": None, "splits": None,
                "reason": reason}
    return {**ref_label(ref), "gap_pace_s_km": act["gap_pace_s_km"],
            "splits": [dict(s) for s in splits], "reason": None}


# ---------------------------------------------------------------------------
# Dépense énergétique modèle vs Garmin.
# ---------------------------------------------------------------------------

# Séances éligibles au calcul (`activity_energy`, `arc_energy.py` gère aussi la
# marche) — mêmes sports que la famille course à pied `arc_metrics.SPORT_FAMILY`
# = "run", jamais une liste maintenue séparément qui pourrait diverger.
ENERGY_ELIGIBLE_SPORTS = tuple(sport for sport, family in M.SPORT_FAMILY.items() if family == "run")
ENERGY_DEFAULT_LIMIT = 10


def _energy_net(total_kcal: Optional[float], bmr_kcal: Optional[float]) -> Optional[float]:
    """`total_kcal - bmr_kcal`, `None` si l'une des deux valeurs manque — jamais un
    NET partiel qui laisserait croire à une soustraction faite alors qu'elle ne
    l'a pas été (voir `arc_energy.ASSUMPTIONS["model"]` : le modèle rend un BRUT,
    le NET n'existe qu'une fois `calories_bmr_kcal` connu)."""
    if total_kcal is None or bmr_kcal is None:
        return None
    return total_kcal - bmr_kcal


def _energy_breakdown_from_row(row: dict) -> Dict[str, Dict[str, Optional[float]]]:
    return {cat: {"seconds": row[f"{cat}_s"], "kcal": row[f"{cat}_kcal"]} for cat in EN.BREAKDOWN_CATEGORIES}


def _energy_session_dict(act: dict, energy_row: Optional[dict]) -> dict:
    """Un point de la sortie `energy` à partir d'une ligne `activity` et de
    sa ligne `activity_energy` correspondante (`None` si l'activité n'a AUCUNE
    ligne — hors famille course à pied ou sans FIT, voir
    `_energy_reason_for_missing_row`, appelée par l'appelant AVANT cette
    fonction pour peupler `reason`/`reason_code` dans ce cas). Rend TOUJOURS le
    même jeu de clés, `None` pour tout ce qui n'est pas calculable — jamais une
    clé absente selon les données rencontrées (un consommateur JSON ne doit pas
    avoir à deviner quelles clés une séance particulière porte).

    `delta_pct`/`net_garmin_kcal`/`net_model_kcal` arrondis à 1 décimale (revue de
    code) — même précision que les autres colonnes stockées (`_round1`), jamais la
    précision flottante brute du calcul exposée telle quelle dans le JSON.
    `delta_reason`/`net_reason` (revue de code) : raisons SPÉCIFIQUES à l'absence
    de `delta_pct`/`net_*_kcal` quand la cause n'est PAS déjà celle de
    `reason_code` (poids/éligibilité) mais une donnée GARMIN manquante —
    `delta_reason="no_garmin_kcal"` si `calories_kcal` est absent (delta
    incalculable même si le modèle, lui, a un résultat) ; `net_reason="no_bmr"`
    si `calories_bmr_kcal` est absent (net incalculable des DEUX côtés). Si
    `net_model_kcal` est `None` alors que le BMR est connu, c'est que `model_kcal`
    lui-même manque — déjà expliqué par `reason`/`reason_code`, `net_reason` reste
    alors `None` (pas de double explication contradictoire)."""
    model_kcal = energy_row["model_kcal"] if energy_row else None
    garmin_kcal = act.get("calories_kcal")
    bmr_kcal = act.get("calories_bmr_kcal")
    delta_pct = EN.delta_pct(model_kcal, garmin_kcal)
    return {
        "garmin_activity_id": act.get("garmin_activity_id"),
        "date": act.get("date"),
        "name": act.get("name"),
        "sport": act.get("sport"),
        "garmin_kcal": garmin_kcal,
        "model_kcal": model_kcal,
        "model_id": (energy_row["model_id"] if energy_row else None) or EN.MODEL_ID,
        "delta_pct": _round1(delta_pct),
        "delta_reason": "no_garmin_kcal" if garmin_kcal is None else None,
        "flag": EN.delta_flag(delta_pct),
        "bmr_kcal": bmr_kcal,
        "net_garmin_kcal": _round1(_energy_net(garmin_kcal, bmr_kcal)),
        "net_model_kcal": _round1(_energy_net(model_kcal, bmr_kcal)),
        "net_reason": "no_bmr" if bmr_kcal is None else None,
        "weight_kg": energy_row["weight_kg"] if energy_row else None,
        "weight_source": energy_row["weight_source"] if energy_row else None,
        "counted_s": energy_row["counted_s"] if energy_row else None,
        "gap_s": energy_row["gap_s"] if energy_row else None,
        "elevation_missing": (bool(energy_row["elevation_missing"])
                               if energy_row and energy_row["elevation_missing"] is not None else None),
        "breakdown": _energy_breakdown_from_row(energy_row) if energy_row else None,
        "reason": energy_row["reason"] if energy_row else None,
        "reason_code": energy_row["reason_code"] if energy_row else None,
    }


def _energy_reason_for_missing_row(conn, act: dict) -> Tuple[str, str]:
    """`reason`/`reason_code` d'une séance SANS ligne `activity_energy` — hors
    famille course à pied, sans aucun identifiant externe (ni `garmin_activity_id`
    ni `intervals_activity_id` : saisie manuelle, aucun FIT rattachable), ou sans
    échantillon FIT ingéré (les seules raisons pour lesquelles `compute_metrics`
    n'insère aucune ligne, voir la DDL de `activity_energy`). Jamais appelée pour
    une séance qui A une ligne (poids introuvable y est déjà `reason_code:
    "no_weight"`, porté par la ligne elle-même)."""
    if M.sport_family(act.get("sport")) != "run":
        return ("hors de la famille course à pied (arc_metrics.sport_family) — le moteur "
                "ne couvre que running/trail/hiking/walking", "not_run_family")
    ref = activity_ref(act)
    if ref is None:
        # Revue de code : distinct de « no_samples » — une séance sans identifiant
        # externe n'a jamais pu avoir de FIT ingéré, ce n'est pas un simple oubli de
        # synchronisation.
        return ("aucun identifiant Garmin ni Intervals.icu pour cette séance — le moteur "
                "dépend des échantillons FIT, qui se rattachent par cet identifiant", "no_activity_id")
    if count_samples(conn, ref) == 0:
        return ("aucun échantillon FIT ingéré pour cette séance (skills/fit-download : "
                "download_fit.py --from-dir activities/ --json)", "no_samples")
    # Ne devrait pas arriver (une activité de la famille course à pied avec des
    # échantillons FIT obtient toujours une ligne, voir compute_metrics) — filet de
    # sécurité honnête plutôt qu'une exception si l'invariant est un jour rompu.
    return "aucune ligne activity_energy pour cette séance (cause inconnue)", "no_row"


def _energy_session_for_activity_row(conn, act: dict) -> dict:
    energy_row = conn.execute(
        "SELECT * FROM activity_energy WHERE activity_id = ?", (act["id"],)).fetchone()
    session = _energy_session_dict(act, dict(energy_row) if energy_row else None)
    if energy_row is None:
        session["reason"], session["reason_code"] = _energy_reason_for_missing_row(conn, act)
    return session


def activity_energy_report(conn, ref: Union[int, str]) -> dict:
    """Détail de dépense énergétique modèle vs Garmin d'UNE séance, par
    `garmin_activity_id` — pour la CLI (`arc_index.py energy --activity`) et les
    agents en headless. Rend TOUJOURS le même jeu de clés (voir
    `_energy_session_dict`), `reason`/`reason_code` explicites si `model_kcal`
    est `None` — jamais une exception ni un échec muet, même discipline que
    `activity_gap_report`/`activity_descent_report`."""
    act = conn.execute(
        "SELECT id, garmin_activity_id, intervals_activity_id, strava_activity_id, date, name, sport, calories_kcal, calories_bmr_kcal FROM activity "
        f"WHERE {ref_column(ref)} = ?", (ref,)).fetchone()
    if act is None:
        empty = _energy_session_dict({**ref_label(ref)}, None)
        empty["reason"] = unknown_activity_reason(ref)
        empty["reason_code"] = "unknown_activity"
        return empty
    return _energy_session_for_activity_row(conn, dict(act))


def energy_report(conn, *, activity: Optional[Union[int, str]] = None, day: Optional[str] = None,
                   since: Optional[str] = None, limit: int = ENERGY_DEFAULT_LIMIT,
                   assumptions: bool = False) -> dict:
    """Dépense énergétique modèle vs Garmin d'un ensemble de séances — pour
    la CLI (`arc_index.py energy`) et pour les agents en headless (voir aussi
    `scripts/arc_race_pacing.py` pour la PRÉVISION par section d'un plan de
    course, un calcul distinct). Un SEUL des trois sélecteurs (`activity`/`day`/`since`) à
    la fois — la CLI (`main`) rejette explicitement leur combinaison plutôt que
    de laisser une précédence silencieuse tromper un appelant headless, comme
    `--date`/`--days` pour `decisions`. Sans sélecteur : les `limit` dernières
    séances ÉLIGIBLES (`ENERGY_ELIGIBLE_SPORTS`), en ORDRE CHRONOLOGIQUE (la plus
    ANCIENNE des `limit` en tête, la plus RÉCENTE en dernier — cohérent avec le
    code, `rows` est explicitement inversé après le `ORDER BY ... DESC ... LIMIT`
    qui sélectionne les `limit` séances les plus récentes) — une séance hors de
    cette famille de sport n'apparaît JAMAIS dans ce mode par défaut
    (contrairement à `--activity`, qui accepte n'importe quel sport pour en
    expliquer explicitement l'inéligibilité). Rend TOUJOURS le même jeu de clés
    `{"model_id", "assumptions", "assumptions_summary", "sessions"}` (revue de
    code) — MAIS `assumptions`/`assumptions_summary` sont MUTUELLEMENT
    EXCLUSIFS, l'une des deux valant toujours `None` : `assumptions` porte
    `arc_energy.ASSUMPTIONS` en entier (plusieurs Ko de JSON) UNIQUEMENT si
    `assumptions=True` (CLI `--assumptions`), sinon `None` et
    `assumptions_summary` porte le résumé court `arc_energy.SUMMARY` (1-2
    lignes) — un agent qui liste des séances n'a pas besoin de relire tout le
    modèle à chaque appel, mais peut le demander explicitement quand il veut
    vérifier une hypothèse."""
    if activity is not None:
        sessions = [activity_energy_report(conn, activity)]
    else:
        cols = "id, garmin_activity_id, intervals_activity_id, strava_activity_id, date, name, sport, calories_kcal, calories_bmr_kcal"
        placeholders = ", ".join("?" for _ in ENERGY_ELIGIBLE_SPORTS)
        if day:
            rows = conn.execute(
                f"SELECT {cols} FROM activity WHERE date = ? AND sport IN ({placeholders}) "
                "ORDER BY date, start_time, garmin_activity_id, id",
                (day, *ENERGY_ELIGIBLE_SPORTS)).fetchall()
        elif since:
            rows = conn.execute(
                f"SELECT {cols} FROM activity WHERE date >= ? AND sport IN ({placeholders}) "
                "ORDER BY date, start_time, garmin_activity_id, id",
                (since, *ENERGY_ELIGIBLE_SPORTS)).fetchall()
        else:
            effective_limit = limit if limit and limit > 0 else ENERGY_DEFAULT_LIMIT
            rows = conn.execute(
                f"SELECT {cols} FROM activity WHERE sport IN ({placeholders}) "
                "ORDER BY date DESC, start_time DESC, garmin_activity_id DESC, id DESC LIMIT ?",
                (*ENERGY_ELIGIBLE_SPORTS, effective_limit)).fetchall()
            rows = list(reversed(rows))  # chronologique, comme les modes --date/--since
        sessions = [_energy_session_for_activity_row(conn, dict(row)) for row in rows]
    out = {"model_id": EN.MODEL_ID}
    out["assumptions"] = EN.ASSUMPTIONS if assumptions else None
    out["assumptions_summary"] = None if assumptions else EN.SUMMARY
    out["sessions"] = sessions
    return out


def activity_energy_report_by_id(conn, activity_id: int) -> dict:
    """Comme `activity_energy_report` mais par identifiant INTERNE de l'activité
    (`activity.id`), pour `/api/activity/<id>` (tableau de bord local) —
    l'API paramétrée route par cet id-là, jamais par `garmin_activity_id` (une
    séance synchronisée depuis Intervals.icu, #68, n'en a d'ailleurs aucun).
    Délègue ENTIÈREMENT à `_energy_session_for_activity_row` (même fonction que
    `energy_report`/`activity_energy_report`) : aucun second calcul du
    delta/flag ici, seule la clause `WHERE` change."""
    act = conn.execute(
        "SELECT id, garmin_activity_id, intervals_activity_id, strava_activity_id, date, name, sport, calories_kcal, calories_bmr_kcal FROM activity "
        "WHERE id = ?", (activity_id,)).fetchone()
    if act is None:
        empty = _energy_session_dict({}, None)
        empty["reason"] = "activité introuvable"
        empty["reason_code"] = "unknown_activity"
        return empty
    return _energy_session_for_activity_row(conn, dict(act))


# Fenêtre de la tendance de dépense énergétique : 12 semaines
# glissantes, même largeur que les autres tendances dérivées des échantillons FIT
# (découplage #45, VAM #46, descente #47, durabilité #48) — pas de raison connue
# d'en choisir une différente pour un KPI qui dépend de la même donnée d'entrée
# (`activity_sample`) et du même filtre d'éligibilité (famille course à pied).
ENERGY_TREND_WEEKS = 12

# Regroupement route/trail de l'écart médian : les deux sports mesurés par la
# validation de référence (voir `arc_energy.ASSUMPTIONS`/`docs/marques.md`) —
# route ±6 %, trail +3/+5 % vs Garmin, des biais DIFFÉRENTS qu'un écart médian
# toutes séances confondues masquerait. Randonnée et marche (aussi éligibles au
# calcul, `ENERGY_ELIGIBLE_SPORTS`) restent hors des deux paniers : la
# validation ne les couvre pas, un écart médian sur ces sports n'aurait aucune
# base de comparaison connue — elles apparaissent quand même dans `sessions`,
# seulement absentes de `delta_median_pct`.
ENERGY_TREND_ROUTE_TRAIL_BUCKET = {"running": "route", "trail": "trail"}


def energy_trend(conn, today: date, weeks: int = ENERGY_TREND_WEEKS) -> dict:
    """Tendance de la dépense énergétique modèle vs Garmin sur les
    `weeks` dernières semaines glissantes se terminant à `today` inclus — pour
    `/api/energy-trend` (tableau de bord local). RÉUTILISE
    `_energy_session_for_activity_row` (même fonction que `energy_report` et
    `activity_energy_report_by_id`/`/api/activity/<id>.energy`) : aucun second
    calcul du delta/flag ici, seuls la fenêtre et le regroupement route/trail
    sont propres à cette fonction.

    TOUTES les séances ÉLIGIBLES (`ENERGY_ELIGIBLE_SPORTS`) de la fenêtre
    apparaissent dans `sessions`, y compris celles sans `model_kcal` calculable
    (`reason`/`reason_code` explicites, comme partout ailleurs dans ce module) —
    un consommateur qui veut seulement les points traçables (nuage de points,
    graphique de tendance) doit lui-même filtrer sur `delta_pct is not None`,
    jamais cette fonction à sa place (elle ne doit pas décider pour l'appelant
    ce qui compte comme « une séance qui compte »).

    `delta_median_pct` : médiane SIGNÉE (jamais la valeur absolue — un biais
    systématique dans un seul sens est une information différente d'un écart
    dispersé des deux côtés) de `delta_pct`, séparément pour `route` et `trail`
    (voir `ENERGY_TREND_ROUTE_TRAIL_BUCKET`) — `None` si aucune séance mesurable
    de ce panier dans la fenêtre, jamais 0 (qui laisserait croire à un accord
    parfait mesuré)."""
    start = today - timedelta(days=weeks * 7 - 1)
    cols = "id, garmin_activity_id, intervals_activity_id, strava_activity_id, date, name, sport, calories_kcal, calories_bmr_kcal"
    placeholders = ", ".join("?" for _ in ENERGY_ELIGIBLE_SPORTS)
    rows = conn.execute(
        f"SELECT {cols} FROM activity WHERE date >= ? AND date <= ? AND sport IN ({placeholders}) "
        "ORDER BY date, start_time, garmin_activity_id, id",
        (start.isoformat(), today.isoformat(), *ENERGY_ELIGIBLE_SPORTS)).fetchall()
    sessions = [_energy_session_for_activity_row(conn, dict(row)) for row in rows]
    by_bucket: Dict[str, List[float]] = {"route": [], "trail": []}
    for s in sessions:
        bucket = ENERGY_TREND_ROUTE_TRAIL_BUCKET.get(s["sport"])
        if bucket and s["delta_pct"] is not None:
            by_bucket[bucket].append(s["delta_pct"])
    return {
        "model_id": EN.MODEL_ID,
        "window_weeks": weeks,
        "delta_alert_pct": EN.DELTA_ALERT_PCT,
        "sessions": sessions,
        "sessions_n": len(sessions),
        "measured_n": sum(1 for s in sessions if s["delta_pct"] is not None),
        "delta_median_pct": {
            "route": _round1(statistics.median(by_bucket["route"])) if by_bucket["route"] else None,
            "trail": _round1(statistics.median(by_bucket["trail"])) if by_bucket["trail"] else None,
        },
        "assumptions_summary": EN.SUMMARY,
        # Statut de calibration par panier (voir `energy_calibration` ci-dessous) — sur SA PROPRE
        # fenêtre (`arc_energy.CALIBRATION_WINDOW_WEEKS`, 26 semaines), INDÉPENDANTE de `weeks`
        # (fenêtre de CE graphique de tendance, souvent plus courte) : la calibration doit rester
        # stable d'un appel à l'autre du même tableau de bord, qu'importe la fenêtre affichée par
        # l'athlète (8/12/26 semaines...) — jamais recalculée sur une fenêtre trop courte pour
        # atteindre `CALIBRATION_MIN_N` juste parce que la vue affiche 8 semaines ce jour-là.
        "calibration": energy_calibration(conn, today),
    }


def energy_calibration(conn, today: date, weeks: int = EN.CALIBRATION_WINDOW_WEEKS) -> dict:
    """Calibration personnelle du modèle de dépense énergétique — ratio médian
    Garmin/modèle par panier route/trail, sur les `weeks` dernières semaines
    glissantes se terminant à `today` inclus (défaut `arc_energy.
    CALIBRATION_WINDOW_WEEKS`, 26 — INDÉPENDANT de `ENERGY_TREND_WEEKS`,
    12, plus court : voir `energy_trend`, qui appelle CETTE fonction avec sa
    fenêtre propre plutôt que celle, plus courte, de la tendance affichée).
    Pour la CLI (`arc_index.py energy --calibration`) et pour `/api/energy-
    trend` (tableau de bord local, champ `calibration`).

    Appliquée UNIQUEMENT aux PRÉVISIONS (`arc_race_pacing.
    race_energy_forecast`), JAMAIS aux séances déjà mesurées — voir
    `arc_energy.ASSUMPTIONS["calibration"]` pour la méthode complète (bornage
    du facteur, statuts, fenêtre).

    Panier route/trail : `ENERGY_TREND_ROUTE_TRAIL_BUCKET` (même regroupement
    qu'`energy_trend`, randonnée/marche hors des deux paniers — aucune
    validation de référence connue pour ces sports). **Aucune exclusion sur
    `flag` ici** (correctif de revue de code, BLOQUANT) : `flag`
    (`arc_energy.delta_flag`, écart ABSOLU modèle/Garmin > `DELTA_ALERT_PCT`
    d'UNE séance) est réservé à l'alerte affichée sur cette séance précise —
    l'exclure du calcul de calibration bride mathématiquement le ratio médian
    atteignable et fait tomber à tort en `insufficient` un biais RÉEL et
    cohérent du panier entier (chaque séance dépasserait alors le seuil PAR
    SÉANCE, alors que rien n'est aberrant dans le panier lui-même). TOUS les
    ratios calculables du panier (Garmin ET modèle connus) sont donc transmis
    tels quels à `arc_energy.calibration_band_report`, qui applique SA PROPRE
    exclusion des aberrantes — RELATIVE à la médiane du panier
    (`CALIBRATION_OUTLIER_RELATIVE_BAND_PCT`), un mécanisme différent et
    indépendant. RÉUTILISE `_energy_session_for_activity_row` (même fonction
    qu'`energy_report`/`energy_trend`/`activity_energy_report_by_id`) pour le
    delta de chaque séance : aucun second calcul du ratio ici.

    Rend `{"model_id", "window_weeks", "min_n", "not_needed_band_pct",
    "factor_min", "factor_max", "buckets": {"route": {...}, "trail": {...}}}`
    — chaque panier via `arc_energy.calibration_band_report` (`n`,
    `ratio_median`, `ratio_iqr`, `status`, `factor`)."""
    start = today - timedelta(days=weeks * 7 - 1)
    cols = "id, garmin_activity_id, intervals_activity_id, strava_activity_id, date, name, sport, calories_kcal, calories_bmr_kcal"
    placeholders = ", ".join("?" for _ in ENERGY_ELIGIBLE_SPORTS)
    rows = conn.execute(
        f"SELECT {cols} FROM activity WHERE date >= ? AND date <= ? AND sport IN ({placeholders}) "
        "ORDER BY date, start_time, garmin_activity_id, id",
        (start.isoformat(), today.isoformat(), *ENERGY_ELIGIBLE_SPORTS)).fetchall()
    ratios_by_bucket: Dict[str, List[float]] = {"route": [], "trail": []}
    for row in rows:
        act = dict(row)
        bucket = ENERGY_TREND_ROUTE_TRAIL_BUCKET.get(act["sport"])
        if bucket is None:
            continue
        session = _energy_session_for_activity_row(conn, act)
        model_kcal = session.get("model_kcal")
        garmin_kcal = session.get("garmin_kcal")
        if not model_kcal or garmin_kcal is None:
            continue  # modèle non calculable ou Garmin absent : ratio non défini pour cette séance
        ratios_by_bucket[bucket].append(garmin_kcal / model_kcal)
    return {
        "model_id": EN.MODEL_ID,
        "window_weeks": weeks,
        "min_n": EN.CALIBRATION_MIN_N,
        "not_needed_band_pct": EN.CALIBRATION_NOT_NEEDED_BAND_PCT,
        "factor_min": EN.CALIBRATION_FACTOR_MIN,
        "factor_max": EN.CALIBRATION_FACTOR_MAX,
        "buckets": {bucket: EN.calibration_band_report(ratios) for bucket, ratios in ratios_by_bucket.items()},
    }


def weekly_polarisation(conn, weeks: int, today: date) -> List[dict]:
    """Polarisation 80/20 hebdomadaire (#43) des `weeks` dernières semaines (la
    courante incluse), plus ancienne en premier — pour la CLI (`arc_index.py zones
    --weeks`) et pour `/api/load`. Une semaine sans AUCUNE activité à échantillons
    (`hr_polarisation_time` vide sur toute la semaine) rend `polarisation: None` —
    jamais 0 % partout, voir `arc_metrics.ASSUMPTIONS["hr_zones"]`. Lit directement
    les seaux Seiler déjà calculés à l'indexation (bornes dédiées par méthode,
    `arc_metrics.seiler_bounds`) — jamais un regroupement de `hr_zone_time` ici."""
    first = _monday(today) - timedelta(weeks=weeks - 1)
    buckets: Dict[str, Dict[str, float]] = {
        (first + timedelta(weeks=w)).isoformat(): {} for w in range(weeks)
    }
    rows = conn.execute(
        "SELECT a.date AS date, hp.bucket AS bucket, hp.seconds AS seconds "
        "FROM hr_polarisation_time hp JOIN activity a ON a.id = hp.activity_id "
        "WHERE a.date >= ? AND a.date <= ?",
        (first.isoformat(), today.isoformat()),
    ).fetchall()
    for row in rows:
        week_start = _monday(date.fromisoformat(row["date"])).isoformat()
        bucket = buckets.get(week_start)
        if bucket is None:
            continue
        bucket[row["bucket"]] = bucket.get(row["bucket"], 0.0) + row["seconds"]
    out = []
    for week_start in sorted(buckets):
        out.append({"week_start": week_start, "polarisation": M.polarisation_shares(buckets[week_start])})
    return out


# `planning/Semaine_<lundi>.md` — reconnaît le fichier DÉDIÉ d'une semaine
# précise, qu'il porte une semaine unique ou (accessoirement) un plan
# multi-semaines dont la première entrée est justement cette semaine-là. Utilisé
# UNIQUEMENT par `_mark_week_shadowing` pour la priorité de collision (#69) —
# distinct de `_SOURCE_WEEK_RE` plus bas (qui, lui, sert à afficher une date pour
# n'importe quel fichier `planning/Semaine_*.md`, sans notion de priorité).
def _dedicated_week_source(week_start: str) -> str:
    return f"planning/Semaine_{week_start}.md"


def week_collisions(conn) -> List[dict]:
    """Semaines (`week_start`) décrites par PLUSIEURS fichiers à la fois (#69) —
    un fichier dédié `planning/Semaine_<lundi>.md` et un plan multi-semaines qui
    couvre incidemment le même lundi, ou deux plans multi-semaines qui se
    recouvrent. Rend une entrée par collision : `week_start`, `winner` (le
    `source_path` qui l'emporte), `losers` (les autres, écartés des tables
    dérivées). Priorité au fichier DÉDIÉ de cette semaine (son nom porte
    exactement ce lundi) ; à défaut (deux plans multi-semaines qui se
    recouvrent sans qu'aucun ne soit le fichier dédié), au chemin le plus petit
    par ordre alphabétique.

    **Alphabétique, jamais la date de dernière modification du fichier**
    (revue de code #69, should-fix 6) — choix délibéré : `mtime` n'est pas
    reconstituée par un `git clone`/`checkout` (tous les fichiers prennent la
    date du checkout, dans un ordre qui ne reflète plus du tout l'historique
    réel des écritures), donc un départage par mtime redeviendrait ARBITRAIRE
    et NON REPRODUCTIBLE dès qu'un workspace versionné change de machine —
    exactement ce que ce module s'interdit ailleurs (voir par ex. `gear_slug`,
    `week_collisions` lui-même). L'ordre alphabétique, lui, ne dépend que du
    CONTENU du dépôt (les chemins), jamais de son historique d'exécution : deux
    passages sur le même jeu de fichiers, sur deux machines différentes,
    rendent toujours le même gagnant. Ce départage reste un FILET DE SÉCURITÉ,
    pas une politique à invoquer sciemment : un plan qui en remplace un autre
    doit retirer ou réécrire les semaines qui se chevauchent dans l'ANCIEN
    fichier plutôt que de compter sur lui pour trancher (voir `agents/
    coach.md`, section « Multi-week plans »).

    Pure lecture (aucune écriture) : calculée à la demande à partir du contenu
    ACTUEL de la table `week`, jamais d'un état mémorisé qui pourrait rester
    périmé si le fichier gagnant disparaît. `_mark_week_shadowing` (appelée par
    `index_workspace` à chaque passage) applique ce même calcul aux colonnes
    `shadowed` de `week`/`planned_session` que lisent le tableau de bord et les
    CLI ; cette fonction-ci existe pour les tests et un futur affichage
    explicite de la collision (backfill, `/api/files`)."""
    rows = conn.execute(
        "SELECT DISTINCT week_start, source_path FROM week WHERE week_start IS NOT NULL"
    ).fetchall()
    by_week: Dict[str, List[str]] = {}
    for row in rows:
        by_week.setdefault(row["week_start"], []).append(row["source_path"])
    collisions = []
    for week_start, sources in sorted(by_week.items()):
        if len(sources) <= 1:
            continue
        sources = sorted(sources)
        dedicated = _dedicated_week_source(week_start)
        winner = dedicated if dedicated in sources else sources[0]
        collisions.append({
            "week_start": week_start, "winner": winner,
            "losers": [s for s in sources if s != winner],
        })
    return collisions


_WEEK_COLLISION_MARKER = "en collision avec"  # identifie nos propres messages dans `issues`


def _mark_week_shadowing(conn) -> None:
    """Recalcule EN ENTIER (#69) la colonne `shadowed` de `week`/`planned_session`
    à partir de `week_collisions` ci-dessus, et tient à jour un avertissement
    dans les `issues` du/des fichier(s) perdant(s) — visible dans
    `backfill_items` et le tableau de bord (`/api/files`) sans qu'on ait besoin
    d'ouvrir le fichier. Repart de zéro à chaque appel (jamais un `shadowed`
    incrémental, jamais un avertissement seulement AJOUTÉ) : les anciens
    messages de collision sont retirés avant que les collisions ACTUELLES ne
    soient réécrites, pour qu'une collision résolue (fichier gagnant réécrit ou
    supprimé) ne laisse jamais un avertissement périmé dans `issues`."""
    conn.execute("UPDATE week SET shadowed = 0")
    conn.execute("UPDATE planned_session SET shadowed = 0")
    loser_messages: Dict[str, List[str]] = {}
    for collision in week_collisions(conn):
        week_start, winner = collision["week_start"], collision["winner"]
        for loser in collision["losers"]:
            conn.execute(
                "UPDATE week SET shadowed = 1 WHERE source_path = ? AND week_start = ?",
                (loser, week_start))
            conn.execute(
                "UPDATE planned_session SET shadowed = 1 WHERE source_path = ? AND week_start = ?",
                (loser, week_start))
            loser_messages.setdefault(loser, []).append(
                f"semaine {week_start} en collision avec {winner} : {winner} fait foi "
                f"pour cette semaine (#69, priorité au fichier dédié sinon au chemin le "
                f"plus petit), cette entrée est ignorée du tableau de bord et des CLI"
            )
    previously_flagged = {
        row["path"] for row in conn.execute(
            f"SELECT path FROM source_file WHERE issues LIKE '%{_WEEK_COLLISION_MARKER}%'"
        ).fetchall()
    }
    for path in previously_flagged | set(loser_messages):
        row = conn.execute("SELECT issues FROM source_file WHERE path = ?", (path,)).fetchone()
        if row is None:
            continue
        issues = [i for i in json.loads(row["issues"] or "[]") if _WEEK_COLLISION_MARKER not in i]
        issues.extend(loser_messages.get(path, []))
        conn.execute("UPDATE source_file SET issues = ? WHERE path = ?", (_j(issues), path))


_CODE_DIGEST: Optional[str] = None


def _code_digest() -> str:
    """Condensé du code du moteur (`scripts/*.py`) : une base sur disque indexée par une
    AUTRE version du code ne doit jamais faire sauter le recalcul des métriques."""
    global _CODE_DIGEST
    if _CODE_DIGEST is None:
        h = hashlib.sha256(str(SCHEMA_VERSION).encode())
        for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
            h.update(path.name.encode())
            h.update(path.read_bytes())
        _CODE_DIGEST = h.hexdigest()
    return _CODE_DIGEST


def metrics_fingerprint(conn, conf: dict, today: str) -> str:
    """Empreinte de TOUT ce dont dépend `compute_metrics` : fichiers indexés (sha,
    statut, avertissements — `_mark_week_shadowing` inclus), échantillons FIT,
    configuration, date de référence et code du moteur. Inchangée ⇒ les tables
    dérivées déjà en base sont exactement celles qu'un recalcul produirait."""
    h = hashlib.sha256()
    h.update(_code_digest().encode())
    h.update((_j(conf) or "").encode("utf-8"))
    h.update(today.encode())
    for row in conn.execute("SELECT path, kind, sha256, parsed_ok, issues FROM source_file ORDER BY path"):
        h.update(repr(tuple(row)).encode("utf-8"))
    for row in conn.execute(
            "SELECT path, sha256, garmin_activity_id, intervals_activity_id, strava_activity_id, status "
            "FROM sample_file ORDER BY path"):
        h.update(repr(tuple(row)).encode("utf-8"))
    return h.hexdigest()


def index_workspace(conn, workspace: Path, today: Optional[str] = None,
                    metrics_cache: Optional[MetricsCache] = None) -> dict:
    """Indexe (incrémental) puis recalcule les métriques. Rend un résumé.

    `metrics_cache` (processus longue durée : le tableau de bord) active deux
    raccourcis, sans changer le résultat : le recalcul des métriques est SAUTÉ si
    `metrics_fingerprint` n'a pas bougé depuis le dernier calcul enregistré en base,
    et sinon les calculs par séance déjà faits sont réutilisés (`MetricsCache`).
    Sans lui (CLI, synchronisation, tests), recalcul intégral à chaque appel.
    """
    conf = settings(load_config(workspace))
    seen = set()
    counts = {"indexed": 0, "unchanged": 0, "removed": 0}
    for path in discover(workspace):
        rel = path.relative_to(workspace).as_posix()
        seen.add(rel)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        known = conn.execute("SELECT sha256 FROM source_file WHERE path = ?", (rel,)).fetchone()
        if known and known[0] == digest:
            counts["unchanged"] += 1
            continue
        _purge(conn, rel)
        kind, data, arc_version, parsed_ok, issues = read_file(path, rel, conf)
        twin = None
        twin_key = None
        if kind == "activity":
            # Même règle pour les deux espaces d'identifiants (#68) : une séance
            # Intervals.icu décrite dans deux fichiers compterait sinon deux fois.
            twin_key = next((k for k in REF_COLUMNS if data.get(k)), None)
        if twin_key:
            twin = conn.execute(f"SELECT source_path FROM activity WHERE {twin_key} = ? AND source_path != ?",
                                (data[twin_key], rel)).fetchone()
        if twin:
            # Même séance décrite dans deux fichiers : une seule charge. Le fichier
            # écarté est relu à chaque passe (sha vide) pour reprendre la main si l'autre disparaît.
            issues.append(f"doublon de {twin[0]} (même {twin_key}) : non compté")
            digest = ""
        elif kind is not None and parsed_ok != "no" and (kind not in ("decision", "gear_inspection") or parsed_ok == "ok"):
            # `decision` (#100, revue de code) : PAS de repli légitime — il n'existe
            # aucun format hérité pour ce type neuf (contrairement à `activity`/
            # `health`/…, où `parsed_ok = "partial"` porte une vraie lecture best-
            # effort). Un bloc `decision` invalide (`read_file` retombe alors sur
            # `data = {}`, tout NULL) ne doit donc jamais être stocké : ce serait une
            # ligne fantôme dans `decisions_query`/le futur journal (#55), aussi
            # invisible dans `backfill_items` (exclu explicitement, voir plus bas)
            # que dans le tableau de bord — silencieusement fausse plutôt qu'absente.
            store(conn, rel, kind, data, arc_version)
        conn.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel, kind, digest, path.stat().st_mtime, arc_version, parsed_ok, _j(issues)),
        )
        counts["indexed"] += 1
    for (rel,) in conn.execute("SELECT path FROM source_file").fetchall():
        if rel not in seen:
            _purge(conn, rel)
            conn.execute("DELETE FROM source_file WHERE path = ?", (rel,))
            counts["removed"] += 1
    # #69 : collisions de `week_start` entre fichiers (fichier dédié vs plan
    # multi-semaines, ou deux plans qui se recouvrent) — recalculé en ENTIER à
    # CHAQUE passage, changement ou non (voir la docstring de la fonction : un
    # fichier gagnant supprimé/inchangé pas de ce passage ne doit jamais laisser
    # une semaine ni un avertissement périmés).
    _mark_week_shadowing(conn)
    # Échantillons FIT (#42) — table dédiée `sample_file`, jamais `source_file` (voir
    # `ingest_samples`) : sa propre découverte/nettoyage ne touche donc jamais la boucle
    # ci-dessus. Le rattachement à `activity` n'est plus résolu ICI (il l'était par
    # rowid dans une version antérieure, bug corrigé — voir `samples()`) : l'ordre
    # d'exécution par rapport au passage Markdown n'a donc plus d'importance pour la
    # correction, seulement `sport` (déjà en base pour un fichier réingéré CETTE passe
    # puisque le passage Markdown ci-dessus vient de le (ré)écrire).
    counts["fit_ingestion"] = ingest_samples(conn, workspace)
    fingerprint = metrics_fingerprint(conn, conf, today or date.today().isoformat())
    known = conn.execute("SELECT value FROM meta WHERE key = 'metrics_fingerprint'").fetchone()
    if metrics_cache is not None and known and known[0] == fingerprint:
        counts["metrics"] = "skipped"
    else:
        compute_metrics(conn, conf, today, metrics_cache)
        counts["metrics"] = "computed"
    # Toujours réécrite après un calcul, cache ou non : une CLI qui recalcule la base
    # partagée avec le tableau de bord la laisse cohérente pour lui.
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('metrics_fingerprint', ?)", (fingerprint,))
    # `arc_gap.ASSUMPTIONS` (#44) fusionné à celles d'`arc_metrics` : la section
    # « Hypothèses » du tableau de bord (`/api/summary` -> `web/js/app.js`) doit
    # exposer la limite connue du modèle de pente (généreux en descente) au même titre que les autres approximations du projet — jamais
    # cachée dans un module que cette agrégation oublierait. `arc_decoupling.ASSUMPTIONS`
    # (#45) fusionné à PART, sous des clés préfixées `decoupling_*` (revue de code) :
    # `arc_decoupling` et `arc_gap` partagent des noms de clé (`model`,
    # `stopped_samples`, `restricted_to_run_family`...) qu'un simple `{**G.ASSUMPTIONS,
    # **DC.ASSUMPTIONS}` écraserait silencieusement au lieu d'exposer les deux.
    decoupling_assumptions = {f"decoupling_{key}": value for key, value in DC.ASSUMPTIONS.items()}
    # `arc_climb.ASSUMPTIONS` (#46) fusionné à PART lui aussi, sous des clés
    # préfixées `vam_*` — même raison que `decoupling_*` ci-dessus (collision de
    # noms de clé possible avec `arc_gap`/`arc_decoupling`, ex. "model",
    # "restricted_to_run_family").
    vam_assumptions = {f"vam_{key}": value for key, value in VC.ASSUMPTIONS.items()}
    # `arc_descent.ASSUMPTIONS` (#47) fusionné à PART lui aussi, sous des clés
    # préfixées `descent_*` — même raison que `decoupling_*`/`vam_*` ci-dessus
    # (collision possible, ex. "model", "restricted_to_run_family", "grade_classes").
    descent_assumptions = {f"descent_{key}": value for key, value in DS.ASSUMPTIONS.items()}
    # `arc_durability.ASSUMPTIONS` (#48) fusionné à PART lui aussi, sous des clés
    # préfixées `durability_*` — même raison que `decoupling_*`/`vam_*`/`descent_*`
    # ci-dessus (collision possible, ex. "model", "restricted_to_run_family").
    durability_assumptions = {f"durability_{key}": value for key, value in DU.ASSUMPTIONS.items()}
    # `arc_slope_model.ASSUMPTIONS` (#58) fusionné à PART lui aussi, sous des clés
    # préfixées `slope_model_` — même raison que `decoupling_*`/`vam_*`/`descent_*`/
    # `durability_*` ci-dessus (collision possible, ex. "model", "fallback").
    slope_model_assumptions = {f"slope_model_{key}": value for key, value in SL.ASSUMPTIONS.items()}
    # `arc_energy.ASSUMPTIONS` (dépense énergétique modèle vs Garmin) fusionné à
    # PART lui aussi, sous des clés préfixées `energy_` — même raison que
    # `decoupling_*`/`vam_*`/`descent_*`/`durability_*`/`slope_model_*` ci-dessus
    # (collision possible, ex. "model", "no_exception").
    energy_assumptions = {f"energy_{key}": value for key, value in EN.ASSUMPTIONS.items()}
    # `arc_cs.ASSUMPTIONS` (#169) fusionné à PART, sous des clés préfixées `cs_`.
    cs_assumptions = {f"cs_{key}": value for key, value in CS.ASSUMPTIONS.items()}
    for key, value in (("settings", _j(conf)),
                       ("assumptions", _j({**M.ASSUMPTIONS, **G.ASSUMPTIONS, **decoupling_assumptions,
                                           **vam_assumptions, **descent_assumptions,
                                           **durability_assumptions, **slope_model_assumptions,
                                           **energy_assumptions, **cs_assumptions})),
                       ("today", today or date.today().isoformat())):
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    conn.commit()
    return counts


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill_items(conn) -> List[dict]:
    """Fichiers qui ne sont pas au contrat, ou incomplets, et ce qui leur manque.

    L'attendu tient compte de la configuration : en `morning_check = "off"`, un
    fichier santé sans HRV n'est pas une dette (expected_keys ne demande rien) ;
    un workspace sans nutritionniste n'a pas de `nutrition/` à remplir.

    Inclut aussi (#69) un fichier par ailleurs VALIDE (`parsed_ok = "ok"`) dont
    une semaine est éclipsée par une collision de `week_start` avec un autre
    fichier (`_mark_week_shadowing`) : ce n'est pas un fichier hors contrat,
    mais son plan est ignoré du tableau de bord tant que la collision n'est pas
    résolue — une dette réelle, actionnable (réécrire le fichier), qui mérite
    la même visibilité qu'une dette de contrat plutôt que de rester invisible.
    """
    items = []
    for row in conn.execute(
        "SELECT path, kind, parsed_ok, issues FROM source_file "
        # `decision` (#54) exclu au même titre que `athlete`/`objective` : c'est un
        # type NEUF, jamais écrit avant ce contrat — aucun fichier historique à
        # reprendre, jamais de dette de backfill à faire apparaître pour lui.
        "WHERE kind IS NOT NULL AND kind NOT IN ('athlete', 'objective', 'decision', 'gear_inspection') "
        f"AND (parsed_ok != 'ok' OR issues LIKE '%{_WEEK_COLLISION_MARKER}%') ORDER BY path"
    ).fetchall():
        # Seul un fichier hors contrat (sans bloc, bloc invalide, illisible) est une dette.
        # Une clé facultative absente d'un bloc valide (pas de verdict ce jour-là, pas de
        # splits sur une séance de renfo) reste visible dans `issues`, sans être à reprendre.
        issues = json.loads(row["issues"] or "[]")
        # `collision` (#69, revue de code should-fix 2) : distingue un fichier
        # RÉELLEMENT hors contrat (`status != "ok"`, à réécrire) d'un fichier
        # par ailleurs valide, seulement éclipsé par une collision de
        # `week_start` — l'action attendue n'est pas la même (trim/suppression
        # de l'entrée en trop, jamais une réécriture du bloc ```arc) ; voir
        # `write_backfill`, qui les liste dans deux sections séparées.
        items.append({
            "path": row["path"], "kind": row["kind"], "status": row["parsed_ok"], "issues": issues,
            "collision": any(_WEEK_COLLISION_MARKER in i for i in issues),
        })
    return items


def write_backfill(conn, workspace: Path) -> Path:
    items = backfill_items(conn)
    # #69, revue de code should-fix 2 : un item de collision (fichier VALIDE au
    # contrat, seulement éclipsé par un autre pour une semaine) n'est pas une
    # dette de contrat — le mélanger à la liste « à réécrire » ferait suivre au
    # skill `arc-backfill` (ou à l'athlète lisant ce fichier) ses étapes de
    # réécriture d'un bloc ```arc sur un fichier qui en a déjà un parfaitement
    # valide. Deux sections séparées, avec l'action qui convient à chacune.
    contract_items = [i for i in items if i["status"] != "ok"]
    collision_items = [i for i in items if i["status"] == "ok" and i["collision"]]
    lines = [
        "# Backfill — fichiers à réécrire au contrat ```arc",
        "",
        "> Généré par `scripts/arc_index.py backfill-plan`. Ne pas éditer : relancer la commande.",
        "",
    ]
    lines += [
        "## Fichiers hors contrat",
        "",
        "> Chaque fichier doit être réécrit avec un bloc ```arc conforme au skill",
        "> `workspace-data-contract`, en conservant le texte existant sous le bloc.",
        "",
        f"**{len(contract_items)} fichier(s)** à traiter.",
        "",
    ]
    for item in contract_items:
        lines.append(f"- [ ] `{item['path']}` — {item['kind']} ({item['status']})")
        for issue in item["issues"]:
            lines.append(f"    - {issue}")
    lines += [
        "",
        "## Collisions de semaine (#69)",
        "",
        "> Ces fichiers sont déjà VALIDES au contrat — n'y ajoutez ni ne réécrivez",
        "> aucun bloc ```arc. Une autre entrée décrit déjà la même semaine et fait",
        "> foi (le fichier DÉDIÉ de cette semaine, sinon le chemin le plus petit —",
        "> voir `skills/workspace-data-contract/SKILL.md`, section « week »).",
        "> Corrigez en RETIRANT ou en SUPPRIMANT l'entrée `weeks[]` en trop (ou le",
        "> fichier entier s'il ne porte plus que des semaines déjà couvertes",
        "> ailleurs) — jamais en réécrivant un bloc qui est déjà correct.",
        "",
        f"**{len(collision_items)} fichier(s)** concerné(s).",
        "",
    ]
    for item in collision_items:
        lines.append(f"- [ ] `{item['path']}`")
        for issue in item["issues"]:
            if _WEEK_COLLISION_MARKER in issue:
                lines.append(f"    - {issue}")
    out = workspace / ".arc/backfill.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Validation d'un fichier (appelée par les agents après chaque écriture)
# ---------------------------------------------------------------------------


def _validate_gear_inspection_links(path: Path, block: dict, warnings: List[str]) -> None:
    """#135 : `gear_id` déclaré comme chaussure dans le profil (et non un slug de matériel #134),
    `previous` existant, de la même paire et antérieur. Avertissements seulement."""
    root = path.parent.parent
    profile = root / "planning" / "Runner_Profile.md"
    gear_id = block.get("gear_id")
    if profile.is_file() and isinstance(gear_id, str):
        declared = {g.get("gear_id") for g in (L.parse_profile(profile.read_text(encoding="utf-8")).get("gear") or [])}
        if gear_id not in declared:
            warnings.append(f"gear_id « {gear_id} » n'est pas une chaussure déclarée dans « ### Chaussures » du "
                            "profil (matériel hors chaussures ? l'inspection photo ne concerne que les chaussures)")
    previous = block.get("previous")
    if isinstance(previous, str) and not C._invalid_workspace_path_reason(previous):
        if not (root / previous).is_file():
            warnings.append(f"previous : {previous} introuvable")
        pm = _GEAR_INSPECTION_FILENAME_RE.match(Path(previous).name)
        if pm:
            if pm.group(2) != gear_id:
                warnings.append(f"previous : inspection d'une autre paire ({pm.group(2)}, pas {gear_id})")
            if isinstance(block.get("date"), str) and pm.group(1) >= block["date"]:
                warnings.append(f"previous : {pm.group(1)} n'est pas antérieure à la date de l'inspection")


def validate_file(path: Path) -> Tuple[bool, List[str], List[str]]:
    if not path.is_file():
        return False, [f"{path} : fichier introuvable"], []
    if path.name in ("Runner_Profile.md", "active_objective.md"):
        return True, [], ["fichier édité par l'humain : pas de bloc ```arc attendu (puces du modèle)"]
    try:
        block = C.extract_block(path.read_text(encoding="utf-8"))
    except C.ContractError as exc:
        return False, [str(exc)], []
    if block is None:
        return False, ["bloc ```arc absent — voir le skill workspace-data-contract"], []
    errors, warnings = C.validate(block)
    expected = classify(f"{path.parent.name}/{path.name}")
    if expected and block.get("kind") in C.KINDS and block.get("kind") != expected:
        warnings.append(f"kind « {block.get('kind')} » inattendu pour ce fichier (« {expected} » attendu)")
    if block.get("kind") == "decision":
        # #100, revue de code : `date` du bloc doit correspondre à la date du nom de
        # fichier (`AAAA-MM-JJ_decision_<slug>.md`) — ce n'est pas une erreur de
        # contrat (le fichier reste indexable, `classify()` ne dépend que du nom),
        # mais une décision retrouvée par sa date de fichier puis lue avec une AUTRE
        # `date` dans le bloc induirait `session_ref`/le tableau de bord en erreur.
        filename_day = L.filename_date(path.name)
        block_day = block.get("date")
        if filename_day and isinstance(block_day, str) and filename_day != block_day:
            warnings.append(
                f"date du nom de fichier ({filename_day}) différente de decision.date "
                f"({block_day})"
            )
        # #55, revue de code : un fichier `decision` hors du format attendu (slug
        # avec un point, ou pas directement sous `planning/`) reste indexable — le
        # bloc ```arc fait foi même quand le nom ne dit rien (voir `read_file`) —
        # mais son identifiant `/api/decision/<id>` (nom de fichier sans extension,
        # jamais de point accepté, voir `arc_serve.DECISION_ID_RE`) ne peut alors
        # plus le désigner : il apparaît dans le journal mais son lien de détail
        # rend 404. `path.parent.name` (jamais le chemin complet, indisponible
        # ici : cette fonction ne reçoit qu'un `Path`, pas la racine du workspace)
        # suffit à détecter un sous-dossier immédiat (`planning/archive/...`).
        if not _DECISION_FILENAME_RE.match(path.name) or path.parent.name != "planning":
            warnings.append(
                "fichier « decision » hors du format attendu "
                "(`planning/AAAA-MM-JJ_decision_<slug>.md`, slug SANS point, "
                "directement sous `planning/`) — le tableau de bord (#55) l'affiche "
                "dans le journal mais ne pourra jamais résoudre son détail par id."
            )
    if block.get("kind") == "gear_inspection":
        # #135 : `gear/AAAA-MM-JJ_<gear_id>_inspection.md` — la date et le `gear_id` du nom de fichier
        # doivent dire la même chose que le bloc (sinon l'inspection est retrouvée sous une autre paire
        # ou une autre date que celle que le nom annonce). Avertissement : le bloc fait foi à l'index.
        m = _GEAR_INSPECTION_FILENAME_RE.match(path.name)
        if not m or path.parent.name != "gear":
            warnings.append("fichier « gear_inspection » hors du format attendu "
                            "(`gear/AAAA-MM-JJ_<gear_id>_inspection.md`) — non indexé s'il n'est pas sous gear/.")
        else:
            _validate_gear_inspection_links(path, block, warnings)
            if isinstance(block.get("date"), str) and m.group(1) != block["date"]:
                warnings.append(f"date du nom de fichier ({m.group(1)}) différente de gear_inspection.date "
                                f"({block['date']})")
            if isinstance(block.get("gear_id"), str) and m.group(2) != block["gear_id"]:
                warnings.append(f"gear_id du nom de fichier ({m.group(2)}) différent de gear_inspection.gear_id "
                                f"({block['gear_id']})")
    return not errors, errors, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def hrv_baseline_today(conn, conf: dict, today: date) -> dict:
    """Point du jour de la ligne de base HRV personnelle (#34) — pour la CLI et pour les
    agents en headless (`/garmin-daily-sync`, ou tout appel sans tableau de bord lancé).

    Respecte `[health].morning_check` : rien n'est calculé hors `"full"` (voir
    `arc_metrics.ASSUMPTIONS["hrv_baseline"]` — décision documentée : en `"minimal"`,
    seule la readiness est exposée ; en `"off"`, aucune donnée de santé n'est récupérée).
    """
    mode = conf["morning_check"]
    if mode != "full":
        return {"status": None, "morning_check": mode,
                "reason": "ligne de base personnelle calculée seulement en "
                          '[health].morning_check = "full"'}
    rows = conn.execute(
        "SELECT date, hrv_overnight_ms FROM health_day WHERE hrv_overnight_ms IS NOT NULL"
    ).fetchall()
    hrv_by_date = {row[0]: row[1] for row in rows}
    point = M.hrv_baseline_series(hrv_by_date, today, today)[0]
    return {**point, "morning_check": mode}


def athlete_sleep_need_s(row) -> float:
    """Résout le besoin de sommeil à partir d'une ligne `athlete` (dict-like portant
    `sleep_need_s` — `sqlite3.Row` ou `dict`, tous deux indexables par nom de colonne
    — ou `None`) : la valeur du profil si présente et non nulle, sinon le défaut
    moteur (`arc_metrics.SLEEP_NEED_DEFAULT_S`, 7 h 30).

    Point de résolution UNIQUE, partagé par la CLI `sleep-debt` ci-dessous et par
    `arc_serve.py` (`/api/summary`, `/api/health`) — revue de code PR #82 : trois
    copies de `(row["sleep_need_s"] if row else None) or DEFAULT` avaient dérivé.
    """
    value = row["sleep_need_s"] if row is not None else None
    return value or M.SLEEP_NEED_DEFAULT_S


def sleep_debt_today(conn, conf: dict, today: date) -> dict:
    """Dette de sommeil 7 j du jour (#37) — pour la CLI et pour les agents en headless.

    Respecte `[health].morning_check` : rien n'est calculé hors `"full"` (même porte
    que `hrv_baseline_today` — voir `arc_metrics.ASSUMPTIONS["sleep_debt"]`).
    """
    mode = conf["morning_check"]
    if mode != "full":
        return {"sleep_debt_7d_s": None, "nights_counted": None, "morning_check": mode,
                "reason": "dette de sommeil calculée seulement en "
                          '[health].morning_check = "full"'}
    rows = conn.execute(
        "SELECT date, sleep_total_s FROM health_day WHERE sleep_total_s IS NOT NULL"
    ).fetchall()
    sleep_by_date = {row[0]: row[1] for row in rows}
    athlete = conn.execute("SELECT sleep_need_s FROM athlete LIMIT 1").fetchone()
    need_s = athlete_sleep_need_s(athlete)
    result = M.sleep_debt_7d(sleep_by_date, today, need_s)
    return {**result, "morning_check": mode}


def heat_acclimation_today(conn, conf: dict, today: date) -> dict:
    """Acclimatation à la chaleur sur les 14 j se terminant à `today` (#38) — pour la
    CLI et pour les agents en headless (`coach`, `course-strategist` pour une course
    dont la météo prévue est chaude).

    Contrairement à `hrv_baseline_today`/`sleep_debt_today`, n'est pas soumis à
    `[health].morning_check` : la jointure activité/météo ne dépend pas du bilan
    matinal (voir `arc_metrics.ASSUMPTIONS["heat_acclimation"]`).
    """
    window_days = M.HEAT_WINDOW_DAYS
    start = (today - timedelta(days=window_days - 1)).isoformat()
    end = today.isoformat()
    activities = [dict(r) for r in conn.execute(
        "SELECT date, sport, duration_s, location FROM activity WHERE date >= ? AND date <= ?",
        (start, end)).fetchall()]
    weather_rows = [dict(r) for r in conn.execute(
        "SELECT date, location, temp_max_c FROM weather_day WHERE date >= ? AND date <= ?",
        (start, end)).fetchall()]
    return M.heat_acclimation(activities, weather_rows, today, conf["heat_threshold_c"], window_days)


def gear_attribution(conn, garmin_gear: Optional[str], chat_gear: Optional[str]) -> dict:
    """Commande « gear-attribution » (#133) : priorité athlète (chat) > Garmin > défaut, résolue par
    `arc_metrics.resolve_gear_attribution` à partir des puces du profil (colonne `garmin_uuid`)."""
    gear_defs = [dict(r) for r in conn.execute(
        "SELECT gear_id, name, garmin_uuid, ignored FROM gear")]
    # Tout ce qui n'a pas la forme d'un uuid (ex. le texte « No gear data found for activity… » de
    # `get_activity_gear`) est ignoré : jamais interprété comme un matériel.
    uuids = [u.strip() for u in (garmin_gear or "").split(",") if L.GEAR_GARMIN_UUID_RE.match(u.strip())]
    chat = None
    if chat_gear and chat_gear.strip():
        # `gear_id` toujours valide au contrat : un id du profil tel quel, sinon un nom du profil
        # (« Nike Pegasus »), sinon le slug du libellé (paire absente du profil, regroupée « inconnue »).
        raw = chat_gear.strip()
        ids = {g["gear_id"] for g in gear_defs if not g["ignored"]}
        slug = C.gear_slug(raw)
        if raw in ids:
            chat = raw
        elif slug in ids:
            chat = slug
        else:
            by_name = [g["gear_id"] for g in gear_defs if not g["ignored"] and C.gear_slug(g["name"] or "") == slug]
            chat = by_name[0] if len(by_name) == 1 else (slug or None)
    return M.resolve_gear_attribution(gear_defs, uuids, chat)


def _gear_defs(conn) -> List[dict]:
    """Paires déclarées PRISES EN COMPTE (`ignored = 0`, #133) — lues par `gear_mileage` ET par le
    bilan de carrière (#135) : une seule requête, jamais retapée à deux endroits."""
    return [dict(r) for r in conn.execute(
        "SELECT gear_id, name, start_date, threshold_m, is_default AS \"default\", retired, collision_base, "
        "start_m, usage FROM gear WHERE ignored = 0")]


def _gear_activities(conn) -> List[dict]:
    """Séances candidates à l'attribution de matériel (partagé `gear_mileage` / `gear_career`)."""
    activities = [dict(r) for r in conn.execute(
        # `date` : indispensable à `M.attribute_gear` pour filtrer l'attribution par
        # défaut par `depuis` (revue PR #85, blocker 1) — jamais utilisée pour
        # exclure une activité à `gear_id` explicite. `id`/`name`/`duration_s` : bilan de carrière.
        "SELECT id, name, duration_s, sport, distance_m, gear_id, gear_source, date, garmin_activity_id, "
        "intervals_activity_id, strava_activity_id, source_path "
        "FROM activity WHERE gear_id IS NOT NULL OR sport IN "
        f"({', '.join('?' for _ in M.GEAR_WEAR_SPORTS)}) ORDER BY date, id", M.GEAR_WEAR_SPORTS).fetchall()]
    for a in activities:
        a["refs"] = [str(v) for v in (a.pop("garmin_activity_id"), a.pop("intervals_activity_id"),
                                       a.pop("strava_activity_id"), a.pop("source_path")) if v is not None]
    return activities


def gear_mileage(conn, today: Optional[date] = None, run_refs: Optional[List[str]] = None) -> dict:
    """Kilométrage par chaussure (#40) — pour la CLI et pour les agents en headless
    (`coach`, rapport hebdomadaire). N'est pas soumis à `[health].morning_check` :
    ne dépend d'aucune donnée de santé, seulement du profil et des activités.

    #132 : départ (`start_m`) compris dans le cumul ; prévision de retraite calculée
    contre `today` (défaut : la date du jour, comme les autres KPI) ; `run_refs`
    (garmin_activity_id, intervals_activity_id ou chemin de fichier des séances du run)
    ajoute `crossed_in_run` — voir `arc_metrics.ASSUMPTIONS["gear_mileage"]`."""
    return M.gear_mileage(_gear_activities(conn), _gear_defs(conn), today or date.today(), run_refs)


def _equipment_defs(conn) -> List[dict]:
    defs = []
    for r in conn.execute(
            "SELECT gear_id, name, category, start_date, maintenance_date, retired, kits, threshold_m, "
            "threshold_s, threshold_sessions, threshold_days, start_m, start_s, start_sessions, "
            "collision_base, parse_warnings FROM equipment"):
        d = {k: v for k, v in dict(r).items() if v is not None}
        d["kits"] = json.loads(d["kits"]) if d.get("kits") else []
        d["parse_warnings"] = json.loads(d["parse_warnings"]) if d.get("parse_warnings") else []
        d["retired"] = bool(d.get("retired"))
        defs.append(d)
    return defs


def _equipment_activities(conn) -> List[dict]:
    activities = [dict(r) for r in conn.execute(
        "SELECT id, name, sport, date, distance_m, duration_s, gear_ids, garmin_activity_id, "
        "intervals_activity_id, strava_activity_id, source_path FROM activity WHERE gear_ids IS NOT NULL")]
    for a in activities:
        try:
            a["gear_ids"] = [g for g in json.loads(a["gear_ids"]) if isinstance(g, str)]
        except (TypeError, ValueError):
            a["gear_ids"] = []
        a["refs"] = [str(v) for v in (a.pop("garmin_activity_id"), a.pop("intervals_activity_id"),
                                       a.pop("strava_activity_id"), a.pop("source_path")) if v is not None]
    return activities


def equipment_usage(conn, today: Optional[date] = None, run_refs: Optional[List[str]] = None,
                    last_pass: Optional[date] = None) -> dict:
    """Matériel hors chaussures (#134) — commande « equipment » : usage (distance, durée, séances,
    jours), déclencheurs typés, kits. N'est PAS soumis à `[health].morning_check` (aucune donnée de
    santé). `gear` (chaussures) reste inchangé. Voir `arc_metrics.ASSUMPTIONS["equipment_usage"]`."""
    defs = _equipment_defs(conn)
    shoe_ids = [r["gear_id"] for r in conn.execute("SELECT gear_id FROM gear")]
    return M.equipment_usage(_equipment_activities(conn), defs, today or date.today(), run_refs, last_pass, shoe_ids)


def equipment_kit(conn, kit: str, sport: Optional[str]) -> dict:
    """Commande « equipment --kit » : objets à attribuer à la séance quand l'athlète déclare un kit.
    `sport` : normalisé (casse) et validé contre `arc_contract.SPORTS` — inconnu → `ConfigError`."""
    if sport is not None:
        sport = sport.strip().lower()
        if sport not in C.SPORTS:
            raise ConfigError(f"--sport : sport inconnu « {sport} » (attendu : {', '.join(C.SPORTS)}).")
    return M.kit_members(_equipment_defs(conn), C.gear_slug(kit), sport)


def equipment_race_check(conn, race_plan: Optional[str], today: date,
                         workspace: Optional[Path] = None) -> dict:
    """Commande « equipment --race-plan » : croise le `gear` du plan de course (chemin du fichier ou
    « » = prochain plan dont `race_date` >= today, sinon le plus récent) avec l'inventaire. Rend
    `{"race_plan": <chemin>, "race_name": ..., "gear": [...], ...}` ou `{"error": ...}`."""
    if race_plan and workspace is not None and (os.path.isabs(race_plan) or race_plan.startswith(".")):
        # chemin absolu ou « ./… » : ramené au chemin relatif au workspace, comme `source_path`
        if os.path.isabs(race_plan):
            try:
                race_plan = Path(race_plan).resolve().relative_to(Path(workspace).resolve()).as_posix()
            except ValueError:
                pass
        else:
            race_plan = os.path.normpath(race_plan).replace(os.sep, "/")
    if race_plan:
        rows = conn.execute("SELECT source_path, race_name, race_date, data_json FROM race_plan "
                            "WHERE source_path = ? OR source_path LIKE ?", (race_plan, f"%{race_plan}")).fetchall()
    else:
        rows = conn.execute("SELECT source_path, race_name, race_date, data_json FROM race_plan "
                            "WHERE race_date >= ? ORDER BY race_date", (today.isoformat(),)).fetchall()
        if not rows:
            rows = conn.execute("SELECT source_path, race_name, race_date, data_json FROM race_plan "
                                "ORDER BY race_date DESC").fetchall()
    if not rows:
        return {"error": "aucun plan de course indexé" if not race_plan else f"plan de course introuvable : {race_plan}"}
    row = rows[0]
    try:
        gear = json.loads(row["data_json"] or "{}").get("gear") or []
    except ValueError:
        gear = []
    usage = equipment_usage(conn, today)
    shoes = gear_mileage(conn, today)["shoes"]
    check = M.race_gear_check(gear, usage["items"], shoes)
    return {"race_plan": row["source_path"], "race_name": row["race_name"], "race_date": row["race_date"],
            "inventory_empty": not usage["items"] and not shoes, **check}


def performance_index(conn, today: Optional[date] = None) -> dict:
    """Indices de performance ITRA/UTMB (#62) — pour la CLI (`arc_index.py
    performance-index`) et le tableau de bord (`/api/performance-index`,
    `/api/summary.performance_index`). N'est pas soumis à `[health].
    morning_check` : ne dépend d'aucune donnée de santé, seulement de ce que
    l'athlète a écrit dans son profil (voir `arc_legacy.parse_performance_index`
    — aucune récupération réseau, ici ni ailleurs).

    `history` : tous les relevés, triés par `(date, ordinal)` — `ordinal` est
    l'ordre d'apparition dans le fichier (voir `arc_legacy.
    parse_performance_index`), jamais l'ordre d'insertion SQLite implicite, pour
    que deux relevés de dates différentes mais de catégories différentes à la
    même date gardent un ordre reproductible d'une lecture à l'autre — condition
    aussi pour que `current` (ci-dessous) soit déterministe. `current` : le
    relevé le plus RÉCENT pour chaque couple (kind, category) — `category` vaut
    `None` pour un indice général.

    `warnings` combine deux sources bien distinctes :
    1. persistées par `arc_index.store` (lignes illisibles ignorées, doublons
       exacts résolus — voir `arc_legacy.parse_performance_index`), jamais
       réimprimées à chaque réindexation (le fichier doit changer pour être
       reparsé) ;
    2. calculées ICI, à CHAQUE appel, contre `today` (par défaut la date du
       jour) : un relevé dont la date est postérieure à `today` (revue de code
       #109, 2e tour) — jamais stockée, parce que « futur » se juge au moment
       de la LECTURE, pas de l'écriture (un relevé écrit hier comme « futur »
       ne l'est peut-être déjà plus aujourd'hui, sans que le fichier n'ait
       changé — un avertissement figé en base à l'écriture resterait alors
       périmé indéfiniment).

    Tout est vide si l'athlète n'a rien déclaré : c'est l'appelant (dashboard)
    qui affiche alors l'état vide, jamais une valeur inventée."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, kind, category, value FROM performance_index ORDER BY date, ordinal")]
    current: Dict[Tuple[str, Optional[str]], dict] = {}
    for row in rows:
        current[(row["kind"], row.get("category"))] = row
    warnings = [r["message"] for r in conn.execute(
        "SELECT message FROM performance_index_warning ORDER BY source_path, ordinal")]
    today_iso = (today or date.today()).isoformat()
    for row in rows:
        if row["date"] > today_iso:
            label = row["kind"] + (f" {row['category']}" if row.get("category") else "")
            warnings.append(f"date future ({row['date']} > {today_iso}) pour {label} : {row['value']:g} — "
                            "relevé conservé tel quel, à vérifier.")
    return {"history": rows, "current": list(current.values()), "warnings": warnings}


def fueling_trend(conn, today: date) -> dict:
    """Glucides/h et taux de sudation sur les sorties longues (#41) — pour la CLI
    (`arc_index.py fueling`) et pour `course-strategist` en headless (plafond
    réaliste d'un plan de course). N'est pas soumis à `[health].morning_check` :
    ne dépend d'aucune donnée de santé, seulement des activités déjà indexées.
    Voir `arc_metrics.ASSUMPTIONS["fueling"]`."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, distance_m, duration_s, carbs_g, sweat_rate_l_h FROM activity "
        "WHERE duration_s > ? AND sport IN "
        f"({', '.join('?' for _ in M.FUELING_SPORTS)})",
        (M.LONG_RUN_MIN_DURATION_S, *M.FUELING_SPORTS)).fetchall()]
    result = M.fueling_trend(rows, today)
    result["carbs_ceiling_g_h"] = M.fueling_carbs_ceiling(result["max_carbs_per_hour_g"])
    result["margin_g_h"] = M.FUELING_MAX_MARGIN_G_H
    result["target_band_g_h"] = list(M.FUELING_TARGET_BAND_G_H)
    return result


# ---------------------------------------------------------------------------
# Journal des décisions (#54, consommé par le dashboard #55 et le resume #56)
# ---------------------------------------------------------------------------


# Exclus par `decisions_query(..., active=True)` (#100, revue de code) : une
# décision remplacée (`supersedes`, voir SKILL.md « Remplacer une décision ») ou
# refusée par l'athlète ne doit plus polluer le journal COURANT, sans pour
# autant disparaître de l'historique complet (toujours accessible sans ce filtre).
DECISION_INACTIVE_OUTCOMES = ("superseded", "rejected_by_athlete")


def decisions_query(conn, today: Optional[date] = None, days: Optional[int] = None,
                     trigger: Optional[str] = None, on_date: Optional[str] = None,
                     outcome: Optional[str] = None, active: bool = False) -> List[dict]:
    """Décisions journalisées, plus récentes d'abord (`date` puis `created_at_utc`).

    `on_date` (une date précise) prime sur `days` (fenêtre glissante se terminant
    à `today`, INCLUSE) — les deux filtres ne se combinent pas, comme les autres
    sous-commandes de ce module (`--activity` prime sur `--weeks`) ; la CLI
    (`main`) rejette explicitement `--date` ET `--days` ensemble plutôt que de
    laisser cette précédence silencieuse tromper un appelant headless. Sans
    aucun filtre de date, rend TOUTES les décisions connues : à l'appelant de
    borner avec `--days` pour un usage headless (#56) sur un historique qui
    grossit. `trigger`/`outcome`/`active` filtrent en plus, quel que soit le
    mode de sélection de date — `active=True` exclut `DECISION_INACTIVE_OUTCOMES`
    (voir « Remplacer une décision » dans SKILL.md) et se combine avec `outcome`
    (rare en pratique : `outcome="applied", active=True` est juste redondant,
    jamais contradictoire, puisque `applied` n'est jamais inactif).

    Tri sur `created_at_utc` (créée à l'écriture, `arc_contract.
    decision_created_at_utc`), PAS sur `created_at` (texte ISO local : trier du
    texte mélangerait l'ordre de décisions écrites depuis des fuseaux
    différents, #100 revue de code).
    """
    where, params = [], []
    if on_date:
        where.append("date = ?")
        params.append(on_date)
    elif days is not None:
        end = today or date.today()
        start = (end - timedelta(days=days - 1)).isoformat() if days > 0 else end.isoformat()
        where.append("date BETWEEN ? AND ?")
        params.extend([start, end.isoformat()])
    if trigger:
        where.append("trigger = ?")
        params.append(trigger)
    if outcome:
        where.append("outcome = ?")
        params.append(outcome)
    if active:
        placeholders = ", ".join("?" for _ in DECISION_INACTIVE_OUTCOMES)
        where.append(f"(outcome IS NULL OR outcome NOT IN ({placeholders}))")
        params.extend(DECISION_INACTIVE_OUTCOMES)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"SELECT * FROM decision {clause} ORDER BY date DESC, created_at_utc DESC", params
    ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        for key in ("inputs", "rule_ids", "sources", "before", "after", "session_ref"):
            raw = d.pop(f"{key}_json", None)
            d[key] = json.loads(raw) if raw else None
        d.pop("body_md", None)
        d.pop("data_json", None)
        d.pop("arc_version", None)
        d.pop("created_at_utc", None)   # détail d'implémentation du tri, pas une donnée du contrat
        out.append(d)
    return out


# Reconnaissance d'un chemin `sources`/`supersedes`/`session_ref.week` de décision
# (#55) PAR SON NOM SEUL, jamais par son contenu — un chemin non reconnu (hors
# workspace, `resources/*`, fichier libre) rend `kind: "other"` et reste un simple
# texte côté dashboard, jamais un lien vers un fichier arbitraire.
_SOURCE_HEALTH_RE = re.compile(r"^medical/(\d{4}-\d{2}-\d{2})_health\.md$")
_SOURCE_WEATHER_RE = re.compile(r"^medical/(\d{4}-\d{2}-\d{2})_meteo\.md$")
_SOURCE_NUTRITION_RE = re.compile(r"^nutrition/(\d{4}-\d{2}-\d{2})_nutrition\.md$")
_SOURCE_ACTIVITY_RE = re.compile(r"^activities/(\d{4}-\d{2}-\d{2})_[^/]+\.md$")
_SOURCE_WEEK_RE = re.compile(r"^planning/Semaine_(\d{4}-\d{2}-\d{2})\.md$")
# Ancré `^planning/[^/]+$` (#55, revue de code) — jamais `Path(path).name` seul :
# celui-ci matchait le nom de fichier quel que soit son dossier, classant à tort
# `planning/archive/2026-09-20_decision_x.md` comme une décision LIABLE alors que
# `arc_serve.DECISION_ID_RE` (id = nom sans extension, jamais un chemin) ne
# désigne QUE `planning/<id>.md` — un sous-dossier rendrait le lien de détail
# invariablement 404 malgré un chemin `sources`/`supersedes` par ailleurs valide.
_SOURCE_DECISION_RE = re.compile(r"^planning/(\d{4}-\d{2}-\d{2})_decision_[^/.]+\.md$")
_SOURCE_REPORT_RE = re.compile(r"^rapports/[^/]+\.md$")


def classify_source_path(path: Optional[str]) -> dict:
    """Classe un chemin cité par une décision (#54/#55) — `sources`, `supersedes`
    ou `session_ref.week` — pour que le dashboard sache à quelle vue le lier,
    SANS jamais lire le fichier ni ouvrir la base : seul le NOM suffit. Rend
    TOUJOURS `{"path", "kind", "date"}` — `kind: "other"` (et `date: None`) pour
    tout chemin non reconnu (`resources/*`, chemin libre, `None`), affiché en
    simple texte par `scripts/arc_serve.py::resolve_source`, jamais comme un
    lien : ce module n'a pas de notion de fichier « servable », c'est
    `arc_serve.py` qui décide, à partir de `kind`, s'il existe une vue à lier —
    jamais en rouvrant le fichier désigné par `path`."""
    if not path:
        return {"path": path, "kind": "other", "date": None}
    for pattern, kind in (
        (_SOURCE_HEALTH_RE, "health"), (_SOURCE_WEATHER_RE, "weather"),
        (_SOURCE_NUTRITION_RE, "nutrition"), (_SOURCE_ACTIVITY_RE, "activity"),
        (_SOURCE_WEEK_RE, "week"),
    ):
        m = pattern.match(path)
        if m:
            return {"path": path, "kind": kind, "date": m.group(1)}
    m = _SOURCE_DECISION_RE.match(path)
    if m:
        return {"path": path, "kind": "decision", "date": m.group(1)}
    if _SOURCE_REPORT_RE.match(path):
        return {"path": path, "kind": "report", "date": None}
    return {"path": path, "kind": "other", "date": None}


# ---------------------------------------------------------------------------
# Découplage aérobie (Pa:HR) et facteur d'efficacité (#45)
# ---------------------------------------------------------------------------


def activity_decoupling_report(conn, ref: Union[int, str]) -> dict:
    """Rapport de découplage aérobie (#45) d'une séance, par `garmin_activity_id` —
    pour la CLI (`arc_index.py decoupling --activity`) et pour les agents en
    headless (`coach`, #51). Lit les colonnes déjà calculées à l'indexation
    (`compute_metrics`), jamais un recalcul à la lecture — même discipline que
    `activity_gap_report` (#44). Rend TOUJOURS `{"garmin_activity_id",
    "decoupling_pct", "ef_whole", "reason"}`, plus `reason_code:
    "unknown_activity"` spécifiquement quand la séance n'est pas (encore)
    indexée, jamais une exception."""
    act = conn.execute(
        f"SELECT sport, decoupling_pct, ef_whole, decoupling_reason FROM activity WHERE {ref_column(ref)} = ?",
        (ref,)).fetchone()
    if act is None:
        return {**ref_label(ref), "decoupling_pct": None, "ef_whole": None,
                "reason": unknown_activity_reason(ref), "reason_code": "unknown_activity"}
    if M.sport_family(act["sport"]) != "run":
        return {**ref_label(ref), "decoupling_pct": None, "ef_whole": None,
                "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                          "arc_decoupling.ASSUMPTIONS[\"restricted_to_run_family\"]"}
    if act["decoupling_pct"] is None and act["decoupling_reason"] is None:
        return {**ref_label(ref), "decoupling_pct": None, "ef_whole": None,
                "reason": "aucun échantillon FIT ingéré pour cette séance"}
    return {**ref_label(ref), "decoupling_pct": act["decoupling_pct"],
            "ef_whole": act["ef_whole"], "reason": act["decoupling_reason"]}


def decoupling_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance du découplage aérobie sur les sorties longues (#45) — pour la CLI
    (`arc_index.py decoupling --weeks`) et pour `coach`/le tableau de bord.
    N'est pas soumis à `[health].morning_check` : ne dépend d'aucune donnée de
    santé, seulement des activités déjà indexées. Voir
    `arc_metrics.ASSUMPTIONS`/`arc_decoupling.ASSUMPTIONS`.

    ATTENTION, deux seuils de durée DIFFÉRENTS et NON liés (revue de code) :
    « sortie longue » ici (`duration_s` DÉCLARÉ au contrat ```arc, temps ÉCOULÉ,
    > `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) détermine seulement quelles
    activités ENTRENT dans cette tendance ; l'ÉLIGIBILITÉ au découplage lui-même
    (`arc_decoupling.MIN_MOVING_DURATION_S`, 60 min de MOUVEMENT mesuré sur les
    échantillons FIT) est vérifiée séparément, à l'indexation
    (`compute_metrics`). Une activité de 70 min déclarées peut donc apparaître
    ici avec `decoupling_pct: null` (sortie longue mais pas forcément éligible),
    et une activité de 65 min déclarées mais réellement longue en mouvement
    n'apparaîtra PAS ici du tout (sous le seuil de 90 min de CETTE tendance)
    même si son découplage est parfaitement calculé et visible sur sa fiche
    séance (`/api/activity/<id>`)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, name, duration_s, decoupling_pct, ef_whole FROM activity "
        "WHERE duration_s > ?", (M.LONG_RUN_MIN_DURATION_S,)).fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.DECOUPLING_TREND_WEEKS
    return M.decoupling_trend(rows, today, window_weeks)


# ---------------------------------------------------------------------------
# VAM — montées détectées (#46)
# ---------------------------------------------------------------------------


def activity_dem_check(conn, workspace: Path, ref: Union[int, str], *, http_get=None) -> dict:
    """Compare l'altitude enregistrée d'une séance au MNT (#176) — OPT-IN STRICT : sans
    `[privacy].dem_for_activities = true`, aucune coordonnée ne part et le rapport le dit
    (`status = "disabled"`). Lecture seule : l'altitude enregistrée n'est JAMAIS remplacée ni
    écrite dans l'index ou le Markdown ; seule la comparaison D+ enregistré / D+ MNT et le biais
    moyen sont rendus. Début/fin de trace (`[privacy].dem_trim_m`, 500 m par défaut) non
    envoyés — protection partielle du domicile, voir `arc_dem.ASSUMPTIONS["privacy"]`. Jamais d'exception réseau :
    `status = "unavailable"` + raison (repli hors ligne)."""
    label = ref_label(ref)
    cfg = DEM.load_settings(workspace)
    if not cfg["activities"]:
        return {**label, "status": "disabled",
                "reason": "correction MNT des séances désactivée : une trace d'activité révèle votre "
                          "domicile. Activez `[privacy].dem_for_activities = true` dans "
                          "config/workspace.user.toml pour l'autoriser (voir docs/elevation.md)."}
    act = conn.execute(f"SELECT id FROM activity WHERE {ref_column(ref)} = ?", (ref,)).fetchone()
    if act is None:
        return {**label, "status": "unknown_activity", "reason": unknown_activity_reason(ref)}
    rows = samples_by_ref(conn, ref)["samples"]
    if not rows:
        return {**label, "status": "no_samples", "reason": "aucun échantillon FIT ingéré pour cette séance"}
    cache = DEM.DemCache(DEM.cache_path(workspace), enabled=cfg["cache"])
    result = DEM.activity_check(rows, cache=cache, http_get=http_get, trim_m=cfg["activity_trim_m"])
    return {**label, **result, "attribution": result.get("report", {}).get("attribution", []),
            "note": "comparaison seulement — l'altitude enregistrée n'est pas modifiée (le baromètre "
                    "reste souvent meilleur sur un FIT récent)"}


def activity_climb_report(conn, ref: Union[int, str]) -> dict:
    """Rapport VAM (#46) d'une séance, par `garmin_activity_id` — pour la CLI
    (`arc_index.py vam --activity`) et pour les agents en headless. Lit les
    lignes/colonnes déjà calculées à l'indexation (`compute_metrics`), jamais un
    recalcul à la lecture — même discipline que `activity_gap_report` (#44) et
    `activity_decoupling_report` (#45). Rend TOUJOURS `{"garmin_activity_id",
    "climbs", "vam_best_10min_m_h", "vam_best_20min_m_h", "vam_by_grade_class",
    "best_climb_vam_elapsed_m_h", "reason", "reason_code", "applicable"}`,
    jamais une exception — voir `arc_climb.climb_report` pour la sémantique de
    `reason_code`/`applicable` (#47, revue de code, nit : contrepartie stable,
    non localisée, de `reason`)."""
    empty = {**ref_label(ref), "climbs": [], "vam_best_10min_m_h": None,
             "vam_best_20min_m_h": None, "vam_by_grade_class": {}, "best_climb_vam_elapsed_m_h": None}
    act = conn.execute(
        "SELECT id, sport, best_vam_10min_m_h, best_vam_20min_m_h, best_climb_vam_elapsed_m_h "
        f"FROM activity WHERE {ref_column(ref)} = ?", (ref,)).fetchone()
    if act is None:
        return {**empty, "reason": unknown_activity_reason(ref),
                "reason_code": "unknown_activity", "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                                    "arc_climb.ASSUMPTIONS[\"restricted_to_run_family\"]",
                "reason_code": "not_run_family", "applicable": False}
    sample_count = count_samples(conn, ref)
    if sample_count == 0:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance",
                "reason_code": "no_samples", "applicable": True}
    climbs = [dict(r) for r in conn.execute(
        "SELECT idx AS \"index\", start_t_s, end_t_s, start_km, end_km, distance_m, gain_m, avg_grade, "
        "grade_class, duration_elapsed_s, duration_moving_s, vam_elapsed_m_h, vam_moving_m_h, segment_id, "
        "hr_first_third_bpm, hr_last_third_bpm, hr_drift_bpm_per_100m, vs_previous_pct, vs_best_pct "
        "FROM activity_climb WHERE activity_id = ? ORDER BY idx", (act["id"],)).fetchall()]
    return {
        **ref_label(ref),
        "climbs": climbs,
        "vam_best_10min_m_h": act["best_vam_10min_m_h"],
        "vam_best_20min_m_h": act["best_vam_20min_m_h"],
        "vam_by_grade_class": VC.vam_by_grade_class(climbs),
        "best_climb_vam_elapsed_m_h": act["best_climb_vam_elapsed_m_h"],
        "reason": None,
        "reason_code": None,
        "applicable": True,
    }


# ---------------------------------------------------------------------------
# Identité de montée entre séances — historique par segment (#49)
# ---------------------------------------------------------------------------


def climb_segment_list(conn) -> List[dict]:
    """Segments connus (#49, `arc_climb_match.py`), pour `/api/climb-segments` et le CLI
    `climb-history` sans argument — jamais de position GPS exposée ici (voir
    `arc_climb_match.ASSUMPTIONS["privacy"]`), seulement le lieu déclaré et la
    signature de profil. Triés par occurrences décroissantes (les montées les plus
    régulièrement gravies d'abord), puis par id pour un ordre stable à égalité."""
    return [dict(r) for r in conn.execute(
        "SELECT id AS segment_id, location, gain_m, distance_m, avg_grade, grade_class, occurrences, "
        "best_time_elapsed_s, best_activity_id, first_seen_activity_id, first_seen_date "
        "FROM climb_segment ORDER BY occurrences DESC, id").fetchall()]


def climb_segment_history(conn, segment_id: int) -> dict:
    """Historique complet d'un segment (#49) : chaque occurrence (date, activité,
    temps écoulé/mouvement, VAM, FC, dérive, progression vs précédent/meilleur déjà
    calculés à l'indexation) — pour `/api/climb-segment/<id>` et le CLI `climb-history
    --segment ID`. Rend TOUJOURS un dict, jamais `None` (même discipline que les autres
    rapports de l'épopée) : `reason`/`reason_code` explicites si le segment est
    inconnu — un id de segment n'est PAS stable d'une réindexation à l'autre (voir la
    table `climb_segment`), un id périmé est donc un cas attendu, pas une erreur de
    programmation."""
    seg = conn.execute(
        "SELECT id AS segment_id, location, gain_m, distance_m, avg_grade, grade_class, occurrences, "
        "best_time_elapsed_s, best_activity_id, first_seen_activity_id, first_seen_date "
        "FROM climb_segment WHERE id = ?", (segment_id,)).fetchone()
    if seg is None:
        return {"segment_id": segment_id, "segment": None, "occurrences": [],
                "reason": "segment inconnu (id périmé — les ids de climb_segment ne sont pas stables "
                          "d'une réindexation à l'autre, voir arc_index.DDL)",
                "reason_code": "unknown_segment", "applicable": True}
    rows = conn.execute(
        "SELECT ac.activity_id, a.date, a.name, ac.start_km, ac.end_km, ac.duration_elapsed_s, "
        "ac.duration_moving_s, ac.vam_elapsed_m_h, ac.vam_moving_m_h, ac.hr_first_third_bpm, "
        "ac.hr_last_third_bpm, ac.hr_drift_bpm_per_100m, ac.vs_previous_pct, ac.vs_best_pct "
        "FROM activity_climb ac JOIN activity a ON a.id = ac.activity_id "
        "WHERE ac.segment_id = ? ORDER BY a.date, ac.activity_id", (segment_id,)).fetchall()
    return {"segment_id": segment_id, "segment": dict(seg), "occurrences": [dict(r) for r in rows],
            "reason": None, "reason_code": None, "applicable": True}


# ---------------------------------------------------------------------------
# Modèle personnel pente -> allure (#58)
# ---------------------------------------------------------------------------


def slope_model_bins(conn, band: str) -> List[dict]:
    """Paniers déjà stockés (recalculés au dernier `compute_metrics`) pour `band` —
    lecture pure, aucun recalcul. Rend `[]` si le modèle n'a pas pu être ajusté pour
    cette bande (voir `slope_model_meta`).

    `grade_lo`/`grade_hi` d'un panier ouvert (queue) restent `NULL` TELS QUELS
    (jamais convertis en `float("inf")`) : `json.dumps` d'un `inf` Python produit le
    jeton `Infinity`/`-Infinity`, INVALIDE en JSON standard — `JSON.parse` d'un
    navigateur le REJETTE (contrairement à `json.loads` de Python, qui l'accepte
    par tolérance) et casserait `web/js/app.js` (revue de code #58). `null` est
    d'ailleurs la représentation la plus juste d'un panier « ouvert » : aucun de
    ses consommateurs (`predict_speed`, qui ne lit que `grade_mid` ; l'UI, qui
    filtre déjà sur `Number.isFinite`, `null` échouant ce test comme `Infinity`
    l'aurait fait) n'a besoin d'un infini numérique réel."""
    rows = conn.execute(
        "SELECT band, grade_lo, grade_hi, grade_mid, label, speed_ms, pace_s_km, hr_bpm, source, "
        "ci_low_speed_ms, ci_high_speed_ms, n_samples, n_activities, effective_time_s, run_share "
        "FROM slope_model_bin WHERE band = ? ORDER BY grade_mid", (band,)).fetchall()
    return [dict(r) for r in rows]


def slope_model_report(conn, band: str = "endurance") -> dict:
    """Modèle personnel pente -> allure déjà stocké (#58) pour `band`
    (`arc_slope_model.BANDS`) — pour `/api/slope-model` et la CLI `slope-model` sans
    `--months` explicite (le modèle stocké est celui de `[metrics].slope_model_months`,
    recalculé à chaque `compute_metrics`). TOUJOURS un dict, `bins: []` avec
    `reason`/`reason_code` si non ajustable — jamais d'exception."""
    if band not in SL.BANDS:
        return {"band": band, "months": None, "half_life_days": None, "as_of": None, "n_activities": 0,
                "flat_reference_speed_ms": None, "selected_by": {"plan": 0, "hr": 0}, "bins": [],
                "reason": f"bande « {band} » inconnue (attendu : {', '.join(SL.BANDS)})",
                "reason_code": "unknown_band"}
    meta = conn.execute(
        "SELECT months, half_life_days, as_of, n_activities, flat_reference_speed_ms, "
        "selected_by_plan, selected_by_hr, reason, reason_code "
        "FROM slope_model_meta WHERE band = ?", (band,)).fetchone()
    if meta is None:
        return {"band": band, "months": None, "half_life_days": None, "as_of": None, "n_activities": 0,
                "flat_reference_speed_ms": None, "selected_by": {"plan": 0, "hr": 0}, "bins": [],
                "reason": "modèle jamais calculé (aucun compute_metrics n'a encore tourné)",
                "reason_code": "not_computed"}
    meta_dict = dict(meta)
    selected_by = {"plan": meta_dict.pop("selected_by_plan") or 0, "hr": meta_dict.pop("selected_by_hr") or 0}
    return {"band": band, **meta_dict, "selected_by": selected_by, "bins": slope_model_bins(conn, band)}


def recompute_slope_model(conn, conf: dict, band: str, months: int, today: Optional[str] = None) -> dict:
    """Comme `slope_model_report`, mais RECALCULÉ à la volée pour une fenêtre `months`
    différente de celle déjà stockée (CLI `slope-model --months`, exploration
    ponctuelle) — parcourt à nouveau les activités course à pied et leurs échantillons
    (coût acceptable pour un usage ponctuel/manuel, à la différence de
    `compute_metrics`, qui doit rester bon marché à chaque passage, voir
    `arc_slope_model.ASSUMPTIONS['aggregation_cost']`)."""
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete) if athlete else {}
    zone_bounds = M.hr_zone_bounds(athlete, conf.get("hr_zones"))
    seiler_thresholds = M.seiler_bounds(athlete, zone_bounds[1]) if zone_bounds else None
    easy_hr_bpm = moderate_hr_bpm = None
    if band == "endurance" and seiler_thresholds:
        easy_hr_bpm, moderate_hr_bpm = seiler_thresholds
    rows = conn.execute(
        "SELECT id, date, garmin_activity_id, intervals_activity_id, strava_activity_id, sport FROM activity "
        "WHERE garmin_activity_id IS NOT NULL OR intervals_activity_id IS NOT NULL "
        "OR strava_activity_id IS NOT NULL "
        "ORDER BY date").fetchall()
    activities = []
    for row in rows:
        act = dict(row)
        if M.sport_family(act.get("sport")) != "run":
            continue
        act_samples = samples(conn, act["id"])
        if not act_samples:
            continue
        series = G.gap_sample_series(act_samples)
        planned = planned_intensity_for(conn, act.get("date"), act.get("sport")) if band == "endurance" else None
        activities.append({"activity_id": act["id"], "date": act.get("date"), "series": series,
                            "planned_intensity": planned})
    result = SL.fit_slope_model(activities, band=band, months=months, easy_hr_bpm=easy_hr_bpm,
                                 moderate_hr_bpm=moderate_hr_bpm, as_of=today)
    # `SL.fit_slope_model` rend des bornes de panier ouvert en `float("inf")` RÉEL
    # (GRADE_BINS), correctes pour un consommateur Python — mais cette fonction
    # nourrit directement le CLI (`json.dumps`), où un `inf` produirait le jeton
    # `Infinity`, invalide en JSON standard (même raison que `slope_model_bins`
    # ci-dessus, revue de code #58) : converti en `None` ICI, à la frontière
    # JSON, jamais plus tôt (les tests purs de `arc_slope_model` continuent de
    # voir de vrais infinis).
    for b in result["bins"]:
        if b["grade_lo"] == float("-inf"):
            b["grade_lo"] = None
        if b["grade_hi"] == float("inf"):
            b["grade_hi"] = None
    return {"band": band, **result}


def vam_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance de la VAM sur les montées détectées (#46) — pour la CLI
    (`arc_index.py vam --weeks`) et pour `coach`/le tableau de bord. Voir
    `arc_metrics.vam_trend`/`arc_climb.ASSUMPTIONS` — AUCUN seuil de durée
    minimale (contrairement à `decoupling_trend`) : une montée peut être
    détectée sur une sortie courte."""
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, name, best_vam_10min_m_h, best_vam_20min_m_h, best_climb_vam_elapsed_m_h "
        "FROM activity").fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.VAM_TREND_WEEKS
    return M.vam_trend(rows, today, window_weeks)


# ---------------------------------------------------------------------------
# Efficacité en descente — par classe de pente (#47)
# ---------------------------------------------------------------------------


def activity_descent_report(conn, ref: Union[int, str]) -> dict:
    """Rapport d'efficacité en descente (#47) d'une séance, par
    `garmin_activity_id` — pour la CLI (`arc_index.py descent --activity`) et
    pour les agents en headless. Lit les lignes/colonnes déjà calculées à
    l'indexation (`compute_metrics`), jamais un recalcul à la lecture — même
    discipline que `activity_climb_report` (#46). Rend TOUJOURS
    `{"garmin_activity_id", "classes", "reference_gap_pace_s_km",
    "reference_source", "reason", "reason_code", "applicable"}`, jamais une
    exception — voir `arc_descent.descent_report` pour la sémantique de
    `reason_code`/`applicable` (contrepartie stable, non localisée, de
    `reason`)."""
    empty = {**ref_label(ref), "classes": {}, "reference_gap_pace_s_km": None,
              "reference_source": None}
    act = conn.execute(
        "SELECT id, sport, descent_reference_gap_pace_s_km, descent_reference_source FROM activity "
        f"WHERE {ref_column(ref)} = ?", (ref,)).fetchone()
    if act is None:
        return {**empty, "reason": unknown_activity_reason(ref), "reason_code": "unknown_activity",
                "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": DS.REASON_NOT_RUN_FAMILY, "reason_code": "not_run_family",
                "applicable": False}
    sample_count = count_samples(conn, ref)
    if sample_count == 0:
        return {**empty, "reason": DS.REASON_NO_SAMPLES, "reason_code": "no_samples", "applicable": True}
    rows = {r["grade_class"]: dict(r) for r in conn.execute(
        "SELECT grade_class, count, duration_moving_s, distance_m, mean_speed_ms, mean_pace_s_km, "
        "mean_gap_speed_ms, mean_grade, efficiency FROM activity_descent_class WHERE activity_id = ?",
        (act["id"],)).fetchall()}
    # Ordre `DESCENT_GRADE_CLASSES` (croissant), jamais un ordre SQL arbitraire sur
    # une colonne texte (qui trierait "-10 à -15 %" avant "-5 à -10 %" alphabétiquement)
    # — même discipline que `arc_climb.vam_by_grade_class`/l'UI (`GRADE_CLASS_ORDER`).
    classes = {label: {k: v for k, v in rows[label].items() if k != "grade_class"}
               for _lo, _hi, label in DS.DESCENT_GRADE_CLASSES if label in rows}
    reason = reason_code = None
    if not classes:
        if act["descent_reference_gap_pace_s_km"] is None:
            reason, reason_code = DS.REASON_NO_REFERENCE, "no_reference"
        else:
            reason, reason_code = DS.REASON_NO_QUALIFYING_CLASS, "no_qualifying_class"
    return {
        **ref_label(ref),
        "classes": classes,
        "reference_gap_pace_s_km": act["descent_reference_gap_pace_s_km"],
        "reference_source": act["descent_reference_source"],
        "reason": reason,
        "reason_code": reason_code,
        "applicable": True,
    }


def descent_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance de l'efficacité en descente (#47) — pour la CLI
    (`arc_index.py descent --weeks`) et pour `coach`/le tableau de bord. Voir
    `arc_metrics.descent_trend`/`arc_descent.ASSUMPTIONS` — AUCUN seuil de durée
    minimale sur la séance (comme `vam_trend`), seul le seuil PAR CLASSE
    (déjà appliqué à l'indexation) filtre les lignes. `a.id AS activity_id`
    (revue de code, should-fix 3) : la clé de regroupement PAR ACTIVITÉ de
    `arc_metrics.descent_trend` doit être l'id, jamais `(date, name, sport)` —
    deux séances distinctes le même jour au même nom générique (« Trail »,
    par exemple, deux sorties bi-quotidiennes) se seraient sinon vues fusionnées
    à tort en une seule. `a.descent_reference_source AS reference_source`
    (revue de code, should-fix) : la référence `"flat"` et son repli
    `"non_descent"` (voir `arc_descent.ASSUMPTIONS["reference"]`) ne sont PAS
    sur la même échelle (mesuré : 0,664 en `flat` vs 0,548 en `non_descent`
    pour la MÊME descente) — la tendance doit pouvoir distinguer les deux,
    jamais les mélanger sans le dire (une séance sans plat suffisant
    apparaîtrait sinon comme une chute d'efficacité)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT a.id AS activity_id, a.date AS date, a.sport AS sport, a.name AS name, "
        "a.descent_reference_source AS reference_source, dc.grade_class AS grade_class, "
        "dc.efficiency AS efficiency, dc.mean_pace_s_km AS mean_pace_s_km, "
        "dc.mean_grade AS mean_grade FROM activity_descent_class dc "
        "JOIN activity a ON a.id = dc.activity_id").fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.DESCENT_TREND_WEEKS
    return M.descent_trend(rows, today, window_weeks)


# ---------------------------------------------------------------------------
# Durabilité sur les sorties longues (#48)
# ---------------------------------------------------------------------------


def activity_durability_report(conn, ref: Union[int, str]) -> dict:
    """Rapport de durabilité (#48) d'une séance, par `garmin_activity_id` — pour
    la CLI (`arc_index.py durability --activity`) et pour les agents en
    headless. Lit les colonnes déjà calculées à l'indexation
    (`compute_metrics`), jamais un recalcul à la lecture — même discipline que
    `activity_decoupling_report` (#45)/`activity_gap_report` (#44). Rend
    TOUJOURS `{"garmin_activity_id", "gap_fade_pct", "ef_fade_pct",
    "hr_first_third_bpm", "hr_middle_third_bpm", "hr_last_third_bpm", "reason",
    "reason_code", "applicable"}`, jamais une exception — voir
    `arc_durability.durability_report` pour la sémantique de
    `reason_code`/`applicable` (contrepartie stable, non localisée, de
    `reason`)."""
    empty = {**ref_label(ref), "gap_fade_pct": None, "ef_fade_pct": None,
              "hr_first_third_bpm": None, "hr_middle_third_bpm": None, "hr_last_third_bpm": None}
    act = conn.execute(
        "SELECT sport, durability_gap_fade_pct, durability_ef_fade_pct, durability_hr_first_third_bpm, "
        "durability_hr_middle_third_bpm, durability_hr_last_third_bpm, durability_reason, "
        f"durability_reason_code FROM activity WHERE {ref_column(ref)} = ?",
        (ref,)).fetchone()
    if act is None:
        return {**empty, "reason": unknown_activity_reason(ref), "reason_code": "unknown_activity",
                "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": DU.REASON_NOT_RUN_FAMILY, "reason_code": "not_run_family",
                "applicable": False}
    if act["durability_gap_fade_pct"] is None and act["durability_reason"] is None:
        return {**empty, "reason": DU.REASON_NO_SAMPLES, "reason_code": "no_samples", "applicable": True}
    return {
        **ref_label(ref),
        "gap_fade_pct": act["durability_gap_fade_pct"],
        "ef_fade_pct": act["durability_ef_fade_pct"],
        "hr_first_third_bpm": act["durability_hr_first_third_bpm"],
        "hr_middle_third_bpm": act["durability_hr_middle_third_bpm"],
        "hr_last_third_bpm": act["durability_hr_last_third_bpm"],
        "reason": act["durability_reason"],
        "reason_code": act["durability_reason_code"],
        "applicable": True,
    }


def durability_trend(conn, today: date, weeks: Optional[int] = None) -> dict:
    """Tendance de durabilité (#48) — pour la CLI (`arc_index.py durability
    --weeks`) et pour `coach`/le tableau de bord. Voir
    `arc_metrics.durability_trend`/`arc_durability.ASSUMPTIONS` : sorties
    longues (`moving_duration_s` déclaré, à défaut `duration_s` écoulé, >
    `arc_metrics.LONG_RUN_MIN_DURATION_S`) de la famille course à pied.
    `id AS activity_id` (revue de code #48, should-fix 3, cohérence avec
    `descent_trend`) : clé de regroupement stable, jamais `(date, name,
    sport)`. Aucun `WHERE` sur la durée ICI (contrairement à `api_decoupling`) :
    le filtrage précis (moving_duration_s OU duration_s) est fait en Python par
    `arc_metrics.durability_trend`, qui a besoin des DEUX colonnes pour
    appliquer son repli — un `WHERE duration_s > ?` exclurait à tort une
    activité dont seul `moving_duration_s` dépasse le seuil."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id AS activity_id, date, sport, name, duration_s, moving_duration_s, "
        "durability_gap_fade_pct, durability_ef_fade_pct, durability_hr_first_third_bpm, "
        "durability_hr_middle_third_bpm, durability_hr_last_third_bpm, durability_reason, "
        "durability_reason_code FROM activity").fetchall()]
    window_weeks = weeks if weeks and weeks > 0 else M.DURABILITY_TREND_WEEKS
    return M.durability_trend(rows, today, window_weeks)


HISTORY_DEFAULT_WEEKS = 12
HISTORY_STALE_DAYS = 7


def history_summary(conn, today: date, weeks: int = HISTORY_DEFAULT_WEEKS) -> dict:
    """Ce que l'athlète a RÉELLEMENT fait, pour `sports-director` (#159) : records
    à pied (plus longue sortie, plus gros D+ en une séance), volume hebdomadaire
    des N dernières semaines, dernier état de charge de `metric_day` et rapports
    de course (`race`, `race_debrief`). Lecture seule, aucun second calcul.

    D+ : la valeur ENREGISTRÉE (montre/fichier) ; un chiffre officiel de course
    vit dans le rapport ou l'objectif, jamais ici. `stale_days` dit depuis
    combien de jours aucune activité n'est indexée : au-delà de
    `HISTORY_STALE_DAYS`, la charge (et l'ACWR) reflète un trou de
    synchronisation, pas un repos — `load.stale` le signale."""
    foot = tuple(M.RUNNING_SPORTS) + ("hiking",)
    marks = ",".join("?" * len(foot))
    cols = "date, sport, name, distance_m, elevation_gain_m, duration_s, source_path"

    def best(column: str) -> Optional[dict]:
        row = conn.execute(
            f"SELECT {cols} FROM activity WHERE sport IN ({marks}) AND {column} IS NOT NULL "
            f"AND date <= ? ORDER BY {column} DESC, date DESC LIMIT 1", (*foot, today.isoformat())).fetchone()
        return dict(row) if row else None

    last = conn.execute("SELECT MAX(date) FROM activity WHERE date <= ?", (today.isoformat(),)).fetchone()[0]
    stale_days = (today - date.fromisoformat(last)).days if last else None

    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=weeks - 1)
    by_week = {(first + timedelta(weeks=i)).isoformat(): {
        "week_start": (first + timedelta(weeks=i)).isoformat(), "sessions": 0,
        "distance_m": 0.0, "elevation_gain_m": 0.0, "duration_s": 0.0} for i in range(weeks)}
    for row in conn.execute(
            f"SELECT date, distance_m, elevation_gain_m, duration_s FROM activity "
            f"WHERE sport IN ({marks}) AND date >= ? AND date <= ?",
            (*foot, first.isoformat(), today.isoformat())):
        d = date.fromisoformat(row["date"])
        week = by_week[(d - timedelta(days=d.weekday())).isoformat()]
        week["sessions"] += 1
        for key in ("distance_m", "elevation_gain_m", "duration_s"):
            week[key] += row[key] or 0.0

    load_row = conn.execute(
        "SELECT date, fitness, fatigue, form, acwr FROM metric_day WHERE date <= ? "
        "ORDER BY date DESC LIMIT 1", (today.isoformat(),)).fetchone()
    load = dict(load_row) if load_row else None
    if load is not None:
        load["stale"] = stale_days is not None and stale_days > HISTORY_STALE_DAYS

    races = [dict(r) for r in conn.execute(
        "SELECT date, report_type, title, location, source_path FROM report "
        "WHERE report_type IN ('race', 'race_debrief') ORDER BY date DESC")]
    return {
        "today": today.isoformat(), "last_activity_date": last, "stale_days": stale_days,
        "records": {"longest_distance": best("distance_m"), "biggest_elevation_gain": best("elevation_gain_m")},
        "weeks": list(by_week.values()), "load": load, "races": races,
    }


def trail_shape_report(conn, today: date) -> dict:
    """Rapport « Trail Shape » (#63) — pour la CLI (`arc_index.py trail-shape`)
    et pour `coach`/le tableau de bord. Délègue ENTIÈREMENT à
    `arc_trail_shape.trail_shape_report` (formule, constantes, gestion des cas
    limites — objectif absent/incomplet, course passée/trop courte, D+ absent,
    durabilité inéligible, données éparses) : ici, seulement la lecture de
    l'objectif actif et des activités depuis l'index SQLite, jamais un second
    calcul. Aucune colonne de santé lue (le score n'en utilise aucune)."""
    objective_row = conn.execute("SELECT * FROM objective LIMIT 1").fetchone()
    objective = dict(objective_row) if objective_row else None
    rows = [dict(r) for r in conn.execute(
        "SELECT date, sport, name, distance_m, elevation_gain_m, duration_s, moving_duration_s, "
        "durability_gap_fade_pct, durability_reason, durability_reason_code FROM activity").fetchall()]
    return TS.trail_shape_report(objective, rows, today)


def load_forecast(conn, today: date, until: Optional[str] = None, compare: Optional[str] = None) -> dict:
    """Projection de charge sur le bloc (#172) — commande « load-forecast » et `/api/load-forecast`.

    Délègue ENTIÈREMENT à `arc_load_forecast` (import PARESSEUX : ce module importe `arc_guardrails`,
    qui importe `arc_index`). `until` : AAAA-MM-JJ ; `compare` : chemin d'un fichier semaine(s) (ou `-`)."""
    import arc_guardrails as GR
    import arc_load_forecast as LF
    until_date = None
    if until:
        try:
            until_date = date.fromisoformat(until)
        except ValueError:
            raise ConfigError(f"--until : date AAAA-MM-JJ attendue, « {until} » reçue.")
    alternative = None
    if compare is not None:
        try:
            alternative = LF.alternative_weeks_from_block(GR._read_week_argument(compare))
        except (ValueError, OSError, ConfigError) as exc:
            raise ConfigError(f"--compare : {str(exc).removeprefix('--week : ')}")
    return LF.load_forecast(conn, today, until_date, alternative)


def _inspection_rows(conn, gear_id: Optional[str] = None) -> List[dict]:
    """Inspections indexées (plus récentes d'abord), colonnes JSON décodées, `path` = fichier."""
    sql = ("SELECT source_path, date, gear_id, distance_m, condition, asymmetry_level, asymmetry_side, "
           "wear_zones, gait_hints, photos, previous, scale_reference, lug_depth_mm FROM gear_inspection")
    params: tuple = ()
    if gear_id:
        sql += " WHERE gear_id = ?"
        params = (gear_id,)
    rows = []
    for r in conn.execute(sql + " ORDER BY date DESC, source_path DESC", params):
        d = dict(r)
        item = {"path": d["source_path"], "date": d["date"], "gear_id": d["gear_id"],
                "condition": d["condition"]}
        if d["distance_m"] is not None:
            item["distance_m"] = d["distance_m"]
        if d["asymmetry_level"]:
            item["asymmetry"] = {"level": d["asymmetry_level"]}
            if d["asymmetry_side"]:
                item["asymmetry"]["side"] = d["asymmetry_side"]
        for key in ("wear_zones", "gait_hints", "photos"):
            if d[key]:
                item[key] = json.loads(d[key])
        if d["previous"]:
            item["previous"] = d["previous"]
        if d["scale_reference"] is not None:
            item["scale_reference"] = bool(d["scale_reference"])
        if d["lug_depth_mm"] is not None:
            item["lug_depth_mm"] = d["lug_depth_mm"]
        rows.append(item)
    return rows


def gear_inspections(conn, gear_id: Optional[str] = None, today: Optional[date] = None,
                     mileage: Optional[dict] = None) -> dict:
    """Inspections photo par paire (#135) — commande « inspections » et `/api/summary.gear_inspections`.

    Rend `{"interval_m", "gear": [...], "due": [gear_id…]}` : par paire, `inspections` (récentes d'abord),
    `latest`, `condition_change` (deux dernières), `km_since_inspection_m` et `due`/`due_reason` (rappel
    « inspection conseillée », jamais imposé — `arc_metrics.ASSUMPTIONS["gear_inspection"]`). N'est PAS
    soumis à `[health].morning_check` (aucune donnée de santé) ni à `[data].source`."""
    shoes = (mileage if mileage is not None else gear_mileage(conn, today))["shoes"]   # `mileage` : déjà calculé (#147)
    ignored = {r["gear_id"]: r["name"] for r in conn.execute("SELECT gear_id, name FROM gear WHERE ignored = 1")}
    entries = M.gear_inspection_status(shoes, _inspection_rows(conn), ignored=ignored)
    if gear_id:
        entries = [e for e in entries if e["gear_id"] == gear_id]
    out = {"interval_m": M.GEAR_INSPECTION_INTERVAL_M, "gear": entries,
           "due": [e["gear_id"] for e in entries if e.get("due")]}
    if gear_id and not entries:
        row = conn.execute("SELECT gear_id, name, retired, ignored FROM gear WHERE gear_id = ?", (gear_id,)).fetchone()
        if row is not None:     # déclarée mais sans inspection (retirée ou `(ignorée)`) : connue, pas une erreur (#149)
            stub = {"gear_id": row["gear_id"], "name": row["name"] or row["gear_id"], "retired": bool(row["retired"]),
                    "unknown": False, "inspections": [], "latest": None, "due": False, "due_reason": None}
            if row["ignored"]:
                stub["ignored"] = True
            out["gear"] = [stub]
        else:
            out["error"] = f"paire inconnue : {gear_id}"     # même contrat que `gear-career` (code retour 1)
    return out


_GEAR_PHOTO_CITATION = re.compile(r'"(gear/photos/[^"]+)"')


def gear_photo_dropbox(conn, workspace: Path) -> dict:
    """Boîte de dépôt `gear/photos/` (#149) — `{"unreferenced_photos": [...], "ignored_files": [...]}`.

    `unreferenced_photos` : images (extensions raster du contrat, `arc_contract.GEAR_PHOTO_EXTENSIONS`,
    celles de la route du tableau de bord) citées par AUCUNE inspection — ni indexée, ni non indexée
    (les `gear/*.md` sont relus en brut : un fichier hors contrat qui cite encore la photo la garde
    « référencée »). Comparaison insensible à la casse (APFS). `ignored_files` : les autres fichiers
    (HEIC d'iPhone, TIFF…), jamais candidats, à expliquer à l'athlète. Chemins relatifs au workspace,
    triés ; liens symboliques et tout chemin dont un composant commence par `.` sont ignorés.
    Lecture seule : ne déplace, ne renomme ni ne supprime rien."""
    ws = Path(workspace)
    root = ws / "gear" / "photos"
    out: Dict[str, List[str]] = {"unreferenced_photos": [], "ignored_files": []}
    if not root.is_dir() or root.is_symlink():
        return out
    cited = {p.casefold() for row in _inspection_rows(conn) for p in row.get("photos", [])}
    for md in (ws / "gear").glob("*.md"):
        try:
            cited.update(m.casefold() for m in _GEAR_PHOTO_CITATION.findall(md.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    for path in root.rglob("*"):
        rel = path.relative_to(ws)
        if path.is_symlink() or not path.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() in C.GEAR_PHOTO_EXTENSIONS:
            if rel.as_posix().casefold() not in cited:
                out["unreferenced_photos"].append(rel.as_posix())
        else:
            out["ignored_files"].append(rel.as_posix())
    return {k: sorted(v) for k, v in out.items()}


def unreferenced_gear_photos(conn, workspace: Path) -> List[str]:
    """Raccourci de `gear_photo_dropbox` : seulement les photos candidates."""
    return gear_photo_dropbox(conn, workspace)["unreferenced_photos"]


def declared_gear(conn) -> List[dict]:
    """TOUTES les paires déclarées au profil (#149) — actives, retirées et `(ignorée)` — avec de quoi
    résoudre un argument de `/inspection` : `gear_id`, `name`, `retired`, `ignored`, `garmin_uuid`."""
    return [{"gear_id": r["gear_id"], "name": r["name"], "retired": bool(r["retired"]),
             "ignored": bool(r["ignored"]), "garmin_uuid": r["garmin_uuid"]}
            for r in conn.execute("SELECT gear_id, name, retired, ignored, garmin_uuid FROM gear "
                                  "ORDER BY name COLLATE NOCASE, gear_id")]


def _activities_of_gear(conn, gear_id: str, today: Optional[date]) -> List[dict]:
    """Séances attribuées à `gear_id` par `M.attribute_gear` — la MÊME règle que `gear_mileage`
    (mêmes requêtes `_gear_defs`/`_gear_activities`, mêmes exclusions : `garmin_unmapped`, paires
    ignorées, `depuis`, futur, sans distance), donc jamais de divergence entre kilométrage et bilan."""
    return [act for act, owner in M.attribute_gear(_gear_activities(conn), _gear_defs(conn), today)
            if owner == gear_id]


def gear_career(conn, gear_id: str, today: Optional[date] = None, mileage: Optional[dict] = None,
                acts: Optional[List[dict]] = None) -> dict:
    """Bilan de carrière d'une paire (#135, item 7) — commande « gear-career --gear ID » : km, séances,
    courses (intensité PLANIFIÉE `race` le jour de la séance), meilleurs efforts (séances à splits),
    dernière inspection. Rend `{"error": ...}` si `gear_id` est inconnu du profil ET des activités."""
    shoes = mileage if mileage is not None else gear_mileage(conn, today)
    shoe = next((sh for sh in shoes["shoes"] if sh["gear_id"] == gear_id), None)
    if shoe is None:
        unknown = next((u for u in shoes["unknown"] if u["gear_id"] == gear_id), None)
        if unknown is None:
            return {"error": f"paire inconnue : {gear_id}"}
        shoe = {"gear_id": gear_id, "name": gear_id, "distance_m": unknown["distance_m"], "retired": False}
    if acts is None:
        acts = _activities_of_gear(conn, gear_id, today)
    for act in acts:    # `is_race`/`splits` posés en place : `gear_detail` les réutilise (#147)
        act["is_race"] = planned_intensity_for(conn, act["date"], act["sport"]) == "race"
        act["splits"] = [dict(r) for r in conn.execute(
            "SELECT km, distance_m, duration_s FROM activity_split WHERE activity_id = ?", (act["id"],))]
    return M.gear_career(shoe, acts, _inspection_rows(conn, gear_id))


def _monthly_km(acts: List[dict]) -> List[dict]:
    """Kilométrage par mois civil (`AAAA-MM`, ordre chronologique, mois vides intercalés à 0 pour un
    axe continu) des séances DÉJÀ attribuées — le départ (`start_m`) n'est daté nulle part : il
    n'entre pas dans ce graphe (dit à l'écran)."""
    totals: Dict[str, float] = {}
    for a in acts:
        if a.get("date") and a.get("distance_m"):
            totals[a["date"][:7]] = totals.get(a["date"][:7], 0.0) + a["distance_m"]
    if not totals:
        return []
    y, m = (int(v) for v in min(totals).split("-"))
    ey, em = (int(v) for v in max(totals).split("-"))
    out = []
    while (y, m) <= (ey, em):
        key = f"{y:04d}-{m:02d}"
        out.append({"month": key, "distance_m": round(totals.get(key, 0.0))})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def gear_detail(conn, gear_id: str, today: Optional[date] = None) -> Optional[dict]:
    """Fiche d'une paire ou d'un objet d'équipement (#147) — `/api/gear/<id>`. `None` si `gear_id` est
    inconnu du profil ET des séances. Bâtie sur les MÊMES fonctions que le kilométrage et le bilan de
    carrière (`gear_mileage`, `gear_career`, `_activities_of_gear` → `M.attribute_gear`,
    `equipment_usage`) : aucune règle d'attribution réécrite ici."""
    today = today or date.today()
    ignored_row = conn.execute("SELECT name, garmin_uuid FROM gear WHERE gear_id = ? AND ignored = 1",
                               (gear_id,)).fetchone()
    if ignored_row is not None:
        insp = gear_inspections(conn, gear_id, today)
        return {"kind": "shoe", "gear_id": gear_id, "name": ignored_row["name"] or gear_id, "ignored": True,
                "garmin_linked": bool(ignored_row["garmin_uuid"]), "sessions": [], "monthly": [],
                "inspections": (insp["gear"][0] if insp.get("gear") else None)}
    shoes = gear_mileage(conn, today)
    known_shoe = any(sh["gear_id"] == gear_id for sh in shoes["shoes"])
    unknown_shoe = any(u["gear_id"] == gear_id for u in shoes["unknown"])
    if known_shoe or unknown_shoe:
        acts = _activities_of_gear(conn, gear_id, today)
        career = gear_career(conn, gear_id, today, mileage=shoes, acts=acts)    # pose `is_race` sur `acts`
        shoe = next((sh for sh in shoes["shoes"] if sh["gear_id"] == gear_id), None)
        row = conn.execute("SELECT garmin_uuid FROM gear WHERE gear_id = ?", (gear_id,)).fetchone()
        sessions = [{"id": a["id"], "date": a["date"], "name": a["name"], "sport": a["sport"],
                     "distance_m": a["distance_m"], "duration_s": a["duration_s"], "is_race": a["is_race"]}
                    for a in sorted(acts, key=lambda a: (a["date"] or "", a["id"]), reverse=True)]
        insp = gear_inspections(conn, gear_id, today, mileage=shoes)
        return {"kind": "shoe", "gear_id": gear_id, "name": career["name"], "unknown": shoe is None,
                "retired": bool(career.get("retired")), "shoe": shoe, "career": career,
                "garmin_linked": bool(row and row["garmin_uuid"]), "monthly": _monthly_km(acts),
                "sessions": sessions,
                "inspections": (insp["gear"][0] if insp.get("gear") else None)}
    usage = equipment_usage(conn, today)
    item = next((i for i in usage["items"] if i["gear_id"] == gear_id), None)
    unknown = next((u for u in usage["unknown"] if u["gear_id"] == gear_id), None)
    if item is None and unknown is None:
        return None
    category = item.get("category") if item else None
    sessions = []
    maintenance = (item or {}).get("maintenance_date")
    for a in _equipment_activities(conn):
        if M.equipment_session_counts(a, gear_id, category, today.isoformat()):
            # `counted` : même règle qu'`equipment_usage` — une séance d'avant (ou du jour de) le
            # dernier entretien n'entre plus dans les compteurs des déclencheurs.
            sessions.append({"id": a["id"], "date": a["date"], "name": a["name"], "sport": a["sport"],
                             "distance_m": a["distance_m"], "duration_s": a["duration_s"],
                             "counted": not (maintenance and (not a["date"] or a["date"] <= maintenance))})
    sessions.sort(key=lambda s: (s["date"] or "", s["id"]), reverse=True)
    names = {i["gear_id"]: i["name"] for i in usage["items"]}
    kits = {k: [{"gear_id": g, "name": names.get(g, g)} for g in usage["kits"].get(k, [])]
            for k in (item.get("kits") or [])} if item else {}
    return {"kind": "equipment", "gear_id": gear_id, "name": (item or {}).get("name") or gear_id,
            "unknown": item is None, "retired": bool((item or {}).get("retired")),
            "item": item, "unknown_usage": unknown, "kits": kits, "sessions": sessions}


def gear_of_activity(conn, activity_id: int, today: Optional[date] = None) -> dict:
    """Matériel d'UNE séance (#147, page séance) : la chaussure attribuée par la règle unique
    `M.attribute_gear` (explicite, sinon défaut) et l'équipement cité dans `gear_ids`."""
    today = today or date.today()
    row = conn.execute("SELECT id, name, duration_s, sport, distance_m, gear_id, gear_source, date, gear_ids "
                       "FROM activity WHERE id = ?", (activity_id,)).fetchone()
    out: Dict[str, Any] = {"shoe": None, "equipment": []}
    if row is None:
        return out
    act = dict(row)
    defs = _gear_defs(conn)
    for _act, owner in M.attribute_gear([act], defs, today):
        d = next((g for g in defs if g["gear_id"] == owner), None)
        out["shoe"] = {"gear_id": owner, "name": (d or {}).get("name") or owner, "unknown": d is None,
                       "retired": bool((d or {}).get("retired")), "source": "declared" if act.get("gear_id") else "default"}
    try:
        ids = [g for g in json.loads(act["gear_ids"] or "[]") if isinstance(g, str)]
    except (TypeError, ValueError):
        ids = []
    names = {r["gear_id"]: r["name"] for r in conn.execute("SELECT gear_id, name FROM equipment")}
    shoe_ids = {r["gear_id"] for r in conn.execute("SELECT gear_id FROM gear")}   # règle d'`equipment_usage`
    out["equipment"] = [{"gear_id": g, "name": names.get(g) or g, "unknown": g not in names}
                        for g in dict.fromkeys(ids) if g not in shoe_ids]
    return out


def altitude_exposure(conn, today: Optional[date] = None, days: Optional[int] = None) -> dict:
    """Exposition à l'altitude à l'entraînement (#185) — commande « altitude-exposure » et
    `/api/altitude-exposure`. Fenêtres de 14 et 28 j (ou `days`), temps et séances au-dessus de
    1 500 / 2 000 m d'après les échantillons FIT (`activity_sample.altitude_m`). Une séance sans
    altitude est comptée à part, jamais comme exposition nulle : voir `arc_altitude.ASSUMPTIONS["exposure"]`."""
    today = today or date.today()
    windows = (max(1, min(365, int(days))),) if days else AL.EXPOSURE_WINDOWS_DAYS
    since = today - timedelta(days=max(windows) - 1)
    weight = "CASE WHEN covered_s IS NULL OR covered_s <= 0 THEN 1.0 ELSE covered_s END"
    thr_cols = ", ".join(f"SUM(CASE WHEN altitude_m >= ? THEN {weight} END) AS ge_{t}"
                         for t in AL.EXPOSURE_THRESHOLDS_M)
    ref = "CAST(COALESCE(garmin_activity_id, intervals_activity_id, strava_activity_id) AS TEXT)"
    sql = (f"SELECT a.date, s.max_alt, s.alt_s, {', '.join('s.ge_' + str(t) for t in AL.EXPOSURE_THRESHOLDS_M)} "
           f"FROM activity a LEFT JOIN (SELECT {ref} AS ref, MAX(altitude_m) AS max_alt, "
           f"SUM(CASE WHEN altitude_m IS NOT NULL THEN {weight} END) AS alt_s, {thr_cols} "
           f"FROM activity_sample GROUP BY {ref}) s "
           f"ON s.ref = CAST(COALESCE(a.garmin_activity_id, a.intervals_activity_id, a.strava_activity_id) AS TEXT) "
           f"WHERE a.date >= ? AND a.date <= ? "
           f"AND COALESCE(a.sport, '') NOT IN ({', '.join('?' for _ in AL.EXPOSURE_EXCLUDED_SPORTS)}) "
           f"ORDER BY a.date, a.id")
    rows = []
    for r in conn.execute(sql, (*AL.EXPOSURE_THRESHOLDS_M, since.isoformat(), today.isoformat(),
                                *AL.EXPOSURE_EXCLUDED_SPORTS)):
        rows.append({"date": r["date"], "max_altitude_m": r["max_alt"], "altitude_s": r["alt_s"],
                     "above_s": {t: r[f"ge_{t}"] or 0.0 for t in AL.EXPOSURE_THRESHOLDS_M}})
    return AL.exposure_report(rows, today, windows)


POWER_HR_DEFAULT_DAYS = 180


def power_hr(conn, conf: dict, today: Optional[date] = None, days: Optional[int] = None) -> dict:
    """Home trainer — commande « power-hr » et `/api/power-hr`. Relation puissance ↔ FC calibrée sur
    les échantillons FIT des séances vélo/home trainer de la fenêtre (`arc_power.calibrate`), puissance
    par zone FC du profil, équipement déclaré (« ### Vélo & home trainer ») et dernières séances avec
    puissance. Lecture seule ; voir `arc_power.ASSUMPTIONS`."""
    today = today or date.today()
    days = max(1, min(730, int(days))) if days else POWER_HR_DEFAULT_DAYS
    since = today - timedelta(days=days - 1)
    marks = ", ".join("?" for _ in PW.POWER_SPORTS)
    acts = conn.execute(
        f"SELECT id, date, sport, name, duration_s, avg_hr_bpm, avg_power_w, normalized_power_w, "
        f"garmin_activity_id, intervals_activity_id, strava_activity_id FROM activity "
        f"WHERE sport IN ({marks}) AND date >= ? AND date <= ? ORDER BY date, id",
        (*PW.POWER_SPORTS, since.isoformat(), today.isoformat())).fetchall()
    sessions = []
    for a in acts:
        ref = next((a[c] for c in REF_COLUMNS if a[c] is not None), None)
        if ref is None:
            continue
        col = ref_column(ref)
        samples = [dict(r) for r in conn.execute(
            f"SELECT t_s, hr_bpm, power_w FROM activity_sample WHERE {col} = ? ORDER BY t_s", (ref,))]
        sessions.append({"ref": str(ref), "date": a["date"], "sport": a["sport"], "samples": samples})
    zones = athlete_hr_zone_resolution(conn, conf)
    report = PW.calibrate(sessions, zones.get("bounds_bpm"), float(S.DEFAULT_RESOLUTION_S))
    athlete = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete) if athlete else {}
    weight, weight_source = resolve_weight_kg_as_of(conn, today.isoformat(), athlete)
    recent = [{"date": a["date"], "sport": a["sport"], "name": a["name"], "duration_s": a["duration_s"],
               "avg_hr_bpm": a["avg_hr_bpm"], "avg_power_w": a["avg_power_w"],
               "normalized_power_w": a["normalized_power_w"]}
              for a in reversed(acts) if a["avg_power_w"] is not None][:5]
    return {
        **report,
        "since": since.isoformat(), "until": today.isoformat(), "days": days,
        "platform": conf.get("home_trainer_platform", "off"),
        "hr_zone_method": zones.get("method"), "hr_zone_reason": zones.get("reason"),
        "equipment": {k: athlete.get(k) for k in ("ht_trainer", "ht_bike", "bike_mass_kg", "ftp_declared_w")
                      if athlete.get(k) is not None},
        "weight_kg": weight, "weight_source": weight_source,
        "recent": recent,
        "sessions_in_window": len(acts),
    }


def power_hr_text(report: dict) -> str:
    lines = [f"Home trainer — puissance ↔ FC ({report['since']} → {report['until']})"]
    eq = report.get("equipment") or {}
    if eq:
        lines.append("Équipement : " + " · ".join(
            v for v in (eq.get("ht_trainer"), eq.get("ht_bike"),
                        f"vélo {eq['bike_mass_kg']:g} kg" if eq.get("bike_mass_kg") else None,
                        f"FTP déclarée {eq['ftp_declared_w']:g} W" if eq.get("ftp_declared_w") else None) if v))
    if report["status"] != "ok":
        lines.append(f"Calibration indisponible : {report.get('reason')}")
        return "\n".join(lines)
    f = report["fit"]
    lines.append(f"P ≈ {f['slope_w_per_bpm']:.2f} × FC {f['intercept_w']:+.0f} W "
                 f"(±{f['resid_sd_w']:.0f} W, {f['windows']} fenêtres, FC {f['hr_range_bpm'][0]}-{f['hr_range_bpm'][1]})")
    for z in report.get("zones") or []:
        flag = " (extrapolé)" if z["extrapolated"] else ""
        lines.append(f"  Z{z['zone']} {z['bounds_bpm'][0]}-{z['bounds_bpm'][1]} bpm → "
                     f"{z['power_w'][0]}-{z['power_w'][1]} W{flag}")
    return "\n".join(lines)


GAIT_DEFAULT_WEEKS = 26


def _gait_session_rows(conn, since: date, until: date) -> List[dict]:
    """Séances de COURSE (route + trail) de la fenêtre, avec la moyenne PONDÉRÉE (par `covered_s`, 1 s si
    absent) de chaque grandeur de foulée sur leurs échantillons FIT — `NULL` quand aucun échantillon ne la
    porte (jamais 0). Une seule requête, jointe par identifiant externe : `garmin_activity_id` s'il existe, sinon
    `intervals_activity_id` (#68, même règle que `_sample_ref_of`) — séances Garmin ET Intervals.icu."""
    weight = "CASE WHEN covered_s IS NULL OR covered_s <= 0 THEN 1.0 ELSE covered_s END"
    cols = []
    for metric in GT.METRICS:
        cols.append(f"SUM(CASE WHEN {metric_col(metric)} IS NOT NULL THEN {metric_col(metric)} * {weight} END) / "
                    f"NULLIF(SUM(CASE WHEN {metric_col(metric)} IS NOT NULL THEN {weight} END), 0) AS {metric}")
    marks = ",".join("?" for _ in M.RUNNING_SPORTS)
    ref = "CAST(COALESCE(garmin_activity_id, intervals_activity_id, strava_activity_id) AS TEXT)"
    sql = (f"SELECT a.id AS activity_id, a.date, a.name, a.sport, a.data_json, "
           f"{', '.join('s.' + m for m in GT.METRICS)} FROM activity a LEFT JOIN ("
           f"SELECT {ref} AS ref, {', '.join(cols)} FROM activity_sample GROUP BY {ref}) s "
           f"ON s.ref = CAST(COALESCE(a.garmin_activity_id, a.intervals_activity_id, a.strava_activity_id) AS TEXT) "
           f"WHERE a.sport IN ({marks}) AND a.date >= ? AND a.date <= ? ORDER BY a.date, a.id")
    return [dict(r) for r in conn.execute(sql, (*M.RUNNING_SPORTS, since.isoformat(), until.isoformat()))]


def metric_col(metric: str) -> str:
    return metric   # les noms de grandeur de `arc_gait.METRICS` SONT les colonnes de `activity_sample`


def gait_summary(conn, today: Optional[date] = None, weeks: int = GAIT_DEFAULT_WEEKS) -> dict:
    """Synthèse « Foulée » (#151) — commande « gait-summary » et `/api/gait`.

    Séances de course de la fenêtre (dynamique mesurée, `arc_gait.resolve_session`) + toutes les inspections
    indexées (indices d'attaque, asymétrie) + confiance et contradictions. Jamais un diagnostic, aucune
    modification de charge : voir `arc_gait.ASSUMPTIONS` et `arc_metrics.ASSUMPTIONS["gait"]`."""
    today = today or date.today()
    weeks = max(1, min(104, int(weeks)))
    since = today - timedelta(days=weeks * 7 - 1)
    sessions = []
    for row in _gait_session_rows(conn, since, today):
        try:
            arc = json.loads(row.pop("data_json") or "{}")
        except (TypeError, ValueError):
            arc = {}
        values, notes = GT.resolve_session(row, arc if isinstance(arc, dict) else {})
        sessions.append({"date": row["date"], "activity_id": row["activity_id"], "name": row["name"],
                         "sport": row["sport"], "values": values, "notes": notes})
    names = {r["gear_id"]: r["name"] for r in conn.execute("SELECT gear_id, name FROM gear")}
    return GT.gait_summary(sessions, _inspection_rows(conn), today, weeks, names)


PACE_CURVE_LOOKBACK_DAYS = 365 + CS.TREND_WINDOW_DAYS   # fenêtre 365 j + profondeur de tendance par défaut


def pace_curve(conn, today: Optional[date] = None, days: Optional[int] = None,
               lt_speed_ms: Optional[float] = None, curve_cache: Optional[dict] = None) -> dict:
    """Courbe allure-durée en GAP, vitesse critique CS et réserve anaérobie D′ (#169) — commande
    « pace-curve » et `/api/pace-curve`.

    Calculée À LA LECTURE depuis `activity_sample` (séances de course route/trail avec FIT
    ingéré, `arc_metrics.RUNNING_SPORTS`) : aucune table nouvelle. Tout le détail (fenêtres
    glissantes sur temps écoulé, couverture, refus explicites, qualité) : `arc_cs.ASSUMPTIONS`.
    `days` : profondeur de la tendance (défaut 365). `lt_speed_ms` : vitesse au seuil lactique
    fournie par l'appelant (agent), pour le contrôle de cohérence — jamais lue ici.
    N'est pas soumis à `[health].morning_check` : aucune donnée de santé.

    `curve_cache` (tableau de bord, `arc_serve.Store`, revue de code #169) : dict EN MÉMOIRE
    `ref -> (empreinte, résultat de arc_cs.activity_curve)`. L'empreinte est celle du CONTENU
    des échantillons (`_sample_stats`, comme `MetricsCache`) : des échantillons modifiés donnent
    une autre empreinte, jamais une courbe périmée. Sans lui (CLI, tests) : recalcul intégral.
    Mesuré sur 450 séances de 1 à 2 h : ~1,3 s sans cache, ~0,2 s avec."""
    today = today or date.today()
    depth = days if days and days > 0 else CS.TREND_DEFAULT_DAYS
    lookback = max(PACE_CURVE_LOOKBACK_DAYS, depth + CS.TREND_WINDOW_DAYS)
    since = (today - timedelta(days=lookback - 1)).isoformat()
    marks = ",".join("?" for _ in M.RUNNING_SPORTS)
    rows = conn.execute(
        f"SELECT id, date, {', '.join(REF_COLUMNS)} FROM activity "
        f"WHERE sport IN ({marks}) AND date >= ? AND date <= ? ORDER BY date, id",
        (*M.RUNNING_SPORTS, since, today.isoformat())).fetchall()
    curves = []
    skipped_no_grade = 0
    stats = _sample_stats(conn) if curve_cache is not None else {}
    seen = set()
    for row in rows:
        ref = activity_ref(row)
        if ref is None:
            continue
        if curve_cache is not None:
            if ref not in stats:
                continue   # aucun échantillon : même effet que la requête vide ci-dessous
            fingerprint = _digest(stats[ref])
            seen.add(ref)
            hit = curve_cache.get(ref)
            if hit is not None and hit[0] == fingerprint:
                result = hit[1]
            else:
                result = None
        else:
            result = None
        if result is None:
            samples_rows = conn.execute(
                "SELECT t_s, distance_m, altitude_m, speed_ms, covered_s "
                f"FROM activity_sample WHERE {ref_column(ref)} = ? ORDER BY t_s", (ref,)).fetchall()
            if not samples_rows:
                continue
            result = CS.activity_curve([dict(r) for r in samples_rows])
            if curve_cache is not None:
                curve_cache[ref] = (fingerprint, result)
        if result["reason_code"] == "no_grade":
            skipped_no_grade += 1
            continue
        if result["curve"]:
            curves.append({"date": row["date"], "ref": ref, "curve": result["curve"]})
    if curve_cache is not None:
        for stale in [k for k in curve_cache if k not in seen]:
            del curve_cache[stale]   # taille bornée par le nombre de séances de la période
    report = CS.build_report(curves, today, days=depth, skipped_no_grade=skipped_no_grade)
    report["threshold_check"] = CS.compare_threshold(report["current"], lt_speed_ms)
    return report


DECISION_EFFECTS_DEFAULT_DAYS = 180


def _decision_effect_data(conn) -> dict:
    """Séries lues dans l'index pour `arc_decision_effects` (aucune imputation : un jour sans mesure est
    simplement absent). Douleur = pire `score` de `health.pain` du jour ; `pain: []` explicite = 0, clé
    absente = pas de mesure."""
    health: Dict[str, dict] = {}
    for r in conn.execute("SELECT date, hrv_overnight_ms, resting_hr_bpm, readiness_score, data_json "
                          "FROM health_day ORDER BY date, source_path"):
        row = health.setdefault(r["date"], {})
        for key, col in (("hrv_ms", "hrv_overnight_ms"), ("rhr_bpm", "resting_hr_bpm"),
                         ("readiness", "readiness_score")):
            if row.get(key) is None and r[col] is not None:
                row[key] = r[col]
        try:
            pain = (json.loads(r["data_json"] or "{}") or {}).get("pain")
        except (TypeError, ValueError):
            pain = None
        if isinstance(pain, list):
            scores = [p.get("score") for p in pain if isinstance(p, dict)
                      and isinstance(p.get("score"), (int, float)) and not isinstance(p.get("score"), bool)]
            row["pain_max"] = max(scores) if scores else 0.0
    acwr = {r["date"]: r["acwr"] for r in conn.execute("SELECT date, acwr FROM metric_day") if r["acwr"] is not None}
    sessions = [dict(r) for r in conn.execute("SELECT date, rpe, decoupling_pct FROM activity")]
    planned = [dict(r) for r in conn.execute(
        "SELECT date, status FROM planned_session WHERE COALESCE(shadowed, 0) = 0")]
    return {"health": health, "acwr": acwr, "sessions": sessions, "planned": planned}


def decision_effects(conn, today: Optional[date] = None, days: Optional[int] = None,
                     trigger: Optional[str] = None) -> dict:
    """Effet des décisions (#175) — commande « decision-effects » et `/api/decision-effects`.

    Évalue (fonctions pures de `arc_decision_effects`) les décisions de la fenêtre (`days`, défaut
    `DECISION_EFFECTS_DEFAULT_DAYS`, se terminant à `today`) ; synthèse par déclencheur × action × issue
    avec avertissement de petit effectif. Le chevauchement (`overlaps`) se lit contre TOUTES les
    décisions connues, quel que soit le filtre `trigger`/`days` : une décision d'un autre déclencheur
    prise dans la même fenêtre confond tout autant l'effet. DÉRIVÉ, jamais stocké : voir
    `arc_decision_effects.ASSUMPTIONS`."""
    today = today or date.today()
    days = DECISION_EFFECTS_DEFAULT_DAYS if days is None else days
    every = decisions_query(conn)
    for d in every:
        d["id"] = Path(d["source_path"]).stem
    start = (today - timedelta(days=days - 1)).isoformat()
    rows = [d for d in every if start <= str(d.get("date") or "") <= today.isoformat()
            and (not trigger or d.get("trigger") == trigger)]
    data = _decision_effect_data(conn)
    evaluations = DE.evaluate_all(rows, data, today, context=every)
    for ev, d in zip(evaluations, rows):
        ev["summary"] = d.get("summary")
    return {"today": today.isoformat(), "days": days, "trigger": trigger, "effects": evaluations,
            "synthesis": DE.synthesize(evaluations), "min_sample_for_trend": DE.MIN_SAMPLE_FOR_TREND,
            "caveat": DE.CAVEAT}


def decision_effects_text(report: dict) -> str:
    """Rendu lisible de `decision_effects` (CLI avec `--text`)."""
    lines = [f"Effet des décisions — {report['days']} derniers jours (au {report['today']})", ""]
    if not report["effects"]:
        lines.append("Aucune décision sur cette période.")
    for g in report["synthesis"]:
        lines.append(f"• {g['statement']}")
        lines.append(f"    {g['warning']}" if g.get("warning") else f"    tendance : {g['trend']}")
    if report["effects"]:
        lines.append("")
    for ev in report["effects"]:
        why = f" ({ev['reason']})" if ev.get("reason") else ""
        lines.append(f"- {ev['date']} {ev['trigger']}/{ev['action']}/{ev['outcome']} → {ev['effect']}{why}")
    lines += ["", report["caveat"]]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", default="index",
                        choices=("index", "backfill-plan", "status", "hrv-baseline", "sleep-debt",
                                 "heat-acclimation", "altitude-exposure", "gear", "gear-attribution", "performance-index", "fueling", "samples",
                                 "zones", "gap", "decoupling", "vam", "descent", "durability",
                                 "climb-history", "decisions", "slope-model", "trail-shape", "energy", "equipment",
                                 "inspections", "gear-career", "gait-summary", "pace-curve",
                                 "decision-effects", "load-forecast", "plan-templates", "strength", "dem-check", "prevention", "plan-skeleton",
                                 "power-hr", "history-summary"))
    parser.add_argument("selector", nargs="?", default=None,
                        help="argument de la sous-commande (ex. garmin_activity_id, intervals_activity_id ou strava_activity_id "
                             "pour « samples »)")
    parser.add_argument("--workspace")
    parser.add_argument("--db")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--today", help="date de fin des séries (AAAA-MM-JJ)")
    parser.add_argument("--validate", nargs="+", metavar="FICHIER")
    parser.add_argument("--activity", metavar="ID",
                        help="commande « zones »/« gap »/« decoupling »/« vam »/« descent »/« durability »/"
                             "« energy » : temps en zone, GAP, découplage, montées/VAM, efficacité en "
                             "descente, durabilité ou dépense énergétique d'une séance (garmin_activity_id "
                             "entier, intervals_activity_id i<chiffres> ou strava_activity_id s<chiffres>)")
    parser.add_argument("--weeks", type=int, metavar="N",
                        help="commande « zones »/« decoupling »/« vam »/« descent »/« durability »/"
                             "« energy --calibration »/« gait-summary »/« history-summary » : polarisation ou tendance sur les N "
                             "dernières semaines (défaut 8 pour « zones », 12 pour « decoupling »/« vam »/"
                             "« descent »/« durability »/« history-summary », 26 pour « energy --calibration »/« gait-summary »)")
    parser.add_argument("--segment", type=int, metavar="SEGMENT_ID",
                        help="commande « climb-history » : historique complet d'un segment (#49)")
    parser.add_argument("--with-gps", action="store_true",
                        help="commande « samples » : inclut lat_deg/lon_deg dans la sortie "
                             "(désactivé par défaut depuis #49 — débogage GPS local uniquement)")
    parser.add_argument("--date", metavar="AAAA-MM-JJ",
                        help="commande « decisions »/« energy » : décisions d'une date précise, ou "
                             "séances éligibles de cette date pour « energy » "
                             "(incompatible avec --days/--since selon la commande, voir plus bas)")
    parser.add_argument("--days", type=int, metavar="N",
                        help="commande « decisions » : fenêtre glissante de N jours (>= 1) se "
                             "terminant à --today (défaut : toutes les décisions connues)")
    parser.add_argument("--since", metavar="AAAA-MM-JJ",
                        help="commande « energy » : toutes les séances éligibles depuis cette date "
                             "(incluse), ordre chronologique — incompatible avec --activity/--date ; "
                             "commande « equipment » : non utilisé (voir --last-pass)")
    parser.add_argument("--last-pass", metavar="AAAA-MM-JJ",
                        help="commande « equipment » (#134) : jour du dernier passage, EXCLU (à l'inverse de "
                             "--since de « energy », inclus) — un déclencheur en jours franchi entre ce jour "
                             "et --today marque `crossed_in_run` ; sans cette option, jamais")
    parser.add_argument("--activities", metavar="ID[,ID…]",
                        help="commande « gear » (#132) : séances synchronisées dans CE run "
                             "(garmin_activity_id, intervals_activity_id, strava_activity_id ou chemin du fichier, séparés par "
                             "des virgules) — ajoute `crossed_in_run` à la paire dont elles franchissent le seuil")
    parser.add_argument("--garmin-gear", metavar="UUID[,UUID…]",
                        help="commande « gear-attribution » (#133) : uuid du matériel Garmin (get_activity_gear ou "
                             "get_gear), séparés par des virgules")
    parser.add_argument("--chat-gear", metavar="GEAR_ID",
                        help="commande « gear-attribution » (#133) : gear_id déclaré par l'athlète en chat")
    parser.add_argument("--kit", metavar="SLUG",
                        help="commande « equipment » (#134) : objets à attribuer à une séance pour ce kit "
                             "(« trail-long »), filtrés par --sport")
    parser.add_argument("--sport", metavar="SPORT",
                        help="commande « equipment --kit » : sport de la séance (écarte les objets dont la "
                             "catégorie ne le porte pas, ex. bâtons sur route)")
    parser.add_argument("--race-plan", nargs="?", const="", metavar="FICHIER",
                        help="commande « equipment » (#134) : croise le matériel obligatoire d'un plan de "
                             "course (chemin, ou sans valeur le prochain plan) avec l'inventaire")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="commande « energy » : nombre de dernières séances éligibles à rendre "
                             "sans --activity/--date/--since (défaut 10) — incompatible avec ces trois")
    parser.add_argument("--gear", metavar="GEAR_ID",
                        help="commande « inspections » (#135) : restreint à cette paire ; commande "
                             "« gear-career » : paire dont on veut le bilan de carrière (obligatoire)")
    parser.add_argument("--unreferenced-photos", action="store_true",
                        help="commande « inspections » (#149) : ajoute `unreferenced_photos` (images de `gear/photos/` "
                             "citées par aucune inspection, boîte de dépôt) et `ignored_files` (fichiers d'un "
                             "format non pris en charge, ex. HEIC) — lecture seule")
    parser.add_argument("--assumptions", action="store_true",
                        help="commande « energy » : rend arc_energy.ASSUMPTIONS en entier au lieu du "
                             "résumé court par défaut (assumptions_summary)")
    parser.add_argument("--calibration", action="store_true",
                        help="commande « energy » : rend la calibration personnelle du modèle "
                             "(ratio médian Garmin/modèle par panier route/trail, arc_index.py "
                             "energy_calibration) au lieu du listing de séances — incompatible avec "
                             "--activity/--date/--since/--limit/--assumptions ; --weeks override la "
                             "fenêtre (défaut arc_energy.CALIBRATION_WINDOW_WEEKS, 26)")
    parser.add_argument("--trigger", choices=C.DECISION_TRIGGER,
                        help="commande « decisions » : ne garde que les décisions de ce déclencheur")
    parser.add_argument("--outcome", choices=C.DECISION_OUTCOME,
                        help="commande « decisions » : ne garde que les décisions de cette issue")
    parser.add_argument("--text", action="store_true",
                        help="commandes « decision-effects », « load-forecast », « plan-templates », « strength », « prevention » et « plan-skeleton » : "
                             "rendu texte lisible (défaut : JSON, comme les autres sous-commandes)")
    parser.add_argument("--active", action="store_true",
                        help="commande « decisions » : exclut « superseded »/« rejected_by_athlete » "
                             "(journal courant, voir DECISION_INACTIVE_OUTCOMES)")
    parser.add_argument("--months", type=int, metavar="N",
                        help="commande « slope-model » : fenêtre d'historique (mois) — sans cette option, "
                             "le modèle déjà stocké (fenêtre `[metrics].slope_model_months`) est renvoyé "
                             "tel quel ; avec elle, recalculé à la volée pour cette fenêtre (#58)")
    parser.add_argument("--lt-speed-ms", type=float, metavar="V", dest="lt_speed_ms",
                        help="commande « pace-curve » (#169) : vitesse (m/s) au seuil lactique Garmin, "
                             "pour le contrôle de cohérence avec la CS (signalé, jamais arbitré)")
    parser.add_argument("--phase", metavar="P",
                        help="commande « strength » (#191) : phase du bloc (base, development, specific, taper, "
                             "recovery — ou leur libellé français, ou l'emphase du gabarit #189)")
    parser.add_argument("--use", metavar="U",
                        help="commande « strength » (#191) : usage ciblé (descente, cheville, hanches, pied)")
    parser.add_argument("--equipment", metavar="LISTE",
                        help="commande « strength » (#191) : matériel disponible, séparé par des virgules "
                             "(none, elastic, dumbbell, step, box) ; sans lui, lu dans le profil de l'athlète")
    parser.add_argument("--acute", metavar="ZONES",
                        help="commande « prevention » (#192) : zones (séparées par des virgules) que l'athlète décrit "
                             "comme nouvelles, vives ou gonflées — aucune routine, consultation")
    parser.add_argument("--known", metavar="ZONES",
                        help="commande « prevention » (#192) : zones dont l'athlète a LUI-MÊME confirmé une gêne "
                             "connue, non aiguë et stable — lève seulement l'attente d'une deuxième déclaration")
    parser.add_argument("--garmin-json", action="store_true", dest="garmin_json",
                        help="commande « strength » (#191) : charge utile Garmin (workout_data + arguments de "
                             "create_strength_workout) au lieu de la sélection ; aucune écriture")
    parser.add_argument("--json", action="store_true",
                        help="commandes « pace-curve », « decision-effects », « load-forecast », « plan-templates », « strength » et « plan-skeleton » : "
                             "sortie JSON (déjà le défaut, accepté pour la clarté ; l'emporte sur --text)")
    parser.add_argument("--until", metavar="AAAA-MM-JJ",
                        help="commande « load-forecast » (#172) : date de fin de la projection (défaut : date de "
                             "l'objectif actif)")
    parser.add_argument("--compare", metavar="FICHIER",
                        help="commande « load-forecast » (#172) : plan modifié à comparer au plan actuel — fichier "
                             "semaine(s) (bloc ```arc ou JSON, `weeks[]` ou une semaine), `-` pour stdin ; les "
                             "semaines de même lundi REMPLACENT celles du plan actuel")
    parser.add_argument("--format", metavar="ID", dest="plan_format",
                        help="commandes « plan-templates » (#189) et « plan-skeleton » (#190) : identifiant du gabarit (ex. marathon_trail)")
    parser.add_argument("--distance-km", type=float, metavar="D", dest="distance_km",
                        help="commande « plan-templates » (#189) : choisit le gabarit d'après la distance de l'objectif")
    parser.add_argument("--race-date", metavar="AAAA-MM-JJ", dest="race_date",
                        help="commande « plan-skeleton » (#190) : date de course (défaut : objectif actif)")
    parser.add_argument("--held-hours", type=float, metavar="H", dest="held_hours",
                        help="commande « plan-skeleton » : volume hebdomadaire (heures) DÉCLARÉ par l'athlète, qui "
                             "remplace celui des 4 dernières semaines de l'index")
    parser.add_argument("--held-elevation-m", type=float, metavar="M", dest="held_elevation_m",
                        help="commande « plan-skeleton » : D+ hebdomadaire (m) déclaré")
    parser.add_argument("--long-run-day", metavar="JOUR", dest="long_run_day",
                        help="commande « plan-skeleton » : jour de la sortie longue (défaut : profil, sinon dimanche)")
    parser.add_argument("--lead-in", choices=("ramp", "flat"), default="ramp", dest="lead_in",
                        help="commande « plan-skeleton » (#204) : mise en route qui monte (ramp, défaut : ≤ +4 %%/semaine, "
                             "plafonnée par R2/R3) ou au volume tenu (flat)")
    parser.add_argument("--lead-in-weeks", type=int, metavar="K", dest="lead_in_weeks",
                        help="commande « plan-skeleton » (#204) : au moins K semaines de mise en route, prises sur le "
                             "gabarit sans jamais descendre sous son minimum")
    parser.add_argument("--write", action="store_true",
                        help="commande « plan-skeleton » : écrit les semaines dans planning/ (jamais d'écrasement) ; "
                             "sans cette option, un dry run")
    parser.add_argument("--band", choices=SL.BANDS, default="endurance",
                        help="commande « slope-model » : bande d'effort (défaut « endurance », voir "
                             "arc_slope_model.ASSUMPTIONS['population'])")
    return parser


def plan_templates_cli(args, workspace: Path) -> int:
    """`arc_index.py plan-templates` (#189) — lecture seule, sans index. Les seuils de
    cohérence viennent de `[guardrails]` du workspace (R2/R3/R6), comme `arc_guardrails`."""
    import arc_guardrails as GR   # import tardif : arc_guardrails importe arc_index
    config = load_config(workspace)
    gset = GR.guardrail_settings(config)
    limits = {k: gset[k] for k in PT.GUARDRAIL_DEFAULTS}
    if args.weeks is not None and args.weeks < 1:
        raise ConfigError(f"--weeks : un entier >= 1 attendu, « {args.weeks} » reçu.")
    if args.sport and args.sport not in PT.SPORTS:
        raise ConfigError(f"--sport : « {args.sport} » inconnu pour les gabarits (attendu : {', '.join(PT.SPORTS)}).")
    # Sans --sport : `[sport].primary` du workspace (route → gabarits route), comme arc_guardrails.
    sport = args.sport or settings(config)["sport"]
    if sport not in PT.SPORTS:
        sport = "trail"
    try:
        report = PT.plan_templates_report(
            template_id=args.plan_format, n_weeks=args.weeks, distance_km=args.distance_km,
            sport=sport, limits=limits)
    except PT.PlanTemplateError as exc:
        raise ConfigError(str(exc))
    if args.json or not args.text:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if "template" in report:
        print(PT.render_text(report["template"], report["weeks"], report["n_weeks"], report["problems"]))
        for note in report["notes"]:
            print("Remarque : " + note)
    elif report.get("matched", True) is None:
        print(report["reason"])
    else:
        for t in report["templates"]:
            d = t["distance_km"]
            print(f"{t['id']:<16} {t['sport']:<5} [{d['min']:g}, {d['max']:g}[ km  "
                  f"{t['weeks']['min']}–{t['weeks']['max']} sem. (défaut {t['weeks']['default']})  {t['label']}")
        print("Vérifications garde-fous : " + ("conforme." if not report["problems"] else "; ".join(report["problems"])))
        for note in report["notes"]:
            print("Remarque : " + note)
    return 0


def strength_cli(args, workspace: Path) -> int:
    """`arc_index.py strength` (#191) — lecture seule, sans index : la bibliothèque est livrée avec le moteur
    (`config/strength/`). JSON par défaut, `--text` lisible, `--garmin-json` pour la charge utile Garmin."""
    fmt = "garmin" if args.garmin_json else ("text" if args.text and not args.json else "json")
    try:
        profile = settings(load_config(workspace))["profile"]     # `[athlete].profile`, comme coach_doctor
        print(SG.run(args.phase, args.use, args.equipment, workspace, fmt, profile))
    except SG.StrengthError as exc:
        raise ConfigError(str(exc))
    return 0


def prevention_cli(conn, args, workspace: Path, today: date) -> str:
    """`arc_index.py prevention` (#192) — lecture seule. Seuil de consultation, agents activés et drapeau de
    risque de blessure sont lus dans la configuration vivante ; un drapeau illisible est dit, jamais supposé
    bas : `injury_risk.unavailable` vaut alors true et aucune routine n'est proposée."""
    import arc_guardrails as G      # import tardif : arc_guardrails importe arc_index
    config = load_config(workspace)
    conf = settings(config)
    gconf = G.injury_risk_settings(config)
    try:
        risk = G.evaluate_injury_risk(G.build_injury_risk_context(conn, config, gconf, today), gconf)
    except Exception:       # pragma: no cover — repli défensif : le drapeau n'est pas évalué, jamais « bas »
        risk = {"unavailable": True}
    fmt = "text" if args.text and not args.json else "json"
    try:
        return PV.run(conn, today, args.days, args.acute, args.equipment, workspace, conf["profile"],
                      gconf["pain_consult_threshold"], "medical" in conf["agents"], risk, fmt, args.known)
    except (PV.PreventionError, SG.StrengthError) as exc:
        raise ConfigError(str(exc))


def plan_skeleton_cli(args, conn, workspace: Path) -> int:
    """`arc_index.py plan-skeleton` (#190) — dry run par défaut ; `--write` écrit `planning/Semaine_*.md`."""
    import arc_plan_skeleton as PS
    today_date = date.fromisoformat(args.today) if args.today else date.today()
    for flag, value in (("--held-hours", args.held_hours), ("--held-elevation-m", args.held_elevation_m)):
        if value is not None and value < 0:
            raise ConfigError(f"{flag} : une valeur >= 0 attendue, « {value} » reçue.")
    if args.race_date:
        try:
            date.fromisoformat(args.race_date)
        except ValueError:
            raise ConfigError(f"--race-date : date AAAA-MM-JJ attendue, « {args.race_date} » reçue.")
    config = load_config(workspace)
    try:
        report = PS.skeleton_report(
            conn=conn, config=config, workspace=workspace, today=today_date, template_id=args.plan_format,
            race_date=args.race_date, held_hours=args.held_hours, held_elevation_m=args.held_elevation_m,
            long_run_day=args.long_run_day, lead_in=args.lead_in, lead_in_weeks=args.lead_in_weeks)
        PS.attach_forecast(conn, today_date, report)
    except (PS.SkeletonError, PT.PlanTemplateError) as exc:
        raise ConfigError(str(exc))
    report["conflicts"] = PS.find_conflicts(workspace, report)
    code = 0
    if args.write:
        report["write"] = PS.write_weeks(workspace, report, validate_file)
        code = 0 if report["write"]["written"] else 1
    if args.json or not args.text:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(PS.render_text(report))
        if args.write:
            w = report["write"]
            print("Écrit : " + (", ".join(w["written"]) if w["written"] else "rien — " + str(w["refused"])))
            for c in w["conflicts"]:
                print(f"  conflit : semaine du {c['week_start']} déjà dans {c['file']}")
    return code


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.today:
        try:
            date.fromisoformat(args.today)
        except ValueError:
            raise ConfigError(f"--today : date AAAA-MM-JJ attendue, « {args.today} » reçue.")

    if args.validate:
        all_ok = True
        for name in args.validate:
            ok, errors, warnings = validate_file(Path(name))
            all_ok &= ok
            print(f"{'ok' if ok else 'NON CONFORME'}: {name}")
            for line in errors:
                print(f"  erreur : {line}")
            for line in warnings:
                print(f"  attention : {line}")
        return 0 if all_ok else 1

    workspace = workspace_root(args.workspace)
    if args.command == "plan-templates":
        return plan_templates_cli(args, workspace)
    if args.command == "strength":
        return strength_cli(args, workspace)
    conn = open_db(workspace, args.db, args.memory, args.rebuild)
    counts = index_workspace(conn, workspace, args.today)
    if args.command == "hrv-baseline":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(hrv_baseline_today(conn, conf, today_date), ensure_ascii=False))
        return 0
    if args.command == "sleep-debt":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(sleep_debt_today(conn, conf, today_date), ensure_ascii=False))
        return 0
    if args.command == "heat-acclimation":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(heat_acclimation_today(conn, conf, today_date), ensure_ascii=False))
        return 0
    if args.command == "gear":
        run_refs = [r.strip() for r in args.activities.split(",") if r.strip()] if args.activities else None
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(gear_mileage(conn, today_date, run_refs), ensure_ascii=False))
        return 0
    if args.command == "gear-attribution":
        print(json.dumps(gear_attribution(conn, args.garmin_gear, args.chat_gear), ensure_ascii=False))
        return 0
    if args.command == "equipment":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        if args.kit:
            print(json.dumps(equipment_kit(conn, args.kit, args.sport), ensure_ascii=False))
        elif args.race_plan is not None:
            print(json.dumps(equipment_race_check(conn, args.race_plan, today_date, workspace), ensure_ascii=False))
        else:
            run_refs = [r.strip() for r in args.activities.split(",") if r.strip()] if args.activities else None
            since_date = date.fromisoformat(args.last_pass) if args.last_pass else None
            print(json.dumps(equipment_usage(conn, today_date, run_refs, since_date), ensure_ascii=False))
        return 0
    if args.command == "inspections":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        report = gear_inspections(conn, args.gear, today_date)
        report["declared"] = declared_gear(conn)       # (#149) toutes les paires du profil, retirées/ignorées comprises
        if args.unreferenced_photos:
            report.update(gear_photo_dropbox(conn, workspace))
        print(json.dumps(report, ensure_ascii=False))
        return 1 if "error" in report else 0
    if args.command == "prevention":
        if args.days is not None and args.days < 1:
            raise ConfigError(f"--days : un entier >= 1 attendu, « {args.days} » reçu.")
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(prevention_cli(conn, args, workspace, today_date))
        return 0
    if args.command == "decision-effects":
        if args.days is not None and args.days < 1:
            raise ConfigError(f"--days : un entier >= 1 attendu, « {args.days} » reçu.")
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        report = decision_effects(conn, today_date, args.days, args.trigger)
        print(decision_effects_text(report) if args.text and not args.json else json.dumps(report, ensure_ascii=False))
        return 0
    if args.command == "power-hr":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        report = power_hr(conn, settings(load_config(workspace)), today_date, args.days)
        print(power_hr_text(report) if args.text else json.dumps(report, ensure_ascii=False))
        return 0
    if args.command == "altitude-exposure":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(altitude_exposure(conn, today_date, args.days), ensure_ascii=False))
        return 0
    if args.command == "gait-summary":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(gait_summary(conn, today_date, args.weeks or GAIT_DEFAULT_WEEKS), ensure_ascii=False))
        return 0
    if args.command == "load-forecast":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        report = load_forecast(conn, today_date, args.until, args.compare)
        if args.text:
            import arc_load_forecast as LF
            print(LF.render_text(report))
        else:
            print(json.dumps(report, ensure_ascii=False))
        return 0
    if args.command == "plan-skeleton":
        return plan_skeleton_cli(args, conn, workspace)
    if args.command == "gear-career":
        if not args.gear:
            raise ConfigError("commande « gear-career » : --gear GEAR_ID est obligatoire.")
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        career = gear_career(conn, args.gear, today_date)
        print(json.dumps(career, ensure_ascii=False))
        return 1 if "error" in career else 0
    if args.command == "pace-curve":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        if args.days is not None and args.days < 1:
            raise ConfigError(f"--days : un entier >= 1 attendu, « {args.days} » reçu.")
        print(json.dumps(pace_curve(conn, today_date, args.days, args.lt_speed_ms), ensure_ascii=False))
        return 0
    if args.command == "performance-index":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(performance_index(conn, today_date), ensure_ascii=False))
        return 0
    if args.command == "fueling":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(fueling_trend(conn, today_date), ensure_ascii=False))
        return 0
    if args.command == "backfill-plan":
        out = write_backfill(conn, workspace)
        print(f"{len(backfill_items(conn))} fichier(s) à reprendre — {out}")
        return 0
    if args.command == "samples":
        if not args.selector:
            raise ConfigError("commande « samples » : identifiant de séance attendu "
                               "(ex. arc_index.py samples 19287537093, ou samples i123456789).")
        result = samples_by_ref(conn, parse_activity_selector(args.selector, "samples"))
        # `--with-gps` (#49, revue de code, nit) : lat_deg/lon_deg RETIRÉS par défaut de la
        # sortie CLI — même si la position n'est pas une fuite nouvelle en soi (déjà lisible
        # dans le fichier `activities/fit/<id>.json` source, voir `samples_by_garmin_id`),
        # un CLI copié/collé sans y penser (log, chat de support) ne doit pas se mettre à
        # exposer une coordonnée qu'il n'exposait jamais avant #49 — sécurité par défaut.
        if not args.with_gps:
            for rec in result.get("samples", []):
                rec.pop("lat_deg", None)
                rec.pop("lon_deg", None)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "zones":
        conf = settings(load_config(workspace))
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        if args.activity is not None:
            print(json.dumps(activity_zone_report(conn, conf, parse_activity_selector(args.activity, "zones")),
                             ensure_ascii=False))
            return 0
        weeks = args.weeks if args.weeks and args.weeks > 0 else 8
        result = {
            **athlete_hr_zone_resolution(conn, conf),
            "weekly_polarisation": weekly_polarisation(conn, weeks, today_date),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "gap":
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is None:
            raise ConfigError("commande « gap » : garmin_activity_id attendu "
                               "(--activity ou argument positionnel, ex. arc_index.py gap 19287537093).")
        print(json.dumps(activity_gap_report(conn, ref), ensure_ascii=False))
        return 0
    if args.command == "dem-check":
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is None:
            raise ConfigError("commande « dem-check » : identifiant de séance requis (--activity ou argument positionnel).")
        print(json.dumps(activity_dem_check(conn, workspace, ref), ensure_ascii=False))
        return 0
    if args.command == "decoupling":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is not None:
            print(json.dumps(activity_decoupling_report(conn, ref), ensure_ascii=False))
            return 0
        print(json.dumps(decoupling_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "vam":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is not None:
            print(json.dumps(activity_climb_report(conn, ref), ensure_ascii=False))
            return 0
        print(json.dumps(vam_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "descent":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is not None:
            print(json.dumps(activity_descent_report(conn, ref), ensure_ascii=False))
            return 0
        print(json.dumps(descent_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "durability":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is not None:
            print(json.dumps(activity_durability_report(conn, ref), ensure_ascii=False))
            return 0
        print(json.dumps(durability_trend(conn, today_date, args.weeks), ensure_ascii=False))
        return 0
    if args.command == "energy":
        if args.calibration:
            # `--calibration` rend un rapport DIFFÉRENT (calibration personnelle du
            # modèle, `energy_calibration`) — incompatible avec tout sélecteur/
            # --limit/--assumptions, qui n'auraient aucun sens ici (jamais une
            # précédence silencieuse, même discipline que --limit + sélecteur
            # ci-dessous). `--weeks` reste le SEUL argument partagé, pour overrider
            # la fenêtre par défaut (`arc_energy.CALIBRATION_WINDOW_WEEKS`, 26).
            if any(v is not None for v in (args.activity, args.date, args.since, args.limit)) \
                    or args.selector or args.assumptions:
                raise ConfigError("commande « energy --calibration » : incompatible avec "
                                   "--activity/--date/--since/--limit/--assumptions ou l'argument "
                                   "positionnel — seul --weeks (fenêtre) s'applique.")
            today_date = date.fromisoformat(args.today) if args.today else date.today()
            weeks = args.weeks if args.weeks and args.weeks > 0 else EN.CALIBRATION_WINDOW_WEEKS
            print(json.dumps(energy_calibration(conn, today_date, weeks), ensure_ascii=False))
            return 0
        # Positionnel ET --activity en même temps (revue de code) : ambigu, jamais
        # une précédence silencieuse (contrairement aux autres sous-commandes, où
        # le positionnel n'est qu'un ALIAS de --activity et les deux ne sont
        # jamais fournis ensemble par erreur en pratique) — rejeté explicitement.
        if args.activity is not None and args.selector:
            raise ConfigError("commande « energy » : passez l'identifiant de séance soit en argument "
                               "positionnel, soit via --activity, jamais les deux à la fois.")
        # Un SEUL sélecteur à la fois — même discipline que `--date`/`--days` pour
        # `decisions` : jamais une précédence silencieuse entre --activity/--date/--since.
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        selectors_used = sum(1 for v in (ref, args.date, args.since) if v is not None)
        if selectors_used > 1:
            raise ConfigError("commande « energy » : --activity/--date/--since sont incompatibles "
                               "entre eux, choisissez un seul sélecteur.")
        if args.date:
            try:
                date.fromisoformat(args.date)
            except ValueError:
                raise ConfigError(f"--date : date AAAA-MM-JJ attendue, « {args.date} » reçue.")
        if args.since:
            try:
                date.fromisoformat(args.since)
            except ValueError:
                raise ConfigError(f"--since : date AAAA-MM-JJ attendue, « {args.since} » reçue.")
        if args.limit is not None and args.limit < 1:
            raise ConfigError(f"--limit : un entier >= 1 attendu, « {args.limit} » reçu.")
        # --limit ne s'applique qu'à la liste PAR DÉFAUT (revue de code) : combiné à
        # un sélecteur, il ne serait jamais utilisé (`energy_report` l'ignore dans
        # ce cas) — un appelant qui le fournit croit presque toujours, à tort,
        # qu'il borne le résultat d'un sélecteur ; rejeté explicitement plutôt que
        # silencieusement sans effet.
        if args.limit is not None and selectors_used >= 1:
            raise ConfigError("commande « energy » : --limit ne s'applique qu'à la liste par défaut "
                               "(sans --activity/--date/--since), où il n'aurait aucun effet.")
        print(json.dumps(energy_report(conn, activity=ref, day=args.date, since=args.since,
                                        limit=args.limit or ENERGY_DEFAULT_LIMIT,
                                        assumptions=args.assumptions), ensure_ascii=False))
        return 0
    if args.command == "climb-history":
        # #49 : `--segment ID` prime (historique direct d'un segment) ; sinon `--activity
        # GARMIN_ID` (ou l'argument positionnel, même convention que les autres
        # sous-commandes) rend l'historique de CHAQUE segment gravi par cette activité ;
        # sans argument, la liste de tous les segments connus (résumé, jamais l'historique
        # complet de chacun — trop volumineux pour un usage courant).
        if args.segment is not None:
            print(json.dumps(climb_segment_history(conn, args.segment), ensure_ascii=False))
            return 0
        ref = parse_activity_selector(args.activity if args.activity is not None else args.selector, args.command)
        if ref is not None:
            act_row = conn.execute(
                f"SELECT id FROM activity WHERE {ref_column(ref)} = ?", (ref,)).fetchone()
            if act_row is None:
                print(json.dumps({"activity_id": None, "segments": [],
                                   "reason": unknown_activity_reason(ref),
                                   "reason_code": "unknown_activity"}, ensure_ascii=False))
                return 0
            seg_ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT segment_id FROM activity_climb WHERE activity_id = ? "
                "AND segment_id IS NOT NULL", (act_row[0],)).fetchall()]
            print(json.dumps(
                {"activity_id": act_row[0], "segments": [climb_segment_history(conn, sid) for sid in seg_ids]},
                ensure_ascii=False))
            return 0
        print(json.dumps({"segments": climb_segment_list(conn)}, ensure_ascii=False))
        return 0
    if args.command == "decisions":
        if args.date:
            try:
                date.fromisoformat(args.date)
            except ValueError:
                raise ConfigError(f"--date : date AAAA-MM-JJ attendue, « {args.date} » reçue.")
        if args.date and args.days is not None:
            # Ambigu, jamais résolu silencieusement (#100, revue de code) : le
            # `on_date` prime sur `days` DANS `decisions_query` (pour un appelant
            # Python qui garderait `days` par défaut d'un appel générique), mais la
            # CLI, elle, force l'appelant humain/headless à choisir.
            raise ConfigError("commande « decisions » : --date et --days sont incompatibles, "
                               "choisissez l'un ou l'autre.")
        if args.days is not None and args.days < 1:
            raise ConfigError(f"--days : un entier >= 1 attendu, « {args.days} » reçu.")
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        result = decisions_query(conn, today_date, args.days, args.trigger, args.date,
                                  args.outcome, args.active)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "slope-model":
        conf = settings(load_config(workspace))
        if args.months is not None:
            if args.months < 1:
                raise ConfigError(f"--months : un entier >= 1 attendu, « {args.months} » reçu.")
            print(json.dumps(recompute_slope_model(conn, conf, args.band, args.months, args.today),
                              ensure_ascii=False))
            return 0
        print(json.dumps(slope_model_report(conn, args.band), ensure_ascii=False))
        return 0
    if args.command == "history-summary":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(history_summary(conn, today_date, args.weeks or HISTORY_DEFAULT_WEEKS),
                         ensure_ascii=False))
        return 0
    if args.command == "trail-shape":
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        print(json.dumps(trail_shape_report(conn, today_date), ensure_ascii=False))
        return 0
    if args.command == "status":
        by_status = {row[0]: row[1] for row in conn.execute(
            "SELECT parsed_ok, COUNT(*) FROM source_file WHERE kind IS NOT NULL GROUP BY parsed_ok")}
        print(json.dumps({
            "workspace": str(workspace), **counts, "files": by_status,
            "samples": sample_coverage(conn),
        }, ensure_ascii=False))
        return 0
    print(f"index : {counts['indexed']} lu(s), {counts['unchanged']} inchangé(s), "
          f"{counts['removed']} retiré(s) — {workspace / DEFAULT_DB if not args.memory and not args.db else args.db or ':memory:'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(1)
