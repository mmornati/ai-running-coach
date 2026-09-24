#!/usr/bin/env python3
"""coach_doctor.py — diagnostic d'installation en une commande (issue #31).

Vérifie l'installation SANS RIEN ÉCRIRE ni appeler le réseau *par défaut* :
âge/échéance des tokens Garmin, présence du binaire MCP `garmin` (voir
`--probe-mcp` pour un vrai handshake, opt-in), validité TOML de
`config/workspace*.toml`, complétude du profil athlète (FC max / FC de repos),
fraîcheur de l'index dérivé `.arc/coach.db`, nombre de fichiers hors contrat,
planification du daily-sync (cron/launchd), configuration ntfy.

Usage :
    scripts/coach_doctor.py                 # tableau ✅/⚠️/❌ en français
    scripts/coach_doctor.py --json          # sortie machine (schéma ci-dessous)
    scripts/coach_doctor.py --workspace DIR
    scripts/coach_doctor.py --now 2026-09-24T12:00:00+00:00   # horloge injectable
    scripts/coach_doctor.py --tokens-dir DIR                  # override des tokens Garmin
    scripts/coach_doctor.py --check garmin_token              # une seule vérification (#32)
    scripts/coach_doctor.py --probe-mcp     # handshake MCP réel — CONTACTE Garmin Connect

Aucun champ de ce script n'affiche jamais le CONTENU d'un token — seuls des
métadonnées (chemins, dates d'échéance, nombre de jours restants) apparaissent
en sortie, table ou JSON.

Code de sortie : **1** si au moins une vérification est ❌ (`status: "error"`),
sinon **0** — un avertissement (`warning`) ou une information (`info`) ne fait
jamais échouer la commande : ce sont des dégradations connues (RPE de repli,
notifications désactivées, daily-sync non installé...), pas des pannes.

SCHÉMA JSON (`--json`) — réutilisé tel quel par la story #32 (alerte ntfy
avant expiration des tokens, qui appelle ce script avec `--json`, éventuellement
`--check garmin_token` pour ne payer que ce coût-là) :

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
    "expires_at": "<ISO8601, microsecondes tronquées>" | null,
    "days_left": <int> | null,          # jours restants, ARRONDI VERS LE BAS
                                         # (négatif = expiré depuis ce nombre de jours)
    "source": "explicit" | "mtime_fallback" | "missing"

MÉTHODE DE DÉTECTION DE L'ÉCHÉANCE DES TOKENS — investigation faite sur
l'installation réelle (`~/.local/share/uv/tools/garmin-mcp`, lecture seule) :

  Le client `garminconnect` (0.3.2) vendored par `garmin-mcp` ne lit/écrit
  QU'UN SEUL fichier : `<tokens_dir>/garmin_tokens.json` (`Client.dump`/`load`,
  ~lignes 1057-1070 de `garminconnect/client.py`), contenant `di_token`,
  `di_refresh_token`, `di_client_id` — jamais `oauth2_token.json` (format
  `garth`, propre à d'autres installations de `garminconnect`, jamais produit
  ici). `install.sh` (voir ses commentaires autour des lignes 584 et 1073)
  traite lui aussi `garmin_tokens.json` comme le fichier réel.

  Concernant une échéance EXPLICITE dans ce fichier :
    - `di_token` EST un JWT (vérifié : 3 segments décodables), mais son claim
      `exp` correspond à une session courte (régénérée automatiquement à
      chaque connexion réussie, de l'ordre d'un jour) — un signal totalement
      inadapté à un avertissement « expire dans 14 jours » : il redeviendrait
      « bientôt expiré » plusieurs fois par semaine sans que l'athlète n'ait
      rien à faire.
    - `di_refresh_token` N'EST PAS un JWT (un seul segment, non décodable) :
      aucune échéance longue durée n'est donc disponible dans ce fichier.
  Repli documenté : mtime du fichier + une fenêtre de validité d'environ
  **6 mois** (`TOKEN_VALIDITY_FALLBACK_DAYS`), cohérente avec
  `docs/troubleshooting.md` (« Les tokens Garmin sont valides environ 6
  mois »). LIMITE CONNUE : `garminconnect` réécrit `garmin_tokens.json` à
  chaque rafraîchissement du DI token (`_refresh_di_token` → `dump`), ce qui
  repousse la mtime — et donc l'échéance estimée — sans que la session ait
  réellement été renouvelée pour 6 mois de plus. `source: "mtime_fallback"`
  signale explicitement cette limite ; ne pas la traiter comme une garantie.

  `oauth2_token.json` (format `garth`) n'est utilisé QUE s'il est le SEUL
  fichier de tokens présent (repli historique, pour ne pas ignorer une
  installation qui l'utiliserait réellement) : son champ explicite
  `refresh_token_expires_at` (epoch secondes) sert alors de signal — en
  notant que c'est l'échéance du *refresh token OAuth2*, pas d'une session
  active, ce qui reste le signal le plus proche disponible dans ce format.

  Si `garmin_tokens.json` ET `oauth2_token.json` sont tous deux présents (ex.
  reliquat d'une ancienne installation `garth`), `garmin_tokens.json` gagne
  toujours : c'est le seul que `garmin-mcp` lit réellement (voir ci-dessus).

RÉSOLUTION DU RÉPERTOIRE DE TOKENS (même ordre que `garmin_mcp/__init__.py`,
où `tokenstore = os.getenv("GARMINTOKENS") or "~/.garminconnect"`) :
  1. `--tokens-dir` (tests, override explicite) ;
  2. `GARMINTOKENS` défini dans l'entrée `env` du serveur MCP `garmin` de
     `.mcp.json` du workspace (c'est ce que `garmin-mcp` verra réellement) ;
  3. `GARMINTOKENS` dans l'environnement du process ;
  4. `GARMIN_TOKENS_DIR` (variable propre à ce script, tests/#32) ;
  5. `~/.garminconnect` (défaut de `garmin-mcp`).

VÉRIFICATION MCP — voir la docstring de `check_garmin_mcp_presence` et de
`probe_garmin_mcp` : par défaut, présence/exécutabilité UNIQUEMENT (aucun
process lancé, aucun réseau, aucune écriture). Un handshake MCP réel est
disponible derrière `--probe-mcp`, qui CONTACTE Garmin Connect.

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
import signal
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_index  # noqa: E402
import arc_legacy as L  # noqa: E402
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

# Borne dure sur le handshake MCP réel (--probe-mcp uniquement, voir
# probe_garmin_mcp) : un `garmin-mcp stdio` qui ne répond pas dans ce délai
# est traité comme un avertissement, jamais comme un blocage de la commande.
# `ARC_MCP_PROBE_TIMEOUT_S` : levier de test uniquement, pour ne pas faire
# durer un cas « le serveur ne répond jamais » plus que nécessaire.
MCP_PROBE_TIMEOUT_S = float(os.environ.get("ARC_MCP_PROBE_TIMEOUT_S", "10"))

CRON_MARKER = "# ai-running-coach daily-sync"
LAUNCHD_PLIST_REL = "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist"

GARMIN_MCP_INSTALL_FIX = "uv tool install --python 3.12 git+https://github.com/Taxuspt/garmin_mcp"

CHECK_IDS = (
    "garmin_token", "garmin_mcp", "config_files", "athlete_profile",
    "index_freshness", "out_of_contract", "daily_sync_scheduled", "ntfy_configured",
)


def build_check(check_id: str, status: str, message: str, fix: Optional[str], **extra: Any) -> dict:
    payload = {"id": check_id, "status": status, "message": message, "fix": fix}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# garmin_token
# ---------------------------------------------------------------------------


def _read_json_object(path: Path) -> Optional[dict]:
    """Charge un fichier JSON en objet — jamais de contenu affiché/loggé ici."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _safe_epoch_to_datetime(raw: Any) -> Optional[datetime]:
    """epoch-secondes -> datetime UTC, en rejetant proprement les valeurs
    aberrantes : un bool (qui passerait `isinstance(x, int)` en Python), un
    epoch en millisecondes (hors plage -> année à 5 chiffres), ou toute autre
    valeur qui ferait planter `datetime.fromtimestamp`."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _explicit_expiry(oauth2_path: Path) -> Optional[datetime]:
    """Champ `refresh_token_expires_at` d'un `oauth2_token.json` façon `garth`
    (voir docstring du module : utilisé seulement si `garmin_tokens.json`
    est absent). Jamais le contenu du token lui-même n'est lu ici."""
    data = _read_json_object(oauth2_path)
    if data is None:
        return None
    return _safe_epoch_to_datetime(data.get("refresh_token_expires_at"))


