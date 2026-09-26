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
from datetime import date, datetime, timezone
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
WEATHER_CATEGORY = ("green", "yellow", "orange", "red")
SLOT = ("morning", "midday", "evening", "none")
INTENSITY = (
    "rest", "recovery", "endurance", "tempo", "threshold", "vo2max", "race", "strength",
)
SESSION_STATUS = ("planned", "done", "missed", "moved", "cancelled")
REPORT_TYPE = ("weekly", "monthly", "comparison", "race", "adhoc")
COURSE_VERDICT = ("compatible", "partial", "incompatible")
WATER_SOURCE = ("officiel", "osm_drinking_water", "osm_spring", "osm_cafe")

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

# Matériel, sudation, glucides pendant l'effort (#39 — champs consommés par #40
# kilométrage chaussures, #41 KPI glucides/h et taux de sudation).
GEAR_ID_MAX_LEN = 40
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


def _enum(values) -> str:
    return "enum:" + "|".join(values)


SCHEMA = {
    "activity": {
        "required": {"date": "date", "sport": _enum(SPORTS), "duration_s": "num+"},
        "optional": {
            "garmin_activity_id": "int+",
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
            "training_effect_aerobic": "num+",
            "training_effect_anaerobic": "num+",
            "rpe": "rpe",
            "splits_cols": "list",
            "splits": "list",
            "gear_id": "gear_id",
            "carbs_g": "carbs_g",
            "fluid_intake_ml": "fluid_ml",
            "weight_pre_kg": "body_weight_kg",
            "weight_post_kg": "body_weight_kg",
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
            "target_time_s": "num+",
            "scenarios": "obj",
            "aid_stations": "[aid_station]",
            "water_points": "[water_point]",
            "gear": "list",
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
        },
    },
    "aid_station": {
        "required": {"km": "num+", "name": "str"},
        "optional": {"services": "list", "cutoff": "str"},
    },
    "water_point": {
        "required": {"km": "num+", "source": _enum(WATER_SOURCE)},
        "optional": {"name": "str"},
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


def validate(data: dict) -> tuple:
    """Rend (erreurs, avertissements). Aucune erreur = bloc conforme."""
    errors, warnings = [], []
    if data.get("arc") != ARC_VERSION:
        errors.append(f"arc : version {ARC_VERSION} attendue, {data.get('arc')!r} trouvée")
    kind = data.get("kind")
    if kind not in SCHEMA:
        errors.append(f"kind : une valeur parmi {', '.join(KINDS)} attendue, {kind!r} trouvé")
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
    return errors, warnings


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
