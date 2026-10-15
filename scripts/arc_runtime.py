#!/usr/bin/env python3
"""Socle commun des commandes du moteur : workspace, configuration, messages.

Équivalent Python de scripts/lib/config.sh, pour les commandes qui ne passent plus
par bash (arc_notify.py, arc_dashboard.py…). Bibliothèque standard uniquement.

Deux racines :
  ENGINE    — le moteur (ce dépôt : agents, skills, scripts)
  workspace — les données personnelles : variable ARC_WORKSPACE, sinon
              ~/.config/ai-running-coach/workspace (écrit par ./install.sh --workspace),
              sinon le moteur lui-même.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENGINE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(ENGINE / "scripts"))

from coach_config import ConfigError, _read_toml_fallback, read_toml  # noqa: E402

_TTY = sys.stdout.isatty()
C_BLUE, C_GREEN, C_YELLOW, C_RED, C_RESET = (
    ("\033[34m", "\033[32m", "\033[33m", "\033[31m", "\033[0m") if _TTY else ("", "", "", "", ""))


def log(msg: str) -> None:
    print(f"{C_BLUE}==>{C_RESET} {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"{C_GREEN}✔{C_RESET} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{C_YELLOW}⚠{C_RESET} {msg}", flush=True)


def err(msg: str) -> None:
    print(f"{C_RED}✖{C_RESET} {msg}", file=sys.stderr, flush=True)


def resolve_workspace() -> Path:
    """ARC_WORKSPACE, sinon le workspace mémorisé par ./install.sh --workspace, sinon le moteur.
    Un chemin qui n'est pas un dossier existant retombe sur le moteur (comme config.sh)."""
    raw = os.environ.get("ARC_WORKSPACE", "")
    pointer = Path.home() / ".config/ai-running-coach/workspace"
    if not raw and pointer.is_file():
        lines = pointer.read_text(encoding="utf-8").splitlines()
        raw = lines[0].strip() if lines else ""
    if not raw or not os.path.isdir(raw):
        return ENGINE
    return Path(raw)


def config_paths(workspace: Path) -> tuple:
    """(workspace.toml partagé, workspace.user.toml) ; sans config dans le workspace, celle du moteur."""
    shared = workspace / "config/workspace.toml"
    if not shared.exists():
        shared = ENGINE / "config/workspace.toml"
    return shared, workspace / "config/workspace.user.toml"


def read_config(path: Path) -> dict:
    """TOML strict ; s'il est invalide, lecture tolérante (même sous-ensemble que config.sh).

    Une faute de frappe ailleurs dans la config (ex. `token_alert_days = [14, three]`) ne doit
    pas faire tomber une commande qui n'a besoin que d'une autre section : on prévient et on lit
    ce qui est lisible."""
    try:
        return read_toml(path)
    except ConfigError as exc:
        warn(f"{exc} — lecture tolérante.")
        return _read_toml_fallback(path.read_text(encoding="utf-8"))


def section(workspace: Path, name: str) -> dict:
    """Section fusionnée clé par clé : workspace.user.toml > workspace.toml.
    Une clé présente mais vide gagne (c'est ainsi qu'on annule un héritage)."""
    merged: dict = {}
    for path in config_paths(workspace):
        values = read_config(path).get(name)
        if isinstance(values, dict):
            merged.update(values)
    return merged
