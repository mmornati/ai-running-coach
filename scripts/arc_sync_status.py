#!/usr/bin/env python3
"""État de la synchronisation automatique — lu dans `<workspace>/logs/`, sans réseau ni LLM.

Répond aux questions « est-ce que ça tourne ? quand ? qu'est-ce qui s'est passé ? » :

- configuration `[sync]` (mode `schedule` | `watch`, heures, intervalle, exécuteur) ;
- état du sondage Garmin ou COROS (`logs/.watch-state.json`, écrit par `watch.py`) ;
- runs de `daily-sync.sh` (`logs/sync-YYYY-MM-DD.log` : en-tête `===== … =====` par run,
  pied `===== … fin code=N durée=Ns =====` depuis cette version, bloc ```resume```) ;
- événements du sondage (`logs/watch.log`) ;
- un verdict (`ok` | `running` | `late` | `failing` | `degraded` | `never` | `off`) et la
  prochaine exécution attendue.

La crontab elle-même n'est pas lue : le tableau de bord tourne souvent en conteneur, où elle
est invisible. Un retard se déduit donc des traces : « le sondage n'a pas tourné depuis 2 h ».

Lecture seule. Utilisé par `arc_serve.py` (`/api/sync-status`, vue « Synchro ») et en ligne
de commande :

    python3 scripts/arc_sync_status.py [--workspace W] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE / "scripts"))

HEADER_RE = re.compile(r"^===== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) — runner=(\S+) lookback=(\S+) trigger=(.*?) =====$")
FOOTER_RE = re.compile(r"^===== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) — fin code=(\d+) durée=(\d+)s =====$")
ERROR_RE = re.compile(r"^(PROVIDER-ERREUR|ERREUR|Error|error:|✖)", re.IGNORECASE)
WATCH_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+(.*)$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

DEFAULT_TIMES = ["07:15", "14:15"]
DEFAULT_INTERVAL = 15
LOG_DAYS = 14             # fichiers sync-*.log lus
MAX_RUNS = 40             # runs rendus
MAX_BODIES = 10           # runs dont le journal complet est rendu
MAX_BODY_CHARS = 20000    # par run (la fin, la plus utile)
WATCH_TAIL = 60           # lignes de watch.log rendues
LOCK_STALE_H = 3          # un verrou plus vieux = sync morte sans nettoyage


def _parse_dt(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def _times(raw) -> List[str]:
    if not isinstance(raw, list):
        return list(DEFAULT_TIMES)
    return [t for t in raw if isinstance(t, str) and TIME_RE.match(t)]


def _int(value, default: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def load_settings(workspace: Path) -> dict:
    from arc_index import load_config

    try:
        config = load_config(workspace)
    except Exception:  # TOML invalide : coach_doctor le signale
        config = {}
    sync = config.get("sync") or {}
    source = (config.get("data") or {}).get("source", "garmin")
    mode = sync.get("mode", "schedule")
    if mode not in ("schedule", "watch"):
        mode = "schedule"
    if mode == "watch" and source not in ("garmin", "coros"):  # même repli que install.sh
        mode = "schedule"
    fallback = sync.get("fallback_times", ["21:30"])
    return {
        "mode": mode,
        "runner": sync.get("runner", "claude") or "claude",
        "model": sync.get("model") or None,
        "source": source,
        "times": _times(sync.get("times", DEFAULT_TIMES)),
        "watch_interval_min": _int(sync.get("watch_interval_min"), DEFAULT_INTERVAL),
        "max_runs_per_day": _int(sync.get("max_runs_per_day"), 6),
        "fallback_times": _times(fallback) if isinstance(fallback, list) else ["21:30"],
        "git_autocommit": bool(sync.get("git_autocommit", False)),
    }


# ---------------------------------------------------------------------------
# Journaux
# ---------------------------------------------------------------------------


def _resume(lines: List[str]) -> List[str]:
    out, inside = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```resume"):
            inside, out = True, []
            continue
        if inside and stripped.startswith("```"):
            inside = False
            continue
        if inside and stripped:
            out.append(stripped)
    return out


def parse_sync_log(text: str, log_file: str) -> List[dict]:
    """Runs d'un fichier `sync-YYYY-MM-DD.log`, dans l'ordre du fichier."""
    runs, current, body = [], None, []

    def close():
        if current is None:
            return
        current["resume"] = _resume(body)
        current["errors"] = [l.strip() for l in body if ERROR_RE.match(l.strip())][:5]
        current["_body"] = "\n".join(body).strip()
        runs.append(current)

    for line in text.splitlines():
        header = HEADER_RE.match(line)
        if header:
            close()
            start, runner, lookback, trigger = header.groups()
            current = {"start": _iso(_parse_dt(start)), "runner": runner, "lookback_days": lookback,
                       "trigger": trigger, "log_file": log_file, "end": None, "rc": None, "duration_s": None}
            body = []
            continue
        footer = FOOTER_RE.match(line)
        if footer and current is not None:
            current["end"] = _iso(_parse_dt(footer.group(1)))
            current["rc"] = int(footer.group(2))
            current["duration_s"] = int(footer.group(3))
            continue
        if current is not None:
            body.append(line)
    close()
    return runs


def read_runs(logs: Path, today: date) -> List[dict]:
    runs = []
    for offset in range(LOG_DAYS):
        day = today - timedelta(days=offset)
        path = logs / f"sync-{day.isoformat()}.log"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        runs.extend(parse_sync_log(text, f"logs/{path.name}"))
    runs.sort(key=lambda r: r["start"] or "", reverse=True)
    runs = runs[:MAX_RUNS]
    for i, run in enumerate(runs):
        body = run.pop("_body")
        if i < MAX_BODIES:
            run["log"] = body[-MAX_BODY_CHARS:]
            run["log_truncated"] = len(body) > MAX_BODY_CHARS
    return runs


def read_watch_log(logs: Path) -> List[dict]:
    try:
        lines = (logs / "watch.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-WATCH_TAIL:]:
        m = WATCH_LINE_RE.match(line)
        if m:
            events.append({"at": m.group(1), "message": m.group(2)})
    return list(reversed(events))


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _slot(day: date, hhmm: str) -> datetime:
    h, m = TIME_RE.match(hhmm).groups()
    return datetime(day.year, day.month, day.day, int(h), int(m))


def next_slot(now: datetime, times: List[str]) -> Optional[datetime]:
    slots = sorted(_slot(now.date() + timedelta(days=d), t) for d in (0, 1) for t in times)
    return next((s for s in slots if s > now), None)


def last_slot(now: datetime, times: List[str]) -> Optional[datetime]:
    slots = sorted(_slot(now.date() - timedelta(days=d), t) for d in (0, 1) for t in times)
    past = [s for s in slots if s <= now]
    return past[-1] if past else None


def _ago(minutes: float) -> str:
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {rest:02d}" if rest else f"{hours} h"
    return f"{hours // 24} jours"


def status(workspace: Path, now: Optional[datetime] = None) -> dict:
    now = (now or datetime.now()).replace(microsecond=0)
    settings = load_settings(workspace)
    logs = workspace / "logs"
    state = _read_json(logs / ".watch-state.json")
    runs = read_runs(logs, now.date())
    watch_events = read_watch_log(logs)

    lock = logs / ".sync.lock"
    running_since = None
    if lock.exists():
        try:
            started = datetime.fromtimestamp(lock.stat().st_mtime).replace(microsecond=0)
            if now - started < timedelta(hours=LOCK_STALE_H):
                running_since = started
        except OSError:
            pass

    last = runs[0] if runs else None
    # Les journaux écrits avant le pied de run n'ont pas de code : celui du sondage le donne.
    if last and last["rc"] is None and state.get("last_run") and last["start"]:
        if abs((_parse_dt(state["last_run"]) - _parse_dt(last["start"])).total_seconds()) < 120:
            last["rc"] = state.get("last_run_rc")

    watch = None
    if settings["mode"] == "watch" or state:
        today = now.date().isoformat()
        runs_state = state.get("runs") or {}
        watch = {
            "last_check": state.get("last_check"),
            "last_run": state.get("last_run"),
            "last_run_rc": state.get("last_run_rc"),
            "runs_today": runs_state.get("count", 0) if runs_state.get("date") == today else 0,
            "backoff_until": state.get("backoff_until"),
            "auth_error": state.get("auth_error_date") == today,
        }

    verdict, reason, nxt, nxt_what = "ok", "", None, None
    if settings["mode"] == "watch":
        interval = settings["watch_interval_min"]
        last_check = _parse_dt(state.get("last_check"))
        label = "COROS" if settings["source"] == "coros" else "Garmin"
        nxt_what = f"sondage {label} (sans LLM)"
        nxt = max(last_check + timedelta(minutes=interval), now) if last_check else None
        if not last_check:
            verdict, reason = "never", f"Le sondage {label} n'a encore jamais tourné : la tâche cron/launchd est-elle installée (./install.sh --daily-sync) ?"
        elif now - last_check > timedelta(minutes=3 * interval + 5):
            verdict = "late"
            reason = (f"Dernier sondage il y a {_ago((now - last_check).total_seconds() / 60)} alors qu'il doit passer "
                      f"toutes les {interval} min : la tâche cron/launchd ne tourne plus (machine éteinte, crontab modifiée ?).")
        elif watch and watch["auth_error"]:
            verdict, reason = "failing", (
                "Connexion COROS refusée : python3 scripts/arc_coros_auth.py login (/coach-doctor)."
                if settings["source"] == "coros" else "Tokens Garmin refusés : renouvelez l'authentification (/coach-doctor).")
        elif _parse_dt(state.get("backoff_until")) and _parse_dt(state["backoff_until"]) > now:
            verdict = "degraded"
            reason = f"{label} injoignable : nouvel essai après {state['backoff_until'][11:16]}."
    else:
        nxt, nxt_what = next_slot(now, settings["times"]), "synchronisation planifiée"
        expected = last_slot(now, settings["times"])
        last_start = _parse_dt(last["start"]) if last else None
        if not settings["times"]:
            verdict, reason = "off", "Aucune heure dans [sync].times."
        elif not runs:
            verdict, reason = "never", "Aucun run dans les 14 derniers jours : la tâche cron/launchd est-elle installée (./install.sh --daily-sync) ?"
        elif expected and now - expected > timedelta(minutes=30) and (last_start is None or last_start < expected - timedelta(minutes=5)):
            verdict = "late"
            reason = (f"Aucun run depuis le créneau de {expected.strftime('%H:%M')} "
                      f"({expected.strftime('%d/%m')}) : la tâche cron/launchd a-t-elle tourné ?")
    if verdict in ("ok",) and last and last["rc"] not in (None, 0):
        verdict = "failing"
        reason = f"Le dernier run a échoué (code {last['rc']}) — détail dans {last['log_file']}."
    if running_since and verdict in ("ok", "late", "degraded"):
        verdict, reason = "running", f"Synchronisation en cours depuis {running_since.strftime('%H:%M')}."
    if verdict == "ok":
        if last and last["start"]:
            reason = f"Dernier run il y a {_ago((now - _parse_dt(last['start'])).total_seconds() / 60)}."
        else:
            reason = "Rien d'anormal."

    return {
        "now": _iso(now),
        "settings": settings,
        "verdict": verdict,
        "reason": reason,
        "running_since": _iso(running_since),
        "next": {"at": _iso(nxt), "what": nxt_what} if nxt else None,
        "last_run": {k: last.get(k) for k in ("start", "end", "rc", "duration_s", "trigger", "resume")} if last else None,
        "watch": watch,
        "runs": runs,
        "watch_events": watch_events,
        "log_dir": "logs/",
    }


def _text(st: dict) -> str:
    s = st["settings"]
    label = "COROS" if s.get("source") == "coros" else "Garmin"
    mode = (f"surveillance {label} toutes les {s['watch_interval_min']} min" if s["mode"] == "watch"
            else f"heures fixes {', '.join(s['times']) or '—'}")
    lines = [f"Synchro : {st['verdict']} — {st['reason']}", f"Mode    : {mode} (exécuteur {s['runner']})"]
    if st["next"]:
        lines.append(f"Prochain: {st['next']['at'].replace('T', ' ')} — {st['next']['what']}")
    for run in st["runs"][:8]:
        rc = "?" if run["rc"] is None else run["rc"]
        lines.append(f"  {run['start'].replace('T', ' ')}  code={rc}  {run['trigger']}  ({run['log_file']})")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", help="racine du workspace (sinon ARC_WORKSPACE / pointeur)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from coach_setup import workspace_root

    st = status(workspace_root(args.workspace))
    print(json.dumps(st, ensure_ascii=False, indent=2) if args.json else _text(st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
