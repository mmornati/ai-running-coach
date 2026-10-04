#!/usr/bin/env python3
"""Roadbook imprimable d'un plan de course (#187, épopée #170) — modèle de données PUR.

Construit, à partir du plan de course PERSISTÉ (`planning/*`, bloc `arc` `kind: race_plan` :
`segments`, `aid_stations`, `start_time`, `gear`, `notes`…), le modèle compact que la page
« Roadbook » du tableau de bord affiche et imprime (`/api/roadbook`). Aucune arithmétique de
passage n'est réinventée ici : les heures de passage et les marges de barrière viennent de
`arc_race_pacing.compute_passages` / `check_cutoffs` (la MÊME source que le plan et le débrief).

    arc_roadbook.build_roadbook(plan_data, plan_path=…, gear_check=…) -> dict

Ce que le roadbook ne fait PAS (et dit explicitement quand c'est le cas, via `missing`) :
- inventer une valeur absente du plan (heure de départ, barrière, matériel, ce qu'on prend à un
  ravito) : la clé est omise et un message en français le signale ;
- afficher une altitude absolue : le plan persiste D+/D- par segment, pas l'altitude — le profil
  est donc RELATIF au départ (cumul D+ - D-), jamais présenté comme une altitude réelle.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_race_pacing as RP  # noqa: E402
import arc_solar as SOLAR  # noqa: E402

SCENARIOS = RP.SCENARIOS                      # ("safe", "realistic", "ambitious")
DEFAULT_SCENARIO = "realistic"

# Seuil au-delà duquel une section est dite « de nuit complète » (le reste, > 0, « partielle ») :
# les fractions de nuit viennent de `arc_race_pacing.apply_night_penalty`, par segment.
NIGHT_FULL_FRACTION = 0.95

ASSUMPTIONS = {
    "passages": (
        "Heures de passage et marges de barrière = `arc_race_pacing.compute_passages`/`check_cutoffs` "
        "(minute arrondie, arrêts ravito compris) : un ravito est rattaché à la fin du segment qui le "
        "contient, donc l'heure peut différer de quelques minutes d'un passage interpolé au mètre."),
    "sections": (
        "Une section va d'un point à l'autre (départ, ravitos, arrivée). Son D+/D- est la somme des "
        "segments qu'elle recouvre, répartie au prorata de la distance pour un segment à cheval sur "
        "un ravito — approximation du projet. Sans ravito, la section est le segment lui-même."),
    "profile": (
        "Profil RELATIF au départ (D+ cumulé moins D- cumulé) : le plan ne persiste pas l'altitude "
        "absolue. Axe en mètres relatifs, jamais une altitude réelle."),
    "clock": (
        "Heures de passage à l'horloge = départ + temps écoulé compté en temps ABSOLU (UTC) puis "
        "affiché dans le fuseau `timezone` du plan : juste après un changement d'heure en pleine "
        "course. Sans `timezone` (ou fuseau inconnu), simple addition à l'heure murale du départ. "
        "Les marges de barrière sont celles d'`arc_race_pacing.check_cutoffs`, calculées dans le même "
        "fuseau, en temps absolu (#205) : justes aussi après un changement d'heure."),
    "night": (
        "Le drapeau nuit d'une section reprend `night_fraction` des segments (#184) pondéré par leur "
        "temps ; absent du plan (course sans nuit, ou plan d'avant #184), aucune nuit n'est déduite."),
}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text_list(value: Any) -> List[str]:
    """Liste de textes non vides, qu'on ait écrit une chaîne ou une liste (jamais d'invention)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, (str, int, float)) and str(v).strip()]


def _zone(plan: dict):
    """Fuseau IANA du plan (`timezone`, #184) ou `None` (absent, inconnu, base tz absente)."""
    name = plan.get("timezone")
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        return SOLAR.resolve_timezone(name.strip())
    except ValueError:
        return None


