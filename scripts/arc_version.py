#!/usr/bin/env python3
"""Version du moteur, affichée par le tableau de bord (`/api/version`).

Deux sources, dans cet ordre :

1. `git describe --tags` quand le moteur est un dépôt git : `v1.1.0` sur une
   release, `v1.1.0-12-gaab4d9c` douze commits plus loin — le fichier VERSION
   dirait encore « 1.1.0 » alors que le code a avancé.
2. Le fichier `VERSION` à la racine : seule source sans `.git`. Il est écrit au
   build depuis le tag dans le moteur embarqué du DMG macOS
   (`scripts/build-macos-dmg.sh`) et dans l'image Docker du tableau de bord
   (`publish.yml`) ; dans le dépôt, il est mis à jour par une PR ordinaire
   (« Tag a release » ne pousse plus rien sur `main`) et peut retarder d'une
   release, par exemple dans une archive GitHub.

Aucune des deux : `None`, et le tableau de bord n'affiche rien plutôt qu'un
numéro inventé.
"""

from __future__ import annotations

import functools
import subprocess
import sys
from pathlib import Path
from typing import Optional

ENGINE = Path(__file__).resolve().parent.parent


def _from_git(root: Path) -> Optional[str]:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--match", "v[0-9]*"],
            capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = result.stdout.strip()
    return out if result.returncode == 0 and out else None


def _from_file(root: Path) -> Optional[str]:
    try:
        raw = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    return raw if raw.startswith("v") else f"v{raw}"


def engine_version(root: Path = ENGINE) -> Optional[str]:
    """Version lisible du moteur (`v1.1.0`, `v1.1.0-12-gaab4d9c`) ou `None`."""
    return _from_git(root) or _from_file(root)


@functools.lru_cache(maxsize=1)
def cached_engine_version() -> Optional[str]:
    """Une seule lecture par processus : le serveur ne relance pas git à chaque requête."""
    return engine_version()


if __name__ == "__main__":
    print(engine_version() or "inconnue")
    sys.exit(0)
