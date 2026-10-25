#!/usr/bin/env python3
"""Séances COROS — construction et validation d'une `course` avant poussée.

## Pourquoi

Le MCP officiel de COROS (`https://mcpeu.coros.com/mcp`, OAuth) écrit les séances
au calendrier de la montre (`createScheduledWorkout`, skill
`coros-workout-scheduling`). Il n'existe AUCUN outil de suppression ni de
déplacement : une séance mal formée ou en double ne se corrige que dans l'app
COROS. Ce module vérifie donc la `course` AVANT l'appel, et fait la conversion
d'unités que le modèle ne doit jamais faire de tête (vitesse m/s de
`arc_workout_targets.py` -> allure en s/km de COROS).

Règles relevées le 2026-10-22 dans le schéma de l'outil `createScheduledWorkout`
(session authentifiée) et vérifiées par une poussée réelle relue à l'identique
(`queryScheduledWorkoutDetails`) : voir `COROS_LIMITS`. Une règle du schéma qui
n'a pas encore été poussée en vrai reste une règle DU SCHÉMA, pas une
observation : `docs/coros.md` dit lesquelles.

## Sous-commandes

- `section` — une section prête à pousser depuis une cible personnelle
  (`--hr LOW HIGH` en bpm, ou `--speed-ms LOW HIGH` en m/s, convertis en s/km).
- `validate` — vérifie une `course` complète (JSON sur l'entrée standard ou
  `--file`) ; code de sortie 1 et liste d'erreurs si elle est invalide.
- `threshold` — allure seuil COROS (`Threshold Pace: 4:12 /km` de
  `queryFitnessAssessmentOverview`, relevé le 2026-10-22) -> vitesse en m/s pour
  `--lt-speed-ms` (`arc_workout_targets.py`, `arc_index.py pace-curve`) : `--pace M:SS`.
- `pace-strategy` — fiche à recopier dans le **Pace Strategy** de l'app COROS depuis un plan
  de course au contrat (`--plan planning/…md`, bloc `race_plan`) : temps cible du scénario,
  temps d'arrêt à chaque ravito (points de passage de la route), allure de chaque segment.
  Le Pace Strategy ne se crée QUE dans l'app COROS (Profil → Pace Strategy, sur une route de
  la bibliothèque) : aucun outil du MCP ne le crée ni ne le lit (relevé le 2026-10-23, article
  d'aide COROS « Pace Strategy »). Temps de passage = `arc_race_pacing.compute_passages`, les
  mêmes que le plan ; rien n'est recalculé ici.

Aucune dépendance hors bibliothèque standard, aucun appel réseau.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import os
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# sportType d'une SÉANCE (≠ codes des activités enregistrées : 100 course, 102 trail…).
SPORTS = {1: "running", 2: "cycling", 5: "trail_running"}
SECTION_TYPES = {"warmup": 1, "training": 2, "recovery": 3, "cooldown": 4}
TARGET_TYPES = {1: "distance_m", 2: "time_s", 3: "climb_m", 4: "free"}
INTENSITY_TYPES = {1: "heart_rate", 2: "pace", 3: "effort_threshold_pace_pct", 4: "power"}

COROS_LIMITS = {
    # Cibles permises par sport : le trail n'a PAS de cible de durée (distance, D+ ou libre).
    "target_types": {1: {1, 2, 4}, 2: {1, 2, 4}, 5: {1, 3, 4}},
    "intensity_types": {1: {1, 2, 4}, 2: {1, 4}, 5: {1, 2, 3, 4}},
    "course_name_max": 100,
    "repeats": (1, 20),
    "zone": (1, 6),
    "value_bounds": {1: (30, 240), 2: (120, 1499), 4: (10, 2000)},  # bpm, s/km, W
    "percent_bounds": {1: (20, 120), 2: (20, 140), 3: (20, 140)},  # %LTHR, % allure seuil
}

_FORMATS = (
    ("sectionIntensity",),
    ("intensityPercentStart", "intensityPercentEnd"),
    ("intensityValueStart", "intensityValueEnd"),
)
_INTENSITY_KEYS = ("intensityType",) + tuple(k for fmt in _FORMATS for k in fmt)


def speed_ms_to_pace_s_km(speed_ms: float) -> int:
    """Vitesse (m/s) -> allure entière en s/km, l'unité de COROS."""
    if not speed_ms or speed_ms <= 0:
        raise ValueError(f"vitesse non positive : {speed_ms!r}")
    return round(1000.0 / speed_ms)


