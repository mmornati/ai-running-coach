#!/usr/bin/env python3
"""Bibliothèque de renforcement / mobilité et programmes par phase ou par usage
(#191, épopée #173). Bibliothèque standard uniquement.

## Pourquoi

Le coach inventait ses exercices à chaque séance de renforcement. Ce module charge une
bibliothèque LIVRÉE avec le moteur (`config/strength/exercises.json`,
`config/strength/programmes.json` — pas dans `resources/`, exclu du dépôt) et fait le calcul
déterministe : validation, choix d'un programme, repli selon le matériel disponible, charge de
l'affûtage, charge utile Garmin ou texte pour intervals.icu. Le modèle choisit et habille ; il
n'invente ni exercice, ni identifiant Garmin, ni série/répétition.

## Correspondance Garmin — jamais devinée

`GARMIN_VERIFIED` est la SEULE liste de couples (category, exercise) acceptée dans les données.
Chaque couple a été vérifié le 2026-10-04 dans le catalogue public de Garmin Connect
(https://connect.garmin.com/web-data/exercises/Exercises.json, 47 catégories, 1531 exercices),
que le serveur `garmin-mcp` épinglé par `install.sh` (Taxuspt/garmin_mcp, commit cfc5d79,
`workout_builders.build_strength_json`) désigne comme référence des catégories, et recoupé avec
`garminconnect/exercises.py` (cyberjunky/python-garminconnect, commit 218e72c). Un exercice sans
équivalent vérifié porte `garmin: null` : il part SANS category/exerciseName (le serveur accepte
une category absente), son nom français reste dans la description de l'étape.

Ajouter un exercice mappé = ajouter d'abord son couple ici, après vérification dans le catalogue.

## Phase / emphase

Les gabarits de périodisation (#189, `config/plans/*.json`, champ `strength`) nomment une EMPHASE
par phase ; les programmes de phase portent les mêmes identifiants (`STRENGTH_EMPHASES`).

    python3 scripts/arc_index.py strength [--phase P] [--use U] [--equipment …] [--text|--garmin-json]
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ENGINE_DIR = Path(__file__).resolve().parent.parent
STRENGTH_DIR = ENGINE_DIR / "config" / "strength"

# Mêmes identifiants que `arc_plan_templates.STRENGTH_EMPHASES` (#189) : un test les compare
# dès que ce module est présent.
STRENGTH_EMPHASES = ("force_maximale", "force_endurance", "pliometrie_excentrique", "entretien", "mobilite")
PHASES = ("base", "development", "specific", "taper", "recovery")
PHASE_TO_EMPHASIS = {"base": "force_maximale", "development": "force_endurance",
                     "specific": "pliometrie_excentrique", "taper": "entretien", "recovery": "mobilite"}
PHASE_LABELS_FR = {"base": "Base", "development": "Développement", "specific": "Spécifique",
                   "taper": "Affûtage", "recovery": "Récupération"}
USES = ("descente", "cheville", "hanches", "pied")
EQUIPMENT = ("none", "elastic", "dumbbell", "step", "box")
GROUPS = ("force", "pliometrie", "mobilite", "proprioception")
MODES = ("reps", "time")
FATIGUE_LEVELS = ("low", "moderate", "high")
TARGETS = (
    "quadriceps", "quadriceps_excentrique", "ischio_jambiers", "fessiers", "abducteurs_hanche", "adducteurs",
    "mollet_gastrocnemien", "soleaire", "tibial_anterieur", "intrinseques_pied", "gainage", "pliometrie",
    "equilibre", "mobilite_cheville", "mobilite_hanche", "mobilite_thoracique",
)
DEFAULT_REPS_WHEN_COERCED = 12     # repli de mode (temps -> répétitions), approximation du projet
DEFAULT_SECONDS_WHEN_COERCED = 30  # repli de mode (répétitions -> temps), approximation du projet

# Couples (category, exercise) vérifiés — voir la docstring. N'ajouter qu'après vérification.
GARMIN_VERIFIED: Dict[str, Tuple[str, ...]] = {
    "BANDED_EXERCISES": ("CLAM_SHELLS", "LATERAL_BAND_WALKS"),
    "CALF_RAISE": ("SINGLE_LEG_BENT_KNEE_CALF_RAISE", "SINGLE_LEG_STANDING_CALF_RAISE",
                   "SINGLE_LEG_STANDING_DUMBBELL_CALF_RAISE", "STANDING_CALF_RAISE"),
    "CARRY": ("FARMERS_WALK_ON_TOES",),
    "DEADLIFT": ("SINGLE_LEG_ROMANIAN_DEADLIFT_WITH_DUMBBELL",),
    "HIP_RAISE": ("HIP_RAISE", "SINGLE_LEG_HIP_RAISE", "SINGLE_LEG_HIP_RAISE_WITH_FOOT_ON_BENCH"),
    "HIP_STABILITY": ("DEAD_BUG", "QUADRUPED_HIP_EXTENSION", "SIDE_LYING_LEG_RAISE"),
    "LEG_CURL": ("BAND_GOOD_MORNING", "SINGLE_LEG_SLIDING_LEG_CURL", "SLIDING_LEG_CURL"),
    "LUNGE": ("DUMBBELL_BULGARIAN_SPLIT_SQUAT", "DUMBBELL_REVERSE_LUNGE", "LUNGE", "SIDE_LUNGE"),
    "PLANK": ("PLANK", "SIDE_PLANK", "SIDE_PLANK_WITH_LEG_LIFT"),
    "PLYO": ("ALTERNATING_JUMP_LUNGE", "BODY_WEIGHT_JUMP_SQUAT", "BOX_JUMP", "LATERAL_LEAP_AND_HOP"),
    "SQUAT": ("AIR_SQUAT", "BODY_WEIGHT_WALL_SQUAT", "DUMBBELL_STEP_UP", "GOBLET_SQUAT", "STEP_UP"),
    "WARM_UP": ("ANKLE_DORSIFLEXION_WITH_BAND", "FORWARD_AND_BACKWARD_LEG_SWINGS", "STRETCH_90_90",
                "STRETCH_CALF", "STRETCH_HAMSTRING", "STRETCH_LUNGING_HIP_FLEXOR", "STRETCH_PIGEON_POSE",
                "STRETCH_QUAD", "THORACIC_ROTATION"),
}

ASSUMPTIONS = {
    "nature": (
        "Tous les nombres de la bibliothèque (séries, répétitions, tempos, repos, séances par semaine, "
        "durées, règles de placement, facteur d'affûtage) sont des « approximations du projet » : des "
        "points de départ prudents et génériques, pas des prescriptions issues d'un protocole publié. "
        "Le profil de l'athlète, le bilan matinal, les garde-fous et l'avis d'un professionnel de santé "
        "priment toujours ; la bibliothèque ne pose aucun diagnostic et ne traite aucune blessure."),
    "sources": (
        "Deux revues vérifiées (Crossref), citées pour la DIRECTION seulement — un entraînement de force "
        "peut améliorer l'économie de course et la performance des coureurs d'endurance — jamais pour un "
        "dosage : Blagrove et al. (2018), Sports Med 48(5):1117-1149, doi 10.1007/s40279-017-0835-7 ; "
        "Beattie et al. (2014), Sports Med 44(6):845-865, doi 10.1007/s40279-014-0157-y."),
    "taper_factor": (
        "Affûtage : le nombre de séries d'un programme d'usage est multiplié par "
        "`phase_volume_factor.taper` (0,67, arrondi, minimum 1) et la pliométrie est retirée — "
        "approximation du projet, aucune source ne fixe ce coefficient."),
    "placement": (
        "Écarts minimaux avant une séance de qualité, une sortie longue ou la course, par niveau de "
        "fatigue du programme (`placement` dans `programmes.json`) : approximations du projet, pas des "
        "valeurs publiées. Ils sont des plafonds de prudence : la sensation de fatigue de l'athlète prime."),
    "garmin_mapping": (
        "Chaque correspondance Garmin est le couple (category, exercise) EXACT du catalogue public de "
        "Garmin Connect, choisi pour son nom : c'est la variante la plus proche, pas toujours le même "
        "mouvement (ex. la descente excentrique sur marche réutilise la montée sur pointe unipodale). "
        "Sans équivalent vérifié : `garmin: null`, le nom français est dans la description de l'étape."),
    "equipment_fallback": (
        "Matériel manquant : l'exercice est remplacé par la première de ses régressions utilisable "
        "avec le matériel disponible (jamais une invention) ; sans repli, il est retiré et signalé."),
}

CAVEAT = ("Programmes génériques, approximations du projet : ni prescription médicale ni diagnostic. "
          "En cas de douleur, on s'arrête et on consulte un professionnel de santé.")


class StrengthError(ValueError):
    """Erreur d'usage (phase/usage/matériel inconnu) ou bibliothèque invalide."""


