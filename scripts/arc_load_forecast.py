#!/usr/bin/env python3
"""Projection de charge sur le bloc planifié (#172) : forme prévue le jour de la course.

Les garde-fous (`arc_guardrails`, R1/R4) projettent l'ACWR et la monotonie sur la SEULE
semaine proposée. Ce module répond à la question centrale de l'affûtage : « avec ce plan,
dans quel état serai-je le jour J ? ». Il propage condition / fatigue / forme jour par jour
depuis l'état RÉEL d'aujourd'hui jusqu'à la date de l'objectif (`planning/active_objective.md`),
en estimant la charge de chaque séance planifiée.

Aucun second modèle de charge : tout est réutilisé.
- `arc_guardrails.projected_session_load` / `_week_loads_by_date` : charge estimée d'une
  séance planifiée (durée × RPE attendu de l'intensité × `arc_metrics.RPE_TO_TRIMP`), appariement
  séance ↔ activité réelle, durée estimée depuis la distance — EXACTEMENT ce que R1 projette ;
- `arc_metrics.daily_series` : condition (42 j) / fatigue (7 j) / forme / ACWR / monotonie ;
- `arc_guardrails.MIN_HISTORY_DAYS_FOR_PROJECTION` : même plancher d'historique que R1.

`forecast()` est PURE (aucune E/S, palier D). `load_forecast()` lit l'index dérivé (`conn`).
La projection est une ESTIMATION à partir du planifié, jamais une mesure — voir
`arc_metrics.ASSUMPTIONS["load_forecast"]`. Bibliothèque standard uniquement.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arc_guardrails as G  # noqa: E402
import arc_metrics as M  # noqa: E402

# Statuts de sortie : chaque état honnête est dit, jamais un chiffre inventé.
STATUS_OK = "ok"
STATUS_NO_OBJECTIVE = "no_objective"
STATUS_PAST = "target_past"
STATUS_NO_PLAN = "no_plan"
STATUS_INSUFFICIENT_HISTORY = "insufficient_history"

# Recalage d'échelle « réel / estimé » (revue #172) : une séance RÉELLE avec FC pèse son TRIMP de Banister,
# une séance PLANIFIÉE son estimation sRPE (minutes × RPE attendu × RPE_TO_TRIMP). Selon la physiologie de
# l'athlète, le rapport des deux varie d'environ 0,9 à 1,45 pour la même séance (FC de réserve 55-90 %,
# H/F) : la condition de départ, bâtie sur du TRIMP réel, se viderait alors vers une charge planifiée plus
# basse et la forme prévue le jour J serait gonflée (≈ +12 pour un plan identique à l'historique avec un
# rapport de 1,3 sur trois semaines). Le rapport est mesuré sur les séances PLANIFIÉES PASSÉES appariées à
# une activité réelle — jamais un second modèle : la même estimation, recalée sur l'athlète.
CALIBRATION_WINDOW_DAYS = 56
CALIBRATION_MIN_PAIRS = 5
CALIBRATION_BOUNDS = (0.5, 2.0)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _parse(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _active_sessions(sessions: List[dict]) -> List[dict]:
    """Séances qui comptent (ni annulées/déplacées/manquées, ni repos) — même filtre que R1."""
    return [s for s in sessions if isinstance(s, dict) and not G._is_excluded(s)]


def _normalise_weeks(planned_weeks: List[dict]) -> Dict[str, List[dict]]:
    """`{lundi ISO: [séances]}` — une semaine déclarée deux fois fusionne ses séances."""
    out: Dict[str, List[dict]] = {}
    for week in planned_weeks or []:
        if not isinstance(week, dict):
            continue
        start = _parse(week.get("week_start"))
        if start is None:
            continue
        key = _monday(start).isoformat()
        out.setdefault(key, []).extend(s for s in (week.get("sessions") or []) if isinstance(s, dict))
    return out


def calibration(pairs: List[tuple]) -> dict:
    """Rapport charge réelle / charge estimée sur des paires `(réelle, estimée)` de séances planifiées
    passées appariées à une activité. PURE. `applied` faux (échelle 1, estimation brute de R1) si moins de
    `CALIBRATION_MIN_PAIRS` paires exploitables ou si le rapport sort de `CALIBRATION_BOUNDS` (FC de repos /
    max, intensités planifiées ou appariements probablement incohérents : on ne recale pas sur un artefact)."""
    usable = [(r, e) for r, e in pairs if r and e and r > 0 and e > 0]
    out = {"pairs": len(usable), "window_days": CALIBRATION_WINDOW_DAYS, "ratio": None, "applied": False,
           "scale": 1.0}
    if len(usable) < CALIBRATION_MIN_PAIRS:
        return {**out, "reason": f"moins de {CALIBRATION_MIN_PAIRS} séances planifiées passées appariées à une "
                                 f"activité sur {CALIBRATION_WINDOW_DAYS} j : charge planifiée NON recalée."}
    ratio = round(sum(r for r, _ in usable) / sum(e for _, e in usable), 3)
    lo, hi = CALIBRATION_BOUNDS
    if not lo <= ratio <= hi:
        return {**out, "ratio": ratio, "reason": f"rapport réel/estimé {ratio} hors de [{lo} ; {hi}] : charge "
                                                 "planifiée NON recalée (vérifier FC de repos/max et intensités)."}
    return {**out, "ratio": ratio, "applied": True, "scale": ratio, "reason": None}


def _entering(series: List[dict], day: date) -> Optional[dict]:
    """État « en entrant dans la journée » `day` : forme du point `day` (déjà calculée avant sa charge
    par `daily_series`) et condition / fatigue / ACWR du point de la VEILLE — les quatre valeurs sont
    ainsi cohérentes (forme = condition − fatigue) et la charge du jour même (la course) n'y entre pas."""
    by_date = {p["date"]: p for p in series}
    point, before = by_date.get(day.isoformat()), by_date.get((day - timedelta(days=1)).isoformat())
    if point is None or before is None:
        return None
    return {"date": point["date"], "form": point["form"], "fitness": before["fitness"],
            "fatigue": before["fatigue"], "acwr": before["acwr"]}


