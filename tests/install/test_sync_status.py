"""Palier A — état de la synchronisation (`arc_sync_status.py`, vue « Synchro »).

Aucun cron : les journaux sont écrits à la main dans un workspace jetable.
(`scripts/update-docker.sh` est testé avec /update-coach, dans test_update_coach.py.)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_sync_status as SS  # noqa: E402

NOW = datetime(2026, 10, 13, 9, 0, 0)

RUN_OK = """===== 2026-10-13 07:30:05 — runner=claude lookback=2 trigger=morning =====
Bilan fait.

```resume
Séances : à jour
HRV : 73 ms
```
===== 2026-10-13 07:34:10 — fin code=0 durée=245s =====
index : 1 lu(s)
"""
RUN_FAILED = """===== 2026-10-13 08:10:00 — runner=claude lookback=2 trigger=activity:42 =====
PROVIDER-ERREUR (OpenRouter) : 402 crédits épuisés
===== 2026-10-13 08:10:09 — fin code=1 durée=9s =====
"""


class SyncStatus(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws)
        (self.ws / "logs").mkdir()
        (self.ws / "config").mkdir()

    def config(self, body: str):
        (self.ws / "config/workspace.user.toml").write_text(body, encoding="utf-8")

    def log(self, day: str, text: str):
        with (self.ws / f"logs/sync-{day}.log").open("a", encoding="utf-8") as fh:
            fh.write(text)

    def state(self, **values):
        (self.ws / "logs/.watch-state.json").write_text(json.dumps(values), encoding="utf-8")

    def test_parses_runs_footer_and_resume(self):
        self.config('[sync]\nmode = "schedule"\ntimes = ["07:15"]\n')
        self.log("2026-10-13", RUN_OK)
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["verdict"], "ok", st["reason"])
        run = st["runs"][0]
        self.assertEqual((run["start"], run["end"], run["rc"], run["duration_s"]),
                         ("2026-10-13T07:30:05", "2026-10-13T07:34:10", 0, 245))
        self.assertEqual(run["resume"], ["Séances : à jour", "HRV : 73 ms"])
        self.assertIn("index : 1 lu(s)", run["log"])
        self.assertEqual(st["next"]["at"], "2026-10-14T07:15:00")

    def test_failed_last_run(self):
        self.config('[sync]\nmode = "schedule"\ntimes = ["07:15"]\n')
        self.log("2026-10-13", RUN_OK + RUN_FAILED)
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["verdict"], "failing")
        self.assertEqual(st["runs"][0]["errors"], ["PROVIDER-ERREUR (OpenRouter) : 402 crédits épuisés"])

    def test_schedule_missed_slot_is_late(self):
        self.config('[sync]\nmode = "schedule"\ntimes = ["07:15"]\n')
        self.log("2026-10-12", RUN_OK.replace("2026-10-13", "2026-10-12"))
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["verdict"], "late")
        self.assertIn("07:15", st["reason"])

    def test_watch_stale_probe_is_late(self):
        self.config('[sync]\nmode = "watch"\nwatch_interval_min = 15\n')
        self.state(last_check="2026-10-13T06:00:00", last_run="2026-10-13T07:30:01", last_run_rc=0)
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["verdict"], "late")
        self.assertIn("3 h", st["reason"])

    def test_watch_fresh_and_auth_error(self):
        self.config('[sync]\nmode = "watch"\nwatch_interval_min = 15\n')
        self.state(last_check="2026-10-13T08:50:00", runs={"date": "2026-10-13", "count": 2})
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["watch"]["runs_today"], 2)
        self.assertEqual(st["next"]["at"], "2026-10-13T09:05:00")
        self.state(last_check="2026-10-13T08:50:00", auth_error_date="2026-10-13")
        self.assertEqual(SS.status(self.ws, NOW)["verdict"], "failing")

    def test_old_log_without_footer_takes_watch_rc(self):
        self.config('[sync]\nmode = "watch"\n')
        self.log("2026-10-13", "===== 2026-10-13 07:30:05 — runner=claude lookback=2 trigger=morning =====\nok\n")
        self.state(last_check="2026-10-13T08:55:00", last_run="2026-10-13T07:30:01", last_run_rc=3)
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["runs"][0]["rc"], 3)
        self.assertEqual(st["verdict"], "failing")

    def test_never_ran(self):
        self.config('[sync]\nmode = "watch"\n')
        self.assertEqual(SS.status(self.ws, NOW)["verdict"], "never")

    def test_watch_falls_back_to_schedule_off_garmin(self):
        self.config('[data]\nsource = "intervals"\n[sync]\nmode = "watch"\n')
        self.assertEqual(SS.status(self.ws, NOW)["settings"]["mode"], "schedule")

    def test_coros_source_keeps_watch_and_names_coros(self):
        """#168 : la surveillance existe aussi pour COROS — pas de repli, libellés COROS."""
        self.config('[data]\nsource = "coros"\n[sync]\nmode = "watch"\n')
        st = SS.status(self.ws, NOW)
        self.assertEqual(st["settings"]["mode"], "watch")
        self.assertIn("COROS", st["reason"])

    def test_cli_json(self):
        self.config('[sync]\nmode = "schedule"\n')
        out = subprocess.run([sys.executable, str(REPO / "scripts/arc_sync_status.py"), "--workspace", str(self.ws), "--json"],
                             capture_output=True, text=True, check=True).stdout
        self.assertIn(json.loads(out)["verdict"], ("never", "late", "ok"))


if __name__ == "__main__":
    unittest.main()
