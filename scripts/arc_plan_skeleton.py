#!/usr/bin/env python3
"""Squelette de bloc d'entraînement semaine par semaine (#190, épopée #173).

## Pourquoi

#189 range la périodisation dans des gabarits (`config/plans/*.json`) : une FORME en
pourcentages d'une semaine pic. Ce module la transforme en un squelette DATÉ, de la semaine
en cours à la semaine de course (puis la récupération post-course), à partir de :

- la date de course et la date du jour (`today`) ;
- le volume (durée) et le D+ que l'athlète TIENT réellement (4 dernières semaines complètes,
  lues dans l'index) — jamais un volume inventé : pic = volume tenu × `peak_from_current` ;
- la disponibilité du profil (séances par semaine, heures max, jours impossibles) ;
- les garde-fous (`arc_guardrails`), qui jugent CHAQUE semaine générée.

Le squelette n'est PAS un plan détaillé : chaque semaine porte des objectifs (volume, D+,
nombre de séances de qualité, sortie longue visée, répartition d'intensité, emphase de
renforcement) et des CRÉNEAUX de séance (`placeholder: true`) posés sur les jours
disponibles. Le coach les habille (contenu, allures, cibles) ; il reste maître du plan.

## Unités

Le volume se compte en DURÉE (secondes, affichée en heures) : c'est ce que R2 compare
(`arc_guardrails._eval_r2`), et ce que les séances prescrivent (`planned_duration_s`). Le D+ est
en mètres (trail). Sur route, la distance planifiée de chaque créneau se déduit de l'allure
moyenne tenue (distance / durée des 4 semaines) — R2 compare aussi la distance en route. Le
volume du squelette est celui de la COURSE À PIED : le renforcement s'ajoute, hors R2.

## Cas particuliers (déterministes, jamais cachés)

- Moins de semaines que `weeks.min` du gabarit → `status: "too_short"`, aucune semaine
  générée, options explicites (format plus court, date de course plus tardive, bloc sans
  gabarit). Jamais de compression sous les minima.
- Plus de semaines que `weeks.max` → `lead_in_weeks` semaines de mise en route AVANT le
  gabarit, au volume tenu (semaine allégée tous les N comme le gabarit) ; le gabarit
  démarre alors sur son dernier `weeks.max` semaines.
- Pas d'historique exploitable (< `MIN_HELD_DURATION_S` par semaine en moyenne) →
  `status: "no_history"` : l'athlète déclare son volume (`--held-hours`), jamais inventé.
- La semaine en cours est déjà entamée (`today` ≠ lundi) → le squelette démarre lundi
  prochain ; la semaine en cours est SUPPOSÉE au volume tenu dans la référence R2/R3.

## Garde-fous

Chaque semaine passe `arc_guardrails.evaluate` (la fonction du moteur, pas une copie), sur un
contexte dont la référence R2/R3 (`mean4`/`previous_week`, comme le workspace) est celle de la
CHAÎNE réelle + semaines déjà générées (une semaine 9 se compare aux semaines 5 à 8 du
squelette, pas à l'historique réel). Les séances des semaines précédentes alimentent la
projection ACWR (R1/R4) comme le fait `check --week` sur un plan multi-semaines (#69).
Une violation R2/R3 réduit la semaine (facteur tiré du verdict lui-même) ; une violation
`block` retire la qualité puis réduit ; si le blocage persiste, la semaine n'est PAS émise
(`unresolved`) et le statut devient `needs_review`. Un squelette ne contient donc jamais de
semaine `block`. Les `warn`/`info` restants (R1, R4, R6, R7…) sont rendus tels quels.

Bibliothèque standard uniquement (CONTRIBUTING.md). Pur sauf `held_from_index`,
`default_context_factory` et `write_weeks` (E/S).
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arc_contract as C  # noqa: E402
import arc_guardrails as G  # noqa: E402
import arc_plan_templates as PT  # noqa: E402

SCHEMA_VERSION = 1

STATUS_OK = "ok"
STATUS_TOO_SHORT = "too_short"
STATUS_NO_HISTORY = "no_history"
STATUS_NO_OBJECTIVE = "no_objective"
STATUS_NO_TEMPLATE = "no_template"
STATUS_PAST = "target_past"
STATUS_NEEDS_REVIEW = "needs_review"

# Types de semaine du squelette.
TYPE_BUILD, TYPE_RECOVERY, TYPE_TAPER = "build", "recovery", "taper"
TYPE_RACE, TYPE_LEAD_IN, TYPE_POST_RACE = "race", "lead_in", "post_race"

MIN_HELD_DURATION_S = 3600           # < 1 h/semaine en moyenne : pas un « volume tenu »
HELD_WEEKS = 4                       # = fenêtre de la référence R2/R3 `mean4`
DEFAULT_SESSIONS_PER_WEEK = 5        # profil muet sur la disponibilité (approximation du projet)
STRENGTH_SLOT_S = 40 * 60            # créneau de renforcement (approximation du projet)
EASY_WEIGHT = 0.8                    # poids d'une sortie facile face à une séance de qualité (1.0)
MIN_SESSIONS_FOR_STRENGTH = 4        # en dessous, tous les créneaux vont à la course à pied
MAX_RACE_WEEK_RUNS = 3               # footings de la semaine de course, course exclue
POST_RACE_REST_DAYS = 3              # jours sans créneau de course à pied après la course (approximation du projet)
CAP_MARGIN = 0.998                   # marge sous le seuil R2/R3 quand on réduit une semaine
MAX_ADJUST_ATTEMPTS = 6
LONG_RUN_FLOOR_FACTOR = 1.15         # plancher de la sortie longue face à une part égale
ROUND_S = 60                         # durées arrondies à la minute
ROUND_ELEV_M = 10                    # D+ arrondi à la dizaine de mètres

DAY_NAMES_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_DAY_ALIASES = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
    "lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

# Intensité du créneau de qualité par phase : un PLACEHOLDER pour la charge projetée (R1), que le
# coach remplace en habillant la séance.
QUALITY_INTENSITY = {"base": "tempo", "development": "threshold", "specific": "threshold", "taper": "tempo",
                     "recovery": "tempo"}

STRENGTH_LABELS_FR = {
    "force_maximale": "force maximale", "force_endurance": "force-endurance",
    "pliometrie_excentrique": "pliométrie / excentrique", "entretien": "entretien", "mobilite": "mobilité",
}
TYPE_LABELS_FR = {
    TYPE_BUILD: "Construction", TYPE_RECOVERY: "Allégée", TYPE_TAPER: "Affûtage", TYPE_RACE: "Course",
    TYPE_LEAD_IN: "Mise en route", TYPE_POST_RACE: "Récupération post-course",
}

ASSUMPTIONS = {
    "nature": (
        "Le squelette est une PROPOSITION déduite d'un gabarit (`arc_plan_templates.ASSUMPTIONS`, tous "
        "ses nombres sont des « approximations du projet ») et du volume tenu : le profil de l'athlète, "
        "le bilan matinal et les garde-fous priment. Les créneaux de séance ne sont pas des séances : "
        "le coach les habille."),
    "held_volume": (
        "Volume tenu = moyenne des 4 dernières semaines COMPLÈTES (lundi-dimanche) de la famille course à "
        "pied dans l'index (durée, D+, distance), la même fenêtre et la même famille que la référence R2/R3 "
        "`mean4` d'`arc_guardrails`. Pic = volume tenu × `peak_from_current` du gabarit (#189) : jamais "
        "plus. Si l'athlète déclare un volume (`--held-hours`/`--held-elevation-m`), il remplace l'index, "
        "et la source est dite `declared`."),
    "start_week": (
        "Le squelette démarre le lundi de la semaine en cours si `today` est un lundi, sinon le lundi "
        "suivant (la semaine en cours est déjà entamée : ses séances réelles et celles que le coach a "
        "déjà écrites ne sont pas écrasées). Cette semaine en cours est SUPPOSÉE au volume tenu dans la "
        "référence R2/R3 de la première semaine générée."),
    "lead_in": (
        "Plus de semaines que `weeks.max` : l'excédent devient des semaines de mise en route au volume "
        "tenu (le gabarit démarre justement à ce volume), avec une semaine allégée tous les N comme le "
        "gabarit, jamais la dernière avant le gabarit. Choix de conception du projet : un étirement du "
        "gabarit au-delà de ses bornes n'est pas vérifié par `validate_template`."),
    "availability": (
        "Disponibilité lue dans `planning/Runner_Profile.md` (« Disponibilité hebdomadaire » : nombre de "
        "séances et plus grande durée en heures citée ; « Jours impossibles » ; « Sortie longue » facultatif). "
        f"Profil muet : {DEFAULT_SESSIONS_PER_WEEK} séances par semaine, sortie longue le dimanche (sinon le "
        "samedi), aucun plafond d'heures. Avec ≥ 4 séances, une est réservée au renforcement. Une journée "
        "partiellement impossible (« dimanche matin ») est comptée impossible : prudent. Un pic au-delà du "
        "plafond d'heures est ramené à ce plafond et signalé."),
    "slots": (
        f"Créneaux : sortie longue visée = part du gabarit (plafonnée en minutes) du volume ; le reste est "
        f"réparti entre séances de qualité (poids 1,0) et sorties faciles (poids {EASY_WEIGHT}), arrondi à la "
        "minute ; la sortie longue vaut au moins "
        f"{LONG_RUN_FLOOR_FACTOR} × la part égale (avec peu de séances, elle reste la plus longue) ; D+ réparti au prorata de la durée, arrondi à 10 m, reliquat à la sortie longue. Séances de "
        "qualité jamais sur deux jours consécutifs, écartées de la sortie longue quand les jours le "
        "permettent (sinon moins de qualité, signalé). L'intensité d'un créneau de qualité est un "
        "PLACEHOLDER (tempo en base/affûtage, seuil ensuite) servant à la charge projetée. Créneau de "
        f"renforcement : {STRENGTH_SLOT_S // 60} min, hors volume course à pied. Semaine de course : jusqu'à "
        f"{MAX_RACE_WEEK_RUNS} footings avant la course, jamais la veille (laissée libre : repos ou "
        "déverrouillage court, au choix du coach), volume du gabarit hors course ramené au prorata des jours "
        "avant la course (jour de course / 6 : 6/6 un dimanche, 1/6 un mardi) ; le créneau de course porte la "
        f"distance/le D+ de l'objectif. Après la course : aucun créneau de course à pied pendant "
        f"{POST_RACE_REST_DAYS} jours, et la semaine concernée garde le volume du gabarit au prorata des jours "
        "restants. Choix prudents du projet (approximation du projet), pas un protocole publié."),
    "guardrails": (
        "Chaque semaine est évaluée par `arc_guardrails.evaluate`. R1/R4 reposent sur la charge PROJETÉE de "
        "créneaux dont l'intensité est un placeholder : lecture indicative. Une semaine réduite pour passer "
        "R2/R3 est signalée (`adjustments`) ; le facteur vient de la valeur observée dans le verdict, avec une "
        f"marge ({CAP_MARGIN}). Un `block` qui persiste après suppression de la qualité et réductions "
        "successives de 10 % exclut la semaine du squelette."),
}


class SkeletonError(ValueError):
    """Entrée invalide (date, option)."""


# ---------------------------------------------------------------------------
# Disponibilité (profil)
# ---------------------------------------------------------------------------


def _strip_accents(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def parse_day(text: Optional[str]) -> Optional[int]:
    """0 (lundi) … 6 (dimanche) depuis un nom de jour français/anglais ou une abréviation."""
    if not text:
        return None
    for token in re.findall(r"[a-z]+", _strip_accents(str(text))):
        if token in _DAY_ALIASES:
            return _DAY_ALIASES[token]
    return None


def _days_in(text: Optional[str]) -> List[int]:
    if not text:
        return []
    found = {_DAY_ALIASES[t] for t in re.findall(r"[a-z]+", _strip_accents(text)) if t in _DAY_ALIASES}
    return sorted(found)


def parse_availability(profile_text: Optional[str] = None, long_run_day: Optional[str] = None) -> dict:
    """Disponibilité depuis le texte du profil (`planning/Runner_Profile.md`), jamais en levant.

    Rend `{sessions_per_week, max_weekly_s, blocked_days, long_run_day, source, notes}` ; une clé
    inconnue vaut `None` (ou `[]`). `long_run_day` (option CLI) l'emporte sur le profil."""
    import arc_legacy as L
    out: Dict[str, Any] = {"sessions_per_week": None, "max_weekly_s": None, "blocked_days": [],
                           "long_run_day": None, "source": "default", "notes": []}
    bullets = L.parse_bullets(profile_text) if profile_text else {}
    avail = L._pick(bullets, "disponibilite hebdomadaire", "disponibilite")
    if avail:
        out["source"] = "profile"
        m = re.search(r"(\d+)\s*(?:seances?|sorties?|entrainements?)", _strip_accents(avail))
        if m:
            out["sessions_per_week"] = max(1, min(14, int(m.group(1))))
        hours = [int(h) * 3600 + (int(mn) * 60 if mn else 0)
                 for h, mn in re.findall(r"(\d+)\s*h(?:eures?)?\s*(\d{2})?", _strip_accents(avail))]
        if hours:
            out["max_weekly_s"] = max(hours)
    blocked = L._pick(bullets, "jours impossibles", "jours indisponibles")
    out["blocked_days"] = _days_in(blocked)
    chosen = long_run_day if long_run_day else L._pick(bullets, "sortie longue", "jour de sortie longue")
    parsed = parse_day(chosen)
    if parsed is not None:
        out["long_run_day"] = parsed
    elif chosen:
        out["notes"].append(f"jour de sortie longue « {chosen} » non reconnu : défaut du moteur.")
    if len(out["blocked_days"]) >= 6:
        out["notes"].append("six jours impossibles ou plus : disponibilité à confirmer avec l'athlète.")
    return out


