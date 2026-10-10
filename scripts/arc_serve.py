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

L'index est construit en arrière-plan dès le démarrage (le serveur écoute
aussitôt ; les requêtes API attendent la fin de ce premier passage), puis
rafraîchi toutes les 30 s par ce même fil — jamais dans une requête : un fichier
écrit par un agent apparaît donc sans relancer le serveur, et aucune page
n'attend une réindexation. Un passage sans changement ne recalcule pas les
métriques ; un passage avec changement ne recalcule que les séances touchées
(`arc_index.MetricsCache`).

Les fichiers statiques sont revalidés par ETag (`304`), et toute réponse
textuelle est compressée (gzip) quand le client l'accepte.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import html
import json
import os
import re
import socketserver
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
from urllib.parse import parse_qs, quote, urlparse, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_block_timeline as BT  # noqa: E402
import arc_guardrails as G  # noqa: E402
import arc_index as I  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_roadbook as RB  # noqa: E402
from coach_config import ConfigError  # noqa: E402

LOOPBACK = "127.0.0.1"                   # défaut : le tableau de bord ne sort pas de la machine
DEFAULT_PORT = 8765
WEB_ROOT = I.ENGINE / "web"
# Intervalle entre deux réindexations (ARC_DASHBOARD_REFRESH_S pour les tests).
REFRESH_EVERY_S = float(os.environ.get("ARC_DASHBOARD_REFRESH_S", "30"))
# Plancher du fil de rafraîchissement : `ARC_DASHBOARD_REFRESH_S=0` (tests) ne doit
# pas devenir une boucle active.
MIN_BACKGROUND_INTERVAL_S = 0.2
# Attente maximale d'une requête API pendant le tout premier index.
READY_TIMEOUT_S = float(os.environ.get("ARC_DASHBOARD_READY_TIMEOUT_S", "120"))
# En dessous, la compression coûte plus qu'elle ne rapporte.
GZIP_MIN_BYTES = 1024
COMPRESSIBLE = ("text/", "application/json", "image/svg+xml")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json",
    ".woff2": "font/woff2", ".ico": "image/x-icon",
}
# Identifiant STABLE d'une décision (#55) exposé par `/api/decision/<id>` : le nom de
# fichier SANS son extension (`planning/<id>.md`), jamais le chemin absolu du
# workspace. Motif volontairement plus strict que `arc_index._DECISION_FILENAME_RE`
# (qui autorise `[^/]+` avant `.md`) : AUCUN point toléré dans le `<slug>` — bloque
# par construction une tentative de remontée de répertoire (`..`) glissée dans l'id
# d'URL, sans avoir à la détecter explicitement (`/api/decision/../../etc/passwd`
# ne correspond simplement jamais à ce motif).
DECISION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_decision_[^/.]+$")
# Photos d'inspection de chaussures (#135) servies par `/media/gear-photo?path=gear/photos/…` : SEULS
# des rasters (jamais SVG — un SVG servi de notre origine exécuterait du script), SEULEMENT sous
# `<workspace>/gear/photos/`, SEULEMENT si une inspection indexée cite ce chemin exact dans `photos`.
GEAR_PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
GEAR_PHOTO_MAX_BYTES = 15 * 1024 * 1024
GUARDRAILS_DOC_URL = "https://mmornati.github.io/ai-running-coach/guardrails/#les-sept-regles"

# ---------------------------------------------------------------------------
# Markdown → HTML (sous-ensemble : ce que les agents écrivent)
# ---------------------------------------------------------------------------

# Le groupe d'URL exclut EXPLICITEMENT `"'<>` (#55, revue de code) — en plus,
# jamais à la place, de `quote=True` ci-dessous : la classe de caractères est
# la protection *structurelle* (même si un futur appel oubliait d'échapper
# avant substitution, un lien `[texte](https://a"onmouseover=...)` ne
# correspondrait simplement plus à ce motif), `html.escape(quote=True)` est le
# filet supplémentaire sur tout le reste du texte (dont `\1`, le libellé du
# lien, jamais nettoyé par la classe de caractères de l'URL).
_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s\"'<>]+)\)"), r'<a href="\2" rel="noopener noreferrer">\1</a>'),
]


def _inline(text: str) -> str:
    # `quote=True` (#55, revue de code — était `quote=False`) : sans lui, un
    # `"` ou `'` littéral du texte source atterrissait tel quel dans l'attribut
    # `href="\2"` généré ci-dessus, permettant à un lien malformé de sortir de
    # l'attribut (`[texte](https://a" onmouseover="...")`) — la CSP du serveur
    # bloque déjà l'exécution d'un script injecté, mais l'attribut lui-même ne
    # doit jamais pouvoir s'échapper. Affecte aussi les autres appelants de
    # `render_markdown` (`/api/report`, `/api/week`, `/api/decision/<id>`).
    out = html.escape(text, quote=True)
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


_LEADING_H1_RE = re.compile(r"^#[ \t]+[^\n]*\n+")


def strip_leading_heading(text: str) -> str:
    """Retire le titre `# ...` de tête d'un corps de fichier (#55, nit de revue),
    s'il en ouvre le texte — jamais un `#` plus loin dans le corps. Utilisé
    seulement là où une page affiche déjà ce même titre ailleurs (le résumé de
    la décision, dans `header()`) : `render_markdown` l'aurait sinon rendu en
    `<h2>` redondant juste sous le titre de page. `/api/report`/`/api/week`
    n'appellent PAS cette fonction : leur titre de page (`report.title`) et le
    `#` de tête de leur corps ne sont pas garantis identiques au même degré
    (fichiers plus anciens, titres reformulés) — un retrait aveugle y risquerait
    de faire disparaître un titre qui n'est PAS un doublon."""
    return _LEADING_H1_RE.sub("", text, count=1)


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------


