"""Sommeil COROS — `querySleepOverview` (texte) -> clés `sleep_*` du bloc `arc`.

Réponse réelle relevée le 2026-10-24 (deuxième nuit avec la montre) : nuit
continue que COROS a coupée en sommeil principal + « sieste » (1 h 52 d'écart).
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_coros_sleep as S  # noqa: E402

REAL = json.dumps(
    "Sleep Overview\n========================\nNote: each record below is dated by its wake-up day.\n\n"
    "2026-10-23\nSleep Score: 0\nSleep detail for this day is not available yet.\n\n"
    "2026-10-24\nSleep Score: 72\nDaily Sleep: 5h 29min (incl. naps)\nMain Sleep (asleep): 4h 47min\n"
    "Main Sleep Period (incl. awake): 4h 53min\nSleep metrics scope: daily\nDeep Sleep Ratio: 24%\n"
    "Light Sleep Ratio: 49%\nREM Ratio: 25%\nAwake Ratio: 2%\nAwake Time: 6 min\nAwake Count (>5 min): 0\n"
    "Main Sleep Window: 2026-10-24 04:45 - 2026-10-24 09:38\nNaps Total (asleep): 42 min\n"
    "Naps Period (incl. awake): 45 min\nNap Window: 2026-10-24 11:30 - 2026-10-24 12:15")


class TestParseSleep(unittest.TestCase):
    def test_main_sleep_only_naps_never_added(self):
        r = S.parse_sleep(REAL, "2026-10-24", "Europe/Paris")
        self.assertTrue(r["available"])
        self.assertEqual(r["arc"]["sleep_total_s"], 4 * 3600 + 47 * 60)
        self.assertEqual(r["daily_asleep_s"], 5 * 3600 + 29 * 60)
        self.assertEqual(r["naps_asleep_s"], 42 * 60)
        self.assertEqual(r["arc"]["sleep_start"], "2026-10-24T04:45:00+02:00")
        self.assertEqual(r["arc"]["sleep_end"], "2026-10-24T09:38:00+02:00")
        self.assertEqual(r["arc"]["provider_scores"][0]["value"], 72)
        self.assertNotIn("sleep_score", r["arc"])

    def test_stage_ratios_kept_never_converted(self):
        r = S.parse_sleep(REAL, "2026-10-24", "Europe/Paris")
        self.assertEqual(r["stage_ratios"], {"deep": 0.24, "light": 0.49, "rem": 0.25, "awake": 0.02})
        self.assertEqual(r["stage_scope"], "daily")
        for key in ("sleep_deep_s", "sleep_light_s", "sleep_rem_s"):
            self.assertNotIn(key, r["arc"])

    def test_split_suspected_when_nap_follows_main_sleep(self):
        r = S.parse_sleep(REAL, "2026-10-24", "Europe/Paris")
        self.assertTrue(r["split_suspected"])
        self.assertEqual(r["split"]["gap_after_main_s"], 3600 + 52 * 60)

    def test_afternoon_nap_is_not_a_split(self):
        late = REAL.replace("11:30 - 2026-10-24 12:15", "15:30 - 2026-10-24 16:15")
        r = S.parse_sleep(late, "2026-10-24", "Europe/Paris")
        self.assertFalse(r["split_suspected"])
        self.assertIsNone(r["split"])

    def test_night_not_computed_yet(self):
        r = S.parse_sleep(REAL, "2026-10-23", "Europe/Paris")
        self.assertFalse(r["available"])
        self.assertEqual(r["arc"], {})

    def test_missing_day(self):
        self.assertIsNone(S.parse_sleep(REAL, "2026-10-25"))

    def test_cli(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(REAL)), redirect_stdout(out):
            code = S.main(["--date", "2026-10-24", "--tz", "Europe/Paris"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["split_suspected"])
        with mock.patch("sys.stdin", io.StringIO(REAL)), redirect_stdout(io.StringIO()):
            self.assertEqual(S.main(["--date", "2026-10-25"]), 1)


if __name__ == "__main__":
    unittest.main()
