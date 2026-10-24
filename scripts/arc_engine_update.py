#!/usr/bin/env python3
"""Mise à jour transactionnelle du moteur macOS et verrou partagé avec la sync."""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BUSY = 75


# Copie volontaire de `coach_config.enforce_workspace_lock` (#127) : ce script est embarqué SEUL dans les
# Resources de l'application macOS (build-macos-dmg.sh), sans `coach_config.py` à côté — aucun import
# frère possible. Même sémantique ; la parité est verrouillée par tests/install/test_engine_update.py.
def enforce_workspace_lock(workspace) -> Path:
    chosen = Path(workspace).expanduser().resolve()
    if os.environ.get("ARC_LOCK_WORKSPACE") != "1":
        return chosen
    locked = os.environ.get("ARC_WORKSPACE", "").strip()
    if not locked:
        raise SystemExit(
            "ERREUR : ARC_LOCK_WORKSPACE=1 sans ARC_WORKSPACE — exécution refusée (verrou sans workspace)."
        )
    locked_path = Path(locked).expanduser().resolve()
    try:  # samefile : APFS insensible à la casse / normalisation Unicode (chemins NFD de l'app Mac)
        same = os.path.samefile(chosen, locked_path)
    except OSError:
        same = chosen == locked_path
    if not same:
        raise SystemExit(
            f"ERREUR : workspace refusé ({chosen}) — cette exécution est verrouillée sur "
            f"{locked_path} (ARC_LOCK_WORKSPACE=1). Retirez --workspace ou utilisez celui de la synchronisation."
        )
    return chosen


def acquire_lock(workspace: Path, *, exclusive: bool) -> int:
    logs = workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    fd = os.open(logs / ".engine.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd


def legacy_sync_running(workspace: Path) -> bool:
    """Les versions antérieures ne prennent que le verrou PID .sync.lock."""
    try:
        pid = int((workspace / "logs/.sync.lock").read_text().strip())
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ValueError, FileNotFoundError, ProcessLookupError):
        return False


def update_engine(archive: Path, engine: Path, workspace: Path, args: list[str]) -> int:
    if workspace == engine or engine in workspace.parents:
        raise ValueError("Le dossier personnel doit être séparé du moteur.")
    try:
        fd = acquire_lock(workspace, exclusive=True)
    except BlockingIOError:
        return BUSY
    try:
        if legacy_sync_running(workspace):
            return BUSY
        # Le moteur de secours survit à un échec de l'installation. Les données
        # personnelles restent dans le workspace, en dehors de ces répertoires.
        engine.parent.mkdir(parents=True, exist_ok=True)
        backup = engine.with_name(engine.name + ".previous")
        # Une interruption brutale ne doit pas perdre le dernier moteur connu.
        if backup.exists():
            if engine.exists():
                shutil.rmtree(engine)
            backup.rename(engine)
        with tempfile.TemporaryDirectory(prefix="engine-update-", dir=engine.parent) as temporary:
            root = Path(temporary)
            stage = root / "stage"
            stage.mkdir()
            subprocess.run(["/usr/bin/tar", "-xzf", str(archive), "-C", str(stage)], check=True)
            if not (stage / "install.sh").is_file():
                raise RuntimeError("Le moteur embarqué ne contient pas install.sh.")
            had_engine = engine.exists()
            if had_engine:
                engine.rename(backup)
            try:
                stage.rename(engine)
                result = subprocess.run(["/bin/bash", str(engine / "install.sh"), *args], cwd=engine)
                if result.returncode != 0:
                    raise RuntimeError(f"Configuration interrompue (code {result.returncode}).")
            except BaseException:
                if engine.exists():
                    shutil.rmtree(engine)
                if had_engine:
                    backup.rename(engine)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        return 0
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    enforce_workspace_lock(options.workspace)
    args = options.args[1:] if options.args[:1] == ["--"] else options.args
    if options.sync:
        if not args:
            parser.error("commande de synchronisation manquante")
        try:
            fd = acquire_lock(options.workspace, exclusive=False)
        except BlockingIOError:
            print("Mise à jour du moteur en cours — synchronisation reportée.")
            return 0
        # exec conserve le PID ; le noyau libère le verrou même après un crash.
        os.set_inheritable(fd, True)
        os.environ["ARC_ENGINE_LOCKED"] = "1"
        os.execvp(args[0], args)
    if not options.archive or not options.engine:
        parser.error("--archive et --engine sont requis")
    try:
        return update_engine(options.archive.resolve(), options.engine.resolve(), options.workspace.resolve(), args)
    except Exception as error:
        print(f"Mise à jour impossible : {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
