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

# Ligne de base HRV personnelle (#34) : moyenne glissante 7 j de ln(HRV) comparée à
# une référence 60 j ± 0,5 ET (Plews, Laursen & Buchheit 2013 ; Kiviniemi et al. 2007).
# Nombres de jours minimaux exigés avant d'afficher quoi que ce soit — sous ce seuil,
# le calcul rend `None` plutôt qu'une valeur bruitée.
HRV_LN_WINDOW_DAYS = 7          # fenêtre de la moyenne glissante à court terme
HRV_LN_MIN_VALID_DAYS = 5       # jours HRV valides exigés dans ces 7 j
HRV_REF_WINDOW_DAYS = 60        # fenêtre de la référence longue
HRV_REF_MIN_VALID_DAYS = 30     # jours HRV valides exigés dans ces 60 j
HRV_BAND_SD_MULT = 0.5          # largeur de bande : ± 0,5 écart-type (smallest worthwhile change)

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
    "hrv_baseline": f"Ligne de base HRV personnelle : moyenne glissante {HRV_LN_WINDOW_DAYS} j de ln(HRV nocturne) "
                    f"(min. {HRV_LN_MIN_VALID_DAYS} jours valides sur {HRV_LN_WINDOW_DAYS}, sinon aucune valeur), "
                    f"comparée à une référence glissante {HRV_REF_WINDOW_DAYS} j de ln(HRV) (moyenne et écart-type, "
                    f"min. {HRV_REF_MIN_VALID_DAYS} jours valides, sinon « en construction ») ± {HRV_BAND_SD_MULT:g} "
                    "écart-type — une largeur de bande couramment retenue comme « plus petit changement significatif » "
                    "(smallest worthwhile change) sur le lnRMSSD 7 j (Plews, Laursen & Buchheit 2013). La fenêtre de "
                    f"référence se termine {HRV_LN_WINDOW_DAYS} j AVANT le jour évalué (jours j-{HRV_LN_WINDOW_DAYS} à "
                    f"j-{HRV_LN_WINDOW_DAYS + HRV_REF_WINDOW_DAYS - 1}) : elle ne recouvre JAMAIS la fenêtre courte, "
                    "sinon la moyenne 7 j se retrouve diluée dans sa propre référence et l'écart entre les deux est "
                    "mécaniquement rétréci. Hypothèse : `hrv_overnight_ms` (moyenne nocturne Garmin) est traité comme "
                    "une mesure de type rMSSD — Garmin ne documente pas publiquement l'algorithme exact. Le passage "
                    "au log réduit l'asymétrie de la distribution du rMSSD (Plews et al. 2012 ; Plews, Laursen & "
                    "Buchheit 2013). Un jour sans mesure n'est jamais compté comme 0, il est simplement absent des "
                    "deux fenêtres. CV 7 j = écart-type / moyenne de ln(HRV) (pas des valeurs brutes) sur la fenêtre "
                    "courte, en pourcentage : Plews et al. (2012) évaluent la stabilité de la modulation "
                    "parasympathique sur le coefficient de variation du lnRMSSD hebdomadaire, pas sur la valeur "
                    "brute. Kiviniemi et al. (2007) est cité comme PRÉCÉDENT de l'entraînement individualisé guidé "
                    "par une bande statistique (± 1 écart-type autour de la puissance HF de la variabilité "
                    "cardiaque, une mesure et une largeur différentes de celles retenues ici) — pas comme source de "
                    "la largeur ± 0,5 ET ni du CV appliqués dans ce module. Écart-type demandé aux deux fenêtres : "
                    "population (division par N, pas N-1), cohérent avec le reste du module (`daily_series`, "
                    "monotonie de Foster). Ce statut n'est calculé et affiché qu'en `[health].morning_check = "
                    "\"full\"` : en `minimal`, seule la readiness est exposée (rien qui dépende de l'HRV) ; en "
                    "`off`, aucune donnée de santé n'est récupérée.",
    "vo2max": "VO2max effective : VO2 de l'allure (Daniels) ÷ fraction de VO2max estimée par (FC moy / FC max − 0,37) / 0,64. "
              "Calculée depuis l'allure et la FC MOYENNES de la séance (pas de série seconde par seconde) : "
              "ordre de grandeur, pas une mesure. Séances de course de 20 min à 3 h seulement, FC moy ≥ 70 % de la FC max, allure effort ≤ 8:30/km ; "
              "tendance 30 j pondérée par la durée, plafonnée à 90 min par séance.",
    "trail_equivalence": f"Trail : distance effort = distance + D+ × {TRAIL_FLAT_M_PER_M_DPLUS:g} "
                         "(config/sports/trail.md : 1000 m D+ ≈ 1,5 à 2 km plat).",
    "prediction": "Prédictions VDOT (Daniels) depuis la tendance VO2max, et Riegel depuis le meilleur effort récent "
                  "(exposant 1,06 route / 1,15 trail).",
    "records": "Records sur fenêtres de splits consécutifs d'environ 1 km : précision ±1 km.",
    "compliance": "Conformité plan vs réalisé : séances de repos hors calcul (sport ou intensité `rest`), "
                  "`cancelled` exclue du dénominateur (le contrat n'a pas de motif d'annulation distinct "
                  "médical/autre), `moved` exclue (pas de date cible dans le contrat), séance future de la semaine "
                  "en cours jamais comptée manquée, séance du jour même sans activité encore en attente (pas "
                  "manquée), `done` sans activité chiffrée exclue des ratios durée/D+ (comptée en séance faite "
                  "seulement), appariement séance ↔ activité par date + sport (route/trail/randonnée/marche et "
                  "variantes vélo interchangeables), les `done` explicites réservant leur activité avant les "
                  "séances sans statut.",
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
# Ligne de base HRV personnelle
# ---------------------------------------------------------------------------


