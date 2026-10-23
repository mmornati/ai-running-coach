#!/usr/bin/env python3
"""Profil d'usage par paire de chaussures (#300, épopée #297) — fonctions **pures**.

Aucun SQLite, aucun accès disque : la lecture en base est faite par
`scripts/arc_index.py::shoe_usage`, qui rassemble les séances DÉJÀ attribuées à chaque paire par la règle
unique `arc_metrics.attribute_gear` (les mêmes que le kilométrage), les valeurs de foulée, la météo, les
douleurs et les inspections, et les passe ici. Rien n'est écrit, rien n'est stocké : tout est calculé à la
lecture.

Ce que dit le rapport, par paire : terrain (route/trail), D+/km et D−/km, distribution des distances, part de
sorties longues, courses, allure et GAP moyennes, part de séances humides, période ; foulée **par tranche
d'allure** ; épisodes de douleur dans les 48 h suivant une séance avec la paire, rapportés à l'exposition ;
séances sans paire ; rôle déduit (entrée de la story #301).

Tout seuil ci-dessous est une **approximation du projet**, pas un seuil cité d'une source. Aucune corrélation
douleur ↔ paire n'est une causalité.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import arc_gait as GT
from arc_decision_effects import MIN_SAMPLE_FOR_TREND

RUNNING_SPORTS = ("running", "trail")
ROAD_SPORT = "running"
TRAIL_SPORT = "trail"

LONG_RUN_S = 90 * 60            # « sortie longue » : strictement plus de 90 min (énoncé de la story #300)
WET_PRECIP_MM = 1.0             # séance « humide » : cumul de pluie du jour >= 1 mm (approximation du projet)
DISTANCE_BUCKETS_KM = (5.0, 10.0, 15.0, 21.0, 30.0)    # bornes hautes exclues ; dernier seau : >= 30 km

PACE_BAND_S_KM = 30             # largeur d'une tranche d'allure (approximation du projet), ancrée sur des multiples de 30 s/km
MIN_BAND_SESSIONS = 3           # séances mini par tranche et par paire (et par grandeur), sinon « données insuffisantes »

PAIN_WINDOW_DAYS = 2            # « <= 48 h » à la granularité du jour : douleur datée de 0 à 2 jours après la séance
PAIN_MIN_CASES = MIN_SAMPLE_FOR_TREND    # même seuil que `decision-effects` : sous 5 épisodes, pas de taux

ROLE_MIN_SESSIONS = 5           # séances mini pour déduire un rôle (hors « course »)
ROLE_TERRAIN_SHARE = 0.70       # part de km sur un terrain pour parler de paire route / trail
ROLE_LONG_SHARE = 0.25          # part de sorties longues (séances) pour « trail_long »
ROLE_RACE_SHARE = 0.50          # part de séances de course pour « race »
ROLE_RACE_MIN_SESSIONS = 2
ROLE_TEMPO_FASTER = 0.05        # allure moyenne >= 5 % plus rapide que la moyenne route de l'athlète pour « road_tempo »

ROLES_FR = {
    "race": "course", "trail_long": "trail, sorties longues", "trail": "trail", "road_tempo": "route, allure soutenue",
    "road_easy": "route, allure facile", "mixed_long": "mixte, sorties longues", "mixed": "mixte", "insufficient_data": "données insuffisantes",
}

CAVEAT = ("Corrélation, pas causalité : un épisode de douleur dans les 48 h suivant une séance n'est jamais "
          "attribué à la paire. Aucun diagnostic ; ce n'est pas un avis médical.")

ASSUMPTIONS = {
    "attribution": "Mêmes séances que le kilométrage (`arc_metrics.attribute_gear`) : jamais une seconde règle.",
    "terrain": "`running` = route, `trail` = trail, `hiking` compté à part (`other`). Les parts sont en km et en séances.",
    "elevation": "D+/km et D−/km : somme du dénivelé sur la somme des km des seules séances qui portent la grandeur "
                 "(couverture exposée : `elevation_sessions`, `elevation_distance_m`).",
    "long_run": f"Sortie longue = durée > {LONG_RUN_S // 60} min (durée totale, à défaut temps en mouvement).",
    "wet": f"Séance humide = cumul de pluie `precip_mm` >= {WET_PRECIP_MM:g} mm dans le fichier météo du jour "
           "(prévision enregistrée par le coach, pas une observation) ; part calculée sur les seules séances "
           "ayant une météo du jour.",
    "pace": "Allure moyenne = temps / distance (temps en mouvement, à défaut durée totale). GAP moyen = moyenne "
            "pondérée par la distance des séances qui portent `gap_pace_s_km`.",
    "gait_bands": f"Foulée comparée par tranche d'allure de {PACE_BAND_S_KM} s/km (tranches ancrées sur des multiples "
                  f"de {PACE_BAND_S_KM}), sur l'allure GAP de la séance si elle existe, sinon l'allure brute : les "
                  "deux bases ne sont jamais mélangées dans une même tranche. Moyenne simple des moyennes de séance "
                  f"(`arc_gait.resolve_session`). Minimum {MIN_BAND_SESSIONS} séances par tranche ET par grandeur, "
                  "sinon « données insuffisantes ». Deux paires ne sont comparées que dans la MÊME tranche. "
                  "Limite : la valeur d'une séance est la moyenne de TOUTE la séance (intervalles, marche, "
                  "échauffement compris) : approximation du projet, sensible aux séances à intervalles ou avec marche.",
    "pain": f"Épisode = une zone douloureuse (`health.pain`, score > 0) ; jours consécutifs d'une même zone fusionnés. "
            f"Rattaché à la séance de course la plus récente datée de 0 à {PAIN_WINDOW_DAYS} jours avant le début "
            "de l'épisode (même jour compris : l'heure de la douleur est inconnue ; en jours entiers, « 48 h » couvre en pratique "
            "jusqu'à environ 72 h). Taux par 100 km et par 100 "
            f"séances, seulement à partir de {PAIN_MIN_CASES} épisodes (même seuil que `decision-effects`) ; en "
            "dessous, comptes bruts et exposition, sans taux ni tendance. Épisode `ambiguous` : plusieurs paires "
            "(ou une séance sans paire) dans la fenêtre.",
    "unassigned": "Séances de course SANS `gear_id` sur la période d'usage de la paire (de sa première séance à "
                  "aujourd'hui pour une paire active, à sa dernière séance pour une paire retirée : la date de "
                  "retraite n'est pas stockée) : comptées et signalées, dont celles postérieures à sa dernière "
                  "séance (`since_last_attributed_run`). "
                  "Celles que la règle de la paire par défaut crédite à la paire sont comptées à part "
                  "(`default_attributed_runs`) : c'est une hypothèse, pas une déclaration.",
    "role": f"Règles dans l'ordre, sur les séances de course à pied : `race` si >= {ROLE_RACE_MIN_SESSIONS} séances et "
            f">= {ROLE_RACE_SHARE:.0%} de courses ; sinon `insufficient_data` sous {ROLE_MIN_SESSIONS} séances ; "
            f"`trail_long` si >= {ROLE_TERRAIN_SHARE:.0%} des km en trail et >= {ROLE_LONG_SHARE:.0%} de sorties "
            f"longues ; `trail` si >= {ROLE_TERRAIN_SHARE:.0%} des km en trail ; `road_tempo` si >= "
            f"{ROLE_TERRAIN_SHARE:.0%} des km sur route et allure moyenne >= {ROLE_TEMPO_FASTER:.0%} plus rapide "
            "que la moyenne route de l'athlète (toutes paires) ; `road_easy` si >= "
            f"{ROLE_TERRAIN_SHARE:.0%} sur route ; `mixed_long` si aucun terrain n'atteint {ROLE_TERRAIN_SHARE:.0%} "
            f"mais >= {ROLE_LONG_SHARE:.0%} de sorties longues (paire polyvalente des longues) ; sinon `mixed`. Approximation du projet, jamais une prescription.",
}


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def _round(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(value, digits)


def _time_s(act: dict) -> Optional[float]:
    t = act.get("moving_duration_s") or act.get("duration_s")
    return float(t) if t else None


def _pace_s_km(act: dict) -> Optional[float]:
    t, d = _time_s(act), act.get("distance_m")
    return t / (d / 1000.0) if t and d else None


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def pace_band(pace_s_km: float) -> Tuple[int, int]:
    """Tranche d'allure [lo, hi) en s/km, ancrée sur des multiples de `PACE_BAND_S_KM`."""
    lo = int(pace_s_km // PACE_BAND_S_KM) * PACE_BAND_S_KM
    return lo, lo + PACE_BAND_S_KM


def band_label(lo: int, hi: int) -> str:
    return f"{_clock(lo)}–{_clock(hi)}/km"


def athlete_road_pace(acts_by_gear: Dict[str, List[dict]]) -> Optional[float]:
    """Allure moyenne route de l'athlète sur TOUTES les paires (référence de `road_tempo`)."""
    time_s = dist_km = 0.0
    for acts in acts_by_gear.values():
        for a in acts:
            if a.get("sport") == ROAD_SPORT and _time_s(a) and a.get("distance_m"):
                time_s += _time_s(a)
                dist_km += a["distance_m"] / 1000.0
    return time_s / dist_km if dist_km else None


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


def _bucket_of(km: float) -> int:
    for i, edge in enumerate(DISTANCE_BUCKETS_KM):
        if km < edge:
            return i
    return len(DISTANCE_BUCKETS_KM)


def _bucket_label(i: int) -> str:
    edges = DISTANCE_BUCKETS_KM
    if i == 0:
        return f"< {edges[0]:g} km"
    if i == len(edges):
        return f">= {edges[-1]:g} km"
    return f"{edges[i - 1]:g}–{edges[i]:g} km"


def usage_of(acts: Sequence[dict]) -> dict:
    """Usage d'une paire à partir de ses séances attribuées. Une grandeur sans donnée est omise."""
    n = len(acts)
    out: Dict[str, Any] = {"sessions": n, "distance_m": round(sum(a.get("distance_m") or 0 for a in acts))}
    if not n:
        return out
    km_total = sum(a.get("distance_m") or 0 for a in acts) / 1000.0
    terrain: Dict[str, dict] = {}
    for key, sports in (("road", (ROAD_SPORT,)), ("trail", (TRAIL_SPORT,))):
        mine = [a for a in acts if a.get("sport") in sports]
        km = sum(a.get("distance_m") or 0 for a in mine) / 1000.0
        terrain[key] = {"sessions": len(mine), "distance_m": round(km * 1000),
                        "share_km": _round(km / km_total, 3) if km_total else None,
                        "share_sessions": _round(len(mine) / n, 3)}
    other = [a for a in acts if a.get("sport") not in RUNNING_SPORTS]
    if other:
        terrain["other"] = {"sessions": len(other),
                            "distance_m": round(sum(a.get("distance_m") or 0 for a in other))}
    out["terrain"] = terrain

    def per_km(field: str) -> Optional[float]:
        have = [a for a in acts if a.get(field) is not None and a.get("distance_m")]
        km = sum(a["distance_m"] for a in have) / 1000.0
        return _round(sum(a[field] for a in have) / km, 1) if km else None

    elev = [a for a in acts if a.get("elevation_gain_m") is not None and a.get("distance_m")]
    if elev:
        out["elevation_sessions"] = len(elev)
        out["elevation_distance_m"] = round(sum(a["distance_m"] for a in elev))
    for field, name in (("elevation_gain_m", "d_plus_m_per_km"), ("elevation_loss_m", "d_minus_m_per_km")):
        v = per_km(field)
        if v is not None:
            out[name] = v

    buckets = [{"label": _bucket_label(i), "sessions": 0} for i in range(len(DISTANCE_BUCKETS_KM) + 1)]
    for a in acts:
        if a.get("distance_m"):
            buckets[_bucket_of(a["distance_m"] / 1000.0)]["sessions"] += 1
    out["distance_distribution"] = buckets

    timed = [a for a in acts if _time_s(a) is not None]
    long_runs = [a for a in timed if (a.get("duration_s") or _time_s(a)) > LONG_RUN_S]
    if timed:
        out["long_runs"] = {"sessions": len(long_runs), "share_sessions": _round(len(long_runs) / len(timed), 3),
                            "threshold_s": LONG_RUN_S}
    races = [a for a in acts if a.get("is_race")]
    out["races"] = {"sessions": len(races), "distance_m": round(sum(a.get("distance_m") or 0 for a in races))}

    runs = [a for a in acts if a.get("sport") in RUNNING_SPORTS]
    time_s = sum(_time_s(a) for a in runs if _time_s(a) and a.get("distance_m"))
    dist_km = sum(a["distance_m"] for a in runs if _time_s(a) and a.get("distance_m")) / 1000.0
    if dist_km:
        out["mean_pace_s_km"] = round(time_s / dist_km)
    gap = [a for a in runs if a.get("gap_pace_s_km") and a.get("distance_m")]
    if gap:
        gap_km = sum(a["distance_m"] for a in gap) / 1000.0
        out["mean_gap_pace_s_km"] = round(sum(a["gap_pace_s_km"] * a["distance_m"] / 1000.0 for a in gap) / gap_km)
        out["gap_sessions"] = len(gap)

    weathered = [a for a in acts if a.get("precip_mm") is not None]
    if weathered:
        wet = [a for a in weathered if a["precip_mm"] >= WET_PRECIP_MM]
        out["wet"] = {"sessions": len(wet), "with_weather": len(weathered),
                      "share": _round(len(wet) / len(weathered), 3)}
    dates = sorted(a["date"] for a in acts if a.get("date"))
    if dates:
        span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1
        out["period"] = {"first_date": dates[0], "last_date": dates[-1], "days": span}
    return out


# ---------------------------------------------------------------------------
# Foulée à allure comparable
# ---------------------------------------------------------------------------


def _session_basis(act: dict) -> Optional[Tuple[str, float]]:
    if act.get("gap_pace_s_km"):
        return "gap", float(act["gap_pace_s_km"])
    pace = _pace_s_km(act)
    return ("pace", pace) if pace else None


def gait_bands(acts: Sequence[dict]) -> Dict[Tuple[str, int], dict]:
    """Par (base, borne basse) : séances de foulée mesurée de la paire dans la tranche d'allure.
    Chaque séance porte `gait` = {grandeur: valeur}. Les courses à pied seulement."""
    bands: Dict[Tuple[str, int], dict] = {}
    for a in acts:
        if a.get("sport") not in RUNNING_SPORTS or not a.get("gait"):
            continue
        basis = _session_basis(a)
        if basis is None:
            continue
        lo, hi = pace_band(basis[1])
        b = bands.setdefault((basis[0], lo), {"basis": basis[0], "lo": lo, "hi": hi, "sessions": []})
        b["sessions"].append(a["gait"])
    return bands


def _band_metrics(sessions: List[dict]) -> Dict[str, dict]:
    metrics: Dict[str, dict] = {}
    for m in GT.METRICS:
        vals = [s[m] for s in sessions if s.get(m) is not None]
        if len(vals) >= MIN_BAND_SESSIONS:
            metrics[m] = {"mean": round(sum(vals) / len(vals), 4), "n": len(vals)}
    return metrics


def gait_report(bands_by_gear: Dict[str, Dict[Tuple[str, int], dict]], names: Dict[str, str], gear_id: str) -> dict:
    """Foulée de `gear_id` par tranche d'allure, avec les autres paires de la MÊME tranche (jamais d'une autre)."""
    rows = []
    mine = bands_by_gear.get(gear_id, {})
    for key in sorted(mine, key=lambda k: (k[0], k[1])):
        b = mine[key]
        n = len(b["sessions"])
        row: Dict[str, Any] = {"basis": b["basis"], "band_lo_s_km": b["lo"], "band_hi_s_km": b["hi"],
                               "label": band_label(b["lo"], b["hi"]), "sessions": n, "min_sessions": MIN_BAND_SESSIONS}
        metrics = _band_metrics(b["sessions"]) if n >= MIN_BAND_SESSIONS else {}
        if metrics:
            row["status"] = "ok"
            row["metrics"] = metrics
            others = []
            for gid, theirs in bands_by_gear.items():
                if gid == gear_id or key not in theirs:
                    continue
                om = _band_metrics(theirs[key]["sessions"]) if len(theirs[key]["sessions"]) >= MIN_BAND_SESSIONS else {}
                if om:
                    others.append({"gear_id": gid, "name": names.get(gid), "sessions": len(theirs[key]["sessions"]),
                                   "metrics": om})
            if others:
                row["others"] = sorted(others, key=lambda o: o["gear_id"])
        else:
            row["status"] = "insufficient"
            row["reason"] = "données insuffisantes"
        rows.append(row)
    return {"bands": rows, "pace_band_s_km": PACE_BAND_S_KM, "min_sessions": MIN_BAND_SESSIONS,
            "sessions_with_gait": sum(len(b["sessions"]) for b in mine.values())}


# ---------------------------------------------------------------------------
# Douleurs
# ---------------------------------------------------------------------------


def pain_episodes(entries: Iterable[dict]) -> List[dict]:
    """`entries` : {date, location, score}. Épisodes = jours consécutifs d'une même zone (score > 0) fusionnés."""
    by_zone: Dict[str, List[dict]] = {}
    for e in entries:
        score = e.get("score")
        if not e.get("date") or not isinstance(score, (int, float)) or isinstance(score, bool) or score <= 0:
            continue
        by_zone.setdefault(str(e.get("location") or "").strip().casefold(), []).append(e)
    episodes = []
    for zone, items in by_zone.items():
        items.sort(key=lambda e: e["date"])
        current = None
        for e in items:
            day = date.fromisoformat(e["date"])
            if current and (day - current["_last"]).days <= 1:
                if day != current["_last"]:      # deux fichiers le même jour pour la même zone : un seul jour
                    current["days"] += 1
                current["_last"] = day
                current["score"] = max(current["score"], e["score"])
                continue
            current = {"date": e["date"], "location": e.get("location"), "score": e["score"], "days": 1, "_last": day}
            episodes.append(current)
    for ep in episodes:
        ep.pop("_last", None)
    return sorted(episodes, key=lambda ep: (ep["date"], ep["location"] or ""))


def link_episodes(episodes: Sequence[dict], runs: Sequence[dict], owner_of: Dict[Any, Optional[str]]) -> Tuple[Dict[str, List[dict]], int, int]:
    """Rattache chaque épisode à la séance de course la plus récente de la fenêtre. `runs` : {id, date};
    `owner_of[id]` : paire (ou None). Rend ({gear_id: [épisodes]}, sans_séance_dans_la_fenêtre, séance_sans_paire)."""
    dated = sorted((r for r in runs if r.get("date")), key=lambda r: (r["date"], r["id"]))
    per_gear: Dict[str, List[dict]] = {}
    no_run = no_pair = 0
    for ep in episodes:
        start = date.fromisoformat(ep["date"])
        window = [r for r in dated if 0 <= (start - date.fromisoformat(r["date"])).days <= PAIN_WINDOW_DAYS]
        if not window:
            no_run += 1
            continue
        owners = {owner_of.get(r["id"]) for r in window}
        paired = [r for r in window if owner_of.get(r["id"]) is not None]
        if not paired:
            no_pair += 1
            continue
        last = paired[-1]      # la plus récente séance AVEC paire ; ambiguë si la fenêtre contient autre chose
        per_gear.setdefault(owner_of[last["id"]], []).append(
            {**ep, "run_date": last["date"], "ambiguous": len(owners) > 1})
    return per_gear, no_run, no_pair


def pain_summary(episodes: Sequence[dict], sessions: int, distance_m: float, unassigned_runs: int,
                 no_run: int = 0, run_without_pair: int = 0) -> dict:
    km = distance_m / 1000.0
    n = len(episodes)
    out: Dict[str, Any] = {
        "episodes": n, "ambiguous_episodes": sum(1 for e in episodes if e.get("ambiguous")),
        "window_days": PAIN_WINDOW_DAYS,
        "exposure": {"sessions": sessions, "distance_m": round(distance_m)},
        "reliable": unassigned_runs == 0, "recent": list(episodes)[-5:],
        "unattributable_episodes": {"total": no_run + run_without_pair, "no_run_in_window": no_run,
                                    "run_without_pair": run_without_pair,
                                    "note": "épisodes de douleur (toutes paires) sans séance de course dans la "
                                            "fenêtre, ou dont les séances n'ont pas de paire : rattachés à aucune paire"},
        "note": CAVEAT,
    }
    if n >= PAIN_MIN_CASES and km > 0 and sessions:
        out["trend_allowed"] = True
        out["per_100km"] = round(n / km * 100.0, 2)
        out["per_100_sessions"] = round(n / sessions * 100.0, 2)
    else:
        out["trend_allowed"] = False
        out["warning"] = (f"effectif trop faible (n={n} < {PAIN_MIN_CASES}) : comptes bruts et exposition, "
                          "sans taux ni tendance")
    if unassigned_runs:
        out["warning_unassigned"] = (f"{unassigned_runs} séance(s) de course sans paire sur la période : le lien "
                                     "douleur ↔ paire n'est pas fiable")
    return out


# ---------------------------------------------------------------------------
# Rôle déduit
# ---------------------------------------------------------------------------


def deduce_role(usage: dict, road_pace_ref: Optional[float]) -> dict:
    """Rôle d'une paire d'après son usage (règles dans `ASSUMPTIONS["role"]`, ordre significatif)."""
    runs = ((usage.get("terrain") or {}).get("road", {}).get("sessions", 0)
            + (usage.get("terrain") or {}).get("trail", {}).get("sessions", 0))
    races = (usage.get("races") or {}).get("sessions", 0)
    road_km = (usage.get("terrain") or {}).get("road", {}).get("share_km") or 0.0
    trail_km = (usage.get("terrain") or {}).get("trail", {}).get("share_km") or 0.0
    # Parts calculées sur les seules courses à pied (la randonnée n'oriente pas un rôle de chaussure de course).
    road_m = (usage.get("terrain") or {}).get("road", {}).get("distance_m", 0)
    trail_m = (usage.get("terrain") or {}).get("trail", {}).get("distance_m", 0)
    run_m = road_m + trail_m
    road_share, trail_share = (road_m / run_m, trail_m / run_m) if run_m else (road_km, trail_km)
    long_share = (usage.get("long_runs") or {}).get("share_sessions") or 0.0
    pace = usage.get("mean_pace_s_km")
    basis = {"running_sessions": runs, "race_sessions": races, "road_share_km": _round(road_share, 3),
             "trail_share_km": _round(trail_share, 3), "long_run_share": _round(long_share, 3),
             "mean_pace_s_km": pace, "athlete_road_pace_s_km": _round(road_pace_ref, 0)}
    if races >= 1 and runs >= ROLE_RACE_MIN_SESSIONS and races / runs >= ROLE_RACE_SHARE:
        role, why = "race", f"{races} course(s) sur {runs} séances"
    elif runs < ROLE_MIN_SESSIONS:
        role, why = "insufficient_data", f"{runs} séance(s) de course à pied (< {ROLE_MIN_SESSIONS})"
    elif trail_share >= ROLE_TERRAIN_SHARE and long_share >= ROLE_LONG_SHARE:
        role, why = "trail_long", f"{trail_share:.0%} des km en trail, {long_share:.0%} de sorties longues"
    elif trail_share >= ROLE_TERRAIN_SHARE:
        role, why = "trail", f"{trail_share:.0%} des km en trail"
    elif road_share >= ROLE_TERRAIN_SHARE and pace and road_pace_ref and pace <= road_pace_ref * (1 - ROLE_TEMPO_FASTER):
        role, why = "road_tempo", (f"{road_share:.0%} des km sur route, allure moyenne {_clock(pace)}/km contre "
                                   f"{_clock(road_pace_ref)}/km pour l'ensemble des paires")
    elif road_share >= ROLE_TERRAIN_SHARE:
        role, why = "road_easy", f"{road_share:.0%} des km sur route, allure non soutenue"
    elif long_share >= ROLE_LONG_SHARE:
        role, why = "mixed_long", (f"route {road_share:.0%} / trail {trail_share:.0%} des km, "
                                   f"{long_share:.0%} de sorties longues")
    else:
        role, why = "mixed", f"route {road_share:.0%} / trail {trail_share:.0%} des km"
    return {"role": role, "label": ROLES_FR[role], "reason": why, "basis": basis,
            "note": "approximation du projet, déduite de l'usage ; jamais une prescription"}


# ---------------------------------------------------------------------------
# Rendu texte
# ---------------------------------------------------------------------------


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.0f} %"


