#!/usr/bin/env python3
"""coach_doctor.py — diagnostic d'installation en une commande (issue #31).

Vérifie l'installation SANS RIEN ÉCRIRE ni appeler le réseau : âge/échéance
des tokens Garmin, joignabilité du MCP `garmin` (handshake léger, borné dans
le temps), validité TOML de `config/workspace*.toml`, complétude du profil
athlète (FC max / FC de repos), fraîcheur de l'index dérivé `.arc/coach.db`,
nombre de fichiers hors contrat, planification du daily-sync (cron/launchd),
configuration ntfy.

Usage :
    scripts/coach_doctor.py                 # tableau ✅/⚠️/❌ en français
    scripts/coach_doctor.py --json          # sortie machine (schéma ci-dessous)
    scripts/coach_doctor.py --workspace DIR
    scripts/coach_doctor.py --now 2026-09-24T12:00:00+00:00   # horloge injectable
    scripts/coach_doctor.py --tokens-dir DIR                  # override ~/.garminconnect

Aucun champ de ce script n'affiche jamais le CONTENU d'un token — seuls des
métadonnées (chemins, dates d'échéance, nombre de jours restants) apparaissent
en sortie, table ou JSON.

Code de sortie : **1** si au moins une vérification est ❌ (`status: "error"`),
sinon **0** — un avertissement (`warning`) ou une information (`info`) ne fait
jamais échouer la commande : ce sont des dégradations connues (RPE de repli,
notifications désactivées, daily-sync non installé...), pas des pannes.

SCHÉMA JSON (`--json`) — réutilisé tel quel par la story #32 (alerte ntfy
avant expiration des tokens, qui appelle ce script avec `--json`) :

    {
      "generated_at": "<ISO8601>",
      "workspace": "<chemin absolu>",
      "ok": <bool>,                    # aucune vérification en "error"
      "checks": [
        {
          "id": "garmin_token" | "garmin_mcp" | "config_files"
                | "athlete_profile" | "index_freshness" | "out_of_contract"
                | "daily_sync_scheduled" | "ntfy_configured",
          "status": "ok" | "warning" | "error" | "info",
          "message": "<texte français>",
          "fix": "<commande de correction>" | null
          # + champs spécifiques à certains checks, voir ci-dessous
        }, ...
      ]
    }

Champs spécifiques à `garmin_token` (consommés par #32) :
    "expires_at": "<ISO8601>" | null,   # échéance estimée
    "days_left": <int> | null,          # jours restants (négatif = expiré)
    "source": "explicit" | "mtime_fallback" | "missing"

Méthode de détection de l'échéance des tokens (voir docs/troubleshooting.md
et l'investigation en commentaire de `check_garmin_token`) :
  1. `~/.garminconnect/oauth2_token.json` (format `garth`, utilisé par
     certaines installations de `garminconnect`) : champ EXPLICITE
     `refresh_token_expires_at` (epoch secondes) — signal le plus fiable.
  2. À défaut, `~/.garminconnect/garmin_tokens.json` (format du client vendored
     de `garmin-mcp`, qui ne persiste que `di_token`/`di_refresh_token`/
     `di_client_id`, sans échéance longue durée explicite) : repli sur la date
     de dernière modification du fichier + une fenêtre de validité d'environ
     **6 mois** (`TOKEN_VALIDITY_FALLBACK_DAYS`), documentée dans
     `docs/troubleshooting.md` (« Les tokens Garmin sont valides environ 6
     mois »). C'est une hypothèse, pas une garantie Garmin : documentée ici et
     dans le fix suggéré.

Bibliothèque standard uniquement (voir CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_index  # noqa: E402
from coach_config import ConfigError, read_toml  # noqa: E402
from coach_setup import workspace_root  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

STATUS_ICON = {"ok": "✅", "warning": "⚠️", "error": "❌", "info": "ℹ️"}
STATUS_ORDER = {"error": 0, "warning": 1, "info": 2, "ok": 3}

# Cf. docstring du module : hypothèse documentée, pas une garantie Garmin.
TOKEN_VALIDITY_FALLBACK_DAYS = 182
TOKEN_WARNING_THRESHOLD_DAYS = 14

# Borne dure sur le handshake MCP (voir check_garmin_mcp) : un `garmin-mcp
# stdio` qui ne répond pas dans ce délai est traité comme un avertissement,
# jamais comme un blocage de la commande.
MCP_HANDSHAKE_TIMEOUT_S = 3.0

CRON_MARKER = "# ai-running-coach daily-sync"
LAUNCHD_PLIST_REL = "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist"

GARMIN_MCP_INSTALL_FIX = "uv tool install --python 3.12 git+https://github.com/Taxuspt/garmin_mcp"


def build_check(check_id: str, status: str, message: str, fix: Optional[str], **extra: Any) -> dict:
    payload = {"id": check_id, "status": status, "message": message, "fix": fix}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# garmin_token
# ---------------------------------------------------------------------------


def _mtime_fallback(path: Path) -> datetime:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime + timedelta(days=TOKEN_VALIDITY_FALLBACK_DAYS)


def _explicit_expiry(oauth2_path: Path) -> Optional[datetime]:
    """Champ `refresh_token_expires_at` d'un `oauth2_token.json` façon `garth`.

    Vérifié sur un fichier réel (`~/.garminconnect/oauth2_token.json`) : c'est
    un entier epoch-secondes, jamais le contenu du token lui-même — rien ici
    ne lit `access_token`/`refresh_token`.
    """
    try:
        data = json.loads(oauth2_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = data.get("refresh_token_expires_at")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    return None


def check_garmin_token(now: datetime, tokens_dir: Path) -> dict:
    check_id = "garmin_token"
    oauth2 = tokens_dir / "oauth2_token.json"
    legacy = tokens_dir / "garmin_tokens.json"

    expires_at: Optional[datetime]
    source: str

    if oauth2.is_file():
        expires_at = _explicit_expiry(oauth2)
        if expires_at is not None:
            source = "explicit"
        else:
            expires_at = _mtime_fallback(oauth2)
            source = "mtime_fallback"
    elif legacy.is_file():
        expires_at = _mtime_fallback(legacy)
        source = "mtime_fallback"
    else:
        return build_check(
            check_id, "error",
            f"Tokens Garmin absents ({tokens_dir}) — première authentification requise.",
            fix="uv run garmin-mcp-auth",
            expires_at=None, days_left=None, source="missing",
        )

    days_left = (expires_at - now).days
    if days_left < 0:
        status = "error"
        message = f"Tokens Garmin expirés depuis {abs(days_left)} jour(s) ({tokens_dir})."
    elif days_left < TOKEN_WARNING_THRESHOLD_DAYS:
        status = "warning"
        message = f"Tokens Garmin : encore {days_left} jour(s) avant échéance."
    else:
        status = "ok"
        message = f"Tokens Garmin valides ({days_left} jour(s) restants)."
    fix = "uv run garmin-mcp-auth" if status != "ok" else None
    return build_check(
        check_id, status, message, fix,
        expires_at=expires_at.isoformat(), days_left=days_left, source=source,
    )


# ---------------------------------------------------------------------------
# garmin_mcp
# ---------------------------------------------------------------------------


def _resolve_mcp_server(workspace: Path) -> dict:
    default = {"command": "garmin-mcp", "args": ["stdio"], "env": {}}
    mcp_json = workspace / ".mcp.json"
    if not mcp_json.is_file():
        return default
    try:
        data = json.loads(mcp_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    server = data.get("mcpServers", {}).get("garmin")
    if not isinstance(server, dict):
        return default
    return {
        "command": server.get("command", default["command"]),
        "args": server.get("args", default["args"]),
        "env": server.get("env", {}) or {},
    }


def _read_line_with_timeout(proc: subprocess.Popen, request: str, timeout_s: float) -> str:
    try:
        proc.stdin.write(request.encode("utf-8"))
        proc.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    try:
        proc.stdin.close()
    except (OSError, ValueError):
        pass

    result: "queue.Queue[bytes]" = queue.Queue(maxsize=1)

    def _reader() -> None:
        try:
            result.put(proc.stdout.readline())
        except (OSError, ValueError):
            result.put(b"")

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    try:
        line = result.get(timeout=timeout_s)
    except queue.Empty:
        return ""
    return line.decode("utf-8", errors="replace").strip()


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _looks_like_mcp_reply(line: str) -> bool:
    if not line:
        return False
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(obj, dict) and obj.get("jsonrpc") == "2.0" and ("result" in obj or "error" in obj)


def check_garmin_mcp(workspace: Path) -> dict:
    """MCP `garmin` joignable : un handshake `initialize` léger et borné.

    Pourquoi pas un vrai appel Garmin (ex. `get_activities`) : install.sh le
    dit déjà (« pas de garmin-mcp --version : cela démarre le serveur stdio et
    bloque ») — un appel authentifié en plus serait lent, consommerait le
    quota Garmin, et échouerait pour une tout autre raison (identifiants) que
    ce que ce check veut mesurer : « le binaire est installé et parle MCP ».
    Le handshake `initialize` JSON-RPC (une ligne écrite sur stdin, une ligne
    lue sur stdout, borné à MCP_HANDSHAKE_TIMEOUT_S) suffit à distinguer
    « absent », « présent mais muet » et « répond correctement », sans jamais
    contacter Garmin Connect.
    """
    check_id = "garmin_mcp"
    server = _resolve_mcp_server(workspace)
    command_path = shutil.which(server["command"])
    if not command_path:
        return build_check(
            check_id, "error",
            f"Commande MCP « {server['command']} » introuvable dans le PATH.",
            fix=GARMIN_MCP_INSTALL_FIX,
        )

    argv = [command_path, *server.get("args", [])]
    env = dict(os.environ)
    env.update(server.get("env", {}))
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "coach-doctor", "version": "1.0"},
        },
    }) + "\n"

    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env,
        )
    except OSError as exc:
        return build_check(
            check_id, "error", f"Impossible de lancer « {server['command']} » : {exc}",
            fix=GARMIN_MCP_INSTALL_FIX,
        )

    try:
        reply = _read_line_with_timeout(proc, request, MCP_HANDSHAKE_TIMEOUT_S)
    finally:
        _terminate(proc)

    if _looks_like_mcp_reply(reply):
        return build_check(check_id, "ok", "MCP garmin joignable (handshake « initialize » réussi).", fix=None)
    return build_check(
        check_id, "warning",
        "MCP garmin : commande présente mais aucune réponse MCP valide reçue dans le délai imparti "
        f"({MCP_HANDSHAKE_TIMEOUT_S:.0f}s) — vérifiez « garmin-mcp stdio » manuellement.",
        fix="garmin-mcp stdio",
    )


# ---------------------------------------------------------------------------
# config_files
# ---------------------------------------------------------------------------


def check_config_files(workspace: Path) -> dict:
    check_id = "config_files"
    checked, problems = [], []
    for rel in ("config/workspace.toml", "config/workspace.user.toml"):
        path = workspace / rel
        if not path.is_file():
            continue
        checked.append(rel)
        try:
            read_toml(path)
        except ConfigError as exc:
            problems.append(f"{rel} : {exc}")
    if not checked:
        return build_check(
            check_id, "error", "Aucun fichier config/workspace.toml trouvé.", fix="./install.sh",
        )
    if problems:
        return build_check(
            check_id, "error", "TOML invalide — " + " ; ".join(problems),
            fix="corrigez le fichier signalé puis relancez `coach doctor`",
        )
    return build_check(check_id, "ok", f"Configuration TOML valide ({', '.join(checked)}).", fix=None)


# ---------------------------------------------------------------------------
# athlete_profile
# ---------------------------------------------------------------------------


def _bullet_filled(text: str, label: str) -> bool:
    pattern = re.compile(rf"^- \*\*{re.escape(label)}\*\*\s*:\s*(.*)$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return False
    value = re.sub(r"<!--.*?-->", "", match.group(1)).strip()
    return bool(value)


def check_athlete_profile(workspace: Path, config: dict) -> dict:
    check_id = "athlete_profile"
    rel = config.get("athlete", {}).get("profile", "planning/Runner_Profile.md")
    path = workspace / rel
    if not path.is_file():
        return build_check(
            check_id, "warning", f"Profil athlète introuvable ({rel}) — lancez /coach-setup.",
            fix="/coach-setup",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    hr_max = _bullet_filled(text, "FC max")
    hr_rest = _bullet_filled(text, "FC de repos de référence")
    if hr_max and hr_rest:
        return build_check(check_id, "ok", "FC max et FC de repos renseignées dans le profil.", fix=None)
    missing = [name for name, present in (("FC max", hr_max), ("FC de repos", hr_rest)) if not present]
    return build_check(
        check_id, "info",
        f"{' et '.join(missing)} absente(s) du profil ({rel}) — le coach basculera sur le RPE pour la charge.",
        fix=f"complétez {rel}",
    )


# ---------------------------------------------------------------------------
# index_freshness / out_of_contract — lecture seule de .arc/coach.db
# ---------------------------------------------------------------------------


def _newest_workspace_mtime(workspace: Path) -> Optional[float]:
    newest = None
    for rel in arc_index.DATA_DIRS:
        directory = workspace / rel
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.md"):
            mtime = path.stat().st_mtime
            if newest is None or mtime > newest:
                newest = mtime
    return newest


def check_index_freshness(workspace: Path) -> dict:
    check_id = "index_freshness"
    db_path = workspace / arc_index.DEFAULT_DB
    if not db_path.is_file():
        return build_check(
            check_id, "info", "Index .arc/coach.db jamais construit.",
            fix="python3 scripts/arc_index.py",
        )
    newest = _newest_workspace_mtime(workspace)
    if newest is None:
        return build_check(check_id, "ok", "Aucun fichier de données à indexer.", fix=None)
    # Marge d'une seconde contre les égalités de mtime dues à la résolution du
    # système de fichiers (certains FS n'ont qu'une précision à la seconde).
    if db_path.stat().st_mtime + 1 < newest:
        return build_check(
            check_id, "warning", "Index .arc/coach.db plus ancien qu'au moins un fichier du workspace.",
            fix="python3 scripts/arc_index.py",
        )
    return build_check(check_id, "ok", "Index .arc/coach.db à jour.", fix=None)


def check_out_of_contract(workspace: Path) -> dict:
    """Compte les fichiers hors contrat via une connexion sqlite EXPLICITEMENT
    en lecture seule (`mode=ro` + `PRAGMA query_only`) — jamais de réindexation
    ici : ce script ne doit rien écrire (voir docstring du module).
    """
    check_id = "out_of_contract"
    db_path = workspace / arc_index.DEFAULT_DB
    if not db_path.is_file():
        return build_check(
            check_id, "info", "Index absent — comptage des fichiers hors contrat impossible.",
            fix="python3 scripts/arc_index.py",
        )
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only = 1")
            row = conn.execute(
                "SELECT COUNT(*) FROM source_file WHERE kind IS NOT NULL "
                "AND kind NOT IN ('athlete', 'objective') AND parsed_ok != 'ok'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return build_check(
            check_id, "warning", f"Index .arc/coach.db illisible ({exc}).",
            fix="python3 scripts/arc_index.py --rebuild",
        )
    count = row[0] if row else 0
    if count == 0:
        return build_check(check_id, "ok", "Aucun fichier hors contrat.", fix=None)
    return build_check(
        check_id, "warning", f"{count} fichier(s) hors contrat ```arc.",
        fix="python3 scripts/arc_index.py backfill-plan",
    )


# ---------------------------------------------------------------------------
# daily_sync_scheduled
# ---------------------------------------------------------------------------


def _uname() -> str:
    # ARC_FAKE_UNAME : même levier que tests/lib/stubs/uname, pour tester le
    # chemin launchd depuis Linux et inversement (tests/README.md).
    override = os.environ.get("ARC_FAKE_UNAME")
    if override:
        return override
    try:
        out = subprocess.run(["uname", "-s"], capture_output=True, text=True, timeout=3)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return platform.system()


def check_daily_sync(home: Path) -> dict:
    """Jamais plus sévère qu'« info » : un daily-sync non installé est un choix
    valide (synchronisation manuelle), pas une panne — voir issue #31.
    """
    check_id = "daily_sync_scheduled"
    if _uname() == "Darwin":
        plist = home / LAUNCHD_PLIST_REL
        if plist.is_file():
            return build_check(check_id, "ok", f"LaunchAgent daily-sync installé ({plist}).", fix=None)
        return build_check(
            check_id, "info", "Aucun LaunchAgent daily-sync — synchronisation Garmin manuelle uniquement.",
            fix="./install.sh --daily-sync",
        )
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return build_check(
            check_id, "info", "crontab injoignable — synchronisation Garmin manuelle uniquement.",
            fix="./install.sh --daily-sync",
        )
    if out.returncode == 0 and CRON_MARKER in out.stdout:
        return build_check(check_id, "ok", "Tâche cron daily-sync présente.", fix=None)
    return build_check(
        check_id, "info", "Aucune tâche cron daily-sync — synchronisation Garmin manuelle uniquement.",
        fix="./install.sh --daily-sync",
    )


# ---------------------------------------------------------------------------
# ntfy_configured
# ---------------------------------------------------------------------------


def check_ntfy(config: dict) -> dict:
    check_id = "ntfy_configured"
    notifications = config.get("notifications", {})
    provider = notifications.get("provider", "none")
    if provider == "none":
        return build_check(
            check_id, "info", 'Notifications désactivées ([notifications].provider = "none").', fix=None,
        )
    if provider != "ntfy":
        return build_check(
            check_id, "warning", f"Fournisseur de notification inconnu : « {provider} ».",
            fix="scripts/setup-ntfy.sh",
        )
    topic = notifications.get("ntfy_topic", "")
    if not topic:
        return build_check(
            check_id, "warning", "ntfy activé mais aucun topic configuré.", fix="scripts/setup-ntfy.sh",
        )
    token_file = notifications.get("ntfy_token_file", "")
    if token_file:
        token_path = Path(token_file).expanduser()
        if not token_path.is_file():
            return build_check(
                check_id, "warning", f"Fichier de token ntfy introuvable ({token_path}).",
                fix="scripts/setup-ntfy.sh",
            )
    return build_check(check_id, "ok", "Notifications ntfy configurées.", fix=None)


# ---------------------------------------------------------------------------
# Orchestration + CLI
# ---------------------------------------------------------------------------


def run_all_checks(workspace: Path, now: datetime, tokens_dir: Path) -> list:
    try:
        config = arc_index.load_config(workspace)
    except ConfigError:
        # Un TOML invalide est déjà signalé par `check_config_files` — les
        # autres vérifications continuent avec des défauts plutôt que de
        # planter toute la commande sur une seule section corrompue.
        config = {}
    return [
        check_garmin_token(now, tokens_dir),
        check_garmin_mcp(workspace),
        check_config_files(workspace),
        check_athlete_profile(workspace, config),
        check_index_freshness(workspace),
        check_out_of_contract(workspace),
        check_daily_sync(Path.home()),
        check_ntfy(config),
    ]


def render_table(checks: list) -> str:
    lines = []
    for check in checks:
        icon = STATUS_ICON.get(check["status"], "?")
        lines.append(f"{icon} {check['id']:<22} {check['message']}")
        if check.get("fix") and check["status"] != "ok":
            lines.append(f"    → correctif : {check['fix']}")
    return "\n".join(lines)


def resolve_now(raw: Optional[str]) -> datetime:
    value = raw or os.environ.get("ARC_DOCTOR_NOW")
    if value:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def resolve_tokens_dir(raw: Optional[str]) -> Path:
    value = raw or os.environ.get("GARMIN_TOKENS_DIR") or "~/.garminconnect"
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", help="racine du workspace (sinon ARC_WORKSPACE / défaut du moteur)")
    parser.add_argument("--json", action="store_true", help="sortie machine (voir schéma dans --help)")
    parser.add_argument("--now", help="horloge injectable, ISO8601 (tests, story #32)")
    parser.add_argument("--tokens-dir", help="override de ~/.garminconnect (tests, GARMIN_TOKENS_DIR)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = workspace_root(args.workspace)
    now = resolve_now(args.now)
    tokens_dir = resolve_tokens_dir(args.tokens_dir)

    checks = run_all_checks(workspace, now, tokens_dir)
    has_error = any(check["status"] == "error" for check in checks)

    if args.json:
        payload = {
            "generated_at": now.isoformat(),
            "workspace": str(workspace),
            "ok": not has_error,
            "checks": checks,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"coach doctor — {workspace}")
        print(render_table(checks))
        print()
        if has_error:
            print("Au moins une vérification est en échec (❌) — voir les correctifs ci-dessus.")
        else:
            print("Aucune vérification en échec.")
    return 1 if has_error else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"coach_doctor: {exc}", file=sys.stderr)
        sys.exit(1)