def _summary(series: List[dict], today: date, target: date, race: Optional[date]) -> dict:
    """Points clés d'une série projetée jusqu'à la date visée. Tout est lu « en entrant dans la
    journée » visée : pic de fatigue, ACWR max et charge totale portent sur `[today, veille de la
    cible]` — la charge de la course elle-même (souvent la plus lourde du bloc) ne fait jamais de la
    semaine de course le « pic de fatigue » ni de l'ACWR du jour J le maximum du bloc."""
    window = [p for p in series if today.isoformat() <= p["date"] < target.isoformat()]
    peak = max(window, key=lambda p: p["fatigue"]) if window else None
    acwr_points = [p for p in window if p.get("acwr") is not None]
    acwr_peak = max(acwr_points, key=lambda p: p["acwr"]) if acwr_points else None
    end = _entering(series, target)
    return {
        "race_day": _entering(series, race) if race else None,
        "end": ({k: end[k] for k in ("date", "form", "fitness", "fatigue")} if end else None),
        "peak_fatigue": ({"date": peak["date"], "week_start": _monday(date.fromisoformat(peak["date"])).isoformat(),
                          "fatigue": peak["fatigue"]} if peak else None),
        "acwr_max": ({"date": acwr_peak["date"], "value": acwr_peak["acwr"]} if acwr_peak else None),
        "planned_load_total": _round(sum(p["load"] for p in window)),
    }


def _week_rows(series: List[dict], weeks_by_start: Dict[str, List[dict]], today: date, target: date) -> List[dict]:
    """Une ligne par semaine (lundi-dimanche) touchant `[today, target]` ; `partial` quand la
    fenêtre ne couvre pas les 7 jours (semaine en cours, semaine de course)."""
    rows = []
    monday = _monday(today)
    while monday <= target:
        days = [p for p in series if monday.isoformat() <= p["date"] <= (monday + timedelta(days=6)).isoformat()
                and today.isoformat() <= p["date"] <= target.isoformat()]
        if days:
            sessions = weeks_by_start.get(monday.isoformat())
            acwr = [p["acwr"] for p in days if p.get("acwr") is not None]
            rows.append({
                "week_start": monday.isoformat(),
                "planned": sessions is not None and bool(_active_sessions(sessions)),
                "sessions": len(_active_sessions(sessions or [])),
                "load_total": _round(sum(p["load"] for p in days)),
                "fitness_end": days[-1]["fitness"], "fatigue_end": days[-1]["fatigue"], "form_end": days[-1]["form"],
                "acwr_max": max(acwr) if acwr else None,
                "partial": len(days) < 7,
            })
        monday += timedelta(days=7)
    return rows