def _window_values(by_date: Dict[str, float], day: date, days: int, end_offset: int = 0) -> List[float]:
    """Valeurs présentes et strictement positives (`ln` exige > 0) sur les `days` jours
    se terminant à `day - end_offset` inclus.

    Un jour absent de `by_date` n'est pas une mesure à 0 : il est simplement ignoré, la
    fenêtre glissante en compte alors moins que `days`. `end_offset` décale la fin de la
    fenêtre dans le passé — sert à rendre la fenêtre de référence NON chevauchante avec
    la fenêtre courte (voir `hrv_baseline_series`).
    """
    values = []
    last = day - timedelta(days=end_offset)
    for k in range(days):
        v = by_date.get((last - timedelta(days=k)).isoformat())
        if v is not None and v > 0:
            values.append(v)
    return values


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _population_sd(values: List[float], mean: float) -> float:
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def hrv_baseline_series(hrv_by_date: Dict[str, float], start: date, end: date) -> List[dict]:
    """Ligne de base HRV personnelle, jour par jour, de `start` à `end` inclus.

    `hrv_by_date` : `hrv_overnight_ms` brut (millisecondes) par date ISO, jours
    manquants absents du dict (jamais 0). Voir `ASSUMPTIONS["hrv_baseline"]` pour
    la méthode complète et ses sources.

    Chaque point rend :
    - `hrv_ln_mean7` : moyenne glissante 7 j de ln(HRV), `None` sous le seuil de jours valides.
    - `hrv_personal_mean7_ms` : la même moyenne, reconvertie en millisecondes (`exp`), pour
      tracer une courbe directement comparable à `hrv_overnight_ms` (moyenne lissée, pas la
      valeur brute de la nuit).
    - `hrv_cv7_pct` : coefficient de variation 7 j calculé sur ln(HRV) (%), même seuil —
      pas sur les valeurs brutes (Plews et al. 2012, voir `ASSUMPTIONS`).
    - `hrv_personal_low_ms` / `hrv_personal_high_ms` : bande de référence 60 j ± 0,5 ET,
      reconvertie en millisecondes (`exp`) pour rester comparable à la bande Garmin. La
      référence se termine `HRV_LN_WINDOW_DAYS` jours avant `day` : elle ne recouvre jamais
      la fenêtre courte (sinon la moyenne se dilue dans sa propre référence).
    - `hrv_personal_status` : `"sous"`, `"dans_la_norme"`, `"au_dessus"`, `"en_construction"`
      (moyenne 7 j disponible mais référence 60 j encore trop courte), ou `None`
      (pas même de moyenne 7 j).
    """
    out = []
    for day in _daterange(start, end):
        short = _window_values(hrv_by_date, day, HRV_LN_WINDOW_DAYS)
        ref = _window_values(hrv_by_date, day, HRV_REF_WINDOW_DAYS, end_offset=HRV_LN_WINDOW_DAYS)
        point = {
            "date": day.isoformat(),
            "hrv_ln_mean7": None,
            "hrv_personal_mean7_ms": None,
            "hrv_cv7_pct": None,
            "hrv_personal_low_ms": None,
            "hrv_personal_high_ms": None,
            "hrv_personal_status": None,
        }
        if len(short) < HRV_LN_MIN_VALID_DAYS:
            out.append(point)
            continue
        ln_short = [math.log(v) for v in short]
        mean7 = _mean(ln_short)
        point["hrv_ln_mean7"] = round(mean7, 4)
        point["hrv_personal_mean7_ms"] = round(math.exp(mean7), 1)
        point["hrv_cv7_pct"] = round(100 * _population_sd(ln_short, mean7) / mean7, 1)
        if len(ref) >= HRV_REF_MIN_VALID_DAYS:
            ln_ref = [math.log(v) for v in ref]
            ref_mean = _mean(ln_ref)
            ref_sd = _population_sd(ln_ref, ref_mean)
            low, high = ref_mean - HRV_BAND_SD_MULT * ref_sd, ref_mean + HRV_BAND_SD_MULT * ref_sd
            point["hrv_personal_low_ms"] = round(math.exp(low), 1)
            point["hrv_personal_high_ms"] = round(math.exp(high), 1)
            # Comparaison sur la moyenne NON arrondie : `hrv_ln_mean7` (arrondi à 4
            # décimales pour l'affichage) pourrait sinon basculer un cas pile à la
            # frontière (écart-type nul, par exemple) du mauvais côté du seuil.
            point["hrv_personal_status"] = "sous" if mean7 < low else "au_dessus" if mean7 > high else "dans_la_norme"
        else:
            point["hrv_personal_status"] = "en_construction"
        out.append(point)
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


