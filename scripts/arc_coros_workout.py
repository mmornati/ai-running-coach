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

Aucune dépendance hors bibliothèque standard, aucun appel réseau.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Sequence

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
    args = ap.parse_args(argv)

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