def section(*, section_type: str = "training", duration_s: Optional[float] = None,
            distance_m: Optional[float] = None, climb_m: Optional[float] = None,
            hr_bpm: Optional[Sequence[float]] = None,
            speed_ms: Optional[Sequence[float]] = None) -> dict:
    """Une section COROS à cible prédéfinie (une seule de durée/distance/D+) et à
    plage absolue : FC en bpm, ou vitesse en m/s convertie en allure s/km
    (plage écrite lente -> rapide). Sans `hr_bpm` ni `speed_ms`, la section n'a
    pas de cible d'intensité (à réserver aux consignes « à la sensation »)."""
    goals = [(1, distance_m), (2, duration_s), (3, climb_m)]
    given = [(t, v) for t, v in goals if v is not None]
    if len(given) != 1:
        raise ValueError("une seule cible parmi durée, distance et D+")
    if hr_bpm is not None and speed_ms is not None:
        raise ValueError("une seule cible d'intensité : FC ou allure")
    target_type, value = given[0]
    out = {"sectionType": SECTION_TYPES[section_type], "targetType": target_type,
           "targetValue": round(value)}
    if hr_bpm is not None:
        low, high = sorted(round(b) for b in hr_bpm)
        out.update(intensityType=1, intensityValueStart=low, intensityValueEnd=high)
    elif speed_ms is not None:
        slow, fast = sorted(speed_ms)
        out.update(intensityType=2, intensityValueStart=speed_ms_to_pace_s_km(slow),
                   intensityValueEnd=speed_ms_to_pace_s_km(fast))
    return out


def _check_intensity(sec: dict, sport: int, where: str) -> List[str]:
    errors: List[str] = []
    itype = sec.get("intensityType")
    used = [fmt for fmt in _FORMATS if any(k in sec for k in fmt)]
    if itype is None:
        if used:
            errors.append(f"{where} : champs d'intensité sans intensityType")
        return errors
    if itype not in COROS_LIMITS["intensity_types"].get(sport, set()):
        errors.append(f"{where} : intensityType {itype} interdit pour le sport {sport}")
        return errors
    if len(used) != 1:
        errors.append(f"{where} : exactement un format d'intensité attendu (zone, % ou valeurs), reçu {len(used)}")
        return errors
    fmt = used[0]
    missing = [k for k in fmt if k not in sec]
    if missing:
        errors.append(f"{where} : {', '.join(missing)} manquant")
        return errors
    if fmt == ("sectionIntensity",):
        if itype == 4 and sport != 2:
            errors.append(f"{where} : la puissance en course/trail n'accepte que des watts absolus")
        lo, hi = COROS_LIMITS["zone"] if itype != 4 else (1, 7)
        if not lo <= sec["sectionIntensity"] <= hi:
            errors.append(f"{where} : zone {sec['sectionIntensity']} hors de [{lo}, {hi}]")
    elif fmt[0] == "intensityPercentStart":
        if itype == 4:
            errors.append(f"{where} : pas de pourcentage pour la puissance")
            return errors
        lo, hi = COROS_LIMITS["percent_bounds"][itype]
        start, end = sec["intensityPercentStart"], sec["intensityPercentEnd"]
        if not lo <= start < end <= hi:
            errors.append(f"{where} : pourcentage {start}-{end} invalide (attendu {lo} <= début < fin <= {hi})")
    else:
        if itype == 3:
            errors.append(f"{where} : le % d'allure seuil à l'effort n'a pas de valeur absolue")
            return errors
        lo, hi = COROS_LIMITS["value_bounds"][itype]
        for key in fmt:
            v = sec[key]
            if not isinstance(v, int) or not lo <= v <= hi:
                errors.append(f"{where} : {key}={v!r} hors de [{lo}, {hi}] (entier)")
    return errors


