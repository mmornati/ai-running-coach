#!/usr/bin/env python3
"""Surveillance Garmin ou COROS sans LLM — ne lance `daily-sync.sh` que s'il y a du neuf.

Garmin n'offre pas de webhook aux particuliers (le Connect Developer Program est
réservé aux entités légales). On interroge donc Garmin Connect à intervalle
régulier, avec la librairie `garminconnect` déjà installée par `garmin-mcp` et
les tokens Garmin du workspace (`~/.garminconnect` par défaut, ou `GARMINTOKENS` de son
`.mcp.json`, #127) — jamais le LLM. Un passage « rien de neuf » coûte un seul appel HTTP et
zéro token.

À chaque passage (cron/launchd, `[sync].watch_interval_min`) :

1. `get_device_last_used()` — heure du dernier envoi de la montre. Inchangée
   et hors fenêtre de revérification : fin du passage.
2. Sinon, comparaison avec le workspace :
   - `activity:<id>` : une séance récente dont l'identifiant n'apparaît dans
     aucun `activities/*.md` (`garmin_activity_id`) ;
   - `morning` : le sommeil du jour est calculé par Garmin mais
     `medical/<jour>_health.md` n'existe pas (sauf `[health].morning_check = off`).
3. Du neuf : on attend que Garmin ait fini ses calculs (`settle_min` après le
   dernier envoi : score de sommeil, readiness), on respecte `min_gap_min`
   entre deux runs et `max_runs_per_day`, puis on lance
   `daily-sync.sh --trigger <déclencheurs>` (verrou, notifications, git : inchangés).
4. Filet de sécurité : si aucun run n'a eu lieu à une heure de
   `fallback_times`, un run complet part quand même (tokens expirés, watcher
   aveugle…) — c'est aussi lui qui déclenche l'alerte d'expiration des tokens.

État (jetable, hors git) : `logs/.watch-state.json`. Journal : `logs/watch.log`
(uniquement les événements, pas chaque passage « rien de neuf »).

Usage :
    scripts/watch.py              # un passage (appelé par cron/launchd)
    scripts/watch.py --dry-run    # décide, affiche, ne lance rien
    scripts/watch.py --status     # état courant (JSON)

COROS (`[data].source = "coros"`, #168) : même boucle, par le relais du projet
(`scripts/arc_coros_mcp.py`, jetons de `arc_coros_auth.py`, lecture seule). Le MCP COROS n'a
pas d'heure de dernier envoi de la montre : chaque passage lit les séances récentes
(`querySportRecords`, un appel) et, tant que le fichier santé du jour manque, le sommeil
(`querySleepOverview` : « Sleep Score: 0 » = nuit pas encore calculée). La stabilisation
(`settle_min`) part de la première fois qu'une nouveauté est vue.
- `activity:c<LabelId>` : une séance dont le `coros_activity_id` n'apparaît dans aucun
  `activities/*.md` ;
- `morning` : score de sommeil du jour calculé par COROS, fichier santé absent.

Tests : `ARC_WATCH_NOW` (ISO local) fixe l'horloge, `ARC_WATCH_FAKE_GARMIN`
(fichier JSON) remplace Garmin Connect, `ARC_WATCH_FAKE_COROS` (fichier JSON :
textes rendus par les outils COROS) le relais COROS, `ARC_WATCH_SYNC_CMD` la commande lancée.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE / "scripts"))

STATE_REL = "logs/.watch-state.json"
LOG_REL = "logs/watch.log"
ACTIVITY_ID_RE = re.compile(r'"garmin_activity_id"\s*:\s*(\d+)')
COROS_ACTIVITY_ID_RE = re.compile(r'"coros_activity_id"\s*:\s*"(c\d+)"')
# Sources surveillées : celles qui ont une sonde ci-dessous.
WATCHED_SOURCES = ("garmin", "coros")

DEFAULTS = {
    "watch_interval_min": 15,
    "settle_min": 10,
    "min_gap_min": 30,
    "max_runs_per_day": 6,
    "recheck_window_min": 90,
    "fallback_times": ["21:30"],
    "lookback_days": 2,
}
# Un déclencheur encore présent après ce nombre de runs est abandonné (journalisé) :
# une séance que l'agent n'arrive pas à persister ne doit pas relancer le LLM en boucle.
MAX_ATTEMPTS = 2
BACKOFF_BASE_MIN = 15
BACKOFF_MAX_MIN = 240


class AuthError(RuntimeError):
    """Jetons Garmin ou connexion COROS refusés : inutile d'insister avant renouvellement."""