def render_text(rep: dict) -> str:
    if rep.get("error"):
        return rep["error"]
    lines: List[str] = []
    for p in rep["pairs"]:
        title = p["gear_id"] + (f" — {p['name']}" if p.get("name") else "")
        u = p["usage"]
        lines.append(f"{title} : {u['sessions']} séance(s), {u['distance_m'] / 1000:.0f} km"
                     + (f", du {u['period']['first_date']} au {u['period']['last_date']}" if u.get("period") else ""))
        if not u["sessions"]:
            lines.append("  aucune séance attribuée")
            continue
        t = u["terrain"]
        lines.append(f"  terrain : route {_pct(t['road']['share_km'])} des km, trail {_pct(t['trail']['share_km'])}")
        extra = []
        if "d_plus_m_per_km" in u:
            extra.append(f"D+ {u['d_plus_m_per_km']:g} m/km")
        if "d_minus_m_per_km" in u:
            extra.append(f"D− {u['d_minus_m_per_km']:g} m/km")
        if "elevation_sessions" in u:
            extra.append(f"(dénivelé sur {u['elevation_sessions']}/{u['sessions']} séances, "
                         f"{u['elevation_distance_m'] / 1000:.0f} km)")
        if "mean_pace_s_km" in u:
            extra.append(f"allure {_clock(u['mean_pace_s_km'])}/km")
        if "mean_gap_pace_s_km" in u:
            extra.append(f"GAP {_clock(u['mean_gap_pace_s_km'])}/km")
        if extra:
            lines.append("  " + " · ".join(extra))
        lines.append("  distances : " + ", ".join(f"{b['label']} ×{b['sessions']}" for b in u["distance_distribution"]
                                                  if b["sessions"]))
        if u.get("long_runs"):
            lines.append(f"  sorties longues (> {LONG_RUN_S // 60} min) : {u['long_runs']['sessions']} "
                         f"({_pct(u['long_runs']['share_sessions'])}) · courses : {u['races']['sessions']}")
        if u.get("wet"):
            lines.append(f"  séances humides : {u['wet']['sessions']}/{u['wet']['with_weather']} avec météo")
        role = p["role"]
        lines.append(f"  rôle déduit : {role['role']} ({role['label']}) — {role['reason']}")
        g = p["gait"]
        if g["bands"]:
            for b in g["bands"]:
                if b["status"] == "ok":
                    vals = ", ".join(f"{m} {v['mean']:g} (n={v['n']})" for m, v in b["metrics"].items())
                    lines.append(f"  foulée {b['label']} [{b['basis']}] : {vals}")
                    for o in b.get("others", []):
                        lines.append(f"    même tranche, {o['gear_id']} : "
                                     + ", ".join(f"{m} {v['mean']:g}" for m, v in o["metrics"].items()))
                else:
                    lines.append(f"  foulée {b['label']} [{b['basis']}] : données insuffisantes ({b['sessions']} < {MIN_BAND_SESSIONS})")
        else:
            lines.append("  foulée : aucune dynamique mesurée")
        pain = p["pain"]
        lines.append(f"  douleurs ≤ 48 h après séance : {pain['episodes']} épisode(s) sur {pain['exposure']['sessions']} "
                     f"séances / {pain['exposure']['distance_m'] / 1000:.0f} km"
                     + (f" — {pain['per_100km']:g} / 100 km" if pain.get("per_100km") is not None else
                        " — pas de taux (effectif trop faible)"))
        if pain.get("warning_unassigned"):
            lines.append(f"  ! {pain['warning_unassigned']}")
        un = pain["unattributable_episodes"]
        if un["total"]:
            lines.append(f"  ! {un['total']} épisode(s) de douleur (toutes paires) rattaché(s) à aucune paire "
                         f"(sans séance dans la fenêtre : {un['no_run_in_window']}, séance sans paire : "
                         f"{un['run_without_pair']}) — corrélation, pas causalité")
        ua = p["unassigned"]
        if ua["runs"] or ua["default_attributed_runs"]:
            lines.append(f"  séances sans gear_id sur la période : {ua['runs']} sans paire"
                         + (f", {ua['default_attributed_runs']} créditée(s) par défaut" if ua["default_attributed_runs"] else "")
                         + (f", dont {ua['since_last_attributed_run']} depuis la dernière séance de la paire"
                            if ua.get("since_last_attributed_run") else ""))
        fb = p.get("feedback")
        if fb and fb.get("comfort"):
            lines.append(f"  confort déclaré : {fb['comfort']['mean']:g}/10 (n={fb['comfort']['n']})"
                         + (", problèmes (séances) : " + ", ".join(f"{k} ×{n}" for k, n in fb["issue_counts"].items())
                            if fb.get("issue_counts") else ""))
        w = p.get("wear")
        if w:
            lines.append(f"  dernière inspection ({w['date']}) : {w['condition']}")
    if not rep["pairs"]:
        lines.append(rep.get("info") or "Aucune paire.")
    lines.append(CAVEAT)
    return "\n".join(lines)
