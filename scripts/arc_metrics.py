#!/usr/bin/env python3
"""Métriques d'entraînement déterministes, calculées à partir de la base dérivée.

Partage des rôles : le LLM observe et juge (il écrit les fichiers et pose le
verdict du jour) ; ce module calcule. Aucune de ces valeurs n'est demandée au
modèle.

- Charge par séance : TRIMP de Banister (FC moyenne, FC repos/max du profil),
  repli sur le session-RPE de Foster quand la FC manque.
- Forme (modèle impulsion-réponse de Banister) : condition (42 j) et fatigue
  (7 j) en moyennes mobiles exponentielles, forme = condition(j-1) − fatigue(j-1),
  ACWR = fatigue / condition. Noms génériques à dessein : voir « Marques »
  dans README.md.
- Monotonie et strain de Foster sur 7 jours.
- VO2max effective par séance (allure + fraction de FC max), tendance 30 j.
- Prédictions : VDOT de Daniels et Riegel.
- Records sur fenêtres glissantes de splits (précision ±1 km).

Toutes les hypothèses sont exposées dans `ASSUMPTIONS`, que le tableau de bord
affiche : ces chiffres sont des modèles, pas des mesures.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constantes et hypothèses
# ---------------------------------------------------------------------------

FITNESS_DAYS = 42
FATIGUE_DAYS = 7
ACWR_SAFE = (0.8, 1.3)
ACWR_MIN_FITNESS = 10.0  # condition quasi nulle (reprise, historique naissant) : le ratio n'a pas de sens

# Banister (1991) : coefficient de pondération exponentielle selon le sexe.
BANISTER_K = {"male": 1.92, "female": 1.67}
BANISTER_K_DEFAULT = 1.92          # sexe non renseigné : valeur classique, signalée

# Session-RPE → échelle TRIMP. Foster compte `minutes × RPE` (≈ 5 UA/min pour un
# effort modéré) ; un TRIMP d'endurance vaut ≈ 1,5 UA/min. Le facteur ramène les
# séances sans FC (renforcement, home trainer sans ceinture) sur la même échelle
# que les autres, sans quoi elles écraseraient la courbe de forme.
RPE_TO_TRIMP = 0.3
DEFAULT_RPE = {"strength": 5, "hiking": 3, "walking": 2, "rest": 0}
DEFAULT_RPE_OTHER = 4

# Équivalence effort du dénivelé en trail — même règle que
# `config/sports/trail.md` (« 1000 m D+ ≈ 1,5 à 2 km plat »), dont
# tests/data/test_arc_metrics.py vérifie l'accord. Milieu de la fourchette.
TRAIL_FLAT_KM_PER_1000M = (1.5, 2.0)
TRAIL_FLAT_M_PER_M_DPLUS = sum(TRAIL_FLAT_KM_PER_1000M) / 2      # 1,75 m plat par m D+

RUNNING_SPORTS = ("running", "trail")
RIEGEL_EXPONENT = {"road": 1.06, "trail": 1.15}
VO2MAX_TREND_DAYS = 30
VO2MAX_PLAUSIBLE = (20.0, 90.0)
VO2MAX_MIN_DURATION_S = 20 * 60
VO2MAX_MAX_DURATION_S = 3 * 3600      # au-delà, dérive cardiaque et fatigue cassent la relation FC → VO2
VO2MAX_MAX_PACE_S_PER_KM = 510        # allure effort > 8:30/km : c'est de la marche, pas une estimation de course
VO2MAX_MAX_WEIGHT_S = 90 * 60         # un ultra de 15 h ne doit pas écraser un mois de séances
VO2MAX_MIN_HR_FRACTION = 0.70         # en dessous de 70 % de la FC max, la relation FC→VO2 est trop lâche
RECORD_DISTANCES_KM = (1, 5, 10, 21)
PREDICTION_DISTANCES_M = (5000.0, 10000.0, 21097.5, 42195.0)

ASSUMPTIONS = {
    "trimp": "TRIMP de Banister : minutes × FCr × 0,64 × e^(k·FCr), FCr = (FC moy − FC repos) / (FC max − FC repos), "
             "k = 1,92 (homme) / 1,67 (femme).",
    "trimp_sex_default": "Sexe non renseigné dans le profil : k = 1,92 appliqué par défaut.",
    "srpe": f"Sans FC : session-RPE de Foster (minutes × RPE) × {RPE_TO_TRIMP} pour rester sur l'échelle TRIMP. "
            "RPE absent : valeur par défaut selon le sport (renforcement 5, randonnée 3, autres 4).",
    "form": f"Modèle impulsion-réponse de Banister : condition = moyenne exponentielle {FITNESS_DAYS} j de la charge, "
            f"fatigue = {FATIGUE_DAYS} j, forme = condition(j-1) − fatigue(j-1). D'autres outils nomment ces grandeurs "
            "CTL, ATL et TSB (marques revendiquées par Peaksware LLC / TrainingPeaks) ; calculées ici sur le TRIMP, "
            "nos valeurs ne sont pas comparables aux leurs.",
    "acwr": f"ACWR = fatigue / condition, affiché dès que la condition atteint {ACWR_MIN_FITNESS:g}. "
            f"La zone {ACWR_SAFE[0]}–{ACWR_SAFE[1]} est un repère indicatif, discuté dans la littérature, pas un seuil de blessure.",
    "monotony": "Monotonie de Foster = moyenne / écart-type de la charge quotidienne sur 7 j ; strain = charge 7 j × monotonie.",
    "vo2max": "VO2max effective : VO2 de l'allure (Daniels) ÷ fraction de VO2max estimée par (FC moy / FC max − 0,37) / 0,64. "
              "Calculée depuis l'allure et la FC MOYENNES de la séance (pas de série seconde par seconde) : "
              "ordre de grandeur, pas une mesure. Séances de course de 20 min à 3 h seulement, FC moy ≥ 70 % de la FC max, allure effort ≤ 8:30/km ; "
              "tendance 30 j pondérée par la durée, plafonnée à 90 min par séance.",
    "trail_equivalence": f"Trail : distance effort = distance + D+ × {TRAIL_FLAT_M_PER_M_DPLUS:g} "
                         "(config/sports/trail.md : 1000 m D+ ≈ 1,5 à 2 km plat).",
    "prediction": "Prédictions VDOT (Daniels) depuis la tendance VO2max, et Riegel depuis le meilleur effort récent "
                  "(exposant 1,06 route / 1,15 trail).",
    "records": "Records sur fenêtres de splits consécutifs d'environ 1 km : précision ±1 km.",
}

# ---------------------------------------------------------------------------
# Charge
# ---------------------------------------------------------------------------


def hr_reserve_fraction(avg_hr, hr_rest, hr_max) -> Optional[float]:
    if not avg_hr or not hr_rest or not hr_max or hr_max <= hr_rest:
        return None
    return min(1.0, max(0.0, (avg_hr - hr_rest) / (hr_max - hr_rest)))


def trimp_banister(duration_s, avg_hr, hr_rest, hr_max, sex=None) -> Optional[float]:
    fraction = hr_reserve_fraction(avg_hr, hr_rest, hr_max)
    if fraction is None or not duration_s:
        return None
    k = BANISTER_K.get(sex or "", BANISTER_K_DEFAULT)
    return (duration_s / 60.0) * fraction * 0.64 * math.exp(k * fraction)


def session_load(activity: dict, athlete: dict) -> Tuple[float, str]:
    """Charge d'une séance et sa provenance : « trimp », « srpe » ou « estimated »."""
    duration = activity.get("duration_s") or 0
    if activity.get("sport") == "rest" or not duration:
        return 0.0, "none"
    trimp = trimp_banister(
        duration, activity.get("avg_hr_bpm"),
        athlete.get("hr_rest_bpm"), athlete.get("hr_max_bpm"), athlete.get("sex"),
    )
    if trimp is not None:
        return trimp, "trimp"
    rpe = activity.get("rpe")
    source = "srpe"
    if rpe is None:
        rpe = DEFAULT_RPE.get(activity.get("sport"), DEFAULT_RPE_OTHER)
        source = "estimated"
    return (duration / 60.0) * rpe * RPE_TO_TRIMP, source


