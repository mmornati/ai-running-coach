#!/usr/bin/env python3
"""Serveur local du tableau de bord : lecture seule, 127.0.0.1 par défaut.

Sert `web/` (HTML/CSS/JS statiques) et une API JSON `/api/*` construite sur
l'index SQLite dérivé (`scripts/arc_index.py`). Rien n'est jamais écrit dans le
workspace hors de `.arc/` (la base elle-même), et rien n'est exposé hors de la
machine : le serveur écoute sur 127.0.0.1.

    arc_serve.py [--workspace DIR] [--port N] [--memory] [--db FICHIER] [--today AAAA-MM-JJ]
                 [--listen ADRESSE --allowed-host NOM ...]

`--listen` (ou ARC_DASHBOARD_LISTEN) n'existe que pour le conteneur Docker, qui
doit écouter sur son interface réseau pour que le reverse proxy l'atteigne. Il
exige `--allowed-host` (ou ARC_DASHBOARD_ALLOWED_HOSTS, séparés par des
virgules) : les noms sous lesquels le proxy présente le tableau de bord. Tout
autre en-tête Host reste refusé. Le tableau de bord n'a pas d'authentification
propre : hors de 127.0.0.1, il se place derrière un proxy qui en a une
(docs/dashboard/docker.md).

Le port vient de `[dashboard].port` (défaut 8765). S'il est pris, les 9 suivants
sont essayés ; `--port 0` laisse le système choisir (tests). La ligne
`URL: http://127.0.0.1:<port>/` est imprimée dès que le serveur écoute.

L'index est rafraîchi au démarrage puis, au plus toutes les 30 s, à la
première requête qui suit — un fichier écrit par un agent apparaît donc sans
relancer le serveur.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import statistics
import sys
import threading
import time
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_index as I  # noqa: E402
import arc_metrics as M  # noqa: E402
from coach_config import ConfigError  # noqa: E402

LOOPBACK = "127.0.0.1"                   # défaut : le tableau de bord ne sort pas de la machine
DEFAULT_PORT = 8765
WEB_ROOT = I.ENGINE / "web"
# Intervalle minimal entre deux réindexations (ARC_DASHBOARD_REFRESH_S pour les tests).
REFRESH_EVERY_S = float(os.environ.get("ARC_DASHBOARD_REFRESH_S", "30"))
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json",
    ".woff2": "font/woff2", ".ico": "image/x-icon",
}

# ---------------------------------------------------------------------------
# Markdown → HTML (sous-ensemble : ce que les agents écrivent)
# ---------------------------------------------------------------------------

_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2" rel="noopener noreferrer">\1</a>'),
]


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out


def _table(lines: list) -> str:
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
    head, body = rows[0], [r for r in rows[2:]] if len(rows) > 1 and set("".join(rows[1])) <= set("-: ") else rows[1:]
    parts = ["<table><thead><tr>", *(f"<th>{_inline(c)}</th>" for c in head), "</tr></thead><tbody>"]
    for row in body:
        parts.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def render_markdown(text: str) -> str:
    """Rendu sûr : tout le texte est échappé, seuls quelques motifs deviennent du HTML."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            fence, block = stripped[:3], []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                block.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(block)) + "</code></pre>")
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = min(len(heading.group(1)) + 1, 6)          # le h1 est le titre de la page
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if stripped.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue
        if stripped.startswith(">"):
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + render_markdown("\n".join(block)) + "</blockquote>")
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.", line))
            tag, items = ("ol" if ordered else "ul"), []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + f"</{tag}>")
            continue
        if not stripped or re.fullmatch(r"-{3,}|\*{3,}", stripped):
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|```|\s*([-*]|\d+\.)\s)", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(para)) + "</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------


class Store:
    """Connexion SQLite partagée entre les threads, sous verrou."""

    def __init__(self, workspace: Path, db=None, memory=False, today=None):
        self.workspace, self.today, self.db, self.memory = workspace, today, db, memory
        self.lock = threading.Lock()
        self.conn = I.open_db(workspace, db, memory)
        self.last_index = 0.0
        self.refresh(force=True)

    def refresh(self, force=False) -> None:
        with self.lock:
            if force or time.monotonic() - self.last_index > REFRESH_EVERY_S:
                try:
                    I.index_workspace(self.conn, self.workspace, self.today)
                except sqlite3.DatabaseError:
                    # Base remplacée ou corrompue par un autre processus : elle est
                    # dérivée, on rouvre et on réindexe.
                    self.conn.close()
                    self.conn = I.open_db(self.workspace, self.db, self.memory, rebuild=True)
                    I.index_workspace(self.conn, self.workspace, self.today)
                self.last_index = time.monotonic()

    def rows(self, sql: str, params=()) -> list:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()):
        found = self.rows(sql, params)
        return found[0] if found else None

    def backfill(self) -> list:
        with self.lock:
            return I.backfill_items(self.conn)

    def heat_acclimation(self, today: date, threshold_c: float) -> dict:
        """Réutilise `arc_index.heat_acclimation_today` (même SQL, même fenêtre)
        plutôt que de la dupliquer ici — voir aussi la CLI `heat-acclimation`."""
        with self.lock:
            return I.heat_acclimation_today(self.conn, {"heat_threshold_c": threshold_c}, today)

    def gear_mileage(self) -> dict:
        """Réutilise `arc_index.gear_mileage` (même SQL) — voir aussi la CLI `gear`."""
        with self.lock:
            return I.gear_mileage(self.conn)

    def meta(self, key: str):
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return json.loads(row["value"]) if row and row["value"] and row["value"][:1] in "[{" else (row or {}).get("value")


def _today(store: Store) -> date:
    return date.fromisoformat(store.meta("today") or date.today().isoformat())


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _strip(row, *keys):
    return {k: v for k, v in (row or {}).items() if k not in keys} if row else None


def api_heat_acclimation(store: Store, today: date, settings: dict, objective: Optional[dict]) -> dict:
    """Acclimatation à la chaleur (#38) : `/api/summary.heat_acclimation`.

    Jointure activité outdoor / météo du même jour, 14 j glissants — délègue à
    `arc_index.heat_acclimation_today` (même SQL que la CLI, pas de duplication) via
    `Store.heat_acclimation`. Voir `arc_metrics.ASSUMPTIONS["heat_acclimation"]`.

    `objective_forecast_hot` : `True`/`False` UNIQUEMENT si un fichier météo dont le
    `location` correspond explicitement à celui de la course existe pour
    `objective.race_date` (`pick_weather_strict` — SANS le raccourci « un seul
    fichier => il s'applique » de `pick_weather` : le fichier météo du jour est,
    par construction du skill `weather-forecast`, presque toujours celui du lieu
    d'ENTRAÎNEMENT, pas celui d'une course lointaine ; lui faire dire « la course
    sera chaude » serait un faux positif). `None` sinon : pas d'objectif avec date
    de course, pas de lieu de course renseigné, ou prévision pas encore disponible
    (souvent le cas tant que la course est à plus de quelques jours — `wttr.in` ne
    prévoit pas au-delà) — jamais confondu avec « pas chaud ». Sert aussi la règle
    d'affichage de la tuile « Aujourd'hui » (voir `web/js/app.js`).
    """
    threshold_c = settings.get("heat_threshold_c", M.HEAT_THRESHOLD_C_DEFAULT)
    result = store.heat_acclimation(today, threshold_c)
    objective_forecast_hot = None
    if objective and objective.get("race_date") and objective.get("location"):
        race_weather_rows = store.rows(
            "SELECT location, temp_max_c FROM weather_day WHERE date = ?", (objective["race_date"],))
        race_weather = M.pick_weather_strict(race_weather_rows, objective["location"])
        if race_weather is not None and race_weather.get("temp_max_c") is not None:
            objective_forecast_hot = race_weather["temp_max_c"] >= threshold_c
    result["objective_forecast_hot"] = objective_forecast_hot
    return result


def api_summary(store: Store, q: dict) -> dict:
    today = _today(store)
    settings = store.meta("settings") or {}
    objective = _strip(store.one("SELECT * FROM objective LIMIT 1"), "body_md")
    if objective and objective.get("race_date"):
        race = date.fromisoformat(objective["race_date"])
        objective["days_left"] = (race - today).days
        objective["weeks_left"] = round((race - today).days / 7, 1)
    athlete = _strip(store.one("SELECT * FROM athlete LIMIT 1"), "body_md", "source_path")
    latest = store.one("SELECT * FROM metric_day WHERE date <= ? ORDER BY date DESC LIMIT 1", (today.isoformat(),))
    health = _strip(store.one("SELECT * FROM health_day WHERE date <= ? ORDER BY date DESC LIMIT 1",
                              (today.isoformat(),)), "body_md", "data_json")
    files = store.rows("SELECT parsed_ok, COUNT(*) AS n FROM source_file WHERE kind IS NOT NULL "
                       "AND kind NOT IN ('athlete','objective') GROUP BY parsed_ok")
    incomplete = len(store.backfill())
    sleep_debt = None
    if settings.get("morning_check") == "full":
        # Dette de sommeil 7 j (#37), même porte que la ligne de base HRV : voir
        # ASSUMPTIONS["sleep_debt"]. Fenêtre EXACTEMENT `SLEEP_DEBT_WINDOW_DAYS` (7 j,
        # nuits d'hier à J-6 puisque la nuit de `today` n'est jamais encore mesurée) —
        # `sleep_debt_7d` ignore de toute façon toute date hors de sa propre fenêtre,
        # récupérer plus large ici n'aurait rien changé au résultat.
        sleep_rows = store.rows(
            "SELECT date, sleep_total_s FROM health_day WHERE date >= ? AND date <= ? "
            "AND sleep_total_s IS NOT NULL",
            ((today - timedelta(days=M.SLEEP_DEBT_WINDOW_DAYS - 1)).isoformat(), today.isoformat()))
        sleep_by_date = {r["date"]: r["sleep_total_s"] for r in sleep_rows}
        sleep_debt = M.sleep_debt_7d(sleep_by_date, today, I.athlete_sleep_need_s(athlete))
    heat_acclimation = api_heat_acclimation(store, today, settings, objective)
    return {
        "today": today.isoformat(), "settings": settings, "objective": objective, "athlete": athlete,
        "form": latest, "health": health, "sleep_debt": sleep_debt, "heat_acclimation": heat_acclimation,
        "gear": store.gear_mileage(),
        "files": {r["parsed_ok"]: r["n"] for r in files},
        "incomplete_files": incomplete, "assumptions": store.meta("assumptions"),
        "compliance_trend": api_compliance_trend(store, q),
        "counts": {
            "activities": (store.one("SELECT COUNT(*) AS n FROM activity") or {}).get("n", 0),
            "reports": (store.one("SELECT COUNT(*) AS n FROM report") or {}).get("n", 0),
            "nutrition": (store.one("SELECT COUNT(*) AS n FROM nutrition_day") or {}).get("n", 0),
        },
    }


def _days(q: dict, default: int, cap: int = 3650) -> int:
    try:
        return max(7, min(cap, int(q.get("days", [default])[0])))
    except ValueError:
        return default


def api_form(store: Store, q: dict) -> dict:
    today = _today(store)
    start = (today - timedelta(days=_days(q, 180) - 1)).isoformat()
    objective = store.one("SELECT race_date FROM objective LIMIT 1") or {}
    return {
        "series": store.rows("SELECT * FROM metric_day WHERE date >= ? AND date <= ? ORDER BY date",
                             (start, today.isoformat())),
        "race_date": objective.get("race_date"),
        "acwr_safe": list(M.ACWR_SAFE),
    }


def api_load(store: Store, q: dict) -> dict:
    weeks = max(4, min(104, int(q.get("weeks", [26])[0]) if q.get("weeks", [""])[0].isdigit() else 26))
    today = _today(store)
    first = _monday(today) - timedelta(weeks=weeks - 1)
    rows = store.rows("SELECT date, sport, distance_m, duration_s, elevation_gain_m, load FROM activity "
                      "WHERE date >= ? AND date <= ?", (first.isoformat(), today.isoformat()))
    buckets, week_rows = {}, {}
    for w in range(weeks):
        start = first + timedelta(weeks=w)
        buckets[start.isoformat()] = {"week_start": start.isoformat(), "distance_m": 0.0, "duration_s": 0.0,
                                      "elevation_m": 0.0, "effort_km": 0.0, "load": 0.0, "sessions": 0}
        week_rows[start.isoformat()] = []
    for row in rows:
        key = _monday(date.fromisoformat(row["date"])).isoformat()
        b = buckets.get(key)
        if not b:
            continue
        b["sessions"] += 1
        b["distance_m"] += row["distance_m"] or 0
        b["duration_s"] += row["duration_s"] or 0
        b["elevation_m"] += row["elevation_gain_m"] or 0
        b["load"] += row["load"] or 0
        week_rows[key].append(row)
    # ITRA km-effort, per week: `effort_km_week_total` sums the raw (unrounded) per-activity
    # values and rounds once — never the sum of values already rounded per activity.
    for key, b in buckets.items():
        b["effort_km"] = M.effort_km_week_total(week_rows[key])
    latest = store.one("SELECT monotony, strain FROM metric_day WHERE date <= ? ORDER BY date DESC LIMIT 1",
                       (today.isoformat(),)) or {}
    return {"weeks": list(buckets.values()), "monotony": latest.get("monotony"), "strain": latest.get("strain")}


def api_health(store: Store, q: dict) -> dict:
    today = _today(store)
    days = _days(q, 90)
    start_date = today - timedelta(days=days - 1)
    start = start_date.isoformat()
    settings = store.meta("settings") or {}
    mode = settings.get("morning_check", "full")
    # Toujours au moins 7 jours de plus pour que la médiane FC de repos (fenêtre j-1..j-7,
    # `range(1, 8)` plus bas) soit définie dès le premier point affiché, quel que soit le
    # mode — un lookback plus court ici décalait silencieusement cette médiane pour les
    # premiers jours de la série (constaté sur les goldens : `rhr_median7`/`rhr_delta`
    # différaient de ceux d'un lookback suffisant, alors que rien d'autre n'avait changé).
    # En mode "full" seulement, lookback bien plus large pour que la référence HRV 60 j
    # (qui se termine `HRV_LN_WINDOW_DAYS` j avant chaque point, voir `hrv_baseline_series`)
    # soit définie dès le premier point affiché ; ce calcul dérivé de l'HRV n'a pas sa
    # place en "minimal" ni "off" (voir ASSUMPTIONS["hrv_baseline"]).
    lookback = (M.HRV_LN_WINDOW_DAYS + M.HRV_REF_WINDOW_DAYS - 2) if mode == "full" else 7
    fetch_from = (today - timedelta(days=days + lookback)).isoformat()
    rows = store.rows("SELECT * FROM health_day WHERE date >= ? AND date <= ? ORDER BY date",
                      (fetch_from, today.isoformat()))
    by_date = {r["date"]: r for r in rows}
    hrv_baseline_by_date = {}
    sleep_debt_by_date = {}
    if mode == "full":
        hrv_by_date = {d: r["hrv_overnight_ms"] for d, r in by_date.items() if r["hrv_overnight_ms"] is not None}
        hrv_baseline_by_date = {p["date"]: p for p in M.hrv_baseline_series(hrv_by_date, start_date, today)}
        # Dette de sommeil 7 j (#37) : même porte que la ligne de base HRV ci-dessus
        # (rien hors "full", voir ASSUMPTIONS["sleep_debt"]). Besoin lu au profil
        # (`athlete.sleep_need_s`), sinon 7 h 30 par défaut — résolution partagée
        # avec `sleep_debt_today` de la CLI (`arc_index.athlete_sleep_need_s`).
        sleep_by_date = {d: r["sleep_total_s"] for d, r in by_date.items() if r["sleep_total_s"] is not None}
        need_s = I.athlete_sleep_need_s(store.one("SELECT sleep_need_s FROM athlete LIMIT 1"))
        sleep_debt_by_date = {p["date"]: p for p in M.sleep_debt_series(sleep_by_date, start_date, today, need_s)}
    series = []
    for i in range(days):
        day = date.fromisoformat(start) + timedelta(days=i)
        row = by_date.get(day.isoformat())
        window = [by_date[d]["resting_hr_bpm"] for d in
                  ((day - timedelta(days=k)).isoformat() for k in range(1, 8))
                  if d in by_date and by_date[d]["resting_hr_bpm"] is not None]
        median = statistics.median(window) if len(window) >= 3 else None
        point = {"date": day.isoformat(), "rhr_median7": median}
        if row:
            point.update({k: row[k] for k in (
                "hrv_overnight_ms", "hrv_baseline_low_ms", "hrv_baseline_high_ms", "hrv_status",
                "resting_hr_bpm", "readiness_score", "sleep_total_s", "sleep_score", "sleep_deep_s",
                "sleep_rem_s", "sleep_light_s", "verdict", "verdict_reason", "morning_check")})
            rhr = row["resting_hr_bpm"]
            point["rhr_delta"] = round(rhr - median, 1) if rhr is not None and median is not None else None
        baseline = hrv_baseline_by_date.get(day.isoformat())
        if baseline:
            point.update({k: v for k, v in baseline.items() if k != "date"})
        debt = sleep_debt_by_date.get(day.isoformat())
        if debt:
            point.update({k: v for k, v in debt.items() if k != "date"})
        series.append(point)
    return {"series": series, "morning_check": mode,
            "thresholds": {"rhr_warn": 5, "rhr_alert": 7,
                           "sleep_debt_warn_h": M.SLEEP_DEBT_WARN_S / 3600,
                           "sleep_debt_alert_h": M.SLEEP_DEBT_ALERT_S / 3600}}


def _week_sessions_and_activities(store: Store, monday: date) -> Tuple[list, list]:
    sunday = monday + timedelta(days=6)
    sessions = store.rows("SELECT * FROM planned_session WHERE date >= ? AND date <= ? ORDER BY date",
                          (monday.isoformat(), sunday.isoformat()))
    activities = store.rows("SELECT id, date, sport, name, distance_m, duration_s, elevation_gain_m, avg_hr_bpm, load "
                            "FROM activity WHERE date >= ? AND date <= ? ORDER BY date",
                            (monday.isoformat(), sunday.isoformat()))
    return sessions, activities


def _week_compliance(store: Store, monday: date, today: date) -> Optional[dict]:
    sessions, activities = _week_sessions_and_activities(store, monday)
    return M.week_compliance(sessions, activities, today)


def api_week(store: Store, q: dict) -> dict:
    today = _today(store)
    requested = q.get("start", [None])[0]
    try:
        monday = date.fromisoformat(requested) if requested else _monday(today)
    except ValueError:
        monday = _monday(today)
    monday = _monday(monday)
    sunday = monday + timedelta(days=6)
    week = store.one("SELECT * FROM week WHERE week_start = ?", (monday.isoformat(),))
    sessions, done = _week_sessions_and_activities(store, monday)
    weather = store.rows("SELECT date, location, category, best_slot, slot_reason, temp_max_c, wind_kmh, precip_mm "
                         "FROM weather_day WHERE date >= ? AND date <= ? ORDER BY date", (monday.isoformat(), sunday.isoformat()))
    weeks = [r["week_start"] for r in store.rows("SELECT DISTINCT week_start FROM week ORDER BY week_start")]
    return {
        "week_start": monday.isoformat(), "today": today.isoformat(),
        "week": _strip(week, "body_md"), "body_html": render_markdown(I.C.body_after_block(week["body_md"] or "")) if week else None,
        "sessions": sessions, "activities": done, "weather": weather, "known_weeks": weeks,
        "compliance": M.week_compliance(sessions, done, today),
    }


def api_compliance_trend(store: Store, q: dict, weeks: int = 4) -> list:
    """Conformité des `weeks` dernières semaines (la courante incluse), plus ancienne en premier.

    Une semaine sans plan (`week_compliance` rend `None`) apparaît quand même dans la
    liste, avec `compliance: null` : c'est ce qui permet à l'affichage de montrer un
    trou plutôt que de faire glisser silencieusement la fenêtre.
    """
    today = _today(store)
    current_monday = _monday(today)
    out = []
    for w in range(weeks - 1, -1, -1):
        monday = current_monday - timedelta(weeks=w)
        out.append({"week_start": monday.isoformat(), "compliance": _week_compliance(store, monday, today)})
    return out


def api_activities(store: Store, q: dict) -> dict:
    limit = min(500, int(q.get("limit", ["200"])[0])) if q.get("limit", ["200"])[0].isdigit() else 200
    return {"activities": store.rows(
        "SELECT id, date, sport, name, location, distance_m, duration_s, elevation_gain_m, avg_hr_bpm, "
        "max_hr_bpm, recovery_hr_bpm, te_aerobic, load, load_source, vo2max_est, arc_version, "
        "gear_id, sweat_rate_l_h "
        "FROM activity ORDER BY date DESC, id DESC LIMIT ?", (limit,))}


def api_activity(store: Store, activity_id: int):
    act = store.one("SELECT * FROM activity WHERE id = ?", (activity_id,))
    if not act:
        return None
    splits = store.rows("SELECT * FROM activity_split WHERE activity_id = ? ORDER BY km", (activity_id,))
    weather = _strip(store.one("SELECT * FROM weather_day WHERE date = ? LIMIT 1", (act["date"],)), "data_json")
    body = act.pop("body_md") or ""
    act.pop("data_json", None)
    act["missing_reason"] = json.loads(act["missing_reason"]) if act.get("missing_reason") else None
    return {"activity": act, "splits": splits, "weather": weather,
            "body_html": render_markdown(I.C.body_after_block(body))}


def api_performance(store: Store, q: dict) -> dict:
    today = _today(store)
    settings = store.meta("settings") or {}
    # Tous les jours de la fenêtre, valeurs nulles comprises : un trou dans les données
    # doit couper la courbe, pas la relier en ligne droite.
    series = store.rows("SELECT date, vo2max FROM metric_day WHERE date <= ? AND date >= ? ORDER BY date",
                        (today.isoformat(), (today - timedelta(days=365)).isoformat()))
    if not any(p["vo2max"] is not None for p in series):
        series = []
    last = next((p for p in reversed(series) if p["vo2max"] is not None), None)
    current = last["vo2max"] if last else None
    acts = []
    for act in store.rows("SELECT id, date, sport, name, distance_m FROM activity WHERE sport IN ('running', 'trail')"):
        act["splits"] = store.rows("SELECT km, distance_m, duration_s FROM activity_split WHERE activity_id = ?",
                                   (act["id"],))
        acts.append(act)
    records = M.best_efforts(acts)
    recent = M.best_efforts([a for a in acts if a["date"] >= (today - timedelta(days=90)).isoformat()])
    objective = store.one("SELECT distance_m, elevation_gain_m, target_time_s, name FROM objective LIMIT 1") or {}
    primary = settings.get("sport", "trail")
    return {
        "vo2max": series, "vo2max_current": current, "vo2max_date": last["date"] if last else None,
        "records": [{"km": k, **v} for k, v in sorted(records.items())],
        "predictions": M.predictions(current, recent, primary, objective.get("distance_m"),
                                     objective.get("elevation_gain_m") if primary == "trail" else None),
        "objective": objective, "sport": primary,
    }


def api_reports(store: Store, q: dict) -> dict:
    return {"reports": store.rows("SELECT source_path, date, report_type, title, period_start, period_end "
                                  "FROM report ORDER BY date DESC, source_path DESC")}


def api_report(store: Store, q: dict):
    path = q.get("path", [""])[0]
    row = store.one("SELECT * FROM report WHERE source_path = ?", (path,))
    if not row:
        return None
    return {**_strip(row, "body_md"), "body_html": render_markdown(I.C.body_after_block(row["body_md"] or ""))}


def api_calendar(store: Store, q: dict) -> dict:
    rows = store.rows("SELECT date, SUM(distance_m) AS distance_m, SUM(duration_s) AS duration_s, "
                      "SUM(elevation_gain_m) AS elevation_m, SUM(load) AS load, COUNT(*) AS sessions "
                      "FROM activity WHERE sport != 'rest' GROUP BY date ORDER BY date")
    years: dict = {}
    for row in rows:
        year = row["date"][:4]
        years.setdefault(year, []).append(row)
    cumulative = {}
    for year, days in years.items():
        total, points = 0.0, []
        for d in days:
            total += d["distance_m"] or 0
            points.append({"doy": date.fromisoformat(d["date"]).timetuple().tm_yday, "distance_m": total})
        cumulative[year] = points
    return {"days": rows, "cumulative": cumulative, "today": _today(store).isoformat()}


def api_nutrition(store: Store, q: dict) -> dict:
    today = _today(store)
    days = _days(q, 60)
    start_date = today - timedelta(days=days - 1)
    start = start_date.isoformat()
    rows = store.rows("SELECT date, intake_kcal, burned_kcal, carbs_g, protein_g, fat_g, hydration_ml, "
                      "weight_kg, target_weight_kg FROM nutrition_day WHERE date >= ? ORDER BY date", (start,))
    # Tendance du poids (#36), additive : `days` (table existante) n'est pas modifié — la
    # série dédiée `weight_series` et le résumé `weight` sont calculés à part, sur une
    # fenêtre élargie en amont pour que la moyenne 7 j / pente 4 semaines du premier point
    # affiché soient déjà définies (même motif que le lookback HRV de `api_health`).
    lookback = max(M.WEIGHT_AVG_WINDOW_DAYS, M.WEIGHT_SLOPE_WINDOW_DAYS) - 1
    fetch_from = (start_date - timedelta(days=lookback)).isoformat()
    # Doublon même jour (deux fichiers santé, ou deux fichiers nutrition, pour la même
    # date) : le contrat n'a pas d'heure de mesure, donc pas de règle « le plus récent »
    # possible. Règle documentée (`ASSUMPTIONS["weight_merge"]`) : le `source_path` le
    # plus grand par ordre alphabétique gagne — appliquée ici en ordonnant `ORDER BY
    # date, source_path` puis en laissant le dict `{date: valeur}` écraser avec la
    # DERNIÈRE ligne itérée pour une date donnée (jamais l'ordre arbitraire que rendrait
    # SQLite sans `ORDER BY`).
    nutrition_weight_rows = store.rows(
        "SELECT date, weight_kg FROM nutrition_day WHERE date >= ? AND date <= ? ORDER BY date, source_path",
        (fetch_from, today.isoformat()))
    health_weight_rows = store.rows(
        "SELECT date, weight_kg FROM health_day WHERE date >= ? AND date <= ? ORDER BY date, source_path",
        (fetch_from, today.isoformat()))
    nutrition_weight_by_date = {r["date"]: r["weight_kg"] for r in nutrition_weight_rows if r["weight_kg"] is not None}
    health_weight_by_date = {r["date"]: r["weight_kg"] for r in health_weight_rows if r["weight_kg"] is not None}
    merged_by_date = {}
    for d in set(nutrition_weight_by_date) | set(health_weight_by_date):
        v = M.merge_weight_kg(health_weight_by_date.get(d), nutrition_weight_by_date.get(d))
        if v is not None:
            merged_by_date[d] = v
    weight_points = M.weight_avg7_series(merged_by_date, start_date, today)
    # Cible la plus récente connue à ce jour (le contrat ne la porte que sur `nutrition`) —
    # pas bornée à `fetch_from` : une cible fixée il y a longtemps et jamais changée reste
    # valide. Même règle de doublon que ci-dessus, dans le même sens (date la plus récente
    # d'abord, puis `source_path` le plus grand par ordre alphabétique) : `DESC` sur les
    # deux colonnes plutôt qu'un simple `ORDER BY date DESC` qui laisserait SQLite décider
    # arbitrairement entre deux fichiers nutrition de la même date.
    target_row = store.one("SELECT target_weight_kg FROM nutrition_day WHERE date <= ? "
                           "AND target_weight_kg IS NOT NULL ORDER BY date DESC, source_path DESC LIMIT 1",
                           (today.isoformat(),))
    target_weight_kg = target_row.get("target_weight_kg") if target_row else None
    # Moyenne 7 j et écart à la cible : valeur DU JOUR (aujourd'hui) seulement, jamais la
    # dernière valeur non nulle trouvée n'importe où dans la fenêtre affichée — sans quoi
    # une moyenne vieille de plusieurs semaines (plus aucune pesée récente) s'afficherait
    # comme si elle était d'aujourd'hui. `avg7_date` porte la date réellement utilisée :
    # toujours `today` ici, mais nommée explicitement pour que l'appelant (l'UI) l'affiche
    # plutôt que de supposer qu'« avg7_kg » est forcément à jour.
    today_point = next((p for p in weight_points if p["date"] == today.isoformat()), None)
    latest_avg7 = today_point["weight_avg7_kg"] if today_point else None
    slope = M.weight_slope_kg_per_week(merged_by_date, today)
    return {
        "days": rows,
        "weight_series": [{"date": p["date"], "weight_kg_merged": p["weight_kg"], "weight_avg7_kg": p["weight_avg7_kg"]}
                          for p in weight_points],
        "weight": {
            "avg7_kg": latest_avg7, "avg7_date": today.isoformat() if latest_avg7 is not None else None,
            "target_kg": target_weight_kg,
            "gap_kg": M.weight_target_gap_kg(latest_avg7, target_weight_kg),
            "slope_kg_per_week": slope,
        },
    }


