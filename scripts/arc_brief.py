#!/usr/bin/env python3
"""Brief Horae (`brief()`, contrat v1) : le résumé du jour pour la note du matin de Horae.

Horae (https://github.com/horae-dev/horae) appelle l'outil MCP `brief(schema_version=1)` du
tableau de bord et en tire une section de la note du matin, des tâches et, pour les seules
alertes `crit`, une notification. Contrat : https://github.com/horae-dev/plugin-mcp-brief
(`docs/brief-contract.md`, schéma `schemas/brief/v1.json`, copié dans
`tests/data/fixtures/horae_brief/`). Documentation : `docs/dashboard/horae.md`.

Deux parties, sans réseau ni écriture :

- `build_brief(facts, now, base_url)` : document v1 à partir des FAITS agrégés que
  `arc_serve.brief_facts` lit dans l'index (séances prévues du jour, bilan matinal, séances
  récentes, semaine suivante, prochaine course, chaussures, état de la synchronisation). Fonction
  pure : mêmes faits, même document. Aucun texte libre du workspace n'y entre (titre de séance,
  motif du verdict, notes) : seulement des champs structurés et des libellés fixes ; les deux noms
  repris tels quels sont ceux d'une chaussure et d'une course, déclarés par l'athlète.
- `McpEndpoint` : le point d'entrée MCP « streamable HTTP » (`POST /mcp`, JSON-RPC 2.0, réponses
  JSON, sans session) qui n'expose QUE l'outil `brief`. Authentification par jeton porteur
  (`HORAE_BRIEF_TOKEN_FILE` ou `HORAE_BRIEF_TOKEN`), comparé en temps constant ; sans jeton
  configuré, le point d'entrée n'existe pas (404).

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
SERVICE_ID = "ai-running-coach"
SERVICE_NAME = {"fr": "Coach running", "en": "Running coach"}

# Durée de validité : la journée en cours, au plus 12 h, au moins 15 min (le contrat borne à 48 h,
# Horae refuse un `valid_until` qui n'est pas après `generated_at`).
VALIDITY_MAX = timedelta(hours=12)
VALIDITY_MIN = timedelta(minutes=15)
# Une synchronisation en échec depuis plus longtemps que ça devient une alerte `crit` (poussée).
SYNC_CRIT_AFTER = timedelta(hours=24)
# Relecture du plan de course : à partir de N jours avant la course.
RACE_REVIEW_DAYS = 14
RACE_REVIEW_LEAD_DAYS = 3
# Récupération basse : verdict rouge du bilan, ou readiness sous ce seuil.
READINESS_LOW = 30
# FC de repos au-dessus de la médiane 7 j (bpm) : même seuil « alerte » que la vue Santé.
RHR_ALERT_BPM = 7
# Plafonds du contrat (le schéma les vérifie aussi ; on ne les atteint jamais en pratique).
MAX_ALERTS, MAX_TASKS, MAX_LINKS = 10, 10, 5
# Le document sérialisé ne dépasse jamais ça (Horae coupe à 64 Kio, réponse MCP comprise : le
# document y figure deux fois, en `structuredContent` et en texte).
BRIEF_MAX_BYTES = 24 * 1024

# Caractères refusés par le contrat dans un texte « une ligne » (Cc, Cf, Zl, Zp et apparentés) :
# même classe que les motifs du schéma v1.
_FORBIDDEN = re.compile(
    "[\x00-\x1f\x7f-\x9f­؀-؅؜۝܏࢐࢑࣢᠎"
    "​-‏ -‮⁠-⁤⁦-⁯﻿￹-￻]")
_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_BASE_URL_RE = re.compile(r"^https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?/(?:[\x21-\x5b\x5d-\x7e]*/)?$")

SPORT_LABEL = {
    "fr": {"running": "Course", "trail": "Trail", "strength": "Renforcement", "indoor_cycling": "Vélo d'intérieur",
           "home_trainer": "Home trainer", "hiking": "Randonnée", "elliptical": "Elliptique", "rest": "Repos",
           "cycling": "Vélo", "swimming": "Natation", "rowing": "Rameur", "walking": "Marche"},
    "en": {"running": "Run", "trail": "Trail run", "strength": "Strength", "indoor_cycling": "Indoor cycling",
           "home_trainer": "Home trainer", "hiking": "Hike", "elliptical": "Elliptical", "rest": "Rest",
           "cycling": "Ride", "swimming": "Swim", "rowing": "Row", "walking": "Walk"},
}
INTENSITY_LABEL = {
    "fr": {"rest": "repos", "recovery": "récupération", "endurance": "endurance", "tempo": "tempo",
           "threshold": "seuil", "vo2max": "VO2max", "race": "course", "strength": "renforcement"},
    "en": {"rest": "rest", "recovery": "recovery", "endurance": "endurance", "tempo": "tempo",
           "threshold": "threshold", "vo2max": "VO2max", "race": "race", "strength": "strength"},
}
VERDICT_LABEL = {
    "fr": {"green": "feu vert", "amber": "feu orange", "red": "feu rouge"},
    "en": {"green": "green light", "amber": "amber light", "red": "red light"},
}
# Ce que le bilan fait de la séance prévue (`health.session_advice[].action`), du plus fort au plus faible.
ADVICE_ORDER = ("cancel", "replace", "lighten")
ADVICE_LABEL = {
    "fr": {"cancel": "séance annulée par le bilan", "replace": "séance à remplacer (bilan)",
           "lighten": "séance à alléger (bilan)"},
    "en": {"cancel": "session cancelled by the check", "replace": "session to replace (check)",
           "lighten": "session to lighten (check)"},
}
# Sports qui n'appellent pas de ressenti à noter.
NO_FEEDBACK_SPORTS = {"rest", "walking"}
SYNC_PROBLEM = {"late", "failing", "degraded", "never"}

T = {
    "fr": {
        "today": "Aujourd'hui : {what}",
        "nothing": "rien de prévu",
        "check_missing": "bilan matinal pas encore fait",
        "readiness": "readiness {score}",
        "sync_degraded": "Synchronisation automatique en retard ou en échec : données peut-être incomplètes.",
        "sync_never": "Synchronisation automatique jamais lancée : données saisies à la main uniquement.",
        "index_error": "Données du tableau de bord indisponibles pour le moment.",
        "index_headline": "Brief indisponible : l'index du tableau de bord n'est pas prêt.",
        "sync_crit": "La synchronisation des données échoue depuis plus de 24 h",
        "sync_crit_body": "Aucune donnée récente : vérifiez la connexion à la montre (/coach-doctor).",
        "sync_warn": "Synchronisation des données en retard ou en échec",
        "sync_warn_body": "Détail dans la vue Synchro du tableau de bord.",
        "sync_never_title": "Synchronisation automatique jamais lancée",
        "readiness_low": "Récupération basse ce matin",
        "readiness_low_body": "Le bilan matinal donne {verdict}{score} : séance du jour à revoir avec le coach.",
        "hrv_low": "HRV sous votre norme personnelle",
        "hrv_low_body": "Moyenne HRV des 7 dernières nuits sous la bande personnelle de 60 jours.",
        "rhr_high": "FC de repos élevée (+{delta} bpm)",
        "rhr_high_body": "FC de repos au-dessus de la médiane des 7 jours précédents.",
        "shoe_retire": "Chaussures à remplacer : {name}",
        "shoe_retire_body": "{km} km pour un seuil de {limit} km.",
        "shoe_near": "Chaussures bientôt en fin de vie : {name}",
        "shoe_near_body": "{km} km pour un seuil de {limit} km{forecast}.",
        "shoe_forecast": ", seuil prévu vers le {date}",
        "task_feedback": "Noter le ressenti de la séance du {date} (/log)",
        "task_plan_week": "Planifier la semaine du {date}",
        "task_race_review": "Relire le plan de course : {name} ({date})",
        "task_race_plan": "Préparer le plan de course : {name} ({date})",
        "race_in": "{name} dans {days} j",
        "race_today": "{name} aujourd'hui",
        "link_dashboard": "Tableau de bord",
        "link_week": "Semaine",
        "link_health": "Santé",
        "link_sync": "Synchro",
        "link_roadbook": "Roadbook",
    },
    "en": {
        "today": "Today: {what}",
        "nothing": "nothing planned",
        "check_missing": "morning check not done yet",
        "readiness": "readiness {score}",
        "sync_degraded": "Automatic sync late or failing: data may be incomplete.",
        "sync_never": "Automatic sync never ran: manually entered data only.",
        "index_error": "Dashboard data unavailable for now.",
        "index_headline": "Brief unavailable: the dashboard index is not ready.",
        "sync_crit": "Data sync has been failing for more than 24 h",
        "sync_crit_body": "No recent data: check the watch connection (/coach-doctor).",
        "sync_warn": "Data sync late or failing",
        "sync_warn_body": "Details in the dashboard Sync view.",
        "sync_never_title": "Automatic sync never ran",
        "readiness_low": "Low recovery this morning",
        "readiness_low_body": "The morning check gives {verdict}{score}: review today's session with the coach.",
        "hrv_low": "HRV below your personal norm",
        "hrv_low_body": "7-night HRV average below the 60-day personal band.",
        "rhr_high": "Resting HR up (+{delta} bpm)",
        "rhr_high_body": "Resting HR above the median of the previous 7 days.",
        "shoe_retire": "Shoes to replace: {name}",
        "shoe_retire_body": "{km} km for a {limit} km threshold.",
        "shoe_near": "Shoes nearing retirement: {name}",
        "shoe_near_body": "{km} km for a {limit} km threshold{forecast}.",
        "shoe_forecast": ", threshold expected around {date}",
        "task_feedback": "Log how the {date} session felt (/log)",
        "task_plan_week": "Plan the week of {date}",
        "task_race_review": "Review the race plan: {name} ({date})",
        "task_race_plan": "Prepare the race plan: {name} ({date})",
        "race_in": "{name} in {days} d",
        "race_today": "{name} today",
        "link_dashboard": "Dashboard",
        "link_week": "Week",
        "link_health": "Health",
        "link_sync": "Sync",
        "link_roadbook": "Roadbook",
    },
}


# ---------------------------------------------------------------------------
# Texte
# ---------------------------------------------------------------------------


def one_line(text, limit: int) -> str:
    """Texte « une ligne » au sens du contrat : sans caractère de contrôle ni de format, espaces
    regroupés, coupé à `limit` caractères (avec « … »)."""
    text = "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in str(text or ""))
    text = _FORBIDDEN.sub("", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def stable_key(raw: str) -> str:
    """Fragment de clé stable et conforme (`[A-Za-z0-9._-]`) : tel quel s'il l'est, sinon un hachage."""
    raw = str(raw or "")
    if _KEY_RE.match(raw):
        return raw
    return "h" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _lang(facts: dict) -> str:
    return "en" if str(facts.get("language") or "fr").lower().startswith("en") else "fr"


def _day(d: date, lang: str) -> str:
    return d.strftime("%d/%m") if lang == "fr" else d.strftime("%m/%d")


def _duration(seconds: float, lang: str) -> str:
    minutes = int(round(seconds / 60))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest:02d}"
    if hours:
        return f"{hours} h"
    return f"{rest} min"


def _km(meters: float) -> str:
    km = meters / 1000
    return f"{km:.0f}" if km >= 20 or abs(km - round(km)) < 0.05 else f"{km:.1f}"


def session_label(session: dict, lang: str) -> str:
    """« Trail endurance 1 h 10 · 12 km » : uniquement les champs structurés de la séance, jamais son titre."""
    sport = session.get("sport") or ""
    label = SPORT_LABEL[lang].get(sport, SPORT_LABEL[lang]["running"] if sport else "")
    parts = [label] if label else []
    intensity = INTENSITY_LABEL[lang].get(session.get("intensity") or "")
    if intensity and intensity.lower() != label.lower():
        parts.append(intensity)
    text = " ".join(parts)
    extra = []
    if session.get("planned_duration_s"):
        extra.append(_duration(float(session["planned_duration_s"]), lang))
    if session.get("planned_distance_m"):
        extra.append(f"{_km(float(session['planned_distance_m']))} km")
    if session.get("planned_elevation_m"):
        extra.append(f"{int(round(float(session['planned_elevation_m'])))} m D+")
    if extra:
        text = f"{text} {extra[0]}" + "".join(f" · {e}" for e in extra[1:])
    return text


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def rfc3339(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validity(now: datetime) -> datetime:
    """Fin de validité : minuit local, au plus 12 h, au moins 15 min après `now`."""
    midnight = datetime.combine(now.date() + timedelta(days=1), time(0, 0), tzinfo=now.tzinfo)
    return max(now + VALIDITY_MIN, min(now + VALIDITY_MAX, midnight))


def link_base(base_url: Optional[str]) -> Optional[str]:
    """URL publique du tableau de bord (`https://hôte/`), ou None si elle n'est pas utilisable."""
    if not base_url:
        return None
    base = base_url.strip()
    if not base.endswith("/"):
        base += "/"
    return base if _BASE_URL_RE.match(base) and len(base) <= 200 else None