class TransientError(RuntimeError):
    """429, réseau, 5xx : on espace les passages (backoff exponentiel)."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _int(value, default: int, minimum: int = 0) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def load_settings(workspace: Path) -> dict:
    """[sync] + [health].morning_check + [data].source, avec les défauts ci-dessus.

    Une valeur invalide retombe sur son défaut : le watcher tourne sans
    surveillance, il ne doit jamais mourir sur une faute de frappe."""
    from arc_index import load_config

    try:
        config = load_config(workspace)
    except Exception:  # TOML invalide : signalé par coach_doctor, pas ici
        config = {}
    sync = config.get("sync") or {}
    settings = {
        "watch_interval_min": _int(sync.get("watch_interval_min"), DEFAULTS["watch_interval_min"], 1),
        "settle_min": _int(sync.get("settle_min"), DEFAULTS["settle_min"]),
        "min_gap_min": _int(sync.get("min_gap_min"), DEFAULTS["min_gap_min"]),
        "max_runs_per_day": _int(sync.get("max_runs_per_day"), DEFAULTS["max_runs_per_day"], 1),
        "recheck_window_min": _int(sync.get("recheck_window_min"), DEFAULTS["recheck_window_min"]),
        "lookback_days": _int(sync.get("lookback_days"), DEFAULTS["lookback_days"], 1),
        "morning_check": (config.get("health") or {}).get("morning_check", "full"),
        "source": (config.get("data") or {}).get("source", "garmin"),
    }
    fallback = sync.get("fallback_times", DEFAULTS["fallback_times"])
    if not isinstance(fallback, list):
        fallback = DEFAULTS["fallback_times"]
    settings["fallback_times"] = [t for t in fallback if isinstance(t, str) and re.fullmatch(r"\d{1,2}:\d{2}", t)]
    return settings


# ---------------------------------------------------------------------------
# État
# ---------------------------------------------------------------------------


def load_state(workspace: Path) -> dict:
    path = workspace / STATE_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(workspace: Path, state: dict) -> None:
    path = workspace / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def log_event(workspace: Path, now: datetime, message: str) -> None:
    path = workspace / LOG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{now.isoformat(timespec='seconds')} {message}\n")
    if sys.stdout.isatty():
        print(message)


def runs_today(state: dict, today: date) -> int:
    runs = state.get("runs") or {}
    return int(runs.get("count", 0)) if runs.get("date") == today.isoformat() else 0


# ---------------------------------------------------------------------------
# Workspace : ce qui est déjà persisté
# ---------------------------------------------------------------------------


def known_activity_ids(workspace: Path) -> set:
    """Identifiants déjà persistés : entiers Garmin et chaînes COROS (« c » + LabelId)."""
    ids = set()
    for md in (workspace / "activities").glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        ids.update(int(m) for m in ACTIVITY_ID_RE.findall(text))
        ids.update(COROS_ACTIVITY_ID_RE.findall(text))
    return ids


def health_file_exists(workspace: Path, day: date) -> bool:
    return (workspace / "medical" / f"{day.isoformat()}_health.md").is_file()


# ---------------------------------------------------------------------------
# Garmin
# ---------------------------------------------------------------------------


class GarminProbe:
    """Les trois lectures dont le watcher a besoin, rien d'autre."""

    label = "Garmin"
    auth_fix = "uv run garmin-mcp-auth"

    def __init__(self, client):
        self.client = client

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:  # garminconnect lève ses propres types
            name = type(exc).__name__
            text = str(exc)
            if "Authentication" in name or "401" in text:
                raise AuthError(f"{name}: {text}") from exc
            raise TransientError(f"{name}: {text}") from exc

    def last_upload_ms(self):
        data = self._call(self.client.get_device_last_used) or {}
        value = data.get("lastUsedDeviceUploadTime")
        return int(value) if value else None

    def recent_activities(self, limit: int = 10) -> list:
        return self._call(self.client.get_activities, 0, limit) or []

    def sleep_ready(self, day: date) -> bool:
        data = self._call(self.client.get_sleep_data, day.isoformat()) or {}
        dto = data.get("dailySleepDTO") or {}
        return bool(dto.get("sleepTimeSeconds"))