# ---------------------------------------------------------------------------
# Forme : condition / fatigue / forme / ACWR, monotonie / strain
# ---------------------------------------------------------------------------


def _daterange(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def daily_series(loads_by_date: Dict[str, float], start: date, end: date) -> List[dict]:
    """Série quotidienne de start à end inclus (jours sans séance = charge 0)."""
    a_fit = 1 - math.exp(-1 / FITNESS_DAYS)
    a_fat = 1 - math.exp(-1 / FATIGUE_DAYS)
    fitness = fatigue = 0.0
    window: List[float] = []
    out = []
    for day in _daterange(start, end):
        load = loads_by_date.get(day.isoformat(), 0.0)
        form = fitness - fatigue                     # forme en entrant dans la journée
        fitness += (load - fitness) * a_fit
        fatigue += (load - fatigue) * a_fat
        window = (window + [load])[-7:]
        monotony = strain = None
        if len(window) == 7:
            mean = sum(window) / 7
            sd = math.sqrt(sum((x - mean) ** 2 for x in window) / 7)
            if sd > 0:
                monotony = mean / sd
                strain = sum(window) * monotony
        out.append({
            "date": day.isoformat(),
            "load": round(load, 2),
            "fitness": round(fitness, 2),
            "fatigue": round(fatigue, 2),
            "form": round(form, 2),
            "acwr": round(fatigue / fitness, 3) if fitness >= ACWR_MIN_FITNESS else None,
            "monotony": round(monotony, 3) if monotony is not None else None,
            "strain": round(strain, 1) if strain is not None else None,
        })
    return out


# ---------------------------------------------------------------------------
# VO2max effective, prédictions
# ---------------------------------------------------------------------------


def vo2_of_speed(meters_per_min: float) -> float:
    """Coût en O2 (ml/kg/min) d'une allure (Daniels & Gilbert)."""
    v = meters_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def vo2max_fraction_of_duration(minutes: float) -> float:
    """Fraction de VO2max soutenable pendant `minutes` (Daniels & Gilbert)."""
    t = minutes
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def vdot(distance_m: float, time_s: float) -> Optional[float]:
    """VDOT d'une performance maximale (distance, temps)."""
    if distance_m <= 0 or time_s <= 0:
        return None
    minutes = time_s / 60
    return vo2_of_speed(distance_m / minutes) / vo2max_fraction_of_duration(minutes)


def effort_distance_m(activity: dict) -> Optional[float]:
    distance = activity.get("distance_m")
    if not distance:
        return None
    if activity.get("sport") == "trail":
        return distance + (activity.get("elevation_gain_m") or 0) * TRAIL_FLAT_M_PER_M_DPLUS
    return float(distance)


def vo2max_effective(activity: dict, athlete: dict) -> Optional[float]:
    """Estimation par séance. None si les données ne suffisent pas ou si l'estimation est aberrante."""
    if activity.get("sport") not in RUNNING_SPORTS:
        return None
    duration, avg_hr, hr_max = activity.get("duration_s"), activity.get("avg_hr_bpm"), athlete.get("hr_max_bpm")
    distance = effort_distance_m(activity)
    if not distance or not duration or not VO2MAX_MIN_DURATION_S <= duration <= VO2MAX_MAX_DURATION_S or not avg_hr or not hr_max:
        return None
    moving = activity.get("moving_duration_s") or duration
    if moving / (distance / 1000) > VO2MAX_MAX_PACE_S_PER_KM or avg_hr / hr_max < VO2MAX_MIN_HR_FRACTION:
        return None
    fraction = (avg_hr / hr_max - 0.37) / 0.64
    if fraction <= 0.3:
        return None
    estimate = vo2_of_speed(distance / (moving / 60)) / min(fraction, 1.0)
    lo, hi = VO2MAX_PLAUSIBLE
    return round(estimate, 2) if lo <= estimate <= hi else None


def vo2max_trend(estimates: List[Tuple[str, float, float]], day: str, days: int = VO2MAX_TREND_DAYS) -> Optional[float]:
    """Moyenne des estimations des `days` derniers jours, pondérée par la durée.

    `estimates` : liste de (date ISO, estimation, durée en s).
    """
    end = date.fromisoformat(day)
    start = end - timedelta(days=days - 1)
    weight = total = 0.0
    for when, value, duration in estimates:
        d = date.fromisoformat(when)
        if start <= d <= end:
            w = min(duration, VO2MAX_MAX_WEIGHT_S)
            total += value * w
            weight += w
    return round(total / weight, 2) if weight else None


def predict_time_vdot(vdot_value: float, distance_m: float) -> Optional[float]:
    """Temps (s) sur `distance_m` pour un VDOT donné : résolution par dichotomie."""
    if not vdot_value or vdot_value <= 0 or distance_m <= 0:
        return None
    lo, hi = 60.0, 60.0 * 60 * 48
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot(distance_m, mid) > vdot_value:
            lo = mid                                # trop rapide pour ce VDOT
        else:
            hi = mid
    return round((lo + hi) / 2)


def riegel(time_s: float, distance_m: float, target_m: float, exponent: float) -> float:
    return round(time_s * (target_m / distance_m) ** exponent)


# ---------------------------------------------------------------------------
# Records (fenêtres de splits)
# ---------------------------------------------------------------------------


def best_efforts(activities: List[dict]) -> Dict[int, dict]:
    """Meilleur temps sur 1/5/10/21 km consécutifs, tous splits confondus.

    Chaque activité : {"date", "sport", "distance_m"?, "splits": [{"km", "duration_s", "distance_m"?}, …]}.
    Un tour qui ne fait pas environ 1 km (distance_m hors de 900-1100 : reliquat final,
    pas de séance structurée de 500 m ou de 2 km) interrompt la fenêtre. Sans distance par split,
    le dernier est présumé partiel dès qu'il y a plus de splits que de kilomètres
    entiers (25,19 km → 26 splits : le 26ᵉ fait 190 m, pas un « record » en 0:49).
    """
    best: Dict[int, dict] = {}
    for act in activities:
        if act.get("sport") not in RUNNING_SPORTS:
            continue
        splits = sorted(act.get("splits") or [], key=lambda s: s.get("km") or 0)
        whole_km = int((act.get("distance_m") or 0) // 1000)
        if splits and whole_km and len(splits) > whole_km and splits[-1].get("distance_m") is None:
            splits = splits[:-1]
        durations = []
        for split in splits:
            partial = split.get("distance_m") is not None and not 900 <= split["distance_m"] <= 1100
            durations.append(None if partial or not split.get("duration_s") else split["duration_s"])
        for km in RECORD_DISTANCES_KM:
            for i in range(0, len(durations) - km + 1):
                window = durations[i:i + km]
                if any(d is None for d in window):
                    continue
                total = sum(window)
                if km not in best or total < best[km]["time_s"]:
                    best[km] = {"time_s": round(total), "date": act["date"], "activity_name": act.get("name")}
    return best


def predictions(vdot_value: Optional[float], records: Dict[int, dict], primary: str,
                target_m: Optional[float] = None, target_dplus_m: Optional[float] = None) -> List[dict]:
    """Tableau de prédictions : distances standard + distance cible de l'objectif."""
    exponent = RIEGEL_EXPONENT.get(primary, RIEGEL_EXPONENT["road"])
    reference = None
    for km in sorted(records, reverse=True):            # le plus long effort est le plus prédictif
        if km >= 5:
            reference = (records[km]["time_s"], km * 1000.0)
            break
    rows = []
    targets = [(d, None, None) for d in PREDICTION_DISTANCES_M]
    if target_m:
        effort = target_m
        if primary == "trail" and target_dplus_m:
            effort = target_m + target_dplus_m * TRAIL_FLAT_M_PER_M_DPLUS
        targets.append((effort, target_m, "objective"))
    for effort_m, real_m, tag in targets:
        rows.append({
            "distance_m": real_m or effort_m,
            "effort_distance_m": round(effort_m),
            "tag": tag,
            "vdot_s": predict_time_vdot(vdot_value, effort_m) if vdot_value else None,
            "riegel_s": riegel(reference[0], reference[1], effort_m, exponent) if reference else None,
        })
    return rows
