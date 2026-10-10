#!/usr/bin/env python3
"""Vitesse critique (CS), réserve anaérobie D′ et courbe allure-durée en GAP (#169).

Fonctions **pures** (sans SQLite ni disque), testées au palier D ; la lecture
des échantillons et l'agrégation par séance vivent dans `scripts/arc_index.py`
(`pace_curve`, CLI `pace-curve`), qui importe ce module. Rien n'est persisté :
tout est recalculé à la lecture depuis `activity_sample` (jetable comme le reste
de l'index) — aucune table nouvelle, donc pas de changement de `SCHEMA_VERSION`.

## Courbe allure-durée (« mean-maximal »)

Pour chaque durée standard (`STANDARD_DURATIONS_S`, 30 s à 2 h), la **meilleure
vitesse GAP moyenne** (allure ajustée à la pente, `arc_gap`) sur une fenêtre
glissante de cette durée dans UNE séance (`activity_curve`), puis le meilleur
de toutes les séances d'une fenêtre de dates (`best_of`) : 42 j, 90 j, 365 j.
La vitesse GAP neutralise le D+ : un effort en côte et un effort à plat de même
coût métabolique se valent (approximation du projet, voir
`ASSUMPTIONS["gap_basis"]`).

## Fenêtres, pauses et trous de signal — le choix et sa raison

Les fenêtres sont sur le **temps écoulé** (une grille régulière de pas =
résolution des échantillons, 5 s par défaut), pas sur le temps de mouvement :
un effort « de 10 min » qui contient 90 s d'arrêt n'est pas un effort de
10 min. Une fenêtre n'est retenue que si les échantillons y **couvrent au moins
`MIN_COVERAGE` (95 %)** de sa durée (`covered_s`, voir
`arc_samples.ASSUMPTIONS["covered_s"]`) ; un trou de signal ou une pause
enregistrée comme absence de mesure disqualifie donc la fenêtre — jamais
interpolé (`arc_samples`, « Pauses et trous de signal »). Un arrêt enregistré
(vitesse ≈ 0) compte, lui, comme du temps couvert à vitesse nulle : il tire la
moyenne vers le bas, ce qui est le comportement voulu pour un « meilleur
effort continu ».

## Ajustement CS / D′ (modèle hyperbolique à 2 paramètres)

`d = CS·t + D′` (distance GAP parcourue en `t` secondes à effort maximal) par
régression linéaire (moindres carrés) sur les meilleurs efforts de
`FIT_MIN_S` à `FIT_MAX_S` (3 à 20 min). Voir `ASSUMPTIONS["model"]`.
`fit_cs` **refuse explicitement** (`status: "refused"`, `reason_code`) quand les
données ne le permettent pas — jamais d'extrapolation silencieuse, jamais de
valeur par défaut. Qualité rapportée : `n_points`, `r2`, `see_m` (erreur
standard de l'estimation, en mètres), `cs_se_ms`, `d_prime_se_m` et le niveau
`quality`, jugé sur l'erreur standard RELATIVE de CS et D′ (`ASSUMPTIONS["quality"]`),
pas sur le R² (presque toujours > 0,99 pour une régression distance-durée).

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_gap as G  # noqa: E402

# Durées standard de la courbe (secondes) : 30 s, 1, 2, 3, 5, 8, 10, 12, 15, 20,
# 30, 45, 60, 90, 120 min.
STANDARD_DURATIONS_S = (30, 60, 120, 180, 300, 480, 600, 720, 900, 1200, 1800, 2700, 3600, 5400, 7200)

# Fenêtres de dates de la courbe « meilleur de » (jours se terminant à `today`).
CURVE_WINDOWS_DAYS = (42, 90, 365)

# Efforts retenus pour l'ajustement CS/D′ : 3 à 20 min (domaine « sévère » où le
# modèle hyperbolique est usuellement appliqué, voir ASSUMPTIONS["model"]).
FIT_MIN_S = 180
FIT_MAX_S = 1200

# Au moins 3 points, et un rapport durée max / durée min d'au moins 3 : sans cette
# dispersion la pente (CS) et l'ordonnée (D′) ne sont pas séparables.
MIN_FIT_POINTS = 3
MIN_SPAN_RATIO = 3.0

# Au moins 2 séances DIFFÉRENTES parmi les points (quand ils portent leur `ref`) : une seule séance
# longue fournit toute la courbe par dilution (fenêtres plus longues que l'effort, mêlées de
# course facile) et imiterait un ajustement hyperbolique sans qu'aucun effort ne le justifie.
MIN_SOURCES = 2

# Part minimale de la durée d'une fenêtre réellement couverte par des échantillons.
MIN_COVERAGE = 0.95

# Bornes de plausibilité de D′ (m) : en deçà, la courbe est plate (efforts non
# maximaux — le « meilleur effort » n'est pas un effort maximal) ; au-delà, l'ajustement
# absorbe autre chose qu'une réserve anaérobie. Approximation du projet.
D_PRIME_MIN_M = 30.0
D_PRIME_MAX_M = 1000.0

# R² minimal pour accepter l'ajustement : en dessous, les « meilleurs efforts »
# ne suivent pas la relation distance-durée linéaire (efforts hétérogènes).
# Garde-fou GROSSIER seulement : la distance croît presque proportionnellement à la
# durée, si bien que le R² d'une régression distance-durée dépasse 0,99 même pour des
# efforts peu cohérents. La QUALITÉ (`QUALITY_SE_PCT`) se juge donc sur l'erreur
# standard RELATIVE de chaque paramètre, pas sur le R² (revue de code #169).
MIN_R2 = 0.95

# Niveaux de qualité : erreur standard relative maximale (%) de la CS et de D′.
# « bonne » exige en plus au moins 4 points (avec 3 points, 1 seul degré de liberté).
# Seuils = approximation du projet (voir ASSUMPTIONS["quality"]).
QUALITY_SE_PCT = {"bonne": (2.0, 10.0), "moyenne": (5.0, 25.0)}
QUALITY_MIN_POINTS_GOOD = 4

# Plage plausible d'une vitesse au seuil lactique (m/s) : hors de cette plage (ex. une
# valeur 10 fois trop petite, unité mal convertie), le contrôle est refusé, jamais calculé.
LT_SPEED_PLAUSIBLE_MS = (1.5, 7.0)

# Pas de la tendance (jours) et fenêtre de « meilleur de » de chaque point.
TREND_STEP_DAYS = 28
TREND_WINDOW_DAYS = 90
TREND_DEFAULT_DAYS = 365

# Écart (fraction) au-delà duquel CS et seuil lactique Garmin sont dits divergents.
THRESHOLD_DIVERGENCE_PCT = 5.0

ASSUMPTIONS = {
    "model": (
        "Vitesse critique (CS) et réserve anaérobie D′ : modèle hyperbolique à 2 paramètres, distance = "
        "CS × durée + D′, ajusté par moindres carrés sur les meilleurs efforts de 3 à 20 minutes. C'est "
        "l'équivalent en course à pied du couple puissance critique / W′ du cyclisme (Jones AM & Vanhatalo A "
        "(2017), « The 'Critical Power' Concept: Applications to Sports Performance with a Focus on "
        "Intermittent High-Intensity Exercise », Sports Med 47(Suppl 1):65-78, doi: 10.1007/s40279-017-0688-0 ; "
        "Poole DC, Burnley M, Vanhatalo A, Rossiter HB & Jones AM (2016), « Critical Power », Med Sci Sports "
        "Exerc 48(11):2320-2334, doi: 10.1249/mss.0000000000000939 — références vérifiées via Crossref ; ces "
        "articles décrivent le concept de puissance critique, son transfert à la vitesse critique en course "
        "est une approximation du projet). La fenêtre 3-20 min et les seuils de validité (au moins 3 points, "
        "rapport de durées d'au moins 3, R² d'au moins 0,95, D′ entre 30 et 1000 m) sont des choix du projet, "
        "pas des valeurs publiées."
    ),
    "gap_basis": (
        "Les vitesses de la courbe sont des vitesses GAP (allure ajustée à la pente, modèle de Kay 2012, voir "
        "arc_gap.ASSUMPTIONS) : la CS est donc une vitesse « équivalent plat ». Les limites du GAP s'héritent : "
        "bruit de pente sur un instant, gain en descente généreux pour la plupart des athlètes. Une séance sans "
        "altitude exploitable (tapis, capteur barométrique absent) est ÉCARTÉE de la courbe (comptée dans "
        "`skipped_no_grade`), jamais supposée plate."
    ),
    "windows_and_gaps": (
        "Fenêtres glissantes sur le temps ÉCOULÉ, grille régulière à la résolution des échantillons (5 s) : "
        "une fenêtre n'est retenue que si les échantillons couvrent au moins 95 % de sa durée (covered_s) ; un "
        "trou de signal ou une pause non enregistrée (pause automatique de la montre) la disqualifie, jamais "
        "interpolé. Un arrêt enregistré (vitesse nulle, ex. ravitaillement en trail) compte comme du temps "
        "couvert à vitesse nulle : un meilleur effort qui enjambe un ravitaillement est donc pénalisé. "
        "Compromis assumé : des fenêtres sur le temps de MOUVEMENT recolleraient les morceaux de part et "
        "d'autre de l'arrêt, alors que D′ se reconstitue pendant l'arrêt — un effort intermittent passerait pour "
        "un effort continu et gonflerait CS et D′. Sur le temps écoulé, l'erreur va dans le sens prudent "
        "(CS basse). Résolution de 5 s : la fenêtre de 30 s "
        "est la plus courte exploitable ; un pic de vitesse GPS isolé peut gonfler les durées très courtes "
        "(hors ajustement CS/D′, qui part de 3 min)."
    ),
    "best_efforts_not_tests": (
        "Les « meilleurs efforts » viennent de l'entraînement et de la course, pas d'un test à l'épuisement : "
        "si l'athlète n'a jamais couru à fond sur une durée, le meilleur effort sous-estime sa capacité réelle "
        "et la CS ressort BASSE (jamais haute par construction). Les points d'un ajustement proviennent de "
        "séances différentes (jusqu'à toute la fenêtre de dates), pas d'une même journée : une forme qui "
        "évolue sur la fenêtre brouille l'ajustement. Une fenêtre courte hérite aussi de tout effort plus long "
        "(le meilleur 3 min d'un effort de 10 min est au moins sa vitesse moyenne) : une seule séance fournit "
        "ainsi toute une courbe (par dilution au-delà de l'effort) : un ajustement dont tous les points "
        "viennent d'une seule séance est refusé, jamais une CS. Même avec 2 séances, des points hérités "
        "d'un effort plus long restent des bornes basses. La qualité (n, R², erreur standard) est toujours "
        "rapportée ; une CS issue d'un ajustement « moyenne » ou « faible » est un ordre de grandeur."
    ),
    "quality": (
        "Qualité d'un ajustement accepté jugée sur l'erreur standard RELATIVE de chaque paramètre (erreur "
        "standard de la pente et de l'ordonnée de la régression, rapportée à la CS et à D′) : « bonne » si au "
        "moins 4 points, CS à ±2 % et D′ à ±10 % ; « moyenne » si CS à ±5 % et D′ à ±25 % ; « faible » sinon. Le "
        "R² n'y entre pas : la distance croissant presque proportionnellement à la durée, il dépasse 0,99 même "
        "pour des efforts peu cohérents (il ne sert que de garde-fou grossier, seuil 0,95). Seuils : "
        "approximation du projet, pas des valeurs publiées."
    ),
    "refusal": (
        "Refus explicite (jamais d'extrapolation silencieuse) : moins de 3 durées disponibles entre 3 et "
        "20 min, points issus d'une seule séance, rapport de durées inférieur à 3, D′ hors de [30 ; 1000] m (courbe plate ou ajustement "
        "incohérent), CS non positive ou R² sous 0,95 — le motif est rendu dans `reason`/`reason_code`."
    ),
    "trend": (
        "Tendance de la CS : un ajustement indépendant tous les 28 jours, chacun sur le meilleur de 90 jours "
        "se terminant à ce point (une fenêtre de 42 jours contient rarement assez d'efforts de 3 à 20 min). "
        "Un point sans ajustement valide rend son motif de refus, jamais une valeur reportée du point "
        "précédent."
    ),
    "targets": (
        "Cibles d'intervalles en % de la CS (arc_workout_targets) : seuil 95-100 %, tempo 88-95 %, VO2max "
        "102-110 % de la CS, UNIQUEMENT quand l'ajustement est valide. Ces pourcentages sont une approximation "
        "du projet (pas des valeurs publiées) : au-dessus de la CS, la durée tenable est bornée par D′ "
        "(D′ / (v − CS)) ; une cible ne doit jamais dépasser ce budget. Elles complètent les zones de "
        "fréquence cardiaque, jamais ne les remplacent. Par la chaleur (targets --heat, #171), elles sont "
        "ralenties du même facteur que les autres cibles d'allure (cs_target.adjusted) ; le budget D′ n'est pas "
        "recalculé (effet de la chaleur sur D′ non modélisé)."
    ),
    "lactate_crosscheck": (
        "Contrôle de cohérence avec le seuil lactique estimé par Garmin (quand l'athlète le renseigne) : un "
        "écart de plus de 5 % entre CS et vitesse au seuil est SIGNALÉ, jamais arbitré — les deux sont des "
        "estimations par des méthodes différentes (CS : meilleurs efforts de l'athlète ; seuil Garmin : "
        "algorithme propriétaire non documenté publiquement dans le détail). Le seuil lactique et la CS ne "
        "désignent pas exactement la même intensité : un écart modéré est normal. Une vitesse au seuil hors de "
        "1,5-7 m/s est refusée (unité probablement mal convertie), jamais comparée."
    ),
}


# ---------------------------------------------------------------------------
# Courbe d'UNE séance
# ---------------------------------------------------------------------------


def _slots(series: Sequence[dict], resolution_s: float):
    """Tableaux (couverture s, distance GAP m) par case de la grille régulière."""
    pts = []
    for s in series:
        t = s.get("t_s")
        v = s.get("gap_speed_ms")
        if t is None or v is None or v < 0:
            continue
        cov = s.get("covered_s")
        cov = resolution_s if cov is None else max(0.0, min(float(cov), resolution_s))
        pts.append((int(t // resolution_s), cov, v * cov))
    if not pts:
        return [], []
    n = max(p[0] for p in pts) + 1
    cov_arr = [0.0] * n
    dist_arr = [0.0] * n
    for idx, cov, dist in pts:
        cov_arr[idx] += cov
        dist_arr[idx] += dist
    return cov_arr, dist_arr


def activity_curve(samples: Sequence[dict], *, durations_s: Sequence[int] = STANDARD_DURATIONS_S,
                   resolution_s: float = G.DEFAULT_RESOLUTION_S, min_coverage: float = MIN_COVERAGE) -> dict:
    """Meilleure vitesse GAP moyenne par durée dans UNE séance.

    Rend `{"curve": {durée_s: vitesse_ms}, "reason_code": ...}` : `curve` ne contient
    que les durées pour lesquelles une fenêtre assez couverte existe ; vide + `reason_code`
    (`"no_samples"`, `"no_grade"`) sinon. Jamais d'exception."""
    if not samples:
        return {"curve": {}, "reason_code": "no_samples"}
    series = G.gap_sample_series(samples)
    if not any(s.get("grade") is not None for s in series):
        return {"curve": {}, "reason_code": "no_grade"}
    cov, dist = _slots(series, resolution_s)
    n = len(cov)
    pc = [0.0] * (n + 1)
    pd = [0.0] * (n + 1)
    for i in range(n):
        pc[i + 1] = pc[i] + cov[i]
        pd[i + 1] = pd[i] + dist[i]
    curve: Dict[int, float] = {}
    for dur in durations_s:
        k = int(round(dur / resolution_s))
        if k < 1 or k > n:
            continue
        need = min_coverage * k * resolution_s
        best = None
        for i in range(0, n - k + 1):
            c = pc[i + k] - pc[i]
            if c < need or c <= 0:
                continue
            v = (pd[i + k] - pd[i]) / c
            if best is None or v > best:
                best = v
        if best is not None:
            curve[int(dur)] = best
    return {"curve": curve, "reason_code": None if curve else "no_window"}