class FakeClient:
    """Garmin simulé depuis un JSON (tests) — mêmes méthodes que `garminconnect.Garmin`."""

    def __init__(self, path: Path):
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def _maybe_fail(self):
        error = self.data.get("error")
        if error == "auth":
            raise RuntimeError("GarminConnectAuthenticationError: 401 Client Error: Unauthorized")
        if error:
            raise RuntimeError(f"GarminConnectTooManyRequestsError: {error}")

    def get_device_last_used(self):
        self._maybe_fail()
        return {"lastUsedDeviceUploadTime": self.data.get("upload_ms")}

    def get_activities(self, start, limit):
        self._maybe_fail()
        return self.data.get("activities", [])[start:start + limit]

    def get_sleep_data(self, day):
        self._maybe_fail()
        return {"dailySleepDTO": {"sleepTimeSeconds": (self.data.get("sleep") or {}).get(day, 0)}}


# Formes relevées le 22-23/10/2026 (docs/coros.md) : une séance par bloc numéroté
# « 1. Outdoor Run — 2026-10-22 » … « LabelId: 481221836600803431 | SportType: 100 ».
_COROS_RECORD_RE = re.compile(r"^\s*\d+\.\s.*?(\d{4}-\d{2}-\d{2})\s*$")
_COROS_LABEL_RE = re.compile(r"LabelId:\s*(\d+)")
_COROS_SLEEP_SCORE_RE = re.compile(r"Sleep Score:\s*(\d+)")


class CorosProbe:
    """Mêmes lectures que `GarminProbe`, par le relais COROS du projet (sans IA, lecture seule)."""

    label = "COROS"
    auth_fix = "python3 scripts/arc_coros_auth.py login"

    def __init__(self, client):
        self.client = client

    def _call(self, tool: str, arguments: dict) -> str:
        try:
            return self.client.call(tool, arguments)
        except Exception as exc:  # CallError du relais, ou panne inattendue
            if getattr(exc, "login_required", False):
                raise AuthError(str(exc)) from exc
            raise TransientError(str(exc)) from exc

    def last_upload_ms(self):
        """Le MCP COROS n'expose pas l'heure du dernier envoi de la montre."""
        return None

    def recent_activities(self, days: int = 2, limit: int = 10, today: date = None) -> list:
        """`[("c<LabelId>", jour de début)]` des `days` derniers jours (dates du compte COROS).
        Un couple, et non un objet Garmin : `detect_triggers` accepte les deux formes."""
        today = today or _now().date()
        text = self._call("querySportRecords", {
            "startDate": (today - timedelta(days=max(days, 1) - 1)).strftime("%Y%m%d"),
            "endDate": today.strftime("%Y%m%d"), "limit": limit})
        out, day = [], None
        for line in text.splitlines():
            record = _COROS_RECORD_RE.match(line)
            if record:
                day = record.group(1)
                continue
            label = _COROS_LABEL_RE.search(line)
            if label and day:
                out.append((f"c{label.group(1)}", day))
                day = None
        return out

    def sleep_ready(self, day: date) -> bool:
        """Nuit calculée : score de sommeil > 0 au jour du réveil (0 = « not available yet »)."""
        text = self._call("querySleepOverview", {"startDate": day.strftime("%Y%m%d"),
                                                 "endDate": day.strftime("%Y%m%d")})
        match = _COROS_SLEEP_SCORE_RE.search(text)
        return bool(match and int(match.group(1)) > 0)


class FakeCoros:
    """Relais COROS simulé depuis un JSON (tests) : `{"error": "auth"|"…", "tools": {nom: texte}}`."""

    def __init__(self, path: Path):
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def call(self, tool: str, arguments: dict) -> str:
        error = self.data.get("error")
        if error == "auth":
            exc = RuntimeError("COROS : COROS non connecté — lancez : python3 scripts/arc_coros_auth.py login")
            exc.login_required = True
            raise exc
        if error:
            raise RuntimeError(f"COROS : {error}")
        return (self.data.get("tools") or {}).get(tool, "")