# ---------------------------------------------------------------------------
# Volume tenu (index)
# ---------------------------------------------------------------------------


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def held_from_weeks(weeks: List[dict], source: str = "index") -> dict:
    """Résumé du volume tenu depuis 4 semaines `{duration_s, distance_m, elevation_gain_m}`."""
    n = len(weeks) or 1
    mean = {k: sum(w.get(k) or 0.0 for w in weeks) / n for k in ("duration_s", "distance_m", "elevation_gain_m")}
    return {"source": source, "weeks": weeks, "duration_s": mean["duration_s"], "distance_m": mean["distance_m"],
            "elevation_gain_m": mean["elevation_gain_m"],
            "has_any_activity": any(w.get("has_any_activity", True) for w in weeks)}


def held_from_index(conn, today: date) -> dict:
    """4 dernières semaines COMPLÈTES avant le lundi de `today`, famille course à pied."""
    current = _monday(today)
    weeks = []
    for i in range(HELD_WEEKS, 0, -1):
        start = current - timedelta(days=7 * i)
        totals = G._run_family_totals(conn, start, start + timedelta(days=6))
        weeks.append({"week_start": start.isoformat(), **totals})
    return held_from_weeks(weeks, "index")


def declared_held(hours: Optional[float], elevation_m: Optional[float], distance_km: Optional[float] = None) -> dict:
    week = {"duration_s": float(hours) * 3600.0 if hours else 0.0, "elevation_gain_m": float(elevation_m or 0.0),
            "distance_m": float(distance_km or 0.0) * 1000.0, "has_any_activity": bool(hours)}
    return held_from_weeks([dict(week) for _ in range(HELD_WEEKS)], "declared")