def api_fueling(store: Store, q: dict) -> dict:
    """Glucides/h et taux de sudation sur les sorties longues (#41) : `/api/fueling`.

    Additive : ne touche à aucune route existante. Délègue à `M.fueling_trend` sur les
    sorties longues (`duration_s` > `M.LONG_RUN_MIN_DURATION_S`) de la fenêtre demandée
    (`weeks`, défaut `M.FUELING_TREND_WEEKS`) — voir `M.ASSUMPTIONS["fueling"]`.
    """
    today = _today(store)
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else M.FUELING_TREND_WEEKS
    weeks = max(4, min(52, weeks))
    rows = store.rows(
        "SELECT date, sport, distance_m, duration_s, carbs_g, sweat_rate_l_h FROM activity "
        "WHERE duration_s > ? AND sport IN "
        f"({', '.join('?' for _ in M.FUELING_SPORTS)})",
        (M.LONG_RUN_MIN_DURATION_S, *M.FUELING_SPORTS))
    result = M.fueling_trend(rows, today, weeks)
    result["carbs_ceiling_g_h"] = M.fueling_carbs_ceiling(result["max_carbs_per_hour_g"])
    result["margin_g_h"] = M.FUELING_MAX_MARGIN_G_H
    result["target_band_g_h"] = list(M.FUELING_TARGET_BAND_G_H)
    return result


