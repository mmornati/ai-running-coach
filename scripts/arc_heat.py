#!/usr/bin/env python3
"""Chaleur : coefficients partagés course/entraînement et ajustement des cibles
de séance (#171, suite de #38 et #59).

## Source unique des coefficients

Les seuils et facteurs de chaleur vivent ICI, et nulle part ailleurs :
`arc_race_pacing.py` (prévision de course, #59) les ré-exporte sous leurs noms
historiques (`HEAT_HOT_C`, `HEAT_HOT_TIME_FACTOR`…) et délègue à
`heat_time_factor` / `resolve_acclimated` ; l'ajustement des séances
d'entraînement (`heat_adjustment`, ci-dessous) utilise les MÊMES valeurs.
Aucun nombre n'est dupliqué dans un prompt : les agents lisent la sortie de
`arc_workout_targets.py targets --heat`.

## Ajustement d'une séance d'entraînement (`heat_adjustment`)

Fonction PURE (aucun accès disque/réseau) : type de séance + température du
créneau retenu (+ ressenti/humidité si présents dans le bloc `arc` météo) +
acclimatation + créneau -> facteur sur l'ALLURE, action recommandée, rappels.

- **La FC prime** : la cible FC (zone de l'intensité planifiée) n'est JAMAIS
  modifiée ; seule l'allure/GAP cible est ralentie (`pace × facteur`). Le facteur
  est celui de la course (`heat_time_factor`) : > `HEAT_HOT_C` -> ×1,10, et ×1,05
  de plus si l'acclimatation est connue comme faible (#38).
- **endurance / sortie longue** : durée conservée, allure ralentie.
- **qualité (seuil, VO2max, tempo) / allure course** : d'abord proposer le créneau
  frais ; à défaut, allures abaissées du même facteur ; en catégorie météo 🔴
  jamais d'intensité maintenue (déplacer ou alléger en endurance à la FC).
- **renforcement / indoor / repos / sport non course** : aucun changement.
- **froid** : volontairement HORS périmètre à l'entraînement. Le facteur de froid
  de la course (< `HEAT_COLD_C`, ×1,05) vise un temps de course prévisionnel ; à
  l'entraînement le froid se gère par l'échauffement et l'habillement, et la FC
  prime déjà. Pas d'ajustement d'allure sous `HEAT_COLD_C`.

## Catégories météo (🟢/🟡/🟠/🔴)

Les seuils de température du skill `weather-forecast` (tableau « Catégories &
seuils ») sont repris ici (`WEATHER_*_C`) pour la seule composante chaleur ; la
catégorie finale est la PIRE entre la catégorie fournie (celle du créneau
retenu, évaluée par le coach, qui voit aussi vent/pluie/orage) et celle déduite
de la température.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_metrics as M  # noqa: E402

# Seuils météo — repris TELS QUELS de `agents/course-strategist.md` (ÉTAPE 6),
# approximation du projet documentée là, jamais une source physiologique
# vérifiable pour ces pourcentages précis.
HEAT_HOT_C = 25.0
HEAT_COLD_C = 5.0
HEAT_HOT_TIME_FACTOR = 1.10
HEAT_COLD_TIME_FACTOR = 1.05
# Supplément si la séance/course est prévue chaude ET que l'athlète a peu été
# exposé à la chaleur récemment (#38) — approximation du projet, pas une mesure.
HEAT_UNACCLIMATED_EXTRA_FACTOR = 1.05
HEAT_ACCLIMATION_MIN_HOT_SESSIONS = 2

# Catégories météo (skill `weather-forecast`, composante température seule).
WEATHER_ORDER = ("green", "yellow", "orange", "red")
WEATHER_YELLOW_C = 22.0   # > 22 °C : 🟡
WEATHER_ORANGE_C = 28.0   # > 28 °C : 🟠
WEATHER_RED_C = 32.0      # > 32 °C : 🔴
# Composantes non thermiques du même tableau, bornes (🟡, 🟠, 🔴) au sens « valeur > borne ».
# Le tableau du skill doit rester ÉGAL à ces constantes : vérifié par
# `tests/lint/test_heat_lint.py` (palier B), qui le relit — une seule source effective.
WEATHER_WIND_KMH = (20.0, 35.0, 50.0)
WEATHER_PRECIP_MM = (1.0, 5.0, 15.0)
WEATHER_UV = (6.0, 8.0)     # > 6 : 🟡, > 8 : 🟠 (le tableau n'a pas de seuil UV 🔴)

# Règles d'hydratation déjà énoncées par le skill `weather-forecast` (« 🟠 ->
# hydratation × 1.2 » ; « chaleur 🟠 + séance longue (> 90 min) -> ≥ 1 L/h »).
HYDRATION_ORANGE_MULTIPLIER = 1.2
HYDRATION_LONG_MIN_L_H = 1.0

# Constantes de Magnus (formule standard du point de rosée, valable ~0-60 °C).
MAGNUS_A = 17.62
MAGNUS_B = 243.12

# Créneaux « frais » (voir `arc_contract.SLOT`).
COOL_SLOTS = ("morning", "evening")

# Types de séance (dérivés de l'intensité planifiée) — voir `classify_session`.
SESSION_TYPES = ("none", "easy", "long", "quality", "race_pace")
QUALITY_INTENSITIES = ("tempo", "threshold", "vo2max")
EASY_INTENSITIES = ("recovery", "endurance")
# Sorties longues : même seuil que `arc_metrics.LONG_RUN_MIN_DURATION_S` (90 min).
LONG_RUN_MIN_DURATION_S = M.LONG_RUN_MIN_DURATION_S

ASSUMPTIONS = {
    "heat_training": (
        "Ajustement des cibles d'ENTRAÎNEMENT à la chaleur prévue (#171). Mêmes coefficients que la "
        "course (`ASSUMPTIONS['heat']` de `arc_race_pacing`, une seule source dans `arc_heat.py`) : "
        "température > 25 °C -> allure × 1,10 (temps), + ×1,05 si l'acclimatation récente est connue "
        "comme faible (#38) — approximation du projet, pas une mesure individuelle ; ces pourcentages "
        "ne proviennent d'aucune étude précise. Contexte seulement : Ely et al. 2007 (Med Sci Sports "
        "Exerc 39(3):487-493, doi:10.1249/mss.0b013e31802d3aba, référence vérifiée sur Crossref) "
        "documentent une dégradation de la performance marathon avec la chaleur ; les coefficients du "
        "projet n'en sont PAS tirés. Facteur appliqué à l'allure/GAP cible UNIQUEMENT : la cible FC "
        "(zone de l'intensité) reste inchangée — à effort perçu et FC égaux, la dérive thermique "
        "ralentit de toute façon l'allure. Température retenue : celle du créneau (`--temp-c`), sinon "
        "`temp_min_c` du jour pour le créneau `morning` et `temp_max_c` pour les autres (borne "
        "prudente : le bloc météo n'a pas de température horaire) ; le ressenti (`feels_like_c`), "
        "quand il est fourni, remplace la température s'il est plus élevé (il intègre déjà l'humidité) ; "
        "en CLI, le ressenti du FICHIER météo (valeur journalière, proche du pic) n'est pas appliqué au "
        "créneau `morning` évalué sur `temp_min_c` (il en annulerait le bénéfice ; `--feels-like-c` reste "
        "possible). "
        "Le point de rosée est calculé (Magnus) à titre INFORMATIF quand l'humidité est présente : "
        "aucun seuil de point de rosée n'est vérifiable ici, donc AUCUNE correction supplémentaire "
        "n'en découle (repli sur la température seule, dit explicitement). Catégories 🟢/🟡/🟠/🔴 : "
        "seuils du skill `weather-forecast` (22/28/32 °C), pire de la catégorie fournie et de la "
        "catégorie déduite. En CLI, la catégorie « du jour » du fichier météo (calculée sur la "
        "température max) n'est PAS reprise telle quelle — elle s'appliquerait à tort à un créneau "
        "frais : seules ses composantes non thermiques (vent, pluie, UV, orage ; `category_from_other`) "
        "et `--category` sont retenues. En 🔴 : aucune intensité n'est maintenue (qualité/allure course -> "
        "déplacer ou alléger en endurance à la FC ; endurance/longue -> reporter ou indoor, règle du "
        "skill). Hydratation : multiplicateur 1,2 (🟠/🔴) et ≥ 1 L/h en sortie longue 🟠/🔴 repris du "
        "skill `weather-forecast` ; le taux de sudation (`arc_index.py fueling`, médiane des sorties "
        "longues) est cité pour information, jamais converti en apport prescrit. Froid : hors "
        "périmètre à l'entraînement (le facteur de froid de la course vise un temps prévisionnel). "
        "Limite : facteur en marche d'escalier à 25 °C (comme la course), sans progressivité."
    ),
}


# ---------------------------------------------------------------------------
# Coefficients partagés avec la course
# ---------------------------------------------------------------------------

def heat_time_factor(temp_max_c: Optional[float], *, acclimated: Optional[bool] = None,
                     hot_factor: Optional[float] = None) -> Tuple[float, List[str]]:
    """Facteur multiplicatif sur le TEMPS (>= 1.0) pour la météo prévue — voir
    `ASSUMPTIONS["heat"]` d'`arc_race_pacing`. `acclimated=False` ajoute le
    supplément `HEAT_UNACCLIMATED_EXTRA_FACTOR` si `temp_max_c` dépasse
    `HEAT_HOT_C`. `hot_factor` (coefficient personnel `[pacing.personal].heat_hot_factor`, #188)
    remplace `HEAT_HOT_TIME_FACTOR` ; `None` = défaut du projet (comportement inchangé).
    Rend `(facteur, notes)`."""
    hot = HEAT_HOT_TIME_FACTOR if hot_factor is None else hot_factor
    if temp_max_c is None:
        return 1.0, ["aucune prévision météo fournie : aucun ajustement chaleur/froid appliqué"]
    notes = []
    factor = 1.0
    if temp_max_c > HEAT_HOT_C:
        factor *= hot
        notes.append(f"chaleur prévue ({temp_max_c:g} °C > {HEAT_HOT_C:g} °C) : temps × {hot:g} "
                     + ("(coefficient personnel, #188)" if hot_factor is not None else "(approximation du projet)"))
        if acclimated is False:
            factor *= HEAT_UNACCLIMATED_EXTRA_FACTOR
            notes.append(f"faible acclimatation chaleur récente (#38) : supplément × "
                         f"{HEAT_UNACCLIMATED_EXTRA_FACTOR:g} (approximation du projet, évaluée sur les 14 "
                         "jours précédant --today)")
    elif temp_max_c < HEAT_COLD_C:
        factor *= HEAT_COLD_TIME_FACTOR
        notes.append(f"froid prévu ({temp_max_c:g} °C < {HEAT_COLD_C:g} °C) : temps × {HEAT_COLD_TIME_FACTOR:g} "
                     "(approximation du projet)")
    return factor, notes


def heat_kind(notes) -> Optional[str]:
    """Nature de l'ajustement météo d'un plan, relue de ses `heat_notes` (la source unique des
    messages est `heat_time_factor`) : `"hot"`, `"cold"`, `"none"` (météo prévue sans correction) ou
    `None` (plan sans notes, ou sans prévision : inconnu, jamais deviné). #188."""
    if not isinstance(notes, (list, tuple)):
        return None
    text = " ".join(str(n) for n in notes)
    if "aucune prévision" in text:
        return None
    if "chaleur prévue" in text:
        return "hot"
    if "froid prévu" in text:
        return "cold"
    return "none"


def resolve_acclimated(conn, conf: dict, today_date, temp_c: Optional[float]) -> Tuple[Optional[bool], Optional[str]]:
    """`(acclimated, note)` — `None` (statut inconnu, jamais assimilé à une
    non-acclimatation) dès que la fenêtre de 14 jours n'a AUCUNE séance
    exploitable (`sessions_considered == 0`), pas seulement aucune séance
    chaude (revue de code #59)."""
    if temp_c is None or temp_c <= HEAT_HOT_C:
        return None, None
    import arc_index as IDX  # noqa: E402 (import tardif : arc_index importe beaucoup de modules)
    report = IDX.heat_acclimation_today(conn, conf, today_date)
    if not report.get("sessions_considered"):
        return None, None
    hot_sessions = report.get("hot_sessions")
    if hot_sessions is None:
        return None, None
    note = f"acclimatation chaleur évaluée sur les 14 jours précédant {today_date.isoformat()} (#38)"
    return hot_sessions >= HEAT_ACCLIMATION_MIN_HOT_SESSIONS, note


# ---------------------------------------------------------------------------
# Entraînement : classification, catégories, ajustement
# ---------------------------------------------------------------------------

def classify_session(session: dict) -> str:
    """`none` | `easy` | `long` | `quality` | `race_pace` à partir de la séance
    (`arc_contract.SUBSCHEMA["session"]`). `none` : renforcement, indoor, repos,
    sport hors course à pied, séance explicitement `outdoor: false`, ou
    intensité inconnue/absente (jamais devinée)."""
    if session.get("sport") not in M.RUNNING_SPORTS or session.get("outdoor") is False:
        return "none"
    intensity = session.get("intensity")
    if intensity in EASY_INTENSITIES:
        duration = session.get("planned_duration_s")
        if isinstance(duration, (int, float)) and duration >= LONG_RUN_MIN_DURATION_S:
            return "long"
        return "easy"
    if intensity in QUALITY_INTENSITIES:
        return "quality"
    if intensity == "race":
        return "race_pace"
    return "none"


def category_from_temp(temp_c: Optional[float]) -> Optional[str]:
    """Catégorie météo (composante température seule) — seuils du skill
    `weather-forecast`. `None` sans température."""
    if temp_c is None:
        return None
    if temp_c > WEATHER_RED_C:
        return "red"
    if temp_c > WEATHER_ORANGE_C:
        return "orange"
    if temp_c > WEATHER_YELLOW_C:
        return "yellow"
    return "green"


def category_from_other(weather: Optional[dict]) -> Optional[str]:
    """Catégorie météo des composantes NON thermiques d'un bloc météo (vent,
    pluie, UV, orage) — mêmes seuils que le tableau du skill `weather-forecast`.
    Sert à ne pas hériter de la catégorie « du jour » (calculée sur la
    température max) pour un créneau frais. `None` sans bloc."""
    if not weather:
        return None
    levels = ["green"]

    def bump(value, bounds):
        if value is None:
            return
        for level, bound in zip(("red", "orange", "yellow"), bounds):
            if value > bound:
                levels.append(level)
                return

    bump(weather.get("wind_kmh"), tuple(reversed(WEATHER_WIND_KMH)))
    bump(weather.get("precip_mm"), tuple(reversed(WEATHER_PRECIP_MM)))
    uv = weather.get("uv_index")
    if uv is not None:
        levels.append("orange" if uv > WEATHER_UV[1] else "yellow" if uv > WEATHER_UV[0] else "green")
    if weather.get("thunderstorm"):
        levels.append("red")
    return worst_category(*levels)


def worst_category(*categories: Optional[str]) -> Optional[str]:
    known = [c for c in categories if c in WEATHER_ORDER]
    return max(known, key=WEATHER_ORDER.index) if known else None


def dew_point_c(temp_c: Optional[float], humidity_pct: Optional[float]) -> Optional[float]:
    """Point de rosée (Magnus), °C, arrondi à 0,1. `None` sans température ou
    avec une humidité hors ]0, 100]."""
    if temp_c is None or humidity_pct is None or not 0 < humidity_pct <= 100:
        return None
    gamma = math.log(humidity_pct / 100.0) + MAGNUS_A * temp_c / (MAGNUS_B + temp_c)
    return round(MAGNUS_B * gamma / (MAGNUS_A - gamma), 1)


def _hydration(session_type: str, category: Optional[str], sweat_rate_l_h: Optional[float]) -> dict:
    """Rappel hydratation/sodium (chaleur uniquement). Jamais un apport prescrit
    calculé à partir du taux de sudation : il n'est cité que pour information."""
    hard = category in ("orange", "red")
    parts = ["boire régulièrement dès le début de la séance et prévoir des électrolytes (sodium)"]
    if sweat_rate_l_h is not None:
        parts.append(f"taux de sudation observé ≈ {sweat_rate_l_h:g} L/h (médiane de tes sorties longues)")
    multiplier = HYDRATION_ORANGE_MULTIPLIER if hard else None
    if multiplier:
        parts.append(f"hydratation habituelle × {multiplier:g}")
    long_min = HYDRATION_LONG_MIN_L_H if hard and session_type == "long" else None
    if long_min:
        parts.append(f"≥ {long_min:g} L/h + casquette en sortie longue")
    return {"sodium_reminder": True, "sweat_rate_l_h": sweat_rate_l_h, "multiplier": multiplier,
            "long_min_l_h": long_min, "text": " ; ".join(parts)}


def heat_adjustment(session_type: str, *, temp_c: Optional[float], feels_like_c: Optional[float] = None,
                    humidity_pct: Optional[float] = None, category: Optional[str] = None,
                    acclimated: Optional[bool] = None, slot: Optional[str] = None,
                    sweat_rate_l_h: Optional[float] = None) -> dict:
    """Ajustement déterministe des cibles d'une séance à la chaleur prévue —
    voir docstring du module et `ASSUMPTIONS["heat_training"]`.

    Rend TOUJOURS un dict (jamais d'exception) : `applies`, `session_type`,
    `temp_c` (retenue), `temp_basis`, `dew_point_c`, `category`, `factor`
    (>= 1, sur l'allure), `pace_slowdown_pct`, `acclimated`, `action`
    (`none` | `slow_pace` | `prefer_cool_slot` | `lower_pace_targets` |
    `reschedule_or_lighten` | `reschedule_or_indoor`), `hr_target_unchanged`
    (toujours `True`), `duration_kept`, `intensity_maintained`,
    `lightened_intensity`, `recommendations`, `hydration`, `reason`, `notes`.
    """
    notes: List[str] = []
    out = {
        "applies": False, "session_type": session_type, "temp_c": None, "temp_basis": None,
        "dew_point_c": None, "category": None, "factor": 1.0, "pace_slowdown_pct": 0.0,
        "acclimated": acclimated, "slot": slot, "action": "none", "hr_target_unchanged": True,
        "duration_kept": True, "intensity_maintained": True, "lightened_intensity": None,
        "recommendations": [], "hydration": None, "reason": None, "notes": notes,
    }
    if session_type not in SESSION_TYPES or session_type == "none":
        notes.append("séance sans cible d'allure de course à pied en extérieur : aucun ajustement chaleur")
        return out

    effective = temp_c
    basis = "temperature"
    if feels_like_c is not None and (effective is None or feels_like_c > effective):
        effective, basis = feels_like_c, "feels_like"
    out["temp_c"], out["temp_basis"] = effective, basis if effective is not None else None
    out["dew_point_c"] = dew_point_c(temp_c, humidity_pct)
    if effective is None:
        pass  # aucune température : la note « aucune température » ci-dessous suffit
    elif humidity_pct is None:
        notes.append("humidité absente du bloc météo : ajustement sur la température seule")
    elif out["dew_point_c"] is not None:
        notes.append(f"point de rosée ≈ {out['dew_point_c']:g} °C (informatif : aucune correction "
                     "supplémentaire, aucun seuil de point de rosée vérifié)")
    if feels_like_c is not None and basis == "temperature":
        notes.append("ressenti ≤ température : température retenue")

    derived = category_from_temp(effective)
    final_category = worst_category(category, derived)
    out["category"] = final_category
    if effective is None and final_category is None:
        notes.append("aucune température ni catégorie météo : aucun ajustement (cibles inchangées)")
        return out

    hot = effective is not None and effective > HEAT_HOT_C
    factor, factor_notes = heat_time_factor(effective if hot else None, acclimated=acclimated)
    notes.extend(n for n in factor_notes if hot)
    if hot and acclimated is None:
        notes.append("acclimatation inconnue : pas de supplément (jamais assimilée à une non-acclimatation)")
    red = final_category == "red"
    if not hot and not red:
        notes.append(f"température ≤ {HEAT_HOT_C:g} °C et catégorie non 🔴 : cibles inchangées")
        return out

    out["applies"] = True
    out["factor"] = round(factor, 4)
    out["pace_slowdown_pct"] = round((factor - 1.0) * 100, 1)
    recs = out["recommendations"]
    temp_txt = f"{effective:g} °C" if effective is not None else "météo 🔴"
    quality = session_type in ("quality", "race_pace")
    cool_already = slot in COOL_SLOTS

    if quality and red:
        out["action"] = "reschedule_or_lighten"
        out["intensity_maintained"] = False
        out["lightened_intensity"] = "endurance"
        recs.append("catégorie 🔴 : ne pas maintenir l'intensité. Déplacer la séance à un jour 🟢/🟡 (ou à un "
                    "créneau frais s'il y repasse en 🟢/🟡), la faire en indoor/tapis, ou l'alléger en endurance "
                    "à la FC (zone endurance)")
        out["reason"] = f"{temp_txt}, catégorie 🔴 : séance de qualité déplacée ou allégée"
    elif quality and not cool_already:
        out["action"] = "prefer_cool_slot"
        recs.append("proposer d'abord le créneau frais (matin tôt, ou soir après la chaleur)")
        recs.append(f"à défaut de créneau frais : allures cibles abaissées (× {out['factor']:g}, soit "
                    f"+{out['pace_slowdown_pct']:g} % sur l'allure), FC cible inchangée, ou déplacer la séance")
        out["reason"] = f"{temp_txt} > {HEAT_HOT_C:g} °C : créneau frais d'abord, sinon allures × {out['factor']:g}"
    elif quality:
        out["action"] = "lower_pace_targets"
        recs.append(f"créneau déjà frais mais {temp_txt} : allures cibles abaissées (× {out['factor']:g}), "
                    "FC cible inchangée ; si la FC dérive, écourter plutôt que forcer")
        out["reason"] = f"{temp_txt} > {HEAT_HOT_C:g} °C : allures × {out['factor']:g}, FC inchangée"
    elif red:
        out["action"] = "reschedule_or_indoor"
        recs.append("catégorie 🔴 : reporter la séance en extérieur ou la basculer en indoor "
                    "(règle du skill weather-forecast) ; si elle est maintenue, allure ralentie et FC en plafond")
        out["reason"] = f"{temp_txt}, catégorie 🔴 : sortie reportée ou indoor"
    else:
        out["action"] = "slow_pace"
        what = "sortie longue" if session_type == "long" else "séance d'endurance"
        recs.append(f"{what} : durée conservée, allure cible ralentie (× {out['factor']:g}, "
                    f"+{out['pace_slowdown_pct']:g} %), FC cible inchangée (la FC prime)")
        out["reason"] = f"{temp_txt} > {HEAT_HOT_C:g} °C : allure × {out['factor']:g}, FC inchangée"
    if hot:
        out["hydration"] = _hydration(session_type, final_category, sweat_rate_l_h)
        recs.append("hydratation/sodium : " + out["hydration"]["text"])
    if acclimated is False and hot:
        out["reason"] += " (acclimatation faible)"
    out["step_note"] = (f"chaleur {temp_txt} : allure × {out['factor']:g}, FC inchangée"
                        if out["action"] in ("slow_pace", "prefer_cool_slot", "lower_pace_targets") else None)
    return out


def slow_pace_s_km(pace_s_km: Optional[float], factor: float) -> Optional[float]:
    """Allure ralentie (s/km) : `pace × factor`. `None`/non positive -> `None`."""
    if not pace_s_km or pace_s_km <= 0:
        return None
    return pace_s_km * factor


def slow_speed_ms(speed_ms: Optional[float], factor: float) -> Optional[float]:
    """Vitesse ralentie (m/s) : `speed / factor` (même sens que `effective_speed =
    base_speed / heat_factor` de la course). `None`/non positive -> `None`."""
    if not speed_ms or speed_ms <= 0 or factor <= 0:
        return None
    return speed_ms / factor
