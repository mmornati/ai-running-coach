#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — tableau de bord local (lecture seule)
#
# Compatibilité : ce script appelle scripts/arc_dashboard.py, mêmes options
# (--port, --no-open, --memory, --rebuild). Il reste en place : l'app macOS,
# les unités systemd et la documentation le lancent sous ce nom.
# =============================================================================
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/arc_dashboard.py" "$@"