# ---------------------------------------------------------------------------
# Meilleur de plusieurs séances
# ---------------------------------------------------------------------------


def best_of(activity_curves: Sequence[dict], today: date, window_days: int) -> List[dict]:
    """Meilleur de `activity_curves` (`{"date": "AAAA-MM-JJ", "ref": ..., "curve": {...}}`) sur
    les `window_days` jours se terminant à `today` (bornes incluses). Rend une ligne par durée
    disponible : `{"duration_s", "speed_ms", "pace_s_km", "date", "ref"}`, triée par durée."""
    start = (today - timedelta(days=window_days - 1)).isoformat()
    end = today.isoformat()
    best: Dict[int, dict] = {}
    for ac in activity_curves:
        d = ac.get("date")
        if d is None or d < start or d > end:
            continue
        for dur, v in ac.get("curve", {}).items():
            cur = best.get(dur)
            if cur is None or v > cur["speed_ms"]:
                best[dur] = {"duration_s": dur, "speed_ms": v, "date": d, "ref": ac.get("ref")}
    rows = [best[d] for d in sorted(best)]
    for r in rows:
        r["pace_s_km"] = 1000.0 / r["speed_ms"] if r["speed_ms"] > 0 else None
    return rows


# ---------------------------------------------------------------------------
# Ajustement CS / D′
# ---------------------------------------------------------------------------