def _parse_dt(value, tz) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed


def _sync_alerts(sync: Optional[dict], now: datetime, lang: str, link) -> Tuple[List[dict], Optional[str]]:
    """Alertes et raison de `degraded` tirées de l'état de la synchronisation."""
    t = T[lang]
    if not sync or sync.get("verdict") not in SYNC_PROBLEM:
        return [], None
    verdict = sync["verdict"]
    if verdict == "never":
        return [{"key": "sync.never", "severity": "warn", "title": t["sync_never_title"],
                 **link("synchro")}], t["sync_never"]
    tz = now.tzinfo
    # Depuis quand ça ne va plus : dernier run réussi (planifié) ou dernier sondage (surveillance).
    last_good = _parse_dt(sync.get("last_check_at") if verdict == "late" and sync.get("mode") == "watch"
                          else sync.get("last_ok_run_at"), tz)
    if last_good is None:
        last_good = _parse_dt(sync.get("oldest_run_at"), tz)
    failing_long = verdict in ("late", "failing") and last_good is not None and now - last_good > SYNC_CRIT_AFTER
    if failing_long:
        alert = {"key": "sync.failing", "severity": "crit", "title": t["sync_crit"], "body": t["sync_crit_body"]}
    else:
        alert = {"key": "sync.late", "severity": "warn", "title": t["sync_warn"], "body": t["sync_warn_body"]}
    alert.update(link("synchro"))
    return [alert], t["sync_degraded"]


