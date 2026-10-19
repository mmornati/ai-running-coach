"""Palier B — toute option `--workspace` passe par le verrou de la sync (#127).

`daily-sync.sh` pose `ARC_LOCK_WORKSPACE=1` ; seuls `coach_setup.workspace_root(explicit)` et
`coach_config.enforce_workspace_lock` le font respecter. Un script qui construit lui-même
`Path(args.workspace)` contournerait le verrou : le runner pourrait lire ou écrire le dossier d'un autre
membre du foyer. Les options qui désignent un fichier ou un dossier (`--db`, `--dir`, `--output-dir`) restent
hors périmètre, documenté dans docs/workspace.md.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RESOLVERS = {"scripts/coach_setup.py", "scripts/coach_config.py"}
DIRECT = re.compile(r"\bPath\(\s*\w+\.workspace\b|\bos\.path\.\w+\(\s*\w+\.workspace\b")


class TestWorkspaceOptionGoesThroughTheLock(unittest.TestCase):
    def _sources(self):
        yield from sorted((REPO / "scripts").glob("*.py"))
        yield from sorted((REPO / "skills").glob("*/scripts/*.py"))

    def test_no_direct_path_construction_from_the_workspace_option(self):
        offenders = []
        for path in self._sources():
            rel = path.relative_to(REPO).as_posix()
            if rel in RESOLVERS:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if DIRECT.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "passez par coach_setup.workspace_root(explicit) ou "
                                        "coach_config.enforce_workspace_lock")


if __name__ == "__main__":
    unittest.main()
