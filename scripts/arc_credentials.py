#!/usr/bin/env python3
"""Dossiers d'identifiants d'un workspace : jetons Garmin et identifiants intervals.icu (#127).

Plusieurs workspaces (un par membre d'un foyer) peuvent tourner sous le MÊME utilisateur
système : leurs identifiants ne doivent alors ni se partager ni s'écraser. Ce module est
l'UNIQUE endroit qui résout ces dossiers, pour `coach_doctor`, `garmin_watch`,
`garmin_gear_backfill` et `skills/fit-download/scripts/download_fit.py`. Il lit le
`.mcp.json` du workspace — là où `./install.sh --garmin-tokens` / `--intervals-dir`
les écrivent — et retombe sur les emplacements historiques quand rien n'est configuré :
une installation mono-athlète ne voit AUCUN changement.

Jetons Garmin — même ordre que `garmin_mcp/__init__.py` (`GARMINTOKENS` d'abord) :
  1. l'option explicite (`--tokens-dir`, tests) ;
  2. `GARMINTOKENS` dans l'`env` du serveur MCP `garmin` du `.mcp.json` du workspace
     (c'est ce que `garmin-mcp` verra réellement) ;
  3. `GARMINTOKENS` dans l'environnement du process ;
  4. `GARMIN_TOKENS_DIR` (variable propre au projet : tests, #32) ;
  5. `~/.garminconnect`.

Identifiants intervals.icu : dossier du wrapper `run.sh` référencé comme commande du serveur
MCP `intervals` du `.mcp.json` (il y a le `.env` de la clé API), sinon
`~/.config/ai-running-coach/intervals-icu-mcp`.

Bibliothèque standard uniquement (voir CONTRIBUTING.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_GARMIN_TOKENS = "~/.garminconnect"
DEFAULT_INTERVALS_DIR = "~/.config/ai-running-coach/intervals-icu-mcp"
INTERVALS_WRAPPER = "run.sh"

SOURCE_EXPLICIT = "option --tokens-dir"
SOURCE_MCP = ".mcp.json du workspace (GARMINTOKENS)"
SOURCE_ENV = "environnement (GARMINTOKENS)"
SOURCE_ENV_PROJECT = "environnement (GARMIN_TOKENS_DIR)"
SOURCE_DEFAULT = "défaut (~/.garminconnect)"


def _mcp_server(workspace: Path, name: str) -> dict:
    """Entrée `name` de `mcpServers` dans `<workspace>/.mcp.json`, `{}` si absente ou illisible
    (un fichier écrit à la main ne doit jamais faire planter un diagnostic)."""
    try:
        data = json.loads((Path(workspace) / ".mcp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    server = servers.get(name) if isinstance(servers, dict) else None
    return server if isinstance(server, dict) else {}


def mcp_server_env(workspace: Path, name: str = "garmin") -> dict:
    """`env` (chaînes seulement) du serveur MCP `name` du workspace."""
    raw = _mcp_server(workspace, name).get("env")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def garmin_tokens_dir_with_source(raw: Optional[str], workspace: Path) -> Tuple[Path, str]:
    """Dossier de jetons Garmin ET l'étiquette de la règle qui l'a désigné (voir docstring du module)."""
    if raw:
        return Path(raw).expanduser(), SOURCE_EXPLICIT
    value = mcp_server_env(workspace).get("GARMINTOKENS")
    if value:
        return Path(value).expanduser(), SOURCE_MCP
    value = os.environ.get("GARMINTOKENS")
    if value:
        return Path(value).expanduser(), SOURCE_ENV
    value = os.environ.get("GARMIN_TOKENS_DIR")
    if value:
        return Path(value).expanduser(), SOURCE_ENV_PROJECT
    return Path(DEFAULT_GARMIN_TOKENS).expanduser(), SOURCE_DEFAULT


def garmin_tokens_dir(raw: Optional[str], workspace: Path) -> Path:
    return garmin_tokens_dir_with_source(raw, workspace)[0]


def intervals_env_dir(workspace: Optional[Path]) -> Path:
    """Dossier des identifiants intervals.icu du workspace : celui du wrapper `run.sh` que
    `.mcp.json` référence (`command` en chaîne, ou premier élément d'une liste), s'il est écrit
    comme tel par `install.sh --intervals-dir` ; sinon le dossier historique."""
    if workspace is not None:
        command = _mcp_server(workspace, "intervals").get("command")
        if isinstance(command, list) and command:
            command = command[0]
        if isinstance(command, str) and command:
            path = Path(command).expanduser()
            if path.name == INTERVALS_WRAPPER and path.is_absolute():
                return path.parent
    return Path(DEFAULT_INTERVALS_DIR).expanduser()


def main(argv: Optional[list] = None) -> int:
    """Interface shell : `arc_credentials.py garmin-tokens|garmin-tokens-mcp|intervals-dir --workspace W` affiche le
    dossier résolu sur une ligne (`--source` ajoute, sur la ligne suivante, la règle qui l'a désigné)."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("what", choices=("garmin-tokens", "garmin-tokens-mcp", "intervals-dir"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--source", action="store_true", help="affiche aussi la règle de résolution (garmin-tokens)")
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).expanduser()
    if args.what == "intervals-dir":
        print(intervals_env_dir(workspace))
        return 0
    if args.what == "garmin-tokens-mcp":
        # Seulement la valeur posée dans le .mcp.json du workspace (rien si absente) : pour les indices
        # d'authentification, qui ne doivent pas dépendre de l'environnement du moment.
        value = mcp_server_env(workspace).get("GARMINTOKENS")
        if value:
            print(Path(value).expanduser())
        return 0
    path, source = garmin_tokens_dir_with_source(None, workspace)
    print(path)
    if args.source:
        print(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
