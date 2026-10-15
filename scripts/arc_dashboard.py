#!/usr/bin/env python3
"""ai-running-coach — tableau de bord local (lecture seule)

Indexe le workspace dans une base SQLite dérivée (<workspace>/.arc/coach.db,
jetable, reconstruite depuis les fichiers Markdown) puis sert le tableau de
bord sur http://127.0.0.1:<port>/. Rien n'écoute hors de la machine, rien
n'est écrit hors de .arc/.

Usage :
  scripts/arc_dashboard.py              # port de [dashboard].port (défaut 8765), ouvre le navigateur
  scripts/arc_dashboard.py --port 9000  # autre port
  scripts/arc_dashboard.py --no-open    # sans ouvrir le navigateur
  scripts/arc_dashboard.py --memory     # base en mémoire : aucun fichier .arc/ écrit
  scripts/arc_dashboard.py --rebuild    # repart d'un index vide

scripts/dashboard.sh accepte les mêmes options (il appelle ce script).

Configuration : section [dashboard] de config/workspace.toml. Workspace :
ARC_WORKSPACE, sinon ~/.config/ai-running-coach/workspace, sinon ce dépôt.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arc_runtime import ENGINE, err, log, ok, resolve_workspace, section  # noqa: E402

DEFAULT_PORT = "8765"


def parse_args(argv: List[str]) -> Optional[dict]:
    """Options lues comme le faisait dashboard.sh. None : erreur déjà affichée."""
    opts = {"port": "", "open": True, "memory": False, "rebuild": False}
    values = list(argv)
    while values:
        arg = values.pop(0)
        if arg == "--port":
            if not values:
                err("--port attend un numéro")
                return None
            opts["port"] = values.pop(0)
        elif arg == "--no-open":
            opts["open"] = False
        elif arg == "--memory":
            opts["memory"] = True
        elif arg == "--rebuild":
            opts["rebuild"] = True
        elif arg in ("--help", "-h"):
            print(__doc__.strip())
            raise SystemExit(0)
        else:
            err(f"Option inconnue : {arg} (voir --help)")
            return None
    return opts


def open_browser(url: str) -> None:
    """Navigateur par défaut du système (macOS, Linux, Windows) ; un échec n'arrête rien."""
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 — pas de navigateur : l'URL reste affichée
        pass


def main(argv: Optional[List[str]] = None) -> int:
    opts = parse_args(sys.argv[1:] if argv is None else list(argv))
    if opts is None:
        return 1
    workspace = resolve_workspace()
    port = opts["port"] or str(section(workspace, "dashboard").get("port", DEFAULT_PORT))
    if not re.fullmatch(r"[0-9]+", port):
        err(f"[dashboard].port : entier attendu, « {port} » trouvé.")
        return 1

    if opts["rebuild"]:
        result = subprocess.run([sys.executable, str(ENGINE / "scripts/arc_index.py"),
                                 "--workspace", str(workspace), "--rebuild"], stdout=subprocess.DEVNULL)
        if result.returncode != 0:
            err("Réindexation impossible — voir le message ci-dessus.")
            return 1

    log(f"Tableau de bord — workspace : {workspace}")

    # Le serveur imprime « URL: http://127.0.0.1:<port>/ » dès qu'il écoute (port éventuellement
    # décalé si le premier est pris) : on relaie la ligne, on ouvre.
    cmd = [sys.executable, str(ENGINE / "scripts/arc_serve.py"), "--workspace", str(workspace), "--port", port]
    if opts["memory"]:
        cmd.append("--memory")
    server = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        assert server.stdout is not None
        for line in server.stdout:
            print(line, end="", flush=True)
            if line.startswith("URL:"):
                url = line[len("URL:"):].strip()
                ok(f"Ouvert sur {url} — Ctrl+C pour arrêter")
                if opts["open"]:
                    open_browser(url)
        return server.wait()
    except KeyboardInterrupt:
        # Le serveur reçoit le même Ctrl+C (même groupe de processus) : on attend qu'il se termine.
        try:
            server.wait(timeout=10)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            server.kill()
        return 130


if __name__ == "__main__":
    sys.exit(main())
