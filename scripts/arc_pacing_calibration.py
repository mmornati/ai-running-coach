#!/usr/bin/env python3
"""Recalibrage des coefficients de pacing au débrief de course (#188, épopée #170).

## Pourquoi

`arc_race_pacing.py` applique des coefficients par défaut (pénalité de nuit, technicité du
terrain, chaleur, altitude) qui sont des HYPOTHÈSES du projet. Au débrief d'une course
(`arc_race_debrief.py`), on connaît l'écart réel plan/réalisé par segment : ce module en tire,
pour chaque facteur, l'erreur qui lui est ATTRIBUABLE, et PROPOSE des coefficients personnels.
Rien n'est appliqué seul : `[pacing.personal]` (`arc_pacing_personal.py`) n'est écrit qu'après
confirmation explicite de l'athlète.

## Méthode (voir `ASSUMPTIONS`)

1. **Ratio par segment** `réalisé / prévu` (temps), segments `resolution: "high"` seulement, sans
   ravito dans le segment (l'arrêt ravito, prévu ou réel, bruiterait le ratio).
2. **Contraste stratifié** : pour un facteur, on compare les segments EXPOSÉS (nuit, terrain
   technique, altitude) aux segments de RÉFÉRENCE (jour, terrain roulant, basse altitude) DANS la
   même cellule de stratification (les autres facteurs sont figés : on ne compare jamais une
   section de nuit technique à une section de jour roulante). Estimateur : rapport des médianes
   pondérées par le temps prévu — simple et robuste, pas de régression sur-ajustée. Le biais
   commun (allure de base, durabilité) disparaît du rapport puisque exposés et référence le
   partagent.
3. **Contrôle de la fatigue** : la référence est restreinte à une fenêtre de position de course
   autour des segments exposés (`POSITION_MARGIN`), pour ne pas confondre « de nuit » et « tard
   dans la course ».
4. **Refus explicite** : trop peu de segments (`MIN_GROUP_N` par groupe et par cellule), facteur
   confondu (aucune cellule où exposés ET référence coexistent), écart noyé dans le bruit.
   Un facteur refusé dit POURQUOI, jamais une valeur par défaut déguisée.
5. **Attrition vers le défaut** : `nouveau = défaut + w × (observé − défaut)`, `w = n / (n + K)`
   (n = segments exposés cumulés sur les débriefs, K = `SHRINKAGE_K_SEGMENTS`).
6. **Cumul** : une preuve par (course, facteur) est conservée dans `[pacing.personal].evidence` ;
   les débriefs successifs COMBINENT leurs preuves (moyenne pondérée par n), n'écrasent rien, et
   rejouer un débrief remplace sa propre preuve au lieu de la compter deux fois.

La chaleur est un facteur UNIQUE pour toute la course (`heat_factor` du plan) : aucun contraste
intra-course n'est possible. Elle ne s'estime qu'ENTRE courses : une course chaude contre une
course sans correction météo, par leur biais de base (référence) respectif.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_heat as H  # noqa: E402
import arc_pacing_personal as PP  # noqa: E402
import arc_race_pacing as RP  # noqa: E402

# --- Constantes (approximations du projet, voir ASSUMPTIONS) ---------------------------------
MIN_GROUP_N = 4                  # segments minimum par groupe (exposé ET référence) et par cellule
SHRINKAGE_K_SEGMENTS = 20        # K de n/(n+K) pour les facteurs estimés par segments
HEAT_SHRINKAGE_K_RACES = 2       # idem pour la chaleur, n = nombre de courses
POSITION_MARGIN = 0.15           # fenêtre de position (fraction de la distance) autour de l'exposition
POSITION_GAP_MAX = 0.15          # écart de position moyenne exposés/référence au-delà duquel la confiance est « faible »
ABNORMAL_FADE_RATIO = 1.5        # dernier quart / première moitié (médianes) : fin de course anormale -> refus
HEAT_MIN_HOT_RACES = 2           # courses chaudes débriefées minimum avant TOUTE proposition de chaleur
NIGHT_MIN_FRACTION = 0.5         # section « de nuit » (même seuil que `night_error_summary`)
DAY_MAX_FRACTION = 0.05          # section « de jour »
TECH_EXPOSED_MIN = 0.05          # effective_factor - 1 >= 0.05 : technique
TECH_SMOOTH_MAX = 0.02           # |effective_factor - 1| <= 0.02 : roulant
ALT_EXPOSED_MIN = 0.02           # altitude_factor - 1 >= 0.02 : exposé
ALT_REF_MAX = 0.005              # altitude_factor - 1 <= 0.005 : référence
DEADBAND = {"night_penalty_pct": 0.5, "technicity_scale": 0.05, "heat_hot_factor": 0.01,
            "altitude_scale": 0.05}
FACTORS = ("night", "technicity", "heat", "altitude")
FACTOR_KEY = {"night": "night_penalty_pct", "technicity": "technicity_scale",
              "heat": "heat_hot_factor", "altitude": "altitude_scale"}
DEFAULTS = {"night_penalty_pct": RP.NIGHT_BASE_PENALTY_PCT, "technicity_scale": 1.0,
            "heat_hot_factor": H.HEAT_HOT_TIME_FACTOR, "altitude_scale": 1.0}
# Altitude (#185) : `altitude_scale` multiplie le SURCOÛT (`altitude_factor` − 1) de chaque section
# dans `arc_race_pacing.apply_altitude_penalty` — exactement la grandeur estimée ici (rapport surcoût
# réel / surcoût prévu, ramené à l'échelle déjà utilisée par le plan, `pacing_personal`).
ALTITUDE_ENGINE_NOTE = ("`altitude_scale` multiplie le surcoût d'altitude (`altitude_factor` − 1) de chaque "
                        "section dans `arc_race_pacing.py` (#185) ; `--altitude-loss-pct` en ligne de "
                        "commande prime sur lui")

ASSUMPTIONS = {
    "method": (
        "Contraste stratifié par rapport des médianes pondérées (poids = temps prévu) des ratios "
        "réalisé/prévu : segments exposés vs segments de référence dans la MÊME cellule des autres "
        "facteurs (nuit/jour/crépuscule × roulant/technique/intermédiaire × basse/haute altitude), "
        "cellules combinées par la moyenne des log-ratios pondérée par le nombre de segments exposés. "
        "Le coefficient observé est la médiane pondérée des coefficients IMPLICITES de chaque segment "
        "exposé (son ratio rapporté à la médiane de référence de sa cellule). "
        "Choix délibéré d'une méthode simple plutôt qu'une régression multi-facteurs : avec quelques "
        "dizaines de segments corrélés (la nuit tombe tard dans la course, l'altitude est groupée), "
        "une régression sur-ajusterait. Approximation du projet, aucune littérature vérifiable ne "
        "fixe ces seuils."
    ),
    "thresholds": (
        f"Groupe minimal {MIN_GROUP_N} segments par groupe et par cellule ; nuit >= "
        f"{NIGHT_MIN_FRACTION:g} de fraction de nuit, jour <= {DAY_MAX_FRACTION:g} ; technique : "
        f"effective_factor >= {1 + TECH_EXPOSED_MIN:g}, roulant : |écart| <= {TECH_SMOOTH_MAX:g} ; "
        f"altitude : facteur >= {1 + ALT_EXPOSED_MIN:g} contre <= {1 + ALT_REF_MAX:g} ; fenêtre de "
        f"position +/- {POSITION_MARGIN:g} de la distance autour des segments exposés. Approximations "
        "du projet."
    ),
    "fatigue": (
        "La fenêtre de position limite la confusion « de nuit » / « tard dans la course » sans "
        "l'annuler : quand la nuit (ou le terrain technique) occupe la FIN de la course, toute la "
        "référence est plus tôt, et un reste de fatigue que le modèle de durabilité n'a pas prévu "
        "gonflerait la pénalité. L'écart de position moyenne exposés/référence (`position_gap`, "
        f"fraction de la distance) est donc publié ; au-delà de {POSITION_GAP_MAX:g}, la confiance est "
        "plafonnée à « faible ». Aucune correction de tendance n'est tentée (elle extrapolerait hors "
        "de la référence)."
    ),
    "outlier_race": (
        "Course anormale (blessure, fin de course marchée, longue pause hors ravito) : si la médiane "
        "des ratios réalisé/prévu du dernier quart dépasse "
        f"{ABNORMAL_FADE_RATIO:g} x celle de la première moitié, AUCUN facteur n'est estimé (refus "
        "`abnormal_fade`). `--exclude-from-km KM` écarte les segments au-delà d'un km (incident "
        "connu de l'athlète) ; une défaillance plus douce que ce seuil n'est PAS détectée : c'est à "
        "l'athlète de la signaler avant d'accepter une proposition. Seuil : approximation du projet."
    ),
    "shrinkage": (
        f"nouveau = défaut + w x (observé - défaut), w = n / (n + K), K = {SHRINKAGE_K_SEGMENTS} segments "
        f"exposés (chaleur : {HEAT_SHRINKAGE_K_RACES} courses). Approximation du projet : un "
        "seul débrief ne déplace donc jamais le coefficient jusqu'à l'observation brute. Bornes "
        "dures par coefficient (`arc_pacing_personal.BOUNDS`)."
    ),
    "confidence": (
        "Confiance = nombre de segments (>= 8 exposés ET référence : haute ; >= 5 : moyenne ; sinon "
        "faible) ET écart > 2x son erreur-type (médiane robuste : 1,2533 x 1,4826 x MAD / racine de n, "
        "formule asymptotique qui SOUS-estime l'erreur sur 4 à 8 segments) pour « haute ». Un écart "
        "inférieur à son erreur-type est « inconclusif » : aucune proposition issue de CE débrief, mais "
        "sa preuve est conservée (sans quoi seules les courses à gros écart seraient cumulées, ce qui "
        "biaiserait le cumul loin du défaut). Le seuil d'une erreur-type est volontairement permissif : "
        "l'attrition, la zone morte, les bornes et la confirmation de l'athlète bornent l'effet d'un "
        "faux positif."
    ),
    "heat": (
        "Un seul `heat_factor` pour toute la course : pas de contraste intra-course. Estimation "
        f"ENTRE courses (au moins {HEAT_MIN_HOT_RACES} chaudes et une sans correction météo avant "
        "toute proposition), par le biais de base de chacune "
        "(médiane des ratios jour/roulant/basse altitude). Ce biais mélange l'erreur de chaleur et "
        "l'erreur d'intensité de base propre à chaque course : confiance faible tant que peu de "
        "courses, d'où une attrition forte. La météo PRÉVUE n'est pas la météo RÉELLE : si la météo "
        "réelle est fournie et contredit la classe chaud/non chaud du plan, la chaleur est refusée."
    ),
    "limits": (
        "Hypothèses non vérifiables par ce module : les temps réels reflètent le terrain, la nuit et "
        "l'altitude, mais aussi la forme du jour, les erreurs de GPS et de segmentation ; le baseline "
        "OSM de technicité (`--technicity-baseline`) n'est pas estimé, seule l'échelle du surcoût l'est ; "
        "la perte d'altitude n'est estimée que si le plan porte `altitude_factor`. " + ALTITUDE_ENGINE_NOTE + ". "
        "Nuit : la pénalité proposée est la pénalité de BASE (plat/montée) ; le supplément de "
        "descente du plan (`night_penalty_fraction`) est retranché de l'observé, pas ré-estimé."
    ),
}


# --- Statistiques robustes --------------------------------------------------------------------

def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    pairs = sorted(zip(values, weights))
    half = sum(w for _, w in pairs) / 2.0
    acc = 0.0
    for i, (v, w) in enumerate(pairs):
        acc += w
        if acc > half + 1e-12:
            return v
        if abs(acc - half) <= 1e-12:  # coupure exacte : moyenne des deux valeurs centrales
            return (v + pairs[i + 1][0]) / 2.0 if i + 1 < len(pairs) else v
    return pairs[-1][0]


def _log_se(rows: Sequence[dict]) -> float:
    """Erreur-type approchée de la médiane des log-ratios (MAD robuste)."""
    logs = [math.log(r["ratio"]) for r in rows]
    n = len(logs)
    if n < 2:
        return 0.0
    med = statistics.median(logs)
    mad = statistics.median([abs(x - med) for x in logs])
    return 1.2533 * 1.4826 * mad / math.sqrt(n)


# --- Lignes de segments -----------------------------------------------------------------------

def _scenario_value(obj, scenario: str) -> Optional[float]:
    """Valeur numérique d'un champ « par scénario » (objet) ou scalaire (`altitude_factor` #185)."""
    if isinstance(obj, dict):
        obj = obj.get(scenario)
    if isinstance(obj, bool) or not isinstance(obj, (int, float)) or not math.isfinite(obj):
        return None
    return float(obj)


