#!/usr/bin/env python3
"""Prévention ciblée : relie une douleur DÉCLARÉE à une routine douce de la bibliothèque de
renforcement (#192, épopée #173). Bibliothèque standard uniquement, fonctions pures.

## Ce que c'est — et ce que ce n'est pas

Une douleur saisie via `/log`, Telegram (#174) ou le bilan `medical` vit dans
`medical/AAAA-MM-JJ_health.md` (`pain: [{location, score}]`). Ce module lit les déclarations des
14 derniers jours, ramène chaque `location` (texte libre) à une ZONE du vocabulaire normalisé
(`config/strength/prevention.json`) et applique des règles de sécurité DÉTERMINISTES avant de
proposer quoi que ce soit :

1. score >= `[injury_risk].pain_consult_threshold` (7/10 par défaut) -> AUCUN exercice, consultation
   recommandée (même formulation que `/log` et Telegram) ;
2. douleur aiguë (mots « vive », « soudaine », « gonflement »… dans la zone déclarée, ou zone passée
   à `acute_zones` par l'agent d'après les mots de l'athlète) -> AUCUN exercice, consultation ;
3. drapeau de risque de blessure (#57) `consult` ou niveau `high` -> AUCUN exercice : jamais assoupli ;
4. score > 3/10, douleur qui s'aggrave, ou qui dure plus de 7 jours -> AUCUN exercice, avis
   professionnel conseillé ;
5. gêne légère (<= 3/10) mais pas encore CONFIRMÉE (une seule déclaration, ou déclarations à moins de
   2 jours d'écart) -> `observe` : AUCUN exercice, l'agent pose les 3 questions (nouvelle ? vive ?
   gonflement ?) ; la routine n'arrive qu'à une deuxième déclaration au moins 2 jours plus tard sans
   hausse, ou si l'athlète confirme lui-même une gêne connue, non aiguë et stable (`--known`) ;
6. seulement une gêne légère (<= 3/10), connue et stable -> routine DOUCE de prévention (2 séries,
   effort facile, sans impact), jamais un traitement.

Une zone revenue à 0/10 est « résolue », sauf si la fenêtre contient un score >= seuil de consultation
ou une douleur aiguë : la recommandation de consulter reste alors affichée.

Rien de tout cela n'est un diagnostic : le module ne nomme que des zones, jamais une pathologie
(un test de lint le vérifie sur toutes les sorties). Les seuils (3/10, 7 jours, aggravation d'un
point) sont des « approximations du projet », sans protocole publié derrière. Quand l'agent
`medical` est activé, c'est lui qui décide (le coach relaie) ; sinon le coach applique ces règles et
dit « ce n'est pas un avis médical ». Rien n'est poussé automatiquement : le coach PROPOSE la routine
à la prochaine interaction.

    python3 scripts/arc_index.py prevention [--days N] [--acute ZONE,…] [--known ZONE,…] [--equipment …] [--text]
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import arc_strength as SG

PREVENTION_FILE = SG.STRENGTH_DIR / "prevention.json"
STATUSES = ("prevention_ok", "observe", "consult", "no_data")
CONSULT_LEVELS = ("urgent", "advised")
DEFAULT_WINDOW_DAYS = 14

DISCLAIMER_COACH = ("Ce n'est pas un avis médical : règles génériques du projet (approximations), sans "
                    "diagnostic. En cas de doute ou si la douleur persiste, consulte un professionnel de santé.")
DISCLAIMER_MEDICAL = ("Décision de l'agent medical : le coach relaie sans l'assouplir. Règles génériques du "
                      "projet (approximations), sans diagnostic.")

# Contrat de SORTIE (vérifié par les tests des paliers B et D sur les sorties, les données livrées, les
# prompts et la documentation) : aucun nom de pathologie, aucun vocabulaire de soin. Les mots que
# l'ATHLÈTE emploie (`synonyms`, `acute_keywords`) sont des entrées, hors contrat. « traitement » n'est
# permis que nié (« jamais un/de traitement », « aucun traitement », « sans traitement »).
DIAGNOSIS_TERMS = re.compile(
    r"tendinite|tendinopathie|tendinose|fracture|entorse|l[ée]sion|p[ée]riostite|syndrome|d[ée]chirure|"
    r"claquage|rupture|fasciite|apon[ée]vrosite|inflammation|bursite|sciatique|sciatalgie|hernie|"
    r"ligamentaire|m[ée]nisque|contracture|[ée]longation|arthrose|luxation|fissure|chondropathie|pubalgie|"
    r"lumbago|[ée]pine calcan[ée]enne|osgood", re.IGNORECASE)
CARE_TERMS = re.compile(
    r"\bsoign|\bgu[ée]ri|(?<!kin[ée]si)th[ée]rap|r[ée][ée]ducation|soulag|\btraiter\b|"
    r"(?<!jamais un )(?<!jamais de )(?<!aucun )(?<!ni un )(?<!pas un )(?<!sans )\btraitement", re.IGNORECASE)

ASSUMPTIONS = {
    "nature": (
        "Zones, seuils et dosages sont des « approximations du projet » : des garde-fous prudents, pas un "
        "protocole publié. Le module ne pose aucun diagnostic, ne nomme aucune pathologie et ne propose "
        "aucun traitement : il décide seulement s'il est raisonnable de proposer une routine DOUCE de "
        "la bibliothèque ou s'il faut s'arrêter et consulter."),
    "thresholds": (
        "Routine douce seulement si le score maximal de la zone sur la fenêtre est <= 3/10 "
        "(`gentle_max_score`), non aggravé (dernier score - premier score < 1 point) et déclaré depuis "
        "7 jours ou moins (`persistence_days`) ; sinon avis professionnel conseillé. Score >= "
        "`[injury_risk].pain_consult_threshold` : consultation recommandée, aucun exercice. Aucune de ces "
        "valeurs ne vient d'une source : elles sont volontairement prudentes."),
    "acute": (
        "Le contrat des données ne porte qu'une zone et un score. Le caractère aigu (nouvelle, vive, "
        "avec gonflement) n'est détecté que par des mots-clés dans la zone déclarée ou signalé par "
        "l'agent d'après les mots de l'athlète (`--acute`) : ABSENCE de signal ne vaut pas preuve "
        "d'absence de gravité, le coach demande si la douleur est nouvelle ou vive."),
    "confirmation": (
        "Une seule déclaration légère ne suffit pas à proposer des exercices de charge : la routine exige "
        "deux déclarations à au moins 2 jours d'écart (`confirm_min_span_days`) sans hausse, ou la "
        "confirmation explicite de l'athlète (gêne connue, non aiguë, stable : `--known`). Avant cela, "
        "statut `observe` : aucun exercice, trois questions. Choix volontairement prudent du projet."),
    "progression_shown": (
        "Le « niveau suivant » d'un exercice n'est jamais un exercice excentrique dédié ni de la "
        "pliométrie (`never_in_prevention`), même affiché « plus tard »."),
    "persistence": (
        "Durée = écart entre la première et la dernière déclaration de la zone dans la fenêtre "
        "(14 jours par défaut) : une douleur plus ancienne n'est pas visible au-delà de la fenêtre."),
    "injury_risk": (
        "Un drapeau de risque de blessure (#57) `consult: true` ou de niveau `high` bloque toute routine, "
        "pour toutes les zones : le module ne l'assouplit jamais."),
    "scope": (
        "Zones reconnues : tendon d'Achille, cheville, mollet, tibia, genou, hanche, fessier, "
        "ischio-jambiers, pied, bas du dos. Toute autre zone (ou zone illisible) n'a pas de routine : "
        "l'agent demande, il n'invente pas."),
}


class PreventionError(ValueError):
    """Données de prévention invalides ou illisibles."""


# ---------------------------------------------------------------------------
# Chargement et validation
# ---------------------------------------------------------------------------

def load_prevention(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else PREVENTION_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PreventionError(f"correspondance de prévention illisible ({p}) : {exc}")
    return doc


def validate_prevention(doc: dict, exercises: Dict[str, dict]) -> List[str]:
    errors: List[str] = []
    th = doc.get("thresholds") or {}
    for key in ("window_days", "gentle_max_score", "persistence_days", "worsening_min_delta",
                "confirm_min_span_days"):
        v = th.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            errors.append(f"thresholds.{key} : nombre > 0 attendu.")
    banned = set(doc.get("never_in_prevention") or [])
    for bid in sorted(banned):
        if bid not in exercises:
            errors.append(f"never_in_prevention : exercice {bid!r} absent de la bibliothèque.")
    if not doc.get("observe_questions"):
        errors.append("observe_questions : au moins une question attendue (nouvelle ? vive ? gonflement ?).")
    ids = set()
    for z in doc.get("zones", []):
        zid = z.get("id")
        if not zid or zid in ids:
            errors.append(f"zone {zid!r} : identifiant manquant ou en double.")
        ids.add(zid)
        if not z.get("synonyms"):
            errors.append(f"zone {zid} : aucun synonyme.")
        if z.get("use") is not None and z["use"] not in SG.USES:
            errors.append(f"zone {zid} : usage {z['use']!r} inconnu.")
        if not z.get("exercises"):
            errors.append(f"zone {zid} : aucune routine.")
        for b in z.get("exercises", []):
            ex = exercises.get(b.get("exercise"))
            if ex is None:
                errors.append(f"zone {zid} : exercice {b.get('exercise')!r} absent de la bibliothèque.")
                continue
            if not isinstance(b.get("sets"), int) or b["sets"] < 1 or b["sets"] > 3:
                errors.append(f"zone {zid}/{ex['id']} : séries 1 à 3 attendues (routine douce).")
            if ex["group"] == "pliometrie":
                errors.append(f"zone {zid}/{ex['id']} : pas de pliométrie dans une routine de prévention.")
            if ex["id"] in banned:
                errors.append(f"zone {zid}/{ex['id']} : exercice exclu de la prévention (never_in_prevention).")
            if ("reps" in b) == ("seconds" in b):
                errors.append(f"zone {zid}/{ex['id']} : exactement un de reps/seconds attendu.")
    for kw in doc.get("acute_keywords", []):
        if kw.rstrip("*") != _fold(kw.rstrip("*")):
            errors.append(f"mot-clé aigu {kw!r} : minuscules sans accent attendues.")
    return errors


def _library() -> Tuple[dict, Dict[str, dict], dict]:
    exercises, sdoc = SG.load_library()
    doc = load_prevention()
    errors = validate_prevention(doc, exercises)
    if errors:
        raise PreventionError("correspondance de prévention invalide : " + " ; ".join(errors))
    return doc, exercises, sdoc


# ---------------------------------------------------------------------------
# Normalisation d'une zone déclarée (/log, Telegram, saisie libre)
# ---------------------------------------------------------------------------

def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").strip().lower()) if unicodedata.category(c) != "Mn")


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", _fold(text).replace("’", " ").replace("'", " ").replace("-", " "))


_SIDES = (("gauche", "left"), ("droit", "right"), ("droite", "right"), ("bilateral", "both"),
          ("deux", "both"))


def normalize_zone(doc: dict, text: str) -> dict:
    """`« Tendon d'Achille gauche »` -> {zone: 'tendon_achille', side: 'left'}. Phrase la plus longue
    d'abord, puis ordre du fichier (le tendon d'Achille passe avant « talon » du pied). `zone: None` si
    rien n'est reconnu : jamais de devinette."""
    words = _words(text)
    joined = " " + " ".join(words) + " "
    best: Optional[Tuple[int, int, str]] = None
    for order, z in enumerate(doc["zones"]):
        for syn in z["synonyms"]:
            syn_words = _words(syn)
            if " " + " ".join(syn_words) + " " in joined:
                key = (-len(syn_words), order, z["id"])
                if best is None or key < best:
                    best = key
    side = next((s for w, s in _SIDES if w in words), None)
    return {"zone": best[2] if best else None, "side": side}


