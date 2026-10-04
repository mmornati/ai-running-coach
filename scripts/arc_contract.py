#!/usr/bin/env python3
"""Contrat de données des fichiers persistés par les agents (bloc ```arc).

Chaque fichier écrit par un agent (activité, santé, météo, semaine, nutrition,
rapport, plan de course…) s'ouvre, juste après son titre, par un bloc clos
étiqueté `arc` contenant un objet JSON. Ce module en est la définition
exécutable : le schéma par type (`kind`), l'extraction du bloc et la
validation.

Le schéma est documenté pour les agents dans
`skills/workspace-data-contract/SKILL.md`. Les deux sont tenus d'accord par
`tests/data/test_arc_contract.py` : chaque exemple du skill doit valider, et
chaque clé du schéma doit y être documentée.

Règles transverses :
- toujours en unités SI (m, s, kg, bpm, °C, km/h, mm), quel que soit
  `[athlete].units` — la conversion est une affaire d'affichage ;
- une mesure absente est absente (clé omise ou `null`), jamais 0 ;
- une clé inconnue est signalée (avertissement) : c'est presque toujours une
  faute de frappe qui ferait perdre la valeur en silence.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Optional

ARC_VERSION = 1

# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------

# Types de fichiers d'activité (AGENTS.md) + sports croisés (`[sport].disciplines`).
SPORTS = (
    "running", "trail", "strength", "indoor_cycling", "home_trainer", "hiking",
    "elliptical", "rest", "cycling", "swimming", "rowing", "walking",
)
MORNING_CHECK = ("full", "minimal", "off")
HRV_STATUS = ("balanced", "unbalanced", "low", "poor", "no_status")
# Statut de la ligne de base HRV PERSONNELLE (#34, scripts/arc_metrics.py::hrv_baseline_series),
# distinct de HRV_STATUS (le statut Garmin). Persisté par l'agent qui a lu la sortie de
# `scripts/arc_index.py hrv-baseline` au moment du bilan matinal, pas recalculé à la volée
# depuis ce fichier (le tableau de bord, lui, recalcule toujours en direct).
HRV_PERSONAL_STATUS = ("sous", "dans_la_norme", "au_dessus", "en_construction")
VERDICT = ("green", "amber", "red")
# Contexte du cycle menstruel (#166, opt-in `[health].cycle_tracking`) — voir scripts/arc_cycle.py.
CYCLE_PHASE = ("menstrual", "follicular", "ovulation", "luteal")
CYCLE_SOURCE = ("garmin", "intervals", "manual")
CYCLE_DAY_PLAUSIBLE = (1, 60)
# Apports poussés vers Garmin Connect (#167, opt-in `[nutrition].garmin_sync`) — voir
# scripts/arc_nutrition_sync.py : source du jour et nature des écritures tracées.
INTAKE_SOURCE = ("manual", "garmin")
GARMIN_PUSH_KIND = ("create_custom_food", "log_custom_food", "log_food", "add_hydration_data")
WEATHER_CATEGORY = ("green", "yellow", "orange", "red")
SLOT = ("morning", "midday", "evening", "none")
# Action recommandée par l'ajustement chaleur d'une séance (#171, `scripts/arc_heat.py`).
HEAT_ACTION = ("none", "slow_pace", "prefer_cool_slot", "lower_pace_targets",
               "reschedule_or_lighten", "reschedule_or_indoor")
# Base de `heat_adjustment.temp_c` : température du créneau ou ressenti (s'il est plus élevé).
HEAT_TEMP_BASIS = ("temperature", "feels_like")
INTENSITY = (
    "rest", "recovery", "endurance", "tempo", "threshold", "vo2max", "race", "strength",
)
SESSION_STATUS = ("planned", "done", "missed", "moved", "cancelled")
# Type de semaine d'un squelette de bloc (#190, `scripts/arc_plan_skeleton.py`).
WEEK_TYPE = ("build", "recovery", "taper", "race", "lead_in", "post_race")
REPORT_TYPE = ("weekly", "monthly", "comparison", "race", "race_debrief", "adhoc")
COURSE_VERDICT = ("compatible", "partial", "incompatible")
WATER_SOURCE = ("officiel", "osm_drinking_water", "osm_spring", "osm_cafe")
# `race_plan.segments[].source` (#59) : provenance de la prédiction de vitesse du
# segment — mêmes valeurs que `arc_slope_model.predict_speed`, jamais une
# quatrième valeur inventée ici (voir `arc_slope_model.py` pour la sémantique de
# "mixed" : vraie interpolation entre un panier personnel et un panier générique).
SEGMENT_SOURCE = ("personal", "generic", "mixed")
# `race_plan.segments[].reason_code` (#59) : raison informative attachée à la
# prédiction d'un segment — mêmes valeurs que celles réellement émises par
# `scripts/arc_race_pacing.py::predict_segments` (jamais toute la liste de
# `arc_slope_model.predict_speed`, qui en connaît d'autres non pertinentes une
# fois agrégées au niveau du segment).
RACE_SEGMENT_REASON_CODE = ("extrapolated", "no_model", "missing_elevation")

# `decision` (#54) : traçabilité d'un ajustement du coach — déclencheur, entrées
# qui l'ont justifié, règles de garde-fous concernées (#52), avant/après de la
# séance touchée, issue. `DECISION_TRIGGER`/`DECISION_OUTCOME` ci-dessous.
DECISION_TRIGGER = (
    "morning_check", "guardrail", "athlete_request", "medical", "weather", "race", "other",
)
DECISION_OUTCOME = ("applied", "proposed", "rejected_by_athlete", "superseded")

# `decision.rule_ids` référence les `rule_id` de `scripts/arc_guardrails.py`
# (r1_acwr_projected … r7_consecutive_quality). Ce module ne les importe PAS :
# `arc_guardrails` importe déjà `arc_index`, qui importe ce module — un import
# dans l'autre sens créerait un cycle. La forme `rN_nom_de_regle` est donc
# validée par un PATTERN, jamais contre la liste vivante des règles connues
# (voir `skills/workspace-data-contract/SKILL.md`, section `decision`, pour le
# renvoi explicite vers `arc_guardrails.RULE_IDS`).
RULE_ID_RE = re.compile(r"^r\d+_[a-z][a-z0-9_]*$")

# `gear_inspection` (#135) : inspection photo d'une paire. `condition` reprend le vocabulaire
# 🟢/🟡/🟠/🔴 (mêmes valeurs que `WEATHER_CATEGORY`, jamais un second vocabulaire de couleur) ;
# `wear_zones[].zone` nomme un endroit de la semelle (jamais un diagnostic) ; `gait_hints` reste
# un INDICE de foulée, jamais une conclusion clinique — voir `skills/gear-inspection/SKILL.md`.
GEAR_CONDITION = ("green", "yellow", "orange", "red")
GEAR_SIDE = ("left", "right")
GEAR_WEAR_ZONE = (
    "heel_posterolateral", "heel_lateral", "heel_medial", "heel_central",
    "midfoot_lateral", "midfoot_medial", "midfoot_central",
    "forefoot_lateral", "forefoot_medial", "forefoot_central", "toe",
)
GEAR_WEAR_SEVERITY = ("light", "moderate", "marked")
GEAR_ASYMMETRY_LEVEL = ("none", "mild", "marked")
GEAR_GAIT_HINT = ("heel_strike", "midfoot_forefoot_strike", "pronation_hint", "supination_hint")
GEAR_INSPECTION_FOLDER = "gear"
GEAR_PHOTO_DIR = "gear/photos/"
GEAR_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
GEAR_PHOTOS_MAX = 12
GEAR_LUG_DEPTH_MM_PLAUSIBLE_MAX = 15.0

# Matériel, sudation, glucides pendant l'effort (#39 — champs consommés par #40
# kilométrage chaussures, #41 KPI glucides/h et taux de sudation).
GEAR_ID_MAX_LEN = 40
# `activity.gear_ids` (#134) : nombre maximal d'objets par séance (un kit complet tient largement).
GEAR_IDS_MAX = 30
# Format slug : minuscules, chiffres, tirets simples, jamais en tête/fin — même
# convention que la plupart des identifiants stables lisibles par un humain
# (ex. "hoka-speedgoat-5-bleue"). La section « Matériel & lieux » du profil
# (`templates/Runner_Profile.template.md`) reste du texte libre écrit par
# l'athlète : `gear_slug()` ci-dessous est la règle PARTAGÉE qui en dérive un
# identifiant — utilisée par #40 pour lire le profil, et par le coach pour
# choisir le `gear_id` d'une activité à partir du nom de modèle donné par
# l'athlète (voir `agents/coach.md`).
GEAR_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_GEAR_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def gear_slug(label: str) -> str:
    """Dérive un `gear_id` (slug) d'un libellé de matériel en texte libre.

    Règle PARTAGÉE entre #39 (validation), #40 (lecture de la section
    « Matériel » du profil, un `gear_id` explicite dans la ligne de l'athlète
    restant prioritaire sur cette dérivation automatique) et le coach (choix du
    `gear_id` d'une activité à partir du nom de modèle cité par l'athlète) :
    1. décomposition Unicode (NFKD) puis suppression des marques diacritiques
       — « Hoka Speedgoat 5 Bleue » perd ses accents avant tout le reste ;
    2. minuscules ;
    3. toute suite de caractères non alphanumériques (espaces, apostrophes,
       ponctuation) devient un tiret unique ;
    4. tirets de tête/fin retirés ;
    5. coupé à `GEAR_ID_MAX_LEN` caractères, puis un éventuel tiret de fin
       laissé par la coupe est retiré à son tour.

    Rend une chaîne vide si `label` ne contient aucun caractère alphanumérique
    — à l'appelant de décider (ex. : ne pas écrire `gear_id` du tout plutôt
    qu'une chaîne vide, qui échouerait de toute façon la validation du
    contrat)."""
    decomposed = unicodedata.normalize("NFKD", label)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    slug = _GEAR_SLUG_NON_ALNUM_RE.sub("-", stripped.lower()).strip("-")
    return slug[:GEAR_ID_MAX_LEN].rstrip("-")
CARBS_G_PLAUSIBLE_MAX = 1000        # ravitaillement pendant l'effort ; au-delà, faute de frappe probable
FLUID_INTAKE_ML_PLAUSIBLE_MAX = 10000
BODY_WEIGHT_KG_PLAUSIBLE = (30.0, 200.0)
# Pesée après effort supérieure à avant : n'arrive normalement pas (perte hydrique),
# mais une petite marge absorbe l'imprécision d'une pesée maison (habits, balance).
# Au-delà, avertissement (pas une erreur) : `sweat_rate_l_h` (arc_metrics.py) ignore
# de toute façon un résultat négatif plutôt que de le rejeter ici en amont.
WEIGHT_POST_TOLERANCE_KG = 1.0

# `health.pain` (#57, revue de code #104, nit) : une liste plus longue sent la
# faute de saisie (copier-coller, entrées dupliquées) plutôt qu'un vrai
# inventaire de zones douloureuses distinctes le même jour — avertissement,
# jamais une erreur (un cas légitime, quoique rare, reste possible).
PAIN_MAX_ENTRIES = 10

# Colonnes de splits reconnues. `km` et `duration_s` sont obligatoires ; les
# autres sont facultatives et dans n'importe quel ordre, puisque l'en-tête est
# déclaré dans la donnée (`splits_cols`).
SPLIT_COLUMNS = {
    "km": "int+",
    "distance_m": "num+",
    "duration_s": "num+",
    "elev_gain_m": "num+",
    "elev_loss_m": "num+",
    "avg_hr_bpm": "hr",
    "max_hr_bpm": "hr",
    "max_speed_kmh": "num+",
    "cadence_spm": "num+",
    "label": "str",
}
SPLIT_REQUIRED = ("km", "duration_s")

# Clés reconnues de `activity.time_in_zone_s` (#51, revue de code) — les 5 zones
# HR affichées, jamais les bornes de polarisation Seiler (`low`/`moderate`/`high`,
# voir `scripts/arc_index.py zones`, table `hr_polarisation_time`), qui ne sont
# pas ce champ.
TIME_IN_ZONE_KEYS = ("z1", "z2", "z3", "z4", "z5")

# Plage plausible d'un découplage Pa:HR (%, signe libre) — un avertissement, pas
# une erreur : une dérive négative franche (l'athlète « monte en régime ») ou un
# découplage élevé sur une séance dégradée restent possibles, mais une valeur
# hors de cette plage sent la faute de frappe ou la recopie d'un mauvais champ.
DECOUPLING_PCT_PLAUSIBLE = (-50.0, 100.0)

# ---------------------------------------------------------------------------
# Schéma
#
# Types :
#   int / int+   entier (≥ 0 pour int+)       num / num+  nombre (≥ 0 pour num+)
#   hr           fréquence cardiaque, 20-250  score       0-100
#   rpe          0-10                         str         chaîne non vide
#   date         AAAA-MM-JJ                   datetime    ISO 8601
#   bool         true / false                 obj         objet JSON libre
#   list         liste JSON libre             enum:a|b    une des valeurs
#   [kind]       liste d'objets validés par le sous-schéma `kind`
# ---------------------------------------------------------------------------


GEAR_SOURCES = ("garmin", "chat", "garmin_unmapped")


def _enum(values) -> str:
    return "enum:" + "|".join(values)


SCHEMA = {
    "activity": {
        "required": {"date": "date", "sport": _enum(SPORTS), "duration_s": "num+"},
        "optional": {
            "garmin_activity_id": "int+",
            # Intervals.icu (#68, `[data].source = "intervals"`) : identifiant
            # d'activité de CE serveur, une CHAÎNE (ex. "i12345678") — jamais le
            # même champ que `garmin_activity_id` (entier), les deux ne
            # partagent ni le type ni l'espace de nommage. Une activité
            # synchronisée depuis Intervals.icu porte celui-ci et omet
            # `garmin_activity_id`, jamais l'inverse.
            "intervals_activity_id": "str",
            # Strava (#164, `[data].source = "strava"`) : identifiant d'activité Strava
            # préfixé « s » (ex. "s12345678901") — l'API rend un entier sans préfixe,
            # indiscernable d'un `garmin_activity_id` ; le préfixe est la convention du
            # projet (voir `arc_samples.STRAVA_ID_RE`). Mêmes règles que ci-dessus :
            # une activité Strava porte celui-ci et omet les deux autres.
            "strava_activity_id": "strava_id",
            "name": "str",
            "location": "str",
            "start_time": "datetime",
            "distance_m": "num+",
            "moving_duration_s": "num+",
            "elevation_gain_m": "num+",
            "elevation_loss_m": "num+",
            "avg_hr_bpm": "hr",
            "max_hr_bpm": "hr",
            "recovery_hr_bpm": "int+",
            "avg_cadence_spm": "num+",
            "calories_kcal": "num+",
            # Part métabolisme de base : copie déclarative du champ
            # `bmr_calories` du MCP `get_activity` (Garmin), jamais recalculée — voir
            # `skills/garmin-sync-efficiency/SKILL.md`. Sert à dériver un net Garmin
            # (`calories_kcal` − `calories_bmr_kcal`) comparable au résultat NET du
            # moteur `scripts/arc_energy.py` (`scripts/arc_index.py energy`), qui lui
            # calcule sa PROPRE dépense BRUTE depuis les échantillons FIT — jamais
            # l'inverse (cette clé ne nourrit ni ne remplace ce calcul dérivé, voir
            # `validate()` pour la seule règle transverse : ne peut dépasser
            # `calories_kcal` quand les deux sont connues).
            "calories_bmr_kcal": "num+",
            "training_effect_aerobic": "num+",
            "training_effect_anaerobic": "num+",
            "rpe": "rpe",
            "splits_cols": "list",
            "splits": "list",
            "gear_id": "gear_id",
            # #133 : provenance du `gear_id` — « garmin » (matériel attaché par la montre,
            # `get_activity_gear`) ou « chat » (déclaré par l'athlète) ; « garmin_unmapped » =
            # la montre a attaché un matériel SANS puce correspondante (ou ambigu/ignoré) : SANS
            # `gear_id`, et exclu de l'attribution par défaut (`arc_metrics.gear_mileage`).
            # Jamais « default » : sans `gear_id`, la paire par défaut est calculée à la lecture.
            "gear_source": _enum(GEAR_SOURCES),
            "carbs_g": "carbs_g",
            "fluid_intake_ml": "fluid_ml",
            "weight_pre_kg": "body_weight_kg",
            "weight_post_kg": "body_weight_kg",
            # #134 : matériel hors chaussures porté sur la séance (liste de slugs, `gear_id` reste
            # LA chaussure). Absent = aucun objet attribué, jamais « aucun » écrit en liste vide
            # (une liste vide est acceptée mais sans effet). Ancien fichier sans `gear_ids` : valide.
            "gear_ids": "gear_id_list",
            # #167 : apport en cours d'effort (`/log`) poussé vers Garmin Connect, après un « oui »
            # explicite — trace d'idempotence (voir SUBSCHEMA["garmin_push"]), jamais écrite en headless.
            "garmin_pushed": "[garmin_push]",
            "missing_reason": "obj",
            # KPI FIT (#51, épopée #21) : snapshot narratif écrit par le coach APRÈS
            # avoir lu la sortie des CLI dédiées (`scripts/arc_index.py gap/decoupling/
            # zones/vam --activity ID`) — jamais recalculé à la main. `scripts/arc_index.py`
            # recalcule sa PROPRE copie de ces mêmes grandeurs dans l'index SQLite à
            # chaque passage, directement depuis les échantillons FIT ingérés : c'est
            # TOUJOURS elle qui fait foi pour le tableau de bord et les requêtes, jamais
            # cette copie Markdown (voir `skills/workspace-data-contract/SKILL.md`, section
            # « Champs KPI FIT »). `gap_pace_s_km`/`decoupling_pct`/`ef_whole` reprennent
            # le nom EXACT de la colonne dérivée correspondante (`activity.gap_pace_s_km`/
            # `decoupling_pct`/`ef_whole`) ; `time_in_zone_s` et `best_climb_vam_m_h` sont
            # des clés DÉLIBÉRÉMENT différentes de leur source (`hr_zone_time`, clés `1`…`5`
            # plutôt que `z1`…`z5` ; `activity.best_climb_vam_elapsed_m_h`, pas
            # `best_vam_10min_m_h`/`best_vam_20min_m_h`, deux fenêtres glissantes distinctes
            # d'une MEILLEURE MONTÉE gravie) — le mapping exact est documenté dans le skill,
            # jamais à deviner depuis le nom seul.
            "gap_pace_s_km": "num+",
            "decoupling_pct": "decoupling_pct",
            "ef_whole": "num+",
            "time_in_zone_s": "obj",
            "best_climb_vam_m_h": "num+",
            # Dynamique de course (#151) : moyennes de séance de la montre Garmin (champs FIT
            # `avg_stance_time`, `avg_stance_time_balance`, `avg_vertical_oscillation`,
            # `avg_vertical_ratio`, `avg_step_length`), SI. Clé ABSENTE = non mesurée — jamais 0, jamais
            # 50 % de balance. REPLI seulement : quand les échantillons FIT de la séance sont ingérés
            # (`activity_sample`), `arc_index.py gait-summary` calcule sa propre moyenne et c'est elle qui
            # fait foi. La balance est un ÉCART à 50 % (le côté du pourcentage n'est pas établi).
            "avg_ground_contact_s": "num+",
            "avg_stance_balance_pct": "stance_balance_pct",
            "avg_vertical_oscillation_m": "num+",
            "avg_vertical_ratio_pct": "gait_pct",
            "avg_step_length_m": "num+",
        },
    },
    "health": {
        "required": {"date": "date", "morning_check": _enum(MORNING_CHECK)},
        "optional": {
            "sleep_total_s": "num+",
            "sleep_deep_s": "num+",
            "sleep_light_s": "num+",
            "sleep_rem_s": "num+",
            "sleep_awake_s": "num+",
            "sleep_score": "score",
            "sleep_start": "datetime",
            "sleep_end": "datetime",
            "hrv_overnight_ms": "num+",
            "hrv_baseline_low_ms": "num+",
            "hrv_baseline_high_ms": "num+",
            "hrv_status": _enum(HRV_STATUS),
            "hrv_personal_low_ms": "num+",
            "hrv_personal_high_ms": "num+",
            "hrv_personal_status": _enum(HRV_PERSONAL_STATUS),
            "resting_hr_bpm": "hr",
            "readiness_score": "score",
            "readiness_factors": "obj",
            "body_battery_high": "score",
            "body_battery_low": "score",
            "stress_avg": "score",
            "weight_kg": "num+",
            "verdict": _enum(VERDICT),
            "verdict_reason": "str",
            "missing_reason": "obj",
            # #57 : douleur structurée déclarée le jour du fichier — voir SUBSCHEMA["pain"].
            "pain": "[pain]",
            # #166 : contexte du cycle (opt-in `[health].cycle_tracking`, jamais écrit à "off") —
            # un CONTEXTE de lecture du bilan matinal, jamais une règle ni un diagnostic.
            "cycle_phase": _enum(CYCLE_PHASE),
            "cycle_day": "cycle_day",
            "cycle_source": _enum(CYCLE_SOURCE),
        },
    },
    "weather": {
        "required": {
            "date": "date",
            "location": "str",
            "category": _enum(WEATHER_CATEGORY),
        },
        "optional": {
            "temp_min_c": "num",
            "temp_max_c": "num",
            "feels_like_c": "num",
            "humidity_pct": "score",
            "wind_kmh": "num+",
            "gust_kmh": "num+",
            "wind_dir_deg": "num+",
            "precip_mm": "num+",
            "chance_of_rain_pct": "score",
            "uv_index": "num+",
            "thunderstorm": "bool",
            "sunrise": "str",
            "sunset": "str",
            "best_slot": _enum(SLOT),
            "slot_reason": "str",
            "source": "str",
            "fetched_at": "datetime",
        },
    },
    "week": {
        # #69 : un fichier `week` porte soit UNE semaine (les champs `required`
        # ci-dessous, au premier niveau — format historique, INCHANGÉ), soit
        # PLUSIEURS (`weeks`, liste d'objets `week_entry` — voir
        # `SUBSCHEMA["week_entry"]` juste en dessous). `validate()` court-circuite
        # `_check_object` pour ce `kind` (voir `_validate_week`) : ce `required`
        # sert donc à DEUX choses seulement — documenter le format historique, et
        # rester le repli legacy (`read_file`, fichier sans bloc ```arc du tout,
        # ancien format Markdown d'avant ce contrat) qui, lui, continue de lire
        # `SCHEMA["week"]["required"]` tel quel. Ne JAMAIS le vider : un fichier
        # `week` pré-contrat redeviendrait alors toujours « inutilisable »
        # (`read_file`, `usable`), même quand `L.legacy_week` en a bien extrait
        # `week_start`.
        "required": {
            "week_start": "date",
            "location": "str",
            "sessions": "[session]",
        },
        "optional": {
            "phase": "str",
            "target_duration_s": "num+",
            "target_distance_m": "num+",
            "target_elevation_m": "num+",
            # #190 : champs du squelette de bloc (`arc_index.py plan-skeleton`), tous facultatifs.
            "week_type": _enum(WEEK_TYPE),
            "quality_sessions": "int+",
            "long_run_target_s": "num+",
            "strength_emphasis": "str",
            # #69, plan multi-semaines : liste de `week_entry` (même forme qu'une
            # semaine unique ci-dessus), une entrée par semaine. Mutuellement
            # exclusif avec les champs de semaine unique au premier niveau — un
            # fichier choisit un seul format, voir SKILL.md.
            "weeks": "[week_entry]",
        },
    },
    "nutrition": {
        "required": {"date": "date"},
        "optional": {
            "intake_kcal": "num+",
            "carbs_g": "num+",
            "protein_g": "num+",
            "fat_g": "num+",
            "hydration_ml": "num+",
            "burned_kcal": "num+",
            "weight_kg": "num+",
            "target_weight_kg": "num+",
            # #167 : source de vérité de l'apport du jour (une seule par jour, jamais deux) et
            # trace de ce qui a été poussé vers Garmin — voir SUBSCHEMA["garmin_push"].
            "intake_source": _enum(INTAKE_SOURCE),
            "garmin_pushed": "[garmin_push]",
        },
    },
    "report": {
        "required": {"date": "date", "report_type": _enum(REPORT_TYPE), "title": "str"},
        "optional": {"period_start": "date", "period_end": "date", "location": "str"},
    },
    "course_eval": {
        "required": {"date": "date", "name": "str"},
        "optional": {
            "distance_m": "num+",
            "elevation_gain_m": "num+",
            "elevation_loss_m": "num+",
            "is_loop": "bool",
            "target_distance_m": "num+",
            "target_elevation_m": "num+",
            "verdict": _enum(COURSE_VERDICT),
            "km_profile": "list",
            "climbs": "list",
        },
    },
    "race_plan": {
        "required": {"date": "date", "race_name": "str", "race_date": "date"},
        "optional": {
            "distance_m": "num+",
            "elevation_gain_m": "num+",
            "start_time": "datetime",
            # Fuseau IANA de la course (#184, ex. "Europe/Paris") : entrée `--tz` de la pénalité
            # de nuit, persistée pour qu'un recalcul ne redemande pas le fuseau.
            "timezone": "str",
            # Chaleur du plan (`arc_race_pacing`, #38) et coefficients personnels réellement
            # appliqués (`[pacing.personal]`, #188) : lus par `arc_pacing_calibration` au débrief
            # pour que ses estimations restent absolues. Optionnels (plans anciens : absents).
            "heat_factor": "num+",
            "heat_notes": "list",
            "pacing_personal": "obj",
            "target_time_s": "num+",
            "scenarios": "obj",
            "aid_stations": "[aid_station]",
            "water_points": "[water_point]",
            "gear": "list",
            # Roadbook imprimable (#187) : `notes` (consignes de course), `emergency` (urgence :
            # numéro de l'organisation, abandon, points de repli) et `nutrition_plan` (chemin du
            # fichier `nutrition/…` du plan de ravitaillement) — imprimés tels quels, absents =
            # dits absents par le roadbook, jamais inventés.
            "notes": "list",
            "emergency": "list",
            "nutrition_plan": "workspace_path",
            # `segments` (#59, allures par segment depuis le modèle personnel) : socle
            # de #61 (débrief post-course, comparaison plan vs réalisé PAR SEGMENT) —
            # voir `scripts/arc_race_pacing.py::segment_course`/`predict_segments` pour
            # la méthode (segmentation par distance cible + fusion de pente similaire,
            # provenance personnelle/générique/mixte par segment). Optionnel : un plan
            # de course écrit sans GPX (URL seule, étape 1 cas B) n'a pas de segments.
            "segments": "[race_segment]",
        },
    },
    # Inspection photo d'une paire de chaussures (#135, épopée #131) — fichier
    # `gear/AAAA-MM-JJ_<gear_id>_inspection.md`. Clés en anglais, SI (`distance_m`).
    # `distance_m` = kilométrage de la paire AU MOMENT de l'inspection (lu dans
    # `arc_index.py gear`), jamais deviné ; `previous` chaîne vers l'inspection précédente de
    # la MÊME paire (le signal le plus fiable est la comparaison, pas le verdict isolé).
    # `lug_depth_mm` n'existe que si `scale_reference` est vrai (pièce/règle dans le cadre) :
    # règle transverse de `validate()`. Le texte libre (justification visuelle, indices de
    # foulée, comparaison) reste SOUS le bloc.
    "gear_inspection": {
        "required": {
            "date": "date",
            "gear_id": "gear_id",
            "condition": _enum(GEAR_CONDITION),
        },
        "optional": {
            "distance_m": "num+",
            "wear_zones": "[wear_zone]",
            "asymmetry": "{gear_asymmetry}",
            "gait_hints": "enums:" + "|".join(GEAR_GAIT_HINT),
            "photos": "photo_paths",
            "previous": "inspection_path",
            "scale_reference": "bool",
            "lug_depth_mm": "num+",
        },
    },
    "decision": {
        "required": {
            "date": "date",
            # `datetime_tz`, pas le `datetime` générique des autres kinds (#100,
            # revue de code) : un `created_at` NAÏF ne peut pas être comparé entre
            # décisions écrites depuis des fuseaux différents (le tri du journal,
            # `arc_index.decisions_query`, compare des instants absolus — voir
            # `created_at_utc` plus bas). Un fuseau explicite (`Z` ou `+HH:MM`) est
            # donc obligatoire ; une date-heure naïve est REJETÉE, pas devinée.
            "created_at": "datetime_tz",
            "trigger": _enum(DECISION_TRIGGER),
            "summary": "str",
            "outcome": _enum(DECISION_OUTCOME),
        },
        "optional": {
            "inputs": "obj",
            "rule_ids": "rule_ids",
            "sources": "source_paths",
            "before": "{session_change}",
            "after": "{session_change}",
            "session_ref": "{session_ref}",
            "garmin_workout_id": "int+",
            # `decision.supersedes` (#100, revue de code) : chemin de la décision
            # REMPLACÉE par celle-ci — voir SKILL.md pour le protocole (écrire la
            # nouvelle décision avec `supersedes`, puis remettre `outcome` de
            # l'ancienne à `superseded`). Même validation de chemin que `sources`.
            "supersedes": "workspace_path",
        },
    },
}

# Sous-schémas des listes d'objets (non utilisables comme `kind` de fichier).
SUBSCHEMA = {
    # `health.pain` (#57, drapeau composite de risque de blessure) : douleur
    # STRUCTURÉE déclarée par l'athlète le jour du fichier (`health.date` fait
    # foi comme date de l'entrée — pas de `date` propre ici, une entrée de
    # douleur n'a de sens que rattachée au bilan du jour où elle est écrite).
    # Champ VOLONTAIREMENT minimal : `location` (texte libre, ex. « genou
    # droit ») et `score` (0-10, même échelle que `rpe` — sévérité perçue, pas
    # une mesure clinique). Une liste (pas un objet unique) : plusieurs
    # douleurs peuvent coexister le même jour (ex. genou ET tendon). Lu par
    # `scripts/arc_guardrails.py::build_injury_risk_context` — le texte libre
    # de la prose sous le bloc reste la SEULE description narrative (protocole,
    # évolution) ; ce champ n'existait pas avant #57, jamais de dette de
    # backfill (mêmes garanties que `decision`, voir SKILL.md).
    "pain": {
        "required": {"location": "str", "score": "pain_score"},
        "optional": {},
    },
    # `nutrition.garmin_pushed` / `activity.garmin_pushed` (#167) : une entrée par écriture
    # confirmée par l'athlète vers Garmin Connect. `key` (empreinte déterministe de
    # scripts/arc_nutrition_sync.py) rend une relance idempotente : une clé déjà présente
    # n'est jamais re-poussée. `log_id` n'est posé que s'il a été relu sans ambiguïté.
    "garmin_push": {
        "required": {"key": "str", "kind": _enum(GARMIN_PUSH_KIND)},
        "optional": {
            "name": "str",
            "qty": "num+",
            "ml": "num+",
            "food_id": "str",
            "serving_id": "str",
            "log_id": "str",
            "at": "datetime",
        },
    },
    # `week.weeks[]` (#69, plan multi-semaines) : exactement la forme d'une semaine
    # unique historique (`SCHEMA["week"]` avant #69) — `week_start`/`location`/
    # `sessions` obligatoires, le reste facultatif. Jamais utilisable comme `kind`
    # de fichier à part entière (comme tout `SUBSCHEMA`) : une entrée de `weeks[]`
    # n'a de sens que rattachée au fichier qui la porte.
    "week_entry": {
        "required": {
            "week_start": "date",
            "location": "str",
            "sessions": "[session]",
        },
        "optional": {
            "phase": "str",
            "target_duration_s": "num+",
            "target_distance_m": "num+",
            "target_elevation_m": "num+",
            # #190 : champs du squelette de bloc (`arc_index.py plan-skeleton`), tous facultatifs.
            "week_type": _enum(WEEK_TYPE),
            "quality_sessions": "int+",
            "long_run_target_s": "num+",
            "strength_emphasis": "str",
        },
    },
    "session": {
        "required": {"date": "date", "sport": _enum(SPORTS), "title": "str"},
        "optional": {
            "planned_duration_s": "num+",
            "planned_distance_m": "num+",
            "planned_elevation_m": "num+",
            "intensity": _enum(INTENSITY),
            "outdoor": "bool",
            "garmin_workout_id": "int+",
            "status": _enum(SESSION_STATUS),
            "weather_category": _enum(WEATHER_CATEGORY),
            "best_slot": _enum(SLOT),
            "heat_adjustment": "{heat_adjustment}",
            # #190 : créneau posé par `plan-skeleton`, à habiller par le coach (qui retire le drapeau).
            "placeholder": "bool",
        },
    },
    # `session.heat_adjustment` (#171) : trace de l'ajustement des cibles à la chaleur prévue,
    # produite par `arc_workout_targets.py targets --heat` (champ `trace`). `factor` = facteur
    # sur l'ALLURE (>= 1, FC cible inchangée) ; `reason` = motif cité à l'athlète.
    "heat_adjustment": {
        "required": {"factor": "num+"},
        "optional": {
            "temp_c": "num",
            "temp_basis": _enum(HEAT_TEMP_BASIS),
            "action": _enum(HEAT_ACTION),
            "category": _enum(WEATHER_CATEGORY),
            "acclimated": "bool",
            "slot": _enum(SLOT),
            "dew_point_c": "num",
            "reason": "str",
        },
    },
    # `gear_inspection.wear_zones[]` (#135) : une zone d'usure constatée sur UNE semelle.
    "wear_zone": {
        "required": {"side": _enum(GEAR_SIDE), "zone": _enum(GEAR_WEAR_ZONE)},
        "optional": {"severity": _enum(GEAR_WEAR_SEVERITY)},
    },
    # `gear_inspection.asymmetry` (#135) : `side` = le côté le PLUS usé (absent si `none`).
    "gear_asymmetry": {
        "required": {"level": _enum(GEAR_ASYMMETRY_LEVEL)},
        "optional": {"side": _enum(GEAR_SIDE)},
    },
    "aid_station": {
        "required": {"km": "num+", "name": "str"},
        # `cutoff_day` (#59) : jour de la barrière (1 = jour du départ, 2 = lendemain…),
        # utile UNIQUEMENT avec un `cutoff` au format `HH:MM` — sans lui, une heure de
        # barrière antérieure à l'heure de départ est supposée le lendemain (repli
        # historique). `cutoff` accepte aussi `+HH:MM` (élapsé depuis le départ, heures
        # au-delà de 24 admises) et une date-heure ISO 8601 complète — voir
        # `scripts/arc_race_pacing.py::ASSUMPTIONS["cutoffs"]` pour le détail des trois
        # formats (barrière du surlendemain d'un ultra, #59).
        # `stop_s` (#61, épopée #23) : temps d'arrêt PRÉVU à ce ravito, secondes —
        # repris tel quel par `scripts/arc_race_pacing.py`/`scripts/arc_race_debrief.py`
        # (`aid_station.get("stop_s", DEFAULT_AID_STATION_STOP_S)`, 90 s par défaut) au
        # lieu du défaut générique dès qu'il est renseigné. Persisté par
        # `course-strategist` seulement quand un temps d'arrêt différent du défaut est
        # réellement attendu (ravito avec repas chaud, drop bag…) — jamais une valeur
        # inventée pour un ravito simple.
        # `take` (#187) : ce que l'athlète PREND à ce ravito d'après le plan nutrition
        # (liste de textes courts, ex. « 2 gels », « 500 ml »), imprimé tel quel par le
        # roadbook — distinct de `services` (ce que le ravito SERT). Jamais déduit.
        "optional": {"services": "list", "cutoff": "str", "cutoff_day": "int+", "stop_s": "num+",
                     "take": "list"},
    },
    "water_point": {
        "required": {"km": "num+", "source": _enum(WATER_SOURCE)},
        "optional": {"name": "str"},
    },
    # `race_plan.segments[]` (#59) : un segment de course, sa pente moyenne, son
    # temps prédit par scénario et sa provenance — voir `arc_race_pacing.py` pour
    # la méthode complète. `id` est stable d'un appel à l'autre pour un même GPX
    # et un même découpage (`s01`, `s02`…) : #61 (débrief post-course) doit pouvoir
    # aligner un segment mesuré avec le même segment du plan sans recalculer sa
    # propre segmentation. `predicted_time_s`/`pace_s_km` portent les TROIS
    # scénarios, avec les MÊMES clés que `race_plan.scenarios`
    # (`ambitious`/`realistic`/`safe`) — jamais un second vocabulaire de scénario
    # pour la même notion.
    "race_segment": {
        "required": {"id": "str", "km_start": "num+", "km_end": "num+"},
        "optional": {
            "distance_m": "num+",
            "grade_mean_pct": "num",
            "elevation_gain_m": "num+",
            "elevation_loss_m": "num+",
            "source": _enum(SEGMENT_SOURCE),
            "reason_code": _enum(RACE_SEGMENT_REASON_CODE),
            "predicted_time_s": "obj",
            "pace_s_km": "obj",
            # Pénalité de nuit (#184, `arc_race_pacing.apply_night_penalty`) : fraction du temps
            # de la section courue de nuit et multiplicateur de temps, par scénario (mêmes clés
            # que `predicted_time_s`). Absents si le plan n'a pas de nuit.
            "night_fraction": "obj",
            "night_factor": "obj",
            # Technicité du terrain (#186, `arc_technicity`) : `{coef, effective_factor, source, tags,
            # coverage_pct, osm_coef?}`. Absent si `--technicity` n'a pas été demandé.
            "technicity": "obj",
            # Pénalité d'altitude (#185, `arc_race_pacing.apply_altitude_penalty`) : altitude
            # moyenne (m) de la section et multiplicateur de temps (identique aux trois
            # scénarios). Absents si aucune section ne dépasse le seuil.
            "altitude_m": "num",
            "altitude_factor": "num+",
            "notes": "list",
        },
    },
    # `decision.before`/`decision.after` (#54) : instantané PARTIEL d'une séance —
    # tous les champs sont facultatifs (une annulation ne change que `status`, un
    # simple allègement ne change que `intensity`/`planned_duration_s`…). Jamais
    # un objet `session` complet du fichier semaine : seuls les champs qui
    # CHANGENT ont à être recopiés ici, le reste se lit dans `session_ref`.
    "session_change": {
        "required": {},
        "optional": {
            "date": "date",
            "sport": _enum(SPORTS),
            "title": "str",
            "intensity": _enum(INTENSITY),
            "planned_duration_s": "num+",
            "status": _enum(SESSION_STATUS),
        },
    },
    # `decision.session_ref` (#54) : pointeur vers la séance du fichier semaine
    # que la décision modifie — le fichier `week` reste la source de vérité de
    # l'état COURANT de la séance, cette référence ne fait que la retrouver.
    "session_ref": {
        "required": {"week": "workspace_path", "date": "date"},
        "optional": {},
    },
}

KINDS = tuple(SCHEMA)

# Dossier attendu pour chaque type (sert à la découverte et au lint).
KIND_FOLDERS = {
    "activity": "activities",
    "health": "medical",
    "weather": "medical",
    "week": "planning",
    "nutrition": "nutrition",
    "report": "rapports",
    "course_eval": "planning",
    "race_plan": "planning",
    "decision": "planning",
    "gear_inspection": "gear",
}

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

BLOCK_RE = re.compile(r"^```arc[ \t]*\n(.*?)\n```[ \t]*$", re.M | re.S)


class ContractError(ValueError):
    """Bloc absent, illisible ou invalide."""


def find_blocks(text: str) -> list:
    return BLOCK_RE.findall(text)


def extract_block(text: str):
    """Rend le dict du bloc ```arc, ou None si le fichier n'en a pas.

    Lève ContractError si le bloc est en double ou n'est pas du JSON objet.
    """
    blocks = find_blocks(text)
    if not blocks:
        return None
    if len(blocks) > 1:
        raise ContractError(f"{len(blocks)} blocs ```arc trouvés : un seul par fichier.")
    try:
        data = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"bloc ```arc : JSON invalide (ligne {exc.lineno}, colonne {exc.colno}) : {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ContractError(f"bloc ```arc : objet JSON attendu, {type(data).__name__} trouvé.")
    return data


def body_after_block(text: str) -> str:
    """Le texte libre du fichier, bloc ```arc retiré (pour l'affichage)."""
    return re.sub(r"\n{3,}", "\n\n", BLOCK_RE.sub("", text, count=1)).strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_value(spec: str, value, where: str, errors: list, warnings: list) -> None:
    """Vérifie une valeur non nulle contre son type."""
    def fail(expected: str) -> None:
        errors.append(f"{where} : {expected} attendu, {json.dumps(value, ensure_ascii=False)} trouvé")

    if spec.startswith("enum:"):
        allowed = spec[5:].split("|")
        if value not in allowed:
            fail("une valeur parmi " + ", ".join(allowed))
        return
    if spec.startswith("enums:"):
        # Liste de valeurs d'une énumération (`gear_inspection.gait_hints`, #135).
        allowed = spec[6:].split("|")
        if not isinstance(value, list):
            fail("une liste de valeurs parmi " + ", ".join(allowed))
            return
        for i, item in enumerate(value):
            if item not in allowed:
                errors.append(f"{where}[{i}] : une valeur parmi {', '.join(allowed)} attendue, "
                              f"{json.dumps(item, ensure_ascii=False)} trouvé")
        return
    if spec.startswith("[") and spec.endswith("]"):
        sub = SUBSCHEMA[spec[1:-1]]
        if not isinstance(value, list):
            fail("une liste")
            return
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{where}[{i}] : objet attendu")
                continue
            _check_object(sub, item, f"{where}[{i}]", errors, warnings)
        return
    if spec.startswith("{") and spec.endswith("}"):
        # Sous-objet UNIQUE (par opposition à `[kind]` ci-dessus, une liste) —
        # `decision.before`/`after`/`session_ref` (#54).
        sub = SUBSCHEMA[spec[1:-1]]
        if not isinstance(value, dict):
            fail("un objet")
            return
        _check_object(sub, value, where, errors, warnings)
        return
    if spec in ("int", "int+"):
        if not isinstance(value, int) or isinstance(value, bool):
            fail("un entier")
        elif spec == "int+" and value < 0:
            fail("un entier positif")
        return
    if spec in ("num", "num+"):
        if not _is_number(value):
            fail("un nombre (SI, sans unité)")
        elif spec == "num+" and value < 0:
            fail("un nombre positif")
        return
    if spec == "decoupling_pct":
        if not _is_number(value):
            fail("un nombre (%, signe libre)")
            return
        lo, hi = DECOUPLING_PCT_PLAUSIBLE
        if not lo <= value <= hi:
            warnings.append(f"{where} : {value} hors de la plage plausible ({lo:g} à {hi:g} %) — à vérifier")
        return
    if spec == "stance_balance_pct":
        # Même fenêtre plausible que `arc_gait.PLAUSIBLE` : hors 30-70 %, avertissement (à vérifier), pas un rejet.
        if not _is_number(value) or not 0 < value < 100:
            fail("un pourcentage strictement entre 0 et 100")
        elif not 30 <= value <= 70:
            warnings.append(f"{where} : {value} hors de la plage plausible (30 à 70 %) — à vérifier ; "
                            "ignoré par `gait-summary`")
        return
    if spec == "gait_pct":
        # Pourcentage de dynamique de course (#151) : balance du temps de contact, ratio vertical.
        if not _is_number(value) or not 0 < value < 100:
            fail("un pourcentage strictement entre 0 et 100")
        return
    if spec == "cycle_day":
        lo, hi = CYCLE_DAY_PLAUSIBLE
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            fail(f"un jour de cycle entier de {lo} à {hi}")
        return
    if spec == "hr":
        if not _is_number(value) or not 20 <= value <= 250:
            fail("une fréquence cardiaque en bpm (20-250)")
        return
    if spec == "score":
        if not _is_number(value) or not 0 <= value <= 100:
            fail("un score de 0 à 100")
        return
    if spec == "rpe":
        if not _is_number(value) or not 0 <= value <= 10:
            fail("un RPE de 0 à 10")
        return
    if spec == "pain_score":
        # `health.pain[].score` (#57) : même échelle 0-10 que `rpe`, mais un type
        # DÉDIÉ — sévérité de douleur perçue, jamais un effort — pour ne jamais
        # confondre les deux dans un message d'erreur.
        if not _is_number(value) or not 0 <= value <= 10:
            fail("un score de douleur de 0 à 10")
        return
    if spec == "gear_id":
        if not isinstance(value, str) or not value.strip():
            fail("un identifiant de matériel (chaîne non vide)")
        elif len(value) > GEAR_ID_MAX_LEN or not GEAR_ID_RE.match(value):
            fail(f"un identifiant de matériel au format slug (minuscules, chiffres, tirets, "
                 f"{GEAR_ID_MAX_LEN} caractères max)")
        return
    if spec == "gear_id_list":
        if not isinstance(value, list):
            fail("une liste d'identifiants de matériel (slugs)")
            return
        if len(value) > GEAR_IDS_MAX:
            fail(f"{GEAR_IDS_MAX} identifiants de matériel au plus")
            return
        seen = set()
        for i, gid in enumerate(value):
            if not isinstance(gid, str) or len(gid) > GEAR_ID_MAX_LEN or not GEAR_ID_RE.match(gid):
                errors.append(f"{where}[{i}] : un identifiant de matériel au format slug (minuscules, chiffres, "
                              f"tirets, {GEAR_ID_MAX_LEN} caractères max) attendu, "
                              f"{json.dumps(gid, ensure_ascii=False)} trouvé")
            elif gid in seen:
                errors.append(f"{where}[{i}] : identifiant « {gid} » en double")
            else:
                seen.add(gid)
        return
    if spec == "carbs_g":
        if not _is_number(value) or not 0 <= value <= CARBS_G_PLAUSIBLE_MAX:
            fail(f"une quantité de glucides en g (0-{CARBS_G_PLAUSIBLE_MAX:g})")
        return
    if spec == "fluid_ml":
        if not _is_number(value) or not 0 <= value <= FLUID_INTAKE_ML_PLAUSIBLE_MAX:
            fail(f"un volume ingéré en ml (0-{FLUID_INTAKE_ML_PLAUSIBLE_MAX:g})")
        return
    if spec == "body_weight_kg":
        lo, hi = BODY_WEIGHT_KG_PLAUSIBLE
        if not _is_number(value) or not lo <= value <= hi:
            fail(f"un poids en kg ({lo:g}-{hi:g})")
        return
    if spec == "rule_ids":
        # `decision.rule_ids` (#54) : identifiants de `arc_guardrails.RULE_IDS`,
        # au format `rN_nom_de_regle`. Validé par PATTERN, pas contre la liste
        # vivante des règles connues (voir la note au-dessus de `RULE_ID_RE`) —
        # une règle future (`r8_...`) ou retirée n'invalide donc pas un bloc
        # `decision` déjà écrit.
        if not isinstance(value, list):
            fail("une liste d'identifiants de règle (arc_guardrails.RULE_IDS)")
            return
        for i, item in enumerate(value):
            if not isinstance(item, str) or not RULE_ID_RE.match(item):
                errors.append(
                    f"{where}[{i}] : identifiant de règle attendu au format rN_nom_de_regle, "
                    f"{json.dumps(item, ensure_ascii=False)} trouvé"
                )
        return
    if spec == "photo_paths":
        # `gear_inspection.photos` (#135) : chemins de photos DANS `gear/photos/`, images
        # raster seulement (jamais SVG : le tableau de bord les sert — voir
        # `arc_serve.gear_photo_file`). Jamais dans le dépôt public : `gear/` est gitignoré.
        if not isinstance(value, list):
            fail("une liste de chemins de photos sous gear/photos/")
            return
        if len(value) > GEAR_PHOTOS_MAX:
            warnings.append(f"{where} : {len(value)} photos, plus de {GEAR_PHOTOS_MAX} — vérifier les doublons")
        for i, item in enumerate(value):
            reason = _invalid_workspace_path_reason(item)
            if reason is None and not (item.startswith(GEAR_PHOTO_DIR)
                                       and item.lower().endswith(GEAR_PHOTO_EXTENSIONS)):
                reason = (f"photo attendue sous {GEAR_PHOTO_DIR} avec une extension parmi "
                          f"{', '.join(GEAR_PHOTO_EXTENSIONS)}")
            if reason:
                errors.append(f"{where}[{i}] : {reason} ({json.dumps(item, ensure_ascii=False)})")
        return
    if spec == "inspection_path":
        # `gear_inspection.previous` (#135) : chemin d'une AUTRE inspection.
        reason = _invalid_workspace_path_reason(value)
        if reason is None and not (value.startswith(GEAR_INSPECTION_FOLDER + "/")
                                   and value.endswith("_inspection.md")):
            reason = "inspection attendue sous gear/ (gear/AAAA-MM-JJ_<gear_id>_inspection.md)"
        if reason:
            errors.append(f"{where} : {reason} ({json.dumps(value, ensure_ascii=False)})")
        return
    if spec == "source_paths":
        # `decision.sources` (#54) : liste de chemins relatifs au workspace —
        # voir `_invalid_workspace_path_reason` pour ce qui est refusé.
        if not isinstance(value, list):
            fail("une liste de chemins relatifs au workspace")
            return
        for i, item in enumerate(value):
            reason = _invalid_workspace_path_reason(item)
            if reason:
                errors.append(f"{where}[{i}] : {reason} ({json.dumps(item, ensure_ascii=False)})")
        return
    if spec == "workspace_path":
        # `decision.supersedes`, `decision.session_ref.week` (#54/#100) : UN SEUL
        # chemin relatif au workspace — même validation que chaque élément de
        # `source_paths` ci-dessus, voir `_invalid_workspace_path_reason`.
        reason = _invalid_workspace_path_reason(value)
        if reason:
            errors.append(f"{where} : {reason} ({json.dumps(value, ensure_ascii=False)})")
        return
    if spec == "str":
        if not isinstance(value, str) or not value.strip():
            fail("une chaîne non vide")
        return
    if spec == "strava_id":
        # `strava_activity_id` (#164) : « s » + chiffres — un identifiant sans préfixe se
        # confondrait avec un `garmin_activity_id` et ne se rattacherait à aucun échantillon.
        if not isinstance(value, str) or not re.fullmatch(r"s\d+", value):
            fail("« s » suivi des chiffres de l'identifiant Strava (ex. \"s12345678901\")")
        return
    if spec == "bool":
        if not isinstance(value, bool):
            fail("true ou false")
        return
    if spec == "obj":
        if not isinstance(value, dict):
            fail("un objet")
        return
    if spec == "list":
        if not isinstance(value, list):
            fail("une liste")
        return
    if spec == "date":
        if not isinstance(value, str) or not DATE_RE.match(value):
            fail("une date AAAA-MM-JJ")
            return
        try:
            date.fromisoformat(value)
        except ValueError:
            fail("une date existante")
        return
    if spec == "datetime":
        if not isinstance(value, str):
            fail("une date-heure ISO 8601")
            return
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            fail("une date-heure ISO 8601")
        return
    if spec == "datetime_tz":
        # `decision.created_at` (#100, revue de code) : fuseau OBLIGATOIRE, une
        # date-heure naïve est REJETÉE (pas de fuseau deviné) — voir la note dans
        # `SCHEMA["decision"]`.
        if not isinstance(value, str):
            fail("une date-heure ISO 8601 avec fuseau (Z ou +HH:MM)")
            return
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            fail("une date-heure ISO 8601 avec fuseau (Z ou +HH:MM)")
            return
        if parsed.tzinfo is None:
            fail("une date-heure avec fuseau explicite (Z ou +HH:MM) — une date-heure naïve "
                 "ne peut pas être comparée entre décisions écrites depuis des fuseaux différents")
        return
    raise AssertionError(f"type de schéma inconnu : {spec}")   # erreur de ce module


# Chemin relatif au workspace (#54, durci #100 revue de code) : ni URL
# (`scheme://…`, `mailto:…`), ni chemin Windows (`C:\…`), ni antislash (jamais
# un séparateur valide dans ce contrat, y compris en préfixe d'un chemin
# Windows relatif), ni `~` (répertoire personnel), ni segment vide/`.`/`..`
# (racine absolue déguisée ou remontée hors du workspace). Un simple test
# `"://" in item` ou `item.startswith("/")` (première version, #54) laissait
# passer `C:\Users\x.md`, `~/secret.md`, `mailto:a@b`, `resources//x.md` — tous
# refusés ici. Partagé par `source_paths` (liste) et `workspace_path` (un seul
# chemin : `supersedes`, `session_ref.week`).
def _invalid_workspace_path_reason(value) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return "chemin non vide attendu"
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return "caractère de contrôle interdit (NUL, retour à la ligne, tabulation…)"
    if "\\" in value:
        return "antislash interdit (jamais un séparateur valide dans ce contrat)"
    if ":" in value:
        return "« : » interdit (pas d'URL comme mailto:/file:, pas de lettre de lecteur Windows)"
    if value.startswith("~"):
        return "chemin relatif au workspace attendu (pas de `~`)"
    if value.startswith("/"):
        return "chemin relatif au workspace attendu (pas de chemin absolu)"
    if any(segment in ("", ".", "..") for segment in value.split("/")):
        return "aucun segment vide, `.` ou `..` autorisé (pas de remontée hors du workspace)"
    return None


def _check_object(schema: dict, data: dict, where: str, errors: list, warnings: list) -> None:
    required, optional = schema["required"], schema["optional"]
    for key, spec in required.items():
        if data.get(key) is None:
            errors.append(f"{where}.{key} : clé obligatoire manquante")
        else:
            _check_value(spec, data[key], f"{where}.{key}", errors, warnings)
    for key, value in data.items():
        if key in required or key in ("arc", "kind"):
            continue
        if key not in optional:
            warnings.append(f"{where}.{key} : clé inconnue du contrat (faute de frappe ?)")
            continue
        if value is not None:
            _check_value(optional[key], value, f"{where}.{key}", errors, warnings)


def _check_splits(data: dict, errors: list) -> None:
    cols, rows = data.get("splits_cols"), data.get("splits")
    if rows is None and cols is None:
        return
    if not isinstance(cols, list) or not isinstance(rows, list):
        errors.append("activity.splits : `splits` et `splits_cols` vont ensemble")
        return
    unknown = [c for c in cols if c not in SPLIT_COLUMNS]
    if unknown:
        errors.append(f"activity.splits_cols : colonnes inconnues {unknown}")
    for needed in SPLIT_REQUIRED:
        if needed not in cols:
            errors.append(f"activity.splits_cols : colonne « {needed} » obligatoire")
    if len(set(cols)) != len(cols):
        errors.append("activity.splits_cols : colonne en double")
    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(cols):
            errors.append(f"activity.splits[{i}] : {len(cols)} valeurs attendues (une par colonne)")
            continue
        for col, value in zip(cols, row):
            if value is not None and col in SPLIT_COLUMNS:
                _check_value(SPLIT_COLUMNS[col], value, f"activity.splits[{i}].{col}", errors, [])


def _check_time_in_zone(data: dict, errors: list, warnings: list) -> None:
    """`activity.time_in_zone_s` (#51, revue de code) : clés `z1`…`z5`
    UNIQUEMENT (`TIME_IN_ZONE_KEYS` — pas les buckets de polarisation `low`/
    `moderate`/`high`, un champ différent), valeurs numériques ≥ 0 et ≤
    `duration_s` de la même activité — une seconde en zone ne peut pas
    dépasser la durée totale de la séance qui la contient. `_check_value`
    (spec `"obj"`) a déjà signalé un `time_in_zone_s` qui n'est pas un objet ;
    cette fonction ne s'exécute que sur un objet effectivement présent."""
    value = data.get("time_in_zone_s")
    if not isinstance(value, dict):
        return
    duration = data.get("duration_s")
    for key, seconds in value.items():
        where = f"activity.time_in_zone_s.{key}"
        if key not in TIME_IN_ZONE_KEYS:
            warnings.append(f"{where} : clé inconnue, attendu une valeur parmi "
                             f"{', '.join(TIME_IN_ZONE_KEYS)}")
            continue
        if not _is_number(seconds) or seconds < 0:
            errors.append(f"{where} : un nombre de secondes positif attendu, "
                           f"{json.dumps(seconds, ensure_ascii=False)} trouvé")
            continue
        if _is_number(duration) and seconds > duration:
            errors.append(f"{where} : {seconds} s dépasse la durée totale de la séance "
                           f"({duration} s)")


# #69 : clés du format « semaine unique » (premier niveau) — présentes en même
# temps que `weeks` (format multi-semaines), c'est un mélange refusé (un fichier
# choisit un seul format, voir SKILL.md).
WEEK_SINGLE_KEYS = (
    "week_start", "location", "sessions", "phase",
    "target_duration_s", "target_distance_m", "target_elevation_m",
)


def _validate_week(data: dict, errors: list, warnings: list) -> None:
    """Valide un bloc `kind: "week"` (#69) : soit une semaine unique au premier
    niveau (format historique, INCHANGÉ — mêmes clés obligatoires et mêmes
    messages qu'avant #69, pour que les fichiers existants restent rétro-
    compatibles à l'octet près), soit plusieurs via `weeks` (liste de
    `week_entry`, voir SUBSCHEMA). Chaque semaine du tableau `weeks` est validée
    INDIVIDUELLEMENT (contrat `week_entry`, `week_start` sur un lundi, ses
    séances datées à l'intérieur de cette semaine), et aucune paire ne peut
    partager le même `week_start` (doublon) dans le même fichier — le
    chevauchement au sens large (deux lundis distincts dont les plages de 7
    jours se recouvriraient) ne peut pas se produire tant que `week_start` est
    lui-même sur un lundi (les blocs de 7 jours alignés sur le lundi sont soit
    identiques, soit disjoints) : le contrôle de lundi ci-dessous couvre donc
    aussi le chevauchement, le doublon de `week_start` restant le seul autre cas
    à vérifier explicitement.

    `"weeks" in data` (revue de code #69, nit) — pas `data.get("weeks") is not
    None` — pour distinguer la clé ABSENTE (format historique légitime) de la
    clé PRÉSENTE mais `null` ou mal typée (`{"weeks": null}`, une chaîne...) :
    cette dernière doit rendre une erreur nommant `weeks` explicitement, jamais
    tomber dans le repli « semaine unique » où elle ressortirait comme une
    simple clé inconnue (`_check_object` ne connaît `weeks` que dans
    `SCHEMA["week"]`, pas dans `SUBSCHEMA["week_entry"]` utilisé pour ce
    repli)."""
    has_weeks_key = "weeks" in data
    weeks = data.get("weeks")
    has_single = any(data.get(k) is not None for k in WEEK_SINGLE_KEYS)
    if has_weeks_key:
        if has_single:
            errors.append(
                "week : ne mélangez pas `weeks` (plan multi-semaines) et les champs de "
                "semaine unique (week_start/location/sessions/…) au premier niveau du "
                "même fichier — choisissez un seul format (voir SKILL.md)."
            )
        if not isinstance(weeks, list) or not weeks:
            errors.append("week.weeks : liste non vide de semaines attendue")
            return
        seen_week_starts: dict = {}
        for i, entry in enumerate(weeks):
            where = f"week.weeks[{i}]"
            if not isinstance(entry, dict):
                errors.append(f"{where} : objet attendu")
                continue
            _check_object(SUBSCHEMA["week_entry"], entry, where, errors, warnings)
            _check_week_start_and_sessions(entry, where, i, seen_week_starts, errors)
        return
    # Format historique : une seule semaine au premier niveau — EXACTEMENT le
    # schéma `week_entry` ci-dessus (`week_start`/`location`/`sessions`
    # obligatoires), donc les mêmes erreurs qu'avant #69 pour un fichier qui
    # n'utilise pas `weeks`.
    _check_object(SUBSCHEMA["week_entry"], data, "week", errors, warnings)


def _check_week_start_and_sessions(entry: dict, where: str, index: int,
                                    seen_week_starts: dict, errors: list) -> None:
    """Lundi obligatoire, doublon de `week_start` refusé, séances de l'entrée
    contenues dans sa propre semaine (lundi à dimanche) — les trois contrôles
    propres au format multi-semaines (#69), en plus du schéma générique déjà
    vérifié par `_check_object` juste avant l'appel."""
    week_start = entry.get("week_start")
    if not isinstance(week_start, str) or not DATE_RE.match(week_start):
        return   # déjà signalé par `_check_object` (clé manquante ou mal typée)
    try:
        monday = date.fromisoformat(week_start)
    except ValueError:
        return   # déjà signalé (date inexistante)
    if monday.weekday() != 0:
        errors.append(
            f"{where}.week_start : {week_start} n'est pas un lundi — le contrat exige "
            "le lundi de la semaine (jour {} trouvé)".format(
                ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")[monday.weekday()]
            )
        )
    if week_start in seen_week_starts:
        errors.append(
            f"{where}.week_start : {week_start} en double dans ce fichier (déjà "
            f"weeks[{seen_week_starts[week_start]}])"
        )
    else:
        seen_week_starts[week_start] = index
    sunday = monday + timedelta(days=6)
    sessions = entry.get("sessions")
    if not isinstance(sessions, list):
        return   # déjà signalé par `_check_object`
    for j, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        session_date = session.get("date")
        if not isinstance(session_date, str) or not DATE_RE.match(session_date):
            continue   # déjà signalé par `_check_object` (session.date)
        try:
            parsed = date.fromisoformat(session_date)
        except ValueError:
            continue
        if not monday <= parsed <= sunday:
            errors.append(
                f"{where}.sessions[{j}].date : {session_date} est hors de la semaine "
                f"{week_start} (lundi) – {sunday.isoformat()} (dimanche)"
            )


def validate(data: dict) -> tuple:
    """Rend (erreurs, avertissements). Aucune erreur = bloc conforme."""
    errors, warnings = [], []
    if data.get("arc") != ARC_VERSION:
        errors.append(f"arc : version {ARC_VERSION} attendue, {data.get('arc')!r} trouvée")
    kind = data.get("kind")
    if kind not in SCHEMA:
        errors.append(f"kind : une valeur parmi {', '.join(KINDS)} attendue, {kind!r} trouvé")
        return errors, warnings
    if kind == "week":
        # #69 : validation dédiée — le format effectivement utilisé (semaine
        # unique vs `weeks[]`) décide ce qui est obligatoire, ce que `_check_object`
        # générique ne peut pas savoir tout seul (`SCHEMA["week"]["required"]`
        # reste celui du format historique, pour le repli legacy de
        # `arc_index.read_file` —
        # voir le commentaire au-dessus de `SCHEMA["week"]`).
        _validate_week(data, errors, warnings)
        return errors, warnings
    _check_object(SCHEMA[kind], data, kind, errors, warnings)
    if kind == "activity":
        _check_splits(data, errors)
        _check_time_in_zone(data, errors, warnings)
    if kind == "health" and data.get("verdict") and not data.get("verdict_reason"):
        errors.append("health.verdict_reason : obligatoire dès qu'un verdict est posé")
    if kind == "health" and isinstance(data.get("pain"), list) and len(data["pain"]) > PAIN_MAX_ENTRIES:
        warnings.append(
            f"health.pain : {len(data['pain'])} entrées, plus de {PAIN_MAX_ENTRIES} — "
            "vérifier qu'il ne s'agit pas d'un doublon plutôt que de zones distinctes"
        )
    if kind == "activity":
        moving, total = data.get("moving_duration_s"), data.get("duration_s")
        if _is_number(moving) and _is_number(total) and moving > total:
            errors.append("activity.moving_duration_s : ne peut dépasser duration_s")
        bmr, calories = data.get("calories_bmr_kcal"), data.get("calories_kcal")
        if _is_number(bmr) and _is_number(calories) and bmr > calories:
            # Le métabolisme de base est une PART de la dépense totale de la séance
            # (dépense énergétique modèle) : il ne peut jamais la dépasser — un `calories_bmr_kcal` >
            # `calories_kcal` trahit presque toujours une confusion de champ côté
            # Garmin (ex. BMR quotidien entier collé sur une activité courte),
            # jamais une valeur physiologiquement plausible à laisser passer.
            errors.append("activity.calories_bmr_kcal : ne peut dépasser calories_kcal")
        source = data.get("gear_source")
        if source in ("garmin", "chat") and not data.get("gear_id"):
            errors.append(f"activity.gear_source : « {source} » exige un gear_id")
        if source == "garmin_unmapped" and data.get("gear_id"):
            errors.append("activity.gear_source : « garmin_unmapped » exclut gear_id (matériel Garmin non associé)")
        pre, post = data.get("weight_pre_kg"), data.get("weight_post_kg")
        if _is_number(pre) and _is_number(post) and post > pre + WEIGHT_POST_TOLERANCE_KG:
            # Pas une erreur : une pesée maison a de l'imprécision (habits, balance), et le
            # contrat ne connaît pas la cause (peut aussi arriver, ex. ravitaillement massif
            # avant une pesée après course). `sweat_rate_l_h` (arc_metrics.py) ignore de
            # toute façon un résultat négatif plutôt que d'être calculé sur ces valeurs.
            warnings.append(
                f"activity.weight_post_kg : supérieur au poids avant effort de plus de "
                f"{WEIGHT_POST_TOLERANCE_KG:g} kg — pesée à vérifier"
            )
    if kind == "decision":
        _check_decision_created_at(data, errors)
    if kind == "gear_inspection":
        _check_gear_inspection(data, errors, warnings)
    return errors, warnings


def _check_gear_inspection(data: dict, errors: list, warnings: list) -> None:
    """Règles transverses de `gear_inspection` (#135)."""
    depth = data.get("lug_depth_mm")
    if depth is not None and not data.get("scale_reference"):
        # Garde-fou du skill : aucune mesure en mm sans référence d'échelle dans la photo.
        errors.append("gear_inspection.lug_depth_mm : interdit sans scale_reference: true "
                      "(aucune mesure en mm sans pièce ou règle dans le cadre)")
    if _is_number(depth) and depth > GEAR_LUG_DEPTH_MM_PLAUSIBLE_MAX:
        warnings.append(f"gear_inspection.lug_depth_mm : {depth:g} mm dépasse "
                        f"{GEAR_LUG_DEPTH_MM_PLAUSIBLE_MAX:g} mm — faute de frappe probable")
    asym = data.get("asymmetry")
    if isinstance(asym, dict):
        level, side = asym.get("level"), asym.get("side")
        if level in ("mild", "marked") and side is None:
            errors.append("gear_inspection.asymmetry.side : obligatoire dès que level vaut mild ou marked "
                          "(le côté le plus usé)")
        if level == "none" and side is not None:
            warnings.append("gear_inspection.asymmetry.side : ignoré quand level vaut none")
    zones = data.get("wear_zones")
    if isinstance(zones, list) and zones:
        sides = {z.get("side") for z in zones if isinstance(z, dict)}
        if sides in ({"left"}, {"right"}):
            warnings.append("gear_inspection.wear_zones : une seule semelle documentée — "
                            "le protocole demande les DEUX (l'asymétrie ne peut pas être jugée)")


# `created_at` (horodatage d'écriture) ne doit pas s'écarter dans le futur, au-delà
# d'une marge raisonnable, de `date` (le jour auquel la décision s'applique) : une
# décision du 20 septembre datée du 25 sent la faute de frappe de date, pas un cas
# légitime (une décision peut en revanche être écrite la VEILLE au soir — bilan du
# lendemain préparé à l'avance — donc `created_at` antérieur à `date` reste normal,
# aucune borne basse).
#
# Comparaison faite dans le FUSEAU PROPRE de `created_at`, tel qu'écrit — PAS
# converti en UTC au préalable (contrairement à `decision_created_at_utc`
# ci-dessous, qui sert au TRI et compare bien des instants absolus). Une
# décision écrite à `2026-09-20T23:50:00+02:00` pour `date: "2026-09-21"` reste
# donc « la veille au soir » (jour local 20) même si son équivalent UTC
# (21h50 UTC, toujours le 20) tombe du même côté ici — mais un fuseau très
# décalé (ex. `-11:00`) pourrait faire basculer le jour local d'un cran par
# rapport à l'UTC. Choix délibéré : cette règle attrape une FAUTE DE FRAPPE
# grossière (des jours d'écart), pas un calcul au fuseau près — le jour tel
# qu'écrit par l'auteur de la décision est le plus significatif pour lui.
DECISION_CREATED_AT_MAX_LEAD_DAYS = 1


def _check_decision_created_at(data: dict, errors: list) -> None:
    day, created_at = data.get("date"), data.get("created_at")
    if not isinstance(day, str) or not isinstance(created_at, str):
        return
    try:
        day_value = date.fromisoformat(day)
        created_day = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    except ValueError:
        return   # déjà signalé par `_check_value` (format de date/date-heure invalide)
    lead = (created_day - day_value).days
    if lead > DECISION_CREATED_AT_MAX_LEAD_DAYS:
        errors.append(
            f"decision.created_at : {created_at} est postérieur de {lead} jour(s) à date "
            f"({day}) — au-delà de {DECISION_CREATED_AT_MAX_LEAD_DAYS} jour, probable faute de frappe"
        )


def decision_created_at_utc(value) -> Optional[str]:
    """`decision.created_at` normalisé en UTC, pour le TRI (#100, revue de code) :
    trier `created_at` comme du texte mélange des décisions écrites depuis des
    fuseaux différents dans le mauvais ordre (`07:00+02:00` textuellement après
    `06:00Z`, alors que 07:00+02:00 = 05:00 UTC est en fait ANTÉRIEUR). Rend
    `None` si `value` n'est pas une date-heure ISO 8601 avec fuseau explicite —
    ne devrait pas arriver pour un bloc déjà validé (`datetime_tz` l'exige),
    mais reste défensif pour un appelant qui indexerait un bloc invalide."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def split_rows(data: dict) -> list:
    """Splits d'une activité sous forme de dicts {colonne: valeur}."""
    cols = data.get("splits_cols") or []
    return [dict(zip(cols, row)) for row in data.get("splits") or [] if isinstance(row, list)]


def documented_keys(kind: str) -> set:
    schema = SCHEMA.get(kind) or SUBSCHEMA[kind]
    return set(schema["required"]) | set(schema["optional"])