def _night_parameters(plan: dict) -> Tuple[float, float]:
    """`(pénalité de base %, supplément de descente max %)` RÉELLEMENT utilisés par le plan :
    `night.parameters` s'il a été recopié, sinon `pacing_personal`, sinon les défauts."""
    params = (plan.get("night") or {}).get("parameters") if isinstance(plan.get("night"), dict) else None
    params = params if isinstance(params, dict) else {}
    personal = plan.get("pacing_personal") if isinstance(plan.get("pacing_personal"), dict) else {}
    base = params.get("base_penalty_pct", personal.get("night_penalty_pct", RP.NIGHT_BASE_PENALTY_PCT))
    dmax = params.get("descent_extra_max_pct", RP.NIGHT_DESCENT_EXTRA_MAX_PCT)
    return float(base), float(dmax)


def segment_rows(plan: dict, debrief: dict, scenario: str,
                 exclude_from_km: Optional[float] = None) -> Tuple[List[dict], dict]:
    """Une ligne par segment exploitable : ratio, poids, position et cellules d'exposition.
    Rend `(rows, meta)` ; `meta` dit ce que le plan porte (nuit, technicité, altitude) et combien de
    segments sont écartés (résolution basse, ravito, non atteints, au-delà de `exclude_from_km`)."""
    plan_segments = {s["id"]: s for s in plan.get("segments") or []}
    night_base, night_dmax = _night_parameters(plan)
    total_km = max((s["km_end"] for s in plan_segments.values()), default=0.0) or 1.0
    aid_kms = [a["km"] for a in plan.get("aid_stations") or [] if isinstance(a.get("km"), (int, float))]
    has = {"night": False, "technicity": False, "altitude": False}
    rows: List[dict] = []
    skipped = {"low_resolution": 0, "aid_station": 0, "not_comparable": 0, "excluded": 0}
    for entry in debrief.get("segments") or []:
        seg = plan_segments.get(entry["id"])
        if seg is None or entry.get("status") == "not_reached":
            skipped["not_comparable"] += 1
            continue
        frac = _scenario_value(seg.get("night_fraction"), scenario)
        nfac = _scenario_value(seg.get("night_factor"), scenario)
        tech = seg.get("technicity") if isinstance(seg.get("technicity"), dict) else None
        eff = tech.get("effective_factor") if tech else None
        eff = float(eff) if isinstance(eff, (int, float)) and not isinstance(eff, bool) else None
        alt = _scenario_value(seg.get("altitude_factor"), scenario)
        has["night"] |= frac is not None
        has["technicity"] |= eff is not None
        has["altitude"] |= alt is not None
        if exclude_from_km is not None and seg["km_end"] > exclude_from_km:
            skipped["excluded"] += 1
            continue
        if entry.get("resolution") != "high":
            skipped["low_resolution"] += 1
            continue
        planned, actual = entry.get("planned_time_s"), entry.get("actual_time_s")
        if not planned or not actual or planned <= 0 or actual <= 0:
            skipped["not_comparable"] += 1
            continue
        if any(seg["km_start"] < k <= seg["km_end"] for k in aid_kms):
            skipped["aid_station"] += 1
            continue
        if frac is None:
            night_cell = "day"
        elif frac >= NIGHT_MIN_FRACTION:
            night_cell = "night"
        elif frac <= DAY_MAX_FRACTION:
            night_cell = "day"
        else:
            night_cell = "twilight"
        if eff is None or abs(eff - 1.0) <= TECH_SMOOTH_MAX:
            tech_cell = "smooth"
        elif eff - 1.0 >= TECH_EXPOSED_MIN:
            tech_cell = "technical"
        else:
            tech_cell = "mid"
        if alt is None or alt - 1.0 <= ALT_REF_MAX:
            alt_cell = "low"
        elif alt - 1.0 >= ALT_EXPOSED_MIN:
            alt_cell = "high"
        else:
            alt_cell = "mid"
        # Supplément de descente (fraction) que le plan a ajouté à la pénalité de base : il n'est
        # pas à attribuer à la base (sinon double compte au plan suivant).
        grade = seg.get("grade_mean_pct")
        grade = float(grade) if isinstance(grade, (int, float)) and not isinstance(grade, bool) else None
        night_extra = (RP.night_penalty_fraction(grade, base_pct=night_base, descent_extra_max_pct=night_dmax)
                       - night_base / 100.0)
        rows.append({
            "id": seg["id"], "ratio": actual / planned, "weight": float(planned), "night_extra": night_extra,
            "pos": ((seg["km_start"] + seg["km_end"]) / 2.0) / total_km,
            "night_cell": night_cell, "tech_cell": tech_cell, "alt_cell": alt_cell,
            "night_fraction": frac, "night_factor": nfac, "eff": eff, "alt": alt,
        })
    return rows, {"has": has, "skipped": skipped, "usable_segments": len(rows)}