def is_acute(doc: dict, text: str) -> bool:
    """Mots-clés de douleur aiguë dans la zone déclarée : mot entier, ou préfixe quand le mot-clé finit par
    « * » (« gonfl* » -> gonflé, gonflement). Jamais une simple sous-chaîne (« vivement » n'est pas « vive »)."""
    ws = _words(text)
    for kw in doc.get("acute_keywords", []):
        if kw.endswith("*"):
            if any(w.startswith(kw[:-1]) for w in ws):
                return True
        elif kw in ws:
            return True
    return False


# ---------------------------------------------------------------------------
# Évaluation
# ---------------------------------------------------------------------------

def _fmt(x: float) -> str:
    return f"{x:g}"


def _routine(zone: dict, exercises: Dict[str, dict], sdoc: dict, doc: dict,
             available: Optional[List[str]]) -> dict:
    blocks: List[dict] = []
    substitutions: List[dict] = []
    dropped: List[dict] = []
    used: set = set()
    banned = set(doc.get("never_in_prevention") or [])

    def allowed(e: dict) -> bool:
        return e["group"] != "pliometrie" and e["id"] not in banned

    for b in zone["exercises"]:
        ex = exercises[b["exercise"]]
        if not SG._usable(ex, available):
            fb = SG._fallback(ex, exercises, available)
            if fb is not None and not allowed(fb):
                fb = None
            if fb is None:
                dropped.append({"exercise": ex["id"], "reason": "matériel manquant, aucune régression utilisable"})
                continue
            substitutions.append({"from": ex["id"], "to": fb["id"], "reason": "matériel manquant : " + ", ".join(
                q for q in ex["equipment"] if q not in (available or []) and q != "none")})
            ex = fb
        if ex["id"] in used:
            dropped.append({"exercise": ex["id"], "reason": "doublon après repli matériel"})
            continue
        used.add(ex["id"])
        blk = SG._coerce_block({k: v for k, v in b.items()}, ex)
        blk["rest_s"] = 30
        blocks.append({**SG._exercise_view(ex), **blk,
                       "next_level": [exercises[p]["name"] for p in ex.get("progressions", [])
                                      if p in exercises and allowed(exercises[p])]})
    return {
        "level": "doux", "use": zone.get("use"), "label": f"Prévention douce — {zone['label']}",
        "sessions_per_week": {"min": 2, "max": 3}, "duration_min": 15, "fatigue": "low",
        "blocks": blocks, "substitutions": substitutions, "dropped": dropped,
        "notes": list(zone.get("notes", [])),
        "progression_rule": doc["progression_rule"],
        "placement": SG.placement_rules(sdoc, "low"),
        "equipment": {"known": available is not None, "available": available},
        "questions": ([] if available is not None else [
            "Matériel disponible inconnu (profil sans « Équipement » exploitable) : demander à l'athlète "
            "(élastique) ou relancer avec --equipment ; aucun repli n'a été appliqué."]),
    }


