#!/usr/bin/env python3
"""coach_doctor.py — diagnostic d'installation en une commande (issue #31).

Vérifie l'installation SANS RIEN ÉCRIRE ni appeler le réseau *par défaut* :
âge/échéance des tokens Garmin, présence du binaire MCP `garmin` (voir
`--probe-mcp` pour un vrai handshake, opt-in), validité TOML de
`config/workspace*.toml`, complétude du profil athlète (FC max / FC de repos),
fraîcheur de l'index dérivé `.arc/coach.db`, nombre de fichiers hors contrat,
planification du daily-sync (cron/launchd), configuration ntfy, lecteur FIT
(`fitparse` dans l'environnement MCP de `[data].source`), pin du serveur
intervals.icu (`intervals_mcp_pin`, #165), et — chat avec
le coach / sync sur une API — cohérence runner/backend/modèle/clé (`llm_config`),
service du chat (`chat_service`), présence d'OpenCode (`opencode_cli`), bot Telegram
(`telegram` : liste blanche, jeton hors dépôt en mode 600, service vivant — jamais le jeton affiché).

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
                | "daily_sync_scheduled" | "ntfy_configured" | "gear_sync"
                | "gear_history" | "fit_reader" | "intervals_mcp_pin" | "llm_config"
                | "chat_service" | "opencode_cli" | "telegram",
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
import urllib.error
import urllib.request
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

GARMIN_MCP_INSTALL_FIX = "uv tool install --python 3.12 git+https://github.com/Taxuspt/garmin_mcp@cfc5d799ab0f165e837f1188a1d093c65838aaf7"

# Pin du serveur MCP intervals.icu (#165) : DOIT rester identique à `INTERVALS_MCP_REF`
# dans install.sh — tests/lint/test_data_source_parity.py le vérifie.
INTERVALS_MCP_PINNED_URL = "https://github.com/hhopke/intervals-icu-mcp"
INTERVALS_MCP_PINNED_COMMIT = "5cd7e1abf716ea28b7bc5a8da5b01860b4bf2aa4"
# Ancien serveur (jusqu'à #165) : mêmes binaires, outils SANS préfixe `icu_`.
INTERVALS_MCP_LEGACY_URL = "https://github.com/eddmann/intervals-icu-mcp"
INTERVALS_MCP_UPDATE_FIX = "./install.sh --source intervals"

CHECK_IDS = (
    "garmin_token", "garmin_mcp", "config_files", "athlete_profile",
    "index_freshness", "out_of_contract", "daily_sync_scheduled", "ntfy_configured",
    "gear_sync", "gear_history", "fit_reader", "intervals_mcp_pin",
    "llm_config", "chat_service", "opencode_cli", "strava_connection", "telegram",
)

CHAT_SYSTEMD_UNIT_REL = ".config/systemd/user/ai-running-coach-chat.service"
CHAT_LAUNCHD_PLIST_REL = "Library/LaunchAgents/com.ai-running-coach.chat.plist"
# Borne dure du sondage de santé du service du chat (boucle locale).
CHAT_HEALTH_TIMEOUT_S = 2.0
OPENCODE_INSTALL_FIX = "curl -fsSL https://opencode.ai/install | bash"


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


WATCH_SCRIPT = "garmin_watch.py"
WATCH_STATE_REL = "logs/.watch-state.json"


def check_watch_heartbeat(check_id: str, workspace: Path, config: dict, now: datetime, installed: str) -> dict:
    """Mode surveillance : le planificateur existe, mais le watcher tourne-t-il vraiment ?

    `warning` si son dernier passage date de plus de 3 intervalles (cron arrêté,
    python introuvable…) : sans lui, plus aucune synchronisation n'a lieu hors
    du run de repli."""
    sync = config.get("sync") or {}
    try:
        interval = max(int(sync.get("watch_interval_min", 15)), 1)
    except (TypeError, ValueError):
        interval = 15
    try:
        state = json.loads((workspace / WATCH_STATE_REL).read_text(encoding="utf-8"))
        last = datetime.fromisoformat(state["last_check"])
    except (OSError, ValueError, KeyError, TypeError):
        return build_check(
            check_id, "warning", f"Surveillance Garmin installée ({installed}) mais jamais exécutée.",
            fix="python3 scripts/garmin_watch.py --dry-run",
        )
    reference = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
    age_min = (reference - last).total_seconds() / 60
    if age_min > 3 * interval:
        return build_check(
            check_id, "warning",
            f"Surveillance Garmin silencieuse depuis {age_min:.0f} min (intervalle {interval} min).",
            fix="python3 scripts/garmin_watch.py --dry-run ; voir logs/watch.log",
        )
    runs = state.get("runs") or {}
    today = reference.date().isoformat()
    count = runs.get("count", 0) if runs.get("date") == today else 0
    return build_check(
        check_id, "ok",
        f"Surveillance Garmin active ({installed}, dernier passage il y a {max(age_min, 0):.0f} min, "
        f"{count} run(s) LLM aujourd'hui).",
        fix=None,
    )


def check_daily_sync(home: Path, workspace: Path | None = None, config: dict | None = None,
                     now: datetime | None = None) -> dict:
    """Jamais plus sévère qu'« info » : un daily-sync non installé est un choix
    valide (synchronisation manuelle), pas une panne — voir issue #31. Seul un
    watcher installé mais muet remonte en `warning` (check_watch_heartbeat)."""
    check_id = "daily_sync_scheduled"
    now = now or datetime.now()
    if _uname() == "Darwin":
        plist = home / LAUNCHD_PLIST_REL
        if plist.is_file():
            if workspace is not None and WATCH_SCRIPT in plist.read_text(encoding="utf-8", errors="replace"):
                return check_watch_heartbeat(check_id, workspace, config or {}, now, "LaunchAgent")
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
        ours = [line for line in out.stdout.splitlines() if CRON_MARKER in line]
        if workspace is not None and any(WATCH_SCRIPT in line for line in ours):
            return check_watch_heartbeat(check_id, workspace, config or {}, now, "cron")
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
# fit_reader
# ---------------------------------------------------------------------------

# Outil `uv` dont l'interpréteur lit les FIT pour `skills/fit-download` (`--json`),
# par source — le même que celui dans lequel `download_fit.py` se relance.
FIT_READER_TOOLS = {"garmin": "garmin-mcp", "intervals": "intervals-icu-mcp"}


def _tool_python(tool: str, home: Path) -> Optional[Path]:
    """Interpréteur de l'outil `uv` `tool` : celui du binaire du PATH (lien uv →
    `<env>/bin/<tool>`), sinon l'emplacement uv par défaut — même résolution que
    `download_fit._auto_relaunch`."""
    exe = shutil.which(tool)
    candidates = []
    if exe:
        candidates.append(Path(os.path.realpath(exe)).parent / "python3")
    candidates.append(home / f".local/share/uv/tools/{tool}/bin/python3")
    return next((c for c in candidates if c.is_file() and os.access(c, os.X_OK)), None)


def check_fit_reader(config: dict, home: Path) -> dict:
    """`fitparse` est-il importable dans l'environnement MCP de la source ? Sans lui,
    `download_fit.py --json` (et l'étape FIT du daily-sync) ne produit aucun
    échantillon : zones, GAP, découplage, VAM, descente, durabilité et dépense
    énergétique modèle restent vides. Typiquement une installation intervals.icu
    antérieure à la lecture des FIT, mise à jour par un simple `git pull` sans
    relancer `install.sh` (docs/update.md). `warning`, jamais `error` : les KPI de
    base restent disponibles. Lance un interpréteur local (`import fitparse`),
    aucun appel réseau."""
    check_id = "fit_reader"
    source = (config.get("data") or {}).get("source", "garmin")
    if source == "strava":
        return build_check(
            check_id, "info",
            "[data].source = \"strava\" — aucun fichier FIT : les flux par seconde sont normalisés par "
            "`download_fit.py --source strava` (stdlib), aucun lecteur `fitparse` requis.",
            fix=None,
        )
    tool = FIT_READER_TOOLS.get(source, FIT_READER_TOOLS["garmin"])
    fix = f"./install.sh --source {source}" if source in FIT_READER_TOOLS else "./install.sh"
    python = _tool_python(tool, home)
    if python is None:
        return build_check(
            check_id, "warning",
            f"Environnement « {tool} » introuvable : les fichiers FIT ne peuvent pas être lus "
            "(KPI fins — zones, GAP, VAM… — indisponibles).",
            fix=fix,
        )
    try:
        proc = subprocess.run([str(python), "-c", "import fitparse"], capture_output=True, timeout=30)
        available = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        available = False
    if not available:
        return build_check(
            check_id, "warning",
            f"fitparse absent de l'environnement « {tool} » : les FIT téléchargés ne sont pas lus "
            "(KPI fins — zones, GAP, VAM… — indisponibles).",
            fix=fix,
        )
    return build_check(check_id, "ok", f"Lecteur FIT (fitparse) présent dans l'environnement « {tool} ».",
                       fix=None)


# ---------------------------------------------------------------------------
# strava_connection (#164)
# ---------------------------------------------------------------------------

STRAVA_TOKEN_REL = ".config/strava-mcp/config.json"
STRAVA_WRAPPER_REL = ".config/ai-running-coach/strava-mcp/run.sh"
STRAVA_NODE_MIN_MAJOR = 18


def check_strava_connection(workspace: Path, config: dict, home: Path) -> dict:
    """`[data].source = "strava"` : Node.js >= 18 (le serveur est un paquet npm lancé par `npx`),
    wrapper du projet, serveur `strava` déclaré dans `.mcp.json`, fichier de jetons du serveur
    (`~/.config/strava-mcp/config.json`) et ses droits. STATIQUE : lit seulement l'existence des clés
    `accessToken`/`refreshToken`/`clientId`/`clientSecret` — JAMAIS leur valeur, qui n'est ni
    affichée, ni journalisée, ni conservée. Aucun appel réseau : l'échéance du jeton d'accès (6 h)
    n'est pas une alerte, le serveur et `download_fit.py` le rafraîchissent seuls ; seul un jeton de
    rafraîchissement absent ou révoqué impose de relancer `connect-strava`. Hors source strava :
    `info`, jamais une panne."""
    check_id = "strava_connection"
    source = (config.get("data") or {}).get("source", "garmin")
    if source != "strava":
        return build_check(check_id, "info",
                           f"[data].source = \"{source}\" — connexion Strava non applicable.", fix=None)
    fix_install = "./install.sh --source strava"
    node = shutil.which("node")
    if not node or not shutil.which("npx"):
        return build_check(check_id, "error",
                           f"Node.js (node + npx, version {STRAVA_NODE_MIN_MAJOR} ou plus) introuvable dans le PATH : "
                           "le serveur MCP Strava ne peut pas démarrer.",
                           fix="installer Node.js >= 18 (https://nodejs.org), puis " + fix_install)
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        major = int(out.lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        major = None
    if major is not None and major < STRAVA_NODE_MIN_MAJOR:
        return build_check(check_id, "error",
                           f"Node.js {out} détecté : le serveur MCP Strava exige la version {STRAVA_NODE_MIN_MAJOR} ou plus.",
                           fix="mettre à jour Node.js (https://nodejs.org)")
    if not (home / STRAVA_WRAPPER_REL).is_file():
        return build_check(check_id, "error", f"Wrapper MCP absent (~/{STRAVA_WRAPPER_REL}).", fix=fix_install)
    try:
        servers = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8")).get("mcpServers") or {}
    except (OSError, ValueError, AttributeError):
        servers = {}
    if not any(str(name).lower().startswith("strava") for name in servers):
        return build_check(check_id, "error", "Aucun serveur MCP « strava » déclaré dans .mcp.json.", fix=fix_install)
    token_file = home / STRAVA_TOKEN_REL
    data = _read_json_object(token_file)
    if data is None:
        return build_check(check_id, "error",
                           f"Compte Strava non connecté (~/{STRAVA_TOKEN_REL} absent ou illisible).",
                           fix="demander à l'agent d'exécuter l'outil connect-strava (docs/strava-setup.md)")
    if not data.get("refreshToken"):
        return build_check(check_id, "error", "Jeton de rafraîchissement Strava absent : la connexion ne peut pas se renouveler.",
                           fix="demander à l'agent d'exécuter connect-strava avec force=true")
    if not (data.get("clientId") and data.get("clientSecret")):
        return build_check(check_id, "warning",
                           "Identifiants de l'application Strava (clientId/clientSecret) absents du fichier de jetons : "
                           "le rafraîchissement automatique échouera.",
                           fix="demander à l'agent d'exécuter connect-strava avec force=true")
    try:
        mode = token_file.stat().st_mode & 0o077
    except OSError:
        mode = 0
    if mode:
        return build_check(check_id, "warning",
                           f"~/{STRAVA_TOKEN_REL} est lisible par d'autres utilisateurs (il contient le secret client et les jetons).",
                           fix=f"chmod 600 ~/{STRAVA_TOKEN_REL}")
    return build_check(check_id, "ok",
                       "Strava : Node.js, wrapper, serveur MCP et jetons présents (valeurs non affichées ; la validité "
                       "réelle du jeton n'est testée par aucun appel réseau ici).", fix=None)

# ---------------------------------------------------------------------------
# intervals_mcp_pin (#165)
# ---------------------------------------------------------------------------


def installed_intervals_origin(home: Path) -> Optional[tuple]:
    """Origine VCS `(url, commit)` du serveur `intervals-icu-mcp` installé par `uv tool`,
    lue dans le `direct_url.json` (PEP 610) du dist-info de son environnement ; `None` si
    l'environnement ou ce fichier est introuvable/illisible. Aucun réseau, aucun process."""
    python = _tool_python("intervals-icu-mcp", home)
    if python is None:
        return None
    env_dir = python.parent.parent
    for path in sorted(env_dir.glob("lib/python*/site-packages/intervals_icu_mcp-*.dist-info/direct_url.json")):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(info, dict):
            return None
        vcs = info.get("vcs_info") if isinstance(info.get("vcs_info"), dict) else {}
        # Même dépôt écrit autrement (`….git`, barre finale) : même origine (cf. install.sh).
        url = str(info.get("url") or "").rstrip("/")
        url = url[:-len(".git")] if url.endswith(".git") else url
        return url, str(vcs.get("commit_id") or "")
    return None


def check_intervals_mcp_pin(config: dict, home: Path) -> dict:
    """#165 : le serveur intervals.icu installé est-il au commit épinglé par `install.sh` ?

    Une installation antérieure (eddmann/intervals-icu-mcp@cb91d4a) expose les outils SANS
    préfixe `icu_` alors que le coach, ses skills et la politique du chat parlent désormais
    `icu_*` : `warning` + commande de mise à jour. Jamais un `error` (rien n'est cassé côté
    données). Ne concerne que `[data].source = "intervals"` — `info` ailleurs, un athlète
    Garmin n'a rien à faire. Lecture locale seule (voir `installed_intervals_origin`)."""
    check_id = "intervals_mcp_pin"
    source = (config.get("data") or {}).get("source", "garmin")
    if source != "intervals":
        return build_check(
            check_id, "info",
            "[data].source != \"intervals\" — serveur intervals.icu non applicable.", fix=None,
        )
    origin = installed_intervals_origin(home)
    if origin is None:
        return build_check(
            check_id, "info",
            "Origine du serveur intervals-icu-mcp illisible (non installé par `uv tool`, ou "
            "environnement introuvable) : pin non vérifié.",
            fix=INTERVALS_MCP_UPDATE_FIX,
        )
    url, commit = origin
    short = commit[:7] or "?"
    if url == INTERVALS_MCP_LEGACY_URL:
        return build_check(
            check_id, "warning",
            f"Serveur intervals-icu-mcp installé depuis l'ancien dépôt eddmann (@{short}) : ses outils "
            "n'ont pas le préfixe `icu_` attendu par le coach (et sans push de séance structuré). "
            "Relancer l'installation ; ouvrir ensuite une NOUVELLE session (docs/update.md).",
            fix=INTERVALS_MCP_UPDATE_FIX,
        )
    if url == INTERVALS_MCP_PINNED_URL:
        if commit == INTERVALS_MCP_PINNED_COMMIT:
            env_file = home / ".config" / "ai-running-coach" / "intervals-icu-mcp" / ".env"
            try:
                too_open = env_file.is_file() and (env_file.stat().st_mode & 0o077) != 0
            except OSError:
                too_open = False
            if too_open:
                # La clé API ne doit être lisible que par son propriétaire (jamais lue ici).
                return build_check(
                    check_id, "warning",
                    f"Serveur intervals-icu-mcp au commit épinglé ({short}), mais le fichier "
                    "d'identifiants est lisible par d'autres comptes de la machine.",
                    fix=f"chmod 600 {env_file}",
                )
            return build_check(
                check_id, "ok", f"Serveur intervals-icu-mcp au commit épinglé ({short}).", fix=None,
            )
        return build_check(
            check_id, "info",
            f"Serveur intervals-icu-mcp au commit {short}, différent du pin du projet "
            f"({INTERVALS_MCP_PINNED_COMMIT[:7]}) : relancer l'installation pour s'aligner.",
            fix=INTERVALS_MCP_UPDATE_FIX,
        )
    return build_check(
        check_id, "info",
        f"Serveur intervals-icu-mcp installé depuis une origine personnalisée ({url or '?'}) : "
        "laissé tel quel, compatibilité des outils `icu_*` non garantie.",
        fix=None,
    )


# ---------------------------------------------------------------------------
# llm_config / chat_service / opencode_cli — chat et sync sur une API
# ---------------------------------------------------------------------------


def llm_env_path() -> Path:
    override = os.environ.get("ARC_LLM_ENV")
    return Path(override).expanduser() if override else Path.home() / ".config/ai-running-coach/llm.env"


def _llm_env_defines(path: Path, variable: str) -> bool:
    """Vrai si `variable=<non vide>` figure dans llm.env — sans jamais lire la valeur
    ailleurs que pour tester qu'elle n'est pas vide, et sans la conserver."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match and match.group(1) == variable and match.group(2).strip().strip("\"'"):
            return True
    return False


def _uses_opencode(config: dict) -> bool:
    sync, chat = config.get("sync") or {}, config.get("chat") or {}
    return sync.get("runner") == "opencode" or (
        bool(chat.get("enabled")) and chat.get("backend") == "opencode"
    )


def _mcp_gateway_only(workspace: Path) -> bool:
    """`.mcp.json` ne déclare que la passerelle leanproxy (aucun serveur direct garmin/intervals) ?"""
    try:
        data = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return False
    # Serveur direct : « garmin » ou tout nom commençant par « intervals » (Intervals_icu…), sans tenir compte de la casse.
    direct = [n for n in servers if str(n).lower() == "garmin" or str(n).lower().startswith(("intervals", "strava"))]
    return "leanproxy" in servers and not direct


def check_llm_config(config: dict, workspace: Optional[Path] = None) -> dict:
    """Jamais plus sévère qu'un `warning` : une configuration LLM incohérente prive
    du chat ou de la sync API, mais n'empêche pas le reste du coach de fonctionner.
    Ne lit ni n'affiche jamais une clé — seulement son NOM, et sa présence."""
    check_id = "llm_config"
    sync, chat = config.get("sync") or {}, config.get("chat") or {}
    chat_on = bool(chat.get("enabled"))
    runner = sync.get("runner", "claude")
    sync_key = str(sync.get("api_key_env") or "")
    chat_key = str(chat.get("api_key_env") or "") if chat_on else ""
    api_mode = bool(sync_key) or chat_on or runner == "opencode"
    if not api_mode:
        return build_check(
            check_id, "info",
            "Aucune API LLM configurée (sync sur abonnement, chat désactivé).",
            fix="./install.sh --llm openrouter|anthropic|openai",
        )

    problems: list = []
    if runner not in ("claude", "codex", "opencode"):
        problems.append(f"[sync].runner inconnu (« {runner} »)")
    if runner == "opencode" and "/" not in str(sync.get("model") or ""):
        problems.append("[sync].model doit être au format fournisseur/modèle pour le runner opencode")
    if sync_key and runner == "codex":
        problems.append("[sync].api_key_env est ignoré par le runner codex")
    if runner == "opencode" and workspace is not None and _mcp_gateway_only(workspace):
        problems.append("opencode + leanproxy non pris en charge pour la synchronisation — utilisez le mode direct")
    if chat_on:
        backend = chat.get("backend", "claude")
        model = str(chat.get("model") or "")
        if backend not in ("claude", "opencode", "mock"):
            problems.append(f"[chat].backend inconnu (« {backend} »)")
        if backend == "opencode" and "/" not in model:
            problems.append("[chat].model doit être au format fournisseur/modèle pour le backend opencode")
        if backend == "claude" and "/" in model:
            problems.append("[chat].model ressemble à un identifiant OpenCode alors que le backend est claude")

    keys = sorted({k for k in (sync_key, chat_key) if k})
    env_path = llm_env_path()
    if keys:
        if not env_path.is_file():
            problems.append(f"{env_path} absent (clés attendues : {', '.join(keys)})")
        else:
            try:
                mode = env_path.stat().st_mode & 0o777
            except OSError:
                mode = 0o600
            if mode & 0o077:
                problems.append(f"{env_path} est lisible par d'autres utilisateurs (mode {oct(mode)[2:]}, attendu 600)")
            for key in keys:
                if not _llm_env_defines(env_path, key) and not os.environ.get(key):
                    problems.append(f"variable {key} non définie dans {env_path}")
    if os.environ.get("ANTHROPIC_API_KEY") and "ANTHROPIC_API_KEY" in keys:
        problems.append(
            "ANTHROPIC_API_KEY est exporté dans l'environnement : Remote Control refuse la clé API "
            "(à garder dans llm.env uniquement)"
        )
    if problems:
        return build_check(
            check_id, "warning", "Configuration LLM à revoir : " + " ; ".join(problems) + ".",
            fix="./install.sh --llm openrouter|anthropic|openai (crée llm.env en mode 600)",
        )
    parts = [f"sync : {runner}" + (f" ({sync.get('model')})" if sync.get("model") else "")]
    if chat_on:
        parts.append(f"chat : {chat.get('backend', 'claude')} ({chat.get('model')})")
    return build_check(
        check_id, "ok",
        "Configuration LLM cohérente — " + ", ".join(parts)
        + (f" ; clé(s) {', '.join(keys)} présente(s) (valeurs non lues)." if keys else "."),
        fix=None,
    )


def _chat_health_url(chat: dict) -> str:
    listen = str(chat.get("listen") or "127.0.0.1")
    host = "127.0.0.1" if listen in ("0.0.0.0", "::", "") else listen
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{chat.get('port', 8766)}/api/chat/healthz"


def check_chat_service(home: Path, config: dict) -> dict:
    """`info`/`warning` uniquement — jamais `error` : un chat arrêté est une
    dégradation de confort, pas une panne du coach."""
    check_id = "chat_service"
    chat = config.get("chat") or {}
    if not chat.get("enabled"):
        return build_check(
            check_id, "info", "Chat avec le coach désactivé ([chat].enabled = false).",
            fix="./install.sh --chat",
        )
    darwin = _uname() == "Darwin"
    unit = home / (CHAT_LAUNCHD_PLIST_REL if darwin else CHAT_SYSTEMD_UNIT_REL)
    installed = unit.is_file()
    url = _chat_health_url(chat)
    reachable, detail = False, ""
    payload = None
    try:
        with urllib.request.urlopen(url, timeout=CHAT_HEALTH_TIMEOUT_S) as response:  # noqa: S310 - boucle locale
            payload = json.loads(response.read(65536).decode("utf-8", errors="replace") or "{}")
        reachable = True
    except urllib.error.HTTPError as exc:
        # `/healthz` répond 503 quand le backend n'est pas sain : le service TOURNE, c'est son
        # corps qui dit pourquoi (HTTPError hérite d'URLError : à traiter avant).
        try:
            payload = json.loads(exc.read(65536).decode("utf-8", errors="replace") or "{}")
        except (OSError, ValueError):
            payload = {"ok": False}
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            payload = {**(payload if isinstance(payload, dict) else {}), "ok": False}   # erreur HTTP = jamais « sain »
        reachable = True
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        reachable = False
    if reachable:
        if isinstance(payload, dict) and payload.get("ok") is False:
            check = payload.get("backend_check")
            detail = f" — backend : {check}" if isinstance(check, str) and len(check) <= 120 else ""
            return build_check(
                check_id, "warning", f"Service du chat joignable ({url}) mais non sain{detail}.",
                fix="scripts/coach-chat.sh logs",
            )
    if reachable:
        where = "service installé" if installed else "lancé à la main (aucun service installé)"
        return build_check(check_id, "ok", f"Service du chat joignable ({where}).", fix=None)
    if not installed:
        return build_check(
            check_id, "warning", f"Chat activé mais aucun service installé et {url} injoignable.",
            fix="./install.sh --chat",
        )
    return build_check(
        check_id, "warning", f"Service du chat installé mais {url} injoignable.",
        fix="scripts/coach-chat.sh restart && scripts/coach-chat.sh logs",
    )


# ---------------------------------------------------------------------------
# telegram — bot Telegram (#174)
# ---------------------------------------------------------------------------

TELEGRAM_SYSTEMD_UNIT_REL = ".config/systemd/user/ai-running-coach-telegram.service"
TELEGRAM_LAUNCHD_PLIST_REL = "Library/LaunchAgents/com.ai-running-coach.telegram.plist"
TELEGRAM_DEFAULT_TOKEN_FILE = "~/.config/ai-running-coach/telegram.env"
TELEGRAM_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
# Le service écrit un battement à chaque interrogation (≤ poll_timeout_s + marge) : au-delà, il est mort.
TELEGRAM_HEARTBEAT_MAX_AGE_S = 300


def check_telegram(workspace: Path, home: Path, config: dict, now: datetime) -> dict:
    """`info`/`warning` uniquement : un bot arrêté est une dégradation de confort. Ne lit le jeton
    que pour en tester le FORMAT et n'affiche jamais sa valeur."""
    check_id = "telegram"
    tg = config.get("telegram") or {}
    if not tg.get("enabled"):
        return build_check(check_id, "info", "Bot Telegram désactivé ([telegram].enabled = false).",
                           fix="./install.sh --telegram")
    problems: list = []
    ids = tg.get("allowed_chat_ids")
    if not isinstance(ids, list) or not [i for i in ids if str(i).strip()]:
        problems.append("[telegram].allowed_chat_ids est vide (tout est refusé ; python3 scripts/arc_telegram.py whoami)")
    token_path = Path(os.path.expanduser(str(tg.get("token_file") or TELEGRAM_DEFAULT_TOKEN_FILE)))
    if not token_path.is_file():
        problems.append(f"fichier du jeton absent ({token_path})")
    else:
        try:
            mode = token_path.stat().st_mode & 0o777
            text = token_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            mode, text = 0o600, ""
        if mode & 0o077:
            problems.append(f"{token_path} est lisible par d'autres utilisateurs (mode {oct(mode)[2:]}, attendu 600)")
        values = [m.group(1).strip().strip("\"'") for m in
                  (re.match(r"^\s*(?:export\s+)?TELEGRAM_BOT_TOKEN=(.*)$", line) for line in text.splitlines()) if m]
        values = [v for v in values if v]
        if not values:
            problems.append("TELEGRAM_BOT_TOKEN non défini dans le fichier du jeton")
        elif not TELEGRAM_TOKEN_RE.match(values[-1]):
            problems.append("TELEGRAM_BOT_TOKEN : format inattendu (valeur non affichée)")
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        problems.append("TELEGRAM_BOT_TOKEN est exporté dans l'environnement : à garder dans le fichier du jeton seulement")
    if tg.get("chat_bridge"):
        chat = config.get("chat") or {}
        if not chat.get("enabled"):
            problems.append("chat_bridge = true mais [chat].enabled = false (la conversation libre répondra qu'elle est indisponible)")
        elif str(chat.get("auth") or "local") != "local":
            problems.append("chat_bridge exige [chat].auth = \"local\"")
    darwin = _uname() == "Darwin"
    unit = home / (TELEGRAM_LAUNCHD_PLIST_REL if darwin else TELEGRAM_SYSTEMD_UNIT_REL)
    beat = workspace / ".arc/telegram/heartbeat"
    alive = False
    try:
        alive = (now.timestamp() - beat.stat().st_mtime) <= TELEGRAM_HEARTBEAT_MAX_AGE_S
    except OSError:
        pass
    if not alive:
        if not unit.is_file():
            problems.append("aucun service installé et aucun signe de vie du bot")
        else:
            problems.append("service installé mais sans signe de vie récent (scripts/coach-telegram.sh logs)")
    if problems:
        fix = "scripts/coach-telegram.sh restart && scripts/coach-telegram.sh logs" if unit.is_file() else "./install.sh --telegram"
        return build_check(check_id, "warning", "Bot Telegram à revoir : " + " ; ".join(problems) + ".", fix=fix)
    bridge = "conversation libre activée" if tg.get("chat_bridge") else "retours en un geste seulement"
    return build_check(check_id, "ok", f"Bot Telegram actif ({bridge} ; jeton non affiché).", fix=None)


def _find_opencode() -> Optional[str]:
    extra = [str(Path.home() / ".local/bin"), str(Path.home() / ".opencode/bin"),
             "/opt/homebrew/bin", "/usr/local/bin"]
    return shutil.which("opencode", path=os.pathsep.join([os.environ.get("PATH", ""), *extra]))


def check_opencode_cli(config: dict) -> dict:
    check_id = "opencode_cli"
    if not _uses_opencode(config):
        return build_check(
            check_id, "info", "OpenCode non utilisé (ni runner de sync, ni backend du chat).", fix=None,
        )
    binary = _find_opencode()
    if not binary:
        return build_check(
            check_id, "warning", "OpenCode introuvable alors qu'un runner ou un backend l'utilise.",
            fix=OPENCODE_INSTALL_FIX,
        )
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5)
        version = (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 and (out.stdout or out.stderr).strip() else ""
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    if not version:
        return build_check(
            check_id, "warning", f"OpenCode présent ({binary}) mais « --version » ne répond pas.",
            fix=OPENCODE_INSTALL_FIX,
        )
    return build_check(check_id, "ok", f"OpenCode {version} ({binary}).", fix=None)


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


GEAR_TOOLS_REQUIRED = ("get_gear", "get_activity_gear")
_LEANPROXY_WHITELIST_RE = re.compile(r'GARMIN_ENABLED_TOOLS"?\s*:\s*"([^"]*)"')


def _read_gear_whitelist(workspace: Path):
    """(outils | None, origine) de la liste blanche Garmin, LUE sans jamais contacter Garmin :
    `.mcp.json` du workspace (mode direct : entrée `garmin`, env `GARMIN_ENABLED_TOOLS`), sinon
    `~/.config/leanproxy_servers.yaml` (mode passerelle). `None` = liste non lisible (fichier
    absent, JSON invalide, config manuelle) — l'appelant ne doit alors RIEN affirmer."""
    mcp = workspace / ".mcp.json"
    if mcp.is_file():
        try:
            data = json.loads(mcp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            garmin = servers.get("garmin")
            env = garmin.get("env") if isinstance(garmin, dict) else None
            listed = env.get("GARMIN_ENABLED_TOOLS") if isinstance(env, dict) else None
            if isinstance(listed, str) and listed.strip():
                return {t.strip() for t in listed.split(",") if t.strip()}, "mcp_json"
    yaml_path = Path.home() / ".config" / "leanproxy_servers.yaml"
    if yaml_path.is_file():
        try:
            m = _LEANPROXY_WHITELIST_RE.search(yaml_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            m = None
        if m:
            return {t.strip() for t in m.group(1).split(",") if t.strip()}, "leanproxy"
    return None, None


def check_gear_sync(workspace: Path, config: dict) -> dict:
    """#133 — synchronisation du matériel Garmin, vérifiée STATIQUEMENT (aucun appel Garmin,
    aucune écriture — même contrat que le reste du script hors `--probe-mcp`) :

    1. la liste blanche `GARMIN_ENABLED_TOOLS` (`.mcp.json`, ou `~/.config/leanproxy_servers.yaml`
       en mode passerelle) contient `get_gear` et `get_activity_gear`. `install.sh` met `.mcp.json`
       à jour à chaque relance mais n'écrit `leanproxy_servers.yaml` que s'il est absent : en mode
       passerelle le correctif est manuel. Liste illisible → on ne dit rien de la liste blanche ;
    2. profil : segment `garmin:` illisible ou uuid dupliqué entre puces (⚠️), paires actives
       sans segment `garmin: <uuid>` (ℹ️). Une puce `(ignorée)` (matériel Garmin volontairement non
       suivi) ou `(retirée)` n'est jamais réclamée. Lister le matériel Garmin sans puce exige
       `get_gear` : c'est le rôle du coach, jamais du doctor.
    """
    check_id = "gear_sync"
    source = (config.get("data") or {}).get("source", "garmin")
    if source == "strava":
        return build_check(
            check_id, "info",
            "[data].source = \"strava\" — le serveur Strava ne rend que le NOM de la paire (aucun identifiant "
            "attribuable par séance) ; attribution via le chat/défaut.",
            fix=None,
        )
    if source == "intervals":
        return build_check(
            check_id, "info",
            "[data].source = \"intervals\" — pas de matériel par séance côté intervals.icu "
            "(inventaire `icu_get_gear_list` en référence seulement) ; attribution via le chat/défaut.",
            fix=None,
        )
    tools, origin = _read_gear_whitelist(workspace)
    if tools is not None:
        missing = [t for t in GEAR_TOOLS_REQUIRED if t not in tools]
        if missing:
            if origin == "leanproxy":
                return build_check(
                    check_id, "warning",
                    f"Liste blanche leanproxy sans {', '.join(missing)} — `install.sh` n'écrit "
                    "~/.config/leanproxy_servers.yaml que s'il est absent : l'attribution du matériel Garmin "
                    "est indisponible.",
                    fix="éditez GARMIN_ENABLED_TOOLS dans ~/.config/leanproxy_servers.yaml : ajoutez "
                        "get_gear,get_activity_gear,add_gear_to_activity",
                )
            return build_check(
                check_id, "warning",
                f"Liste blanche `GARMIN_ENABLED_TOOLS` sans {', '.join(missing)} — l'attribution "
                "automatique du matériel Garmin est indisponible.",
                fix="./install.sh (relancez-le : la liste blanche de .mcp.json est mise à jour)",
            )
        whitelist_note = ""
    else:
        whitelist_note = " (liste blanche non lue : fichier absent ou illisible, mode passerelle ou config manuelle)"
    rel = config.get("athlete", {}).get("profile", "planning/Runner_Profile.md")
    path = workspace / rel
    pairs = []
    if path.is_file():
        try:
            pairs = L.parse_gear(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pairs = []
    label = lambda g: g.get("name") or g["gear_id"]   # noqa: E731
    invalid = [g for g in pairs if g.get("garmin_uuid_invalid")]
    seen: dict = {}
    for g in pairs:
        if g.get("garmin_uuid"):
            seen.setdefault(g["garmin_uuid"], []).append(label(g))
    duplicates = {u: names for u, names in seen.items() if len(names) > 1}
    if invalid or duplicates:
        problems = []
        if invalid:
            problems.append("segment garmin: illisible (" + ", ".join(label(g) for g in invalid) + ")")
        if duplicates:
            problems.append("même uuid Garmin sur plusieurs puces (" + " / ".join(
                " + ".join(names) for names in duplicates.values()) + ")")
        return build_check(
            check_id, "warning", " ; ".join(problems) + whitelist_note + " — ces puces ne seront pas associées.",
            fix=f"corrigez les segments `garmin: <uuid>` de {rel} (uuid recopié de get_gear, un par paire)",
        )
    active = [g for g in pairs if not g.get("retired") and not g.get("ignored")]
    unlinked = [g for g in active if not g.get("garmin_uuid")]
    if unlinked:
        names = ", ".join(label(g) for g in unlinked)
        return build_check(
            check_id, "info",
            f"{len(unlinked)} paire(s) active(s) sans segment `garmin: <uuid>` ({names}){whitelist_note} — "
            "le coach propose l'association au prochain `get_gear` ; rien n'est jamais associé sans votre accord.",
            fix="demandez au coach « associe mes chaussures à Garmin » (aucun appel n'est fait par le doctor)",
        )
    if not active:
        msg = ("Outils matériel Garmin présents dans la liste blanche ; aucune paire active déclarée."
               if not whitelist_note else f"Aucune paire active déclarée{whitelist_note}.")
        return build_check(check_id, "ok", msg, fix=None)
    return build_check(
        check_id, "ok",
        f"{len(active)} paire(s) active(s), toutes associées à Garmin{whitelist_note}.", fix=None,
    )


GEAR_HISTORY_MIN_ACTIVITIES = 5
GEAR_HISTORY_MIN_RATIO = 0.5


def check_gear_history(workspace: Path, config: dict) -> dict:
    """#145 — historique sans matériel : information quand au moins `GEAR_HISTORY_MIN_ACTIVITIES`
    séances portent un `garmin_activity_id` ET que plus de la moitié (`GEAR_HISTORY_MIN_RATIO`) n'a pas de
    `gear_id` — un seul `gear_id` déclaré ne fait donc pas taire le signal. STATIQUE (lit les blocs `arc` de
    `activities/`, jamais l'index ni Garmin) ; jamais un avertissement."""
    check_id = "gear_history"
    source = (config.get("data") or {}).get("source", "garmin")
    if source in ("intervals", "strava"):
        return build_check(check_id, "info",
                           f"[data].source = \"{source}\" — pas de matériel Garmin à rattraper.", fix=None)
    with_id = without_gear = 0
    folder = workspace / "activities"
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            block = arc_index.C.extract_block(path.read_text(encoding="utf-8", errors="replace"))
        except (arc_index.C.ContractError, OSError):
            continue
        if not block or block.get("kind") != "activity":
            continue
        if block.get("garmin_activity_id") is not None:
            with_id += 1
            if not block.get("gear_id"):
                without_gear += 1
    if with_id >= GEAR_HISTORY_MIN_ACTIVITIES and without_gear / with_id > GEAR_HISTORY_MIN_RATIO:
        return build_check(
            check_id, "info",
            f"{without_gear} séance(s) sur {with_id} avec garmin_activity_id n'ont pas de gear_id — historique sans matériel : "
            "la carte Matériel reste vide. Lancer le rattrapage (simulation d'abord, aucun écrit sans --apply).",
            fix="python3 scripts/garmin_gear_backfill.py   # simulation ; ajouter --apply après relecture",
        )
    return build_check(check_id, "ok", "Historique cohérent (pas de rattrapage du matériel à proposer).", fix=None)


def check_garmin_check_not_applicable(check_id: str, source: str = "intervals") -> dict:
    """#68 : `[data].source = "intervals"` — ni tokens OAuth Garmin ni serveur
    MCP `garmin` à vérifier ici (aucun des deux n'est installé/enregistré
    avec cette source). Un statut `error`/`warning` serait un faux diagnostic
    (« tokens absents », « garmin-mcp introuvable ») pour un athlète qui n'a
    jamais eu de compte Garmin — `info`, jamais une panne."""
    return build_check(
        check_id, "info",
        f"[data].source = \"{source}\" — vérification Garmin non applicable.",
        fix=None,
    )


def run_single_check(check_id: str, workspace: Path, now: datetime, tokens_dir: Path, probe_mcp: bool) -> dict:
    config = _load_config(workspace)
    source = (config.get("data") or {}).get("source", "garmin")
    if check_id in ("garmin_token", "garmin_mcp") and source in ("intervals", "strava"):
        return check_garmin_check_not_applicable(check_id, source)
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
        return check_daily_sync(Path.home(), workspace, config, now)
    if check_id == "ntfy_configured":
        return check_ntfy(config)
    if check_id == "gear_sync":
        return check_gear_sync(workspace, config)
    if check_id == "gear_history":
        return check_gear_history(workspace, config)
    if check_id == "fit_reader":
        return check_fit_reader(config, Path.home())
    if check_id == "intervals_mcp_pin":
        return check_intervals_mcp_pin(config, Path.home())
    if check_id == "llm_config":
        return check_llm_config(config, workspace)
    if check_id == "chat_service":
        return check_chat_service(Path.home(), config)
    if check_id == "opencode_cli":
        return check_opencode_cli(config)
    if check_id == "strava_connection":
        return check_strava_connection(workspace, config, Path.home())
    if check_id == "telegram":
        return check_telegram(workspace, Path.home(), config, now)
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