# --- Contraste stratifié ----------------------------------------------------------------------

def stratified_contrast(rows: Sequence[dict], is_exposed, is_ref, cell_of) -> dict:
    """Rapport des médianes pondérées exposés/référence par cellule, combiné entre cellules.
    Rend `n_exposed`/`n_reference` (totaux avant stratification), `cells` (utilisables),
    `ratio`, `se_pct`, et `refusal` (`None` | `no_exposure` | `too_few` | `confounded`)."""
    cells: Dict[tuple, dict] = {}
    n_exp = n_ref = 0
    for r in rows:
        if is_exposed(r):
            n_exp += 1
            cells.setdefault(cell_of(r), {"exp": [], "ref": []})["exp"].append(r)
        elif is_ref(r):
            n_ref += 1
            cells.setdefault(cell_of(r), {"exp": [], "ref": []})["ref"].append(r)
    out = {"n_exposed": n_exp, "n_reference": n_ref, "cells": [], "refusal": None}
    if n_exp == 0:
        out["refusal"] = "no_exposure"
        return out
    used = []
    for cell, g in sorted(cells.items(), key=lambda kv: str(kv[0])):
        if not g["exp"]:
            continue
        lo = min(r["pos"] for r in g["exp"]) - POSITION_MARGIN
        hi = max(r["pos"] for r in g["exp"]) + POSITION_MARGIN
        ref = [r for r in g["ref"] if lo <= r["pos"] <= hi]
        if len(g["exp"]) < MIN_GROUP_N or len(ref) < MIN_GROUP_N:
            continue
        ref_med = weighted_median([r["ratio"] for r in ref], [r["weight"] for r in ref])
        log_m = math.log(weighted_median([r["ratio"] for r in g["exp"]], [r["weight"] for r in g["exp"]]) / ref_med)
        se = math.hypot(_log_se(g["exp"]), _log_se(ref))
        gap = (sum(r["pos"] * r["weight"] for r in g["exp"]) / sum(r["weight"] for r in g["exp"])
               - sum(r["pos"] * r["weight"] for r in ref) / sum(r["weight"] for r in ref))
        used.append({"cell": "/".join(str(c) for c in cell) if isinstance(cell, tuple) else str(cell),
                     "n_exposed": len(g["exp"]), "n_reference": len(ref), "log_ratio": log_m, "se": se,
                     # ratio de chaque exposé RELATIF à la référence de sa cellule (estimation par segment)
                     "exposed": [dict(r, rel=r["ratio"] / ref_med) for r in g["exp"]], "gap": gap})
    if not used:
        out["refusal"] = "too_few" if (n_exp < MIN_GROUP_N or n_ref < MIN_GROUP_N) else "confounded"
        return out
    wsum = sum(c["n_exposed"] for c in used)
    log_ratio = sum(c["log_ratio"] * c["n_exposed"] for c in used) / wsum
    se = math.sqrt(sum((c["n_exposed"] * c["se"]) ** 2 for c in used)) / wsum
    exposed = [r for c in used for r in c["exposed"]]
    out.update({
        "ratio": math.exp(log_ratio), "se_pct": round((math.exp(se) - 1.0) * 100.0, 2),
        "_se": se, "n_used_exposed": wsum, "n_used_reference": sum(c["n_reference"] for c in used),
        "_exposed_rows": exposed,
        "position_gap": round(sum(c["gap"] * c["n_exposed"] for c in used) / wsum, 3),
        "cells": [{"cell": c["cell"], "n_exposed": c["n_exposed"], "n_reference": c["n_reference"],
                   "ratio": round(math.exp(c["log_ratio"]), 4)} for c in used],
    })
    return out