def _per_day(entries: List[dict], zone_of) -> Dict[str, Dict[str, dict]]:
    """zone -> date -> {score max du jour, textes}. Plusieurs entrées le même jour : le pire score gagne."""
    out: Dict[str, Dict[str, dict]] = {}
    for e in entries:
        z = zone_of(e)
        day = out.setdefault(z, {}).setdefault(e["date"], {"score": 0.0, "texts": []})
        day["score"] = max(day["score"], float(e["score"]))
        day["texts"].append(e.get("location", ""))
    return out


def evaluate(entries: List[dict], today: date, consult_threshold: float, doc: Optional[dict] = None,
             exercises: Optional[Dict[str, dict]] = None, sdoc: Optional[dict] = None,
             available: Optional[List[str]] = None, medical_enabled: bool = False,
             acute_zones: Optional[List[str]] = None, injury_risk: Optional[dict] = None,
             window_days: Optional[int] = None, known_zones: Optional[List[str]] = None) -> dict:
    """Cœur PUR. `entries` : [{date: 'AAAA-MM-JJ', location: str, score: nombre 0-10}] (déclarations de
    douleur lues dans `medical/*_health.md`). Rend, par zone, un statut (`prevention_ok` | `consult`),
    des raisons et, seulement si prevention_ok, une routine douce ; `no_data` global sans déclaration.
    `known_zones` : zones que l'athlète a lui-même confirmées connues, non aiguës et stables (lève seulement
    l'attente d'une deuxième déclaration, jamais une autre règle). `injury_risk={"unavailable": True}` :
    drapeau non évalué -> aucune routine (`observe`), jamais supposé bas."""
    if doc is None or exercises is None or sdoc is None:
        doc, exercises, sdoc = _library()
    th = doc["thresholds"]
    window = int(window_days or th["window_days"])
    start = today - timedelta(days=window - 1)
    def _ids(names: Optional[List[str]]) -> set:
        # zone reconnue -> son id ; sinon la clé des zones non reconnues (« ?texte replié »)
        return {normalize_zone(doc, z)["zone"] or "?" + _fold(z) for z in (names or [])}

    acute_ids = _ids(acute_zones)
    known_ids = _ids(known_zones)
    zones_by_id = {z["id"]: z for z in doc["zones"]}

    kept: List[dict] = []
    for e in entries:
        try:
            d = date.fromisoformat(str(e["date"]))
            score = float(e["score"])
        except (KeyError, ValueError, TypeError):
            continue
        if start <= d <= today and 0 <= score <= 10:
            kept.append({"date": d.isoformat(), "location": str(e.get("location", "")), "score": score})
    # Un score 0 = « plus de douleur » ce jour-là : il compte pour savoir si la zone est résolue.
    resolved_ids: List[str] = []
    meta = {e["location"]: normalize_zone(doc, e["location"]) for e in kept}
    per = _per_day(kept, lambda e: meta[e["location"]]["zone"] or ("?" + _fold(e["location"])))

    risk_unknown = bool(injury_risk and injury_risk.get("unavailable"))
    risk_block = bool(injury_risk and not risk_unknown
                      and (injury_risk.get("consult") or injury_risk.get("level") == "high"))
    min_span = th["confirm_min_span_days"]
    gentle_max = th["gentle_max_score"]
    results: List[dict] = []
    unrecognized: List[dict] = []

    for zid, days in per.items():
        dates = sorted(days)
        latest = days[dates[-1]]
        scores = [days[d]["score"] for d in dates]
        positive = [d for d in dates if days[d]["score"] > 0]
        texts = [t for d in dates for t in days[d]["texts"]]
        if latest["score"] == 0:
            # 0/10 = résolue… sauf si la fenêtre garde un signal d'alerte : la consultation reste affichée.
            red_flag = bool(positive) and (max(scores) >= consult_threshold or zid in acute_ids
                                           or any(is_acute(doc, t) for t in texts))
            if not red_flag:
                if not zid.startswith("?"):
                    resolved_ids.append(zid)
                continue
        first_d, last_d = date.fromisoformat(positive[0]), date.fromisoformat(positive[-1])
        span = (last_d - first_d).days
        max_s, first_s, last_s = max(scores), days[positive[0]]["score"], days[positive[-1]]["score"]
        reasons: List[str] = []
        level: Optional[str] = None

        def need(lv: str, why: str) -> None:
            nonlocal level
            level = "urgent" if "urgent" in (level, lv) else "advised"
            reasons.append(why)

        if risk_block:
            need("urgent", "Le drapeau de risque de blessure demande une consultation : aucun exercice, "
                           "il n'est jamais assoupli ici.")
        if max_s >= consult_threshold:
            need("urgent", f"Score {_fmt(max_s)}/10 ≥ seuil de consultation ({_fmt(consult_threshold)}/10) : je te "
                           "recommande de consulter un professionnel de santé avant de reprendre la course. "
                           "Aucun exercice proposé.")
        if zid in acute_ids or any(is_acute(doc, t) for t in texts):
            need("urgent", "Douleur décrite comme aiguë (nouvelle, vive ou avec gonflement) : pas d'exercice "
                           "de charge, consulte un professionnel de santé.")
        if gentle_max < max_s < consult_threshold:
            need("advised", f"Score {_fmt(max_s)}/10 au-dessus du niveau de gêne légère (≤ {_fmt(gentle_max)}/10) : "
                            "pas d'exercice de charge, un avis professionnel est conseillé.")
        if last_s - first_s >= th["worsening_min_delta"] and len(positive) > 1:
            need("advised", f"Douleur qui s'aggrave ({_fmt(first_s)} → {_fmt(last_s)}/10 depuis le "
                            f"{first_d.isoformat()}) : pas d'exercice, un avis professionnel est conseillé.")
        if span > th["persistence_days"]:
            need("advised", f"Douleur déclarée depuis {span} jours (> {th['persistence_days']} jours) : "
                            "elle persiste, un avis professionnel est conseillé avant toute routine.")
        if latest["score"] == 0 and level is not None:
            reasons.append("Dernière déclaration à 0/10, mais la fenêtre contient un signal d'alerte : la "
                           "recommandation de consulter reste valable avant toute routine.")

        base = {"entries": [{"date": d, "score": days[d]["score"]} for d in dates],
                "latest_score": latest["score"], "max_score": max_s, "first_date": first_d.isoformat(),
                "last_date": last_d.isoformat(), "span_days": span}
        if zid.startswith("?"):
            label = texts[-1].strip() or "zone non précisée"
            if level is None:
                unrecognized.append({**base, "location": label, "status": "no_data", "consult_level": None,
                                     "reasons": ["Zone non reconnue : aucune routine n'est proposée, demander "
                                                 "à l'athlète de préciser (zones reconnues : "
                                                 + ", ".join(z["label"].split(" (")[0] for z in doc["zones"])
                                                 + ")."],
                                     "questions": list(doc["observe_questions"])})
            else:
                unrecognized.append({**base, "location": label, "status": "consult", "consult_level": level,
                                     "reasons": reasons})
            continue
        z = zones_by_id[zid]
        sides = sorted({s for t in texts for s in [normalize_zone(doc, t)["side"]] if s})
        confirmed = (len(positive) >= 2 and span >= min_span) or zid in known_ids
        if level is not None:
            results.append({**base, "zone": zid, "label": z["label"], "sides": sides, "status": "consult",
                            "consult_level": level, "reasons": reasons, "routine": None})
        elif risk_unknown or not confirmed:
            why = []
            if risk_unknown:
                why.append("Drapeau de risque de blessure non évalué (données illisibles) : aucune routine tant "
                           "qu'il ne l'est pas, jamais supposé bas.")
            if not confirmed:
                why.append(f"Gêne légère (≤ {_fmt(gentle_max)}/10) pas encore confirmée (une seule déclaration, ou "
                           f"déclarations à moins de {min_span} jours d'écart) : aucun exercice pour l'instant, on "
                           "observe. Poser les questions ci-dessous ; si l'athlète confirme une gêne connue, non "
                           "aiguë et stable, relancer avec --known ; une réponse « oui » à l'une d'elles : --acute.")
            results.append({**base, "zone": zid, "label": z["label"], "sides": sides, "status": "observe",
                            "consult_level": None, "reasons": why, "routine": None,
                            "questions": list(doc["observe_questions"])})
        else:
            why = [f"Gêne légère (≤ {_fmt(gentle_max)}/10), stable, déclarée depuis {span} jour(s) : "
                   "routine douce de prévention possible."]
            if len(positive) == 1:
                why.append("Une seule déclaration, confirmée par l'athlète comme connue et stable : à surveiller "
                           "— arrêter la routine et consulter si la douleur augmente, devient vive ou persiste.")
            results.append({**base, "zone": zid, "label": z["label"], "sides": sides, "status": "prevention_ok",
                            "consult_level": None, "reasons": why,
                            "routine": _routine(z, exercises, sdoc, doc, available)})

    order = {"urgent": 0, "advised": 1, None: 2}
    rank = {"consult": 0, "observe": 1, "prevention_ok": 2, "no_data": 3}
    results.sort(key=lambda r: (order[r["consult_level"]], rank[r["status"]], r["zone"]))
    unrecognized.sort(key=lambda r: (order[r["consult_level"]], r["location"]))
    everything = results + unrecognized
    if any(r["status"] == "consult" for r in everything):
        overall = "consult"
    elif any(r["status"] == "observe" for r in everything):
        overall = "observe"        # le plus prudent l'emporte : des questions avant toute routine
    elif any(r["status"] == "prevention_ok" for r in everything):
        overall = "prevention_ok"
    else:
        overall = "no_data"
    return {
        "today": today.isoformat(), "window_days": window, "status": overall,
        "decision_owner": "medical" if medical_enabled else "coach",
        "disclaimer": DISCLAIMER_MEDICAL if medical_enabled else DISCLAIMER_COACH,
        "consult_threshold": consult_threshold, "gentle_max_score": gentle_max,
        "persistence_days": th["persistence_days"], "zones": results, "unrecognized": unrecognized,
        "resolved": sorted(resolved_ids),
        "injury_risk": ({"level": injury_risk.get("level"), "consult": bool(injury_risk.get("consult")),
                         "blocks_routines": risk_block or risk_unknown, "unavailable": risk_unknown}
                        if injury_risk else None),
        "no_data_reason": ("Aucune douleur déclarée sur la fenêtre : rien à proposer (jamais d'exercice 'au cas où')."
                           if overall == "no_data" and not everything else None),
        "proposal": "Le coach PROPOSE la routine à la prochaine interaction ; aucun envoi automatique.",
        "status_label": "approximation_projet",
    }