def api_files(store: Store, q: dict) -> dict:
    return {"items": store.backfill()}


ROUTES = {
    "/api/summary": api_summary, "/api/form": api_form, "/api/load": api_load,
    "/api/health": api_health, "/api/week": api_week, "/api/activities": api_activities,
    "/api/performance": api_performance, "/api/reports": api_reports, "/api/report": api_report,
    "/api/calendar": api_calendar, "/api/nutrition": api_nutrition, "/api/fueling": api_fueling,
    "/api/files": api_files,
}

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "arc-dashboard"
    store: Store = None           # posé par serve()
    allowed_hosts: set = set()

    def log_message(self, fmt, *args):         # silencieux : c'est un outil local
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
                         "font-src https://fonts.gstatic.com; img-src 'self' data:; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        # Protection contre le DNS rebinding : une page tierce qui ferait résoudre
        # son domaine vers 127.0.0.1 enverrait son propre Host.
        host = (self.headers.get("Host") or "").lower()
        return host in self.allowed_hosts or host.rsplit(":", 1)[0] in self.allowed_hosts

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            self._json(HTTPStatus.FORBIDDEN, {"error": "hôte non autorisé"})
            return
        url = urlparse(self.path)
        if url.path == "/healthz":              # sonde du conteneur : ne réindexe pas
            self._json(HTTPStatus.OK, {"status": "ok"})
        elif url.path.startswith("/api/"):
            self._api(url)
        else:
            self._static(url.path)

    def do_POST(self):          # lecture seule
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "lecture seule"})

    do_PUT = do_DELETE = do_PATCH = do_POST

    def _api(self, url) -> None:
        q = parse_qs(url.query)
        try:
            self.store.refresh()
            match = re.fullmatch(r"/api/activity/(\d+)", url.path)
            if match:
                payload = api_activity(self.store, int(match.group(1)))
            elif url.path in ROUTES:
                payload = ROUTES[url.path](self.store, q)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "route inconnue"})
                return
        except Exception as exc:                  # une erreur de données ne doit pas tuer le serveur
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if payload is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})
        else:
            self._json(HTTPStatus.OK, payload)

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_ROOT / rel).resolve()
        root = WEB_ROOT.resolve()
        if root not in target.parents or not target.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"introuvable", "text/plain; charset=utf-8")
            return
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, target.read_bytes(), ctype)


