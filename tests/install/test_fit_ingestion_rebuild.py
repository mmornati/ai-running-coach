"""Palier A — `--rebuild` de bout en bout sur un workspace synthétique construit avec
`--with-samples` (#42) : les échantillons FIT survivent à une reconstruction complète
de l'index, exactement comme le reste des tables dérivées.
"""

from __future__ import annotations

import datetime
import json
import unittest

from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-09-23"


class TestFitIngestionRebuild(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=30, sport="trail", seed=5,
                         today=datetime.date.fromisoformat(TODAY), with_samples=True)
        self.db = self.sb.root / "coach.db"

    def tearDown(self):
        self.sb.__exit__(None, None, None)

    def _run_index(self, *extra_args):
        return self.sb.run(
            ["python3", str(self.sb.repo / "scripts/arc_index.py"), *extra_args,
             "--workspace", str(self.ws), "--db", str(self.db), "--today", TODAY],
        )

    def _status(self):
        result = self._run_index("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fit_samples_exist_after_initial_index(self):
        fit_files = list((self.ws / "activities/fit").glob("*.json"))
        self.assertGreater(len(fit_files), 0, "le workspace synthétique --with-samples doit produire des FIT")
        result = self._run_index("index")
        self.assertEqual(result.returncode, 0, result.stderr)
        status = self._status()
        self.assertEqual(status["samples"]["activities_with_samples"], len(fit_files))
        self.assertGreater(status["samples"]["rows"], 0)
        self.assertEqual(status["samples"]["unlinked_garmin_ids"], 0)

    def test_rebuild_preserves_sample_coverage(self):
        self._run_index("index")
        before = self._status()["samples"]
        result = self._run_index("--rebuild", "index")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self._status()["samples"]
        self.assertEqual(before, after)

    def test_rebuild_is_idempotent_on_row_count(self):
        self._run_index("--rebuild", "index")
        rows_1 = self._status()["samples"]["rows"]
        self._run_index("--rebuild", "index")
        rows_2 = self._status()["samples"]["rows"]
        self.assertEqual(rows_1, rows_2)

    def test_samples_cli_returns_data_for_a_real_synthetic_activity(self):
        self._run_index("index")
        fit_id = next((self.ws / "activities/fit").glob("*.json")).stem
        result = self._run_index("samples", fit_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["garmin_activity_id"], int(fit_id))
        self.assertGreater(len(payload["samples"]), 0)