def _refused(code: str, reason: str, **extra) -> dict:
    return {"status": "refused", "valid": False, "reason_code": code, "reason": reason,
            "cs_ms": None, "cs_pace_s_km": None, "d_prime_m": None, **extra}


def fit_cs(points: Sequence[dict], *, fit_min_s: int = FIT_MIN_S, fit_max_s: int = FIT_MAX_S) -> dict:
    """Ajuste distance = CS·t + D′ sur `points` (`{"duration_s", "speed_ms"}`), uniquement ceux
    de `[fit_min_s, fit_max_s]`. Rend toujours un dict avec `status` (`"ok"` | `"refused"`),
    `valid`, `reason`/`reason_code` ; en cas de succès aussi `cs_ms`, `cs_pace_s_km`, `d_prime_m`,
    `r2`, `see_m`, `cs_se_ms`, `n_points`, `quality`, `points` (durée, distance, ajustée)."""
    sel = sorted(((float(p["duration_s"]), float(p["speed_ms"])) for p in points
                  if fit_min_s <= p["duration_s"] <= fit_max_s and p.get("speed_ms") and p["speed_ms"] > 0))
    n = len(sel)
    if n < MIN_FIT_POINTS:
        return _refused("insufficient_points",
                        f"{n} effort(s) exploitable(s) entre {fit_min_s // 60} et {fit_max_s // 60} min "
                        f"(minimum {MIN_FIT_POINTS}) : données insuffisantes", n_points=n)
    refs = {p.get("ref") for p in points if fit_min_s <= p["duration_s"] <= fit_max_s and p.get("ref") is not None}
    if any("ref" in p for p in points) and len(refs) < MIN_SOURCES:
        return _refused("single_source",
                        f"tous les efforts viennent d'une seule séance (minimum {MIN_SOURCES} séances "
                        "différentes) : une seule séance ne permet pas d'ajuster CS et D′", n_points=n)
    ratio = sel[-1][0] / sel[0][0]
    if ratio < MIN_SPAN_RATIO:
        return _refused("insufficient_span",
                        f"efforts trop rapprochés en durée (rapport {ratio:.1f}, minimum {MIN_SPAN_RATIO:g}) : "
                        "CS et D′ non séparables", n_points=n)
    ts = [t for t, _ in sel]
    ds = [t * v for t, v in sel]
    mt = sum(ts) / n
    md = sum(ds) / n
    sxx = sum((t - mt) ** 2 for t in ts)
    cs = sum((t - mt) * (d - md) for t, d in zip(ts, ds)) / sxx
    dp = md - cs * mt
    fitted = [cs * t + dp for t in ts]
    ssr = sum((d - f) ** 2 for d, f in zip(ds, fitted))
    sst = sum((d - md) ** 2 for d in ds)
    r2 = 1.0 - ssr / sst if sst > 0 else 1.0
    see = math.sqrt(ssr / (n - 2)) if n > 2 else 0.0
    cs_se = see / math.sqrt(sxx)
    dp_se = see * math.sqrt(1.0 / n + mt * mt / sxx)   # erreur standard de l'ordonnée (D′)
    pts = [{"duration_s": int(t), "distance_m": round(d, 1), "fitted_m": round(f, 1)}
           for t, d, f in zip(ts, ds, fitted)]
    common = {"n_points": n, "r2": round(r2, 4), "see_m": round(see, 1), "cs_se_ms": round(cs_se, 4),
              "d_prime_se_m": round(dp_se, 1), "points": pts}
    if cs <= 0:
        return _refused("non_positive_cs", "vitesse critique non positive : efforts incohérents", **common)
    if dp < D_PRIME_MIN_M or dp > D_PRIME_MAX_M:
        return _refused("d_prime_out_of_range",
                        f"D′ = {dp:.0f} m hors de [{D_PRIME_MIN_M:g} ; {D_PRIME_MAX_M:g}] m : courbe plate "
                        "(efforts non maximaux) ou ajustement incohérent", **common)
    if r2 < MIN_R2:
        return _refused("poor_fit", f"ajustement médiocre (R² = {r2:.3f}, minimum {MIN_R2:g}) : "
                                    "efforts hétérogènes", **common)
    cs_se_pct, dp_se_pct = cs_se / cs * 100.0, dp_se / dp * 100.0
    good, fair = QUALITY_SE_PCT["bonne"], QUALITY_SE_PCT["moyenne"]
    if n >= QUALITY_MIN_POINTS_GOOD and cs_se_pct <= good[0] and dp_se_pct <= good[1]:
        quality = "bonne"
    elif cs_se_pct <= fair[0] and dp_se_pct <= fair[1]:
        quality = "moyenne"
    else:
        quality = "faible"
    return {"status": "ok", "valid": True, "reason": None, "reason_code": None,
            "cs_ms": round(cs, 4), "cs_pace_s_km": round(1000.0 / cs, 1), "d_prime_m": round(dp, 1),
            "quality": quality, "cs_se_pct": round(cs_se_pct, 1), "d_prime_se_pct": round(dp_se_pct, 1),
            **common}