class Store:
    """Connexion SQLite partagée entre les threads, sous verrou.

    Par défaut (tests, usages en bibliothèque), le premier index est construit dans le
    constructeur. `background=True` (le serveur) le laisse à `start_background`, dont
    le fil réindexe ensuite à intervalle fixe : aucune requête ne réindexe jamais.
    """

    def __init__(self, workspace: Path, db=None, memory=False, today=None, background=False):
        self.workspace, self.today, self.db, self.memory = workspace, today, db, memory
        self.lock = threading.Lock()
        self.conn = I.open_db(workspace, db, memory)
        self.last_index = 0.0
        self.last_counts: dict = {}
        self.metrics_cache = I.MetricsCache()
        # Courbes allure-durée par séance (#169), voir `arc_index.pace_curve(curve_cache=...)`.
        self.pace_curve_cache: dict = {}
        self.ready = threading.Event()
        self.background = background
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if not background:
            self.refresh(force=True)

    def refresh(self, force=False) -> None:
        with self.lock:
            if force or time.monotonic() - self.last_index > REFRESH_EVERY_S:
                try:
                    counts = I.index_workspace(self.conn, self.workspace, self.today, self.metrics_cache)
                except sqlite3.DatabaseError:
                    # Base remplacée ou corrompue par un autre processus : elle est
                    # dérivée, on rouvre et on réindexe — sans rien reprendre du cache,
                    # les échantillons vont être réingérés.
                    self.conn.close()
                    self.metrics_cache.clear()
                    self.pace_curve_cache.clear()
                    self.conn = I.open_db(self.workspace, self.db, self.memory, rebuild=True)
                    counts = I.index_workspace(self.conn, self.workspace, self.today, self.metrics_cache)
                self.last_counts = counts
                self.last_index = time.monotonic()
        self.ready.set()

    def start_background(self, interval: float = REFRESH_EVERY_S) -> None:
        """Premier index puis réindexation toutes les `interval` s, dans un fil démon."""
        self._thread = threading.Thread(target=self._loop, args=(max(interval, MIN_BACKGROUND_INTERVAL_S),),
                                        name="arc-index", daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)

    def _loop(self, interval: float) -> None:
        while not self._stop.is_set():
            try:
                self.refresh(force=True)
            except Exception as exc:  # noqa: BLE001 — le fil ne doit jamais mourir
                print(f"avertissement : réindexation impossible : {type(exc).__name__}: {exc}", file=sys.stderr)
            finally:
                # Même en échec : les requêtes servent alors l'état précédent (ou une
                # base vide) plutôt que d'attendre indéfiniment.
                self.ready.set()
            self._stop.wait(interval)

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        return self.ready.wait(READY_TIMEOUT_S if timeout is None else timeout)

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

    def gear_mileage(self, today: date) -> dict:
        """Réutilise `arc_index.gear_mileage` (même SQL) — voir aussi la CLI `gear`.
        `today` : jour de référence de la prévision de retraite (#132)."""
        with self.lock:
            return I.gear_mileage(self.conn, today)

    def equipment_usage(self, today: date) -> dict:
        """Réutilise `arc_index.equipment_usage` (#134, matériel hors chaussures) — voir aussi la
        CLI `equipment`. `gear_mileage` (chaussures) reste inchangé."""
        with self.lock:
            return I.equipment_usage(self.conn, today)
    def gear_inspections(self, today: date) -> dict:
        """Réutilise `arc_index.gear_inspections` (#135) — voir aussi la CLI `inspections`."""
        with self.lock:
            return I.gear_inspections(self.conn, None, today)

    def gait(self, today: date, weeks: int) -> dict:
        """Réutilise `arc_index.gait_summary` (#151) — voir aussi la CLI `gait-summary`."""
        with self.lock:
            return I.gait_summary(self.conn, today, weeks)

    def altitude_exposure(self, today: date, days: Optional[int]) -> dict:
        """Réutilise `arc_index.altitude_exposure` (#185) — voir aussi la CLI `altitude-exposure`."""
        with self.lock:
            return I.altitude_exposure(self.conn, today, days)

    def pace_curve(self, today: date, days: Optional[int], lt_speed_ms: Optional[float]) -> dict:
        """Réutilise `arc_index.pace_curve` (#169) — voir aussi la CLI `pace-curve`."""
        with self.lock:
            return I.pace_curve(self.conn, today, days, lt_speed_ms, curve_cache=self.pace_curve_cache)

    def decision_effects(self, today: date, days: Optional[int], trigger: Optional[str]) -> dict:
        """Réutilise `arc_index.decision_effects` (#175) — voir aussi la CLI `decision-effects`."""
        with self.lock:
            return I.decision_effects(self.conn, today, days, trigger)

    def gear_detail(self, gear_id: str, today: date):
        """Réutilise `arc_index.gear_detail` (#147) — fiche d'une paire/d'un objet, `None` si inconnu."""
        with self.lock:
            return I.gear_detail(self.conn, gear_id, today)

    def gear_of_activity(self, activity_id: int, today: date) -> dict:
        """Réutilise `arc_index.gear_of_activity` (#147) — chaussure attribuée + équipement de la séance."""
        with self.lock:
            return I.gear_of_activity(self.conn, activity_id, today)

    def track(self, activity_id: int, max_points: int):
        """Réutilise `arc_index.track` — trace GPS et flux de la page séance (`None` si inconnue)."""
        with self.lock:
            return I.track(self.conn, activity_id, max_points)

    def session_gait(self, activity_id: int):
        """Réutilise `arc_index.session_gait` (#151) — dynamique de course d'une séance."""
        with self.lock:
            return I.session_gait(self.conn, activity_id)

    def performance_index(self, today: date) -> dict:
        """Réutilise `arc_index.performance_index` (#62) — voir aussi la CLI
        `performance-index`. `today` : recalcule l'avertissement de date
        future à CHAQUE appel (revue de code #109, 2e tour) — jamais une
        valeur stockée qui resterait périmée d'un jour sur l'autre."""
        with self.lock:
            return I.performance_index(self.conn, today)

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
    # Contexte du cycle (#166) retiré : aucune carte ne l'affiche (docs/cycle-menstruel.md), une
    # donnée aussi personnelle ne sort donc pas de l'index par l'API — et la réponse reste
    # identique à celle d'avant #166 pour qui n'a rien activé.
    health = _strip(store.one("SELECT * FROM health_day WHERE date <= ? ORDER BY date DESC LIMIT 1",
                              (today.isoformat(),)), "body_md", "data_json",
                    "cycle_phase", "cycle_day", "cycle_source")
    files = store.rows("SELECT parsed_ok, COUNT(*) AS n FROM source_file WHERE kind IS NOT NULL "
                       "AND kind NOT IN ('athlete','objective') GROUP BY parsed_ok")
    # `collision` (#69, revue de code) : un item de `backfill()` peut être un
    # fichier DÉJÀ VALIDE au contrat, seulement éclipsé pour une semaine par un
    # autre fichier (voir `arc_index.backfill_items`) — ce n'est pas une dette
    # de contrat, `incomplete_files` (nav « N fichier(s) hors contrat ») ne doit
    # donc JAMAIS le compter : un fichier parfaitement valide se retrouverait
    # sinon étiqueté « hors contrat ». Compté à part (`week_collisions_count`),
    # pour la même visibilité sans le mauvais libellé.
    backfill_items = store.backfill()
    incomplete = sum(1 for i in backfill_items if not i.get("collision"))
    week_collisions_count = sum(1 for i in backfill_items if i.get("collision"))
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
        "gear": store.gear_mileage(today),
        "equipment": store.equipment_usage(today),
        "gear_inspections": store.gear_inspections(today),
        "gear_ignored": store.rows("SELECT gear_id, name FROM gear WHERE ignored = 1 ORDER BY name, gear_id"),
        "performance_index": store.performance_index(today),
        "files": {r["parsed_ok"]: r["n"] for r in files},
        "incomplete_files": incomplete, "week_collisions_count": week_collisions_count,
        "compliance_trend": api_compliance_trend(store, q),
        "counts": {
            "activities": (store.one("SELECT COUNT(*) AS n FROM activity") or {}).get("n", 0),
            "reports": (store.one("SELECT COUNT(*) AS n FROM report") or {}).get("n", 0),
            "nutrition": (store.one("SELECT COUNT(*) AS n FROM nutrition_day") or {}).get("n", 0),
        },
    }


def api_pace_curve(store: Store, q: dict) -> dict:
    """Courbe allure-durée GAP, vitesse critique CS et D′ (#169) : `/api/pace-curve?days=N&lt_speed_ms=V`.
    Additive : ne touche à aucune route existante. Délègue à `arc_index.pace_curve` (mêmes chiffres que
    la CLI `pace-curve`) ; `days` (1 à 730, défaut 365) = profondeur de la tendance. Refus explicite et
    motivé quand les données ne permettent pas l'ajustement — jamais une CS inventée. Aucune donnée GPS
    ni de santé."""
    days_raw = q.get("days", [""])[0]
    days = max(1, min(730, int(days_raw))) if days_raw.isdigit() else None
    try:
        lt = float(q.get("lt_speed_ms", [""])[0])
    except ValueError:
        lt = None
    return store.pace_curve(_today(store), days, lt)


def api_gait(store: Store, q: dict) -> dict:
    """Synthèse « Foulée » (#151) : `/api/gait?weeks=N` (défaut 26, 1 à 104). Additive : ne touche à
    aucune route existante. Délègue à `arc_index.gait_summary` (mêmes chiffres que la CLI
    `gait-summary`) — dynamique de course mesurée, indices d'inspection, `confidence`,
    `contradictions`. Jamais un diagnostic ; aucune donnée GPS ni de santé du matin."""
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else I.GAIT_DEFAULT_WEEKS
    return store.gait(_today(store), max(1, min(104, weeks)))


def api_decision_effects(store: Store, q: dict) -> dict:
    """Effet des décisions (#175) : `/api/decision-effects?days=N&trigger=T` (défaut 180 j, 1 à 3650).
    Additive. Délègue à `arc_index.decision_effects` (mêmes chiffres que la CLI) — effets DÉRIVÉS, jamais
    stockés ; corrélation, pas causalité (`caveat`)."""
    days_raw = q.get("days", [""])[0]
    days = max(1, min(3650, int(days_raw))) if days_raw.isdigit() else None
    trigger = q.get("trigger", [""])[0] or None
    if trigger and trigger not in I.C.DECISION_TRIGGER:
        trigger = None
    return store.decision_effects(_today(store), days, trigger)


def api_altitude_exposure(store: Store, q: dict) -> dict:
    """Exposition à l'altitude (#185) : `/api/altitude-exposure[?days=N]` (défaut : fenêtres 14 et
    28 j). Additive. Délègue à `arc_index.altitude_exposure` (mêmes chiffres que la CLI) ; aucune
    coordonnée GPS ni donnée de santé."""
    raw = q.get("days", [""])[0]
    return store.altitude_exposure(_today(store), max(1, min(365, int(raw))) if raw.isdigit() else None)


def api_assumptions(store: Store, q: dict) -> dict:
    """Hypothèses des métriques (≈ 100 Ko de texte) : route à part plutôt que dans
    `/api/summary`, chargé à chaque ouverture — seule la vue Performance les affiche."""
    return {"assumptions": store.meta("assumptions")}


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
    conf = store.meta("settings") or {}
    with store.lock:
        polarisation = I.weekly_polarisation(store.conn, weeks, today)
        # Raison explicite quand AUCUNE zone n'est calculable (profil incomplet, ou
        # méthode forcée par [athlete].hr_zones mais champ manquant) : sans elle, la
        # section « Polarisation 80/20 » disparaîtrait silencieusement côté UI plutôt
        # que d'en expliquer la cause (revue de code #43, round 3) — `None` ici veut
        # dire « des zones sont calculables », pas nécessairement que la fenêtre a des
        # données (une semaine sans échantillons FIT reste `polarisation: null`, sans
        # rapport avec cette raison globale).
        hr_zones_reason = I.athlete_hr_zone_resolution(store.conn, conf)["reason"]
    return {"weeks": list(buckets.values()), "monotony": latest.get("monotony"), "strain": latest.get("strain"),
            "polarisation_weeks": polarisation, "hr_zones_reason": hr_zones_reason}