def forecast(real_loads: Dict[str, float], today: date, race_date: Optional[str], until: Optional[date],
             planned_weeks: List[dict], activities: Optional[List[dict]] = None,
             recent_pace_s_km: Optional[float] = None, calib: Optional[dict] = None) -> dict:
    """Projection de condition/fatigue/forme sur `[today, cible]`, où cible = `until` ou la date de
    l'objectif. PURE.

    `real_loads` : charge réelle indexée par jour (< `today` seul est lu). `planned_weeks` : semaines
    (`{week_start, sessions[]}`, séances au format du contrat `week`). `activities` : activités réelles
    `{date, sport, load}` de la semaine en cours (apparient les séances d'aujourd'hui — le réel prime,
    jamais compté deux fois). Un jour sans séance planifiée compte 0 de charge (hypothèse, signalée
    par `weeks_unplanned`) ; jamais d'extrapolation de la moyenne récente. `calib` (voir `calibration`) :
    quand `applied`, la charge PROJETÉE (jamais la réelle) est multipliée par `calib["scale"]`."""
    race = _parse(race_date)
    target = until or race
    base = {"status": None, "today": today.isoformat(), "race_date": race.isoformat() if race else None,
            "target_date": target.isoformat() if target else None, "is_estimate": True,
            "assumptions_ref": "arc_metrics.ASSUMPTIONS[\"load_forecast\"] (/api/assumptions)",
            "calibration": calib or calibration([])}
    if target is None:
        return {**base, "status": STATUS_NO_OBJECTIVE,
                "reason": "Aucun objectif actif (planning/active_objective.md sans date de course) et pas de "
                          "--until : rien à projeter."}
    if target < today:
        return {**base, "status": STATUS_PAST,
                "reason": f"La date visée ({target.isoformat()}) est déjà passée : rien à projeter."}

    first_real = min((date.fromisoformat(d) for d in real_loads), default=None)
    history_span = (today - first_real).days if first_real else 0
    base["history_span_days"] = history_span
    if history_span < G.MIN_HISTORY_DAYS_FOR_PROJECTION:
        return {**base, "status": STATUS_INSUFFICIENT_HISTORY,
                "reason": f"Historique réel insuffisant ({history_span} j < {G.MIN_HISTORY_DAYS_FOR_PROJECTION} j) : "
                          "la condition (moyenne exponentielle 42 j) démarre à zéro et fausserait la forme prévue — "
                          "même plancher que le garde-fou R1."}

    weeks_by_start = _normalise_weeks(planned_weeks)
    scale = base["calibration"]["scale"] if base["calibration"].get("applied") else 1.0
    loads: Dict[str, float] = {d: v for d, v in real_loads.items() if date.fromisoformat(d) < today}
    acts_by_week: Dict[str, List[dict]] = {}
    for act in activities or []:
        day = _parse(act.get("date"))
        if day is not None:
            acts_by_week.setdefault(_monday(day).isoformat(), []).append(act)

    unresolved: List[str] = []
    estimated: List[str] = []
    planned_weeks_n, unplanned_starts = 0, []
    monday = _monday(today)
    while monday <= target:
        key = monday.isoformat()
        sessions = weeks_by_start.get(key) or []
        end_of_week = monday + timedelta(days=6)
        week_context = {"week_activities": acts_by_week.get(key, []), "recent_run_pace_s_km": recent_pace_s_km}
        day_loads = G._week_loads_by_date(week_context, sessions, monday, end_of_week, today, zero_proposed=False)
        # Part RÉELLE seule (même appel, séances proposées à zéro) : le recalage ne touche que l'estimé.
        real_part = G._week_loads_by_date(week_context, sessions, monday, end_of_week, today, zero_proposed=True)
        for day_iso, load in day_loads.items():
            day = date.fromisoformat(day_iso)
            if today <= day <= target:
                real = real_part.get(day_iso, 0.0)
                loads[day_iso] = real + (load - real) * scale
        if _active_sessions(sessions):
            planned_weeks_n += 1
            unresolved += G._unresolved_duration_dates(sessions, recent_pace_s_km)
            estimated += G._estimated_duration_dates(sessions, recent_pace_s_km)
        else:
            unplanned_starts.append(key)
        monday += timedelta(days=7)

    series = M.daily_series(loads, first_real, target)
    state_today = next((p for p in series if p["date"] == today.isoformat()), None)
    out = {**base, "today_state": {k: state_today[k] for k in ("fitness", "fatigue", "form", "acwr")}
           if state_today else None,
           "weeks_planned": planned_weeks_n, "weeks_unplanned": len(unplanned_starts),
           "unplanned_week_starts": unplanned_starts,
           "estimated_duration_dates": sorted(set(estimated)), "unresolved_duration_dates": sorted(set(unresolved)),
           "series": [{**p, "projected": p["date"] >= today.isoformat()} for p in series
                      if p["date"] >= (today - timedelta(days=1)).isoformat()]}
    if planned_weeks_n == 0:
        return {**out, "status": STATUS_NO_PLAN,
                "reason": "Aucune séance planifiée entre aujourd'hui et la date visée : une projection à charge "
                          "nulle ne serait pas un plan — écrire les semaines avant de projeter."}
    summary = _summary(series, today, target, race if race and today <= race <= target else None)
    out.update(summary)
    out["weeks"] = _week_rows(series, weeks_by_start, today, target)
    out["status"] = STATUS_OK
    out["partial_plan"] = bool(unplanned_starts)
    out["reason"] = None
    return out