def _confidence(n_exp: int, n_ref: int, ratio: float, se: float) -> str:
    n = min(n_exp, n_ref)
    if n >= 8 and abs(math.log(ratio)) > 2.0 * se:
        return "high"
    return "medium" if n >= 5 else "low"


_REFUSAL_TEXT = {
    "no_exposure": "aucun segment exposé dans ce plan (rien à calibrer)",
    "too_few": f"trop peu de segments (minimum {MIN_GROUP_N} par groupe, exposés et référence)",
    "confounded": ("facteur confondu : les segments exposés ne coexistent avec aucun segment de référence "
                   "comparable (même nuit/technicité/altitude, même zone de la course) — les "
                   "séparer serait deviner"),
}


def _estimate_segment_factor(rows, factor: str, plan_personal: dict) -> dict:
    """Estimation par contraste pour `night`, `technicity` ou `altitude`. Rend un dict de statut
    `estimated | inconclusive | refused | not_applicable` avec ses chiffres."""
    if factor == "night":
        exposed = lambda r: r["night_cell"] == "night"                                  # noqa: E731
        ref = lambda r: r["night_cell"] == "day"                                        # noqa: E731
        cell_of = lambda r: (r["tech_cell"], r["alt_cell"])                             # noqa: E731
    elif factor == "technicity":
        exposed = lambda r: r["tech_cell"] == "technical"                               # noqa: E731
        ref = lambda r: r["tech_cell"] == "smooth"                                      # noqa: E731
        cell_of = lambda r: (r["night_cell"], r["alt_cell"])                            # noqa: E731
    else:
        exposed = lambda r: r["alt_cell"] == "high"                                     # noqa: E731
        ref = lambda r: r["alt_cell"] == "low"                                          # noqa: E731
        cell_of = lambda r: (r["night_cell"], r["tech_cell"])                           # noqa: E731
    c = stratified_contrast(rows, exposed, ref, cell_of)
    res: Dict[str, object] = {"factor": factor, "n_exposed": c["n_exposed"], "n_reference": c["n_reference"]}
    if c["refusal"]:
        res["status"] = "not_applicable" if c["refusal"] == "no_exposure" else "refused"
        res["reason"] = _REFUSAL_TEXT[c["refusal"]]
        res["refusal_code"] = c["refusal"]
        return res
    m, se = c["ratio"], c["_se"]
    res.update({"cells": c["cells"], "ratio": round(m, 4), "ratio_se_pct": c["se_pct"],
                "n_used_exposed": c["n_used_exposed"], "n_used_reference": c["n_used_reference"],
                "position_gap": c["position_gap"],
                "confidence": _confidence(c["n_used_exposed"], c["n_used_reference"], m, se)})
    if abs(c["position_gap"]) > POSITION_GAP_MAX:
        res["confidence"] = "low"
        res["position_note"] = (f"référence en moyenne {abs(c['position_gap']) * 100:.0f} % de la distance "
                                f"plus {'tôt' if c['position_gap'] > 0 else 'tard'} que les segments exposés : "
                                "une fatigue non prévue par la durabilité peut se mêler à l'écart")
    # Coefficient IMPLICITE de chaque segment exposé (son ratio rapporté à la référence de sa
    # cellule), puis médiane pondérée par le temps prévu : la même pondération que le contraste.
    # (Une moyenne des facteurs du plan combinée à une médiane des ratios mélangerait des segments
    # différents dès que le facteur varie avec la pente — biais mesuré en revue #188.)
    rows_e = c["_exposed_rows"]
    if factor == "night":
        rows_e = [r for r in rows_e if r["night_factor"] is not None and r["night_fraction"]]
        if not rows_e:
            res.update(status="refused", reason="plan sans night_factor : pénalité non reconstructible")
            return res
        # F_vrai ≈ F_plan × rel = 1 + f × (base + supplément de descente) : on ne garde que la base.
        implied = [(r["night_factor"] * r["rel"] - 1.0 - r["night_fraction"] * r["night_extra"])
                   / r["night_fraction"] * 100.0 for r in rows_e]
    else:
        key = "eff" if factor == "technicity" else "alt"
        rows_e = [r for r in rows_e if r.get(key) is not None and r[key] - 1.0 >= 1e-6]
        if not rows_e:
            res.update(status="refused", reason="facteur du plan sans surcoût exploitable")
            return res
        used = float(plan_personal.get("technicity_scale" if factor == "technicity" else "altitude_scale", 1.0))
        implied = [used * (r[key] * r["rel"] - 1.0) / (r[key] - 1.0) for r in rows_e]
    observed = weighted_median(implied, [r["weight"] for r in rows_e])
    lo, hi = PP.BOUNDS[FACTOR_KEY[factor]]
    res["observed"] = round(min(hi, max(lo, observed)), 4)
    if not (lo <= observed <= hi):
        res["observed_clamped_from"] = round(observed, 4)
    # La preuve est gardée même dans le bruit (voir ASSUMPTIONS["confidence"]) : seul le statut
    # dit si CE débrief justifie une proposition.
    res["evidence"] = (res["n_used_exposed"], res["observed"])
    if abs(math.log(m)) <= se:
        res["status"] = "inconclusive"
        res["reason"] = (f"écart exposés/référence ({(m - 1.0) * 100.0:+.1f} %) dans le bruit "
                         f"(erreur-type {c['se_pct']:.1f} %) : aucune proposition, preuve conservée")
        return res
    res["status"] = "estimated"
    return res