def _ensure_garminconnect(argv: list) -> None:
    """Relance avec le python de garmin-mcp si `garminconnect` est absent (cf. download_fit.py)."""
    try:
        import garminconnect  # noqa: F401
        return
    except ImportError:
        pass
    exe = shutil.which("garmin-mcp")
    # Le python du venv est souvent un lien vers le MÊME binaire que python3
    # système (seul sys.prefix diffère) : on ne compare pas les chemins réels,
    # un marqueur d'environnement suffit à éviter une relance en boucle.
    if exe and not os.environ.get("ARC_WATCH_REEXEC"):
        bindir = os.path.dirname(os.path.realpath(exe))
        for name in ("python3", "python"):
            py = os.path.join(bindir, name)
            if os.path.exists(py):
                env = dict(os.environ, ARC_WATCH_REEXEC="1")
                sys.exit(subprocess.run([py, os.path.abspath(__file__), *argv], env=env).returncode)
    print("ERREUR : module 'garminconnect' introuvable (garmin-mcp installé ?)", file=sys.stderr)
    sys.exit(2)


def make_probe(source: str = "garmin", workspace: Path | None = None):
    if source == "coros":
        fake_coros = os.environ.get("ARC_WATCH_FAKE_COROS")
        if fake_coros:
            return CorosProbe(FakeCoros(Path(fake_coros)))
        os.environ["COROS_READ_ONLY"] = "1"  # le watcher ne fait que lire
        import arc_coros_mcp

        return CorosProbe(arc_coros_mcp.Client(name="ai-running-coach/watch"))
    fake = os.environ.get("ARC_WATCH_FAKE_GARMIN")
    if fake:
        return GarminProbe(FakeClient(Path(fake)))
    from garminconnect import Garmin
    from arc_credentials import garmin_tokens_dir
    from coach_setup import workspace_root

    # Jetons DU workspace (GARMINTOKENS de son .mcp.json, #127), sinon ~/.garminconnect comme avant.
    tokens = garmin_tokens_dir(None, workspace if workspace is not None else workspace_root())
    client = Garmin()
    try:
        client.login(str(tokens))
    except Exception as exc:
        name = type(exc).__name__
        if "Authentication" in name or "401" in str(exc):
            raise AuthError(f"{name}: {exc}") from exc
        raise TransientError(f"{name}: {exc}") from exc
    return GarminProbe(client)


# ---------------------------------------------------------------------------
# Décision
# ---------------------------------------------------------------------------


def probe_fix(source: str) -> str:
    """Commande de renouvellement de la connexion, par source."""
    return CorosProbe.auth_fix if source == "coros" else GarminProbe.auth_fix


def detect_triggers(probe, workspace: Path, settings: dict, today: date) -> list:
    """Ce que la source a et que le workspace n'a pas encore."""
    triggers = []
    oldest = today - timedelta(days=settings["lookback_days"] - 1)
    known = known_activity_ids(workspace)
    recent = (probe.recent_activities(days=settings["lookback_days"], today=today) if isinstance(probe, CorosProbe)
              else probe.recent_activities())
    for item in recent:
        if isinstance(item, dict):  # Garmin : identifiant entier, début en heure locale
            activity_id = int(item["activityId"]) if item.get("activityId") else None
            start = str(item.get("startTimeLocal") or "")[:10]
        else:                       # COROS : ("c<LabelId>", "AAAA-MM-JJ")
            activity_id, start = item
        if not activity_id or not start:
            continue
        try:
            started = date.fromisoformat(start)
        except ValueError:
            continue
        if started >= oldest and activity_id not in known:
            triggers.append(f"activity:{activity_id}")
    if settings["morning_check"] != "off" and not health_file_exists(workspace, today):
        if probe.sleep_ready(today):
            triggers.append("morning")
    return sorted(triggers)


def _minutes_since(now: datetime, iso) -> float:
    if not iso:
        return float("inf")
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds() / 60
    except ValueError:
        return float("inf")


def _attempt_key(trigger: str, today: date) -> str:
    # « morning » vaut pour un jour donné ; une séance a son identifiant.
    return f"morning:{today.isoformat()}" if trigger == "morning" else trigger


def _prune_attempts(state: dict, today: date) -> None:
    """Rien de neuf : les tentatives passées n'ont plus d'objet (sauf le matin du jour)."""
    keep = {k: v for k, v in (state.get("attempts") or {}).items() if k == f"morning:{today.isoformat()}"}
    if keep:
        state["attempts"] = keep
    else:
        state.pop("attempts", None)
    state.pop("given_up_logged", None)


