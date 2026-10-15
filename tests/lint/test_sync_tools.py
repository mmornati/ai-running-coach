"""Palier B — `scripts/arc_sync_tools.py`, source unique des outils refusés en headless.

`daily-sync.sh` relit la sortie `shell` avec `eval` et `install.sh` appelle `write` /
`health-denied` : les deux doivent voir exactement les listes du module.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts/arc_sync_tools.py"
sys.path.insert(0, str(REPO / "scripts"))

import arc_sync_tools  # noqa: E402


def _shell_vars(*args: str) -> dict:
    """Variables obtenues par bash après `eval` de la sortie `shell`, comme dans daily-sync.sh."""
    names = ("SYNC_GARMIN_WRITE_PREFIXES", "SYNC_WRITE_TOOLS", "SYNC_READ_TOOLS", "SYNC_HEALTH_DENIED_TOOLS",
             "SYNC_DENY_TOOLS", "SYNC_GARMIN_WRITE_TOOLS", "SYNC_INTERVALS_WRITE_TOOLS", "SYNC_STRAVA_WRITE_TOOLS")
    script = 'set -euo pipefail; eval "$(python3 "$0" shell "$@")"; ' + "; ".join(
        f'printf "%s\\t%s\\n" {n} "${n}"' for n in names)
    out = subprocess.run(["bash", "-c", script, str(SCRIPT), *args],
                         capture_output=True, text=True, check=True).stdout
    return {name: value.split() for name, _, value in (line.partition("\t") for line in out.splitlines())}


class SyncToolsShellTest(unittest.TestCase):
    def test_shell_output_matches_the_module_for_every_source(self):
        for source in ("garmin", "intervals", "strava"):
            for deny in (False, True):
                with self.subTest(source=source, deny_health=deny):
                    got = _shell_vars(source, *(["--deny-health"] if deny else []))
                    self.assertEqual(got["SYNC_WRITE_TOOLS"], arc_sync_tools.write_tools(source))
                    self.assertEqual(got["SYNC_DENY_TOOLS"], arc_sync_tools.deny_tools(source, deny))
                    self.assertEqual(got["SYNC_HEALTH_DENIED_TOOLS"],
                                     arc_sync_tools.health_denied_tools(source, deny))
                    self.assertEqual(got["SYNC_GARMIN_WRITE_PREFIXES"],
                                     list(arc_sync_tools.GARMIN_WRITE_PREFIXES))
                    for kind in ("garmin", "intervals", "strava"):
                        self.assertEqual(got[f"SYNC_{kind.upper()}_WRITE_TOOLS"],
                                         arc_sync_tools.write_tools(kind))

    def test_health_is_denied_only_for_garmin_with_open_wearables(self):
        self.assertEqual(arc_sync_tools.health_denied_tools("garmin", False), [])
        self.assertEqual(arc_sync_tools.health_denied_tools("intervals", True), [])
        self.assertIn("get_hrv_data", arc_sync_tools.health_denied_tools("garmin", True))

    def test_unknown_source_has_no_tools(self):
        self.assertEqual(_shell_vars("inconnue")["SYNC_WRITE_TOOLS"], [])

    def test_garmin_read_tools_drop_writes_and_denied_health(self):
        whitelist = "get_activities,schedule_workouts,remove_gear_from_activity,get_hrv_data"
        self.assertEqual(arc_sync_tools.read_tools("garmin", whitelist), ["get_activities", "get_hrv_data"])
        self.assertEqual(arc_sync_tools.read_tools("garmin", whitelist, deny_health=True), ["get_activities"])

    def test_every_named_garmin_write_carries_a_write_prefix(self):
        """Les refus par préfixe (Gemini, OpenCode) couvrent au moins les refus nommés."""
        for tool in arc_sync_tools.GARMIN_WRITE_TOOLS:
            self.assertTrue(tool.startswith(arc_sync_tools.GARMIN_WRITE_PREFIXES), tool)


if __name__ == "__main__":
    unittest.main()
