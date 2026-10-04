#!/usr/bin/env python3
"""Gabarits de périodisation structurés (#189, épopée #173) : données + validation.

## Pourquoi

Le coach écrivait chaque plan « à main levée » : la périodisation et l'affûtage
ne vivaient que dans son prompt. Ce module range les gabarits dans des DONNÉES
(`config/plans/*.json`, livrées avec le moteur — `resources/` est personnel et
hors dépôt) et les VÉRIFIE par du code, pas par de la prose :

- `load_templates(...)` / `validate_template(...)` : contrôle de schéma ET de
  cohérence avec les garde-fous (`arc_guardrails` R2, R3, R6, R7) ;
- `resolve_weeks(template, n_weeks)` : semaine par semaine, en % du pic, pour un
  nombre de semaines donné (règles d'étirement/compression ci-dessous) ;
- `match_template(...)` : choix du gabarit selon l'objectif (distance, sport).

Ce module N'ÉCRIT PAS de plan : le squelette daté (date de course, disponibilité,
historique) est l'affaire de #190. Les gabarits sont des POINTS DE DÉPART : le
profil de l'athlète, le bilan matinal et les garde-fous priment toujours.

## Format d'un gabarit (JSON, clés en anglais, textes en français)

```
{"schema_version": 1, "id": "trail_court", "label": "...", "sport": "trail"|"road",
 "applies_to": {"distance_km": {"min": 0, "max": 30}},      # [min, max[ — voir match_template
 "reference": {"distance_km": 21, "elevation_gain_m": 1000}, # indicatif
 "weeks": {"min": 8, "default": 12, "max": 16},              # semaines AVANT la course
 "peak_week_indicative": {"duration_h": {"min": 5, "max": 8}},
 "stretch_order": ["development", "specific", "base", "taper"],
 "phases": [{"id": "base", "label": "...", "weeks": {"min": 3, "max": 5},
             "volume_pct": {"start": 70, "end": 80},    # % de la semaine pic (= 100)
             "elevation_pct": {"start": 60, "end": 75}, # trail seulement
             "intensity": {"easy_pct": 85, "moderate_pct": 5, "hard_pct": 10},
             "quality_sessions": 1, "long_run": {"share_pct": 28, "cap_min": 120},
             "strength": "force_maximale"}, ...,
            {"id": "recovery", "post_race": true, "weeks": {"min": 1, "max": 2}, ...}],
 "recovery_week": {"every_n_weeks": 4, "volume_factor": 0.7, "elevation_factor": 0.6,
                   "quality_sessions_max": 1, "phases": ["base", "development", "specific"]},
 "sources": [...], "caveat": "approximation du projet : ..."}
```

Phases dans l'ordre `base` → `development` → `specific` → `taper` (affûtage) avec la
semaine de course comme DERNIÈRE semaine de l'affûtage (son `volume_pct` s'entend HORS
course), puis `recovery` (récupération) APRÈS la course, hors des semaines du bloc
(`post_race: true`).

## Règles de résolution (déterministes)

Pour `n_weeks` (borné à `weeks.min`..`weeks.max`, sinon `PlanTemplateError`) :

1. Chaque phase pré-course démarre à son `weeks.min`.
2. Les semaines restantes (`n_weeks − Σ min`) sont distribuées UNE par UNE, en
   parcourant `stretch_order` en boucle, à chaque phase qui n'a pas atteint son
   `weeks.max` — aucune aléa, mêmes entrées → mêmes sorties. Étirer ou comprimer
   suit donc la même règle : on n'est jamais en dessous des minima.
3. Dans une phase de k semaines, `volume_pct` (et `elevation_pct`) est interpolé
   linéairement de `start` à `end` (k = 1 → `end`).
4. Semaine allégée : la semaine w (1-based, sur tout le bloc) est une semaine de
   récupération si `w % every_n_weeks == 0`, si sa phase est dans
   `recovery_week.phases` et si la semaine suivante n'est PAS déjà l'affûtage (la
   semaine avant l'affûtage reste la semaine pic). Son volume (resp. D+) vaut
   `volume_factor` (resp. `elevation_factor`) × la dernière semaine non allégée, et
   ses séances de qualité sont plafonnées à `quality_sessions_max`.

## Vérifications (cœur du livrable)

`validate_template` rend la liste des problèmes (vide = conforme). Au-delà du
schéma (clés inconnues, bornes, somme des intensités = 100, phases ordonnées), il
résout le gabarit à `weeks.min`, `weeks.default` et `weeks.max` ET à chaque longueur
intermédiaire, et vérifie sur les semaines résolues, avec les seuils des
garde-fous (`DEFAULT_*`, ou ceux du workspace via `limits=`) :

- R2 : hausse du volume ≤ `r2_volume_increase_max_pct` vs la référence configurée
  (`r2_volume_reference` : `mean4` = moyenne des 4 semaines précédentes divisée par 4,
  défaut du moteur, ou `previous_week`), calculée par `arc_guardrails._pct_increase`
  (même arrondi) ; les semaines d'avant le bloc valent la semaine 1 (volume tenu) ;
  ET vs la dernière semaine non allégée (contrôle du projet, plus strict) ;
- R3 : idem pour le D+ (trail) ;
- R6 : part de la sortie longue ≤ `r6_long_run_share_max_pct` ;
- R7 : ≤ `MAX_QUALITY_SESSIONS` séances de qualité par semaine (le gabarit ne
  place pas de jours : la non-consécutivité est l'affaire du squelette, #190) ;
- semaines allégées présentes dès que le bloc compte ≥ 2 × `every_n_weeks` semaines ;
- affûtage ⊂ dernières semaines, volume décroissant et sous le pic.

Les gabarits ne remplacent JAMAIS les garde-fous : chaque semaine écrite passe
encore `arc_guardrails.py check` sur l'historique réel de l'athlète.

Bibliothèque standard uniquement (CONTRIBUTING.md). `arc_index` importe ce module
pour sa CLI et `arc_guardrails` importe `arc_index` : ce module importe donc
`arc_guardrails` tardivement (dans la validation) pour réutiliser son calcul ; les
seuils par défaut sont copiés ici et un test verrouille leur égalité avec
`arc_guardrails.DEFAULT_*`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

ENGINE = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ENGINE / "config" / "plans"

PHASES_PRE_RACE = ("base", "development", "specific", "taper")
PHASE_RECOVERY = "recovery"
PHASE_LABELS_FR = {
    "base": "Base", "development": "Développement", "specific": "Spécifique",
    "taper": "Affûtage", "recovery": "Récupération",
}
SPORTS = ("trail", "road")

# Emphases de renforcement : NOMS seulement (la bibliothèque d'exercices est #191).
STRENGTH_EMPHASES = ("force_maximale", "force_endurance", "pliometrie_excentrique", "entretien", "mobilite")

# Seuils des garde-fous (copie des `arc_guardrails.DEFAULT_*` ; égalité testée).
GUARDRAIL_DEFAULTS = {
    "r2_volume_increase_max_pct": 10.0,
    "r3_elevation_increase_max_pct": 10.0,
    "r6_long_run_share_max_pct": 35.0,
    "r2_volume_reference": "mean4",
}
# R7 (deux séances de qualité sur deux jours consécutifs) : sans jours dans un gabarit,
# on plafonne le NOMBRE (approximation du projet) pour que le squelette puisse les espacer.
MAX_QUALITY_SESSIONS = 3
MIN_EASY_PCT = 75.0          # « 80/20 » polarisé, avec une marge d'arrondi (approximation du projet)
MAX_LONG_RUN_CAP_MIN = 600   # 10 h : au-delà, ce n'est plus une « sortie longue » planifiable
MIN_TAPER_FINAL_REDUCTION_PCT = 25.0

ASSUMPTIONS = {
    "nature": (
        "Tous les nombres des gabarits (durées de phase, % du pic, D+, répartition d'intensité, "
        "plafonds de sortie longue, fréquence des semaines allégées, affûtage) sont des "
        "« approximations du projet » : des points de départ prudents, pas des prescriptions "
        "issues d'un protocole publié. Le profil de l'athlète, le bilan matinal et les garde-fous "
        "priment toujours."),
    "sources": (
        "Deux sources seulement, vérifiées (Crossref) et citées pour la DIRECTION, jamais pour un "
        "chiffre : Mujika & Padilla (2003), Med Sci Sports Exerc 35(7):1182-1187, doi "
        "10.1249/01.MSS.0000074448.73931.11 — affûtage (réduction de volume, intensité conservée) ; "
        "Seiler (2010), Int J Sports Physiol Perform 5(3):276-291, doi 10.1123/ijspp.5.3.276 — "
        "distribution d'intensité polarisée. Aucun plan commercial n'est reproduit."),
    "guardrail_consistency": (
        "La cohérence avec R2/R3/R6/R7 est vérifiée sur les semaines RÉSOLUES, pas seulement "
        "déclarée. Elle porte sur les seuils par défaut du moteur (ou ceux du workspace via la "
        "CLI) ; elle ne garantit rien sur l'historique réel de l'athlète, que seul "
        "`arc_guardrails.py check` évalue."),
    "held_volume": (
        "Les gabarits démarrent PRÈS du pic (≈ 83–92 % selon le format) : avec R2/R3 à +10 % face à "
        "la moyenne de 4 semaines et une semaine allégée toutes les 4, la croissance d'un cycle de "
        "4 semaines est de quelques pourcents seulement — une montée depuis un volume bas ferait "
        "réagir les garde-fous. Le pic n'est donc PAS une cible absolue : il se DÉDUIT du volume que "
        "l'athlète tient sur ses 4 dernières semaines (pic = ce volume × `peak_from_current`). Si ce "
        "pic est trop bas pour l'objectif, la réponse est un bloc de mise en route préalable ou un "
        "objectif revu, jamais un gabarit étiré. Les semaines d'avant le bloc, inconnues du gabarit, "
        "valent la semaine 1 dans le calcul de la référence `mean4`."),
    "stretching": (
        "Étirement/compression : minima d'abord, puis une semaine à la fois dans l'ordre de "
        "`stretch_order`, en boucle. Choix de conception du projet, sans fondement physiologique "
        "propre : il garantit seulement un résultat déterministe et conforme aux vérifications."),
}


class PlanTemplateError(ValueError):
    """Gabarit introuvable, invalide, ou nombre de semaines hors des bornes."""


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------


def load_template_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanTemplateError(f"{path.name} : lecture/JSON impossible ({exc}).")
    if not isinstance(data, dict):
        raise PlanTemplateError(f"{path.name} : un objet JSON est attendu.")
    return data


def load_templates(directory: Optional[Path] = None) -> List[dict]:
    """Tous les `*.json` du dossier, triés par nom de fichier. Ne valide pas."""
    directory = directory or TEMPLATES_DIR
    return [load_template_file(p) for p in sorted(directory.glob("*.json"))]


def get_template(template_id: str, templates: Optional[List[dict]] = None) -> dict:
    templates = templates if templates is not None else load_templates()
    for t in templates:
        if t.get("id") == template_id:
            return t
    known = ", ".join(sorted(str(t.get("id")) for t in templates))
    raise PlanTemplateError(f"gabarit inconnu « {template_id} » (disponibles : {known}).")


def match_template(templates: List[dict], distance_km: float, sport: str = "trail") -> Optional[dict]:
    """Gabarit dont `applies_to.distance_km` contient la distance (borne basse incluse,
    haute exclue), pour ce sport ; `None` si aucun. Les bandes d'un même sport ne se
    chevauchent pas (vérifié par `validate_templates`), donc au plus un résultat."""
    for t in templates:
        if t.get("sport") != sport:
            continue
        band = (t.get("applies_to") or {}).get("distance_km") or {}
        try:
            if band["min"] <= distance_km < band["max"]:
                return t
        except (KeyError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Résolution semaine par semaine
# ---------------------------------------------------------------------------


def _pre_race_phases(template: dict) -> List[dict]:
    return [p for p in template["phases"] if p["id"] in PHASES_PRE_RACE]


def allocate_phase_weeks(template: dict, n_weeks: int) -> Dict[str, int]:
    """Semaines par phase pré-course pour `n_weeks` — règles 1 et 2 du docstring."""
    w = template["weeks"]
    if not isinstance(n_weeks, int) or isinstance(n_weeks, bool) or not w["min"] <= n_weeks <= w["max"]:
        raise PlanTemplateError(
            f"{template['id']} : {n_weeks!r} semaines hors de {w['min']}–{w['max']}.")
    phases = {p["id"]: p for p in _pre_race_phases(template)}
    alloc = {pid: p["weeks"]["min"] for pid, p in phases.items()}
    extra = n_weeks - sum(alloc.values())
    order = [pid for pid in template.get("stretch_order", []) if pid in phases]
    if extra < 0 or (extra and not order):
        raise PlanTemplateError(f"{template['id']} : {n_weeks} semaines non réalisables avec ces phases.")
    while extra > 0:
        progressed = False
        for pid in order:
            if extra > 0 and alloc[pid] < phases[pid]["weeks"]["max"]:
                alloc[pid] += 1
                extra -= 1
                progressed = True
        if not progressed:
            raise PlanTemplateError(f"{template['id']} : {n_weeks} semaines dépassent les maxima de phase.")
    return alloc


def _interp(spec: Optional[dict], i: int, k: int) -> Optional[float]:
    if spec is None:
        return None
    if k <= 1:
        return float(spec["end"])
    return spec["start"] + (spec["end"] - spec["start"]) * i / (k - 1)


def resolve_weeks(template: dict, n_weeks: int, with_recovery: bool = True) -> List[dict]:
    """Semaines du bloc, de 1 à `n_weeks`, puis (si `with_recovery`) les semaines de
    récupération post-course (index > n_weeks, `post_race: true`)."""
    alloc = allocate_phase_weeks(template, n_weeks)
    rec = template.get("recovery_week") or {}
    every = rec.get("every_n_weeks")
    # Découpage en (phase, i, k)
    slots = []
    for p in _pre_race_phases(template):
        k = alloc[p["id"]]
        for i in range(k):
            slots.append((p, i, k))
    weeks: List[dict] = []
    last_build_vol = last_build_elev = None
    for idx, (p, i, k) in enumerate(slots, start=1):
        vol = _interp(p.get("volume_pct"), i, k)
        elev = _interp(p.get("elevation_pct"), i, k)
        quality = p["quality_sessions"]
        kind = "taper" if p["id"] == "taper" else "build"
        next_is_taper = idx < len(slots) and slots[idx][0]["id"] == "taper"
        if (kind == "build" and every and idx % every == 0 and p["id"] in rec.get("phases", [])
                and not next_is_taper and last_build_vol is not None):
            kind = "recovery_week"
            vol = last_build_vol * rec["volume_factor"]
            if elev is not None and last_build_elev is not None:
                elev = last_build_elev * rec.get("elevation_factor", rec["volume_factor"])
            quality = min(quality, rec["quality_sessions_max"])
        else:
            last_build_vol, last_build_elev = vol, elev
        weeks.append(_week_record(idx, p, kind, vol, elev, quality, post_race=False))
    if with_recovery:
        post = next((p for p in template["phases"] if p["id"] == PHASE_RECOVERY), None)
        if post:
            for j in range(post["weeks"]["min"]):
                weeks.append(_week_record(
                    n_weeks + 1 + j, post, "post_race",
                    _interp(post.get("volume_pct"), j, post["weeks"]["min"]),
                    _interp(post.get("elevation_pct"), j, post["weeks"]["min"]),
                    post["quality_sessions"], post_race=True))
    return weeks


def _week_record(index: int, phase: dict, kind: str, vol, elev, quality: int, post_race: bool) -> dict:
    return {
        "week": index,
        "phase": phase["id"],
        "phase_label": PHASE_LABELS_FR[phase["id"]],
        "kind": kind,
        "post_race": post_race,
        "volume_pct": None if vol is None else round(vol, 1),
        "elevation_pct": None if elev is None else round(elev, 1),
        "quality_sessions_max": quality,
        "long_run_share_pct": phase["long_run"]["share_pct"],
        "long_run_cap_min": phase["long_run"]["cap_min"],
        "intensity": dict(phase["intensity"]),
        "strength": phase["strength"],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_TOP_KEYS = {"schema_version", "id", "label", "sport", "applies_to", "reference", "weeks",
             "peak_week_indicative", "stretch_order", "phases", "recovery_week", "sources", "caveat"}
_PHASE_KEYS = {"id", "label", "post_race", "weeks", "volume_pct", "elevation_pct", "intensity",
               "quality_sessions", "long_run", "strength"}
_REC_KEYS = {"every_n_weeks", "volume_factor", "elevation_factor", "quality_sessions_max", "phases"}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _range(errors: List[str], where: str, spec: Any, lo: float, hi: float, integer: bool = False) -> bool:
    """`{min, max}` avec lo ≤ min ≤ max ≤ hi."""
    ok = isinstance(spec, dict) and set(spec) >= {"min", "max"} and set(spec) <= {"min", "max", "default"}
    check = _int if integer else _num
    if not ok or not check(spec.get("min")) or not check(spec.get("max")):
        errors.append(f"{where} : {{min, max}} {'entiers' if integer else 'numériques'} attendus.")
        return False
    if not (lo <= spec["min"] <= spec["max"] <= hi):
        errors.append(f"{where} : doit vérifier {lo} ≤ min ≤ max ≤ {hi} (reçu {spec['min']}–{spec['max']}).")
        return False
    return True


def _start_end(errors: List[str], where: str, spec: Any) -> bool:
    if not (isinstance(spec, dict) and set(spec) == {"start", "end"} and _num(spec["start"]) and _num(spec["end"])):
        errors.append(f"{where} : {{start, end}} numériques attendus.")
        return False
    if not (0 < spec["start"] <= 100 and 0 < spec["end"] <= 100):
        errors.append(f"{where} : pourcentages dans ]0, 100] attendus (reçu {spec['start']}→{spec['end']}).")
        return False
    return True


def _validate_phase(errors: List[str], tid: str, p: Any, sport: str) -> None:
    if not isinstance(p, dict):
        errors.append(f"{tid} : une phase doit être un objet.")
        return
    pid = p.get("id")
    where = f"{tid}.{pid}"
    unknown = set(p) - _PHASE_KEYS
    if unknown:
        errors.append(f"{where} : clés inconnues {sorted(unknown)}.")
    if pid not in PHASES_PRE_RACE + (PHASE_RECOVERY,):
        errors.append(f"{where} : id de phase inconnu (attendu {PHASES_PRE_RACE + (PHASE_RECOVERY,)}).")
        return
    if not isinstance(p.get("label"), str) or not p["label"].strip():
        errors.append(f"{where} : `label` (texte français) attendu.")
    if (pid == PHASE_RECOVERY) != (p.get("post_race") is True):
        errors.append(f"{where} : `post_race: true` est exigé pour `recovery`, et seulement pour elle.")
    _range(errors, f"{where}.weeks", p.get("weeks"), 1, 52, integer=True)
    _start_end(errors, f"{where}.volume_pct", p.get("volume_pct"))
    if sport == "trail":
        _start_end(errors, f"{where}.elevation_pct", p.get("elevation_pct"))
    elif "elevation_pct" in p:
        errors.append(f"{where} : `elevation_pct` n'a pas de sens pour un gabarit route.")
    inten = p.get("intensity")
    keys = ("easy_pct", "moderate_pct", "hard_pct")
    if not (isinstance(inten, dict) and set(inten) == set(keys) and all(_num(inten[k]) and 0 <= inten[k] <= 100 for k in keys)):
        errors.append(f"{where}.intensity : {keys} dans [0, 100] attendus.")
    else:
        if abs(sum(inten[k] for k in keys) - 100) > 0.01:
            errors.append(f"{where}.intensity : la somme doit valoir 100 (reçu {sum(inten[k] for k in keys):g}).")
        if inten["easy_pct"] < MIN_EASY_PCT:
            errors.append(f"{where}.intensity : easy_pct {inten['easy_pct']:g} < {MIN_EASY_PCT:g} "
                          "(répartition polarisée ~80/20).")
    q = p.get("quality_sessions")
    if not _int(q) or not 0 <= q <= MAX_QUALITY_SESSIONS:
        errors.append(f"{where}.quality_sessions : entier 0–{MAX_QUALITY_SESSIONS} attendu (R7).")
    lr = p.get("long_run")
    if not (isinstance(lr, dict) and set(lr) == {"share_pct", "cap_min"} and _num(lr["share_pct"]) and _int(lr["cap_min"])):
        errors.append(f"{where}.long_run : {{share_pct, cap_min}} attendus.")
    else:
        if not 0 < lr["share_pct"] <= 100:
            errors.append(f"{where}.long_run.share_pct : dans ]0, 100] attendu.")
        if not 0 < lr["cap_min"] <= MAX_LONG_RUN_CAP_MIN:
            errors.append(f"{where}.long_run.cap_min : 1–{MAX_LONG_RUN_CAP_MIN} minutes attendues.")
    if p.get("strength") not in STRENGTH_EMPHASES:
        errors.append(f"{where}.strength : {p.get('strength')!r} hors de {STRENGTH_EMPHASES}.")


def _structure_errors(t: dict) -> List[str]:
    """Contrôles de schéma et de structure ; si non vide, la résolution n'est pas tentée."""
    errors: List[str] = []
    tid = t.get("id") if isinstance(t.get("id"), str) and t.get("id") else "?"
    unknown = set(t) - _TOP_KEYS
    if unknown:
        errors.append(f"{tid} : clés inconnues {sorted(unknown)}.")
    if t.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{tid} : schema_version {SCHEMA_VERSION} attendu.")
    if tid == "?":
        errors.append("`id` (texte) manquant.")
    if t.get("sport") not in SPORTS:
        errors.append(f"{tid} : sport {t.get('sport')!r} hors de {SPORTS}.")
    sport = t.get("sport")
    if not isinstance(t.get("label"), str) or not t["label"].strip():
        errors.append(f"{tid} : `label` attendu.")
    if not isinstance(t.get("caveat"), str) or "approximation du projet" not in t["caveat"]:
        errors.append(f"{tid} : `caveat` doit contenir « approximation du projet ».")
    srcs = t.get("sources")
    if not (isinstance(srcs, list) and all(isinstance(s, str) and s for s in srcs)):
        errors.append(f"{tid} : `sources` : liste de textes attendue (vide acceptée).")
    ap = t.get("applies_to")
    if not (isinstance(ap, dict) and set(ap) == {"distance_km"}):
        errors.append(f"{tid} : applies_to = {{distance_km: {{min, max}}}} attendu.")
    else:
        _range(errors, f"{tid}.applies_to.distance_km", ap["distance_km"], 0, 1000)
        if isinstance(ap["distance_km"], dict) and ap["distance_km"].get("min") == ap["distance_km"].get("max"):
            errors.append(f"{tid}.applies_to.distance_km : bande vide.")
    ref = t.get("reference")
    if not (isinstance(ref, dict) and set(ref) <= {"distance_km", "elevation_gain_m"} and all(_num(v) and v >= 0 for v in ref.values()) and "distance_km" in ref):
        errors.append(f"{tid} : reference = {{distance_km[, elevation_gain_m]}} positifs attendus.")
    w = t.get("weeks")
    if _range(errors, f"{tid}.weeks", w, 1, 52, integer=True):
        if not (_int(w.get("default")) and w["min"] <= w["default"] <= w["max"]):
            errors.append(f"{tid}.weeks.default : entier dans [min, max] attendu.")
    pk = t.get("peak_week_indicative")
    if not (isinstance(pk, dict) and set(pk) == {"duration_h"}):
        errors.append(f"{tid} : peak_week_indicative = {{duration_h: {{min, max}}}} attendu.")
    else:
        _range(errors, f"{tid}.peak_week_indicative.duration_h", pk["duration_h"], 0.5, 40)
    phases = t.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append(f"{tid} : `phases` : liste non vide attendue.")
        return errors
    for p in phases:
        _validate_phase(errors, tid, p, sport)
    ids = [p.get("id") for p in phases if isinstance(p, dict)]
    expected = list(PHASES_PRE_RACE) + [PHASE_RECOVERY]
    if ids != expected:
        errors.append(f"{tid} : phases dans l'ordre {expected} attendues (reçu {ids}).")
    so = t.get("stretch_order")
    if not (isinstance(so, list) and set(so) == set(PHASES_PRE_RACE) and len(so) == len(PHASES_PRE_RACE)):
        errors.append(f"{tid} : stretch_order doit être une permutation de {list(PHASES_PRE_RACE)}.")
    rec = t.get("recovery_week")
    if not (isinstance(rec, dict) and set(rec) <= _REC_KEYS and {"every_n_weeks", "volume_factor", "quality_sessions_max", "phases"} <= set(rec)):
        errors.append(f"{tid}.recovery_week : {sorted(_REC_KEYS)} attendus (elevation_factor facultatif en route).")
    else:
        if not (_int(rec["every_n_weeks"]) and 2 <= rec["every_n_weeks"] <= 6):
            errors.append(f"{tid}.recovery_week.every_n_weeks : entier 2–6 attendu.")
        for key in ("volume_factor", "elevation_factor"):
            if key in rec and not (_num(rec[key]) and 0.4 <= rec[key] <= 0.9):
                errors.append(f"{tid}.recovery_week.{key} : dans [0.4, 0.9] attendu.")
        if sport == "trail" and "elevation_factor" not in rec:
            errors.append(f"{tid}.recovery_week.elevation_factor : requis en trail.")
        if not (_int(rec["quality_sessions_max"]) and 0 <= rec["quality_sessions_max"] <= 1):
            errors.append(f"{tid}.recovery_week.quality_sessions_max : 0 ou 1 attendu.")
        if not (isinstance(rec["phases"], list) and rec["phases"] and set(rec["phases"]) <= {"base", "development", "specific"}):
            errors.append(f"{tid}.recovery_week.phases : sous-ensemble non vide de base/development/specific.")
    if errors:
        return errors
    # Cohérence des bornes de semaines : toute longueur de [min, max] doit être réalisable.
    pre = _pre_race_phases(t)
    lo = sum(p["weeks"]["min"] for p in pre)
    hi = sum(p["weeks"]["max"] for p in pre)
    if lo > w["min"]:
        errors.append(f"{tid} : Σ minima de phases ({lo}) > weeks.min ({w['min']}) — les longueurs courtes ne sont pas réalisables.")
    if hi < w["max"]:
        errors.append(f"{tid} : Σ maxima de phases ({hi}) < weeks.max ({w['max']}) — les longueurs longues ne sont pas réalisables.")
    taper = next(p for p in pre if p["id"] == "taper")
    if taper["volume_pct"]["start"] < taper["volume_pct"]["end"]:
        errors.append(f"{tid}.taper : le volume doit décroître (start ≥ end).")
    if 100 - taper["volume_pct"]["end"] < MIN_TAPER_FINAL_REDUCTION_PCT:
        errors.append(f"{tid}.taper : réduction finale < {MIN_TAPER_FINAL_REDUCTION_PCT:g} % du pic "
                      f"(volume final {taper['volume_pct']['end']:g} %).")
    peak = max(p["volume_pct"]["end"] for p in pre if p["id"] != "taper")
    if peak != 100:
        errors.append(f"{tid} : la semaine pic doit valoir 100 % (max des fins de phase = {peak:g}).")
    if t["sport"] == "trail":
        peak_e = max(p["elevation_pct"]["end"] for p in pre if p["id"] != "taper")
        if peak_e != 100:
            errors.append(f"{tid} : le D+ pic doit valoir 100 % (max des fins de phase = {peak_e:g}).")
    return errors