# ---------------------------------------------------------------------------
# Chargement et validation
# ---------------------------------------------------------------------------

def load_library(directory: Optional[Path] = None) -> Tuple[Dict[str, dict], dict]:
    """Retourne (exercices par id, document des programmes). Lève StrengthError si invalide."""
    d = Path(directory) if directory else STRENGTH_DIR
    try:
        ex_doc = json.loads((d / "exercises.json").read_text(encoding="utf-8"))
        doc = json.loads((d / "programmes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StrengthError(f"bibliothèque de renforcement illisible ({d}) : {exc}")
    exercises = {e.get("id"): e for e in ex_doc.get("exercises", []) if isinstance(e, dict)}
    errors = validate_library(ex_doc, doc)
    if errors:
        raise StrengthError("bibliothèque de renforcement invalide : " + " ; ".join(errors))
    return exercises, doc


def _is_int(v: Any, minimum: int = 0) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimum


def validate_library(ex_doc: dict, doc: dict) -> List[str]:
    """Liste d'erreurs (vide = conforme) : identifiants uniques, références résolues, couples Garmin
    dans `GARMIN_VERIFIED`, cohérence mode/séries, emphases du gabarit #189."""
    errors: List[str] = []
    exercises = ex_doc.get("exercises") if isinstance(ex_doc, dict) else None
    if not isinstance(exercises, list) or not exercises:
        return ["exercises.json : liste `exercises` absente ou vide."]
    ids: Dict[str, dict] = {}
    for i, e in enumerate(exercises):
        where = f"exercice #{i}"
        if not isinstance(e, dict):
            errors.append(f"{where} : objet attendu.")
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not re.fullmatch(r"[a-z0-9_]+", eid):
            errors.append(f"{where} : id invalide {eid!r}.")
            continue
        where = f"exercice {eid}"
        if eid in ids:
            errors.append(f"{where} : id en double.")
        ids[eid] = e
        if not isinstance(e.get("name"), str) or not e["name"].strip():
            errors.append(f"{where} : `name` manquant.")
        if e.get("group") not in GROUPS:
            errors.append(f"{where} : group {e.get('group')!r} hors de {GROUPS}.")
        if e.get("mode") not in MODES:
            errors.append(f"{where} : mode {e.get('mode')!r} hors de {MODES}.")
        if not isinstance(e.get("unilateral"), bool):
            errors.append(f"{where} : `unilateral` doit être un booléen.")
        tg = e.get("targets")
        if not isinstance(tg, list) or not tg or any(t not in TARGETS for t in tg):
            errors.append(f"{where} : `targets` vide ou hors vocabulaire {TARGETS}.")
        eq = e.get("equipment")
        if not isinstance(eq, list) or not eq or any(x not in EQUIPMENT for x in eq):
            errors.append(f"{where} : `equipment` vide ou hors de {EQUIPMENT}.")
        cues = e.get("cues")
        if not isinstance(cues, list) or not cues or any(not isinstance(c, str) or not c.strip() for c in cues):
            errors.append(f"{where} : `cues` (consignes) vide.")
        if not isinstance(e.get("caution"), str) or not e["caution"].strip():
            errors.append(f"{where} : `caution` manquante (note de précaution générique).")
        g = e.get("garmin")
        if g is not None:
            if (not isinstance(g, dict) or set(g) != {"category", "exercise"}
                    or g.get("exercise") not in GARMIN_VERIFIED.get(g.get("category"), ())):
                errors.append(f"{where} : correspondance Garmin {g!r} absente de GARMIN_VERIFIED "
                              f"(vérifier dans le catalogue Garmin, jamais deviner).")
    for eid, e in ids.items():
        for key in ("progressions", "regressions"):
            refs = e.get(key)
            if not isinstance(refs, list):
                errors.append(f"exercice {eid} : `{key}` doit être une liste.")
                continue
            for r in refs:
                if r not in ids:
                    errors.append(f"exercice {eid} : {key} → « {r} » inconnu.")
                elif r == eid:
                    errors.append(f"exercice {eid} : {key} se référence lui-même.")

    errors += _validate_programmes(doc, ids)
    return errors


def _validate_programmes(doc: dict, ids: Dict[str, dict]) -> List[str]:
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["programmes.json : objet attendu."]
    if doc.get("status") != "approximation_projet":
        errors.append("programmes.json : `status` doit valoir « approximation_projet ».")
    for s in doc.get("sources", []):
        if not (isinstance(s, dict) and re.fullmatch(r"10\.\d{4,9}/\S+", str(s.get("doi", "")))):
            errors.append(f"source invalide : {s!r}.")
    placement = doc.get("placement", {})
    for lvl in FATIGUE_LEVELS:
        r = placement.get(lvl) if isinstance(placement, dict) else None
        if not (isinstance(r, dict) and all(_is_int(r.get(k)) for k in
                                            ("min_h_before_quality", "min_h_before_long_run", "min_days_before_race"))):
            errors.append(f"placement.{lvl} : trois entiers >= 0 attendus.")
    factor = doc.get("phase_volume_factor", {})
    if not (isinstance(factor, dict) and all(isinstance(factor.get(p), (int, float)) and 0 < factor[p] <= 1
                                             for p in ("base", "development", "specific", "taper"))):
        errors.append("phase_volume_factor : base/development/specific/taper dans ]0, 1] attendus.")
    progs = doc.get("programmes")
    if not isinstance(progs, list) or not progs:
        return errors + ["programmes.json : liste `programmes` absente ou vide."]
    seen_ids, emphases, uses = set(), set(), set()
    for i, p in enumerate(progs):
        pid = p.get("id") if isinstance(p, dict) else None
        where = f"programme {pid or '#' + str(i)}"
        if not isinstance(pid, str) or pid in seen_ids:
            errors.append(f"{where} : id manquant ou en double.")
            continue
        seen_ids.add(pid)
        if p.get("kind") == "phase":
            if p.get("emphasis") not in STRENGTH_EMPHASES:
                errors.append(f"{where} : emphase {p.get('emphasis')!r} hors de {STRENGTH_EMPHASES}.")
            elif p["emphasis"] in emphases:
                errors.append(f"{where} : emphase {p['emphasis']} déjà couverte.")
            else:
                emphases.add(p["emphasis"])
            if p.get("phase") not in PHASES or PHASE_TO_EMPHASIS.get(p.get("phase")) != p.get("emphasis"):
                errors.append(f"{where} : `phase` incohérente avec l'emphase.")
        elif p.get("kind") == "usage":
            if p.get("use") not in USES:
                errors.append(f"{where} : usage {p.get('use')!r} hors de {USES}.")
            elif p["use"] in uses:
                errors.append(f"{where} : usage {p['use']} déjà couvert.")
            else:
                uses.add(p["use"])
            ph = p.get("phases")
            if not isinstance(ph, list) or not ph or any(x not in PHASES for x in ph):
                errors.append(f"{where} : `phases` hors de {PHASES}.")
        else:
            errors.append(f"{where} : kind {p.get('kind')!r} (phase|usage attendu).")
        if not isinstance(p.get("label"), str) or not isinstance(p.get("purpose"), str):
            errors.append(f"{where} : `label`/`purpose` manquants.")
        spw = p.get("sessions_per_week")
        spw = spw if isinstance(spw, dict) else {}
        if not (_is_int(spw.get("min"), 1) and _is_int(spw.get("max"), 1) and spw["min"] <= spw["max"]):
            errors.append(f"{where} : sessions_per_week {{min <= max, entiers >= 1}} attendu.")
        if not _is_int(p.get("duration_min"), 1):
            errors.append(f"{where} : duration_min entier >= 1 attendu.")
        if p.get("fatigue") not in FATIGUE_LEVELS:
            errors.append(f"{where} : fatigue {p.get('fatigue')!r} hors de {FATIGUE_LEVELS}.")
        for key in ("warmup", "cooldown"):
            for r in p.get(key, []):
                if r not in ids:
                    errors.append(f"{where} : {key} → « {r} » inconnu.")
        blocks = p.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            errors.append(f"{where} : `blocks` vide.")
            continue
        for j, b in enumerate(blocks):
            bw = f"{where} bloc {j}"
            ex = ids.get(b.get("exercise"))
            if ex is None:
                errors.append(f"{bw} : exercice « {b.get('exercise')} » inconnu.")
                continue
            if not _is_int(b.get("sets"), 1):
                errors.append(f"{bw} : sets entier >= 1 attendu.")
            if not _is_int(b.get("rest_s")):
                errors.append(f"{bw} : rest_s entier >= 0 attendu.")
            if ex.get("mode") == "time":
                if not _is_int(b.get("seconds"), 1) or "reps" in b:
                    errors.append(f"{bw} : exercice chronométré → `seconds` seul attendu.")
            elif not _is_int(b.get("reps"), 1) or "seconds" in b:
                errors.append(f"{bw} : exercice en répétitions → `reps` seul attendu.")
            if "tempo" in b and not re.fullmatch(r"\d-\d-\d", str(b["tempo"])):
                errors.append(f"{bw} : tempo « {b['tempo']} » (format D-P-M, ex. 3-0-1).")
            if not isinstance(b.get("each_side"), bool) or (b["each_side"] and not ex.get("unilateral")):
                errors.append(f"{bw} : each_side invalide (booléen, vrai seulement pour un exercice unilatéral).")
    if emphases != set(STRENGTH_EMPHASES):
        errors.append(f"programmes de phase : emphases manquantes {sorted(set(STRENGTH_EMPHASES) - emphases)}.")
    if uses != set(USES):
        errors.append(f"programmes d'usage : usages manquants {sorted(set(USES) - uses)}.")
    return errors


# ---------------------------------------------------------------------------
# Entrées utilisateur : phase, usage, matériel
# ---------------------------------------------------------------------------

def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.strip().lower()) if unicodedata.category(c) != "Mn")