# ---------------------------------------------------------------------------
# Contexte des garde-fous
# ---------------------------------------------------------------------------


def synthetic_context(week_start: date, today: date, sport: str = "trail", morning_check: str = "full") -> dict:
    """Contexte minimal sans historique de charge (R1/R4 sautées « insufficient_history ») : tests,
    ou workspace sans index. La référence R2/R3 est surchargée par le squelette."""
    return {"week_start": week_start.isoformat(), "week_end": (week_start + timedelta(days=6)).isoformat(),
            "today": today.isoformat(), "sport_primary": sport, "morning_check": morning_check,
            "race_date": None, "is_race_week": False, "has_load_history": False, "loads_by_date": {},
            "week_activities": [], "recent_run_pace_s_km": None, "health_by_date": {}}


def default_context_factory(conn, config: dict, gconf: dict, today: date) -> Callable:
    """Fabrique le contexte réel (`arc_guardrails.build_context`) d'une semaine ; les semaines
    déjà générées servent de `other_weeks` (projection ACWR d'une semaine au-delà de la prochaine, #69).
    La semaine EN COURS (non générée : le squelette démarre lundi prochain) y entre aussi avec ses
    séances déjà planifiées dans l'index : sans elles, ses jours restants compteraient comme du repos
    complet dans la projection R1/R4 (le réel prime toujours, `_intervening_weeks_loads`)."""
    import arc_load_forecast as LF
    current = _monday(today)
    planned_now = LF._planned_weeks_from_index(conn, current, current + timedelta(days=6))

    def factory(week_start: date, prior_weeks: List[dict]) -> dict:
        others = [w for w in planned_now if w["week_start"] < week_start.isoformat()] + list(prior_weeks or [])
        return G.build_context(conn, config, gconf, week_start, today, others or None)
    return factory


def _reference(chain: List[dict], reference: str) -> dict:
    keys = ("duration_s", "distance_m", "elevation_gain_m")
    if reference == "previous_week":
        last = chain[-1]
        ref = {k: last.get(k) or 0.0 for k in keys}
    else:
        last4 = chain[-HELD_WEEKS:]
        ref = {k: sum(w.get(k) or 0.0 for w in last4) / HELD_WEEKS for k in keys}
    ref["has_any_activity"] = any((w.get("duration_s") or 0) > 0 for w in chain[-HELD_WEEKS:])
    return ref


# ---------------------------------------------------------------------------
# Créneaux d'une semaine
# ---------------------------------------------------------------------------


def _spread(avail: Sequence[int], k: int, anchor: int) -> List[int]:
    """`k` jours parmi `avail`, `anchor` inclus, aussi espacés que possible (déterministe)."""
    chosen = [anchor]
    rest = [d for d in avail if d != anchor]
    while len(chosen) < k and rest:
        best = max(rest, key=lambda d: (min(abs(d - c) for c in chosen), -d))
        chosen.append(best)
        rest.remove(best)
    return sorted(chosen)


def _place_quality(days: Sequence[int], long_day: Optional[int], q: int) -> List[int]:
    """Jours de qualité : jamais consécutifs ; écartés de la sortie longue si possible. Réduit `q`
    si les jours ne le permettent pas."""
    cands = [d for d in days if d != long_day]
    for count in range(min(q, len(cands)), 0, -1):
        best = None
        for combo in itertools.combinations(cands, count):
            if any(b - a == 1 for a, b in zip(combo, combo[1:])):
                continue
            pool = sorted(list(combo) + ([long_day] if long_day is not None else []))
            gap = min((b - a for a, b in zip(pool, pool[1:])), default=7)
            adjacent = sum(1 for d in combo if long_day is not None and abs(d - long_day) == 1)
            score = (adjacent, -gap, combo)
            if best is None or score < best[0]:
                best = (score, list(combo))
        if best:
            return best[1]
    return []


def _round(value: float, step: int) -> int:
    return int(round(value / step)) * step


def _split_duration(total_s: float, long_idx: Optional[int], roles: List[str], share_pct: float,
                    cap_min: float) -> List[int]:
    """Durées (s) des créneaux course à pied, dans l'ordre de `roles` (`long`/`quality`/`easy`)."""
    total = _round(total_s, ROUND_S)
    if not roles or total <= 0:
        return [0] * len(roles)
    durations = [0.0] * len(roles)
    remaining = float(total)
    if long_idx is not None:
        # La sortie longue doit rester la plus longue : avec peu de séances, la part du gabarit (pensée
        # pour ≥ 4 séances) ne suffit pas, d'où un plancher à 1,15 × la part égale (approximation du projet).
        floor_share = 100.0 / len(roles) * LONG_RUN_FLOOR_FACTOR
        long_s = min(total * max(share_pct, floor_share) / 100.0, cap_min * 60.0)
        if len(roles) == 1:
            long_s = total
        durations[long_idx] = long_s
        remaining = total - long_s
    weights = [(1.0 if r == "quality" else EASY_WEIGHT) if i != long_idx else 0.0 for i, r in enumerate(roles)]
    wsum = sum(weights)
    for i, w in enumerate(weights):
        if wsum > 0 and i != long_idx:
            durations[i] = remaining * w / wsum
    rounded = [_round(d, ROUND_S) for d in durations]
    drift = total - sum(rounded)
    # Le reliquat d'arrondi va à la plus grande séance non longue (sinon à la longue).
    pool = [i for i in range(len(roles)) if i != long_idx] or list(range(len(roles)))
    target = max(pool, key=lambda i: (rounded[i], -i))
    rounded[target] += drift
    return rounded


def _split_elevation(total_m: float, durations: List[int], long_idx: Optional[int]) -> List[int]:
    total = _round(total_m, ROUND_ELEV_M)
    dsum = sum(durations)
    if total <= 0 or dsum <= 0:
        return [0] * len(durations)
    out = [_round(total * d / dsum, ROUND_ELEV_M) for d in durations]
    drift = total - sum(out)
    out[long_idx if long_idx is not None else max(range(len(out)), key=lambda i: out[i])] += drift
    return out