def _reference_value(values: List[float], i: int, reference: str) -> float:
    """Référence R2/R3 de la semaine `i` (0-based), avec la sémantique d'`arc_guardrails`
    (`_reference_totals`) : `previous_week` = la semaine précédente ; `mean4` = la moyenne
    des 4 semaines calendaires précédentes, TOUJOURS divisée par 4. Les semaines d'avant le
    bloc sont inconnues : elles valent la semaine 1 (prémisse du gabarit — le bloc part d'un
    volume que l'athlète tient déjà, voir `ASSUMPTIONS["held_volume"]`)."""
    padded = [values[0]] * 4 + list(values)
    j = i + 4
    if reference == "previous_week":
        return padded[j - 1]
    return sum(padded[j - 4:j]) / 4.0


def _consistency_errors(t: dict, limits: dict) -> List[str]:
    # Import tardif : arc_guardrails importe arc_index, qui importe ce module pour sa CLI.
    import arc_guardrails as GR
    errors: List[str] = []
    tid = t["id"]
    r2, r3, r6 = (limits["r2_volume_increase_max_pct"], limits["r3_elevation_increase_max_pct"],
                  limits["r6_long_run_share_max_pct"])
    reference = limits.get("r2_volume_reference", GR.DEFAULT_VOLUME_REFERENCE)
    eps = 1e-6
    every = t["recovery_week"]["every_n_weeks"]
    for n in range(t["weeks"]["min"], t["weeks"]["max"] + 1):
        try:
            weeks = [w for w in resolve_weeks(t, n, with_recovery=False)]
        except PlanTemplateError as exc:
            errors.append(str(exc))
            continue
        tag = f"{tid}@{n}s"
        metrics = [("volume_pct", r2, "R2")]
        if t["sport"] == "trail":
            metrics.append(("elevation_pct", r3, "R3"))
        for key, limit, rule in metrics:
            values = [wk[key] for wk in weeks]
            last_build = None
            for i, wk in enumerate(weeks):
                v = wk[key]
                # Même calcul et même arrondi qu'`arc_guardrails._eval_r2/_eval_r3`
                # (`_pct_increase` arrondi à 0,1, violation si strictement au-dessus).
                up = GR._pct_increase(v, _reference_value(values, i, reference))
                # Avec `previous_week`, la reprise qui suit une semaine allégée dépasse
                # mécaniquement le seuil (100 / 80 = +25 %) : arc_guardrails l'AVERTIRA bien
                # sur l'historique réel, mais c'est une propriété de la référence, pas un
                # défaut du gabarit — signalée une fois par `reference_notes`, pas ici, tant
                # que la reprise ne dépasse pas aussi la dernière semaine non allégée.
                rebound = (reference == "previous_week" and i > 0 and weeks[i - 1]["kind"] == "recovery_week"
                           and last_build is not None
                           and (GR._pct_increase(v, last_build) or 0.0) <= limit)
                if up is not None and up > limit and not rebound:
                    errors.append(f"{tag} : {rule} semaine {wk['week']} : {key} +{up:g} % vs {reference} "
                                  f"(> {limit:g} %).")
                if wk["kind"] != "taper":
                    if last_build is not None and wk["kind"] == "build":
                        up = GR._pct_increase(v, last_build)
                        if up is not None and up > limit:
                            errors.append(f"{tag} : {rule} semaine {wk['week']} : {key} +{up:.1f} % vs la dernière "
                                          f"semaine non allégée (> {limit:g} %).")
                    if wk["kind"] == "build":
                        last_build = v
        for wk in weeks:
            if wk["long_run_share_pct"] > r6 + eps:
                errors.append(f"{tag} : R6 semaine {wk['week']} : sortie longue {wk['long_run_share_pct']:g} % > {r6:g} %.")
            if wk["quality_sessions_max"] > MAX_QUALITY_SESSIONS:
                errors.append(f"{tag} : R7 semaine {wk['week']} : {wk['quality_sessions_max']} séances de qualité.")
        # affûtage ⊂ dernières semaines, décroissant, sous le pic
        kinds = [wk["kind"] for wk in weeks]
        first_taper = kinds.index("taper") if "taper" in kinds else None
        if first_taper is None or any(k != "taper" for k in kinds[first_taper:]):
            errors.append(f"{tag} : l'affûtage doit occuper les dernières semaines, sans interruption.")
        else:
            tv = [wk["volume_pct"] for wk in weeks[first_taper:]]
            if any(b > a + eps for a, b in zip(tv, tv[1:])) or max(tv) >= max(wk["volume_pct"] for wk in weeks[:first_taper]):
                errors.append(f"{tag} : l'affûtage doit décroître et rester sous la semaine pic.")
        if n >= 2 * every and "recovery_week" not in kinds:
            errors.append(f"{tag} : aucune semaine allégée alors que le bloc compte ≥ {2 * every} semaines.")
    return errors