def bind(port: int, tries: int = 10, listen: str = LOOPBACK) -> ThreadingHTTPServer:
    last = None
    candidates = [0] if port == 0 else range(port, port + tries)
    for candidate in candidates:
        try:
            return ThreadingHTTPServer((listen, candidate), Handler)
        except OSError as exc:
            last = exc
    raise ConfigError(f"aucun port libre entre {port} et {port + tries - 1} sur {listen} ({last}). Essayez --port.")


def host_allowlist(port: int, extra=()) -> set:
    """En-têtes Host acceptés : la boucle locale, plus les noms publics déclarés.

    Un nom déclaré est accepté seul (derrière un proxy, `coach.example.org`) ou
    suivi d'un port (`coach.example.org:8443`) ; la casse est ignorée.
    """
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    for name in extra:
        hosts.add(name.strip().lower())
    return hosts


def check_exposure(listen: str, extra_hosts) -> None:
    """Hors de la boucle locale, sans nom public déclaré, rien ne serait servi."""
    if listen not in (LOOPBACK, "localhost") and not extra_hosts:
        raise ConfigError(
            f"--listen {listen} sans --allowed-host : toute requête venue du réseau serait refusée. "
            "Déclarez le nom public (ARC_DASHBOARD_ALLOWED_HOSTS), derrière un proxy authentifié.")