def make_week(spec: dict, scale_d: float = 1.0, scale_e: float = 1.0, no_quality: bool = False) -> dict:
    """Entrée `week_entry` d'une semaine (créneaux compris). PURE.

    `spec` : voir `build_skeleton` (clés `week_start`, `record` (semaine résolue du gabarit),
    `type`, `target_duration_s`, `target_elevation_m`, `availability`, `race_date`, `sport`,
    `location`, `distance_per_s`, `n_run`, `strength`)."""
    ws: date = spec["week_start"]
    rec = spec["record"]
    typ = spec["type"]
    av = spec["availability"]
    blocked = set(av.get("blocked_days") or [])
    days = [d for d in range(7) if d not in blocked]
    race: Optional[date] = spec.get("race_date") if typ == TYPE_RACE else None
    race_wd = race.weekday() if race else None
    flags: List[str] = []
    target_s = max(0.0, spec["target_duration_s"] * scale_d)
    target_e = (spec["target_elevation_m"] * scale_e) if spec.get("target_elevation_m") else None
    # Volume au prorata des jours réellement utilisables (semaine de course avant un dimanche, première
    # semaine post-course) : jamais tout le volume du gabarit entassé sur un ou deux jours.
    prorata = 1.0
    quality_q = 0 if no_quality else rec["quality_sessions_max"]
    n_run = spec["n_run"]

    long_day: Optional[int] = None
    if typ == TYPE_RACE:
        # Veille de course laissée libre (repos ou déverrouillage court, au choix du coach) ; volume au
        # prorata des jours avant la course (course le dimanche = 6/6).
        days = [d for d in days if d < race_wd - 1]
        prorata = race_wd / 6.0
        if race_wd < 6:
            flags.append(f"course un {DAY_NAMES_FR[race_wd]} : volume de la semaine ramené à {race_wd}/6 "
                         "(jours avant la course), veille laissée libre.")
        n_run = min(n_run, MAX_RACE_WEEK_RUNS, len(days))
        chosen = _spread(days, n_run, days[0]) if days and n_run else []
        # Activation : une seule séance de qualité, au plus tard 3 jours avant la course.
        q_days = [d for d in chosen if d <= race_wd - 3][:1] if quality_q else []
        if quality_q and not q_days:
            flags.append("pas de jour disponible pour l'activation de la semaine de course (≥ 3 jours avant).")
        strength_day = None
    else:
        if typ == TYPE_POST_RACE:
            n_run = min(n_run, 4)
            rest_end = spec["race_date"] + timedelta(days=POST_RACE_REST_DAYS)
            cut = sum(1 for d in range(7) if ws + timedelta(days=d) <= rest_end)
            if cut:
                days = [d for d in days if ws + timedelta(days=d) > rest_end]
                prorata = (7 - cut) / 7.0
                flags.append(f"aucun créneau de course à pied jusqu'au {rest_end.isoformat()} "
                             f"({POST_RACE_REST_DAYS} jours après la course) ; volume ramené à {7 - cut}/7.")
        n_run = max(1, min(n_run, len(days))) if days else 0
        if not days:
            flags.append("aucun jour disponible : semaine sans créneau (disponibilité à revoir).")
        pref = av.get("long_run_day")
        if days:
            long_day = pref if pref in days else (6 if 6 in days else 5 if 5 in days else max(days))
            if pref is not None and pref not in days:
                flags.append(f"jour de sortie longue ({DAY_NAMES_FR[pref]}) indisponible : {DAY_NAMES_FR[long_day]}.")
        chosen = _spread(days, n_run, long_day) if days else []
        q_days = _place_quality([d for d in chosen], long_day, quality_q) if chosen else []
        if len(q_days) < min(quality_q, max(0, len(chosen) - 1)):
            flags.append(f"{len(q_days)} séance(s) de qualité sur {quality_q} (jours non espaçables).")
        free = [d for d in days if d not in chosen]
        strength_day = None
        if spec.get("strength") and free and typ != TYPE_POST_RACE:
            cands = [d for d in free if long_day is None or d != long_day - 1] or free
            strength_day = cands[0]

    target_s *= prorata
    if target_e:
        target_e *= prorata
    roles, role_days = [], []
    for d in sorted(chosen):
        if d == long_day:
            roles.append("long")
        elif d in q_days:
            roles.append("quality")
        else:
            roles.append("easy")
        role_days.append(d)
    long_idx = roles.index("long") if "long" in roles else None
    durations = _split_duration(target_s, long_idx, roles, rec["long_run_share_pct"], rec["long_run_cap_min"])
    elevs = _split_elevation(target_e, durations, long_idx) if target_e else [0] * len(roles)
    if long_idx is not None and len(roles) > 1 and durations[long_idx] < max(
            d for i, d in enumerate(durations) if i != long_idx):
        flags.append("la sortie longue n'est pas la plus longue séance (plafond de durée du gabarit).")

    easy_intensity = "recovery" if typ in (TYPE_RECOVERY, TYPE_POST_RACE) else "endurance"
    primary = spec["sport"]
    sessions: List[dict] = []
    for d, role, dur, elev in zip(role_days, roles, durations, elevs):
        day = ws + timedelta(days=d)
        title = {"long": "Sortie longue", "quality": "Séance de qualité", "easy": "Footing facile"}[role]
        s = {"date": day.isoformat(), "sport": primary, "title": f"{title} (à définir)",
             "planned_duration_s": dur,
             "intensity": QUALITY_INTENSITY.get(rec["phase"], "tempo") if role == "quality" else
             ("endurance" if role == "long" else easy_intensity),
             "outdoor": True, "status": "planned", "placeholder": True}
        if elev:
            s["planned_elevation_m"] = elev
        if spec.get("distance_per_s") and dur:
            s["planned_distance_m"] = _round(dur * spec["distance_per_s"], 100)
        sessions.append(s)
    if strength_day is not None:
        sessions.append({"date": (ws + timedelta(days=strength_day)).isoformat(), "sport": "strength",
                         "title": f"Renforcement — {STRENGTH_LABELS_FR.get(rec['strength'], rec['strength'])} (à définir)",
                         "planned_duration_s": STRENGTH_SLOT_S, "intensity": "strength", "outdoor": False,
                         "status": "planned", "placeholder": True})
    if race is not None:
        obj = spec.get("objective") or {}
        r = {"date": race.isoformat(), "sport": primary, "title": f"Course — {obj.get('name') or 'objectif'}",
             "intensity": "race", "outdoor": True, "status": "planned"}
        if obj.get("target_time_s"):
            r["planned_duration_s"] = int(obj["target_time_s"])
        if obj.get("distance_m"):
            r["planned_distance_m"] = obj["distance_m"]
        if obj.get("elevation_gain_m"):
            r["planned_elevation_m"] = obj["elevation_gain_m"]
        sessions.append(r)
    sessions.sort(key=lambda s: (s["date"], s["sport"] == "strength"))

    run_total = sum(durations)
    entry = {"week_start": ws.isoformat(), "location": spec["location"], "phase": rec["phase_label"],
             "week_type": typ, "target_duration_s": run_total, "quality_sessions": len(q_days),
             "strength_emphasis": rec["strength"], "sessions": sessions}
    if elevs and sum(elevs):
        entry["target_elevation_m"] = sum(elevs)
    if spec.get("distance_per_s") and run_total:
        entry["target_distance_m"] = sum(s.get("planned_distance_m", 0) for s in sessions
                                         if s["sport"] == primary and s.get("placeholder"))
    if long_idx is not None:
        entry["long_run_target_s"] = durations[long_idx]
    entry["_flags"] = flags
    return entry


# ---------------------------------------------------------------------------
# Évaluation par les garde-fous
# ---------------------------------------------------------------------------


def _run_totals(entry: dict) -> dict:
    """Totaux course à pied tels que `arc_guardrails` les lit (`_run_family_sessions`)."""
    runs = G._run_family_sessions([s for s in entry["sessions"] if s.get("intensity") != "race"])
    return {"duration_s": sum(s.get("planned_duration_s") or 0.0 for s in runs),
            "distance_m": sum(s.get("planned_distance_m") or 0.0 for s in runs),
            "elevation_gain_m": sum(s.get("planned_elevation_m") or 0.0 for s in runs),
            "has_any_activity": True}


def check_week(entry: dict, chain: List[dict], prior: List[dict], context_factory: Callable, gconf: dict,
               race_date: Optional[date]) -> dict:
    """Verdict d'`arc_guardrails.evaluate` pour une semaine générée, sur la référence `chain`."""
    ws = date.fromisoformat(entry["week_start"])
    proposed = {k: v for k, v in entry.items() if not k.startswith("_")}
    ctx = dict(context_factory(ws, prior))
    ctx["previous_week"] = _reference(chain, "previous_week")
    ctx["mean4_weeks"] = _reference(chain, "mean4")
    if race_date is not None:
        ctx["race_date"] = race_date.isoformat()
        ctx["is_race_week"] = ws <= race_date <= ws + timedelta(days=6)
    result = G.evaluate(proposed, ctx, gconf)
    return result