def _parse_start(plan: dict, zone=None) -> Optional[datetime]:
    """Heure de départ en HEURE MURALE locale (naïve) : `start_time` ISO complet, ou `HH:MM`
    associé à `race_date`. Un `start_time` avec décalage (`Z`, `+01:00`) est d'abord ramené dans
    le fuseau du plan quand il est connu (`…T16:00Z` = 18:00 à Paris l'été), sinon son heure murale
    est gardée telle quelle. Rien d'autre n'est deviné (pas de 07:00 par défaut)."""
    raw = plan.get("start_time")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is not None and zone is not None:
            parsed = parsed.astimezone(zone)
        return parsed.replace(tzinfo=None)
    try:
        hh, mm = RP._parse_hhmm(raw.strip(), label="start_time")
        base = datetime.fromisoformat(str(plan.get("race_date")))
    except (ValueError, TypeError):
        return None
    return base.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _local(start_dt: datetime, elapsed_s: float, zone=None) -> datetime:
    """Heure locale (naïve) de départ + `elapsed_s` : en temps absolu dans `zone` quand il est
    connu (changement d'heure en course, comme la nuit de #184), sinon addition murale."""
    if zone is None:
        return start_dt + timedelta(seconds=elapsed_s)
    start_utc = start_dt.replace(tzinfo=zone).astimezone(timezone.utc)
    return (start_utc + timedelta(seconds=elapsed_s)).astimezone(zone).replace(tzinfo=None)


def _clock(start_dt: Optional[datetime], elapsed_s: Optional[float], zone=None) -> Optional[str]:
    if start_dt is None or elapsed_s is None:
        return None
    dt = _local(start_dt, elapsed_s, zone)
    days = (dt.date() - start_dt.date()).days
    return dt.strftime("%H:%M") + (f" (J+{days})" if days > 0 else "")


def _valid_segments(plan: dict) -> List[dict]:
    out = []
    for seg in plan.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        if _num(seg.get("km_start")) is None or _num(seg.get("km_end")) is None:
            continue
        out.append(seg)
    return sorted(out, key=lambda s: s["km_start"])


def _available_scenarios(segments: Sequence[dict]) -> List[str]:
    """Un scénario n'est exploitable que si CHAQUE segment porte son temps prédit (sinon le cumul
    serait faux : `compute_passages` compte 0 pour un temps absent)."""
    if not segments:
        return []
    return [s for s in SCENARIOS
            if all(isinstance(seg.get("predicted_time_s"), dict)
                   and _num(seg["predicted_time_s"].get(s)) is not None for seg in segments)]


def _cum_at(segments: Sequence[dict], km: float, key: str) -> float:
    """Cumul de `key` (elevation_gain_m / elevation_loss_m) jusqu'à `km`, au prorata de la
    distance dans le segment à cheval."""
    total = 0.0
    for seg in segments:
        a, b = seg["km_start"], seg["km_end"]
        v = _num(seg.get(key)) or 0.0
        if km >= b:
            total += v
        elif km > a and b > a:
            total += v * (km - a) / (b - a)
    return total


def _profile(segments: Sequence[dict]) -> Optional[dict]:
    if not segments:
        return None
    pts = [[round(segments[0]["km_start"], 3), 0.0]]
    elev = 0.0
    for seg in segments:
        elev += (_num(seg.get("elevation_gain_m")) or 0.0) - (_num(seg.get("elevation_loss_m")) or 0.0)
        pts.append([round(seg["km_end"], 3), round(elev, 1)])
    return {"points": pts, "relative": True}


def _elev_at(points: Sequence[Sequence[float]], km: float) -> float:
    if km <= points[0][0]:
        return points[0][1]
    for (k0, e0), (k1, e1) in zip(points, points[1:]):
        if k0 <= km <= k1:
            return e0 if k1 == k0 else e0 + (e1 - e0) * (km - k0) / (k1 - k0)
    return points[-1][1]


def _night_fraction(segments: Sequence[dict], scenario: str, a: float, b: float) -> float:
    """Part de nuit (0-1) de [a, b] km, pondérée par le temps prédit de chaque segment recouvert."""
    num = den = 0.0
    for seg in segments:
        s0, s1 = seg["km_start"], seg["km_end"]
        overlap = min(b, s1) - max(a, s0)
        if overlap <= 0 or s1 <= s0:
            continue
        t = (_num(seg["predicted_time_s"].get(scenario)) or 0.0) * overlap / (s1 - s0)
        nf = seg.get("night_fraction")
        f = _num(nf.get(scenario)) if isinstance(nf, dict) else None
        num += t * (f or 0.0)
        den += t
    return num / den if den > 0 else 0.0


