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
from datetime import date, datetime

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

# Matériel, sudation, glucides pendant l'effort (#39 — champs consommés par #40
# kilométrage chaussures, #41 KPI glucides/h et taux de sudation).
GEAR_ID_MAX_LEN = 40
# Format slug : minuscules, chiffres, tirets simples, jamais en tête/fin — même
# convention que la plupart des identifiants stables lisibles par un humain
# (ex. "hoka-speedgoat-5-bleue"). `planning/Runner_Profile.md` (#40) écrira la
# section « Matériel » avec ce même identifiant : c'est la clé de jointure
# entre une séance et sa paire de chaussures.
GEAR_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CARBS_G_PLAUSIBLE_MAX = 1000        # ravitaillement pendant l'effort ; au-delà, faute de frappe probable
FLUID_INTAKE_ML_PLAUSIBLE_MAX = 10000
BODY_WEIGHT_KG_PLAUSIBLE = (30.0, 200.0)
# Pesée après effort supérieure à avant : n'arrive normalement pas (perte hydrique),
# mais une petite marge absorbe l'imprécision d'une pesée maison (habits, balance).
# Au-delà, avertissement (pas une erreur) : `sweat_rate_l_h` (arc_metrics.py) ignore
# de toute façon un résultat négatif plutôt que de le rejeter ici en amont.
WEIGHT_POST_TOLERANCE_KG = 1.0

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
}

# Sous-schémas des listes d'objets (non utilisables comme `kind` de fichier).
SUBSCHEMA = {
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
    raise AssertionError(f"type de schéma inconnu : {spec}")   # erreur de ce module


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
    if kind == "health" and data.get("verdict") and not data.get("verdict_reason"):
        errors.append("health.verdict_reason : obligatoire dès qu'un verdict est posé")
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
    return errors, warnings


def split_rows(data: dict) -> list:
    """Splits d'une activité sous forme de dicts {colonne: valeur}."""
    cols = data.get("splits_cols") or []
    return [dict(zip(cols, row)) for row in data.get("splits") or [] if isinstance(row, list)]


def documented_keys(kind: str) -> set:
    schema = SCHEMA.get(kind) or SUBSCHEMA[kind]
    return set(schema["required"]) | set(schema["optional"])