def _estimate_heat(plan: dict, rows: Sequence[dict], actual_weather: Optional[dict]) -> dict:
    """Preuve de chaleur de CETTE course : son biais de base (référence : jour/roulant/basse
    altitude), classée chaude ou neutre d'après les `heat_notes` du plan."""
    res: Dict[str, object] = {"factor": "heat"}
    kind = H.heat_kind(plan.get("heat_notes"))
    if kind is None:
        res.update(status="not_applicable", reason="plan sans `heat_notes` exploitables (météo prévue inconnue)")
        return res
    if kind == "cold":
        res.update(status="not_applicable", reason="course froide : le facteur de froid n'est pas calibré")
        return res
    if actual_weather and isinstance(actual_weather.get("temp_max_c"), (int, float)):
        actually_hot = actual_weather["temp_max_c"] > H.HEAT_HOT_C
        if actually_hot != (kind == "hot"):
            res.update(status="refused", reason="météo réelle (%.1f °C) contredit la classe chaud/non chaud du plan "
                       "(prévision) : le biais de base ne mesurerait pas la chaleur prévue"
                       % actual_weather["temp_max_c"])
            return res
    base = [r for r in rows if r["night_cell"] == "day" and r["tech_cell"] == "smooth" and r["alt_cell"] == "low"]
    res["n_reference"] = len(base)
    if len(base) < MIN_GROUP_N:
        res.update(status="refused",
                   reason=f"trop peu de segments de référence (jour/roulant/basse altitude : {len(base)} < "
                          f"{MIN_GROUP_N}) pour mesurer le biais de base de la course")
        return res
    r_base = weighted_median([r["ratio"] for r in base], [r["weight"] for r in base])
    res["base_ratio"] = round(r_base, 4)
    hot_used = float((plan.get("pacing_personal") or {}).get("heat_hot_factor", H.HEAT_HOT_TIME_FACTOR))
    res["status"] = "estimated"
    res["kind"] = kind
    if kind == "hot":
        res["evidence"] = (len(base), hot_used * r_base, "heat_hot")
    else:
        res["evidence"] = (len(base), r_base, "heat_neutral")
    res["confidence"] = "low"
    return res


