#!/usr/bin/env python3
"""Code partagé par les stubs MCP factices du palier C (#26).

`stub_garmin_mcp.py` et `stub_intervals_mcp.py` parlent le même sous-ensemble
de JSON-RPC 2.0 (une requête par ligne sur stdin/stdout), journalisent leurs
appels au même format, et acceptent la même mécanique de scripting par cas
d'éval (`[stub.<serveur>.<outil>]`). Seules la liste d'outils et les données
canned diffèrent d'un stub à l'autre — ce module porte tout le reste pour
éviter de dupliquer le protocole.

Bibliothèque standard uniquement (voir `CONTRIBUTING.md`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

PROTOCOL_VERSION = "2024-11-05"

# Borne dure sur le SOMMEIL du stub avant d'abandonner un appel « timeout »,
# quelle que soit la valeur `delay` demandée par le cas — un `delay` énorme
# dans un `.toml` ne doit pas faire dormir le process plus que ça. Ça ne borne
# PAS l'attente du client en face : passé ce délai, le stub ne répond
# toujours PAS à cet appel (voir `DropRequest`), exactement comme un vrai
# serveur qui ne répondrait jamais. C'est au client de couper court — un
# agent réel via son propre timeout MCP (voir `runner.run_case`, qui règle
# `MCP_TOOL_TIMEOUT` pour un cas qui scripte un timeout), un test palier D
# avec son propre `select`/`communicate(timeout=...)`.
MAX_TIMEOUT_DELAY_S = float(os.environ.get("ARC_STUB_TIMEOUT_CAP", "10"))
DEFAULT_TIMEOUT_DELAY_S = 2.0

CONFIG_ENV_VAR = "ARC_STUB_CONFIG"
LOG_ENV_VAR = "ARC_TOOL_LOG"

# Seule liste faisant foi des `error =` reconnus par un `[stub.<serveur>.<outil>]`
# — `tests/evals/test_evals.py` la réutilise pour valider les cas, au lieu de
# dupliquer l'ensemble.
ERROR_KINDS = frozenset({"401", "timeout", "empty"})


class DropRequest(Exception):
    """L'appel ne doit recevoir aucune réponse (simulation d'un vrai timeout)."""


def log_call(log_path: str | None, server: str, name: str, arguments: dict) -> None:
    """Journalise un appel d'outil.

    Format conservé (`tool`, `arguments`) pour la compatibilité avec les
    assertions existantes (`tool in result["tool_calls"]`, une simple
    recherche de sous-chaîne) ; `server` est un champ ajouté, inoffensif pour
    ces vérifications.
    """
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"tool": name, "server": server, "arguments": arguments}, ensure_ascii=False
            ) + "\n")
    except OSError:
        pass                       # journaliser ne doit jamais casser le serveur


def load_stub_config(env_var: str = CONFIG_ENV_VAR) -> dict:
    """Charge la section `[stub.<serveur>]` d'un cas, déposée en JSON par le
    runner (une clé par outil, voir `runner.build_workspace`).

    Variable absente ou fichier illisible → dict vide, c'est-à-dire
    exactement le comportement d'avant #26 pour tout cas sans section
    `[stub]`.
    """
    path = os.environ.get(env_var)
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _empty_like(default):
    """Une valeur « vide » plausible, de la même forme que la donnée canned."""
    if isinstance(default, list):
        return []
    if isinstance(default, dict):
        return {}
    return None


def auth_expired_text(tool_name: str) -> str:
    """Message d'un token expiré, façon garmin_mcp — SANS remède.

    Vérifié dans le paquet `garmin_mcp` réellement installé (version 0.1.0) :
    `garminconnect/__init__.py` (autour de la ligne 339) lève
    `GarminConnectAuthenticationError(f"Authentication failed: {e}")` où `e`
    est l'exception HTTP sous-jacente (typiquement
    `401 Client Error: Unauthorized for url: ...`) ; chaque outil de
    `garmin_mcp/health_wellness.py` l'attrape et la restitue en TEXTE dans un
    résultat d'outil NORMAL — pas d'erreur JSON-RPC, pas de `isError` — sous
    la forme `f"Error retrieving {chose} data: {str(e)}"`.

    Le serveur réel ne mentionne **aucune** commande de renouvellement : c'est
    l'agent (via `agents/coach.md`/`agents/medical.md`, et plus tard #31/#32)
    qui doit reconnaître la panne et orienter vers `uv run garmin-mcp-auth` —
    pas le stub qui la lui souffle. Un `isError`/une erreur JSON-RPC serait
    plus « propre » au sens du protocole MCP, mais ne reproduirait pas ce
    qu'un agent voit réellement contre le vrai serveur : fidélité
    comportementale plutôt que pureté du spec.
    """
    return (
        f"Error retrieving data for {tool_name}: Authentication failed: "
        "401 Client Error: Unauthorized for url: https://connect.garmin.com/modern/proxy/"
    )


def resolve_content(
    *, name: str, default, overrides: dict, fixtures_dir: Path,
) -> str:
    """Rend le texte de `content` pour un appel, en tenant compte d'un
    éventuel override `[stub.<serveur>.<outil>]`. Peut lever `DropRequest`.

    `default` est la donnée canned (déjà résolue par le stub appelant) — sa
    forme (liste/dict) sert de gabarit pour `error = "empty"`.
    """
    override = (overrides or {}).get(name) or {}
    if "file" in override:
        # Résolution bornée à `fixtures/stub-responses/` : un cas ne doit pas
        # pouvoir faire lire au stub un fichier arbitraire du système
        # (`../../etc/hosts`, chemin absolu...) via un `file =` malicieux ou
        # mal formé.
        base = (fixtures_dir / "stub-responses").resolve()
        candidate = (base / override["file"]).resolve()
        if base not in candidate.parents and candidate != base:
            raise ValueError(
                f"[stub.*.{name}] file en dehors de stub-responses/ : {override['file']!r}"
            )
        if not candidate.is_file():
            raise FileNotFoundError(f"réponse stub introuvable pour {name} : {candidate}")
        return candidate.read_text(encoding="utf-8")

    error = override.get("error")
    if error is None:
        return json.dumps(default, ensure_ascii=False)
    error = str(error)              # un `error = 401` TOML (entier) reste géré
    if error == "401":
        return auth_expired_text(name)
    if error == "empty":
        return json.dumps(_empty_like(default), ensure_ascii=False)
    if error == "timeout":
        delay = min(float(override.get("delay", DEFAULT_TIMEOUT_DELAY_S)), MAX_TIMEOUT_DELAY_S)
        time.sleep(delay)
        raise DropRequest()
    raise ValueError(f"type d'erreur stub inconnu pour {name} : {error!r}")


def make_handler(
    *, server_name: str, tools: list, result_for: Callable[[str, dict], object],
    fixtures_dir: Path, config_env_var: str = CONFIG_ENV_VAR, log_env_var: str = LOG_ENV_VAR,
):
    """Construit la fonction `handle(request)` d'un stub.

    `tools` : liste `[(nom, description), ...]` rendue par `tools/list`.
    `result_for(name, arguments)` : donnée canned par défaut pour un appel —
    identique au comportement du stub avant #26 quand aucun override
    n'existe pour cet outil.
    """
    overrides = load_stub_config(config_env_var)
    log_path = os.environ.get(log_env_var)

    def handle(request: dict):
        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"{server_name}-stub", "version": "0.1.0"},
            }
        if method == "tools/list":
            return {"tools": [
                {
                    "name": name,
                    "description": description,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "start_date": {"type": "string"},
                            "end_date": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                }
                for name, description in tools
            ]}
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            log_call(log_path, server_name, name, arguments)
            default = result_for(name, arguments)
            text = resolve_content(
                name=name, default=default, overrides=overrides, fixtures_dir=fixtures_dir,
            )
            return {"content": [{"type": "text", "text": text}]}
        if method in ("ping", "notifications/initialized"):
            return {} if request_id is not None else None
        if request_id is None:
            return None                # notification inconnue : rien à répondre
        raise LookupError(method)

    return handle


def _error_response(request_id, code: int, message: str):
    if request_id is None:
        return None                   # notification : jamais de réponse, même en erreur
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(handle: Callable[[dict], object]) -> int:
    """Boucle JSON-RPC stdin/stdout, une requête par ligne.

    Un cas mal réglé (fichier de réponse absent, `error` inconnu...) ne doit
    faire échouer QUE l'appel concerné, jamais tuer le process : le stub
    répond alors -32603 pour cette requête et continue de servir les
    suivantes — c'est ce qui permet à un agent de recevoir l'erreur, de s'en
    remettre, et de continuer sa session.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = request.get("id")
        try:
            result = handle(request)
        except DropRequest:
            continue                   # timeout simulé : aucune réponse pour cet appel
        except LookupError as exc:
            response = _error_response(request_id, -32601, f"méthode inconnue : {exc}")
        except Exception as exc:  # noqa: BLE001 — un cas mal scripté ne doit jamais tuer le stub
            response = _error_response(request_id, -32603, f"erreur interne du stub : {exc}")
        else:
            response = (
                {"jsonrpc": "2.0", "id": request_id, "result": result}
                if request_id is not None and result is not None
                else None
            )
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0