def _compact(result: dict) -> dict:
    keys = ("race_day", "end", "peak_fatigue", "acwr_max", "planned_load_total")
    return {k: result.get(k) for k in keys}


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return _round(b - a) if a is not None and b is not None else None


def apply_alternative(planned_weeks: List[dict], alternative_weeks: List[dict]) -> List[dict]:
    """Plan modifié : les semaines de l'alternative REMPLACENT celles du plan actuel de même lundi
    (jamais fusionnées séance à séance) ; les autres restent telles quelles ; une semaine nouvelle s'ajoute."""
    alt = _normalise_weeks(alternative_weeks)
    kept = [w for w in planned_weeks if isinstance(w, dict) and _parse(w.get("week_start"))
            and _monday(_parse(w["week_start"])).isoformat() not in alt]
    return kept + [{"week_start": k, "sessions": v} for k, v in sorted(alt.items())]


def compare(real_loads: Dict[str, float], today: date, race_date: Optional[str], until: Optional[date],
            planned_weeks: List[dict], alternative_weeks: List[dict], activities: Optional[List[dict]] = None,
            recent_pace_s_km: Optional[float] = None, calib: Optional[dict] = None) -> dict:
    """Plan actuel vs plan modifié : deux projections + écarts (alternatif − actuel). PURE.
    Une projection non `ok` (historique, pas de plan…) est rendue telle quelle, sans écarts."""
    current = forecast(real_loads, today, race_date, until, planned_weeks, activities, recent_pace_s_km, calib)
    modified_weeks = apply_alternative(planned_weeks, alternative_weeks)
    alternative = forecast(real_loads, today, race_date, until, modified_weeks, activities, recent_pace_s_km, calib)
    replaced = sorted(set(_normalise_weeks(alternative_weeks)) & set(_normalise_weeks(planned_weeks)))
    added = sorted(set(_normalise_weeks(alternative_weeks)) - set(_normalise_weeks(planned_weeks)))
    out = {"current": current, "alternative": alternative, "replaced_weeks": replaced, "added_weeks": added,
           "deltas": None}
    if current["status"] != STATUS_OK or alternative["status"] != STATUS_OK:
        return out
    cur, alt = _compact(current), _compact(alternative)

    def pick(block, *path):
        for key in path:
            block = (block or {}).get(key) if isinstance(block, dict) else None
        return block

    deltas = {
        "race_day_form": _delta(pick(cur, "race_day", "form"), pick(alt, "race_day", "form")),
        "race_day_fitness": _delta(pick(cur, "race_day", "fitness"), pick(alt, "race_day", "fitness")),
        "race_day_fatigue": _delta(pick(cur, "race_day", "fatigue"), pick(alt, "race_day", "fatigue")),
        "end_form": _delta(pick(cur, "end", "form"), pick(alt, "end", "form")),
        "peak_fatigue": _delta(pick(cur, "peak_fatigue", "fatigue"), pick(alt, "peak_fatigue", "fatigue")),
        "acwr_max": _delta(pick(cur, "acwr_max", "value"), pick(alt, "acwr_max", "value")),
        "planned_load_total": _delta(cur["planned_load_total"], alt["planned_load_total"]),
    }
    out["deltas"] = deltas
    form_delta = deltas["race_day_form"] if deltas["race_day_form"] is not None else deltas["end_form"]
    if form_delta is not None:
        verdict = "plus fraîche" if form_delta > 0 else "moins fraîche" if form_delta < 0 else "identique"
        out["reading"] = (f"Forme prévue à la date visée : {verdict} avec le plan modifié ({form_delta:+.1f}) — "
                          "estimation à partir du planifié, pas une mesure.")
    return out