def d_prime_budget_s(fit: Optional[dict], speed_ms: float) -> Optional[float]:
    """Durée (s) pendant laquelle `speed_ms` (> CS) épuise D′ : D′ / (v − CS). `None` si l'ajustement
    n'est pas valide ou si `speed_ms` n'est pas au-dessus de la CS (pas d'épuisement de D′)."""
    if not fit or not fit.get("valid") or speed_ms is None or speed_ms <= fit["cs_ms"]:
        return None
    return fit["d_prime_m"] / (speed_ms - fit["cs_ms"])


# ---------------------------------------------------------------------------
# Tendance
# ---------------------------------------------------------------------------


def cs_trend(activity_curves: Sequence[dict], today: date, *, days: int = TREND_DEFAULT_DAYS,
             step_days: int = TREND_STEP_DAYS, window_days: int = TREND_WINDOW_DAYS) -> List[dict]:
    """Un ajustement CS/D′ tous les `step_days` jours (du plus ancien au plus récent, le dernier à
    `today`), chacun sur le meilleur de `window_days` jours se terminant à ce point."""
    points = []
    steps = max(0, days // step_days)
    for i in range(steps, -1, -1):
        end = today - timedelta(days=i * step_days)
        rows = best_of(activity_curves, end, window_days)
        fit = fit_cs(rows)
        points.append({"date": end.isoformat(), "status": fit["status"], "cs_ms": fit["cs_ms"],
                       "cs_pace_s_km": fit["cs_pace_s_km"], "d_prime_m": fit["d_prime_m"],
                       "r2": fit.get("r2"), "n_points": fit.get("n_points", 0),
                       "reason_code": fit["reason_code"], "reason": fit["reason"]})
    return points


# ---------------------------------------------------------------------------
# Contrôle de cohérence avec le seuil lactique Garmin
# ---------------------------------------------------------------------------


def compare_threshold(fit: Optional[dict], threshold_speed_ms: Optional[float]) -> dict:
    """Compare la CS à une vitesse au seuil lactique (m/s, fournie par l'appelant, jamais lue ici).
    Signale (`diverges`) un écart > `THRESHOLD_DIVERGENCE_PCT` % ; ne choisit jamais l'une des deux."""
    if threshold_speed_ms is None or threshold_speed_ms <= 0 or not math.isfinite(threshold_speed_ms):
        return {"available": False, "reason": "vitesse au seuil lactique non fournie"}
    lo, hi = LT_SPEED_PLAUSIBLE_MS
    if not lo <= threshold_speed_ms <= hi:
        return {"available": False,
                "reason": f"vitesse au seuil lactique {threshold_speed_ms:g} m/s hors de [{lo:g} ; {hi:g}] m/s : "
                          "unité probablement mal convertie, contrôle non effectué"}
    if not fit or not fit.get("valid"):
        return {"available": False, "reason": "CS non ajustable (voir le motif du refus)"}
    delta = (fit["cs_ms"] - threshold_speed_ms) / threshold_speed_ms * 100.0
    return {"available": True, "threshold_speed_ms": threshold_speed_ms, "cs_ms": fit["cs_ms"],
            "delta_pct": round(delta, 1), "diverges": abs(delta) > THRESHOLD_DIVERGENCE_PCT,
            "note": "écart signalé, aucune des deux valeurs n'est préférée : à discuter avec l'athlète"}


# ---------------------------------------------------------------------------
# Rapport complet
# ---------------------------------------------------------------------------


def build_report(activity_curves: Sequence[dict], today: date, *, days: int = TREND_DEFAULT_DAYS,
                 skipped_no_grade: int = 0, n_activities: Optional[int] = None) -> dict:
    """Courbes par fenêtre, ajustement CS/D′ par fenêtre, tendance. `days` : profondeur de la
    tendance ; les courbes de 42/90/365 j sont toujours rendues."""
    windows = []
    for w in CURVE_WINDOWS_DAYS:
        rows = best_of(activity_curves, today, w)
        windows.append({"window_days": w, "curve": rows, "fit": fit_cs(rows)})
    current = next((w["fit"] for w in windows if w["window_days"] == TREND_WINDOW_DAYS), None)
    return {
        "today": today.isoformat(),
        "n_activities": len(activity_curves) if n_activities is None else n_activities,
        "skipped_no_grade": skipped_no_grade,
        "durations_s": list(STANDARD_DURATIONS_S),
        "windows": windows,
        "current": current,
        "trend": cs_trend(activity_curves, today, days=days),
        "trend_window_days": TREND_WINDOW_DAYS,
        "reason": None if activity_curves else "aucune séance course avec échantillons FIT (altitude) indexée",
    }