def synced_today_elsewhere(workspace: Path, today: date) -> bool:
    """Un daily-sync a déjà tourné aujourd'hui hors du watcher (session mobile,
    lancement manuel, ancien cron à heures fixes le jour de la bascule) :
    `daily-sync.sh` ouvre chaque run par un en-tête « ===== » dans
    `logs/sync-<jour>.log`."""
    path = workspace / "logs" / f"sync-{today.isoformat()}.log"
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return any(line.startswith("===== ") for line in fh)
    except OSError:
        return False


def fallback_due(settings: dict, state: dict, now: datetime, workspace: Path) -> bool:
    """Aucun run aujourd'hui (du watcher ou d'ailleurs) et une heure de repli est passée."""
    if runs_today(state, now.date()) > 0 or state.get("fallback_date") == now.date().isoformat():
        return False
    if synced_today_elsewhere(workspace, now.date()):
        return False
    for t in settings["fallback_times"]:
        hour, minute = (int(x) for x in t.split(":"))
        if now >= now.replace(hour=hour, minute=minute, second=0, microsecond=0):
            return True
    return False


def tick(workspace: Path, now: datetime, probe_factory, run_sync, dry_run: bool = False) -> dict:
    """Un passage. Retourne {'action': ..., 'triggers': [...], 'reason': ...}.

    `probe_factory()` → GarminProbe ou CorosProbe ; `run_sync(triggers)` → code de retour.
    Séparés pour être remplacés dans les tests."""
    settings = load_settings(workspace)
    state = load_state(workspace)
    today = now.date()
    state["last_check"] = now.isoformat(timespec="seconds")
    result = {"action": "none", "triggers": [], "reason": ""}

    def log(message: str):
        if dry_run:
            print(message)
        else:
            log_event(workspace, now, message)

    def finish(action: str, reason: str, triggers=None):
        result.update(action=action, reason=reason, triggers=triggers or [])
        if not dry_run:
            save_state(workspace, state)
        return result

    def launch(triggers: list, reason: str):
        if dry_run:
            return finish("sync", reason + " (dry-run)", triggers)
        log(f"sync lancée — {reason} — déclencheurs : {','.join(triggers) or 'aucun'}")
        state["runs"] = {"date": today.isoformat(), "count": runs_today(state, today) + 1}
        state["last_run"] = now.isoformat(timespec="seconds")
        state.pop("pending", None)
        state.pop("pending_since", None)
        for t in triggers:
            key = _attempt_key(t, today)
            state.setdefault("attempts", {})[key] = state["attempts"].get(key, 0) + 1
        save_state(workspace, state)  # avant le run : un run long ne doit pas être relancé en double
        rc = run_sync(triggers)
        state["last_run_rc"] = rc
        if rc != 0:
            log(f"daily-sync terminé en erreur (code {rc})")
        return finish("sync", reason, triggers)

    if settings["source"] not in WATCHED_SOURCES:
        return finish("skip", "[data].source n'est ni garmin ni coros — surveillance non applicable")
    label = "COROS" if settings["source"] == "coros" else "Garmin"

    if _minutes_since(now, state.get("backoff_until")) < 0:
        return finish("skip", f"backoff jusqu'à {state['backoff_until']}")

    try:
        probe = probe_factory()
        upload_ms = probe.last_upload_ms()
        upload_changed = upload_ms is not None and upload_ms != state.get("last_upload_ms")
        if upload_changed:
            state["last_upload_ms"] = upload_ms
            state["upload_seen_at"] = now.isoformat(timespec="seconds")
        in_recheck = _minutes_since(now, state.get("upload_seen_at")) <= settings["recheck_window_min"]
        triggers = []
        # Sans heure de dernier envoi (COROS), la liste des séances EST le signal : lue à chaque passage.
        if upload_ms is None or upload_changed or in_recheck or state.get("pending"):
            triggers = detect_triggers(probe, workspace, settings, today)
    except AuthError as exc:
        state.pop("errors", None)
        if state.get("auth_error_date") != today.isoformat():
            state["auth_error_date"] = today.isoformat()
            log(f"connexion {label} refusée — {exc}")
        # Le run de repli relaiera l'alerte (daily-sync → notification tokens).
        if fallback_due(settings, state, now, workspace):
            state["fallback_date"] = today.isoformat()
            return launch([], "repli (tokens refusés)")
        return finish("error", f"connexion {label} refusée — {probe_fix(settings['source'])}")
    except TransientError as exc:
        errors = int(state.get("errors", 0)) + 1
        state["errors"] = errors
        wait = min(BACKOFF_BASE_MIN * 2 ** (errors - 1), BACKOFF_MAX_MIN)
        state["backoff_until"] = (now + timedelta(minutes=wait)).isoformat(timespec="seconds")
        log(f"{label} injoignable ({exc}) — prochain essai dans {wait} min")
        return finish("error", f"{label} injoignable, backoff {wait} min")

    state.pop("errors", None)
    state.pop("backoff_until", None)
    state.pop("auth_error_date", None)

    attempts = state.setdefault("attempts", {})
    given_up = [t for t in triggers if attempts.get(_attempt_key(t, today), 0) >= MAX_ATTEMPTS]
    if given_up:
        if state.get("given_up_logged") != given_up:
            log(f"abandon après {MAX_ATTEMPTS} runs sans effet : {','.join(given_up)}")
            state["given_up_logged"] = given_up
        triggers = [t for t in triggers if t not in given_up]

    if triggers:
        if triggers != state.get("pending"):
            log(f"nouveautés {label} : {','.join(triggers)}")
        if not state.get("pending"):
            state["pending_since"] = now.isoformat(timespec="seconds")
        state["pending"] = triggers
        if upload_ms is None:
            # COROS : la stabilisation part de la première détection (aucune heure d'envoi).
            upload_age = _minutes_since(now, state.get("pending_since"))
        else:
            upload_age = (now.timestamp() * 1000 - upload_ms) / 60000
        if upload_age < settings["settle_min"]:
            return finish("wait", f"stabilisation {label} ({upload_age:.0f}/{settings['settle_min']} min)", triggers)
        if _minutes_since(now, state.get("last_run")) < settings["min_gap_min"]:
            return finish("wait", f"écart minimal entre deux runs ({settings['min_gap_min']} min)", triggers)
        if runs_today(state, today) >= settings["max_runs_per_day"]:
            return finish("wait", f"plafond journalier atteint ({settings['max_runs_per_day']} runs)", triggers)
        return launch(triggers, f"nouveautés {label}")

    state.pop("pending", None)
    state.pop("pending_since", None)
    _prune_attempts(state, today)
    if fallback_due(settings, state, now, workspace):
        state["fallback_date"] = today.isoformat()
        return launch([], "repli : aucun run aujourd'hui")
    return finish("none", "rien de neuf")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _now() -> datetime:
    override = os.environ.get("ARC_WATCH_NOW")
    return datetime.fromisoformat(override) if override else datetime.now()