# --- Accumulation -----------------------------------------------------------------------------

def _shrink(default: float, observed: float, n: float, k: float) -> Tuple[float, float]:
    w = n / (n + k)
    return default + w * (observed - default), w


def accumulate(evidence: Sequence[PP.Evidence]) -> Dict[str, dict]:
    """Coefficient proposé par facteur depuis TOUTES les preuves cumulées (`{clé: {...}}`),
    après attrition vers le défaut et bornes."""
    out: Dict[str, dict] = {}
    for factor in ("night", "technicity", "altitude"):
        recs = [r for r in evidence if r[2] == factor]
        if not recs:
            continue
        n = sum(r[3] for r in recs)
        observed = sum(r[3] * r[4] for r in recs) / n
        key = FACTOR_KEY[factor]
        value, w = _shrink(DEFAULTS[key], observed, n, SHRINKAGE_K_SEGMENTS)
        out[key] = {"observed": round(observed, 4), "n": n, "races": len(recs), "weight": round(w, 3),
                    "value": value}
    hot = [r for r in evidence if r[2] == "heat_hot"]
    neutral = [r for r in evidence if r[2] == "heat_neutral"]
    # Le biais de base d'une course mêle chaleur et intensité du jour : une seule course chaude ne
    # suffit jamais (ASSUMPTIONS["heat"]).
    if len(hot) >= HEAT_MIN_HOT_RACES and neutral:
        n_hot, n_neu = sum(r[3] for r in hot), sum(r[3] for r in neutral)
        observed = (sum(r[3] * r[4] for r in hot) / n_hot) / (sum(r[3] * r[4] for r in neutral) / n_neu)
        k_races = min(len(hot), len(neutral))
        value, w = _shrink(DEFAULTS["heat_hot_factor"], observed, k_races, HEAT_SHRINKAGE_K_RACES)
        out["heat_hot_factor"] = {"observed": round(observed, 4), "n": n_hot + n_neu, "races": len(hot) + len(neutral),
                                  "weight": round(w, 3), "value": value}
    for key, d in out.items():
        lo, hi = PP.BOUNDS[key]
        clamped = min(hi, max(lo, d["value"]))
        d["clamped"] = clamped != d["value"]
        d["value"] = round(clamped, 4)
    return out


