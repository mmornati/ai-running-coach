"""Palier D — version du moteur (`scripts/arc_version.py`, `/api/version`).

`git describe` d'abord, fichier VERSION sinon, rien du tout plutôt qu'un numéro inventé.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_version as V  # noqa: E402

GIT = shutil.which("git")


class EngineVersion(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                       check=True, capture_output=True)

    def test_version_file_without_git(self):
        (self.root / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.assertEqual(V.engine_version(self.root), "v1.1.0")

    def test_nothing_known(self):
        self.assertIsNone(V.engine_version(self.root))
        (self.root / "VERSION").write_text("\n", encoding="utf-8")
        self.assertIsNone(V.engine_version(self.root))

    @unittest.skipUnless(GIT, "git absent")
    def test_git_describe_wins_over_file(self):
        (self.root / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("add", "VERSION")
        self.git("commit", "-q", "-m", "release")
        self.git("tag", "-a", "v1.1.0", "-m", "v1.1.0")
        self.assertEqual(V.engine_version(self.root), "v1.1.0")
        (self.root / "x").write_text("x", encoding="utf-8")
        self.git("add", "x")
        self.git("commit", "-q", "-m", "suite")
        self.assertRegex(V.engine_version(self.root), r"^v1\.1\.0-1-g[0-9a-f]+$")

    @unittest.skipUnless(GIT, "git absent")
    def test_git_without_tag_falls_back_to_file(self):
        (self.root / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("add", "VERSION")
        self.git("commit", "-q", "-m", "init")
        self.assertEqual(V.engine_version(self.root), "v1.1.0")


if __name__ == "__main__":
    unittest.main()