def _health_alerts(health: Optional[dict], lang: str, link) -> List[dict]:
    t = T[lang]
    if not health:
        return []
    alerts = []
    verdict, score = health.get("verdict"), health.get("readiness_score")
    if verdict == "red" or (isinstance(score, (int, float)) and score < READINESS_LOW):
        verdict_text = VERDICT_LABEL[lang].get(verdict, "")
        score_text = (", " if verdict_text else "") + t["readiness"].format(score=int(round(score))) \
            if isinstance(score, (int, float)) else ""
        alerts.append({"key": "readiness.low", "severity": "warn", "title": t["readiness_low"],
                       "body": t["readiness_low_body"].format(verdict=verdict_text, score=score_text), **link("sante")})
    if health.get("hrv_personal_status") == "sous":
        alerts.append({"key": "hrv.below_baseline", "severity": "warn", "title": t["hrv_low"],
                       "body": t["hrv_low_body"], **link("sante")})
    delta = health.get("rhr_delta")
    if isinstance(delta, (int, float)) and delta >= RHR_ALERT_BPM:
        alerts.append({"key": "rhr.elevated", "severity": "warn", "title": t["rhr_high"].format(delta=int(round(delta))),
                       "body": t["rhr_high_body"], **link("sante")})
    return alerts


def _shoe_alerts(shoes: List[dict], lang: str, link) -> List[dict]:
    t = T[lang]
    alerts = []
    for shoe in shoes or []:
        if shoe.get("retired"):
            continue
        name = one_line(shoe.get("name") or shoe.get("gear_id"), 60) or "?"
        km, limit = _km(shoe.get("distance_m") or 0), _km(shoe.get("threshold_m") or 0)
        key = stable_key(shoe.get("gear_id"))
        if shoe.get("alert"):
            alerts.append({"key": f"shoe.{key}.retire", "severity": "warn", "title": t["shoe_retire"].format(name=name),
                           "body": t["shoe_retire_body"].format(km=km, limit=limit), **link("materiel")})
        elif shoe.get("near_threshold"):
            forecast = ""
            if shoe.get("retire_forecast_date"):
                try:
                    forecast = t["shoe_forecast"].format(date=_day(date.fromisoformat(shoe["retire_forecast_date"]), lang))
                except ValueError:
                    forecast = ""
            alerts.append({"key": f"shoe.{key}.near", "severity": "warn", "title": t["shoe_near"].format(name=name),
                           "body": t["shoe_near_body"].format(km=km, limit=limit, forecast=forecast), **link("materiel")})
    return alerts