def api_load_forecast(store: Store, q: dict) -> dict:
    """Projection de charge sur le bloc (#172) : `/api/load-forecast`. Délègue à `arc_index.load_forecast`
    (même fonction que la CLI) ; `until=AAAA-MM-JJ` optionnel. Estimation à partir du planifié, jamais une mesure."""
    until = q.get("until", [""])[0] or None
    today = _today(store)
    try:
        with store.lock:
            return I.load_forecast(store.conn, today, until)
    except I.ConfigError as exc:
        return {"status": "invalid_until", "reason": str(exc)}


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
    # `shadowed = 0` (#69, plan multi-semaines) : exclut les séances d'un fichier
    # écarté par une collision de `week_start` (voir `arc_index._mark_week_shadowing`)
    # — sinon une même semaine décrite deux fois (fichier dédié + plan multi-semaines
    # qui la recouvre) doublerait ses séances ici.
    sessions = store.rows("SELECT * FROM planned_session WHERE date >= ? AND date <= ? "
                          "AND shadowed = 0 ORDER BY date",
                          (monday.isoformat(), sunday.isoformat()))
    activities = store.rows("SELECT id, date, sport, name, distance_m, duration_s, elevation_gain_m, avg_hr_bpm, load "
                            "FROM activity WHERE date >= ? AND date <= ? ORDER BY date",
                            (monday.isoformat(), sunday.isoformat()))
    # `shadowed` déjà filtré (toujours 0 ici) : ne sert à rien côté client, on ne
    # le sérialise pas (revue de code #69, nit — évite un champ figé à 0 dans
    # chaque séance de `/api/week`, et un diff de golden qui n'apporterait rien).
    sessions = [_strip(s, "shadowed") for s in sessions]
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
    # `shadowed = 0` (#69) : même raison que `_week_sessions_and_activities` ci-dessus
    # — une semaine éclipsée par une collision de `week_start` ne doit jamais être
    # servie à la place de celle qui fait foi.
    week = store.one("SELECT * FROM week WHERE week_start = ? AND shadowed = 0", (monday.isoformat(),))
    sessions, done = _week_sessions_and_activities(store, monday)
    weather = store.rows("SELECT date, location, category, best_slot, slot_reason, temp_max_c, wind_kmh, precip_mm "
                         "FROM weather_day WHERE date >= ? AND date <= ? ORDER BY date", (monday.isoformat(), sunday.isoformat()))
    weeks = [r["week_start"] for r in store.rows(
        "SELECT DISTINCT week_start FROM week WHERE shadowed = 0 ORDER BY week_start")]
    return {
        "week_start": monday.isoformat(), "today": today.isoformat(),
        "week": _strip(week, "body_md", "shadowed"), "body_html": render_markdown(I.C.body_after_block(week["body_md"] or "")) if week else None,
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
    # Plafond large : la vue Séances charge tout l'historique d'un coup et pagine
    # côté navigateur — 500 tronquait silencieusement deux ans d'entraînement.
    limit = min(10000, int(q.get("limit", ["200"])[0])) if q.get("limit", ["200"])[0].isdigit() else 200
    return {"activities": store.rows(
        "SELECT id, date, sport, name, location, distance_m, duration_s, elevation_gain_m, avg_hr_bpm, "
        "max_hr_bpm, recovery_hr_bpm, te_aerobic, load, load_source, vo2max_est, arc_version, "
        "gear_id, sweat_rate_l_h, gap_pace_s_km, decoupling_pct, ef_whole "
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
            "hr_zones": api_activity_hr_zones(store, activity_id),
            "climbs": api_activity_climbs(store, activity_id),
            "descent": api_activity_descent(store, activity_id),
            "durability": api_activity_durability(store, activity_id),
            "energy": api_activity_energy(store, activity_id),
            "gear": store.gear_of_activity(activity_id, _today(store)),
            "gait": store.session_gait(activity_id),
            "pain": _pain_of_day(store, act["date"]),
            "body_html": render_markdown(I.C.body_after_block(body))}


def _pain_of_day(store: Store, day: str) -> list:
    """Douleurs déclarées le jour de la séance (#57/#67, `pain` du fichier santé, `/log`) : la
    liste `{location, score}` telle que validée par le contrat, vide si rien n'est déclaré."""
    row = store.one("SELECT data_json FROM health_day WHERE date = ? LIMIT 1", (day,))
    try:
        pain = json.loads(row["data_json"] or "{}").get("pain") if row else None
    except (TypeError, ValueError, AttributeError):
        pain = None
    return [p for p in pain if isinstance(p, dict)] if isinstance(pain, list) else []


def api_activity_track(store: Store, activity_id: int, q: Optional[dict] = None) -> Optional[dict]:
    """`/api/activity/<id>/track[?points=N]` : trace GPS + flux (distance, altitude, FC,
    vitesse, cadence) pour la carte et les graphiques liés de la page séance — voir
    `arc_index.track`. `points` : plafond de points (2 à `TRACK_MAX_POINTS`, défaut ce
    maximum). Seule route qui renvoie des coordonnées (`arc_climb_match.ASSUMPTIONS["privacy"]`)."""
    try:
        points = int(((q or {}).get("points") or [I.TRACK_MAX_POINTS])[0])
    except (TypeError, ValueError):
        points = I.TRACK_MAX_POINTS
    return store.track(activity_id, max(2, min(I.TRACK_MAX_POINTS, points)))


def api_activity_energy(store: Store, activity_id: int) -> dict:
    """Dépense énergétique modèle vs Garmin d'UNE séance, pour
    `/api/activity/<id>.energy` — délègue ENTIÈREMENT à
    `I.activity_energy_report_by_id` (même fonction que la CLI `arc_index.py
    energy`/`/api/energy-trend`, jamais un second calcul du delta/flag).
    Garmin reste la référence par défaut partout ailleurs (nutrition, rapports) ;
    ce bloc sert uniquement à afficher le modèle indépendant en contrôle."""
    with store.lock:
        return I.activity_energy_report_by_id(store.conn, activity_id)


def api_activity_climbs(store: Store, activity_id: int) -> dict:
    """Montées détectées et VAM d'une séance (#46), pour
    `/api/activity/<id>.climbs` : liste des montées (bornes, gain, pente, VAM
    temps écoulé/temps de mouvement, classe de pente) déjà calculées à
    l'indexation (`compute_metrics` -> `arc_climb.detect_climbs`), id INTERNE
    de l'activité. Rend TOUJOURS un dict (jamais `None`, même discipline que
    `api_activity_hr_zones`/#43) avec une `reason` explicite quand `climbs`
    est vide pour une raison AUTRE qu'un parcours plat (revue de code #46,
    should-fix 5) : hors de la famille course à pied, ou pas d'échantillons
    FIT ingérés — l'UI distingue ces deux cas d'une séance réellement plate
    (`climbs: [], reason: None`), au lieu d'afficher partout le même message
    « aucune montée détectée » qui laisserait croire à tort qu'une séance de
    renforcement ou de vélo aurait pu en avoir une."""
    act = store.one("SELECT sport, garmin_activity_id, intervals_activity_id, strava_activity_id FROM activity WHERE id = ?",
                    (activity_id,))
    empty = {"climbs": [], "vam_by_grade_class": {}}
    if act is None:
        return {**empty, "reason": "activité introuvable", "reason_code": "unknown_activity", "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                                    "arc_climb.ASSUMPTIONS[\"restricted_to_run_family\"]",
                "reason_code": "not_run_family", "applicable": False}
    sample_count = 0
    ref = I.activity_ref(act)
    if ref is not None:
        row = store.one(f"SELECT COUNT(*) AS n FROM activity_sample WHERE {I.ref_column(ref)} = ?", (ref,))
        sample_count = row["n"] if row else 0
    if not sample_count:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance",
                "reason_code": "no_samples", "applicable": True}
    # `segment_id`/`hr_*`/`vs_*` (#49, identité de montée entre séances) : colonnes SEULES
    # exposées de l'appariement — jamais une position GPS (voir
    # `arc_climb_match.ASSUMPTIONS["privacy"]`), `climb_segment` n'est d'ailleurs même pas
    # jointe ici (le nécessaire est déjà dénormalisé sur `activity_climb` à l'indexation).
    rows = store.rows(
        "SELECT idx AS \"index\", start_t_s, end_t_s, start_km, end_km, distance_m, gain_m, avg_grade, "
        "grade_class, duration_elapsed_s, duration_moving_s, vam_elapsed_m_h, vam_moving_m_h, segment_id, "
        "hr_first_third_bpm, hr_last_third_bpm, hr_drift_bpm_per_100m, vs_previous_pct, vs_best_pct "
        "FROM activity_climb WHERE activity_id = ? ORDER BY idx", (activity_id,))
    return {"climbs": rows, "vam_by_grade_class": I.VC.vam_by_grade_class(rows), "reason": None,
            "reason_code": None, "applicable": True}


def api_climb_segments(store: Store, q: dict) -> dict:
    """Segments de montée connus (#49), pour `/api/climb-segments` — résumé (id, lieu,
    profil, occurrences, meilleur temps), jamais de position GPS (voir
    `arc_climb_match.ASSUMPTIONS["privacy"]`)."""
    with store.lock:
        return {"segments": I.climb_segment_list(store.conn)}


def api_climb_segment(store: Store, segment_id: int) -> dict:
    """Historique complet d'un segment (#49), pour `/api/climb-segment/<id>` : chaque
    occurrence (date, activité, temps, VAM, FC, dérive, progression vs précédent/
    meilleur) déjà calculée à l'indexation — jamais de position GPS. Rend TOUJOURS un
    dict (même discipline que `api_activity`), `reason_code: "unknown_segment"` explicite
    si l'id ne correspond à aucun segment connu (id non stable d'une réindexation à
    l'autre, voir `arc_index.DDL`)."""
    with store.lock:
        return I.climb_segment_history(store.conn, segment_id)


def api_activity_descent(store: Store, activity_id: int) -> dict:
    """Efficacité en descente par classe de pente (#47), pour
    `/api/activity/<id>.descent` : classes déjà calculées à l'indexation
    (`compute_metrics` -> `arc_descent.descent_speed_by_grade_class`), id
    INTERNE de l'activité. Rend TOUJOURS un dict (jamais `None`, même
    discipline que `api_activity_climbs`/#46) avec une `reason` explicite dans
    TOUS les cas vides (contrairement aux montées, l'absence de classe
    qualifiante est toujours documentée ici — critère d'acceptation de #47 :
    « classes sans assez de données -> absentes », jamais silencieusement)."""
    act = store.one("SELECT sport, garmin_activity_id, intervals_activity_id, strava_activity_id, descent_reference_gap_pace_s_km, "
                     "descent_reference_source FROM activity WHERE id = ?", (activity_id,))
    empty = {"classes": {}, "reference_gap_pace_s_km": None, "reference_source": None}
    if act is None:
        return {**empty, "reason": "activité introuvable", "reason_code": "unknown_activity", "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                                    "arc_descent.ASSUMPTIONS[\"restricted_to_run_family\"]",
                "reason_code": "not_run_family", "applicable": False}
    sample_count = 0
    ref = I.activity_ref(act)
    if ref is not None:
        row = store.one(f"SELECT COUNT(*) AS n FROM activity_sample WHERE {I.ref_column(ref)} = ?", (ref,))
        sample_count = row["n"] if row else 0
    if not sample_count:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance",
                "reason_code": "no_samples", "applicable": True}
    rows = {r["grade_class"]: r for r in store.rows(
        "SELECT grade_class, count, duration_moving_s, distance_m, mean_speed_ms, mean_pace_s_km, "
        "mean_gap_speed_ms, mean_grade, efficiency FROM activity_descent_class WHERE activity_id = ?",
        (activity_id,))}
    # Ordre `DESCENT_GRADE_CLASSES` (croissant), jamais l'ordre SQL arbitraire d'une
    # colonne texte (même discipline que `arc_index.activity_descent_report`/l'UI).
    classes = {label: {k: v for k, v in rows[label].items() if k != "grade_class"}
               for _lo, _hi, label in I.DS.DESCENT_GRADE_CLASSES if label in rows}
    reason = reason_code = None
    if not classes:
        if act["descent_reference_gap_pace_s_km"] is None:
            reason, reason_code = I.DS.REASON_NO_REFERENCE, "no_reference"
        else:
            reason, reason_code = I.DS.REASON_NO_QUALIFYING_CLASS, "no_qualifying_class"
    return {
        "classes": classes,
        "reference_gap_pace_s_km": act["descent_reference_gap_pace_s_km"],
        "reference_source": act["descent_reference_source"],
        "reason": reason,
        "reason_code": reason_code,
        "applicable": True,
    }


def api_activity_durability(store: Store, activity_id: int) -> dict:
    """Durabilité sur les sorties longues (#48), pour
    `/api/activity/<id>.durability` : fade GAP/EF entre le premier et le
    dernier tiers, FC par tiers, déjà calculés à l'indexation
    (`compute_metrics` -> `arc_durability.durability_report_from_series`), id
    INTERNE de l'activité. Rend TOUJOURS un dict (jamais `None`, même
    discipline que `api_activity_descent`/#47) avec une `reason`/`reason_code`
    explicites dans TOUS les cas où `gap_fade_pct` est `None` — hors de la
    famille course à pied, pas d'échantillon FIT, séance pas assez longue,
    portion insuffisante, FC incomplète ou pente trop asymétrique entre les
    deux tiers comparés (voir `arc_durability.ASSUMPTIONS`)."""
    act = store.one(
        "SELECT sport, durability_gap_fade_pct, durability_ef_fade_pct, durability_hr_first_third_bpm, "
        "durability_hr_middle_third_bpm, durability_hr_last_third_bpm, durability_reason, "
        "durability_reason_code FROM activity WHERE id = ?", (activity_id,))
    empty = {"gap_fade_pct": None, "ef_fade_pct": None, "hr_first_third_bpm": None,
             "hr_middle_third_bpm": None, "hr_last_third_bpm": None}
    if act is None:
        return {**empty, "reason": "activité introuvable", "reason_code": "unknown_activity", "applicable": True}
    if M.sport_family(act["sport"]) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                                    "arc_durability.ASSUMPTIONS[\"restricted_to_run_family\"]",
                "reason_code": "not_run_family", "applicable": False}
    if act["durability_gap_fade_pct"] is None and act["durability_reason"] is None:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance",
                "reason_code": "no_samples", "applicable": True}
    return {
        "gap_fade_pct": act["durability_gap_fade_pct"],
        "ef_fade_pct": act["durability_ef_fade_pct"],
        "hr_first_third_bpm": act["durability_hr_first_third_bpm"],
        "hr_middle_third_bpm": act["durability_hr_middle_third_bpm"],
        "hr_last_third_bpm": act["durability_hr_last_third_bpm"],
        "reason": act["durability_reason"],
        "reason_code": act["durability_reason_code"],
        "applicable": True,
    }