def _check_plain(sec: dict, sport: int, where: str, in_group: bool) -> List[str]:
    errors: List[str] = []
    stype = sec.get("sectionType")
    allowed = {2, 3} if in_group else set(SECTION_TYPES.values())
    if stype not in allowed:
        errors.append(f"{where} : sectionType {stype!r} interdit ici (permis : {sorted(allowed)})")
    ttype = sec.get("targetType")
    if ttype not in COROS_LIMITS["target_types"].get(sport, set()):
        errors.append(f"{where} : targetType {ttype!r} interdit pour le sport {sport} "
                      f"(permis : {sorted(COROS_LIMITS['target_types'].get(sport, ()))})")
    elif ttype == 4:
        if sec.get("targetValue") not in (None, 0):
            errors.append(f"{where} : mode libre sans targetValue")
    else:
        v = sec.get("targetValue")
        if not isinstance(v, int) or v <= 0:
            errors.append(f"{where} : targetValue entier positif attendu, reçu {v!r}")
    return errors + _check_intensity(sec, sport, where)


def validate_course(course: dict) -> List[str]:
    """Erreurs de forme d'une `course` COROS (liste vide = valide)."""
    if not isinstance(course, dict):
        return ["course : objet JSON attendu"]
    errors: List[str] = []
    sport = course.get("sportType")
    if sport not in SPORTS:
        errors.append(f"sportType {sport!r} non poussable (1 course, 2 vélo, 5 trail ; pas de renforcement)")
        return errors
    name = (course.get("courseName") or "").strip()
    if not name:
        errors.append("courseName vide")
    elif len(name) > COROS_LIMITS["course_name_max"]:
        errors.append(f"courseName > {COROS_LIMITS['course_name_max']} caractères")
    if not (course.get("courseDescription") or "").strip():
        errors.append("courseDescription vide")
    for key in ("dayNo", "intensityType", "strengthBodypart"):
        if course.get(key) is not None:
            errors.append(f"{key} interdit au niveau de la séance")
    sections = course.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections : liste non vide attendue")
        return errors
    lo, hi = COROS_LIMITS["repeats"]
    for i, sec in enumerate(sections, 1):
        where = f"section {i}"
        if sec.get("intervalGroup"):
            if any(k in sec for k in _INTENSITY_KEYS + ("targetType", "targetValue")):
                errors.append(f"{where} : un groupe ne porte ni cible ni intensité (elles vont dans ses sets)")
            if not isinstance(sec.get("repeats"), int) or not lo <= sec["repeats"] <= hi:
                errors.append(f"{where} : repeats entre {lo} et {hi}")
            members = sec.get("sets")
            if not isinstance(members, list) or not members:
                errors.append(f"{where} : sets non vide attendu")
                continue
            for j, member in enumerate(members, 1):
                if member.get("intervalGroup"):
                    errors.append(f"{where}.{j} : groupes imbriqués interdits")
                else:
                    errors += _check_plain(member, sport, f"{where}.{j}", in_group=True)
        else:
            errors += _check_plain(sec, sport, where, in_group=False)
    return errors


def pace_to_speed_ms(pace: str) -> float:
    """« 4:12 », « 4:12 /km » ou « 4:12/km » -> vitesse en m/s (3 décimales). Refuse le reste."""
    m = re.fullmatch(r"\s*(\d{1,2}):([0-5]\d)\s*(?:/\s*km)?\s*", pace or "")
    if not m:
        raise ValueError(f"allure illisible : {pace!r} (attendu M:SS, en min/km)")
    seconds = int(m.group(1)) * 60 + int(m.group(2))
    if not 120 <= seconds <= 1499:  # bornes d'allure du schéma COROS
        raise ValueError(f"allure hors bornes : {pace!r}")
    return round(1000.0 / seconds, 3)


# ---------------------------------------------------------------------------
# Pace Strategy (app COROS) — fiche depuis un plan de course
# ---------------------------------------------------------------------------

# Le DERNIER ravito à moins de 2 % de la longueur mesurée du GPX (50 m au moins) est l'arrivée : pas de
# temps d'arrêt à saisir. Règle partagée avec le roadbook : `arc_race_pacing.finish_tolerance_km`.


def _clock(seconds: float) -> str:
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}"


def _short(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60} min {total % 60:02d} s" if total >= 60 else f"{total} s"


def _pace(seconds_per_km: float) -> str:
    total = int(round(seconds_per_km))
    return f"{total // 60}:{total % 60:02d} /km"


def load_race_plan(path: str) -> dict:
    import arc_contract as C  # noqa: E402 (même dossier)

    try:
        block = C.extract_block(open(path, encoding="utf-8").read())
    except (OSError, C.ContractError) as exc:
        raise ValueError(f"{path} : {exc}") from exc
    if not block or block.get("kind") != "race_plan":
        raise ValueError(f"{path} : bloc ```arc de type « race_plan » attendu")
    return block


