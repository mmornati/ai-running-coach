#!/usr/bin/env python3
"""Palier D — `runner.record_result` / `runner.results_output_path` (#29, revue PR #74).

Aucun sous-processus, aucun modèle : ces deux fonctions ne font que lire/écrire
un fichier JSON local selon une variable d'environnement — testable en pur
`unittest` avec `tempfile` et `unittest.mock.patch.dict`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.evals import runner  # noqa: E402


class TestResultsOutputPath(unittest.TestCase):
    def test_none_when_env_var_unset(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop(runner.RESULTS_ENV, None)
            self.assertIsNone(runner.results_output_path())

    def test_path_when_env_var_set(self):
        with mock.patch.dict("os.environ", {runner.RESULTS_ENV: "/tmp/whatever.json"}):
            self.assertEqual(runner.results_output_path(), Path("/tmp/whatever.json"))


class TestRecordResult(unittest.TestCase):
    def test_no_op_without_env_var(self):
        """Toute exécution locale qui ne règle pas `ARC_EVAL_RESULTS_OUT` ne doit
        laisser AUCUNE trace sur le disque — c'est ce qui garantit que ce mécanisme
        n'a rien changé au comportement historique du palier C en local."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop(runner.RESULTS_ENV, None)
                runner.record_result("some-case", passed=2, attempts=3)
            self.assertFalse(target.exists())

    def test_writes_passed_attempts_and_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target)}):
                runner.record_result("case-a", passed=2, attempts=3)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["case-a"], {"passed": 2, "attempts": 3, "rate": 2 / 3})

    def test_attempts_zero_gives_rate_zero_not_a_division_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target)}):
                runner.record_result("empty-case", passed=0, attempts=0)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["empty-case"]["rate"], 0.0)

    def test_meta_present_after_a_single_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {
                runner.RESULTS_ENV: str(target), "ARC_EVAL_MODEL": "claude-haiku-4-5-20251001",
                "ARC_EVAL_REPEAT": "3",
            }):
                runner.record_result("case-a", passed=3, attempts=3)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("_meta", data)
            self.assertEqual(data["_meta"]["model"], "claude-haiku-4-5-20251001")
            self.assertEqual(data["_meta"]["repeat"], 3)
            self.assertIn("date", data["_meta"])
            self.assertIsNone(data["_meta"]["case_filter"], "pas de filtre réglé : doit être None, pas absent")

    def test_meta_captures_the_case_filter_when_set(self):
        """Même variable que celle lue par le workflow `Évals` pour le `-k` (#74,
        second passage, point 4) — `render_results.py` s'en sert pour distinguer un
        cas exclu volontairement d'un cas interrompu en route."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target), "ARC_EVAL_CASE_FILTER": "sport-trail"}):
                runner.record_result("sport-trail-elevation", passed=3, attempts=3)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["_meta"]["case_filter"], "sport-trail")

    def test_meta_case_filter_is_none_when_env_var_is_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target), "ARC_EVAL_CASE_FILTER": ""}):
                runner.record_result("case-a", passed=1, attempts=1)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIsNone(data["_meta"]["case_filter"])

    def test_two_calls_merge_instead_of_overwriting(self):
        """Un deuxième cas ne doit jamais effacer le premier — lecture-fusion-écriture,
        vérifié ici avec deux appels réels (pas seulement affirmé en commentaire)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target)}):
                runner.record_result("case-a", passed=3, attempts=3)
                runner.record_result("case-b", passed=1, attempts=3)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["case-a"], {"passed": 3, "attempts": 3, "rate": 1.0})
            self.assertEqual(data["case-b"], {"passed": 1, "attempts": 3, "rate": 1 / 3})

    def test_second_call_updates_meta_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target)}):
                runner.record_result("case-a", passed=3, attempts=3)
                first_date = json.loads(target.read_text(encoding="utf-8"))["_meta"]["date"]
                runner.record_result("case-b", passed=3, attempts=3)
                data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("case-a", data)
            self.assertIn("case-b", data)
            self.assertIn("_meta", data)
            self.assertIsInstance(first_date, str)

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "dir" / "results.json"
            with mock.patch.dict("os.environ", {runner.RESULTS_ENV: str(target)}):
                runner.record_result("case-a", passed=1, attempts=1)
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