# ---------------------------------------------------------------------------
# Lecture de l'index (impure)
# ---------------------------------------------------------------------------


def _planned_weeks_from_index(conn, since: date, until: Optional[date] = None) -> List[dict]:
    """Semaines planifiées indexées (hors `shadowed`, voir #69) dont la date est dans `[since, until]`."""
    rows = conn.execute(
        "SELECT week_start, date, sport, planned_duration_s, planned_distance_m, planned_elevation_m, "
        "intensity, status FROM planned_session WHERE shadowed = 0 AND date >= ? AND date <= ? ORDER BY date",
        (since.isoformat(), (until or date.max).isoformat())).fetchall()
    weeks: Dict[str, List[dict]] = {}
    for week_start, day, sport, duration_s, distance_m, elevation_m, intensity, status in rows:
        weeks.setdefault(week_start or _monday(date.fromisoformat(day)).isoformat(), []).append({
            "date": day, "sport": sport, "planned_duration_s": duration_s, "planned_distance_m": distance_m,
            "planned_elevation_m": elevation_m, "intensity": intensity, "status": status})
    return [{"week_start": k, "sessions": v} for k, v in sorted(weeks.items())]


def _calibration_pairs(conn, today: date, recent_pace_s_km: Optional[float]) -> List[tuple]:
    """Paires `(charge réelle, charge estimée)` des séances planifiées des `CALIBRATION_WINDOW_DAYS`
    derniers jours (veille incluse) appariées à une activité réelle — même appariement que la conformité
    et R1 (`arc_metrics.resolve_sessions`), même estimation que la projection (`projected_session_load`)."""
    start, end = today - timedelta(days=CALIBRATION_WINDOW_DAYS), today - timedelta(days=1)
    sessions = [s for w in _planned_weeks_from_index(conn, start, end) for s in w["sessions"]
                if not G._is_excluded(s)]
    by_date: Dict[str, List[dict]] = {}
    for d, sport, load in conn.execute("SELECT date, sport, load FROM activity WHERE date >= ? AND date <= ?",
                                       (start.isoformat(), end.isoformat())).fetchall():
        by_date.setdefault(d, []).append({"date": d, "sport": sport, "load": load or 0.0, "_used": False})
    resolved = M.resolve_sessions(sorted(sessions, key=lambda s: s.get("date") or ""), by_date, end.isoformat())
    return [(r["actual"].get("load") or 0.0, G.projected_session_load(r["session"], recent_pace_s_km))
            for r in resolved if r["actual"]]