def _night_spans(segments: Sequence[dict], scenario: str) -> List[List[float]]:
    spans: List[List[float]] = []
    for seg in segments:
        nf = seg.get("night_fraction")
        f = _num(nf.get(scenario)) if isinstance(nf, dict) else None
        if f and f > 0:
            if spans and abs(spans[-1][1] - seg["km_start"]) < 1e-6:
                spans[-1][1] = round(seg["km_end"], 3)
            else:
                spans.append([round(seg["km_start"], 3), round(seg["km_end"], 3)])
    return spans


def _stations(plan: dict) -> List[dict]:
    out = []
    for st in plan.get("aid_stations") or []:
        if isinstance(st, dict) and _num(st.get("km")) is not None:
            out.append(st)
    return sorted(out, key=lambda a: a["km"])


def _station_info(st: dict) -> dict:
    info: Dict[str, Any] = {"name": st.get("name") or f"km {st['km']:g}"}
    services = _text_list(st.get("services"))
    take = _text_list(st.get("take"))
    if services:
        info["services"] = services
    if take:
        info["take"] = take
    return info


def _cutoff_entry(cut: Optional[dict], scenario: str, st: dict) -> Optional[dict]:
    if not cut or scenario not in cut:
        return None
    entry = {"text": st.get("cutoff"), **cut[scenario]}
    if st.get("cutoff_day"):
        entry["day"] = st["cutoff_day"]
    return entry


def _scenario_block(plan: dict, segments: Sequence[dict], stations: Sequence[dict], scenario: str,
                    passages: dict, cutoffs: Sequence[dict], start_dt: Optional[datetime],
                    total_km: float, warnings: List[str], zone=None) -> dict:
    total_s = passages["totals_s"][scenario]
    seg_pass = passages["aid_station_passages"]
    cut_by_km = {round(c["km"], 6): c for c in cutoffs}
    bounds: List[dict] = [{"km": segments[0]["km_start"], "name": "Départ", "arrival_s": 0.0, "stop_s": 0.0}]
    for st, ps in zip(stations, seg_pass):
        stop = _num(st.get("stop_s"))
        stop = RP.DEFAULT_AID_STATION_STOP_S if stop is None else stop
        bounds.append({"km": min(st["km"], total_km), "name": _station_info(st)["name"], "st": st,
                       "arrival_s": float(ps[scenario]), "stop_s": float(stop)})
    bounds.append({"km": total_km, "name": "Arrivée", "arrival_s": float(total_s), "stop_s": 0.0})
    # Sans ravito, la section est le segment (un seul bloc Départ -> Arrivée serait peu lisible).
    if not stations and len(segments) > 1:
        cum = 0.0
        bounds = [{"km": segments[0]["km_start"], "name": "Départ", "arrival_s": 0.0, "stop_s": 0.0}]
        for seg in segments:
            cum += _num(seg["predicted_time_s"][scenario]) or 0.0
            bounds.append({"km": seg["km_end"], "name": f"km {seg['km_end']:.1f}".replace(".", ","),
                           "arrival_s": float(RP._round_passage(cum)), "stop_s": 0.0})
        bounds[-1]["name"] = "Arrivée"
        bounds[-1]["arrival_s"] = float(total_s)
    sections = []
    for prev, cur in zip(bounds, bounds[1:]):
        a, b = prev["km"], cur["km"]
        moving = max(0.0, cur["arrival_s"] - (prev["arrival_s"] + prev["stop_s"]))
        nf = _night_fraction(segments, scenario, a, b)
        row: Dict[str, Any] = {
            "from_km": round(a, 3), "to_km": round(b, 3), "from_name": prev["name"], "to_name": cur["name"],
            "distance_m": round((b - a) * 1000.0, 1),
            "gain_m": round(_cum_at(segments, b, "elevation_gain_m") - _cum_at(segments, a, "elevation_gain_m"), 1),
            "loss_m": round(_cum_at(segments, b, "elevation_loss_m") - _cum_at(segments, a, "elevation_loss_m"), 1),
            "moving_s": round(moving), "arrival_s": round(cur["arrival_s"]),
        }
        clock = _clock(start_dt, cur["arrival_s"], zone)
        if clock:
            row["arrival_clock"] = clock
        if cur.get("st") is not None:
            row["station"] = _station_info(cur["st"])
            row["stop_s"] = round(cur["stop_s"])
            dep = _clock(start_dt, cur["arrival_s"] + cur["stop_s"], zone)
            if dep:
                row["departure_clock"] = dep
            cutoff = _cutoff_entry(cut_by_km.get(round(cur["st"]["km"], 6)), scenario, cur["st"])
            if cutoff:
                row["cutoff"] = cutoff
        if nf > 0:
            row["night"] = "full" if nf >= NIGHT_FULL_FRACTION else "partial"
            row["night_fraction"] = round(nf, 2)
        sections.append(row)
    block: Dict[str, Any] = {
        "available": True, "total_s": round(total_s), "sections": sections,
        "night_spans_km": _night_spans(segments, scenario),
        "lamp_sections": sum(1 for r in sections if r.get("night")),
    }
    finish = _clock(start_dt, total_s, zone)
    if finish:
        block["finish_clock"] = finish
    return block


