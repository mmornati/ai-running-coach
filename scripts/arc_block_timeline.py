#!/usr/bin/env python3
"""Frise du bloc planifié (#193) — fonctions pures, sans E/S (stdlib).

Alimente `/api/block` du tableau de bord (frise des phases dans « Semaine » et « Calendrier »).
Une semaine est lue telle qu'écrite dans `planning/` : on ne DEVINE jamais une phase. Le champ
`phase` du contrat est du texte libre (le squelette #190 y écrit le libellé français du gabarit :
« Base », « Développement », « Spécifique », « Affûtage », « Récupération ») ; il n'est reconnu
que s'il correspond EXACTEMENT à l'un de ces libellés (ou à son identifiant anglais, accents et
casse ignorés). Tout autre texte est rendu tel quel dans une bande « autre » ; l'absence de
phase donne une bande « phase inconnue ».
"""

from __future__ import annotations

import unicodedata
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

PHASE_IDS = ("base", "development", "specific", "taper", "recovery")
# Libellés d'affichage — identiques à `arc_plan_templates.PHASE_LABELS_FR` (non importé : ce module
# reste sans dépendance ; un test verrouille la concordance).
PHASE_LABELS_FR = {"base": "Base", "development": "Développement", "specific": "Spécifique",
                   "taper": "Affûtage", "recovery": "Récupération"}
# Types de semaine du contrat (`arc_contract.WEEK_TYPE`) tenus pour « allégés » dans la frise.
RECOVERY_TYPES = ("recovery", "post_race")
UNKNOWN = "unknown"
OTHER = "other"
# Semaine sans fichier comblée à l'intérieur d'un bloc du squelette (voir `ASSUMPTIONS["bloc"]`).
MISSING = "missing"

ASSUMPTIONS = {
    "reconnaissance": (
        "La phase d'une semaine n'est reconnue que par correspondance EXACTE avec un libellé du gabarit "
        "(accents et casse ignorés). Un texte libre différent (« Base spécifique ») reste affiché tel quel, "
        "classé « autre » : la frise n'invente jamais de phase."),
    "bloc": (
        "Bloc = suite de semaines planifiées aux lundis consécutifs. On retient celle qui contient la "
        "semaine courante, sinon la prochaine à venir, sinon la plus récente. Convention de ce projet : "
        "UNE semaine sans fichier ne coupe pas le bloc si ses deux voisines viennent du squelette de bloc "
        "(champ `week_type` renseigné, #190) — semaine de vacances, fichier supprimé ; elle est tracée "
        "« semaine sans plan », jamais remplie. Deux semaines manquantes, ou une voisine écrite à la main "
        "(sans `week_type`), coupent le bloc."),
    "realise": "Volume réalisé = somme des activités (hors repos) du lundi au dimanche ; partiel pour la semaine en cours.",
}


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in folded if unicodedata.category(c) != "Mn")


_ALIASES: Dict[str, str] = {}
for _pid, _label in PHASE_LABELS_FR.items():
    _ALIASES[_norm(_label)] = _pid
    _ALIASES[_pid] = _pid


def classify_phase(text: Optional[str]) -> str:
    """Identifiant canonique, `OTHER` (texte libre non reconnu) ou `UNKNOWN` (rien d'écrit)."""
    if text is None or not str(text).strip():
        return UNKNOWN
    return _ALIASES.get(_norm(str(text)), OTHER)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def select_block(week_starts: List[str], today: date, bridgeable: Iterable[str] = ()) -> List[str]:
    """Lundis (ISO) du bloc retenu parmi les semaines planifiées (voir `ASSUMPTIONS["bloc"]`).

    `bridgeable` : lundis des semaines issues du squelette (`week_type` renseigné). Un trou d'UNE
    semaine entre deux d'entre elles est comblé : son lundi figure dans la liste rendue (sans fichier)."""
    days = sorted({date.fromisoformat(w) for w in week_starts})
    bridge = {date.fromisoformat(w) for w in bridgeable}
    runs: List[List[date]] = []
    for d in days:
        gap = d - runs[-1][-1] if runs else None
        if gap == timedelta(days=7):
            runs[-1].append(d)
        elif gap == timedelta(days=14) and d in bridge and runs[-1][-1] in bridge:
            runs[-1].extend([d - timedelta(days=7), d])
        else:
            runs.append([d])
    if not runs:
        return []
    current = _monday(today)
    chosen = next((r for r in runs if r[0] <= current <= r[-1]), None)
    if chosen is None:
        chosen = next((r for r in runs if r[0] > current), runs[-1])
    return [d.isoformat() for d in chosen]


def block_bridgeable(weeks: List[dict]) -> List[str]:
    """Lundis des semaines issues du squelette (`week_type` renseigné) — voir `select_block`."""
    return [w["week_start"] for w in weeks if w.get("week_start") and w.get("week_type")]


def build(weeks: List[dict], done_by_week: Dict[str, dict], race_date: Optional[str], today: date,
          race_name: Optional[str] = None) -> dict:
    """Frise : `weeks` = lignes `week` non éclipsées ; `done_by_week` : lundi ISO ->
    `{duration_s, distance_m, elevation_m, sessions}` réalisés."""
    by_start = {w["week_start"]: w for w in weeks if w.get("week_start")}
    starts = select_block(list(by_start), today, block_bridgeable(weeks))
    current = _monday(today).isoformat()
    race = None
    race_monday = None
    if race_date:
        try:
            race = date.fromisoformat(race_date)
            race_monday = _monday(race).isoformat()
        except ValueError:
            race = None
    out = []
    for ws in starts:
        w = by_start.get(ws)
        planned = w is not None
        w = w or {}
        phase_text = (w.get("phase") or "").strip() or None
        pid = classify_phase(phase_text) if planned else MISSING
        wtype = w.get("week_type")
        status = "current" if ws == current else ("past" if ws < current else "future")
        label = {MISSING: "Semaine sans plan", OTHER: phase_text}.get(pid, "Phase inconnue")
        item = {
            "week_start": ws, "status": status, "planned": planned, "phase": pid, "phase_text": phase_text,
            "phase_label": PHASE_LABELS_FR.get(pid, label),
            "week_type": wtype, "light": wtype in RECOVERY_TYPES or pid == "recovery",
            "is_race_week": ws == race_monday,
            "target_duration_s": w.get("target_duration_s"), "target_distance_m": w.get("target_distance_m"),
            "target_elevation_m": w.get("target_elevation_m"),
        }
        if ws <= current:
            done = done_by_week.get(ws) or {}
            item["done"] = {"duration_s": done.get("duration_s") or 0, "distance_m": done.get("distance_m") or 0,
                            "elevation_m": done.get("elevation_m") or 0, "sessions": done.get("sessions") or 0,
                            "partial": ws == current}
        out.append(item)
    payload = {"status": "ok" if out else "no_plan", "today": today.isoformat(), "current_week_start": current,
               "weeks": out, "phases": [{"id": i, "label": PHASE_LABELS_FR[i]} for i in PHASE_IDS],
               "unknown_weeks": sum(1 for w in out if w["phase"] == UNKNOWN),
               "missing_weeks": sum(1 for w in out if not w["planned"]),
               "race": None}
    if race is not None:
        payload["race"] = {"date": race.isoformat(), "name": race_name, "week_start": race_monday,
                           "in_block": race_monday in starts,
                           "days_left": (race - today).days}
    if not out:
        payload["reason"] = "Aucune semaine planifiée au contrat dans planning/."
    return payload