# ---------------------------------------------------------------------------
# Conformité plan vs réalisé (#33)
#
# Compare les séances planifiées d'une semaine (`planning/Semaine_<lundi>.md`,
# sous-schéma `session` de scripts/arc_contract.py) aux activités effectivement
# enregistrées (`activities/*.md`). But : un chiffre de conformité par semaine,
# jamais une déduction sur des données absentes.
#
# Règles, dans l'ordre :
# - une séance de repos (`sport == "rest"` ou `intensity == "rest"`) est hors
#   sujet pour ce KPI : rien n'y est « conforme » ou « manqué ». Elle est
#   retirée de tous les calculs (dénominateur global ET répartition par
#   intensité), comptée à part dans `sessions_rest`. Sans cette exclusion, les
#   semaines lues au format hérité (`scripts/arc_legacy.py::legacy_week`, qui
#   classe toute ligne « Repos » en `sport = "rest"` sans statut) tombaient à
#   50 % de conformité alors que tout avait été fait ;
# - un statut explicite (`done`, `missed`, `cancelled`, `moved`) prime toujours
#   sur l'appariement automatique — mais un appariement automatique différé
#   (deux passes, ci-dessous) leur laisse toujours la priorité sur les activités ;
# - `cancelled` : le contrat (scripts/arc_contract.py::SUBSCHEMA["session"]) n'a
#   pas de motif d'annulation distinct (médical vs organisationnel). Ajouter une
#   clé rien que pour ce KPI aurait été la seule raison de son existence ; on
#   exclut donc TOUTE séance `cancelled` du dénominateur — l'énoncé du critère
#   d'acceptation (annulation médicale hors assiduité) est ainsi respecté au prix
#   d'être plus généreux qu'une distinction fine ne le serait. Si un besoin de
#   distinguer apparaît, la clé optionnelle à ajouter est `cancel_reason`
#   (enum `medical` / autre), documentée aux deux endroits exigés par
#   CONTRIBUTING.md avant d'être utilisée ici ;
# - `moved` : rien n'indique dans le contrat vers quelle date la séance a été
#   déplacée. On l'exclut du dénominateur (ni faite, ni manquée) ; si le coach a
#   effectivement écrit une nouvelle séance à la date réelle, cette séance est
#   comptée pour elle-même, avec son propre statut ;
# - `done` explicite SANS activité appariée (le coach a coché « fait » avant que
#   la synchronisation n'écrive le fichier d'activité, ou l'a écrit sans
#   chiffres) : compte dans `sessions_done` / `sessions_pct`, mais est exclu des
#   DEUX côtés des ratios durée/D+ — l'inclure aurait dégradé le ratio d'un
#   dénominateur planifié sans numérateur réel, pour une séance qu'on sait
#   pourtant faite ;
# - `planned` (ou statut absent), appariement en deux passes pour qu'une séance
#   sans statut ne puisse jamais « voler » l'activité d'une séance `done`
#   explicite du même jour :
#     1. les séances `done` explicites réservent d'abord leur activité (sport
#        exact, puis famille — `SPORT_FAMILY` : route/trail/randonnée/marche
#        interchangeables, variantes de vélo entre elles) ;
#     2. puis les séances sans statut piochent dans ce qui reste. Séance future
#        (date > aujourd'hui) → ignorée (jamais comptée manquée par
#        anticipation) ; séance du jour même sans activité correspondante →
#        `pending` (le jour n'est pas terminé, pas encore une séance manquée) ;
#        séance strictement passée sans correspondance → `missed`.
#   Plusieurs séances/activités le même jour : chaque activité n'est consommée
#   qu'une fois ;
# - semaine sans aucune séance planifiée (hors repos) → `None` (KPI absent),
#   jamais un ratio à 0/0 qui laisserait croire à une semaine blanche.
#
# Répartition par intensité : `easy` (récupération, endurance), `quality`
# (tempo, seuil, VO2max, course) et `other` — le contrat autorise aussi
# `strength` (scripts/arc_contract.py::INTENSITY), qui n'est ni l'un ni
# l'autre ; `other` couvre cette valeur et toute intensité absente, pour que
# easy + quality + other reconstitue toujours le total (hors repos).
# ---------------------------------------------------------------------------