# ---------------------------------------------------------------------------
# Lecture de l'index, texte, point d'entrée
# ---------------------------------------------------------------------------

def collect_entries(conn, today: date, days: int) -> List[dict]:
    """Déclarations `health.pain` des `days` derniers jours (index dérivé, `health_day.data_json`)."""
    start = today - timedelta(days=days - 1)
    rows = conn.execute("SELECT date, data_json FROM health_day WHERE date >= ? AND date <= ? ORDER BY date",
                        (start.isoformat(), today.isoformat())).fetchall()
    out: List[dict] = []
    for d, raw in rows:
        try:
            data = json.loads(raw or "{}") or {}
        except (ValueError, TypeError):
            continue
        for p in data.get("pain") or []:
            if isinstance(p, dict) and isinstance(p.get("location"), str) \
                    and isinstance(p.get("score"), (int, float)) and not isinstance(p.get("score"), bool):
                out.append({"date": d, "location": p["location"], "score": float(p["score"])})
    return out


def render_text(report: dict) -> str:
    lines = [f"Prévention ciblée — fenêtre {report['window_days']} j au {report['today']} "
             f"(décision : {report['decision_owner']})"]
    if report["injury_risk"]:
        ir = report["injury_risk"]
        if ir.get("unavailable"):
            lines.append("Drapeau de risque de blessure non évalué (données illisibles) — aucune routine.")
        else:
            lines.append(f"Drapeau de risque de blessure : niveau {ir['level']}, consult={ir['consult']}"
                         + (" — aucune routine." if ir["blocks_routines"] else "."))
    if report["no_data_reason"]:
        lines.append(report["no_data_reason"])
    for r in report["zones"] + report["unrecognized"]:
        name = r.get("label") or r["location"]
        lines += ["", f"{name} : {r['status']}" + (f" ({r['consult_level']})" if r["consult_level"] else "")
                  + f" — {_fmt(r['latest_score'])}/10, du {r['first_date']} au {r['last_date']}"]
        lines += [f"  - {x}" for x in r["reasons"]]
        lines += [f"  ? {q}" for q in r.get("questions") or []]
        rt = r.get("routine")
        if rt:
            lines.append(f"  Routine douce (~{rt['duration_min']} min, {rt['sessions_per_week']['min']}-"
                         f"{rt['sessions_per_week']['max']} fois par semaine, approximation du projet) :")
            for b in rt["blocks"]:
                amount = f"{b['seconds']} s" if "seconds" in b else f"{b['reps']}"
                side = " (chaque côté)" if b.get("each_side") else ""
                nxt = f" (niveau suivant, plus tard : {' / '.join(b['next_level'])})" if b.get("next_level") else ""
                lines.append(f"    - {b['name']}{side} : {b['sets']} x {amount}, effort facile{nxt}")
            for s in rt["substitutions"]:
                lines.append(f"    Repli matériel : {s['from']} → {s['to']} ({s['reason']})")
            lines += [f"    {n}" for n in rt["notes"]]
            lines += [f"    {q}" for q in rt["questions"]]
            lines.append("    " + rt["progression_rule"])
    lines += ["", report["disclaimer"], report["proposal"]]
    return "\n".join(lines)


def run(conn, today: date, days: Optional[int], acute: Optional[str], equipment: Optional[str],
        workspace: Optional[Path], profile: str, consult_threshold: float, medical_enabled: bool,
        injury_risk: Optional[dict], fmt: str = "json", known: Optional[str] = None) -> str:
    """Point d'entrée de `arc_index.py prevention` (lecture seule, aucune écriture)."""
    doc, exercises, sdoc = _library()
    window = days or doc["thresholds"]["window_days"]
    if equipment is not None:
        available = SG.parse_equipment(equipment)
    else:
        prof = Path(workspace) / (profile or "planning/Runner_Profile.md") if workspace else None
        text = prof.read_text(encoding="utf-8") if prof is not None and prof.is_file() else ""
        available = SG.equipment_from_profile(text)["available"]
    acute_zones = [x.strip() for x in (acute or "").split(",") if x.strip()]
    known_zones = [x.strip() for x in (known or "").split(",") if x.strip()]
    report = evaluate(collect_entries(conn, today, window), today, consult_threshold, doc, exercises, sdoc,
                      available, medical_enabled, acute_zones, injury_risk, window, known_zones)
    return render_text(report) if fmt == "text" else json.dumps(report, ensure_ascii=False)