def _tasks(facts: dict, today: date, lang: str, link) -> List[dict]:
    t = T[lang]
    tasks = []
    for day_iso in sorted(facts.get("feedback_missing") or []):
        try:
            day = date.fromisoformat(day_iso)
        except ValueError:
            continue
        tasks.append({"id": f"feedback.{day.isoformat()}", "title": t["task_feedback"].format(date=_day(day, lang)),
                      "due": today.isoformat(), **link("seances")})
    next_monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    if today.weekday() >= 4 and not facts.get("next_week_planned"):
        tasks.append({"id": f"plan.week.{next_monday.isoformat()}",
                      "title": t["task_plan_week"].format(date=_day(next_monday, lang)),
                      "due": (next_monday - timedelta(days=1)).isoformat(), **link("semaine")})
    race = facts.get("race")
    if race and race.get("date"):
        try:
            race_day = date.fromisoformat(race["date"])
        except ValueError:
            race_day = None
        if race_day and 0 <= (race_day - today).days <= RACE_REVIEW_DAYS:
            name = one_line(race.get("name"), 80) or "?"
            due = max(today, race_day - timedelta(days=RACE_REVIEW_LEAD_DAYS)).isoformat()
            if race.get("has_plan"):
                tasks.append({"id": f"race.review.{race_day.isoformat()}", "due": due,
                              "title": t["task_race_review"].format(name=name, date=_day(race_day, lang)),
                              **link("roadbook")})
            else:
                tasks.append({"id": f"race.plan.{race_day.isoformat()}", "due": due,
                              "title": t["task_race_plan"].format(name=name, date=_day(race_day, lang))})
    return tasks[:MAX_TASKS]


