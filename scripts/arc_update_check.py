#!/usr/bin/env python3
"""Nouvelle version disponible ? Compare le moteur à la dernière release GitHub.

Une seule vérification, partagée par trois surfaces :

- le tableau de bord (`/api/version` de `arc_serve.py`, bandeau dans l'en-tête) ;
- Claude Code (hook `SessionStart` écrit par `install.sh`, mode `--hook`) ;
- la notification du daily-sync (mode `--notify-once`, puis `--mark-notified` une fois
  l'envoi réussi : une notification perdue est retentée au run suivant).

Réseau : au plus UN appel par 24 h (`releases/latest` de l'API GitHub, délai 3 s),
résultat gardé dans `~/.cache/ai-running-coach/update-check.json`. Rien n'est
envoyé hormis la requête elle-même. Un échec (hors ligne, quota, réponse
inattendue) n'affiche rien, ne casse rien et n'est pas retenté avant 1 h
(mémorisé dans le cache, et en mémoire si le cache n'est pas inscriptible).

Désactivation : `[update].check = false` (ou `"off"`, `"non"`, vide…) dans
`config/workspace.user.toml`, ou `ARC_UPDATE_CHECK=off` dans l'environnement (bac à
sable des tests). Une version locale inconnue ne déclenche aucun appel réseau.

Comparaison : seule une release STRICTEMENT plus récente que la version locale
compte. Un moteur sur `main` après la v1.1.0 (`v1.1.0-24-gaa77fc7`) n'est pas
alerté pour la v1.1.0 ; une version locale inconnue n'alerte jamais.

    python3 scripts/arc_update_check.py                 # une ligne, rien si à jour
    python3 scripts/arc_update_check.py --json --force  # état complet, cache ignoré
    python3 scripts/arc_update_check.py --hook          # contexte Claude Code (SessionStart)
    python3 scripts/arc_update_check.py --notify-once logs/.update-notified
    python3 scripts/arc_update_check.py --mark-notified logs/.update-notified
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_version as V  # noqa: E402
from coach_config import config_paths, read_toml  # noqa: E402

REPOSITORY = "mmornati/ai-running-coach"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
CACHE_TTL_S = 24 * 3600
RETRY_AFTER_FAILURE_S = 3600
TIMEOUT_S = 3
NOTES_MAX_CHARS = 4000
DISABLED_VALUES = {"0", "off", "false", "no", "non"}
UPDATE_COMMAND = "/update-coach"

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
# Suffixe de `git describe` (« -24-gaa77fc7 ») : des commits APRÈS le tag, jamais une pré-version.
_DESCRIBE_SUFFIX = re.compile(r"-\d+-g[0-9a-f]+$")


def parse_version(raw: Optional[str]) -> Optional[tuple]:
    """Clé de tri d'une version (`v1.2.0`, `1.2.0-rc.1`, `v1.1.0-24-gabc1234`), `None` si illisible.

    Une pré-version passe avant la release de même numéro (`1.2.0-rc.1` < `1.2.0`)."""
    if not raw:
        return None
    match = _SEMVER.match(_DESCRIBE_SUFFIX.sub("", raw.strip()))
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def is_newer(latest: Optional[str], current: Optional[str]) -> bool:
    latest_key, current_key = parse_version(latest), parse_version(current)
    return bool(latest_key and current_key and latest_key > current_key)


def enabled(workspace: Optional[Path]) -> bool:
    """`[update].check` (défaut : activé) ; `ARC_UPDATE_CHECK=off` l'emporte toujours."""
    if os.environ.get("ARC_UPDATE_CHECK", "").strip().lower() in DISABLED_VALUES:
        return False
    if workspace is None:
        return True
    for path in config_paths(workspace):
        try:
            section = read_toml(path).get("update", {})
        except Exception:  # TOML invalide : coach_doctor le signale, ici on garde le défaut
            continue
        if "check" in section:
            # Clé présente mais vide = héritage annulé (AGENTS.md) : vide vaut désactivé.
            value = section["check"]
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() not in DISABLED_VALUES | {""}
    return True


def cache_file() -> Path:
    explicit = os.environ.get("ARC_UPDATE_CACHE")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "ai-running-coach" / "update-check.json"


def _read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, data: dict) -> None:
    # Image Docker en lecture seule, HOME absent… : sans cache, on revérifiera simplement plus tard.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass


def fetch_latest(timeout: float = TIMEOUT_S) -> dict:
    """Dernière release publiée (GitHub exclut d'office brouillons et pré-versions)."""
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ai-running-coach/{V.engine_version() or 'inconnue'}",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"réponse inattendue : {type(payload).__name__}")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not parse_version(tag):
        raise ValueError(f"tag de release illisible : {tag!r}")
    return {
        "latest": tag,
        "url": payload.get("html_url") or f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
        "published_at": payload.get("published_at"),
        "notes": (payload.get("body") or "")[:NOTES_MAX_CHARS],
    }


# Dernier échec par fichier de cache, pour un processus long (tableau de bord) dont le cache
# n'est pas inscriptible : sans lui, chaque requête repaierait le délai réseau.
_FAILED_AT: dict = {}


def _recent(stamp, now: float, window: float) -> bool:
    return isinstance(stamp, (int, float)) and 0 <= now - stamp < window