def reference_notes(limits: Optional[dict] = None) -> List[str]:
    """Remarques (pas des problèmes) liées aux réglages R2/R3 du workspace."""
    if (limits or {}).get("r2_volume_reference", GUARDRAIL_DEFAULTS["r2_volume_reference"]) != "previous_week":
        return []
    return ["`[guardrails].r2_volume_reference = \"previous_week\"` : la semaine qui suit chaque "
            "semaine allégée dépasse mécaniquement le seuil R2/R3 face à la semaine précédente. "
            "`arc_guardrails.py check` l'avertira sur l'historique réel ; c'est attendu (la reprise "
            "reste sous la dernière semaine non allégée + seuil, ce que la validation vérifie)."]


def validate_template(template: dict, limits: Optional[dict] = None) -> List[str]:
    """Liste des problèmes (vide = conforme). `limits` : seuils des garde-fous
    (clés de `GUARDRAIL_DEFAULTS`) ; défaut = seuils du moteur."""
    if not isinstance(template, dict):
        return ["gabarit : un objet est attendu."]
    errors = _structure_errors(template)
    if errors:
        return errors
    merged = dict(GUARDRAIL_DEFAULTS)
    merged.update(limits or {})
    return _consistency_errors(template, merged)


def validate_templates(templates: List[dict], limits: Optional[dict] = None) -> List[str]:
    """Valide chaque gabarit + l'unicité des ids + l'absence de chevauchement des bandes
    de distance pour un même sport."""
    errors: List[str] = []
    seen: Dict[str, int] = {}
    for t in templates:
        tid = t.get("id") if isinstance(t, dict) else None
        if tid in seen:
            errors.append(f"id de gabarit en double : {tid}.")
        seen[tid] = 1
        errors.extend(validate_template(t, limits))
    bands: Dict[str, List[tuple]] = {}
    for t in templates:
        try:
            b = t["applies_to"]["distance_km"]
            bands.setdefault(t["sport"], []).append((b["min"], b["max"], t["id"]))
        except (KeyError, TypeError):
            continue
    for sport, items in bands.items():
        items.sort()
        for (a0, a1, aid), (b0, b1, bid) in zip(items, items[1:]):
            if b0 < a1:
                errors.append(f"bandes de distance qui se chevauchent ({sport}) : {aid} [{a0}, {a1}[ et {bid} [{b0}, {b1}[.")
    return errors