def _headline(facts: dict, today: date, lang: str) -> str:
    t = T[lang]
    sessions = [s for s in facts.get("sessions_today") or [] if s.get("status") not in ("cancelled", "moved")]
    what = " + ".join(session_label(s, lang) for s in sessions[:3] if session_label(s, lang)) or t["nothing"]
    parts = [t["today"].format(what=what)]
    health = facts.get("health_today")
    if facts.get("morning_check") != "off":
        if health:
            bits = []
            verdict = VERDICT_LABEL[lang].get(health.get("verdict") or "")
            if verdict:
                bits.append(verdict)
            if isinstance(health.get("readiness_score"), (int, float)):
                bits.append(t["readiness"].format(score=int(round(health["readiness_score"]))))
            actions = set(health.get("advice_actions") or [])
            advice = next((a for a in ADVICE_ORDER if a in actions), None)
            if advice and sessions:
                bits.append(ADVICE_LABEL[lang][advice])
            if bits:
                parts.append(", ".join(bits))
        else:
            parts.append(t["check_missing"])
    race = facts.get("race")
    if race and race.get("date"):
        try:
            days = (date.fromisoformat(race["date"]) - today).days
        except ValueError:
            days = -1
        if 0 <= days <= RACE_REVIEW_DAYS:
            name = one_line(race.get("name"), 60) or "?"
            parts.append(t["race_today"].format(name=name) if days == 0 else t["race_in"].format(name=name, days=days))
    return one_line(" · ".join(parts), 200)


def error_brief(now: datetime, lang: str, reason_key: str = "index_error") -> dict:
    """Document `error` : rien d'utilisable (index pas prêt, erreur de lecture). Aucun détail interne."""
    t = T["en" if lang == "en" else "fr"]
    return {
        "schema_version": SCHEMA_VERSION,
        "service": {"id": SERVICE_ID, "name": SERVICE_NAME["en" if lang == "en" else "fr"]},
        "generated_at": rfc3339(now),
        "valid_until": rfc3339(now + VALIDITY_MIN),
        "status": {"state": "error", "reason": t[reason_key]},
        "headline": t["index_headline"],
    }