def _sync_runner(workspace: Path):
    def run(triggers: list) -> int:
        custom = os.environ.get("ARC_WATCH_SYNC_CMD")
        cmd = shlex.split(custom) if custom else [str(ENGINE / "scripts/daily-sync.sh")]
        if triggers:
            cmd += ["--trigger", ",".join(triggers)]
        env = dict(os.environ, ARC_WORKSPACE=str(workspace))
        return subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

    return run


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", help="racine du workspace (sinon ARC_WORKSPACE / pointeur)")
    parser.add_argument("--dry-run", action="store_true", help="décide et affiche, ne lance rien, n'écrit pas l'état")
    parser.add_argument("--status", action="store_true", help="affiche l'état courant (JSON)")
    args = parser.parse_args(argv)

    # cron démarre avec un PATH minimal : garmin-mcp vit dans ~/.local/bin.
    os.environ["PATH"] = os.pathsep.join(
        [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "")]
    )
    from coach_setup import workspace_root

    workspace = workspace_root(args.workspace)
    if args.status:
        print(json.dumps({"workspace": str(workspace), **load_state(workspace)}, indent=2, sort_keys=True))
        return 0
    source = load_settings(workspace)["source"]
    if source == "garmin" and not os.environ.get("ARC_WATCH_FAKE_GARMIN"):
        _ensure_garminconnect(argv)

    result = tick(workspace, _now(), lambda: make_probe(source, workspace), _sync_runner(workspace), dry_run=args.dry_run)
    if args.dry_run or sys.stdout.isatty():
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