# ---------------------------------------------------------------------------
# Rendu (CLI `arc_index.py plan-templates`)
# ---------------------------------------------------------------------------


def summarize(template: dict) -> dict:
    return {
        "id": template["id"], "label": template["label"], "sport": template["sport"],
        "distance_km": template["applies_to"]["distance_km"], "weeks": template["weeks"],
        "reference": template["reference"],
    }


def render_text(template: dict, weeks: List[dict], n_weeks: int, problems: List[str]) -> str:
    lines = [f"{template['label']} — {n_weeks} semaines avant la course (gabarit `{template['id']}`)",
             f"Pic indicatif : {template['peak_week_indicative']['duration_h']['min']:g}–"
             f"{template['peak_week_indicative']['duration_h']['max']:g} h/semaine.",
             "Pourcentages du volume (et du D+) de la semaine pic. " + template["caveat"],
             "Pic = volume tenu sur les 4 dernières semaines × "
             + " ; D+ × ".join(f"{v:g}" for v in peak_from_current(weeks, template["sport"]).values())
             + " (jamais plus : la semaine 1 suppose ce volume déjà tenu).", ""]
    trail = template["sport"] == "trail"
    header = "Sem | Phase          | Type          | Vol % |" + (" D+ % |" if trail else "") + " Qualité | Sortie longue | Intensité f/m/d | Renfo"
    lines.append(header)
    for wk in weeks:
        i = wk["intensity"]
        lines.append(
            f"{wk['week']:>3} | {wk['phase_label']:<14} | {wk['kind']:<13} | {wk['volume_pct']:>5.1f} |"
            + (f" {wk['elevation_pct']:>4.1f} |" if trail else "")
            + f" {wk['quality_sessions_max']:>7} | {wk['long_run_share_pct']:g} % ≤ {wk['long_run_cap_min']} min | "
            f"{i['easy_pct']:g}/{i['moderate_pct']:g}/{i['hard_pct']:g} | {wk['strength']}")
    lines.append("")
    lines.append("Vérifications garde-fous : " + ("conforme." if not problems else "; ".join(problems)))
    return "\n".join(lines)