def normalize_phase(value: str) -> str:
    """Accepte l'identifiant de phase (#189), son libellé français, ou l'identifiant d'emphase."""
    v = _fold(value)
    table = {"developpement": "development", "specifique": "specific", "affutage": "taper",
             "recuperation": "recovery", "transition": "recovery"}
    v = table.get(v, v)
    if v in PHASES:
        return v
    for ph, emph in PHASE_TO_EMPHASIS.items():
        if v == emph:
            return ph
    raise StrengthError(f"phase « {value} » inconnue (attendu : {', '.join(PHASES)}, ou une emphase "
                        f"{', '.join(STRENGTH_EMPHASES)}).")


def normalize_use(value: str) -> str:
    v = _fold(value)
    table = {"hanche": "hanches", "pieds": "pied", "chevilles": "cheville", "descentes": "descente"}
    v = table.get(v, v)
    if v not in USES:
        raise StrengthError(f"usage « {value} » inconnu (attendu : {', '.join(USES)}).")
    return v


def parse_equipment(value: str) -> List[str]:
    """`--equipment elastic,dumbbell` → liste triée (« none » toujours implicite)."""
    items = [x for x in re.split(r"[,\s;]+", value.strip().lower()) if x]
    bad = [x for x in items if x not in EQUIPMENT]
    if bad:
        raise StrengthError(f"matériel inconnu : {', '.join(bad)} (attendu : {', '.join(EQUIPMENT)}).")
    return sorted(set(items) | {"none"})