def check(workspace: Optional[Path], *, force: bool = False, now: Optional[float] = None,
          fetch: Callable[[], dict] = fetch_latest, current: Optional[str] = None,
          cache: Optional[Path] = None) -> dict:
    """État de la mise à jour. Ne lève jamais : toute erreur de récupération devient `error`."""
    current = current if current is not None else V.engine_version()
    result = {"enabled": enabled(workspace), "current": current, "latest": None,
              "update_available": False, "url": None, "published_at": None,
              "notes": "", "checked_at": None, "command": UPDATE_COMMAND}
    if not result["enabled"] or not parse_version(current):
        return result  # version locale inconnue : aucune alerte possible, donc aucun appel
    now = time.time() if now is None else now
    path = cache or cache_file()
    cached = _read_cache(path)
    fresh = _recent(cached.get("checked_at"), now, CACHE_TTL_S) and cached.get("latest")
    failed_recently = (_recent(cached.get("failed_at"), now, RETRY_AFTER_FAILURE_S)
                       or _recent(_FAILED_AT.get(path), now, RETRY_AFTER_FAILURE_S))
    if force or not (fresh or failed_recently):
        try:
            cached = {**fetch(), "checked_at": now}
            _FAILED_AT.pop(path, None)
            _write_cache(path, cached)
        except Exception as error:  # réseau, HTTP, JSON inattendu… : jamais d'exception à l'appelant
            result["error"] = str(error) or error.__class__.__name__
            # Échec mémorisé (dernière release connue conservée) : pas de nouvel essai avant 1 h.
            _FAILED_AT[path] = now
            cached = {**cached, "failed_at": now}
            _write_cache(path, cached)
    elif failed_recently and not fresh:
        result["error"] = "échec récent, nouvel essai plus tard"
    for key in ("latest", "url", "published_at", "notes", "checked_at"):
        if cached.get(key) is not None:
            result[key] = cached[key]
    result["update_available"] = is_newer(result["latest"], current)
    return result


def summary_line(state: dict) -> str:
    return (f"ai-running-coach {state['latest']} est disponible (installée : {state['current']}) "
            f"— {state['command']} pour mettre à jour · {state['url']}")


def hook_context(state: dict) -> str:
    """Texte injecté au démarrage d'une session Claude Code (stdout d'un hook SessionStart)."""
    return (f"[ai-running-coach] {summary_line(state)}\n"
            "Mentionne-le une seule fois à l'athlète, en une ligne à la fin de ta première réponse, "
            f"en proposant {state['command']}. Ne lance jamais la mise à jour sans sa demande ; "
            "n'en parle pas pendant une décision médicale ni dans un run headless.")


def _writable(path: Path) -> bool:
    """`path` pourra-t-il être écrit (lui-même, ou son plus proche dossier existant) ?"""
    if path.exists():
        return os.access(path, os.W_OK)
    for parent in path.parents:
        if parent.exists():
            return os.access(parent, os.W_OK)
    return False


def notify_once(state: dict, state_file: Path) -> Optional[str]:
    """Message à envoyer si cette release n'a pas encore été notifiée.

    Ne mémorise rien : l'appelant appelle `mark_notified` APRÈS un envoi réussi, sinon une
    notification perdue (ntfy injoignable) ne serait jamais retentée."""
    if not state["update_available"]:
        return None
    try:
        if state_file.read_text(encoding="utf-8").strip() == state["latest"]:
            return None
    except OSError:
        pass
    if not _writable(state_file):
        return None  # sans mémoire possible, on notifierait à chaque run : mieux vaut se taire
    return summary_line(state)


def mark_notified(state: dict, state_file: Path) -> bool:
    """Mémorise la release comme notifiée (après un envoi réussi)."""
    if not state["update_available"]:
        return False
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(state["latest"] + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, help="workspace dont lire [update].check")
    parser.add_argument("--force", action="store_true", help="ignorer le cache de 24 h")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="état complet en JSON")
    mode.add_argument("--hook", action="store_true", help="contexte pour un hook SessionStart de Claude Code")
    mode.add_argument("--notify-once", type=Path, metavar="FICHIER_ÉTAT",
                      help="une ligne seulement pour une release pas encore notifiée (ne mémorise rien)")
    mode.add_argument("--mark-notified", type=Path, metavar="FICHIER_ÉTAT",
                      help="mémorise la release courante comme notifiée (après un envoi réussi)")
    args = parser.parse_args(argv)

    if args.hook and os.environ.get("ARC_HEADLESS"):
        return 0  # daily-sync : la notification dédiée s'en charge, pas le résumé du modèle
    workspace = args.workspace
    if workspace is not None:
        from coach_config import enforce_workspace_lock   # verrou de la sync (#127)
        workspace = enforce_workspace_lock(workspace)
    if workspace is None:
        try:
            from coach_setup import workspace_root
            workspace = workspace_root()
        except Exception:
            workspace = None
    state = check(workspace, force=args.force)
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=1))
    elif args.hook:
        if state["update_available"]:
            print(hook_context(state))
    elif args.notify_once:
        message = notify_once(state, args.notify_once)
        if message:
            print(message)
    elif args.mark_notified:
        return 0 if mark_notified(state, args.mark_notified) else 1
    elif state["update_available"]:
        print(summary_line(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