SPORT_FAMILY = {
    "running": "run", "trail": "run", "hiking": "run", "walking": "run",
    "cycling": "bike", "indoor_cycling": "bike", "home_trainer": "bike",
}


def sport_family(sport: Optional[str]) -> Optional[str]:
    return SPORT_FAMILY.get(sport, sport)


EASY_INTENSITIES = ("recovery", "endurance")
QUALITY_INTENSITIES = ("tempo", "threshold", "vo2max", "race")
INTENSITY_BUCKETS = {"easy": EASY_INTENSITIES, "quality": QUALITY_INTENSITIES}

# Statuts qui priment sur l'appariement automatique.
_EXPLICIT_DONE = "done"
_EXPLICIT_MISSED = "missed"


def _is_rest(session: dict) -> bool:
    return session.get("sport") == "rest" or session.get("intensity") == "rest"


def _match_activity(by_date: Dict[str, List[dict]], day: Optional[str], sport: Optional[str]) -> Optional[dict]:
    """Consomme, au plus une fois, la meilleure activité du jour pour ce sport."""
    candidates = by_date.get(day) or []
    for act in candidates:
        if not act["_used"] and act.get("sport") == sport:
            act["_used"] = True
            return act
    family = sport_family(sport)
    for act in candidates:
        if not act["_used"] and sport_family(act.get("sport")) == family:
            act["_used"] = True
            return act
    return None


def _resolve_sessions(sessions: List[dict], by_date: Dict[str, List[dict]], today_iso: str) -> List[dict]:
    """Rend, pour chaque séance (dans l'ordre donné), `{session, effective, actual}`.

    Statuts effectifs : `done`, `missed`, `cancelled`, `moved`, `future`, `pending`.
    Deux passes sur l'appariement automatique (voir le commentaire de tête du
    module) : les `done` explicites réservent leur activité avant que les
    séances sans statut ne piochent dans ce qui reste.
    """
    resolved: List[Optional[dict]] = [None] * len(sessions)

    for i, session in enumerate(sessions):
        if session.get("status") == _EXPLICIT_DONE:
            actual = _match_activity(by_date, session.get("date"), session.get("sport"))
            resolved[i] = {"session": session, "effective": "done", "actual": actual}

    for i, session in enumerate(sessions):
        if resolved[i] is not None:
            continue
        status, day = session.get("status"), session.get("date")
        if status == "cancelled":
            resolved[i] = {"session": session, "effective": "cancelled", "actual": None}
        elif status == "moved":
            resolved[i] = {"session": session, "effective": "moved", "actual": None}
        elif status == _EXPLICIT_MISSED:
            resolved[i] = {"session": session, "effective": "missed", "actual": None}
        elif day and day > today_iso:
            resolved[i] = {"session": session, "effective": "future", "actual": None}
        else:
            matched = _match_activity(by_date, day, session.get("sport"))
            if matched:
                resolved[i] = {"session": session, "effective": "done", "actual": matched}
            elif day == today_iso:
                resolved[i] = {"session": session, "effective": "pending", "actual": None}
            else:
                resolved[i] = {"session": session, "effective": "missed", "actual": None}
    return resolved