def plan_templates_report(directory: Optional[Path] = None, template_id: Optional[str] = None,
                          n_weeks: Optional[int] = None, distance_km: Optional[float] = None,
                          sport: Optional[str] = None, limits: Optional[dict] = None) -> dict:
    """Rapport JSON de la CLI : liste (sans `template_id`/`distance_km`) ou détail résolu."""
    templates = load_templates(directory)
    if template_id is None and distance_km is not None:
        chosen = match_template(templates, distance_km, sport or "trail")
        if chosen is None:
            return {"matched": None, "distance_km": distance_km, "sport": sport or "trail",
                    "reason": "aucun gabarit pour cette distance — construire le bloc sans gabarit, "
                              "en le disant à l'athlète.", "templates": [summarize(t) for t in templates]}
        template_id = chosen["id"]
    if template_id is None:
        return {"templates": [summarize(t) for t in templates],
                "problems": validate_templates(templates, limits), "notes": reference_notes(limits),
                "assumptions": ASSUMPTIONS}
    t = get_template(template_id, templates)
    problems = validate_template(t, limits)
    n = n_weeks if n_weeks is not None else t["weeks"]["default"]
    weeks = resolve_weeks(t, n)
    return {"template": t, "n_weeks": n, "phase_weeks": allocate_phase_weeks(t, n), "weeks": weeks,
            "peak_from_current": peak_from_current(weeks, t["sport"]),
            "problems": problems, "notes": reference_notes(limits),
            "guardrail_limits": {**GUARDRAIL_DEFAULTS, **(limits or {})},
            "assumptions": ASSUMPTIONS}


def peak_from_current(weeks: List[dict], sport: str) -> dict:
    """Multiplicateurs « pic = volume tenu actuellement × facteur » (et D+ en trail).

    Le gabarit est une FORME en % du pic qui démarre à `weeks[0]` : la semaine 1 suppose
    le volume que l'athlète tient déjà (`ASSUMPTIONS["held_volume"]`). Le pic atteignable
    sans faire réagir R2/R3 vaut donc ce volume × 100 / `volume_pct` de la semaine 1 —
    jamais plus. Le squelette (#190) et le coach dérivent le pic d'ici, pas l'inverse."""
    first = weeks[0]
    out = {"volume_factor": round(100.0 / first["volume_pct"], 3)}
    if sport == "trail" and first.get("elevation_pct"):
        out["elevation_factor"] = round(100.0 / first["elevation_pct"], 3)
    return out