def _compact_verdict(result: dict, gconf: dict) -> dict:
    viol = [{"rule_id": v["rule_id"], "severity": v["severity"], "message": v["message"]}
            for v in result["violations"]]
    order = {"info": 1, "warn": 2, "block": 3}
    top = max((v["severity"] for v in viol), key=lambda s: order[s], default=None)
    return {"ok": result["ok"], "level": top or "pass", "violations": viol,
            "checked_rules": result["checked_rules"],
            "skipped_rules": [{"rule_id": s["rule_id"], "reason_code": s["reason_code"]}
                              for s in result["skipped_rules"]],
            "guardrails_enabled": bool(gconf.get("enabled", True))}


def _violation(result: dict, rule_id: str) -> Optional[dict]:
    return next((v for v in result["violations"] if v["rule_id"] == rule_id and v["severity"] != "info"), None)


def _scale_from(violation: dict) -> float:
    """Facteur ramenant la valeur observée sous le seuil, tiré du verdict lui-même."""
    observed, threshold = violation["values"]["observed"], violation["values"]["threshold"]
    return ((1 + threshold / 100.0) / (1 + observed / 100.0)) * CAP_MARGIN


def _is_rebound(entry: dict, violation: Optional[dict], rebound_ref: Optional[dict], key: str) -> bool:
    """Reprise après une semaine allégée avec `r2_volume_reference = "previous_week"` : le dépassement
    face à la semaine allégée est mécanique (100 / 80 = +25 %), comme `arc_plan_templates` le traite
    (#189) — pas de réduction tant que la reprise reste sous la dernière semaine non allégée + seuil.
    Le `warn` reste dans le verdict (`arc_guardrails.py check` l'avertira aussi sur l'historique réel)."""
    if violation is None or rebound_ref is None or violation["severity"] == "block":
        return False
    up = G._pct_increase(_run_totals(entry)[key], rebound_ref.get(key) or 0.0)
    return up is not None and up <= violation["values"]["threshold"]


def settle_week(spec: dict, chain: List[dict], prior: List[dict], context_factory: Callable, gconf: dict,
                race_date: Optional[date], rebound_ref: Optional[dict] = None) -> Tuple[Optional[dict], dict, List[str]]:
    """Génère la semaine, l'évalue, l'ajuste (R2/R3 → réduction ; `block` → sans qualité puis −10 %).

    `rebound_ref` : totaux de la dernière semaine non allégée quand la semaine suit une semaine allégée
    avec la référence `previous_week` (voir `_is_rebound`). Rend `(entrée | None, verdict compact,
    ajustements)`. `None` = blocage persistant."""
    scale_d = scale_e = 1.0
    no_quality = False
    adjustments: List[str] = []
    for _ in range(MAX_ADJUST_ATTEMPTS):
        entry = make_week(spec, scale_d, scale_e, no_quality)
        result = check_week(entry, chain, prior, context_factory, gconf, race_date)
        v2, v3 = _violation(result, "r2_weekly_volume_jump"), _violation(result, "r3_weekly_elevation_jump")
        r2_key = "distance_m" if v2 and "distance" in v2["message"].lower() else "duration_s"
        if _is_rebound(entry, v2, rebound_ref, r2_key):
            v2 = None
        if _is_rebound(entry, v3, rebound_ref, "elevation_gain_m"):
            v3 = None
        blocks = [v for v in result["violations"] if v["severity"] == "block"
                  and v["rule_id"] not in ("r2_weekly_volume_jump", "r3_weekly_elevation_jump")]
        if v2:
            f = _scale_from(v2)
            scale_d *= f
            adjustments.append(f"volume réduit de {round((1 - f) * 100, 1)} % (R2 : +{v2['values']['observed']:g} % "
                               f"vs référence, seuil {v2['values']['threshold']:g} %).")
        if v3:
            f = _scale_from(v3)
            scale_e *= f
            adjustments.append(f"D+ réduit de {round((1 - f) * 100, 1)} % (R3 : +{v3['values']['observed']:g} % "
                               f"vs référence, seuil {v3['values']['threshold']:g} %).")
        if blocks and not (v2 or v3):
            if not no_quality and any(s.get("intensity") in ("tempo", "threshold", "vo2max")
                                      for s in entry["sessions"]):
                no_quality = True
                adjustments.append("séances de qualité converties en endurance (verdict `block` : "
                                   + ", ".join(sorted(b["rule_id"] for b in blocks)) + ").")
            else:
                scale_d *= 0.9
                scale_e *= 0.9
                adjustments.append("volume et D+ réduits de 10 % (verdict `block`).")
            continue
        if v2 or v3 or blocks:
            continue
        verdict = _compact_verdict(result, gconf)
        return entry, verdict, adjustments
    # Dernière évaluation : la semaine ne passe pas (R2/R3 résiduels = warn seulement).
    entry = make_week(spec, scale_d, scale_e, no_quality)
    result = check_week(entry, chain, prior, context_factory, gconf, race_date)
    verdict = _compact_verdict(result, gconf)
    if not result["ok"]:
        return None, verdict, adjustments
    return entry, verdict, adjustments


# ---------------------------------------------------------------------------
# Le squelette
# ---------------------------------------------------------------------------


def _kind_to_type(kind: str, is_last_taper: bool) -> str:
    if kind == "taper":
        return TYPE_RACE if is_last_taper else TYPE_TAPER
    return {"build": TYPE_BUILD, "recovery_week": TYPE_RECOVERY, "post_race": TYPE_POST_RACE,
            "lead_in": TYPE_LEAD_IN}[kind]


def _lead_in_records(first: dict, template: dict, count: int) -> List[dict]:
    rec = template["recovery_week"]
    out = []
    for j in range(1, count + 1):
        r = dict(first)
        r["kind"] = "lead_in"
        if j % rec["every_n_weeks"] == 0 and j < count:
            r["kind"] = "recovery_week"
            r["volume_pct"] = round(first["volume_pct"] * rec["volume_factor"], 1)
            if first.get("elevation_pct") is not None:
                r["elevation_pct"] = round(first["elevation_pct"] * rec.get("elevation_factor", rec["volume_factor"]), 1)
            r["quality_sessions_max"] = min(first["quality_sessions_max"], rec["quality_sessions_max"])
        out.append(r)
    return out


def too_short_options(templates: List[dict], sport: str, n_weeks: int, template: dict, start: date) -> List[dict]:
    options = []
    shorter = [t["id"] for t in templates if t.get("sport") == sport and t["id"] != template["id"]
               and t["weeks"]["min"] <= max(n_weeks, 0)]
    if shorter:
        options.append({"id": "shorter_format", "templates": shorter,
                        "label": "Un format plus court (`--format`), si l'objectif le permet réellement."})
    earliest = _monday(start + timedelta(days=7 * (template["weeks"]["min"] - 1)))
    options.append({"id": "later_race", "earliest_race_week": earliest.isoformat(),
                    "label": f"Course visée au plus tôt la semaine du {earliest.isoformat()} pour ce gabarit."})
    options.append({"id": "freehand", "label": "Bloc sans gabarit, construit à la main par le coach "
                                                "(à dire à l'athlète : aucun squelette vérifié)."})
    return options