def build_brief(facts: dict, now: datetime, base_url: Optional[str] = None) -> dict:
    """Document brief v1 à partir des faits agrégés (`arc_serve.brief_facts`). `now` : instant AVEC fuseau."""
    if now.tzinfo is None:
        raise ValueError("now doit porter un fuseau")
    lang = _lang(facts)
    t = T[lang]
    today = date.fromisoformat(facts["today"])
    base = link_base(base_url)

    def link(view: Optional[str]) -> dict:
        if not base:
            return {}
        return {"link": base + (f"#/{view}" if view else "")}

    sync_alerts, degraded_reason = _sync_alerts(facts.get("sync"), now, lang, link)
    alerts = sync_alerts + _health_alerts(facts.get("health_today") if facts.get("morning_check") != "off" else None,
                                          lang, link) + _shoe_alerts(facts.get("shoes") or [], lang, link)
    # `crit` d'abord : Horae pousse au plus 3 alertes par service, dans l'ordre du document.
    alerts.sort(key=lambda a: {"crit": 0, "warn": 1, "info": 2}[a["severity"]])
    seen, unique = set(), []
    for alert in alerts:
        if alert["key"] not in seen:
            seen.add(alert["key"])
            unique.append(alert)
    tasks = _tasks(facts, today, lang, link)
    links = []
    if base:
        links = [{"label": t["link_dashboard"], "url": base}, {"label": t["link_week"], "url": base + "#/semaine"}]
        if facts.get("morning_check") != "off":
            links.append({"label": t["link_health"], "url": base + "#/sante"})
        if degraded_reason:
            links.append({"label": t["link_sync"], "url": base + "#/synchro"})
    doc = {
        "schema_version": SCHEMA_VERSION,
        "service": {"id": SERVICE_ID, "name": SERVICE_NAME[lang]},
        "generated_at": rfc3339(now),
        "valid_until": rfc3339(validity(now)),
        "status": {"state": "degraded", "reason": degraded_reason} if degraded_reason else {"state": "ok"},
        "headline": _headline(facts, today, lang),
        "alerts": [{**a, "title": one_line(a["title"], 120), **({"body": one_line(a["body"], 500)} if a.get("body") else {})}
                   for a in unique[:MAX_ALERTS]],
        "tasks": [{**task, "title": one_line(task["title"], 200)} for task in tasks],
        "links": links[:MAX_LINKS],
    }
    return doc


# ---------------------------------------------------------------------------
# Jeton
# ---------------------------------------------------------------------------

TOKEN_ENV = "HORAE_BRIEF_TOKEN"
TOKEN_FILE_ENV = "HORAE_BRIEF_TOKEN_FILE"
BASE_URL_ENV = "HORAE_BRIEF_BASE_URL"
TOKEN_MIN_LEN = 32
TOKEN_MAX_LEN = 512
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")


