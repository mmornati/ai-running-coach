#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — envoi d'une notification push (ntfy)
#
# Compatibilité : ce script appelle scripts/arc_notify.py send (même usage, mêmes
# codes de sortie : 0 envoyé ou provider = "none", 1 configuration, 2 réseau).
# Utilisez directement : scripts/arc_notify.py send [--title …] [--priority 1-5] [--tags …] "message"
# =============================================================================
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/arc_notify.py" send "$@"