def build_skeleton(*, template: dict, today: date, race_date: date, held: dict, availability: dict,
                   gconf: dict, context_factory: Callable, location: str = "à définir", objective: Optional[dict] = None,
                   templates: Optional[List[dict]] = None) -> dict:
    """Squelette complet. PURE (le `context_factory` est le seul accès au monde extérieur)."""
    sport = template["sport"]
    primary = "trail" if sport == "trail" else "running"
    current = _monday(today)
    start = current if today == current else current + timedelta(days=7)
    race_monday = _monday(race_date)
    n_weeks = (race_monday - start).days // 7 + 1
    wk = template["weeks"]
    base = {"schema_version": SCHEMA_VERSION, "status": None, "reason": None, "today": today.isoformat(),
            "start_week": start.isoformat(), "race_date": race_date.isoformat(),
            "race_week_start": race_monday.isoformat(), "n_weeks": n_weeks,
            "template": {"id": template["id"], "label": template["label"], "sport": sport,
                         "weeks": wk},
            "availability": availability, "assumptions": ASSUMPTIONS}
    if race_date < today:
        return {**base, "status": STATUS_PAST, "weeks": [],
                "reason": f"la date de course ({race_date.isoformat()}) est passée."}
    if n_weeks < wk["min"]:
        return {**base, "status": STATUS_TOO_SHORT, "weeks": [],
                "reason": f"{max(n_weeks, 0)} semaine(s) jusqu'à la semaine de course, le gabarit « {template['id']} » "
                          f"en exige au moins {wk['min']} : aucune compression sous les minima.",
                "options": too_short_options(templates or [template], sport, n_weeks, template, start)}
    held_s, held_e = held["duration_s"], held["elevation_gain_m"]
    if held_s < MIN_HELD_DURATION_S or not held.get("has_any_activity", True):
        return {**base, "status": STATUS_NO_HISTORY, "weeks": [], "held": _held_view(held),
                "reason": "volume tenu inconnu ou inférieur à 1 h par semaine sur les 4 dernières semaines : "
                          "demander à l'athlète son volume hebdomadaire actuel (`--held-hours`, `--held-elevation-m`) "
                          "— jamais inventé."}

    n_eff = min(n_weeks, wk["max"])
    lead = n_weeks - n_eff
    resolved = PT.resolve_weeks(template, n_eff, with_recovery=True)
    pre = [w for w in resolved if not w["post_race"]]
    post = [w for w in resolved if w["post_race"]]
    factors = PT.peak_from_current(pre, sport)
    warnings: List[str] = list(availability.get("notes") or [])
    peak_s = held_s * factors["volume_factor"]
    capped = False
    max_s = availability.get("max_weekly_s")
    if max_s and peak_s > max_s:
        warnings.append(f"pic dérivé {_h(peak_s)} > plafond de disponibilité {_h(max_s)} : "
                        "pic ramené au plafond (le bloc part alors sous le volume tenu).")
        peak_s, capped = float(max_s), True
    peak_e = None
    if sport == "trail":
        if held_e > 0:
            peak_e = held_e * factors["elevation_factor"]
        else:
            warnings.append("D+ tenu nul sur les 4 dernières semaines : D+ cible non dérivable (R3 non vérifiable) "
                            "— `--held-elevation-m` si l'athlète en fait réellement.")
    ind = template["peak_week_indicative"]["duration_h"]
    if peak_s / 3600 < ind["min"]:
        warnings.append(f"pic dérivé {_h(peak_s)} sous le pic indicatif du gabarit ({ind['min']:g}–{ind['max']:g} h) : "
                        "proposer d'abord une mise en route qui FASSE MONTER le volume tenu (semaines écrites et vérifiées "
                        "par les garde-fous, puis relancer `plan-skeleton`) ou revoir l'objectif — jamais étirer le "
                        "gabarit ; les semaines `lead_in` du squelette restent, elles, au volume tenu.")
    distance_per_s = held["distance_m"] / held_s if sport == "road" and held["distance_m"] > 0 else None

    sessions_per_week = availability.get("sessions_per_week") or DEFAULT_SESSIONS_PER_WEEK
    free_days = 7 - len(set(availability.get("blocked_days") or []))
    strength_slot = sessions_per_week >= MIN_SESSIONS_FOR_STRENGTH
    n_run = min(sessions_per_week - (1 if strength_slot else 0), free_days)

    records: List[Tuple[dict, str]] = []
    for r in _lead_in_records(pre[0], template, lead) if lead else []:
        records.append((r, _kind_to_type(r["kind"], False)))
    last_pre = len(pre) - 1
    for i, r in enumerate(pre):
        records.append((r, _kind_to_type(r["kind"], i == last_pre)))
    for r in post:
        records.append((r, TYPE_POST_RACE))

    # Chaîne de référence R2/R3 : 4 semaines réelles (+ la semaine en cours supposée au volume tenu).
    chain = [{k: w.get(k) or 0.0 for k in ("duration_s", "distance_m", "elevation_gain_m")} for w in held["weeks"]]
    if start > current:
        chain.append({"duration_s": held_s, "distance_m": held["distance_m"], "elevation_gain_m": held_e})

    weeks_out: List[dict] = []
    entries_for_ctx: List[dict] = []
    unresolved: List[dict] = []
    # Types parallèles à `chain` (semaines réelles/supposée = pleines) : reprise après semaine allégée.
    chain_types: List[str] = ["held"] * len(chain)
    lighter = (TYPE_RECOVERY, TYPE_TAPER, TYPE_RACE, TYPE_POST_RACE)
    for idx, (rec, typ) in enumerate(records):
        ws = start + timedelta(days=7 * idx)
        target_s = peak_s * rec["volume_pct"] / 100.0
        target_e = peak_e * rec["elevation_pct"] / 100.0 if peak_e and rec.get("elevation_pct") else None
        spec = {"week_start": ws, "record": rec, "type": typ, "target_duration_s": target_s,
                "target_elevation_m": target_e, "availability": availability, "race_date": race_date,
                "sport": primary, "location": location, "distance_per_s": distance_per_s, "n_run": n_run,
                "strength": strength_slot, "objective": objective}
        rebound_ref = None
        if gconf.get("r2_volume_reference") == "previous_week" and chain_types[-1] in (TYPE_RECOVERY, TYPE_POST_RACE):
            rebound_ref = next((c for c, t in zip(reversed(chain), reversed(chain_types)) if t not in lighter), None)
        entry, verdict, adjustments = settle_week(spec, chain, entries_for_ctx, context_factory, gconf, race_date,
                                                  rebound_ref)
        chain_types.append(typ)
        if entry is None:
            unresolved.append({"week_start": ws.isoformat(), "week_type": typ, "phase": rec["phase_label"],
                               "guardrails": verdict, "adjustments": adjustments})
            # La semaine n'est pas émise : la chaîne suppose le volume cible pour les suivantes.
            chain.append({"duration_s": target_s, "distance_m": 0.0, "elevation_gain_m": target_e or 0.0})
            continue
        flags = entry.pop("_flags")
        if rebound_ref is not None and any(v["rule_id"] in ("r2_weekly_volume_jump", "r3_weekly_elevation_jump")
                                           for v in verdict["violations"]):
            flags.append("reprise après une semaine allégée (ou post-course) : R2/R3 avertit face à la semaine précédente "
                         "(référence `previous_week`), mais reste sous la dernière semaine non allégée + seuil.")
        chain.append(_run_totals(entry))
        entries_for_ctx.append({"week_start": entry["week_start"], "sessions": entry["sessions"]})
        weeks_out.append({
            "week": idx + 1, "week_start": entry["week_start"], "phase": rec["phase"], "phase_label": rec["phase_label"],
            "type": typ, "type_label": TYPE_LABELS_FR[typ],
            "volume_pct_of_peak": rec["volume_pct"], "elevation_pct_of_peak": rec.get("elevation_pct"),
            "target_duration_s": entry["target_duration_s"], "target_duration_h": round(entry["target_duration_s"] / 3600, 2),
            "target_elevation_m": entry.get("target_elevation_m"), "target_distance_m": entry.get("target_distance_m"),
            "quality_sessions": entry["quality_sessions"], "long_run_target_s": entry.get("long_run_target_s"),
            "long_run_cap_min": rec["long_run_cap_min"], "intensity_split": rec["intensity"],
            "strength_emphasis": rec["strength"], "flags": flags, "adjustments": adjustments,
            "guardrails": verdict, "entry": entry})

    status = STATUS_NEEDS_REVIEW if unresolved else STATUS_OK
    summary = {"weeks": len(weeks_out), "block_free": all(w["guardrails"]["level"] != "block" for w in weeks_out),
               "levels": {lvl: sum(1 for w in weeks_out if w["guardrails"]["level"] == lvl)
                          for lvl in ("pass", "info", "warn")},
               "adjusted_weeks": sum(1 for w in weeks_out if w["adjustments"])}
    return {**base, "status": status,
            "reason": None if not unresolved else f"{len(unresolved)} semaine(s) non émise(s) : blocage des garde-fous persistant.",
            "lead_in_weeks": lead, "phase_weeks": PT.allocate_phase_weeks(template, n_eff),
            "held": _held_view(held),
            "peak": {"duration_s": round(peak_s), "duration_h": round(peak_s / 3600, 2),
                     "elevation_m": round(peak_e) if peak_e else None,
                     "volume_factor": factors["volume_factor"], "elevation_factor": factors.get("elevation_factor"),
                     "capped_by_availability": capped, "indicative_h": ind},
            "slots": {"run_slots_per_week": n_run, "strength_slot": strength_slot},
            "warnings": warnings, "weeks": weeks_out, "unresolved": unresolved, "summary": summary}


