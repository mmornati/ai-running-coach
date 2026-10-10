"""Relation puissance ↔ fréquence cardiaque sur home trainer / vélo (stdlib, pur).

Sert à dire « quelle puissance tenez-vous dans votre zone 2 ? » à partir des
échantillons FIT de vos propres séances (`activity_sample.power_w` + `hr_bpm`),
jamais à partir d'une FTP Garmin recalculée sur une séance de récupération.

Méthode (approximation du projet) :

- fenêtres de ``WINDOW_S`` (5 min) glissantes par pas de ``STEP_S`` (1 min), après
  ``SKIP_S`` (10 min) d'échauffement ;
- FC de la fenêtre décalée de ``HR_LAG_S`` (60 s) : la FC suit la puissance avec
  retard ;
- une fenêtre n'est retenue que si la puissance y est assez régulière
  (écart-type ≤ ``MAX_CV`` × moyenne), moyenne ≥ 40 W, et que FC et puissance
  couvrent ≥ 80 % de la fenêtre ;
- régression linéaire P = a + b·FC sur toutes les fenêtres retenues ; refus
  explicite sous ``MIN_WINDOWS`` fenêtres ou si la FC ne varie pas.

La relation bouge avec la forme, la chaleur et la fatigue : c'est une moyenne sur
la période, et la FC reste la consigne pendant la séance.
"""

from __future__ import annotations

import math
import statistics as st
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

WINDOW_S = 300
STEP_S = 60
HR_LAG_S = 60
SKIP_S = 600
MAX_CV = 0.35
MIN_POWER_W = 40.0
MIN_COVERAGE = 0.8
MIN_WINDOWS = 30
# Sports dont les échantillons de puissance alimentent la calibration.
POWER_SPORTS = ("home_trainer", "indoor_cycling", "cycling")

ASSUMPTIONS = {
    "method": f"Fenêtres de {WINDOW_S} s, pas de {STEP_S} s, après {SKIP_S} s ; FC décalée de {HR_LAG_S} s ; "
              f"puissance régulière (écart-type ≤ {MAX_CV:.0%} de la moyenne, moyenne ≥ {MIN_POWER_W:.0f} W) ; "
              f"régression P = a + b·FC ; refus sous {MIN_WINDOWS} fenêtres.",
    "zones": "Puissance d'une zone = droite évaluée aux bornes de la zone FC du profil ; « extrapolated » "
             "quand la zone sort de la plage de FC observée (moins fiable).",
}


def _series(samples: Sequence[dict], key: str) -> Dict[int, float]:
    """`{t_s arrondi: valeur}` des échantillons où la clé est mesurée."""
    out = {}
    for s in samples:
        t, v = s.get("t_s"), s.get(key)
        if t is not None and v is not None:
            out[int(t)] = float(v)
    return out


def _window_mean(series: Dict[int, float], start: float, end: float, step: float) -> Optional[float]:
    vals = [v for t, v in series.items() if start <= t < end]
    if not vals or len(vals) * step < MIN_COVERAGE * (end - start):
        return None
    return math.fsum(vals) / len(vals)


def windows(samples: Sequence[dict], step_s: float = 5.0) -> List[Tuple[float, float]]:
    """(FC moyenne, puissance moyenne) de chaque fenêtre stable d'une séance.
    `step_s` = résolution des échantillons (5 s dans l'index)."""
    power = _series(samples, "power_w")
    hr = _series(samples, "hr_bpm")
    if not power or not hr:
        return []
    end_t = max(power)
    out = []
    t = SKIP_S
    while t + WINDOW_S + HR_LAG_S <= end_t + step_s:
        pw = [v for k, v in power.items() if t <= k < t + WINDOW_S]
        mean_p = math.fsum(pw) / len(pw) if pw else 0.0
        if (pw and len(pw) * step_s >= MIN_COVERAGE * WINDOW_S and mean_p >= MIN_POWER_W
                and st.pstdev(pw) <= MAX_CV * mean_p):
            mean_hr = _window_mean(hr, t + HR_LAG_S, t + HR_LAG_S + WINDOW_S, step_s)
            if mean_hr is not None:
                out.append((mean_hr, mean_p))
        t += STEP_S
    return out


def fit(points: Iterable[Tuple[float, float]]) -> Optional[dict]:
    """Régression P = a + b·FC, ou None (trop peu de fenêtres, FC constante, pente ≤ 0)."""
    pts = list(points)
    if len(pts) < MIN_WINDOWS:
        return None
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    mx, my = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = math.fsum((x - mx) * (y - my) for x, y in pts) / sxx
    if slope <= 0:
        return None
    icpt = my - slope * mx
    resid = st.pstdev([y - (icpt + slope * x) for x, y in pts])
    return {"intercept_w": round(icpt, 1), "slope_w_per_bpm": round(slope, 3),
            "resid_sd_w": round(resid, 1), "windows": len(pts),
            "hr_range_bpm": [round(min(xs)), round(max(xs))]}


def power_at(fitted: dict, hr_bpm: float) -> float:
    return fitted["intercept_w"] + fitted["slope_w_per_bpm"] * hr_bpm


def zone_power(fitted: dict, bounds_bpm: Optional[Sequence[float]]) -> List[dict]:
    """Puissance par zone FC du profil (`bounds_bpm` = bornes de `arc_metrics.hr_zone_resolution`)."""
    if not fitted or not bounds_bpm or len(bounds_bpm) < 2:
        return []
    lo_obs, hi_obs = fitted["hr_range_bpm"]
    out = []
    for i in range(len(bounds_bpm) - 1):
        lo, hi = float(bounds_bpm[i]), float(bounds_bpm[i + 1])
        if hi <= 0 or hi <= lo:
            continue
        p_lo, p_hi = max(power_at(fitted, lo), 0.0), max(power_at(fitted, hi), 0.0)
        out.append({"zone": i + 1, "bounds_bpm": [round(lo), round(hi)],
                    "power_w": [round(p_lo), round(p_hi)],
                    "extrapolated": lo < lo_obs or hi > hi_obs})
    return out


def calibrate(sessions: Sequence[dict], bounds_bpm: Optional[Sequence[float]] = None,
              step_s: float = 5.0) -> dict:
    """`sessions` : `[{"ref", "date", "sport", "samples": [...]}]` → calibration complète.

    Statuts : ``ok``, ``no_power_samples`` (aucune séance avec puissance + FC),
    ``insufficient_data`` (moins de ``MIN_WINDOWS`` fenêtres ou relation non exploitable).
    """
    used, pts = [], []
    for s in sessions:
        w = windows(s.get("samples") or [], step_s)
        p = [r.get("power_w") for r in s.get("samples") or [] if r.get("power_w") is not None]
        if not p:
            continue
        pts.extend(w)
        used.append({"ref": s.get("ref"), "date": s.get("date"), "sport": s.get("sport"),
                     "windows": len(w), "avg_power_w": round(math.fsum(p) / len(p))})
    out: dict = {"sessions": used, "assumptions": ASSUMPTIONS}
    if not used:
        return {**out, "status": "no_power_samples", "fit": None, "zones": [],
                "reason": "aucune séance vélo/home trainer avec puissance et FC dans les échantillons FIT"}
    fitted = fit(pts)
    if fitted is None:
        return {**out, "status": "insufficient_data", "fit": None, "zones": [],
                "reason": f"{len(pts)} fenêtre(s) stable(s) (minimum {MIN_WINDOWS}) ou FC sans variation exploitable"}
    return {**out, "status": "ok", "fit": fitted, "zones": zone_power(fitted, bounds_bpm)}