def _ratio(actual_total: float, planned_total: float, has_planned: bool) -> Optional[float]:
    return round(actual_total / planned_total, 3) if has_planned and planned_total > 0 else None


def _bucket_metrics(resolved: List[dict]) -> dict:
    """% de séances faites + ratios durée/D+ sur un sous-ensemble de séances résolues."""
    counted = [r for r in resolved if r["effective"] in (_EXPLICIT_DONE, _EXPLICIT_MISSED)]
    done = [r for r in counted if r["effective"] == _EXPLICIT_DONE]
    duration_planned = duration_actual = elevation_planned = elevation_actual = 0.0
    has_duration = has_elevation = False
    for r in counted:
        if r["effective"] == _EXPLICIT_DONE and not r["actual"]:
            # Faite, mais sans activité chiffrée : ni au numérateur ni au dénominateur
            # du ratio (voir le commentaire de tête du module).
            continue
        s = r["session"]
        planned_d = s.get("planned_duration_s")
        if planned_d is not None:
            has_duration = True
            duration_planned += planned_d
            if r["actual"]:
                duration_actual += r["actual"].get("duration_s") or 0
        planned_e = s.get("planned_elevation_m")
        if planned_e is not None:
            has_elevation = True
            elevation_planned += planned_e
            if r["actual"]:
                elevation_actual += r["actual"].get("elevation_gain_m") or 0
    return {
        "sessions_planned": len(counted),
        "sessions_done": len(done),
        "sessions_pct": round(100 * len(done) / len(counted), 1) if counted else None,
        "duration_ratio": _ratio(duration_actual, duration_planned, has_duration),
        "elevation_ratio": _ratio(elevation_actual, elevation_planned, has_elevation),
    }


def week_compliance(sessions: List[dict], activities: List[dict], today) -> Optional[dict]:
    """Conformité plan vs réalisé d'une semaine. `None` si aucune séance planifiée
    (hors repos — voir le commentaire de tête du module).

    `sessions` : lignes `planned_session` (ou sous-schéma `session` du contrat).
    `activities` : lignes `activity` de la même fenêtre (date, sport, duration_s,
    elevation_gain_m…). `today` : `date` ou chaîne AAAA-MM-JJ.
    """
    non_rest_input = [s for s in sessions if not _is_rest(s)]
    if not non_rest_input:
        return None
    today_iso = today.isoformat() if hasattr(today, "isoformat") else today
    by_date: Dict[str, List[dict]] = {}
    for act in activities:
        by_date.setdefault(act.get("date"), []).append({**act, "_used": False})

    ordered = sorted(sessions, key=lambda s: s.get("date") or "")
    resolved_all = _resolve_sessions(ordered, by_date, today_iso)
    rest_count = sum(1 for r in resolved_all if _is_rest(r["session"]))
    resolved = [r for r in resolved_all if not _is_rest(r["session"])]

    overall = _bucket_metrics(resolved)
    other_intensities = set(EASY_INTENSITIES) | set(QUALITY_INTENSITIES)
    by_intensity = {
        name: _bucket_metrics([r for r in resolved if r["session"].get("intensity") in values])
        for name, values in INTENSITY_BUCKETS.items()
    }
    by_intensity["other"] = _bucket_metrics(
        [r for r in resolved if r["session"].get("intensity") not in other_intensities])
    overall.update({
        "sessions_rest": rest_count,
        "sessions_cancelled": sum(1 for r in resolved if r["effective"] == "cancelled"),
        "sessions_moved": sum(1 for r in resolved if r["effective"] == "moved"),
        "sessions_future": sum(1 for r in resolved if r["effective"] == "future"),
        "sessions_pending": sum(1 for r in resolved if r["effective"] == "pending"),
        "by_intensity": by_intensity,
    })
    return overall
