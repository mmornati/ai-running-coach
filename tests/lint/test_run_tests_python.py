"""Palier B — `tests/run_tests.py` se relance sous le Python de la CI.

Verrouille : CI_PYTHON reste celui de `.github/workflows/tests.yml` (sinon la relance locale
viserait une autre version que la CI), et le lien `python3` du PATH pointe sur l'interpréteur.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
import run_tests  # noqa: E402


class RunTestsPython(unittest.TestCase):
    def test_ci_python_matches_the_workflow(self):
        workflow = (REPO / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        versions = set(re.findall(r'python-version:\s*["\']?([0-9.]+)', workflow))
        self.assertEqual(versions, {".".join(map(str, run_tests.CI_PYTHON))})

    def test_suite_runs_under_the_ci_python(self):
        if os.environ.get("ARC_TESTS_ANY_PYTHON") == "1":
            self.skipTest("ARC_TESTS_ANY_PYTHON=1")
        self.assertGreaterEqual(sys.version_info[:2], run_tests.CI_PYTHON)

    def test_shim_links_python3_to_the_interpreter(self):
        shim = run_tests.python_shim_dir(sys.executable)
        for name in ("python3", "python"):
            self.assertEqual(os.readlink(shim / name), sys.executable)
        self.assertTrue(str(shim).startswith(tempfile.gettempdir()))


if __name__ == "__main__":
    unittest.main()
