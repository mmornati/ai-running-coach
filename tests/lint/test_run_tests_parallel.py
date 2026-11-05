"""Palier B — `tests/run_tests.py --jobs` : aucune classe perdue, aucun échec masqué.

Verrouille ce qu'un exécuteur parallèle peut casser en silence : un test oublié, un module
qui ne s'importe pas, un processus de travail qui meurt (la suite doit échouer, pas rester
bloquée), et la capture de la sortie, y compris celle des sous-processus d'un test.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
import run_tests  # noqa: E402


class RunParallel(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="arc-parallel-"))
        self.addCleanup(shutil.rmtree, self.root)
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))
        self.marks = self.root / "marks"
        self.marks.mkdir()
        self.package = "arcparallel" + self.root.name.replace("-", "_").replace("arc_parallel_", "")
        (self.root / self.package).mkdir()
        (self.root / self.package / "__init__.py").touch()

    def write(self, name: str, body: str) -> None:
        header = f"import os, subprocess, sys, unittest\nfrom pathlib import Path\nMARKS = Path({str(self.marks)!r})\n"
        (self.root / self.package / f"{name}.py").write_text(header + textwrap.dedent(body), encoding="utf-8")

    def run_suite(self, jobs: int = 2) -> tuple:
        suite = unittest.defaultTestLoader.discover(str(self.root / self.package), pattern="test_*.py",
                                                    top_level_dir=str(self.root))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            success = run_tests.run_parallel(suite, jobs)
        return success, out.getvalue()

    def test_every_case_runs_exactly_once(self):
        self.write("test_a", """
            class A(unittest.TestCase):
                def test_1(self): (MARKS / "a1").open("a").write("x")
                def test_2(self): (MARKS / "a2").open("a").write("x")
            class B(unittest.TestCase):
                def test_1(self): (MARKS / "b1").open("a").write("x")
        """)
        self.write("test_b", """
            class C(unittest.TestCase):
                def test_1(self): (MARKS / "c1").open("a").write("x")
        """)
        success, out = self.run_suite()
        self.assertTrue(success, out)
        self.assertIn("Ran 4 tests", out)
        self.assertEqual(sorted(p.name for p in self.marks.iterdir()), ["a1", "a2", "b1", "c1"])
        self.assertTrue(all(p.read_text() == "x" for p in self.marks.iterdir()))

    def test_class_setup_is_shared_within_one_process(self):
        self.write("test_a", """
            class A(unittest.TestCase):
                @classmethod
                def setUpClass(cls): (MARKS / f"setup-{os.getpid()}").open("a").write("x")
                def test_1(self): pass
                def test_2(self): pass
                def test_3(self): pass
        """)
        success, out = self.run_suite(jobs=3)
        self.assertTrue(success, out)
        self.assertEqual(len(list(self.marks.iterdir())), 1)

    def test_failure_is_reported_with_its_output(self):
        self.write("test_a", """
            class Good(unittest.TestCase):
                def test_ok(self): print("BRUIT-DU-SUCCES")
            class Bad(unittest.TestCase):
                def test_ko(self):
                    subprocess.run([sys.executable, "-c", "print('SORTIE-DU-SOUS-PROCESSUS')"])
                    self.fail("RAISON-DE-L-ECHEC")
        """)
        success, out = self.run_suite()
        self.assertFalse(success)
        self.assertIn("FAILED (failures=1)", out)
        self.assertIn("RAISON-DE-L-ECHEC", out)
        self.assertIn("SORTIE-DU-SOUS-PROCESSUS", out)
        self.assertNotIn("BRUIT-DU-SUCCES", out)

    def test_module_that_cannot_be_imported_fails_the_run(self):
        self.write("test_a", """
            class Good(unittest.TestCase):
                def test_ok(self): pass
        """)
        self.write("test_b", "raise RuntimeError('IMPORT-CASSE')\n")
        success, out = self.run_suite()
        self.assertFalse(success)
        self.assertIn("IMPORT-CASSE", out)

    def test_class_setup_failure_fails_the_run(self):
        self.write("test_a", """
            class A(unittest.TestCase):
                @classmethod
                def setUpClass(cls): raise RuntimeError("SETUP-CASSE")
                def test_1(self): pass
        """)
        success, out = self.run_suite()
        self.assertFalse(success)
        self.assertIn("SETUP-CASSE", out)

    def test_dead_worker_fails_the_run_instead_of_hanging(self):
        self.write("test_a", """
            class A(unittest.TestCase):
                def test_crash(self): os._exit(3)
        """)
        success, out = self.run_suite()
        self.assertFalse(success)
        self.assertIn("BrokenProcessPool", out)

    def test_skips_are_not_failures(self):
        self.write("test_a", """
            class A(unittest.TestCase):
                @unittest.skip("plus tard")
                def test_1(self): self.fail("jamais lancé")
                def test_2(self): pass
        """)
        success, out = self.run_suite()
        self.assertTrue(success, out)
        self.assertIn("OK (skipped=1)", out)


class ParseJobs(unittest.TestCase):
    def test_values(self):
        self.assertEqual(run_tests.parse_jobs("3"), 3)
        self.assertGreaterEqual(run_tests.parse_jobs("auto"), 1)
        for bad in ("0", "-1", "beaucoup"):
            with self.assertRaises(argparse.ArgumentTypeError):
                run_tests.parse_jobs(bad)


class Workflow(unittest.TestCase):
    def test_ci_runs_every_matrix_tier_in_parallel(self):
        workflow = (REPO / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"run_tests\.py --tier [^\n]*--jobs auto")


if __name__ == "__main__":
    unittest.main()
