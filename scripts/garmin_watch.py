#!/usr/bin/env python3
"""Ancien nom de `scripts/watch.py` (surveillance Garmin ou COROS sans LLM).

Gardé pour les crontabs et LaunchAgents posés avant le renommage : il lance `watch.py` avec les
mêmes arguments. `./install.sh` (et donc `/update-coach`) réécrit ces tâches avec le nouveau nom.
Importé comme module, il expose celui de `watch.py`.
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    sys.argv[0] = os.path.join(HERE, "watch.py")
    runpy.run_path(sys.argv[0], run_name="__main__")
else:
    sys.path.insert(0, HERE)
    from watch import *  # noqa: E402,F401,F403