def _mtime_fallback(path: Path) -> Optional[datetime]:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError, OverflowError):
        return None
    return mtime + timedelta(days=TOKEN_VALIDITY_FALLBACK_DAYS)


def check_garmin_token(now: datetime, tokens_dir: Path) -> dict:
    check_id = "garmin_token"
    # `garmin_tokens.json` gagne TOUJOURS quand il est présent : c'est le seul
    # fichier que le client `garminconnect` vendored par `garmin-mcp` lit ou
    # écrit réellement (voir docstring du module) — un `oauth2_token.json`
    # laissé par une ancienne installation ne doit jamais faire croire à des
    # tokens expirés/valides que `garmin-mcp` n'utilise même pas.
    legacy = tokens_dir / "garmin_tokens.json"
    oauth2 = tokens_dir / "oauth2_token.json"

    expires_at: Optional[datetime] = None
    source = "missing"

    if legacy.is_file():
        expires_at = _mtime_fallback(legacy)
        source = "mtime_fallback" if expires_at is not None else "missing"
    elif oauth2.is_file():
        expires_at = _explicit_expiry(oauth2)
        if expires_at is not None:
            source = "explicit"
        else:
            expires_at = _mtime_fallback(oauth2)
            source = "mtime_fallback" if expires_at is not None else "missing"

    if expires_at is None:
        return build_check(
            check_id, "error",
            f"Tokens Garmin absents ou illisibles ({tokens_dir}) — première authentification requise.",
            fix="uv run garmin-mcp-auth",
            expires_at=None, days_left=None, source="missing",
        )

    # `.days` sur un timedelta négatif arrondit déjà vers -∞ (Python floor) :
    # un token expiré depuis 30h30 rend -2, pas -1 — c'est le comportement
    # voulu par #32 (« au moins ce nombre de jours de retard »).
    days_left = (expires_at - now).days
    if days_left < 0:
        status = "error"
        message = f"Tokens Garmin expirés depuis {abs(days_left)} jour(s) ({tokens_dir})."
    elif days_left < TOKEN_WARNING_THRESHOLD_DAYS:
        status = "warning"
        message = f"Tokens Garmin : encore {days_left} jour(s) avant échéance estimée."
    else:
        status = "ok"
        message = f"Tokens Garmin valides ({days_left} jour(s) restants estimés)."
    fix = "uv run garmin-mcp-auth" if status != "ok" else None
    return build_check(
        check_id, status, message, fix,
        expires_at=expires_at.replace(microsecond=0).isoformat(), days_left=days_left, source=source,
    )