_PROFILE_EQUIPMENT_RE = re.compile(r"^\s*-\s*\*\*Équipement\*\*\s*:\s*(.*)$", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_KEYWORDS = (
    ("dumbbell", ("haltere", "dumbbell", "kettlebell", "salle")),
    ("elastic", ("elastique", "bande", "band", "miniband")),
    ("step", ("marche", "step", "escalier", "salle")),
    ("box", ("box", "caisse", "banc", "chaise", "salle")),
)
# Mots entiers seulement (« boxe » n'est pas une box, « bandeau » pas un élastique), au singulier
# ou au pluriel (s/x/es).
_WORD_RE = re.compile(r"[a-z0-9]+")
# Activités, pas du matériel : « marche à pied », « marche nordique »…
_NOT_EQUIPMENT_RE = re.compile(r"\bmarche\s+(?:a\s+pied|nordique|rapide|active)\b")
# Négation simple : « pas d'haltères », « sans élastique », « ni marche » → le mot suivant est retiré.
_NEGATION_RE = re.compile(r"\b(?:pas\s+(?:de\s+|d\s*'\s*|d\s+)|sans\s+|ni\s+|aucune?\s+|no\s+)"
                          r"(?:une?\s+|des?\s+)?[a-z0-9]+")
# Déclaration explicite « rien que le poids du corps » → matériel connu : `none`.
_BODYWEIGHT_ONLY_RE = re.compile(r"\b(?:aucune?|rien|neant|poids\s+du\s+corps|sans\s+materiel|"
                                 r"pas\s+de\s+materiel|none)\b")


def _has_keyword(words: set, kw: str) -> bool:
    return any(w in words for w in (kw, kw + "s", kw + "x", kw + "es"))


def equipment_from_profile(text: str) -> Dict[str, Any]:
    """Lit la puce « Équipement » du profil (`templates/Runner_Profile.template.md`). Texte libre :
    mots-clés reconnus (mots entiers, accents et pluriels tolérés, négations simples « pas de » /
    « sans » écartées) → matériel ; « aucun », « rien », « poids du corps » seuls → poids du corps
    (`none`) ; vide, gabarit non rempli ou rien de reconnu → `known: false` (on ne devine pas : le
    coach demande à l'athlète)."""
    m = _PROFILE_EQUIPMENT_RE.search(text or "")
    declared = _HTML_COMMENT_RE.sub("", m.group(1)).strip() if m else ""
    if not declared:
        return {"known": False, "available": None, "declared": ""}
    folded = _NOT_EQUIPMENT_RE.sub(" ", _fold(declared).replace("’", "'"))
    words = set(_WORD_RE.findall(_NEGATION_RE.sub(" ", folded)))
    found = {eq for eq, kws in _KEYWORDS if any(_has_keyword(words, k) for k in kws)}
    if not found and _BODYWEIGHT_ONLY_RE.search(folded):
        return {"known": True, "available": ["none"], "declared": declared}
    if not found:
        return {"known": False, "available": None, "declared": declared}
    return {"known": True, "available": sorted(found | {"none"}), "declared": declared}


# ---------------------------------------------------------------------------
# Sélection
# ---------------------------------------------------------------------------

def _usable(ex: dict, available: Optional[List[str]]) -> bool:
    return available is None or all(q in available or q == "none" for q in ex["equipment"])


def _fallback(ex: dict, exercises: Dict[str, dict], available: List[str]) -> Optional[dict]:
    """Première régression (transitive, en largeur) utilisable avec le matériel disponible."""
    queue, seen = list(ex.get("regressions", [])), {ex["id"]}
    while queue:
        rid = queue.pop(0)
        if rid in seen:
            continue
        seen.add(rid)
        cand = exercises[rid]
        if _usable(cand, available):
            return cand
        queue += cand.get("regressions", [])
    return None


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def _exercise_view(ex: dict) -> dict:
    return {"exercise_id": ex["id"], "name": ex["name"], "group": ex["group"], "targets": ex["targets"],
            "equipment": ex["equipment"], "cues": ex["cues"], "caution": ex["caution"], "garmin": ex["garmin"]}


def placement_rules(doc: dict, fatigue: str) -> dict:
    r = doc["placement"][fatigue]
    return {"fatigue": fatigue, **r, "advice": _placement_advice(fatigue, r)}


def _placement_advice(fatigue: str, r: dict) -> List[str]:
    lines = []
    if r["min_h_before_quality"]:
        lines.append(f"Au moins {r['min_h_before_quality']} h avant une séance de qualité (VMA, seuil, côtes) : "
                     "jamais la veille ; le mieux est après elle le même jour ou un jour facile.")
    else:
        lines.append("Compatible avec n'importe quel jour, y compris la veille d'une séance de qualité.")
    if r["min_h_before_long_run"]:
        lines.append(f"Au moins {r['min_h_before_long_run']} h avant une sortie longue.")
    lines.append(f"Dernière séance au moins {r['min_days_before_race']} jour(s) avant la course "
                 "(approximations du projet).")
    return lines


def check_placement(rules: dict, hours_to_quality: Optional[float] = None,
                    hours_to_long_run: Optional[float] = None, days_to_race: Optional[float] = None) -> dict:
    """Contrôle déterministe d'un placement candidat (écarts jusqu'à la prochaine échéance ; `None` =
    pas d'échéance connue). `rules` vient de `placement_rules`."""
    violations = []
    if hours_to_quality is not None and hours_to_quality < rules["min_h_before_quality"]:
        violations.append(f"séance de qualité dans {hours_to_quality:g} h (< {rules['min_h_before_quality']} h)")
    if hours_to_long_run is not None and hours_to_long_run < rules["min_h_before_long_run"]:
        violations.append(f"sortie longue dans {hours_to_long_run:g} h (< {rules['min_h_before_long_run']} h)")
    if days_to_race is not None and days_to_race < rules["min_days_before_race"]:
        violations.append(f"course dans {days_to_race:g} j (< {rules['min_days_before_race']} j)")
    return {"ok": not violations, "violations": violations}


def _coerce_block(block: dict, ex: dict) -> dict:
    out = {k: v for k, v in block.items() if k != "exercise"}
    if ex["mode"] == "time" and "seconds" not in out:
        out.pop("reps", None)
        out.pop("tempo", None)
        out["seconds"] = DEFAULT_SECONDS_WHEN_COERCED
    elif ex["mode"] == "reps" and "reps" not in out:
        out.pop("seconds", None)
        out["reps"] = DEFAULT_REPS_WHEN_COERCED
    if not ex["unilateral"]:
        out["each_side"] = False
    return out


def select_programme(exercises: Dict[str, dict], doc: dict, phase: Optional[str] = None, use: Optional[str] = None,
                     available: Optional[List[str]] = None, equipment_source: str = "unknown") -> dict:
    """Choisit et résout un programme. `available` = None → matériel inconnu (aucun filtre, question posée)."""
    if not phase and not use:
        raise StrengthError("indiquer --phase et/ou --use.")
    phase_id = normalize_phase(phase) if phase else None
    use_id = normalize_use(use) if use else None
    warnings: List[str] = []
    questions: List[str] = []
    progs = doc["programmes"]
    factor = 1.0
    if use_id and phase_id == "recovery":
        warnings.append(f"Phase récupération : l'usage « {use_id} » n'est pas appliqué, programme de mobilité "
                        "proposé à la place.")
        prog = next(p for p in progs if p["kind"] == "phase" and p["phase"] == "recovery")
    elif use_id:
        prog = next(p for p in progs if p["kind"] == "usage" and p["use"] == use_id)
        if phase_id and phase_id not in prog["phases"]:
            names = ", ".join(PHASE_LABELS_FR[x] for x in prog["phases"])
            warnings.append(f"Programme « {use_id} » hors de sa fenêtre recommandée ({names}) en phase "
                            f"{PHASE_LABELS_FR[phase_id]} : à valider avec l'athlète.")
        if phase_id == "taper":
            factor = doc["phase_volume_factor"]["taper"]
            warnings.append(f"Affûtage : séries × {factor:g} (minimum 1), pliométrie retirée.")
    else:
        prog = next(p for p in progs if p["kind"] == "phase" and p["phase"] == phase_id)

    if available is None:
        questions.append("Matériel disponible inconnu (profil sans « Équipement » exploitable) : demander à "
                         "l'athlète (haltères, élastique, marche, box) ou relancer avec --equipment ; "
                         "aucun repli n'a été appliqué.")

    substitutions: List[dict] = []
    dropped: List[dict] = []
    used: set = set()
    blocks: List[dict] = []
    for b in prog["blocks"]:
        ex = exercises[b["exercise"]]
        if factor < 1.0 and ex["group"] == "pliometrie":
            dropped.append({"exercise": ex["id"], "reason": "pliométrie retirée à l'affûtage"})
            continue
        if not _usable(ex, available):
            fb = _fallback(ex, exercises, available)
            if fb is None:
                dropped.append({"exercise": ex["id"], "reason": "matériel manquant, aucune régression utilisable"})
                continue
            substitutions.append({"from": ex["id"], "to": fb["id"],
                                  "reason": "matériel manquant : " + ", ".join(
                                      q for q in ex["equipment"] if q not in (available or []) and q != "none")})
            ex = fb
        if ex["id"] in used:
            dropped.append({"exercise": ex["id"], "reason": "doublon après repli matériel"})
            continue
        used.add(ex["id"])
        nb = _coerce_block(b, ex)
        if factor < 1.0:
            nb["sets"] = max(1, _round_half_up(nb["sets"] * factor))
        blocks.append({**_exercise_view(ex), **nb})

    def brief(ids: List[str]) -> List[dict]:
        out = []
        for i in ids:
            e = exercises[i]
            if _usable(e, available):
                out.append({"exercise_id": i, "name": e["name"], "mode": e["mode"], "cues": e["cues"],
                            "garmin": e["garmin"]})
        return out

    return {
        "phase": phase_id, "emphasis": PHASE_TO_EMPHASIS.get(phase_id) if phase_id else None, "use": use_id,
        "programme": {
            "id": prog["id"], "kind": prog["kind"], "label": prog["label"], "purpose": prog["purpose"],
            "sessions_per_week": prog["sessions_per_week"], "duration_min": prog["duration_min"],
            "fatigue": prog["fatigue"], "warmup": brief(prog.get("warmup", [])), "blocks": blocks,
            "cooldown": brief(prog.get("cooldown", [])), "notes": prog.get("notes", []),
        },
        "equipment": {"known": available is not None, "available": available, "source": equipment_source},
        "substitutions": substitutions, "dropped": dropped,
        "placement": placement_rules(doc, prog["fatigue"]),
        "warnings": warnings, "questions": questions,
        "status": "approximation_projet", "sources": doc.get("sources", []), "caveat": CAVEAT,
    }


# ---------------------------------------------------------------------------
# Sorties : charge utile Garmin, texte
# ---------------------------------------------------------------------------

def _block_amount(b: dict) -> str:
    return f"{b['seconds']} s" if "seconds" in b else f"{b['reps']}"


def _label(b: dict) -> str:
    side = " (chaque côté)" if b.get("each_side") else ""
    return f"{b['name']}{side}"


def _no_target() -> dict:
    return {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}


def garmin_payload(selection: dict) -> dict:
    """Charges utiles Garmin d'un programme résolu.

    - `workout_data` : DTO structuré du skill `garmin-workout-scheduling` (« Strength circuit WITH FULL
      DETAIL », TESTÉ) — RepeatGroupDTO par exercice, étapes reps (endCondition 10) ou temps (2 ; une
      étape par côté pour un exercice chronométré « chaque côté »), repos stepTypeId 5 ; `category`/`exerciseName` seulement pour un couple vérifié. À pousser via
      `schedule_workouts` (une entrée `{calendar_date, workout_data}`).
    - `create_strength_workout` : arguments de l'outil simplifié (`name`, `exercises`) ; il ne peut pas
      porter la clé d'exercice Garmin (son `name` sert aussi d'`exerciseName`) : `category` seulement,
      nom français en description. Un exercice chronométré y devient 1 répétition + durée dans le nom."""
    prog = selection["programme"]
    steps: List[dict] = []
    simple: List[dict] = []
    unmapped: List[str] = []
    order = 1
    for b in prog["blocks"]:
        g = b["garmin"]
        if g is None:
            unmapped.append(b["exercise_id"])
        timed = "seconds" in b
        desc = f"{_label(b)} — {b['sets']} x {_block_amount(b)}" + (f" — tempo {b['tempo']}" if b.get("tempo") else "")
        work = {
            "type": "ExecutableStepDTO", "stepOrder": 1,
            "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
            "description": desc,
            "endCondition": ({"conditionTypeId": 2, "conditionTypeKey": "time"} if timed
                             else {"conditionTypeId": 10, "conditionTypeKey": "reps"}),
            "endConditionValue": b["seconds"] if timed else b["reps"],
            "targetType": _no_target(),
        }
        if g:
            work["category"] = g["category"]
            work["exerciseName"] = g["exercise"]
        # Exercice chronométré « chaque côté » : une étape temps par côté (sinon la montre arrête le
        # chrono après le premier côté) ; en répétitions, la valeur reste par côté (description).
        works = [work]
        if timed and b.get("each_side"):
            works = [{**work, "stepOrder": i + 1, "description": f"{desc} — côté {i + 1}/2"} for i in range(2)]
        rest = {
            "type": "ExecutableStepDTO", "stepOrder": 2,
            "stepType": {"stepTypeId": 5, "stepTypeKey": "rest"},
            "description": f"Repos {b['rest_s']} s",
            "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
            "endConditionValue": b["rest_s"], "targetType": _no_target(),
        }
        inner = works + ([{**rest, "stepOrder": len(works) + 1}] if b["rest_s"] > 0 else [])
        if b["sets"] > 1:
            steps.append({"type": "RepeatGroupDTO", "stepOrder": order, "numberOfIterations": b["sets"],
                          "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                          "workoutSteps": inner})
            order += 1
        else:
            for s in inner:
                steps.append({**s, "stepOrder": order})
                order += 1
        entry = {"name": _label(b) + (f" — {b['seconds']} s" if timed else ""), "sets": b["sets"],
                 "reps": 1 if timed else b["reps"], "rest_seconds": b["rest_s"]}
        if g:
            entry["category"] = g["category"]
        simple.append(entry)
    sport = {"sportTypeId": 5, "sportTypeKey": "strength_training"}
    warnings = []
    if unmapped:
        warnings.append(f"{len(unmapped)} exercice(s) sans correspondance Garmin vérifiée ({', '.join(unmapped)}) : "
                        "envoyés sans category/exerciseName, nom français dans la description de l'étape.")
    return {
        "workout_data": {
            "workoutName": prog["label"],
            "description": f"{prog['label']} — approximation du projet, voir docs/strength.md",
            "sportType": sport,
            "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": steps}],
        },
        "create_strength_workout": {"name": prog["label"], "exercises": simple},
        "unmapped": unmapped, "warnings": warnings + selection["warnings"],
        "note": "Aucune écriture : le coach demande une confirmation explicite avant tout push (jamais en headless).",
    }


def render_text(selection: dict) -> str:
    """Version texte (chat, `description` d'un événement intervals.icu) : une ligne par exercice."""
    prog = selection["programme"]
    lines = [f"{prog['label']} — {prog['duration_min']} min environ, "
             f"{prog['sessions_per_week']['min']}-{prog['sessions_per_week']['max']} séance(s) par semaine "
             "(approximation du projet)", prog["purpose"], ""]
    eq = selection["equipment"]
    lines.append("Matériel : " + (", ".join("poids du corps" if q == "none" else q for q in eq["available"])
                                  if eq["known"] else "inconnu (à confirmer)"))
    if prog["warmup"]:
        lines.append("Échauffement : " + " ; ".join(x["name"] for x in prog["warmup"]))
    lines.append("")
    for b in prog["blocks"]:
        extra = [f"repos {b['rest_s']} s"]
        if b.get("tempo"):
            extra.append(f"tempo {b['tempo']}")
        if b.get("load"):
            extra.append(b["load"])
        lines.append(f"- {_label(b)} : {b['sets']} x {_block_amount(b)} — " + " · ".join(extra))
        lines.append("    " + " ".join(b["cues"]))
    if prog["cooldown"]:
        lines += ["", "Retour au calme : " + " ; ".join(x["name"] for x in prog["cooldown"])]
    for s in selection["substitutions"]:
        lines.append(f"Repli matériel : {s['from']} → {s['to']} ({s['reason']})")
    for d in selection["dropped"]:
        lines.append(f"Retiré : {d['exercise']} ({d['reason']})")
    lines += ["", "Placement : " + " ".join(selection["placement"]["advice"])]
    lines += [f"Attention : {w}" for w in selection["warnings"]]
    lines += [f"Question : {q}" for q in selection["questions"]]
    lines += ["", selection["caveat"]]
    return "\n".join(lines)


def catalogue(exercises: Dict[str, dict], doc: dict) -> dict:
    """Vue d'ensemble (appel sans --phase ni --use)."""
    return {
        "phases": [{"id": p, "label": PHASE_LABELS_FR[p], "emphasis": PHASE_TO_EMPHASIS[p]} for p in PHASES],
        "uses": list(USES), "equipment": list(EQUIPMENT),
        "programmes": [{"id": p["id"], "kind": p["kind"], "label": p["label"], "fatigue": p["fatigue"],
                        "phase": p.get("phase"), "use": p.get("use")} for p in doc["programmes"]],
        "exercises": len(exercises), "garmin_mapped": sum(1 for e in exercises.values() if e["garmin"]),
        "status": "approximation_projet", "caveat": CAVEAT,
    }


def run(phase: Optional[str], use: Optional[str], equipment: Optional[str], workspace: Optional[Path],
        fmt: str = "json", profile: str = "planning/Runner_Profile.md") -> str:
    """Point d'entrée de `arc_index.py strength`. `fmt` : json | text | garmin. `profile` : chemin du
    profil relatif au workspace (`[athlete].profile`, résolu par `arc_index.settings`)."""
    exercises, doc = load_library()
    if not phase and not use:
        return json.dumps(catalogue(exercises, doc), ensure_ascii=False)
    if equipment is not None:
        available, src = parse_equipment(equipment), "cli"
    else:
        prof = Path(workspace) / (profile or "planning/Runner_Profile.md") if workspace else None
        text = prof.read_text(encoding="utf-8") if prof is not None and prof.is_file() else ""
        info = equipment_from_profile(text)
        available, src = info["available"], ("profile" if info["known"] else "unknown")
    sel = select_programme(exercises, doc, phase, use, available, src)
    if fmt == "text":
        return render_text(sel)
    if fmt == "garmin":
        return json.dumps(garmin_payload(sel), ensure_ascii=False)
    return json.dumps(sel, ensure_ascii=False)