def _held_view(held: dict) -> dict:
    return {"source": held["source"], "duration_s": round(held["duration_s"]),
            "duration_h": round(held["duration_s"] / 3600, 2),
            "elevation_gain_m": round(held["elevation_gain_m"]), "distance_m": round(held["distance_m"]),
            "weeks": held["weeks"]}


# ---------------------------------------------------------------------------
# Objectif, gabarit, rapport (entrées de la CLI)
# ---------------------------------------------------------------------------


def choose_template(templates: List[dict], template_id: Optional[str], objective: Optional[dict],
                    sport: str) -> Tuple[Optional[dict], Optional[str]]:
    """`(gabarit, raison d'absence)`."""
    if template_id:
        return PT.get_template(template_id, templates), None
    dist = (objective or {}).get("distance_m")
    if not dist:
        return None, "pas de `--format` et pas de distance dans l'objectif actif : impossible de choisir un gabarit."
    t = PT.match_template(templates, dist / 1000.0, sport)
    if t is None:
        return None, f"aucun gabarit pour {dist / 1000:g} km ({sport}) : bloc sans gabarit, à dire à l'athlète."
    return t, None


def skeleton_report(*, conn, config: dict, workspace: Path, today: date, template_id: Optional[str] = None,
                    race_date: Optional[str] = None, held_hours: Optional[float] = None,
                    held_elevation_m: Optional[float] = None, long_run_day: Optional[str] = None,
                    directory: Optional[Path] = None) -> dict:
    """Squelette complet depuis l'index et le workspace (impur)."""
    import arc_index as I
    templates = PT.load_templates(directory)
    gconf = G.guardrail_settings(config)
    sport = I.settings(config)["sport"]
    if sport not in PT.SPORTS:
        sport = "trail"
    row = conn.execute("SELECT * FROM objective LIMIT 1").fetchone()
    objective = dict(row) if row else None
    base = {"schema_version": SCHEMA_VERSION, "today": today.isoformat(), "assumptions": ASSUMPTIONS}
    race = race_date or (objective or {}).get("race_date")
    if not race:
        return {**base, "status": STATUS_NO_OBJECTIVE, "weeks": [],
                "reason": "aucune date de course (objectif actif sans date et pas de `--race-date`)."}
    try:
        race_d = date.fromisoformat(race)
    except ValueError:
        raise SkeletonError(f"--race-date : date AAAA-MM-JJ attendue, « {race} » reçue.")
    template, why = choose_template(templates, template_id, objective, sport)
    if template is None:
        return {**base, "status": STATUS_NO_TEMPLATE, "weeks": [], "race_date": race, "reason": why,
                "templates": [PT.summarize(t) for t in templates]}
    profile_rel = I.settings(config).get("profile") or "planning/Runner_Profile.md"
    profile_text = None
    for cand in (workspace / profile_rel, workspace / "planning" / "Runner_Profile.md"):
        try:
            profile_text = cand.read_text(encoding="utf-8")
            break
        except OSError:
            continue
    availability = parse_availability(profile_text, long_run_day)
    if held_hours is not None:
        # Déclaré, même à 0 : `no_history` honnête plutôt qu'un repli silencieux sur l'index.
        held = declared_held(held_hours, held_elevation_m)
    else:
        held = held_from_index(conn, today)
        if held_elevation_m is not None:
            for w in held["weeks"]:
                w["elevation_gain_m"] = float(held_elevation_m)
            held = held_from_weeks(held["weeks"], "index+declared_elevation")
    import arc_legacy as L
    location = ((objective or {}).get("training_location")
                or (L.parse_profile(profile_text).get("default_location") if profile_text else None)
                or (objective or {}).get("location") or "à définir")
    # Seuils de configuration → référence R2/R3 réelle.
    factory = default_context_factory(conn, config, gconf, today)
    result = build_skeleton(template=template, today=today, race_date=race_d, held=held, availability=availability,
                            gconf=gconf, context_factory=factory, location=location, objective=objective,
                            templates=templates)
    if location == "à définir":
        result.setdefault("warnings", []).append(
            "aucun lieu d'entraînement (objectif actif, profil) : `location` = « à définir » ; à renseigner avant "
            "la météo.")
    return result


def attach_forecast(conn, today: date, result: dict) -> dict:
    """Forme projetée le jour J avec le squelette (compare à `arc_load_forecast`). Ajoute `forecast`."""
    import arc_load_forecast as LF
    if result.get("status") not in (STATUS_OK, STATUS_NEEDS_REVIEW) or not result.get("weeks"):
        result["forecast"] = None
        return result
    alt = [{"week_start": w["week_start"], "sessions": w["entry"]["sessions"]} for w in result["weeks"]]
    race = date.fromisoformat(result["race_date"])
    cmp_ = LF.load_forecast(conn, today, race, alt)

    def trim(f):
        return {k: v for k, v in f.items() if k not in ("series", "weeks")} if isinstance(f, dict) else f
    result["forecast"] = {**{k: v for k, v in cmp_.items() if k not in ("current", "alternative")},
                          "current": trim(cmp_.get("current")), "alternative": trim(cmp_.get("alternative")),
                          "note": "projection à partir de créneaux dont l'intensité est un placeholder : "
                                  "ordre de grandeur, pas une mesure."}
    return result


# ---------------------------------------------------------------------------
# Écriture (--write)
# ---------------------------------------------------------------------------


def existing_week_starts(workspace: Path) -> Dict[str, str]:
    """`{lundi: fichier}` des semaines déjà écrites dans `planning/` (semaine unique ou `weeks[]`)."""
    found: Dict[str, str] = {}
    for path in sorted((workspace / "planning").glob("*.md")):
        try:
            block = C.extract_block(path.read_text(encoding="utf-8"))
        except (C.ContractError, OSError):
            continue
        if not isinstance(block, dict) or block.get("kind") != "week":
            continue
        entries = block["weeks"] if isinstance(block.get("weeks"), list) else [block]
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("week_start"), str):
                found.setdefault(e["week_start"], path.name)
    return found