def api_activity_hr_zones(store: Store, activity_id: int) -> dict:
    """Zones FC + temps en zone d'une séance (#43), pour `/api/activity/<id>.hr_zones` :
    bornes et méthode effectives (précédence `arc_metrics.hr_zone_resolution`), temps
    en zone (`hr_zone_time`) et polarisation Seiler (`hr_polarisation_time`, bornes
    dédiées par méthode) de la séance, id INTERNE de l'activité.

    Rend TOUJOURS un dict, jamais `None` (revue de code #43, point 4) : un
    `bounds_bpm: null` porte une `reason` explicite (méthode inconnue, méthode forcée
    mais champ manquant au profil, ou aucune donnée du tout) que l'UI affiche au lieu
    de masquer silencieusement la section. `zone_seconds`/`polarisation` restent
    `None` sans échantillons FIT (ou sport hors de la famille course à pied — voir
    `compute_metrics`), même quand les bornes sont connues."""
    conf = store.meta("settings") or {}
    with store.lock:
        resolution = I.athlete_hr_zone_resolution(store.conn, conf)
        if resolution["bounds_bpm"] is None:
            return {**resolution, "zone_seconds": None, "polarisation": None}
        rows = store.conn.execute(
            "SELECT zone, seconds FROM hr_zone_time WHERE activity_id = ?", (activity_id,)).fetchall()
        pol_rows = store.conn.execute(
            "SELECT bucket, seconds FROM hr_polarisation_time WHERE activity_id = ?", (activity_id,)).fetchall()
    zone_seconds = {row["zone"]: row["seconds"] for row in rows} if rows else None
    pol_seconds = {row["bucket"]: row["seconds"] for row in pol_rows} if pol_rows else None
    return {
        **resolution, "zone_seconds": zone_seconds,
        "polarisation": M.polarisation_shares(pol_seconds) if pol_seconds else None,
    }


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