def _gear_block(gear_check: Optional[dict], plan: dict) -> Optional[dict]:
    declared = plan.get("gear")
    if not isinstance(declared, list) or not declared:
        return None
    if not gear_check or gear_check.get("error"):
        return {"entries": [{"entry": str(g.get("name") if isinstance(g, dict) else g), "status": "unchecked"}
                            for g in declared if str(g.get("name") if isinstance(g, dict) else g).strip()],
                "inventory_checked": False}
    return {
        "entries": [{"entry": e["entry"], "status": e["status"],
                     "items": [m.get("name") for m in e.get("matches") or [] if m.get("name")]}
                    for e in gear_check.get("entries") or []],
        "inventory_checked": not gear_check.get("inventory_empty", False),
    }


def build_roadbook(plan: dict, *, plan_path: Optional[str] = None,
                   gear_check: Optional[dict] = None) -> dict:
    """Modèle du roadbook d'UN plan de course persisté (`plan` = bloc `arc` décodé). Rend
    `{"status": "ok", …}` ; chaque donnée absente du plan est omise ET listée dans `missing`."""
    missing: List[str] = []
    warnings: List[str] = []
    segments = _valid_segments(plan)
    stations = _stations(plan)
    zone = _zone(plan)
    start_dt = _parse_start(plan, zone)
    if start_dt is None:
        missing.append("heure de départ absente du plan (`start_time`) : pas d'heures de passage "
                       "à l'horloge, seulement des durées depuis le départ")
    if not segments:
        missing.append("aucun segment dans le plan (course analysée sans GPX) : pas de sections "
                       "chronométrées, ni de profil, ni de D+ par section")

    avail = _available_scenarios(segments)
    for s in SCENARIOS:
        if segments and s not in avail:
            missing.append(f"scénario « {s} » incomplet dans les segments du plan : non affiché")

    total_km = segments[-1]["km_end"] if segments else None
    header: Dict[str, Any] = {"race_name": plan.get("race_name"), "race_date": plan.get("race_date")}
    if start_dt is not None:
        header["start_clock"] = start_dt.strftime("%H:%M")
    if plan.get("timezone"):
        header["timezone"] = plan["timezone"]
    header["distance_m"] = _num(plan.get("distance_m")) or (round(total_km * 1000.0, 1) if total_km else None)
    header["elevation_gain_m"] = _num(plan.get("elevation_gain_m")) or (
        round(_cum_at(segments, total_km, "elevation_gain_m"), 1) if segments else None)
    if segments:
        header["elevation_loss_m"] = round(_cum_at(segments, total_km, "elevation_loss_m"), 1)
    header = {k: v for k, v in header.items() if v is not None}

    scenarios: Dict[str, Any] = {}
    if avail:
        passages = RP.compute_passages(segments, stations)
        for p in passages["aid_station_passages"]:
            if p.get("note"):
                warnings.append(p["note"])
        cutoffs: List[dict] = []
        if stations and any(st.get("cutoff") for st in stations):
            if start_dt is None:
                missing.append("barrières horaires présentes mais heure de départ inconnue : marges non calculées")
            else:
                cutoffs = RP.check_cutoffs(passages["aid_station_passages"], stations, start_dt, zone)
                if zone is None and RP.has_offset_cutoff(stations):
                    missing.append("barrière horaire avec décalage mais fuseau du plan (`timezone`) inconnu : "
                                   "marge comparée à l'heure murale de la barrière")
        elif stations:
            missing.append("aucune barrière horaire renseignée sur les ravitos du plan")
        for s in avail:
            scenarios[s] = _scenario_block(plan, segments, stations, s, passages, cutoffs, start_dt,
                                           total_km, warnings, zone)
        if zone is not None and start_dt is not None:
            longest = max(passages["totals_s"][s] for s in avail)
            off0 = start_dt.replace(tzinfo=zone).utcoffset()
            off1 = _local(start_dt, longest, zone).replace(tzinfo=zone).utcoffset()
            if off0 != off1:
                warnings.append(
                    "changement d'heure pendant la course : heures de passage et marges de barrière "
                    "en heure locale réelle")
        for s in SCENARIOS:
            if s not in scenarios:
                scenarios[s] = {"available": False}
    else:
        for s in SCENARIOS:
            scenarios[s] = {"available": False}
    targets = plan.get("scenarios") if isinstance(plan.get("scenarios"), dict) else {}
    for s in SCENARIOS:
        t = _num(targets.get(s))
        if t is not None:
            scenarios[s]["target_s"] = round(t)
    if _num(plan.get("target_time_s")) is not None:
        header["target_time_s"] = round(plan["target_time_s"])

    profile = _profile(segments)
    markers = []
    if profile:
        for st in stations:
            km = min(st["km"], total_km)
            markers.append({"km": round(km, 3), "name": _station_info(st)["name"],
                            "elev_m": round(_elev_at(profile["points"], km), 1)})
        profile["aid_stations"] = markers
    water = [{"km": w["km"], "name": w.get("name"), "source": w.get("source")}
             for w in plan.get("water_points") or [] if isinstance(w, dict) and _num(w.get("km")) is not None]

    if stations and not any(_station_info(st).get("take") for st in stations):
        missing.append("ce qu'on prend à chaque ravito n'est pas renseigné (`take` des aid_stations) : "
                       "voir le plan nutrition, rien n'est déduit ici")
    if not stations and segments:
        missing.append("aucun ravito dans le plan : sections = segments")

    gear = _gear_block(gear_check, plan)
    if gear is None:
        missing.append("aucun matériel obligatoire (`gear`) déclaré dans le plan")
    lamp_needed = any(b.get("lamp_sections") for b in scenarios.values() if b.get("available"))
    if lamp_needed and gear is not None and not any(
            any(w in e["entry"].lower() for w in ("frontale", "lampe", "headlamp")) for e in gear["entries"]):
        warnings.append("de la nuit est prévue mais aucune frontale n'est listée dans le matériel du plan")
    if lamp_needed and gear is None:
        warnings.append("de la nuit est prévue : pense à la frontale et à ses piles de rechange")

    notes = _text_list(plan.get("notes"))
    emergency = _text_list(plan.get("emergency"))
    if not emergency:
        missing.append("aucune consigne d'urgence (`emergency`) dans le plan")

    return {
        "status": "ok", "plan": plan_path, "header": header, "profile": profile, "water_points": water,
        "scenarios": scenarios, "default_scenario": DEFAULT_SCENARIO if DEFAULT_SCENARIO in avail
        else (avail[0] if avail else DEFAULT_SCENARIO),
        "gear": gear, "notes": notes, "emergency": emergency,
        "nutrition_plan": plan.get("nutrition_plan") if isinstance(plan.get("nutrition_plan"), str) else None,
        "missing": missing, "warnings": warnings, "assumptions": ASSUMPTIONS,
    }