def abnormal_fade(rows: Sequence[dict]) -> Optional[dict]:
    """Fin de course anormale (blessure, fin marchée) : médiane pondérée des ratios du dernier
    quart / celle de la première moitié >= `ABNORMAL_FADE_RATIO`. `None` si rien d'anormal ou trop
    peu de segments pour en juger (voir ASSUMPTIONS["outlier_race"])."""
    early = [r for r in rows if r["pos"] <= 0.5]
    late = [r for r in rows if r["pos"] >= 0.75]
    if len(early) < MIN_GROUP_N or len(late) < MIN_GROUP_N:
        return None
    ratio = (weighted_median([r["ratio"] for r in late], [r["weight"] for r in late])
             / weighted_median([r["ratio"] for r in early], [r["weight"] for r in early]))
    return {"late_over_early": round(ratio, 3)} if ratio >= ABNORMAL_FADE_RATIO else None


def calibrate(plan: dict, debrief: dict, *, scenario: str, existing: Optional[dict] = None,
              actual_weather: Optional[dict] = None, race_date: Optional[str] = None,
              exclude_from_km: Optional[float] = None) -> dict:
    """Rapport de calibration d'UN débrief combiné aux preuves déjà cumulées (`existing` =
    `arc_pacing_personal.read_config`). Pure : aucun accès disque. N'applique RIEN.
    `exclude_from_km` écarte les segments au-delà de ce km (incident déclaré par l'athlète)."""
    existing = existing or {"values": {}, "evidence": [], "warnings": []}
    rows, meta = segment_rows(plan, debrief, scenario, exclude_from_km=exclude_from_km)
    fade = abnormal_fade(rows)
    plan_personal = plan.get("pacing_personal") if isinstance(plan.get("pacing_personal"), dict) else {}
    date = race_date or plan.get("race_date") or debrief.get("race_date") or "0000-00-00"
    slug = PP.slugify(plan.get("race_name") or debrief.get("race_name"))
    factors: Dict[str, dict] = {}
    for f in ("night", "technicity", "altitude"):
        if fade is not None:
            factors[f] = {"factor": f, "status": "refused", "refusal_code": "abnormal_fade",
                          "reason": _abnormal_reason(fade)}
        elif f == "technicity" and not meta["has"]["technicity"]:
            factors[f] = {"factor": f, "status": "not_applicable", "n_exposed": 0, "n_reference": 0,
                          "reason": "plan construit sans technicité (--technicity) : rien à calibrer"}
        elif f == "night" and not meta["has"]["night"]:
            factors[f] = {"factor": f, "status": "not_applicable", "n_exposed": 0, "n_reference": 0,
                          "reason": "plan sans pénalité de nuit (aucun night_fraction) : rien à calibrer"}
        elif f == "altitude" and not meta["has"]["altitude"]:
            factors[f] = {"factor": f, "status": "not_applicable", "n_exposed": 0, "n_reference": 0,
                          "reason": "plan sans altitude_factor : rien à calibrer"}
        else:
            factors[f] = _estimate_segment_factor(rows, f, plan_personal)
    if fade is not None:
        factors["heat"] = {"factor": "heat", "status": "refused", "refusal_code": "abnormal_fade",
                           "reason": _abnormal_reason(fade)}
    else:
        factors["heat"] = _estimate_heat(plan, rows, actual_weather)

    new_records: List[PP.Evidence] = []
    for f, est in factors.items():
        if "evidence" not in est:
            continue
        ev = est.pop("evidence")
        factor_name = ev[2] if len(ev) == 3 else f
        new_records.append((str(date), slug, factor_name, int(ev[0]), float(ev[1])))
    merged = PP.merge_evidence(existing["evidence"], new_records)
    accumulated = accumulate(merged)
    current = {k: existing["values"].get(k, DEFAULTS[k]) for k in PP.KEYS}

    proposals: Dict[str, dict] = {}
    touched = {FACTOR_KEY[f] for f, e in factors.items() if e.get("status") == "estimated"}
    for key in sorted(touched):
        acc = accumulated.get(key)
        if acc is None:
            continue
        delta = acc["value"] - current[key]
        factor = next(f for f, k in FACTOR_KEY.items() if k == key)
        prop = {"current": round(current[key], 4), "default": DEFAULTS[key], "proposed": acc["value"],
                "observed_cumulated": acc["observed"], "weight": acc["weight"], "n": acc["n"],
                "races": acc["races"], "confidence": factors[factor].get("confidence", "low"),
                "bounds": list(PP.BOUNDS[key])}
        if acc["clamped"]:
            prop["clamped"] = True
        if abs(delta) < DEADBAND[key]:
            prop["status"] = "no_change"
            prop["proposed"] = round(current[key], 4)
        else:
            prop["status"] = "proposal"
        proposals[key] = prop

    # Un facteur « estimé » sans accumulation possible (chaleur : il manque une course de
    # comparaison) l'explique au lieu de se taire.
    if factors["heat"].get("status") == "estimated" and "heat_hot_factor" not in proposals:
        factors["heat"]["note"] = (f"preuve enregistrée ; il faut au moins {HEAT_MIN_HOT_RACES} courses chaudes "
                                   "ET une course sans correction météo débriefées pour estimer le facteur chaud")

    to_write = {k: p["proposed"] for k, p in proposals.items() if p["status"] == "proposal"}
    report = {
        "race": {"name": plan.get("race_name") or debrief.get("race_name"), "date": date, "scenario": scenario},
        "segments": {"usable": meta["usable_segments"], "skipped": meta["skipped"],
                     **({"exclude_from_km": exclude_from_km} if exclude_from_km is not None else {}),
                     **({"abnormal_fade": fade} if fade is not None else {})},
        "factors": {f: _public(e) for f, e in factors.items()},
        "proposals": proposals,
        "defaults": DEFAULTS,
        "current": {k: round(v, 4) for k, v in current.items()},
        "evidence": [PP.format_evidence(r) for r in merged],
        "config_patch": {"section": PP.SECTION, "values": to_write,
                         "evidence": [PP.format_evidence(r) for r in merged] if new_records else []},
        "applied": False,
        "warnings": list(existing.get("warnings") or []),
        "assumptions": ASSUMPTIONS,
    }
    return report


