#!/usr/bin/env python3
"""Effet des décisions (#175, épopée #54) : que s'est-il passé APRÈS chaque décision du coach ?

Fonctions **pures** (aucun SQLite, aucun accès disque) : la lecture en base est faite par
`scripts/arc_index.py::decision_effects`, qui rassemble les séries (santé, ACWR, séances,
conformité) et les passe ici.

Pour chaque décision du journal (`planning/*_decision_*.md`), on compare une fenêtre AVANT et une
fenêtre APRÈS (J+N, N propre au déclencheur) sur les signaux pertinents pour ce déclencheur, puis on
classe l'`effect` : `improved` / `neutral` / `worsened` / `insufficient_data`, avec les chiffres et
les fenêtres utilisés. Fonctionne aussi pour `rejected_by_athlete` (que se passe-t-il quand le
conseil n'est pas suivi). Un signal absent est SAUTÉ (raison dite), jamais imputé.

**Corrélation, pas causalité** : l'effet mesuré est ce qui s'est passé après la décision, pas ce que
la décision a causé (repos, sommeil, météo, hasard, régression vers la moyenne jouent aussi). Ce bilan
n'assouplit jamais un garde-fou `block`, une décision médicale ni un verdict rouge — voir
`ASSUMPTIONS["not_causal"]`.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

import arc_metrics as M

EFFECTS = ("improved", "neutral", "worsened", "insufficient_data")

# Un effectif inférieur n'autorise AUCUNE « tendance » : on énonce les comptes, rien de plus.
MIN_SAMPLE_FOR_TREND = 5

# Fenêtre AVANT (jours, jour J inclus : la mesure qui a déclenché la décision) pour les séries
# quotidiennes ; fenêtre AVANT des séances (jours précédant J, J exclu) ; fenêtre AVANT de la
# conformité hebdomadaire.
PRE_DAYS = 3
PRE_SESSION_DAYS = 14
PRE_COMPLIANCE_DAYS = 7

# Zone ACWR de référence : `arc_metrics.ACWR_SAFE` (repère indicatif du projet, pas un seuil clinique).
ACWR_BAND = M.ACWR_SAFE

# Par déclencheur : horizon N (jours après J) et signaux évalués. `other` : séances seulement.
TRIGGER_PLAN: Dict[str, Dict[str, Any]] = {
    "morning_check": {"horizon_days": 3, "signals": ("hrv", "rhr", "readiness")},
    "medical": {"horizon_days": 7, "signals": ("pain", "rhr", "hrv")},
    "guardrail": {"horizon_days": 7, "signals": ("acwr_gap", "hrv", "pain")},
    "athlete_request": {"horizon_days": 7, "signals": ("rpe", "decoupling", "compliance")},
    "weather": {"horizon_days": 3, "signals": ("rpe", "decoupling", "compliance")},
    "race": {"horizon_days": 7, "signals": ("rpe", "decoupling", "compliance")},
    "other": {"horizon_days": 7, "signals": ("rpe", "decoupling", "compliance")},
}

# Signaux : libellé, sens (`higher_better`), mode de seuil (`rel` = fraction de la valeur AVANT,
# `abs` = unité du signal), tolérance sous laquelle la variation est « neutre », minimum de points
# de mesure dans chaque fenêtre.
SIGNALS: Dict[str, Dict[str, Any]] = {
    "hrv": {"label": "HRV nocturne (ms)", "higher_better": True, "mode": "rel", "tol": 0.05,
            "min_pre": 1, "min_post": 2},
    "rhr": {"label": "FC de repos (bpm)", "higher_better": False, "mode": "abs", "tol": 2.0,
            "min_pre": 1, "min_post": 2},
    "readiness": {"label": "Readiness", "higher_better": True, "mode": "abs", "tol": 5.0,
                  "min_pre": 1, "min_post": 2},
    "pain": {"label": "Douleur déclarée (moyenne /10)", "higher_better": False, "mode": "abs", "tol": 1.0,
             "min_pre": 1, "min_post": 1},
    "acwr_gap": {"label": "Écart de l'ACWR à la zone 0,8–1,3", "higher_better": False, "mode": "abs",
                 "tol": 0.1, "min_pre": 1, "min_post": 2},
    "rpe": {"label": "RPE moyen des séances (/10)", "higher_better": False, "mode": "abs", "tol": 1.0,
            "min_pre": 1, "min_post": 1},
    "decoupling": {"label": "Découplage aérobie moyen (%)", "higher_better": False, "mode": "abs",
                   "tol": 2.0, "min_pre": 1, "min_post": 1},
    "compliance": {"label": "Conformité du plan (séances faites / prévues)", "higher_better": True,
                   "mode": "abs", "tol": 0.15, "min_pre": 2, "min_post": 2},
}

# Libellés (langue des documents) des déclencheurs dans l'énoncé de synthèse.
TRIGGER_LABEL = {
    "morning_check": "bilan matinal", "guardrail": "garde-fou", "athlete_request": "demande de l'athlète",
    "medical": "médical", "weather": "météo", "race": "course", "other": "autre",
}

# Nature de l'action (revue #175) : DÉRIVÉE des champs `before`/`after` déjà présents au contrat
# `decision` (#54) — aucun champ nouveau à remplir par les agents, et les décisions déjà écrites en
# profitent. Ordre des intensités : `arc_contract.INTENSITY` sans `strength` (hors de l'axe).
ACTION_KINDS = ("lighten", "cancel", "move", "intensify", "replace", "other", "unspecified")
ACTION_LABEL = {
    "lighten": "allègement", "cancel": "annulation", "move": "report", "intensify": "renforcement",
    "replace": "remplacement", "other": "autre changement", "unspecified": "action non précisée",
}
INTENSITY_RANK = {k: i for i, k in enumerate(
    ("rest", "recovery", "endurance", "tempo", "threshold", "vo2max", "race"))}


def _sign(a: Any, b: Any) -> int:
    return 0 if a is None or b is None or a == b else (1 if b > a else -1)


def action_kind(decision: dict) -> str:
    """Nature de l'action d'une décision, lue dans `before`/`after` (#54) — jamais devinée du texte.

    `after.status = cancelled` → `cancel` ; `after.status = moved` ou date changée → `move` ;
    intensité (rang) et/ou durée prévue en baisse sans rien en hausse → `lighten`, en hausse sans rien
    en baisse → `intensify` ; sport/titre changés seuls → `replace` ; signaux contraires → `other` ;
    ni `before` ni `after` → `unspecified`."""
    before = decision.get("before") if isinstance(decision.get("before"), dict) else {}
    after = decision.get("after") if isinstance(decision.get("after"), dict) else {}
    if not before and not after:
        return "unspecified"
    if after.get("status") == "cancelled":
        return "cancel"
    if after.get("status") == "moved" or (before.get("date") and after.get("date")
                                           and before["date"] != after["date"]):
        return "move"
    signs = {_sign(INTENSITY_RANK.get(before.get("intensity")), INTENSITY_RANK.get(after.get("intensity"))),
             _sign(before.get("planned_duration_s") if _num(before.get("planned_duration_s")) else None,
                   after.get("planned_duration_s") if _num(after.get("planned_duration_s")) else None)}
    signs.discard(0)
    if signs == {-1}:
        return "lighten"
    if signs == {1}:
        return "intensify"
    if signs:
        return "other"
    if any(k in after for k in ("sport", "title", "intensity")):
        return "replace"
    return "other"


REASONS = {
    "proposed": "décision seulement proposée : rien n'a été appliqué, aucun effet à mesurer",
    "superseded": "décision remplacée par une réévaluation plus récente : l'effet est porté par la suivante",
    "window_open": "fenêtre d'observation pas encore écoulée",
    "no_signal": "aucun signal exploitable avant ET après",
    "bad_date": "date de décision illisible",
}

ASSUMPTIONS = {
    "not_causal": (
        "L'effet mesuré est une CORRÉLATION temporelle (ce qui s'est passé après la décision), jamais "
        "une preuve de causalité : repos, sommeil, météo, charge déjà en cours, régression vers la "
        "moyenne et hasard jouent aussi. Ce bilan n'assouplit JAMAIS un garde-fou `block`, une "
        "décision médicale ni un verdict rouge, et ne justifie pas à lui seul de changer le plan."
    ),
    "windows": (
        "AVANT = les 3 jours se terminant à J inclus (mesure déclenchante) pour les séries "
        "quotidiennes (HRV, FC de repos, readiness, douleur, ACWR) ; les 14 jours précédant J pour les "
        "séances (RPE, découplage) ; les 7 jours se terminant à J pour la conformité. APRÈS = J+1 à "
        "J+N, N par déclencheur : 3 (bilan matinal, météo — l'effet d'un allègement sur la HRV/FC de "
        "repos se lit en quelques nuits), 7 (blessure, garde-fou, demande de l'athlète, course, autre — "
        "douleur et charge évoluent plus lentement). APPROXIMATIONS DU PROJET, pas des seuils tirés "
        "d'une source : choisies pour un recul court mais non bruité sur un seul relevé."
    ),
    "thresholds": (
        "Une variation AVANT→APRÈS est « neutre » sous la tolérance du signal : HRV ±5 % (relatif), FC "
        "de repos ±2 bpm, readiness ±5 points, douleur ±1 point, écart d'ACWR ±0,1, RPE ±1, découplage "
        "±2 points, conformité ±15 points. APPROXIMATIONS DU PROJET (ordre de grandeur de la variation "
        "quotidienne usuelle de chaque grandeur), jamais une norme clinique."
    ),
    "combination": (
        "Les signaux d'une décision votent : `improved` si au moins un s'améliore et aucun ne se "
        "dégrade ; `worsened` si au moins un se dégrade et aucun ne s'améliore ; sinon `neutral` "
        "(signaux contradictoires ou stables). Un signal dont une fenêtre manque de points est SAUTÉ "
        "avec sa raison, jamais imputé ; aucun signal exploitable → `insufficient_data`."
    ),
    "sample": (
        f"Sous {MIN_SAMPLE_FOR_TREND} décisions évaluables dans un groupe (déclencheur × action × "
        "issue), la synthèse énonce les comptes sans parler de « tendance » : trop peu de cas pour "
        "distinguer un effet du hasard. Les décisions `insufficient_data` ne comptent pas dans "
        "l'effectif. Au-delà : « plutôt favorable » si au moins 60 % des cas évoluent favorablement, "
        "« plutôt défavorable » si au moins 60 % évoluent défavorablement, « mitigée » sinon (seuil "
        "APPROXIMATION DU PROJET). Une décision prise sur une valeur basse est souvent suivie d'un "
        "retour vers la moyenne, qu'elle ait été suivie ou non : comparer le groupe « appliquées » au "
        "groupe « refusées » quand les deux existent."
    ),
    "scope": (
        "Seules les décisions `applied` et `rejected_by_athlete` sont évaluées (comparaison suivi / "
        "non suivi) ; `proposed` (rien d'appliqué) et `superseded` restent `insufficient_data` : dans "
        "une chaîne `supersedes`, l'effet est porté par la DERNIÈRE décision, mesuré depuis sa propre "
        "date (une décision appliquée quelques jours puis remplacée n'est pas créditée)."
    ),
    "action": (
        "Regroupement par déclencheur × nature de l'action × issue. La nature (`allègement`, "
        "`annulation`, `report`, `renforcement`, `remplacement`, `autre changement`) est DÉRIVÉE des "
        "champs `before`/`after` déjà présents au contrat `decision` (rang d'intensité "
        "repos < récupération < endurance < tempo < seuil < VO2max < course, durée prévue, statut, "
        "date) ; sans `before`/`after`, « action non précisée ». Jamais déduite du texte libre."
    ),
    "overlap": (
        "Deux décisions (hors `proposed`) dont les fenêtres se chevauchent — même jour, ou une "
        "décision prise pendant la fenêtre AVANT/APRÈS d'une autre — sont signalées (`overlaps`) : "
        "leurs effets se confondent et ne peuvent pas être attribués à l'une plutôt qu'à l'autre. "
        "Elles restent comptées, avec ce signalement dans la synthèse. Une décision et celle qu'elle "
        "remplace (`supersedes`) forment un seul fil de réévaluation : jamais un chevauchement."
    ),
    "signal_reading": (
        "Sens des signaux : HRV en hausse, FC de repos en baisse, readiness en hausse, douleur en "
        "baisse, ACWR plus proche de la zone 0,8–1,3, RPE et découplage en baisse, conformité en "
        "hausse = évolution favorable. Limite : RPE et découplage dépendent de l'intensité des séances, "
        "que la décision elle-même change souvent (un allègement fait baisser le RPE "
        "mécaniquement) — à lire comme la tolérance ressentie, pas comme un gain de forme. Douleur : "
        "MOYENNE des relevés de chaque fenêtre (un maximum sur des fenêtres de longueurs différentes "
        "pencherait vers « aggravée »)."
    ),
    "storage": (
        "Effets DÉRIVÉS, jamais stockés : recalculés à chaque appel depuis l'index (déjà dérivé des "
        "fichiers). Pas de table, pas de champ dans le contrat `arc` : un fichier de décision écrit par "
        "un agent/athlète n'est jamais modifié, et un effet ne peut pas rester périmé quand la fenêtre "
        "d'observation se referme ou qu'un relevé arrive après coup."
    ),
}

CAVEAT = ("Corrélation, pas causalité : ce bilan décrit ce qui s'est passé après les décisions, pas ce "
          "qu'elles ont causé. Il n'assouplit jamais un garde-fou `block`, une décision médicale ni un "
          "verdict rouge.")


def _d(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _day_series(series: Dict[str, Optional[float]], start: date, end: date) -> List[float]:
    """Valeurs présentes (non nulles) d'une série quotidienne dans [start, end] — jamais imputées."""
    out = []
    d = start
    while d <= end:
        v = series.get(d.isoformat())
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
        d += timedelta(days=1)
    return out


def _acwr_gap(value: float) -> float:
    lo, hi = ACWR_BAND
    return max(0.0, lo - value, value - hi)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _by_day(rows: Optional[Iterable[dict]]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for r in rows or []:
        day = _d(r.get("date"))
        if day:
            out.setdefault(day.isoformat(), []).append(r)
    return out


def _indexed(data: dict) -> dict:
    """Séances/séances prévues regroupées par jour, une seule fois (évite un balayage complet par
    signal et par décision — l'historique peut compter des centaines de décisions)."""
    if "_sessions_by_day" not in data:
        data = {**data, "_sessions_by_day": _by_day(data.get("sessions")),
                "_planned_by_day": _by_day(data.get("planned"))}
    return data


def _days(start: date, end: date) -> Iterable[str]:
    d = start
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def _window_values(signal: str, data: dict, start: date, end: date) -> List[float]:
    """Valeurs brutes d'un signal dans [start, end] (une par jour ou par séance)."""
    data = _indexed(data)
    if signal in ("hrv", "rhr", "readiness", "pain"):
        health = data.get("health") or {}
        key = {"hrv": "hrv_ms", "rhr": "rhr_bpm", "readiness": "readiness", "pain": "pain_max"}[signal]
        return _day_series({d: (health.get(d) or {}).get(key) for d in _days(start, end)}, start, end)
    if signal == "acwr_gap":
        return [_acwr_gap(v) for v in _day_series(data.get("acwr") or {}, start, end)]
    if signal in ("rpe", "decoupling"):
        key = "rpe" if signal == "rpe" else "decoupling_pct"
        return [float(s[key]) for d in _days(start, end) for s in data["_sessions_by_day"].get(d, [])
                if _num(s.get(key))]
    if signal == "compliance":
        return [1.0 if p["status"] == "done" else 0.0 for d in _days(start, end)
                for p in data["_planned_by_day"].get(d, []) if p.get("status") in ("done", "missed")]
    return []


def _windows(signal: str, day: date, horizon: int):
    """((début, fin) AVANT, (début, fin) APRÈS) du signal — voir ASSUMPTIONS["windows"]."""
    if signal in ("rpe", "decoupling"):
        pre = (day - timedelta(days=PRE_SESSION_DAYS), day - timedelta(days=1))
    elif signal == "compliance":
        pre = (day - timedelta(days=PRE_COMPLIANCE_DAYS - 1), day)
    else:
        pre = (day - timedelta(days=PRE_DAYS - 1), day)
    return pre, (day + timedelta(days=1), day + timedelta(days=horizon))


def evaluate_signal(signal: str, data: dict, day: date, horizon: int) -> dict:
    """Un signal : moyennes AVANT/APRÈS, variation, verdict — ou `skipped` avec la raison."""
    spec = SIGNALS[signal]
    (pre_s, pre_e), (post_s, post_e) = _windows(signal, day, horizon)
    pre_vals = _window_values(signal, data, pre_s, pre_e)
    post_vals = _window_values(signal, data, post_s, post_e)
    base = {"signal": signal, "label": spec["label"],
            "pre": {"from": pre_s.isoformat(), "to": pre_e.isoformat(), "n": len(pre_vals)},
            "post": {"from": post_s.isoformat(), "to": post_e.isoformat(), "n": len(post_vals)}}
    # Moyenne pour TOUS les signaux, douleur comprise (revue #175) : un maximum comparé entre une
    # fenêtre AVANT de 3 jours et une fenêtre APRÈS de 7 jours (et des relevés `/log` souvent plus
    # nombreux pendant le suivi d'une blessure) penchait mécaniquement vers « aggravée ».
    pre_v, post_v = _mean(pre_vals), _mean(post_vals)
    if len(pre_vals) < spec["min_pre"] or len(post_vals) < spec["min_post"]:
        missing = []
        if len(pre_vals) < spec["min_pre"]:
            missing.append(f"avant : {len(pre_vals)}/{spec['min_pre']} mesure(s)")
        if len(post_vals) < spec["min_post"]:
            missing.append(f"après : {len(post_vals)}/{spec['min_post']} mesure(s)")
        return {**base, "skipped": "mesures insuffisantes (" + ", ".join(missing) + ")"}
    delta = post_v - pre_v
    tol = spec["tol"] * (abs(pre_v) if spec["mode"] == "rel" else 1.0)
    if spec["mode"] == "rel" and pre_v == 0:
        return {**base, "skipped": "valeur de référence nulle (variation relative indéfinie)"}
    if abs(delta) < tol:
        verdict = "neutral"
    else:
        better = (delta > 0) == spec["higher_better"]
        verdict = "improved" if better else "worsened"
    return {**base, "pre_value": round(pre_v, 3), "post_value": round(post_v, 3),
            "delta": round(delta, 3), "tolerance": round(tol, 3), "verdict": verdict}


def evaluate_decision(decision: dict, data: dict, today: date) -> dict:
    """Effet d'UNE décision : `effect`, horizon, signaux évalués et sautés, raison éventuelle."""
    trigger = decision.get("trigger") or "other"
    plan = TRIGGER_PLAN.get(trigger) or TRIGGER_PLAN["other"]
    horizon = plan["horizon_days"]
    out = {"id": decision.get("id"), "source_path": decision.get("source_path"), "date": decision.get("date"),
           "trigger": trigger, "action": action_kind(decision), "outcome": decision.get("outcome"),
           "horizon_days": horizon, "signals": [], "skipped": []}

    def done(effect: str, reason_code: Optional[str] = None, **extra) -> dict:
        out["effect"] = effect
        if reason_code:
            out["reason_code"] = reason_code
            out["reason"] = REASONS[reason_code]
        out.update(extra)
        return out

    day = _d(decision.get("date"))
    if day is None:
        return done("insufficient_data", "bad_date")
    if decision.get("outcome") in ("proposed", "superseded"):
        return done("insufficient_data", decision["outcome"])
    mature = day + timedelta(days=horizon)
    if today < mature:
        return done("insufficient_data", "window_open", mature_on=mature.isoformat())
    for signal in plan["signals"]:
        res = evaluate_signal(signal, data, day, horizon)
        if "skipped" in res:
            out["skipped"].append({"signal": signal, "label": res["label"], "reason": res["skipped"]})
        else:
            out["signals"].append(res)
    if not out["signals"]:
        return done("insufficient_data", "no_signal")
    verdicts = {s["verdict"] for s in out["signals"]}
    if "improved" in verdicts and "worsened" not in verdicts:
        effect = "improved"
    elif "worsened" in verdicts and "improved" not in verdicts:
        effect = "worsened"
    else:
        effect = "neutral"
    return done(effect)


def _span(decision: dict) -> Optional[tuple]:
    day = _d(decision.get("date"))
    if day is None:
        return None
    plan = TRIGGER_PLAN.get(decision.get("trigger") or "other") or TRIGGER_PLAN["other"]
    return day - timedelta(days=PRE_DAYS - 1), day + timedelta(days=plan["horizon_days"])


def evaluate_all(decisions: Iterable[dict], data: dict, today: date,
                 context: Optional[Iterable[dict]] = None) -> List[dict]:
    """Évalue chaque décision ; `overlaps` = autres décisions (hors `proposed`, prises dans `context`,
    défaut : les mêmes) datées dans la fenêtre AVANT/APRÈS de celle-ci — ASSUMPTIONS["overlap"]."""
    decisions = list(decisions)
    data = _indexed(data)
    others = [c for c in (decisions if context is None else context) if c.get("outcome") != "proposed"]
    out = []
    for d in decisions:
        ev = evaluate_decision(d, data, today)
        span = _span(d)
        if span and ev["outcome"] in ("applied", "rejected_by_athlete"):
            # Une décision et celle qu'elle remplace (`supersedes`, dans un sens ou l'autre) sont le
            # MÊME fil de réévaluation, pas deux décisions concurrentes : jamais comptées en chevauchement.
            ev["overlaps"] = sorted(
                str(c.get("id")) for c in others
                if c.get("id") != d.get("id") and _d(c.get("date")) and span[0] <= _d(c.get("date")) <= span[1]
                and not (d.get("supersedes") and d.get("supersedes") == c.get("source_path"))
                and not (c.get("supersedes") and c.get("supersedes") == d.get("source_path")))
        out.append(ev)
    return out


def synthesize(evaluations: Iterable[dict]) -> List[dict]:
    """Synthèse par groupe (déclencheur × action × issue) : comptes, `trend_allowed`, énoncé honnête.

    `trend` n'est renseigné que si l'effectif évaluable atteint `MIN_SAMPLE_FOR_TREND` — jamais sur
    2 cas. L'énoncé ne dit que les comptes ; le mot « tendance » n'apparaît que si elle est permise."""
    groups: Dict[tuple, dict] = {}
    for ev in evaluations:
        if ev["outcome"] not in ("applied", "rejected_by_athlete"):
            continue   # proposed/superseded : jamais évaluées (ASSUMPTIONS["scope"]), pas de groupe vide
        action = ev.get("action") or "unspecified"
        key = (ev["trigger"], action, ev["outcome"])
        g = groups.setdefault(key, {"trigger": ev["trigger"], "action": action, "outcome": ev["outcome"],
                                     "total": 0, "improved": 0, "neutral": 0, "worsened": 0,
                                     "insufficient_data": 0, "overlapping": 0})
        g["total"] += 1
        g[ev["effect"]] += 1
        if ev["effect"] != "insufficient_data" and ev.get("overlaps"):
            g["overlapping"] += 1
    out = []
    for g in groups.values():
        n = g["improved"] + g["neutral"] + g["worsened"]
        g["n"] = n
        g["trend_allowed"] = n >= MIN_SAMPLE_FOR_TREND
        parts = []
        if n:
            parts = [f"{g[k]} {label}" for k, label in
                     (("improved", "améliorée(s)"), ("neutral", "neutre(s)"), ("worsened", "aggravée(s)")) if g[k]]
        who = {"applied": "appliquées", "rejected_by_athlete": "non suivies (refusées par l'athlète)",
               "proposed": "proposées", "superseded": "remplacées"}.get(g["outcome"], str(g["outcome"]))
        what = (f"{ACTION_LABEL.get(g['action'], g['action']).capitalize()} après "
                f"{TRIGGER_LABEL.get(g['trigger'], g['trigger'])}")
        text = f"{what} — décisions {who} : {n} évaluée(s)" + (f" ({', '.join(parts)})" if parts else "")
        if g["overlapping"]:
            text += (f" ; dont {g['overlapping']} avec une autre décision dans la même fenêtre "
                     "(effets confondus)")
        if g["insufficient_data"]:
            text += f" ; {g['insufficient_data']} sans données suffisantes"
        if n == 0:
            g["trend"] = None
            g["warning"] = "aucune décision évaluable pour l'instant"
        elif g["trend_allowed"]:
            share = g["improved"] / n
            g["trend"] = ("plutôt favorable" if share >= 0.6 and g["worsened"] <= g["improved"]
                          else "plutôt défavorable" if g["worsened"] / n >= 0.6 else "mitigée")
            g["warning"] = None
        else:
            g["trend"] = None
            g["warning"] = (f"effectif trop faible (n={n} < {MIN_SAMPLE_FOR_TREND}) : comptes bruts, "
                            "aucune tendance")
        g["statement"] = text
        out.append(g)
    out.sort(key=lambda g: (-g["n"], g["trigger"], g["action"], str(g["outcome"])))
    return out