def load_token(env=None, warn: Callable[[str], None] = None) -> Optional[str]:
    """Jeton porteur attendu, ou None (point d'entrée désactivé). Le fichier (`HORAE_BRIEF_TOKEN_FILE`,
    un secret Docker) prime sur la variable. Un jeton trop court ou mal formé désactive le point
    d'entrée, avec un avertissement qui ne cite jamais sa valeur."""
    env = os.environ if env is None else env
    warn = warn or (lambda msg: print(f"avertissement : {msg}", file=sys.stderr))
    path = (env.get(TOKEN_FILE_ENV) or "").strip()
    if path:
        try:
            token = Path(path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            warn(f"{TOKEN_FILE_ENV} illisible : point d'entrée /mcp (brief Horae) désactivé.")
            return None
    else:
        token = (env.get(TOKEN_ENV) or "").strip()
    if not token:
        return None
    if not (TOKEN_MIN_LEN <= len(token) <= TOKEN_MAX_LEN) or not _TOKEN_RE.match(token):
        warn(f"jeton du brief Horae refusé ({TOKEN_MIN_LEN} à {TOKEN_MAX_LEN} caractères parmi A-Z a-z 0-9 . _ ~ + / = -) : "
             "point d'entrée /mcp désactivé.")
        return None
    return token


def token_ok(header: Optional[str], expected: str) -> bool:
    """`Authorization: Bearer <jeton>` comparé en temps constant (empreintes de même longueur)."""
    if not header or not expected:
        return False
    scheme, _, given = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    given = given.strip()
    return hmac.compare_digest(hashlib.sha256(given.encode("utf-8", "surrogateescape")).digest(),
                               hashlib.sha256(expected.encode("utf-8")).digest())


# ---------------------------------------------------------------------------
# MCP (JSON-RPC 2.0 sur « streamable HTTP », réponses JSON, sans session)
# ---------------------------------------------------------------------------

# Versions du protocole à poignée de main (`initialize`). La plus récente sert de repli ; une
# sonde `server/discover` (révision 2026-07-28) reçoit « méthode inconnue » : le client
# retombe alors sur `initialize` (comportement documenté du SDK `mcp`).
PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MCP_BODY_MAX = 64 * 1024

BRIEF_TOOL = {
    "name": "brief",
    "title": "Brief du coach",
    "description": ("Résumé du jour pour Horae (contrat brief v1) : séance prévue, bilan matinal, alertes et tâches. "
                    "Agrégats seulement, lecture seule."),
    "inputSchema": {
        "type": "object",
        "properties": {"schema_version": {"type": "integer", "minimum": 1, "default": 1,
                                          "description": "Version majeure la plus haute que l'appelant comprend."}},
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False, "openWorldHint": False},
}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _tool_error(req_id, message: str) -> dict:
    return _result(req_id, {"content": [{"type": "text", "text": message}], "isError": True})


def handle_rpc(payload, produce: Callable[[], dict], server_version: str = "") -> Optional[dict]:
    """Une requête JSON-RPC déjà décodée → réponse (dict), ou None pour une notification (HTTP 202).

    `produce()` rend le document brief (déjà validé par construction). Aucune entrée de l'appelant
    n'est recopiée dans un message d'erreur."""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        req_id = payload.get("id") if isinstance(payload, dict) and isinstance(payload.get("id"), (str, int)) else None
        return _error(req_id, INVALID_REQUEST, "Invalid request")
    method = payload["method"]
    if "id" not in payload:
        return None                                  # notification (`notifications/initialized`…) : rien à rendre
    req_id = payload["id"]
    if not isinstance(req_id, (str, int)) or isinstance(req_id, bool):
        return _error(None, INVALID_REQUEST, "Invalid request")
    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(req_id, INVALID_PARAMS, "Invalid params")
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1]
        return _result(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVICE_ID, "version": server_version or "0"},
            "instructions": "Un seul outil, `brief`, en lecture seule : le résumé du jour au format Horae brief v1.",
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": [BRIEF_TOOL]})
    if method == "tools/call":
        if params.get("name") != "brief":
            return _error(req_id, INVALID_PARAMS, "Unknown tool")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict) or set(arguments) - {"schema_version"}:
            return _error(req_id, INVALID_PARAMS, "Invalid arguments")
        wanted = arguments.get("schema_version", 1)
        if not isinstance(wanted, int) or isinstance(wanted, bool) or wanted < SCHEMA_VERSION:
            return _tool_error(req_id, f"Unsupported schema_version: this service speaks brief v{SCHEMA_VERSION}.")
        try:
            doc = produce()
            text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        except Exception:                            # noqa: BLE001 — jamais de détail interne vers l'appelant
            return _tool_error(req_id, "Brief unavailable.")
        if len(text.encode("utf-8")) > BRIEF_MAX_BYTES:
            return _tool_error(req_id, "Brief too large.")
        return _result(req_id, {"content": [{"type": "text", "text": text}], "structuredContent": doc, "isError": False})
    return _error(req_id, METHOD_NOT_FOUND, "Method not found")


def handle_body(body: bytes, produce: Callable[[], dict], server_version: str = "") -> Tuple[int, Optional[bytes]]:
    """Corps HTTP d'un `POST /mcp` → (statut HTTP, corps JSON ou None). Pas de lot (retiré du protocole)."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return 400, json.dumps(_error(None, PARSE_ERROR, "Parse error")).encode("utf-8")
    if isinstance(payload, list):
        return 400, json.dumps(_error(None, INVALID_REQUEST, "Batches are not supported")).encode("utf-8")
    if isinstance(payload, dict) and "method" not in payload and ("result" in payload or "error" in payload):
        return 202, None                             # réponse du client à une requête : ce serveur n'en envoie jamais
    response = handle_rpc(payload, produce, server_version)
    if response is None:
        return 202, None
    return 200, json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
