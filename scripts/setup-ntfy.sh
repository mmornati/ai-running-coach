#!/usr/bin/env bash
# =============================================================================
# ai-running-coach — configuration des notifications push (ntfy)
#
# Compatibilité : ce script appelle scripts/arc_notify.py setup (mêmes options :
# --url, --topic, --token-file, --disable, --no-test).
# Utilisez directement : scripts/arc_notify.py setup
# =============================================================================
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/arc_notify.py" setup "$@"
