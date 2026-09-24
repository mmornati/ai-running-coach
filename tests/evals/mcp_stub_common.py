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

# Borne dure sur le délai d'un appel « timeout », quelle que soit la valeur
# `delay` demandée par le cas : un cas mal réglé (delay énorme, oubli du kill
# côté appelant) ne doit jamais suspendre la suite de tests indéfiniment.
# Le protocole lui-même reste fidèle à un vrai timeout : au-delà du délai,
# le stub ne répond PAS à cet appel (voir `DropRequest`) — c'est au client
# (agent, ou test palier D avec son propre `communicate(timeout=...)`) de
# couper court, exactement comme il le ferait contre un vrai serveur lent.
MAX_TIMEOUT_DELAY_S = float(os.environ.get("ARC_STUB_TIMEOUT_CAP", "10"))
DEFAULT_TIMEOUT_DELAY_S = 2.0

CONFIG_ENV_VAR = "ARC_STUB_CONFIG"
LOG_ENV_VAR = "ARC_TOOL_LOG"


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
    """Message d'un token expiré, façon garmin_mcp.

    Vérifié dans le paquet `garmin_mcp` réellement installé
    (`garmin_mcp/health_wellness.py` et consorts, version 0.1.0) : chaque
    outil attrape l'exception `GarminConnectAuthenticationError` levée par
    `garminconnect` et la restitue en TEXTE dans un résultat d'outil NORMAL —
    pas d'erreur JSON-RPC, pas de `isError`. Le message de `garminconnect`
    lui-même contient littéralement « Authentication failed (401
    Unauthorized) ». Un `isError` ou une erreur JSON-RPC serait plus
    « propre » au sens du protocole MCP, mais ne reproduirait pas ce qu'un
    agent voit réellement contre le vrai serveur — on choisit donc la
    fidélité comportementale à la pureté du spec.
    """
    return (
        f"Error retrieving data for {tool_name}: Authentication failed (401 Unauthorized). "
        "Session token expired — run 'uv run garmin-mcp-auth' to re-authenticate."
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
        candidate = fixtures_dir / "stub-responses" / override["file"]
        if not candidate.is_file():
            raise FileNotFoundError(f"réponse stub introuvable pour {name} : {candidate}")
        return candidate.read_text(encoding="utf-8")

    error = override.get("error")
    if error is None:
        return json.dumps(default, ensure_ascii=False)
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


def serve(handle: Callable[[dict], object]) -> int:
    """Boucle JSON-RPC stdin/stdout, une requête par ligne."""
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
            if request_id is None:
                continue
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32601, "message": f"méthode inconnue : {exc}"}}
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        if request_id is None or result is None:
            continue                   # notification : pas de réponse
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0