def serve(workspace: Path, port: int, db=None, memory=False, today=None,
          listen: str = LOOPBACK, extra_hosts=()) -> None:
    check_exposure(listen, extra_hosts)
    Handler.store = Store(workspace, db, memory, today)
    httpd = bind(port, listen=listen)
    actual = httpd.server_address[1]
    Handler.allowed_hosts = host_allowlist(actual, extra_hosts)
    print(f"URL: http://127.0.0.1:{actual}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def configured_port(workspace: Path) -> int:
    value = I.load_config(workspace).get("dashboard", {}).get("port", DEFAULT_PORT)
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"[dashboard].port : entier attendu, « {value} » trouvé.")
    if not 0 <= port <= 65535:
        raise ConfigError(f"[dashboard].port : {port} hors de 0-65535.")
    return port


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace")
    parser.add_argument("--port", type=int)
    parser.add_argument("--db")
    parser.add_argument("--memory", action="store_true", help="base en mémoire, rien sur disque")
    parser.add_argument("--today", help="date de référence AAAA-MM-JJ (démonstrations, tests)")
    parser.add_argument("--listen", default=os.environ.get("ARC_DASHBOARD_LISTEN") or LOOPBACK,
                        help="adresse d'écoute (conteneur uniquement ; défaut 127.0.0.1)")
    parser.add_argument("--allowed-host", action="append", dest="allowed_hosts",
                        default=[h for h in os.environ.get("ARC_DASHBOARD_ALLOWED_HOSTS", "").split(",") if h.strip()],
                        help="nom public accepté dans l'en-tête Host (répétable)")
    args = parser.parse_args(argv)
    workspace = I.workspace_root(args.workspace)
    port = args.port if args.port is not None else configured_port(workspace)
    serve(workspace, port, args.db, args.memory, args.today, args.listen, args.allowed_hosts)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(1)