def load_forecast(conn, today: date, until: Optional[date] = None,
                  alternative_weeks: Optional[List[dict]] = None) -> dict:
    """Projection depuis l'index dérivé : charge réelle, activités de la semaine en cours, semaines
    planifiées, allure récente (estimation de durée depuis une distance, comme R1) et date de l'objectif."""
    rows = conn.execute("SELECT date, load FROM activity WHERE load IS NOT NULL").fetchall()
    real_loads: Dict[str, float] = {}
    for day, load in rows:
        real_loads[day] = real_loads.get(day, 0.0) + (load or 0.0)
    monday = _monday(today)
    activities = [{"date": d, "sport": s, "load": load or 0.0} for d, s, load in conn.execute(
        "SELECT date, sport, load FROM activity WHERE date >= ?", (monday.isoformat(),)).fetchall()]
    planned = _planned_weeks_from_index(conn, monday)
    pace = G._recent_run_pace_s_km(conn, today)
    race_date = G._active_objective_race_date(conn)
    calib = calibration(_calibration_pairs(conn, today, pace))
    if alternative_weeks is not None:
        return compare(real_loads, today, race_date, until, planned, alternative_weeks, activities, pace, calib)
    return forecast(real_loads, today, race_date, until, planned, activities, pace, calib)


def alternative_weeks_from_block(block: dict) -> List[dict]:
    """Semaines d'un bloc `--compare` : fichier multi-semaines (`weeks[]`) ou semaine unique
    (`week_start` + `sessions`). `ValueError` si rien d'exploitable."""
    if isinstance(block.get("weeks"), list):
        weeks = [w for w in block["weeks"] if isinstance(w, dict) and _parse(w.get("week_start"))]
    elif _parse(block.get("week_start")):
        weeks = [block]
    else:
        weeks = []
    if not weeks:
        raise ValueError("aucune semaine exploitable (week_start + sessions, ou weeks[]).")
    return [{"week_start": w["week_start"], "sessions": w.get("sessions") or []} for w in weeks]


def render_text(result: dict) -> str:
    """Rendu texte court (CLI `--text`), vocabulaire générique : condition / fatigue / forme."""
    lines = []
    if "current" in result:                       # comparaison
        for label, key in (("Plan actuel", "current"), ("Plan modifié", "alternative")):
            lines.append(f"{label} :")
            lines += ["  " + ln for ln in render_text(result[key]).splitlines()]
        if result.get("deltas"):
            deltas = result["deltas"]
            lines.append("Écarts (modifié − actuel) : "
                         + ", ".join(f"{k} {v:+.1f}" for k, v in deltas.items() if v is not None))
            if result.get("reading"):
                lines.append(result["reading"])
        return "\n".join(lines)
    if result["status"] != STATUS_OK:
        return f"Projection indisponible ({result['status']}) : {result.get('reason')}"
    race_day, end = result.get("race_day"), result.get("end")
    point = race_day or end
    unplanned = result["weeks_unplanned"]
    lines.append(f"Estimation (pas une mesure) jusqu'au {result['target_date']} — "
                 f"{result['weeks_planned']} semaine(s) planifiée(s)"
                 + (f", {unplanned} non planifiée(s) (charge nulle supposée : forme prévue optimiste)." if unplanned
                    else "."))
    calib = result.get("calibration") or {}
    if calib.get("applied"):
        lines.append(f"Charge planifiée recalée ×{calib['scale']:.2f} (réel/estimé sur {calib['pairs']} séance(s) "
                     f"appariée(s) des {calib['window_days']} derniers jours).")
    else:
        lines.append(f"Charge planifiée non recalée : {calib.get('reason') or 'aucun rapport réel/estimé disponible.'}")
    if point:
        label = "Forme prévue le jour J" if race_day else "Forme à la date visée"
        lines.append(f"{label} ({point['date']}, en entrant dans la journée) : {point['form']:+.1f} "
                     f"(condition {point['fitness']:.1f}, fatigue {point['fatigue']:.1f}).")
    peak = result.get("peak_fatigue")
    if peak:
        lines.append(f"Pic de fatigue : semaine du {peak['week_start']} ({peak['fatigue']:.1f}, le {peak['date']}).")
    acwr = result.get("acwr_max")
    lines.append(f"ACWR projeté max : {acwr['value']:.2f} ({acwr['date']})." if acwr else "ACWR projeté : indisponible.")
    return "\n".join(lines)