def api_block(store: Store, q: dict) -> dict:
    """Frise du bloc planifié (#193) : phases semaine par semaine + repère de course. Lecture seule de
    l'index (`week`, `activity`, `objective`) ; la logique pure vit dans `arc_block_timeline`."""
    today = _today(store)
    weeks = store.rows("SELECT week_start, phase, week_type, target_duration_s, target_distance_m, "
                       "target_elevation_m FROM week WHERE shadowed = 0 ORDER BY week_start")
    starts = BT.select_block([w["week_start"] for w in weeks if w["week_start"]], today, BT.block_bridgeable(weeks))
    done: dict = {}
    if starts:
        last = date.fromisoformat(starts[-1]) + timedelta(days=6)
        for row in store.rows("SELECT date, distance_m, duration_s, elevation_gain_m FROM activity "
                              "WHERE sport != 'rest' AND date >= ? AND date <= ?", (starts[0], last.isoformat())):
            ws = _monday(date.fromisoformat(row["date"])).isoformat()
            agg = done.setdefault(ws, {"duration_s": 0, "distance_m": 0, "elevation_m": 0, "sessions": 0})
            agg["duration_s"] += row["duration_s"] or 0
            agg["distance_m"] += row["distance_m"] or 0
            agg["elevation_m"] += row["elevation_gain_m"] or 0
            agg["sessions"] += 1
    obj = store.one("SELECT name, race_date FROM objective WHERE race_date IS NOT NULL ORDER BY source_path LIMIT 1")
    return BT.build(weeks, done, obj["race_date"] if obj else None, today, obj["name"] if obj else None)


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
        "SELECT date, weight_kg, weight_origin FROM health_day WHERE date >= ? AND date <= ? "
        "ORDER BY date, source_path", (fetch_from, today.isoformat()))
    nutrition_weight_by_date = {r["date"]: r["weight_kg"] for r in nutrition_weight_rows if r["weight_kg"] is not None}
    health_weight_by_date = {r["date"]: r["weight_kg"] for r in health_weight_rows if r["weight_kg"] is not None}
    health_origin_by_date = {r["date"]: r["weight_origin"] for r in health_weight_rows if r["weight_kg"] is not None}
    merged_by_date, origin_by_date = {}, {}
    for d in set(nutrition_weight_by_date) | set(health_weight_by_date):
        v = M.merge_weight_kg(health_weight_by_date.get(d), nutrition_weight_by_date.get(d))
        if v is not None:
            merged_by_date[d] = v
            # Provenance du point retenu (#222) : `garmin` seulement si la pesée de santé gagne ET
            # vient de Garmin (`weight_origin`) ; sinon déclarée par l'athlète (`chat`, fichier
            # santé d'avant #222 sans la clé, ou poids du fichier nutrition).
            from_health = health_weight_by_date.get(d) is not None
            origin_by_date[d] = "garmin" if from_health and health_origin_by_date.get(d) == "garmin" else "athlete"
    weight_points = M.weight_avg7_series(merged_by_date, start_date, today)
    latest_day = max((d for d in merged_by_date if d <= today.isoformat()), default=None)
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
        "weight_series": [{"date": p["date"], "weight_kg_merged": p["weight_kg"], "weight_avg7_kg": p["weight_avg7_kg"],
                           "weight_origin": origin_by_date.get(p["date"]) if p["weight_kg"] is not None else None}
                          for p in weight_points],
        "weight": {
            # Dernière pesée connue (fenêtre de calcul comprise) et sa provenance (#222).
            "latest": ({"date": latest_day, "weight_kg": merged_by_date[latest_day],
                        "origin": origin_by_date[latest_day]} if latest_day else None),
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


def api_decoupling(store: Store, q: dict) -> dict:
    """Tendance du découplage aérobie (Pa:HR) et du facteur d'efficacité sur les
    sorties longues (#45) : `/api/decoupling`.

    Additive : ne touche à aucune route existante. Délègue à `M.decoupling_trend`
    sur les sorties longues de la famille course à pied (`duration_s` >
    `M.LONG_RUN_MIN_DURATION_S`) de la fenêtre demandée (`weeks`, défaut
    `M.DECOUPLING_TREND_WEEKS`) — voir `arc_decoupling.ASSUMPTIONS`.
    """
    today = _today(store)
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else M.DECOUPLING_TREND_WEEKS
    weeks = max(4, min(52, weeks))
    rows = store.rows(
        "SELECT date, sport, name, duration_s, decoupling_pct, ef_whole FROM activity "
        "WHERE duration_s > ?", (M.LONG_RUN_MIN_DURATION_S,))
    return M.decoupling_trend(rows, today, weeks)


def api_vam(store: Store, q: dict) -> dict:
    """Tendance de la VAM sur les montées détectées (#46) : `/api/vam`.

    Additive : ne touche à aucune route existante. Délègue à `M.vam_trend` sur
    TOUTES les activités de la famille course à pied de la fenêtre demandée
    (`weeks`, défaut `M.VAM_TREND_WEEKS`) — AUCUN seuil de durée minimale,
    contrairement à `api_decoupling` (voir `arc_climb.ASSUMPTIONS`).
    """
    today = _today(store)
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else M.VAM_TREND_WEEKS
    weeks = max(4, min(52, weeks))
    rows = store.rows(
        "SELECT date, sport, name, best_vam_10min_m_h, best_vam_20min_m_h, best_climb_vam_elapsed_m_h "
        "FROM activity")
    return M.vam_trend(rows, today, weeks)


def api_descent(store: Store, q: dict) -> dict:
    """Tendance de l'efficacité en descente par classe de pente (#47) :
    `/api/descent`.

    Additive : ne touche à aucune route existante. Délègue à `M.descent_trend`
    sur TOUTES les activités de la famille course à pied de la fenêtre demandée
    (`weeks`, défaut `M.DESCENT_TREND_WEEKS`) — AUCUN seuil de durée minimale
    sur la séance (comme `api_vam`), seul le seuil PAR CLASSE (déjà appliqué à
    l'indexation) filtre les lignes — voir `arc_descent.ASSUMPTIONS`.
    `a.descent_reference_source` (revue de code, should-fix) : `"flat"` et son
    repli `"non_descent"` ne sont pas sur la même échelle (mesuré : 0,664 en
    `flat` vs 0,548 en `non_descent` pour la MÊME descente) — porté sur chaque
    point de la tendance pour que l'UI ne les mélange jamais sans le dire.
    """
    today = _today(store)
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else M.DESCENT_TREND_WEEKS
    weeks = max(4, min(52, weeks))
    rows = store.rows(
        "SELECT a.id AS activity_id, a.date AS date, a.sport AS sport, a.name AS name, "
        "a.descent_reference_source AS reference_source, dc.grade_class AS grade_class, "
        "dc.efficiency AS efficiency, dc.mean_pace_s_km AS mean_pace_s_km, "
        "dc.mean_grade AS mean_grade FROM activity_descent_class dc JOIN activity a ON a.id = dc.activity_id")
    return M.descent_trend(rows, today, weeks)


def api_durability(store: Store, q: dict) -> dict:
    """Tendance de durabilité sur les sorties longues (#48) : `/api/durability`.

    Additive : ne touche à aucune route existante. Délègue à `M.durability_trend`
    sur les sorties longues de la famille course à pied (`moving_duration_s`
    déclaré, à défaut `duration_s` écoulé, > `M.LONG_RUN_MIN_DURATION_S`) de la
    fenêtre demandée (`weeks`, défaut `M.DURABILITY_TREND_WEEKS`) — voir
    `arc_durability.ASSUMPTIONS`. `id AS activity_id` (revue de code #48,
    should-fix 3, cohérence avec `api_descent`). Pas de `WHERE` sur la durée ICI
    (contrairement à `api_decoupling`, revue de code #48) : `M.durability_trend`
    a besoin des DEUX colonnes de durée pour appliquer son repli
    `moving_duration_s or duration_s` — un `WHERE duration_s > ?` exclurait à
    tort une activité dont seul `moving_duration_s` dépasse le seuil.
    """
    today = _today(store)
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else M.DURABILITY_TREND_WEEKS
    weeks = max(4, min(52, weeks))
    rows = store.rows(
        "SELECT id AS activity_id, date, sport, name, duration_s, moving_duration_s, "
        "durability_gap_fade_pct, durability_ef_fade_pct, durability_hr_first_third_bpm, "
        "durability_hr_middle_third_bpm, durability_hr_last_third_bpm, durability_reason, "
        "durability_reason_code FROM activity")
    return M.durability_trend(rows, today, weeks)


def api_performance_index(store: Store, q: dict) -> dict:
    """Indices de performance ITRA/UTMB (#62) : `/api/performance-index`.

    Duplique volontairement `store.performance_index()` déjà exposée sous
    `/api/summary.performance_index` (comme `gear`/`/api/summary.gear` n'a pas
    besoin d'une route dédiée aujourd'hui) : la vue Performance de `web/js/
    app.js` lit `SUMMARY.performance_index` (un seul `/api/summary` déjà
    récupéré au chargement, pas d'aller-retour supplémentaire) — cette route
    dédiée sert un appelant headless (agent, CLI externe) qui veut CETTE seule
    donnée sans tout le résumé, et documente sa forme indépendamment."""
    return store.performance_index(_today(store))


def api_trail_shape(store: Store, q: dict) -> dict:
    """Score « Trail Shape » (#63) : `/api/trail-shape`.

    Délègue ENTIÈREMENT à `I.trail_shape_report` (donc à
    `arc_trail_shape.trail_shape_report` — formule, constantes, cas limites),
    même fonction que la CLI `arc_index.py trail-shape` : aucun second calcul
    ici. Aucune donnée de santé lue (le score n'en utilise aucune, voir
    `arc_trail_shape` docstring)."""
    today = _today(store)
    with store.lock:
        return I.trail_shape_report(store.conn, today)


def api_roadbook(store: Store, q: dict) -> dict:
    """Roadbook imprimable d'un plan de course (#187) : `/api/roadbook?plan=<fichier>&scenario=`.

    Délègue ENTIÈREMENT à `arc_roadbook.build_roadbook` (heures de passage et marges de barrière :
    `arc_race_pacing`, matériel : `arc_index.equipment_race_check`, #134) — aucun calcul ici. Sans
    `plan`, le prochain plan dont la date n'est pas passée (sinon le plus récent) ; `scenario`
    (`safe|realistic|ambitious`) ne garde que ce scénario, absent ou inconnu = les trois (la page
    bascule sans nouvel appel). Lecture seule, aucune donnée de santé."""
    plan = (q.get("plan", [""])[0] or "").strip()
    wanted = (q.get("scenario", [""])[0] or "").strip()
    today = _today(store)                  # avant le verrou : `store.meta` le prend aussi
    with store.lock:
        plans = [dict(r) for r in store.conn.execute(
            "SELECT source_path AS path, race_name, race_date FROM race_plan ORDER BY race_date DESC, source_path")]
        if not plans:
            return {"status": "no_plan", "plans": [],
                    "message": "Aucun plan de course indexé : demande-le au course-strategist."}
        check = I.equipment_race_check(store.conn, plan or None, today, store.workspace)
        if check.get("error"):
            return {"status": "plan_not_found", "plans": plans, "message": check["error"]}
        row = store.conn.execute("SELECT data_json FROM race_plan WHERE source_path = ?",
                                 (check["race_plan"],)).fetchone()
    try:
        data = json.loads(row["data_json"] or "{}")
    except ValueError:
        data = {}
    model = RB.build_roadbook(data, plan_path=check["race_plan"], gear_check=check)
    model["plans"] = plans
    if wanted in RB.SCENARIOS:
        model["scenarios"] = {wanted: model["scenarios"][wanted]}
        model["default_scenario"] = wanted
    elif wanted and wanted != "all":
        model["warnings"].append(f"scénario inconnu « {wanted} » : les trois scénarios sont renvoyés")
    return model


def api_slope_model(store: Store, q: dict) -> dict:
    """Modèle personnel pente -> allure (et FC) — #58, `/api/slope-model?band=`.

    Additive : ne touche à aucune route existante. Délègue à
    `I.slope_model_report`, le modèle DÉJÀ CALCULÉ au dernier passage de
    `compute_metrics` (fenêtre `[metrics].slope_model_months`, voir
    `arc_slope_model.ASSUMPTIONS`) — jamais un recalcul par requête HTTP (ce
    n'est possible, à la demande, que par la CLI `slope-model --months`).
    `band` (défaut `"endurance"`) : `"all"` sinon (`arc_slope_model.BANDS`), une
    valeur inconnue retombe sur `"endurance"` plutôt que d'échouer."""
    band = q.get("band", ["endurance"])[0]
    if band not in ("endurance", "all"):
        band = "endurance"
    with store.lock:
        return I.slope_model_report(store.conn, band)


def api_energy_trend(store: Store, q: dict) -> dict:
    """Tendance de la dépense énergétique modèle vs Garmin :
    `/api/energy-trend`. Additive : ne touche à aucune route existante. Délègue
    ENTIÈREMENT à `I.energy_trend` (même fonction que `/api/activity/<id>.energy`
    et la CLI `arc_index.py energy`, jamais un second calcul du delta/flag)."""
    today = _today(store)
    weeks_raw = q.get("weeks", [""])[0]
    weeks = int(weeks_raw) if weeks_raw.isdigit() else I.ENERGY_TREND_WEEKS
    weeks = max(4, min(52, weeks))
    with store.lock:
        return I.energy_trend(store.conn, today, weeks)


def gear_photo_file(store: Store, rel) -> Optional[Tuple[Path, str]]:
    """(chemin absolu, type MIME) de la photo `rel` (relatif au workspace), `None` si elle ne peut pas
    être servie. Quatre barrières successives (#135) : chemin relatif propre (`arc_contract`, ni `..`,
    ni antislash, ni `:`, ni absolu) sous `gear/photos/` ; extension raster ; citée par une inspection
    indexée ; résolution réelle (liens symboliques compris) toujours DANS `gear/photos/` ; fichier
    ordinaire de taille raisonnable."""
    if not isinstance(rel, str) or I.C._invalid_workspace_path_reason(rel):
        return None
    if not rel.startswith(I.C.GEAR_PHOTO_DIR):
        return None
    ctype = GEAR_PHOTO_TYPES.get(Path(rel).suffix.lower())
    if ctype is None:
        return None
    cited = False
    for row in store.rows("SELECT photos FROM gear_inspection WHERE photos IS NOT NULL"):
        try:
            if rel in json.loads(row["photos"]):
                cited = True
                break
        except (TypeError, ValueError):
            continue
    if not cited:
        return None
    try:
        root = (store.workspace / "gear" / "photos").resolve()
        target = (store.workspace / rel).resolve()
        if root not in target.parents or not target.is_file():
            return None
        if target.stat().st_size > GEAR_PHOTO_MAX_BYTES:
            return None
    except (OSError, ValueError):     # NUL, nom trop long, permission…
        return None
    return target, ctype


def api_files(store: Store, q: dict) -> dict:
    return {"items": store.backfill()}


# ---------------------------------------------------------------------------
# Journal des décisions (#55) : « Pourquoi aujourd'hui ? » + vue « Décisions »
# ---------------------------------------------------------------------------


def rule_info(rule_id: str) -> dict:
    """Métadonnées STATIQUES d'une règle de garde-fou (#55), pour l'affichage à
    côté d'un `rule_id` cité par `decision.rule_ids` — jamais le MESSAGE d'une
    violation précise (celui-ci porte des valeurs mesurées, régénérées à chaque
    évaluation par `arc_guardrails.evaluate`, et disparues une fois la décision
    écrite : seul le `rule_id` traverse jusqu'ici). `label`/`default_severity`
    viennent de `arc_guardrails.RULE_LABELS`/`DEFAULT_SEVERITY` (import LÉGER,
    aucune ouverture d'index — voir l'en-tête du module) ; un `rule_id` inconnu
    (règle retirée, faute de frappe historique — voir SKILL.md, `rule_ids` n'est
    pas vérifié contre la liste vivante des règles) rend quand même un objet
    exploitable plutôt qu'une exception, `label` retombant sur l'id lui-même."""
    return {
        "rule_id": rule_id,
        "label": G.RULE_LABELS.get(rule_id, rule_id),
        "default_severity": G.DEFAULT_SEVERITY.get(rule_id),
        "doc_url": GUARDRAILS_DOC_URL,
    }


def resolve_source(store: Store, path: str, target_date: Optional[str] = None) -> dict:
    """Résout un chemin `sources`/`supersedes`/`session_ref.week` de décision
    (#55) en `{"path", "kind", "label", "route"}` — `route` un hash de l'app
    (`#/...`) vers une vue EXISTANTE du dashboard quand le chemin s'y prête,
    `None` sinon (texte simple côté UI). Ne lit JAMAIS le fichier désigné —
    `arc_index.classify_source_path` (pur) donne le genre par le NOM seul ;
    ici, seules des requêtes SQL déjà utilisées par d'autres routes (`activity`/
    `report`/`decision` par `source_path`) enrichissent le libellé quand c'est
    bon marché. Aucun contenu de fichier n'est jamais renvoyé — la surface
    exposée reste celle, déjà publique, des autres routes `/api/*`.

    `target_date` (#69, revue de code should-fix 4) : pour `kind == "week"`,
    `classify_source_path` ne rend que le lundi du NOM DU FICHIER — correct
    pour une semaine unique, mais TOUJOURS le lundi de la PREMIÈRE semaine d'un
    plan multi-semaines (`weeks[]`), quelle que soit la semaine réellement
    visée. Quand l'appelant connaît une date à viser (la propre `date` de la
    décision qui cite ce fichier dans `sources`), on route vers le lundi DE
    CETTE semaine plutôt que vers celui du nom de fichier — sinon un lien vers
    la 2e semaine ou plus d'un tel plan ouvrirait systématiquement la 1re."""
    info = I.classify_source_path(path)
    kind, day = info["kind"], info["date"]
    if kind == "week" and target_date:
        try:
            day = _monday(date.fromisoformat(target_date)).isoformat()
        except ValueError:
            pass
    label, route = path, None
    if kind == "health":
        label, route = f"Santé du {day}", "#/sante"
    elif kind == "weather":
        label = f"Météo du {day}"
    elif kind == "nutrition":
        label, route = f"Nutrition du {day}", "#/nutrition"
    elif kind == "week":
        label, route = f"Semaine du {day}", f"#/semaine?debut={day}"
    elif kind == "activity":
        row = store.one("SELECT id, name, sport FROM activity WHERE source_path = ?", (path,))
        label = (row and (row.get("name") or row.get("sport"))) or f"Séance du {day}"
        route = f"#/seance/{row['id']}" if row else None
    elif kind == "report":
        row = store.one("SELECT title FROM report WHERE source_path = ?", (path,))
        label = (row and row.get("title")) or path
        route = f"#/rapport?path={quote(path, safe='')}"
    elif kind == "decision":
        row = store.one("SELECT summary FROM decision WHERE source_path = ?", (path,))
        label = (row and row.get("summary")) or path
        route = f"#/decision?id={quote(Path(path).stem, safe='')}"
    return {"path": path, "kind": kind, "label": label, "route": route}


def _decision_id(source_path: str) -> str:
    return Path(source_path).stem


def _enrich_decision(store: Store, d: dict) -> dict:
    d = dict(d)
    d["id"] = _decision_id(d["source_path"])
    d["rules"] = [rule_info(rid) for rid in (d.get("rule_ids") or [])]
    # `d["date"]` (#69, revue de code should-fix 4) : la meilleure date connue à
    # viser pour un `sources` qui serait un fichier `week` multi-semaines — voir
    # `resolve_source`, `target_date`.
    d["source_links"] = [resolve_source(store, p, d.get("date")) for p in (d.get("sources") or [])]
    return d


DECISIONS_DEFAULT_DAYS = 90  # #55, revue de code : voir la docstring d'`api_decisions`.


def api_decisions(store: Store, q: dict) -> dict:
    """Journal des décisions (#54), plus récentes d'abord : `/api/decisions`.

    `days` (fenêtre glissante se terminant à `today`) ; `trigger`/`outcome`
    filtrent en plus ; `active=1` exclut `superseded`/`rejected_by_athlete`
    (voir `arc_index.decisions_query`). Sans `days` NI `all=1`, la fenêtre
    retombe sur `DECISIONS_DEFAULT_DAYS` (90 j) plutôt que de rendre tout le
    journal — un workspace qui tourne depuis longtemps aurait fini par charger
    des centaines de décisions à chaque ouverture de la vue « Décisions »
    (revue de code #55, nit). `all=1` demande explicitement l'historique
    complet (l'option « Tout » de la vue) : un appelant qui veut vraiment tout
    le doit dire, jamais par la simple absence de `days`."""
    today = _today(store)
    days_raw = q.get("days", [""])[0]
    show_all = q.get("all", [""])[0] in ("1", "true")
    if days_raw.isdigit():
        days = max(1, min(3650, int(days_raw)))
    elif show_all:
        days = None
    else:
        days = DECISIONS_DEFAULT_DAYS
    trigger = q.get("trigger", [""])[0] or None
    outcome = q.get("outcome", [""])[0] or None
    active = q.get("active", [""])[0] in ("1", "true")
    with store.lock:
        rows = I.decisions_query(store.conn, today=today, days=days, trigger=trigger,
                                 outcome=outcome, active=active)
    return {"decisions": [_enrich_decision(store, d) for d in rows],
            "trigger": trigger, "outcome": outcome, "days": days, "active": active}


def api_gear(store: Store, gear_id: str):
    """Fiche d'une paire ou d'un objet d'équipement (#147) : `/api/gear/<id>`. `<id>` est un slug
    (`arc_contract.GEAR_ID_RE`) — tout autre motif (dont `..`, `/`, majuscules) rend `None` (404),
    sans distinction avec un identifiant inconnu. Bâtie sur `arc_index.gear_detail` (attribution
    unique `arc_metrics.attribute_gear`), jamais sur une seconde règle."""
    if not gear_id or not I.C.GEAR_ID_RE.match(gear_id):
        return None
    return store.gear_detail(gear_id, _today(store))


def api_decision(store: Store, decision_id: str):
    """Détail d'une décision (#55) : `/api/decision/<id>` — `<id>` est le nom du
    fichier SANS extension (`DECISION_ID_RE`, jamais un chemin). Recherché par
    `_decision_id(source_path) == decision_id` sur TOUTES les lignes `decision`
    connues (jamais en reconstruisant `planning/<id>.md` puis en l'égalant à
    `source_path` — #55, revue de code : `arc_index.classify()` reste permissif
    par conception, un fichier `decision` mal placé — sous-dossier de
    `planning/`, comme un fichier hors contrat repris via son propre bloc
    ```arc``` — peut donc exister dans l'index avec un `source_path` que la
    reconstruction naïve ne retrouverait jamais, alors qu'il apparaît bien dans
    `/api/decisions` : le lien de détail rendait alors 404 à tort). Aucun accès
    disque avec `decision_id` : la ligne existe ou non dans l'index déjà
    construit depuis de vrais fichiers workspace. Rend `None` (404) pour un id
    malformé (dont toute tentative de remontée de répertoire, bloquée par le
    motif — même un id contenant `/` ou `..` ne fait jamais correspondre
    `_decision_id`, qui ne compare que des noms de fichier) ou une décision
    inconnue — jamais de distinction entre les deux dans la réponse."""
    if not decision_id or not DECISION_ID_RE.match(decision_id):
        return None
    row = next((r for r in store.rows("SELECT * FROM decision") if _decision_id(r["source_path"]) == decision_id), None)
    if not row:
        return None
    source_path = row["source_path"]
    d = dict(row)
    body = d.pop("body_md") or ""
    d.pop("data_json", None)
    d.pop("arc_version", None)
    d.pop("created_at_utc", None)   # détail d'implémentation du tri, pas une donnée du contrat
    for key in ("inputs", "rule_ids", "sources", "before", "after", "session_ref"):
        raw = d.pop(f"{key}_json", None)
        d[key] = json.loads(raw) if raw else None
    d = _enrich_decision(store, d)
    d["supersedes_info"] = None
    if d.get("supersedes"):
        prev = store.one("SELECT source_path, summary, outcome, date FROM decision WHERE source_path = ?",
                         (d["supersedes"],))
        if prev:
            d["supersedes_info"] = {**prev, "id": _decision_id(prev["source_path"])}
    superseded_by = store.rows("SELECT source_path, summary, outcome, date FROM decision WHERE supersedes = ?",
                               (source_path,))
    d["superseded_by"] = [{**r, "id": _decision_id(r["source_path"])} for r in superseded_by]
    d["session_ref_route"] = None
    session_ref = d.get("session_ref") or {}
    week_path = session_ref.get("week")
    if week_path:
        week_info = I.classify_source_path(week_path)
        if week_info["kind"] == "week":
            # #69, revue de code should-fix 4 : `session_ref.date` (la date de LA
            # séance référencée) fait foi pour choisir le lundi visé, jamais le
            # lundi du NOM du fichier (`week_info["date"]`) — celui-ci est
            # toujours celui de la PREMIÈRE semaine d'un plan multi-semaines
            # (`weeks[]`), quelle que soit la semaine où vit réellement la
            # séance. Repli sur le lundi du nom de fichier seulement si
            # `session_ref.date` est absent ou illisible (ancienne décision,
            # ou format inattendu) — mieux vaut un lien vers LA semaine du
            # fichier que pas de lien du tout.
            week_start = week_info["date"]
            session_date = session_ref.get("date")
            if isinstance(session_date, str):
                try:
                    week_start = _monday(date.fromisoformat(session_date)).isoformat()
                except ValueError:
                    pass
            d["session_ref_route"] = f"#/semaine?debut={week_start}"
    d["body_html"] = render_markdown(strip_leading_heading(I.C.body_after_block(body)))
    return d


def api_injury_risk(store: Store, q: dict) -> dict:
    """Drapeau composite de risque de blessure (#57) : `/api/injury-risk`.

    Délègue ENTIÈREMENT à `arc_guardrails` (mêmes fonctions que la CLI
    `injury-risk`, jamais une seconde copie de la logique) — `[injury_risk]`
    est lu depuis `I.load_config(store.workspace)` plutôt que
    `store.meta("settings")` (qui ne porte que `arc_index.settings`, pas les
    sections libres comme `[injury_risk]`)."""
    today = _today(store)
    with store.lock:
        config = I.load_config(store.workspace)
        gconf = G.injury_risk_settings(config)
        context = G.build_injury_risk_context(store.conn, config, gconf, today)
    return G.evaluate_injury_risk(context, gconf)


ROUTES = {
    "/api/summary": api_summary, "/api/assumptions": api_assumptions, "/api/form": api_form, "/api/load": api_load,
    "/api/health": api_health, "/api/week": api_week, "/api/activities": api_activities,
    "/api/performance": api_performance, "/api/reports": api_reports, "/api/report": api_report,
    "/api/calendar": api_calendar, "/api/block": api_block, "/api/nutrition": api_nutrition, "/api/fueling": api_fueling,
    "/api/decoupling": api_decoupling, "/api/vam": api_vam, "/api/descent": api_descent,
    "/api/durability": api_durability, "/api/slope-model": api_slope_model, "/api/files": api_files,
    "/api/trail-shape": api_trail_shape, "/api/energy-trend": api_energy_trend,
    "/api/climb-segments": api_climb_segments, "/api/decisions": api_decisions,
    "/api/injury-risk": api_injury_risk, "/api/performance-index": api_performance_index,
    "/api/gait": api_gait, "/api/altitude-exposure": api_altitude_exposure, "/api/pace-curve": api_pace_curve,
    "/api/decision-effects": api_decision_effects, "/api/load-forecast": api_load_forecast,
    "/api/roadbook": api_roadbook,
}

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


# Proxy local du chat (`/api/chat/*`) : un simple tuyau vers le service `arc_chat.py`.
# Actif seulement si `[chat].enabled` ET que le tableau de bord écoute en boucle locale ;
# en conteneur / derrière un proxy, c'est Traefik qui route `/api/chat` directement.
CHAT_PREFIX = "/api/chat/"
CHAT_DEFAULT_PORT = 8766
CHAT_CONNECT_TIMEOUT_S = 5.0
CHAT_READ_TIMEOUT_S = float(os.environ.get("ARC_DASHBOARD_CHAT_READ_TIMEOUT_S", "120"))  # > ping SSE (15 s)
CHAT_UNREACHABLE = {"error": "Service de chat injoignable — lancez scripts/coach-chat.sh start"}
# En-têtes de requête relayés (liste blanche : ni Cookie, ni Authorization).
CHAT_FORWARD_REQUEST = ("Content-Type", "X-ARC-Chat", "Origin", "Sec-Fetch-Site", "Accept", "Host")
# En-têtes de réponse relayés (jamais de CORS).
CHAT_FORWARD_RESPONSE = ("Content-Type", "Cache-Control", "X-Accel-Buffering", "Retry-After")
LOOPBACK_LISTEN = (LOOPBACK, "localhost", "::1")


def chat_proxy_port(config: dict, listen: str) -> Optional[int]:
    """Port du service de chat à relayer, ou `None` si le proxy doit rester inactif."""
    chat = config.get("chat", {}) or {}
    if not chat.get("enabled", False) or listen not in LOOPBACK_LISTEN:
        return None
    try:
        port = int(chat.get("port", CHAT_DEFAULT_PORT))
    except (TypeError, ValueError):
        return None
    return port if 0 < port <= 65535 else None


def tile_origin(template: str) -> str:
    """Source CSP `img-src` des tuiles de carte, tirée du modèle déjà validé par
    `arc_index._map_tiles` : `https://{s}.hôte/…` → `https://*.hôte`, `""` sans fond de carte."""
    if not template:
        return ""
    parts = urlsplit(template.replace("{s}.", "SUBDOMAIN.", 1))
    host = parts.netloc.replace("SUBDOMAIN.", "*.", 1)
    return f"{parts.scheme}://{host}"


class Handler(BaseHTTPRequestHandler):
    server_version = "arc-dashboard"
    store: Store = None           # posé par serve()
    allowed_hosts: set = set()
    chat_port: Optional[int] = None   # posé par serve() ; None = pas de proxy
    tile_src: str = ""                # posé par serve() : « ␣https://hôte » des tuiles de carte, ou vide

    def log_message(self, fmt, *args):         # silencieux : c'est un outil local
        pass

    def _accepts_gzip(self) -> bool:
        return any(part.split(";")[0].strip() == "gzip"
                   for part in (self.headers.get("Accept-Encoding") or "").lower().split(","))

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store",
              etag: Optional[str] = None, gzipped: Optional[bytes] = None) -> None:
        """`cache` : `no-store` pour l'API (données de santé, jamais en cache) ;
        `no-cache` + `etag` pour les fichiers statiques (revalidés, `304` si inchangés).
        `gzipped` : version compressée déjà calculée (fichiers statiques)."""
        compressible = ctype.startswith(COMPRESSIBLE)
        encoded = False
        if compressible and len(body) >= GZIP_MIN_BYTES and self._accepts_gzip():
            body = gzipped if gzipped is not None else gzip.compress(body, compresslevel=6)
            encoded = True
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if encoded:
            self.send_header("Content-Encoding", "gzip")
        if compressible:
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", cache)
        if etag:
            self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
                         f"font-src https://fonts.gstatic.com; img-src 'self' data:{self.tile_src}; "
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
        elif url.path.startswith(CHAT_PREFIX) and self.chat_port:
            self._chat_proxy()
        elif url.path == "/media/gear-photo":
            self._gear_photo(url)
        elif url.path.startswith("/api/"):
            self._api(url)
        else:
            self._static(url.path)

    def do_POST(self):          # lecture seule (sauf le tuyau vers le service de chat)
        if self.path.startswith(CHAT_PREFIX) and self.chat_port:
            if not self._host_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "hôte non autorisé"})
                return
            self._chat_proxy()
            return
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "lecture seule"})

    do_PUT = do_DELETE = do_PATCH = do_POST

    def _chat_proxy(self) -> None:
        """Relaie la requête telle quelle au service de chat et renvoie sa réponse au fil
        de l'eau (SSE : un `flush` par bloc reçu). Aucune écriture dans le workspace."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else None
        headers = {h: self.headers[h] for h in CHAT_FORWARD_REQUEST if self.headers.get(h)}
        conn = http.client.HTTPConnection("127.0.0.1", self.chat_port, timeout=CHAT_CONNECT_TIMEOUT_S)
        try:
            conn.request(self.command, self.path, body=body, headers=headers, encode_chunked=False)
            conn.sock.settimeout(CHAT_READ_TIMEOUT_S)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException):
            conn.close()
            self._json(HTTPStatus.BAD_GATEWAY, CHAT_UNREACHABLE)
            return
        try:
            self.close_connection = True            # corps délimité par la fermeture
            self.send_response(resp.status)
            for name in CHAT_FORWARD_RESPONSE:
                if resp.getheader(name):
                    self.send_header(name, resp.getheader(name))
            if not resp.getheader("Cache-Control"):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read1(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException):
            pass                                    # client parti ou service coupé en cours de flux
        finally:
            conn.close()

    def _api(self, url) -> None:
        q = parse_qs(url.query)
        if self.store.background:
            # Le fil d'index tient la base à jour : une requête n'attend que le TOUT
            # premier passage (démarrage), jamais une réindexation.
            if not self.store.wait_ready():
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "index en cours de construction, réessayez"})
                return
        else:
            self.store.refresh()
        try:
            match = re.fullmatch(r"/api/activity/(\d+)", url.path)
            track_match = re.fullmatch(r"/api/activity/(\d+)/track", url.path)
            segment_match = re.fullmatch(r"/api/climb-segment/(\d+)", url.path)
            decision_match = re.fullmatch(r"/api/decision/([^/]+)", url.path)
            gear_match = re.fullmatch(r"/api/gear/([^/]+)", url.path)
            if match:
                payload = api_activity(self.store, int(match.group(1)))
            elif track_match:
                payload = api_activity_track(self.store, int(track_match.group(1)), q)
            elif segment_match:
                payload = api_climb_segment(self.store, int(segment_match.group(1)))
            elif decision_match:
                payload = api_decision(self.store, decision_match.group(1))
            elif gear_match:
                payload = api_gear(self.store, gear_match.group(1))
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

    def _gear_photo(self, url) -> None:
        found = gear_photo_file(self.store, (parse_qs(url.query).get("path") or [None])[0])
        if found is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})
            return
        target, ctype = found
        try:
            body = target.read_bytes()
        except (OSError, ValueError):
            self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})
            return
        self._send(HTTPStatus.OK, body, ctype, cache="private, no-cache")

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_ROOT / rel).resolve()
        root = WEB_ROOT.resolve()
        if root not in target.parents or not target.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"introuvable", "text/plain; charset=utf-8")
            return
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        body, etag, gzipped = static_entry(target)
        if etag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Vary", "Accept-Encoding")
            self.end_headers()
            return
        self._send(HTTPStatus.OK, body, ctype, cache="no-cache", etag=etag, gzipped=gzipped)


_STATIC: dict = {}
_STATIC_LOCK = threading.Lock()


def static_entry(target: Path) -> Tuple[bytes, str, Optional[bytes]]:
    """Contenu, ETag et version gzip d'un fichier de `web/`, recalculés seulement
    quand le fichier change (taille/mtime) — pas à chaque requête."""
    st = target.stat()
    key = (str(target), st.st_mtime_ns, st.st_size)
    with _STATIC_LOCK:
        cached = _STATIC.get(key[0])
        if cached and cached[0] == key:
            return cached[1]
    body = target.read_bytes()
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    ctype = CONTENT_TYPES.get(target.suffix, "")
    gzipped = gzip.compress(body, compresslevel=9) if ctype.startswith(COMPRESSIBLE) else None
    with _STATIC_LOCK:
        _STATIC[key[0]] = (key, (body, etag, gzipped))
    return body, etag, gzipped


class Server(ThreadingHTTPServer):
    """`ThreadingHTTPServer` sans résolution DNS inverse au démarrage.

    `HTTPServer.server_bind` appelle `socket.getfqdn(host)` pour remplir
    `server_name` (que nous n'utilisons jamais). Sur une machine dont le
    résolveur traîne — les runners macOS de GitHub, mais aussi un Mac sans
    réseau — cet appel bloque ~35 s avant que le serveur n'écoute.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def bind(port: int, tries: int = 10, listen: str = LOOPBACK) -> Server:
    last = None
    candidates = [0] if port == 0 else range(port, port + tries)
    for candidate in candidates:
        try:
            return Server((listen, candidate), Handler)
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
    # Le premier index (≈ 10 s sur un historique complet avec FIT) se construit en
    # arrière-plan : le serveur écoute tout de suite, la page s'affiche, et les
    # requêtes API attendent la fin de ce passage (`Store.wait_ready`).
    Handler.store = Store(workspace, db, memory, today, background=True)
    httpd = bind(port, listen=listen)
    actual = httpd.server_address[1]
    Handler.allowed_hosts = host_allowlist(actual, extra_hosts)
    config = I.load_config(workspace)
    Handler.chat_port = chat_proxy_port(config, listen)
    origin = tile_origin(I.settings(config)["map_tiles"])
    Handler.tile_src = f" {origin}" if origin else ""
    Handler.store.start_background()
    print(f"URL: http://127.0.0.1:{actual}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        Handler.store.stop_background()
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