def pace_strategy(plan: dict, scenario: Optional[str] = None) -> dict:
    """Ce qu'il faut saisir dans le Pace Strategy COROS (version « Route ») pour suivre `plan`.

    Scénario par défaut : celui dont le total vaut `target_time_s` du plan, sinon `realistic`.
    Les temps de passage viennent de `arc_race_pacing.compute_passages` (arrêts ravito compris,
    arrondis à la minute comme dans le plan) ; les allures des `segments` du plan, telles quelles."""
    import arc_race_pacing as RP  # noqa: E402 (même dossier)

    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("plan de course sans segments (plan écrit sans GPX ?) : rien à recopier")
    aid = sorted((a for a in plan.get("aid_stations") or [] if isinstance(a, dict) and "km" in a),
                 key=lambda a: a["km"])
    passages = RP.compute_passages(segments, aid)
    notes: List[str] = []
    if scenario is None:
        target = plan.get("target_time_s")
        scenario = next((s for s in RP.SCENARIOS if (plan.get("scenarios") or {}).get(s) == target), "realistic")
        notes.append(f"scénario « {scenario} » retenu "
                     + ("(celui du temps visé du plan)" if (plan.get("scenarios") or {}).get(scenario) == target
                        else "(par défaut : aucun scénario ne correspond au temps visé du plan)"))
    if scenario not in RP.SCENARIOS:
        raise ValueError(f"scénario inconnu : {scenario!r} ({', '.join(RP.SCENARIOS)})")
    start = None
    if plan.get("start_time"):
        try:
            start = datetime.fromisoformat(str(plan["start_time"]))
        except ValueError:
            notes.append(f"heure de départ illisible ({plan['start_time']!r}) : pas d'heure murale")
    end_km = segments[-1].get("km_end") or 0.0
    waypoints = []
    tolerance = RP.finish_tolerance_km(end_km)
    for i, (station, passage) in enumerate(zip(aid, passages["aid_station_passages"])):
        arrival = passage[scenario]
        finish = i == len(aid) - 1 and station["km"] >= end_km - tolerance
        stop = 0.0 if finish else float(station.get("stop_s", RP.DEFAULT_AID_STATION_STOP_S))
        entry = {"km": station["km"], "name": station.get("name"), "finish": finish,
                 "arrival_s": arrival, "arrival": _clock(arrival), "stop_s": stop, "stop": _short(stop)}
        if start is not None:
            entry["clock"] = (start + timedelta(seconds=arrival)).strftime("%H:%M")
        if "stop_s" not in station and not finish:
            entry["stop_default"] = True
        waypoints.append(entry)
    rows = []
    for seg in segments:
        pace = (seg.get("pace_s_km") or {}).get(scenario)
        time_s = (seg.get("predicted_time_s") or {}).get(scenario)
        if pace is None or time_s is None:
            raise ValueError(f"segment {seg.get('id')} : pas d'allure pour le scénario « {scenario} »")
        rows.append({"id": seg.get("id"), "km_start": seg.get("km_start"), "km_end": seg.get("km_end"),
                     "grade_mean_pct": seg.get("grade_mean_pct"), "elevation_gain_m": seg.get("elevation_gain_m"),
                     "elevation_loss_m": seg.get("elevation_loss_m"), "pace_s_km": round(pace),
                     "pace": _pace(pace), "time_s": time_s, "time": _clock(time_s)})
    total = passages["totals_s"][scenario]
    if any(not w["finish"] for w in waypoints):
        notes.append("route : un point de passage AVEC alerte par ravito (Explore → route), sinon l'app ne "
                     "propose pas de temps aux points de passage")
    if any(w.get("stop_default") for w in waypoints):
        notes.append(f"temps d'arrêt par défaut du projet ({int(RP.DEFAULT_AID_STATION_STOP_S)} s) aux ravitos "
                     "sans stop_s dans le plan")
    notes.append("COROS découpe ses propres segments et calcule leur allure : ne corriger que ceux qui "
                 "s'écartent nettement des allures ci-dessous")
    return {"race_name": plan.get("race_name"), "race_date": plan.get("race_date"),
            "start_time": plan.get("start_time"), "scenario": scenario,
            "target_time_s": total, "target_time": _clock(total),
            "distance_m": plan.get("distance_m"), "elevation_gain_m": plan.get("elevation_gain_m"),
            "waypoints": waypoints, "segments": rows, "notes": notes}