def _abnormal_reason(fade: dict) -> str:
    return (f"fin de course anormale (dernier quart {fade['late_over_early']:g} x plus lent, par rapport au "
            "plan, que la première moitié : blessure, fin marchée ?) — l'écart ne mesure plus les "
            "facteurs ; relancer avec --exclude-from-km KM pour ne garder que la partie normale")


def _public(est: dict) -> dict:
    return {k: v for k, v in est.items() if not k.startswith("_")}


def select_scenario(plan: dict, debrief_for: "callable") -> Tuple[str, dict]:
    """Scénario dont le temps total prévu est le plus proche du réalisé (`--scenario auto`)."""
    best = None
    for scenario in RP.SCENARIOS:
        d = debrief_for(scenario)
        tot = d.get("totals") or {}
        if tot.get("planned_time_s") and tot.get("actual_time_s"):
            gap = abs(math.log(tot["actual_time_s"] / tot["planned_time_s"]))
        else:
            gap = float("inf")
        if best is None or gap < best[0]:
            best = (gap, scenario, d)
    return best[1], best[2]


def render_text(report: dict) -> str:
    lines = [f"Recalibrage des coefficients — {report['race'].get('name')} ({report['race'].get('date')}, "
             f"scénario {report['race']['scenario']})",
             f"Segments exploitables : {report['segments']['usable']} (écartés : "
             + ", ".join(f"{k} {v}" for k, v in report["segments"]["skipped"].items()) + ")", ""]
    for f, e in report["factors"].items():
        head = f"- {f} : {e['status']}"
        if "ratio" in e:
            head += (f" — ratio exposés/référence {e['ratio']} (± {e['ratio_se_pct']} %, "
                     f"n = {e['n_used_exposed']}/{e['n_used_reference']}, confiance {e['confidence']})")
        lines.append(head)
        if e.get("reason"):
            lines.append(f"    raison : {e['reason']}")
        if e.get("note"):
            lines.append(f"    note : {e['note']}")
        if e.get("position_note"):
            lines.append(f"    position : {e['position_note']}")
    lines.append("")
    if report["proposals"]:
        lines.append("Propositions (jamais appliquées seules, confirmation de l'athlète requise) :")
        for key, p in report["proposals"].items():
            lines.append(f"- {key} : {p['current']} -> {p['proposed']} ({p['status']}, défaut {p['default']}, "
                         f"observé cumulé {p['observed_cumulated']}, poids {p['weight']}, n = {p['n']}, "
                         f"confiance {p['confidence']})")
    else:
        lines.append("Aucune proposition.")
    for w in report["warnings"]:
        lines.append(f"avertissement : {w}")
    if report["applied"]:
        lines.append(f"ÉCRIT dans {report['applied_path']}")
    return "\n".join(lines)