def find_conflicts(workspace: Path, result: dict) -> List[dict]:
    """Semaines du squelette déjà écrites dans `planning/` (par un fichier du même nom ou un autre fichier)."""
    existing = existing_week_starts(workspace)
    out = []
    for w in result.get("weeks") or []:
        path = workspace / "planning" / week_file_name(w["week_start"])
        if path.exists() or w["week_start"] in existing:
            out.append({"week_start": w["week_start"], "file": existing.get(w["week_start"]) or path.name})
    return out


def week_file_name(week_start: str) -> str:
    return f"Semaine_{week_start}.md"


def week_markdown(result: dict, w: dict) -> str:
    entry = {"arc": C.ARC_VERSION, "kind": "week", **{k: v for k, v in w["entry"].items()}}
    t = result["template"]
    lines = [f"# Semaine du {w['week_start']} — {w['phase_label']} ({w['type_label'].lower()}, squelette)", "",
             "```arc", json.dumps(entry, ensure_ascii=False, indent=2), "```", "",
             f"> Squelette généré par `arc_index.py plan-skeleton` (gabarit `{t['id']}`, semaine {w['week']} du bloc, "
             f"course le {result['race_date']}). Les séances ci-dessus sont des **créneaux à habiller** "
             "(`placeholder: true`) : le coach définit le contenu, les cibles et retire le drapeau.", "",
             f"- Volume course à pied visé : {w['target_duration_h']:g} h"
             + (f", D+ {w['target_elevation_m']:g} m" if w.get("target_elevation_m") else "")
             + f" ({w['volume_pct_of_peak']:g} % du pic de {result['peak']['duration_h']:g} h).",
             f"- Séances de qualité : {w['quality_sessions']} ; renforcement : {STRENGTH_LABELS_FR.get(w['strength_emphasis'])}.",
             "- Répartition d'intensité visée (facile / modérée / dure) : "
             f"{w['intensity_split']['easy_pct']:g} / {w['intensity_split']['moderate_pct']:g} / "
             f"{w['intensity_split']['hard_pct']:g} %.",
             f"- Garde-fous : {w['guardrails']['level']}"
             + ("".join(f" ; {v['rule_id']} ({v['severity']})" for v in w["guardrails"]["violations"]) or "") + "."]
    for adj in w["adjustments"] + w["flags"]:
        lines.append(f"- Note : {adj}")
    return "\n".join(lines) + "\n"


def write_weeks(workspace: Path, result: dict, validate: Callable) -> dict:
    """Écrit un fichier `planning/Semaine_<lundi>.md` par semaine, sans jamais écraser. Refuse (rien
    d'écrit) si un conflit existe ou si le squelette n'est pas `ok`. Valide chaque fichier ; en cas
    d'échec de validation, retire ce qui vient d'être écrit."""
    out = {"written": [], "conflicts": [], "refused": None, "validation": []}
    if result.get("status") != STATUS_OK:
        out["refused"] = f"squelette non écrivable (statut « {result.get('status')} »)."
        return out
    planning = workspace / "planning"
    out["conflicts"] = find_conflicts(workspace, result)
    if out["conflicts"]:
        out["refused"] = "des semaines existent déjà : rien n'est écrit (jamais d'écrasement)."
        return out
    planning.mkdir(parents=True, exist_ok=True)
    created: List[Path] = []
    try:
        for w in result["weeks"]:
            path = planning / week_file_name(w["week_start"])
            # Création exclusive (« x ») : un fichier apparu depuis la détection des conflits n'est
            # jamais écrasé ; toute erreur retire ce qui vient d'être écrit (tout ou rien).
            with open(path, "x", encoding="utf-8") as fh:
                created.append(path)
                fh.write(week_markdown(result, w))
    except OSError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        out["refused"] = f"écriture interrompue ({exc}) : fichiers retirés, rien n'est écrit."
        return out
    bad = False
    for path in created:
        ok, errors, warnings = validate(path)
        out["validation"].append({"file": path.name, "ok": ok, "errors": errors, "warnings": warnings})
        bad = bad or not ok
    if bad:
        for path in created:
            path.unlink(missing_ok=True)
        out["refused"] = "validation du contrat échouée : fichiers retirés."
        return out
    out["written"] = [str(p.relative_to(workspace)) for p in created]
    return out


# ---------------------------------------------------------------------------
# Rendu texte
# ---------------------------------------------------------------------------


def _h(seconds: Optional[float]) -> str:
    if not seconds:
        return "—"
    h, m = divmod(int(round(seconds / 60)), 60)
    return f"{h} h {m:02d}"


def render_text(result: dict) -> str:
    st = result.get("status")
    if st not in (STATUS_OK, STATUS_NEEDS_REVIEW):
        lines = [f"Squelette indisponible ({st}) : {result.get('reason')}"]
        for opt in result.get("options") or []:
            lines.append(f"- {opt['label']}")
        return "\n".join(lines)
    t, p, held = result["template"], result["peak"], result["held"]
    lines = [f"{t['label']} — course le {result['race_date']} ; {result['n_weeks']} semaines du "
             f"{result['start_week']} à la semaine de course"
             + (f" (dont {result['lead_in_weeks']} de mise en route)." if result["lead_in_weeks"] else "."),
             f"Volume tenu ({held['source']}) : {_h(held['duration_s'])}/sem, D+ {held['elevation_gain_m']} m. "
             f"Pic = ×{p['volume_factor']:g} → {_h(p['duration_s'])}"
             + (f", D+ {p['elevation_m']} m" if p["elevation_m"] else "") + ".",
             "Proposition (dry run) : rien n'est écrit sans `--write`. Les séances sont des créneaux à habiller.", ""]
    lines.append("Sem | Début      | Phase / type                   | Durée   | D+ m | Q | Sortie longue | Renfo | Garde-fous")
    for w in result["weeks"]:
        lines.append(f"{w['week']:>3} | {w['week_start']} | {w['phase_label'] + ' / ' + w['type_label']:<30} | "
                     f"{_h(w['target_duration_s']):<7} | {w['target_elevation_m'] or '—':>4} | {w['quality_sessions']} | "
                     f"{_h(w.get('long_run_target_s')):<13} | {w['strength_emphasis']} | {w['guardrails']['level']}")
    for w in result["weeks"]:
        for note in w["adjustments"] + w["flags"]:
            lines.append(f"  semaine du {w['week_start']} : {note}")
    for u in result.get("unresolved") or []:
        lines.append(f"NON ÉMISE : semaine du {u['week_start']} ({u['phase']}) — "
                     + "; ".join(v["message"] for v in u["guardrails"]["violations"] if v["severity"] == "block"))
    for warn in result.get("warnings") or []:
        lines.append(f"Attention : {warn}")
    fc = result.get("forecast")
    if fc and (fc.get("alternative") or {}).get("status") == "ok":
        rd = fc["alternative"].get("race_day") or fc["alternative"].get("end")
        lines.append(f"Forme prévue le jour J avec ce squelette : {rd['form']:+.1f} (condition {rd['fitness']:.1f}, "
                     f"fatigue {rd['fatigue']:.1f}) — estimation, pas une mesure.")
    elif fc:
        alt = fc.get("alternative") or {}
        lines.append(f"Forme prévue le jour J : indisponible ({alt.get('status')}) : {alt.get('reason')}")
    if result.get("conflicts"):
        lines.append("Semaines déjà écrites (`--write` refuserait, rien n'est jamais écrasé) : "
                     + ", ".join(c["week_start"] for c in result["conflicts"]) + ".")
    s = result["summary"]
    lines.append(f"Garde-fous : {s['levels']['pass']} conforme(s), {s['levels']['info']} info, {s['levels']['warn']} "
                 f"warn ; aucune semaine `block` émise ; {s['adjusted_weeks']} semaine(s) ajustée(s).")
    return "\n".join(lines)