def pace_strategy_text(sheet: dict) -> str:
    lines = [f"Pace Strategy COROS — {sheet.get('race_name') or 'course'} ({sheet.get('race_date') or 'date ?'})",
             f"Temps cible : {sheet['target_time']} (scénario « {sheet['scenario']} »)"]
    if sheet.get("start_time"):
        lines.append(f"Départ : {sheet['start_time']}")
    if sheet["waypoints"]:
        lines.append("Points de passage (temps d'arrêt à saisir) :")
        for w in sheet["waypoints"]:
            when = f"arrivée {w['arrival']}" + (f" ({w['clock']})" if w.get("clock") else "")
            stop = "arrivée de course" if w["finish"] else f"arrêt {w['stop']}"
            lines.append(f"  km {w['km']:g} — {w['name']} : {when}, {stop}")
    lines.append("Allures par segment (référence pour « Expand and Edit ») :")
    for r in sheet["segments"]:
        lines.append(f"  km {r['km_start']:.1f}-{r['km_end']:.1f} : {r['pace']} ({r['time']}, "
                     f"pente {r['grade_mean_pct']:+.1f} %)")
    lines += [f"Note : {n}" for n in sheet["notes"]]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p_sec = sub.add_parser("section", help="une section depuis une cible personnelle")
    p_sec.add_argument("--type", dest="section_type", choices=tuple(SECTION_TYPES), default="training")
    goal = p_sec.add_mutually_exclusive_group(required=True)
    goal.add_argument("--duration-s", type=float)
    goal.add_argument("--distance-m", type=float)
    goal.add_argument("--climb-m", type=float)
    target = p_sec.add_mutually_exclusive_group()
    target.add_argument("--hr", nargs=2, type=float, metavar=("BAS", "HAUT"), help="plage FC (bpm)")
    target.add_argument("--speed-ms", nargs=2, type=float, metavar=("BAS", "HAUT"),
                        help="plage de vitesse (m/s, telle que rendue par arc_workout_targets.py)")
    p_val = sub.add_parser("validate", help="vérifie une course (JSON sur l'entrée standard ou --file)")
    p_val.add_argument("--file")
    p_thr = sub.add_parser("threshold", help="allure seuil COROS (M:SS /km) -> m/s pour --lt-speed-ms")
    p_thr.add_argument("--pace", required=True, help="« Threshold Pace » de queryFitnessAssessmentOverview, ex. 4:12")
    p_ps = sub.add_parser("pace-strategy", help="fiche Pace Strategy COROS depuis un plan de course")
    p_ps.add_argument("--plan", required=True, help="plan de course au contrat (planning/…md, bloc race_plan)")
    p_ps.add_argument("--scenario", choices=("safe", "realistic", "ambitious"),
                      help="défaut : celui du temps visé du plan, sinon realistic")
    p_ps.add_argument("--text", action="store_true", help="fiche lisible au lieu du JSON")
    args = ap.parse_args(argv)

    if args.command == "pace-strategy":
        try:
            sheet = pace_strategy(load_race_plan(args.plan), args.scenario)
        except ValueError as exc:
            print(f"erreur : {exc}", file=sys.stderr)
            return 2
        print(pace_strategy_text(sheet) if args.text else json.dumps(sheet, ensure_ascii=False, indent=2))
        return 0

    if args.command == "threshold":
        try:
            speed = pace_to_speed_ms(args.pace)
        except ValueError as exc:
            print(f"erreur : {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"lt_speed_ms": speed, "pace_s_per_km": round(1000.0 / speed), "source": "COROS"}))
        return 0

    if args.command == "section":
        try:
            out = section(section_type=args.section_type, duration_s=args.duration_s,
                          distance_m=args.distance_m, climb_m=args.climb_m,
                          hr_bpm=args.hr, speed_ms=args.speed_ms)
        except ValueError as exc:
            print(f"erreur : {exc}", file=sys.stderr)
            return 2
        print(json.dumps(out, ensure_ascii=False))
        return 0

    try:
        raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
        course = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2
    errors = validate_course(course)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