# ---------------------------------------------------------------------------
# garmin_mcp
# ---------------------------------------------------------------------------


def _resolve_mcp_server(workspace: Path) -> dict:
    """Lit `.mcp.json` du workspace avec des garde-fous : un fichier écrit à
    la main (ou par un scénario de test) peut avoir `mcpServers` en liste,
    `args` en chaîne, ou des valeurs d'`env` non-chaînes — jamais de plantage
    ici, un défaut raisonnable à la place."""
    default = {"command": "garmin-mcp", "args": ["stdio"], "env": {}}
    mcp_json = workspace / ".mcp.json"
    if not mcp_json.is_file():
        return default
    try:
        data = json.loads(mcp_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return default
    server = servers.get("garmin")
    if not isinstance(server, dict):
        return default

    command = server.get("command", default["command"])
    if not isinstance(command, str) or not command:
        command = default["command"]

    args = server.get("args", default["args"])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        args = list(default["args"])

    raw_env = server.get("env", {})
    env: dict = {}
    if isinstance(raw_env, dict):
        for key, value in raw_env.items():
            if isinstance(key, str) and isinstance(value, str):
                env[key] = value

    return {"command": command, "args": args, "env": env}


def check_garmin_mcp_presence(workspace: Path) -> dict:
    """Vérification par défaut : présence + exécutabilité SEULEMENT.

    Aucun process n'est lancé, aucun octet ne part sur le réseau, aucun
    fichier n'est touché. Pourquoi c'est suffisant par défaut : lancer
    réellement `garmin-mcp` exécute son `main()`, qui appelle
    `init_api()` → `Garmin.login(tokenstore)` **avant** de servir quoi que ce
    soit en MCP — donc de vrais appels réseau vers Garmin Connect (avec
    retries), une possible réécriture de `garmin_tokens.json` lors d'un
    rafraîchissement du DI token (`Client._refresh_di_token` → `dump`), et
    même une authentification SSO complète si `GARMIN_EMAIL`/`GARMIN_PASSWORD`
    traînent dans l'environnement (transmis tel quel via `os.environ`). Rien
    de tout cela n'est nécessaire pour répondre à « le binaire MCP `garmin`
    est-il installé et exécutable ? » — et `install.sh` évite déjà
    `garmin-mcp --version` pour la même raison (cela démarre le serveur stdio
    et bloque). Le vrai handshake reste disponible en opt-in : `--probe-mcp`.
    """
    check_id = "garmin_mcp"
    server = _resolve_mcp_server(workspace)
    command_path = shutil.which(server["command"])
    if not command_path or not os.access(command_path, os.X_OK):
        return build_check(
            check_id, "error",
            f"Commande MCP « {server['command']} » introuvable ou non exécutable dans le PATH.",
            fix=GARMIN_MCP_INSTALL_FIX,
        )
    return build_check(
        check_id, "ok",
        f"MCP garmin : commande « {server['command']} » présente ({command_path}).",
        fix=None,
    )


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


def _terminate_group(proc: subprocess.Popen) -> None:
    """Tue le GROUPE de process (voir `start_new_session=True` dans
    `probe_garmin_mcp`) : un simple `proc.kill()` laisserait vivre les
    éventuels petits-enfants qu'un serveur MCP réel peut lancer."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
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


def probe_garmin_mcp(workspace: Path) -> dict:
    """Handshake MCP `initialize` RÉEL — opt-in (`--probe-mcp`) UNIQUEMENT.

    ATTENTION : ceci CONTACTE Garmin Connect. Lancer le vrai `garmin-mcp`
    exécute son `main()`, qui tente `Garmin.login(tokenstore)` avant de
    répondre au protocole MCP (voir `check_garmin_mcp_presence` pour le
    détail) — réseau, retries, possible réécriture des tokens, voire
    authentification complète si des identifiants traînent dans
    l'environnement. Le process est lancé dans un groupe dédié
    (`start_new_session=True`) et tué par groupe (`_terminate_group`) pour ne
    pas laisser d'orphelins si le handshake dépasse `MCP_PROBE_TIMEOUT_S`.
    """
    check_id = "garmin_mcp"
    server = _resolve_mcp_server(workspace)
    command_path = shutil.which(server["command"])
    if not command_path or not os.access(command_path, os.X_OK):
        return build_check(
            check_id, "error",
            f"Commande MCP « {server['command']} » introuvable ou non exécutable dans le PATH.",
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
            stderr=subprocess.DEVNULL, env=env, start_new_session=True,
        )
    except OSError as exc:
        return build_check(
            check_id, "error", f"Impossible de lancer « {server['command']} » : {exc}",
            fix=GARMIN_MCP_INSTALL_FIX,
        )

    try:
        reply = _read_line_with_timeout(proc, request, MCP_PROBE_TIMEOUT_S)
    finally:
        _terminate_group(proc)

    if _looks_like_mcp_reply(reply):
        return build_check(
            check_id, "ok",
            "MCP garmin joignable (handshake « initialize » réussi — a contacté Garmin Connect).",
            fix=None,
        )
    return build_check(
        check_id, "warning",
        "MCP garmin : commande présente mais aucune réponse MCP valide reçue dans le délai imparti "
        f"({MCP_PROBE_TIMEOUT_S:.0f}s) — vérifiez « garmin-mcp stdio » manuellement.",
        fix="garmin-mcp stdio",
    )


# ---------------------------------------------------------------------------
# config_files
# ---------------------------------------------------------------------------


def _toml_strict_available() -> bool:
    """`tomllib` (validation stricte) n'existe qu'à partir de Python 3.11 —
    en-dessous, `coach_config.read_toml` retombe sur un analyseur tolérant
    qui ne rejette pas toute syntaxe invalide (voir `_read_toml_fallback`).
    `ARC_FORCE_TOML_FALLBACK` permet aux tests de verrouiller ce chemin sans
    dépendre de la version de Python de la machine qui les exécute."""
    if os.environ.get("ARC_FORCE_TOML_FALLBACK"):
        return False
    return sys.version_info >= (3, 11)


def check_config_files(workspace: Path) -> dict:
    check_id = "config_files"
    workspace_toml = workspace / "config" / "workspace.toml"
    user_toml = workspace / "config" / "workspace.user.toml"

    # Un `workspace.user.toml` sans `workspace.toml` à côté est aussi cassé
    # que l'absence totale de configuration (defaults versionnés absents).
    if not workspace_toml.is_file():
        return build_check(check_id, "error", "config/workspace.toml introuvable.", fix="./install.sh")

    checked, problems = [], []
    for path, rel in ((workspace_toml, "config/workspace.toml"), (user_toml, "config/workspace.user.toml")):
        if not path.is_file():
            continue
        checked.append(rel)
        try:
            read_toml(path)
        except ConfigError as exc:
            problems.append(f"{rel} : {exc}")

    if problems:
        return build_check(
            check_id, "error", "TOML invalide — " + " ; ".join(problems),
            fix="corrigez le fichier signalé puis relancez `coach doctor`",
        )
    if not _toml_strict_available():
        return build_check(
            check_id, "warning",
            f"Validation TOML stricte indisponible (Python {platform.python_version()} < 3.11, pas de "
            f"`tomllib` — repli tolérant) : {', '.join(checked)} lus sans erreur, mais une syntaxe "
            "invalide pourrait passer inaperçue.",
            fix="utilisez Python ≥ 3.11 pour une validation stricte",
        )
    return build_check(check_id, "ok", f"Configuration TOML valide ({', '.join(checked)}).", fix=None)


# ---------------------------------------------------------------------------
# athlete_profile
# ---------------------------------------------------------------------------


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
    try:
        # Même analyseur que l'index (`arc_index.py` → `arc_legacy.parse_profile`) :
        # gère les variantes de libellés supportées et ne traverse jamais une
        # valeur sur plusieurs puces (contrairement à une regex `.*` naïve, qui
        # ferait passer un modèle non rempli pour un profil complet dès que la
        # puce suivante contient du texte).
        data = L.parse_profile(text)
    except Exception:
        data = {}
    hr_max = data.get("hr_max_bpm") is not None
    hr_rest = data.get("hr_rest_bpm") is not None
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


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """Connexion sqlite EXPLICITEMENT en lecture seule (`mode=ro` +
    `PRAGMA query_only`) — jamais de réindexation ici. `as_uri()` (plutôt
    qu'une interpolation `f"file:{db_path}"` manuelle) gère correctement les
    chemins contenant `#`, des espaces ou d'autres caractères spéciaux."""
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = 1")
    return conn


def check_index_freshness(workspace: Path) -> dict:
    check_id = "index_freshness"
    db_path = workspace / arc_index.DEFAULT_DB
    if not db_path.is_file():
        return build_check(
            check_id, "info", "Index .arc/coach.db jamais construit.",
            fix="python3 scripts/arc_index.py",
        )

    disk_files = arc_index.discover(workspace)
    disk_rel = {p.relative_to(workspace).as_posix() for p in disk_files}
    newest = max((p.stat().st_mtime for p in disk_files), default=None)

    try:
        conn = _open_readonly(db_path)
        try:
            indexed = {row[0] for row in conn.execute("SELECT path FROM source_file").fetchall()}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return build_check(
            check_id, "warning", f"Index .arc/coach.db illisible ({exc}).",
            fix="python3 scripts/arc_index.py --rebuild",
        )

    deleted = indexed - disk_rel
    if deleted:
        return build_check(
            check_id, "warning",
            f"{len(deleted)} fichier(s) supprimé(s) du workspace mais toujours présent(s) dans l'index.",
            fix="python3 scripts/arc_index.py --rebuild",
        )
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
    check_id = "out_of_contract"
    db_path = workspace / arc_index.DEFAULT_DB
    if not db_path.is_file():
        return build_check(
            check_id, "info", "Index absent — comptage des fichiers hors contrat impossible.",
            fix="python3 scripts/arc_index.py",
        )
    try:
        conn = _open_readonly(db_path)
        try:
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
    valide (synchronisation manuelle), pas une panne — voir issue #31."""
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


def _load_config(workspace: Path) -> dict:
    try:
        return arc_index.load_config(workspace)
    except ConfigError:
        # Un TOML invalide est déjà signalé par `check_config_files` — les
        # autres vérifications continuent avec des défauts plutôt que de
        # planter toute la commande sur une seule section corrompue.
        return {}


def run_single_check(check_id: str, workspace: Path, now: datetime, tokens_dir: Path, probe_mcp: bool) -> dict:
    config = _load_config(workspace)
    if check_id == "garmin_token":
        return check_garmin_token(now, tokens_dir)
    if check_id == "garmin_mcp":
        return probe_garmin_mcp(workspace) if probe_mcp else check_garmin_mcp_presence(workspace)
    if check_id == "config_files":
        return check_config_files(workspace)
    if check_id == "athlete_profile":
        return check_athlete_profile(workspace, config)
    if check_id == "index_freshness":
        return check_index_freshness(workspace)
    if check_id == "out_of_contract":
        return check_out_of_contract(workspace)
    if check_id == "daily_sync_scheduled":
        return check_daily_sync(Path.home())
    if check_id == "ntfy_configured":
        return check_ntfy(config)
    raise ValueError(f"vérification inconnue : {check_id!r}")


def run_all_checks(workspace: Path, now: datetime, tokens_dir: Path, probe_mcp: bool = False) -> list:
    return [run_single_check(check_id, workspace, now, tokens_dir, probe_mcp) for check_id in CHECK_IDS]


def render_table(checks: list) -> str:
    lines = []
    for check in checks:
        icon = STATUS_ICON.get(check["status"], "?")
        lines.append(f"{icon} {check['id']:<22} {check['message']}")
        if check.get("fix") and check["status"] != "ok":
            lines.append(f"    → correctif : {check['fix']}")
    return "\n".join(lines)


def _normalize_iso(value: str) -> str:
    """`datetime.fromisoformat` n'accepte le suffixe `Z` qu'à partir de
    Python 3.11 — on le normalise nous-mêmes pour rester compatible plus bas."""
    value = value.strip()
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    return value


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(_normalize_iso(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_now_arg(value: str) -> datetime:
    """Validateur `argparse` pour `--now` : une erreur propre (avec message
    d'usage) plutôt qu'une trace Python sur une valeur malformée."""
    try:
        return _parse_iso(value)
    except (ValueError, OverflowError) as exc:
        raise argparse.ArgumentTypeError(f"horloge --now invalide ({value!r}) : {exc}") from exc


def resolve_now(parsed_now: Optional[datetime]) -> datetime:
    if parsed_now is not None:
        return parsed_now
    env_value = os.environ.get("ARC_DOCTOR_NOW")
    if env_value:
        try:
            return _parse_iso(env_value)
        except (ValueError, OverflowError):
            print(
                f"coach_doctor: ARC_DOCTOR_NOW invalide ({env_value!r}) — horloge système utilisée.",
                file=sys.stderr,
            )
    return datetime.now(timezone.utc)


def resolve_tokens_dir(raw: Optional[str], workspace: Path) -> Path:
    """Voir la docstring du module pour l'ordre de résolution complet — même
    logique que `garmin_mcp/__init__.py` (`GARMINTOKENS` d'abord), avec
    `--tokens-dir` / `GARMIN_TOKENS_DIR` en plus pour les tests et #32."""
    if raw:
        return Path(raw).expanduser()
    mcp_env = _resolve_mcp_server(workspace).get("env", {})
    for source in (mcp_env, os.environ):
        value = source.get("GARMINTOKENS")
        if value:
            return Path(value).expanduser()
    value = os.environ.get("GARMIN_TOKENS_DIR")
    if value:
        return Path(value).expanduser()
    return Path("~/.garminconnect").expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", help="racine du workspace (sinon ARC_WORKSPACE / défaut du moteur)")
    parser.add_argument("--json", action="store_true", help="sortie machine (voir schéma dans --help)")
    parser.add_argument("--now", type=parse_now_arg, help="horloge injectable, ISO8601 (tests, story #32)")
    parser.add_argument("--tokens-dir", help="override du répertoire de tokens Garmin (tests, GARMIN_TOKENS_DIR)")
    parser.add_argument(
        "--check", choices=CHECK_IDS,
        help="n'exécuter qu'une seule vérification (ex. --check garmin_token, pour la story #32)",
    )
    parser.add_argument(
        "--probe-mcp", action="store_true",
        help="handshake MCP réel au lieu d'une simple vérification de présence — CONTACTE Garmin Connect",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = workspace_root(args.workspace)
    now = resolve_now(args.now)
    tokens_dir = resolve_tokens_dir(args.tokens_dir, workspace)

    if args.check:
        checks = [run_single_check(args.check, workspace, now, tokens_dir, args.probe_mcp)]
    else:
        checks = run_all_checks(workspace, now, tokens_dir, probe_mcp=args.probe_mcp)
    has_error = any(check["status"] == "error" for check in checks)

    if args.json:
        payload = {
            "generated_at": now.replace(microsecond=0).isoformat(),
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
